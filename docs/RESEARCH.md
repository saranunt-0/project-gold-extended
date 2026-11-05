# Research Notes

How Gold Extended was derived from Project Gold's **Brushstroke Tools** add-on,
how each effect is modelled, how hyper-parameters were mapped to controls,
and what the visual-capability exploration covered.

---

## 1. The base: Brushstroke Tools v1.2.3 (Blender Studio, Project Gold)

Source: `base/add-on-brushstroke-tools-v1.2.3.zip` (GPL-3.0-or-later).

### 1.1 What it is

A Blender 4.2+ extension that paints 3D surfaces with brush strokes. Python
code (`ops.py`, `utils.py`, `settings.py`, `ui.py`, `draw_tool.py`) is a
thin layer; the real work happens in Geometry Nodes groups and materials
stored in binary resources:

| Resource | Content |
|---|---|
| `assets/core/brushstroke_tools-resources.blend` | GN groups `.brushstroke_tools.surface_fill`, `.surface_draw`, `.pre_processing`, `.curves_to_brushstrokes`, `.animation`, …; the **Brush Material**; FX shader groups (`BSBST-FX-canvas/crayon/fade/rake`) |
| `assets/styles/brushstroke_tools-oil_brushes.blend` | Brush styles `BSBST-BS.Oil Paint.<Type>.<Name>` (Feathery, Dry Scrumble, Streaky Dashes, …) using EXR brush scans |

Key mechanisms:

* **Two methods.** *Fill* scatters strokes over a surface following a *flow*
  curves object; *Draw* turns hand-drawn curves into strokes.
* **Preset object + socket "link context".** A hidden preset object holds
  the modifier stack; each modifier socket can be linked to context (surface
  object, flow object, material, UV map, random seed) and copied to new
  layers (`modifier_info` / `socket_info` property groups).
* **Brush styles** are shader node groups named
  `BSBST-BS.<Category>.<Type>.<Name>` returning a mask. Materials pick one by
  replacing the node tree of the node called `Brush Style`.
* **5.2 compatibility** (`geomod.py`): Blender 5.2 moved GeoNodes modifier
  inputs from `mod["Socket_n"]` to `mod.properties.inputs.Socket_n.value`.
* **Render Setup** raises Cycles *transparent bounces* to 256.

### 1.2 The brush-stroke attribute contract (probed)

Nothing documents what the Brush Material expects, so it was reverse
engineered by loading the resources in headless Blender, dumping node trees
and running `.curves_to_brushstrokes` on a test curve:

| Attribute | Domain | Type | Meaning |
|---|---|---|---|
| `brush_stroke.uv` | corner | float2 | x across the stroke 0–1, y along 0–1 |
| `brush_stroke.dimension` | face | vector | (width, length, 0) |
| `brush_stroke.length` | face | float | stroke length |
| `brush_stroke.id` | face | vector | random 0–1 per stroke |
| `brush_stroke.opacity` | face | float | per-stroke opacity |
| `brush_stroke` | face | bool | marks stroke faces |
| `brush_stroke.color` | point | color | paint colour |
| `brush_stroke.normal` | point | vector | shading normal |
| `stroke_index` | face | int | stroke number |
| `opacity` | point | float | read by the Brush Material |

**This is the integration point of the whole project.** Any geometry that
carries these attributes is paintable by every Project Gold brush style –
the oil-paint scans included – so the extension never has to fork the base
add-on. `tests/test_gold_extended.py::test_brush_contract_every_effect`
asserts the contract (names, domains, types) for every effect.

### 1.3 Gaps the extension fills

| Brushstroke Tools | Gold Extended |
|---|---|
| Strokes live *on surfaces* (fill/draw) | Strokes in volumes, on particles, along procedural curves |
| Animation = stroke flicker / deforming surfaces | Procedural motion: falling, wind, licking flames, waves, billowing |
| Raw modifier sockets as UI | Curated, unit-aware hyper-parameters, presets, advanced filter |
| One material model | Look shader with colour, chromatic, light and opacity controls + compositor grade |

---

## 2. Design decisions

**Reuse the contract, not the node groups.** The stroke geometry is built by
two new shared groups – *Stroke Cards* (points → quads) and *Stroke Ribbons*
(curves → strips) – which emit exactly the attributes above. Copying the base
node groups would tie the extension to their internals and socket ids.

**Own Look shader, base brush styles.** Effects need per-stroke emission
(fire), view-dependent transparency (water), brushless surfaces (water body)
and controls exposed on *one* node. The base Brush Material spreads its
settings over ~70 nodes, so a new shader group was written; the brush mask
still comes from any `BSBST-BS.*` style, and the style node keeps the name
`Brush Style`, so the base add-on's brush browser also works on Gold FX
materials. Seven procedural styles (`BSBST-BS.Gold FX.*`) are generated so
the extension works without the base library.

**Stateless, time-driven animation.** Every effect is a pure function of
`(parameters, time)`; no simulation zones or caches.

* scrub anywhere, render frames in any order on any machine;
* deterministic (tested by evaluating, scrubbing back and comparing);
* **seamless loops** become possible (below);
* trade-off: no accumulation or collisions (snow piling up, fire spreading).
  Those would need simulation zones – listed as future work.

**Camera-facing strokes.** A painter shows a stroke broadside. Particles,
puffs, flames and hair face the scene camera (blendable with natural
orientation via *Face Camera*). In the viewport they face the *scene* camera,
not the viewport view – an accepted limitation of Geometry Nodes.

**Materials assigned inside the node tree.** Effect objects carry no
material slots: Geometry Nodes' *Set Material* order differs from slot order,
and pre-made slots are matched by index, which painted the water body with
the stroke material during development (caught by a render, now covered by
`test_material_slots_follow_geometry_nodes`).

### 2.1 Seamless loop mathematics

With `Loop Frames = N` every time-periodic term must have a period that
divides the loop length `L`:

* **Life cycles** (particles, flames, embers, water strokes):
  `c = t / T + phase`, `u = fract(c)`, `k = floor(c)`. `T` is quantised to
  `L / round(L / T)` and the rebirth id `k` is wrapped `k mod n`, so the
  random spawn sequence repeats.
* **Oscillations** (sway, flutter, flicker, spin, wave dispersion): the
  frequency is quantised, `f' = round(f·L) / L`.
* **Evolving noise**: `n(t) = lerp(noise(p, t), noise(p, t − L), t/L)` with
  `t` wrapped to `[0, L)`; both ends evaluate `noise(p, 0)`.
* **Translating noise** (gust fronts, cloud drift): a translating field is
  never periodic, so two copies one loop apart are cross-faded:
  `lerp(N(p − v·t), N(p − v·(t − L)), t/L)`.

`goldx.check_loop` (UI: *Animation Test → Check Loop Seam*) verifies this
numerically by comparing every visible vertex one loop apart at two phase
offsets. Writing that checker found three real bugs during development
(non-quantised spin, a decorrelated sway frequency, drifting cloud noise);
`test_loops_are_seamless` now runs it for **every preset of every effect**.

Quantisation changes speeds slightly – a 6.7 s snow fall period in a 2 s loop
becomes 2 s. Choose loop lengths close to the natural periods.

---

## 3. Effect models and hyper-parameter mapping

Method used for every effect:

1. Write the process as equations in a few physical/visual degrees of freedom.
2. Expose each degree of freedom in **user units** – metres, m/s, Hz,
   seconds, angles, 0–1 factors – with ranges that cover useful looks only.
3. Group controls by the question the artist asks, in a fixed order:
   *Source → Shape → Motion → Stroke → Color → Animation*.
4. Hide fine-tuning knobs behind **Advanced** (74 of them).
5. Store named **presets** as points in that space (38 built in), plus user
   presets saved as JSON.

The full table of 200+ controls is generated into
[`PARAMETERS.md`](PARAMETERS.md) from the code.

### Particles – rain, snow, sand, dust, dirt
`T_i = H / speed_i`; position = spawn + `Wind·age` + turbulence + sway,
wrapped horizontally, optional vortex rotation `Vortex·age` about the domain
axis; card length `= Size·Aspect + |v|·Motion Stretch` (the painter's motion
streak). Rain splashes are spawned at the previous cycle's landing point and
animate radially for `Splash Duration`.
*Main controls:* Count, Size, Fall Speed, Wind, Turbulence, Sway, Vortex,
Motion Stretch, Face Camera. Presets: Rain, Storm, Snow, Blizzard, Sand, Dust
Devil, Dust Motes, Dirt.

### Cloud
Puffs on/under an editable mesh shape, displaced by billow noise and
coloured with `light = wrap(dot(n, sun))`, a height gradient toward the base
colour, and a silver lining `rim = sil² · (0.35 + backlight)`. Puff normals are
written to `brush_stroke.normal` so the Look can light puffs as spheres.
*Main controls:* Density, Puff Size, Billow, Flatten Bottom, Sun, Lit/Shadow/
Base colours, Rim Light, Evolve Speed, Drift, Dissipate.

### Grass
`P(s) = root + n·L·s + (bend + wind)·L·s²` minus a first-order length
correction `|lean|² / (2·L·s)` so bent blades don't stretch. Wind = travelling
gust noise + flutter. Growth masked by any vertex group / attribute and by
slope.
*Main controls:* Density, Length, Width, Taper, Bend, Wind Strength,
Wind Direction, Root/Tip/Dry colours, Dry Patches.

### Foliage
Leaf cards on/inside a canopy mesh, lit like clouds with interior
darkening, seasonal accent patches, wind sway weighted by height, and leaf
flutter rotation.

### Hair
`dir0 = normalize(lerp(n, comb_tangent, Comb))`,
`P(s) = root + dir0·L·s − ẑ·Gravity·L·s² + curl(s)`. **Clumping**: each strand
is pulled toward the strand of its nearest clump leader by
`Clumping · s^ClumpShape` – the step that turns fur into painted locks. Can
restyle an existing hair *Curves* object instead of generating strands.

### Fire
Tongues: `env = sin(πu)^0.6` growth/decay, upward-scrolling turbulence
driven by the tongue's *age* (loop-safe), colour core→mid→tip cooling with
age, per-point `gx_emit`. Embers rise, swirl and flicker; smoke puffs are born
above the flames, grow and fade. Three materials (Flames, Embers, Smoke).

### Water
Three Gerstner-style wave trains with deep-water dispersion
`ω = √(g·k)` (long waves travel faster), analytic slope normals, ripple
noise. Flow strokes lie on the displaced surface and live short lives;
foam appears where height exceeds a crest threshold; sparkles appear where
`dot(reflect(−sun, n), view)^sharpness` is high. An optional subdivided,
displaced water body gives the painted base colour.

---

## 4. Visual capabilities explored

Two layers: **per-stroke** controls in the material Look (they know the
stroke's UV, id and normal) and **per-image** controls in the compositor
(they need the final frame). See `docs/media/visual_features.png` for each
control isolated and `docs/media/look_presets.png` for the presets.

| Capability | Where | How |
|---|---|---|
| **Vibrance** | Look + Grade | `s' = s·(1 + v·(1 − s))`: boosts muted colours more than saturated ones; negative values mute selectively |
| Saturation / Hue / Brightness / Contrast | Look + Grade | HSV pipeline + Bright/Contrast |
| **Chromatic fringe** | Look | Lateral aberration *per stroke*: the two stroke edges get opposite hue shifts (`Fringe · edge · (2u − 1) · Fringe Hue`) plus a saturation boost in the edge band – prismatic paint edges |
| **Chromatic aberration** | Grade | Real lens dispersion (Lens Distortion node): RGB split toward the frame edges |
| **Iridescence** | Look | Thin-film style hue cycling with the facing ratio |
| **Sheen** | Look | Principled sheen + NPR rim `smoothstep(1 − falloff, 1, facing)` in a tint colour – hair, silk, water |
| **Sheer** | Look | View-dependent transparency: see-through facing the camera, denser at grazing angles (chiffon, water film) |
| Edge Darken | Look | Watercolour pigment pooling `4a(1 − a)` at the mask edge |
| Dry Brush | Look | Grain noise thresholded against the mask |
| Posterize | Look | Value quantised into N bands (gouache/cel) |
| Color Jitter | Look | Per-stroke HSV variation from `brush_stroke.id` |
| Emission / Translucency / Gloss | Look | Fire & neon, leaves & clouds, wet paint |
| Bloom, Vignette | Grade | Glare (Bloom), resolution-independent radial vignette |

"Sheer" in the brief was ambiguous, so both readings are implemented:
*Sheen* (glossy rim light) and *Sheer* (view-dependent see-through).

---

## 5. Validation

* `tests/test_gold_extended.py` – 18 tests, **all passing on Blender
  4.5.15 LTS and 5.2.3 LTS** (headless `bpy` module): registration,
  spec/preset consistency (every preset key is a real parameter / look input
  / brush), brush contract per effect, motion + determinism, seamless loops
  for all 38 presets, masks/slope, material assignment, operators (presets,
  user presets, seed, loop check, look/brush switching, rebuild keeps values),
  scene grade graph, base library bridge with the real oil-paint styles, UI
  draw validation against RNA, Cycles render smoke test.
* The built zip passes Blender's own `extension validate`, installs into a
  clean profile as `bl_ext.user_default.gold_extended` and runs.
* Performance with default settings (Blender 5.2, 4-core cloud VM, measured
  while other renders shared the CPU – treat as upper bounds). Node groups are
  built once per file; evaluation is per frame change:

  | Effect | Build group | Per frame | Faces |
  |---|---|---|---|
  | Particles (Rain) | 1.2 s | 124 ms | 7.7 k |
  | Cloud | 0.8 s | 9 ms | 0.3 k |
  | Grass | 0.6 s | 376 ms | 54 k |
  | Foliage | 1.0 s | 14 ms | 0.9 k |
  | Hair | 1.7 s | 71 ms | 15.6 k |
  | Fire | 1.2 s | 14 ms | 0.4 k |
  | Water | 4.4 s | 48 ms | 8.7 k |

  Grass and particle counts are the main cost; lower *Density*/*Count* (or
  *Resolution*) while blocking out, raise for final renders.

**Not verified here:** EEVEE (the test machine has software GL only) – the
materials use standard nodes and dithered transparency and should work, but
look tuning was done in Cycles. The Scene Grade compositor path for 4.5 was
only graph-tested; rendering it was tested on 5.2.
