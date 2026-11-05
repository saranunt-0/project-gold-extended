# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Hair: painterly locks as brush ribbons.

Strands are generated on a surface (or taken from an existing hair *Curves*
object used as guides).  Generated strand shape:

    dir0  = normalize(lerp(normal, comb (projected on the tangent plane), Comb))
    P(s)  = root + dir0*L*s + down*Gravity*L*s^2 + curl(s) + frizz(s)

**Clumping** pulls each strand's tip toward its clump leader – the strand
grown from the nearest clump centre – which is what makes hair read as
painted locks rather than fur.  Wind is applied with a stiffness exponent so
roots stay put.
"""

import bmesh

from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import TAU, rnd
from .greenery import wind_offset


def _strand_shape(tb, P, root, n, L, s, phase):
    comb = P['Comb Direction']
    comb_t = tb.normalize(comb - n * tb.dot(comb, n) + (1e-5, 0.0, 0.0))
    dir0 = tb.normalize(tb.lerp(n, comb_t, P['Comb']))
    pos = root + dir0 * (L * s) + tb.combine(0.0, 0.0, -1.0) * (P['Gravity'] * L * s * s)
    a = tb.normalize(tb.cross(dir0, (0.31, 0.17, 0.93)))
    b = tb.cross(dir0, a)
    ang = s * P['Curl Frequency'] * TAU + phase
    curl = (a * tb.cos(ang) + b * tb.sin(ang)) * (P['Curl Radius'] * tb.smoothstep(0.0, 0.25, s))
    return pos + curl


@register_effect
class Hair(Effect):
    id = 'HAIR'
    label = 'Hair'
    icon = 'CURVES'
    category = 'Nature'
    description = 'Painterly hair locks with clumping, curls and wind'
    host = 'SURFACE'

    spec = [
        Panel('Source', [
            P('Surface', 'OBJECT', desc='Scalp / skin mesh the hair grows from'),
            P('Guide Curves', 'OBJECT', desc='Optional hair Curves object: style its strands instead of generating'),
            P('Density', 'FLOAT', 900.0, 0.0, 100000.0, desc='Strands per square metre'),
            P('Seed', 'INT', 0, 0, 100000),
            P('Mask Attribute', 'STRING', '', desc='Vertex group / attribute (0-1) controlling where hair grows'),
        ]),
        Panel('Shape', [
            P('Length', 'FLOAT', 0.45, 0.0, 100.0, 'DISTANCE'),
            P('Length Variation', 'FLOAT', 0.25, 0.0, 1.0, 'FACTOR'),
            P('Resolution', 'INT', 14, 2, 128, desc='Points per strand'),
            P('Gravity', 'FLOAT', 0.9, -2.0, 4.0, desc='Droop of the strands'),
            P('Comb Direction', 'VECTOR', (0.0, 0.3, -1.0), subtype='XYZ', desc='Direction the hair is combed'),
            P('Comb', 'FLOAT', 0.8, 0.0, 1.0, 'FACTOR', 'How strongly strands follow the comb direction'),
            P('Curl Radius', 'FLOAT', 0.0, 0.0, 10.0, 'DISTANCE'),
            P('Curl Frequency', 'FLOAT', 3.0, 0.0, 50.0, desc='Curl turns along a strand'),
            P('Frizz', 'FLOAT', 0.008, 0.0, 1.0, 'DISTANCE', 'Random noise along strands'),
        ]),
        Panel('Clumping', [
            P('Strands per Clump', 'FLOAT', 25.0, 1.0, 1000.0, desc='Average number of strands per lock'),
            P('Clumping', 'FLOAT', 0.65, 0.0, 1.0, 'FACTOR', 'Pull strand tips toward their lock'),
            P('Clump Shape', 'FLOAT', 0.7, 0.05, 4.0, desc='Higher = clumping only near the tips'),
        ]),
        Panel('Stroke', [
            P('Strand Width', 'FLOAT', 0.035, 0.0, 10.0, 'DISTANCE', 'Brush width of each strand'),
            P('Taper', 'FLOAT', 0.75, 0.0, 1.0, 'FACTOR'),
            P('Face Camera', 'FLOAT', 0.85, 0.0, 1.0, 'FACTOR'),
            P('Camera', 'OBJECT', desc='Camera to face (empty = scene camera)'),
        ]),
        Panel('Color', [
            P('Root Color', 'COLOR', (0.12, 0.06, 0.03, 1.0)),
            P('Tip Color', 'COLOR', (0.55, 0.33, 0.15, 1.0)),
            P('Value Variation', 'FLOAT', 0.25, 0.0, 1.0, 'FACTOR'),
            P('Opacity', 'FLOAT', 1.0, 0.0, 1.0, 'FACTOR'),
        ]),
        Panel('Wind', [
            P('Wind Strength', 'FLOAT', 0.08, 0.0, 10.0),
            P('Wind Direction', 'VECTOR', (1.0, 0.0, 0.0), subtype='XYZ'),
            P('Gust Scale', 'FLOAT', 0.6, 0.001, 100.0),
            P('Gust Speed', 'FLOAT', 1.0, 0.0, 50.0, 'VELOCITY'),
            P('Flutter', 'FLOAT', 0.03, 0.0, 2.0),
            P('Flutter Frequency', 'FLOAT', 1.5, 0.0, 30.0),
            P('Stiffness', 'FLOAT', 2.0, 0.5, 8.0, desc='Higher = only the ends move'),
        ], closed=True),
        common.animation_panel(),
        Panel('Display', [P('Material', 'MATERIAL', hidden=True)], closed=True),
    ]

    materials = [MaterialSlot('Material', 'Strands', 'Streak', 'Default',
                              {'Shading': 0.6, 'Sheen': 0.55, 'Gloss': 0.4, 'Roughness': 0.35, 'Color Jitter': 0.12})]

    presets = {
        'Brown Locks': {},
        'Blonde Waves': {'Root Color': (0.45, 0.32, 0.15, 1.0), 'Tip Color': (0.95, 0.8, 0.5, 1.0),
                         'Curl Radius': 0.025, 'Curl Frequency': 2.5, 'Length': 0.6},
        'Black Straight': {'Root Color': (0.02, 0.02, 0.025, 1.0), 'Tip Color': (0.12, 0.11, 0.13, 1.0),
                           'Gravity': 1.2, 'Clumping': 0.4, 'Frizz': 0.002,
                           '_look': {'Strands': {'Sheen': 0.9, 'Sheen Tint': (0.7, 0.75, 0.9, 1.0)}}},
        'Curly Red': {'Root Color': (0.35, 0.08, 0.03, 1.0), 'Tip Color': (0.85, 0.32, 0.1, 1.0),
                      'Curl Radius': 0.05, 'Curl Frequency': 5.0, 'Gravity': 0.3, 'Length': 0.35},
        'Fur': {'Density': 3000.0, 'Length': 0.05, 'Strand Width': 0.008, 'Gravity': 0.1, 'Comb': 0.7,
                'Clumping': 0.3, 'Strands per Clump': 6.0, 'Resolution': 5},
        'Anime Spikes': {'Density': 60.0, 'Length': 0.5, 'Strand Width': 0.09, 'Taper': 1.0, 'Gravity': 0.2,
                         'Clumping': 0.85, 'Strands per Clump': 4.0, 'Frizz': 0.0,
                         'Root Color': (0.1, 0.1, 0.35, 1.0), 'Tip Color': (0.3, 0.45, 0.95, 1.0),
                         '_look': {'Strands': {'Shading': 0.0, 'Posterize': 3.0, 'Hardness': 0.8}}},
    }

    variants = [Variant('Hair', 'Brown Locks', 'CURVES', 'Hair on the selected mesh (or a new head)')]

    def make_mesh(self, mesh):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=16, radius=0.5)
        bm.to_mesh(mesh)
        bm.free()
        # Default "head": only grow on the upper/back part.
        vg_weights = [max(0.0, min(1.0, (v.co.z + 0.05) * 4.0 + (v.co.y * 1.5))) for v in mesh.vertices]
        attr = mesh.attributes.new('hair_mask', 'FLOAT', 'POINT')
        attr.data.foreach_set('value', vg_weights)

    def setup_object(self, context, obj, mod):
        from ..core.registry import get_param, set_param
        surf = get_param(mod, 'Surface')
        if surf is not None and 'hair_mask' in surf.data.attributes:
            set_param(mod, 'Mask Attribute', 'hair_mask')

    def build(self, tb, P):
        seed = P['Seed']
        surf = common.surface_geometry(tb, P)
        t, loop = common.time(tb, P)

        # ---- roots ----------------------------------------------------------
        surf = common.surface_mask(tb, surf, P['Mask Attribute'])
        dist = tb.node('GeometryNodeDistributePointsOnFaces',
                       {'Mesh': surf, 'Density': P['Density'], 'Seed': seed}, distribute_method='RANDOM')
        roots = tb.store(dist['Points'], '_n', dist['Normal'], 'FLOAT_VECTOR')
        weight = tb.named('_gx_mask')
        roots = tb.delete(roots, tb.compare('GREATER_THAN', rnd(tb, seed, 1), weight))

        # ---- clump leaders ----------------------------------------------------
        cdist = tb.node('GeometryNodeDistributePointsOnFaces',
                        {'Mesh': surf, 'Density': P['Density'] / tb.max(P['Strands per Clump'], 1.0),
                         'Seed': seed + 1}, distribute_method='RANDOM')
        leaders = tb.store(cdist['Points'], '_n', cdist['Normal'], 'FLOAT_VECTOR')
        leaders = tb.store(leaders, '_cl_len', P['Length'] * (1.0 + (rnd(tb, seed, 8) - 0.5) * 2.0
                                                              * P['Length Variation']))
        leaders = tb.store(leaders, '_cl_ph', rnd(tb, seed, 9, 0.0, TAU))
        near = tb.node('GeometryNodeSampleNearest', {'Geometry': leaders, 'Sample Position': tb.position()},
                       domain='POINT').out
        roots = tb.store(roots, '_cl_root', tb.sample_index(leaders, tb.position(), near, 'FLOAT_VECTOR'),
                         'FLOAT_VECTOR')
        roots = tb.store(roots, '_cl_n', tb.sample_index(leaders, tb.named('_n', 'FLOAT_VECTOR'), near,
                                                         'FLOAT_VECTOR'), 'FLOAT_VECTOR')
        roots = tb.store(roots, '_cl_len', tb.sample_index(leaders, tb.named('_cl_len'), near))
        roots = tb.store(roots, '_cl_ph', tb.sample_index(leaders, tb.named('_cl_ph'), near))
        roots = tb.store(roots, '_root', tb.position(), 'FLOAT_VECTOR')
        roots = tb.store(roots, '_len', P['Length'] * (1.0 + (rnd(tb, seed, 2) - 0.5) * 2.0 * P['Length Variation']))
        roots = tb.store(roots, '_ph', rnd(tb, seed, 3, 0.0, TAU))
        roots = tb.store(roots, '_vv', rnd(tb, seed, 4))

        curves, s, _ = common.strands(tb, roots, P['Resolution'])
        root = tb.named('_root', 'FLOAT_VECTOR')
        n = tb.named('_n', 'FLOAT_VECTOR')
        own = _strand_shape(tb, P, root, n, tb.named('_len'), s, tb.named('_ph'))
        cl_root = tb.named('_cl_root', 'FLOAT_VECTOR')
        lead = _strand_shape(tb, P, cl_root, tb.named('_cl_n', 'FLOAT_VECTOR'), tb.named('_cl_len'), s,
                             tb.named('_cl_ph'))
        lead = lead + (root - cl_root) * (1.0 - s)
        pull = P['Clumping'] * tb.pow(s, P['Clump Shape'])
        gen_pos = tb.lerp(own, lead, pull)
        generated = tb.set_position(curves, gen_pos)
        generated = tb.store(generated, '_s', s)

        # ---- optional guide curves ----------------------------------------------
        gi = tb.object_info(P['Guide Curves'])
        guides = tb.realize(gi['Geometry'])
        guides = tb.node('GeometryNodeResampleCurve', {'Curve': guides, 'Count': P['Resolution']}).out
        guides = tb.store(guides, '_s', tb.node('GeometryNodeSplineParameter')['Factor'])
        guides = tb.store(guides, '_vv', tb.rand('FLOAT', 0.0, 1.0,
                                                 id=tb.node('GeometryNodeCurveOfPoint')['Curve Index'],
                                                 seed=seed + 4))
        has_guides = tb.compare('GREATER_THAN', tb.node('GeometryNodeAttributeDomainSize', {'Geometry': guides},
                                                        component='CURVE')['Point Count'], 0, 'INT')
        crv = tb.switch(has_guides, generated, guides, 'GEOMETRY')

        # ---- wind + frizz (applied to both sources) --------------------------------
        sp = tb.named('_s')
        first = tb.node('GeometryNodePointsOfCurve',
                        {'Curve Index': tb.node('GeometryNodeCurveOfPoint')['Curve Index'], 'Sort Index': 0})
        root_any = tb.sample_index(crv, tb.position(), first['Point Index'], 'FLOAT_VECTOR')
        wind = wind_offset(tb, P, root_any, t, loop, tb.length(root_any) * 7.0)
        stiff = tb.pow(sp, P['Stiffness'])
        frz = tb.noise(tb.position() * 25.0 + root_any * 3.0, scale=1.0, detail=1.0)[1]
        frizz = (frz - (0.5, 0.5, 0.5)) * (P['Frizz'] * 2.0 * sp)
        pos = tb.position() + wind * stiff * 0.5 + frizz
        crv = tb.set_position(crv, pos)

        cam = common.camera_location(tb, P['Camera'])
        facing = common.facing_blend(tb, tb.position(), cam, P['Face Camera'],
                                     tb.normalize(root_any - (0.0, 0.0, 0.0) + (1e-4, 0, 0)))
        width = P['Strand Width'] * (1.0 - P['Taper'] * tb.pow(sp, 1.3))
        col = tb.mix_color(tb.smoothstep(0.0, 1.0, sp), P['Root Color'], P['Tip Color'])
        vv = 1.0 + (tb.named('_vv') - 0.5) * 2.0 * P['Value Variation']
        col = tb.mix_color(1.0, col, tb.combine(vv, vv, vv), blend='MULTIPLY')
        return common.ribbons(tb, {
            'Curves': crv, 'Width': width, 'Facing': facing, 'Color': col, 'Opacity': P['Opacity'],
            'Seed': seed, 'Material': P['Material'],
        })
