# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Declarative hyper-parameter schema.

Each effect describes its controls once, as a list of :class:`Panel` objects
holding :class:`P` parameters.  That single description is used to

* create the Geometry Nodes group interface (sockets, ranges, sub-types,
  tooltips, panels),
* draw the sidebar UI (including the *Advanced* filter),
* validate and apply presets by human-readable name.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import nodes


@dataclass
class P:
    """One user-facing hyper-parameter."""
    name: str
    type: str = 'FLOAT'          # FLOAT INT BOOL VECTOR COLOR OBJECT MATERIAL MENU STRING
    default: Any = None
    min: float | None = None
    max: float | None = None
    subtype: str | None = None   # FACTOR DISTANCE ANGLE PERCENTAGE TIME VELOCITY XYZ ...
    desc: str = ''
    items: tuple = ()            # MENU items (names)
    advanced: bool = False       # only shown when "Advanced" is enabled
    hidden: bool = False         # wired automatically (e.g. surface object), never drawn


@dataclass
class Panel:
    name: str
    params: list = field(default_factory=list)
    closed: bool = False
    desc: str = ''


def iter_params(spec):
    for panel in spec:
        for p in panel.params:
            yield panel, p


def find_param(spec, name):
    for _, p in iter_params(spec):
        if p.name == name:
            return p
    return None


def build_interface(tree, spec, geometry_in=True, outputs=(('Geometry', 'GEOMETRY'),)):
    """Create interface sockets for ``spec`` on ``tree``.

    Returns a dict mapping parameter name -> interface socket.
    """
    for name, stype in outputs:
        nodes.new_socket(tree, name, 'OUTPUT', stype)
    if geometry_in:
        nodes.new_socket(tree, 'Geometry', 'INPUT', 'GEOMETRY')
    sockets = {}
    for panel in spec:
        ip = tree.interface.new_panel(panel.name, description=panel.desc, default_closed=panel.closed)
        for p in panel.params:
            single = p.type in ('FLOAT', 'INT', 'BOOL', 'VECTOR', 'COLOR')
            s = nodes.new_socket(tree, p.name, 'INPUT', p.type, parent=ip, default=p.default,
                                 min=p.min, max=p.max, subtype=p.subtype, description=p.desc,
                                 single=single)
            sockets[p.name] = s
    return sockets


def finalize_menu_defaults(tree, spec):
    """Menu sockets only accept a default once a Menu Switch defines items."""
    for _, p in iter_params(spec):
        if p.type != 'MENU' or p.default is None:
            continue
        for item in tree.interface.items_tree:
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == p.name:
                try:
                    item.default_value = p.default
                except (TypeError, ValueError):
                    pass


def socket_identifier(tree, name):
    for item in tree.interface.items_tree:
        if item.item_type == 'SOCKET' and item.in_out == 'INPUT' and item.name == name:
            return item.identifier
    return None


def menu_index(tb: nodes.TreeBuilder, menu_socket, items) -> 'nodes.S':
    """Drive a Menu Switch from a menu group input; returns the selected item index (INT).

    Also defines the menu items for the group input socket.
    """
    n = tb.node('GeometryNodeMenuSwitch', data_type='INT')
    ms = n.n
    coll = ms.enum_items
    coll.clear()
    for it in items:
        coll.new(it)
    tb.set_input(ms, 'Menu', menu_socket)
    for i, it in enumerate(items):
        tb.set_input(ms, it, i)
    return n['Output']
