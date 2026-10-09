from __future__ import annotations

import asyncio
import math
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from .schemas import CreateJobRequest, JobStatus, OperationRequest

router = APIRouter()

_TERMINAL_STATUSES = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
_WAIT_POLL_SECONDS = 0.25


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def _is_plain_filename(filename: str) -> bool:
    return bool(
        filename
        and filename not in {".", ".."}
        and "/" not in filename
        and "\\" not in filename
        and "\x00" not in filename
        and "\r" not in filename
        and "\n" not in filename
        and Path(filename).name == filename
    )


def _manifest(settings: Any) -> dict[str, Any]:
    return {
        "manifest_version": 1,
        "service": {"name": settings.app_name, "version": settings.app_version},
        "routes": [
            {"method": "GET", "path": "/api/agent-manifest", "purpose": "Discover API workflow and request schemas."},
            {"method": "GET", "path": "/openapi.json", "purpose": "Browse the complete API route catalog."},
            {"method": "GET", "path": "/api/capabilities", "purpose": "Read current engine, profile, and upload capabilities."},
            {"method": "GET", "path": "/api/operations/capabilities", "purpose": "Read current per-operation availability."},
            {"method": "POST", "path": "/api/uploads", "purpose": "Upload an input image."},
            {"method": "POST", "path": "/api/jobs", "purpose": "Queue a generation job."},
            {"method": "GET", "path": "/api/jobs", "purpose": "List jobs with pagination and filters."},
            {"method": "GET", "path": "/api/jobs/{job_id}/wait", "purpose": "Wait for a terminal job state for up to 25 seconds."},
            {"method": "GET", "path": "/api/jobs/{job_id}", "purpose": "Read the full job record."},
            {"method": "POST", "path": "/api/jobs/{job_id}/cancel", "purpose": "Request cancellation of a queued or running job."},
            {"method": "POST", "path": "/api/jobs/{job_id}/operations", "purpose": "Queue a supported operation on a completed model."},
            {"method": "GET", "path": "/api/jobs/{job_id}/artifacts/{filename}/download", "purpose": "Download an artifact registered in the job record."},
            {"method": "GET", "path": "/api/jobs/{job_id}/download", "purpose": "Download the completed primary model."},
        ],
        "workflow": [
            "Read /api/agent-manifest for routes and schemas, then query /api/capabilities before choosing generation options; capabilities describe current configuration and do not guarantee a successful run.",
            "Upload an image with POST /api/uploads and submit its upload.id with POST /api/jobs.",
            "Poll with GET /api/jobs/{job_id}/wait. A timeout reports the current job and does not cancel it or imply success.",
            "Use GET /api/jobs/{job_id} for full details. Download only the primary model or filenames listed in job.artifacts.",
            "Before POST /api/jobs/{job_id}/operations, query /api/operations/capabilities and require availability for the requested operation.",
        ],
        "retry_policy": {
            "mutating_post_is_idempotent": False,
            "guidance": "Do not automatically retry an upload, generation, operation, or cancellation POST after an ambiguous timeout; inspect current API/job state first.",
        },
        "schemas": {
            "generation_request": CreateJobRequest.model_json_schema(),
            "operation_request": OperationRequest.model_json_schema(),
        },
        "links": {
            "openapi": "/openapi.json",
            "generation_schema": "#/schemas/generation_request",
            "operation_schema": "#/schemas/operation_request",
        },
        "limits": {
            "upload_max_mb": settings.max_upload_mb,
            "upload_limit_source": {"method": "GET", "path": "/api/capabilities", "json_pointer": "/limits/max_upload_mb"},
            "wait_timeout_seconds": {"minimum": 0, "maximum": 25, "default": 20},
        },
        "dynamic_capabilities": {
            "engines_and_profiles": {"method": "GET", "path": "/api/capabilities"},
            "operations": {"method": "GET", "path": "/api/operations/capabilities"},
        },
        "authentication": {
            "rest_api_enforces_bearer": False,
            "remote_mcp_bridge": {
                "requires_https_for_non_loopback": True,
                "token_environment_variable": "FORGE3D_API_TOKEN",
                "header": "Authorization: Bearer <token>",
                "validation": "Requires a trusted gateway or proxy; the normal REST app does not validate bearer tokens.",
            },
        },
        "faithc": {
            "mode": "geometry",
            "request_schema_pointer": "#/schemas/generation_request/$defs/GenerationOptions/properties/faithc",
            "pbr_texturing": False,
            "availability": {"method": "GET", "path": "/api/capabilities"},
        },
    }


@router.get("/api/agent-manifest", tags=["agents"])
async def agent_manifest(request: Request) -> dict[str, Any]:
    return _manifest(request.app.state.settings)


@router.get("/api/jobs/{job_id}/wait", tags=["agents"], response_model=None)
async def wait_for_job(
    request: Request,
    job_id: str,
    timeout_seconds: float = Query(default=20, ge=0, le=25),
) -> Any:
    """Return {job, terminal, timed_out}; timeout never cancels the job, disconnect ends polling."""
    if not math.isfinite(timeout_seconds):
        raise HTTPException(status_code=422, detail="timeout_seconds must be between 0 and 25.")

    store = request.app.state.store
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        job = await asyncio.to_thread(store.get_job, job_id)
        terminal = job.status in _TERMINAL_STATUSES
        if terminal:
            return {"job": job.model_dump(mode="json"), "terminal": True, "timed_out": False}

        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return {"job": job.model_dump(mode="json"), "terminal": False, "timed_out": True}
        if await request.is_disconnected():
            return Response(status_code=499)
        await asyncio.sleep(min(_WAIT_POLL_SECONDS, remaining))


@router.get("/api/jobs/{job_id}/artifacts/{filename}/download", tags=["agents"])
async def download_job_artifact(request: Request, job_id: str, filename: str) -> FileResponse:
    if len(filename) > 255 or not _is_plain_filename(filename):
        raise _not_found("Artefato não encontrado")

    store = request.app.state.store
    job = store.get_job(job_id)
    artifact = next((item for item in job.artifacts if item.filename == filename), None)
    if artifact is None:
        raise _not_found("Artefato não registrado neste job")

    try:
        output_root = store.outputs_dir.resolve(strict=True)
        raw_job_dir = store.outputs_dir / job.id
        if raw_job_dir.is_symlink():
            raise _not_found("Diretório de artefatos inválido")
        job_dir = raw_job_dir.resolve(strict=True)
        expected_job_dir = output_root / job.id
        if job_dir != expected_job_dir or not job_dir.is_dir():
            raise _not_found("Diretório de artefatos inválido")

        path = (job_dir / filename).resolve(strict=True)
        if path.parent != job_dir or output_root not in path.parents or not path.is_file():
            raise _not_found("Artefato inválido")
    except HTTPException:
        raise
    except (OSError, RuntimeError, ValueError) as exc:
        raise _not_found("Artefato não encontrado") from exc

    media_type = artifact.media_type
    if not media_type or any(ord(character) < 32 or ord(character) == 127 for character in media_type):
        media_type = "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)
