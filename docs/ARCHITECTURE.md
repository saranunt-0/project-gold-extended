# Architecture

## Repository layout

```
project-gold-extended/
├── base/
│   └── add-on-brushstroke-tools-v1.2.3.zip   # upstream Project Gold add-on (unmodified)
├── gold_extended/                  # the Blender extension (installable)
│   ├── blender_manifest.toml       # id "gold_extended", Blender ≥ 4.5
│   ├── __init__.py                 # register / unregister
│   ├── props.py                    # Scene settings, add-on preferences
│   ├── operators.py                # create, presets, look/brush, animation tests, grade
│   ├── ui.py                       # N-panel "Gold FX" + Add > Gold FX menu (spec-driven)
│   ├── core/
│   │   ├── nodes.py                # node-tree DSL (operator overloading, version shims, layout)
│   │   ├── params.py               # P / Panel hyper-parameter schema → sockets, UI, presets
│   │   ├── strokes.py              # shared GN groups: Stroke Cards, Stroke Ribbons, Loop Noise, Time, Camera
│   │   ├── shading.py              # Look shader group, materials, look presets
│   │   ├── brushes.py              # built-in brush styles + Brushstroke Tools library bridge
│   │   ├── grade.py                # compositor Scene Grade
│   │   ├── compat.py               # modifier input access across Blender versions
│   │   └── registry.py             # Effect base class, create(), presets, rebuild
│   └── effects/
│       ├── common.py               # time, looping/scrolling noise, cycles, facing, strands, masks
│       ├── particles.py            # Rain · Snow · Sand · Dust · Dirt
│       ├── cloud.py
│       ├── greenery.py             # Grass, Foliage (+ shared wind model)
│       ├── hair.py
│       ├── fire.py
│       └── water.py
├── tests/
│   ├── test_gold_extended.py       # headless test-suite (no pytest needed)
│   ├── render_previews.py          # per-effect stills / looping GIFs / gallery
│   └── render_showcase.py          # look presets, isolated visual features, parameter sweeps
├── scripts/
│   ├── build_extension.py          # zip the extension (fallback for `blender --command extension build`)
│   └── gen_param_docs.py           # regenerate docs/PARAMETERS.md from the specs
└── docs/
    ├── RESEARCH.md  ARCHITECTURE.md  PARAMETERS.md
    └── media/                      # rendered previews
```

## Layers

```
            ┌───────────────────────────── effect module ─────────────────────────────┐
            │  spec: [Panel(P(...), ...)]   presets   variants   materials   build()  │
            └──────┬────────────────────────────┬──────────────────────┬───────────────┘
                   │ params.build_interface     │ registry.apply_preset│ build(tb, P)
                   ▼                            ▼                      ▼
   ui.py draws  ◄── GN group interface   modifier input values   nodes.TreeBuilder DSL
   panels from      (sockets, ranges,                                   │
   the spec         tooltips, panels)                                   ▼
                                                    points / curves + per-point fields
                                                                         │
                                       strokes.ensure_cards / ensure_ribbons
                                                                         ▼
                                   mesh with the brush_stroke.* attribute contract
                                                                         │ Set Material
                                                                         ▼
                        material:  [Brush Style: BSBST-BS.*] ──mask──► [Look group] ──► output
                                    (built-in or Brushstroke Tools library)
                                                                         │
                                         render ──► compositor [Scene Grade group]
```

* **One spec, many consumers.** `params.P` describes a control once (name,
  type, default, range, unit sub-type, tooltip, advanced flag). The same list
  creates the node-group interface, draws the sidebar, validates presets and
  generates `docs/PARAMETERS.md`.
* **Recipes, not .blend files.** Node groups are generated from Python at
  first use, so the repository is diff-able text and the groups are always in
  sync with the code. `Rebuild Node Groups` regenerates them in an existing
  file and re-points modifiers, restoring values by parameter name.
* **Contract boundary.** Effects only produce points/curves + fields; the two
  stroke builders own the brush attribute contract shared with Brushstroke
  Tools.

## Object model

| Host | Created object | Geometry source |
|---|---|---|
| `DOMAIN` (Particles, Cloud, Foliage) | new mesh object at the 3D cursor whose mesh *is* the domain/shape | modifier input geometry |
| `SURFACE` (Grass, Hair, Fire, Water) | new empty-mesh object parented to the selected mesh (or a generated default surface) | `Surface` object input via Object Info |

Effect objects are tagged `goldx_effect` / `goldx_version` / `goldx_preset`;
the modifier is called **Gold FX**. Materials are created per material slot
role and set as *material inputs* of the node group – the object itself has no
material slots (see RESEARCH §2).

## Naming and versioning

| Data-block | Name |
|---|---|
| Effect GN group | `GOLDX <Label> v<version>` (visible in the Add Modifier menu) |
| Shared helpers | `.GOLDX.stroke_cards.v1`, `.GOLDX.stroke_ribbons.v1`, `.GOLDX.loop_noise.v1`, `.GOLDX.time.v1`, `.GOLDX.camera.v1`, `.GOLDX.look.v1`, `.GOLDX.grade.v1` |
| Built-in brush styles | `BSBST-BS.Gold FX.<Type>.<Name>` (base add-on convention) |
| Materials | `GX <Label> · <Role>`, custom props `GOLDX`, `GOLDX_role` |

Changing a recipe in an incompatible way → bump the effect's `version`
(new group name) so existing files keep working.

## Version compatibility

* `core/compat.py` – modifier inputs (`mod[...]` before 5.2,
  `mod.properties.inputs...` from 5.2).
* `TreeBuilder._set_prop` – node *properties* that became *menu sockets* in
  5.x are set through whichever exists.
* `nodes.SOCKET_ALIASES` – sockets renamed between versions
  (`Fac`/`Factor`, `Geometry`/`Mesh`).
* Interface sockets use `structure_type = 'SINGLE'` (5.x) or
  `force_non_field` (4.x).
* `registry.rebuild_group` never mutates a group still used by modifiers
  (crashes 4.5).

Tested on Blender **4.5.15 LTS** and **5.2.3 LTS**.

## Adding an effect

1. Create `gold_extended/effects/my_effect.py`:

```python
from ..core.params import P, Panel
from ..core.registry import Effect, MaterialSlot, Variant, register_effect
from . import common
from .common import rnd


@register_effect
class Bubbles(Effect):
    id = 'BUBBLES'
    label = 'Bubbles'
    icon = 'SHADING_RENDERED'
    category = 'Elements'
    description = 'Rising painterly bubbles'
    host = 'DOMAIN'
    spec = [
        Panel('Bubbles', [
            P('Count', 'INT', 300, 0, 100000, desc='Number of bubbles'),
            P('Seed', 'INT', 0, 0, 100000),
            P('Size', 'FLOAT', 0.05, 0.0, 10.0, 'DISTANCE'),
            P('Rise Speed', 'FLOAT', 0.5, 0.0, 20.0, 'VELOCITY'),
            P('Camera', 'OBJECT'),
        ]),
        common.animation_panel(),
        Panel('Display', [P('Material', 'MATERIAL', hidden=True)], closed=True),
    ]
    materials = [MaterialSlot('Material', 'Bubbles', 'Soft Dab', 'Default', {'Sheen': 0.8, 'Sheer': 0.7})]
    presets = {'Default': {}}
    variants = [Variant('Bubbles', 'Default', 'SHADING_RENDERED', 'Rising bubbles')]

    def build(self, tb, P):
        seed = P['Seed']
        bb = tb.bound_box(P['Geometry'])
        size = bb['Max'] - bb['Min']
        t, loop = common.time(tb, P)
        pts = tb.node('GeometryNodePoints', {'Count': P['Count']}).out
        u, k, per = common.cycle(tb, t, tb.sep(size)[2] / P['Rise Speed'], rnd(tb, seed, 1), loop)
        x = tb.rand('FLOAT', 0, 1, id=tb.index(), seed=seed * 31 + k * 7919)
        y = tb.rand('FLOAT', 0, 1, id=tb.index(), seed=seed * 31 + k * 7919 + 1)
        pos = bb['Min'] + tb.combine(x, y, u) * size
        pts = tb.set_position(pts, pos)
        cam = common.camera_location(tb, P['Camera'])
        return common.cards(tb, {'Points': pts, 'Direction': (0, 0, 1), 'Facing': tb.normalize(cam - pos),
                                 'Width': P['Size'], 'Length': P['Size'], 'Seed': seed,
                                 'Material': P['Material']})
```

2. Import it in `effects/__init__.py`.
3. Run `python tests/test_gold_extended.py` – the generic tests (contract,
   motion, determinism, seamless loops for every preset, UI) cover it
   automatically. Add the id to `EFFECT_IDS` in the test file.
4. `python scripts/gen_param_docs.py` to refresh the reference.

The UI, presets, user presets, loop checker and docs need no extra code.
