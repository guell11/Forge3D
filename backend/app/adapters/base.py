from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..profiles import HardwareProfile
from ..schemas import ExportFormat, GenerationOptions


class AdapterError(RuntimeError):
    """A local adapter failed or is not configured for the requested job."""


@dataclass(slots=True)
class AdapterResult:
    output_path: Path
    adapter_id: str
    warnings: list[str] = field(default_factory=list)
    # Tail of real local-worker output. The pipeline persists only a scrubbed,
    # bounded version so an external command cannot grow job metadata forever.
    logs: list[str] = field(default_factory=list)


class GenerationAdapter(Protocol):
    id: str

    async def generate(
        self,
        *,
        image_path: Path,
        output_path: Path,
        profile: HardwareProfile,
        options: GenerationOptions,
        output_format: ExportFormat,
    ) -> AdapterResult: ...

    async def capability(self) -> dict: ...
