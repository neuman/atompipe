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
     requires; `interpolate true`), written every iteration;
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
`.dat` files. A converged line is not enough: the pressure drop's remaining
change must be under 0.1% of it. Over the last 20 iterations, a pressure drop
that is not monotone may still swing by its largest movement in the last 10; a
monotone one is a geometric tail, its contraction per iteration read from the
step sizes in each window of 10 (the slower of the two), and what is to come is
the last step x q / (1 - q), never less than the last window's movement. U
relaxed to 0.03 makes the normalised residuals tiny while the number creeps: one
such run passed a 10-iteration stillness test 9.7% from its converged value.

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
# Region type :   sampledSurface nopekit_upstream
# Faces           : 20
# Area            : 1.0000000000e-05
# Time            	areaAverage(p)    	areaAverage(U)
91                	8.8235294768e-04  	(1.0000e-02 1.2e-09 0)
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
