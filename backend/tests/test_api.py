from __future__ import annotations

import base64
import asyncio
import json
import struct
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.adapters.demo import _cube_glb
from app.adapters.operations import MeshOperationAdapter
from app.adapters.trellis import TrellisCppCliAdapter
from app.adapters.ultrashape import UltraShapeRefiner
from app.main import create_app
from app.quality import validate_glb
from app.schemas import GenerationOptions


ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLq3gAAAABJRU5ErkJggg=="
)


@pytest.fixture()
def client(tmp_path):
    settings = Settings(
        data_dir=tmp_path / "local-data",
        trellis_server_url=None,
        trellis_cpp_command=None,
        engine_profile_path=tmp_path / "missing-engine-profile.json",
    )
    with TestClient(create_app(settings)) as test_client:
        yield test_client


def _create_demo_job(client: TestClient) -> dict:
    uploaded = client.post(
        "/api/uploads",
        files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    upload_id = uploaded.json()["upload"]["id"]
    created = client.post(
        "/api/jobs",
        json={
            "upload_id": upload_id,
            "profile": "8gb",
            "adapter": "demo",
            "output_format": "glb",
            "options": {"mesh_quality": "high", "texture_resolution": 1024, "designer_only_toggle": True},
        },
    )
    assert created.status_code == 202, created.text
    return created.json()["job"]


def _wait_for_job(client: TestClient, job_id: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()["job"]
        if job["status"] in {"completed", "failed", "cancelled"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not reach a terminal state")


def test_health_profiles_and_capabilities_are_truthful(client: TestClient) -> None:
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["queue"]["concurrency"] == 1
    assert health.json()["active_profile"]["id"] == "8gb"

    profiles = client.get("/api/profiles").json()["profiles"]
    assert [item["id"] for item in profiles] == ["6gb", "8gb", "12gb", "16gb"]
    assert [item["target_resolution"] for item in profiles] == [512, 512, 1024, 1536]
    assert not any(item["official_trellis2_supported"] for item in profiles)

    capabilities = client.get("/api/capabilities")
    assert capabilities.status_code == 200
    official = capabilities.json()["pipeline"]["official_trellis2"]
    assert official["available_for_shipped_profiles"] is False
    assert official["minimum_reference_vram_gb"] == 24
    refiner = capabilities.json()["pipeline"]["refiners"][0]
    assert refiner["id"] == "ultrashape"
    assert refiner["available"] is False
    assert "ULTRASHAPE_COMMAND" not in refiner["detail"]


def test_api_uses_the_profile_selected_by_the_installer(client: TestClient) -> None:
    uploaded = client.post(
        "/api/uploads",
        files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")},
    ).json()["upload"]

    created = client.post(
        "/api/jobs",
        json={
            "upload_id": uploaded["id"],
            "profile": "16gb",
            "adapter": "demo",
            "output_format": "glb",
            "options": {"resolution": 2048, "texture_resolution": 8192, "remove_background": False},
        },
    )

    assert created.status_code == 202, created.text
    job = created.json()["job"]
    assert job["profile"] == "8gb"
    assert job["options"]["resolution"] == 512
    assert job["options"]["texture_resolution"] == 1024
    assert job["options"]["remove_background"] is True


def test_demo_job_is_persisted_and_downloadable(client: TestClient) -> None:
    created = _create_demo_job(client)
    final = _wait_for_job(client, created["id"])
    assert final["status"] == "completed", final
    assert final["adapter_used"] == "demo"
    assert final["output"]["format"] == "glb"
    assert final["options"]["mesh_quality"] == "high"
    assert final["options"]["texture_resolution"] == 1024
    assert "Modo demo ativo" in " ".join(final["warnings"])
    assert final["pipeline_mode"] == "trellis_detail"
    assert final["current_tool"] == "demo"
    assert final["validation"]["passed"] is True
    assert final["validation"]["status"] == "valid_untextured"
    assert final["validation"]["vertices"] == 8
    assert final["validation"]["triangles"] == 12
    assert final["artifacts"][0]["kind"] == "model"
    assert final["eta_seconds"] == 0

    model = client.get(final["output"]["url"])
    assert model.status_code == 200
    assert model.content[:4] == b"glTF"

    downloaded = client.get(final["output"]["download_url"])
    assert downloaded.status_code == 200
    assert downloaded.content[:4] == b"glTF"


def test_unknown_adapter_fails_without_lying_about_a_demo(client: TestClient) -> None:
    uploaded = client.post("/api/uploads", files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")}).json()["upload"]
    created = client.post(
        "/api/jobs",
        json={"upload_id": uploaded["id"], "adapter": "not-a-real-adapter", "output_format": "glb"},
    ).json()["job"]
    final = _wait_for_job(client, created["id"])
    assert final["status"] == "failed"
    assert final["adapter_used"] is None
    assert "Adapter desconhecido" in final["error"]


def test_trellis_default_never_falls_back_when_worker_is_unavailable(client: TestClient) -> None:
    uploaded = client.post("/api/uploads", files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")}).json()["upload"]
    created = client.post(
        "/api/jobs",
        json={"upload_id": uploaded["id"], "adapter": "auto", "pipeline_mode": "trellis_detail", "output_format": "glb"},
    ).json()["job"]

    final = _wait_for_job(client, created["id"])
    assert final["status"] == "failed"
    assert final["current_tool"] is None
    assert "TRELLIS" in final["error"]
    assert final["output"] is None


def test_dependency_free_glb_audit_reports_mesh_and_missing_texture(tmp_path) -> None:
    path = tmp_path / "cube.glb"
    path.write_bytes(_cube_glb())

    report = validate_glb(path)
    assert report.passed is True
    assert report.status == "valid_untextured"
    assert report.vertices == 8
    assert report.triangles == 12
    assert report.has_texture is False


def test_requested_trellis_tier_is_limited_to_installed_profile(client: TestClient) -> None:
    uploaded = client.post("/api/uploads", files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")}).json()["upload"]
    created = client.post(
        "/api/jobs",
        json={
            "upload_id": uploaded["id"],
            "adapter": "demo",
            "options": {"trellis_quality_id": "profile-8gb", "ultrashape": "off"},
        },
    )
    assert created.status_code == 202, created.text
    options = created.json()["job"]["options"]
    assert options["trellis_quality_id"] == "profile-8gb"
    assert options["ultrashape"] == "off"

    rejected = client.post(
        "/api/jobs",
        json={"upload_id": uploaded["id"], "adapter": "demo", "options": {"trellis_quality_id": "maximum"}},
    )
    assert rejected.status_code == 422


def test_installer_quality_registry_controls_effective_trellis_options(tmp_path) -> None:
    registry = tmp_path / "engine-profile.json"
    registry.write_text(
        json.dumps(
            {
                "profile": "12gb",
                "trellis": {
                    "qualities": [
                        {"id": "balanced", "label": "Equilibrado", "resolution": 512, "atlas": 2048},
                        {"id": "detailed", "label": "Detalhado", "resolution": 1024, "atlas": 2048},
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    settings = Settings(
        data_dir=tmp_path / "local-data",
        active_profile="12gb",
        trellis_server_url=None,
        trellis_cpp_command=None,
        engine_profile_path=registry,
    )
    with TestClient(create_app(settings)) as client:
        capabilities = client.get("/api/capabilities").json()["pipeline"]["active_profile"]
        assert [item["id"] for item in capabilities["trellis_qualities"]] == ["balanced", "detailed"]
        uploaded = client.post("/api/uploads", files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")}).json()["upload"]
        created = client.post(
            "/api/jobs",
            json={"upload_id": uploaded["id"], "adapter": "demo", "options": {"trellis_quality_id": "detailed", "ultrashape": "off"}},
        )
        assert created.status_code == 202, created.text
        options = created.json()["job"]["options"]
        assert options["resolution"] == 1024
        # Atlas and texture decode are independent in trellis-cli. A 2K UV
        # atlas still uses the supported 1K PBR decoder, never --tex-res 2048.
        assert options["texture_resolution"] == 1024


def test_glb_audit_reports_actual_pbr_map_slots_and_image_dimensions(tmp_path) -> None:
    raw = _cube_glb()
    json_size = struct.unpack("<I", raw[12:16])[0]
    document = json.loads(raw[20 : 20 + json_size].decode("utf-8").rstrip(" "))
    binary_start = 20 + json_size + 8
    binary = raw[binary_start:]
    png = ONE_PIXEL_PNG
    uv_offset = len(binary)
    binary += struct.pack("<8f", 0.0, 0.0, 1.0, 0.0, 1.0, 1.0, 0.0, 1.0)
    image_offset = len(binary)
    binary += png
    document["buffers"][0]["byteLength"] = len(binary)
    document["bufferViews"].extend(
        [
            {"buffer": 0, "byteOffset": uv_offset, "byteLength": 32, "target": 34962},
            {"buffer": 0, "byteOffset": image_offset, "byteLength": len(png)},
        ]
    )
    document["accessors"].append({"bufferView": 2, "componentType": 5126, "count": 4, "type": "VEC2"})
    primitive = document["meshes"][0]["primitives"][0]
    primitive["attributes"]["TEXCOORD_0"] = 2
    document["images"] = [{"bufferView": 3, "mimeType": "image/png"}]
    document["textures"] = [{"source": 0}]
    document["materials"] = [
        {
            "pbrMetallicRoughness": {"baseColorTexture": {"index": 0}, "metallicRoughnessTexture": {"index": 0}},
            "normalTexture": {"index": 0},
            "occlusionTexture": {"index": 0},
        }
    ]
    document["meshes"][0]["primitives"][0]["material"] = 0
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(encoded) + 8 + len(binary))
    glb += struct.pack("<I", len(encoded)) + b"JSON" + encoded + struct.pack("<I", len(binary)) + b"BIN\x00" + binary
    path = tmp_path / "maps.glb"
    path.write_bytes(glb)

    report = validate_glb(path)
    assert report.passed is True
    assert report.has_base_color_texture is True
    assert report.has_metallic_roughness_texture is True
    assert report.has_normal_map is True
    assert report.has_occlusion_texture is True
    assert report.image_dimensions[0].width == 1
    assert report.image_dimensions[0].height == 1


def test_job_library_patch_search_sse_and_safe_delete(client: TestClient) -> None:
    created = _create_demo_job(client)
    final = _wait_for_job(client, created["id"])
    assert final["status"] == "completed"

    patched = client.patch(
        f"/api/jobs/{final['id']}",
        json={"favorite": True, "metadata": {"title": "Árvore favorita", "tags": ["natureza", "Natureza"], "notes": "asset local"}},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["job"]["metadata"]["tags"] == ["natureza"]

    listing = client.get("/api/jobs", params={"favorite": "true", "search": "favorita", "limit": 1, "offset": 0})
    assert listing.status_code == 200
    assert listing.json()["pagination"]["total"] == 1
    assert listing.json()["jobs"][0]["id"] == final["id"]

    events = client.get(f"/api/jobs/{final['id']}/events")
    assert events.status_code == 200
    assert "event: snapshot" in events.text
    assert "event: terminal" in events.text

    deleted = client.delete(f"/api/jobs/{final['id']}")
    assert deleted.status_code == 204, deleted.text
    assert client.get(f"/api/jobs/{final['id']}").status_code == 404


def test_operation_endpoint_reports_missing_worker_without_fake_fallback(client: TestClient) -> None:
    created = _create_demo_job(client)
    final = _wait_for_job(client, created["id"])
    operation = client.post(f"/api/jobs/{final['id']}/operations", json={"kind": "simplify", "target_triangles": 1000})
    assert operation.status_code == 409
    assert "Nenhum worker" in operation.json()["detail"]


def test_generic_operation_worker_is_not_advertised_as_all_operations(tmp_path) -> None:
    """A path to an arbitrary process is not evidence of PBR-safe remesh."""

    worker = tmp_path / "external-worker.py"
    worker.write_text("# deliberately not a verified Blender worker\n", encoding="utf-8")
    adapter = MeshOperationAdapter(
        Settings(
            data_dir=tmp_path / "data",
            mesh_operations_python=Path(sys.executable),
            mesh_operations_worker=worker,
        )
    )
    capability = asyncio.run(adapter.capability())

    assert capability["configured"] is True
    assert capability["available"] is False
    assert capability["operations"] == []
    assert all(not item["available"] for item in capability["by_operation"].values())
    assert "genérico" in capability["by_operation"]["remesh"]["detail"]


def test_operation_endpoint_checks_selected_capability_not_global_flag(client: TestClient) -> None:
    """Retexture stays blocked even if other verified operations are ready."""

    created = _create_demo_job(client)
    final = _wait_for_job(client, created["id"])

    class SelectiveOperations:
        async def capability(self) -> dict:
            return {
                "available": True,
                "detail": "Outras operações estão disponíveis.",
                "by_operation": {
                    "split": {"available": True, "detail": "ok"},
                    "simplify": {"available": True, "detail": "ok"},
                    "remesh": {"available": True, "detail": "ok"},
                    "transform": {"available": True, "detail": "ok"},
                    "retexture": {
                        "available": False,
                        "detail": "Rebake PBR não foi instalado; nenhuma geometria será regenerada.",
                    },
                },
            }

    client.app.state.runner.operations = SelectiveOperations()
    response = client.post(f"/api/jobs/{final['id']}/operations", json={"kind": "retexture"})

    assert response.status_code == 409
    assert "nenhuma geometria será regenerada" in response.json()["detail"]


def test_managed_cli_rejects_unavailable_q8_variant_before_queueing(tmp_path) -> None:
    registry = tmp_path / "engine-profile.json"
    registry.write_text(
        json.dumps(
            {
                "profile": "12gb",
                "trellis": {
                    "model_sets": ["q4", "q8"],
                    "default_quant": "q4",
                    "qualities": [
                        {"id": "balanced", "resolution": 512, "atlas": 1024, "quant": "q4"},
                        {"id": "detailed", "resolution": 1024, "atlas": 2048, "quant": "q8"},
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    cli = tmp_path / "trellis-cli.exe"
    cli.write_bytes(b"placeholder")
    q4 = tmp_path / "models" / "q4"
    q4.mkdir(parents=True)
    settings = Settings(
        data_dir=tmp_path / "data",
        active_profile="12gb",
        trellis_server_url=None,
        trellis_cpp_command=None,
        trellis_cli_bin=cli,
        trellis_cli_models_dir=q4,
        engine_profile_path=registry,
    )
    with TestClient(create_app(settings)) as test_client:
        caps = test_client.get("/api/capabilities").json()["pipeline"]["active_profile"]["trellis_qualities"]
        assert caps[0]["available"] is True
        assert caps[1]["available"] is False
        uploaded = test_client.post("/api/uploads", files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")}).json()["upload"]
        rejected = test_client.post(
            "/api/jobs",
            json={"upload_id": uploaded["id"], "adapter": "trellis-cli", "options": {"trellis_quality_id": "detailed"}},
        )
        assert rejected.status_code == 422
        assert "q8" in rejected.json()["detail"]


def test_managed_cli_builds_only_structured_trellis_arguments(tmp_path) -> None:
    cli = tmp_path / "trellis-cli.exe"
    cli.write_bytes(b"placeholder")
    models = tmp_path / "models"
    models.mkdir()
    adapter = TrellisCppCliAdapter(Settings(data_dir=tmp_path / "data", trellis_cli_bin=cli, trellis_cli_models_dir=models))
    command = adapter._managed_command(
        image_path=tmp_path / "input.png",
        output_path=tmp_path / "output.glb",
        seed=42,
        resolution=512,
        texture_resolution=1024,
        models_dir=models,
        options=GenerationOptions(target_triangles=300_000, trellis_max_tokens=4096, trellis_remesh_band=2, trellis_decimation_grid=8, trellis_webp=False, trellis_gss=7.5, trellis_gsh=3.0, trellis_flash_attention=False, trellis_f32=True),
    )
    for flag in ("--image", "--output", "--models", "--gpu", "--res", "--atlas", "--tex-res", "--bg-removal", "--xatlas", "--max-tokens", "--band", "--decim", "--webp", "--gss", "--gsh", "--no-fa", "--f32", "--require-gpu"):
        assert flag in command
    assert command[command.index("--decim") + 1] == "8"


def test_ultrashape_official_controls_are_bounded_and_structured(tmp_path) -> None:
    with pytest.raises(ValueError):
        GenerationOptions(ultrashape_steps=11)
    with pytest.raises(ValueError):
        GenerationOptions(ultrashape_num_latents=4096)

    source = tmp_path / "UltraShape"
    source.mkdir()
    python = tmp_path / "python.exe"
    checkpoint = tmp_path / "ultrashape_v1.pt"
    worker = tmp_path / "worker.py"
    for path in (python, checkpoint, worker):
        path.write_bytes(b"probe")
    refiner = UltraShapeRefiner(
        Settings(
            data_dir=tmp_path / "data",
            ultrashape_python=python,
            ultrashape_home=source,
            ultrashape_checkpoint=checkpoint,
            ultrashape_worker=worker,
        )
    )
    command = refiner._worker_command(
        "refine", steps=12, num_latents=8192, chunk_size=2048, octree_res=512, scale=0.99, low_vram_override="1"
    )
    for flag in ("--steps", "--num-latents", "--chunk-size", "--octree-res", "--scale", "--low-vram-override"):
        assert flag in command


def test_f32_is_rejected_outside_16gb_profile(client: TestClient) -> None:
    uploaded = client.post("/api/uploads", files={"file": ("asset.png", ONE_PIXEL_PNG, "image/png")}).json()["upload"]
    response = client.post(
        "/api/jobs",
        json={"upload_id": uploaded["id"], "adapter": "demo", "options": {"trellis_f32": True}},
    )
    assert response.status_code == 422
    assert "16 GB" in response.json()["detail"]
