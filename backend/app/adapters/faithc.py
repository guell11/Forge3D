from __future__ import annotations

"""Opt-in Faithful Contouring worker integration.

FaithC reconstructs geometry only. Its Torch/CUDA extension stays in a
dedicated Python process and its output is never promoted over the source PBR
GLB by this adapter.
"""

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from .base import AdapterError, AdapterResult
from .command import run_command

WorkerOutput = Callable[[str], Awaitable[None] | None]
Cancelled = Callable[[], bool]
_PROBE_PREFIX = "FORGE3D_FAITHC_PROBE:"
_RESOLUTIONS = (128, 256, 512)


@dataclass(frozen=True, slots=True)
class FaithCProbe:
    configured: bool
    runtime_ready: bool
    available: bool
    detail: str
    probe_state: str = "not-calibrated"
    torch_version: str | None = None
    cuda_device: str | None = None


class FaithCRefiner:
    """Run the upstream FCT encoder/decoder in an isolated CUDA process."""

    id = "faithc"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._probe_cache: FaithCProbe | None = None
        self._last_probe: FaithCProbe | None = None

    def _worker_path(self) -> Path:
        return self.settings.faithc_worker or Path(__file__).resolve().parents[3] / "scripts" / "faithc_worker.py"

    @property
    def configured(self) -> bool:
        return self._base_detail() is None

    @property
    def configuration_issue(self) -> str | None:
        """Return configuration problems without starting Python or CUDA."""

        return self._base_detail()

    def _base_detail(self) -> str | None:
        if not self.settings.faithc_enabled:
            return "FaithC está desligado. Defina FAITHC_ENABLED=1 para habilitar o refinamento opcional."
        python = self.settings.faithc_python
        if not python or not python.is_file():
            return "FAITHC_PYTHON não aponta para um Python válido do ambiente FaithC isolado."
        worker = self._worker_path()
        if not worker.is_file():
            return "Worker scripts/faithc_worker.py não encontrado."
        return None

    async def probe(
        self,
        *,
        refresh: bool = False,
        is_cancelled: Cancelled | None = None,
    ) -> FaithCProbe:
        if self._probe_cache is not None and not refresh:
            return self._probe_cache

        issue = self._base_detail()
        if issue:
            state = "disabled" if not self.settings.faithc_enabled else "unconfigured"
            result = FaithCProbe(False, False, False, issue, probe_state=state)
            self._last_probe = result
            return result

        payload: dict = {}

        async def capture_probe(_source: str, message: str) -> None:
            if not message.startswith(_PROBE_PREFIX):
                return
            try:
                parsed = json.loads(message[len(_PROBE_PREFIX):])
            except json.JSONDecodeError:
                payload.clear()
                return
            payload.clear()
            if isinstance(parsed, dict):
                payload.update(parsed)

        try:
            await run_command(
                self._worker_command("probe"),
                max(1, self.settings.faithc_probe_timeout_seconds),
                "FaithC probe",
                on_output=capture_probe,
                is_cancelled=is_cancelled,
            )
        except AdapterError as exc:
            if is_cancelled and is_cancelled():
                raise
            detail = str(payload.get("detail") or str(exc).strip() or "sem detalhes")[:700]
            result = FaithCProbe(True, False, False, f"Probe real de CUDA/imports FaithC falhou: {detail}", probe_state="failed")
            self._last_probe = result
            return result
        if payload.get("ok") is not True:
            detail = str(payload.get("detail") or "o worker não confirmou CUDA e imports")[:700]
            result = FaithCProbe(True, False, False, f"Probe real de CUDA/imports FaithC falhou: {detail}", probe_state="failed")
        else:
            result = FaithCProbe(
                True,
                True,
                True,
                "FaithC, Atom3d, PyTorch e dispositivo CUDA passaram no probe isolado.",
                probe_state="ready",
                torch_version=str(payload.get("torch_version") or "desconhecida"),
                cuda_device=str(payload.get("cuda_device") or "NVIDIA CUDA"),
            )
        self._last_probe = result
        if result.available:
            self._probe_cache = result
        return result

    async def capability(self, profile=None) -> dict:
        issue = self._base_detail()
        if issue:
            state = "disabled" if not self.settings.faithc_enabled else "unconfigured"
            probe = FaithCProbe(False, False, False, issue, probe_state=state)
        elif self._probe_cache is not None:
            probe = self._probe_cache
        elif self._last_probe is not None:
            probe = self._last_probe
        else:
            probe = FaithCProbe(
                True,
                False,
                False,
                "Configuração detectada; CUDA será validada apenas dentro da fila, depois da liberação de VRAM.",
                probe_state="not-calibrated",
            )
        return {
            "id": self.id,
            "label": "FaithC — Faithful Contouring",
            "kind": "isolated-cuda-worker",
            "configured": probe.configured,
            "runtime_ready": probe.runtime_ready,
            "available": probe.available,
            "probe_state": probe.probe_state,
            "uses_gpu": True,
            "outputs": ["glb", "geometry-only"],
            "mode": "geometry",
            "resolutions": list(_RESOLUTIONS),
            "recommended_resolution": 256,
            "torch_version": probe.torch_version,
            "cuda_device": probe.cuda_device,
            "detail": probe.detail,
            "limitations": [
                "FaithC reconstrói geometria a partir de FCTs; não gera textura, UV ou normal maps.",
                "O GLB FaithC é um artefato separado; o GLB principal mantém o resultado TRELLIS/PBR.",
                "Resolução maior aumenta custo de memória e não cria detalhes ausentes na malha de entrada.",
            ],
        }

    def _worker_command(self, action: str, **options: str | int) -> list[str]:
        python = self.settings.faithc_python
        worker = self._worker_path()
        if not python or not worker:
            raise AdapterError("FaithC requer FAITHC_PYTHON e o worker estruturado scripts/faithc_worker.py.")
        command = [str(python), str(worker), action]
        for name, value in options.items():
            command.extend([f"--{name.replace('_', '-')}", str(value)])
        return command

    async def refine(
        self,
        *,
        input_path: Path,
        output_path: Path,
        resolution: int,
        probe: FaithCProbe,
        on_output: WorkerOutput | None = None,
        is_cancelled: Cancelled | None = None,
    ) -> AdapterResult:
        if resolution not in _RESOLUTIONS:
            raise AdapterError("A resolução FaithC aceita somente 128, 256 ou 512.")
        if input_path.suffix.lower() != ".glb" or not input_path.is_file():
            raise AdapterError("FaithC requer um GLB existente como malha de entrada.")
        if not probe.available:
            raise AdapterError(f"FaithC requer um probe de CUDA bem-sucedido após a liberação da GPU: {probe.detail}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            logs = await run_command(
                self._worker_command(
                    "refine",
                    mesh=str(input_path),
                    output=str(output_path),
                    resolution=resolution,
                ),
                max(1, self.settings.faithc_timeout_seconds),
                "FaithC",
                on_output=(lambda _source, message: on_output(message)) if on_output else None,
                is_cancelled=is_cancelled,
            )
        except Exception:
            output_path.unlink(missing_ok=True)
            output_path.with_suffix(output_path.suffix + ".part").unlink(missing_ok=True)
            raise

        if not output_path.is_file() or output_path.stat().st_size < 20:
            output_path.unlink(missing_ok=True)
            raise AdapterError("FaithC terminou sem criar o GLB geométrico esperado.")
        if output_path.read_bytes()[:4] != b"glTF":
            output_path.unlink(missing_ok=True)
            raise AdapterError("FaithC criou um arquivo sem assinatura GLB válida.")
        return AdapterResult(output_path=output_path, adapter_id=self.id, logs=logs)
