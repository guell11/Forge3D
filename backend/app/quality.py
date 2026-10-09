from __future__ import annotations

"""Small output auditing and local ETA estimation.

The API reads GLB geometry and material links directly, and uses bounded Pillow
decoding only to confirm raster image payloads before reporting PBR maps.
"""

import base64
import binascii
import json
import statistics
import struct
import warnings
from dataclasses import dataclass
from datetime import datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import unquote_to_bytes

from PIL import Image, UnidentifiedImageError

from .config import Settings
from .profiles import ProfileId
from .schemas import EtaConfidence, ExportFormat, JobRecord, OutputValidation, PipelineMode
from .storage import LocalStore, utc_now

_GLB_HEADER_SIZE = 12
_GLB_CHUNK_HEADER_SIZE = 8
_GLB_MAGIC = b"glTF"
_GLB_JSON_CHUNK = b"JSON"
_MAX_GLB_JSON_BYTES = 16 * 1024 * 1024
_MAX_IMAGE_BYTES = 64 * 1024 * 1024
_MAX_IMAGE_DIMENSION = 32_768
_MAX_IMAGE_PIXELS = 32_000_000


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
    usable_images = _usable_image_indices(document, binary_chunks)
    used_materials: set[int] = set()
    texture_slots = {
        "base_color": set(),
        "metallic_roughness": set(),
        "normal": set(),
        "occlusion": set(),
    }
    base_color_on_uv_mesh = False

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
            uv_compatible = _uv_accessor_compatible(accessors, attributes.get("TEXCOORD_0"), position)
            has_uvs = has_uvs or uv_compatible
            mode = primitive.get("mode", 4)
            index_count = _accessor_count(accessors, primitive.get("indices"))
            if mode == 4:
                triangles += index_count // 3 if index_count else position // 3

            material_index = primitive.get("material")
            if (
                not isinstance(material_index, int)
                or isinstance(material_index, bool)
                or material_index < 0
                or material_index >= len(materials)
                or not isinstance(materials[material_index], dict)
            ):
                continue
            used_materials.add(material_index)
            material = materials[material_index]
            pbr = material.get("pbrMetallicRoughness")
            texture_infos = {
                "base_color": pbr.get("baseColorTexture") if isinstance(pbr, dict) else None,
                "metallic_roughness": pbr.get("metallicRoughnessTexture") if isinstance(pbr, dict) else None,
                "normal": material.get("normalTexture"),
                "occlusion": material.get("occlusionTexture"),
            }
            for slot, texture_info in texture_infos.items():
                texture_index = _texture_info_index(texture_info)
                if texture_index is None or not uv_compatible:
                    continue
                image_index = _texture_image_index(textures, texture_index, len(images))
                if image_index is None or image_index not in usable_images:
                    continue
                texture_slots[slot].add(texture_index)
                if slot == "base_color":
                    base_color_on_uv_mesh = True

    if not has_position:
        errors.append("Nenhum atributo POSITION utilizável foi encontrado nas malhas.")
    if not has_uvs:
        warnings.append("Malha sem coordenadas UV TEXCOORD_0 compatíveis com a posição.")

    pbr_materials = sum(
        1
        for index in used_materials
        if isinstance(materials[index].get("pbrMetallicRoughness"), dict)
    )
    has_texture = base_color_on_uv_mesh
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


def _uv_accessor_compatible(accessors: list, index: object, position_count: int) -> bool:
    if not isinstance(index, int) or isinstance(index, bool) or index < 0 or index >= len(accessors):
        return False
    accessor = accessors[index]
    if not isinstance(accessor, dict) or accessor.get("type") != "VEC2":
        return False
    if _accessor_count(accessors, index) != position_count:
        return False
    component_type = accessor.get("componentType")
    if component_type == 5126:
        return True
    return component_type in {5121, 5123} and accessor.get("normalized") is True


def _texture_info_index(value: object) -> int | None:
    if not isinstance(value, dict):
        return None
    index = value.get("index")
    return index if isinstance(index, int) and not isinstance(index, bool) and index >= 0 else None


def _texture_image_index(textures: list, texture_index: int, image_count: int) -> int | None:
    if texture_index >= len(textures) or not isinstance(textures[texture_index], dict):
        return None
    texture = textures[texture_index]
    source = texture.get("source")
    if not isinstance(source, int) or isinstance(source, bool):
        extensions = texture.get("extensions")
        if isinstance(extensions, dict):
            for extension_name in ("EXT_texture_webp", "KHR_texture_basisu"):
                extension = extensions.get(extension_name)
                candidate = extension.get("source") if isinstance(extension, dict) else None
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    source = candidate
                    break
    if not isinstance(source, int) or isinstance(source, bool) or source < 0 or source >= image_count:
        return None
    return source


def _usable_image_indices(document: dict, binary_chunks: list[bytes]) -> set[int]:
    usable: set[int] = set()
    images = _collection(document, "images")
    buffer_views = _collection(document, "bufferViews")
    for index, image in enumerate(images):
        if not isinstance(image, dict):
            continue
        payload = _image_payload(image, buffer_views, binary_chunks)
        width, height, detected_mime = _image_size(payload)
        mime_type = image.get("mimeType")
        uri = image.get("uri")
        if isinstance(uri, str) and uri.startswith("data:"):
            mime_type = uri[5:].split(",", 1)[0].split(";", 1)[0].lower()
        if (
            payload
            and width
            and height
            and detected_mime
            and (not isinstance(mime_type, str) or mime_type.lower() == detected_mime)
        ):
            usable.add(index)
    return usable


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
    uri = image.get("uri")
    if isinstance(uri, str) and uri.startswith("data:"):
        return _decode_image_data_uri(uri)
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
        or byte_length > _MAX_IMAGE_BYTES
        or byte_offset < 0
        or buffer_index >= len(binary_chunks)
    ):
        return None
    data = binary_chunks[buffer_index]
    end = byte_offset + byte_length
    return data[byte_offset:end] if end <= len(data) else None


def _decode_image_data_uri(uri: str) -> bytes | None:
    try:
        header, encoded = uri[5:].split(",", 1)
    except ValueError:
        return None
    mime_type, *parameters = header.split(";")
    mime_type = mime_type.lower()
    if not mime_type.startswith("image/"):
        return None
    is_base64 = any(parameter.lower() == "base64" for parameter in parameters)
    if is_base64:
        if len(encoded) % 4:
            return None
        padding = len(encoded) - len(encoded.rstrip("="))
        estimated_size = (len(encoded) // 4) * 3 - min(padding, 2)
        if (
            len(encoded) > ((_MAX_IMAGE_BYTES + 2) // 3) * 4
            or estimated_size > _MAX_IMAGE_BYTES
        ):
            return None
    else:
        decoded_size = 0
        cursor = 0
        while cursor < len(encoded):
            escape = encoded[cursor + 1:cursor + 3]
            if (
                encoded[cursor] == "%"
                and len(escape) == 2
                and all(character in "0123456789abcdefABCDEF" for character in escape)
            ):
                decoded_size += 1
                cursor += 3
            else:
                decoded_size += len(encoded[cursor].encode("utf-8"))
                cursor += 1
            if decoded_size > _MAX_IMAGE_BYTES:
                return None
    try:
        payload = (
            base64.b64decode(encoded, validate=True)
            if is_base64
            else unquote_to_bytes(encoded)
        )
    except (binascii.Error, ValueError):
        return None
    width, height, detected_mime = _image_size(payload)
    return payload if payload and width and height and detected_mime == mime_type else None


def _image_size(payload: bytes | None) -> tuple[int | None, int | None, str | None]:
    """Return dimensions only after a bounded full decode of a supported image."""
    if not payload or len(payload) > _MAX_IMAGE_BYTES:
        return None, None, None

    supported_formats = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
    }
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(payload)) as image:
                image_format = image.format
                width, height = image.size
                if (
                    image_format not in supported_formats
                    or width <= 0
                    or height <= 0
                    or width > _MAX_IMAGE_DIMENSION
                    or height > _MAX_IMAGE_DIMENSION
                    or width * height > _MAX_IMAGE_PIXELS
                ):
                    return None, None, None
                image.verify()

            with Image.open(BytesIO(payload)) as image:
                if image.format != image_format or image.size != (width, height):
                    return None, None, None
                image.load()
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        EOFError,
        OverflowError,
    ):
        return None, None, None

    return width, height, supported_formats[image_format]


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
