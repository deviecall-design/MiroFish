"""Unauthenticated or wrongly authenticated requests must get 401 on every route."""

import pytest

from .conftest import TEST_KEY, auth

ROUTES = [
    ("post", "/api/simulation/start", {"json": {"seed_material": "x"}}),
    ("get", "/api/simulation/mfa_anything/status", {}),
    ("get", "/api/simulation/mfa_anything/result", {}),
    ("get", "/health", {}),
    ("get", "/does/not/exist", {}),
    ("post", "/api/graph/ontology/generate", {}),  # upstream paths are not proxied either
]

BAD_HEADERS = [
    {},
    {"Authorization": ""},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer "},
    {"Authorization": "Bearer wrong-key"},
    {"Authorization": f"Basic {TEST_KEY}"},
    {"Authorization": TEST_KEY},
    {"Authorization": f"Bearer {TEST_KEY}x"},
    {"Authorization": f"Bearer {TEST_KEY[:-1]}"},
    {"X-Api-Key": TEST_KEY},
]


@pytest.mark.parametrize("method,path,kw", ROUTES)
@pytest.mark.parametrize("headers", BAD_HEADERS)
def test_rejects_without_valid_bearer(make_app, method, path, kw, headers):
    client = make_app().test_client()
    resp = getattr(client, method)(path, headers=headers, **kw)
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate") == "Bearer"
    assert TEST_KEY not in resp.get_data(as_text=True)


@pytest.mark.parametrize("method,path,kw", ROUTES)
def test_unauthenticated_start_queues_nothing(make_app, method, path, kw):
    app = make_app()
    getattr(app.test_client(), method)(path, **kw)
    assert app.extensions["mirofish_adapter"]["queue"].empty()


def test_fails_closed_when_no_key_configured(make_app):
    client = make_app(key=None).test_client()
    for headers in ({}, {"Authorization": "Bearer "}, auth("")):
        assert client.get("/health", headers=headers).status_code == 503
        assert client.post("/api/simulation/start", json={"seed_material": "x"}, headers=headers).status_code == 503


def test_valid_bearer_passes(make_app):
    client = make_app().test_client()
    assert client.get("/health", headers=auth()).status_code == 200
    assert client.get("/health", headers={"Authorization": f"bearer {TEST_KEY}"}).status_code == 200
