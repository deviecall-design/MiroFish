"""Drives the upstream MiroFish backend over HTTP for one seed bulletin.

ontology -> graph build (Zep) -> create -> prepare (profiles + config) -> start
(capped rounds) -> wait -> read actions -> distill. The report agent is skipped:
the trader only needs bias and conviction, and the report is the costliest
non-simulation step.
"""

import logging
import time
from typing import Any, Callable, Dict, List, Optional

import httpx

from . import distill

log = logging.getLogger("mirofish.adapter")

REQUIREMENT = (
    "Simulate how market participants on social media react to this signal bulletin over the next few "
    "days: do they front-run the move, fade it, or ignore it? Capture sentiment direction and how strongly "
    "the crowd agrees."
)


class PipelineError(RuntimeError):
    pass


class BackendClient:
    def __init__(self, base_url: str, timeout: float = 120.0) -> None:
        self.http = httpx.Client(base_url=base_url, timeout=timeout)

    def _data(self, resp: httpx.Response) -> Dict[str, Any]:
        try:
            body = resp.json()
        except ValueError:
            raise PipelineError(f"backend returned non-JSON ({resp.status_code})")
        if resp.status_code >= 400 or not body.get("success", False):
            raise PipelineError(f"backend error ({resp.status_code}): {str(body.get('error'))[:300]}")
        return body.get("data") or {}

    def post(self, path: str, **kw) -> Dict[str, Any]:
        return self._data(self.http.post(path, **kw))

    def get(self, path: str, **kw) -> Dict[str, Any]:
        return self._data(self.http.get(path, **kw))


def run_pipeline(
    seed_material: str,
    client: BackendClient,
    *,
    platform: str,
    max_rounds: int,
    poll_s: int,
    timeout_s: int,
    on_progress: Callable[[str, int, Dict[str, Any]], None],
    chat: Optional[Callable[[List[Dict[str, str]]], str]] = None,
    distill_mode: str = "llm",
    sleep: Callable[[float], None] = time.sleep,
) -> Dict[str, Any]:
    deadline = time.time() + timeout_s
    t0 = time.time()
    timings: Dict[str, float] = {}

    def wait(fn, done, failed, stage, lo, hi):
        while True:
            if time.time() > deadline:
                raise PipelineError(f"timed out during {stage}")
            d = fn()
            if failed(d):
                raise PipelineError(f"{stage} failed: {str(d.get('error') or d.get('message'))[:300]}")
            if done(d):
                return d
            pct = d.get("progress") or d.get("progress_percent") or 0
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                pct = 0
            on_progress(stage, int(lo + (hi - lo) * min(100.0, pct) / 100.0), {})
            sleep(poll_s)

    def mark(stage):
        timings[stage] = round(time.time() - t0, 1)

    on_progress("ontology", 2, {})
    onto = client.post(
        "/api/graph/ontology/generate",
        data={"simulation_requirement": REQUIREMENT, "project_name": "trader-scan"},
        files={"files": ("seed.md", seed_material.encode("utf-8"), "text/markdown")},
    )
    project_id = onto["project_id"]
    mark("ontology")

    on_progress("graph", 10, {"project_id": project_id})
    build = client.post("/api/graph/build", json={"project_id": project_id})
    task_id = build["task_id"]
    wait(
        lambda: client.get(f"/api/graph/task/{task_id}"),
        lambda d: d.get("status") == "completed",
        lambda d: d.get("status") == "failed",
        "graph", 10, 25,
    )
    mark("graph")

    sim = client.post(
        "/api/simulation/create",
        json={
            "project_id": project_id,
            "enable_twitter": platform in ("twitter", "parallel"),
            "enable_reddit": platform in ("reddit", "parallel"),
        },
    )
    sim_id = sim["simulation_id"]
    on_progress("prepare", 25, {"backend_simulation_id": sim_id})
    prep = client.post(
        "/api/simulation/prepare",
        json={"simulation_id": sim_id, "use_llm_for_profiles": True, "parallel_profile_count": 3},
    )
    if not prep.get("already_prepared"):
        prep_task = prep.get("task_id")
        wait(
            lambda: client.post("/api/simulation/prepare/status", json={"task_id": prep_task, "simulation_id": sim_id}),
            lambda d: d.get("status") in ("completed", "ready") or d.get("already_prepared"),
            lambda d: d.get("status") == "failed",
            "prepare", 25, 45,
        )
    mark("prepare")

    client.post(
        "/api/simulation/start",
        json={
            "simulation_id": sim_id,
            "platform": platform,
            "max_rounds": max_rounds,
            "enable_graph_memory_update": False,
        },
    )
    run = wait(
        lambda: client.get(f"/api/simulation/{sim_id}/run-status"),
        lambda d: d.get("runner_status") in ("completed", "stopped"),
        lambda d: d.get("runner_status") == "failed",
        "simulation", 45, 92,
    )
    mark("simulation")

    on_progress("distill", 95, {})
    actions = client.get(f"/api/simulation/{sim_id}/actions", params={"limit": 5000}).get("actions", [])
    texts = distill.post_texts(actions)
    reading = None
    if distill_mode == "llm" and chat is not None:
        try:
            reading = distill.distill_llm(texts, seed_material, chat)
        except Exception as e:  # provider hiccup: fall back, never fail the job for it
            log.warning("LLM distillation failed, using lexicon: %s", type(e).__name__)
    if reading is None:
        reading = distill.distill_lexicon(texts)
    mark("distill")

    return {
        "bias": reading["bias"],
        "conviction": reading["conviction"],
        "detail": {
            "engine": "mirofish-oasis",
            "method": reading["method"],
            "posts_scored": len(texts),
            "actions": len(actions),
            "rounds": run.get("current_round"),
            "total_rounds": run.get("total_rounds"),
            "platform": platform,
            "project_id": project_id,
            "backend_simulation_id": sim_id,
            "timings_s": timings,
        },
    }


def openai_chat(api_key: str, base_url: str, model: str) -> Callable[[List[Dict[str, str]]], str]:
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=120)

    def chat(messages):
        r = client.chat.completions.create(model=model, messages=messages, temperature=0.2, max_tokens=1500)
        return r.choices[0].message.content or ""

    return chat
