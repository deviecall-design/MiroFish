"""Flask app exposing the contract mirofish-trader's client speaks.

  POST /api/simulation/start          {"seed_material": "..."} -> 202 {"simulation_id", "status", "cached"}
  GET  /api/simulation/<id>/status    -> {"status": pending|running|completed|failed, "progress", "stage", "error"?}
  GET  /api/simulation/<id>/result    -> {"bias", "conviction", "detail"} (409 until completed)

Every request, on every path (including unknown ones), must carry
Authorization: Bearer <MIROFISH_API_KEY>; otherwise 401. With no key configured
the adapter refuses everything (503). The upstream backend stays on 127.0.0.1
and is never exposed directly.
"""

import hmac
import logging
import queue
import threading
import time
from typing import Any, Callable, Dict, Optional

from flask import Flask, jsonify, request

from .config import Settings
from .store import JobStore, seed_key

log = logging.getLogger("mirofish.adapter")

MAX_SEED_CHARS = 20_000


def create_app(settings: Optional[Settings] = None, runner: Optional[Callable[[str, Callable], Dict[str, Any]]] = None,
               start_worker: bool = True) -> Flask:
    settings = settings or Settings()
    store = JobStore(settings.state_dir, settings.cache_ttl_s)
    jobs: "queue.Queue[tuple]" = queue.Queue()

    if runner is None:
        from . import pipeline

        def runner(seed: str, on_progress: Callable) -> Dict[str, Any]:
            chat = None
            if settings.distill == "llm" and settings.llm_api_key:
                chat = pipeline.openai_chat(settings.llm_api_key, settings.llm_base_url, settings.llm_model)
            return pipeline.run_pipeline(
                seed,
                pipeline.BackendClient(settings.backend_url),
                platform=settings.platform,
                max_rounds=settings.max_rounds,
                poll_s=settings.poll_s,
                timeout_s=settings.job_timeout_s,
                on_progress=on_progress,
                chat=chat,
                distill_mode=settings.distill,
            )

    def work_one(job_id: str, seed: str) -> None:
        store.update(job_id, status="running", stage="starting", started_at=time.time())

        def on_progress(stage: str, pct: int, extra: Dict[str, Any]) -> None:
            store.update(job_id, stage=stage, progress=max(0, min(99, int(pct))), **extra)

        try:
            result = runner(seed, on_progress)
            store.update(job_id, status="completed", progress=100, stage="done", result=result,
                         finished_at=time.time())
        except Exception as e:
            log.error("job %s failed: %s", job_id, e)
            store.update(job_id, status="failed", stage="failed", error=str(e)[:500], finished_at=time.time())

    def worker() -> None:
        # One simulation at a time: a cost and RAM guard on a 16 GB Mac.
        while True:
            job_id, seed = jobs.get()
            try:
                work_one(job_id, seed)
            finally:
                jobs.task_done()

    if start_worker:
        threading.Thread(target=worker, name="mirofish-adapter-worker", daemon=True).start()

    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024
    app.extensions["mirofish_adapter"] = {"store": store, "queue": jobs, "work_one": work_one}

    @app.before_request
    def require_bearer():
        if not settings.api_key:
            return jsonify({"error": "adapter not configured"}), 503
        header = request.headers.get("Authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token or not hmac.compare_digest(
            token.strip().encode("utf-8"), settings.api_key.encode("utf-8")
        ):
            return jsonify({"error": "unauthorized"}), 401, {"WWW-Authenticate": "Bearer"}
        return None

    @app.post("/api/simulation/start")
    def start():
        body = request.get_json(silent=True) or {}
        seed = body.get("seed_material")
        if not isinstance(seed, str) or not seed.strip():
            return jsonify({"error": "seed_material is required"}), 400
        if len(seed) > MAX_SEED_CHARS:
            return jsonify({"error": f"seed_material over {MAX_SEED_CHARS} characters"}), 413
        key = seed_key(seed)
        reusable = store.find_reusable(key)
        if reusable:
            return jsonify({"simulation_id": reusable["id"], "status": reusable["status"], "cached": True}), 200
        if settings.max_runs_per_day and store.runs_started_since(time.time() - 86400) >= settings.max_runs_per_day:
            return jsonify({"error": "daily simulation cap reached"}), 429
        job = store.create(key)
        jobs.put((job["id"], seed))
        return jsonify({"simulation_id": job["id"], "status": "pending", "cached": False}), 202

    @app.get("/api/simulation/<job_id>/status")
    def status(job_id: str):
        job = store.get(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        out = {"status": job["status"], "progress": job.get("progress", 0), "stage": job.get("stage")}
        if job.get("error"):
            out["error"] = job["error"]
        return jsonify(out)

    @app.get("/api/simulation/<job_id>/result")
    def result(job_id: str):
        job = store.get(job_id)
        if not job:
            return jsonify({"error": "not found"}), 404
        if job["status"] != "completed":
            return jsonify({"error": f"simulation is {job['status']}", "status": job["status"]}), 409
        r = job["result"]
        return jsonify({"bias": r["bias"], "conviction": r["conviction"], "detail": r.get("detail", {})})

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "queued": jobs.qsize()})

    return app
