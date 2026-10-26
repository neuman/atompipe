# motorbike: the air around a motorcycle

OpenFOAM's motorBike tutorial body, a motorcycle with a rider, in still air at
72 km/h (20 m/s), run by the `aero-openfoam` pack. The question is R1's:

> The bike and rider must push through still air at 72 km/h with a drag area of
> at most 0.35 m^2.

The page shows the flow as OpenFOAM calculated it on the base mesh (the body
coloured by its surface pressure Cp, the stream tracks coloured by the speed of
the air, the wake), beside the claims and what settles each one.

## What you need

- ESI OpenFOAM v2606 with its tutorials, and its `openfoam2606` wrapper on PATH
  (`packs/cfd-openfoam/references/installing.md`).
- For the pictures, ParaView 6.2.0 as `pvbatch62`
  (`packs/aero-openfoam/references/rendering.md`). Without it the gates run, the
  chart is drawn, and the pictures are left out.
- About 1.5 GB of free disk for the scratch of one base-mesh run.

The body, `motorBike.obj.gz`, is not in this repository: it is part of the
OpenFOAM tutorials (GPL-3.0-or-later). `model/bike.py` names it in the install
(`$FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz`) and pins its sha256, so a
run on another file is an error, not a result.

## Run it

```sh
cd examples/motorbike
nopekit check --tier 1                          # the guards: case, flow, domain, mesh
nopekit check --tier 2 --only aero.converged    # the base-mesh solve, with the guards
nopekit check --tier 2 --only aero.wall_treatment   # y+ on the body, with the guards
nopekit check --tier 2                          # every gate: the guards, the mesh ladder and C1
nopekit site init                               # once: the page's files
nopekit site build
nopekit site serve
```

Measured on 2026-10-23, on 6 MPI ranks of a 7-core machine (WSL2), from a cold
cache:

| Step | Time | What runs |
|---|---|---|
| `check --tier 1` | 1 min 32 s | the three tier-0 reads, surfaceCheck twice (for the Reynolds number's length and for the domain), snappyHexMesh and checkMesh (1 min 25 s) |
| `check --tier 2 --only aero.converged` | 7 min 33 s | the guards again (1 min 35 s for the mesh), then the base mesh again, potentialFoam and 500 iterations of simpleFoam (5 min 28 s), and the gate's control on the pack's spheroid (30 s) |
| `check --tier 2 --only aero.wall_treatment` | 11 min 28 s | the guards and the base mesh's run again, then the base mesh solved once more with OpenFOAM's yPlus, and the controls of both gates on the pack's spheroid. y+ at most 300 on 95.04% of the body (before layers were held to 0.2 of their cell; 96.32% on 2026-10-25) |
| `site build` | 26 s, measured before `aero.wall` | the renderer control, five pictures in ParaView and the history chart; `aero.wall` adds a sixth picture once C6 has a result |

The whole check, `check --tier 2`, measured on 2026-10-25 on 6 ranks: 63 min 39 s.
`aero.mesh_independence` took 54 min 16 s of it: the three meshes (358654, 926215
and 2674337 cells), each guarded and solved for 500 iterations; the finest solve
alone took 26 min 27 s. `aero.converged` and `aero.wall_treatment` took 4 min 30 s
each, `aero.mesh_quality` 1 min 17 s, and the controls on the pack's spheroid 4 min
26 s in all.

Every OpenFOAM gate runs again at each check: its tools read files nopekit cannot
see, so between checks its claims read *stale*, with that cause. Its tools do not:
each gate keeps what they wrote in the run store, `.nopekit/cache/runs/` (ignored by
git), keyed on every byte of the case it staged, the tools and their bytes, the
ranks and the gate's code. A later check on the same inputs reads the stored run,
and its line says *reused*. Measured on 2026-10-26, on 6 ranks, after the review of
the run store had moved the spine (every entry re-keyed):

| Step | Time | What runs |
|---|---|---|
| `check --tier 2`, cold (no verdict cache, no run store) | 61 min 30 s | every tool of every gate and control, as above; the store then holds 11 runs, 43 MB |
| `check --tier 2`, warm (the same inputs, right after) | 28 s | the gates and their controls, served all 11 stored runs (each named in its line or a `note:`); surfaceCheck for the body's bounds, and the three spheroid meshes of `aero.mesh_independence`'s known-bad control (`narrow_ladder` is refused before any solve, so it keeps no run) |

The warm check files no new entry: a stored run is read through the same code and
keyed on the same reads as the solve it stands for, so `git status` stays as the
cold check left it. `nopekit check --force` and `nopekit export` never read the
store: they solve again (about an hour), and an export judges its own solve.
`rm -rf .nopekit/cache/runs` is always safe; it costs the next check a solve.

## What you should see

From `nopekit check --tier 2` on 2026-10-25:

```
[ok  ] aero.mesh_quality : ... 0 faces in error against the pack's limits; 358654 cells on 6 ranks ...
[ok  ] aero.converged : U_I 0.603% of the drag area 0.29925 m^2 over iterations 401-500 (within 1%) ...
[ok  ] aero.wall_treatment : y+ at most 300 on 96.32% of the body's area (at least 90%) ...
[FAIL] aero.mesh_independence : level 2 (2674337 cells) is not converged: U_I 1.98% of the drag area, past 1% ...
[skip] aero.drag_area : prerequisite failed: aero.mesh_independence
```

- **C2 to C6 are the guards** of the base-mesh run: the flow is the stated one, the
  box is large enough, the mesh is the one asked for, the drag area settled, and
  the wall model applies (y+). They pass.
- **C7 fails, so C1 is skipped.** C1 carries the tag `drag-area`, and only
  `aero.drag_area` covers that tag: a guard judges its own quantity, never the
  drag area. `aero.drag_area` judges the finest of three meshes at the top of its
  band, after C6 (the wall model, `aero.wall_treatment`) and C7 (mesh
  independence, `aero.mesh_independence`). On 2026-10-25 the ladder gave a drag
  area of 0.29925, 0.29625 and 0.30206 m^2 on 358654, 926215 and 2674337 cells.
  The finest mesh did not settle in its 500 iterations (U_I 1.98%, past 1%), and
  that is the reason C7 gives: the gate holds each level to `aero.converged`'s
  rule before it compares the three, so it did not judge their order and
  computed no mesh error band (GCI). The values go down, then up, but that order
  is not resolved: the change between the two finest meshes (0.0058 m^2) is less
  than the finest mesh's iterative uncertainty (0.0060 m^2), and the pack's
  three-grid procedure calls such a change unresolved, not oscillatory.
  `aero.drag_area` does not run (design decision D6: the demo ships so). P0
  (2026-10-23) saw a finest level that did not settle either, on the tutorial's
  own case (its box and block (20 8 8), 1500 iterations a level): 0.3075, 0.2964
  and 0.3007 m^2, and U_I 1.09% on the finest. More iterations on the finest mesh
  come first; a ladder of other mesh sizes, only if the three settled values then
  do not converge in one direction. A second full check after the review of this
  round (2026-10-25, the spine moved) gave the same values to the last digit.
- **A1 and A2 are assumptions**: the wheels do not turn, and a steady solution
  stands for an unsteady wake. Each counts only when the person it names records
  it in their own shell (`nopekit claim physical A1 assume`).
- So the milestone `wind-tunnel` is **not ready**. That is the method working.

## How `case/` was made

From the v2606 tutorial `incompressible/simpleFoam/motorBike`, as
`packs/aero-openfoam/references/motorbike.md` says:

1. `0.orig/` copied to `0/`, and every file read through `foamDictionary
   -expand` (no `#include` is left); `functions` removed from
   `system/controlDict` (the pack writes its own); `#includeEtc
   "caseDicts/setConstraintTypes"` put back first in each `0/` file's
   `boundaryField`; no `decomposeParDict` and no `meshQualityDict` (the pack's).
2. **The domain grown** in `system/blockMeshDict`: from (-5 -4 0) (15 4 8) to
   (-8 -8 0) (24 8 12), block (32 16 12), so that the inlet, the sides and the top
   are at least 5 body heights from the body and the outlet at least 15 (COST
   732, Franke et al. 2007; `packs/aero-openfoam/references/domain.md`). The
   tutorial's own box fails four of those distances. The cells stay 1 m cubes.
3. **Spalding's wall function** on the body: `0/nut`'s `motorBikeGroup` is
   `nutUSpaldingWallFunction` (valid from y+ 1 into the log layer), not the
   tutorial's `nutkWallFunction`.

The pack replaces the case's cell caps, mesh-quality limits, decomposition and
function objects in its staged copy, and checks OpenFOAM's own reading of the
copy before any tool runs.

<!-- nopekit:begin badge -->
<a href="https://github.com/neuman/nopekit"><img src="https://raw.githubusercontent.com/neuman/nopekit/main/docs/img/made-with-nopekit.png" width="160" alt="Made with nopekit"></a>
<!-- nopekit:end badge -->
