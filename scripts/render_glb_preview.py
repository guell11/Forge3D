"""Render a deterministic Forge3D GLB preview with Blender.

Usage:
  blender --background --factory-startup --python render_glb_preview.py -- input.glb output.png
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def look_at(camera: bpy.types.Object, target: Vector) -> None:
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    if len(args) != 2:
        raise SystemExit("expected input.glb output.png")
    source, output = map(Path, args)
    if not source.is_file():
        raise FileNotFoundError(source)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("GLB has no mesh objects")

    corners = [obj.matrix_world @ Vector(corner) for obj in meshes for corner in obj.bound_box]
    low = Vector((min(point.x for point in corners), min(point.y for point in corners), min(point.z for point in corners)))
    high = Vector((max(point.x for point in corners), max(point.y for point in corners), max(point.z for point in corners)))
    center = (low + high) * 0.5
    extent = high - low
    radius = max(extent.x, extent.y, extent.z) * 0.5

    camera_data = bpy.data.cameras.new("Forge3D Preview Camera")
    camera = bpy.data.objects.new("Forge3D Preview Camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.lens = 58
    camera_data.sensor_width = 36
    distance = max(radius * 3.25, 1.0)
    camera.location = center + Vector((distance * 0.78, -distance, distance * 0.58))
    look_at(camera, center + Vector((0, 0, extent.z * 0.03)))
    bpy.context.scene.camera = camera

    world = bpy.data.worlds.new("Forge3D Preview World")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.018, 0.022, 0.03, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.38
    bpy.context.scene.world = world

    for name, energy, size, offset, color in (
        ("Key", 1250, radius * 2.5, (1.4, -1.8, 2.2), (1.0, 0.91, 0.82)),
        ("Fill", 850, radius * 2.0, (-1.8, -0.5, 1.0), (0.67, 0.77, 1.0)),
        ("Rim", 1000, radius * 1.7, (0.4, 1.8, 2.0), (0.77, 0.84, 1.0)),
    ):
        light_data = bpy.data.lights.new(name, "AREA")
        light_data.energy = energy
        light_data.shape = "DISK"
        light_data.size = max(size, 0.5)
        light_data.color = color
        light = bpy.data.objects.new(name, light_data)
        bpy.context.collection.objects.link(light)
        light.location = center + Vector(offset) * max(radius, 0.5)
        look_at(light, center)

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x = 720
    scene.render.resolution_y = 720
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.render.filepath = str(output)
    scene.render.image_settings.color_depth = "8"
    scene.view_settings.look = "AgX - Medium High Contrast"
    output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.render.render(write_still=True)


if __name__ == "__main__":
    main()
