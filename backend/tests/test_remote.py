from __future__ import annotations

import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.serve_remote import create_remote_app


ACCESS_TOKEN = "kaggle-smoke-access-token-0123456789"


def _client(tmp_path: Path) -> TestClient:
    distribution = tmp_path / "dist"
    (distribution / "assets").mkdir(parents=True)
    (distribution / "index.html").write_text(
        '<!doctype html><html><script type="module" src="/assets/app.js"></script></html>',
        encoding="utf-8",
    )
    (distribution / "assets" / "app.js").write_text("export const ready = true;", encoding="utf-8")

    outputs = tmp_path / "outputs"
    outputs.mkdir()
    (outputs / "model.glb").write_bytes(b"glTF" + bytes(16))
    (tmp_path / "outside.txt").write_text("private-outside-static-root", encoding="utf-8")

    api = FastAPI()

    @api.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @api.get("/api/jobs/{job_id}/events")
    async def events(job_id: str) -> StreamingResponse:
        async def stream():
            yield f"event: update\ndata: {job_id}\n\n".encode("utf-8")

        return StreamingResponse(stream(), media_type="text/event-stream")

    api.mount("/outputs", StaticFiles(directory=str(outputs)), name="outputs")
    return TestClient(
        create_remote_app(api_app=api, static_directory=distribution, access_token=ACCESS_TOKEN),
        base_url="https://forge3d.ngrok.app",
        follow_redirects=False,
    )


def test_gateway_requires_auth_for_api_assets_and_outputs(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/health").status_code == 401
    assert client.get("/assets/app.js", headers={"accept": "application/javascript"}).status_code == 401
    assert client.get("/outputs/model.glb").status_code == 401
    root = client.get("/", headers={"accept": "text/html"})
    assert root.status_code == 303
    assert root.headers["location"] == "/_auth/login"


def test_bearer_auth_covers_api_assets_and_glb(tmp_path: Path) -> None:
    client = _client(tmp_path)
    headers = {"authorization": f"Bearer {ACCESS_TOKEN}"}
    assert client.get("/api/health", headers=headers).json() == {"status": "ok"}
    assert client.get("/assets/app.js", headers=headers).text == "export const ready = true;"
    assert client.get("/outputs/model.glb", headers=headers).content.startswith(b"glTF")


def test_browser_login_sets_secure_http_only_session_for_ui_api_and_sse(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/_auth/login",
        data={"token": ACCESS_TOKEN},
        headers={"origin": "https://forge3d.ngrok.app", "x-forwarded-proto": "https"},
    )
    assert response.status_code == 303
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=Strict" in cookie
    assert "Secure" in cookie
    assert client.get("/", headers={"accept": "text/html"}).status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}
    stream = client.get("/api/jobs/job-123/events", headers={"accept": "text/event-stream"})
    assert stream.status_code == 200
    assert "event: update\ndata: job-123" in stream.text
    assert client.get("/outputs/model.glb").content.startswith(b"glTF")


def test_login_rejects_wrong_unicode_token_and_cross_origin(tmp_path: Path) -> None:
    client = _client(tmp_path)
    origin = {"origin": "https://forge3d.ngrok.app", "x-forwarded-proto": "https"}
    assert client.post("/_auth/login", data={"token": "wrong-token"}, headers=origin).status_code == 401
    unicode_response = client.post("/_auth/login", data={"token": "é" * 32}, headers=origin)
    assert unicode_response.status_code == 401
    cross_origin = client.post(
        "/_auth/login",
        data={"token": ACCESS_TOKEN},
        headers={
            "origin": "https://attacker.example",
            "x-forwarded-host": "forge3d.ngrok.app",
            "x-forwarded-proto": "https",
        },
    )
    assert cross_origin.status_code == 403


def test_expired_and_malformed_cookies_fail_closed(tmp_path: Path) -> None:
    client = _client(tmp_path)
    expired = client.get("/api/health", headers={"cookie": "forge3d_session=1." + "x" * 43})
    overlong_expiry = client.get("/api/health", headers={"cookie": "forge3d_session=" + "9" * 100 + ".bad"})
    assert expired.status_code == 401
    assert overlong_expiry.status_code == 401


def test_static_mount_rejects_parent_path_traversal(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.get(
        "/outputs/%2e%2e%2foutside.txt",
        headers={"authorization": f"Bearer {ACCESS_TOKEN}"},
    )
    assert response.status_code != 200
    assert b"private-outside-static-root" not in response.content
