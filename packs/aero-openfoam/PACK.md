# aero-openfoam

Runs a steady, incompressible flow past a body in an open stream in ESI OpenFOAM
v2606 (openfoam.com): snappyHexMesh builds the mesh around the body, simpleFoam
solves it with the k-omega SST model. The claim this pack is for is the **drag
area**, CdA in m^2, at a stated air speed. Guards run first: the case is one this
pack can read and vouch for, the run is the stated flow, the flow is turbulent at
the wall and incompressible, the domain is large enough, the mesh has no face
in error, and the run settled on the base mesh.

**Before you trust a Checked claim from this pack,** know what it is: the
steady RANS equations with k-omega SST, solved on the body in the case's
snappyHexMeshDict, in the domain of its blockMeshDict. It is not a measurement. A
good run shows that the equations were solved well, never that they were the
right equations or the right body. `lenses.md` lists what to attack.

## What this pack settles

| Gate | Tier | Basis | Settles |
|---|---|---|---|
| `aero.case_readable` | 0 | model-only | the case parses, runs simpleFoam with RAS k-omega SST and a Newtonian nu, meshes with blockMesh and snappyHexMesh, compiles no code and carries no function object of its own; a surface file is the one its sha256 pins (the guard) |
| `aero.reference` | 0 | model-only | the inlet is a `fixedValue` of exactly (U 0 0), U = `aero_u_inf_m_s`; the body group exists, every body patch is a wall, 0/U reaches each body patch by a literal entry that names one of its groups (never by a regular expression), and the body is still (`noSlip`) |
| `aero.regime` | 1 | sourced | `aero_ref_length_m` is no longer than the body along the flow (surfaceCheck's box for a surface file); Re on it at least 5e5; Mach below 0.3 |
| `aero.domain` | 1 | sourced | inlet 5 H, outlet 15 H, sides and top 5 H from the body; blockage at most 3%, each directional blockage at most 17% (Franke et al. 2007, Blocken 2015) |
| `aero.mesh_quality` | 1 | established | snappyHexMesh finished without errors and reached no cell cap; `checkMesh -meshQuality` counts no face in error against the pack's limits |
| `aero.converged` | 2 | established | on the base mesh, `simpleFoam` ran to its end on every rank, no residual climbed in the last window, and the drag area's iterative uncertainty U_I = (max - min) / 2 over the last 100 iterations is at most `aero_iter_unc_max_pct` of its mean (ITTC 7.5-03-01-01) |

`aero.reference`, `aero.regime`, `aero.domain` and `aero.mesh_quality` each
need `aero.case_readable`; `aero.converged` needs all four. Each gate covers
its own tag only. No gate here covers `drag-area` yet: a guard judges its own
quantity, not a drag area, so a drag-area claim reads Gap until
`aero.drag_area`, the gate that judges its limit, is in the pack.

Known-bad controls (`selftest/bad_cases.py`, one edit each to the baseline
spheroid, each 15% past its limit): `coded_inlet` (a `codedFixedValue` inlet),
`wrong_speed` (the inlet at 23 m/s against 20), `thick_air` (Re 4.35e5),
`short_wake` (the outlet 13.0 H behind the body), `cell_cap`
(`aero_max_global_cells` 20 000: snappyHexMesh stops at the cap and still says
it finished without errors), `cut_short` (endTime 110: U_I 11.1%).

The tier-0 gates read the case with the pack's own dictionary reader
(`gates/_foam.py`, cfd-openfoam's, standard library only): they run without
OpenFOAM. So does `aero.regime` for a body the dictionary states (a sphere or
a box); for a surface file it runs surfaceCheck. The reader accepts a strict
subset of what OpenFOAM accepts. A directive, a macro outside blockMeshDict, a
coded condition, a keyword written twice in one dictionary or a file it does
not read is a fail. The tier-1 gates copy the case under the gate's out
directory and run OpenFOAM there. On that copy the pack writes its own
dictionaries (`gates/_fo.py`): the mesh-quality limits for snappyHexMesh and
checkMesh, the cell cap, the decomposition, the write precision and every
function object. Before any
run, OpenFOAM's own reading of every dictionary (`foamDictionary -expand`) must
equal the reader's. Every tool runs with a private HOME that turns off
`allowSystemOperations`, with floating-point trapping on, and every parallel
run first asks each rank for its HOME and its `FOAM_SIGFPE` (`_par.rank_probe`).

These gates read inside a subprocess, so they are **opaque**: they run again on
every check where OpenFOAM exists. Between check runs their claims read Stale
with the cause *unseen inputs*.

## What this pack CANNOT settle

- **A measured drag.** A wind-tunnel or coast-down CdA is a physical claim,
  Pending build until a person records it.
- **Turning wheels, a moving rider, a cross wind.** The body is a still wall in
  a stream along +x. A wheel that turns, a yaw angle or a gust is another case.
- **Transient flow.** Steady RANS gives a steady answer. When the real flow
  sheds vortices, the drag of the steady run is not the time-mean drag. A run
  that does not settle shows as a limit cycle (see "Failure modes").
- **Transition.** k-omega SST as run here has no transition model. Below Re 5e5
  `aero.regime` fails; above it, a laminar run of flow on a smooth nose is still
  modelled as turbulent.
- **omega bounding.** k-omega SST clips omega where it goes negative. The
  motorBike's L0 mesh does this on every iteration (min omega -1.75e5, P0) and
  still settles. `aero.converged` reports the count; it does not judge it.
- **Drift.** The half-range does not see a slow drift of the mean (P0: +0.59%
  on the motorBike's L0 between iterations 500 and 1000, while U_I read 0.27%).
  `aero.converged` reports the drift; no source found sets a limit on it.
- **Layer coverage.** snappyHexMesh may not extrude layers everywhere (56.5% of
  the motorBike's faces at L0). It is reported, not judged here.
- **Lift, side force, moments.** forceCoeffs writes them; no gate reads them.
- **The body you meant.** The pack meshes the body the snappyHexMeshDict states.
  A surface file is pinned by its sha256, never by its name. Whether it is the
  design's is for a person to check.

## Claim tags

| Tag | Bound by |
|---|---|
| `drag-area` | no gate yet (`aero.drag_area` comes with the mesh ladder): a claim with this tag reads Gap |
| `case-readable` | `aero.case_readable` |
| `flow-reference` | `aero.reference` |
| `flow-regime` | `aero.regime` |
| `domain-size` | `aero.domain` |
| `mesh-quality` | `aero.mesh_quality` |
| `convergence` | `aero.converged` |

Write a drag-area claim as `"quantity": "drag area"`, `"units": "m^2"`, an upper
limit (`<=`). The other gates' quantities are `aero case readability`, `aero flow
reference`, `aero flow regime`, `aero domain size`, `aero mesh quality` and
`aero solver convergence`.

## Units, frames and which object

- **SI throughout.** Metres, m/s, m^2/s for nu, m^2 for the drag area.
- **The frame is the case's.** The air enters along **+x** through the one patch
  on the low-x side of blockMeshDict's box; the drag direction is (1 0 0), lift
  (0 0 1). A case set up along another axis fails `aero.reference`.
- **The object is the body**: every surface in snappyHexMeshDict's
  `refinementSurfaces`, in the patch group `aero_body_group`. The drag is summed
  over that group. The domain is blockMeshDict's box, which must be one
  axis-aligned box.
- **H** is the height of the body's top over the ground (a wall on the box's
  bottom), or the body's own height in free air. The domain's distances are in H.

### Parameters

| Key | Read by | Default |
|---|---|---|
| `aero_case` | every gate | none: the case directory, against the project root |
| `aero_geometry`, `aero_geometry_sha256` | every gate, when the body is a surface file | none; `$FOAM_TUTORIALS/...` reads from the install |
| `aero_body_group` | reference, converged | none |
| `aero_u_inf_m_s` | reference, regime, converged | none |
| `aero_ref_length_m` | regime | none |
| `aero_sound_speed_m_s` | regime | none |
| `aero_ranks` | tier 1+ | 8 `[pack default]` |
| `aero_max_global_cells` | tier 1+ | 2e7 `[pack default]` |
| `aero_iter_unc_max_pct` | converged | 1 `[pack default]` |
| `aero_timeout_s` | tier 1+ | 3600 s per tool run |

A missing input is a skip, never a default, except the settings marked
`[pack default]` in the verdict.

## Pictures

`aero.converged` writes the picture data with OpenFOAM's own function objects,
at the last iteration, on the base mesh: the body with Cp (`static(p)_coeff`),
CpT (`total(p)_coeff`) and the speed (`mag(U)`), the wake surface CpT = 0,
three wake cuts behind the body (at 0.12, 0.6 and 1.35 body lengths), and two
rakes of stream tracks (`streamLine`, `postProcessing/sets/`). Its summary.json
names each file with its sha256 (`fields`), with the body's box, the ground and
the flow direction, and no limit: a viewgen binds those digests, so a figure
draws this run and no other. A figure bound to `aero.converged` still shows when
a later gate fails, beside its claim's status.

The views (`views/flow3d.py`) draw these files with ParaView (`pvbatch62`) and
OpenFOAM's history with Vega-Lite: `aero.hero` (the body by Cp, the stream
tracks by speed, lit, with its 3D file), `aero.surface_cp` (Cp, unlit: each
pixel a colour of the key), `aero.history` (the drag area at each iteration and
the judged window), `aero.wake` and `aero.wake_cuts`. The colour map is Turbo.
Without ParaView the pictures are left out and no status moves.

## The physics, in one paragraph

Drag force F_D = 1/2 rho U^2 CdA. CdA is the force over the dynamic pressure, so
it does not need a frontal area: forceCoeffs with `Aref 1` writes it as its Cd
column. A streamlined body has a CdA much smaller than its frontal area (the
spheroid baseline: 0.0044 m^2 against 0.049 m^2 frontal); a bluff body is near
its frontal area (a car about 0.6-0.8 m^2, a motorcycle and rider about 0.3-0.6
m^2; the motorBike tutorial reads 0.305 m^2). Re = U L / nu: about 1.9e6 for the
motorBike at 20 m/s. A CdA that doubles when the mesh is refined, or a negative
CdA, is a broken run, not a design.

## Common failure modes

- **A domain too small.** The flow squeezes past the body (blockage) or meets the
  outlet before it recovers (a short wake). `aero.domain` fails and names the
  distance. The motorBike tutorial's own domain fails four distances.
- **A mesher that gave up.** A cell cap reached, or snappyHexMesh unable to snap,
  gives a mesh that is not the one asked for. `aero.mesh_quality` fails, naming
  the cap or the faces in error.
- **A stated speed that is not the run's.** `aero.reference` fails: every
  coefficient is made dimensionless by the stated speed.
- **A limit cycle.** A steady run of an unsteady wake swings about a mean for
  ever. `aero.converged` fails when the swing's half-range is past its ceiling;
  a longer run does not help (P0: the motorBike's L2 swings by 1.0-1.7% from
  iteration 1000 to 1500). A drift of the mean between windows is in the detail.
- **A run cut short.** simpleFoam exits 0 and prints End when it runs out of
  iterations. `aero.converged` reads the history: a window that never filled,
  or one still in the start-up, fails.
- **A run that hangs on one rank.** Every parallel run has a timeout that kills
  all ranks; a timeout is a skip.

## Where to look next

| File | For |
|---|---|
| `references/domain.md` | the domain limits, quoted from their sources, and the tutorial measured against them |
| `references/meshing.md` | snappyHexMesh as the pack runs it, the quality limits, the cell cap, the ranks |
| `references/convergence.md` | iterative uncertainty (ITTC 7.5-03-01-01), drift, the windows P0 measured |
| `references/wall-treatment.md` | y+ and the wall functions (Spalding), the bands, P0's measurements |
| `references/rendering.md` | ParaView for the pictures: the build, its checks, Turbo, lit and unlit pictures |
| `references/motorbike.md` | the motorBike geometry: where it comes from, its licence, its digest, its bounds |
| `lenses.md` | what to attack before anyone builds from a result |
