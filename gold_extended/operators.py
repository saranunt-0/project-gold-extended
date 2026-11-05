# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators."""

import json
import os
import random

import bpy

from .core import brushes, compat, grade, params, registry, shading

ADDON = __package__


def _prefs(context):
    addon = context.preferences.addons.get(ADDON)
    return addon.preferences if addon else None


def _active_effect(context):
    obj = context.active_object
    if registry.is_effect_object(obj):
        return obj, registry.effect_of(obj), registry.effect_modifier(obj)
    return None, None, None


# --------------------------------------------------------------------------
# User presets (JSON, one file per effect)
# --------------------------------------------------------------------------

def presets_dir():
    try:
        return bpy.utils.extension_path_user(ADDON, path='presets', create=True)
    except (ValueError, AttributeError, RuntimeError):
        path = os.path.join(bpy.utils.user_resource('CONFIG'), 'gold_extended', 'presets')
        os.makedirs(path, exist_ok=True)
        return path


def load_user_presets(effect_id):
    path = os.path.join(presets_dir(), f'{effect_id.lower()}.json')
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_user_preset(effect_id, name, data):
    presets = load_user_presets(effect_id)
    presets[name] = data
    path = os.path.join(presets_dir(), f'{effect_id.lower()}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(presets, f, indent=2)
    return path


_enum_cache = {}


def _cache(key, items):
    # Blender requires dynamic enum strings to stay referenced from Python.
    _enum_cache[key] = items
    return items


def preset_items(self, context):
    _obj, eff, _mod = _active_effect(context)
    if eff is None:
        return _cache('presets', [('NONE', 'No effect', '')])
    items = [(name, name, f'Built-in {eff.label} preset') for name in eff.presets]
    for name in load_user_presets(eff.id):
        items.append((f'USER:{name}', f'{name} (user)', 'User preset'))
    return _cache('presets', items)


def look_preset_items(self, context):
    return _cache('looks', [(n, n, 'Look preset') for n in shading.LOOK_PRESETS])


def brush_items(self, context):
    prefs = _prefs(context)
    return _cache('brushes', brushes.enum_items(prefs.brush_library_path if prefs else ''))


def grade_preset_items(self, context):
    return _cache('grade', [(n, n, 'Scene grade preset') for n in grade.GRADE_PRESETS])


# --------------------------------------------------------------------------
# Create / manage effects
# --------------------------------------------------------------------------

class GOLDX_OT_create_effect(bpy.types.Operator):
    bl_idname = 'goldx.create_effect'
    bl_label = 'Create Effect'
    bl_options = {'REGISTER', 'UNDO'}

    effect: bpy.props.StringProperty()
    preset: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, props):
        eff = registry.EFFECTS.get(props.effect)
        if eff is None:
            return 'Create a Gold FX effect'
        for v in eff.variants:
            if v.preset == props.preset:
                hint = ' on the selected mesh' if eff.host == 'SURFACE' else ' at the 3D cursor'
                return f'{v.description}.\nCreated{hint}'
        return eff.description

    def execute(self, context):
        if self.effect not in registry.EFFECTS:
            self.report({'ERROR'}, f'Unknown effect {self.effect}')
            return {'CANCELLED'}
        prefs = _prefs(context)
        obj, _mod = registry.create(context, self.effect, self.preset or None,
                                    render_setup=prefs.auto_render_setup if prefs else True)
        self.report({'INFO'}, f'Created {obj.name}')
        return {'FINISHED'}


class GOLDX_OT_apply_preset(bpy.types.Operator):
    bl_idname = 'goldx.apply_preset'
    bl_label = 'Apply Preset'
    bl_description = 'Apply a preset to the active effect'
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'preset'

    preset: bpy.props.EnumProperty(items=preset_items, name='Preset')
    include_look: bpy.props.BoolProperty(name='Include Look', default=True,
                                         description='Also reset materials to the preset look and brush')

    @classmethod
    def poll(cls, context):
        return _active_effect(context)[0] is not None

    def execute(self, context):
        obj, eff, mod = _active_effect(context)
        if self.preset.startswith('USER:'):
            data = load_user_presets(eff.id).get(self.preset[5:])
            if data is None:
                return {'CANCELLED'}
            apply_user_preset(obj, data, self.include_look)
        else:
            registry.apply_preset(obj, self.preset, self.include_look)
        return {'FINISHED'}


def apply_user_preset(obj, data, include_look=True):
    mod = registry.effect_modifier(obj)
    for k, v in data.get('params', {}).items():
        registry.set_param(mod, k, v)
    if include_look:
        for slot, mat in registry.materials_of(obj):
            if mat is None:
                continue
            if slot.role in data.get('look', {}):
                shading.apply_look(mat, data['look'][slot.role])
            if slot.role in data.get('brush', {}):
                shading.set_brush_style(mat, data['brush'][slot.role])
    compat.tag_update(obj, mod)


class GOLDX_OT_save_preset(bpy.types.Operator):
    bl_idname = 'goldx.save_preset'
    bl_label = 'Save Preset'
    bl_description = 'Save the current parameters, looks and brushes as a user preset'
    bl_options = {'REGISTER'}

    name: bpy.props.StringProperty(name='Name', default='My Preset')

    @classmethod
    def poll(cls, context):
        return _active_effect(context)[0] is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def execute(self, context):
        obj, eff, _mod = _active_effect(context)
        data = {'params': registry.capture_preset(obj), 'look': {}, 'brush': {}}
        for slot, mat in registry.materials_of(obj):
            node = shading.look_node(mat)
            if node is None:
                continue
            look = {}
            for s in node.inputs:
                if s.name == 'Brush Mask' or not hasattr(s, 'default_value'):
                    continue
                v = s.default_value
                look[s.name] = tuple(v) if hasattr(v, '__len__') else v
            data['look'][slot.role] = look
            st = shading.style_node(mat)
            if st is not None and st.node_tree:
                data['brush'][slot.role] = st.node_tree.name
        path = save_user_preset(eff.id, self.name, data)
        self.report({'INFO'}, f'Saved preset to {path}')
        return {'FINISHED'}


class GOLDX_OT_randomize_seed(bpy.types.Operator):
    bl_idname = 'goldx.randomize_seed'
    bl_label = 'Randomize Seed'
    bl_description = 'Pick a new random seed for the active effect'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_effect(context)[0] is not None

    def execute(self, context):
        obj, _eff, mod = _active_effect(context)
        registry.set_param(mod, 'Seed', random.randint(0, 99999))
        compat.tag_update(obj, mod)
        return {'FINISHED'}


class GOLDX_OT_select_effect(bpy.types.Operator):
    bl_idname = 'goldx.select_effect'
    bl_label = 'Select Effect'
    bl_description = 'Select and activate this effect object'
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None:
            return {'CANCELLED'}
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        for o in context.selected_objects:
            o.select_set(False)
        if obj.visible_get():
            obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class GOLDX_OT_delete_effect(bpy.types.Operator):
    bl_idname = 'goldx.delete_effect'
    bl_label = 'Delete Effect'
    bl_description = 'Delete this effect object (its surface/emitter is kept)'
    bl_options = {'REGISTER', 'UNDO'}

    name: bpy.props.StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.name)
        if obj is None or not registry.is_effect_object(obj):
            return {'CANCELLED'}
        bpy.data.objects.remove(obj)
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Look & brush
# --------------------------------------------------------------------------

class GOLDX_OT_apply_look_preset(bpy.types.Operator):
    bl_idname = 'goldx.apply_look_preset'
    bl_label = 'Look Preset'
    bl_description = 'Apply a look preset to this material (resets all look controls first)'
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'preset'

    material: bpy.props.StringProperty()
    preset: bpy.props.EnumProperty(items=look_preset_items, name='Look')

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        if mat is None:
            return {'CANCELLED'}
        values = dict(shading.LOOK_PRESETS.get(self.preset, {}))
        # keep the effect's own base settings for things the preset doesn't touch
        obj = context.active_object
        eff = registry.effect_of(obj)
        if eff is not None:
            for slot in eff.materials:
                if mat.get('GOLDX_role') == slot.role:
                    base = dict(slot.look)
                    base.update(values)
                    values = base
        shading.apply_look(mat, values, reset=True)
        return {'FINISHED'}


class GOLDX_OT_set_brush_style(bpy.types.Operator):
    bl_idname = 'goldx.set_brush_style'
    bl_label = 'Brush Style'
    bl_description = 'Choose the brush style (built-in or from the Brushstroke Tools library)'
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'style'

    material: bpy.props.StringProperty()
    style: bpy.props.EnumProperty(items=brush_items, name='Brush Style')

    def invoke(self, context, event):
        context.window_manager.invoke_search_popup(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        mat = bpy.data.materials.get(self.material)
        prefs = _prefs(context)
        if mat is None or not shading.set_brush_style(mat, self.style, prefs.brush_library_path if prefs else ''):
            self.report({'WARNING'}, 'Could not set brush style')
            return {'CANCELLED'}
        return {'FINISHED'}


class GOLDX_OT_refresh_brushes(bpy.types.Operator):
    bl_idname = 'goldx.refresh_brushes'
    bl_label = 'Refresh Brush Library'
    bl_description = 'Rescan brush style libraries'

    def execute(self, context):
        prefs = _prefs(context)
        styles = brushes.list_styles(prefs.brush_library_path if prefs else '', refresh=True)
        self.report({'INFO'}, f'{len(styles)} brush styles available')
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Render / maintenance
# --------------------------------------------------------------------------

class GOLDX_OT_render_setup(bpy.types.Operator):
    bl_idname = 'goldx.render_setup'
    bl_label = 'Render Setup'
    bl_description = 'Raise Cycles transparent bounces so overlapping brush strokes never render black'
    bl_options = {'REGISTER', 'UNDO'}

    bounces: bpy.props.IntProperty(name='Transparent Bounces', default=registry.TRANSPARENT_BOUNCES, min=8,
                                   max=1024)

    def execute(self, context):
        changed = registry.ensure_render_settings(context.scene, self.bounces)
        self.report({'INFO'}, 'Render settings updated' if changed else 'Render settings already sufficient')
        return {'FINISHED'}


class GOLDX_OT_rebuild_groups(bpy.types.Operator):
    bl_idname = 'goldx.rebuild_groups'
    bl_label = 'Rebuild Node Groups'
    bl_description = ('Regenerate all Gold FX node groups from the add-on recipes, keeping parameter values '
                      '(use after updating the add-on)')
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        total = 0
        for eff in registry.EFFECTS.values():
            if bpy.data.node_groups.get(eff.group_name) is not None:
                ng = registry.rebuild_group(eff)
                total += ng.get('goldx_restored', 0)
        for obj in bpy.data.objects:
            if registry.is_effect_object(obj):
                compat.tag_update(obj, registry.effect_modifier(obj))
        self.report({'INFO'}, f'Rebuilt node groups, restored {total} effects')
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Animation test tools
# --------------------------------------------------------------------------

class GOLDX_OT_fit_timeline(bpy.types.Operator):
    bl_idname = 'goldx.fit_timeline'
    bl_label = 'Fit Timeline to Loop'
    bl_description = 'Set the scene frame range to exactly one loop of the active effect'
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _active_effect(context)[0] is not None

    def execute(self, context):
        _obj, _eff, mod = _active_effect(context)
        loop = registry.get_param(mod, 'Loop Frames')
        if not loop:
            self.report({'WARNING'}, 'Set Loop Frames first')
            return {'CANCELLED'}
        sc = context.scene
        sc.frame_end = sc.frame_start + int(loop) - 1
        return {'FINISHED'}


class GOLDX_OT_play(bpy.types.Operator):
    bl_idname = 'goldx.play'
    bl_label = 'Play / Pause'
    bl_description = 'Toggle viewport animation playback to test the effect'

    def execute(self, context):
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


def evaluate_positions(context, obj, frame):
    """Evaluated vertex positions and per-vertex opacity (or None) at ``frame``."""
    import numpy as np
    context.scene.frame_set(frame)
    dg = context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, dtype=np.float64)
    me.vertices.foreach_get('co', co)
    op = None
    attr = me.attributes.get('opacity')
    if attr is not None and attr.domain == 'POINT':
        op = np.empty(len(me.vertices), dtype=np.float64)
        attr.data.foreach_get('value', op)
    ev.to_mesh_clear()
    return co.reshape(-1, 3), op


def check_loop(context, obj, mod, offsets=(0, 7)):
    """Compare geometry exactly one loop apart, at several phase offsets.

    Checking more than one offset catches effects that match at the loop
    boundary but jump on the next iteration.  Vertices that are invisible in
    both frames (opacity ~ 0, e.g. particles fading while wrapping around the
    domain) are ignored: the check is about *visible* seams.

    Returns (ok, max_error, motion, message).
    """
    import numpy as np
    loop = registry.get_param(mod, 'Loop Frames')
    if not loop:
        return False, None, None, 'Loop Frames is 0: nothing to check'
    loop = int(loop)
    sc = context.scene
    keep = sc.frame_current
    f0 = sc.frame_start
    worst, motion = 0.0, 0.0
    try:
        for off in offsets:
            a, oa = evaluate_positions(context, obj, f0 + off)
            b, ob = evaluate_positions(context, obj, f0 + off + loop)
            if a.shape != b.shape:
                return False, None, None, f'Vertex count differs ({len(a)} vs {len(b)}) at +{off}: not seamless'
            if not len(a):
                continue
            diff = np.abs(a - b).max(axis=1)
            if oa is not None and ob is not None:
                diff = diff[(oa > 0.01) | (ob > 0.01)]
            worst = max(worst, float(diff.max()) if len(diff) else 0.0)
            m, _om = evaluate_positions(context, obj, f0 + off + loop // 2)
            if m.shape == a.shape:
                motion = max(motion, float(np.abs(a - m).max()))
            else:
                motion = float('inf')
    finally:
        sc.frame_set(keep)
    ok = worst <= 1e-3
    msg = f'{"Seamless" if ok else "NOT seamless"}: max error {worst:.2e} (motion mid-loop {motion:.3g})'
    return ok, worst, motion, msg


class GOLDX_OT_check_loop(bpy.types.Operator):
    bl_idname = 'goldx.check_loop'
    bl_label = 'Check Loop Seam'
    bl_description = ('Evaluate the effect at the loop start and one loop later and compare every vertex: '
                      'verifies that the animation loops seamlessly')

    @classmethod
    def poll(cls, context):
        return _active_effect(context)[0] is not None

    def execute(self, context):
        obj, _eff, mod = _active_effect(context)
        ok, _err, _moved, msg = check_loop(context, obj, mod)
        context.scene.goldx.loop_report = msg
        self.report({'INFO'} if ok else {'WARNING'}, msg)
        return {'FINISHED'}


# --------------------------------------------------------------------------
# Scene grade
# --------------------------------------------------------------------------

class GOLDX_OT_grade_enable(bpy.types.Operator):
    bl_idname = 'goldx.grade_enable'
    bl_label = 'Enable Scene Grade'
    bl_description = 'Add the Gold FX grade (bloom, chromatic aberration, vibrance, vignette) to the compositor'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        try:
            grade.enable(context.scene)
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        return {'FINISHED'}


class GOLDX_OT_grade_disable(bpy.types.Operator):
    bl_idname = 'goldx.grade_disable'
    bl_label = 'Remove Scene Grade'
    bl_description = 'Remove the Gold FX grade from the compositor'
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        grade.disable(context.scene)
        return {'FINISHED'}


class GOLDX_OT_grade_preset(bpy.types.Operator):
    bl_idname = 'goldx.grade_preset'
    bl_label = 'Grade Preset'
    bl_description = 'Apply a scene grade preset'
    bl_options = {'REGISTER', 'UNDO'}
    bl_property = 'preset'

    preset: bpy.props.EnumProperty(items=grade_preset_items, name='Preset')

    def execute(self, context):
        grade.apply_preset(context.scene, self.preset)
        return {'FINISHED'}


classes = (
    GOLDX_OT_create_effect, GOLDX_OT_apply_preset, GOLDX_OT_save_preset, GOLDX_OT_randomize_seed,
    GOLDX_OT_select_effect, GOLDX_OT_delete_effect, GOLDX_OT_apply_look_preset, GOLDX_OT_set_brush_style,
    GOLDX_OT_refresh_brushes, GOLDX_OT_render_setup, GOLDX_OT_rebuild_groups, GOLDX_OT_fit_timeline,
    GOLDX_OT_play, GOLDX_OT_check_loop, GOLDX_OT_grade_enable, GOLDX_OT_grade_disable, GOLDX_OT_grade_preset,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
