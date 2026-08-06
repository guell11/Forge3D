from __future__ import annotations

"""Forge3D Blender worker for genuine, GLB-to-GLB derived operations.

It never calls the image-to-3D pipeline.  Every action starts by importing the
parent GLB and produces a separate GLB.  Retexture is deliberately unavailable
until a PBR rebake worker is verified; accepting it with a new TRELLIS run
would silently replace the user's geometry.
"""

import argparse
import json
import sys
from pathlib import Path


_CAPABILITIES = {
    "split": {
        "available": True,
        "preserves_pbr": True,
        "detail": "Separa componentes conectados do GLB atual e preserva slots de materiais/texturas.",
    },
    "simplify": {
        "available": True,
        "preserves_pbr": True,
        "detail": "Decimate collapse no GLB atual com teto de triângulos e preservação de UV/material.",
    },
    "remesh": {
        "available": True,
        "preserves_pbr": True,
        "detail": "Voxel remesh experimental no GLB atual com transferência aproximada de UV/material. Reconstrói topologia, pode suavizar detalhe e sempre preserva o original.",
    },
    "retexture": {
        "available": False,
        "preserves_pbr": False,
        "detail": "Indisponível: requer um worker de rebake PBR que projete/bakeie texturas na malha atual. Não inicia uma nova geração 2D→3D.",
    },
    "transform": {
        "available": True,
        "preserves_pbr": True,
        "detail": "Aplica transformação à malha atual sem alterar sua geometria ou materiais.",
    },
}


def _arguments() -> argparse.Namespace:
    values = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", nargs="?", choices=tuple(_CAPABILITIES))
    parser.add_argument("--probe", action="store_true")
    parser.add_argument("--input")
    parser.add_argument("--output")
    parser.add_argument("--parameters")
    parser.add_argument("--image")
    args = parser.parse_args(values)
    if not args.probe and (not args.operation or not args.input or not args.output or not args.parameters):
        parser.error("operation, --input, --output e --parameters são obrigatórios")
    return args


def _mesh_objects(bpy):
    return [item for item in bpy.context.scene.objects if item.type == "MESH" and not item.name.startswith("__forge_source_")]


def _triangle_count(objects) -> int:
    return sum(sum(max(0, len(polygon.vertices) - 2) for polygon in item.data.polygons) for item in objects)


def _activate_only(bpy, item) -> None:
    bpy.ops.object.select_all(action="DESELECT")
    item.select_set(True)
    bpy.context.view_layer.objects.active = item


def _clone_source(bpy, item):
    clone = item.copy()
    clone.data = item.data.copy()
    clone.name = "__forge_source_" + item.name
    clone.hide_render = True
    bpy.context.collection.objects.link(clone)
    return clone


def _remove_sources(bpy, sources) -> None:
    for source in sources:
        if source and source.name in bpy.data.objects:
            bpy.data.objects.remove(source, do_unlink=True)


def _copy_material_slots(source, target) -> None:
    target.data.materials.clear()
    for material in source.data.materials:
        target.data.materials.append(material)


def _transfer_material_indices(source, target) -> None:
    """Assign each remeshed face the nearest source material slot.

    Blender's Data Transfer modifier supports UV loop layers but not material
    indices.  Keeping the material slots alone would therefore make a
    multi-material GLB appear textured while assigning every face to slot 0.
    The BVH lookup is deliberately explicit and fails loudly if it cannot map
    the remeshed surface back to its current GLB.
    """

    if not source.data.polygons or not target.data.polygons:
        raise RuntimeError("Não há polígonos suficientes para transferir materiais no remesh.")
    if not source.data.materials:
        return
    if len(source.data.materials) == 1:
        # The common TRELLIS GLB has one PBR material. A nearest-face BVH query
        # for every remeshed polygon cannot change the answer and made a normal
        # 150K-face remesh spend minutes in Python. Assign slot 0 in bulk.
        target.data.polygons.foreach_set("material_index", [0] * len(target.data.polygons))
        return
    from mathutils.bvhtree import BVHTree

    bvh = BVHTree.FromPolygons(
        [vertex.co.copy() for vertex in source.data.vertices],
        [tuple(polygon.vertices) for polygon in source.data.polygons],
        all_triangles=False,
    )
    for polygon in target.data.polygons:
        nearest = bvh.find_nearest(polygon.center)
        if nearest is None:
            raise RuntimeError("Não foi possível mapear uma face do remesh ao material de origem.")
        source_polygon_index = nearest[2]
        polygon.material_index = source.data.polygons[source_polygon_index].material_index


def _transfer_pbr_data(bpy, source, target) -> None:
    """Transfer UV loops and material indices from the original GLB mesh.

    Voxel remesh changes topology, so texture pixels remain useful only after
    a nearest/interpolated UV transfer. If Blender cannot perform it we raise;
    exporting a geometry-only GLB under a PBR-preserving label would be wrong.
    """

    _copy_material_slots(source, target)
    _transfer_material_indices(source, target)
    if not source.data.uv_layers:
        return
    if not target.data.uv_layers:
        target.data.uv_layers.new(name=source.data.uv_layers.active.name if source.data.uv_layers.active else "UVMap")
    # Blender's POLYINTERP_NEAREST Data Transfer modifier took more than
    # 15 minutes on a normal 143K-face TRELLIS GLB. glTF/xatlas already splits
    # vertices at UV seams, so a nearest-source-vertex KD tree preserves the
    # established UV islands while keeping this operation practical.
    from mathutils.kdtree import KDTree

    source_layer = source.data.uv_layers.active or source.data.uv_layers[0]
    source_uvs = [None] * len(source.data.vertices)
    for loop in source.data.loops:
        if source_uvs[loop.vertex_index] is None:
            source_uvs[loop.vertex_index] = source_layer.data[loop.index].uv.copy()
    tree = KDTree(len(source.data.vertices))
    for vertex in source.data.vertices:
        tree.insert(vertex.co, vertex.index)
    tree.balance()
    target_vertex_uvs = []
    for vertex in target.data.vertices:
        _position, source_index, _distance = tree.find(vertex.co)
        uv = source_uvs[source_index]
        target_vertex_uvs.append(uv if uv is not None else (0.0, 0.0))
    flattened_uvs = []
    for loop in target.data.loops:
        uv = target_vertex_uvs[loop.vertex_index]
        flattened_uvs.extend((float(uv[0]), float(uv[1])))
    target_layer = target.data.uv_layers.active or target.data.uv_layers[0]
    target_layer.data.foreach_set("uv", flattened_uvs)
    target.data.update()
    if not target.data.uv_layers:
        raise RuntimeError("Remesh concluiu sem UV após transferência PBR.")


def _voxel_size(item, parameters: dict) -> float:
    requested = parameters.get("voxel_size")
    if isinstance(requested, (int, float)) and requested > 0:
        return float(requested)
    target = parameters.get("target_triangles")
    target = int(target) if isinstance(target, int) and target >= 100 else 50_000
    max_dimension = max((float(value) for value in item.dimensions), default=1.0)
    # A safe topology-density heuristic, not a claimed exact triangle target.
    # Voxel surfaces grow roughly with resolution squared. The previous 0.8
    # coefficient routinely produced several times the requested density and
    # made UV transfer exceed the operation timeout. This conservative value
    # keeps enough headroom for the final exact simplify pass.
    return max(0.0001, max_dimension / max(32.0, (target**0.5) * 0.20))


def _simplify_to_target(bpy, objects, target: int) -> int:
    current = _triangle_count(objects)
    if target < 100 or target >= current:
        raise ValueError(f"target_triangles deve estar entre 100 e {max(100, current - 1)}")
    for attempt in range(3):
        current = _triangle_count(objects)
        if current <= int(target * 1.01):
            break
        ratio = max(0.0001, min(1.0, target / current))
        for item in objects:
            _activate_only(bpy, item)
            modifier = item.modifiers.new(name=f"Forge3D target pass {attempt + 1}", type="DECIMATE")
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            modifier.use_collapse_triangulate = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
    final_triangles = _triangle_count(objects)
    if final_triangles > int(target * 1.01):
        raise RuntimeError(f"Blender não atingiu o teto com tolerância de 1%: {final_triangles} > {target}")
    return final_triangles


def _remesh(bpy, objects, parameters: dict) -> None:
    sources = [_clone_source(bpy, item) for item in objects]
    try:
        for item, source in zip(objects, sources, strict=True):
            _activate_only(bpy, item)
            print(f"FORGE3D_OPERATION: voxel remesh em {item.name}", flush=True)
            modifier = item.modifiers.new(name="Forge3D voxel remesh", type="REMESH")
            modifier.mode = "VOXEL"
            modifier.voxel_size = _voxel_size(item, parameters)
            modifier.use_smooth_shade = True
            bpy.ops.object.modifier_apply(modifier=modifier.name)
            print(f"FORGE3D_OPERATION: transferindo UV e material PBR para {item.name}", flush=True)
            _transfer_pbr_data(bpy, source, item)
        target = parameters.get("target_triangles")
        if isinstance(target, int) and target >= 100 and _triangle_count(objects) > target:
            final_triangles = _simplify_to_target(bpy, objects, target)
            print(f"FORGE3D_OPERATION: remesh + limite de triangulos={final_triangles}", flush=True)
        else:
            print(f"FORGE3D_OPERATION: voxel remesh triangulos={_triangle_count(objects)}", flush=True)
    finally:
        _remove_sources(bpy, sources)


def _export_glb(bpy, output: Path) -> None:
    objects = _mesh_objects(bpy)
    bpy.ops.object.select_all(action="DESELECT")
    for item in objects:
        item.select_set(True)
    if objects:
        bpy.context.view_layer.objects.active = objects[0]
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(output), export_format="GLB", export_apply=True, use_selection=True)
    if not output.is_file() or output.stat().st_size < 20 or output.read_bytes()[:4] != b"glTF":
        raise RuntimeError("Blender não produziu um GLB válido")


def main() -> int:
    args = _arguments()
    import bpy  # Available only inside the pinned Blender runtime.

    if args.probe:
        print("FORGE3D_OPERATION_CAPS:" + json.dumps({"operations": _CAPABILITIES}, ensure_ascii=False), flush=True)
        return 0
    if args.operation == "retexture":
        raise ValueError(_CAPABILITIES["retexture"]["detail"])

    source = Path(args.input).resolve()
    output = Path(args.output).resolve()
    parameters = json.loads(Path(args.parameters).read_text(encoding="utf-8"))
    if not source.is_file() or source.read_bytes()[:4] != b"glTF":
        raise ValueError("GLB de entrada inválido")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    objects = _mesh_objects(bpy)
    if not objects:
        raise ValueError("O GLB não contém objetos de malha")

    if args.operation == "split":
        for item in list(objects):
            _activate_only(bpy, item)
            bpy.ops.object.mode_set(mode="EDIT")
            bpy.ops.mesh.select_all(action="SELECT")
            bpy.ops.mesh.separate(type="LOOSE")
            bpy.ops.object.mode_set(mode="OBJECT")
        print(f"FORGE3D_OPERATION: componentes separados={len(_mesh_objects(bpy))}", flush=True)
    elif args.operation == "simplify":
        target = int(parameters.get("target_triangles") or 0)
        final_triangles = _simplify_to_target(bpy, objects, target)
        print(f"FORGE3D_OPERATION: triangulos={final_triangles} alvo={target}", flush=True)
    elif args.operation == "remesh":
        _remesh(bpy, objects, parameters)
    elif args.operation == "transform":
        spec = parameters.get("transform") or {}
        translation = tuple(float(v) for v in spec.get("translation", (0, 0, 0)))
        rotation = tuple(float(v) for v in spec.get("rotation_degrees", (0, 0, 0)))
        scale = tuple(float(v) for v in spec.get("scale", (1, 1, 1)))
        if len(translation) != 3 or len(rotation) != 3 or len(scale) != 3 or any(value == 0 for value in scale):
            raise ValueError("Transformação inválida: posição, rotação e escala precisam ter três valores; escala não pode ser zero.")
        from math import radians
        from mathutils import Euler, Matrix

        transform_matrix = (
            Matrix.Translation(translation)
            @ Euler(tuple(radians(value) for value in rotation), "XYZ").to_matrix().to_4x4()
            @ Matrix.Diagonal((*scale, 1.0))
        )
        for item in objects:
            item.matrix_world = transform_matrix @ item.matrix_world
        print("FORGE3D_OPERATION: transformacao aplicada", flush=True)

    _export_glb(bpy, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
