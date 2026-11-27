"""The contract app/lib/mirofish-client.ts in mirofish-trader speaks."""

from .conftest import auth, drain


def test_start_returns_immediately_then_completes(make_app):
    app = make_app()
    c = app.test_client()
    r = c.post("/api/simulation/start", json={"seed_material": "Market signal bulletin - BTC"}, headers=auth())
    assert r.status_code == 202
    sid = r.get_json()["simulation_id"]
    assert r.get_json()["status"] == "pending"

    s = c.get(f"/api/simulation/{sid}/status", headers=auth()).get_json()
    assert s["status"] == "pending"
    assert c.get(f"/api/simulation/{sid}/result", headers=auth()).status_code == 409

    drain(app)
    s = c.get(f"/api/simulation/{sid}/status", headers=auth()).get_json()
    assert s["status"] == "completed" and s["progress"] == 100
    res = c.get(f"/api/simulation/{sid}/result", headers=auth()).get_json()
    assert res == {"bias": 0.42, "conviction": 0.31, "detail": {"engine": "fake", "posts_scored": 3}}


def test_same_seed_is_deduplicated_and_cached(make_app):
    app = make_app()
    c = app.test_client()
    seed = {"seed_material": "same bulletin"}
    a = c.post("/api/simulation/start", json=seed, headers=auth()).get_json()
    b = c.post("/api/simulation/start", json=seed, headers=auth()).get_json()
    assert a["simulation_id"] == b["simulation_id"] and b["cached"] is True
    drain(app)
    d = c.post("/api/simulation/start", json=seed, headers=auth())
    assert d.status_code == 200 and d.get_json()["simulation_id"] == a["simulation_id"]
    assert d.get_json()["status"] == "completed"
    assert app.extensions["mirofish_adapter"]["queue"].empty()


def test_cache_expires(make_app):
    app = make_app(ADAPTER_CACHE_TTL_S=0)
    c = app.test_client()
    seed = {"seed_material": "bulletin"}
    a = c.post("/api/simulation/start", json=seed, headers=auth()).get_json()
    drain(app)
    import time

    time.sleep(1.1)
    b = c.post("/api/simulation/start", json=seed, headers=auth()).get_json()
    assert b["simulation_id"] != a["simulation_id"]


def test_failed_job_reports_error(make_app):
    def boom(seed, on_progress):
        raise RuntimeError("backend error (500): LLM_API_KEY missing")

    app = make_app(runner=boom)
    c = app.test_client()
    sid = c.post("/api/simulation/start", json={"seed_material": "x"}, headers=auth()).get_json()["simulation_id"]
    drain(app)
    s = c.get(f"/api/simulation/{sid}/status", headers=auth()).get_json()
    assert s["status"] == "failed" and "backend error" in s["error"]
    assert c.get(f"/api/simulation/{sid}/result", headers=auth()).status_code == 409


def test_validation_and_unknown_ids(make_app):
    c = make_app().test_client()
    assert c.post("/api/simulation/start", json={}, headers=auth()).status_code == 400
    assert c.post("/api/simulation/start", json={"seed_material": "x" * 20001}, headers=auth()).status_code == 413
    assert c.get("/api/simulation/nope/status", headers=auth()).status_code == 404
    assert c.get("/api/simulation/nope/result", headers=auth()).status_code == 404


def test_daily_cap(make_app):
    app = make_app(ADAPTER_MAX_RUNS_PER_DAY=2)
    c = app.test_client()
    for i in range(2):
        assert c.post("/api/simulation/start", json={"seed_material": f"s{i}"}, headers=auth()).status_code == 202
    assert c.post("/api/simulation/start", json={"seed_material": "s3"}, headers=auth()).status_code == 429


def test_restart_marks_inflight_failed(make_app, tmp_path, monkeypatch):
    app = make_app()
    c = app.test_client()
    sid = c.post("/api/simulation/start", json={"seed_material": "x"}, headers=auth()).get_json()["simulation_id"]
    app2 = make_app()  # same state dir: simulates an adapter restart
    s = app2.test_client().get(f"/api/simulation/{sid}/status", headers=auth()).get_json()
    assert s["status"] == "failed"
