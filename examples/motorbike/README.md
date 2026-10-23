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
nopekit site init                               # once: the page's files
nopekit site build
nopekit site serve
```

Measured on 2026-10-23, on 6 MPI ranks of a 7-core machine (WSL2), from a cold
cache:

| Step | Time | What runs |
|---|---|---|
| `check --tier 1` | 2 min 41 s | the four tier-0 reads, surfaceCheck, snappyHexMesh and checkMesh (2 min 22 s) |
| `check --tier 2 --only aero.converged` | 8 min 51 s | the guards again (2 min 2 s for the mesh), then the base mesh again, potentialFoam and 500 iterations of simpleFoam (6 min 4 s), and the gate's control on the pack's spheroid (32 s) |
| `site build` | 24 s | the renderer control and five pictures in ParaView, the chart |

Every OpenFOAM gate runs again at each check: its tools read files nopekit cannot
see, so between checks its claims read *stale*, with that cause.

## What you should see

```
[ok  ] aero.mesh_quality : ... 0 faces in error against the pack's limits; 351753 cells on 6 ranks ...
[ok  ] aero.converged : U_I 0.883% of the drag area 0.297779 m^2 over iterations 401-500 (within 1%) ...
[gap  ] C1 The drag area of the bike and rider is at most 0.35 m^2 ... — no evaluator
```

- **C2 to C5 are the guards** of the base-mesh run: the flow is the stated one, the
  box is large enough, the mesh is the one asked for, and the drag area settled.
  They pass.
- **C1 reads gap.** The base mesh alone does not give the drag area. The judge,
  `aero.drag_area`, comes with the mesh ladder (three meshes and their GCI), with
  C6 (the wall model) and C7 (mesh independence). Until then no evaluator covers
  them. On the tutorial's own ladder the design measured an oscillatory
  convergence, so C7 is expected to fail, and C1 with it.
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
