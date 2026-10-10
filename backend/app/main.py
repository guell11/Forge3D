from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings, get_settings
from .hardware import detect_gpu
from .agent_api import router as agent_api_router
from .pipeline import PipelineRunner
from .profiles import all_profiles, get_profile, resolve_trellis_quality
from .queue import SerialGPUQueue
from .schemas import (
    CreateJobRequest,
    GenerationOptions,
    FaithCMode,
    JobKind,
    JobPatchRequest,
    JobRecord,
    JobStatus,
    OperationRequest,
    UploadMeta,
)
from .storage import LocalStore


def _media_type(path: Path) -> str:
    return {
        ".glb": "model/gltf-binary",
        ".obj": "text/plain; charset=utf-8",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(path.suffix.lower(), "application/octet-stream")


def _store(request: Request) -> LocalStore:
    return request.app.state.store


def _queue(request: Request) -> SerialGPUQueue:
    return request.app.state.queue


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = LocalStore(settings)
    runner = PipelineRunner(settings, store)
    queue = SerialGPUQueue(store, runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await asyncio.to_thread(runner.audit_completed_history)
        await queue.start()
        try:
            yield
        finally:
            await queue.stop()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Backend local para fila image-to-3D com adapters explícitos e fallback demo seguro.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.store = store
    app.state.runner = runner
    app.state.queue = queue

    allow_all_origins = "*" in settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=not allow_all_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Direct static URLs make GLB previewing easy in a browser viewer. The API
    # also provides an explicit /api/outputs route below for clients that prefer
    # a versioned API namespace.
    app.mount("/outputs", StaticFiles(directory=str(store.outputs_dir)), name="outputs")

    @app.get("/api", tags=["system"])
    async def api_index() -> dict:
        return {"name": settings.app_name, "version": settings.app_version, "docs": "/docs"}

    @app.get("/api/health", tags=["system"])
    async def health(request: Request) -> dict:
        return {
            "status": "ok",
            "service": settings.app_name,
            "version": settings.app_version,
            # Demo remains an explicit diagnostics adapter only. It is never
            # an automatic substitute for TRELLIS, so the dashboard must not
            # label a healthy engine as a demo instance.
            "demo_fallback": False,
            "demo_available_for_diagnostics": True,
            "active_profile": get_profile(settings.active_profile).to_api(),
            "hardware": await asyncio.to_thread(detect_gpu, settings.trellis_cli_gpu_index),
            "queue": _queue(request).snapshot(),
            "storage": {"data_dir": str(settings.data_dir), "writable": settings.data_dir.is_dir()},
        }

    @app.get("/api/capabilities", tags=["system"])
    async def capabilities(request: Request) -> dict:
        return {
            "profiles": all_profiles(),
            "pipeline": await request.app.state.runner.capabilities(),
            "limits": {"max_upload_mb": settings.max_upload_mb, "gpu_concurrency": 1},
        }

    @app.get("/api/profiles", tags=["system"])
    async def profiles() -> dict:
        return {"profiles": all_profiles()}

    @app.post("/api/uploads", status_code=status.HTTP_201_CREATED, tags=["uploads"])
    async def upload_image(request: Request, file: UploadFile = File(...)) -> dict:
        upload = await _store(request).save_upload(file)
        return {"upload": upload.model_dump(mode="json")}

    @app.get("/api/uploads/{upload_id}/download", tags=["uploads"])
    async def download_upload(request: Request, upload_id: str) -> FileResponse:
        store = _store(request)
        meta = store.get_upload(upload_id)
        path = store.upload_path(upload_id)
        return FileResponse(path, media_type=_media_type(path), filename=meta.filename)

    @app.post("/api/jobs", status_code=status.HTTP_202_ACCEPTED, tags=["jobs"])
    async def create_job(request: Request, payload: CreateJobRequest) -> dict:
        # The installed model set/quality must exist, but inference resolution
        # is explicitly user-controlled. The CLI may still fail with OOM.
        profile = get_profile(request.app.state.settings.active_profile)
        requested_options = payload.options
        try:
            selected_quality = resolve_trellis_quality(
                profile,
                requested_options.trellis_quality_id,
                request.app.state.settings.engine_profile_path,
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        if payload.adapter.strip().lower() != "demo" and request.app.state.runner.trellis_cli.managed_configured:
            quality_state = next(
                (
                    item
                    for item in request.app.state.runner.trellis_cli.quality_capabilities(profile)
                    if item["id"] == selected_quality["id"]
                ),
                None,
            )
            if quality_state and not quality_state["available"]:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=quality_state["detail"],
                )
        effective_options = GenerationOptions(
            seed=requested_options.seed,
            resolution=requested_options.resolution or selected_quality["resolution"],
            texture_resolution=requested_options.texture_resolution or selected_quality.get("texture_resolution", 1024),
            target_triangles=requested_options.target_triangles,
            remove_background=profile.background_removal,
            mesh_quality=requested_options.mesh_quality,
            trellis_quality_id=selected_quality["id"],
            trellis_background_removal=requested_options.trellis_background_removal,
            trellis_uv_mode=requested_options.trellis_uv_mode,
            trellis_max_tokens=requested_options.trellis_max_tokens,
            trellis_remesh_band=requested_options.trellis_remesh_band,
            trellis_decimation_grid=requested_options.trellis_decimation_grid,
            trellis_webp=requested_options.trellis_webp,
            trellis_gss=requested_options.trellis_gss,
            trellis_gsh=requested_options.trellis_gsh,
            trellis_flash_attention=requested_options.trellis_flash_attention,
            trellis_f32=requested_options.trellis_f32,
            ultrashape=requested_options.ultrashape,
            ultrashape_quality=requested_options.ultrashape_quality,
            ultrashape_steps=requested_options.ultrashape_steps,
            ultrashape_num_latents=requested_options.ultrashape_num_latents,
            ultrashape_chunk_size=requested_options.ultrashape_chunk_size,
            ultrashape_octree_resolution=requested_options.ultrashape_octree_resolution,
            ultrashape_scale=requested_options.ultrashape_scale,
            ultrashape_low_vram=requested_options.ultrashape_low_vram,
            faithc=requested_options.faithc,
            faithc_resolution=requested_options.faithc_resolution,
            refine=requested_options.refine,
        )
        if effective_options.trellis_f32 and profile.vram_gb < 16:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O compute F32 do trellis-cli só é liberado pelo Forge3D no perfil de 16 GB.",
            )
        effective_payload = payload.model_copy(
            update={"profile": request.app.state.settings.active_profile, "options": effective_options}
        )
        if effective_payload.job_kind != JobKind.GENERATION or effective_payload.parent_job_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Use /api/jobs/{job_id}/operations para criar uma operação derivada.",
            )
        if (
            (effective_payload.options.refine or effective_payload.options.ultrashape.value == "auto")
            and effective_payload.output_format.value != "glb"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O refinamento externo opcional requer output_format='glb'.",
            )
        if (
            effective_payload.options.faithc == FaithCMode.GEOMETRY
            and effective_payload.output_format.value != "glb"
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="O artefato de geometria FaithC requer output_format='glb'.",
            )
        job = _store(request).create_job(effective_payload)
        await _queue(request).enqueue(job.id)
        return {"job": job.model_dump(mode="json")}

    @app.get("/api/operations/capabilities", tags=["operations"])
    async def operation_capabilities(request: Request) -> dict:
        return {"operations": (await request.app.state.runner.operations.capability())}

    @app.get("/api/jobs", tags=["jobs"])
    async def list_jobs(
        request: Request,
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        search: str | None = Query(default=None, max_length=200),
        status_filter: list[JobStatus] = Query(default=[], alias="status"),
        favorite: bool | None = Query(default=None),
    ) -> dict:
        jobs, total = _store(request).query_jobs(
            limit=limit,
            offset=offset,
            search=search,
            statuses=set(status_filter) or None,
            favorite=favorite,
        )
        next_offset = offset + len(jobs)
        return {
            "jobs": [job.model_dump(mode="json") for job in jobs],
            "pagination": {
                "total": total,
                "limit": limit,
                "offset": offset,
                "next_offset": next_offset if next_offset < total else None,
            },
            "queue": _queue(request).snapshot(),
        }

    @app.post("/api/jobs/{job_id}/operations", status_code=status.HTTP_202_ACCEPTED, tags=["operations"])
    async def create_operation(request: Request, job_id: str, payload: OperationRequest) -> dict:
        capability = await request.app.state.runner.operations.capability()
        # A working Blender transform must not accidentally enable retexturing
        # or any other operation.  The worker declares each operation through
        # a probe; the API enforces that declaration before a child job reaches
        # the queue.
        operation = capability.get("by_operation", {}).get(payload.kind.value)
        if not isinstance(operation, dict) or operation.get("available") is not True:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(operation.get("detail") if isinstance(operation, dict) else capability.get("detail")),
            )
        job = _store(request).create_operation_job(job_id, payload)
        await _queue(request).enqueue(job.id)
        return {"job": job.model_dump(mode="json")}

    @app.get("/api/jobs/{job_id}/events", tags=["jobs"])
    async def stream_job_events(request: Request, job_id: str, after: int = Query(default=0, ge=0)) -> StreamingResponse:
        # Resolve once before opening a stream so a typo returns a conventional
        # 404 rather than a late error in a chunked response.
        _store(request).get_job(job_id)

        async def event_stream():
            cursor = after
            first = True
            while True:
                job = _store(request).get_job(job_id)
                if first:
                    payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False)
                    yield f"event: snapshot\ndata: {payload}\n\n"
                    first = False
                events = job.events
                if cursor > len(events):
                    # Events are intentionally bounded on disk. Re-sync a slow
                    # client instead of pretending it saw an event we no longer
                    # retain.
                    cursor = 0
                while cursor < len(events):
                    payload = json.dumps(events[cursor].model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {cursor + 1}\nevent: job\ndata: {payload}\n\n"
                    cursor += 1
                if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                    payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False)
                    yield f"event: terminal\ndata: {payload}\n\n"
                    return
                if await request.is_disconnected():
                    return
                # The snapshot carries elapsed time, ETA and worker logs even
                # when a quiet CLI has not emitted another stage event yet.
                payload = json.dumps(job.model_dump(mode="json"), ensure_ascii=False)
                yield f"event: snapshot\ndata: {payload}\n\n"
                await asyncio.sleep(0.5)

        return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.get("/api/jobs/{job_id}", tags=["jobs"])
    async def get_job(request: Request, job_id: str) -> dict:
        job = _store(request).get_job(job_id)
        return {"job": job.model_dump(mode="json")}

    @app.patch("/api/jobs/{job_id}", tags=["jobs"])
    async def patch_job(request: Request, job_id: str, payload: JobPatchRequest) -> dict:
        job = _store(request).patch_job(job_id, favorite=payload.favorite, metadata=payload.metadata)
        return {"job": job.model_dump(mode="json")}

    @app.post("/api/jobs/{job_id}/cancel", tags=["jobs"])
    async def cancel_job(request: Request, job_id: str) -> dict:
        job = _queue(request).cancel(job_id)
        return {"job": job.model_dump(mode="json")}

    @app.delete("/api/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["jobs"])
    async def delete_job(request: Request, job_id: str) -> None:
        _store(request).delete_job(job_id)

    @app.get("/api/jobs/{job_id}/download", tags=["jobs"])
    async def download_job(request: Request, job_id: str) -> FileResponse:
        store = _store(request)
        job = store.get_job(job_id)
        if job.status != JobStatus.COMPLETED or not job.output:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="O modelo ainda não está disponível para download.")
        path = store.output_path(job_id, job.output.filename)
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de saída não encontrado no armazenamento local.")
        return FileResponse(path, media_type=_media_type(path), filename=path.name)

    @app.get("/api/outputs/{job_id}/{filename}", tags=["jobs"])
    async def api_output(request: Request, job_id: str, filename: str) -> FileResponse:
        store = _store(request)
        job = store.get_job(job_id)
        if not job.output or job.output.filename != filename:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de saída não encontrado.")
        path = store.output_path(job_id, filename)
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de saída não encontrado no armazenamento local.")
        return FileResponse(path, media_type=_media_type(path), filename=path.name)

    app.include_router(agent_api_router)
    return app


# Required by ``uvicorn app.main:app`` from the backend directory.
app = create_app()
