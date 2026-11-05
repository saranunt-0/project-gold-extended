# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Particles: rain, snow, sand and dust/dirt from one stateless engine.

Model (per particle *i*, effect time *t*):

* fall period ``T_i = H / speed_i`` (quantised to the loop when looping);
* cycle ``c = t / T_i + phase_i``; normalised age ``u = fract(c)``, rebirth
  id ``k = floor(c)`` re-randomises the spawn position every cycle;
* position = spawn + wind * age + looping turbulence + sway, wrapped
  horizontally into the domain, with an optional vortex around the domain
  axis;
* the brush card is stretched along the velocity (``Motion Stretch``) like
  a painter's motion streak.

Nothing is simulated, so the result is deterministic, scrubbable and loops
seamlessly when ``Loop Frames`` is set.
"""

from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import TAU, rnd


@register_effect
class Particles(Effect):
    id = 'PARTICLES'
    label = 'Particles'
    icon = 'PARTICLES'
    category = 'Particles'
    description = 'Painterly precipitation and airborne particles: rain, snow, sand, dust, dirt'
    host = 'DOMAIN'

    spec = [
        Panel('Emission', [
            P('Count', 'INT', 3000, 0, 1000000, desc='Number of particles in the domain'),
            P('Seed', 'INT', 0, 0, 100000, desc='Random seed'),
            P('Size', 'FLOAT', 0.03, 0.0, 100.0, 'DISTANCE', 'Stroke width'),
            P('Size Variation', 'FLOAT', 0.5, 0.0, 1.0, 'FACTOR', 'Random size spread'),
            P('Aspect', 'FLOAT', 1.0, 0.05, 50.0, desc='Stroke length / width at rest'),
        ], desc='How many particles and how big. The domain is the bounding box of this object'),
        Panel('Motion', [
            P('Fall Speed', 'FLOAT', 6.0, -200.0, 200.0, 'VELOCITY', 'Vertical speed (negative rises: bubbles, ash)'),
            P('Speed Variation', 'FLOAT', 0.2, 0.0, 1.0, 'FACTOR', 'Random speed spread'),
            P('Wind', 'VECTOR', (0.5, 0.0, 0.0), subtype='VELOCITY', desc='Constant drift velocity'),
            P('Turbulence', 'FLOAT', 0.0, 0.0, 50.0, 'DISTANCE', 'Amplitude of the swirling noise displacement'),
            P('Turbulence Scale', 'FLOAT', 0.5, 0.001, 100.0, desc='Spatial frequency of the turbulence'),
            P('Turbulence Speed', 'FLOAT', 0.5, 0.0, 20.0, desc='How fast the turbulence field evolves'),
            P('Sway', 'FLOAT', 0.0, 0.0, 10.0, 'DISTANCE', 'Side-to-side flutter (snowflakes, leaves)'),
            P('Sway Frequency', 'FLOAT', 0.5, 0.0, 20.0, desc='Flutter frequency in Hz'),
            P('Vortex', 'FLOAT', 0.0, -20.0, 20.0, desc='Swirl around the domain axis (rad/s): dust devils, blizzards'),
        ], desc='Physics-inspired but stateless motion model'),
        Panel('Stroke', [
            P('Motion Stretch', 'FLOAT', 0.0, 0.0, 2.0, desc='Stretch strokes along their velocity (seconds of '
                                                            'motion trail): long for rain, zero for snow'),
            P('Random Rotation', 'FLOAT', 1.0, 0.0, 1.0, 'FACTOR', 'Random stroke angle vs. aligned to motion'),
            P('Spin', 'FLOAT', 0.0, 0.0, 50.0, desc='Spin speed of each stroke (rad/s)'),
            P('Face Camera', 'FLOAT', 1.0, 0.0, 1.0, 'FACTOR', 'Billboard toward the camera (1) or tumble randomly (0)'),
            P('Camera', 'OBJECT', desc='Camera to face (empty = scene camera)'),
        ], desc='How each particle is painted'),
        Panel('Color', [
            P('Color', 'COLOR', (0.75, 0.82, 0.95, 1.0), desc='Main particle colour'),
            P('Color B', 'COLOR', (0.55, 0.62, 0.8, 1.0), desc='Secondary colour'),
            P('Color Mix', 'FLOAT', 0.3, 0.0, 1.0, 'FACTOR', 'Share of particles using Color B'),
            P('Value Variation', 'FLOAT', 0.15, 0.0, 1.0, 'FACTOR', 'Random brightness variation'),
            P('Opacity', 'FLOAT', 0.8, 0.0, 1.0, 'FACTOR', 'Particle opacity'),
            P('Fade Edges', 'FLOAT', 0.12, 0.0, 0.5, 'FACTOR', 'Fade near the domain boundaries (hides respawn)'),
        ]),
        Panel('Splash', [
            P('Splash Amount', 'FLOAT', 0.0, 0.0, 1.0, 'FACTOR', 'Share of particles that splash on the floor'),
            P('Splash Size', 'FLOAT', 0.15, 0.0, 10.0, 'DISTANCE', 'Splash radius'),
            P('Splash Duration', 'FLOAT', 0.25, 0.01, 5.0, 'TIME', 'Splash lifetime in seconds'),
            P('Splash Droplets', 'INT', 4, 1, 16, desc='Droplets per splash'),
        ], closed=True, desc='Rain hitting the domain floor'),
        common.animation_panel(),
        Panel('Display', [
            P('Show Domain', 'BOOL', True, desc='Show the domain box in the viewport (never renders)'),
            P('Material', 'MATERIAL', hidden=True),
        ], closed=True),
    ]

    materials = [MaterialSlot('Material', 'Particles', 'Streak', 'Default',
                              {'Shading': 0.3, 'Color Jitter': 0.1})]

    presets = {
        'Rain': {
            'Count': 4000, 'Size': 0.012, 'Size Variation': 0.4, 'Aspect': 1.0, 'Fall Speed': 9.0,
            'Speed Variation': 0.15, 'Wind': (1.2, 0.0, 0.0), 'Turbulence': 0.05, 'Sway': 0.0,
            'Motion Stretch': 0.045, 'Random Rotation': 0.0, 'Spin': 0.0, 'Face Camera': 1.0,
            'Color': (0.72, 0.8, 0.92, 1.0), 'Color B': (0.9, 0.94, 1.0, 1.0), 'Color Mix': 0.25,
            'Opacity': 0.55, 'Splash Amount': 0.6, 'Splash Size': 0.12, 'Vortex': 0.0,
            '_brush': {'Particles': 'Streak'},
            '_look': {'Particles': {'Shading': 0.2, 'Sheer': 0.3, 'Hardness': 0.2}},
        },
        'Storm': {
            'Count': 9000, 'Size': 0.014, 'Size Variation': 0.5, 'Aspect': 1.0, 'Fall Speed': 14.0,
            'Speed Variation': 0.25, 'Wind': (5.0, 1.0, 0.0), 'Turbulence': 0.4, 'Turbulence Scale': 0.3,
            'Turbulence Speed': 1.5, 'Motion Stretch': 0.05, 'Random Rotation': 0.0, 'Face Camera': 1.0,
            'Color': (0.6, 0.66, 0.78, 1.0), 'Color B': (0.85, 0.9, 1.0, 1.0), 'Opacity': 0.5,
            'Splash Amount': 0.8, 'Splash Size': 0.18,
            '_brush': {'Particles': 'Streak'},
            '_look': {'Particles': {'Shading': 0.2, 'Sheer': 0.3, 'Contrast': 0.2}},
        },
        'Snow': {
            'Count': 2500, 'Size': 0.035, 'Size Variation': 0.6, 'Aspect': 1.0, 'Fall Speed': 0.9,
            'Speed Variation': 0.35, 'Wind': (0.3, 0.1, 0.0), 'Turbulence': 0.25, 'Turbulence Scale': 0.6,
            'Turbulence Speed': 0.3, 'Sway': 0.15, 'Sway Frequency': 0.4, 'Motion Stretch': 0.0,
            'Random Rotation': 1.0, 'Spin': 1.5, 'Face Camera': 1.0,
            'Color': (0.95, 0.97, 1.0, 1.0), 'Color B': (0.8, 0.86, 0.98, 1.0), 'Color Mix': 0.35,
            'Opacity': 0.95, 'Splash Amount': 0.0,
            '_brush': {'Particles': 'Soft Dab'},
            '_look': {'Particles': {'Shading': 0.15, 'Hardness': 0.3, 'Translucency': 0.3}},
        },
        'Blizzard': {
            'Count': 9000, 'Size': 0.025, 'Size Variation': 0.6, 'Fall Speed': 2.5, 'Speed Variation': 0.4,
            'Wind': (6.0, 1.5, 0.0), 'Turbulence': 0.8, 'Turbulence Scale': 0.35, 'Turbulence Speed': 1.2,
            'Sway': 0.1, 'Motion Stretch': 0.04, 'Random Rotation': 0.3, 'Spin': 3.0, 'Vortex': 0.3,
            'Color': (0.93, 0.96, 1.0, 1.0), 'Color B': (0.75, 0.82, 0.95, 1.0), 'Opacity': 0.85,
            '_brush': {'Particles': 'Streak'},
            '_look': {'Particles': {'Shading': 0.15}},
        },
        'Sand': {
            'Count': 8000, 'Size': 0.012, 'Size Variation': 0.7, 'Aspect': 1.5, 'Fall Speed': 0.4,
            'Speed Variation': 0.6, 'Wind': (4.5, 0.5, 0.15), 'Turbulence': 0.6, 'Turbulence Scale': 0.4,
            'Turbulence Speed': 0.9, 'Sway': 0.05, 'Sway Frequency': 1.5, 'Motion Stretch': 0.06,
            'Random Rotation': 0.2, 'Spin': 4.0, 'Vortex': 0.0,
            'Color': (0.86, 0.68, 0.42, 1.0), 'Color B': (0.66, 0.47, 0.27, 1.0), 'Color Mix': 0.45,
            'Value Variation': 0.3, 'Opacity': 0.75, 'Splash Amount': 0.0,
            '_brush': {'Particles': 'Scumble'},
            '_look': {'Particles': {'Shading': 0.4, 'Dry Brush': 0.2, 'Vibrance': 0.2}},
        },
        'Dust Devil': {
            'Count': 6000, 'Size': 0.02, 'Size Variation': 0.7, 'Aspect': 1.2, 'Fall Speed': -0.8,
            'Speed Variation': 0.5, 'Wind': (0.6, 0.0, 0.0), 'Turbulence': 0.35, 'Turbulence Scale': 0.5,
            'Turbulence Speed': 0.8, 'Motion Stretch': 0.08, 'Random Rotation': 0.0, 'Vortex': 2.5,
            'Color': (0.78, 0.62, 0.42, 1.0), 'Color B': (0.55, 0.42, 0.3, 1.0), 'Opacity': 0.6,
            '_brush': {'Particles': 'Scumble'},
            '_look': {'Particles': {'Shading': 0.4, 'Dry Brush': 0.3}},
        },
        'Dust Motes': {
            'Count': 1500, 'Size': 0.012, 'Size Variation': 0.8, 'Aspect': 1.0, 'Fall Speed': 0.03,
            'Speed Variation': 1.0, 'Wind': (0.05, 0.02, 0.0), 'Turbulence': 0.3, 'Turbulence Scale': 0.8,
            'Turbulence Speed': 0.15, 'Sway': 0.05, 'Sway Frequency': 0.2, 'Motion Stretch': 0.0,
            'Random Rotation': 1.0, 'Spin': 0.5, 'Color': (1.0, 0.93, 0.75, 1.0),
            'Color B': (1.0, 0.85, 0.6, 1.0), 'Opacity': 0.7,
            '_brush': {'Particles': 'Soft Dab'},
            '_look': {'Particles': {'Shading': 0.0, 'Emission': 1.5, 'Vibrance': 0.3}},
        },
        'Dirt': {
            'Count': 2500, 'Size': 0.03, 'Size Variation': 0.8, 'Aspect': 1.3, 'Fall Speed': 3.0,
            'Speed Variation': 0.6, 'Wind': (1.5, 0.0, 0.0), 'Turbulence': 0.2, 'Turbulence Scale': 0.7,
            'Turbulence Speed': 0.6, 'Motion Stretch': 0.02, 'Random Rotation': 1.0, 'Spin': 6.0,
            'Face Camera': 0.6, 'Color': (0.33, 0.24, 0.16, 1.0), 'Color B': (0.5, 0.38, 0.25, 1.0),
            'Color Mix': 0.4, 'Value Variation': 0.35, 'Opacity': 0.95,
            '_brush': {'Particles': 'Bristle Dab'},
            '_look': {'Particles': {'Shading': 0.8, 'Hardness': 0.5, 'Dry Brush': 0.25}},
        },
    }

    variants = [
        Variant('Rain', 'Rain', 'MOD_FLUIDSIM', 'Falling rain streaks with floor splashes'),
        Variant('Snow', 'Snow', 'FREEZE', 'Fluttering soft snow dabs'),
        Variant('Sand', 'Sand', 'FORCE_WIND', 'Wind-blown sand grains'),
        Variant('Dust', 'Dust Motes', 'SHADING_RENDERED', 'Floating glowing dust motes'),
        Variant('Dirt', 'Dirt', 'OUTLINER_OB_POINTCLOUD', 'Tumbling dirt clods'),
    ]

    def make_mesh(self, mesh):
        import bmesh
        from mathutils import Matrix
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=1.0, matrix=Matrix.Diagonal((8.0, 8.0, 6.0, 1.0)))
        bmesh.ops.translate(bm, verts=bm.verts, vec=(0.0, 0.0, 3.0))
        bm.to_mesh(mesh)
        bm.free()

    def build(self, tb, P):
        geo_in = P['Geometry']
        seed = P['Seed']
        bb = tb.bound_box(geo_in)
        bmin, bmax = bb['Min'], bb['Max']
        size = tb.max(bmax - bmin, (1e-3, 1e-3, 1e-3))
        sx, sy, sz = tb.sep(size)
        center = (bmin + bmax) * 0.5
        t, loop = common.time(tb, P)

        pts = tb.node('GeometryNodePoints', {'Count': P['Count']}).out

        # --- per particle constants ---------------------------------------
        phase = rnd(tb, seed, 1)
        spd = P['Fall Speed'] * (1.0 + (rnd(tb, seed, 2) - 0.5) * 2.0 * P['Speed Variation'])
        period = sz / tb.max(tb.abs(spd), 1e-3)
        u, k, per = common.cycle(tb, t, period, phase, loop)
        age = u * per
        cyc_seed = seed * 31 + k * 7919
        x0 = tb.rand('FLOAT', 0.0, 1.0, id=tb.index(), seed=cyc_seed + 11)
        y0 = tb.rand('FLOAT', 0.0, 1.0, id=tb.index(), seed=cyc_seed + 12)
        rising = tb.compare('LESS_THAN', spd, 0.0)
        z = tb.switch(rising, tb.sep(bmax)[2] - u * sz, tb.sep(bmin)[2] + u * sz)

        # --- motion -----------------------------------------------------------
        wind = P['Wind']
        base = tb.combine(x0 * sx, y0 * sy, z - tb.sep(bmin)[2])
        _, turb = common.loop_noise(tb, base + bmin, t * P['Turbulence Speed'], loop * P['Turbulence Speed'],
                                    scale=P['Turbulence Scale'], detail=1.0, seed=tb.math('ADD', seed, 0.0))
        turb = turb * P['Turbulence']
        # x/y flutter at slightly different rates; both quantised to the loop
        f = common.quantize_freq(tb, P['Sway Frequency'], loop)
        f2 = common.quantize_freq(tb, P['Sway Frequency'] * 0.83, loop)
        ph1 = rnd(tb, seed, 3, 0.0, TAU)
        ph2 = rnd(tb, seed, 4, 0.0, TAU)
        sway = tb.combine(tb.sin(t * f * TAU + ph1), tb.cos(t * f2 * TAU + ph2), 0.0) * P['Sway']
        disp = wind * age + turb + sway
        dx, dy, dz = tb.sep(disp)
        px = tb.wrap(x0 * sx + dx, 0.0, sx)
        py = tb.wrap(y0 * sy + dy, 0.0, sy)
        pos = tb.combine(px, py, 0.0) + bmin * (1.0, 1.0, 0.0) + tb.combine(0.0, 0.0, z + dz * 0.3)
        # vortex around the domain axis
        ang = P['Vortex'] * age
        rel = pos - center
        rel = tb.rotate_axis(rel * (1.0, 1.0, 0.0), (0.0, 0.0, 1.0), ang) + tb.combine(0.0, 0.0, tb.sep(rel)[2])
        pos = center + rel

        # --- stroke orientation ---------------------------------------------
        vel = wind + tb.combine(0.0, 0.0, -spd)
        speed_mag = tb.length(vel)
        cam = common.camera_location(tb, P['Camera'])
        rand_face = tb.rand('FLOAT_VECTOR', (-1, -1, -1), (1, 1, 1), id=tb.index(), seed=seed + 7)
        rand_face = tb.normalize(rand_face + common.loop_noise(tb, rand_face * 3.0, t * P['Spin'] * 0.2,
                                                               loop * P['Spin'] * 0.2)[1])
        facing = common.facing_blend(tb, pos, cam, P['Face Camera'], rand_face)
        motion_dir = tb.normalize(vel)
        # spin rate (rad/s) as a frequency so it can be quantised to the loop
        spin_hz = common.quantize_freq(tb, P['Spin'] * (rnd(tb, seed, 6) - 0.5) * 2.0 / TAU, loop)
        spin_ang = rnd(tb, seed, 5, 0.0, TAU) * P['Random Rotation'] + t * spin_hz * TAU
        direction = tb.rotate_axis(motion_dir, facing, spin_ang)

        width = P['Size'] * (1.0 + (rnd(tb, seed, 8) - 0.5) * 2.0 * P['Size Variation'])
        length = width * P['Aspect'] + speed_mag * P['Motion Stretch']

        # --- colour / opacity ---------------------------------------------------
        use_b = tb.math('LESS_THAN', rnd(tb, seed, 9), P['Color Mix'])
        col = tb.mix_color(use_b, P['Color'], P['Color B'])
        vv = 1.0 + (rnd(tb, seed, 10) - 0.5) * 2.0 * P['Value Variation']
        col = tb.mix_color(1.0, col, tb.combine(vv, vv, vv), blend='MULTIPLY')
        fe = tb.max(P['Fade Edges'], 1e-4)
        fade_v = tb.smoothstep(0.0, fe, u) * tb.smoothstep(0.0, fe, 1.0 - u)
        qx, qy = px / sx, py / sy
        edge = tb.min(tb.min(qx, 1.0 - qx), tb.min(qy, 1.0 - qy))
        fade_h = tb.smoothstep(0.0, fe * 0.5, edge)
        opacity = P['Opacity'] * fade_v * fade_h

        pts = tb.set_position(pts, pos)
        drops = common.cards(tb, {
            'Points': pts, 'Direction': direction, 'Facing': facing, 'Width': width, 'Length': length,
            'Color': col, 'Opacity': opacity, 'Seed': seed, 'Material': P['Material'],
        })

        # --- splashes -------------------------------------------------------------
        sp_pts = tb.node('GeometryNodePoints', {'Count': P['Count']}).out
        sp_age = age / tb.max(P['Splash Duration'], 1e-3)
        lucky = tb.math('LESS_THAN', rnd(tb, seed, 11), P['Splash Amount'])
        visible = tb.bool_math('AND', tb.compare('LESS_THAN', sp_age, 1.0),
                               tb.bool_math('AND', tb.compare('GREATER_THAN', lucky, 0.5),
                                            tb.bool_math('NOT', rising)))
        prev_seed = seed * 31 + (k - 1.0) * 7919
        xp = tb.rand('FLOAT', 0.0, 1.0, id=tb.index(), seed=prev_seed + 11)
        yp = tb.rand('FLOAT', 0.0, 1.0, id=tb.index(), seed=prev_seed + 12)
        land_drift = wind * per
        lx = tb.wrap(xp * sx + tb.sep(land_drift)[0], 0.0, sx)
        ly = tb.wrap(yp * sy + tb.sep(land_drift)[1], 0.0, sy)
        land = tb.combine(lx, ly, 0.0) + bmin
        sp_pts = tb.store(sp_pts, '_sp_land', land, 'FLOAT_VECTOR')
        sp_pts = tb.store(sp_pts, '_sp_age', sp_age)
        sp_pts = tb.store(sp_pts, '_sp_col', col, 'FLOAT_COLOR')
        sp_pts = tb.delete(sp_pts, tb.bool_math('NOT', visible))
        dup = tb.node('GeometryNodeDuplicateElements', {'Geometry': sp_pts, 'Amount': P['Splash Droplets']},
                      domain='POINT')
        j = dup['Duplicate Index']
        a = tb.named('_sp_age')
        d_ang = (j / tb.max(P['Splash Droplets'], 1) + rnd(tb, seed, 12)) * TAU
        radial = tb.combine(tb.cos(d_ang), tb.sin(d_ang), 0.0)
        r = P['Splash Size'] * tb.sqrt(a)
        hgt = P['Splash Size'] * 0.9 * 4.0 * a * (1.0 - a)
        sp_pos = tb.named('_sp_land', 'FLOAT_VECTOR') + radial * r + tb.combine(0.0, 0.0, hgt)
        sp_geo = tb.set_position(dup['Geometry'], sp_pos)
        sp_dir = tb.normalize(radial + tb.combine(0.0, 0.0, (1.0 - 2.0 * a) * 2.0))
        sp_face = common.facing_blend(tb, sp_pos, cam, 1.0, (0.0, -1.0, 0.0))
        sp_w = P['Size'] * 0.8
        splashes = common.cards(tb, {
            'Points': sp_geo, 'Direction': sp_dir, 'Facing': sp_face, 'Width': sp_w, 'Length': sp_w * 2.5,
            'Color': tb.named('_sp_col', 'FLOAT_COLOR'), 'Opacity': P['Opacity'] * (1.0 - a),
            'Seed': seed + 99, 'Material': P['Material'],
        })

        return tb.join(drops, splashes, common.domain_wire(tb, geo_in, P['Show Domain']))
