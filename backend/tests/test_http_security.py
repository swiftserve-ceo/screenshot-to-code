# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false
"""CORS policy + operator gate + request-id middleware.

Regression cover for BASELINE_FUNCTIONAL_AUDIT SF-3 (wildcard CORS) and SF-4
(unauthenticated eval / agent-run endpoints).
"""

import importlib

import pytest
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

import config
import operator_gate
from operator_gate import require_operator
from request_context import RequestContextMiddleware


@pytest.fixture()
def app_client():
    # Reload main so it is built against the current (default) settings.
    main = importlib.import_module("main")
    importlib.reload(main)
    with TestClient(main.app) as client:
        yield client


# --- CORS --------------------------------------------------------------------

def test_cors_allows_configured_dev_origin(app_client):
    resp = app_client.get(
        "/api/capabilities", headers={"Origin": "http://localhost:5173"}
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unlisted_origin(app_client):
    resp = app_client.get(
        "/api/capabilities", headers={"Origin": "https://evil.example"}
    )
    # Request still succeeds server-side, but the browser is not granted access.
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


def test_cors_preflight_from_unlisted_origin_is_not_allowed(app_client):
    resp = app_client.options(
        "/api/design-systems",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.headers.get("access-control-allow-origin") != "https://evil.example"


# --- operator gate ----------------------------------------------------------

def test_operator_endpoints_closed_by_default(app_client):
    for path in ("/agent-runs", "/prompt-reports", "/eval-sets", "/models"):
        resp = app_client.get(path)
        assert resp.status_code == 403, path


def test_public_endpoints_still_open(app_client):
    assert app_client.get("/api/capabilities").status_code == 200
    assert app_client.get("/").status_code == 200


def _gated_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.settings.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/secret", dependencies=[Depends(require_operator)])
    def _secret():
        return {"ok": True}

    return app


def test_operator_gate_requires_token(monkeypatch):
    fake = config.settings.model_copy(
        update={"operator_token": "topsecret", "operator_endpoints_public": False}
    )
    monkeypatch.setattr(operator_gate, "settings", fake)
    client = TestClient(_gated_app())
    assert client.get("/secret").status_code == 401
    assert client.get("/secret", headers={"X-Operator-Token": "wrong"}).status_code == 401
    assert (
        client.get("/secret", headers={"X-Operator-Token": "topsecret"}).status_code
        == 200
    )


def test_operator_gate_public_escape_hatch(monkeypatch):
    fake = config.settings.model_copy(update={"operator_endpoints_public": True})
    monkeypatch.setattr(operator_gate, "settings", fake)
    client = TestClient(_gated_app())
    assert client.get("/secret").status_code == 200


# --- request id -----------------------------------------------------------

def test_response_carries_request_id(app_client):
    resp = app_client.get("/api/capabilities")
    assert resp.headers.get("X-Request-ID")


def test_request_id_from_inbound_header_is_echoed(app_client):
    resp = app_client.get(
        "/api/capabilities", headers={"X-Request-ID": "trace-abc-123"}
    )
    assert resp.headers.get("X-Request-ID") == "trace-abc-123"
