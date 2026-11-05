# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Cloud: painterly cumulus made of lit brush puffs.

The object's own mesh is the cloud *shape* – sculpt or edit it freely.
Puffs are scattered on and just under that surface, displaced by looping
noise (billowing), and coloured with a painter's lighting model:

    light  = wrap(dot(puff_normal, sun))          lit <-> shadow colour
    height = gradient from the base colour up    darker, cooler bottoms
    rim    = silhouette * back-light              silver lining

The puff normal is also written to ``brush_stroke.normal`` so the Look
shader's *Stroke Normal* option can light puffs as spheres in render.
"""

import bmesh
from mathutils import Matrix

from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import TAU, rnd


@register_effect
class Cloud(Effect):
    id = 'CLOUD'
    label = 'Cloud'
    icon = 'OUTLINER_DATA_VOLUME'
    category = 'Atmosphere'
    description = 'Painterly clouds from lit brush puffs scattered over an editable shape'
    host = 'DOMAIN'

    spec = [
        Panel('Shape', [
            P('Density', 'FLOAT', 5.0, 0.0, 1000.0, desc='Puffs per square metre of the cloud shape surface'),
            P('Seed', 'INT', 0, 0, 100000),
            P('Puff Size', 'FLOAT', 0.7, 0.0, 100.0, 'DISTANCE', 'Average puff diameter'),
            P('Size Variation', 'FLOAT', 0.5, 0.0, 1.0, 'FACTOR'),
            P('Depth', 'FLOAT', 0.4, 0.0, 100.0, 'DISTANCE', 'How deep inside the shape puffs are scattered'),
            P('Billow', 'FLOAT', 0.35, 0.0, 100.0, 'DISTANCE', 'Cauliflower bulging along the surface normal'),
            P('Billow Scale', 'FLOAT', 0.7, 0.001, 100.0, desc='Size of the billows'),
            P('Flatten Bottom', 'FLOAT', 0.5, 0.0, 1.0, 'FACTOR', 'Flat cumulus base'),
        ]),
        Panel('Lighting', [
            P('Sun', 'OBJECT', desc='Light whose direction lights the cloud (empty = Sun Direction)'),
            P('Sun Direction', 'VECTOR', (0.4, -0.35, 0.85), subtype='XYZ', desc='Direction towards the sun'),
            P('Lit Color', 'COLOR', (1.0, 0.97, 0.9, 1.0)),
            P('Shadow Color', 'COLOR', (0.4, 0.46, 0.66, 1.0)),
            P('Base Color', 'COLOR', (0.42, 0.45, 0.58, 1.0), desc='Colour of the cloud base'),
            P('Light Wrap', 'FLOAT', 0.45, 0.0, 1.0, 'FACTOR', 'Soft light wrapping around the puffs'),
            P('Height Gradient', 'FLOAT', 0.7, 0.0, 1.0, 'FACTOR', 'Darken towards the base'),
            P('Rim Light', 'FLOAT', 0.35, 0.0, 2.0, desc='Silver lining on the back-lit silhouette'),
            P('Ambient', 'FLOAT', 0.15, 0.0, 1.0, 'FACTOR', 'Lift shadows toward the lit colour'),
        ], desc="A painter's lighting model baked into stroke colours"),
        Panel('Motion', [
            P('Evolve Speed', 'FLOAT', 0.12, 0.0, 10.0, desc='How fast billows churn'),
            P('Drift', 'VECTOR', (0.15, 0.0, 0.03), subtype='VELOCITY', desc='Internal flow of the billow pattern'),
            P('Puff Pulse', 'FLOAT', 0.15, 0.0, 1.0, 'FACTOR', 'Puff size breathing'),
            P('Dissipate', 'FLOAT', 0.0, 0.0, 1.0, 'FACTOR', 'Animated dissolving of the cloud'),
        ]),
        Panel('Stroke', [
            P('Face Camera', 'FLOAT', 1.0, 0.0, 1.0, 'FACTOR', 'Billboard puffs toward the camera'),
            P('Camera', 'OBJECT', desc='Camera to face (empty = scene camera)'),
            P('Opacity', 'FLOAT', 0.9, 0.0, 1.0, 'FACTOR'),
            P('Edge Softness', 'FLOAT', 0.5, 0.0, 1.0, 'FACTOR', 'Fade puffs at the silhouette for wispy edges'),
        ]),
        common.animation_panel(),
        Panel('Display', [
            P('Show Domain', 'BOOL', False, desc='Show the cloud shape wireframe in the viewport'),
            P('Material', 'MATERIAL', hidden=True),
        ], closed=True),
    ]

    materials = [MaterialSlot('Material', 'Puffs', 'Puff', 'Default',
                              {'Shading': 0.25, 'Translucency': 0.3, 'Gloss': 0.0, 'Color Jitter': 0.08,
                               'Stroke Normal': 1.0})]

    presets = {
        'Cumulus': {},
        'Storm Cloud': {
            'Density': 7.0, 'Puff Size': 0.9, 'Billow': 0.5, 'Lit Color': (0.78, 0.8, 0.85, 1.0),
            'Shadow Color': (0.2, 0.22, 0.3, 1.0), 'Base Color': (0.12, 0.13, 0.18, 1.0),
            'Height Gradient': 0.8, 'Rim Light': 0.2, 'Ambient': 0.05, 'Evolve Speed': 0.3,
            '_look': {'Puffs': {'Contrast': 0.2}},
        },
        'Sunset': {
            'Lit Color': (1.0, 0.72, 0.42, 1.0), 'Shadow Color': (0.45, 0.32, 0.55, 1.0),
            'Base Color': (0.35, 0.22, 0.42, 1.0), 'Rim Light': 0.8, 'Sun Direction': (-0.8, 0.3, 0.15),
            '_look': {'Puffs': {'Vibrance': 0.4}},
        },
        'Wispy': {
            'Density': 3.0, 'Puff Size': 0.5, 'Billow': 0.15, 'Flatten Bottom': 0.0, 'Opacity': 0.55,
            'Edge Softness': 0.8, 'Drift': (0.4, 0.0, 0.0), 'Evolve Speed': 0.25,
            '_brush': {'Puffs': 'Streak'},
            '_look': {'Puffs': {'Shading': 0.3, 'Dry Brush': 0.2}},
        },
        'Smoke Plume': {
            'Density': 8.0, 'Puff Size': 0.5, 'Lit Color': (0.55, 0.55, 0.55, 1.0),
            'Shadow Color': (0.2, 0.2, 0.22, 1.0), 'Base Color': (0.15, 0.15, 0.16, 1.0),
            'Flatten Bottom': 0.0, 'Evolve Speed': 0.5, 'Drift': (0.0, 0.0, 0.5), 'Dissipate': 0.2,
        },
    }

    variants = [Variant('Cloud', 'Cumulus', 'OUTLINER_DATA_VOLUME', 'Painterly cumulus cloud')]

    def make_mesh(self, mesh):
        bm = bmesh.new()
        lobes = [((0, 0, 0), 1.6), ((1.7, 0.2, -0.3), 1.2), ((-1.6, -0.1, -0.4), 1.1), ((0.5, 0.3, 0.9), 1.1)]
        for loc, r in lobes:
            bmesh.ops.create_icosphere(bm, subdivisions=3, radius=r,
                                       matrix=Matrix.Translation(loc) @ Matrix.Diagonal((1.0, 0.8, 0.75, 1.0)))
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0.0, 0.0, 4.0))
        bm.to_mesh(mesh)
        bm.free()

    def build(self, tb, P):
        geo_in = P['Geometry']
        seed = P['Seed']
        bb = tb.bound_box(geo_in)
        bmin, bmax = bb['Min'], bb['Max']
        center = (bmin + bmax) * 0.5
        size = tb.max(bmax - bmin, (1e-3, 1e-3, 1e-3))
        t, loop = common.time(tb, P)

        dist = tb.node('GeometryNodeDistributePointsOnFaces',
                       {'Mesh': geo_in, 'Density': P['Density'], 'Seed': seed}, distribute_method='RANDOM')
        pts = tb.store(dist['Points'], '_n', dist['Normal'], 'FLOAT_VECTOR')
        n = tb.named('_n', 'FLOAT_VECTOR')
        p0 = tb.position()

        ev = P['Evolve Speed']
        bil, _ = common.scrolling_noise(tb, p0, P['Drift'], t, loop, evolve=ev, scale=P['Billow Scale'],
                                        detail=2.0, seed=tb.math('ADD', seed, 0.0))
        depth = P['Depth'] * tb.sqrt(rnd(tb, seed, 1))
        pos = p0 - n * depth + n * (bil * P['Billow'])
        # flat base
        zb = tb.sep(bmin)[2] + (tb.sep(center)[2] - tb.sep(bmin)[2]) * P['Flatten Bottom']
        px, py, pz = tb.sep(pos)
        pos = tb.combine(px, py, tb.max(pz, zb))

        pn = tb.normalize(tb.lerp(n, tb.normalize(pos - center), 0.5))
        sun = common.sun_direction(tb, P['Sun'], P['Sun Direction'])
        wrap = P['Light Wrap']
        light = tb.clamp01((tb.dot(pn, sun) + wrap) / (1.0 + wrap))
        light = tb.smoothstep(0.0, 1.0, light)
        shadow = tb.mix_color(P['Ambient'], P['Shadow Color'], P['Lit Color'])
        col = tb.mix_color(light, shadow, P['Lit Color'])
        h = tb.clamp01((tb.sep(pos)[2] - tb.sep(bmin)[2]) / tb.sep(size)[2])
        col = tb.mix_color(tb.lerp(1.0, tb.smoothstep(0.0, 0.85, h), P['Height Gradient']), P['Base Color'], col)
        cam = common.camera_location(tb, P['Camera'])
        to_cam = tb.normalize(cam - pos)
        sil = 1.0 - tb.abs(tb.dot(pn, to_cam))
        back = (tb.dot(sun, to_cam * -1.0) + 1.0) * 0.5
        rim = P['Rim Light'] * sil * sil * (0.35 + back)
        col = tb.mix_color(tb.clamp01(rim), col, P['Lit Color'], blend='SCREEN')

        pulse, _ = common.loop_noise(tb, p0 * 0.5, t * ev * 2.0, loop * ev * 2.0, scale=1.0)
        psize = P['Puff Size'] * (1.0 + (rnd(tb, seed, 2) - 0.5) * 2.0 * P['Size Variation'])
        psize = psize * (1.0 + pulse * P['Puff Pulse'])
        diss, _ = common.scrolling_noise(tb, p0, P['Drift'], t, loop, evolve=ev, scale=0.6,
                                         seed=tb.math('ADD', seed, 5.0))
        thr = P['Dissipate'] * 2.0 - 1.0
        keep = tb.smoothstep(thr - 0.05, thr + 0.25, diss)
        edge = tb.lerp(1.0, tb.smoothstep(-0.05, 0.55, tb.dot(pn, to_cam)), P['Edge Softness'])
        opacity = P['Opacity'] * keep * edge

        facing = common.facing_blend(tb, pos, cam, P['Face Camera'], pn)
        up = tb.normalize(tb.cross(facing, tb.cross((0.0, 0.0, 1.0), facing)) + (1e-4, 0.0, 0.0))
        direction = tb.rotate_axis(up, facing, rnd(tb, seed, 3, 0.0, TAU))

        pts = tb.set_position(pts, pos)
        puffs = common.cards(tb, {
            'Points': pts, 'Direction': direction, 'Facing': facing, 'Width': psize, 'Length': psize,
            'Color': col, 'Opacity': opacity, 'Normal': pn, 'Seed': seed, 'Material': P['Material'],
        })
        return tb.join(puffs, common.domain_wire(tb, geo_in, P['Show Domain']))
