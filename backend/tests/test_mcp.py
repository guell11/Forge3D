from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
import pytest

from app import mcp_server


def _api(monkeypatch: pytest.MonkeyPatch, handler, *, base_url: str = "http://127.0.0.1:8000", token: str = ""):
    api = mcp_server.Forge3DApi(base_url, token, transport=httpx.MockTransport(handler))
    monkeypatch.setattr(mcp_server, "_api", lambda: api)
    return api


def _response(request: httpx.Request, status: int, payload: object, headers: dict[str, str] | None = None):
    return httpx.Response(status, json=payload, headers=headers, request=request)


def test_api_url_requires_https_outside_loopback_and_token_remotely() -> None:
    with pytest.raises(mcp_server.Forge3DError, match="HTTPS"):
        mcp_server.Forge3DApi("http://forge.example", "token")
    with pytest.raises(mcp_server.Forge3DError, match="FORGE3D_API_TOKEN"):
        mcp_server.Forge3DApi("https://forge.example", "")

    assert mcp_server.Forge3DApi("http://localhost:8000", "").is_loopback
    assert mcp_server.Forge3DApi("http://[::1]:8000", "").is_loopback


def test_remote_api_sends_bearer_and_ngrok_header_without_following_redirects() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _response(request, 200, {"ok": True})

    api = mcp_server.Forge3DApi(
        "https://forge.ngrok-free.app",
        "secret-token",
        transport=httpx.MockTransport(handler),
    )
    assert api.request_json("GET", "/api/health") == {"ok": True}
    assert seen[0].headers["authorization"] == "Bearer secret-token"
    assert seen[0].headers["ngrok-skip-browser-warning"] == "1"

    redirects: list[httpx.Request] = []

    def redirect(request: httpx.Request) -> httpx.Response:
        redirects.append(request)
        return httpx.Response(307, headers={"location": "https://other.example/api/health"}, request=request)

    redirected = mcp_server.Forge3DApi(
        "https://forge.ngrok-free.app",
        "secret-token",
        transport=httpx.MockTransport(redirect),
    )
    with pytest.raises(mcp_server.Forge3DError, match="redirects are blocked"):
        redirected.request_json("GET", "/api/health")
    assert len(redirects) == 1


def test_api_http_errors_and_timeouts_are_actionable_and_do_not_expose_token() -> None:
    def unauthorized(request: httpx.Request) -> httpx.Response:
        return _response(request, 401, {"detail": "Bearer token rejected"})

    api = mcp_server.Forge3DApi(
        "https://forge.example",
        "private-token-value",
        transport=httpx.MockTransport(unauthorized),
    )
    with pytest.raises(mcp_server.Forge3DError, match="HTTP 401: Bearer token rejected") as error:
        api.request_json("GET", "/api/capabilities")
    assert "private-token-value" not in str(error.value)

    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    slow_api = mcp_server.Forge3DApi("http://127.0.0.1:8000", "", transport=httpx.MockTransport(timeout))
    with pytest.raises(mcp_server.Forge3DError, match="timed out"):
        slow_api.request_json("GET", "/api/capabilities")


def test_upload_image_checks_local_path_size_and_signature_before_post(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    png = tmp_path / "asset.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/capabilities":
            return _response(request, 200, {"limits": {"max_upload_mb": 1}})
        assert request.url.path == "/api/uploads"
        body = request.read()
        assert b"filename=\"asset.png\"" in body
        assert b"Content-Type: image/png" in body
        return _response(request, 201, {"upload": {"id": "a" * 32, "filename": "asset.png"}})

    _api(monkeypatch, handler)
    upload = mcp_server.upload_image(str(png))
    assert upload["id"] == "a" * 32
    assert [request.url.path for request in seen] == ["/api/capabilities", "/api/uploads"]

    with pytest.raises(mcp_server.Forge3DError, match="not a URL"):
        mcp_server.upload_image("https://example.test/image.png")

    mismatch = tmp_path / "wrong.png"
    mismatch.write_bytes(b"not an image")
    with pytest.raises(mcp_server.Forge3DError, match="do not match"):
        mcp_server.upload_image(str(mismatch))


def test_upload_image_honors_api_size_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    png = tmp_path / "asset.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nrest")
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return _response(request, 200, {"limits": {"max_upload_mb": 0}})

    _api(monkeypatch, handler)
    with pytest.raises(mcp_server.Forge3DError, match="max_upload_mb"):
        mcp_server.upload_image(str(png))
    assert requests == ["/api/capabilities"]


def test_generate_model_validates_options_with_api_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        payload = json.loads(request.read())
        assert payload["upload_id"] == "a" * 32
        assert payload["options"]["seed"] == 42
        assert payload["options"]["faithc"] == "geometry"
        return _response(request, 202, {"job": {"id": "b" * 32, "status": "queued"}})

    _api(monkeypatch, handler)
    job = mcp_server.generate_model(
        "a" * 32,
        {"seed": 42, "faithc": "geometry", "faithc_resolution": 512},
        adapter="auto",
    )
    assert job["status"] == "queued"
    assert captured[0].url.path == "/api/jobs"

    with pytest.raises(mcp_server.Forge3DError, match="Unsupported generation option"):
        mcp_server.generate_model("a" * 32, {"shell_command": "whoami"})
    with pytest.raises(mcp_server.Forge3DError, match="Invalid generation request"):
        mcp_server.generate_model("a" * 32, {"seed": -1})


def test_job_tools_use_existing_paginated_rest_routes_and_operation_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    full_job = {
        "id": "a" * 32,
        "status": "queued",
        "progress": 0,
        "stage": "queued",
        "queue_position": 1,
        "options": {"seed": 42},
        "events": [{"message": "queued"}],
        "logs": [{"message": "worker output"}],
        "artifacts": [{"filename": "model.glb"}],
        "validation": None,
        "error": None,
        "warnings": [],
        "output": None,
        "output_format": "glb",
        "updated_at": "2026-10-09T00:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/jobs":
            return _response(request, 200, {"jobs": [full_job], "pagination": {"total": 1}})
        if request.url.path.endswith("/operations"):
            payload = json.loads(request.read())
            assert payload == {"kind": "simplify", "target_triangles": 100000}
            return _response(request, 202, {"job": {"id": "c" * 32, "status": "queued"}})
        if request.url.path.endswith("/cancel"):
            return _response(request, 200, {"job": {"id": "b" * 32, "status": "cancelled"}})
        return _response(request, 200, {"job": {**full_job, "id": "b" * 32, "status": "running"}})

    _api(monkeypatch, handler)
    listing = mcp_server.list_jobs(limit=10, offset=20, status=["queued", "running"], favorite=True)
    assert listing["pagination"]["total"] == 1
    summary = listing["jobs"][0]
    assert summary["id"] == "a" * 32
    assert summary["status"] == "queued"
    assert {"artifacts", "validation", "error", "warnings"} <= set(summary)
    assert not {"logs", "options", "events"} & set(summary)
    assert seen[0].url.params.get_list("status") == ["queued", "running"]
    assert seen[0].url.params["limit"] == "10"
    full_detail = mcp_server.get_job("b" * 32)
    assert full_detail["status"] == "running"
    assert {"logs", "options", "events", "artifacts"} <= set(full_detail)
    assert mcp_server.cancel_job("b" * 32)["status"] == "cancelled"
    assert mcp_server.create_operation("b" * 32, "simplify", target_triangles=100000)["status"] == "queued"
    mcp_server.list_jobs()
    assert seen[4].url.params["limit"] == "20"

    with pytest.raises(mcp_server.Forge3DError, match="32-character"):
        mcp_server.get_job("../jobs")
    with pytest.raises(mcp_server.Forge3DError, match="Invalid operation request"):
        mcp_server.create_operation("b" * 32, "transform", transform={"unknown": [0, 0, 0]})
    with pytest.raises(mcp_server.Forge3DError, match="kind must be one of"):
        mcp_server.create_operation("b" * 32, "generation")


def test_agent_tools_describe_wait_and_download_registered_artifact(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[httpx.Request] = []
    job = {
        "id": "a" * 32,
        "status": "completed",
        "progress": 100,
        "stage": "completed",
        "output": {"filename": "model.glb"},
        "artifacts": [{"filename": "texture preview.png", "url": "https://untrusted.example/file"}],
        "validation": {"passed": True},
        "error": None,
        "warnings": [],
        "options": {"seed": 42},
        "events": [{"message": "finished"}],
        "logs": [{"message": "worker output"}],
        "updated_at": "2026-10-09T00:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/agent-manifest":
            return _response(request, 200, {"manifest_version": 1, "routes": []})
        if request.url.path == f"/api/jobs/{'a' * 32}/wait":
            assert request.url.params["timeout_seconds"] == "20"
            return _response(request, 200, {"job": job, "terminal": True, "timed_out": False})
        assert request.url.path == f"/api/jobs/{'a' * 32}/artifacts/texture preview.png/download"
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"preview"),
            headers={"content-length": "7", "content-type": "image/png"},
            request=request,
        )

    _api(monkeypatch, handler)
    assert mcp_server.describe_api()["manifest_version"] == 1

    waited = mcp_server.wait_job("a" * 32)
    assert waited["terminal"] is True
    assert waited["timed_out"] is False
    assert waited["job"]["output"] == job["output"]
    assert waited["job"]["artifacts"] == job["artifacts"]
    assert waited["job"]["validation"] == job["validation"]
    assert waited["job"]["warnings"] == []
    assert not {"options", "events", "logs"} & set(waited["job"])

    destination = tmp_path / "nested" / "preview.png"
    downloaded = mcp_server.download_artifact("a" * 32, "texture preview.png", str(destination))
    assert destination.read_bytes() == b"preview"
    assert downloaded["size"] == 7
    assert seen[-1].url.raw_path == b"/api/jobs/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/artifacts/texture%20preview.png/download"

    with pytest.raises(mcp_server.Forge3DError, match="filename"):
        mcp_server.download_artifact("a" * 32, "../secret.png", str(tmp_path / "secret.png"))
    with pytest.raises(mcp_server.Forge3DError, match="not a URL"):
        mcp_server.download_artifact("a" * 32, "asset.png", "https://example.test/asset.png")
    with pytest.raises(mcp_server.Forge3DError, match="already exists"):
        mcp_server.download_artifact("a" * 32, "texture preview.png", str(destination))


def test_wait_job_validates_timeout_and_api_response(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _response(
            request,
            200,
            {
                "job": {"id": "a" * 32, "status": "queued", "progress": 0},
                "terminal": False,
                "timed_out": True,
            },
        )

    _api(monkeypatch, handler)
    result = mcp_server.wait_job("a" * 32, timeout_seconds=0)
    assert result["terminal"] is False
    assert result["timed_out"] is True
    assert requests[0].url.params["timeout_seconds"] == "0"

    for timeout in (-0.1, 25.1, float("nan")):
        with pytest.raises(mcp_server.Forge3DError, match="between 0 and 25"):
            mcp_server.wait_job("a" * 32, timeout_seconds=timeout)

    def inconsistent(request: httpx.Request) -> httpx.Response:
        return _response(request, 200, {"job": {"status": "queued"}, "terminal": False, "timed_out": False})

    _api(monkeypatch, inconsistent)
    with pytest.raises(mcp_server.Forge3DError, match="inconsistent"):
        mcp_server.wait_job("a" * 32)


def test_download_streams_with_limit_and_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request.url.path)
        return httpx.Response(
            200,
            stream=httpx.ByteStream(b"glTFmodel"),
            headers={"content-length": "9", "content-type": "model/gltf-binary"},
            request=request,
        )

    _api(monkeypatch, handler)
    destination = tmp_path / "nested" / "model.glb"
    result = mcp_server.download_model("d" * 32, str(destination))
    assert destination.read_bytes() == b"glTFmodel"
    assert result["size"] == 9
    with pytest.raises(mcp_server.Forge3DError, match="already exists"):
        mcp_server.download_model("d" * 32, str(destination))
    assert len(requested) == 1


def test_download_rejects_oversize_and_removes_partial_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def too_large(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-length": str(mcp_server._MAX_DOWNLOAD_BYTES + 1)}, request=request)

    _api(monkeypatch, too_large)
    destination = tmp_path / "large.glb"
    with pytest.raises(mcp_server.Forge3DError, match="1 GiB"):
        mcp_server.download_model("e" * 32, str(destination))
    assert not destination.exists()

    class BrokenStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"partial model"
            raise httpx.ReadError("connection broke")

        def close(self) -> None:
            return None

    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=BrokenStream(), request=request)

    _api(monkeypatch, broken)
    with pytest.raises(mcp_server.Forge3DError, match="download model"):
        mcp_server.download_model("e" * 32, str(destination))
    assert not destination.exists()


def test_capabilities_calls_existing_api_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return _response(request, 200, {"ok": True})

    _api(monkeypatch, handler)
    assert mcp_server.capabilities() == {"api": {"ok": True}, "operations": {"ok": True}}
    assert seen == ["/api/capabilities", "/api/operations/capabilities"]


def test_real_stdio_handshake_and_tool_listing_without_api_or_gpu() -> None:
    async def check_client() -> None:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        backend = Path(__file__).resolve().parents[1]
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
            env={"FORGE3D_API_URL": "http://127.0.0.1:8000", "FORGE3D_API_TOKEN": ""},
            cwd=str(backend),
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                tools = await session.list_tools()
        assert initialized.serverInfo.name == "Forge3D"
        by_name = {tool.name: tool for tool in tools.tools}
        assert set(by_name) == {
            "describe_api",
            "capabilities",
            "upload_image",
            "generate_model",
            "list_jobs",
            "get_job",
            "wait_job",
            "cancel_job",
            "create_operation",
            "download_model",
            "download_artifact",
        }
        for name in {"describe_api", "capabilities", "list_jobs", "get_job", "wait_job"}:
            assert by_name[name].annotations is not None
            assert by_name[name].annotations.readOnlyHint is True
        for name in {"upload_image", "generate_model", "create_operation", "cancel_job", "download_model", "download_artifact"}:
            assert by_name[name].annotations is not None
            assert by_name[name].annotations.readOnlyHint is False

    asyncio.run(check_client())
