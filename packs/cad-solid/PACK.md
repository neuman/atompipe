# cad-solid

Solid-geometry validation for exported mechanical parts. It answers two questions:
**is this file actually a solid**, and **do the placed solids share material**.
**Everything here is about the ASSEMBLY: solids already placed in the assembly
frame, and an envelope that is the assembled product's, not any one part's.** That
is the opposite of what `fdm-print` means by the same words — it judges ONE PART in
its print orientation — so the two packs' keys are named for the object they
describe: `assembly_bbox_mm` here, `part_bbox_mm` there. See
[Keys, frames and resolution order](#keys-frames-and-resolution-order).

Everything in here runs on a triangle mesh. That is a deliberate choice — the mesh
is the representation every downstream process actually consumes (slicer, mesher,
renderer, viewer, quoting tool), so it is the representation worth checking. It is
also the representation where a part the CAD kernel calls valid stops being valid.

## What this pack settles

| Claim, in plain language | Gate |
|---|---|
| "the exported part is closed — no holes, no doubled surfaces" | `cad.watertight` |
| "the part is a solid a boolean can operate on" | `cad.is_volume` |
| "the tessellation has no duplicate vertices or zero-area triangles" | `cad.degenerate_faces` |
| "no two placed parts share material" | `cad.clash` |
| "the part fits its envelope and balances where it should" | `cad.bounding` |
| "no wall is thinner than the process allows" | `cad.wall_thickness` |

## What this pack CANNOT settle

Read this section before the gate list. It names what a reader will otherwise
assume, and the assumptions are expensive.

- **It cannot tell you the model is right.** Every gate here checks a mesh against
  a rule. A part that is watertight, valid, clash-free and correctly sized can still
  be the wrong part.
- **`cad.bounding` does not open the geometry.** It is arithmetic on numbers the
  projection supplies. If `assembly_bbox_mm` was written by hand, or was computed before the
  last model change, this gate will cheerfully certify a stale number. Proving the
  projection still agrees with the exported mesh is a *cross-representation* claim
  (method rule 6) and needs its own gate.
- **`cad.clash` checks ONE POSE.** A mechanism that clears at the pose you exported
  can jam at full travel. Sweeping is `references/travel_sweeps.md`, and it is a
  project's job to export the poses.
- **`cad.clash` does not measure clearance.** It reports shared material. Two parts
  0.01 mm apart and two parts 8 mm apart are both "clear". A minimum-gap claim
  needs a distance query, which this pack does not ship.
- **`cad.clash` does not say that two parts touching is wrong** — and it will not be
  talked into it by a boolean kernel. A pair whose bounding boxes meet without
  overlapping on some axis is reported as `contact`, not as a clash, and no boolean
  is run on it: two solids can only share material inside the intersection of their
  bounding boxes, so a degenerate box holds none and there is nothing to measure.
  That inequality is exact, which is why this can never hide an overlap — a pair
  sharing any volume has a positive overlap on all three axes and reaches the
  kernel. What it *does* rule out is the failure that cost a reader an afternoon:
  `worst reported 31277.200 mm³ ... inf mm equivalent depth over 0.00 mm²` on a
  bulkhead and a deck panel that shared one face exactly. Every digit of that was a
  kernel shrugging at a coplanar contact, and the gate printed it as a headline.
- **`cad.clash`'s volume tolerances have a size regime, and its depth tolerances are
  what make the verdict scale-free.** A volume tolerance forgives a fixed volume, so
  on its own it forgives a penetration *depth* that grows without bound as the
  contact area shrinks: at 0.2 mm³ a 0.5 mm pin may be driven 0.79 mm into a block —
  deeper than the pin is wide — and still read as clear. So every pair is checked on
  BOTH the shared volume and an equivalent depth (shared volume over the largest face
  of the two parts' overlapping bounding boxes), and either one over tolerance is an
  interference. Read the two numbers together: the 3 mm³ organic tolerance was
  calibrated on a part of ordinary size, roughly 100 mm across, at default export
  settings, and on a part an order of magnitude larger the mating area grows with it
  and that volume is too small. The depth figure does not move with part size, which
  is why it is the one to trust on a slender contact. The depth is a *lower* bound on
  the real penetration — a pair that fails it is at least that far in; a pair that
  passes it may still be deeper than the number says on a contact patch much smaller
  than the AABB overlap.
- **`cad.clash` needs a boolean engine that is not shipped with trimesh.** trimesh
  implements no booleans of its own and declares none of manifold3d, Blender or
  OpenSCAD as a dependency. With none of them installed the gate reports **SKIPPED**
  and names what it looked for. It does not report interference: a missing kernel is
  a missing tool, never a verdict about the design.
- **`cad.wall_thickness` is a sampler, not a proof.** It casts rays from facet
  centroids along facet normals. A thin region whose thinnest direction is normal to
  no sampled facet is missed, and a coarsely tessellated curve **under**-reports by
  about `t*(1 - cos(pi/N))` for a wall of thickness `t` across an N-sided
  tessellation — 1.9% of the wall at N=16, 7.6% at N=8 — because the ray leaves one
  chord, which sits inside the true surface, and lands on another. That direction is
  conservative (false alarms, never false passes) but it is a real number if you are
  calibrating margin off it. The one mechanism that over-reports is different and
  should not be conflated with it: facet-normal obliquity on an irregular
  tessellation, where a ray that does not point at the opposing surface travels
  further than the wall is thick. Treat a pass as "nothing found", never as
  "nothing there".
- **`cad.degenerate_faces` is not a sliver-quality check.** It finds duplicate
  vertices and numerically zero-area triangles. A 1e-6 mm² needle with a 10,000:1
  aspect ratio passes every gate here and will still wreck a mesher.
- **On an STL it cannot find duplicate vertices.** STL stores a bag of independent
  triangles with no vertex identity at all, so the pack welds a `.stl` once at
  1e-4 mm on load to give it a topology, says so in every verdict that depends on
  topology, and `cad.degenerate_faces` then reports only what survives that weld
  (zero-area faces, including ones the weld exposes). Duplicate-vertex detection is
  only meaningful on a format that carries vertex identity — 3MF, PLY, OBJ, glTF.
- **No self-intersection test.** trimesh's `is_volume` catches winding and closure;
  a surface that passes through itself while remaining closed and consistently
  wound is not detected. That needs a dedicated self-intersection pass.
- **Nothing here is a stress, thermal, or tolerance-stack analysis.** A clash gate
  at nominal dimensions says nothing about the same assembly at the extremes of its
  tolerance band — see `lenses.md`.
- **Nothing here knows about a kernel's healing tolerance.** If the CAD system
  inflated a vertex tolerance to close a boolean, the mesh you export is valid,
  watertight, and geometrically wrong. Read `references/tolerance_healing.md`.

## Gates

| Gate | Tier | Measures | Limit from | Known-bad fixture |
|---|---|---|---|---|
| `cad.bounding` | 0 | worst of assembly bbox / volume / CoM utilisation | the model's own `*_limit_*` params | `selftest/bad_bounds.py:tall_part` — 15% over the Z envelope, nothing else changed |
| `cad.watertight` | 1 | open + non-manifold edges | 0, by definition of a solid | `selftest/bad_meshes.py:holed_box` — +Z facet deleted, 4 open edges |
| `cad.is_volume` | 1 | parts that are not volumes | 0, by definition | `selftest/bad_meshes.py:flipped_facet` — one triangle wound backwards, still watertight |
| `cad.degenerate_faces` | 1 | repairs needed (welds + drops) | 0 | `selftest/bad_meshes.py:sliver_pair` — one corner of a closed box emitted twice 1e-6 mm apart, a subset of its faces repointed at the copy, one face spanning the two |
| `cad.wall_thickness` | 1 | thinnest sampled wall, mm | `process_min_wall_mm` (or `min_wall_mm`) in the projection | `selftest/bad_meshes.py:thin_plate` — a plate at a quarter of that limit |
| `cad.clash` | 1 | interfering pairs | 0 pairs; per-pair volume **and** depth tolerance | `selftest/bad_meshes.py:overlapping_pair` — two valid boxes sharing 800 mm³ |

`cad.clash` is the one gate here whose other direction needs proving too. A negative
control can only require a FAILURE, and half of this gate's job is to come out clear
on a pair that *touches* — without anyone writing an allowlist entry for it. A gate
hardened against false negatives loses that quietly, and the symptom is a page of red
on a correctly built assembly, which is the moment somebody reaches for a wildcard.
So the pack ships four more fixtures and a script that asserts the whole matrix:

```
python3 packs/cad-solid/selftest/check_clash_contact.py
```

| Fixture | Must |
|---|---|
| `bad_meshes.py:coplanar_touch_pair` | **PASS** — two boxes sharing one face exactly, no allowlist entry |
| `bad_meshes.py:overlapping_pair` | FAIL — the same boxes 2 mm into each other |
| `bad_meshes.py:bonded_over_interference` | FAIL — that 2 mm overlap with a well-formed `bonded_joints` entry over it |
| `bad_meshes.py:bonded_wildcard` | FAIL — `"block_a"` vs `"*"`, on the declaration, with nothing wrong in the geometry |
| `bad_meshes.py:bonded_sliding_fit` | FAIL — the baseline's own sliding pair declared bonded |

The script also checks the pair that decides whether `bonded_joints` is honest at
all: a 0.01 mm overlap over a 20 × 20 mm face is 4 mm³, twenty times the prismatic
volume tolerance and a fifth of the bonded depth tolerance. It must **fail
undeclared and pass declared** — the first half proves the declaration is doing
something, the second proves it is doing the right thing. It reports NOT EXERCISED,
never a pass, on a machine with no boolean engine.

`cad.wall_thickness` casts its own rays. trimesh's ray engines are not dependencies
of trimesh: the pure-python one culls candidates with an `rtree` index and the fast
one needs an embree binding, so on a machine carrying only what this gate declares
(`trimesh`, `numpy`) `mesh.ray` raises `ModuleNotFoundError` from inside a property
and the gate CRASHES. A crash settles nothing and reads as "the design is wrong"
rather than "the tool is missing", so the gate uses an accelerated engine when one
is importable and otherwise falls back to its own vectorised Möller-Trumbore cast —
the same intersection test, brute-forced over the whole face list instead of culled
by a spatial index, which is why the accelerated engine is still preferred when it
is present.

Do not read "fallback" as "degraded", and do not read it as "identical" either.
**Which caster ran is a fact about the machine, not about the model**: the two agree
to float round-off on the hits they both find, and neither approximates the other's
geometry, but they are two implementations with two sets of edge-case rules (grazing
facets, coincident surfaces, a ray starting exactly on a face). That equivalence is
measured rather than asserted — `selftest/check_ray_cast.py` asserts scale
invariance over five orders of magnitude, span independence (the same shell measured
alone and inside a 200 m assembly), and, where an accelerated engine is installed,
agreement between the two. Run it after touching either path:

```
python3 packs/cad-solid/selftest/check_ray_cast.py
```

It reports the engine comparison as NOT EXERCISED, never as a pass, on a machine
with no accelerated engine — an untested equivalence is an assumption.

`cad.bounding` is the tier-0 gate and the only one that runs with no mesh library
present. Everything else declares `requires_python: ["trimesh", "numpy"]`, so on a
machine without them those gates report **SKIPPED** and their claims resolve
**BLOCKED**. That is the intended behaviour, not a degradation: a geometry check
that quietly passes because its library is missing is the exact failure this whole
system exists to prevent.

`cad.clash` needs one more thing that the manifest cannot express. trimesh dispatches
booleans to **manifold3d**, a **headless Blender**, or **OpenSCAD**, and declares none
of them as a dependency — the gate needs any ONE of the three, while `requires_python`
and `requires_tools` and their gate-level equivalents are checked as an AND. So the
disjunction is probed inside the gate, once, before any pair is touched, and an empty
result is a SKIP naming all three. `pip install manifold3d` is the cheapest of them
and the only one that is a wheel. Nothing about a machine's kernel inventory is ever
allowed to reach a verdict about the design.

### Order matters

The registration order is the sweep order: `bounding`, `watertight`, `is_volume`,
`degenerate_faces`, `wall_thickness`, `clash`. The three validity gates come before
the two measurement gates because **a non-watertight mesh poisons everything
downstream**. A boolean against a leaking mesh can return an empty intersection
without raising — so a corrupt part reads as colliding with nothing, which is the
most dangerous available false negative because it is the answer everyone wanted.
If `cad.watertight` fails, treat every later verdict on that part as void.

## Views, and the node names that are an interface

| View | Kind | Asset | Built from | Addressed by |
|---|---|---|---|---|
| `assembly` | `model3d` | `assets/assembly.glb` + explode manifest | the same mesh map the gates read | node name, or mover name |

`views/assembly.py` exports every placed solid into one GLB, **in the model frame,
untransformed**: no recentring, no Z-up/Y-up rebasing, no node matrices. A
millimetre in the projection is a millimetre in the GLB, which is what lets
`cad.wall_thickness` pin the thin spot at the coordinates it measured it at. It
returns `None` — not an error, not an empty view — when the projection carries no
meshes.

### The node naming scheme

```
part "guide roller"  ->  mover "guide_roller"  ->  node "guide_roller__0"
                                                        ^part^   ^body^
```

- **A node is `<part>__<body>`**, one per solid body, numbered from 0 in sorted
  order. A part that is one solid today and two after somebody splits it for
  printing keeps its name and its locators; only the body count changes.
- **A mover is the part** — everything before `__`. `atompipe.site.derive_explode`
  groups nodes by that prefix, so all of a part's bodies travel together, and the
  site accepts a mover name as a locator target.
- **Part names are sanitised** to letters, digits, `-`, `.` and `_`, with runs of
  `_` collapsed. The collapse is load-bearing: `__` is the mover separator, so a
  part called `lid  left` would otherwise become a *body of the mover* `lid`,
  silently merging two parts into one exploded group. A collision after
  sanitisation takes a visible `-2` suffix rather than sharing a node.
- Both sides compute this from `cad_solid_parts.py`, never from two copies of the
  convention. **This is an interface**: change it there or not at all.

### What each gate pins, and what it refuses to pin

| Gate | Locator | Why that and not more |
|---|---|---|
| `cad.clash` | two per interfering pair — each part, labelled with the shared volume, the equivalent depth and the *other* part | the pair is what interferes; pinning one of the two leaves the part that usually moves dark |
| `cad.watertight` | the parts with open or non-manifold edges, worst first | it knows which part leaks; the edge indices it counted are not a position |
| `cad.is_volume` | the parts that are not volumes, labelled with *why* | "winding inconsistent" and "volume ≤ 0, inside-out" send you to two different fixes |
| `cad.degenerate_faces` | the parts needing repairs, worst first | same: duplicate vertices and needle triangles are fixed at different points in the export chain |
| `cad.wall_thickness` | one `point` at the thin spot, in model coordinates | the sampler genuinely knows where the thinnest ray started. Only the worst one: pinning runners-up would suggest a thickness map this gate did not produce |
| `cad.bounding` | none | the envelope is a property of the whole assembly; there is no part to blame |
| `cad.clash`, allowlist refused | none | that failure is about the allowlist *document*. Pinning the parts an unusable entry names would light up two parts that may fit perfectly |

At most twelve pins per verdict — so at most six interfering pairs, since a pair
takes two. The count in `detail` is always the real one —
the cap trims the drawing, never the measurement — because a model exported at the
wrong scale clashes on every pair at once, and a hundred pins is a red model rather
than a finding.

Where a gate does not know, it attaches nothing and the site says the verdict has
no anchor. A confident highlight on the wrong part is worse than no highlight: it
sends someone to inspect a part that is fine, and the second time that happens they
stop trusting the overlay.

`site/explode.json` is read by this viewgen and merged per mover over the derived
manifest. A file that will not parse, or an override naming a mover that no longer
exists, costs the override and never the model — the problem lands in the view's
`meta` instead, because somebody hand-wrote that file and the one thing they must
not get is a missing model with no explanation.

## What the projection must provide

```python
params = {
    # every mesh gate
    "meshes": {"housing": "build/housing.stl", "lid": "build/lid.stl"},   # or trimesh objects
    # cad.bounding (tier 0) - the ASSEMBLY's envelope, not a part's
    "assembly_bbox_mm": [78.0, 52.0, 23.5],
    "assembly_bbox_limit_mm": [80.0, 60.0, 25.0],
    "assembly_volume_mm3": 41200.0,
    "assembly_volume_limit_mm3": 60000.0,                            # optional
    "assembly_com_mm": [39.0, 26.0, 9.2],
    "assembly_com_target_mm": [39.0, 26.0, 9.0],
    "assembly_com_tol_mm": 1.5,                                      # optional
    # cad.wall_thickness - the thinnest wall the PROCESS allows, a limit
    "process_min_wall_mm": 1.2,
    "wall_samples": 4000,                                            # optional
    # cad.clash
    "clash_tolerance_mm3": 0.2,                                      # optional override
    "clash_tolerances_mm3": {"housing|lid": 3.0},                    # optional, per pair
    "clash_depth_tol_mm": 0.01,                                      # optional override
    "clash_depth_tols_mm": {"housing|lid": 0.05},                    # optional, per pair
    "organic_parts": ["grip"],                                       # optional
    "sliding_fits": [["rail", "carriage"]],                          # optional
    "clash_allow": [{"pair": ["housing", "lid"], "reason": "0.1 mm press fit, intended"}],
    "bonded_joints": [{"pair": ["girder", "floor"],                  # optional
                       "reason": "epoxy fillet down both sides of the girder foot"}],
}
```

Everything is loaded **unprocessed**: the default load pipeline in most mesh
libraries welds vertices and drops degenerate faces on the way in, which would
repair the defects these gates exist to report and certify a file no other program
reads the same way. The one exception is a soup format (`.stl`), which has no vertex
identity to preserve — see "cannot settle" above.

`meshes` is also read from `solids` or `parts`, and a bare list of paths is accepted
(names come from the filenames). When no geometry is found, the mesh gates SKIP and
say which keys they looked for. **They never guess a filename**, because a gate that
guesses is a gate that can check the wrong file and pass.

The same refusal applies to geometry written short. `assembly_bbox_mm`,
`assembly_com_mm` and `assembly_com_target_mm` are *measurements* and must be 3-lists — a single number there is not
a compact spelling, it is two missing axes, and expanding it into a cube would hand
back a confident PASS on a Y and Z the gate invented. `cad.bounding` SKIPS and names
the key instead. `assembly_bbox_limit_mm` is the one place a scalar is accepted, because "the
same in every axis" is a real envelope somebody might mean. `wall_samples`, likewise,
must be a positive integer if it is present at all: `0` used to become the default
4000, and a projection that asks for no sampling should be told it will get none, not
quietly given the maximum.

## The known-good baseline

`selftest/baseline.json` is this pack's own **known-good projection**: a complete,
physically coherent assembly on which every gate in the pack must PASS. It exists so
that each negative control means something. A control is only readable as "the
fixture changed one thing and the gate flipped" if there is a baseline the gate
demonstrably passes; without one, a control that fails proves the gate dislikes its
fixture, which is a much weaker statement.

The object is a generic sealed equipment enclosure in one alloy — a die-cast
open-top housing with 3 mm walls, a bolted 4 mm cover plate, a carriage that slides
along X on 0.4 mm running clearance, and a turned guide roller resting on the cavity
floor. It is deliberately not minimal: it carries a real wall thickness, a real
intended face contact (`clash_allow`), a real sliding fit (`sliding_fits`, which both
the allowlist and the bonded declaration must refuse to cover) and one curved part
(`organic_parts`), so every key the gates read has a value a practitioner would
recognise rather than a placeholder. The `_notes` block in the file names each key
and its unit. `bonded_joints` is present and **empty**: this enclosure is bolted, not
bonded, and a declaration invented for a joint that does not exist is how a
mechanism stops meaning anything. The bonded paths are exercised by the three
fixtures above instead, on geometry built for them.

Geometry and numbers come from one place. `selftest/make_baseline_meshes.py` builds
the four solids as explicit vertex/face lists — never by a boolean, because a
boolean kernel is entitled to emit slivers and a sliver in the KNOWN-GOOD fixture
would fail `cad.degenerate_faces` for a reason that has nothing to do with the
design — exports them to `selftest/meshes/*.stl`, and then CHECKS the bounding box,
volume and centre of mass stated in `baseline.json` against the solids it just
wrote. Run it after any change to either:

```
python3 packs/cad-solid/selftest/make_baseline_meshes.py
```

It exits non-zero and names the drift if the projection and the geometry have come
apart. STL is deliberate: it is the soup format the pack has to weld on load, so the
baseline exercises that path rather than avoiding it.

## Keys, frames and resolution order

Every measurement this pack reads is of the **assembly**: every solid, placed, in
the assembly frame. Every limit is the assembly's or the process's. `fdm-print`
reads part-sized numbers under names that used to be identical, and on a project
with both packs installed — an assembly and printed parts, which is every
mechanical project — one word had to mean two things. Published as the assembly,
`fdm.bed_fit` measured a 480 mm boat against a 220 mm printer bed and FAILED.
Published as the part, `cad.bounding` skipped and its envelope claim went unheld.

Two things fix it, and a project may use either:

* **Name the object.** `assembly_bbox_mm` is unambiguous everywhere; so is
  `part_bbox_mm` in the other pack. The bare spellings still work as fallbacks.
* **Scope the key.** Prefix it with this pack's scope — `cad.` — and this pack's
  gates take it first: `cad.bbox_mm` for the assembly, `fdm.bbox_mm` for the part,
  from one projection. Also accepted as a nested group:
  `"cad": {"bbox_mm": [...]}`.

**Resolution order, in full, highest first**, written down because the old one
(`bbox_mm` before `bbox`, undocumented) cost a user an afternoon:

1. `cad.<key>` — this pack's scoped spelling
2. `cad-solid.<key>` — the pack's full name
3. the bare key, trying the spellings below in the order given

A scoped key always beats an unscoped one.

| Quantity | Primary key | Also accepted | What it is |
|---|---|---|---|
| Assembly envelope | `assembly_bbox_mm` | `bbox_mm` | `[X, Y, Z]` of the whole assembled product, mm |
| Envelope limit | `assembly_bbox_limit_mm` | `bbox_limit_mm` | where it has to fit, mm (a scalar means a cube) |
| Material volume | `assembly_volume_mm3` | `volume_mm3` | every solid's volume summed, mm³ |
| Volume budget | `assembly_volume_limit_mm3` | `volume_limit_mm3` | optional |
| Centre of mass | `assembly_com_mm` | `com_mm` | `[X, Y, Z]`, assembly frame |
| CoM target / tolerance | `assembly_com_target_mm`, `assembly_com_tol_mm` | `com_target_mm`, `com_tol_mm` | optional pair |
| Minimum wall | `process_min_wall_mm` | `min_wall_mm` | the thinnest wall the PROCESS allows — a limit. `fdm-print`'s `min_wall_mm` is the thinnest section MEASURED in a part, which is the opposite kind of number: publish a measurement under this name and the gate compares the geometry against a threshold nobody chose |
| Placed solids | `meshes` | `solids`, `parts` | `{name: path}`, already placed in the assembly frame |

The full list, with a unit and a sentence per key, is `selftest/baseline.json` —
every key any gate here reads, on an assembly they all pass, with the fallback
spellings in its `_aliases` map.

`atompipe doctor` diffs this vocabulary against every other installed pack's and
warns when two of them read one key differently, naming both packs.

## Units and frames

- **Lengths mm, areas mm², volumes mm³, angles degrees.** Everything. A mesh
  exported in metres makes `cad.wall_thickness` report `0.001` against a `1.2`
  limit and `cad.clash` find nothing, both without a single warning.
- **Meshes must already be placed in the ASSEMBLY frame.** `cad.clash` booleans the
  meshes as given. Parts exported at their own local origins either all overlap or
  none do, and both answers are confidently wrong. If your exporter writes
  part-local geometry, apply the placement transform before handing the mesh over.
- **Z up**, right-handed, matching the model. This pack never re-orients anything.
- `cad.bounding` compares the projection's numbers in the projection's frame. It
  cannot tell an X/Y swap from a part that fits.
- **The envelope is the ASSEMBLY's.** If the number you have is one printed part's,
  it belongs to `fdm-print` under `part_bbox_mm`, and handing it to this gate
  proves the wrong thing quietly.

## The physics in one paragraph

A solid is a closed, orientable, consistently wound 2-manifold: every edge is shared
by exactly two triangles, and the two agree on which side is outside. That is the
whole basis on which a signed volume, an inside/outside test, and every boolean
operation stand. Break any of it and the operations do not fail loudly — they return
plausible numbers. A hole makes a ray test flip parity at the wrong place, so
"inside" becomes arbitrary; a reversed facet makes the signed volume wrong by twice
that facet's contribution; a duplicated vertex splits adjacency so the surface is
topologically open where it is geometrically closed. Intersection volume is the clash metric
because it is a *measure*: it goes to zero continuously as parts separate, which lets
a tolerance absorb tessellation noise without hiding real interference — at 0.2 mm³
for flat prismatic pairs, 3 mm³ for curved ones, because chord error on a tessellated
curve is genuinely larger than the sliver noise between two coincident planes. But a
measure is not a depth, and a fixed volume tolerance forgives an unbounded
penetration as the contact patch narrows, so the same volume is also divided by the
largest face of the two parts' overlapping bounding boxes to give a mean penetration
depth and compared against 0.01 mm prismatic / 0.05 mm curved — the exporter's planar
deviation and a tessellated curve's chord height respectively. Volume answers "how
much material is shared"; depth answers "how far in", and only the second stays the
same statement on a 5 mm pin and a 200 mm flange. That asymmetry is also why a
bonded joint is judged on depth alone: shared volume on a bond line is depth times
glue area, and the glue area is how big the joint was designed to be. One more
consequence of the same measure-theoretic fact: the intersection of two solids lies
inside the intersection of their bounding boxes, so when that box is flat the shared
volume is zero exactly — no tolerance and no kernel involved.

## Common failure modes, and what they look like

| Symptom | What it usually is |
|---|---|
| `cad.clash` reports zero clashes on an assembly you know interferes | a part is not watertight; the boolean returned empty. Check `cad.watertight` first — this gate counts a non-volume as a clash for exactly this reason |
| Every pair clashes with enormous volumes | meshes are at their local origins, not placed in the assembly frame |
| `cad.wall_thickness` reports ~0.001 mm | the mesh is in metres |
| `cad.degenerate_faces` passes but the mesher still chokes | slivers with non-zero area — outside this pack's claim, see "cannot settle" |
| `cad.bounding` passes and the part does not fit | the projection's numbers are stale; nothing here re-derives them from the mesh |
| Clash volumes of a few mm³ on a curved mating face | tessellation noise. Set a **per-pair** tolerance. Raising the global one hides the flat-plate interference you actually care about |
| Clash volumes of tens of mm³ at a hundredth of a millimetre of depth, on a joint you glued | a bond line. The volume is big because the *joint* is big; declare the pair in `bonded_joints` and read the depth |
| A huge shared volume reported with `inf` depth or a `0.00 mm²` contact patch | it should be impossible now — the pair is reported as `contact` and never booleaned. If you see it, the two bounding boxes DO overlap on all three axes and the kernel is genuinely confused: check `cad.watertight` and `cad.is_volume` first |
| An allowlist grows until the gate never fails | that is the designed-in risk; see below |
| A glued assembly opens with a page of red | see below — that is the moment `bonded_joints` exists for, and the moment a wildcard is most tempting |

## The allowlist, the bonded declaration, and how they go wrong

Three levels, and the middle one exists because the gap between the other two is
where wildcards get written.

**Nothing declared** is the default, and it is right for most pairs. Note that
*touching is already not a failure*: a pair whose bounding boxes meet without
overlapping is `contact` and passes. Nothing has to be declared for a butt joint,
two hull sections end to end, or a panel sitting on a rim.

**`bonded_joints`** is for a joint DESIGNED to be face to face — glued, welded,
bonded. On a correctly modelled one the two faces are two tessellations of *one*
nominal surface, so the pair reports a shared volume of depth × glue area, and the
glue area is a design quantity that is legitimately large: a 2400 mm² epoxy fillet
at 0.011 mm of tessellation overlap is 26 mm³, a hundred times the prismatic volume
tolerance, with nothing wrong. So the declaration **waives the volume tolerance and
keeps a depth one** (0.05 mm — the same chord-height figure as the organic depth
tolerance, for the same reason, and not a new licence). A bonded pair deeper than
that still **FAILS**: depth does not move with the size of the joint, so "this part
is 2 mm into that one" is still sayable about a glued pair. A kernel that raised, a
part that is not a volume, a negative or non-finite intersection — all still clashes
for a bonded pair too. The declaration says the contact is intended; it says nothing
about the boolean being trustworthy.

**`clash_allow`** waives the pair entirely, and is for a contact that is genuinely
supposed to share material: a press fit, an interference snap, a gasket crushed on
assembly.

Every entry in either list needs a stated `reason`, and the gate **fails outright**
rather than honouring these:

1. **An entry with no reason.** Nobody will ever dare delete an unexplained
   permission to share material, so it outlives the design decision that justified it.
2. **A blanket entry** — a `"*"` on either side, "part X vs anything". One line
   switches the check off for every pair that part is in and the report stays green
   forever. This is how real interference actually gets hidden in practice, and a
   bonded declaration is a statement about *one joint*.
3. **A pair listed in `sliding_fits`.** See below.
4. **A pair in BOTH lists.** One waives it and the other keeps it under a depth
   check, so which one governs is a guess, and a green report nobody can defend is
   the thing this pack exists to prevent. Delete one.

### Why a sliding fit can never be declared bonded

The two statements contradict each other in physics before they contradict each
other in the parser. **A bond is a joint that has been given zero degrees of
freedom; a sliding fit is a joint whose entire purpose is one.** A pair cannot be
both glued and free to move, so an entry claiming both is not a permission — it is a
description of a part that does not exist, and the gate should not be asked to act
on it.

The consequence if it were accepted is worse than the contradiction. `cad.clash`
sees exactly one pose, and at one pose "they touch" and "they jam" are the same
picture; the pair that must move is therefore the pair whose failure this gate is
least able to see, and the declaration would waive its volume tolerance — the half
that would have caught a running clearance closed up to nothing. A sliding fit that
reports contact is not a case for a declaration. It is a case for
`references/travel_sweeps.md`, which is where a pose-dependent claim belongs.

`clash_allow` refuses a sliding pair for the same reason, and always has.

## Claim vocabulary

These are the tags this pack's gates bind to. The contract has two sides and they
are not symmetric: **a gate lists everything its result is relevant evidence for;
a claim carries the narrowest vocabulary that describes what it actually asserts.**
Tagging a narrow assertion with a broad word is where it goes wrong — a claim that
says "the cover is not interfering with the housing" tagged `geometry` gets covered
by every geometry gate in every installed pack, so a wall-thickness failure makes an
*interference* claim read FAIL and the reader goes hunting in the wrong file.

| Tag | Use it on a claim about | Gates that bear on it |
|---|---|---|
| `envelope` | the part fitting inside a stated bounding volume | `cad.bounding` |
| `packaging` | what has to fit around or inside what, at assembly level | `cad.bounding` |
| `wall` | a minimum or maximum material thickness | `cad.wall_thickness` |
| `interference` | two named parts sharing material | `cad.clash` |
| `fit` | a mating pair going together as intended | `cad.clash` |
| `assembly` | the placed assembly as a whole, in its assembly frame | `cad.clash` |
| `mesh` | the exported triangle mesh as a file: closure, winding, degeneracy | `cad.watertight`, `cad.is_volume`, `cad.degenerate_faces`, `cad.wall_thickness` |
| `manufacturability` | a process being able to make the thing as exported | `cad.watertight`, `cad.is_volume`, `cad.degenerate_faces`, `cad.wall_thickness` |
| `mechanical` | a physical-arrangement assertion that is not purely geometric | `cad.bounding`, `cad.clash` |
| `geometry` | broad; prefer a narrower tag above whenever one fits | every gate here |
| `cad` | broad; the domain, not a quantity. Prefer a narrower tag | every gate here |

`geometry` and `cad` are listed last on purpose. They are the vocabularies every
gate in this pack claims, so a claim carrying one of them is covered by all six —
useful on a deliberately broad claim ("the exported geometry is sound"), wrong on
anything specific.

The same list is `claim_classes` in `pack.json`, which is what `atompipe gap` scores
a claim's quantity against when it is looking for a pack that could settle it. A tag
a gate emits and the manifest does not declare is a tag no gap search will ever route
here, so the two are kept in step.

## Where to look next

- `references/mesh_hygiene.md` — export settings, the repair order that works, and
  why loading with `process=True` hides the defect you were looking for.
- `references/tolerance_healing.md` — the kernel's own tolerance budget, and why a
  healthy part sits orders of magnitude below the limit.
- `references/travel_sweeps.md` — checking a mechanism through its travel instead of
  at the one pose that happened to be saved.
- `lenses.md` — the adversarial review dimensions to attack a design from before it
  is built.
- `sourcing.md` — exchange formats, tessellation settings, and what a vendor's
  quoting tool will do to your file.
