from __future__ import annotations

import base64
from io import BytesIO
import struct
import pytest
from PIL import Image

from app import quality
from app.quality import _image_size, _inspect_gltf


def _raster_image(image_format: str, size: tuple[int, int] = (1, 1)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (210, 80, 30)).save(output, format=image_format)
    return output.getvalue()


_PNG_BYTES = _raster_image("PNG")
_PNG_DATA_URI = "data:image/png;base64," + base64.b64encode(_PNG_BYTES).decode("ascii")
_HEADER_ONLY_PNG = b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", 1, 1)
_HEADER_ONLY_JPEG = bytes.fromhex("ffd8ffc000070800010001")
_HEADER_ONLY_WEBP = b"RIFF" + struct.pack("<I", 22) + b"WEBPVP8X" + struct.pack("<I", 10) + b"\x00" * 10


def _document(image: dict, *, uv_count: int = 3, material_on_primitive: bool = True) -> dict:
    primitive = {
        "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
    }
    if material_on_primitive:
        primitive["material"] = 0
    return {
        "scenes": [{}],
        "meshes": [{"primitives": [primitive]}],
        "accessors": [
            {"count": 3, "componentType": 5126, "type": "VEC3"},
            {"count": uv_count, "componentType": 5126, "type": "VEC2"},
        ],
        "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
        "textures": [{"source": 0}],
        "images": [image],
    }


def _inspect(document: dict, binary_chunks: list[bytes] | None = None) -> tuple[dict, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics = _inspect_gltf(document, binary_chunks or [], errors, warnings)
    return metrics, errors, warnings


def test_textured_primitive_requires_valid_data_uri_and_matching_uvs() -> None:
    metrics, errors, _warnings = _inspect(_document({"uri": _PNG_DATA_URI, "mimeType": "image/png"}))

    assert errors == []
    assert metrics["has_uvs"] is True
    assert metrics["has_texture"] is True
    assert metrics["has_base_color_texture"] is True
    assert metrics["image_dimensions"] == [{"index": 0, "mime_type": "image/png", "width": 1, "height": 1}]


def test_textured_primitive_accepts_embedded_png_buffer_view() -> None:
    document = _document({"bufferView": 0, "mimeType": "image/png"})
    document["bufferViews"] = [{"buffer": 0, "byteOffset": 0, "byteLength": len(_PNG_BYTES)}]

    metrics, errors, _warnings = _inspect(document, [_PNG_BYTES])

    assert errors == []
    assert metrics["has_texture"] is True


def test_header_only_png_does_not_claim_embedded_pbr_texture() -> None:
    header_uri = "data:image/png;base64," + base64.b64encode(_HEADER_ONLY_PNG).decode("ascii")
    metrics, _errors, _warnings = _inspect(
        _document({"uri": header_uri, "mimeType": "image/png"})
    )

    assert metrics["has_texture"] is False
    assert metrics["has_base_color_texture"] is False
    assert metrics["image_dimensions"][0]["width"] is None


@pytest.mark.parametrize(
    ("payload", "mime_type"),
    [
        (_HEADER_ONLY_PNG, "image/png"),
        (_HEADER_ONLY_JPEG, "image/jpeg"),
        (_HEADER_ONLY_WEBP, "image/webp"),
    ],
    ids=["png-header", "jpeg-sof", "webp-vp8x"],
)
def test_image_headers_without_decodable_pixels_do_not_claim_pbr_texture(
    payload: bytes, mime_type: str
) -> None:
    uri = f"data:{mime_type};base64," + base64.b64encode(payload).decode("ascii")
    metrics, _errors, _warnings = _inspect(
        _document({"uri": uri, "mimeType": mime_type})
    )

    assert metrics["has_texture"] is False
    assert metrics["has_base_color_texture"] is False


@pytest.mark.parametrize(
    ("image_format", "mime_type"),
    [("PNG", "image/png"), ("JPEG", "image/jpeg"), ("WEBP", "image/webp")],
)
def test_supported_raster_formats_are_decoded_before_texture_claim(
    image_format: str, mime_type: str
) -> None:
    payload = _raster_image(image_format)
    uri = f"data:{mime_type};base64," + base64.b64encode(payload).decode("ascii")
    metrics, errors, _warnings = _inspect(
        _document({"uri": uri, "mimeType": mime_type})
    )

    assert errors == []
    assert metrics["has_texture"] is True
    assert metrics["image_dimensions"][0]["width"] == 1
    assert metrics["image_dimensions"][0]["height"] == 1


def test_image_pixel_limit_is_checked_before_decode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.quality._MAX_IMAGE_PIXELS", 1)

    assert _image_size(_raster_image("PNG", size=(2, 1))) == (None, None, None)


def test_oversized_buffer_view_is_rejected_before_slicing(monkeypatch: pytest.MonkeyPatch) -> None:
    class NoSliceBytes(bytes):
        def __getitem__(self, key):
            if isinstance(key, slice):
                raise AssertionError("oversized buffer view must not be copied")
            return super().__getitem__(key)

    monkeypatch.setattr(quality, "_MAX_IMAGE_BYTES", 4)

    payload = quality._image_payload(
        {"bufferView": 0},
        [{"buffer": 0, "byteOffset": 0, "byteLength": 5}],
        [NoSliceBytes(b"12345")],
    )

    assert payload is None


def test_oversized_base64_data_uri_is_rejected_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quality, "_MAX_IMAGE_BYTES", 4)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("oversized data URI must not be decoded")

    monkeypatch.setattr(quality.base64, "b64decode", fail_decode)

    assert quality._decode_image_data_uri("data:image/png;base64,MTIzNDU=") is None


def test_oversized_percent_data_uri_is_rejected_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quality, "_MAX_IMAGE_BYTES", 4)

    def fail_decode(*_args, **_kwargs):
        raise AssertionError("oversized data URI must not be decoded")

    monkeypatch.setattr(quality, "unquote_to_bytes", fail_decode)

    assert quality._decode_image_data_uri("data:image/png,%41%42%43%44%45") is None


def test_orphan_pbr_material_does_not_claim_texture() -> None:
    metrics, errors, _warnings = _inspect(
        _document({"uri": _PNG_DATA_URI, "mimeType": "image/png"}, material_on_primitive=False)
    )

    assert errors == []
    assert metrics["pbr_materials"] == 0
    assert metrics["has_texture"] is False
    assert metrics["has_base_color_texture"] is False


def test_texture_with_out_of_range_image_source_is_not_pbr() -> None:
    document = _document({"uri": _PNG_DATA_URI, "mimeType": "image/png"})
    document["textures"][0]["source"] = 3

    metrics, _errors, _warnings = _inspect(document)

    assert metrics["has_texture"] is False
    assert metrics["has_base_color_texture"] is False


def test_external_or_invalid_image_uri_is_not_reported_as_embedded_texture() -> None:
    metrics, _errors, _warnings = _inspect(_document({"uri": "missing-texture.png", "mimeType": "image/png"}))

    assert metrics["has_texture"] is False


def test_uv_accessor_must_match_position_count_for_texture_claim() -> None:
    metrics, _errors, _warnings = _inspect(
        _document({"uri": _PNG_DATA_URI, "mimeType": "image/png"}, uv_count=2)
    )

    assert metrics["has_uvs"] is False
    assert metrics["has_texture"] is False
