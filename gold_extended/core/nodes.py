# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
A small DSL for building node trees from Python.

Every effect in Gold Extended is a Geometry Nodes group generated from a
Python "recipe".  Writing those recipes with raw ``nodes.new`` / ``links.new``
calls is unreadable, so this module wraps output sockets in :class:`S`, which
supports arithmetic operators, and offers one helper per common node.

    tb = TreeBuilder(node_group)
    t = tb.time_seconds()
    height = tb.I('Height')                       # group input socket
    z = height - tb.fract(t * tb.I('Speed')) * height
    pos = tb.combine(x, y, z)

Version tolerance: Blender 5.x turned several node *properties* into *menu
input sockets* (e.g. Resample Curve "Mode").  ``TreeBuilder.node`` accepts
both as keyword arguments and routes each to whichever exists.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

import bpy

# --------------------------------------------------------------------------
# Socket wrapper
# --------------------------------------------------------------------------

_VECTOR_TYPES = {'VECTOR'}
_FLOAT_TYPES = {'VALUE', 'INT', 'BOOLEAN'}


class S:
    """Wrapper around a node *output* socket with operator overloading."""

    __slots__ = ('tb', 's')

    def __init__(self, tb: 'TreeBuilder', socket):
        self.tb = tb
        self.s = socket

    # type information ------------------------------------------------------
    @property
    def type(self) -> str:
        return self.s.type

    @property
    def is_vector(self) -> bool:
        return self.s.type in _VECTOR_TYPES

    # arithmetic ------------------------------------------------------------
    def __add__(self, o):
        return self.tb.add(self, o)

    def __radd__(self, o):
        return self.tb.add(o, self)

    def __sub__(self, o):
        return self.tb.sub(self, o)

    def __rsub__(self, o):
        return self.tb.sub(o, self)

    def __mul__(self, o):
        return self.tb.mul(self, o)

    def __rmul__(self, o):
        return self.tb.mul(o, self)

    def __truediv__(self, o):
        return self.tb.div(self, o)

    def __rtruediv__(self, o):
        return self.tb.div(o, self)

    def __neg__(self):
        return self.tb.mul(self, -1.0)

    def __pow__(self, o):
        return self.tb.math('POWER', self, o)

    # vector component access ----------------------------------------------
    @property
    def x(self):
        return self.tb.sep(self)[0]

    @property
    def y(self):
        return self.tb.sep(self)[1]

    @property
    def z(self):
        return self.tb.sep(self)[2]

    def __repr__(self):
        return f"<S {self.s.node.name}.{self.s.name} ({self.s.type})>"


def _is_vec_const(v) -> bool:
    return isinstance(v, (tuple, list)) and len(v) == 3


def _is_vec(v) -> bool:
    if isinstance(v, S):
        return v.is_vector
    return _is_vec_const(v)


class NodeW:
    """Wrapper around a node giving convenient output access."""

    __slots__ = ('tb', 'n')

    def __init__(self, tb: 'TreeBuilder', node):
        self.tb = tb
        self.n = node

    def __getitem__(self, key) -> S:
        return S(self.tb, _find_socket(self.n.outputs, key))

    @property
    def out(self) -> S:
        for s in self.n.outputs:
            if _socket_enabled(s):
                return S(self.tb, s)
        return S(self.tb, self.n.outputs[0])

    def inp(self, key):
        return _find_socket(self.n.inputs, key)


def _socket_enabled(s) -> bool:
    # ``enabled`` exists up to at least 5.2; be defensive for later versions.
    en = getattr(s, 'enabled', True)
    if getattr(s, 'is_unavailable', False):
        return False
    return en


# Sockets renamed between Blender versions (4.5 name <-> 5.x name).
SOCKET_ALIASES = {
    'Mesh': ('Geometry',),        # Set Shade Smooth input
    'Factor': ('Fac',),           # Noise / Color Ramp output and input
    'Fac': ('Factor',),
}


def _find_socket(sockets, key):
    """Find a socket by index, name or identifier, preferring enabled ones."""
    if isinstance(key, int):
        return sockets[key]
    for candidate in (key, *SOCKET_ALIASES.get(key, ())):
        first = None
        for s in sockets:
            if s.name == candidate or s.identifier == candidate:
                if _socket_enabled(s):
                    return s
                if first is None:
                    first = s
        if first is not None:
            return first
    raise KeyError(f"Socket '{key}' not found among {[s.name for s in sockets]}")


# --------------------------------------------------------------------------
# Tree builder
# --------------------------------------------------------------------------

class TreeBuilder:
    """Helper to add nodes and links to a node tree."""

    def __init__(self, tree: bpy.types.NodeTree, clear: bool = False):
        self.tree = tree
        self.nodes = tree.nodes
        self.links = tree.links
        self.is_geo = tree.bl_idname == 'GeometryNodeTree'
        self.is_shader = tree.bl_idname == 'ShaderNodeTree'
        if clear:
            self.nodes.clear()
        self._gin = None
        self._gout = None
        self._sep_cache: dict = {}

    # -- generic -----------------------------------------------------------
    def node(self, idname: str, inputs: dict | None = None, label: str = '',
             name: str = '', **props) -> NodeW:
        n = self.nodes.new(idname)
        if label:
            n.label = label
        if name:
            n.name = name
        # Properties first: they change which sockets are enabled.
        for k, v in props.items():
            self._set_prop(n, k, v)
        if inputs:
            for k, v in inputs.items():
                self.set_input(n, k, v)
        return NodeW(self, n)

    def _set_prop(self, n, key, value):
        if hasattr(n, key) and not isinstance(getattr(type(n), key, None), property):
            try:
                setattr(n, key, value)
                return
            except (TypeError, AttributeError):
                pass
        # Blender 5.x: property migrated to a menu input socket.
        label = key.replace('_', ' ').title()
        for s in n.inputs:
            if s.type == 'MENU' and s.name.lower() in (label.lower(), key.lower()):
                s.default_value = _menu_label(value)
                return
        raise AttributeError(f"{n.bl_idname} has no property or menu '{key}'")

    def set_input(self, n, key, value):
        sock = _find_socket(n.inputs, key)
        if value is None:
            return
        if isinstance(value, NodeW):
            value = value.out
        if isinstance(value, S):
            self.links.new(value.s, sock)
            return
        if isinstance(value, bpy.types.NodeSocket):
            self.links.new(value, sock)
            return
        if sock.type == 'MENU':
            sock.default_value = _menu_label(value)
            return
        if sock.type in ('VECTOR', 'RGBA') and isinstance(value, (int, float)):
            n_comp = len(sock.default_value)
            value = tuple([float(value)] * n_comp)
        if sock.type == 'RGBA' and isinstance(value, (tuple, list)) and len(value) == 3:
            value = (*value, 1.0)
        sock.default_value = value

    def link(self, a, b):
        if isinstance(a, NodeW):
            a = a.out
        if isinstance(a, S):
            a = a.s
        if isinstance(b, S):
            b = b.s
        return self.links.new(a, b)

    # -- group IO ----------------------------------------------------------
    @property
    def gin(self):
        if self._gin is None:
            self._gin = self.nodes.get('Group Input') or self.nodes.new('NodeGroupInput')
        return self._gin

    @property
    def gout(self):
        if self._gout is None:
            self._gout = self.nodes.get('Group Output') or self.nodes.new('NodeGroupOutput')
            self._gout.is_active_output = True
        return self._gout

    def I(self, name: str) -> S:  # noqa: E743 - short name used pervasively
        """Group input socket by interface name."""
        return S(self, _find_socket(self.gin.outputs, name))

    def output(self, name: str, value):
        self.set_input(self.gout, name, value)

    def group(self, ng, inputs: dict | None = None, label: str = '', name: str = '') -> NodeW:
        idname = {'GeometryNodeTree': 'GeometryNodeGroup',
                  'ShaderNodeTree': 'ShaderNodeGroup',
                  'CompositorNodeTree': 'CompositorNodeGroup'}[self.tree.bl_idname]
        n = self.nodes.new(idname)
        n.node_tree = ng
        if label:
            n.label = label
        if name:
            n.name = name
        if inputs:
            for k, v in inputs.items():
                self.set_input(n, k, v)
        return NodeW(self, n)

    # -- constants ---------------------------------------------------------
    def value(self, v: float, label: str = '') -> S:
        n = self.node('ShaderNodeValue', label=label)
        n.n.outputs[0].default_value = v
        return n.out

    def vec(self, v) -> S:
        if self.is_geo:
            n = self.node('FunctionNodeInputVector')
            n.n.vector = v
            return n.out
        return self.combine(*v)

    def _as_socket(self, v, want_vec=False):
        if isinstance(v, NodeW):
            return v.out
        return v

    # -- math --------------------------------------------------------------
    def math(self, op: str, a, b=None, c=None, clamp: bool = False) -> S:
        n = self.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.set_input(n.n, i, self._as_socket(v))
        return n.out

    def vmath(self, op: str, a, b=None, c=None, scale=None) -> S:
        n = self.node('ShaderNodeVectorMath', operation=op)
        for i, v in enumerate((a, b, c)):
            if v is not None:
                self.set_input(n.n, i, self._as_socket(v))
        if scale is not None:
            self.set_input(n.n, 'Scale', scale)
        if op in ('DOT_PRODUCT', 'LENGTH', 'DISTANCE'):
            return n['Value']
        return n['Vector']

    def _bin(self, fop, vop, a, b):
        if _is_vec(a) or _is_vec(b):
            return self.vmath(vop, a, b)
        return self.math(fop, a, b)

    def add(self, a, b):
        return self._bin('ADD', 'ADD', a, b)

    def sub(self, a, b):
        return self._bin('SUBTRACT', 'SUBTRACT', a, b)

    def mul(self, a, b):
        if _is_vec(a) and not _is_vec(b):
            return self.vmath('SCALE', a, scale=b)
        if _is_vec(b) and not _is_vec(a):
            return self.vmath('SCALE', b, scale=a)
        return self._bin('MULTIPLY', 'MULTIPLY', a, b)

    def div(self, a, b):
        if _is_vec(a) and not _is_vec(b):
            return self.vmath('SCALE', a, scale=self.math('DIVIDE', 1.0, b))
        return self._bin('DIVIDE', 'DIVIDE', a, b)

    def fract(self, a):
        return self.vmath('FRACTION', a) if _is_vec(a) else self.math('FRACT', a)

    def floor(self, a):
        return self.vmath('FLOOR', a) if _is_vec(a) else self.math('FLOOR', a)

    def abs(self, a):
        return self.vmath('ABSOLUTE', a) if _is_vec(a) else self.math('ABSOLUTE', a)

    def sin(self, a):
        return self.vmath('SINE', a) if _is_vec(a) else self.math('SINE', a)

    def cos(self, a):
        return self.vmath('COSINE', a) if _is_vec(a) else self.math('COSINE', a)

    def min(self, a, b):
        return self._bin('MINIMUM', 'MINIMUM', a, b)

    def max(self, a, b):
        return self._bin('MAXIMUM', 'MAXIMUM', a, b)

    def pow(self, a, b):
        return self.math('POWER', a, b)

    def sqrt(self, a):
        return self.math('SQRT', a)

    def clamp01(self, a):
        return self.math('ADD', a, 0.0, clamp=True)

    def wrap(self, a, lo, hi):
        if _is_vec(a):
            return self.vmath('WRAP', a, hi, lo)
        return self.math('WRAP', a, hi, lo)

    def mod(self, a, b):
        return self.math('FLOORED_MODULO', a, b)

    def round(self, a):
        return self.math('ROUND', a)

    def lerp(self, a, b, t):
        """Linear interpolation; vector aware."""
        if _is_vec(a) or _is_vec(b):
            return self.mix(t, a, b, 'VECTOR', clamp=False)
        return self.mix(t, a, b, 'FLOAT', clamp=False)

    def smoothstep(self, e0, e1, x):
        return self.map_range(x, e0, e1, 0.0, 1.0, interp='SMOOTHSTEP')

    def normalize(self, v):
        return self.vmath('NORMALIZE', v)

    def length(self, v):
        return self.vmath('LENGTH', v)

    def dot(self, a, b):
        return self.vmath('DOT_PRODUCT', a, b)

    def cross(self, a, b):
        return self.vmath('CROSS_PRODUCT', a, b)

    def scale(self, v, s):
        return self.vmath('SCALE', v, scale=s)

    # -- vectors -----------------------------------------------------------
    def combine(self, x=0.0, y=0.0, z=0.0) -> S:
        return self.node('ShaderNodeCombineXYZ', {0: x, 1: y, 2: z}).out

    def sep(self, v):
        if isinstance(v, S):
            key = (v.s.node.name, v.s.identifier)
            if key in self._sep_cache:
                return self._sep_cache[key]
        n = self.node('ShaderNodeSeparateXYZ', {0: v})
        res = (n[0], n[1], n[2])
        if isinstance(v, S):
            self._sep_cache[(v.s.node.name, v.s.identifier)] = res
        return res

    def rotate_axis(self, vec, axis, angle) -> S:
        return self.node('ShaderNodeVectorRotate', {'Vector': vec, 'Axis': axis, 'Angle': angle},
                         rotation_type='AXIS_ANGLE').out

    # -- misc utility nodes --------------------------------------------------
    def mix(self, fac, a, b, data_type='FLOAT', blend='MIX', clamp=True) -> S:
        n = self.node('ShaderNodeMix', data_type=data_type, blend_type=blend, clamp_factor=clamp)
        self.set_input(n.n, 'Factor', fac)
        self.set_input(n.n, 'A', a)
        self.set_input(n.n, 'B', b)
        return n['Result']

    def mix_color(self, fac, a, b, blend='MIX', clamp=True) -> S:
        return self.mix(fac, a, b, 'RGBA', blend, clamp)

    def map_range(self, v, fmin=0.0, fmax=1.0, tmin=0.0, tmax=1.0, clamp=True, interp='LINEAR') -> S:
        n = self.node('ShaderNodeMapRange', interpolation_type=interp, clamp=clamp)
        for k, val in (('Value', v), ('From Min', fmin), ('From Max', fmax), ('To Min', tmin), ('To Max', tmax)):
            self.set_input(n.n, k, val)
        return n['Result']

    def color_ramp(self, fac, stops: Iterable[tuple[float, tuple]], interp='LINEAR') -> S:
        n = self.node('ShaderNodeValToRGB', {0: fac})
        cr = n.n.color_ramp
        cr.interpolation = interp
        stops = list(stops)
        while len(cr.elements) < len(stops):
            cr.elements.new(0.5)
        for el, (pos, col) in zip(cr.elements, stops):
            el.position = pos
            el.color = col if len(col) == 4 else (*col, 1.0)
        return n['Color']

    def noise(self, vec=None, w=None, scale=1.0, detail=2.0, roughness=0.5, distortion=0.0,
              dims=None, normalize=True):
        if dims is None:
            dims = '4D' if w is not None else '3D'
        n = self.node('ShaderNodeTexNoise', noise_dimensions=dims)
        n.n.normalize = normalize
        ins = {'Vector': vec, 'Scale': scale, 'Detail': detail, 'Roughness': roughness,
               'Distortion': distortion}
        if w is not None:
            ins['W'] = w
        for k, v in ins.items():
            if v is not None:
                self.set_input(n.n, k, v)
        return n['Factor'], n['Color']

    def white_noise(self, vec=None, w=None, dims='3D'):
        n = self.node('ShaderNodeTexWhiteNoise', noise_dimensions=dims)
        if vec is not None:
            self.set_input(n.n, 'Vector', vec)
        if w is not None:
            self.set_input(n.n, 'W', w)
        return n['Value'], n['Color']

    def compare(self, op, a, b, data_type='FLOAT') -> S:
        return self.node('FunctionNodeCompare', {'A': a, 'B': b}, data_type=data_type, operation=op).out

    def bool_math(self, op, a, b=None) -> S:
        ins = {0: a}
        if b is not None:
            ins[1] = b
        return self.node('FunctionNodeBooleanMath', ins, operation=op).out

    def switch(self, cond, false, true, input_type='FLOAT') -> S:
        n = self.node('GeometryNodeSwitch', input_type=input_type)
        self.set_input(n.n, 'Switch', cond)
        self.set_input(n.n, 'False', false)
        self.set_input(n.n, 'True', true)
        return n['Output']

    # -- geometry nodes ------------------------------------------------------
    def time_seconds(self) -> S:
        return self.node('GeometryNodeInputSceneTime')['Seconds']

    def time_frame(self) -> S:
        return self.node('GeometryNodeInputSceneTime')['Frame']

    def index(self) -> S:
        return self.node('GeometryNodeInputIndex').out

    def position(self) -> S:
        return self.node('GeometryNodeInputPosition').out

    def normal(self) -> S:
        return self.node('GeometryNodeInputNormal').out

    def rand(self, data_type='FLOAT', lo=0.0, hi=1.0, id=None, seed=None, prob=None) -> S:
        n = self.node('FunctionNodeRandomValue', data_type=data_type)
        if data_type == 'BOOLEAN':
            self.set_input(n.n, 'Probability', prob if prob is not None else 0.5)
        else:
            self.set_input(n.n, 'Min', lo)
            self.set_input(n.n, 'Max', hi)
        if id is not None:
            self.set_input(n.n, 'ID', id)
        if seed is not None:
            self.set_input(n.n, 'Seed', seed)
        return n['Value']

    def hash_int(self, value, seed=0) -> S:
        return self.node('FunctionNodeHashValue', {'Value': value, 'Seed': seed}, data_type='INT').out

    def int_math(self, op, a, b=None) -> S:
        ins = {0: a}
        if b is not None:
            ins[1] = b
        return self.node('FunctionNodeIntegerMath', ins, operation=op).out

    def store(self, geo, name: str, value, data_type='FLOAT', domain='POINT', selection=None) -> S:
        n = self.node('GeometryNodeStoreNamedAttribute', data_type=data_type, domain=domain)
        self.set_input(n.n, 'Geometry', geo)
        self.set_input(n.n, 'Name', name)
        self.set_input(n.n, 'Value', value)
        if selection is not None:
            self.set_input(n.n, 'Selection', selection)
        return n['Geometry']

    def named(self, name: str, data_type='FLOAT') -> S:
        return self.node('GeometryNodeInputNamedAttribute', {'Name': name}, data_type=data_type)['Attribute']

    def capture(self, geo, fields: list, domain='POINT'):
        """Capture fields on ``geo``. Returns (geometry, [captured fields])."""
        n = self.node('GeometryNodeCaptureAttribute', domain=domain)
        self.set_input(n.n, 'Geometry', geo)
        outs = []
        for i, (dtype, val) in enumerate(fields):
            item = n.n.capture_items.new(dtype, f'v{i}')
            self.set_input(n.n, item.name, val)
            outs.append(S(self, _find_socket(n.n.outputs, item.name)))
        return n['Geometry'], outs

    def sample_index(self, geo, value, index, data_type='FLOAT', domain='POINT', clamp=False) -> S:
        n = self.node('GeometryNodeSampleIndex', data_type=data_type, domain=domain, clamp=clamp)
        self.set_input(n.n, 'Geometry', geo)
        self.set_input(n.n, 'Value', value)
        self.set_input(n.n, 'Index', index)
        return n['Value']

    def set_position(self, geo, position=None, offset=None, selection=None) -> S:
        n = self.node('GeometryNodeSetPosition', {'Geometry': geo})
        if position is not None:
            self.set_input(n.n, 'Position', position)
        if offset is not None:
            self.set_input(n.n, 'Offset', offset)
        if selection is not None:
            self.set_input(n.n, 'Selection', selection)
        return n['Geometry']

    def join(self, *geos) -> S:
        n = self.node('GeometryNodeJoinGeometry')
        # Multi-input socket: link in reverse so the visual order matches.
        for g in reversed([g for g in geos if g is not None]):
            self.link(g, n.n.inputs[0])
        return n.out

    def delete(self, geo, selection, domain='POINT', mode='ALL') -> S:
        return self.node('GeometryNodeDeleteGeometry', {'Geometry': geo, 'Selection': selection},
                         domain=domain, mode=mode).out

    def object_info(self, obj, space='RELATIVE', as_instance=False) -> NodeW:
        return self.node('GeometryNodeObjectInfo', {'Object': obj, 'As Instance': as_instance},
                         transform_space=space)

    def bound_box(self, geo) -> NodeW:
        return self.node('GeometryNodeBoundBox', {'Geometry': geo})

    def set_material(self, geo, mat, selection=None) -> S:
        n = self.node('GeometryNodeSetMaterial', {'Geometry': geo, 'Material': mat})
        if selection is not None:
            self.set_input(n.n, 'Selection', selection)
        return n.out

    def realize(self, geo) -> S:
        return self.node('GeometryNodeRealizeInstances', {'Geometry': geo}).out

    def is_viewport(self) -> S:
        return self.node('GeometryNodeIsViewport').out

    def rotation_from_axes(self, primary, secondary, primary_axis='Y', secondary_axis='Z') -> S:
        return self.node('FunctionNodeAxesToRotation', {'Primary Axis': primary, 'Secondary Axis': secondary},
                         primary_axis=primary_axis, secondary_axis=secondary_axis).out

    # -- layout --------------------------------------------------------------
    def layout(self, x_step: float = 240.0, y_step: float = 170.0):
        """Simple left-to-right layout by dependency depth."""
        depth: dict = {}
        incoming: dict = {n: [] for n in self.nodes}
        for l in self.links:
            incoming[l.to_node].append(l.from_node)

        def get_depth(n, stack=()):
            if n in depth:
                return depth[n]
            if n in stack:
                return 0
            d = 0
            for p in incoming.get(n, []):
                d = max(d, get_depth(p, stack + (n,)) + 1)
            depth[n] = d
            return d

        for n in self.nodes:
            get_depth(n)
        if self._gout is not None:
            depth[self._gout] = max(depth.values(), default=0) + 1
        columns: dict = {}
        for n in self.nodes:
            if n.bl_idname == 'NodeFrame':
                continue
            columns.setdefault(depth.get(n, 0), []).append(n)
        for d, col in columns.items():
            for i, n in enumerate(col):
                n.location = (d * x_step, -i * y_step + len(col) * y_step * 0.5)


def _menu_label(value: str) -> str:
    """Menu sockets take the item *name* (e.g. 'Count'); props take 'COUNT'."""
    if isinstance(value, str) and value.isupper():
        return value.replace('_', ' ').title()
    return value


# --------------------------------------------------------------------------
# Interface helpers
# --------------------------------------------------------------------------

SOCKET_TYPES = {
    'FLOAT': 'NodeSocketFloat',
    'INT': 'NodeSocketInt',
    'BOOL': 'NodeSocketBool',
    'VECTOR': 'NodeSocketVector',
    'COLOR': 'NodeSocketColor',
    'OBJECT': 'NodeSocketObject',
    'MATERIAL': 'NodeSocketMaterial',
    'COLLECTION': 'NodeSocketCollection',
    'GEOMETRY': 'NodeSocketGeometry',
    'MENU': 'NodeSocketMenu',
    'STRING': 'NodeSocketString',
    'SHADER': 'NodeSocketShader',
    'ROTATION': 'NodeSocketRotation',
    'IMAGE': 'NodeSocketImage',
}


def new_socket(tree, name, in_out, stype, parent=None, default=None, min=None, max=None,
               subtype=None, description='', single=False, hide_value=False):
    kwargs = dict(name=name, in_out=in_out, socket_type=SOCKET_TYPES[stype], description=description)
    if parent is not None:
        kwargs['parent'] = parent
    s = tree.interface.new_socket(**kwargs)
    if subtype:
        try:
            s.subtype = subtype
        except (TypeError, AttributeError, ValueError):
            pass
    if min is not None and hasattr(s, 'min_value'):
        s.min_value = min
    if max is not None and hasattr(s, 'max_value'):
        s.max_value = max
    if default is not None and hasattr(s, 'default_value') and stype != 'MENU':
        if stype == 'COLOR' and len(default) == 3:
            default = (*default, 1.0)
        s.default_value = default
    if single and in_out == 'INPUT':
        if hasattr(s, 'structure_type'):
            try:
                s.structure_type = 'SINGLE'
            except (TypeError, ValueError):
                pass
        elif hasattr(s, 'force_non_field'):
            s.force_non_field = True
    if hide_value:
        s.hide_value = True
    return s


def ensure_tree(name: str, kind='GeometryNodeTree', rebuild=False):
    """Get or create a node group. Returns (tree, created)."""
    ng = bpy.data.node_groups.get(name)
    if ng is not None and not rebuild:
        return ng, False
    if ng is None:
        ng = bpy.data.node_groups.new(name, kind)
    else:
        ng.nodes.clear()
        ng.interface.clear()
    return ng, True


TAU = math.tau
