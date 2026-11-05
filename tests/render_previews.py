# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Render preview stills / animations of every effect variant with Cycles.

Runs headless with the ``bpy`` module (pip install bpy) or Blender:

    python tests/render_previews.py --out docs/media [--frames 1,25] [--gif] [--only RAIN,SNOW]
    blender -b -P tests/render_previews.py -- --out docs/media

Each scene is staged with a camera, sun, sky colour and ground, then the
effect is created exactly as the *Create* buttons do (registry.create).
"""

import argparse
import math
import os
import sys
import time

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import gold_extended.effects  # noqa: E402,F401  (registers effects)
from gold_extended.core import registry  # noqa: E402

# name: (effect, preset, camera loc, camera rot X deg, sky, ground, extra)
SCENES = {
    'RAIN': ('PARTICLES', 'Rain', (0, -13, 2.6), 84, (0.3, 0.34, 0.4), (0.16, 0.18, 0.2), {}),
    'SNOW': ('PARTICLES', 'Snow', (0, -13, 2.6), 84, (0.38, 0.42, 0.5), (0.8, 0.82, 0.88), {}),
    'SAND': ('PARTICLES', 'Sand', (0, -13, 2.0), 86, (0.75, 0.6, 0.42), (0.7, 0.55, 0.35), {}),
    'DUST': ('PARTICLES', 'Dust Motes', (0, -9, 2.2), 86, (0.05, 0.045, 0.04), (0.06, 0.05, 0.04), {}),
    'DIRT': ('PARTICLES', 'Dirt', (0, -13, 2.6), 84, (0.62, 0.56, 0.48), (0.35, 0.28, 0.2), {}),
    'CLOUD': ('CLOUD', 'Cumulus', (0, -15, 3.2), 95, (0.33, 0.55, 0.85), None, {}),
    'GRASS': ('GRASS', 'Meadow', (0, -4.2, 1.1), 76, (0.55, 0.7, 0.85), (0.12, 0.2, 0.08), {}),
    'FOLIAGE': ('FOLIAGE', 'Summer Bush', (0, -5.2, 1.4), 88, (0.6, 0.72, 0.85), (0.2, 0.25, 0.12), {}),
    'HAIR': ('HAIR', 'Brown Locks', (0, -2.4, 0.15), 90, (0.5, 0.48, 0.45), None, {}),
    'FIRE': ('FIRE', 'Campfire', (0, -4.2, 1.0), 84, (0.02, 0.02, 0.03), (0.05, 0.04, 0.035), {}),
    'WATER': ('WATER', 'Lake', (0, -7.5, 2.6), 72, (0.62, 0.75, 0.88), None, {}),
}


def stage(name):
    eff, preset, cam_loc, cam_rx, sky, ground, _extra = SCENES[name]
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.use_denoising = False
    sc.render.fps = 24
    world = bpy.data.worlds.new('Sky')
    sc.world = world
    bg = world.node_tree.nodes.get('Background')
    bg.inputs[0].default_value = (*sky, 1.0)
    bg.inputs[1].default_value = 1.0
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = cam_loc
    cam.rotation_euler = (math.radians(cam_rx), 0, 0)
    sun = bpy.data.objects.new('Sun', bpy.data.lights.new('Sun', 'SUN'))
    sc.collection.objects.link(sun)
    sun.rotation_euler = (math.radians(45), math.radians(15), math.radians(35))
    sun.data.energy = 3.0
    if ground is not None:
        me = bpy.data.meshes.new('Ground')
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=40.0)
        bm.to_mesh(me)
        bm.free()
        g = bpy.data.objects.new('Ground', me)
        sc.collection.objects.link(g)
        mat = bpy.data.materials.new('Ground')
        mat.diffuse_color = (*ground, 1.0)
        if hasattr(mat, 'use_nodes') and not mat.use_nodes:
            mat.use_nodes = True
        mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*ground, 1.0)
        me.materials.append(mat)
    if name == 'FIRE':
        # fire is lit by itself: add a warm point light for the ground
        pl = bpy.data.objects.new('Glow', bpy.data.lights.new('Glow', 'POINT'))
        pl.data.energy = 150.0
        pl.data.color = (1.0, 0.55, 0.2)
        pl.location = (0, 0, 0.6)
        sc.collection.objects.link(pl)
        sun.data.energy = 0.0
    obj, mod = registry.create(bpy.context, eff, preset)
    if eff in ('GRASS', 'WATER'):
        # Surfaces: make the generated surface large enough for the camera.
        surf = obj.parent
        surf.scale = (1.6, 1.6, 1.0) if eff == 'GRASS' else (1.4, 1.4, 1.0)
        if eff == 'GRASS':
            surf.hide_render = False
            gm = bpy.data.materials.new('Soil')
            gm.diffuse_color = (*ground, 1.0)
            if hasattr(gm, 'use_nodes') and not gm.use_nodes:
                gm.use_nodes = True
            gm.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = (*ground, 1.0)
            surf.data.materials.append(gm)
    if eff in ('HAIR', 'FIRE'):
        surf = obj.parent
        mat = bpy.data.materials.new('Skin' if eff == 'HAIR' else 'Logs')
        col = (0.75, 0.55, 0.45, 1.0) if eff == 'HAIR' else (0.08, 0.05, 0.03, 1.0)
        mat.diffuse_color = col
        if hasattr(mat, 'use_nodes') and not mat.use_nodes:
            mat.use_nodes = True
        mat.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value = col
        surf.data.materials.append(mat)
    return obj, mod


def render(name, frames, out_dir, res=(480, 270), samples=24, loop=0):
    obj, mod = stage(name)
    if loop:
        registry.set_param(mod, 'Loop Frames', loop)
    sc = bpy.context.scene
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.cycles.samples = samples
    paths = []
    for f in frames:
        sc.frame_set(f)
        path = os.path.join(out_dir, f'{name.lower()}_{f:04d}.png')
        sc.render.filepath = path
        t0 = time.time()
        bpy.ops.render.render(write_still=True)
        print(f'{name} frame {f}: {time.time() - t0:.1f}s -> {path}', flush=True)
        paths.append(path)
    return paths


def make_gif(paths, out, fps=12):
    from PIL import Image
    frames = [Image.open(p).convert('RGB') for p in paths]
    pal = [f.quantize(colors=96, method=Image.Quantize.MEDIANCUT) for f in frames]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=int(1000 / fps), loop=0, optimize=True)
    return out


def contact_sheet(paths, out, cols=4, label=True):
    from PIL import Image, ImageDraw
    ims = [Image.open(p).convert('RGB') for p in paths]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new('RGB', (w * cols, h * rows), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    for i, (im, p) in enumerate(zip(ims, paths)):
        x, y = (i % cols) * w, (i // cols) * h
        sheet.paste(im, (x, y))
        if label:
            draw.rectangle([x, y, x + 120, y + 18], fill=(0, 0, 0))
            draw.text((x + 4, y + 3), os.path.basename(p).split('_')[0].upper(), fill=(255, 255, 255))
    sheet.save(out)
    return out


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'media'))
    ap.add_argument('--frames', default='12')
    ap.add_argument('--only', default='')
    ap.add_argument('--gif', action='store_true', help='render frames 1..N and assemble a GIF per effect')
    ap.add_argument('--gif-frames', type=int, default=24)
    ap.add_argument('--res', default='480x270')
    ap.add_argument('--samples', type=int, default=24)
    ap.add_argument('--sheet', default='')
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    res = tuple(int(x) for x in args.res.split('x'))
    names = [n for n in SCENES if not args.only or n in args.only.split(',')]
    stills = []
    for name in names:
        if args.gif:
            frames = list(range(1, args.gif_frames + 1))
            paths = render(name, frames, args.out, res, args.samples, loop=args.gif_frames)
            make_gif(paths, os.path.join(args.out, f'{name.lower()}.gif'))
            stills.append(paths[len(paths) // 2])
            for p in paths:
                if p != paths[len(paths) // 2]:
                    os.remove(p)
        else:
            stills += render(name, [int(f) for f in args.frames.split(',')], args.out, res, args.samples)
    if args.sheet:
        contact_sheet(stills, args.sheet)


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    main(argv)
