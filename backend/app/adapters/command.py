from __future__ import annotations

import asyncio
import inspect
import os
import shlex
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from .base import AdapterError


def command_is_resolvable(command_template: str | None) -> bool:
    if not command_template:
        return False
    try:
        parts = shlex.split(command_template, posix=os.name != "nt")
    except ValueError:
        return False
    if not parts:
        return False
    executable = parts[0].strip('"')
    return bool(shutil.which(executable) or Path(executable).is_file())


def render_command(template: str, **values: object) -> list[str]:
    """Render a local-operator command without invoking a shell.

    The template is intentionally constrained to whitespace-separated command
    tokens plus Python ``str.format`` placeholders. This prevents any filename
    from being interpreted as shell code.
    """

    try:
        tokens = shlex.split(template, posix=os.name != "nt")
    except ValueError as exc:
        raise AdapterError(f"Comando externo inválido: {exc}") from exc
    if not tokens:
        raise AdapterError("Comando externo vazio.")
    try:
        rendered = [token.format(**values) for token in tokens]
    except KeyError as exc:
        raise AdapterError(f"Placeholder não suportado no comando externo: {exc}") from exc
    # ``shlex.split(..., posix=False)`` retains enclosing quotes on Windows.
    # Passing those quotes to create_subprocess_exec makes an executable under
    # a path with spaces fail to resolve (e.g. C:\\...\\3d engine\\...).
    return [_strip_enclosing_quotes(token) for token in rendered]


def _strip_enclosing_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}:
        return token[1:-1]
    return token


CommandOutput = Callable[[str, str], Awaitable[None] | None]
Cancelled = Callable[[], bool]


async def run_command(
    command: list[str],
    timeout_seconds: int,
    label: str,
    *,
    on_output: CommandOutput | None = None,
    is_cancelled: Cancelled | None = None,
) -> list[str]:
    """Run a local worker without a shell and return a short output tail.

    Worker output is streamed as it arrives.  Consumers can turn meaningful
    tool messages into UI events while commands that provide no percentage stay
    explicitly indeterminate rather than receiving made-up progress.
    """
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise AdapterError(f"Executável de {label} não encontrado: {command[0]}") from exc
    output_tail: list[str] = []

    async def drain(stream: asyncio.StreamReader | None, source: str) -> None:
        if stream is None:
            return
        while line := await stream.readline():
            text = _safe_output_line(line)
            if not text:
                continue
            output_tail.append(f"{source}: {text}")
            del output_tail[:-40]
            if on_output is not None:
                try:
                    value = on_output(source, text)
                    if inspect.isawaitable(value):
                        await value
                except Exception:
                    # A dashboard/log callback must never break a generation.
                    pass

    stdout_task = asyncio.create_task(drain(process.stdout, "stdout"))
    stderr_task = asyncio.create_task(drain(process.stderr, "stderr"))
    try:
        elapsed = 0.0
        while process.returncode is None:
            if is_cancelled and is_cancelled():
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=8)
                except TimeoutError:
                    process.kill()
                    await process.wait()
                raise AdapterError(f"{label} cancelado pelo usuário.")
            try:
                await asyncio.wait_for(process.wait(), timeout=0.25)
            except TimeoutError:
                elapsed += 0.25
                if elapsed >= timeout_seconds:
                    process.kill()
                    await process.wait()
                    raise AdapterError(f"{label} excedeu o limite de {timeout_seconds}s.")
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.wait()
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
        raise
    if process.returncode:
        detail = " ".join(output_tail[-8:])[:800] if output_tail else "sem saída de erro"
        raise AdapterError(f"{label} terminou com código {process.returncode}: {detail}")
    return output_tail


def _safe_output_line(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    # Keep output one-line and bounded before it ever reaches persisted job
    # metadata. ANSI/control sequences are not useful in a browser UI.
    text = "".join(character for character in text if character >= " " or character == "\t")
    # Structured worker probes (for example per-operation Blender
    # capabilities) are one-line JSON and legitimately exceed 500 chars.
    # Keep a hard bound, but large enough that the declaration is not silently
    # truncated into invalid JSON.
    return text.replace("\t", " ")[:4096]
