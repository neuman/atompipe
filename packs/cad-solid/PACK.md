# cad-solid

Solid-geometry validation for exported mechanical parts. It answers two questions:
**is this file actually a solid**, and **do the placed solids share material**.

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
  projection supplies. If `bbox_mm` was written by hand, or was computed before the
  last model change, this gate will cheerfully certify a stale number. Proving the
  projection still agrees with the exported mesh is a *cross-representation* claim
  (method rule 6) and needs its own gate.
- **`cad.clash` checks ONE POSE.** A mechanism that clears at the pose you exported
  can jam at full travel. Sweeping is `references/travel_sweeps.md`, and it is a
  project's job to export the poses.
- **`cad.clash` does not measure clearance.** It reports shared material. Two parts
  0.01 mm apart and two parts 8 mm apart are both "clear". A minimum-gap claim
  needs a distance query, which this pack does not ship.
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
| `cad.bounding` | 0 | worst of bbox / volume / CoM utilisation | the model's own `*_limit_*` params | `selftest/bad_bounds.py:tall_part` — 15% over the Z envelope, nothing else changed |
| `cad.watertight` | 1 | open + non-manifold edges | 0, by definition of a solid | `selftest/bad_meshes.py:holed_box` — +Z facet deleted, 4 open edges |
| `cad.is_volume` | 1 | parts that are not volumes | 0, by definition | `selftest/bad_meshes.py:flipped_facet` — one triangle wound backwards, still watertight |
| `cad.degenerate_faces` | 1 | repairs needed (welds + drops) | 0 | `selftest/bad_meshes.py:sliver_pair` — one corner of a closed box emitted twice 1e-6 mm apart, a subset of its faces repointed at the copy, one face spanning the two |
| `cad.wall_thickness` | 1 | thinnest sampled wall, mm | `min_wall_mm` in the projection | `selftest/bad_meshes.py:thin_plate` — a plate at a quarter of that limit |
| `cad.clash` | 1 | interfering pairs | 0 pairs; per-pair volume **and** depth tolerance | `selftest/bad_meshes.py:overlapping_pair` — two valid boxes sharing 800 mm³ |

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

## What the projection must provide

```python
params = {
    # every mesh gate
    "meshes": {"housing": "build/housing.stl", "lid": "build/lid.stl"},   # or trimesh objects
    # cad.bounding (tier 0)
    "bbox_mm": [78.0, 52.0, 23.5],  "bbox_limit_mm": [80.0, 60.0, 25.0],
    "volume_mm3": 41200.0,          "volume_limit_mm3": 60000.0,     # optional
    "com_mm": [39.0, 26.0, 9.2],    "com_target_mm": [39.0, 26.0, 9.0],
    "com_tol_mm": 1.5,                                               # optional
    # cad.wall_thickness
    "min_wall_mm": 1.2,
    "wall_samples": 4000,                                            # optional
    # cad.clash
    "clash_tolerance_mm3": 0.2,                                      # optional override
    "clash_tolerances_mm3": {"housing|lid": 3.0},                    # optional, per pair
    "clash_depth_tol_mm": 0.01,                                      # optional override
    "clash_depth_tols_mm": {"housing|lid": 0.05},                    # optional, per pair
    "organic_parts": ["grip"],                                       # optional
    "sliding_fits": [["rail", "carriage"]],                          # optional
    "clash_allow": [{"pair": ["housing", "lid"], "reason": "0.1 mm press fit, intended"}],
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

The same refusal applies to geometry written short. `bbox_mm`, `com_mm` and
`com_target_mm` are *measurements* and must be 3-lists — a single number there is not
a compact spelling, it is two missing axes, and expanding it into a cube would hand
back a confident PASS on a Y and Z the gate invented. `cad.bounding` SKIPS and names
the key instead. `bbox_limit_mm` is the one place a scalar is accepted, because "the
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
intended face contact (`clash_allow`), a real sliding fit (`sliding_fits`, which the
allowlist must refuse to cover) and one curved part (`organic_parts`), so every key
the gates read has a value a practitioner would recognise rather than a placeholder.
The `_notes` block in the file names each key and its unit.

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
same statement on a 5 mm pin and a 200 mm flange.

## Common failure modes, and what they look like

| Symptom | What it usually is |
|---|---|
| `cad.clash` reports zero clashes on an assembly you know interferes | a part is not watertight; the boolean returned empty. Check `cad.watertight` first — this gate counts a non-volume as a clash for exactly this reason |
| Every pair clashes with enormous volumes | meshes are at their local origins, not placed in the assembly frame |
| `cad.wall_thickness` reports ~0.001 mm | the mesh is in metres |
| `cad.degenerate_faces` passes but the mesher still chokes | slivers with non-zero area — outside this pack's claim, see "cannot settle" |
| `cad.bounding` passes and the part does not fit | the projection's numbers are stale; nothing here re-derives them from the mesh |
| Clash volumes of a few mm³ on a curved mating face | tessellation noise. Set a **per-pair** tolerance. Raising the global one hides the flat-plate interference you actually care about |
| An allowlist grows until the gate never fails | that is the designed-in risk; see below |

## The allowlist, and how it goes wrong

`clash_allow` exists because some contacts are intended: a press fit, an interference
snap, a gasket crushed on assembly. Each entry needs a stated `reason`, and the gate
**fails outright** on three kinds of entry rather than honouring them:

1. **An entry with no reason.** Nobody will ever dare delete an unexplained
   permission to interfere, so it outlives the design decision that justified it.
2. **A blanket entry** — a `"*"` on either side, "part X vs anything". One line
   switches interference checking off for a part and the report stays green forever.
   This is how real interference actually gets hidden in practice.
3. **A pair listed in `sliding_fits`.** A pair whose job is to *move* relative to the
   other is the pair that most needs this check — "they touch" and "they jam" look
   identical to a boolean at a single pose. An intended contact is allowlistable; an
   intended motion is not.

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
