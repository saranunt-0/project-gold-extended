# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Helpers shared by effect recipes."""

import bpy

from ..core import strokes
from ..core.nodes import TAU, TreeBuilder
from ..core.params import P, Panel


def animation_panel(speed=1.0, loop=0, extra=()):
    return Panel('Animation', [
        P('Speed', 'FLOAT', speed, -10.0, 10.0, desc='Time scale of the whole effect (negative plays backwards)'),
        P('Time Offset', 'FLOAT', 0.0, -100000.0, 100000.0, desc='Shift the animation by N frames'),
        P('Loop Frames', 'INT', loop, 0, 100000,
          desc='Make the animation loop seamlessly every N frames (0 = no loop). '
               'Periods are quantised so every cycle fits the loop'),
        *extra,
    ], closed=True, desc='Time controls. All motion is stateless: scrub anywhere, render on any machine')


def cards(tb: TreeBuilder, inputs: dict):
    """Instance the shared Stroke Cards group (points -> brush cards)."""
    return tb.group(bpy.data.node_groups[strokes.CARDS], inputs).out


def ribbons(tb: TreeBuilder, inputs: dict):
    """Instance the shared Stroke Ribbons group (curves -> brush ribbons)."""
    return tb.group(bpy.data.node_groups[strokes.RIBBONS], inputs).out


def rnd(tb: TreeBuilder, seed, salt: int, lo=0.0, hi=1.0, id=None, dtype='FLOAT'):
    """Per-element random value, decorrelated by ``salt``."""
    return tb.rand(dtype, lo, hi, id=id if id is not None else tb.index(), seed=seed + salt)


def time(tb: TreeBuilder, P):
    g = tb.group(bpy.data.node_groups[strokes.TIME],
                 {'Speed': P['Speed'], 'Offset': P['Time Offset'], 'Loop Frames': P['Loop Frames']})
    return g['Time'], g['Loop']


def loop_noise(tb: TreeBuilder, vec, t, loop, scale=1.0, detail=1.0, roughness=0.5, seed=0.0):
    g = tb.group(bpy.data.node_groups[strokes.LOOP_NOISE],
                 {'Vector': vec, 'Time': t, 'Loop': loop, 'Scale': scale, 'Detail': detail,
                  'Roughness': roughness, 'Seed': seed})
    return g['Value'], g['Vector']


def scrolling_noise(tb: TreeBuilder, vec, velocity, t, loop, evolve=0.0, scale=1.0, detail=1.0,
                    roughness=0.5, seed=0.0):
    """Noise field translating with ``velocity`` that still loops seamlessly.

    A translating field is never periodic, so in loop mode two copies are
    blended: one sampled at ``p - v*tm`` and one a full loop behind
    (``p - v*(tm - L)``), cross-faded by ``tm / L`` with ``tm = t mod L``.
    Both ends of the loop then sample ``p`` exactly.
    """
    use_loop = tb.compare('GREATER_THAN', loop, 1e-5)
    L = tb.max(loop, 1e-5)
    tm = tb.switch(use_loop, t, tb.mod(t, L))
    f = tb.switch(use_loop, 0.0, tm / L)
    va, a = loop_noise(tb, (vec - velocity * tm) * scale, t * evolve, loop * evolve, 1.0, detail, roughness, seed)
    vb, b = loop_noise(tb, (vec - velocity * (tm - L)) * scale, t * evolve, loop * evolve, 1.0, detail, roughness,
                       seed)
    return tb.lerp(va, vb, f), tb.lerp(a, b, f)


def surface_mask(tb: TreeBuilder, surf, attr_name):
    """Store a 0-1 growth mask on the surface so it survives point distribution.

    Vertex groups are not propagated by *Distribute Points on Faces*, so the
    weight is copied to a regular attribute first.  Empty/missing name = 1.
    """
    na = tb.node('GeometryNodeInputNamedAttribute', {'Name': attr_name}, data_type='FLOAT')
    weight = tb.switch(na['Exists'], 1.0, na['Attribute'])
    return tb.store(surf, '_gx_mask', weight, 'FLOAT', 'POINT')


def camera_location(tb: TreeBuilder, cam):
    return tb.group(bpy.data.node_groups[strokes.CAMERA], {'Camera': cam})['Location']


def quantize_freq(tb: TreeBuilder, freq, loop):
    """Round a frequency (Hz in effect time) so it loops in ``loop`` seconds."""
    use_loop = tb.compare('GREATER_THAN', loop, 1e-5)
    q = tb.round(freq * loop) / tb.max(loop, 1e-5)
    return tb.switch(use_loop, freq, q)


def quantize_period(tb: TreeBuilder, period, loop):
    """Return (period, cycles_per_loop) adjusted so ``loop`` holds whole cycles."""
    use_loop = tb.compare('GREATER_THAN', loop, 1e-5)
    n = tb.max(tb.round(loop / tb.max(period, 1e-4)), 1.0)
    return tb.switch(use_loop, period, loop / n), n


def cycle(tb: TreeBuilder, t, period, phase, loop):
    """Stateless life cycle.

    Returns (u, k): ``u`` in [0, 1) is the normalised age, ``k`` an integer
    cycle id used to re-randomise each rebirth (wrapped in loop mode so the
    loop end matches the start).
    """
    per, n = quantize_period(tb, period, loop)
    c = t / per + phase
    u = tb.fract(c)
    k = tb.floor(c)
    use_loop = tb.compare('GREATER_THAN', loop, 1e-5)
    k = tb.switch(use_loop, k, tb.mod(k, n))
    return u, k, per


def facing_blend(tb: TreeBuilder, pos, cam_loc, amount, random_vec):
    to_cam = tb.normalize(cam_loc - pos)
    return tb.normalize(tb.lerp(tb.normalize(random_vec), to_cam, amount))


def domain_wire(tb: TreeBuilder, geo_in, show):
    """Viewport-only wireframe of the input domain (edges never render)."""
    edges = tb.delete(geo_in, True, domain='FACE', mode='ONLY_FACE')
    vis = tb.bool_math('AND', tb.is_viewport(), show)
    return tb.switch(vis, None, edges, 'GEOMETRY')


def sun_direction(tb: TreeBuilder, sun_obj, fallback):
    """Direction *towards* the light: from a Sun object's rotation or a vector."""
    info = tb.object_info(sun_obj)
    d = tb.node('FunctionNodeRotateVector', {'Vector': (0.0, 0.0, 1.0), 'Rotation': info['Rotation']}).out
    has = tb.compare('GREATER_THAN', tb.length(info['Scale']), 0.0)
    return tb.normalize(tb.switch(has, fallback, d, 'VECTOR'))


def surface_geometry(tb: TreeBuilder, P):
    """Geometry of the referenced surface object, in this object's space."""
    return tb.object_info(P['Surface'])['Geometry']


def strands(tb: TreeBuilder, roots, resolution):
    """One curve per root point with ``resolution`` points.

    Returns (curves, s, root_index): ``s`` is the 0-1 parameter along each
    strand and ``root_index`` the index of the originating root point.
    """
    line = tb.node('GeometryNodeCurvePrimitiveLine', {'Start': (0, 0, 0), 'End': (0, 0, 1)}).out
    line = tb.node('GeometryNodeResampleCurve', {'Curve': line, 'Count': resolution}).out
    inst = tb.node('GeometryNodeInstanceOnPoints', {'Points': roots, 'Instance': line}).out
    inst = tb.node('GeometryNodeStoreNamedAttribute', {'Geometry': inst, 'Name': '_gx_root', 'Value': tb.index()},
                   data_type='INT', domain='INSTANCE').out
    curves = tb.realize(inst)
    s = tb.node('GeometryNodeSplineParameter')['Factor']
    return curves, s, tb.named('_gx_root', 'INT')

