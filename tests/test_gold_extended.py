# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Headless test-suite for Gold Extended.

Run with the ``bpy`` module (pip install bpy) or Blender itself:

    python tests/test_gold_extended.py [--render] [-k NAME]
    blender -b --factory-startup -P tests/test_gold_extended.py -- [--render]

No pytest needed (Blender ships without it); every ``test_*`` function is
collected, run in a fresh empty scene and reported.  Exit code is the number
of failures.
"""

import argparse
import math
import os
import shutil
import sys
import tempfile
import traceback
import zipfile

import bpy
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# Keep user presets written by the tests out of the real config directory.
os.environ.setdefault('BLENDER_USER_CONFIG', tempfile.mkdtemp(prefix='goldx_cfg_'))

import gold_extended  # noqa: E402
from gold_extended import operators  # noqa: E402
from gold_extended.core import brushes, grade, params, registry, shading  # noqa: E402

LOOP = 48

CONTRACT = {
    'brush_stroke.uv': ('CORNER', 'FLOAT2'),
    'brush_stroke.dimension': ('FACE', 'FLOAT_VECTOR'),
    'brush_stroke.length': ('FACE', 'FLOAT'),
    'brush_stroke.id': ('FACE', 'FLOAT_VECTOR'),
    'brush_stroke.opacity': ('FACE', 'FLOAT'),
    'brush_stroke': ('FACE', 'BOOLEAN'),
    'brush_stroke.color': ('POINT', 'FLOAT_COLOR'),
    'brush_stroke.normal': ('POINT', 'FLOAT_VECTOR'),
    'stroke_index': ('FACE', 'INT'),
    'opacity': ('POINT', 'FLOAT'),
}

# Effects whose output includes a brushless surface (water body) checked separately.
EFFECT_IDS = ['PARTICLES', 'CLOUD', 'GRASS', 'FOLIAGE', 'HAIR', 'FIRE', 'WATER']


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    cam = bpy.data.objects.new('Camera', bpy.data.cameras.new('Camera'))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.location = (0, -10, 2)
    cam.rotation_euler = (math.radians(85), 0, 0)
    sc.frame_start, sc.frame_end = 1, 250
    sc.frame_set(1)
    return sc


def create(effect_id, preset=None):
    return registry.create(bpy.context, effect_id, preset)


def evaluate(obj, frame=None):
    if frame is not None:
        bpy.context.scene.frame_set(frame)
    ev = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3)
    me.vertices.foreach_get('co', co)
    attrs = {a.name: (a.domain, a.data_type) for a in me.attributes if not a.name.startswith('.')}
    n_faces = len(me.polygons)
    mats = [m.name if m else None for m in me.materials]
    mi = np.empty(n_faces, dtype=np.int32)
    me.polygons.foreach_get('material_index', mi)
    ev.to_mesh_clear()
    return co.reshape(-1, 3), attrs, n_faces, mats, mi


def check(cond, msg):
    if not cond:
        raise AssertionError(msg)


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------

def test_register_unregister():
    gold_extended.unregister()
    check(not hasattr(bpy.types.Scene, 'goldx'), 'scene props not removed')
    gold_extended.register()
    check(hasattr(bpy.types.Scene, 'goldx'), 'scene props missing')
    for op in ('create_effect', 'apply_preset', 'check_loop', 'grade_enable', 'set_brush_style'):
        check(hasattr(bpy.ops.goldx, op), f'operator goldx.{op} missing')


def test_all_effects_registered():
    check(sorted(registry.EFFECTS) == sorted(EFFECT_IDS), f'effects: {sorted(registry.EFFECTS)}')
    variants = [v.label for e in registry.EFFECTS.values() for v in e.variants]
    for name in ('Rain', 'Snow', 'Sand', 'Dirt', 'Cloud', 'Grass', 'Foliage', 'Hair', 'Fire', 'Water'):
        check(name in variants, f'variant {name} missing from Create panel')


def test_specs_are_consistent():
    for eff in registry.EFFECTS.values():
        names = [p.name for _, p in params.iter_params(eff.spec)]
        check(len(names) == len(set(names)), f'{eff.id}: duplicate parameter names')
        for slot in eff.materials:
            check(slot.socket in names, f'{eff.id}: material socket {slot.socket} not in spec')
        for v in eff.variants:
            check(v.preset in eff.presets, f'{eff.id}: variant preset {v.preset} missing')
        for pname, preset in eff.presets.items():
            for k in preset:
                if k.startswith('_'):
                    continue
                check(k in names, f'{eff.id} preset {pname}: unknown parameter {k!r}')
            for role, look in preset.get('_look', {}).items():
                check(role in [s.role for s in eff.materials], f'{eff.id} preset {pname}: unknown role {role}')
                for k in look:
                    check(k in shading.look_defaults(), f'{eff.id} preset {pname}: unknown look input {k!r}')
            for role, style in preset.get('_brush', {}).items():
                check(brushes.find_style(style) is not None, f'{eff.id} preset {pname}: unknown brush {style}')
        for slot in eff.materials:
            for k in slot.look:
                check(k in shading.look_defaults(), f'{eff.id} slot {slot.role}: unknown look input {k!r}')
    for lp, values in shading.LOOK_PRESETS.items():
        for k in values:
            check(k in shading.look_defaults(), f'look preset {lp}: unknown input {k!r}')


def test_brush_contract_every_effect():
    for eid in EFFECT_IDS:
        fresh_scene()
        obj, _mod = create(eid)
        co, attrs, n_faces, mats, mi = evaluate(obj, 12)
        check(n_faces > 0, f'{eid}: no faces')
        check(not np.isnan(co).any(), f'{eid}: NaN positions')
        for name, (domain, dtype) in CONTRACT.items():
            check(name in attrs, f'{eid}: missing attribute {name}')
            check(attrs[name] == (domain, dtype), f'{eid}: {name} is {attrs[name]}, expected {(domain, dtype)}')
        check(all(m is not None and m.startswith('GX ') for i, m in enumerate(mats) if i in set(mi.tolist())),
              f'{eid}: faces use non Gold FX materials {mats}')


def test_animation_moves_and_is_deterministic():
    for eid in EFFECT_IDS:
        fresh_scene()
        obj, _mod = create(eid)
        a1 = evaluate(obj, 1)[0]
        b = evaluate(obj, 13)[0]
        a2 = evaluate(obj, 1)[0]          # scrub back
        check(a1.shape == a2.shape and np.array_equal(a1, a2), f'{eid}: not deterministic when scrubbing')
        moved = (a1.shape != b.shape) or np.abs(a1 - b).max() > 1e-4
        check(moved, f'{eid}: nothing moves between frames 1 and 13')


def test_loops_are_seamless():
    """Every preset of every effect must loop seamlessly when Loop Frames is set."""
    for eid, eff in registry.EFFECTS.items():
        for pname in eff.presets:
            fresh_scene()
            obj, mod = create(eid, pname)
            registry.set_param(mod, 'Loop Frames', LOOP)
            ok, err, moved, msg = operators.check_loop(bpy.context, obj, mod)
            check(ok, f'{eid}/{pname}: {msg}')
            check(moved is None or moved > 1e-3, f'{eid}/{pname}: loop has no motion ({msg})')


def test_every_preset_evaluates():
    for eid, eff in registry.EFFECTS.items():
        for pname in eff.presets:
            fresh_scene()
            obj, _mod = create(eid, pname)
            co, _attrs, n_faces, _m, _mi = evaluate(obj, 7)
            check(n_faces > 0, f'{eid}/{pname}: empty result')
            check(not np.isnan(co).any(), f'{eid}/{pname}: NaN positions')
            check(obj.get('goldx_preset') == pname, f'{eid}/{pname}: preset not recorded')


def test_seed_changes_result():
    fresh_scene()
    obj, mod = create('PARTICLES', 'Snow')
    a = evaluate(obj, 5)[0]
    registry.set_param(mod, 'Seed', 1234)
    b = evaluate(obj, 5)[0]
    check(a.shape != b.shape or np.abs(a - b).max() > 1e-3, 'seed has no effect')


def test_surface_effect_uses_selected_mesh():
    fresh_scene()
    bpy.ops.mesh.primitive_plane_add(size=4)
    plane = bpy.context.active_object
    plane.select_set(True)
    obj, mod = create('GRASS')
    check(obj.parent == plane, 'grass not parented to the selected plane')
    check(registry.get_param(mod, 'Surface') == plane, 'Surface param not linked')
    co = evaluate(obj, 1)[0]
    check(np.abs(co[:, :2]).max() < 2.6, 'grass grows outside the plane')


def test_masks_and_slope():
    fresh_scene()
    bpy.ops.mesh.primitive_cube_add(size=2)
    cube = bpy.context.active_object
    cube.select_set(True)
    obj, mod = create('GRASS')
    co = evaluate(obj, 1)[0]
    check(co[:, 2].min() > 0.99, 'grass grew on steep cube sides despite Max Slope')
    vg = cube.vertex_groups.new(name='none')
    vg.add([v.index for v in cube.data.vertices], 0.0, 'REPLACE')
    registry.set_param(mod, 'Mask Attribute', 'none')
    n_faces = evaluate(obj, 1)[2]
    check(n_faces == 0, f'zero-weight mask still grows {n_faces} faces')


def test_water_hides_guide_surface():
    fresh_scene()
    obj, _mod = create('WATER')
    check(obj.parent.hide_render, 'water guide surface still renders (would cover the waves)')


def test_material_slots_follow_geometry_nodes():
    fresh_scene()
    obj, _mod = create('FIRE')
    check(len(obj.data.materials) == 0, 'effect object should not carry its own material slots')
    _co, _a, _n, mats, mi = evaluate(obj, 12)
    used = {mats[i] for i in set(mi.tolist())}
    for role in ('Flames', 'Embers', 'Smoke'):
        check(any(m and role in m for m in used), f'fire: no faces with the {role} material ({used})')


def test_operators():
    fresh_scene()
    bpy.ops.goldx.create_effect(effect='PARTICLES', preset='Rain')
    obj = bpy.context.active_object
    check(registry.is_effect_object(obj), 'operator did not create an effect')
    check(bpy.context.scene.cycles.transparent_max_bounces >= registry.TRANSPARENT_BOUNCES,
          'render setup not applied')
    mod = registry.effect_modifier(obj)
    bpy.ops.goldx.apply_preset(preset='Snow')
    check(abs(registry.get_param(mod, 'Fall Speed') - 0.9) < 1e-6, 'preset not applied')
    seed = registry.get_param(mod, 'Seed')
    random_seeds = set()
    for _ in range(3):
        bpy.ops.goldx.randomize_seed()
        random_seeds.add(registry.get_param(mod, 'Seed'))
    check(len(random_seeds - {seed}) > 0, 'randomize seed did nothing')
    bpy.ops.goldx.save_preset(name='Test Preset')
    check('Test Preset' in operators.load_user_presets('PARTICLES'), 'user preset not saved')
    registry.set_param(mod, 'Count', 7)
    bpy.ops.goldx.apply_preset(preset='USER:Test Preset')
    check(registry.get_param(mod, 'Count') != 7, 'user preset not applied')
    registry.set_param(mod, 'Loop Frames', 24)
    bpy.ops.goldx.fit_timeline()
    check(bpy.context.scene.frame_end == bpy.context.scene.frame_start + 23, 'fit timeline failed')
    bpy.ops.goldx.check_loop()
    check(bpy.context.scene.goldx.loop_report.startswith('Seamless'), bpy.context.scene.goldx.loop_report)
    mat = next(m for _s, m in registry.materials_of(obj))
    bpy.ops.goldx.apply_look_preset(material=mat.name, preset='Watercolor')
    check(abs(shading.look_node(mat).inputs['Edge Darken'].default_value - 0.65) < 1e-6, 'look preset failed')
    bpy.ops.goldx.set_brush_style(material=mat.name, style=brushes.builtin_id_name('Bristle Dab'))
    check(shading.style_node(mat).node_tree.name.endswith('Bristle Dab'), 'brush style not set')
    registry.set_param(mod, 'Count', 777)
    bpy.ops.goldx.rebuild_groups()
    check(registry.get_param(mod, 'Count') == 777, 'rebuild lost parameter values')
    check(evaluate(obj, 3)[2] > 0, 'effect empty after rebuild')
    name = obj.name
    bpy.ops.goldx.delete_effect(name=name)
    check(name not in bpy.data.objects, 'delete failed')


def test_scene_grade_graph():
    sc = fresh_scene()
    node = grade.enable(sc)
    check(node is not None and node.node_tree is not None, 'grade not enabled')
    grade.apply_preset(sc, 'Vivid Pop')
    check(abs(node.inputs['Vibrance'].default_value - 0.8) < 1e-6, 'grade preset not applied')
    check(grade.disable(sc), 'grade not removed')
    check(grade.grade_node(sc) is None, 'grade node still present')


def test_base_brush_library_bridge():
    """Extract the bundled Brushstroke Tools zip and use its oil-paint styles."""
    zpath = os.path.join(ROOT, 'base', 'add-on-brushstroke-tools-v1.2.3.zip')
    if not os.path.exists(zpath):
        print('    (skipped: base zip not found)')
        return
    tmp = tempfile.mkdtemp(prefix='goldx_lib_')
    try:
        with zipfile.ZipFile(zpath) as z:
            for m in z.namelist():
                if m.startswith('assets/') or '/assets/' in m:
                    z.extract(m, tmp)
        lib = next(os.path.join(r, 'assets') for r, d, _f in os.walk(tmp) if 'assets' in d)
        styles = brushes.list_styles(lib, refresh=True)
        oil = [s for s in styles if s.category == 'Oil Paint']
        check(len(oil) >= 6, f'expected oil paint styles from base library, got {[s.name for s in styles]}')
        fresh_scene()
        obj, _mod = create('FOLIAGE')
        mat = next(m for _s, m in registry.materials_of(obj))
        check(shading.set_brush_style(mat, oil[0].id_name, lib), 'could not apply base style')
        check(shading.style_node(mat).node_tree.name.startswith('BSBST-BS.Oil Paint'), 'wrong style node')
        check(all(img.packed_file for img in bpy.data.images if img.name.startswith('oil_paint')),
              'base brush textures not packed')
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        brushes.list_styles(refresh=True)


def test_builtin_brush_styles_build():
    fresh_scene()
    for name in brushes.BUILTIN:
        ng = brushes.ensure_builtin(name)
        check(ng is not None and ng.outputs if hasattr(ng, 'outputs') else ng.interface.items_tree,
              f'brush {name} failed')
        check(ng.name.startswith('BSBST-BS.Gold FX.'), 'brush naming must follow BSBST-BS.<Cat>.<Type>.<Name>')


class _MockLayout:
    """Records UI calls and validates them against real RNA.

    Panels cannot be drawn without a window, but every ``prop`` path and
    ``operator`` id/property can be checked, which is where UI code breaks.
    """

    def __init__(self, log):
        self.log = log
        self.use_property_split = False
        self.use_property_decorate = True
        self.active = True
        self.enabled = True

    def _child(self, *a, **k):
        return _MockLayout(self.log)

    row = column = box = grid_flow = split = _child

    def label(self, **k):
        self.log.append(('label', k.get('text', '')))

    def separator(self, **k):
        pass

    def panel(self, idname, default_closed=False):
        self.log.append(('panel', idname))
        return _MockLayout(self.log), _MockLayout(self.log)

    def prop(self, data, prop, **k):
        if prop.startswith('["'):
            key = prop[2:-2]
            check(key in data.keys(), f'UI prop {prop} missing on {data}')
        else:
            check(prop in data.bl_rna.properties.keys(), f'UI prop {prop!r} missing on {data!r}')
        self.log.append(('prop', prop))

    def menu(self, idname, **k):
        check(hasattr(bpy.types, idname), f'menu {idname} not registered')

    def _op(self, idname):
        mod, name = idname.split('.')
        check(hasattr(getattr(bpy.ops, mod), name), f'operator {idname} missing')
        rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
        log = self.log

        class _Props:
            def __setattr__(self, key, value):
                check(key in rna.properties.keys(), f'{idname} has no property {key}')
                log.append(('opprop', idname, key))
        return _Props()

    def operator(self, idname, **k):
        self.log.append(('op', idname))
        return self._op(idname)

    def operator_menu_enum(self, idname, prop, **k):
        props = self._op(idname)
        rna = getattr(getattr(bpy.ops, idname.split('.')[0]), idname.split('.')[1]).get_rna_type()
        check(prop in rna.properties.keys(), f'{idname} has no enum {prop}')
        return props


class _FakePanel:
    def __init__(self, layout):
        self.layout = layout


def test_ui_panels_draw():
    from gold_extended import ui
    for eid in EFFECT_IDS:
        fresh_scene()
        obj, _mod = create(eid)
        bpy.context.scene.goldx.show_advanced = True
        grade.enable(bpy.context.scene)
        log = []
        for cls in ui.classes:
            if not issubclass(cls, bpy.types.Panel):
                continue
            if hasattr(cls, 'poll') and not cls.poll(bpy.context):
                continue
            if hasattr(cls, 'draw_header'):
                cls.draw_header(_FakePanel(_MockLayout(log)), bpy.context)
            cls.draw(_FakePanel(_MockLayout(log)), bpy.context)
        ui.GOLDX_MT_add.draw(_FakePanel(_MockLayout(log)), bpy.context)
        drawn = [e[1] for e in log if e[0] == 'prop']
        eff = registry.EFFECTS[eid]
        visible = [p for _pn, p in params.iter_params(eff.spec) if not p.hidden and p.type != 'MATERIAL']
        check(len(drawn) >= len(visible), f'{eid}: only {len(drawn)} props drawn for {len(visible)} params')
        check(('op', 'goldx.create_effect') in log, 'create buttons missing')


def test_render_smoke():
    """Render every effect at tiny resolution (only with --render)."""
    if not RUN_RENDER:
        print('    (skipped: pass --render)')
        return
    for eid in EFFECT_IDS:
        sc = fresh_scene()
        obj, _mod = create(eid)
        sc.render.engine = 'CYCLES'
        sc.cycles.samples = 4
        sc.cycles.device = 'CPU'
        sc.render.resolution_x, sc.render.resolution_y = 96, 54
        sc.render.film_transparent = True
        out = os.path.join(tempfile.gettempdir(), f'goldx_smoke_{eid}.png')
        sc.render.filepath = out
        sc.frame_set(12)
        bpy.ops.render.render(write_still=True)
        img = bpy.data.images.load(out)
        px = np.array(img.pixels[:]).reshape(-1, 4)
        cover = (px[:, 3] > 0.05).mean()
        check(cover > 0.002, f'{eid}: render is empty (coverage {cover:.4f})')


# --------------------------------------------------------------------------
# runner
# --------------------------------------------------------------------------

RUN_RENDER = False


def main(argv):
    global RUN_RENDER
    ap = argparse.ArgumentParser()
    ap.add_argument('--render', action='store_true')
    ap.add_argument('-k', default='')
    args = ap.parse_args(argv)
    RUN_RENDER = args.render
    gold_extended.register()
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith('test_') and callable(f)]
    tests = [(n, f) for n, f in tests if args.k in n]
    failures = 0
    print(f'Blender {bpy.app.version_string} - {len(tests)} tests')
    for name, fn in tests:
        try:
            fresh_scene()
            fn()
            print(f'  PASS {name}')
        except Exception:  # noqa: BLE001 - report everything
            failures += 1
            print(f'  FAIL {name}')
            traceback.print_exc()
    print(f'{len(tests) - failures} passed, {failures} failed')
    return failures


if __name__ == '__main__':
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else sys.argv[1:]
    code = main(argv)
    sys.stdout.flush()
    sys.stderr.flush()
    # The bpy 4.5 module can hang while tearing down at interpreter exit;
    # exit hard once results are reported.
    os._exit(code)
