from __future__ import annotations

"""Truthful capability bridge for derived GLB operations.

Each operation is independently advertised.  A configured executable alone is
not enough to claim that retexturing or PBR-safe remeshing exists.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..schemas import JobKind
from .base import AdapterError, AdapterResult
from .command import Cancelled, CommandOutput, run_command


@dataclass(frozen=True, slots=True)
class OperationCapability:
    available: bool
    detail: str
    preserves_pbr: bool = False

    def to_api(self) -> dict:
        return {"available": self.available, "detail": self.detail, "preserves_pbr": self.preserves_pbr}


class MeshOperationAdapter:
    id = "mesh-operation-worker"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._probe_cache: dict[str, OperationCapability] | None = None

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.mesh_operations_python
            and self.settings.mesh_operations_worker
            and self.settings.mesh_operations_python.is_file()
            and self.settings.mesh_operations_worker.is_file()
        )

    @property
    def _is_blender(self) -> bool:
        executable = self.settings.mesh_operations_python
        return bool(executable and executable.name.lower().startswith("blender"))

    def _unavailable(self, detail: str) -> dict[str, OperationCapability]:
        return {
            kind.value: OperationCapability(False, detail)
            for kind in (JobKind.SPLIT, JobKind.SIMPLIFY, JobKind.REMESH, JobKind.RETEXTURE, JobKind.TRANSFORM)
        }

    async def _probe_blender(self) -> dict[str, OperationCapability]:
        if self._probe_cache is not None:
            return self._probe_cache
        if not self.configured:
            return self._unavailable("Worker Blender não está configurado.")
        python = self.settings.mesh_operations_python
        worker = self.settings.mesh_operations_worker
        assert python is not None and worker is not None
        command = [str(python), "--background", "--factory-startup", "--python", str(worker), "--", "--probe"]
        try:
            logs = await run_command(command, 30, "probe do worker Blender")
        except AdapterError as exc:
            return self._unavailable(f"Blender/worker não confirmou disponibilidade: {str(exc)[:300]}")
        payload: dict | None = None
        for line in reversed(logs):
            text = line.split(": ", 1)[-1]
            if not text.startswith("FORGE3D_OPERATION_CAPS:"):
                continue
            try:
                candidate = json.loads(text.split(":", 1)[1])
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict):
                payload = candidate
                break
        if not payload:
            return self._unavailable("O worker Blender não retornou uma declaração de capacidades verificável.")
        raw = payload.get("operations")
        if not isinstance(raw, dict):
            return self._unavailable("O worker Blender retornou capacidades inválidas.")
        result: dict[str, OperationCapability] = {}
        for kind in (JobKind.SPLIT, JobKind.SIMPLIFY, JobKind.REMESH, JobKind.RETEXTURE, JobKind.TRANSFORM):
            item = raw.get(kind.value)
            if isinstance(item, dict):
                result[kind.value] = OperationCapability(
                    available=item.get("available") is True,
                    detail=str(item.get("detail") or "Sem detalhes.")[:500],
                    preserves_pbr=item.get("preserves_pbr") is True,
                )
            else:
                result[kind.value] = OperationCapability(False, "Worker não declarou esta operação.")
        self._probe_cache = result
        return result

    async def operation_capabilities(self) -> dict[str, OperationCapability]:
        if not self.configured:
            return self._unavailable(
                "Nenhum worker de operações configurado; a API não executará uma cópia disfarçada como simplificação, remesh ou retextura."
            )
        if self._is_blender:
            return await self._probe_blender()
        return self._unavailable(
            "Worker externo genérico não possui declaração verificável por operação. Configure o worker Blender Forge3D ou um adaptador com probe estruturado."
        )

    async def capability(self) -> dict:
        by_operation = await self.operation_capabilities()
        enabled = [name for name, item in by_operation.items() if item.available]
        detail = (
            "Operações disponíveis: " + ", ".join(enabled) + "."
            if enabled
            else next(iter(by_operation.values())).detail
        )
        return {
            "id": self.id,
            "label": "Worker local de operações de malha",
            "kind": "structured-external-worker",
            "configured": self.configured,
            "available": bool(enabled),
            "uses_gpu": False,
            # Kept for existing clients; ``by_operation`` is the source of
            # truth and prevents one working action from enabling all buttons.
            "operations": enabled,
            "by_operation": {name: item.to_api() for name, item in by_operation.items()},
            "contract": {
                "command": "Blender --background --python blender_worker.py -- <operation> --input <glb> --output <glb> --parameters <json>",
                "input": "GLB pai validado; nenhuma operação de malha inicia TRELLIS novamente",
                "output": "GLB derivado validado",
            },
            "fallback": "none",
            "detail": detail,
        }

    async def execute(
        self,
        *,
        kind: JobKind,
        input_path: Path,
        output_path: Path,
        parameters_path: Path,
        image_path: Path | None,
        on_output: CommandOutput | None = None,
        is_cancelled: Cancelled | None = None,
    ) -> AdapterResult:
        if kind == JobKind.GENERATION:
            raise AdapterError("O worker de operações não executa gerações iniciais.")
        capabilities = await self.operation_capabilities()
        operation = capabilities.get(kind.value)
        if not operation or not operation.available:
            raise AdapterError(f"Operação {kind.value} indisponível: {operation.detail if operation else 'não declarada pelo worker'}")
        if not input_path.is_file():
            raise AdapterError("GLB pai não encontrado para a operação solicitada.")
        if not parameters_path.is_file():
            raise AdapterError("Parâmetros estruturados da operação não foram preparados.")
        python = self.settings.mesh_operations_python
        worker = self.settings.mesh_operations_worker
        assert python is not None and worker is not None
        output_path.parent.mkdir(parents=True, exist_ok=True)
        worker_args = [kind.value, "--input", str(input_path), "--output", str(output_path), "--parameters", str(parameters_path)]
        command = [str(python), "--background", "--factory-startup", "--python", str(worker), "--", *worker_args]
        # Retexture is intentionally not implemented by the bundled worker.
        # If a future verified worker exposes it, this image is a reference for
        # material baking only; it must never be routed to a 2D->3D generator.
        if image_path is not None:
            command.extend(["--image", str(image_path)])
        logs = await run_command(
            command,
            self.settings.mesh_operations_timeout_seconds,
            f"operação {kind.value}",
            on_output=on_output,
            is_cancelled=is_cancelled,
        )
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AdapterError(f"Worker de operação {kind.value} terminou sem criar o GLB esperado.")
        if output_path.read_bytes()[:4] != b"glTF":
            raise AdapterError(f"Worker de operação {kind.value} criou um arquivo sem assinatura GLB.")
        return AdapterResult(output_path=output_path, adapter_id=f"{self.id}:{kind.value}", logs=logs)
