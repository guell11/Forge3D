from __future__ import annotations

import asyncio
import importlib.util
import json
import struct
import sys
import time
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.adapters.base import AdapterResult, AdapterError
from app.adapters.demo import _cube_glb
from app.adapters.faithc import FaithCProbe, FaithCRefiner
from app.config import Settings
from app.main import create_app
from app.schemas import FaithCMode, GenerationOptions

_WORKER_SOURCE = Path(__file__).resolve().parents[2] / "scripts" / "faithc_worker.py"
_WORKER_SPEC = importlib.util.spec_from_file_location("faithc_worker_fixture", _WORKER_SOURCE)
assert _WORKER_SPEC and _WORKER_SPEC.loader
_WORKER_MODULE = importlib.util.module_from_spec(_WORKER_SPEC)
_WORKER_SPEC.loader.exec_module(_WORKER_MODULE)
_coordinate_frame = _WORKER_MODULE._coordinate_frame

_png_buffer = BytesIO()
Image.new("RGB", (1, 1), (210, 80, 30)).save(_png_buffer, format="PNG")
ONE_PIXEL_PNG = _png_buffer.getvalue()


def _textured_cube_glb() -> bytes:
    raw = _cube_glb()
    json_size = struct.unpack("<I", raw[12:16])[0]
    document = json.loads(raw[20 : 20 + json_size].decode("utf-8").rstrip(" "))
    binary_start = 20 + json_size + 8
    binary = raw[binary_start:]
    primitive = document["meshes"][0]["primitives"][0]
    position_accessor = document["accessors"][primitive["attributes"]["POSITION"]]
    uv_count = position_accessor["count"]
    uv_pattern = (0, 0, 1, 0, 1, 1, 0, 1)
    uv_values = tuple(uv_pattern[index % len(uv_pattern)] for index in range(uv_count * 2))
    uv_offset = len(binary)
    binary += struct.pack(f"<{len(uv_values)}f", *uv_values)
    image_offset = len(binary)
    binary += ONE_PIXEL_PNG
    document["buffers"][0]["byteLength"] = len(binary)
    document["bufferViews"].extend(
        [
            {"buffer": 0, "byteOffset": uv_offset, "byteLength": len(uv_values) * 4, "target": 34962},
            {"buffer": 0, "byteOffset": image_offset, "byteLength": len(ONE_PIXEL_PNG)},
        ]
    )
    document["accessors"].append({"bufferView": 2, "componentType": 5126, "count": uv_count, "type": "VEC2"})
    primitive["attributes"]["TEXCOORD_0"] = 2
    document["images"] = [{"bufferView": 3, "mimeType": "image/png"}]
    document["textures"] = [{"source": 0}]
    document["materials"] = [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}]
    primitive["material"] = 0
    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    encoded += b" " * ((4 - len(encoded) % 4) % 4)
    binary += b"\x00" * ((4 - len(binary) % 4) % 4)
    glb = b"glTF" + struct.pack("<II", 2, 12 + 8 + len(encoded) + 8 + len(binary))
    return glb + struct.pack("<I4s", len(encoded), b"JSON") + encoded + struct.pack("<I4s", len(binary), b"BIN\x00") + binary


def _fake_worker(path: Path, *, probe_body: str = "", refine_body: str = "") -> Path:
    path.write_text(
        "import json, pathlib, sys, time\n"
        "action = sys.argv[1]\n"
        "if action == 'probe':\n"
        + probe_body
        + " print('FORGE3D_FAITHC_PROBE:' + json.dumps({'ok': True, 'torch_version': '2.5.1+cu124', 'cuda_device': 'NVIDIA T4'}))\n"
        + " raise SystemExit(0)\n"
        + refine_body,
        encoding="utf-8",
    )
    return path


def _settings(tmp_path: Path, worker: Path, **overrides) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        faithc_enabled=True,
        faithc_python=Path(sys.executable),
        faithc_worker=worker,
        faithc_timeout_seconds=overrides.pop("faithc_timeout_seconds", 10),
        faithc_probe_timeout_seconds=overrides.pop("faithc_probe_timeout_seconds", 4),
        engine_profile_path=tmp_path / "missing-engine-profile.json",
        trellis_server_url=None,
        trellis_cpp_command=None,
        **overrides,
    )


def test_faithc_options_are_bounded_and_opt_in() -> None:
    defaults = GenerationOptions()
    assert defaults.faithc == FaithCMode.OFF
    assert defaults.faithc_resolution == 256
    for resolution in (128, 256, 512):
        assert GenerationOptions(faithc="geometry", faithc_resolution=resolution).faithc_resolution == resolution
    with pytest.raises(ValidationError):
        GenerationOptions(faithc="smooth")
    with pytest.raises(ValidationError):
        GenerationOptions(faithc="geometry", faithc_resolution=1024)


def test_worker_normalization_restores_original_center_and_units() -> None:
    center, scale = _coordinate_frame((-6.0, 2.0, -1.0), (10.0, 6.0, 3.0))
    assert center == (2.0, 4.0, 1.0)
    source_point = (10.0, 2.0, 3.0)
    normalized = tuple((source_point[i] - center[i]) * scale for i in range(3))
    restored = tuple(normalized[i] / scale + center[i] for i in range(3))
    assert restored == pytest.approx(source_point)


@pytest.mark.parametrize("resolution", [128, 256, 512])
def test_adapter_runs_worker_with_structured_arguments(tmp_path: Path, resolution: int) -> None:
    output_name = "geometry ; $(touch should-not-run).glb"
    worker = _fake_worker(
        tmp_path / "worker.py",
        refine_body=(
            "args = dict(zip(sys.argv[2::2], sys.argv[3::2]))\n"
            "out = pathlib.Path(args['--output'])\n"
            "out.parent.mkdir(parents=True, exist_ok=True)\n"
            "out.write_bytes(b'glTF' + bytes(24))\n"
            "print('FAITHC_STAGE: fixture worker completed')\n"
        ),
    )
    source = tmp_path / "source.glb"
    source.write_bytes(_cube_glb())
    output = tmp_path / output_name
    adapter = FaithCRefiner(_settings(tmp_path, worker))

    result = asyncio.run(
        adapter.refine(
            input_path=source,
            output_path=output,
            resolution=resolution,
            probe=FaithCProbe(True, True, True, "fixture ready", probe_state="ready"),
        )
    )

    assert result.output_path == output
    assert output.read_bytes().startswith(b"glTF")
    assert result.adapter_id == "faithc"


def test_adapter_probe_requires_worker_confirmation(tmp_path: Path) -> None:
    worker = tmp_path / "bad-probe.py"
    worker.write_text("raise SystemExit(0)\n", encoding="utf-8")
    adapter = FaithCRefiner(_settings(tmp_path, worker))

    probe = asyncio.run(adapter.probe())

    assert probe.configured is True
    assert probe.available is False
    assert "não confirmou" in probe.detail.lower() or "falhou" in probe.detail.lower()


def test_capability_reports_uncalibrated_without_starting_cuda_worker(tmp_path: Path) -> None:
    marker = tmp_path / "worker-started.txt"
    worker = tmp_path / "marker-worker.py"
    worker.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text(sys.argv[1])\n",
        encoding="utf-8",
    )
    adapter = FaithCRefiner(_settings(tmp_path, worker))

    capability = asyncio.run(adapter.capability())

    assert capability["configured"] is True
    assert capability["available"] is False
    assert capability["probe_state"] == "not-calibrated"
    assert "dentro da fila" in capability["detail"]
    assert not marker.exists()


def test_failed_probe_retries_and_only_success_is_cached(tmp_path: Path) -> None:
    marker = tmp_path / "probe-count.txt"
    worker = tmp_path / "retry-worker.py"
    worker.write_text(
        "import json, pathlib, sys\n"
        "marker = pathlib.Path(" + repr(str(marker)) + ")\n"
        "if not marker.exists():\n"
        " marker.write_text('1')\n"
        " print('FORGE3D_FAITHC_PROBE:' + json.dumps({'ok': False, 'detail': 'temporary CUDA allocation failure'}))\n"
        " raise SystemExit(1)\n"
        "marker.write_text(str(int(marker.read_text()) + 1))\n"
        "print('FORGE3D_FAITHC_PROBE:' + json.dumps({'ok': True, 'torch_version': '2.5.1+cu124', 'cuda_device': 'NVIDIA T4'}))\n",
        encoding="utf-8",
    )
    adapter = FaithCRefiner(_settings(tmp_path, worker))

    first = asyncio.run(adapter.probe())
    failed_capability = asyncio.run(adapter.capability())
    second = asyncio.run(adapter.probe())
    third = asyncio.run(adapter.probe())

    assert first.available is False
    assert first.probe_state == "failed"
    assert failed_capability["probe_state"] == "failed"
    assert second.available is True
    assert third.available is True
    assert marker.read_text(encoding="utf-8") == "2"


def test_probe_cancellation_terminates_worker(tmp_path: Path) -> None:
    worker = _fake_worker(tmp_path / "slow-probe.py", probe_body=" time.sleep(30)\n")
    adapter = FaithCRefiner(_settings(tmp_path, worker, faithc_probe_timeout_seconds=10))
    calls = 0

    def is_cancelled() -> bool:
        nonlocal calls
        calls += 1
        return calls > 2

    with pytest.raises(AdapterError, match="cancelado"):
        asyncio.run(adapter.probe(is_cancelled=is_cancelled))


@pytest.mark.parametrize(
    ("timeout", "cancel", "expected"),
    [(1, False, "excedeu o limite"), (10, True, "cancelado")],
)
def test_adapter_timeout_and_cancellation_terminate_worker(
    tmp_path: Path,
    timeout: int,
    cancel: bool,
    expected: str,
) -> None:
    worker = _fake_worker(tmp_path / "slow.py", refine_body="time.sleep(30)\n")
    source = tmp_path / "source.glb"
    source.write_bytes(_cube_glb())
    output = tmp_path / "out.glb"
    adapter = FaithCRefiner(_settings(tmp_path, worker, faithc_timeout_seconds=timeout))
    calls = 0

    def is_cancelled() -> bool:
        nonlocal calls
        calls += 1
        return cancel and calls > 2

    with pytest.raises(AdapterError, match=expected):
        asyncio.run(
            adapter.refine(
                input_path=source,
                output_path=output,
                resolution=128,
                probe=FaithCProbe(True, True, True, "fixture ready", probe_state="ready"),
                is_cancelled=is_cancelled,
            )
        )
    assert not output.exists()


class _FakeGenerator:
    id = "test-pbr"

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def generate(self, *, output_path: Path, **_kwargs) -> AdapterResult:
        output_path.write_bytes(self.payload)
        return AdapterResult(output_path=output_path, adapter_id=self.id)


class _FakeFaithC:
    id = "faithc"

    def __init__(self, *, available: bool = True, fail: bool = False) -> None:
        self.available = available
        self.fail = fail
        self.called = False

    @property
    def configuration_issue(self):
        return None

    async def probe(self, *, is_cancelled=None, refresh=False):
        return SimpleNamespace(available=self.available, detail="probe double")

    async def capability(self, *_args, **_kwargs):
        return {"id": self.id, "available": self.available}

    async def refine(self, *, output_path: Path, **_kwargs) -> AdapterResult:
        self.called = True
        if self.fail:
            raise AdapterError("worker fixture failed")
        output_path.write_bytes(_cube_glb())
        return AdapterResult(output_path=output_path, adapter_id=self.id)


def _run_job_with_faithc(tmp_path: Path, monkeypatch, fake_faithc: _FakeFaithC, *, release_gpu=None) -> dict:
    settings = Settings(
        data_dir=tmp_path / "data",
        faithc_enabled=False,
        engine_profile_path=tmp_path / "missing-engine-profile.json",
        trellis_server_url=None,
        trellis_cpp_command=None,
    )
    with TestClient(create_app(settings)) as client:
        runner = client.app.state.runner
        generator = _FakeGenerator(_textured_cube_glb())
        monkeypatch.setattr(runner, "_requested_adapter", lambda _job: (generator.id, generator))
        monkeypatch.setattr(runner, "faithc", fake_faithc)
        if release_gpu is not None:
            monkeypatch.setattr(runner.gpu, "release_for", release_gpu)
        uploaded = client.post(
            "/api/uploads",
            files={"file": ("source.png", ONE_PIXEL_PNG, "image/png")},
        ).json()["upload"]
        created = client.post(
            "/api/jobs",
            json={
                "upload_id": uploaded["id"],
                "adapter": "demo",
                "output_format": "glb",
                "options": {"ultrashape": "off", "faithc": "geometry", "faithc_resolution": 128},
            },
        )
        assert created.status_code == 202, created.text
        job_id = created.json()["job"]["id"]
        deadline = time.monotonic() + 3
        final = None
        while time.monotonic() < deadline:
            final = client.get(f"/api/jobs/{job_id}").json()["job"]
            if final["status"] in {"completed", "failed", "cancelled"}:
                break
            time.sleep(0.02)
        assert final and final["status"] == "completed", final
        main_output = client.get(f"/api/jobs/{job_id}/download")
        assert main_output.content == generator.payload
        assert final["validation"]["has_texture"] is True
        return final


def test_geometry_artifact_is_audited_without_replacing_pbr_main_output(tmp_path: Path, monkeypatch) -> None:
    final = _run_job_with_faithc(tmp_path, monkeypatch, _FakeFaithC())
    artifacts = {artifact["kind"]: artifact for artifact in final["artifacts"]}
    assert "faithc-geometry" in artifacts
    assert "faithc-audit" in artifacts
    geometry_audit = json.loads(
        (tmp_path / "data" / "outputs" / final["id"] / artifacts["faithc-audit"]["filename"]).read_text(encoding="utf-8")
    )
    assert geometry_audit["artifact_kind"] == "geometry-only"
    assert geometry_audit["audit"]["passed"] is True
    assert geometry_audit["audit"]["has_texture"] is False


@pytest.mark.parametrize("fake_faithc", [_FakeFaithC(available=False), _FakeFaithC(fail=True)])
def test_unavailable_or_failed_faithc_keeps_pbr_job_completed(tmp_path: Path, monkeypatch, fake_faithc) -> None:
    final = _run_job_with_faithc(tmp_path, monkeypatch, fake_faithc)
    assert final["status"] == "completed"
    assert final["validation"]["has_texture"] is True
    assert final["output"]["filename"] == "model.glb"
    assert any("FaithC" in warning and "principal" in warning for warning in final["warnings"])


def test_faithc_does_not_start_when_gpu_release_cannot_be_confirmed(tmp_path: Path, monkeypatch) -> None:
    fake = _FakeFaithC()
    async def fail_release(_tool: str):
        return SimpleNamespace(released=False, detail="worker GPU não gerenciado")

    final = _run_job_with_faithc(tmp_path, monkeypatch, fake, release_gpu=fail_release)
    assert final["status"] == "completed"
    assert not fake.called
    assert final["output"]["filename"] == "model.glb"
    assert final["validation"]["has_texture"] is True
    assert any("worker GPU não gerenciado" in warning for warning in final["warnings"])
