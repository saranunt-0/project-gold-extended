# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Gold Extended – painterly effects built on Project Gold's Brushstroke Tools.

Package layout
--------------
core/      framework: node DSL, parameter schema, stroke builders, Look shader,
           brush library bridge, scene grade, effect registry
effects/   one module per effect recipe (particles, cloud, greenery, hair,
           fire, water); importing a module registers its effect
props.py   scene settings and add-on preferences
operators.py, ui.py
"""

bl_info = {  # used only when installed as a legacy add-on
    "name": "Gold Extended - Brushstroke FX",
    "author": "Gold Extended Authors",
    "version": (1, 0, 0),
    "blender": (4, 5, 0),
    "location": "3D Viewport > Sidebar > Gold FX, Add > Gold FX",
    "description": "Painterly particles, clouds, greenery, hair, fire and water using Project Gold brush styles",
    "category": "Paint",
}

from . import props, operators, ui  # noqa: E402
from . import effects  # noqa: E402,F401  (registers effect recipes)

modules = (props, operators, ui)


def register():
    for m in modules:
        m.register()


def unregister():
    for m in reversed(modules):
        m.unregister()
