# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Water: painterly water surfaces.

Waves are a sum of three directional (Gerstner-style) waves with deep-water
dispersion ``omega = sqrt(g * k)`` – long waves travel faster, which is what
makes the motion read as water – plus looping ripple noise.  Each wave's
angular frequency is quantised to the loop when looping.

On top of the waves:

* **Strokes** lie flat on the displaced surface, aligned to the flow, and
  live short lives (fading in/out) while drifting along the flow;
* **Foam** scumbles appear on wave crests;
* **Sparkles** are emissive dabs where the sun's reflection reaches the
  camera (``dot(reflect(-sun, n), view) ^ sharpness``);
* an optional **water body** (the surface, subdivided and displaced) gives a
  painted base colour under the strokes.
"""

import bmesh

from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import TAU, rnd

G = 9.81
WAVES = ((0.0, 1.0, 1.0), (1.0, 0.61, 0.5), (-0.7, 0.37, 0.3))   # (spread factor, wavelength, amplitude)


def wave_field(tb, P, t, loop):
    """Height, horizontal displacement and normal as fields of ``position``."""
    p = tb.position() * (1.0, 1.0, 0.0)
    d0 = tb.normalize(P['Direction'] * (1.0, 1.0, 0.0) + (1e-5, 0.0, 0.0))
    height = None
    disp = None
    hx = hy = None
    for spread_f, lam_f, amp_f in WAVES:
        dk = tb.rotate_axis(d0, (0.0, 0.0, 1.0), P['Direction Spread'] * spread_f) if spread_f else d0
        lam = tb.max(P['Wavelength'] * lam_f, 1e-3)
        kappa = TAU / lam
        amp = P['Wave Height'] * amp_f
        omega = tb.sqrt(kappa * G) * P['Wave Speed']
        omega = common.quantize_freq(tb, omega / TAU, loop) * TAU
        phase = kappa * tb.dot(dk, p) - omega * t
        sp, cp = tb.sin(phase), tb.cos(phase)
        h = amp * sp
        dvec = dk * (amp * P['Choppiness'] * -1.0 * cp)
        dkx, dky, _ = tb.sep(dk)
        gx = amp * kappa * dkx * cp
        gy = amp * kappa * dky * cp
        height = h if height is None else height + h
        disp = dvec if disp is None else disp + dvec
        hx = gx if hx is None else hx + gx
        hy = gy if hy is None else hy + gy
    rip, _ = common.loop_noise(tb, p * P['Ripple Scale'], t * 0.5, loop * 0.5, scale=1.0, detail=2.0)
    height = height + rip * P['Ripple']
    normal = tb.normalize(tb.combine(hx * -1.0, hy * -1.0, 1.0))
    return height, disp * (1.0, 1.0, 0.0), normal


def apply_waves(tb, geo, field, lift=0.0):
    """Store wave attributes on ``geo`` (at its current positions) and displace it."""
    height, disp, normal = field
    geo = tb.store(geo, '_wh', height)
    geo = tb.store(geo, '_wn', normal, 'FLOAT_VECTOR')
    geo = tb.store(geo, '_wd', disp, 'FLOAT_VECTOR')
    off = tb.named('_wd', 'FLOAT_VECTOR') + tb.combine(0.0, 0.0, tb.named('_wh') + lift)
    return tb.set_position(geo, offset=off)


def height_color(tb, P, hn):
    """Deep -> shallow -> crest colour by normalised height ``hn`` in [-1, 1]."""
    hn = hn * P['Color by Height']
    c = tb.mix_color(tb.smoothstep(-1.0, 0.1, hn), P['Deep Color'], P['Shallow Color'])
    return tb.mix_color(tb.smoothstep(0.2, 1.0, hn), c, P['Crest Color'])


@register_effect
class Water(Effect):
    id = 'WATER'
    label = 'Water'
    icon = 'MOD_OCEAN'
    category = 'Elements'
    description = 'Painterly water: wave-driven flow strokes, crest foam, sun sparkles and a painted body'
    host = 'SURFACE'
    hide_surface = True

    spec = [
        Panel('Source', [
            P('Surface', 'OBJECT', desc='Water surface mesh (roughly horizontal)'),
            P('Seed', 'INT', 0, 0, 100000),
        ]),
        Panel('Waves', [
            P('Wave Height', 'FLOAT', 0.12, 0.0, 100.0, 'DISTANCE', 'Amplitude of the main wave'),
            P('Wavelength', 'FLOAT', 2.5, 0.01, 1000.0, 'DISTANCE'),
            P('Direction', 'VECTOR', (1.0, 0.35, 0.0), subtype='XYZ', desc='Wave travel and flow direction'),
            P('Direction Spread', 'FLOAT', 0.5, 0.0, 3.1416, 'ANGLE', 'Angle between the wave trains'),
            P('Choppiness', 'FLOAT', 0.6, 0.0, 2.0, desc='Sharp crests, broad troughs (Gerstner)'),
            P('Wave Speed', 'FLOAT', 1.0, 0.0, 10.0, desc='Multiplier on physical deep-water speed'),
            P('Ripple', 'FLOAT', 0.02, 0.0, 10.0, 'DISTANCE', 'Small noise ripples'),
            P('Ripple Scale', 'FLOAT', 2.5, 0.001, 100.0),
        ], desc='Sum of three dispersive wave trains'),
        Panel('Strokes', [
            P('Density', 'FLOAT', 25.0, 0.0, 10000.0, desc='Strokes per square metre'),
            P('Stroke Length', 'FLOAT', 0.45, 0.0, 100.0, 'DISTANCE'),
            P('Stroke Width', 'FLOAT', 0.08, 0.0, 10.0, 'DISTANCE'),
            P('Length Variation', 'FLOAT', 0.5, 0.0, 1.0, 'FACTOR'),
            P('Align to Flow', 'FLOAT', 0.85, 0.0, 1.0, 'FACTOR', 'Strokes follow the flow (1) or scatter (0)'),
            P('Flow Speed', 'FLOAT', 0.25, -50.0, 50.0, 'VELOCITY', 'Drift of strokes along the flow'),
            P('Stroke Life', 'FLOAT', 2.5, 0.05, 60.0, 'TIME', 'Seconds each stroke lives before re-spawning'),
            P('Lift', 'FLOAT', 0.01, -1.0, 1.0, 'DISTANCE', 'Offset above the water body'),
        ]),
        Panel('Color', [
            P('Deep Color', 'COLOR', (0.03, 0.16, 0.3, 1.0)),
            P('Shallow Color', 'COLOR', (0.1, 0.42, 0.55, 1.0)),
            P('Crest Color', 'COLOR', (0.55, 0.82, 0.88, 1.0)),
            P('Color by Height', 'FLOAT', 1.0, 0.0, 2.0, desc='How strongly wave height drives colour'),
            P('Opacity', 'FLOAT', 0.85, 0.0, 1.0, 'FACTOR'),
        ]),
        Panel('Foam', [
            P('Foam Amount', 'FLOAT', 0.3, 0.0, 1.0, 'FACTOR', 'How much of the crests carry foam'),
            P('Foam Density', 'FLOAT', 20.0, 0.0, 10000.0),
            P('Foam Size', 'FLOAT', 0.12, 0.0, 10.0, 'DISTANCE'),
            P('Foam Color', 'COLOR', (0.92, 0.97, 1.0, 1.0)),
        ], closed=True),
        Panel('Sparkles', [
            P('Sparkle Amount', 'FLOAT', 0.6, 0.0, 1.0, 'FACTOR'),
            P('Sparkle Density', 'FLOAT', 30.0, 0.0, 10000.0),
            P('Sparkle Size', 'FLOAT', 0.04, 0.0, 10.0, 'DISTANCE'),
            P('Sparkle Sharpness', 'FLOAT', 24.0, 1.0, 500.0, desc='Higher = tighter sun glints'),
            P('Sparkle Color', 'COLOR', (1.0, 0.97, 0.85, 1.0)),
            P('Sun', 'OBJECT', desc='Light whose reflection makes sparkles (empty = Sun Direction)'),
            P('Sun Direction', 'VECTOR', (0.3, 0.9, 0.35), subtype='XYZ', desc='Direction towards the sun'),
            P('Camera', 'OBJECT', desc='Viewing camera (empty = scene camera)'),
        ], closed=True),
        Panel('Water Body', [
            P('Show Body', 'BOOL', True, desc='Render the displaced surface under the strokes'),
            P('Body Subdivisions', 'INT', 4, 0, 8, desc='Subdivision levels for the body displacement'),
        ], closed=True),
        common.animation_panel(),
        Panel('Display', [
            P('Stroke Material', 'MATERIAL', hidden=True),
            P('Foam Material', 'MATERIAL', hidden=True),
            P('Sparkle Material', 'MATERIAL', hidden=True),
            P('Body Material', 'MATERIAL', hidden=True),
        ], closed=True),
    ]

    materials = [
        MaterialSlot('Stroke Material', 'Strokes', 'Streak', 'Default',
                     {'Shading': 0.45, 'Gloss': 0.5, 'Roughness': 0.25, 'Sheen': 0.25,
                      'Sheen Tint': (0.8, 0.95, 1.0, 1.0), 'Color Jitter': 0.12}),
        MaterialSlot('Foam Material', 'Foam', 'Scumble', 'Default', {'Shading': 0.3, 'Gloss': 0.0}),
        MaterialSlot('Sparkle Material', 'Sparkles', 'Soft Dab', 'Default',
                     {'Shading': 0.0, 'Emission': 5.0, 'Gloss': 0.0}),
        MaterialSlot('Body Material', 'Body', None, 'Default',
                     {'Shading': 0.5, 'Gloss': 0.6, 'Roughness': 0.15, 'Color Jitter': 0.0, 'Sheer': 0.2,
                      'Stroke Normal': 0.0}),
    ]

    presets = {
        'Lake': {},
        'Ocean Swell': {'Wave Height': 0.45, 'Wavelength': 7.0, 'Choppiness': 0.9, 'Density': 18.0,
                        'Stroke Length': 0.8, 'Foam Amount': 0.45, 'Deep Color': (0.02, 0.1, 0.22, 1.0)},
        'Calm Pond': {'Wave Height': 0.02, 'Wavelength': 1.2, 'Choppiness': 0.2, 'Ripple': 0.01,
                      'Flow Speed': 0.05, 'Foam Amount': 0.0, 'Shallow Color': (0.2, 0.45, 0.35, 1.0),
                      'Deep Color': (0.05, 0.2, 0.15, 1.0), 'Crest Color': (0.6, 0.78, 0.7, 1.0)},
        'River': {'Wave Height': 0.04, 'Wavelength': 0.8, 'Direction Spread': 0.2, 'Flow Speed': 1.2,
                  'Align to Flow': 1.0, 'Stroke Length': 0.9, 'Stroke Width': 0.05, 'Density': 40.0,
                  'Stroke Life': 1.5},
        'Stylized Toon': {'Density': 12.0, 'Stroke Width': 0.15, 'Foam Amount': 0.5, 'Sparkle Amount': 0.9,
                          '_look': {'Strokes': {'Shading': 0.0, 'Posterize': 3.0, 'Hardness': 0.7},
                                    'Body': {'Shading': 0.0, 'Posterize': 3.0}}},
    }

    variants = [Variant('Water', 'Lake', 'MOD_OCEAN', 'Water on the selected mesh (or a new plane)')]

    def make_mesh(self, mesh):
        bm = bmesh.new()
        bmesh.ops.create_grid(bm, x_segments=4, y_segments=4, size=4.0)
        bm.to_mesh(mesh)
        bm.free()

    def _spawn(self, tb, P, surf, density, life, salt, t, loop):
        """Short-lived points re-spawned at random surface positions."""
        seed = P['Seed']
        bb = tb.bound_box(surf)
        bmin, bmax = bb['Min'], bb['Max']
        size = tb.max(bmax - bmin, (1e-3, 1e-3, 1e-3))
        sx, sy, sz = tb.sep(size)
        count = density * sx * sy
        pts = tb.node('GeometryNodePoints', {'Count': count}).out
        per_life = life * rnd(tb, seed, salt + 1, 0.6, 1.4)
        u, k, per = common.cycle(tb, t, per_life, rnd(tb, seed, salt + 2), loop)
        cs = seed * 31 + k * 7919 + salt
        x = tb.rand('FLOAT', 0.0, 1.0, id=tb.index(), seed=cs + 1)
        y = tb.rand('FLOAT', 0.0, 1.0, id=tb.index(), seed=cs + 2)
        flow_dir = tb.normalize(P['Direction'] * (1.0, 1.0, 0.0) + (1e-5, 0.0, 0.0))
        p = bmin + tb.combine(x * sx, y * sy, 0.0) + flow_dir * (P['Flow Speed'] * u * per)
        src = tb.combine(tb.sep(p)[0], tb.sep(p)[1], tb.sep(bmax)[2] + 1.0)
        ray = tb.node('GeometryNodeRaycast', {'Target Geometry': surf, 'Source Position': src,
                                              'Ray Direction': (0.0, 0.0, -1.0), 'Ray Length': sz + 2.0})
        pts = tb.set_position(pts, ray['Hit Position'])
        pts = tb.store(pts, '_hit', ray['Is Hit'], 'BOOLEAN')
        pts = tb.store(pts, '_u', u)
        pts = tb.delete(pts, tb.bool_math('NOT', tb.named('_hit', 'BOOLEAN')))
        return pts, flow_dir

    def build(self, tb, P):
        seed = P['Seed']
        surf = common.surface_geometry(tb, P)
        t, loop = common.time(tb, P)
        field = wave_field(tb, P, t, loop)
        cam = common.camera_location(tb, P['Camera'])
        H = tb.max(P['Wave Height'] * 1.8 + P['Ripple'], 1e-4)
        env = tb.pow(tb.sin(tb.named('_u') * 3.14159), 0.5)

        # ---- flow strokes -------------------------------------------------------
        pts, flow_dir = self._spawn(tb, P, surf, P['Density'], P['Stroke Life'], 0, t, loop)
        pts = apply_waves(tb, pts, field, P['Lift'])
        wn = tb.named('_wn', 'FLOAT_VECTOR')
        rand_dir = tb.rand('FLOAT_VECTOR', (-1, -1, 0), (1, 1, 0), id=tb.index(), seed=seed + 5)
        d = tb.lerp(tb.normalize(rand_dir + (1e-4, 0, 0)), flow_dir, P['Align to Flow'])
        d = tb.normalize(d - wn * tb.dot(d, wn))
        length = P['Stroke Length'] * (1.0 + (rnd(tb, seed, 6) - 0.5) * 2.0 * P['Length Variation'])
        hn = tb.named('_wh') / H
        strokes = common.cards(tb, {
            'Points': pts, 'Direction': d, 'Facing': wn, 'Width': P['Stroke Width'], 'Length': length,
            'Color': height_color(tb, P, hn), 'Opacity': P['Opacity'] * env, 'Normal': wn, 'Seed': seed,
            'Material': P['Stroke Material'],
        })

        # ---- foam on crests ----------------------------------------------------------
        fpts, _ = self._spawn(tb, P, surf, P['Foam Density'], P['Stroke Life'] * 0.6, 100, t, loop)
        fpts = apply_waves(tb, fpts, field, P['Lift'] * 2.0)
        fh = tb.clamp01(tb.named('_wh') / H * 0.5 + 0.5)
        fa = P['Foam Amount']
        foam_mask = tb.smoothstep(1.0 - fa - 0.12, 1.0 - fa + 0.12, fh) * tb.math('GREATER_THAN', fa, 0.001)
        fdir = tb.normalize(flow_dir - tb.named('_wn', 'FLOAT_VECTOR') * tb.dot(flow_dir, tb.named('_wn',
                                                                                                   'FLOAT_VECTOR')))
        fsize = P['Foam Size'] * rnd(tb, seed, 101, 0.6, 1.4)
        foam = common.cards(tb, {
            'Points': fpts, 'Direction': fdir, 'Facing': tb.named('_wn', 'FLOAT_VECTOR'), 'Width': fsize,
            'Length': fsize * 1.8, 'Color': P['Foam Color'], 'Opacity': foam_mask * env,
            'Normal': tb.named('_wn', 'FLOAT_VECTOR'), 'Seed': seed + 1, 'Material': P['Foam Material'],
        })

        # ---- sun sparkles ------------------------------------------------------------------
        spts, _ = self._spawn(tb, P, surf, P['Sparkle Density'], 0.6, 200, t, loop)
        spts = apply_waves(tb, spts, field, P['Lift'] * 3.0)
        sn = tb.named('_wn', 'FLOAT_VECTOR')
        sun = common.sun_direction(tb, P['Sun'], P['Sun Direction'])
        pos = tb.position()
        view = tb.normalize(cam - pos)
        refl = sun * -1.0 + sn * (2.0 * tb.dot(sun, sn))
        spec = tb.pow(tb.max(tb.dot(refl, view), 0.0), P['Sparkle Sharpness'])
        s_op = P['Sparkle Amount'] * tb.smoothstep(0.15, 0.6, spec) * tb.pow(tb.sin(tb.named('_u') * 3.14159), 2.0)
        ssz = P['Sparkle Size'] * (0.6 + spec)
        s_up = tb.normalize(tb.cross(view, tb.cross((0.0, 0.0, 1.0), view)) + (1e-4, 0.0, 0.0))
        sparkles = common.cards(tb, {
            'Points': spts, 'Direction': tb.rotate_axis(s_up, view, rnd(tb, seed, 201, 0.0, TAU)), 'Facing': view,
            'Width': ssz, 'Length': ssz, 'Color': P['Sparkle Color'], 'Opacity': s_op, 'Seed': seed + 2,
            'Material': P['Sparkle Material'],
        })

        # ---- water body ------------------------------------------------------------------------
        body = tb.node('GeometryNodeSubdivideMesh', {'Mesh': surf, 'Level': P['Body Subdivisions']}).out
        body = apply_waves(tb, body, field)
        body = tb.store(body, 'brush_stroke.color', height_color(tb, P, tb.named('_wh') / H), 'FLOAT_COLOR')
        body = tb.store(body, 'brush_stroke.normal', tb.named('_wn', 'FLOAT_VECTOR'), 'FLOAT_VECTOR')
        body = tb.store(body, 'opacity', 1.0)
        body = tb.set_material(body, P['Body Material'])
        body = tb.node('GeometryNodeSetShadeSmooth', {'Mesh': body, 'Shade Smooth': True}).out
        body = tb.switch(P['Show Body'], None, body, 'GEOMETRY')

        return tb.join(body, strokes, foam, sparkles)
