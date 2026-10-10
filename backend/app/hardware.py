"""Best-effort NVIDIA GPU discovery; never substitute installer profile for hardware."""

from __future__ import annotations

import shutil
import subprocess


def detect_gpu(index: int = 0) -> dict:
    """Return measured hardware or explicitly unknown; bound subprocess latency."""
    executable = shutil.which("nvidia-smi")
    if not executable:
        return {"detected": False, "name": None, "memory_total_mib": None, "detail": "nvidia-smi indisponível neste runtime"}
    try:
        completed = subprocess.run(
            [executable, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=3, check=True,
        )
        rows = [row.strip() for row in completed.stdout.splitlines() if row.strip()]
        if not 0 <= index < len(rows):
            raise ValueError("GPU configurada não encontrada na lista do nvidia-smi")
        name, memory = rows[index].rsplit(",", 1)
        memory_mib = int(memory.strip())
        if not name.strip() or memory_mib <= 0:
            raise ValueError("Dados incompletos de GPU")
        return {"detected": True, "name": name.strip(), "memory_total_mib": memory_mib, "detail": "Identificado pelo nvidia-smi"}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"detected": False, "name": None, "memory_total_mib": None, "detail": f"GPU não identificada: {type(exc).__name__}"}
