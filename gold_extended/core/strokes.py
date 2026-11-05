# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Shared Geometry Nodes building blocks.

The base *Brushstroke Tools* add-on shades any mesh that carries these
attributes (discovered by probing ``.brushstroke_tools.curves_to_brushstrokes``):

==========================  ======  ========  ===================================
attribute                   domain  type      meaning
==========================  ======  ========  ===================================
``brush_stroke.uv``         CORNER  FLOAT2    x = across width (0-1), y = along (0-1)
``brush_stroke.dimension``  FACE    VECTOR    (width, length, 0)
``brush_stroke.length``     FACE    FLOAT     stroke length
``brush_stroke.id``         FACE    VECTOR    random per stroke (0-1)
``brush_stroke.opacity``    FACE    FLOAT     per-stroke opacity
``brush_stroke``            FACE    BOOL      marks brush-stroke faces
``brush_stroke.color``      POINT   COLOR     paint colour
``brush_stroke.normal``     POINT   VECTOR    shading normal
``stroke_index``            FACE    INT       stroke number
``opacity``                 POINT   FLOAT     read by the base *Brush Material*
==========================  ======  ========  ===================================

Two builders produce that contract, so every effect can use any Project Gold
brush style (and the base add-on's material) unchanged:

* **Stroke Cards** – one quad per point (particles, puffs, leaves, dabs).
* **Stroke Ribbons** – one strip per curve (grass blades, hair, flames).
"""

import bpy

from .nodes import TreeBuilder, ensure_tree, new_socket

VERSION = 1
CARDS = f'.GOLDX.stroke_cards.v{VERSION}'
RIBBONS = f'.GOLDX.stroke_ribbons.v{VERSION}'
LOOP_NOISE = f'.GOLDX.loop_noise.v{VERSION}'
TIME = f'.GOLDX.time.v{VERSION}'
CAMERA = f'.GOLDX.camera.v{VERSION}'


def _finalize_face_attrs(tb: TreeBuilder, geo, width, length, stroke_index):
    """Store the per-face part of the brush-stroke contract."""
    dim = tb.combine(width, length, 0.0)
    geo = tb.store(geo, 'brush_stroke.dimension', dim, 'FLOAT_VECTOR', 'FACE')
    geo = tb.store(geo, 'brush_stroke.length', length, 'FLOAT', 'FACE')
    geo = tb.store(geo, 'brush_stroke.id', tb.named('brush_stroke.id', 'FLOAT_VECTOR'), 'FLOAT_VECTOR', 'FACE')
    geo = tb.store(geo, 'brush_stroke.opacity', tb.named('opacity', 'FLOAT'), 'FLOAT', 'FACE')
    geo = tb.store(geo, 'brush_stroke', True, 'BOOLEAN', 'FACE')
    geo = tb.store(geo, 'stroke_index', stroke_index, 'INT', 'FACE')
    return geo


def _remove_attrs(tb: TreeBuilder, geo, names):
    for nm in names:
        geo = tb.node('GeometryNodeRemoveAttribute', {'Geometry': geo, 'Name': nm}).out
    return geo


# --------------------------------------------------------------------------
# Stroke cards
# --------------------------------------------------------------------------

def ensure_cards():
    ng, created = ensure_tree(CARDS)
    if not created:
        return ng
    ng.description = 'Turn points into brush-stroke cards carrying Project Gold brush attributes'
    new_socket(ng, 'Mesh', 'OUTPUT', 'GEOMETRY')
    new_socket(ng, 'Points', 'INPUT', 'GEOMETRY')
    new_socket(ng, 'Direction', 'INPUT', 'VECTOR', default=(0, 0, 1), description='Stroke length axis')
    new_socket(ng, 'Facing', 'INPUT', 'VECTOR', default=(0, -1, 0), description='Card normal (towards the viewer)')
    new_socket(ng, 'Width', 'INPUT', 'FLOAT', default=0.1, min=0.0)
    new_socket(ng, 'Length', 'INPUT', 'FLOAT', default=0.1, min=0.0)
    new_socket(ng, 'Color', 'INPUT', 'COLOR', default=(1, 1, 1, 1))
    new_socket(ng, 'Opacity', 'INPUT', 'FLOAT', default=1.0, min=0.0, max=1.0)
    new_socket(ng, 'Normal', 'INPUT', 'VECTOR', default=(0, 0, 0), description='Shading normal (zero = use Facing)')
    new_socket(ng, 'Seed', 'INPUT', 'INT', default=0)
    new_socket(ng, 'Material', 'INPUT', 'MATERIAL')

    tb = TreeBuilder(ng)
    pts = tb.I('Points')
    facing = tb.normalize(tb.I('Facing'))
    normal_in = tb.I('Normal')
    has_normal = tb.compare('GREATER_THAN', tb.length(normal_in), 1e-6)
    normal = tb.switch(has_normal, facing, tb.normalize(normal_in), 'VECTOR')
    sid = tb.rand('FLOAT_VECTOR', (0, 0, 0), (1, 1, 1), id=tb.index(), seed=tb.I('Seed'))

    pts = tb.store(pts, 'brush_stroke.color', tb.I('Color'), 'FLOAT_COLOR', 'POINT')
    pts = tb.store(pts, 'opacity', tb.I('Opacity'), 'FLOAT', 'POINT')
    pts = tb.store(pts, 'brush_stroke.normal', normal, 'FLOAT_VECTOR', 'POINT')
    pts = tb.store(pts, 'brush_stroke.id', sid, 'FLOAT_VECTOR', 'POINT')
    pts = tb.store(pts, '_gx_w', tb.I('Width'), 'FLOAT', 'POINT')
    pts = tb.store(pts, '_gx_l', tb.I('Length'), 'FLOAT', 'POINT')

    grid = tb.node('GeometryNodeMeshGrid', {'Size X': 1.0, 'Size Y': 1.0, 'Vertices X': 2, 'Vertices Y': 2})
    card = tb.store(grid['Mesh'], 'brush_stroke.uv', grid['UV Map'], 'FLOAT2', 'CORNER')

    rot = tb.rotation_from_axes(tb.I('Direction'), facing, 'Y', 'Z')
    scale = tb.combine(tb.I('Width'), tb.I('Length'), 1.0)
    inst = tb.node('GeometryNodeInstanceOnPoints',
                   {'Points': pts, 'Instance': card, 'Rotation': rot, 'Scale': scale}).out
    mesh = tb.realize(inst)
    mesh = _finalize_face_attrs(tb, mesh, tb.named('_gx_w'), tb.named('_gx_l'), tb.index())
    mesh = _remove_attrs(tb, mesh, ['_gx_w', '_gx_l'])
    mesh = tb.set_material(mesh, tb.I('Material'))
    tb.output('Mesh', mesh)
    tb.layout()
    return ng


# --------------------------------------------------------------------------
# Stroke ribbons
# --------------------------------------------------------------------------

def ensure_ribbons():
    ng, created = ensure_tree(RIBBONS)
    if not created:
        return ng
    ng.description = 'Turn curves into brush-stroke ribbons carrying Project Gold brush attributes'
    new_socket(ng, 'Mesh', 'OUTPUT', 'GEOMETRY')
    new_socket(ng, 'Curves', 'INPUT', 'GEOMETRY')
    new_socket(ng, 'Width', 'INPUT', 'FLOAT', default=0.05, min=0.0, description='Full width per curve point')
    new_socket(ng, 'Facing', 'INPUT', 'VECTOR', default=(0, -1, 0), description='Direction the ribbon faces')
    new_socket(ng, 'Color', 'INPUT', 'COLOR', default=(1, 1, 1, 1))
    new_socket(ng, 'Opacity', 'INPUT', 'FLOAT', default=1.0, min=0.0, max=1.0)
    new_socket(ng, 'Normal', 'INPUT', 'VECTOR', default=(0, 0, 0), description='Shading normal (zero = use Facing)')
    new_socket(ng, 'Seed', 'INPUT', 'INT', default=0)
    new_socket(ng, 'Material', 'INPUT', 'MATERIAL')

    tb = TreeBuilder(ng)
    crv = tb.I('Curves')
    tangent = tb.node('GeometryNodeInputTangent').out
    facing = tb.normalize(tb.I('Facing'))
    side = tb.normalize(tb.cross(tangent, facing))
    # Degenerate when tangent // facing: fall back to an arbitrary perpendicular.
    alt = tb.normalize(tb.cross(tangent, (0.0, 0.0, 1.0)))
    side = tb.switch(tb.compare('GREATER_THAN', tb.length(tb.cross(tangent, facing)), 1e-4), alt, side, 'VECTOR')
    normal_in = tb.I('Normal')
    has_normal = tb.compare('GREATER_THAN', tb.length(normal_in), 1e-6)
    normal = tb.switch(has_normal, facing, tb.normalize(normal_in), 'VECTOR')
    spline = tb.node('GeometryNodeSplineParameter')

    crv = tb.store(crv, '_gx_c', tb.position(), 'FLOAT_VECTOR', 'POINT')
    crv = tb.store(crv, '_gx_s', tb.scale(side, tb.I('Width')), 'FLOAT_VECTOR', 'POINT')
    crv = tb.store(crv, '_gx_v', spline['Factor'], 'FLOAT', 'POINT')
    # Width is a point field: store on points first, then read on the curve
    # domain so Blender averages it per curve.
    crv = tb.store(crv, '_gx_wp', tb.I('Width'), 'FLOAT', 'POINT')
    crv = tb.store(crv, '_gx_w', tb.named('_gx_wp'), 'FLOAT', 'CURVE')
    length = tb.node('GeometryNodeSplineLength')['Length']
    crv = tb.store(crv, '_gx_l', length, 'FLOAT', 'CURVE')
    crv = tb.store(crv, 'brush_stroke.color', tb.I('Color'), 'FLOAT_COLOR', 'POINT')
    crv = tb.store(crv, 'opacity', tb.I('Opacity'), 'FLOAT', 'POINT')
    crv = tb.store(crv, 'brush_stroke.normal', normal, 'FLOAT_VECTOR', 'POINT')
    sid = tb.rand('FLOAT_VECTOR', (0, 0, 0), (1, 1, 1), id=tb.index(), seed=tb.I('Seed'))
    crv = tb.store(crv, 'brush_stroke.id', sid, 'FLOAT_VECTOR', 'CURVE')
    crv = tb.store(crv, '_gx_i', tb.index(), 'INT', 'CURVE')

    prof = tb.node('GeometryNodeCurvePrimitiveLine', {'Start': (-0.5, 0, 0), 'End': (0.5, 0, 0)}).out
    prof = tb.store(prof, '_gx_u', tb.node('GeometryNodeSplineParameter')['Factor'], 'FLOAT', 'POINT')
    mesh = tb.node('GeometryNodeCurveToMesh', {'Curve': crv, 'Profile Curve': prof}).out

    u = tb.named('_gx_u')
    pos = tb.named('_gx_c', 'FLOAT_VECTOR') + tb.scale(tb.named('_gx_s', 'FLOAT_VECTOR'), u - 0.5)
    mesh = tb.set_position(mesh, pos)
    mesh = tb.store(mesh, 'brush_stroke.uv', tb.combine(u, tb.named('_gx_v'), 0.0), 'FLOAT2', 'CORNER')
    mesh = _finalize_face_attrs(tb, mesh, tb.named('_gx_w'), tb.named('_gx_l'), tb.named('_gx_i', 'INT'))
    mesh = _remove_attrs(tb, mesh, ['_gx_c', '_gx_s', '_gx_v', '_gx_u', '_gx_w', '_gx_wp', '_gx_l', '_gx_i'])
    mesh = tb.set_material(mesh, tb.I('Material'))
    mesh = tb.node('GeometryNodeSetShadeSmooth', {'Mesh': mesh, 'Shade Smooth': True}).out
    tb.output('Mesh', mesh)
    tb.layout()
    return ng


# --------------------------------------------------------------------------
# Looping noise
# --------------------------------------------------------------------------

def ensure_loop_noise():
    """4D noise that loops seamlessly in time.

    ``n(t) = lerp(noise(p, t), noise(p, t - L), t / L)`` with ``t`` wrapped to
    ``[0, L)``: at ``t = 0`` and ``t = L`` both terms evaluate ``noise(p, 0)``.
    With ``Loop = 0`` plain 4D noise is returned.
    """
    ng, created = ensure_tree(LOOP_NOISE)
    if not created:
        return ng
    new_socket(ng, 'Value', 'OUTPUT', 'FLOAT')
    new_socket(ng, 'Vector', 'OUTPUT', 'VECTOR')
    new_socket(ng, 'Vector', 'INPUT', 'VECTOR')
    new_socket(ng, 'Time', 'INPUT', 'FLOAT')
    new_socket(ng, 'Loop', 'INPUT', 'FLOAT', default=0.0, min=0.0)
    new_socket(ng, 'Scale', 'INPUT', 'FLOAT', default=1.0)
    new_socket(ng, 'Detail', 'INPUT', 'FLOAT', default=1.0, min=0.0, max=15.0)
    new_socket(ng, 'Roughness', 'INPUT', 'FLOAT', default=0.5, min=0.0, max=1.0)
    new_socket(ng, 'Seed', 'INPUT', 'FLOAT', default=0.0)

    tb = TreeBuilder(ng)
    t = tb.I('Time')
    L = tb.I('Loop')
    use_loop = tb.compare('GREATER_THAN', L, 1e-5)
    L_safe = tb.max(L, 1e-5)
    tm = tb.switch(use_loop, t, tb.mod(t, L_safe))
    f = tb.switch(use_loop, 0.0, tm / L_safe)
    vec = tb.I('Vector')
    seed = tb.I('Seed') * 17.31
    sc, de, ro = tb.I('Scale'), tb.I('Detail'), tb.I('Roughness')
    fa, ca = tb.noise(vec, w=tm + seed, scale=sc, detail=de, roughness=ro)
    fb, cb = tb.noise(vec, w=tm - L + seed, scale=sc, detail=de, roughness=ro)
    val = tb.lerp(fa, fb, f)
    col = tb.lerp(ca, cb, f)
    tb.output('Value', (val - 0.5) * 2.0)
    tb.output('Vector', tb.scale(col - (0.5, 0.5, 0.5), 2.0))
    tb.layout()
    return ng


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def ensure_time():
    """Effect time in seconds with speed/offset and loop length conversion.

    Seconds-per-frame is derived as ``seconds / frame`` (Geometry Nodes has no
    fps input); at frame 0 every quantity is 0 so the fallback is harmless.
    """
    ng, created = ensure_tree(TIME)
    if not created:
        return ng
    new_socket(ng, 'Time', 'OUTPUT', 'FLOAT')
    new_socket(ng, 'Loop', 'OUTPUT', 'FLOAT')
    new_socket(ng, 'Speed', 'INPUT', 'FLOAT', default=1.0)
    new_socket(ng, 'Offset', 'INPUT', 'FLOAT', default=0.0)
    new_socket(ng, 'Loop Frames', 'INPUT', 'INT', default=0, min=0)

    tb = TreeBuilder(ng)
    st = tb.node('GeometryNodeInputSceneTime')
    frame, secs = st['Frame'], st['Seconds']
    nonzero = tb.compare('GREATER_THAN', tb.abs(frame), 1e-4)
    spf = tb.switch(nonzero, 1.0 / 24.0, secs / tb.switch(nonzero, 1.0, frame))
    speed = tb.I('Speed')
    t = (frame + tb.I('Offset')) * spf * speed
    loop = tb.I('Loop Frames') * spf * tb.abs(speed)
    tb.output('Time', t)
    tb.output('Loop', loop)
    tb.layout()
    return ng


def ensure_camera():
    """Camera location: explicit object, else the scene's active camera."""
    ng, created = ensure_tree(CAMERA)
    if not created:
        return ng
    new_socket(ng, 'Location', 'OUTPUT', 'VECTOR')
    new_socket(ng, 'Camera', 'INPUT', 'OBJECT')
    tb = TreeBuilder(ng)
    active = tb.node('GeometryNodeInputActiveCamera').out
    explicit = tb.object_info(tb.I('Camera'))['Location']
    fallback = tb.object_info(active)['Location']
    has = tb.compare('GREATER_THAN', tb.length(explicit), 0.0)
    # An explicitly assigned camera exactly at the origin is treated as unset;
    # acceptable for a painterly facing direction.
    tb.output('Location', tb.switch(has, fallback, explicit, 'VECTOR'))
    tb.layout()
    return ng


def ensure_all():
    return {
        'cards': ensure_cards(),
        'ribbons': ensure_ribbons(),
        'loop_noise': ensure_loop_noise(),
        'time': ensure_time(),
        'camera': ensure_camera(),
    }
