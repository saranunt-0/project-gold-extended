# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Brush styles: built-in procedural styles + bridge to the base library.

A *brush style* in Project Gold is a shader node group named
``BSBST-BS.<Category>.<Type>.<Name>`` with a single ``Value`` output (the
paint mask) that reads the ``brush_stroke.*`` attributes.  The base add-on
ships oil-paint styles in ``styles/*.blend`` inside its resource directory.

Gold Extended

* generates its own procedural styles (category ``Gold FX``) tuned for
  effects – they follow the same naming, so the base add-on's brush browser
  lists them too;
* discovers and imports the base library styles when Brushstroke Tools is
  installed (or when a library path is set in the preferences).
"""

from __future__ import annotations

import os
import platform
from dataclasses import dataclass
from pathlib import Path

import bpy

from .nodes import TreeBuilder, new_socket

PREFIX = 'BSBST-BS'
BUILTIN_CATEGORY = 'Gold FX'


@dataclass
class BrushStyle:
    name: str          # display name, e.g. "Soft Dab"
    id_name: str       # node group name
    filepath: str = ''  # '' for built-in / local
    category: str = ''
    type: str = ''


# --------------------------------------------------------------------------
# Built-in procedural styles
# --------------------------------------------------------------------------

def _attr(tb: TreeBuilder, name, out='Vector'):
    n = tb.node('ShaderNodeAttribute', attribute_type='GEOMETRY')
    n.n.attribute_name = name
    return n[out]


def _common(tb):
    uv = _attr(tb, 'brush_stroke.uv')
    sid = _attr(tb, 'brush_stroke.id')
    dim = _attr(tb, 'brush_stroke.dimension')
    u, v, _ = tb.sep(uv)
    w, l, _ = tb.sep(dim)
    aspect = l / tb.max(w, 1e-4)
    return uv, sid, u, v, aspect


def _style_soft_dab(tb):
    """Round dab with a painterly, noise-distorted edge."""
    uv, sid, u, v, aspect = _common(tb)
    c = tb.combine((u - 0.5) * 2.0, (v - 0.5) * 2.0, 0.0)
    nfac, _ = tb.noise(c + sid * 10.0, scale=tb.I('Distortion Scale'), detail=3.0, roughness=0.6)
    r = tb.length(c) + (nfac - 0.5) * tb.I('Distortion')
    return 1.0 - tb.smoothstep(tb.I('Fill'), 1.0, r)


def _style_bristle_dab(tb):
    """Round dab broken up by bristle streaks along the stroke."""
    uv, sid, u, v, aspect = _common(tb)
    c = tb.combine((u - 0.5) * 2.0, (v - 0.5) * 2.0, 0.0)
    nfac, _ = tb.noise(c + sid * 10.0, scale=3.0, detail=2.0)
    r = tb.length(c) + (nfac - 0.5) * 0.3
    shape = 1.0 - tb.smoothstep(tb.I('Fill'), 1.0, r)
    bfac, _ = tb.noise(tb.combine(u * tb.I('Bristles'), v * 0.6, tb.sep(sid)[0] * 50.0), scale=1.0, detail=4.0,
                       roughness=0.7)
    bristle = tb.smoothstep(tb.I('Dryness') * 0.6 + 0.2, tb.I('Dryness') * 0.6 + 0.45, bfac)
    return shape * tb.lerp(1.0, bristle, tb.I('Bristle Strength'))


def _style_streak(tb):
    """Elongated stroke with tapered head/tail and dry-brush bristles."""
    uv, sid, u, v, aspect = _common(tb)
    across = tb.abs((u - 0.5) * 2.0)
    taper = tb.smoothstep(0.0, tb.I('Head'), v) * (1.0 - tb.smoothstep(1.0 - tb.I('Tail'), 1.0, v))
    # width narrows toward the tail tip
    width = tb.lerp(1.0, 0.35, tb.smoothstep(0.4, 1.0, v) * tb.I('Tail'))
    nfac, _ = tb.noise(tb.combine(u * 2.0, v * aspect * 0.5, tb.sep(sid)[1] * 30.0), scale=2.0, detail=2.0)
    edge = across / tb.max(width, 0.05) + (nfac - 0.5) * 0.4
    body = (1.0 - tb.smoothstep(tb.I('Fill'), 1.0, edge)) * taper
    bfac, _ = tb.noise(tb.combine(u * tb.I('Bristles'), v * 0.8, tb.sep(sid)[0] * 40.0), scale=1.0, detail=5.0,
                       roughness=0.65)
    dry = tb.smoothstep(tb.I('Dryness') * 0.55 + 0.2, tb.I('Dryness') * 0.55 + 0.4, bfac)
    return body * tb.lerp(1.0, dry, tb.I('Bristle Strength'))


def _style_flame(tb):
    """Tear-drop flame tongue with an inner lick."""
    uv, sid, u, v, aspect = _common(tb)
    across = tb.abs((u - 0.5) * 2.0)
    # widest near the bottom, pointy tip
    prof = tb.pow(tb.sin(tb.min(v * 1.15, 1.0) * 3.14159) + 0.0001, 0.6) * (1.0 - tb.pow(v, 3.0) * 0.6)
    nfac, _ = tb.noise(tb.combine(u * 1.5, v * 3.0, tb.sep(sid)[2] * 20.0), scale=tb.I('Wobble Scale'), detail=2.0)
    edge = across / tb.max(prof, 0.02) + (nfac - 0.5) * tb.I('Wobble')
    outer = 1.0 - tb.smoothstep(tb.I('Fill'), 1.0, edge)
    inner = 1.0 - tb.smoothstep(0.1, 0.55, edge)
    return tb.clamp01(outer * 0.75 + inner * 0.35 * tb.I('Core'))


def _style_puff(tb):
    """Cauliflower puff for clouds and smoke."""
    uv, sid, u, v, aspect = _common(tb)
    c = tb.combine((u - 0.5) * 2.0, (v - 0.5) * 2.0, 0.0)
    nfac, _ = tb.noise(c * 0.8 + sid * 7.0, scale=tb.I('Lobe Scale'), detail=1.0, roughness=0.4)
    r = tb.length(c) - (nfac - 0.5) * tb.I('Lobes')
    shape = 1.0 - tb.smoothstep(tb.I('Fill'), 1.0, r)
    gfac, _ = tb.noise(c * 4.0 + sid * 3.0, scale=2.0, detail=4.0)
    return shape * tb.lerp(1.0, tb.smoothstep(0.25, 0.6, gfac), tb.I('Breakup'))


def _style_leaf(tb):
    """Almond leaf/petal shape."""
    uv, sid, u, v, aspect = _common(tb)
    across = tb.abs((u - 0.5) * 2.0)
    prof = tb.pow(tb.sin(v * 3.14159) + 0.0001, tb.I('Roundness'))
    nfac, _ = tb.noise(tb.combine(u, v, tb.sep(sid)[0] * 9.0), scale=4.0, detail=2.0)
    edge = across / tb.max(prof, 0.02) + (nfac - 0.5) * 0.25
    shape = 1.0 - tb.smoothstep(tb.I('Fill'), 1.0, edge)
    vein = tb.smoothstep(0.0, 0.08, across)
    return shape * tb.lerp(1.0, vein, tb.I('Vein'))


def _style_scumble(tb):
    """Broken dry-brush patch (dirt, sand, foam)."""
    uv, sid, u, v, aspect = _common(tb)
    c = tb.combine((u - 0.5) * 2.0, (v - 0.5) * 2.0, 0.0)
    shape = 1.0 - tb.smoothstep(tb.I('Fill'), 1.0, tb.length(c))
    nfac, _ = tb.noise(c + sid * 11.0, scale=tb.I('Grain Scale'), detail=6.0, roughness=0.7)
    grain = tb.smoothstep(tb.I('Dryness'), tb.I('Dryness') + 0.15, nfac)
    return shape * grain


BUILTIN = {
    # name: (type, builder, [(input, default, min, max)])
    'Soft Dab': ('Dabs', _style_soft_dab,
                 [('Fill', 0.45, 0.0, 1.0), ('Distortion', 0.35, 0.0, 2.0), ('Distortion Scale', 2.5, 0.0, 20.0)]),
    'Bristle Dab': ('Dabs', _style_bristle_dab,
                    [('Fill', 0.55, 0.0, 1.0), ('Bristles', 12.0, 1.0, 64.0), ('Bristle Strength', 0.6, 0.0, 1.0),
                     ('Dryness', 0.35, 0.0, 1.0)]),
    'Streak': ('Brushstrokes', _style_streak,
               [('Fill', 0.5, 0.0, 1.0), ('Head', 0.15, 0.0, 1.0), ('Tail', 0.45, 0.0, 1.0),
                ('Bristles', 10.0, 1.0, 64.0), ('Bristle Strength', 0.5, 0.0, 1.0), ('Dryness', 0.3, 0.0, 1.0)]),
    'Flame Tongue': ('Brushstrokes', _style_flame,
                     [('Fill', 0.55, 0.0, 1.0), ('Wobble', 0.5, 0.0, 2.0), ('Wobble Scale', 2.0, 0.0, 20.0),
                      ('Core', 1.0, 0.0, 1.0)]),
    'Puff': ('Dabs', _style_puff,
             [('Fill', 0.35, 0.0, 1.0), ('Lobes', 0.55, 0.0, 2.0), ('Lobe Scale', 2.2, 0.0, 20.0),
              ('Breakup', 0.25, 0.0, 1.0)]),
    'Leaf': ('Dabs', _style_leaf,
             [('Fill', 0.6, 0.0, 1.0), ('Roundness', 0.7, 0.1, 3.0), ('Vein', 0.35, 0.0, 1.0)]),
    'Scumble': ('Patches', _style_scumble,
                [('Fill', 0.5, 0.0, 1.0), ('Grain Scale', 6.0, 0.0, 50.0), ('Dryness', 0.45, 0.0, 1.0)]),
}


def builtin_id_name(name):
    return f'{PREFIX}.{BUILTIN_CATEGORY}.{BUILTIN[name][0]}.{name}'


def ensure_builtin(name) -> bpy.types.ShaderNodeTree:
    id_name = builtin_id_name(name)
    ng = bpy.data.node_groups.get(id_name)
    if ng is not None:
        return ng
    typ, builder, inputs = BUILTIN[name]
    ng = bpy.data.node_groups.new(id_name, 'ShaderNodeTree')
    new_socket(ng, 'Value', 'OUTPUT', 'FLOAT')
    for nm, d, lo, hi in inputs:
        new_socket(ng, nm, 'INPUT', 'FLOAT', default=d, min=lo, max=hi)
    tb = TreeBuilder(ng)
    tb.output('Value', tb.clamp01(builder(tb)))
    tb.layout()
    return ng


# --------------------------------------------------------------------------
# Base library discovery
# --------------------------------------------------------------------------

def _base_default_resource_dir() -> Path:
    # Mirrors brushstroke_tools.utils.get_default_resource_directory()
    if platform.system() == 'Windows':
        return Path.home().joinpath('AppData/Roaming/Blender Studio Tools/Brushstroke Tools/')
    if platform.system() == 'Darwin':
        return Path.home().joinpath('Library/Application Support/Blender Studio Tools/Brushstroke Tools/')
    return Path.home().joinpath('.config/blender_studio_tools/brushstroke_tools/')


def base_addon_prefs():
    """Return the preferences of an installed Brushstroke Tools add-on, if any."""
    for key, addon in bpy.context.preferences.addons.items():
        if key.split('.')[-1] == 'brushstroke_tools':
            return addon.preferences
    return None


def library_dirs(extra: str = '') -> list[Path]:
    dirs = []
    if extra:
        dirs.append(Path(bpy.path.abspath(extra)))
    prefs = base_addon_prefs()
    if prefs is not None and getattr(prefs, 'resource_path', ''):
        dirs.append(Path(prefs.resource_path))
    dirs.append(_base_default_resource_dir())
    seen, out = set(), []
    for d in dirs:
        key = str(d.resolve()) if d.exists() else str(d)
        if key in seen or not d.exists():
            continue
        seen.add(key)
        out.append(d)
    return out


def parse_style_name(id_name: str):
    """'BSBST-BS.Oil Paint.Brushstrokes.Feathery' -> (name, category, type)."""
    parts = id_name.split('.')
    name = parts[-1]
    typ = parts[-2] if len(parts) >= 3 else ''
    cat = parts[1] if len(parts) >= 4 else ''
    return name, cat, typ


_cache: list[BrushStyle] | None = None


def list_styles(extra_dir: str = '', refresh: bool = False) -> list[BrushStyle]:
    global _cache
    if _cache is not None and not refresh:
        return _cache
    styles: list[BrushStyle] = []
    for name, (typ, _, _) in BUILTIN.items():
        styles.append(BrushStyle(name, builtin_id_name(name), '', BUILTIN_CATEGORY, typ))
    known = {s.id_name for s in styles}
    for d in library_dirs(extra_dir):
        for root, _dirs, files in os.walk(d):
            for f in sorted(files):
                if not f.endswith('.blend'):
                    continue
                path = os.path.join(root, f)
                try:
                    with bpy.data.libraries.load(path) as (src, _dst):
                        names = [n for n in src.node_groups if n.startswith(PREFIX)]
                except (OSError, RuntimeError):
                    continue
                for id_name in names:
                    if id_name in known:
                        continue
                    known.add(id_name)
                    nm, cat, typ = parse_style_name(id_name)
                    styles.append(BrushStyle(nm, id_name, path, cat, typ))
    # Styles already present in the file (e.g. appended by the base add-on).
    for ng in bpy.data.node_groups:
        if ng.name.startswith(PREFIX) and ng.name not in known and ng.bl_idname == 'ShaderNodeTree':
            known.add(ng.name)
            nm, cat, typ = parse_style_name(ng.name)
            styles.append(BrushStyle(nm, ng.name, '', cat, typ))
    _cache = styles
    return styles


def find_style(name_or_id: str, extra_dir: str = '') -> BrushStyle | None:
    for s in list_styles(extra_dir):
        if name_or_id in (s.name, s.id_name):
            return s
    return None


def ensure_style(style: BrushStyle) -> bpy.types.ShaderNodeTree | None:
    """Return the node group for ``style``, generating or appending it."""
    ng = bpy.data.node_groups.get(style.id_name)
    if ng is not None:
        return ng
    if style.category == BUILTIN_CATEGORY and style.name in BUILTIN:
        return ensure_builtin(style.name)
    if not style.filepath:
        return None
    before = set(bpy.data.node_groups)
    with bpy.data.libraries.load(style.filepath, link=False) as (_src, dst):
        dst.node_groups = [style.id_name]
    # Pack images coming from the library so files stay self-contained,
    # as the base add-on does on append.
    for img in bpy.data.images:
        ref = getattr(img, 'library_weak_reference', None)
        if ref and os.path.basename(style.filepath) in ref.filepath and not img.packed_file:
            try:
                img.pack()
            except RuntimeError:
                pass
    new = set(bpy.data.node_groups) - before
    for g in new:
        if g.name.startswith(style.id_name):
            return g
    return bpy.data.node_groups.get(style.id_name)


def enum_items(extra_dir: str = ''):
    items = []
    for i, s in enumerate(list_styles(extra_dir)):
        label = f'{s.category} · {s.name}' if s.category else s.name
        items.append((s.id_name, label, f'{s.type} brush style ({"built-in" if not s.filepath else s.filepath})',
                      'BRUSH_DATA', i))
    return items
