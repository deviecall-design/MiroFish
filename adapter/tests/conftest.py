import pytest

from adapter.config import Settings
from adapter.server import create_app

TEST_KEY = "test-key-not-a-secret-0123456789abcdef"


def fake_runner(seed, on_progress):
    on_progress("simulation", 50, {})
    return {"bias": 0.42, "conviction": 0.31, "detail": {"engine": "fake", "posts_scored": 3}}


@pytest.fixture
def make_app(tmp_path, monkeypatch):
    def _make(key=TEST_KEY, runner=fake_runner, **env):
        if key is None:
            monkeypatch.delenv("MIROFISH_API_KEY", raising=False)
            monkeypatch.setenv("MIROFISH_API_KEY", "")
        else:
            monkeypatch.setenv("MIROFISH_API_KEY", key)
        monkeypatch.setenv("ADAPTER_STATE_DIR", str(tmp_path / "state"))
        for k, v in env.items():
            monkeypatch.setenv(k, str(v))
        app = create_app(Settings(), runner=runner, start_worker=False)
        app.testing = True
        return app

    return _make


def auth(key=TEST_KEY):
    return {"Authorization": f"Bearer {key}"}


def drain(app):
    """Run queued jobs synchronously (the worker thread is off in tests)."""
    ext = app.extensions["mirofish_adapter"]
    q = ext["queue"]
    while not q.empty():
        job_id, seed = q.get()
        ext["work_one"](job_id, seed)
        q.task_done()
