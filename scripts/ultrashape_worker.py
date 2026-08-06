"""One-shot, structured UltraShape worker for Forge3D.

Run this file with the isolated UltraShape venv, never the API Python process.
It invokes the official ``scripts/infer_dit_refine.py`` with validated paths
and converts the upstream output-name convention into Forge3D's explicit GLB
destination. No shell is used for model execution.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def emit(stage: str, message: str) -> None:
    print(f"FORGE3D_ULTRASHAPE_STAGE:{stage}:{message}", flush=True)


def _path(value: str, label: str, *, directory: bool = False) -> Path:
    path = Path(value).expanduser().resolve()
    valid = path.is_dir() if directory else path.is_file()
    if not valid:
        raise ValueError(f"{label} inválido: {path}")
    return path


def _probe(source: Path, checkpoint: Path, output: str | None = None) -> int:
    payload: dict[str, object] = {"ok": False}
    try:
        if not (source / "scripts" / "infer_dit_refine.py").is_file():
            raise RuntimeError("scripts/infer_dit_refine.py não encontrado")
        if checkpoint.stat().st_size == 0:
            raise RuntimeError("checkpoint vazio")
        import torch  # Deliberately imported in the isolated worker only.

        if not torch.cuda.is_available():
            raise RuntimeError("CUDA não está disponível no ambiente UltraShape")
        if not str(torch.__version__).startswith("2.5.1") or str(torch.version.cuda) != "12.1":
            raise RuntimeError(f"PyTorch upstream esperado 2.5.1/cu121; detectado {torch.__version__}/cu{torch.version.cuda}")
        imported: dict[str, str] = {}
        for package in ("flash_attn", "sageattention", "cubvh"):
            module = importlib.import_module(package)
            imported[package] = str(getattr(module, "__version__", "importado"))
        payload = {
            "ok": True,
            "cuda": True,
            "torch": str(torch.__version__),
            "torch_cuda": str(torch.version.cuda),
            "device": str(torch.cuda.get_device_name(0)),
            "imports": imported,
        }
    except Exception as exc:  # Probe must be machine-readable and never traceback-only.
        payload = {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    if output:
        destination = Path(output).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps({**payload, "available": payload["ok"] is True}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("FORGE3D_ULTRASHAPE_PROBE:" + json.dumps(payload, ensure_ascii=False), flush=True)
    return 0 if payload["ok"] is True else 2


def _preset(mode: str) -> dict[str, int | bool]:
    if mode == "economy":
        return {"steps": 12, "num_latents": 8192, "chunk_size": 2048, "octree_res": 512, "low_vram": True}
    if mode == "full":
        return {"steps": 50, "num_latents": 32768, "chunk_size": 8000, "octree_res": 1024, "low_vram": False}
    raise ValueError("modo UltraShape inválido")


def _refine(args: argparse.Namespace, source: Path, checkpoint: Path) -> int:
    image = _path(args.image, "imagem")
    mesh = _path(args.mesh, "malha")
    if mesh.suffix.lower() not in {".glb", ".obj"}:
        raise ValueError("UltraShape aceita apenas malha GLB ou OBJ")
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    preset = _preset(args.mode)
    for key in ("steps", "num_latents", "chunk_size", "octree_res", "scale"):
        value = getattr(args, key)
        if value is not None:
            preset[key] = value
    if args.low_vram_override is not None:
        preset["low_vram"] = args.low_vram_override == "1"
    config = source / "configs" / "infer_dit_refine.yaml"
    if not config.is_file():
        config = source / "configs" / "infer_dit2.yaml"
    if not config.is_file():
        raise ValueError("Configuração de inferência UltraShape não encontrada")

    run_dir = output.parent / f".{output.stem}-ultrashape-work"
    run_dir.mkdir(parents=True, exist_ok=True)
    upstream = source / "scripts" / "infer_dit_refine.py"
    command = [
        sys.executable,
        str(upstream),
        "--ckpt",
        str(checkpoint),
        "--image",
        str(image),
        "--mesh",
        str(mesh),
        "--output_dir",
        str(run_dir),
        "--config",
        str(config),
        "--steps",
        str(preset["steps"]),
        "--num_latents",
        str(preset["num_latents"]),
        "--chunk_size",
        str(preset["chunk_size"]),
        "--octree_res",
        str(preset["octree_res"]),
        "--scale",
        str(preset.get("scale", 0.99)),
        "--seed",
        str(args.seed),
    ]
    if preset["low_vram"]:
        command.append("--low_vram")

    emit("loading", f"UltraShape {args.mode}: carregando geometria e checkpoint")
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(source) + os.pathsep + environment.get("PYTHONPATH", "")
    process = subprocess.Popen(
        command,
        cwd=str(source),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert process.stdout is not None
    for line in process.stdout:
        clean = line.strip()
        if clean:
            print("FORGE3D_ULTRASHAPE_LOG:" + clean[:500], flush=True)
    code = process.wait()
    if code:
        raise RuntimeError(f"infer_dit_refine.py terminou com código {code}")

    expected = run_dir / f"{image.stem}_refined.glb"
    if not expected.is_file() or expected.stat().st_size < 20:
        raise RuntimeError("UltraShape não produziu o GLB refinado esperado")
    if expected.read_bytes()[:4] != b"glTF":
        raise RuntimeError("UltraShape gerou um arquivo sem assinatura GLB")
    shutil.copyfile(expected, output)
    emit("complete", f"UltraShape concluiu: {output.name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Forge3D UltraShape one-shot worker")
    parser.add_argument("action", choices=("probe", "refine"), nargs="?")
    parser.add_argument("--probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--source", required=True)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--image")
    parser.add_argument("--mesh")
    parser.add_argument("--output")
    parser.add_argument("--mode", choices=("economy", "full"), default="economy")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--steps", type=int, choices=range(12, 51))
    parser.add_argument("--num-latents", type=int, dest="num_latents")
    parser.add_argument("--chunk-size", type=int, dest="chunk_size")
    parser.add_argument("--octree-res", type=int, dest="octree_res")
    parser.add_argument("--scale", type=float)
    parser.add_argument("--low-vram-override", choices=("0", "1"))
    parser.add_argument("--profile", help=argparse.SUPPRESS)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        source = _path(args.source, "fonte UltraShape", directory=True)
        checkpoint = _path(args.checkpoint, "checkpoint UltraShape")
        action = "probe" if args.probe else args.action
        if action == "probe":
            return _probe(source, checkpoint, args.output)
        if not args.image or not args.mesh or not args.output:
            raise ValueError("refine requer --image, --mesh e --output")
        return _refine(args, source, checkpoint)
    except Exception as exc:
        print(f"FORGE3D_ULTRASHAPE_ERROR:{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
