"""Pipeline against a fake backend (no network, no LLM)."""

import httpx

from adapter import pipeline


def fake_backend():
    state = {"polls": 0}

    def handler(req: httpx.Request):
        p = req.url.path
        ok = lambda d: httpx.Response(200, json={"success": True, "data": d})
        if p == "/api/graph/ontology/generate":
            return ok({"project_id": "proj_1"})
        if p == "/api/graph/build":
            return ok({"task_id": "t1"})
        if p == "/api/graph/task/t1":
            state["polls"] += 1
            return ok({"status": "completed" if state["polls"] > 1 else "processing", "progress": 50})
        if p == "/api/simulation/create":
            return ok({"simulation_id": "sim_1"})
        if p == "/api/simulation/prepare":
            return ok({"task_id": "t2"})
        if p == "/api/simulation/prepare/status":
            return ok({"status": "completed"})
        if p == "/api/simulation/start":
            return ok({"runner_status": "running"})
        if p == "/api/simulation/sim_1/run-status":
            return ok({"runner_status": "completed", "current_round": 10, "total_rounds": 10})
        if p == "/api/simulation/sim_1/actions":
            return ok({"actions": [
                {"action_type": "CREATE_POST", "action_args": {"content": "buy the breakout"}},
                {"action_type": "CREATE_COMMENT", "action_args": {"content": "strong momentum, adding"}},
            ]})
        return httpx.Response(404, json={"success": False, "error": "nope"})

    return handler


def test_runs_end_to_end_with_lexicon():
    client = pipeline.BackendClient("http://backend")
    client.http = httpx.Client(base_url="http://backend", transport=httpx.MockTransport(fake_backend()))
    stages = []
    out = pipeline.run_pipeline(
        "seed", client, platform="reddit", max_rounds=10, poll_s=0, timeout_s=60,
        on_progress=lambda s, p, e: stages.append(s), chat=None, distill_mode="lexicon", sleep=lambda s: None,
    )
    assert out["bias"] > 0 and 0 <= out["conviction"] <= 1
    assert out["detail"]["posts_scored"] == 2 and out["detail"]["rounds"] == 10
    assert stages[0] == "ontology" and "distill" in stages


def test_backend_error_raises():
    client = pipeline.BackendClient("http://backend")
    client.http = httpx.Client(base_url="http://backend", transport=httpx.MockTransport(
        lambda r: httpx.Response(500, json={"success": False, "error": "ZEP_API_KEY未配置"})))
    try:
        pipeline.run_pipeline("seed", client, platform="reddit", max_rounds=10, poll_s=0, timeout_s=60,
                              on_progress=lambda *a: None, sleep=lambda s: None)
    except pipeline.PipelineError as e:
        assert "500" in str(e)
    else:
        raise AssertionError("expected PipelineError")
