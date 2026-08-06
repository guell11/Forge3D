from __future__ import annotations

"""Structured local UltraShape integration.

UltraShape is geometry-only upstream. This adapter intentionally runs the
official ``infer_dit_refine.py`` through a short-lived isolated Python worker;
it neither imports torch into the API process nor accepts arbitrary command
templates from an environment variable.
"""

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from ..config import Settings
from ..profiles import HardwareProfile, ProfileId
from ..schemas import GenerationOptions, UltraShapeQuality
from .base import AdapterError, AdapterResult

WorkerOutput = Callable[[str], Awaitable[None] | None]
Cancelled = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class UltraShapeProbe:
    configured: bool
    runtime_ready: bool
    calibrated: bool
    available: bool
    detail: str
    modes: tuple[str, ...]
    checkpoint_sha256: str | None = None


class UltraShapeRefiner:
    id = "ultrashape"
    _probe_cache: UltraShapeProbe | None = None

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(
            self.settings.ultrashape_home
            and self.settings.ultrashape_python
            and self.settings.ultrashape_checkpoint
            and self._worker_path()
        )

    def _worker_path(self) -> Path | None:
        if self.settings.ultrashape_worker:
            return self.settings.ultrashape_worker
        return Path(__file__).resolve().parents[3] / "scripts" / "ultrashape_worker.py"

    def _base_checks(self) -> list[str]:
        issues: list[str] = []
        if not self.settings.ultrashape_enabled:
            issues.append("UltraShape foi desabilitado pelo instalador deste perfil.")
        source = self.settings.ultrashape_home
        python = self.settings.ultrashape_python
        checkpoint = self.settings.ultrashape_checkpoint
        worker = self._worker_path()
        if not source or not source.is_dir():
            issues.append("ULTRASHAPE_HOME ausente ou inválido.")
        elif not (source / "scripts" / "infer_dit_refine.py").is_file():
            issues.append("A fonte UltraShape não contém scripts/infer_dit_refine.py.")
        if not python or not python.is_file():
            issues.append("ULTRASHAPE_PYTHON ausente ou inválido.")
        if not checkpoint or not checkpoint.is_file() or checkpoint.stat().st_size == 0:
            issues.append("ULTRASHAPE_CKPT ausente, vazio ou inválido.")
        if not worker or not worker.is_file():
            issues.append("ULTRASHAPE_WORKER ausente ou inválido.")
        return issues

    @staticmethod
    def _mode_for(profile: HardwareProfile, requested: UltraShapeQuality | None) -> UltraShapeQuality | None:
        if profile.id == ProfileId.GB6:
            return None
        if requested == UltraShapeQuality.FULL and profile.id != ProfileId.GB16:
            return None
        if requested is not None:
            return requested
        return UltraShapeQuality.FULL if profile.id == ProfileId.GB16 else UltraShapeQuality.ECONOMY

    def _read_calibration(self) -> tuple[bool, str, tuple[str, ...], str | None]:
        path = self.settings.ultrashape_probe_path or self.settings.ultrashape_install_status
        if not path or not path.is_file():
            return False, "Nenhuma calibração UltraShape verificada foi encontrada.", (), None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False, "O arquivo de calibração UltraShape está ilegível.", (), None
        if not isinstance(payload, dict) or payload.get("passed") is not True:
            reason = payload.get("reason") if isinstance(payload, dict) else None
            return False, f"A calibração UltraShape não foi aprovada{': ' + str(reason) if reason else ''}.", (), None
        modes = payload.get("modes", ["economy"])
        valid_modes = tuple(mode for mode in modes if mode in {"economy", "full"}) if isinstance(modes, list) else ()
        if not valid_modes:
            return False, "A calibração UltraShape não declarou nenhum modo seguro.", (), None
        expected_hash = payload.get("checkpoint_sha256")
        if expected_hash is not None and not isinstance(expected_hash, str):
            return False, "A calibração UltraShape contém checksum inválido.", (), None
        return True, "Calibração UltraShape aprovada localmente.", valid_modes, expected_hash

    async def probe(self, profile: HardwareProfile | None = None, *, refresh: bool = False) -> UltraShapeProbe:
        if self._probe_cache is not None and not refresh:
            return self._apply_profile_limit(self._probe_cache, profile)

        issues = self._base_checks()
        if issues:
            probe = UltraShapeProbe(False, False, False, False, " ".join(issues), ())
            self._probe_cache = probe
            return self._apply_profile_limit(probe, profile)

        runtime_ready, runtime_detail = await self._run_runtime_probe()
        calibrated, calibration_detail, modes, expected_hash = self._read_calibration()
        checkpoint_hash: str | None = None
        if calibrated and expected_hash:
            checkpoint_hash = _sha256(self.settings.ultrashape_checkpoint)
            if checkpoint_hash != expected_hash.lower():
                calibrated = False
                calibration_detail = "O checksum do checkpoint mudou desde a calibração UltraShape."
                modes = ()
        available = runtime_ready and calibrated
        detail = runtime_detail if not runtime_ready else calibration_detail
        probe = UltraShapeProbe(True, runtime_ready, calibrated, available, detail, modes, checkpoint_hash)
        self._probe_cache = probe
        return self._apply_profile_limit(probe, profile)

    def _apply_profile_limit(self, probe: UltraShapeProbe, profile: HardwareProfile | None) -> UltraShapeProbe:
        if profile is None:
            return probe
        if not probe.available:
            return probe
        allowed = [mode for mode in probe.modes if self._mode_for(profile, UltraShapeQuality(mode)) is not None]
        if profile.id == ProfileId.GB6:
            return UltraShapeProbe(
                probe.configured,
                probe.runtime_ready,
                probe.calibrated,
                False,
                "UltraShape está desabilitado no perfil de 6 GB para evitar OOM.",
                (),
                probe.checkpoint_sha256,
            )
        if not allowed:
            return UltraShapeProbe(
                probe.configured,
                probe.runtime_ready,
                probe.calibrated,
                False,
                "A calibração UltraShape não aprovou um modo seguro para este perfil.",
                (),
                probe.checkpoint_sha256,
            )
        return UltraShapeProbe(
            probe.configured,
            probe.runtime_ready,
            probe.calibrated,
            probe.available,
            probe.detail,
            tuple(allowed),
            probe.checkpoint_sha256,
        )

    async def capability(self, profile: HardwareProfile | None = None) -> dict:
        probe = await self.probe(profile)
        return {
            "id": self.id,
            "label": "UltraShape — refinamento geométrico local",
            "kind": "isolated-windows-worker",
            "configured": probe.configured,
            "runtime_ready": probe.runtime_ready,
            "calibrated": probe.calibrated,
            "available": probe.available,
            "outputs": ["glb"],
            "uses_gpu": True,
            "modes": list(probe.modes),
            "checkpoint_sha256": probe.checkpoint_sha256,
            "detail": probe.detail,
            "limitations": [
                "UltraShape refina geometria; não cria texturas ou normal maps.",
                "Um GLB refinado sem UV/PBR não substitui o export TRELLIS texturizado.",
            ],
        }

    async def _run_runtime_probe(self) -> tuple[bool, str]:
        """Run the isolated worker's lightweight CUDA/import check."""

        command = self._worker_command("probe")
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
        except (OSError, TimeoutError) as exc:
            return False, f"Não foi possível executar a prova UltraShape: {type(exc).__name__}."
        messages = _worker_messages(stdout, stderr)
        status = _worker_json(messages)
        if process.returncode != 0:
            reason = status.get("reason") if status else _tail(messages)
            return False, f"A prova UltraShape falhou: {reason or 'sem detalhes'}"
        if not status or status.get("ok") is not True:
            return False, f"A prova UltraShape não confirmou CUDA/imports: {status.get('reason') if status else _tail(messages) or 'sem detalhes'}"
        return True, "Runtime UltraShape, CUDA e imports verificados no ambiente isolado."

    def _worker_command(self, action: str, **extra: str | int | bool) -> list[str]:
        python = self.settings.ultrashape_python
        worker = self._worker_path()
        source = self.settings.ultrashape_home
        checkpoint = self.settings.ultrashape_checkpoint
        if not python or not worker or not source or not checkpoint:
            raise AdapterError("UltraShape não está configurado com paths estruturados.")
        command = [
            str(python),
            str(worker),
            action,
            "--source",
            str(source),
            "--checkpoint",
            str(checkpoint),
        ]
        for key, value in extra.items():
            flag = "--" + key.replace("_", "-")
            if isinstance(value, bool):
                if value:
                    command.append(flag)
            else:
                command.extend([flag, str(value)])
        return command

    async def refine(
        self,
        *,
        image_path: Path,
        input_path: Path,
        output_path: Path,
        profile: HardwareProfile,
        options: GenerationOptions,
        on_output: WorkerOutput | None = None,
        is_cancelled: Cancelled | None = None,
    ) -> AdapterResult:
        requested = self._mode_for(profile, options.ultrashape_quality)
        probe = await self.probe(profile)
        if not requested or requested.value not in probe.modes or not probe.available:
            raise AdapterError(f"UltraShape indisponível: {probe.detail}")
        if input_path.suffix.lower() not in {".glb", ".obj"}:
            raise AdapterError("UltraShape requer uma malha base GLB ou OBJ.")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        worker_options: dict[str, str | int | float | Path] = {
            "image": image_path,
            "mesh": input_path,
            "output": output_path,
            "mode": requested.value,
            "seed": options.seed if options.seed is not None else profile.default_seed,
        }
        optional_controls = {
            "steps": options.ultrashape_steps,
            "num_latents": options.ultrashape_num_latents,
            "chunk_size": options.ultrashape_chunk_size,
            "octree_res": options.ultrashape_octree_resolution,
            "scale": options.ultrashape_scale,
        }
        worker_options.update({key: value for key, value in optional_controls.items() if value is not None})
        if options.ultrashape_low_vram is not None:
            worker_options["low_vram_override"] = "1" if options.ultrashape_low_vram else "0"
        command = self._worker_command("refine", **worker_options)
        lines = await self._run_worker(command, on_output=on_output, is_cancelled=is_cancelled)
        if not output_path.is_file() or output_path.stat().st_size == 0:
            raise AdapterError("UltraShape terminou sem criar o GLB refinado esperado.")
        if output_path.read_bytes()[:4] != b"glTF":
            raise AdapterError("UltraShape criou um arquivo sem assinatura GLB válida.")
        return AdapterResult(output_path=output_path, adapter_id=self.id, logs=lines[-40:])

    async def _run_worker(
        self,
        command: list[str],
        *,
        on_output: WorkerOutput | None,
        is_cancelled: Cancelled | None,
    ) -> list[str]:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as exc:
            raise AdapterError(f"Não foi possível iniciar o worker UltraShape: {type(exc).__name__}.") from exc

        lines: list[str] = []

        async def drain(stream: asyncio.StreamReader | None, source: str) -> None:
            if stream is None:
                return
            while line := await stream.readline():
                message = line.decode("utf-8", errors="replace").replace("\x00", " ").strip()[:500]
                if not message:
                    continue
                lines.append(f"{source}: {message}")
                del lines[:-80]
                if on_output:
                    value = on_output(message)
                    if hasattr(value, "__await__"):
                        await value

        stdout_task = asyncio.create_task(drain(process.stdout, "stdout"))
        stderr_task = asyncio.create_task(drain(process.stderr, "stderr"))
        try:
            elapsed = 0.0
            while process.returncode is None:
                if is_cancelled and is_cancelled():
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=10)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                    raise AdapterError("UltraShape cancelado pelo usuário.")
                try:
                    await asyncio.wait_for(process.wait(), timeout=0.25)
                except TimeoutError:
                    elapsed += 0.25
                    if elapsed >= self.settings.ultrashape_timeout_seconds:
                        process.kill()
                        await process.wait()
                        raise AdapterError(f"UltraShape excedeu o limite de {self.settings.ultrashape_timeout_seconds}s.")
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        except Exception:
            if process.returncode is None:
                process.kill()
                await process.wait()
            await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        if process.returncode:
            raise AdapterError(f"UltraShape terminou com código {process.returncode}: {_tail(lines) or 'sem detalhes'}")
        return lines


def _sha256(path: Path | None) -> str | None:
    if not path or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _worker_messages(stdout: bytes, stderr: bytes) -> list[str]:
    return [line.strip() for line in (stdout + b"\n" + stderr).decode("utf-8", errors="replace").splitlines() if line.strip()]


def _worker_json(lines: list[str]) -> dict:
    for line in reversed(lines):
        if line.startswith("FORGE3D_ULTRASHAPE_PROBE:"):
            try:
                payload = json.loads(line.split(":", 1)[1])
            except json.JSONDecodeError:
                continue
            return payload if isinstance(payload, dict) else {}
    return {}


def _tail(lines: list[str]) -> str:
    return " ".join(lines[-6:])[:700]
