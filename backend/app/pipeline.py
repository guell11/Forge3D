from __future__ import annotations

import json
import re
import contextlib
from pathlib import Path

from .adapters import AdapterError, DemoAdapter, MeshOperationAdapter, TrellisCppCliAdapter, TrellisServerAdapter, UltraShapeRefiner
from .adapters.base import AdapterResult, GenerationAdapter
from .adapters.faithc import FaithCRefiner
from .config import Settings
from .gpu import GPUOwnershipSupervisor
from .profiles import get_profile, resolve_trellis_quality
from .quality import EtaEstimate, LocalEtaEstimator, validate_model
from .schemas import (
    ExportFormat,
    JobArtifact,
    JobEvent,
    JobKind,
    JobOutput,
    JobRecord,
    JobStatus,
    PipelineMode,
    FaithCMode,
    UltraShapeMode,
)
from .storage import LocalStore, utc_now


class PipelineRunner:
    """Coordinates a TRELLIS base result and an optional real UltraShape pass.

    The queue calls this method serially. Heavy ML modules remain in their own
    local processes. A texturless UltraShape result never replaces the audited
    TRELLIS PBR GLB just because the refinement command completed.
    """

    _ALIASES = {
        # Older Forge3D clients used "trellis" as a generic selector.  It
        # must now resolve to the managed one-shot CLI, not the legacy HTTP
        # server, otherwise TRELLIS_AUTOSTART=0 causes a needless failure.
        "trellis": "trellis-cli",
        "trellis-server": "trellis-server",
        "trellis-cpp": "trellis-cli",
        "trellis.cpp": "trellis-cli",
        "trellis-cpp-cli": "trellis-cli",
        "trellis-cli": "trellis-cli",
        "demo": "demo",
    }

    def __init__(self, settings: Settings, store: LocalStore) -> None:
        self.settings = settings
        self.store = store
        self.demo = DemoAdapter()
        self.trellis_server = TrellisServerAdapter(settings)
        self.trellis_cli = TrellisCppCliAdapter(settings)
        self.operations = MeshOperationAdapter(settings)
        self.ultrashape = UltraShapeRefiner(settings)
        self.faithc = FaithCRefiner(settings)
        self.gpu = GPUOwnershipSupervisor(settings)
        self.eta = LocalEtaEstimator(store, settings)

    def audit_completed_history(self) -> None:
        """Refresh persisted audits after validator upgrades without deleting history."""
        for stored in self.store.list_jobs(limit=200):
            if stored.status != JobStatus.COMPLETED or not stored.output:
                continue
            output_path = self.store.output_path(stored.id, stored.output.filename)
            if not output_path.is_file():
                continue
            report = validate_model(output_path, stored.output_format)
            if stored.validation is not None:
                report = report.model_copy(update={"validated_at": stored.validation.validated_at})
            if stored.validation == report:
                continue

            def update(job: JobRecord, refreshed=report) -> None:
                job.validation = refreshed
                job.warnings = [
                    warning for warning in job.warnings
                    if warning != "Malha sem textura PBR incorporada detectável."
                ]
                for warning in refreshed.warnings:
                    if warning not in job.warnings:
                        job.warnings.append(warning)

            self.store.mutate_job(stored.id, update)

    async def capabilities(self) -> dict:
        active_profile = get_profile(self.settings.active_profile)
        adapters = [
            await self.trellis_cli.capability(),
            await self.trellis_server.capability(),
            await self.demo.capability(),
        ]
        refiner = await self.ultrashape.capability(active_profile)
        faithc = await self.faithc.capability(active_profile)
        operations = await self.operations.capability()
        return {
            "queue_policy": "serial-gpu",
            "models_kept_loaded_by_api": False,
            "gpu_ownership": self.gpu.capability(),
            "default_pipeline": PipelineMode.TRELLIS_DETAIL.value,
            "pipeline_modes": {
                PipelineMode.TRELLIS_DETAIL.value: {
                    "label": "TRELLIS 2 — malha, UV e PBR",
                    "adapter": "trellis-cli gerenciado (primário), depois trellis-server",
                    "fallback": "none",
                },
                PipelineMode.SMART_TEXTURED.value: {
                    "label": "Legado — roteado para TRELLIS 2",
                    "adapter": "trellis-cli gerenciado (primário), depois trellis-server",
                    "fallback": "none",
                },
            },
            "active_profile": {
                "id": active_profile.id.value,
                "trellis_qualities": self.trellis_cli.quality_capabilities(active_profile),
                "installed_gguf": self._installed_gguf(),
                "ultrashape_default": "auto",
                "ultrashape_modes": refiner["modes"],
            },
            "adapters": adapters,
            "refiners": [refiner, faithc],
            "operations": operations,
            "official_trellis2": {
                "id": "trellis2-official",
                "configured": bool(self.settings.official_trellis2_command),
                "available_for_shipped_profiles": False,
                "supported_profiles": [],
                "minimum_reference_vram_gb": 24,
                "reference_platform": "Linux",
                "detail": (
                    "O backend não marca o TRELLIS.2 oficial como compatível com 6/8/12/16 GB. "
                    "Use o runtime local trellis.cpp instalado pelo perfil."
                ),
            },
            "auto_selection": "trellis-cli gerenciado é a base. UltraShape automático só roda após probe/calibração e liberação de VRAM confirmadas.",
        }

    @staticmethod
    def _installed_gguf() -> dict:
        """Read installer metadata if present; never infer a quantization."""

        runtime = Path(__file__).resolve().parents[2] / "runtime" / "engine-profile.json"
        if not runtime.is_file():
            return {"known": False, "detail": "Metadados do pacote GGUF não encontrados."}
        try:
            payload = json.loads(runtime.read_text(encoding="utf-8"))
            trellis = payload.get("trellis", {})
            model_set = trellis.get("model_set") if isinstance(trellis, dict) else None
            model_sets = trellis.get("model_sets") if isinstance(trellis, dict) else None
            default_quant = trellis.get("default_quant") if isinstance(trellis, dict) else None
            legacy_quant = trellis.get("quant") if isinstance(trellis, dict) else None
            known_sets = [item for item in model_sets if isinstance(item, str)] if isinstance(model_sets, list) else []
            selected = model_set if isinstance(model_set, str) else default_quant if isinstance(default_quant, str) else legacy_quant if isinstance(legacy_quant, str) else None
            return {
                "known": bool(selected or known_sets),
                "id": selected,
                "installed_variants": known_sets,
                "detail": "Identificado pelo instalador; a seleção só é funcional quando o models-dir correspondente existe.",
            }
        except (OSError, json.JSONDecodeError):
            return {"known": False, "detail": "Metadados do pacote GGUF inválidos."}

    def _requested_adapter(self, job: JobRecord) -> tuple[str, GenerationAdapter]:
        requested = job.adapter_requested.strip().lower()
        normalized = self._ALIASES.get(requested)
        if requested in {"trellis2", "trellis2-official", "official-trellis2"}:
            raise AdapterError("TRELLIS.2 oficial não é selecionável nos perfis enviados; use o runtime local instalado.")
        if job.pipeline_mode not in {PipelineMode.TRELLIS_DETAIL, PipelineMode.SMART_TEXTURED}:
            raise AdapterError(f"Pipeline desconhecido: {job.pipeline_mode}.")
        if requested == "auto":
            if self.trellis_cli.managed_configured or self.settings.trellis_cpp_command:
                return "trellis-cli", self.trellis_cli
            if self.settings.trellis_server_url:
                return "trellis-server", self.trellis_server
            raise AdapterError("TRELLIS não está configurado neste computador. Não houve fallback automático para demo.")
        if normalized == "trellis-server":
            return normalized, self.trellis_server
        if normalized == "trellis-cli":
            return normalized, self.trellis_cli
        if normalized == "demo":
            return normalized, self.demo
        if normalized is None:
            raise AdapterError(f"Adapter desconhecido: {job.adapter_requested}. Use trellis-cli, trellis-server ou demo.")
        raise AdapterError("TRELLIS aceita trellis-cli, trellis-server ou demo explícito.")

    def _set_running(self, job_id: str) -> bool:
        started = False

        def mutate(job: JobRecord) -> None:
            nonlocal started
            if job.status == JobStatus.CANCELLED or job.status != JobStatus.QUEUED:
                return
            now = utc_now()
            job.status = JobStatus.RUNNING
            job.stage = job.current_stage = "preflight"
            job.stage_started_at = now
            job.progress = max(job.progress, 5)
            job.progress_indeterminate = False
            job.queue_position = 0
            job.started_at = now
            job.events.append(JobEvent(at=now, stage="preflight", message="Verificando imagem e preparando a fila GPU serial.", progress=job.progress))
            job.events = job.events[-80:]
            started = True

        self.store.mutate_job(job_id, mutate)
        return started

    def _set_stage(
        self,
        job_id: str,
        *,
        stage: str,
        message: str,
        progress: int,
        tool: str | None = None,
        indeterminate: bool = False,
        estimate: EtaEstimate | None = None,
        adapter_started: bool = False,
    ) -> None:
        def mutate(job: JobRecord) -> None:
            if job.status == JobStatus.CANCELLED:
                return
            now = utc_now()
            job.stage = job.current_stage = stage
            job.stage_started_at = now
            job.progress = max(0, min(100, progress))
            job.current_tool = tool or job.current_tool
            if adapter_started and tool:
                job.adapter_used = tool
            job.progress_indeterminate = indeterminate
            if estimate is not None:
                job.estimated_total_seconds = estimate.seconds
                job.eta_seconds = estimate.seconds
                job.eta_confidence = estimate.confidence
            job.events.append(JobEvent(at=now, stage=stage, message=message, progress=job.progress, tool=job.current_tool, indeterminate=indeterminate))
            job.events = job.events[-80:]

        self.store.mutate_job(job_id, mutate)

    def _add_warning(self, job_id: str, warning: str, *, fallback: bool = False) -> None:
        def mutate(job: JobRecord) -> None:
            if warning not in job.warnings:
                job.warnings.append(warning)
            if fallback:
                job.fallback_reason = warning

        self.store.mutate_job(job_id, mutate)

    def _add_artifact(self, job_id: str, *, kind: str, label: str, path: Path, media_type: str = "model/gltf-binary") -> None:
        if not path.is_file():
            return

        def mutate(job: JobRecord) -> None:
            artifact = JobArtifact(kind=kind, label=label, filename=path.name, size=path.stat().st_size, url=f"/outputs/{job.id}/{path.name}", media_type=media_type)
            job.artifacts = [item for item in job.artifacts if not (item.kind == kind and item.filename == path.name)] + [artifact]

        self.store.mutate_job(job_id, mutate)

    def _is_cancelled(self, job_id: str) -> bool:
        return self.store.get_job(job_id).status == JobStatus.CANCELLED

    def _mark_cancelled_after_work(self, job_id: str) -> None:
        def mutate(job: JobRecord) -> None:
            if job.status != JobStatus.CANCELLED:
                return
            now = utc_now()
            job.stage = job.current_stage = "cancelled"
            job.stage_started_at = now
            job.progress_indeterminate = False
            job.eta_seconds = 0
            job.completed_at = job.completed_at or now
            job.events.append(JobEvent(at=now, stage="cancelled", message="Geração cancelada pelo usuário.", progress=job.progress))
            job.events = job.events[-80:]

        self.store.mutate_job(job_id, mutate)

    def _set_validation(self, job_id: str, result: AdapterResult, output_format: ExportFormat) -> None:
        report = validate_model(result.output_path, output_format)

        def mutate(job: JobRecord) -> None:
            job.validation = report
            for warning in report.warnings:
                if warning not in job.warnings:
                    job.warnings.append(warning)

        self.store.mutate_job(job_id, mutate)
        if not report.passed:
            detail = "; ".join(report.errors) or "auditoria do modelo falhou"
            raise AdapterError(f"Saída rejeitada pela auditoria: {detail}")

    def _mark_completed(self, job_id: str, result: AdapterResult, output_format: ExportFormat) -> None:
        output_path = result.output_path
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AdapterError("O adapter não retornou um arquivo de saída utilizável.")

        def mutate(job: JobRecord) -> None:
            if job.status == JobStatus.CANCELLED:
                return
            now = utc_now()
            job.status = JobStatus.COMPLETED
            job.stage = job.current_stage = "completed"
            job.stage_started_at = now
            job.progress = 100
            job.progress_indeterminate = False
            job.adapter_used = result.adapter_id
            job.current_tool = result.adapter_id
            job.eta_seconds = 0
            job.output = JobOutput(filename=output_path.name, format=output_format, size=output_path.stat().st_size, url=f"/outputs/{job.id}/{output_path.name}", download_url=f"/api/jobs/{job.id}/download")
            artifact = JobArtifact(kind="model", label="Modelo 3D validado" if job.validation and job.validation.passed else "Modelo 3D", filename=output_path.name, size=output_path.stat().st_size, url=f"/outputs/{job.id}/{output_path.name}", media_type="model/gltf-binary" if output_format == ExportFormat.GLB else "text/plain; charset=utf-8")
            job.artifacts = [item for item in job.artifacts if item.kind != "model"] + [artifact]
            for warning in result.warnings:
                if warning not in job.warnings:
                    job.warnings.append(warning)
            job.completed_at = now
            job.events.append(JobEvent(at=now, stage="completed", message="Modelo pronto e validado." if job.validation and job.validation.passed else "Modelo salvo localmente.", progress=100, tool=result.adapter_id))
            job.events = job.events[-80:]

        self.store.mutate_job(job_id, mutate)

    def _mark_failed(self, job_id: str, error: Exception) -> None:
        message = (str(error).strip() or type(error).__name__)[:1_500]

        def mutate(job: JobRecord) -> None:
            if job.status == JobStatus.CANCELLED:
                return
            now = utc_now()
            job.status = JobStatus.FAILED
            job.stage = job.current_stage = "failed"
            job.stage_started_at = now
            job.progress_indeterminate = False
            job.eta_seconds = 0
            job.error = message
            job.completed_at = now
            job.events.append(JobEvent(at=now, stage="failed", message=message, progress=job.progress, tool=job.current_tool))
            job.events = job.events[-80:]

        self.store.mutate_job(job_id, mutate)

    async def _ultrashape_log(self, job_id: str, message: str) -> None:
        self.store.add_log(job_id, "ultrashape", message)

    async def _faithc_log(self, job_id: str, message: str) -> None:
        self.store.add_log(job_id, "faithc", message)

    async def _trellis_log(self, job_id: str, source: str, message: str) -> None:
        """Expose real trellis-cli output and only use progress it emits."""

        self.store.add_log(job_id, f"trellis-{source}", message)
        step_match = re.search(r"(?i)(?:step\s*)?(\d{1,2})\s*/\s*12\b", message)
        if step_match and not self._is_cancelled(job_id):
            current_step = max(0, min(12, int(step_match.group(1))))
            job = self.store.get_job(job_id)
            progress = max(job.progress, min(90, 25 + round((current_step / 12) * 65)))
            self.store.add_event(
                job_id,
                "generating",
                f"TRELLIS — passo {current_step}/12: {message}",
                progress,
                tool="trellis-cli",
                indeterminate=False,
            )
            return
        match = re.search(r"(?<!\d)(100|[1-9]?\d)%(?!\d)", message)
        if not match or self._is_cancelled(job_id):
            return
        # The CLI's own percentage is a real sub-process measurement. Keep it
        # inside the generation band so validation/refinement remains visible.
        cli_progress = int(match.group(1))
        job = self.store.get_job(job_id)
        progress = max(job.progress, min(90, 25 + round(cli_progress * 0.65)))
        self.store.add_event(
            job_id,
            "generating",
            f"trellis-cli: {message}",
            progress,
            tool="trellis-cli",
            indeterminate=False,
        )

    async def _operation_log(self, job_id: str, source: str, message: str) -> None:
        self.store.add_log(job_id, f"operation-{source}", message)
        lowered = message.lower()
        if "voxel remesh" in lowered:
            self.store.add_event(job_id, "remeshing", message, 40, tool=self.operations.id, indeterminate=True)
            return
        if "transferindo uv" in lowered:
            self.store.add_event(job_id, "transferring_pbr", message, 65, tool=self.operations.id, indeterminate=True)
            return
        if "limite de triangulos" in lowered or "triangulos=" in lowered:
            self.store.add_event(job_id, "topology_ready", message, 86, tool=self.operations.id, indeterminate=False)
            return
        match = re.search(r"(?<!\d)(100|[1-9]?\d)%(?!\d)", message)
        if not match or self._is_cancelled(job_id):
            return
        job = self.store.get_job(job_id)
        progress = max(job.progress, min(90, 20 + round(int(match.group(1)) * 0.7)))
        self.store.add_event(
            job_id,
            "operating",
            f"Worker de operação: {message}",
            progress,
            tool=self.operations.id,
            indeterminate=False,
        )

    async def _run_operation(self, job: JobRecord) -> None:
        if not job.parent_job_id:
            raise AdapterError("Operação sem job pai associado.")
        parent = self.store.get_job(job.parent_job_id)
        if parent.status != JobStatus.COMPLETED or not parent.output:
            raise AdapterError("O job pai ainda não possui um GLB concluído para operar.")
        input_path = self.store.output_path(parent.id, parent.output.filename)
        if not input_path.is_file():
            raise AdapterError("GLB do job pai não está disponível no armazenamento local.")
        image_path = self.store.upload_path(parent.input.upload_id)
        output_path = self.store.output_path(job.id, f"{job.job_kind.value}.glb")
        parameters_path = self.store.output_path(job.id, "operation-parameters.json")
        parameters = {
            "kind": job.job_kind.value,
            "target_triangles": job.operation_target_triangles,
            "transform": job.operation_transform.model_dump(mode="json") if job.operation_transform else None,
            "parent_job_id": parent.id,
        }
        parameters_path.write_text(json.dumps(parameters, ensure_ascii=False), encoding="utf-8")
        self._add_artifact(
            job.id,
            kind="operation-parameters",
            label="Parâmetros da operação",
            path=parameters_path,
            media_type="application/json",
        )
        estimate = self.eta.estimate(mode=job.pipeline_mode, profile=job.profile, tool=self.operations.id)
        self._set_stage(
            job.id,
            stage="operating",
            message=f"Executando operação {job.job_kind.value} no GLB pai com worker local.",
            progress=20,
            tool=self.operations.id,
            indeterminate=True,
            estimate=estimate,
            adapter_started=True,
        )
        result = await self.operations.execute(
            kind=job.job_kind,
            input_path=input_path,
            output_path=output_path,
            parameters_path=parameters_path,
            image_path=image_path if job.job_kind == JobKind.RETEXTURE else None,
            on_output=lambda source, message: self._operation_log(job.id, source, message),
            is_cancelled=lambda: self._is_cancelled(job.id),
        )
        if self._is_cancelled(job.id):
            self._mark_cancelled_after_work(job.id)
            return
        # Remesh and simplify legitimately change topology, but they must not
        # turn a PBR parent into an untextured child while being labelled as a
        # successful PBR-preserving operation.  The Blender worker transfers
        # UV/material data for remesh; this audit is the final guardrail.
        source_report = validate_model(input_path, ExportFormat.GLB)
        result_report = validate_model(result.output_path, ExportFormat.GLB)
        pbr_preserving_kinds = {JobKind.SPLIT, JobKind.SIMPLIFY, JobKind.REMESH, JobKind.TRANSFORM}
        if (
            job.job_kind in pbr_preserving_kinds
            and source_report.passed
            and source_report.has_texture
            and (
                not result_report.passed
                or not result_report.has_uvs
                or not result_report.has_texture
            )
        ):
            raise AdapterError(
                "A operação alterou o GLB, mas não preservou UV e textura PBR do modelo atual; "
                "o resultado derivado foi rejeitado para evitar uma exportação enganosa."
            )
        self._set_stage(
            job.id,
            stage="validating",
            message="Validando GLB resultante da operação.",
            progress=92,
            tool=result.adapter_id,
        )
        self._set_validation(job.id, result, ExportFormat.GLB)
        self._mark_completed(job.id, result, ExportFormat.GLB)

    async def _run_faithc_geometry(self, job: JobRecord, result: AdapterResult) -> None:
        """Create a separately audited geometry artifact; never replace the PBR result."""

        if job.output_format != ExportFormat.GLB:
            self._add_warning(
                job.id,
                "FaithC ignorado: o artefato de geometria requer uma saída GLB. O resultado principal foi preservado.",
                fallback=True,
            )
            return

        configuration_issue = self.faithc.configuration_issue
        if configuration_issue:
            self._add_warning(
                job.id,
                f"FaithC solicitado, mas não configurado: {configuration_issue} O GLB principal permanece intacto.",
                fallback=True,
            )
            return

        if self._is_cancelled(job.id):
            return

        self._set_stage(
            job.id,
            stage="releasing_vram",
            message="Confirmando VRAM livre para o worker FaithC isolado.",
            progress=86,
            tool=self.faithc.id,
            indeterminate=True,
        )
        try:
            release = await self.gpu.release_for(self.faithc.id)
        except Exception as exc:
            release = None
            release_detail = f"falha ao confirmar liberação da GPU ({type(exc).__name__})"
        else:
            release_detail = release.detail
        if release is None or not release.released:
            self._add_warning(
                job.id,
                f"FaithC não iniciado: {release_detail} O GLB principal permanece intacto.",
                fallback=True,
            )
            return

        if self._is_cancelled(job.id):
            return

        try:
            probe = await self.faithc.probe(is_cancelled=lambda: self._is_cancelled(job.id))
        except AdapterError as exc:
            if self._is_cancelled(job.id):
                return
            self._add_warning(
                job.id,
                f"FaithC não iniciado: falha no probe isolado ({str(exc).strip() or type(exc).__name__}). O GLB principal permanece intacto.",
                fallback=True,
            )
            return
        if not probe.available:
            self._add_warning(
                job.id,
                f"FaithC solicitado, mas indisponível: {probe.detail} O GLB principal permanece intacto.",
                fallback=True,
            )
            return

        resolution = job.options.faithc_resolution
        output_path = self.store.output_path(job.id, f"model-faithc-geometry-{resolution}.glb")
        self._set_stage(
            job.id,
            stage="faithc_contouring",
            message=f"FaithC — reconstruindo um artefato geométrico em resolução {resolution}.",
            progress=87,
            tool=self.faithc.id,
            indeterminate=True,
        )
        try:
            refined = await self.faithc.refine(
                input_path=result.output_path,
                output_path=output_path,
                resolution=resolution,
                probe=probe,
                on_output=lambda message: self._faithc_log(job.id, message),
                is_cancelled=lambda: self._is_cancelled(job.id),
            )
            self.gpu.mark_finished(self.faithc.id, keeps_gpu_resident=False)
            if self._is_cancelled(job.id):
                return
            report = validate_model(refined.output_path, ExportFormat.GLB)
        except Exception as exc:
            self.gpu.mark_finished(self.faithc.id, keeps_gpu_resident=False)
            with contextlib.suppress(OSError):
                output_path.unlink(missing_ok=True)
            self._add_warning(
                job.id,
                f"FaithC solicitado, mas falhou: {str(exc).strip() or type(exc).__name__}. O GLB principal permanece intacto.",
                fallback=True,
            )
            return

        audit_path = self.store.output_path(job.id, "faithc-geometry-audit.json")
        try:
            audit_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "algorithm": "Faithful Contouring (FaithC)",
                        "artifact_kind": "geometry-only",
                        "source_filename": result.output_path.name,
                        "resolution": resolution,
                        "audit": report.model_dump(mode="json"),
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self._add_artifact(
                job.id,
                kind="faithc-audit",
                label="FaithC — auditoria do artefato geométrico",
                path=audit_path,
                media_type="application/json",
            )
        except Exception as exc:
            self._add_warning(
                job.id,
                f"FaithC gerou geometria, mas não foi possível gravar a auditoria: {type(exc).__name__}. O GLB principal permanece intacto.",
                fallback=True,
            )
            return

        if not report.passed or report.meshes < 1 or report.vertices < 1 or report.triangles < 1:
            detail = "; ".join(report.errors) or "o GLB não contém malha triangulada válida"
            self._add_warning(
                job.id,
                f"FaithC produziu um artefato que falhou na auditoria: {detail}. O GLB principal permanece intacto.",
                fallback=True,
            )
            return

        try:
            self._add_artifact(
                job.id,
                kind="faithc-geometry",
                label=f"FaithC — geometria sem promessa de UV/PBR ({resolution})",
                path=refined.output_path,
            )
        except Exception as exc:
            self._add_warning(
                job.id,
                f"FaithC validou o artefato, mas não foi possível registrá-lo: {type(exc).__name__}. O GLB principal permanece intacto.",
                fallback=True,
            )
            return
        self._add_warning(
            job.id,
            "FaithC gerou um artefato geométrico separado; a saída principal mantém UV e PBR originais quando presentes.",
        )

    async def _apply_generation_triangle_target(self, job: JobRecord, result: AdapterResult) -> AdapterResult:
        """Apply the requested ceiling to the generated GLB without rerunning 2D→3D.

        This preserves the original PBR GLB as an artifact and asks the
        calibrated Blender worker for an exact ceiling only when the generated
        result actually has more triangles. Smaller meshes are never subdivided.
        """

        target = job.options.target_triangles
        if not target or job.output_format != ExportFormat.GLB:
            return result
        source_report = validate_model(result.output_path, ExportFormat.GLB)
        if not source_report.passed or not source_report.triangles or source_report.triangles <= target:
            return result

        capability = await self.operations.capability()
        simplify = capability.get("by_operation", {}).get(JobKind.SIMPLIFY.value, {})
        if simplify.get("available") is not True:
            self._add_warning(
                job.id,
                "A malha densa foi preservada, mas o teto de triângulos não pôde ser aplicado: "
                + str(simplify.get("detail") or capability.get("detail") or "worker Blender indisponível"),
                fallback=True,
            )
            return result

        self._add_artifact(
            job.id,
            kind="dense-trellis-model",
            label=f"TRELLIS denso antes do teto de {target:,}",
            path=result.output_path,
        )
        parameters_path = self.store.output_path(job.id, "generation-triangle-target.json")
        parameters_path.write_text(
            json.dumps({"kind": "simplify", "target_triangles": target}, ensure_ascii=False),
            encoding="utf-8",
        )
        final_path = self.store.output_path(job.id, "model-target.glb")
        self._set_stage(
            job.id,
            stage="simplifying",
            message=f"Blender — reduzindo a malha densa ao teto real de {target:,} triângulos.",
            progress=89,
            tool=self.operations.id,
            indeterminate=True,
        )
        simplified = await self.operations.execute(
            kind=JobKind.SIMPLIFY,
            input_path=result.output_path,
            output_path=final_path,
            parameters_path=parameters_path,
            image_path=None,
            on_output=lambda source, message: self._operation_log(job.id, source, message),
            is_cancelled=lambda: self._is_cancelled(job.id),
        )
        final_report = validate_model(simplified.output_path, ExportFormat.GLB)
        preserves_pbr = (
            final_report.passed
            and final_report.triangles is not None
            and final_report.triangles <= int(target * 1.01)
            and (not source_report.has_texture or (final_report.has_uvs and final_report.has_texture))
        )
        if not preserves_pbr:
            self._add_warning(
                job.id,
                "A redução ao teto não passou na auditoria de triângulos/UV/PBR; mantendo o GLB denso original.",
                fallback=True,
            )
            return result
        return AdapterResult(
            output_path=simplified.output_path,
            adapter_id=f"{result.adapter_id}+blender-target",
            warnings=result.warnings + simplified.warnings,
            logs=result.logs + simplified.logs,
        )

    async def run(self, job_id: str) -> None:
        """Run a persisted job. The caller must be the one-worker GPU queue."""

        if not self._set_running(job_id):
            return
        try:
            job = self.store.get_job(job_id)
            if job.job_kind != JobKind.GENERATION:
                await self._run_operation(job)
                return
            input_path = self.store.upload_path(job.input.upload_id)
            if not input_path.is_file() or not input_path.stat().st_size:
                raise AdapterError("Imagem de entrada ausente ou vazia.")
            profile = get_profile(job.profile)
            try:
                resolve_trellis_quality(profile, job.options.trellis_quality_id, self.settings.engine_profile_path)
            except ValueError as exc:
                raise AdapterError(str(exc)) from exc
            adapter_id, adapter = self._requested_adapter(job)
            if adapter_id == "trellis-server":
                server_ready, server_detail = await self.gpu.ensure_trellis_server()
                if not server_ready:
                    raise AdapterError(server_detail)
            elif adapter_id == "trellis-cli":
                server_reachable, _ = await self.trellis_server._probe()
                if server_reachable:
                    release = await self.gpu.release_existing_trellis_server_for_cli()
                    self._set_stage(
                        job.id,
                        stage="releasing_vram",
                        message="Liberando trellis-server gerenciado antes de iniciar trellis-cli. " + release.detail,
                        progress=10,
                        tool=adapter_id,
                        indeterminate=True,
                    )
                    if not release.released:
                        raise AdapterError(
                            "trellis-cli não será iniciado enquanto trellis-server usar a GPU: " + release.detail
                        )
            estimate = self.eta.estimate(mode=job.pipeline_mode, profile=job.profile, tool=adapter_id)

            previous = self.gpu.active_tool
            if previous and previous != adapter_id:
                release = await self.gpu.release_for(adapter_id)
                self._set_stage(job.id, stage="releasing_vram", message=release.detail, progress=12, tool=adapter_id, indeterminate=True, estimate=estimate)
                if not release.released:
                    raise AdapterError("Não foi possível trocar de worker GPU com segurança: " + release.detail)
            else:
                self._set_stage(job.id, stage="releasing_vram", message="Reservando a fila GPU serial para a ferramenta selecionada.", progress=12, tool=adapter_id, indeterminate=True, estimate=estimate)
            if self._is_cancelled(job.id):
                self._mark_cancelled_after_work(job.id)
                return

            output_path = self.store.output_path(job.id, f"model.{job.output_format.value}")
            self._set_stage(job.id, stage="generating", message="TRELLIS — gerando malha, UV e materiais PBR." if adapter_id.startswith("trellis") else "Executando modo demo de diagnóstico (sem IA).", progress=25, tool=adapter_id, indeterminate=True, adapter_started=True)
            if adapter_id == "trellis-cli":
                result = await self.trellis_cli.generate(
                    image_path=input_path,
                    output_path=output_path,
                    profile=profile,
                    options=job.options,
                    output_format=job.output_format,
                    on_output=lambda source, message: self._trellis_log(job.id, source, message),
                    is_cancelled=lambda: self._is_cancelled(job.id),
                )
            else:
                result = await adapter.generate(image_path=input_path, output_path=output_path, profile=profile, options=job.options, output_format=job.output_format)
            self.gpu.mark_finished(adapter_id, keeps_gpu_resident=adapter_id == "trellis-server")
            if self._is_cancelled(job.id):
                self._mark_cancelled_after_work(job.id)
                return

            wants_ultrashape = job.options.ultrashape == UltraShapeMode.AUTO
            if job.options.ultrashape == UltraShapeMode.OFF:
                wants_ultrashape = False
            elif job.options.refine:
                wants_ultrashape = True

            if wants_ultrashape and adapter_id.startswith("trellis"):
                if job.output_format != ExportFormat.GLB:
                    self._add_warning(job.id, "UltraShape ignorado: o refinador aceita somente uma malha GLB.", fallback=True)
                else:
                    probe = await self.ultrashape.probe(profile)
                    if not probe.available:
                        self._add_warning(job.id, f"UltraShape automático indisponível: {probe.detail} Mantendo o GLB TRELLIS base.", fallback=True)
                    else:
                        self._set_stage(job.id, stage="releasing_vram", message="Liberando VRAM do TRELLIS antes de iniciar UltraShape.", progress=68, tool=self.ultrashape.id, indeterminate=True)
                        release = await self.gpu.release_for(self.ultrashape.id)
                        if not release.released:
                            self._add_warning(job.id, f"UltraShape não iniciado: {release.detail} Mantendo o GLB TRELLIS base.", fallback=True)
                        else:
                            self._add_artifact(job.id, kind="base-model", label="TRELLIS base — PBR antes do refinamento", path=result.output_path)
                            refined_path = self.store.output_path(job.id, "model-ultrashape.glb")
                            self._set_stage(job.id, stage="refining", message="UltraShape — refinando a geometria com worker local isolado.", progress=78, tool=self.ultrashape.id, indeterminate=True)
                            refined = await self.ultrashape.refine(image_path=input_path, input_path=result.output_path, output_path=refined_path, profile=profile, options=job.options, on_output=lambda message: self._ultrashape_log(job.id, message), is_cancelled=lambda: self._is_cancelled(job.id))
                            self.gpu.mark_finished(self.ultrashape.id, keeps_gpu_resident=False)
                            refined_report = validate_model(refined.output_path, ExportFormat.GLB)
                            self._add_artifact(job.id, kind="refined-geometry", label="UltraShape — geometria refinada (intermediário)", path=refined.output_path)
                            self._set_stage(job.id, stage="auditing_refined_materials", message="Auditando UV, texturas PBR e normal maps realmente presentes no resultado refinado.", progress=87, tool=self.ultrashape.id, indeterminate=True)
                            if refined_report.passed and refined_report.has_uvs and refined_report.has_texture:
                                result = AdapterResult(output_path=refined.output_path, adapter_id=f"{result.adapter_id}+{self.ultrashape.id}", warnings=result.warnings + refined.warnings, logs=result.logs + refined.logs)
                            else:
                                self._add_warning(job.id, "UltraShape concluiu a geometria, mas o GLB refinado não preservou UV/textura PBR. Nenhum normal map foi inventado; mantendo o GLB TRELLIS base validado.", fallback=True)
            elif wants_ultrashape and adapter_id == "demo":
                self._add_warning(job.id, "UltraShape não é aplicado ao modo demo de diagnóstico.")

            if job.options.faithc == FaithCMode.GEOMETRY:
                await self._run_faithc_geometry(job, result)

            if self._is_cancelled(job.id):
                self._mark_cancelled_after_work(job.id)
                return
            result = await self._apply_generation_triangle_target(job, result)
            if self._is_cancelled(job.id):
                self._mark_cancelled_after_work(job.id)
                return
            self._set_stage(job.id, stage="validating", message="Validando GLB, malha, UV, materiais PBR e mapas de textura.", progress=92, tool=result.adapter_id, indeterminate=False)
            self._set_validation(job.id, result, job.output_format)
            self._mark_completed(job.id, result, job.output_format)
        except Exception as exc:
            self._mark_failed(job_id, exc)
