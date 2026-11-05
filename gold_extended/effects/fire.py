# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Fire: flame tongues, embers and smoke.

**Flames** – each tongue is a ribbon rooted on the emitter surface that lives
for ``Lifetime`` seconds: it grows and shrinks with ``env = sin(pi*u)^0.6``,
is pushed sideways by noise scrolling *upward* at ``Rise Speed`` (the classic
licking motion) and leans with the wind.  Colour runs core -> mid -> tip
along the tongue and cools with age; ``gx_emit`` drives emission in the Look.

**Embers** – small emissive dabs rising, swirling and flickering.

**Smoke** – grey puffs born above the flames, growing and fading.
"""

import bmesh

from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import TAU, rnd


@register_effect
class Fire(Effect):
    id = 'FIRE'
    label = 'Fire'
    icon = 'LIGHT_SUN'
    category = 'Elements'
    description = 'Painterly fire: licking flame tongues, embers and smoke'
    host = 'SURFACE'

    spec = [
        Panel('Source', [
            P('Surface', 'OBJECT', desc='Emitter mesh (logs, torch head, ground patch)'),
            P('Density', 'FLOAT', 60.0, 0.0, 100000.0, desc='Flame tongues per square metre of emitter'),
            P('Seed', 'INT', 0, 0, 100000),
        ]),
        Panel('Flames', [
            P('Height', 'FLOAT', 1.0, 0.0, 100.0, 'DISTANCE'),
            P('Height Variation', 'FLOAT', 0.45, 0.0, 1.0, 'FACTOR'),
            P('Width', 'FLOAT', 0.22, 0.0, 10.0, 'DISTANCE', 'Brush width of each tongue'),
            P('Lifetime', 'FLOAT', 0.7, 0.05, 20.0, 'TIME', 'Seconds each tongue lives'),
            P('Lifetime Variation', 'FLOAT', 0.4, 0.0, 1.0, 'FACTOR'),
            P('Rise Speed', 'FLOAT', 1.8, 0.0, 50.0, 'VELOCITY', 'Upward scroll of the licking turbulence'),
            P('Turbulence', 'FLOAT', 0.18, 0.0, 10.0, 'DISTANCE'),
            P('Turbulence Scale', 'FLOAT', 1.3, 0.001, 100.0),
            P('Lean', 'VECTOR', (0.15, 0.0, 0.0), subtype='XYZ', desc='Wind lean of the tongues'),
            P('Resolution', 'INT', 10, 2, 64),
            P('Camera', 'OBJECT', desc='Camera to face (empty = scene camera)'),
        ]),
        Panel('Flame Color', [
            P('Core Color', 'COLOR', (1.0, 0.85, 0.3, 1.0)),
            P('Mid Color', 'COLOR', (1.0, 0.48, 0.08, 1.0)),
            P('Tip Color', 'COLOR', (0.7, 0.1, 0.03, 1.0)),
            P('Core Size', 'FLOAT', 0.3, 0.0, 1.0, 'FACTOR', 'Portion of the tongue in the core colour'),
            P('Cooling', 'FLOAT', 0.35, 0.0, 1.0, 'FACTOR', 'Shift toward the tip colour as tongues age'),
            P('Opacity', 'FLOAT', 0.9, 0.0, 1.0, 'FACTOR'),
        ]),
        Panel('Embers', [
            P('Ember Count', 'INT', 60, 0, 100000, desc='0 disables embers'),
            P('Ember Size', 'FLOAT', 0.018, 0.0, 10.0, 'DISTANCE'),
            P('Ember Rise', 'FLOAT', 1.4, 0.0, 50.0, 'VELOCITY'),
            P('Ember Lifetime', 'FLOAT', 1.6, 0.05, 30.0, 'TIME'),
            P('Ember Turbulence', 'FLOAT', 0.35, 0.0, 10.0, 'DISTANCE'),
            P('Ember Color', 'COLOR', (1.0, 0.55, 0.12, 1.0)),
        ], closed=True),
        Panel('Smoke', [
            P('Smoke Count', 'INT', 25, 0, 100000, desc='0 disables smoke'),
            P('Smoke Size', 'FLOAT', 0.45, 0.0, 100.0, 'DISTANCE'),
            P('Smoke Rise', 'FLOAT', 0.8, 0.0, 50.0, 'VELOCITY'),
            P('Smoke Lifetime', 'FLOAT', 3.0, 0.05, 60.0, 'TIME'),
            P('Smoke Spread', 'FLOAT', 0.35, 0.0, 10.0, 'DISTANCE'),
            P('Smoke Color', 'COLOR', (0.2, 0.19, 0.19, 1.0)),
            P('Smoke Opacity', 'FLOAT', 0.35, 0.0, 1.0, 'FACTOR'),
        ], closed=True),
        common.animation_panel(),
        Panel('Display', [
            P('Flame Material', 'MATERIAL', hidden=True),
            P('Ember Material', 'MATERIAL', hidden=True),
            P('Smoke Material', 'MATERIAL', hidden=True),
        ], closed=True),
    ]

    materials = [
        MaterialSlot('Flame Material', 'Flames', 'Flame Tongue', 'Default',
                     {'Shading': 0.0, 'Emission': 1.6, 'Emission Attribute': 1.0, 'Vibrance': 0.5,
                      'Color Jitter': 0.1, 'Gloss': 0.0}),
        MaterialSlot('Ember Material', 'Embers', 'Soft Dab', 'Default',
                     {'Shading': 0.0, 'Emission': 6.0, 'Emission Attribute': 1.0, 'Gloss': 0.0}),
        MaterialSlot('Smoke Material', 'Smoke', 'Puff', 'Default',
                     {'Shading': 0.4, 'Gloss': 0.0, 'Translucency': 0.2, 'Color Jitter': 0.1}),
    ]

    presets = {
        'Campfire': {},
        'Torch': {'Density': 200.0, 'Height': 0.45, 'Width': 0.1, 'Lifetime': 0.45, 'Turbulence': 0.08,
                  'Ember Count': 25, 'Smoke Count': 12, 'Smoke Size': 0.2},
        'Inferno': {'Density': 90.0, 'Height': 2.2, 'Width': 0.4, 'Lifetime': 0.9, 'Turbulence': 0.35,
                    'Rise Speed': 2.5, 'Ember Count': 250, 'Smoke Count': 60, 'Smoke Size': 0.9,
                    'Smoke Color': (0.1, 0.09, 0.09, 1.0)},
        'Candle': {'Density': 3000.0, 'Height': 0.12, 'Height Variation': 0.1, 'Width': 0.04,
                   'Lifetime': 1.2, 'Turbulence': 0.004, 'Ember Count': 0, 'Smoke Count': 0,
                   'Core Color': (1.0, 0.97, 0.8, 1.0)},
        'Magic Blue': {'Core Color': (0.85, 0.97, 1.0, 1.0), 'Mid Color': (0.2, 0.55, 1.0, 1.0),
                       'Tip Color': (0.35, 0.1, 0.8, 1.0), 'Ember Color': (0.5, 0.8, 1.0, 1.0),
                       'Smoke Count': 0, '_look': {'Flames': {'Fringe': 0.4, 'Iridescence': 0.2}}},
    }

    variants = [Variant('Fire', 'Campfire', 'LIGHT_SUN', 'Fire on the selected mesh (or a new fire pit)')]

    def make_mesh(self, mesh):
        bm = bmesh.new()
        bmesh.ops.create_circle(bm, cap_ends=True, segments=16, radius=0.4)
        bm.to_mesh(mesh)
        bm.free()

    def build(self, tb, P):
        seed = P['Seed']
        surf = common.surface_geometry(tb, P)
        t, loop = common.time(tb, P)
        cam = common.camera_location(tb, P['Camera'])
        up = (0.0, 0.0, 1.0)

        dist = tb.node('GeometryNodeDistributePointsOnFaces',
                       {'Mesh': surf, 'Density': P['Density'], 'Seed': seed}, distribute_method='RANDOM')
        roots = dist['Points']

        # ---- flame tongues -------------------------------------------------------
        life = P['Lifetime'] * (1.0 + (rnd(tb, seed, 1) - 0.5) * 2.0 * P['Lifetime Variation'])
        u, k, per = common.cycle(tb, t, life, rnd(tb, seed, 2), loop)
        cs = seed * 13 + k * 101
        env = tb.pow(tb.sin(u * 3.14159), 0.6)
        h = P['Height'] * (1.0 + (tb.rand('FLOAT', -1.0, 1.0, id=tb.index(), seed=cs + 3)) * P['Height Variation'])
        jit = tb.rand('FLOAT_VECTOR', (-1, -1, 0), (1, 1, 0), id=tb.index(), seed=cs + 4) * (P['Width'] * 0.35)
        roots = tb.store(roots, '_root', tb.position() + jit, 'FLOAT_VECTOR')
        roots = tb.store(roots, '_h', h * (0.25 + 0.75 * env))
        roots = tb.store(roots, '_env', env)
        roots = tb.store(roots, '_u', u)
        roots = tb.store(roots, '_k', k)
        roots = tb.store(roots, '_age', u * per)

        curves, s, _ = common.strands(tb, roots, P['Resolution'])
        root = tb.named('_root', 'FLOAT_VECTOR')
        hh = tb.named('_h')
        ts = P['Turbulence Scale']
        # Noise scrolls upward with the tongue's *age* (periodic in loop mode),
        # evolution runs on the looping noise's own time axis.
        scroll = tb.combine(0.0, 0.0, tb.mul(s, hh) - tb.named('_age') * P['Rise Speed'])
        _, tv = common.loop_noise(tb, (root + scroll) * ts, t * 0.6 + tb.named('_k') * 3.7, loop * 0.6,
                                  scale=1.0, detail=1.5)
        sway = tv * (1.0, 1.0, 0.2) * (P['Turbulence'] * tb.pow(s, 1.3))
        pos = root + tb.combine(0.0, 0.0, 1.0) * (s * hh) + sway + P['Lean'] * (s * s * hh)
        curves = tb.set_position(curves, pos)
        cool = tb.clamp01(s + tb.named('_u') * P['Cooling'])
        c1 = tb.mix_color(tb.smoothstep(0.0, tb.max(P['Core Size'], 1e-3), cool), P['Core Color'], P['Mid Color'])
        col = tb.mix_color(tb.smoothstep(P['Core Size'], 1.0, cool), c1, P['Tip Color'])
        curves = tb.store(curves, 'gx_emit', tb.lerp(1.6, 0.4, cool))
        to_cam = tb.normalize(cam - pos)
        flames = common.ribbons(tb, {
            'Curves': curves, 'Width': P['Width'] * (0.55 + 0.45 * tb.named('_env')), 'Facing': to_cam,
            'Color': col, 'Opacity': P['Opacity'] * tb.smoothstep(0.0, 0.25, tb.named('_env')),
            'Seed': seed, 'Material': P['Flame Material'],
        })

        # ---- embers ------------------------------------------------------------------
        n_roots = tb.node('GeometryNodeAttributeDomainSize', {'Geometry': roots}, component='POINTCLOUD')['Point Count']
        em = tb.node('GeometryNodePoints', {'Count': P['Ember Count']}).out
        e_life = P['Ember Lifetime'] * rnd(tb, seed, 20, 0.5, 1.5)
        eu, ek, eper = common.cycle(tb, t, e_life, rnd(tb, seed, 21), loop)
        e_root_i = tb.int_math('MODULO', tb.hash_int(tb.math('ADD', tb.index(), ek * 977.0), seed),
                               tb.max(n_roots, 1))
        e_root_i = tb.int_math('ABSOLUTE', e_root_i)
        e_root = tb.sample_index(dist['Points'], tb.position(), e_root_i, 'FLOAT_VECTOR')
        e_age = eu * eper
        _, etv = common.loop_noise(tb, e_root * 2.0 + tb.combine(0.0, 0.0, e_age), t * 0.8, loop * 0.8, scale=1.0)
        e_pos = (e_root + tb.combine(0.0, 0.0, 1.0) * (P['Ember Rise'] * e_age * rnd(tb, seed, 22, 0.6, 1.4))
                 + etv * (P['Ember Turbulence'] * eu) + P['Lean'] * (e_age * 1.5))
        em = tb.set_position(em, e_pos)
        f_hz = common.quantize_freq(tb, rnd(tb, seed, 23, 2.5, 5.0), loop)
        flick = 0.65 + 0.35 * tb.sin(t * f_hz * TAU + rnd(tb, seed, 24, 0.0, TAU))
        em = tb.store(em, 'gx_emit', flick * 1.5)
        e_dir = tb.normalize(tb.combine(0.0, 0.0, 1.0) + etv * 0.5)
        embers = common.cards(tb, {
            'Points': em, 'Direction': e_dir, 'Facing': tb.normalize(cam - e_pos),
            'Width': P['Ember Size'] * (1.0 - eu * 0.6), 'Length': P['Ember Size'] * 2.0 * (1.0 - eu * 0.6),
            'Color': P['Ember Color'], 'Opacity': tb.smoothstep(0.0, 0.1, eu) * (1.0 - tb.smoothstep(0.6, 1.0, eu)),
            'Seed': seed + 1, 'Material': P['Ember Material'],
        })

        # ---- smoke ------------------------------------------------------------------------
        sm = tb.node('GeometryNodePoints', {'Count': P['Smoke Count']}).out
        s_life = P['Smoke Lifetime'] * rnd(tb, seed, 30, 0.7, 1.3)
        su, sk, sper = common.cycle(tb, t, s_life, rnd(tb, seed, 31), loop)
        s_root_i = tb.int_math('ABSOLUTE', tb.int_math('MODULO', tb.hash_int(
            tb.math('ADD', tb.index(), sk * 613.0), seed + 7), tb.max(n_roots, 1)))
        s_root = tb.sample_index(dist['Points'], tb.position(), s_root_i, 'FLOAT_VECTOR')
        s_age = su * sper
        _, stv = common.loop_noise(tb, s_root + tb.combine(0.0, 0.0, s_age * 0.5), t * 0.3, loop * 0.3, scale=0.8)
        s_pos = (s_root + tb.combine(0.0, 0.0, P['Height'] * 0.75 + P['Smoke Rise'] * s_age)
                 + stv * (P['Smoke Spread'] * su) + P['Lean'] * (s_age * 2.0))
        sm = tb.set_position(sm, s_pos)
        sm = tb.store(sm, 'gx_emit', 0.0)
        s_face = tb.normalize(cam - s_pos)
        s_up = tb.normalize(tb.cross(s_face, tb.cross(up, s_face)) + (1e-4, 0.0, 0.0))
        s_dir = tb.rotate_axis(s_up, s_face, rnd(tb, seed, 32, 0.0, TAU) + s_age * 0.3)
        s_size = P['Smoke Size'] * (0.35 + 0.65 * su)
        smoke = common.cards(tb, {
            'Points': sm, 'Direction': s_dir, 'Facing': s_face, 'Width': s_size, 'Length': s_size,
            'Color': tb.mix_color(su * 0.4, P['Smoke Color'], (0.45, 0.44, 0.44, 1.0)),
            'Opacity': P['Smoke Opacity'] * tb.pow(tb.sin(su * 3.14159), 0.7), 'Seed': seed + 2,
            'Material': P['Smoke Material'],
        })
        return tb.join(flames, embers, smoke)
