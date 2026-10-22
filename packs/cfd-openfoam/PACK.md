# cfd-openfoam

Runs a laminar, steady, incompressible flow case in ESI OpenFOAM v2606
(openfoam.com) and settles the static pressure drop between two planes. Five
guards run first: the case is one this pack can read and vouch for, the flow is
laminar and incompressible, checkMesh finds the mesh sound, simpleFoam
converged, and three meshes agree (the grid convergence index, Celik et al. 2008).

**Before you trust a Checked claim from this pack,** know what it is: the
equations of a laminar, Newtonian, isothermal flow, solved on the geometry in
the case's `blockMeshDict`, to the pack's residual target, on three meshes that
agree to within the GCI you allowed. It is not a measurement. A converged,
mesh-independent run shows the equations were solved well, never that they were
the right equations or the right geometry. `lenses.md` lists what to attack.

## What this pack settles

| Gate | Tier | Basis | Settles |
|---|---|---|---|
| `cfd.case_readable` | 0 | model-only | the case parses, runs simpleFoam, laminar and Newtonian, meshes with blockMesh, compiles no code and reads no file outside itself (the guard) |
| `cfd.regime` | 0 | sourced | Re on the hydraulic diameter below 2300, Mach below 0.3 |
| `cfd.mesh_quality` | 1 | established | checkMesh says `Mesh OK.` and the worst non-orthogonality, skewness and aspect ratio are each inside the project's limit |
| `cfd.converged` | 2 | established | simpleFoam printed `SIMPLE solution converged`, every residual is at the pack's target, the pressure drop's estimated remaining change is under 0.1%, and the run carried the stated velocity |
| `cfd.mesh_independence` | 2 | sourced | the case's mesh and two refinements converge monotonically at an observed order in [0.95, formal + 0.05], with a fine-grid GCI at most `cfd_gci_max_pct`; each plane on a cell face or centre at every level |
| `cfd.pressure_drop` | 2 | established | the pressure drop on the finest mesh, raised by its GCI, is at most the limit of the claim tagged `pressure-drop` |

Each gate needs the one before it (`case_readable` → `regime` and `mesh_quality`
→ `converged` → `mesh_independence` → `pressure_drop`). A pressure drop never
reaches a claim past a guard that did not pass: it reads Skipped and names the
guard.

The tier-0 gates read the case with this pack's own dictionary reader
(`gates/_foam.py`, standard library only), so they run without OpenFOAM, CI
included. The reader accepts only a strict subset of what OpenFOAM accepts, the
subset it can read exactly as OpenFOAM does (see "Pointing a project at its
case"): a directive, a macro or a file it would not evaluate is a fail, never a
guess. The others copy the case's `0/`, `constant/` (not its mesh) and
`system/` under the gate's out directory and run OpenFOAM there. On that copy the
pack writes its own residual targets and its own function objects (two
planes; in `cfd.pressure_drop` also OpenFOAM's `mag` of U and its static
pressure in Pa, which the site's pictures draw), and removes the case's: the numbers come from the pack, never from the project's
`controlDict`. Before the run, OpenFOAM's own reading of the copy
(`foamDictionary -expand`) must hold exactly the pack's function objects and
residual targets and the case's nu, and the solver's log must report the pack's
convergence criteria; any difference is an error. Every tool runs with a
private HOME that turns off `allowSystemOperations` and with floating-point
trapping forced on, and a log whose banner does not show both is an error. These gates read inside a
subprocess, so they are **opaque**: they re-run on every check where OpenFOAM
exists (the baseline's six gates take about 10 s in all). Between check runs their
claims read Stale with the cause *unseen inputs*: nopekit cannot see the inputs
OpenFOAM reads, so only a check run can show that a result is current. `check`
says this on the line after its *ready*; `nopekit doctor` lists every input. Each gate runs its
own meshes: nothing is shared between gates, because the spine empties caches
before every run.

**Exit codes decide nothing here.** checkMesh exits 0 on a failed mesh and
simpleFoam exits 0 when it runs out of iterations. The gates read the text. A run
that dies on a signal (SIGFPE is divergence), exits non-zero or never prints `End`
is an error; a timeout is a skip.

## What this pack CANNOT settle

- **Turbulent, transient, compressible or heated flow.** Phase 1 runs simpleFoam,
  laminar, Newtonian, isothermal. A case with a turbulence model, another solver
  or another transport model fails `cfd.case_readable`, saying so. External flow
  and forces (phase 2) and conjugate heat transfer (phase 3) are planned in
  GitHub issue #15.
- **Source terms, porosity, a moving reference frame.** A file the pack does not
  read (`constant/fvOptions`, `MRFProperties`, `fvModels`, ...) is refused, so
  each of these fails `cfd.case_readable`.
- **Geometry from CAD.** The mesh is built by blockMesh from the case's
  `system/blockMeshDict`. A case with a `snappyHexMeshDict` is refused. Whether
  the blocks are the design's geometry is for a person to check (`lenses.md`).
- **A number the planes do not hold.** The pressure drop is the area average of
  static p on one plane minus the other. Each plane cuts the whole mesh: in a
  passage that branches it averages every branch it crosses. Total pressure, a
  peak, a force, a flow split: none of them is measured.
- **Whether the model is right.** A converged, mesh-independent laminar run of a
  flow that is turbulent, or of a 2D channel standing in for a 3D duct, is a good
  answer to another question. `cfd.regime` checks the stated Reynolds number; it
  cannot check that the hydraulic diameter you stated is the passage's.
- **The meshes the ladder does not make.** Refinement multiplies every block's
  cell counts by the ratio. Only a 2D case's one-cell direction, across its empty
  patches, stays one cell. A feature no block resolves stays unresolved at every
  level.
- **A pressure drop that moves after the run stops.** `cfd.converged` estimates
  the change still to come from the history (Eca and Hoekstra 2009). Some
  histories deceive it: an overshoot near its turning point, a slow mode under a
  fast oscillation, a rate that becomes slower in the last few iterations, and a
  drift under 1e-8 of the value per iteration. An overshoot read at its turning
  point can be far from its limit: up to 29% in the measured set.
  `references/running-openfoam.md` gives each one with its measured error.
- **Anything about a built part.** A measured pressure drop is a physical claim,
  Pending build until a person records it.

## Claim tags

| Tag | Bound by |
|---|---|
| `cfd`, `fluid-dynamics`, `internal-flow` | every gate here (too broad for a claim) |
| `pressure-drop` | every gate here: the guards bind it too, so a pressure-drop claim is never Checked past a guard that did not pass |
| `flow-regime` | `cfd.regime` |
| `mesh-quality` | `cfd.mesh_quality` |
| `convergence` | `cfd.converged` |
| `mesh-independence` | `cfd.mesh_independence` |

**The claim's quantity.** nopekit compares a value with a claim's limit only
when the claim's `acceptance.quantity` is the quantity the gate settles, word
for word. For the pressure drop, write `"quantity": "pressure drop from cfd"`
and `"units": "Pa"`. With another word, such as `"pressure drop"`, the value
of `cfd.pressure_drop` is not compared with the claim's limit, and the card on
the page shows no large value. The quantities of the other gates are
`cfd case readability`, `cfd flow regime`, `cfd mesh quality`, `cfd solver
convergence` and `cfd mesh independence`.

**The limit is the claim's.** `cfd.pressure_drop` reads its limit from the
claim tagged `pressure-drop` (`ctx.acceptance`), and from no parameter. It
compares the top of the GCI band with that limit and reports the limit and the
comparator of the claim. Edit the limit in `claims/`: the next check runs the
gate again. The gate gives an error, and runs no mesh, when the claim:

- states its limit in units other than `Pa` (for example, `kPa`);
- states a comparator other than `<=` or `<` (the top of the band is on the
  side that fails only for an upper limit);
- is not there, or two claims tagged `pressure-drop` state different
  conditions. Tag one pressure-drop claim for each case.

In earlier versions the limit was a parameter, `cfd_dp_max_pa`, beside the
claim's limit. A claim at 0.5 Pa and the parameter at 0.6 Pa gave a pass at
0.52 Pa, and the card said that the value does not meet the acceptance
condition. The gate does not read that parameter now. Remove it from your
model.

## Units

SI. Metres, m/s, kg/m^3, Pa, seconds. OpenFOAM's incompressible `p` is kinematic
(m^2/s^2): `cfd.pressure_drop` multiplies it by `cfd_density_kg_m3` and reports
Pa.

Each guard gives its value in the units of its own calculation, against its own
limit. The site then shows, for example, "20 Re against a limit of 2300 Re, 99%
inside the limit".

| Gate | Value | Limit |
|---|---|---|
| `cfd.regime` | Re = U Dh / nu, in `Re`: U is `cfd_velocity_m_s`, Dh is `cfd_length_m`, nu is from the case | below 2300, the onset of transition in a pipe |
| `cfd.regime` | Mach = U / c, in `Mach`, when it is nearer its limit than Re | below 0.3 |
| `cfd.mesh_quality` | the worst non-orthogonality in `deg`, skewness in `skewness` or aspect ratio in `aspect ratio`: the one nearest its limit | `cfd_max_non_ortho_deg`, `cfd_max_skewness`, `cfd_max_aspect_ratio` |
| `cfd.converged` | the estimated change still to come in the pressure drop, in `%` of it | at most 0.1 % |
| `cfd.mesh_independence` | the fine-grid GCI, in `%` of the pressure drop | `cfd_gci_max_pct` |

A gate that judges more than one value gives the value nearest its limit. Thus a
pass never shows more margin than the gate has, and a fail gives the value that
failed. A gate gives no value when it fails for a reason that is not a value:
`cfd.converged` when the run stops short, and `cfd.mesh_quality` when checkMesh
fails a check but each value is in its limit. The detail of `cfd.converged`
gives the iteration that the run converged at.

In earlier versions, `cfd.regime` and `cfd.mesh_quality` gave the worst value
divided by its limit. The page then showed "0.008696 fraction of limit" for Re
20.

Each gate that runs simpleFoam writes the pressure drop's history as a CSV file
beside its `summary.json`, one for each mesh, and the summary holds the
estimated remaining change as `iterative_error_pct`. A chart of the history
calculates nothing (`references/running-openfoam.md`, "What the evidence
holds").

## Pictures on the site

Each picture is of `cfd.pressure_drop`'s result, the result that the page
shows beside the claim. A picture changes no status.

| View | What it shows | Tool |
|---|---|---|
| `cfd-openfoam.ladder` | the pressure drop on each mesh against its cell size, the value at zero cell size, and the GCI band | none |
| `cfd-openfoam.settle` | how much the pressure drop changed after each iteration on each mesh, the tolerance, and the estimate of the change still to come | none |
| `cfd-openfoam.speed` | OpenFOAM's `mag(U)` on the finest mesh, cut at the middle of its thickness | `pvbatch62` |
| `cfd-openfoam.pressure` | OpenFOAM's `static(p)` in Pa on the same cut; "Turn it in 3D" shows the cut in 3D | `pvbatch62` |

A chart draws the numbers of the result and no other number. On the ladder,
the site adds the claim's limit and a ring at the judged value, the top of the
GCI band. The band is a vertical line with a short bar at each end; when the
band is small, the two bars touch. The settling chart is of a change in
percent, so it has no limit and no ring. In a still, each cell shows its own
value, and the two lines are the measuring planes. Their names are above the
picture. OpenFOAM computed each field, and ParaView only gives it colours.

**Which cut.** The stills show a planar 2D case only. The gate writes the
normal of the case's `empty` patches into the summary (`thin_normal`), and
ParaView cuts the case across it, at the middle of its thickness, so the cut
holds every cell of the finest mesh. The flow, from the upstream plane to the
downstream plane, goes from left to right in the picture, whatever the axis
of the case. The pack refuses a still whose cut does not hold every cell of
the finest mesh, and one whose plane lines are not in that order. A 3D case
gets the two charts and no still: no one cut shows a 3D duct, and the caption
would not be true. A picture is at most as tall as it is wide.

**The scales.** Each colour scale is a constant of the pack times a value of
the result. It is never the claim's limit: a colour set by the limit would be
a second verdict on the claim, so an edit of the limit changes no colour.

- Speed: from 0 to two times the mean speed through the upstream plane.
  Developed laminar flow has a peak of 1.5 times its mean between plates and
  2 times its mean in a round pipe, so the core of the flow is in the scale. A
  jet that is faster is magenta.
- Static pressure: from one pressure drop below the pressure on the
  downstream plane to two pressure drops above it. On the baseline this holds
  the outlet (0.5 drops below) and the inlet (1.5 drops above). At the corners
  of the inlet the pressure is above the scale (2.6 drops on the finest mesh,
  and more on a finer mesh), so those cells are magenta.
- The colour map is ParaView's `Viridis`. Magenta is above the scale and grey
  is below it. The page draws the legend from the same scale.

**What git keeps.** A round commits the two stills (about 4 KB each on the
baseline) and the files of the charts. The 3D file (940 KB on the baseline)
stays on this computer, in a folder that git ignores, until `nopekit export`
runs the result again. The next build then commits it.

**"From another run".** A still is drawn only from the field files whose
sha256 the result's `summary.json` names. The files on this computer can be
from another run: for example, a check of another design wrote over them
after the result on the page. Then the build draws no new picture, and its
warning says "the file on this computer is from another run: `nopekit check
--force --only cfd.pressure_drop` solves it again", after the name of the
file. The charts say the same when `summary.json` is from another run. The page keeps a still of
another result, and says so, or shows no still. Run that command, then
`nopekit site build`.

**Without ParaView.** The stills and the 3D view need ParaView 6.2.0 through
a `pvbatch62` launcher on PATH (`references/rendering.md`). The pack uses
only the ParaView build it checked, and a renderer control runs one time on
that build before the first still. `nopekit doctor` shows a `pvbatch62` row.
Without ParaView, the charts are drawn and the stills and the 3D view are
not. No status changes, and the build warnings say why.

## Pointing a project at its case

```json
"cfd_case": "cfd/manifold",
"cfd_dp_planes": [
  {"point": [0.010, 0, 0], "normal": [1, 0, 0]},
  {"point": [0.190, 0, 0], "normal": [1, 0, 0]}
],
"cfd_velocity_m_s": 0.4,
"cfd_length_m": 0.006,
"cfd_sound_speed_m_s": 1480,
"cfd_density_kg_m3": 998,
"cfd_residual_target": 1e-6,
"cfd_refinement_ratio": 2,
"cfd_gci_max_pct": 2
```

and one claim, `claims/C1.json`:

```json
{"statement": "The static pressure drop along the manifold is at most 150 Pa",
 "kind": "measurable",
 "acceptance": {"quantity": "pressure drop from cfd", "comparator": "<=",
                "limit": 150, "units": "Pa"},
 "tags": ["pressure-drop"]}
```

Required: `cfd_case`, `cfd_dp_planes`, `cfd_velocity_m_s` (the mean velocity
through the upstream plane), `cfd_length_m` (the hydraulic diameter, 4 x area /
wetted perimeter), `cfd_sound_speed_m_s`, `cfd_density_kg_m3` and
`cfd_gci_max_pct`; each missing one is a skip that names it. The pressure-drop
limit is the claim's, never a parameter. The mesh-quality
limits, the residual target and the refinement ratio have pack defaults, marked
`[pack default]` in the verdict; `cfd_timeout_s` defaults to 600 s.

**The case is a strict subset of OpenFOAM's.** Exactly
`system/{controlDict,fvSchemes,fvSolution,blockMeshDict}`,
`constant/{transportProperties,turbulenceProperties}` and `0/{U,p}`
(`system/decomposeParDict` may sit beside them; `constant/polyMesh` is ignored).
No other file or directory. No directive, except the
`#includeEtc "caseDicts/setConstraintTypes"` that ESI's own 0/ files carry in
`boundaryField`. Macros (`$name`) only in `blockMeshDict`, never a whole
dictionary expanded in place (`$name;`). A quoted (regular-expression) keyword
only under `boundaryField`, `solvers`, `equations` or `fields`. No `#calc`,
`#codeStream`, `coded*` or `libs`. Boundary conditions whose value is written in
the case (`fixedValue`, `zeroGradient`, `noSlip`, `slip`, `inletOutlet`,
`totalPressure`, ...; never `expr*` or a `uniformFixedValue` table). Laminar
`Stokes` only, and `momentumPredictor` on. A 2D case is planar, one cell thick across its `empty` patches (wedges are
refused). Expand a case written otherwise with `foamDictionary -expand` first.
Set `endTime` (with `deltaT 1`) high enough for every level of the ladder.

**Put each plane on a cell face or a cell centre, at every level.** OpenFOAM's
sampled value is exact there and about 1% off a quarter of a cell away, an error
the ladder would read as convergence. Each plane must be normal to an evenly
graded direction of the blocks it crosses (straight edges), and
`cfd.mesh_independence` fails, naming the plane and the level, when it falls
elsewhere. With r = 2 or 3, a plane on a face or a centre of the first mesh
stays on one; the baseline's planes, at 12.5 and 37.5 cells of 50, fail at r =
1.5.

**Choose the refinement ratio for the cost.** At r = 2 the finest of the three
meshes has 16 times the cells of the first in 2D and 64 times in 3D. A 3D case
of 200 000 cells at r = 2 solves a 12.8-million-cell mesh. r = 3 is 81 and 729
times; Celik et al. ask for at least 1.3.

## The physics, in one paragraph

Between parallel plates a gap h apart, developed laminar flow has a parabolic
profile and a pressure gradient dp/dx = 12 mu U / h^2, U the mean velocity (12 nu
U / h^2 in OpenFOAM's kinematic pressure). The
baseline's 10 mm channel of 10 cSt oil at 10 mm/s loses 6.0e-4 m^2/s^2 (0.522 Pa)
over 50 mm. The finite-volume answer on Ny cells across is exactly dp / (1 + 2 /
Ny^2): 2% low at 10 cells, 0.125% at 40, falling as Ny^-2, which is why the
observed order is 2. The flow develops within about one channel height of the
uniform inlet (measured: the planes at 2.5 and 7.5 heights read the developed
answer to 3e-6), so they see none of the entrance. A pressure in m^2/s^2 read as Pa is off by the density, 870 times
for this oil: check the units first.

## Where to look next

- `references/installing.md`: getting ESI OpenFOAM v2606, and checking it.
- `references/rendering.md`: getting ParaView 6.2.0 for the pictures, the
  `pvbatch62` launcher, and the renderer control.
- `references/running-openfoam.md`: how the gates run each tool, and every
  failure mode they read.
- `references/gci.md`: Celik et al.'s procedure, the traps in it, and the
  published examples the arithmetic is held to.
- `references/channel.md`: the baseline case and its known-bad controls.
- `lenses.md`: how to attack a CFD result before anyone builds from it.
