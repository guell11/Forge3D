#!/usr/bin/env python3
"""Run upstream FaithC geometry reconstruction in its dedicated CUDA env."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import sys
from pathlib import Path
from typing import Sequence

PROBE_PREFIX = "FORGE3D_FAITHC_PROBE:"
RESOLUTIONS = (128, 256, 512)


def _coordinate_frame(
    bounds_min: Sequence[float],
    bounds_max: Sequence[float],
    margin: float = 0.05,
) -> tuple[tuple[float, float, float], float]:
    """Return a uniform normalization frame and its center/scale inverse."""

    if not 0.0 <= margin < 1.0:
        raise ValueError("margin deve estar no intervalo [0, 1).")
    center = tuple((float(bounds_min[i]) + float(bounds_max[i])) / 2.0 for i in range(3))
    half_extent = max(abs(float(bounds_max[i]) - center[i]) for i in range(3))
    if not math.isfinite(half_extent) or half_extent <= 1e-12:
        raise ValueError("A malha não possui extensão geométrica finita.")
    normalization_scale = (1.0 - margin) / half_extent
    return center, normalization_scale


def _normalize_vertices(vertices, center, scale):
    return (vertices - center) * scale


def _restore_vertices(vertices, center, scale):
    return vertices / scale + center


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Worker isolado do refinamento geométrico FaithC.")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("probe", help="verifica imports, CUDA e uma alocação real")
    refine = subparsers.add_parser("refine", help="executa Faithful Contouring sobre um GLB")
    refine.add_argument("--mesh", required=True, type=Path)
    refine.add_argument("--output", required=True, type=Path)
    refine.add_argument("--resolution", required=True, type=int, choices=RESOLUTIONS)
    return parser


def _probe() -> int:
    payload: dict[str, object]
    try:
        import torch

        if not torch.cuda.is_available():
            raise RuntimeError("PyTorch não encontrou um dispositivo CUDA.")

        from atom3d import MeshBVH  # noqa: F401
        from atom3d.grid import OctreeIndexer  # noqa: F401
        from faithcontour import FCTDecoder, FCTEncoder  # noqa: F401

        device = torch.device("cuda:0")
        probe_tensor = torch.zeros((1,), device=device)
        torch.cuda.synchronize(device)
        del probe_tensor
        torch.cuda.empty_cache()
        payload = {
            "ok": True,
            "torch_version": str(torch.__version__),
            "cuda_device": str(torch.cuda.get_device_name(0)),
            "faithcontour_version": _package_version("faithcontour"),
            "atom3d_version": _package_version("atom3d"),
        }
    except Exception as exc:
        payload = {"ok": False, "detail": f"{type(exc).__name__}: {str(exc)[:500]}"}
    print(PROBE_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
    return 0 if payload.get("ok") is True else 1


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _load_world_mesh(path: Path):
    import numpy as np
    import trimesh

    loaded = trimesh.load(str(path), force="scene", process=False)
    if isinstance(loaded, trimesh.Scene):
        if not loaded.geometry:
            raise ValueError("O GLB não contém geometrias.")
        mesh = loaded.dump(concatenate=True)
    elif isinstance(loaded, trimesh.Trimesh):
        mesh = loaded
    else:
        raise ValueError("Formato de malha não reconhecido pelo trimesh.")

    # Keep source coordinates in float64 until the normalized coordinates enter
    # the GPU. This avoids losing small meshes translated far from the origin.
    vertices = np.asarray(mesh.vertices, dtype=np.float64)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        raise ValueError("A malha precisa conter pelo menos três vértices 3D.")
    if faces.ndim != 2 or faces.shape[1] != 3 or len(faces) < 1:
        raise ValueError("A malha precisa conter faces trianguladas.")
    if not np.isfinite(vertices).all() or faces.min() < 0 or faces.max() >= len(vertices):
        raise ValueError("A malha contém coordenadas ou índices de face inválidos.")
    return mesh, vertices, faces


def _refine(mesh_path: Path, output_path: Path, resolution: int) -> int:
    import numpy as np
    import torch
    import trimesh
    from atom3d import MeshBVH
    from atom3d.grid import OctreeIndexer
    from faithcontour import FCTDecoder, FCTEncoder

    if resolution not in RESOLUTIONS:
        raise ValueError("A resolução aceita somente 128, 256 ou 512.")
    if not mesh_path.is_file() or mesh_path.suffix.lower() != ".glb":
        raise ValueError("A entrada deve ser um arquivo GLB existente.")
    if mesh_path.resolve() == output_path.resolve():
        raise ValueError("O arquivo de saída não pode substituir a malha de entrada.")

    print("FAITHC_STAGE: carregando GLB e aplicando transformações da cena", flush=True)
    source_mesh, source_vertices, source_faces = _load_world_mesh(mesh_path)
    center, scale = _coordinate_frame(source_vertices.min(axis=0), source_vertices.max(axis=0))
    normalized_values = _normalize_vertices(source_vertices, np.asarray(center, dtype=np.float64), scale)
    triangles = normalized_values[source_faces]
    double_areas = np.linalg.norm(
        np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]),
        axis=1,
    )
    valid_faces = np.isfinite(double_areas) & (double_areas > 1e-12)
    if not valid_faces.any():
        raise ValueError("A malha não contém faces não degeneradas para codificar.")
    source_faces = source_faces[valid_faces]
    normalized_values = np.asarray(normalized_values, dtype=np.float32)
    normalized_vertices = torch.as_tensor(normalized_values, dtype=torch.float32, device="cuda")
    faces = torch.as_tensor(source_faces, dtype=torch.long, device="cuda")
    bounds = torch.tensor([[-1.0, -1.0, -1.0], [1.0, 1.0, 1.0]], dtype=torch.float32, device="cuda")

    print(f"FAITHC_STAGE: codificando FCT em resolução {resolution}", flush=True)
    octree = OctreeIndexer(max_level=int(math.log2(resolution)), bounds=bounds, device="cuda")
    # Match Atom3d's upstream demo/API: MeshBVH receives vertices and faces;
    # the input tensors already live on the CUDA device.
    bvh = MeshBVH(normalized_vertices, faces)
    encoder = FCTEncoder(bvh, octree, device="cuda")
    min_level = min(4, max(1, int(math.log2(resolution)) - 1))
    encoded = encoder.encode(
        min_level=min_level,
        compute_flux=True,
        clamp_anchors=True,
    )

    print("FAITHC_STAGE: decodificando malha", flush=True)
    decoder = FCTDecoder(resolution=resolution, bounds=bounds, device="cuda")
    decoded = decoder.decode_from_result(encoded)
    torch.cuda.synchronize()

    decoded_vertices = decoded.vertices.detach().cpu().numpy()
    decoded_faces = decoded.faces.detach().cpu().numpy()
    world_vertices = _restore_vertices(
        decoded_vertices.astype(np.float64, copy=False),
        np.asarray(center, dtype=np.float64),
        scale,
    )
    if world_vertices.size == 0 or decoded_faces.size == 0:
        raise ValueError("FaithC não reconstruiu faces e vértices.")
    if not np.isfinite(world_vertices).all():
        raise ValueError("FaithC produziu coordenadas não finitas.")

    geometry = trimesh.Trimesh(vertices=world_vertices, faces=decoded_faces, process=False)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".part")
    print("FAITHC_STAGE: exportando GLB de geometria sem UV/PBR", flush=True)
    payload = geometry.export(file_type="glb")
    if not isinstance(payload, bytes) or len(payload) < 20 or payload[:4] != b"glTF":
        raise ValueError("Trimesh não produziu um GLB binário válido.")
    temporary_path.write_bytes(payload)
    os.replace(temporary_path, output_path)
    print(
        f"FAITHC_STAGE: concluído ({len(world_vertices)} vértices, {len(decoded_faces)} faces); "
        f"bounds origem={source_mesh.bounds.tolist()}",
        flush=True,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.action == "probe":
        return _probe()
    try:
        return _refine(args.mesh, args.output, args.resolution)
    except Exception as exc:
        print(f"FAITHC_ERROR: {type(exc).__name__}: {str(exc)[:700]}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
