# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Sidebar UI (3D Viewport > N panel > Gold FX) and the Add menu entry.

All parameter UI is generated from the effect specs (:mod:`.core.params`)
and the Look shader inputs, so new effects need no UI code.
"""

import bpy

from .core import brushes, compat, grade, params, registry, shading

CATEGORY = 'Gold FX'
CATEGORY_ORDER = ['Particles', 'Atmosphere', 'Nature', 'Elements']


def _effects_by_category():
    cats = {}
    for eff in registry.EFFECTS.values():
        cats.setdefault(eff.category, []).append(eff)
    order = CATEGORY_ORDER + [c for c in cats if c not in CATEGORY_ORDER]
    return [(c, cats[c]) for c in order if c in cats]


def _active(context):
    obj = context.active_object
    if registry.is_effect_object(obj):
        return obj, registry.effect_of(obj), registry.effect_modifier(obj)
    return None, None, None


class _Base:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = CATEGORY


class GOLDX_PT_create(_Base, bpy.types.Panel):
    bl_label = 'Create'
    bl_idname = 'GOLDX_PT_create'

    def draw(self, context):
        layout = self.layout
        for cat, effs in _effects_by_category():
            col = layout.column(align=True)
            col.label(text=cat)
            grid = col.grid_flow(row_major=True, columns=2, even_columns=True, align=True)
            for eff in effs:
                for v in eff.variants:
                    op = grid.operator('goldx.create_effect', text=v.label, icon=v.icon)
                    op.effect = eff.id
                    op.preset = v.preset
        ob = context.active_object
        box = layout.box()
        if ob and ob.type == 'MESH' and ob.select_get() and not registry.is_effect_object(ob):
            box.label(text=f'Surface effects grow on: {ob.name}', icon='OUTLINER_OB_MESH')
        else:
            box.label(text='Select a mesh for Grass, Hair, Fire, Water', icon='INFO')


class GOLDX_PT_scene_effects(_Base, bpy.types.Panel):
    bl_label = 'Scene Effects'
    bl_idname = 'GOLDX_PT_scene_effects'

    def draw(self, context):
        layout = self.layout
        objs = [o for o in context.scene.objects if registry.is_effect_object(o)]
        if not objs:
            layout.label(text='No effects yet', icon='GHOST_DISABLED')
            return
        col = layout.column(align=True)
        for o in objs:
            eff = registry.effect_of(o)
            row = col.row(align=True)
            active = o == context.active_object
            op = row.operator('goldx.select_effect', text=o.name, icon=eff.icon if eff else 'OBJECT_DATA',
                              depress=active)
            op.name = o.name
            row.prop(o, 'hide_viewport', text='', emboss=False)
            row.prop(o, 'hide_render', text='', emboss=False)
            op = row.operator('goldx.delete_effect', text='', icon='X', emboss=False)
            op.name = o.name


def draw_params(layout, context, eff, mod, show_advanced):
    ng = mod.node_group
    for panel in eff.spec:
        items = [p for p in panel.params if not p.hidden and p.type != 'MATERIAL'
                 and (show_advanced or not p.advanced)]
        if not items:
            continue
        header, body = layout.panel(f'goldx_{eff.id}_{panel.name}', default_closed=panel.closed)
        header.label(text=panel.name)
        if body is None:
            continue
        col = body.column()
        col.use_property_split = True
        col.use_property_decorate = False
        for p in items:
            ident = params.socket_identifier(ng, p.name)
            if ident is None or not compat.has_input(mod, ident):
                continue
            compat.draw_input(col, mod, ident, text=p.name)


class GOLDX_PT_effect(_Base, bpy.types.Panel):
    bl_label = 'Effect'
    bl_idname = 'GOLDX_PT_effect'

    @classmethod
    def poll(cls, context):
        return _active(context)[0] is not None

    def draw_header(self, context):
        _obj, eff, _mod = _active(context)
        self.layout.label(text=eff.label if eff else '', icon=eff.icon if eff else 'NONE')

    def draw(self, context):
        obj, eff, mod = _active(context)
        layout = self.layout
        if eff is None or mod is None:
            layout.label(text='Effect definition not found', icon='ERROR')
            return
        row = layout.row(align=True)
        row.operator_menu_enum('goldx.apply_preset', 'preset', text=obj.get('goldx_preset', 'Presets'),
                               icon='PRESET')
        row.operator('goldx.save_preset', text='', icon='ADD')
        row.operator('goldx.randomize_seed', text='', icon='FILE_REFRESH')
        row = layout.row()
        row.prop(context.scene.goldx, 'show_advanced', toggle=True, icon='OPTIONS')
        draw_params(layout, context, eff, mod, context.scene.goldx.show_advanced)


def _draw_look_inputs(layout, node, panel_name):
    col = layout.column()
    col.use_property_split = True
    col.use_property_decorate = False
    for nm, _typ, _d, _lo, _hi, panel, _desc in shading.LOOK_INPUTS:
        if panel != panel_name:
            continue
        sock = node.inputs.get(nm)
        if sock is not None:
            col.prop(sock, 'default_value', text=nm)


class GOLDX_PT_look(_Base, bpy.types.Panel):
    bl_label = 'Look'
    bl_idname = 'GOLDX_PT_look'

    @classmethod
    def poll(cls, context):
        return _active(context)[0] is not None

    def draw(self, context):
        obj, eff, _mod = _active(context)
        layout = self.layout
        for i, (slot, mat) in enumerate(registry.materials_of(obj)):
            header, body = layout.panel(f'goldx_look_{eff.id}_{slot.role}', default_closed=i > 0)
            header.label(text=slot.role, icon='MATERIAL')
            if body is None:
                continue
            if mat is None:
                body.label(text='No material assigned', icon='ERROR')
                continue
            node = shading.look_node(mat)
            if node is None:
                body.label(text=f'{mat.name} is not a Gold FX material', icon='INFO')
                continue
            row = body.row(align=True)
            st = shading.style_node(mat)
            if st is not None and st.node_tree is not None:
                nm, cat, _typ = brushes.parse_style_name(st.node_tree.name)
                op = row.operator('goldx.set_brush_style', text=nm, icon='BRUSH_DATA')
                op.material = mat.name
            op = row.operator_menu_enum('goldx.apply_look_preset', 'preset', text='Look', icon='SHADING_RENDERED')
            op.material = mat.name
            if st is not None and st.node_tree is not None and len(st.inputs):
                h2, b2 = body.panel(f'goldx_brush_{eff.id}_{slot.role}', default_closed=True)
                h2.label(text='Brush')
                if b2:
                    col = b2.column()
                    col.use_property_split = True
                    col.use_property_decorate = False
                    for s in st.inputs:
                        if hasattr(s, 'default_value'):
                            col.prop(s, 'default_value', text=s.name)
            for pn in shading.LOOK_PANELS:
                h2, b2 = body.panel(f'goldx_lookp_{eff.id}_{slot.role}_{pn}', default_closed=pn != 'Color')
                h2.label(text=pn)
                if b2:
                    _draw_look_inputs(b2, node, pn)


class GOLDX_PT_animation(_Base, bpy.types.Panel):
    bl_label = 'Animation Test'
    bl_idname = 'GOLDX_PT_animation'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        sc = context.scene
        obj, eff, mod = _active(context)
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(sc, 'frame_start', text='Start')
        row.prop(sc, 'frame_end', text='End')
        col.prop(sc, 'frame_current', text='Frame')
        if obj is not None:
            col = layout.column()
            col.use_property_split = True
            for nm in ('Speed', 'Loop Frames'):
                ident = params.socket_identifier(mod.node_group, nm)
                if ident and compat.has_input(mod, ident):
                    compat.draw_input(col, mod, ident, text=nm)
        row = layout.row(align=True)
        row.operator('goldx.play', icon='PLAY')
        row.operator('goldx.fit_timeline', text='Fit to Loop', icon='ARROW_LEFTRIGHT')
        layout.operator('goldx.check_loop', icon='CHECKMARK')
        if sc.goldx.loop_report:
            layout.label(text=sc.goldx.loop_report,
                         icon='CHECKMARK' if sc.goldx.loop_report.startswith('Seamless') else 'ERROR')


class GOLDX_PT_grade(_Base, bpy.types.Panel):
    bl_label = 'Scene Grade'
    bl_idname = 'GOLDX_PT_grade'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        node = grade.grade_node(context.scene)
        if node is None:
            layout.operator('goldx.grade_enable', icon='NODE_COMPOSITING')
            return
        row = layout.row(align=True)
        row.operator_menu_enum('goldx.grade_preset', 'preset', text='Preset', icon='PRESET')
        row.operator('goldx.grade_disable', text='', icon='X')
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        for nm, *_ in grade.GRADE_INPUTS:
            if nm in node.inputs:
                col.prop(node.inputs[nm], 'default_value', text=nm)


class GOLDX_PT_settings(_Base, bpy.types.Panel):
    bl_label = 'Settings'
    bl_idname = 'GOLDX_PT_settings'
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.operator('goldx.render_setup', icon='RENDER_STILL')
        col.operator('goldx.refresh_brushes', icon='BRUSH_DATA')
        col.operator('goldx.rebuild_groups', icon='NODETREE')
        cyc = getattr(context.scene, 'cycles', None)
        if cyc is not None:
            layout.prop(cyc, 'transparent_max_bounces', text='Transparent Bounces')
        base = brushes.base_addon_prefs()
        layout.label(text='Brushstroke Tools library: ' + ('found' if base else 'not installed'),
                     icon='CHECKMARK' if base else 'INFO')


class GOLDX_MT_add(bpy.types.Menu):
    bl_idname = 'GOLDX_MT_add'
    bl_label = 'Gold FX'

    def draw(self, context):
        layout = self.layout
        for cat, effs in _effects_by_category():
            layout.label(text=cat)
            for eff in effs:
                for v in eff.variants:
                    op = layout.operator('goldx.create_effect', text=v.label, icon=v.icon)
                    op.effect = eff.id
                    op.preset = v.preset


def draw_add_menu(self, context):
    self.layout.menu(GOLDX_MT_add.bl_idname, icon='BRUSHES_ALL')


classes = (GOLDX_PT_create, GOLDX_PT_scene_effects, GOLDX_PT_effect, GOLDX_PT_look, GOLDX_PT_animation,
           GOLDX_PT_grade, GOLDX_PT_settings, GOLDX_MT_add)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.VIEW3D_MT_add.append(draw_add_menu)


def unregister():
    bpy.types.VIEW3D_MT_add.remove(draw_add_menu)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
