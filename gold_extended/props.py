# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scene settings and add-on preferences."""

import bpy

from .core import brushes


class GOLDX_SceneSettings(bpy.types.PropertyGroup):
    show_advanced: bpy.props.BoolProperty(
        name='Advanced', default=False,
        description='Show advanced parameters (seeds, resolutions, camera overrides, fine tuning)')
    loop_report: bpy.props.StringProperty(name='Loop Check', default='')


class GOLDX_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    brush_library_path: bpy.props.StringProperty(
        name='Extra Brush Library', subtype='DIR_PATH', default='',
        description='Additional folder with .blend files containing BSBST-BS.* brush styles. '
                    'The Brushstroke Tools library is found automatically when installed',
        update=lambda self, ctx: brushes.list_styles(self.brush_library_path, refresh=True))
    auto_render_setup: bpy.props.BoolProperty(
        name='Auto Render Setup', default=True,
        description='Raise Cycles transparent bounces when creating effects (deep stroke overlaps '
                    'otherwise render black)')

    def draw(self, context):
        layout = self.layout
        layout.prop(self, 'brush_library_path')
        layout.prop(self, 'auto_render_setup')
        prefs = brushes.base_addon_prefs()
        box = layout.box()
        if prefs is None:
            box.label(text='Brushstroke Tools not detected: using built-in brush styles only', icon='INFO')
        else:
            box.label(text='Brushstroke Tools detected: its brush library is available', icon='CHECKMARK')
        dirs = brushes.library_dirs(self.brush_library_path)
        for d in dirs:
            box.label(text=str(d), icon='FILE_FOLDER')


classes = (GOLDX_SceneSettings, GOLDX_Preferences)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.goldx = bpy.props.PointerProperty(type=GOLDX_SceneSettings)


def unregister():
    del bpy.types.Scene.goldx
    for c in reversed(classes):
        bpy.utils.unregister_class(c)
