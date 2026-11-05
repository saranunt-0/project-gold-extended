# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Effect registry and the generic create / preset machinery.

An effect is a subclass of :class:`Effect` that declares

* ``spec``      – hyper-parameters (:mod:`.params`), grouped in panels,
* ``build()``   – the Geometry Nodes recipe (:mod:`.nodes` DSL),
* ``materials`` – one :class:`MaterialSlot` per material socket (role),
* ``presets``   – named parameter sets (+ optional look/brush overrides),
* ``variants``  – one-click entries shown in the *Create* panel.

Everything else – node group creation, object setup, material creation,
preset application – is shared and lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import bpy
from mathutils import Matrix

from . import compat, params, shading, strokes
from .nodes import TreeBuilder, ensure_tree

EFFECTS: dict[str, 'Effect'] = {}
MODIFIER_NAME = 'Gold FX'


@dataclass
class MaterialSlot:
    socket: str                  # material input name on the node group
    role: str                    # human readable role ("Flames", "Smoke"...)
    brush: str | None = 'Soft Dab'  # default brush style (name or id); None = no brush (solid surface)
    look_preset: str = 'Default'
    look: dict = field(default_factory=dict)


@dataclass
class Variant:
    label: str
    preset: str
    icon: str = 'NONE'
    description: str = ''


class Effect:
    id = ''
    label = ''
    icon = 'NONE'
    category = ''
    description = ''
    host = 'DOMAIN'              # DOMAIN: own mesh is the volume. SURFACE: references a surface mesh.
    hide_surface = False         # SURFACE effects that replace their surface (water) hide it from render
    version = 1
    spec: list = []
    presets: dict = {}
    materials: list = []
    variants: list = []

    # ---- naming ----------------------------------------------------------
    @property
    def group_name(self):
        return f'GOLDX {self.label} v{self.version}'

    # ---- to implement ----------------------------------------------------
    def build(self, tb: TreeBuilder, P: 'ParamAccess'):
        raise NotImplementedError

    def make_mesh(self, mesh: bpy.types.Mesh):
        """Fill ``mesh`` with the default domain (DOMAIN) or surface (SURFACE)."""
        import bmesh
        bm = bmesh.new()
        bmesh.ops.create_cube(bm, size=2.0)
        bm.to_mesh(mesh)
        bm.free()

    def setup_object(self, context, obj, mod):
        """Optional hook after the object, modifier and materials exist."""


class ParamAccess:
    """Lazy access to group input sockets by parameter name."""

    def __init__(self, tb: TreeBuilder):
        self.tb = tb
        self._cache = {}

    def __getitem__(self, name):
        if name not in self._cache:
            self._cache[name] = self.tb.I(name)
        return self._cache[name]


# Fine-tuning controls hidden until "Advanced" is enabled, so the default UI
# shows the handful of parameters that define the look and motion.
ADVANCED = {
    'Seed', 'Camera', 'Resolution', 'Time Offset', 'Size Variation', 'Speed Variation', 'Length Variation',
    'Height Variation', 'Lifetime Variation', 'Value Variation', 'Turbulence Scale', 'Turbulence Speed',
    'Sway Frequency', 'Fade Edges', 'Splash Droplets', 'Billow Scale', 'Edge Softness', 'Light Wrap', 'Ambient',
    'Interior Darkening', 'Accent Scale', 'Gust Scale', 'Gust Speed', 'Flutter Frequency', 'Stiffness',
    'Clump Shape', 'Patch Scale', 'Max Slope', 'Direction Spread', 'Wave Speed', 'Ripple Scale', 'Lift',
    'Sparkle Sharpness', 'Body Subdivisions', 'Strands per Clump', 'Sun Direction', 'Cooling', 'Core Size',
}


def register_effect(cls):
    inst = cls()
    for _panel, p in params.iter_params(inst.spec):
        if p.name in ADVANCED:
            p.advanced = True
    EFFECTS[inst.id] = inst
    return cls


# --------------------------------------------------------------------------
# Node groups
# --------------------------------------------------------------------------

def _build_into(ng, effect: Effect):
    strokes.ensure_all()
    params.build_interface(ng, effect.spec)
    tb = TreeBuilder(ng)
    P = ParamAccess(tb)
    geo = effect.build(tb, P)
    tb.output('Geometry', geo)
    params.finalize_menu_defaults(ng, effect.spec)
    tb.layout()
    ng['goldx_effect'] = effect.id
    ng['goldx_version'] = effect.version
    ng.description = effect.description
    return ng


def ensure_group(effect: Effect, rebuild: bool = False):
    if rebuild:
        return rebuild_group(effect)
    ng, created = ensure_tree(effect.group_name)
    if created:
        _build_into(ng, effect)
    return ng


def rebuild_group(effect: Effect):
    """Regenerate an effect's node group without mutating the one in use.

    A new group is built, every modifier is re-pointed to it with its values
    restored by parameter name, then the old group is removed.  (Clearing a
    group that modifiers still use crashes Blender 4.5.)
    """
    old = bpy.data.node_groups.get(effect.group_name)
    new = bpy.data.node_groups.new(effect.group_name + ' (rebuild)', 'GeometryNodeTree')
    _build_into(new, effect)
    restored = 0
    if old is not None:
        names = [p.name for _panel, p in params.iter_params(effect.spec)]
        for obj in bpy.data.objects:
            for mod in obj.modifiers:
                if mod.type != 'NODES' or mod.node_group != old:
                    continue
                values = {}
                for nm in names:
                    ident = params.socket_identifier(old, nm)
                    if ident and compat.has_input(mod, ident):
                        values[nm] = compat.get_value(mod, ident)
                mod.node_group = new
                for nm, v in values.items():
                    if v is not None:
                        set_param(mod, nm, v)
                restored += 1
        bpy.data.node_groups.remove(old)
    new.name = effect.group_name
    new['goldx_restored'] = restored
    return new


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------

def effect_of(obj) -> Effect | None:
    if obj is None:
        return None
    return EFFECTS.get(obj.get('goldx_effect', ''))


def effect_modifier(obj):
    if obj is None:
        return None
    for mod in obj.modifiers:
        if mod.type == 'NODES' and mod.node_group and mod.node_group.get('goldx_effect'):
            return mod
    return None


def is_effect_object(obj) -> bool:
    return effect_modifier(obj) is not None and 'goldx_effect' in obj.keys()


def materials_of(obj):
    """Yield (MaterialSlot, material) pairs for an effect object."""
    eff = effect_of(obj)
    mod = effect_modifier(obj)
    if eff is None or mod is None:
        return
    for slot in eff.materials:
        ident = params.socket_identifier(mod.node_group, slot.socket)
        mat = compat.get_value(mod, ident) if ident and compat.has_input(mod, ident) else None
        yield slot, mat


def set_param(mod, name, value):
    ident = params.socket_identifier(mod.node_group, name)
    if ident is None or not compat.has_input(mod, ident):
        print(f"Gold Extended: unknown parameter '{name}'")
        return False
    compat.set_value(mod, ident, value)
    mod.id_data.update_tag()
    return True


def get_param(mod, name):
    ident = params.socket_identifier(mod.node_group, name)
    return compat.get_value(mod, ident) if ident else None


# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------

def apply_preset(obj, preset_name: str, include_look: bool = True):
    eff = effect_of(obj)
    mod = effect_modifier(obj)
    if eff is None or mod is None:
        return False
    preset = eff.presets.get(preset_name)
    if preset is None:
        return False
    for k, v in preset.items():
        if k.startswith('_'):
            continue
        set_param(mod, k, v)
    if include_look:
        looks = preset.get('_look', {})
        brushes_ = preset.get('_brush', {})
        for slot, mat in materials_of(obj):
            if mat is None:
                continue
            values = dict(shading.LOOK_PRESETS.get(slot.look_preset, {}))
            values.update(slot.look)
            values.update(looks.get(slot.role, {}))
            shading.apply_look(mat, values, reset=True)
            if slot.role in brushes_:
                shading.set_brush_style(mat, brushes_[slot.role])
    obj['goldx_preset'] = preset_name
    compat.tag_update(obj, mod)
    return True


def capture_preset(obj) -> dict:
    """Current parameter values of an effect object as a preset dict."""
    eff = effect_of(obj)
    mod = effect_modifier(obj)
    out = {}
    if eff is None or mod is None:
        return out
    for _panel, p in params.iter_params(eff.spec):
        if p.type in ('OBJECT', 'MATERIAL', 'COLLECTION'):
            continue
        val = get_param(mod, p.name)
        if hasattr(val, '__len__') and not isinstance(val, str):
            val = tuple(round(x, 4) for x in val)
        elif isinstance(val, float):
            val = round(val, 4)
        out[p.name] = val
    return out


# --------------------------------------------------------------------------
# Object creation
# --------------------------------------------------------------------------

def _link_like(obj, ref, context):
    cols = [c for c in (ref.users_collection if ref else []) if not c.library]
    if not cols:
        cols = [context.collection if not context.collection.library else context.scene.collection]
    for c in cols:
        c.objects.link(obj)


def _pick_surface(context, effect):
    ob = context.active_object
    if ob and ob.type == 'MESH' and not is_effect_object(ob) and ob.select_get():
        return ob, False
    mesh = bpy.data.meshes.new(f'{effect.label} Surface')
    effect.make_mesh(mesh)
    surf = bpy.data.objects.new(f'{effect.label} Surface', mesh)
    surf.location = context.scene.cursor.location
    _link_like(surf, None, context)
    return surf, True


def create(context, effect_id: str, preset: str | None = None, name: str = '', render_setup: bool = True):
    """Create an effect object. Returns (object, modifier)."""
    eff = EFFECTS[effect_id]
    ng = ensure_group(eff)
    if context.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')

    label = name or eff.label
    if eff.host == 'SURFACE':
        surface, _created = _pick_surface(context, eff)
        obj = bpy.data.objects.new(f'{surface.name} · {label}', bpy.data.meshes.new(f'{label}'))
        _link_like(obj, surface, context)
        obj.parent = surface
        obj.matrix_parent_inverse = Matrix.Identity(4)
    else:
        surface = None
        mesh = bpy.data.meshes.new(label)
        eff.make_mesh(mesh)
        obj = bpy.data.objects.new(label, mesh)
        obj.location = context.scene.cursor.location
        _link_like(obj, None, context)

    mod = obj.modifiers.new(MODIFIER_NAME, 'NODES')
    mod.node_group = ng
    obj['goldx_effect'] = eff.id
    obj['goldx_version'] = eff.version
    obj.visible_shadow = False

    if surface is not None:
        set_param(mod, 'Surface', surface)

    if surface is not None and eff.hide_surface:
        surface.hide_render = True
        surface.display_type = 'WIRE'

    # Materials are assigned inside the node tree (Set Material). The object
    # gets no material slots of its own: Geometry Nodes orders the evaluated
    # material list itself, and pre-made slots would be matched by index.
    for slot in eff.materials:
        mat = shading.new_material(f'GX {label} · {slot.role}', slot.brush, slot.look, slot.look_preset,
                                   role=slot.role, extra_dir=_extra_dir(context))
        set_param(mod, slot.socket, mat)

    preset = preset or (next(iter(eff.presets)) if eff.presets else None)
    if preset:
        apply_preset(obj, preset)

    eff.setup_object(context, obj, mod)
    if render_setup:
        ensure_render_settings(context.scene)

    for o in context.selected_objects:
        o.select_set(False)
    obj.select_set(True)
    context.view_layer.objects.active = obj
    compat.tag_update(obj, mod)
    return obj, mod


TRANSPARENT_BOUNCES = 256


def ensure_render_settings(scene, bounces: int = TRANSPARENT_BOUNCES) -> bool:
    """Brush cards overlap many layers deep; Cycles' default of 8 transparent
    bounces turns deep overlaps black.  Raise the limit (never lower it), as
    the base add-on's Render Setup does.  Returns True when changed."""
    cyc = getattr(scene, 'cycles', None)
    if cyc is None or cyc.transparent_max_bounces >= bounces:
        return False
    cyc.transparent_max_bounces = bounces
    return True


def _extra_dir(context):
    try:
        return context.preferences.addons[__package__.rsplit('.', 1)[0]].preferences.brush_library_path
    except (KeyError, AttributeError):
        return ''
