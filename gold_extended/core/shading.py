# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
The *Look* shader: one shader node group that turns a brush-style mask plus
the ``brush_stroke.*`` attributes into a painterly surface, with every visual
control exposed as a group input (so the sidebar can draw them directly).

Visual capabilities (see docs/RESEARCH.md for the reasoning):

Color      Hue Shift, Saturation, **Vibrance** (saturation boost weighted
           toward muted colours), Brightness, Contrast, Posterize, per-stroke
           Color Jitter.
Chromatic  **Fringe** – lateral chromatic aberration across each stroke
           (opposite hue shifts on the two stroke edges), **Iridescence** –
           view-angle thin-film hue cycling.
Light      Shading (flat paint <-> lit), Gloss, Roughness, **Sheen** (rim
           light + Principled sheen), Translucency, Emission.
Opacity    Opacity, Coverage, Hardness, **Sheer** (view-dependent
           see-through, like chiffon/water), Edge Darken (watercolour
           pigment pooling), Dry Brush breakup.
"""

from __future__ import annotations

import bpy

from . import brushes
from .nodes import TreeBuilder, ensure_tree, new_socket

VERSION = 1
LOOK = f'.GOLDX.look.v{VERSION}'

# name, type, default, min, max, panel, description
LOOK_INPUTS = [
    ('Base Color', 'COLOR', (0.8, 0.8, 0.8, 1.0), None, None, 'Paint',
     'Colour used where the stroke has no colour attribute'),
    ('Use Stroke Color', 'FLOAT', 1.0, 0.0, 1.0, 'Paint',
     'Blend between Base Color (0) and the per-stroke colour computed by the effect (1)'),
    ('Tint', 'COLOR', (1.0, 1.0, 1.0, 1.0), None, None, 'Paint', 'Multiplied over the paint colour'),
    ('Color Jitter', 'FLOAT', 0.15, 0.0, 1.0, 'Paint', 'Random hue/saturation/value variation per stroke'),

    ('Hue Shift', 'FLOAT', 0.0, -0.5, 0.5, 'Color', 'Rotate all hues'),
    ('Saturation', 'FLOAT', 1.0, 0.0, 2.0, 'Color', 'Uniform saturation multiplier'),
    ('Vibrance', 'FLOAT', 0.0, -1.0, 1.0, 'Color',
     'Smart saturation: boosts muted colours more than already-saturated ones'),
    ('Brightness', 'FLOAT', 1.0, 0.0, 3.0, 'Color', 'Value multiplier'),
    ('Contrast', 'FLOAT', 0.0, -1.0, 1.0, 'Color', 'Colour contrast'),
    ('Posterize', 'FLOAT', 0.0, 0.0, 16.0, 'Color', 'Quantise value into N bands (0 = off) for a graphic, gouache look'),

    ('Fringe', 'FLOAT', 0.0, 0.0, 1.0, 'Chromatic',
     'Chromatic aberration across each stroke: the two edges shift hue in opposite directions'),
    ('Fringe Width', 'FLOAT', 0.5, 0.01, 1.0, 'Chromatic', 'How far the fringe reaches into the stroke'),
    ('Fringe Hue', 'FLOAT', 0.12, 0.0, 0.5, 'Chromatic', 'Hue distance between the two fringe sides'),
    ('Iridescence', 'FLOAT', 0.0, 0.0, 1.0, 'Chromatic', 'Thin-film rainbow hue that changes with viewing angle'),
    ('Iridescence Cycles', 'FLOAT', 1.5, 0.0, 8.0, 'Chromatic', 'How many hue cycles from facing to grazing angles'),

    ('Shading', 'FLOAT', 0.7, 0.0, 1.0, 'Light', 'Flat unlit paint (0) to fully lit (1)'),
    ('Stroke Normal', 'FLOAT', 1.0, 0.0, 1.0, 'Light',
     'Light using the effect-provided normal (e.g. spherical cloud puffs) instead of the flat card normal'),
    ('Roughness', 'FLOAT', 0.6, 0.0, 1.0, 'Light', 'Surface roughness of lit paint'),
    ('Gloss', 'FLOAT', 0.25, 0.0, 1.0, 'Light', 'Specular highlight strength (wet paint)'),
    ('Sheen', 'FLOAT', 0.0, 0.0, 1.0, 'Light', 'Soft rim highlight at grazing angles (hair, fabric, water)'),
    ('Sheen Tint', 'COLOR', (1.0, 0.95, 0.85, 1.0), None, None, 'Light', 'Colour of the sheen/rim highlight'),
    ('Sheen Falloff', 'FLOAT', 0.35, 0.01, 1.0, 'Light', 'Width of the rim highlight'),
    ('Translucency', 'FLOAT', 0.0, 0.0, 1.0, 'Light', 'Light passing through thin strokes (leaves, clouds)'),
    ('Emission', 'FLOAT', 0.0, 0.0, 100.0, 'Light', 'Self illumination strength (fire, embers, neon)'),
    ('Emission Attribute', 'FLOAT', 0.0, 0.0, 1.0, 'Light',
     'Modulate emission by the per-stroke "gx_emit" attribute written by the effect'),

    ('Opacity', 'FLOAT', 1.0, 0.0, 1.0, 'Opacity', 'Overall opacity'),
    ('Coverage', 'FLOAT', 0.0, -1.0, 1.0, 'Opacity', 'Grow (+) or shrink (-) the painted area of the brush mask'),
    ('Hardness', 'FLOAT', 0.0, 0.0, 1.0, 'Opacity', 'Soft brush edge (0) to hard cut-out edge (1)'),
    ('Sheer', 'FLOAT', 0.0, 0.0, 1.0, 'Opacity',
     'View-dependent transparency: see-through when facing the camera, denser at grazing angles'),
    ('Edge Darken', 'FLOAT', 0.0, 0.0, 1.0, 'Opacity', 'Watercolour pigment pooling at stroke edges'),
    ('Dry Brush', 'FLOAT', 0.0, 0.0, 1.0, 'Opacity', 'Break the stroke up with dry-brush grain'),
    ('Grain Scale', 'FLOAT', 6.0, 0.1, 50.0, 'Opacity', 'Scale of the dry-brush grain'),
    ('Use Fade Attribute', 'FLOAT', 1.0, 0.0, 1.0, 'Opacity',
     'Multiply by the per-point "opacity" fade written by the effect'),
]

LOOK_PANELS = ['Paint', 'Color', 'Chromatic', 'Light', 'Opacity']


def look_defaults():
    return {nm: d for nm, _t, d, *_ in LOOK_INPUTS}


# --------------------------------------------------------------------------
# Look presets: named starting points that showcase the visual capabilities
# --------------------------------------------------------------------------

LOOK_PRESETS = {
    'Default': {},
    'Oil Impasto': {'Shading': 1.0, 'Gloss': 0.45, 'Roughness': 0.35, 'Hardness': 0.55, 'Color Jitter': 0.3,
                    'Contrast': 0.1},
    'Watercolor': {'Shading': 0.35, 'Edge Darken': 0.65, 'Coverage': -0.1, 'Hardness': 0.15, 'Dry Brush': 0.1,
                   'Opacity': 0.8, 'Fringe': 0.12, 'Saturation': 0.9, 'Gloss': 0.0},
    'Gouache Flat': {'Shading': 0.0, 'Posterize': 5.0, 'Hardness': 0.8, 'Saturation': 1.1, 'Gloss': 0.0},
    'Vibrant Pop': {'Vibrance': 0.8, 'Saturation': 1.2, 'Contrast': 0.2, 'Fringe': 0.25, 'Color Jitter': 0.25},
    'Pastel': {'Saturation': 0.6, 'Brightness': 1.15, 'Contrast': -0.25, 'Dry Brush': 0.25, 'Gloss': 0.0},
    'Prismatic': {'Fringe': 0.85, 'Fringe Hue': 0.22, 'Fringe Width': 0.7, 'Iridescence': 0.45, 'Vibrance': 0.5},
    'Silk Sheen': {'Sheen': 0.85, 'Sheer': 0.45, 'Gloss': 0.5, 'Roughness': 0.25, 'Sheen Falloff': 0.4},
    'Ink Wash': {'Saturation': 0.0, 'Contrast': 0.45, 'Edge Darken': 0.8, 'Posterize': 4.0, 'Shading': 0.3},
    'Neon Glow': {'Emission': 4.0, 'Vibrance': 1.0, 'Saturation': 1.4, 'Shading': 0.2, 'Sheen': 0.4},
}


# --------------------------------------------------------------------------
# Shader group
# --------------------------------------------------------------------------

def _attr(tb, name, out):
    n = tb.node('ShaderNodeAttribute', attribute_type='GEOMETRY')
    n.n.attribute_name = name
    return n[out]


def ensure_look():
    ng, created = ensure_tree(LOOK, 'ShaderNodeTree')
    if not created:
        return ng
    ng.description = 'Gold Extended painterly look: colour grading, chromatic effects, light and opacity'
    new_socket(ng, 'Shader', 'OUTPUT', 'SHADER')
    new_socket(ng, 'Brush Mask', 'INPUT', 'FLOAT', default=1.0, min=0.0, max=1.0,
               description='Mask from the Brush Style node')
    panels = {p: ng.interface.new_panel(p) for p in LOOK_PANELS}
    for nm, typ, d, lo, hi, panel, desc in LOOK_INPUTS:
        new_socket(ng, nm, 'INPUT', typ, parent=panels[panel], default=d, min=lo, max=hi, description=desc,
                   subtype='FACTOR' if (typ == 'FLOAT' and lo == 0.0 and hi == 1.0) else None)

    tb = TreeBuilder(ng)
    I = tb.I
    stroke_col = _attr(tb, 'brush_stroke.color', 'Color')
    sid = _attr(tb, 'brush_stroke.id', 'Vector')
    uv = _attr(tb, 'brush_stroke.uv', 'Vector')
    dim = _attr(tb, 'brush_stroke.dimension', 'Vector')
    fade = _attr(tb, 'opacity', 'Factor')
    emit_attr = _attr(tb, 'gx_emit', 'Factor')
    stroke_n = _attr(tb, 'brush_stroke.normal', 'Vector')
    u, v, _ = tb.sep(uv)
    ix, iy, iz = tb.sep(sid)
    lw = tb.node('ShaderNodeLayerWeight', {'Blend': 0.5})
    facing = lw['Facing']                      # 0 facing camera -> 1 grazing

    # ---- alpha ------------------------------------------------------------
    mask = I('Brush Mask')
    center = 0.5 - I('Coverage') * 0.5
    half = (1.0 - I('Hardness')) * 0.5 + 0.01
    a = tb.map_range(mask, center - half, center + half, 0.0, 1.0)
    aspect = tb.sep(dim)[1] / tb.max(tb.sep(dim)[0], 1e-4)
    gfac, _ = tb.noise(tb.combine(u, v * tb.min(aspect, 8.0), ix * 37.0), scale=I('Grain Scale'), detail=5.0,
                       roughness=0.65)
    dry = I('Dry Brush')
    a = a * tb.smoothstep(dry * 0.75 - 0.1, dry * 0.75 + 0.05, gfac)
    a = a * I('Opacity') * tb.lerp(1.0, fade, I('Use Fade Attribute'))
    sheer_a = tb.lerp(1.0, facing * 0.85 + 0.15, I('Sheer'))
    a = tb.clamp01(a * sheer_a)

    # ---- colour -----------------------------------------------------------
    col = tb.mix_color(I('Use Stroke Color'), I('Base Color'), stroke_col)
    col = tb.mix_color(1.0, col, I('Tint'), blend='MULTIPLY')
    jit = I('Color Jitter')
    # per-stroke jitter in HSV
    hsv = tb.node('ShaderNodeSeparateColor', {'Color': col}, mode='HSV')
    h = hsv['Red'] + (ix - 0.5) * jit * 0.15
    s = hsv['Green'] * (1.0 + (iy - 0.5) * jit)
    val = hsv['Blue'] * (1.0 + (iz - 0.5) * jit * 0.6)
    # chromatic fringe: opposite hue shift on each side of the stroke
    # band across the stroke width: 1 at both stroke sides, 0 in the centre
    edge = 1.0 - tb.smoothstep(0.0, I('Fringe Width'), 1.0 - tb.abs(u * 2.0 - 1.0))
    side = (u - 0.5) * 2.0
    fringe_shift = I('Fringe') * edge * side * I('Fringe Hue')
    irid_shift = I('Iridescence') * facing * I('Iridescence Cycles')
    h = tb.fract(h + I('Hue Shift') + fringe_shift + irid_shift + 1.0)
    # fringe also boosts saturation in the edge zone so the split reads
    s = s * I('Saturation') * (1.0 + I('Fringe') * edge * 0.6)
    # vibrance: s' = s * (1 + vib * (1 - s))
    s = tb.clamp01(s * (1.0 + I('Vibrance') * (1.0 - tb.clamp01(s))))
    val = val * I('Brightness')
    # posterize value bands (when > 0)
    steps = tb.max(I('Posterize'), 1.0)
    post = tb.floor(val * steps + 0.5) / steps
    val = tb.lerp(val, post, tb.math('GREATER_THAN', I('Posterize'), 0.5))
    col = tb.node('ShaderNodeCombineColor', {'Red': h, 'Green': s, 'Blue': val}, mode='HSV').out
    col = tb.node('ShaderNodeBrightContrast', {'Color': col, 'Bright': 0.0, 'Contrast': I('Contrast')}).out
    # watercolour pigment pooling near the mask edge
    pool = a * (1.0 - a) * 4.0
    col = tb.mix_color(pool * I('Edge Darken') * 0.55, col, (0.0, 0.0, 0.0, 1.0), blend='MULTIPLY')
    col = tb.mix_color(pool * I('Edge Darken') * 0.4, col, col, blend='MULTIPLY')

    # ---- light ------------------------------------------------------------
    geo = tb.node('ShaderNodeNewGeometry')
    n_world = tb.node('ShaderNodeVectorTransform', {'Vector': stroke_n}, vector_type='NORMAL',
                      convert_from='OBJECT', convert_to='WORLD').out
    has_sn = tb.math('GREATER_THAN', tb.length(stroke_n), 0.001)
    normal = tb.normalize(tb.lerp(geo['Normal'], n_world, I('Stroke Normal') * has_sn))
    emit_mask = tb.lerp(1.0, emit_attr, I('Emission Attribute'))
    emit = I('Emission') * emit_mask
    bsdf = tb.node('ShaderNodeBsdfPrincipled', {
        'Base Color': col, 'Roughness': I('Roughness'), 'Specular IOR Level': I('Gloss'),
        'Sheen Weight': I('Sheen'), 'Sheen Tint': I('Sheen Tint'), 'Normal': normal,
        'Emission Color': col, 'Emission Strength': emit,
    }).out
    transl = tb.node('ShaderNodeBsdfTranslucent', {'Color': tb.mix_color(I('Translucency'), (0, 0, 0, 1), col),
                                                   'Normal': normal}).out
    lit = tb.node('ShaderNodeAddShader', {0: bsdf, 1: transl}).out
    flat = tb.node('ShaderNodeEmission', {'Color': col, 'Strength': 1.0 + emit}).out
    surface = tb.node('ShaderNodeMixShader', {0: I('Shading'), 1: flat, 2: lit}).out
    # NPR rim sheen visible in flat and lit modes
    rim = tb.smoothstep(1.0 - I('Sheen Falloff'), 1.0, facing) * I('Sheen')
    rim_sh = tb.node('ShaderNodeEmission', {'Color': I('Sheen Tint'), 'Strength': rim * 1.5}).out
    surface = tb.node('ShaderNodeAddShader', {0: surface, 1: rim_sh}).out
    transp = tb.node('ShaderNodeBsdfTransparent').out
    out = tb.node('ShaderNodeMixShader', {0: a, 1: transp, 2: surface}).out
    tb.output('Shader', out)
    tb.layout()
    return ng


# --------------------------------------------------------------------------
# Materials
# --------------------------------------------------------------------------

def _set_render_method(mat):
    if hasattr(mat, 'surface_render_method'):
        mat.surface_render_method = 'DITHERED'
    elif hasattr(mat, 'blend_method'):
        mat.blend_method = 'HASHED'
    if hasattr(mat, 'use_transparent_shadow'):
        mat.use_transparent_shadow = True
    if hasattr(mat, 'shadow_method'):
        mat.shadow_method = 'HASHED'
    mat.use_backface_culling = False


def new_material(name: str, brush_style: str | None = 'Soft Dab', look: dict | None = None,
                 look_preset: str = 'Default', role: str = '', extra_dir: str = '') -> bpy.types.Material:
    """Create a Gold Extended brush material.

    The brush style node is named ``Brush Style`` – the same name the base
    add-on uses – so Brushstroke Tools' brush-style browser works on it too.
    """
    look_ng = ensure_look()
    mat = bpy.data.materials.new(name)
    if hasattr(mat, 'use_nodes') and not mat.use_nodes:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    tb = TreeBuilder(nt)
    lk = tb.group(look_ng, name='Look', label='Gold FX Look')
    if brush_style:
        # A continuous surface (e.g. a water body) has no stroke UVs: no brush.
        style = brushes.find_style(brush_style, extra_dir) or brushes.find_style('Soft Dab')
        bs = tb.group(brushes.ensure_style(style), name='Brush Style', label='Brush Style')
        tb.link(bs.n.outputs[0], lk.n.inputs['Brush Mask'])
        bs.n.location = (-300, 0)
    out = tb.node('ShaderNodeOutputMaterial', name='Material Output')
    tb.link(lk.n.outputs[0], out.n.inputs['Surface'])
    lk.n.location = (0, 0)
    lk.n.width = 220
    out.n.location = (300, 0)
    values = dict(LOOK_PRESETS.get(look_preset, {}))
    values.update(look or {})
    apply_look(mat, values)
    _set_render_method(mat)
    mat['GOLDX'] = True
    mat['GOLDX_role'] = role
    base = values.get('Base Color', (0.8, 0.8, 0.8, 1.0))
    mat.diffuse_color = base if len(base) == 4 else (*base, 1.0)
    return mat


def look_node(mat):
    if not mat or not mat.node_tree:
        return None
    return mat.node_tree.nodes.get('Look')


def style_node(mat):
    if not mat or not mat.node_tree:
        return None
    return mat.node_tree.nodes.get('Brush Style')


def apply_look(mat, values: dict, reset: bool = False):
    node = look_node(mat)
    if node is None:
        return
    if reset:
        merged = look_defaults()
        merged.update(values)
        values = merged
    for k, v in values.items():
        sock = node.inputs.get(k)
        if sock is None:
            continue
        if sock.type == 'RGBA' and len(v) == 3:
            v = (*v, 1.0)
        sock.default_value = v


def set_brush_style(mat, id_name: str, extra_dir: str = ''):
    node = style_node(mat)
    style = brushes.find_style(id_name, extra_dir)
    if node is None or style is None:
        return False
    ng = brushes.ensure_style(style)
    if ng is None:
        return False
    prev = {s.name: s.default_value for s in node.inputs if hasattr(s, 'default_value')}
    node.node_tree = ng
    for s in node.inputs:
        if s.name in prev:
            try:
                s.default_value = prev[s.name]
            except (TypeError, ValueError):
                pass
    if node.outputs and not node.outputs[0].links:
        lk = look_node(mat)
        if lk:
            mat.node_tree.links.new(node.outputs[0], lk.inputs['Brush Mask'])
    return True
