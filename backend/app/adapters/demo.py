from __future__ import annotations

import json
import struct
from pathlib import Path

from ..profiles import HardwareProfile
from ..schemas import ExportFormat, GenerationOptions
from .base import AdapterResult


class DemoAdapter:
    """Produces a valid small mesh without loading a model or GPU weights.

    It exists so the UI, storage, exporting, and queue can be exercised safely
    on a machine before a real local image-to-3D backend is installed. It is
    deliberately labeled as demo in each job result.
    """

    id = "demo"

    async def capability(self) -> dict:
        return {
            "id": self.id,
            "label": "Demo seguro (sem pesos)",
            "kind": "built-in",
            "configured": True,
            "available": True,
            "outputs": ["glb", "obj"],
            "uses_gpu": False,
            "description": "Gera uma malha de demonstração válida; não executa IA nem afirma usar TRELLIS.",
        }

    async def generate(
        self,
        *,
        image_path: Path,
        output_path: Path,
        profile: HardwareProfile,
        options: GenerationOptions,
        output_format: ExportFormat,
    ) -> AdapterResult:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_format == ExportFormat.OBJ:
            output_path.write_text(_cube_obj(), encoding="utf-8")
        else:
            output_path.write_bytes(_cube_glb())
        return AdapterResult(
            output_path=output_path,
            adapter_id=self.id,
            warnings=[
                "Modo demo ativo: a saída é uma malha-cubo de validação, não uma geração de IA a partir da imagem.",
            ],
        )


def _cube_obj() -> str:
    return """# Local 3D Engine demo mesh — no AI model was used
o demo_cube
v -0.5 -0.5 0.5
v 0.5 -0.5 0.5
v 0.5 0.5 0.5
v -0.5 0.5 0.5
v -0.5 -0.5 -0.5
v 0.5 -0.5 -0.5
v 0.5 0.5 -0.5
v -0.5 0.5 -0.5
f 1 2 3
f 1 3 4
f 2 6 7
f 2 7 3
f 6 5 8
f 6 8 7
f 5 1 4
f 5 4 8
f 4 3 7
f 4 7 8
f 5 6 2
f 5 2 1
"""


def _cube_glb() -> bytes:
    # Eight shared vertices and 12 triangles. The mesh is intentionally tiny,
    # but it is a standards-compliant GLB that browser viewers can load.
    positions = (
        -0.5, -0.5, 0.5,
        0.5, -0.5, 0.5,
        0.5, 0.5, 0.5,
        -0.5, 0.5, 0.5,
        -0.5, -0.5, -0.5,
        0.5, -0.5, -0.5,
        0.5, 0.5, -0.5,
        -0.5, 0.5, -0.5,
    )
    indices = (
        0, 1, 2, 0, 2, 3,
        1, 5, 6, 1, 6, 2,
        5, 4, 7, 5, 7, 6,
        4, 0, 3, 4, 3, 7,
        3, 2, 6, 3, 6, 7,
        4, 5, 1, 4, 1, 0,
    )
    binary = struct.pack("<24f", *positions) + struct.pack("<36H", *indices)
    document = {
        "asset": {"version": "2.0", "generator": "Local 3D Engine demo adapter"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {"baseColorFactor": [0.25, 0.64, 0.95, 1.0], "metallicFactor": 0.05, "roughnessFactor": 0.55}}],
        "buffers": [{"byteLength": len(binary)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 96, "target": 34962},
            {"buffer": 0, "byteOffset": 96, "byteLength": 72, "target": 34963},
        ],
        "accessors": [
            {
                "bufferView": 0,
                "componentType": 5126,
                "count": 8,
                "type": "VEC3",
                "min": [-0.5, -0.5, -0.5],
                "max": [0.5, 0.5, 0.5],
            },
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    json_chunk = json.dumps(document, separators=(",", ":")).encode("utf-8")
    json_chunk += b" " * ((4 - len(json_chunk) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    total_length = 12 + 8 + len(json_chunk) + 8 + len(binary)
    return b"glTF" + struct.pack("<I", 2) + struct.pack("<I", total_length) + (
        struct.pack("<I", len(json_chunk)) + b"JSON" + json_chunk + struct.pack("<I", len(binary)) + b"BIN\x00" + binary
    )
