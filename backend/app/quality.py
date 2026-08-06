from __future__ import annotations

"""Small, dependency-free output auditing and local ETA estimation.

The API intentionally does not import a full 3D library just to inspect an
export.  GLB has a compact binary envelope and JSON manifest, which is enough
to report the facts the designer needs: scene, geometry, UVs, images and PBR
material references.
"""

import json
import statistics
import struct
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Settings
from .profiles import ProfileId
from .schemas import EtaConfidence, ExportFormat, JobRecord, OutputValidation, PipelineMode
from .storage import LocalStore, utc_now

_GLB_HEADER_SIZE = 12
_GLB_CHUNK_HEADER_SIZE = 8
_GLB_MAGIC = b"glTF"
_GLB_JSON_CHUNK = b"JSON"
_MAX_GLB_JSON_BYTES = 16 * 1024 * 1024


def validate_model(path: Path, output_format: ExportFormat) -> OutputValidation:
    """Return an audit report without trusting an adapter's success message."""

    if output_format == ExportFormat.GLB:
        return validate_glb(path)
    return _validate_obj(path)


def validate_glb(path: Path) -> OutputValidation:
    now = utc_now()
    errors: list[str] = []
    warnings: list[str] = []
    file_size = path.stat().st_size if path.is_file() else 0
    base = _new_glb_report(now, file_size)

    if not path.is_file():
        return base.model_copy(update={"errors": ["Arquivo GLB não encontrado."], "status": "invalid"})
    if file_size < _GLB_HEADER_SIZE + _GLB_CHUNK_HEADER_SIZE:
        return base.model_copy(update={"errors": ["Arquivo é menor que o envelope GLB mínimo."], "status": "invalid"})

    try:
        with path.open("rb") as handle:
            header = handle.read(_GLB_HEADER_SIZE)
            magic, version, declared_length = struct.unpack("<4sII", header)
            if magic != _GLB_MAGIC:
                errors.append("Assinatura GLB ausente (esperado 'glTF').")
            if version != 2:
                errors.append(f"Versão GLB não suportada: {version} (esperado 2).")
            if declared_length != file_size:
                errors.append("Tamanho declarado no GLB não coincide com o arquivo salvo.")

            chunk_header = handle.read(_GLB_CHUNK_HEADER_SIZE)
            json_length, chunk_type = struct.unpack("<I4s", chunk_header)
            if chunk_type != _GLB_JSON_CHUNK:
                errors.append("Primeiro chunk do GLB não é JSON.")
            if json_length > _MAX_GLB_JSON_BYTES:
                errors.append("Manifesto JSON do GLB excede o limite seguro de auditoria.")
                document: dict = {}
            elif json_length > max(0, file_size - _GLB_HEADER_SIZE - _GLB_CHUNK_HEADER_SIZE):
                errors.append("Chunk JSON do GLB excede os limites do arquivo.")
                document = {}
            else:
                raw_json = handle.read(json_length)
                try:
                    parsed = json.loads(raw_json.decode("utf-8"))
                    document = parsed if isinstance(parsed, dict) else {}
                    if not document:
                        errors.append("Manifesto JSON do GLB não é um objeto válido.")
                except (UnicodeDecodeError, json.JSONDecodeError):
                    errors.append("Manifesto JSON do GLB está corrompido.")
                    document = {}
            binary_chunks: list[bytes] = []
            while handle.tell() + _GLB_CHUNK_HEADER_SIZE <= file_size:
                chunk_length, chunk_type = struct.unpack("<I4s", handle.read(_GLB_CHUNK_HEADER_SIZE))
                if chunk_length > file_size - handle.tell():
                    errors.append("Chunk GLB excede os limites do arquivo.")
                    break
                chunk = handle.read(chunk_length)
                if chunk_type == b"BIN\x00":
                    binary_chunks.append(chunk)
    except (OSError, struct.error) as exc:
        return base.model_copy(update={"errors": [f"Não foi possível ler o GLB: {type(exc).__name__}."], "status": "invalid"})

    metrics = _inspect_gltf(document, binary_chunks if "binary_chunks" in locals() else [], errors, warnings)
    passed = not errors
    status = "valid_textured" if passed and metrics["has_texture"] else "valid_untextured" if passed else "invalid"
    return OutputValidation(
        validated_at=now,
        format=ExportFormat.GLB,
        passed=passed,
        status=status,
        file_size=file_size,
        glb_version=version if "version" in locals() else None,
        errors=errors,
        warnings=warnings,
        **metrics,
    )


def _new_glb_report(now: datetime, file_size: int) -> OutputValidation:
    return OutputValidation(
        validated_at=now,
        format=ExportFormat.GLB,
        passed=False,
        status="invalid",
        file_size=file_size,
    )


def _collection(document: dict, name: str) -> list:
    value = document.get(name, [])
    return value if isinstance(value, list) else []


def _accessor_count(accessors: list, index: object) -> int:
    if not isinstance(index, int) or index < 0 or index >= len(accessors):
        return 0
    accessor = accessors[index]
    if not isinstance(accessor, dict):
        return 0
    count = accessor.get("count", 0)
    return count if isinstance(count, int) and count >= 0 else 0


def _inspect_gltf(document: dict, binary_chunks: list[bytes], errors: list[str], warnings: list[str]) -> dict:
    scenes = _collection(document, "scenes")
    nodes = _collection(document, "nodes")
    meshes = _collection(document, "meshes")
    materials = _collection(document, "materials")
    images = _collection(document, "images")
    textures = _collection(document, "textures")
    accessors = _collection(document, "accessors")

    if not scenes:
        errors.append("GLB não declara uma cena.")
    if not meshes:
        errors.append("GLB não declara nenhuma malha.")

    vertices = 0
    triangles = 0
    has_uvs = False
    has_position = False
    for mesh in meshes:
        primitives = mesh.get("primitives", []) if isinstance(mesh, dict) else []
        if not isinstance(primitives, list):
            continue
        for primitive in primitives:
            if not isinstance(primitive, dict):
                continue
            attributes = primitive.get("attributes", {})
            if not isinstance(attributes, dict):
                continue
            position = _accessor_count(accessors, attributes.get("POSITION"))
            if position:
                has_position = True
                vertices += position
            if _accessor_count(accessors, attributes.get("TEXCOORD_0")):
                has_uvs = True
            mode = primitive.get("mode", 4)
            index_count = _accessor_count(accessors, primitive.get("indices"))
            if mode == 4:
                triangles += index_count // 3 if index_count else position // 3

    if not has_position:
        errors.append("Nenhum atributo POSITION utilizável foi encontrado nas malhas.")
    if not has_uvs:
        warnings.append("Malha sem coordenadas UV TEXCOORD_0.")

    pbr_materials = sum(
        1
        for material in materials
        if isinstance(material, dict) and isinstance(material.get("pbrMetallicRoughness"), dict)
    )
    texture_slots = {
        "base_color": [],
        "metallic_roughness": [],
        "normal": [],
        "occlusion": [],
    }
    for material in materials:
        if not isinstance(material, dict):
            continue
        pbr = material.get("pbrMetallicRoughness")
        if isinstance(pbr, dict):
            _append_texture_index(texture_slots["base_color"], pbr.get("baseColorTexture"))
            _append_texture_index(texture_slots["metallic_roughness"], pbr.get("metallicRoughnessTexture"))
        _append_texture_index(texture_slots["normal"], material.get("normalTexture"))
        _append_texture_index(texture_slots["occlusion"], material.get("occlusionTexture"))

    base_color_images = _texture_image_indices(textures, texture_slots["base_color"])
    has_texture = bool(images and textures and base_color_images)
    if not has_texture:
        warnings.append("Malha sem textura PBR incorporada detectável.")

    image_dimensions = _inspect_image_dimensions(document, binary_chunks)

    return {
        "scenes": len(scenes),
        "meshes": len(meshes),
        "nodes": len(nodes),
        "vertices": vertices,
        "triangles": triangles,
        "has_uvs": has_uvs,
        "images": len(images),
        "textures": len(textures),
        "materials": len(materials),
        "pbr_materials": pbr_materials,
        "has_texture": has_texture,
        "base_color_textures": len(texture_slots["base_color"]),
        "metallic_roughness_textures": len(texture_slots["metallic_roughness"]),
        "normal_textures": len(texture_slots["normal"]),
        "occlusion_textures": len(texture_slots["occlusion"]),
        "has_base_color_texture": bool(texture_slots["base_color"]),
        "has_metallic_roughness_texture": bool(texture_slots["metallic_roughness"]),
        "has_normal_map": bool(texture_slots["normal"]),
        "has_occlusion_texture": bool(texture_slots["occlusion"]),
        "image_dimensions": image_dimensions,
    }


def _append_texture_index(target: list[int], value: object) -> None:
    if not isinstance(value, dict):
        return
    index = value.get("index")
    if isinstance(index, int) and index >= 0:
        target.append(index)


def _texture_image_indices(textures: list, indices: list[int]) -> set[int]:
    result: set[int] = set()
    for index in indices:
        if index >= len(textures) or not isinstance(textures[index], dict):
            continue
        texture = textures[index]
        source = texture.get("source")
        if not isinstance(source, int):
            extensions = texture.get("extensions")
            if isinstance(extensions, dict):
                for extension_name in ("EXT_texture_webp", "KHR_texture_basisu"):
                    extension = extensions.get(extension_name)
                    if isinstance(extension, dict) and isinstance(extension.get("source"), int):
                        source = extension["source"]
                        break
        if isinstance(source, int) and source >= 0:
            result.add(source)
    return result


def _inspect_image_dimensions(document: dict, binary_chunks: list[bytes]) -> list[dict]:
    images = _collection(document, "images")
    buffer_views = _collection(document, "bufferViews")
    details: list[dict] = []
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        mime_type = image.get("mimeType") if isinstance(image.get("mimeType"), str) else None
        payload = _image_payload(image, buffer_views, binary_chunks)
        width, height, detected_mime = _image_size(payload)
        details.append(
            {
                "index": index,
                "mime_type": mime_type or detected_mime,
                "width": width,
                "height": height,
            }
        )
    return details


def _image_payload(image: dict, buffer_views: list, binary_chunks: list[bytes]) -> bytes | None:
    view_index = image.get("bufferView")
    if not isinstance(view_index, int) or view_index < 0 or view_index >= len(buffer_views):
        return None
    view = buffer_views[view_index]
    if not isinstance(view, dict):
        return None
    buffer_index = view.get("buffer", 0)
    byte_length = view.get("byteLength")
    byte_offset = view.get("byteOffset", 0)
    if (
        not isinstance(buffer_index, int)
        or not isinstance(byte_length, int)
        or not isinstance(byte_offset, int)
        or buffer_index < 0
        or byte_length < 0
        or byte_offset < 0
        or buffer_index >= len(binary_chunks)
    ):
        return None
    data = binary_chunks[buffer_index]
    end = byte_offset + byte_length
    return data[byte_offset:end] if end <= len(data) else None


def _image_size(payload: bytes | None) -> tuple[int | None, int | None, str | None]:
    if not payload:
        return None, None, None
    if payload[:8] == b"\x89PNG\r\n\x1a\n" and len(payload) >= 24:
        return int.from_bytes(payload[16:20], "big"), int.from_bytes(payload[20:24], "big"), "image/png"
    if payload[:2] == b"\xff\xd8":
        position = 2
        while position + 9 <= len(payload):
            if payload[position] != 0xFF:
                position += 1
                continue
            while position < len(payload) and payload[position] == 0xFF:
                position += 1
            if position >= len(payload):
                break
            marker = payload[position]
            position += 1
            if marker in {0xD8, 0xD9}:
                continue
            if position + 2 > len(payload):
                break
            segment_length = int.from_bytes(payload[position:position + 2], "big")
            if segment_length < 2 or position + segment_length > len(payload):
                break
            if marker in {*range(0xC0, 0xC4), *range(0xC5, 0xC8), *range(0xC9, 0xCC)} and segment_length >= 7:
                height = int.from_bytes(payload[position + 3:position + 5], "big")
                width = int.from_bytes(payload[position + 5:position + 7], "big")
                return width or None, height or None, "image/jpeg"
            position += segment_length
        return None, None, "image/jpeg"
    if payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        kind = payload[12:16]
        if kind == b"VP8X" and len(payload) >= 30:
            width = 1 + int.from_bytes(payload[24:27], "little")
            height = 1 + int.from_bytes(payload[27:30], "little")
            return width, height, "image/webp"
        if kind == b"VP8L" and len(payload) >= 25:
            bits = int.from_bytes(payload[21:25], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1, "image/webp"
        if kind == b"VP8 " and len(payload) >= 30 and payload[23:26] == b"\x9d\x01\x2a":
            width = int.from_bytes(payload[26:28], "little") & 0x3FFF
            height = int.from_bytes(payload[28:30], "little") & 0x3FFF
            return width or None, height or None, "image/webp"
        return None, None, "image/webp"
    return None, None, None


def _validate_obj(path: Path) -> OutputValidation:
    file_size = path.stat().st_size if path.is_file() else 0
    errors: list[str] = []
    if not path.is_file() or not file_size:
        errors.append("Arquivo OBJ não encontrado ou vazio.")
    return OutputValidation(
        validated_at=utc_now(),
        format=ExportFormat.OBJ,
        passed=not errors,
        status="valid_untextured" if not errors else "invalid",
        file_size=file_size,
        errors=errors,
        warnings=["Auditoria OBJ é básica; UV e textura externos não foram verificados."],
    )


@dataclass(frozen=True, slots=True)
class EtaEstimate:
    seconds: int | None
    confidence: EtaConfidence
    sample_count: int


class LocalEtaEstimator:
    """Uses completed local jobs only; no cloud timings or fake percentages."""

    def __init__(self, store: LocalStore, settings: Settings) -> None:
        self.store = store
        self.settings = settings

    def estimate(self, *, mode: PipelineMode, profile: ProfileId, tool: str) -> EtaEstimate:
        durations: list[float] = []
        for job in self.store.list_jobs(limit=200):
            if job.status.value != "completed" or job.pipeline_mode != mode:
                continue
            if job.profile != profile or job.adapter_used != tool:
                continue
            if not job.started_at or not job.completed_at:
                continue
            seconds = (job.completed_at - job.started_at).total_seconds()
            if 0 < seconds <= 24 * 60 * 60:
                durations.append(seconds)

        if durations:
            # Restrict history to recent local runs so an old model/config does
            # not dominate the ETA after the operator changes quality settings.
            median = int(round(statistics.median(durations[:20])))
            confidence = EtaConfidence.MEASURED if len(durations) >= 3 else EtaConfidence.LEARNING
            return EtaEstimate(seconds=max(1, median), confidence=confidence, sample_count=len(durations))

        if tool.startswith("trellis"):
            baseline = self.settings.trellis_calibration_seconds
        else:
            baseline = None
        return EtaEstimate(
            seconds=max(1, baseline) if baseline else None,
            confidence=EtaConfidence.INITIAL if baseline else EtaConfidence.UNAVAILABLE,
            sample_count=0,
        )
