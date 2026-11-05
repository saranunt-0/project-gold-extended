# SPDX-FileCopyrightText: 2026 Gold Extended Authors
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Scene Grade: scene-wide visual finishing in the compositor.

Per-stroke looks live in the material (:mod:`.shading`).  Some effects are
only possible on the final image, so Gold Extended adds one compositor node
group with these controls:

Bloom                 glow around bright paint (fire, sparkles, neon)
Chromatic Aberration  real lens dispersion (RGB split toward the edges)
Saturation/Vibrance   global saturation and smart saturation
Contrast              global contrast
Vignette              resolution-independent darkened corners

Blender 5.x stores the compositor as a node group on the scene
(``scene.compositing_node_group``); Blender 4.x uses ``scene.node_tree``.
Both are handled; only 5.x is covered by the automated tests.
"""

import bpy

from .nodes import TreeBuilder, ensure_tree, new_socket

VERSION = 1
GRADE = f'.GOLDX.grade.v{VERSION}'
NODE_NAME = 'GOLDX Grade'
IS_5X = bpy.app.version >= (5, 0, 0)

GRADE_INPUTS = [
    # name, default, min, max, description
    ('Bloom', 0.0, 0.0, 5.0, 'Glow strength around bright areas'),
    ('Bloom Threshold', 1.0, 0.0, 100.0, 'Brightness above which paint glows'),
    ('Bloom Size', 0.5, 0.0, 1.0, 'Relative size of the glow'),
    ('Chromatic Aberration', 0.0, 0.0, 1.0, 'Lens dispersion: RGB fringes toward the frame edges'),
    ('Saturation', 1.0, 0.0, 2.0, 'Global saturation'),
    ('Vibrance', 0.0, -1.0, 1.0, 'Smart saturation: boosts muted colours more'),
    ('Contrast', 0.0, -50.0, 50.0, 'Global contrast'),
    ('Vignette', 0.0, 0.0, 1.0, 'Darken the corners'),
]

GRADE_PRESETS = {
    'Neutral': {},
    'Painterly Warm': {'Vibrance': 0.35, 'Contrast': 8.0, 'Vignette': 0.35, 'Bloom': 0.3},
    'Dreamy Glow': {'Bloom': 1.2, 'Bloom Threshold': 0.6, 'Bloom Size': 0.8, 'Saturation': 0.9, 'Vignette': 0.25},
    'Vivid Pop': {'Vibrance': 0.8, 'Saturation': 1.15, 'Contrast': 15.0, 'Chromatic Aberration': 0.15},
    'Retro Lens': {'Chromatic Aberration': 0.6, 'Vignette': 0.6, 'Saturation': 0.85, 'Contrast': 10.0},
}


def _glare_type(node, value='BLOOM'):
    if 'Type' in node.inputs and node.inputs['Type'].type == 'MENU':
        node.inputs['Type'].default_value = value.title()
    elif hasattr(node, 'glare_type'):
        node.glare_type = value


def ensure_grade_group():
    ng, created = ensure_tree(GRADE, 'CompositorNodeTree')
    if not created:
        return ng
    new_socket(ng, 'Image', 'OUTPUT', 'COLOR')
    new_socket(ng, 'Image', 'INPUT', 'COLOR', default=(0, 0, 0, 1))
    for nm, d, lo, hi, desc in GRADE_INPUTS:
        new_socket(ng, nm, 'INPUT', 'FLOAT', default=d, min=lo, max=hi, description=desc)
    tb = TreeBuilder(ng)
    I = tb.I
    img = I('Image')

    glare = tb.node('CompositorNodeGlare')
    _glare_type(glare.n, 'BLOOM')
    tb.set_input(glare.n, 'Image', img)
    for k, v in (('Threshold', I('Bloom Threshold')), ('Strength', I('Bloom')), ('Size', I('Bloom Size'))):
        if k in glare.n.inputs:
            tb.set_input(glare.n, k, v)
    if not IS_5X:   # 4.x: properties instead of sockets
        glare.n.threshold = 1.0
    img = glare['Image']

    lens = tb.node('CompositorNodeLensdist')
    tb.set_input(lens.n, 'Image', img)
    if 'Dispersion' in lens.n.inputs:
        tb.set_input(lens.n, 'Dispersion', I('Chromatic Aberration') * 0.25)
    img = lens['Image']

    hs = tb.node('CompositorNodeHueSat', {'Image': img, 'Saturation': I('Saturation')})
    img = hs['Image']

    sep = tb.node('CompositorNodeSeparateColor', {'Image': img}, mode='HSV')
    s = sep['Green']
    s2 = tb.clamp01(s * (1.0 + I('Vibrance') * (1.0 - tb.clamp01(s))))
    comb = tb.node('CompositorNodeCombineColor', {'Red': sep['Red'], 'Green': s2, 'Blue': sep['Blue'],
                                                  'Alpha': sep['Alpha']}, mode='HSV')
    img = comb['Image']

    bc = tb.node('CompositorNodeBrightContrast', {'Image': img, 'Contrast': I('Contrast')})
    img = bc['Image']

    if IS_5X:
        coords = tb.node('CompositorNodeImageCoordinates', {'Image': img})['Normalized']
        d = tb.vmath('DISTANCE', coords, (0.5, 0.5, 0.0))
        vig = tb.map_range(d, 0.3, 0.75, 0.0, 1.0, interp='SMOOTHSTEP') * I('Vignette')
        img = tb.mix_color(vig, img, (0.0, 0.0, 0.0, 1.0))
    tb.output('Image', img)
    tb.layout()
    return ng


def _scene_tree(scene, create=True):
    if IS_5X and hasattr(scene, 'compositing_node_group'):
        tree = scene.compositing_node_group
        if tree is None and create:
            tree = bpy.data.node_groups.new(f'{scene.name} Compositing', 'CompositorNodeTree')
            new_socket(tree, 'Image', 'OUTPUT', 'COLOR')
            rl = tree.nodes.new('CompositorNodeRLayers')
            out = tree.nodes.new('NodeGroupOutput')
            tree.links.new(rl.outputs['Image'], out.inputs[0])
            rl.location, out.location = (-300, 0), (300, 0)
            scene.compositing_node_group = tree
        return tree
    if create and not scene.use_nodes:
        scene.use_nodes = True
    return scene.node_tree


def _output_socket(tree):
    for n in tree.nodes:
        if n.bl_idname == 'NodeGroupOutput' and n.inputs:
            return n.inputs[0]
    for n in tree.nodes:
        if n.bl_idname == 'CompositorNodeComposite':
            return n.inputs['Image']
    return None


def grade_node(scene):
    tree = _scene_tree(scene, create=False)
    if tree is None:
        return None
    return tree.nodes.get(NODE_NAME)


def enable(scene):
    """Insert the grade node right before the compositor output."""
    tree = _scene_tree(scene)
    node = tree.nodes.get(NODE_NAME)
    if node is not None:
        node.mute = False
        return node
    target = _output_socket(tree)
    if target is None:
        raise RuntimeError('No compositor output found')
    node = tree.nodes.new('CompositorNodeGroup')
    node.node_tree = ensure_grade_group()
    node.name = NODE_NAME
    node.label = 'Gold FX Scene Grade'
    node.width = 220
    if target.links:
        src = target.links[0].from_socket
        tree.links.new(src, node.inputs['Image'])
    tree.links.new(node.outputs['Image'], target)
    node.location = (target.node.location.x - 260, target.node.location.y)
    target.node.location.x += 40
    scene.render.use_compositing = True
    return node


def disable(scene):
    node = grade_node(scene)
    if node is None:
        return False
    tree = node.id_data
    src = node.inputs['Image'].links[0].from_socket if node.inputs['Image'].links else None
    dst = [l.to_socket for l in node.outputs['Image'].links]
    tree.nodes.remove(node)
    if src is not None:
        for d in dst:
            tree.links.new(src, d)
    return True


def apply_preset(scene, name):
    node = grade_node(scene)
    if node is None:
        return False
    values = {nm: d for nm, d, *_ in GRADE_INPUTS}
    values.update(GRADE_PRESETS.get(name, {}))
    for k, v in values.items():
        if k in node.inputs:
            node.inputs[k].default_value = v
    return True
