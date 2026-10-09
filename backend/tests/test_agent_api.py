from __future__ import annotations

import asyncio
import os
import subprocess
import time
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from app.schemas import CreateJobRequest, JobArtifact, OperationRequest


_png_buffer = BytesIO()
Image.new("RGB", (1, 1), (210, 80, 30)).save(_png_buffer, format="PNG")
_ONE_PIXEL_PNG = _png_buffer.getvalue()


@pytest.fixture()
def client(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "local-data",
        max_upload_mb=7,
        trellis_server_url=None,
        trellis_cpp_command=None,
        engine_profile_path=tmp_path / "missing-engine-profile.json",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _create_demo_job(client: TestClient) -> str:
    uploaded = client.post(
        "/api/uploads",
        files={"file": ("asset.png", _ONE_PIXEL_PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    created = client.post(
        "/api/jobs",
        json={"upload_id": uploaded.json()["upload"]["id"], "adapter": "demo", "output_format": "glb"},
    )
    assert created.status_code == 202, created.text
    return created.json()["job"]["id"]


def test_agent_manifest_exposes_real_schemas_and_dynamic_discovery(client: TestClient) -> None:
    response = client.get("/api/agent-manifest")
    assert response.status_code == 200
    manifest = response.json()

    assert manifest["manifest_version"] == 1
    assert manifest["service"]["version"] == client.app.state.settings.app_version
    assert manifest["schemas"]["generation_request"] == CreateJobRequest.model_json_schema()
    assert manifest["schemas"]["operation_request"] == OperationRequest.model_json_schema()
    assert manifest["limits"]["upload_max_mb"] == 7
    assert manifest["dynamic_capabilities"]["engines_and_profiles"]["path"] == "/api/capabilities"
    assert manifest["dynamic_capabilities"]["operations"]["path"] == "/api/operations/capabilities"
    assert manifest["authentication"]["rest_api_enforces_bearer"] is False
    assert manifest["authentication"]["remote_mcp_bridge"]["token_environment_variable"] == "FORGE3D_API_TOKEN"
    assert manifest["faithc"]["mode"] == "geometry"
    assert manifest["faithc"]["pbr_texturing"] is False
    pointer = manifest["faithc"]["request_schema_pointer"]
    schema_property = manifest
    for part in pointer[2:].split("/"):
        schema_property = schema_property[part.replace("~1", "/").replace("~0", "~")]
    assert schema_property["$ref"] == "#/$defs/FaithCMode"
    paths = {route["path"] for route in manifest["routes"]}
    assert {"/openapi.json", "/api/jobs", "/api/jobs/{job_id}/cancel"} <= paths
    assert manifest["links"]["openapi"] == "/openapi.json"
    assert all(route["path"].startswith("/") for route in manifest["routes"])
    assert all("http://" not in route["path"] and "https://" not in route["path"] for route in manifest["routes"])


def test_wait_returns_terminal_record_at_zero_and_max_timeout(client: TestClient) -> None:
    job_id = _create_demo_job(client)
    response = client.get(f"/api/jobs/{job_id}/wait", params={"timeout_seconds": 25})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["job"]["id"] == job_id
    assert result["job"]["status"] == "completed"
    assert result["terminal"] is True
    assert result["timed_out"] is False

    immediate = client.get(f"/api/jobs/{job_id}/wait", params={"timeout_seconds": 0})
    assert immediate.status_code == 200
    assert immediate.json()["terminal"] is True
    assert immediate.json()["timed_out"] is False


def test_wait_returns_404_for_unknown_or_invalid_job(client: TestClient) -> None:
    assert client.get(f"/api/jobs/{'f' * 32}/wait").status_code == 404
    assert client.get("/api/jobs/not-an-id/wait").status_code == 404


def test_wait_timeout_does_not_cancel_job_and_validates_bounds(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def hold_job(_: str) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(client.app.state.runner, "run", hold_job)
    job_id = _create_demo_job(client)

    started = time.monotonic()
    response = client.get(f"/api/jobs/{job_id}/wait", params={"timeout_seconds": 0.05})
    assert time.monotonic() - started < 1
    assert response.status_code == 200
    result = response.json()
    assert result["job"]["status"] == "queued"
    assert result["terminal"] is False
    assert result["timed_out"] is True
    assert client.get(f"/api/jobs/{job_id}").json()["job"]["status"] == "queued"

    for timeout in (-0.1, 25.1, "NaN"):
        assert client.get(f"/api/jobs/{job_id}/wait", params={"timeout_seconds": timeout}).status_code == 422


def test_wait_stops_polling_when_request_disconnects(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def hold_job(_: str) -> None:
        await asyncio.Event().wait()

    async def disconnected(_: Request) -> bool:
        return True

    monkeypatch.setattr(client.app.state.runner, "run", hold_job)
    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    job_id = _create_demo_job(client)

    response = client.get(f"/api/jobs/{job_id}/wait", params={"timeout_seconds": 10})
    assert response.status_code == 499
    assert client.get(f"/api/jobs/{job_id}").json()["job"]["status"] == "queued"


def test_artifact_download_requires_registration_and_stays_inside_job_output(client: TestClient, tmp_path: Path) -> None:
    job_id = _create_demo_job(client)
    finished = client.get(f"/api/jobs/{job_id}/wait", params={"timeout_seconds": 25}).json()["job"]
    artifact = next(item for item in finished["artifacts"] if item["kind"] == "model")

    downloaded = client.get(f"/api/jobs/{job_id}/artifacts/{artifact['filename']}/download")
    assert downloaded.status_code == 200
    assert downloaded.content[:4] == b"glTF"

    assert client.get(f"/api/jobs/{job_id}/artifacts/unregistered.glb/download").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/artifacts/%2E%2E%2Fsecret.glb/download").status_code == 404

    outside = tmp_path / "secret.glb"
    outside.write_bytes(b"private")
    raw_job_dir = client.app.state.store.outputs_dir / job_id
    link = raw_job_dir / "escape.glb"

    if os.name == "nt":
        external_job_dir = tmp_path / "outside-job-dir"
        raw_job_dir.rename(external_job_dir)
        (external_job_dir / "escape.glb").write_bytes(b"private")
        junction = subprocess.run(
            ["cmd.exe", "/c", "mklink", "/J", str(raw_job_dir), str(external_job_dir)],
            capture_output=True,
            text=True,
            check=False,
        )
        if junction.returncode != 0:
            pytest.skip(f"Directory junction creation unavailable: {junction.stderr.strip()}")
    else:
        try:
            link.symlink_to(outside)
        except OSError as exc:
            pytest.skip(f"Symlink creation unavailable: {exc}")

    def register_escape(job) -> None:
        job.artifacts.append(
            JobArtifact(
                kind="preview",
                label="preview",
                filename=link.name,
                size=outside.stat().st_size,
                url=f"/outputs/{job_id}/{link.name}",
                media_type="model/gltf-binary",
            )
        )

    client.app.state.store.mutate_job(job_id, register_escape)
    rejected = client.get(f"/api/jobs/{job_id}/artifacts/{link.name}/download")
    assert rejected.status_code == 404
