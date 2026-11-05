# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Greenery: grass blades and foliage canopies.

**Grass** grows one brush *ribbon* per blade on a referenced surface.  Each
blade is a curve ``P(s) = root + n*L*s + bend*L*s^2 + wind(s)`` where the
wind term is a scrolling gust field plus flutter, weighted by ``s^2`` so
roots stay planted, and a first-order length correction keeps bent blades
from stretching.

**Foliage** scatters leaf *cards* over and inside the object's own mesh (the
canopy shape) and colours them with the same painter's lighting model as
the clouds, plus seasonal accent patches and wind flutter.
"""

import bmesh
from mathutils import Matrix

from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import TAU, rnd


def wind_panel(strength=0.15, extra=()):
    return Panel('Wind', [
        P('Wind Strength', 'FLOAT', strength, 0.0, 10.0, desc='How far the wind pushes (relative to length)'),
        P('Wind Direction', 'VECTOR', (1.0, 0.3, 0.0), subtype='XYZ', desc='Direction the wind blows towards'),
        P('Gust Scale', 'FLOAT', 0.3, 0.001, 100.0, desc='Spatial size of gusts (smaller = larger gust fronts)'),
        P('Gust Speed', 'FLOAT', 1.5, 0.0, 50.0, 'VELOCITY', 'Speed at which gust fronts travel'),
        P('Flutter', 'FLOAT', 0.04, 0.0, 2.0, desc='Fast small oscillation'),
        P('Flutter Frequency', 'FLOAT', 2.5, 0.0, 30.0, desc='Flutter frequency in Hz'),
        *extra,
    ], desc='Scrolling gust field + flutter; both loop when Loop Frames is set')


def wind_offset(tb, P, root, t, loop, phase):
    """Horizontal wind push at a root position (unit-length scale)."""
    wdir = tb.normalize(P['Wind Direction'] * (1.0, 1.0, 0.0) + (1e-5, 0.0, 0.0))
    gust, _ = common.scrolling_noise(tb, root, wdir * P['Gust Speed'], t, loop, evolve=0.2,
                                     scale=P['Gust Scale'], detail=1.0)
    gust = gust * 0.5 + 0.5
    fq = common.quantize_freq(tb, P['Flutter Frequency'], loop)
    flutter = tb.sin(t * fq * TAU + phase) * P['Flutter']
    side = tb.cross(wdir, (0.0, 0.0, 1.0))
    return wdir * (P['Wind Strength'] * (0.35 + 0.65 * gust)) + side * flutter


@register_effect
class Grass(Effect):
    id = 'GRASS'
    label = 'Grass'
    icon = 'OUTLINER_OB_HAIR'
    category = 'Nature'
    description = 'Wind-swept painterly grass: one brush ribbon per blade'
    host = 'SURFACE'

    spec = [
        Panel('Source', [
            P('Surface', 'OBJECT', desc='Mesh the grass grows on'),
            P('Density', 'FLOAT', 300.0, 0.0, 100000.0, desc='Blades per square metre'),
            P('Seed', 'INT', 0, 0, 100000),
            P('Mask Attribute', 'STRING', '', desc='Vertex group / attribute (0-1) controlling where grass grows'),
            P('Max Slope', 'FLOAT', 1.2, 0.0, 3.1416, 'ANGLE', 'No grass on surfaces steeper than this'),
        ]),
        Panel('Blade', [
            P('Length', 'FLOAT', 0.35, 0.0, 100.0, 'DISTANCE'),
            P('Length Variation', 'FLOAT', 0.4, 0.0, 1.0, 'FACTOR'),
            P('Width', 'FLOAT', 0.035, 0.0, 10.0, 'DISTANCE', 'Brush width at the root'),
            P('Taper', 'FLOAT', 0.6, 0.0, 1.0, 'FACTOR', 'Narrow toward the tip'),
            P('Bend', 'FLOAT', 0.35, 0.0, 2.0, desc='Random natural lean'),
            P('Resolution', 'INT', 6, 2, 64, desc='Points per blade (smoothness of bending)'),
            P('Face Camera', 'FLOAT', 0.6, 0.0, 1.0, 'FACTOR', 'Turn blades so the brush stroke is seen broadside'),
            P('Camera', 'OBJECT', desc='Camera to face (empty = scene camera)'),
        ]),
        wind_panel(0.18),
        Panel('Color', [
            P('Root Color', 'COLOR', (0.08, 0.22, 0.07, 1.0)),
            P('Tip Color', 'COLOR', (0.48, 0.7, 0.24, 1.0)),
            P('Dry Color', 'COLOR', (0.72, 0.62, 0.3, 1.0), desc='Colour of dry patches'),
            P('Dry Patches', 'FLOAT', 0.2, 0.0, 1.0, 'FACTOR', 'Share of dry, straw-coloured patches'),
            P('Patch Scale', 'FLOAT', 0.4, 0.001, 100.0, desc='Size of colour patches'),
            P('Value Variation', 'FLOAT', 0.25, 0.0, 1.0, 'FACTOR'),
            P('Opacity', 'FLOAT', 1.0, 0.0, 1.0, 'FACTOR'),
        ]),
        common.animation_panel(),
        Panel('Display', [P('Material', 'MATERIAL', hidden=True)], closed=True),
    ]

    materials = [MaterialSlot('Material', 'Blades', 'Streak', 'Default',
                              {'Shading': 0.55, 'Translucency': 0.25, 'Gloss': 0.1, 'Color Jitter': 0.15})]

    presets = {
        'Meadow': {},
        'Lawn': {'Density': 900.0, 'Length': 0.12, 'Width': 0.018, 'Bend': 0.15, 'Dry Patches': 0.05,
                 'Wind Strength': 0.08, 'Tip Color': (0.4, 0.68, 0.22, 1.0)},
        'Tall Wild Grass': {'Density': 180.0, 'Length': 0.9, 'Length Variation': 0.5, 'Width': 0.05,
                            'Bend': 0.5, 'Resolution': 10, 'Wind Strength': 0.35, 'Dry Patches': 0.35,
                            'Tip Color': (0.62, 0.68, 0.3, 1.0)},
        'Autumn Field': {'Density': 250.0, 'Length': 0.5, 'Root Color': (0.25, 0.2, 0.08, 1.0),
                         'Tip Color': (0.86, 0.62, 0.25, 1.0), 'Dry Color': (0.6, 0.3, 0.12, 1.0),
                         'Dry Patches': 0.5, '_look': {'Blades': {'Vibrance': 0.3}}},
        'Stylized Toon': {'Density': 150.0, 'Length': 0.45, 'Width': 0.08, 'Taper': 0.9, 'Face Camera': 1.0,
                          '_look': {'Blades': {'Shading': 0.0, 'Posterize': 4.0, 'Hardness': 0.7}}},
    }

    variants = [Variant('Grass', 'Meadow', 'OUTLINER_OB_HAIR', 'Grass on the selected mesh (or a new ground)')]

    def make_mesh(self, mesh):
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=8, y_segments=8, size=3.0)
        bm.to_mesh(mesh)
        bm.free()

    def build(self, tb, P):
        seed = P['Seed']
        surf = common.surface_geometry(tb, P)
        t, loop = common.time(tb, P)

        surf = common.surface_mask(tb, surf, P['Mask Attribute'])
        dist = tb.node('GeometryNodeDistributePointsOnFaces',
                       {'Mesh': surf, 'Density': P['Density'], 'Seed': seed}, distribute_method='RANDOM')
        roots = dist['Points']
        n = dist['Normal']
        roots = tb.store(roots, '_n', n, 'FLOAT_VECTOR')
        # mask: attribute weight + slope limit
        weight = tb.named('_gx_mask')
        steep = tb.compare('LESS_THAN', tb.sep(tb.named('_n', 'FLOAT_VECTOR'))[2], tb.cos(P['Max Slope']))
        drop = tb.bool_math('OR', steep, tb.compare('GREATER_THAN', rnd(tb, seed, 1), weight))
        roots = tb.delete(roots, drop)

        rn = tb.named('_n', 'FLOAT_VECTOR')
        L = P['Length'] * (1.0 + (rnd(tb, seed, 2) - 0.5) * 2.0 * P['Length Variation'])
        bend_dir = tb.normalize(tb.rand('FLOAT_VECTOR', (-1, -1, -0.2), (1, 1, 0.2), id=tb.index(), seed=seed + 3))
        bend_dir = tb.normalize(bend_dir - rn * tb.dot(bend_dir, rn))
        bend = bend_dir * (P['Bend'] * rnd(tb, seed, 4, 0.3, 1.0))
        face_rand = tb.normalize(tb.rand('FLOAT_VECTOR', (-1, -1, 0), (1, 1, 0), id=tb.index(), seed=seed + 5)
                                 + (1e-4, 0, 0))
        roots = tb.store(roots, '_root', tb.position(), 'FLOAT_VECTOR')
        roots = tb.store(roots, '_len', L)
        roots = tb.store(roots, '_bend', bend, 'FLOAT_VECTOR')
        roots = tb.store(roots, '_face', face_rand, 'FLOAT_VECTOR')
        roots = tb.store(roots, '_ph', rnd(tb, seed, 6, 0.0, TAU))
        roots = tb.store(roots, '_vv', rnd(tb, seed, 7))

        curves, s, _ = common.strands(tb, roots, P['Resolution'])
        root = tb.named('_root', 'FLOAT_VECTOR')
        nrm = tb.named('_n', 'FLOAT_VECTOR')
        Ls = tb.named('_len')
        wind = wind_offset(tb, P, root, t, loop, tb.named('_ph'))
        s2 = s * s
        lean = (tb.named('_bend', 'FLOAT_VECTOR') + wind) * (Ls * s2)
        lean_h = lean - nrm * tb.dot(lean, nrm)
        sink = tb.dot(lean_h, lean_h) / (2.0 * tb.max(Ls * s, 1e-4))
        pos = root + nrm * (Ls * s - tb.min(sink, Ls * s * 0.8)) + lean_h
        curves = tb.set_position(curves, pos)

        cam = common.camera_location(tb, P['Camera'])
        facing = common.facing_blend(tb, pos, cam, P['Face Camera'], tb.named('_face', 'FLOAT_VECTOR'))
        width = P['Width'] * (1.0 - P['Taper'] * tb.pow(s, 1.5))
        col = tb.mix_color(tb.smoothstep(0.0, 1.0, s), P['Root Color'], P['Tip Color'])
        patch, _ = tb.noise(root * P['Patch Scale'], scale=1.0, detail=2.0)
        dry = tb.smoothstep(1.0 - P['Dry Patches'] - 0.08, 1.0 - P['Dry Patches'] + 0.08, patch)
        col = tb.mix_color(dry * tb.smoothstep(0.1, 0.8, s), col, P['Dry Color'])
        vv = 1.0 + (tb.named('_vv') - 0.5) * 2.0 * P['Value Variation']
        col = tb.mix_color(1.0, col, tb.combine(vv, vv, vv), blend='MULTIPLY')

        return common.ribbons(tb, {
            'Curves': curves, 'Width': width, 'Facing': facing, 'Color': col, 'Opacity': P['Opacity'],
            'Normal': nrm, 'Seed': seed, 'Material': P['Material'],
        })


@register_effect
class Foliage(Effect):
    id = 'FOLIAGE'
    label = 'Foliage'
    icon = 'OUTLINER_OB_POINTCLOUD'
    category = 'Nature'
    description = 'Painterly leaf canopies and bushes over an editable shape'
    host = 'DOMAIN'

    spec = [
        Panel('Leaves', [
            P('Density', 'FLOAT', 60.0, 0.0, 10000.0, desc='Leaves per square metre of the canopy surface'),
            P('Seed', 'INT', 0, 0, 100000),
            P('Leaf Size', 'FLOAT', 0.14, 0.0, 10.0, 'DISTANCE'),
            P('Size Variation', 'FLOAT', 0.4, 0.0, 1.0, 'FACTOR'),
            P('Aspect', 'FLOAT', 1.6, 0.1, 10.0, desc='Leaf length / width'),
            P('Depth', 'FLOAT', 0.3, 0.0, 10.0, 'DISTANCE', 'Scatter leaves this deep into the canopy'),
            P('Face Camera', 'FLOAT', 0.45, 0.0, 1.0, 'FACTOR', 'Leaves face the camera (1) or the canopy normal (0)'),
            P('Camera', 'OBJECT', desc='Camera to face (empty = scene camera)'),
        ]),
        Panel('Lighting', [
            P('Sun', 'OBJECT', desc='Light whose direction lights the canopy (empty = Sun Direction)'),
            P('Sun Direction', 'VECTOR', (0.4, -0.4, 0.8), subtype='XYZ'),
            P('Lit Color', 'COLOR', (0.55, 0.76, 0.24, 1.0)),
            P('Shadow Color', 'COLOR', (0.06, 0.2, 0.14, 1.0)),
            P('Light Wrap', 'FLOAT', 0.3, 0.0, 1.0, 'FACTOR'),
            P('Interior Darkening', 'FLOAT', 0.5, 0.0, 1.0, 'FACTOR', 'Leaves deeper inside are darker'),
            P('Rim Light', 'FLOAT', 0.25, 0.0, 2.0),
        ]),
        Panel('Color', [
            P('Accent Color', 'COLOR', (0.95, 0.55, 0.12, 1.0), desc='Seasonal accent (autumn, blossoms)'),
            P('Accent Amount', 'FLOAT', 0.0, 0.0, 1.0, 'FACTOR'),
            P('Accent Scale', 'FLOAT', 0.6, 0.001, 100.0, desc='Patch size of the accent colour'),
            P('Opacity', 'FLOAT', 1.0, 0.0, 1.0, 'FACTOR'),
        ]),
        wind_panel(0.04, extra=(P('Leaf Flutter', 'FLOAT', 0.35, 0.0, 3.1416, 'ANGLE', 'Leaf rotation jitter'),)),
        common.animation_panel(),
        Panel('Display', [
            P('Show Domain', 'BOOL', False, desc='Show the canopy shape wireframe in the viewport'),
            P('Material', 'MATERIAL', hidden=True),
        ], closed=True),
    ]

    materials = [MaterialSlot('Material', 'Leaves', 'Leaf', 'Default',
                              {'Shading': 0.35, 'Translucency': 0.3, 'Color Jitter': 0.2, 'Stroke Normal': 1.0})]

    presets = {
        'Summer Bush': {},
        'Autumn Tree': {'Accent Amount': 0.65, 'Lit Color': (0.85, 0.62, 0.2, 1.0),
                        'Shadow Color': (0.35, 0.14, 0.06, 1.0), 'Accent Color': (0.85, 0.25, 0.08, 1.0)},
        'Cherry Blossom': {'Lit Color': (1.0, 0.82, 0.88, 1.0), 'Shadow Color': (0.6, 0.35, 0.5, 1.0),
                           'Accent Color': (1.0, 1.0, 1.0, 1.0), 'Accent Amount': 0.3, 'Leaf Size': 0.08,
                           'Density': 140.0, 'Aspect': 1.1, '_brush': {'Leaves': 'Soft Dab'}},
        'Impressionist': {'Leaf Size': 0.22, 'Density': 40.0, 'Aspect': 1.2, 'Face Camera': 0.9,
                          '_brush': {'Leaves': 'Bristle Dab'},
                          '_look': {'Leaves': {'Vibrance': 0.6, 'Color Jitter': 0.45, 'Shading': 0.15}}},
    }

    variants = [Variant('Foliage', 'Summer Bush', 'OUTLINER_OB_POINTCLOUD', 'Leaf canopy / bush')]

    def make_mesh(self, mesh):
        bm = bmesh.new()
        bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0,
                                   matrix=Matrix.Translation((0, 0, 1.2)) @ Matrix.Diagonal((1.2, 1.2, 0.95, 1.0)))
        bm.to_mesh(mesh)
        bm.free()

    def build(self, tb, P):
        geo_in = P['Geometry']
        seed = P['Seed']
        bb = tb.bound_box(geo_in)
        center = (bb['Min'] + bb['Max']) * 0.5
        t, loop = common.time(tb, P)

        dist = tb.node('GeometryNodeDistributePointsOnFaces',
                       {'Mesh': geo_in, 'Density': P['Density'], 'Seed': seed}, distribute_method='RANDOM')
        pts = tb.store(dist['Points'], '_n', dist['Normal'], 'FLOAT_VECTOR')
        n = tb.named('_n', 'FLOAT_VECTOR')
        p0 = tb.position()
        dpt = tb.sqrt(rnd(tb, seed, 1))
        base = p0 - n * (P['Depth'] * dpt)
        # wind sway grows with height above the canopy base
        h = tb.clamp01((tb.sep(base)[2] - tb.sep(bb['Min'])[2]) / tb.max(tb.sep(bb['Max'] - bb['Min'])[2], 1e-3))
        sway = wind_offset(tb, P, base, t, loop, rnd(tb, seed, 2, 0.0, TAU))
        pos = base + sway * (0.3 + 0.7 * h)

        pn = tb.normalize(tb.lerp(n, tb.normalize(pos - center), 0.4))
        sun = common.sun_direction(tb, P['Sun'], P['Sun Direction'])
        wrap = P['Light Wrap']
        light = tb.smoothstep(0.0, 1.0, tb.clamp01((tb.dot(pn, sun) + wrap) / (1.0 + wrap)))
        light = light * (1.0 - P['Interior Darkening'] * dpt)
        col = tb.mix_color(light, P['Shadow Color'], P['Lit Color'])
        acc, _ = tb.noise(p0 * P['Accent Scale'], scale=1.0, detail=2.0)
        amask = tb.smoothstep(1.0 - P['Accent Amount'] - 0.06, 1.0 - P['Accent Amount'] + 0.06, acc)
        acc_col = tb.mix_color(light * 0.7 + 0.3, tb.mix_color(0.6, P['Shadow Color'], P['Accent Color']),
                               P['Accent Color'])
        col = tb.mix_color(amask, col, acc_col)
        cam = common.camera_location(tb, P['Camera'])
        to_cam = tb.normalize(cam - pos)
        sil = 1.0 - tb.abs(tb.dot(pn, to_cam))
        col = tb.mix_color(tb.clamp01(P['Rim Light'] * sil * sil), col, P['Lit Color'], blend='SCREEN')

        facing = common.facing_blend(tb, pos, cam, P['Face Camera'], pn)
        flut_q = common.quantize_freq(tb, P['Flutter Frequency'], loop)
        flut = tb.sin(t * flut_q * TAU + rnd(tb, seed, 3, 0.0, TAU)) * P['Leaf Flutter']
        up = tb.normalize(tb.cross(facing, tb.cross((0.0, 0.0, 1.0), facing)) + (1e-4, 0.0, 0.0))
        direction = tb.rotate_axis(up, facing, rnd(tb, seed, 4, -1.2, 1.2) + flut)
        size = P['Leaf Size'] * (1.0 + (rnd(tb, seed, 5) - 0.5) * 2.0 * P['Size Variation'])

        pts = tb.set_position(pts, pos)
        leaves = common.cards(tb, {
            'Points': pts, 'Direction': direction, 'Facing': facing, 'Width': size,
            'Length': size * P['Aspect'], 'Color': col, 'Opacity': P['Opacity'], 'Normal': pn, 'Seed': seed,
            'Material': P['Material'],
        })
        return tb.join(leaves, common.domain_wire(tb, geo_in, P['Show Domain']))
