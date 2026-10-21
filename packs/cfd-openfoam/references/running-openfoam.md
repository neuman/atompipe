# How the gates run OpenFOAM, and what they read

Every line here was measured on ESI OpenFOAM v2606 while the pack was written.

## The run

1. **Stage.** Copy the case's `0/`, `constant/` (not `constant/polyMesh`) and
   `system/` into an empty directory under the gate's out directory. Nothing an
   earlier run left (time directories, `postProcessing/`, `dynamicCode/`,
   `processor*`) is copied. A re-run in a used directory writes
   `surfaceFieldValue_0.dat` beside the old file, and a reader can take the old one.
2. **Edit the copy** (`cfd.converged` and after):
   - remove every `functions` entry from `system/controlDict` and add the pack's
     two `surfaceFieldValue` function objects, `nopekit_upstream` and
     `nopekit_downstream`: `areaAverage` of `p` and `U` on a sampled plane
     (`planeType pointAndNormal`, the point inside `pointAndNormalDict`, as v2606
     requires; `interpolate true`), written every iteration at `writePrecision
     12` (13 significant digits, whatever the case's own controlDict says);
   - replace `SIMPLE/residualControl` in `system/fvSolution` with `p` and `U` at
     `cfd_residual_target`;
   - for a refined level, multiply each block's cell counts in
     `system/blockMeshDict` (half up, at least one more cell than the level
     below; a 2D case's one-cell direction, found from the geometry, stays one).
3. **Read the copy as OpenFOAM reads it.** `foamDictionary -expand` on the
   controlDict, fvSolution, transportProperties, turbulenceProperties and
   fvSchemes. The expanded `functions` must be exactly the pack's two objects,
   key for key; `residualControl` exactly the pack's; nu, the laminar model,
   the iteration budget and the convection schemes what `cfd.case_readable`
   read. Any difference is an error. Why: OpenFOAM MERGES a repeated dictionary
   keyword, so a `functions` dictionary that reached the copy any other way
   would add its keys (a `scaleFactor`, a `weightField`) to the pack's, and a
   text edit cannot see that.
4. **Run** `blockMesh`, `checkMesh` (its direction count must be the case's
   dimension) and `simpleFoam`, from `$FOAM_APPBIN`, with the case as the
   working directory and the environment `etc/bashrc` made (sourced from a bare
   environment; 0.2 to 0.5 s). Each log is written to `log.<tool>` in the
   stage. simpleFoam's own `SIMPLE: convergence criteria` block must name p and
   U at the pack's target.

## Exit codes and failures

| What happened | Exit | What the gate does |
|---|---|---|
| FOAM FATAL ERROR or FATAL IO ERROR | 1, the message on stderr | error, with the message |
| a bad option | 1, the message on stdout | error |
| divergence, with trapping on | -8 (SIGFPE), a stack trace, no FATAL text | error: "SIGFPE ... divergence" |
| killed | -15, -2 or -9, no `End` | error |
| past `cfd_timeout_s` | none | skip: nothing was shown |
| simpleFoam ran out of iterations | **0**, `End` printed | `cfd.converged` fails: no converged line |
| checkMesh found a bad mesh | **0**, `Failed N mesh checks.` | `cfd.mesh_quality` fails on the text |

With `FOAM_SIGFPE=false`, a diverging run puts NaN in its residual lines and v2606
stops only because it cannot read the word `nan` back: not something to rely on.
So trapping is forced on.

## checkMesh

The gate reads the text, never the JSON. `-writeChecks json` disagrees with the
text on v2606: a 75.96-degree mesh is `Mesh OK.` in the text and `"fail"` in the
JSON; with `-meshQuality` the text says `Failed 1` and the JSON says `"pass"`.

What checkMesh fails on, its limits fixed in `primitiveMeshCheck.C`: skewness over 4
(exactly 4 reads OK), aspect ratio over 1000, a volume at or below 0, wrongly
oriented face pyramids, non-orthogonality of 90 degrees or more. Non-orthogonality
from 70 to 90 is a warning only (`*`), never a failed check (`***`). So
`cfd.mesh_quality` holds the values to the project's own limits too.

Lines read:

```
    cells:            500
    Mesh has 2 geometric (non-empty/wedge) directions (1 1 0)
    Max aspect ratio = 2 OK.
 ***High aspect ratio cells found, Max aspect ratio: 5000, number of cells 2
    Mesh non-orthogonality Max: 75.9638 average: 75.9638
    Max skewness = 4.142e-14 OK.
Mesh OK.
Failed 4 mesh checks.
```

checkMesh is not read-only: it writes `constant/polyMesh/sets/` even unasked.
It runs on the staged copy.

## simpleFoam

A converged run:

```
Time = 91
smoothSolver:  Solving for Ux, Initial residual = 9.1e-07, Final residual = ..., No Iterations 2
...
SIMPLE solution converged in 91 iterations
...
End
```

The gate reads the converged line, the first `Initial residual` of each field in
the last iteration (p and a U component must both be there), and the pack's
`.dat` files. A converged line is not enough: the pressure drop's estimated
remaining change must be under 0.1% of it.

U relaxed to 0.03 makes the normalised residuals tiny while the number creeps:
one such run passed a 10-iteration stillness test 9.7% from its converged value.
The estimate that replaced that test read real v2606 histories as settled up to
23.4% from their converged value (a laminar pitzDaily under slow relaxation).
The current estimate reads no point of those histories as settled more than
0.1% from converged.

### The estimate

The estimate is Eca and Hoekstra's (Computers & Fluids 38, 2009, Eq. 9). A
least-squares line through the log of the change per iteration gives the rate.
The sum of the geometric tail at that rate, times 1.25, is the change still to
come. `gates/_iter.py` adds these rules, each with the history that made it
necessary:

- The rate is the upper 95% bound of the fitted rate. A fit has 8 changes or
  more.
- The gate fits windows of 8, 16, 32, ... changes and the whole history, each
  to the last change above round-off, and uses the largest result.
- Each window fits the largest change from each iteration to the end. Thus a
  decaying oscillation reads as a decay.
- The rate of the last 8 changes must agree with the rate of the last 16, within
  two combined standard errors. A slower rate gives no estimate, and the run fails. A
  faster rate also gives no estimate while the last change is above 1e-7 of the
  value, if it is faster by more than 0.1% of the rate.
- A change under 1e-8 of the value is round-off. When the last 8 changes or more
  are round-off, the estimate is the largest swing in that tail. This rule does
  not apply when one of the 16 changes before the tail is exactly zero: the
  history then moves in steps of one printed digit.
- A second reading uses no model of the single changes. It continues the drift
  of the means of the last three sixths of the run, and of the slopes of its
  last two quarters, and the gate uses the larger value.
- A value that is not a finite number gives no estimate. The gate refuses a
  last value of inf before it compares, because inf is less than 0.1% of inf.

The estimate needs at least 17 values. A converged run with OpenFOAM's default
precision (7 significant digits) can fail here, because its last changes are
steps of one printed digit. That is why the pack sets `writePrecision 12`.

### What the estimate cannot see

Each of these histories reads settled at some iterations while it is more than
0.1% from the value it converges to. The numbers are from the synthetic
histories of GitHub #15, Phase 0, and from its review. Each item gives every
measured history of its kind, so its largest error is the largest that was
measured.

- **An overshoot at its turning point.** Two modes of opposite sign cancel, and
  the value stops at an extremum before it turns back. At the extremum the value
  does not move, and no estimate from the history can tell it from the limit.
  The error is then the distance from the extremum to the limit. The three
  overshoots of Phase 0 read settled at 2 points up to 0.27%, at 1 point at
  0.70% and at 2 points up to 0.20%. In the review, 37 of 84 overshoots with
  rates from 0.7 to 0.9995 per iteration read settled at 187 points, from 62
  iterations before the extremum to 4 after it, up to 29%
  (`1 + 0.25 x 0.7^n - 0.3 x 0.999^n` at iteration 19).
- **A slow mode under a fast oscillation.** The fit follows the peaks of the
  fast mode. `1 + 0.005 x 0.998^n + 0.05 x 0.9^n (-1)^n` reads settled at 1
  point at 0.43%. `1 + 0.5 x 0.8^n cos(0.9 n) + 0.003 x 0.995^n` reads settled
  at 12 points up to 0.25%. `1 + 0.5 x 0.8^n cos(0.9 n) + 0.002 x 0.999^n` reads
  settled at 23 points from iteration 40 to 70, up to 0.20%.
  `1 + 0.005 x 0.998^n + 0.01 x 0.99^n sin(0.7 n)` reads settled at 2 points up
  to 0.10%.
- **A rate that becomes slower in the last few iterations.** The shortest
  window does not see it yet. A rate that changes from 0.85 to 0.995 per
  iteration at iteration 40 reads settled at 5 points up to 1.51%. A rate that
  changes from 0.7 to 0.998 at iteration 30 reads settled at 13 points up to
  0.39%.
- **A drift under 1e-8 of the value per iteration.** The estimate calls it
  round-off. A ramp of 5e-9 per iteration reads settled at its first 787
  points. At that rate, the value needs 200 000 iterations to move 0.1%.
- **A change after the last iteration.** No estimate made from the history can
  see it. A decay that later rises (MARIN's df_iter1537) reads settled at 14
  points, up to 1.36%.
- **A fixed point that moves with the under-relaxation.** The estimate gives
  the distance to the value this run converges to. It cannot tell if another
  relaxation gives another value.

Two costs are on the safe side (a run that has settled reads not settled). A
history printed to 7 significant digits almost never reads settled. The
turbulent pitzDaily runs never read settled, even after they settle; this pack
is laminar only.

### Against the authors' tool

MARIN's `iterative_error` (closed) adds a correction from Eca and Hoekstra's
2006 paper in SNH. That paper was not read for this pack, so the comparison is
of the numbers only, and the formula is not the tool's. On the tool manual's
Table 1, this estimate is 0.71 to 2.00 times the tool's (median 0.93) on the 8
items with 8 changes or more. It is below the tool on items 1, 2, 3 and 6. Eq. 9
without the rules above is 0.32 to 0.70 times the tool's.

### What the evidence holds

`cfd.converged` writes `history.csv` beside its `summary.json`.
`cfd.mesh_independence` and `cfd.pressure_drop` write `history_level0.csv`,
`history_level1.csv` and `history_level2.csv`, one for each mesh. Each row holds
`iteration` (from 1), the pressure drop (`dp_m2_s2`; `dp_pa` in
`cfd.pressure_drop`) and `change_pct`: the change from the iteration before, as
a percentage of the last value. The first row has no `change_pct`.

`summary.json` holds the estimate as `iterative_error_pct`, a percentage of the
last value (in `levels` for a ladder, one for each mesh), and the tolerance as
`convergence_tol_pct` (0.1). `iterative_error_pct` is `null` when there is no
estimate. A chart of the history uses these numbers and calculates none. The
history is a CSV file because the site's prose check reads each number in a
JSON evidence file as a match for a number in the text, in any unit.

## Where the planes sit

OpenFOAM's sampled plane (`interpolate true`) reads a value that is exact when
the plane lies on a cell face or a cell centre and about 1% off a quarter of a
cell away (75 cells along the baseline channel). On a ladder that moves the
planes through the cells, that error changes from level to level, and the GCI
reads it as convergence: one ladder at r = 1.7 passed a band 0.34% under the
exact pressure drop. So `cfd.mesh_independence` requires each plane to be normal
to an evenly graded direction of every block it crosses, those blocks to have
straight edges, and the plane to fall on a face or a centre of the cells at
every level, and fails, naming the plane and the level, before it runs anything.
With r = 2 or 3, a plane on a face or a centre of the first mesh stays on one.

```
# Region type :     sampledSurface nopekit_upstream
# Faces             : 20
# Area              : 1.000000000000e-05
# Scale factor      : 1.000000000000e+00
# Time              	areaAverage(p)	areaAverage(U)
91                  	8.823530330387e-04	(9.999996662583e-03 8.756808141046e-14 0.000000000000e+00)
```

A plane whose area is 0 or not a number cuts no part of the mesh: an error. So is
a `Scale factor` other than 1, and an iteration written twice or out of order. The
`U_converged` column of a `solverInfo` file is the LINEAR solver's, not
residualControl's: it reads `false` on every row of a converged run, so it is not
read.

## The banner

```
Build  : _481094f-20260618 OPENFOAM=2606 version=2606
trapFpe: Floating point exception trapping enabled (FOAM_SIGFPE).
allowSystemOperations : Disallowing user-supplied system call operations
```

A run whose banner lacks any of the three is an error. There is no `-version`
option (tools reject it, exit 1) and no `foamVersion` command on v2606;
`foamEtcFile -show-api` prints the API.

## Times (the baseline, one core)

blockMesh and checkMesh on 500 cells: about 0.05 s each. simpleFoam on 500, 2000
and 8000 cells: about 0.2, 0.5 and 1 s. The whole selftest: about 10 s (load
moves it).
