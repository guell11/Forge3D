from __future__ import annotations

"""Truthful ownership coordination for local GPU workers.

The API has a serial queue, but a long-lived trellis.cpp HTTP process can keep
weights resident after a request finishes.  UltraShape is allowed to start only
after that process is actually released through the managed PID record created
by the launcher.  A completed one-shot CLI process is already released.
"""

import asyncio
import contextlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import Settings


@dataclass(frozen=True, slots=True)
class GPUReleaseOutcome:
    released: bool
    previous_tool: str | None
    detail: str


class GPUOwnershipSupervisor:
    """Coordinates model residency without pretending to control foreign PIDs."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._active_tool: str | None = None
        self._persistent = False

    @property
    def active_tool(self) -> str | None:
        return self._active_tool

    def mark_finished(self, tool: str, *, keeps_gpu_resident: bool) -> None:
        self._active_tool = tool if keeps_gpu_resident else None
        self._persistent = keeps_gpu_resident

    async def release_for(self, next_tool: str) -> GPUReleaseOutcome:
        previous = self._active_tool
        if previous is None:
            return GPUReleaseOutcome(True, None, f"GPU livre para {next_tool}.")
        if previous == next_tool and self._persistent:
            return GPUReleaseOutcome(False, previous, f"{previous} ainda é o dono ativo da GPU.")
        if not self._persistent:
            self._active_tool = None
            return GPUReleaseOutcome(True, previous, f"{previous} é um worker de execução única e já terminou.")

        if previous == "trellis-server":
            released, detail = await self._release_managed_trellis()
            if released:
                self._active_tool = None
                self._persistent = False
            return GPUReleaseOutcome(released, previous, detail)

        return GPUReleaseOutcome(False, previous, f"Não há liberação confirmável para o worker persistente {previous}.")

    async def release_existing_trellis_server_for_cli(self) -> GPUReleaseOutcome:
        """Release a launcher-managed server before a one-shot CLI invocation.

        The launcher may have started trellis-server before the API process,
        so it is not present in ``_active_tool`` yet. We still must never
        launch a second TRELLIS model on an 8 GB GPU without a verified stop.
        """

        self._active_tool = "trellis-server"
        self._persistent = True
        return await self.release_for("trellis-cli")

    async def ensure_trellis_server(self) -> tuple[bool, str]:
        """Start a trusted trellis.cpp server again after an UltraShape pass.

        The launcher and this supervisor use the same validated PID-record
        format. If a server is already listening the method does not touch it;
        a subsequent UltraShape pass still requires a managed PID record.
        """

        if await self._port_open():
            self._active_tool = "trellis-server"
            self._persistent = True
            return True, "trellis.cpp já está acessível localmente."
        binary = self.settings.trellis_server_bin
        models = self.settings.trellis_models_dir
        pid_file = self.settings.trellis_managed_pid_file
        if not self.settings.trellis_autostart:
            return False, "TRELLIS_AUTOSTART está desativado e o servidor não está em execução."
        if not binary or not models or not binary.is_file() or not models.is_dir():
            return False, "Não há binário/modelos TRELLIS válidos para reiniciar o servidor após o UltraShape."
        if not pid_file:
            return False, "TRELLIS_MANAGED_PID_FILE não foi configurado; não é seguro reiniciar um servidor que depois não poderá ser liberado."
        command = [
            str(binary),
            "--models",
            str(models),
            "--port",
            str(self.settings.trellis_server_port),
            "--res",
            str(self.settings.trellis_default_resolution),
            "--atlas",
            str(self.settings.trellis_default_atlas),
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(binary.parent),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError as exc:
            return False, f"Não foi possível iniciar trellis.cpp: {type(exc).__name__}."
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        record = {"pid": process.pid, "expected_bin": str(binary.resolve())}
        temp = pid_file.with_suffix(pid_file.suffix + ".tmp")
        temp.write_text(json.dumps(record), encoding="utf-8")
        temp.replace(pid_file)
        for _ in range(50):
            if await self._port_open():
                self._active_tool = "trellis-server"
                self._persistent = True
                return True, "trellis.cpp reiniciado como processo gerenciado."
            if process.returncode is not None:
                pid_file.unlink(missing_ok=True)
                return False, f"trellis.cpp encerrou ao reiniciar (código {process.returncode})."
            await asyncio.sleep(0.2)
        process.terminate()
        with contextlib.suppress(ProcessLookupError):
            await process.wait()
        pid_file.unlink(missing_ok=True)
        return False, "trellis.cpp não abriu a porta local após 10 segundos."

    async def _port_open(self) -> bool:
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection("127.0.0.1", self.settings.trellis_server_port), timeout=0.4
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (OSError, TimeoutError):
            return False

    async def _release_managed_trellis(self) -> tuple[bool, str]:
        """Ask only a launcher-managed trellis.cpp server to terminate.

        No arbitrary command is accepted. The PowerShell helper validates the
        PID's executable path before stopping it, so an old PID file cannot
        cause the API to terminate an unrelated process.
        """

        script = self.settings.trellis_release_script
        pid_file = self.settings.trellis_managed_pid_file
        binary = self.settings.trellis_server_bin
        if script and pid_file and binary and script.is_file() and binary.is_file():
            if not pid_file.is_file():
                return False, "O servidor TRELLIS em execução não possui um PID gerenciado; a liberação de VRAM não pode ser comprovada."
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if not powershell:
                return False, "PowerShell não encontrado para liberar o trellis.cpp gerenciado."
            command = [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-PidFile",
                str(pid_file),
                "-ExpectedBin",
                str(binary),
            ]
            try:
                process = await asyncio.create_subprocess_exec(
                    *command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=35)
            except (OSError, TimeoutError) as exc:
                return False, f"Falha ao liberar trellis.cpp gerenciado: {type(exc).__name__}."
            if process.returncode == 0:
                detail = (stdout.decode("utf-8", errors="replace").strip() or "trellis.cpp gerenciado liberado.")[:300]
                return True, detail
            detail = (stderr.decode("utf-8", errors="replace").strip() or stdout.decode("utf-8", errors="replace").strip() or "sem detalhes")[:300]
            return False, f"A liberação do trellis.cpp falhou: {detail}"

        if self.settings.trellis_release_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    response = await client.post(self.settings.trellis_release_url)
                if response.is_success:
                    return True, "Endpoint local de liberação TRELLIS confirmou a VRAM liberada."
                return False, f"Endpoint de liberação TRELLIS respondeu HTTP {response.status_code}."
            except httpx.HTTPError as exc:
                return False, f"Endpoint de liberação TRELLIS indisponível: {type(exc).__name__}."

        return (
            False,
            "O trellis.cpp em servidor não possui PID/endpoint de liberação confirmado; "
            "o UltraShape não será iniciado para evitar dois modelos na VRAM.",
        )

    def capability(self) -> dict:
        script = self.settings.trellis_release_script
        pid_file = self.settings.trellis_managed_pid_file
        binary = self.settings.trellis_server_bin
        managed_release_ready = bool(script and pid_file and binary and script.is_file() and binary.is_file())
        return {
            "kind": "serial-gpu-ownership-supervisor",
            "active_tool": self._active_tool,
            "managed_trellis_release": managed_release_ready,
            "release_strategy": "managed-pid-script" if managed_release_ready else "none-confirmed",
            "managed_trellis_restart": bool(
                self.settings.trellis_autostart
                and binary
                and self.settings.trellis_models_dir
                and pid_file
                and binary.is_file()
                and self.settings.trellis_models_dir.is_dir()
            ),
            "detail": (
                "O servidor trellis.cpp é encerrado por um PID validado antes do UltraShape."
                if managed_release_ready
                else "A fila é serial, mas não há uma liberação confirmável do servidor TRELLIS para trocar de modelo."
            ),
        }
