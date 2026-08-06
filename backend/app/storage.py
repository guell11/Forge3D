from __future__ import annotations

import json
import re
import shutil
import threading
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

from .config import Settings
from .profiles import ProfileId
from .schemas import (
    CreateJobRequest,
    JobKind,
    JobMetadata,
    OPERATION_KINDS,
    OperationRequest,
    JobEvent,
    JobInput,
    JobLog,
    JobRecord,
    JobStatus,
    UploadMeta,
)

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
_ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/webp", "image/bmp"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LocalStore:
    """Small, inspectable filesystem store for uploads, job metadata, and assets.

    JSON files are written atomically, so an interrupted process cannot leave a
    half-written job record. This is intentionally local-first rather than a
    hidden database service.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.RLock()
        self.ensure_layout()

    @property
    def uploads_dir(self) -> Path:
        return self.settings.uploads_dir

    @property
    def jobs_dir(self) -> Path:
        return self.settings.jobs_dir

    @property
    def outputs_dir(self) -> Path:
        return self.settings.outputs_dir

    def ensure_layout(self) -> None:
        for directory in (self.settings.data_dir, self.uploads_dir, self.jobs_dir, self.outputs_dir):
            directory.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename or "image").name
        name = _SAFE_NAME.sub("_", name).strip("._")
        return name or "image"

    @staticmethod
    def _atomic_json(path: Path, data: dict) -> None:
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)

    def _upload_meta_path(self, upload_id: str) -> Path:
        return self.uploads_dir / f"{upload_id}.json"

    def _job_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "job.json"

    def _manifest_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "manifest.json"

    def _assert_id(self, value: str, label: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{32}", value):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{label} não encontrado")

    async def save_upload(self, upload: UploadFile) -> UploadMeta:
        original_filename = self._safe_filename(upload.filename or "image")
        suffix = Path(original_filename).suffix.lower()
        content_type = (upload.content_type or "").lower()
        if suffix not in _ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail="Envie uma imagem PNG, JPG, WEBP ou BMP.",
            )
        if content_type and content_type not in _ALLOWED_TYPES:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=f"Tipo de arquivo não suportado: {content_type}",
            )

        upload_id = uuid.uuid4().hex
        stored_filename = f"{upload_id}{suffix}"
        target = self.uploads_dir / stored_filename
        byte_limit = self.settings.max_upload_mb * 1024 * 1024
        size = 0
        try:
            with target.open("wb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > byte_limit:
                        handle.close()
                        target.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail=f"Arquivo excede o limite de {self.settings.max_upload_mb} MB.",
                        )
                    handle.write(chunk)
        finally:
            await upload.close()

        meta = UploadMeta(
            id=upload_id,
            filename=original_filename,
            stored_filename=stored_filename,
            content_type=content_type or "application/octet-stream",
            size=size,
            created_at=utc_now(),
            url=f"/api/uploads/{upload_id}/download",
        )
        with self._lock:
            self._atomic_json(self._upload_meta_path(upload_id), meta.model_dump(mode="json"))
        return meta

    def get_upload(self, upload_id: str) -> UploadMeta:
        self._assert_id(upload_id, "Upload")
        path = self._upload_meta_path(upload_id)
        if not path.exists():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Upload não encontrado")
        try:
            return UploadMeta.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Metadados do upload inválidos") from exc

    def upload_path(self, upload_id: str) -> Path:
        meta = self.get_upload(upload_id)
        path = (self.uploads_dir / meta.stored_filename).resolve()
        if self.uploads_dir.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo enviado não encontrado")
        return path

    def create_job(self, request: CreateJobRequest) -> JobRecord:
        upload = self.get_upload(request.upload_id)
        job_id = uuid.uuid4().hex
        now = utc_now()
        job = JobRecord(
            id=job_id,
            status=JobStatus.QUEUED,
            progress=0,
            stage="queued",
            current_stage="queued",
            stage_started_at=now,
            profile=request.profile or ProfileId.GB8,
            adapter_requested=request.adapter.strip().lower(),
            pipeline_mode=request.pipeline_mode,
            job_kind=request.job_kind,
            parent_job_id=request.parent_job_id,
            metadata=(request.metadata or JobMetadata()).normalized(),
            output_format=request.output_format,
            prompt=request.prompt.strip() if request.prompt else None,
            options=request.options,
            input=JobInput(
                upload_id=upload.id,
                filename=upload.filename,
                content_type=upload.content_type,
            ),
            events=[JobEvent(at=now, stage="queued", message="Trabalho aguardando a fila GPU serial.", progress=0)],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            job_dir = self.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            self._atomic_json(self._job_path(job_id), job.model_dump(mode="json"))
            self._write_manifest_locked(job)
        return job

    def create_operation_job(self, parent_job_id: str, request: OperationRequest) -> JobRecord:
        """Create a derived job without duplicating its parent upload/output.

        The operation worker reads only the completed parent GLB and the
        original input image retained by the parent job. Jobs are deliberately
        immutable once queued so edits cannot change a running mesh operation.
        """

        if request.kind not in OPERATION_KINDS:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Informe uma operação de malha válida.")
        parent = self.get_job(parent_job_id)
        if parent.status != JobStatus.COMPLETED or not parent.output:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="A operação requer um job pai concluído com GLB disponível.")
        if parent.output.format.value != "glb":
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A operação requer uma saída GLB do job pai.")
        parent_path = self.output_path(parent.id, parent.output.filename)
        if not parent_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo GLB do job pai não está mais disponível.")

        now = utc_now()
        job_id = uuid.uuid4().hex
        metadata = (request.metadata or JobMetadata()).normalized()
        job = JobRecord(
            id=job_id,
            status=JobStatus.QUEUED,
            progress=0,
            stage="queued",
            current_stage="queued",
            stage_started_at=now,
            profile=parent.profile,
            adapter_requested="mesh-operation-worker",
            pipeline_mode=parent.pipeline_mode,
            job_kind=request.kind,
            parent_job_id=parent.id,
            operation_target_triangles=request.target_triangles,
            operation_transform=request.transform,
            metadata=metadata,
            output_format=parent.output.format,
            prompt=parent.prompt,
            options=parent.options,
            input=parent.input,
            events=[
                JobEvent(
                    at=now,
                    stage="queued",
                    message=f"Operação {request.kind.value} aguardando a fila serial.",
                    progress=0,
                    tool="mesh-operation-worker",
                )
            ],
            created_at=now,
            updated_at=now,
        )
        with self._lock:
            job_dir = self.jobs_dir / job_id
            job_dir.mkdir(parents=True, exist_ok=False)
            self._atomic_json(self._job_path(job_id), job.model_dump(mode="json"))
            self._write_manifest_locked(job)
        return job

    def _read_job(self, job_id: str) -> JobRecord:
        self._assert_id(job_id, "Job")
        path = self._job_path(job_id)
        if not path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job não encontrado")
        try:
            return JobRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Metadados do job inválidos") from exc

    @staticmethod
    def _hydrate_runtime_metrics(job: JobRecord) -> JobRecord:
        """Calculate elapsed/remaining time at read time without timer tasks."""

        if job.started_at:
            end = job.completed_at or utc_now()
            job.elapsed_seconds = max(0, int((end - job.started_at).total_seconds()))
        if job.status == JobStatus.RUNNING and job.estimated_total_seconds is not None:
            job.eta_seconds = max(0, job.estimated_total_seconds - job.elapsed_seconds)
        elif job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
            job.eta_seconds = 0
        return job

    def get_job(self, job_id: str) -> JobRecord:
        return self._hydrate_runtime_metrics(self._read_job(job_id))

    def _all_jobs(self) -> list[JobRecord]:
        jobs: list[JobRecord] = []
        for path in self.jobs_dir.glob("*/job.json"):
            try:
                jobs.append(self._hydrate_runtime_metrics(JobRecord.model_validate_json(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                # A malformed file should not take down the dashboard. It remains
                # on disk for inspection by the local operator.
                continue
        jobs.sort(key=lambda item: item.created_at, reverse=True)
        return jobs

    def list_jobs(self, limit: int = 50) -> list[JobRecord]:
        jobs = self._all_jobs()
        return jobs[:max(1, min(limit, 200))]

    def query_jobs(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        search: str | None = None,
        statuses: set[JobStatus] | None = None,
        favorite: bool | None = None,
    ) -> tuple[list[JobRecord], int]:
        needle = " ".join((search or "").lower().split())
        filtered: list[JobRecord] = []
        for job in self._all_jobs():
            if statuses and job.status not in statuses:
                continue
            if favorite is not None and job.favorite != favorite:
                continue
            if needle:
                haystack = " ".join(
                    part for part in [
                        job.id,
                        job.input.filename,
                        job.prompt or "",
                        job.metadata.title or "",
                        job.metadata.notes or "",
                        " ".join(job.metadata.tags),
                        job.job_kind.value,
                    ] if part
                ).lower()
                if needle not in haystack:
                    continue
            filtered.append(job)
        total = len(filtered)
        safe_offset = max(0, offset)
        safe_limit = max(1, min(limit, 200))
        return filtered[safe_offset : safe_offset + safe_limit], total

    def mutate_job(self, job_id: str, mutate: Callable[[JobRecord], None]) -> JobRecord:
        with self._lock:
            # Read the stored estimate rather than the dynamic response value;
            # otherwise every event write would subtract elapsed time twice.
            job = self._read_job(job_id)
            mutate(job)
            job.updated_at = utc_now()
            self._hydrate_runtime_metrics(job)
            self._atomic_json(self._job_path(job_id), job.model_dump(mode="json"))
            self._write_manifest_locked(job)
            return job.model_copy(deep=True)

    def add_event(
        self,
        job_id: str,
        stage: str,
        message: str,
        progress: int,
        *,
        tool: str | None = None,
        indeterminate: bool = False,
    ) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            job.stage = stage
            job.current_stage = stage
            job.stage_started_at = utc_now()
            job.progress = max(0, min(100, progress))
            job.current_tool = tool or job.current_tool
            job.progress_indeterminate = indeterminate
            job.events.append(
                JobEvent(
                    at=utc_now(),
                    stage=stage,
                    message=message,
                    progress=job.progress,
                    tool=tool or job.current_tool,
                    indeterminate=indeterminate,
                )
            )
            # Persist enough observability for the UI without allowing a long
            # running local instance to grow metadata indefinitely.
            job.events = job.events[-80:]

        return self.mutate_job(job_id, mutate)

    def add_log(self, job_id: str, source: str, message: str) -> JobRecord:
        safe_source = re.sub(r"[^A-Za-z0-9._-]+", "_", source)[:48] or "worker"
        safe_message = " ".join(message.replace("\x00", " ").split())[:500]
        if not safe_message:
            return self.get_job(job_id)

        def mutate(job: JobRecord) -> None:
            job.logs.append(JobLog(at=utc_now(), source=safe_source, message=safe_message))
            job.logs = job.logs[-80:]

        return self.mutate_job(job_id, mutate)

    def set_queue_position(self, job_id: str, position: int | None) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            job.queue_position = position

        return self.mutate_job(job_id, mutate)

    def patch_job(self, job_id: str, *, favorite: bool | None, metadata: JobMetadata | None) -> JobRecord:
        def mutate(job: JobRecord) -> None:
            if favorite is not None:
                job.favorite = favorite
            if metadata is not None:
                job.metadata = metadata.normalized()

        return self.mutate_job(job_id, mutate)

    def delete_job(self, job_id: str) -> None:
        """Remove a terminal job and only its own stored output/metadata."""

        with self._lock:
            job = self._read_job(job_id)
            if job.status in {JobStatus.QUEUED, JobStatus.RUNNING}:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Cancele ou aguarde o job antes de removê-lo.")
            children = [item.id for item in self._all_jobs() if item.parent_job_id == job.id]
            if children:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Remova primeiro os jobs derivados desta malha.",
                )
            job_dir = (self.jobs_dir / job.id).resolve()
            output_dir = (self.outputs_dir / job.id).resolve()
            for root, target in ((self.jobs_dir.resolve(), job_dir), (self.outputs_dir.resolve(), output_dir)):
                if root not in target.parents:
                    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Caminho de job inválido para remoção.")
                if target.exists():
                    shutil.rmtree(target)

    def _write_manifest_locked(self, job: JobRecord) -> None:
        """Persist a user-inspectable complete manifest beside ``job.json``."""

        payload = {
            "schema_version": 2,
            "generated_at": utc_now().isoformat(),
            "engine": {
                "name": self.settings.app_name,
                "active_profile": getattr(self.settings.active_profile, "value", str(self.settings.active_profile)),
                "ultrashape": {
                    "checkpoint": self.settings.ultrashape_checkpoint.name if self.settings.ultrashape_checkpoint else None,
                    "probe_recorded": bool(self.settings.ultrashape_probe_path and self.settings.ultrashape_probe_path.is_file()),
                },
            },
            "pipeline": {
                "mode": job.pipeline_mode.value,
                "tool": job.current_tool or job.adapter_used,
                "profile": job.profile.value,
                "stage": job.current_stage,
            },
            "job": job.model_dump(mode="json"),
        }
        self._atomic_json(self._manifest_path(job.id), payload)

    def output_dir(self, job_id: str) -> Path:
        self._assert_id(job_id, "Job")
        directory = self.outputs_dir / job_id
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def output_path(self, job_id: str, filename: str) -> Path:
        safe_name = self._safe_filename(filename)
        if safe_name != filename or not safe_name:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nome de saída inválido")
        path = (self.output_dir(job_id) / safe_name).resolve()
        if self.outputs_dir.resolve() not in path.parents:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo de saída inválido")
        return path

    def recover_unfinished_jobs(self) -> list[str]:
        recovered: list[str] = []
        for item in self.list_jobs(limit=200):
            if item.status not in {JobStatus.QUEUED, JobStatus.RUNNING}:
                continue
            if item.status == JobStatus.RUNNING:
                def reset(job: JobRecord) -> None:
                    job.status = JobStatus.QUEUED
                    job.stage = "queued"
                    job.error = None
                    job.warnings.append("Job recuperado após reinício do backend local.")
                    job.events.append(JobEvent(at=utc_now(), stage="queued", message="Recuperado após reinício.", progress=job.progress))

                self.mutate_job(item.id, reset)
            recovered.append(item.id)
        return recovered

    def profile_for_job(self, job_id: str) -> ProfileId:
        return self.get_job(job_id).profile
