# SPDX-FileCopyrightText: 2025 Blender Studio Tools Authors
# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Geometry Nodes modifier input access across Blender versions.

Adapted from ``geomod.py`` of Brushstroke Tools (Blender Studio):
Blender 5.2 replaced dict-style custom-property access on GeoNodes modifiers
with RNA properties.

  Before 5.2:  modifier["identifier"] = value
  5.2+:        modifier.properties.inputs.identifier.value = value
"""

from typing import Any

import bpy

NEW_API = bpy.app.version >= (5, 2, 0)


def get_value(mod, identifier: str) -> Any:
    if NEW_API:
        return getattr(mod.properties.inputs, identifier).value
    return mod[identifier]


def set_value(mod, identifier: str, value: Any):
    if NEW_API:
        inp = getattr(mod.properties.inputs, identifier)
        cur = inp.value
        if isinstance(cur, float) and isinstance(value, int):
            value = float(value)
        if hasattr(cur, '__len__') and not isinstance(cur, str) and len(value) != len(cur):
            value = tuple(value)[:len(cur)] if len(value) > len(cur) else (*value, 1.0)
        inp.value = value
        return
    prop_ui = mod.id_properties_ui(identifier).as_dict()
    if 'items' in prop_ui:
        for item in prop_ui['items']:
            if item[0] == value:
                mod[identifier] = item[4]
                return
        print(f"Gold Extended: menu item '{value}' not found for '{identifier}' on '{mod.name}'")
        return
    cur = mod[identifier]
    if isinstance(cur, float) and isinstance(value, int):
        value = float(value)
    mod[identifier] = value


def has_input(mod, identifier: str) -> bool:
    if NEW_API:
        inp = getattr(mod.properties.inputs, identifier, None)
        return inp is not None and hasattr(inp, 'value')
    return identifier in mod.keys()


def draw_input(layout, mod, identifier: str, text: str | None = None, **kwargs):
    """Draw a modifier input value widget."""
    if text is not None:
        kwargs['text'] = text
    if NEW_API:
        layout.prop(getattr(mod.properties.inputs, identifier), 'value', **kwargs)
        return
    layout.prop(mod, f'["{identifier}"]', **kwargs)


def tag_update(obj, mod=None):
    if mod is not None and mod.node_group is not None:
        mod.node_group.interface_update(bpy.context)
    obj.update_tag()
