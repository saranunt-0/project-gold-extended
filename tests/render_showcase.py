# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Visual-capability showcase renders (documentation images).

* ``looks``     – every Look preset on the same foliage bush
* ``features``  – each visual control isolated (vibrance, chromatic fringe,
                  iridescence, sheen, sheer, edge darkening, posterize, dry brush)
* ``sweeps``    – hyper-parameter sweeps showing how one control maps to the
                  result (wind, motion stretch, clumping, choppiness)

    python tests/render_showcase.py --out docs/media [--only looks,features,sweeps]
"""

import argparse
import os
import sys

import bpy

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'tests'))

import render_previews as rp  # noqa: E402
from gold_extended.core import registry, shading  # noqa: E402

FEATURES = [
    ('Baseline', {}),
    ('Vibrance +1', {'Vibrance': 1.0}),
    ('Vibrance -1', {'Vibrance': -1.0}),
    ('Chromatic Fringe', {'Fringe': 1.0, 'Fringe Hue': 0.3, 'Fringe Width': 0.8}),
    ('Iridescence', {'Iridescence': 1.0, 'Iridescence Cycles': 2.0}),
    ('Sheen', {'Sheen': 1.0, 'Sheen Falloff': 0.5, 'Sheen Tint': (1.0, 0.9, 0.6, 1.0)}),
    ('Sheer', {'Sheer': 1.0}),
    ('Edge Darken', {'Edge Darken': 1.0}),
    ('Posterize 3', {'Posterize': 3.0, 'Shading': 0.0}),
    ('Dry Brush', {'Dry Brush': 0.6}),
    ('Hue Shift', {'Hue Shift': 0.35}),
    ('Emission', {'Emission': 3.0}),
]

SWEEPS = {
    'GRASS': ('Wind Strength', [0.0, 0.3, 0.8]),
    'RAIN': ('Motion Stretch', [0.0, 0.03, 0.1]),
    'HAIR': ('Clumping', [0.0, 0.5, 1.0]),
    'WATER': ('Choppiness', [0.0, 0.8, 1.6]),
}


def _render(path, res=(320, 180), samples=16, frame=12):
    sc = bpy.context.scene
    sc.frame_set(frame)
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.cycles.samples = samples
    sc.render.filepath = path
    bpy.ops.render.render(write_still=True)
    return path


def _label(path, text):
    from PIL import Image, ImageDraw
    im = Image.open(path).convert('RGB')
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 8 + 6 * len(text), 16], fill=(0, 0, 0))
    d.text((4, 2), text, fill=(255, 255, 255))
    im.save(path)
    return path


def _sheet(paths, out, cols):
    from PIL import Image
    ims = [Image.open(p) for p in paths]
    w, h = ims[0].size
    rows = (len(ims) + cols - 1) // cols
    sheet = Image.new('RGB', (w * cols, h * rows), (15, 15, 15))
    for i, im in enumerate(ims):
        sheet.paste(im, ((i % cols) * w, (i // cols) * h))
    sheet.save(out)
    for p in paths:
        os.remove(p)
    return out


def _foliage_close():
    obj, mod = rp.stage('FOLIAGE')
    registry.set_param(mod, 'Leaf Size', 0.22)
    registry.set_param(mod, 'Density', 35.0)
    for mat in bpy.data.materials:
        if mat.get('GOLDX'):
            shading.set_brush_style(mat, 'Bristle Dab')
    cam = bpy.context.scene.camera
    cam.location = (0.0, -3.6, 1.3)
    return obj, mod


def looks(out):
    paths = []
    for name in shading.LOOK_PRESETS:
        _foliage_close()
        for mat in bpy.data.materials:
            if mat.get('GOLDX'):
                values = dict(registry.EFFECTS['FOLIAGE'].materials[0].look)
                values.update(shading.LOOK_PRESETS[name])
                shading.apply_look(mat, values, reset=True)
        paths.append(_label(_render(os.path.join(out, f'_look_{len(paths)}.png')), name))
    return _sheet(paths, os.path.join(out, 'look_presets.png'), 5)


def features(out):
    paths = []
    for label, values in FEATURES:
        _foliage_close()
        for mat in bpy.data.materials:
            if mat.get('GOLDX'):
                shading.apply_look(mat, values)
        paths.append(_label(_render(os.path.join(out, f'_feat_{len(paths)}.png')), label))
    return _sheet(paths, os.path.join(out, 'visual_features.png'), 4)


def sweeps(out):
    paths = []
    for scene_name, (param, values) in SWEEPS.items():
        for v in values:
            _obj, mod = rp.stage(scene_name)
            registry.set_param(mod, param, v)
            paths.append(_label(_render(os.path.join(out, f'_sweep_{len(paths)}.png')),
                                f'{scene_name.title()}: {param} = {v}'))
    return _sheet(paths, os.path.join(out, 'parameter_sweeps.png'), 3)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'media'))
    ap.add_argument('--only', default='looks,features,sweeps')
    args = ap.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    for job in args.only.split(','):
        print('wrote', {'looks': looks, 'features': features, 'sweeps': sweeps}[job](args.out), flush=True)


if __name__ == '__main__':
    main(sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:])
