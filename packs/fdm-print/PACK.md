# fdm-print

Filament printability. Seven gates: five that cost nothing and run on every edit,
two that read the mesh.

## What this pack settles

- **Does it fit the machine**, with the brim on it, in either XY orientation, and
  under the Z travel.
- **Is every section thick enough to print reliably** — three perimeters at the
  nozzle you are actually using.
- **Will it need support**, how much of the part is involved, and how bad the worst
  face is.
- **Will the unsupported horizontal spans bridge**, or do they need a chamfer, a
  split, or support — and **is it a bridge at all**, because a ceiling held on one
  side is a cantilever and gets a limit more than ten times smaller.
- **Is the primary load carried across the layer bonds** — the failure a structural
  pack cannot see, because a structural pack computes with bulk properties and a
  printed part is not a bulk material.
- **Roughly how long it will take and how much filament it will eat**, to an order
  of magnitude, against a time ceiling *and* a one-spool mass ceiling.
- **Is the mesh a solid at all** — both mesh gates refuse a mesh that is not
  watertight or is wound inside out, because every face normal in it is a fiction
  and so is every number read off one.
- **Whether the pack's own rules still apply** — `fdm.process_model_valid` decides
  whether the other six are entitled to an opinion at all.

## What it does NOT settle

Read this section before you trust a green sweep from this pack.

- **It is not a slicer.** No gate here runs the actual toolpath. A part can pass
  every gate and still fail in the slicer on a thin-wall gap-fill artifact, a
  seam placement, or a cooling conflict between two islands.
- **It says nothing about dimensional accuracy.** Holes print undersize, outer
  dimensions print oversize, and both depend on the machine, the material and the
  flow calibration. If a feature has a tolerance, that is a *physical* claim
  settled with calipers on a real print, not here. See `sourcing.md` for what to
  expect per material.
- **It does not check that supports can be removed.** A steep face inside a closed
  pocket passes `fdm.overhang` and traps its support permanently. That is a review
  question — see `lenses.md`.
- **It does not check bed adhesion or warp.** A 200 mm flat ABS part fits the bed,
  clears every wall rule, and still lifts its corners. Warp is a function of
  material, footprint area, enclosure and cooling; the pack carries the knowledge
  in `sourcing.md` and the questions in `lenses.md`, but has no gate for it.
- **`fdm.layer_alignment` is a screen, not a strength calculation.** It derates a
  utilisation somebody else computed. It cannot tell you the part is strong enough;
  it can tell you the orientation makes that number meaningless.
- **`fdm.print_time_est` is an estimate.** Expect ±30% against a real slicer and
  worse on small, tall or many-island parts. It exists to catch the three-day print
  and the part that will not fit on one spool — it now has a threshold for both,
  but a mass that clears `max_filament_g` is still an estimate, not a weighed spool.
- **`fdm.layer_alignment` is optimistic through the middle of its range.** The
  ``1 - (1-r)·sin²φ`` interpolation agrees with Hankinson at 0° and 90° and sits
  9–13% above it between; a part that only just passes at φ ≈ 45° has not been
  proven. The reasoning and the numbers are in `_directional_knockdown`.
- **Mesh solidity is checked, mesh *quality* is not.** The gates refuse a mesh that
  is not watertight or is wound inside out. They say nothing about sliver triangles,
  a tessellation too coarse to represent the real chamfer angle, or a mesh that is
  watertight and still self-intersecting in a way `is_watertight` does not see.
- **It does not decide the print orientation.** Everything here measures the part
  *in the orientation it was handed*. Re-orienting changes the overhang, bridge,
  strength and time answers at once, and choosing between those is a design
  decision — `references/orientation.md` is the guidance, not a gate.
- **`min_wall` does not know whether a thin section matters.** It settles wall
  thickness, not minimum feature size: a 1 mm cosmetic fin and a 1 mm load path
  fail it identically.
- **A cantilever allowance is a rule of thumb, not a sag calculation.** The gate
  separates a cantilever from a bridge and compares it to `max_cantilever_mm`; it
  does not compute how far the strand actually droops for your material, cooling
  and layer time.
- **Nothing here covers resin, SLS, or any other additive process.** The physics of
  a layer bond is specific to extruded filament.

## Gates

| id | tier | measures | fails when | control |
|---|---|---|---|---|
| `fdm.process_model_valid` | 0 | units (absolute extent, volume vs its own bbox, thinnest section vs one bead), nozzle range, layer/nozzle and width/nozzle ratios | any assumption the other gates stand on has stopped holding | `metres_not_millimetres` — every length, area and volume in the projection divided by 1000 to the right power |
| `fdm.bed_fit` | 0 | footprint / (bed − 2× brim), and height / Z | utilisation > 1.0 | `brim_overflow` — a footprint sized halfway between the brimmed area and the raw bed, from the projection's own brim |
| `fdm.min_wall` | 0 | thinnest section vs 3 perimeters at the line width | section < minimum | `two_perimeter_wall` — the section cut to two beads of the width the project actually uses |
| `fdm.layer_alignment` | 0 | utilisation derated by the layer-normal knockdown, strength or modulus per `utilisation_kind` | derated utilisation > 1.0 | `load_across_layers` — load rotated onto the build axis with the utilisation set 15% past the knockdown |
| `fdm.print_time_est` | 0 | estimated hours and grams | hours > `max_print_time_h` **or** grams > `max_filament_g` | `crawling_speed` — the speed, solved from the gate's own model, that lands the part 15% past the project's time ceiling |
| `fdm.overhang` | 1 | area past the overhang limit, as a fraction of surface | fraction > allowance; mesh not a solid; `overhang_limit_deg` ≥ `bridge_ceiling_deg` | `steep_cone` — a cone stood on its apex, 70° half angle |
| `fdm.bridge_span` | 1 | longest unsupported horizontal span, per ceiling region, classified bridge / cantilever / unanchored | span > `max_bridge_mm` (bridge), > `max_cantilever_mm` (cantilever), any span at all (unanchored); mesh not a solid | `long_bridge` — an arch whose ceiling spans 3× the limit between two real anchors |

Thresholds and their provenance live inline in `gates/printability.py` and
`gates/mesh.py` as module constants with docstrings — the brim allowance, the
three-perimeter rule, the 45° limit, the 0.5× layer-normal ratio, the duty factor.
Every one of them is overridable from the projection, and every verdict prints the
value it actually used.

`fdm.overhang` and `fdm.bridge_span` need `trimesh` and `numpy`. Both are declared,
both are imported lazily inside the gate bodies, and when they are missing the two
gates report SKIPPED with the module named and their claims resolve BLOCKED. They
never fall back to a cheaper approximation. A pack that quietly downgrades turns
"we did not check this" into "this is fine".

## Units and frames

Everything is **millimetres, degrees, grams, seconds**. Volume is mm³, area mm²,
density g/cm³, speed mm/s, time hours in the verdict and seconds internally.

The mesh is read **in its print orientation**: the model exports the part the way
it will sit on the bed. The build direction is `build_axis` in the projection and
defaults to `[0, 0, 1]`. Every angle is measured against it, so a project that
prints along another axis gets the right answer without re-exporting.

**Overhang angle** is inclination away from the build direction: a vertical wall is
0°, a 45° chamfer underside is 45°, a flat ceiling is 90°. This is the number a
slicer's support threshold refers to. `fdm.layer_alignment` uses a different angle —
`phi`, between the load and the **layer plane** — where 0° is in-plane (good) and
90° is layer-normal (bad). The two are complements; do not mix them up.

## The physics in one paragraph

A filament part is a stack of welded beads, not a solid. Within a layer the
material is continuous and close to the coupon strength the datasheet quotes.
Between layers it is a weld made by a bead of hot plastic re-melting the top of the
one below, and that weld is worth roughly half the bead — less if the part is cold,
fast or well cooled. Geometry follows from the same fact: each layer must land on
something, so a face that leans more than about 45° from vertical has half a bead
hanging in air and needs support; a face that is horizontal is not leaning at all
and gets bridged instead, which works up to the span where the extruded strand sags
before it cools. Wall thickness is quantised by the nozzle, because a wall is a
whole number of beads and the slicer fills what is left over with something that is
not structure. And the part is glued to the bed by the first layer alone, so a large
flat footprint in a material that shrinks on cooling is a lever trying to peel
itself off.

If a result here looks absurd, check these: `fdm.overhang` reporting **0.0°** on a
part that visibly has overhangs means the mesh is inside out — an inverted mesh
produces *zero* overhang, not 90°, because every normal is mirrored (the gate now
refuses such a mesh outright rather than reporting the 0.0°); a bed utilisation
near 0.02 usually means the model is in metres or inches; a print time under a
minute usually means `volume_mm3` is actually cm³.

## Common failure modes and what they look like

- **"worst util 1.02 in XY"** from `fdm.bed_fit` — the part fits the bed and not the
  brim. Shrink it, drop the brim and accept the lift risk, or print it diagonally
  (which this gate does not model — it only tries the two square rotations).
- **"2.1 beads"** from `fdm.min_wall` — a wall that will be printed as two
  perimeters with gap fill between them. It prints; it splits in service.
- **"51% of surface"** from `fdm.overhang` — this is not a nub, it is the part. Do
  not reach for support settings; reorient it or add a chamfer.
- **"UNANCHORED"** from `fdm.bridge_span` — a ceiling with nothing under either end.
  No bridge length saves it; it needs support or a different orientation.
- **"CANTILEVER, 1 anchored edge(s) all to one side"** from `fdm.bridge_span` — a
  shelf projecting into air off a single wall. It is not a bridge of twice the
  length: there is no second landing to pull the strand taut, so it droops from the
  first pass. Chamfer the underside to 45°, add a rib down to material below, or
  support it.
- **"is not watertight" / "wound inside out"** from either mesh gate — the export is
  broken, not the design. Every face normal in that mesh is a fiction, so no
  overhang or bridge number could be produced from it. Repair and re-export.
- **"INERT CONFIGURATION"** from `fdm.overhang` — `overhang_limit_deg` was set at or
  above `bridge_ceiling_deg`, which hands every face the gate could fail on to
  `fdm.bridge_span` and leaves nothing for it to measure.
- **"utilisation 0.70 / knockdown 0.50 = 1.40"** from `fdm.layer_alignment` — the
  structural gate passed on bulk properties and the part will snap along a layer.
  Rotating the part is usually free; thickening it is not.
- **A SKIPPED mesh gate with `trimesh` in the reason** — the claim is BLOCKED, not
  passed. Install the dependency or leave the row visibly open.

## Where to look next

- `selftest/baseline.json` — a worked projection of a part that passes every gate
  here, with a one-line note on each key and its unit. It is the fastest way to
  learn what this pack expects a model to project, and it is what the negative
  controls are measured against: each fixture moves one number in it and the gate
  under test flips to FAIL. `selftest/baseline_mesh.py` is the source of the solid
  it points at.
- `references/orientation.md` — how to choose the print orientation, and why it is
  the single decision that moves strength, finish, support and time at once.
- `references/geometry_rules.md` — the numeric rules of thumb: holes, threads,
  clearances, text, chamfer-instead-of-support, and the parameters this pack reads.
- `sourcing.md` — filament by material: temperatures, warp, UV and moisture,
  achievable tolerance, and which ones actually survive outdoors.
- `lenses.md` — the adversarial review dimensions to attack the design from before
  anything is printed.
