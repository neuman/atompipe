# Meshing: snappyHexMesh as aero-openfoam runs it

## The sequence

On a copy of the case under the gate's out directory:

1. The pack writes its own `system/meshQualityDict`, `system/decomposeParDict`
   (`hierarchical`, `aero_ranks` ranks split as (nx ny 1), x first), and in `snappyHexMeshDict` its own
   `meshQualityControls`, the cell cap `maxGlobalCells`
   (`aero_max_global_cells`) and `maxLocalCells` 2e6 (not a cap: the count per
   rank past which snappyHexMesh balances before it refines; no project states
   it).
   `controlDict` gets `writePrecision 12`.
2. `foamDictionary -expand` of every dictionary the reader read (controlDict,
   fvSchemes, fvSolution, snappyHexMeshDict, transportProperties,
   turbulenceProperties, surfaceFeatureExtractDict) and of the two the pack
   wrote: each must equal the reader's own parse of the same file. blockMeshDict
   (its macros are expanded) is held instead to what blockMesh reports: its cell
   count and its bounding box.
3. `blockMesh`, then `surfaceFeatureExtract` when the body is a surface file.
4. `decomposePar -force`.
5. The rank probe: `mpirun ... /bin/sh -c 'printf ...'` asks each rank for its
   rank, its HOME and its `FOAM_SIGFPE`.
6. `mpirun --oversubscribe -np N -x HOME -x FOAM_SIGFPE snappyHexMesh -overwrite
   -parallel`.
7. `mpirun ... checkMesh -meshQuality -constant -parallel`.

## The quality limits

ESI v2606's own `etc/caseDicts/meshQualityDict`, value for value
(`gates/_fo.py`, `QUALITY`): maxNonOrtho 65, maxBoundarySkewness 20,
maxInternalSkewness 4, maxConcave 80, minVol 1e-13, minTetQuality 1e-15, minArea
-1, minTwist 0.02, minDeterminant 0.001, minFaceWeight 0.05, minVolRatio 0.01,
minTriangleTwist -1, minEdgeLength -1; with snappyHexMesh's nSmoothScale 4 and
errorReduction 0.75 (the tutorial's).

snappyHexMesh meshes to these limits and `checkMesh -meshQuality` judges
against them, so the mesher and the judge hold one set of numbers. checkMesh
prints them back in its "Checking faces in error" block; the gate holds the
printed thresholds to the pack's (nine lines, `_fo.CHECKED`) and errors when
they differ.

**What P0 measured.** The motorBike tutorial's own dict sets `minFaceWeight
0.02` and has a `relaxed { maxNonOrtho 75; }` for the layer stage. Its meshes
pass that dict and fail the etc dict: 1 095 faces at L0 and 2 084 at L1 with
interpolation weight under 0.05. Meshed with the etc dict staged before
snappyHexMesh, L0 had 346 181 cells and 0 faces in error, but layer coverage
fell from 56.5% to 41.5%.

**Plain checkMesh is never the judge.** Its skewness limit is fixed at 4 and
fails every motorBike mesh ("Failed 1 mesh checks": skewness 8.13 on 29 faces at
L2). Its verdict line is not read.

## What fails `aero.mesh_quality`

- `checkMesh -meshQuality` counts any face in error. The value is the count,
  against 0.
- snappyHexMesh reached a cell cap: "No cells marked for refinement since
  reached limit N". The mesh is not the one its dictionary asks for. P0: the
  spheroid capped at 20 000 cells ended at 27 429 cells (27 332 on 4 ranks, decomposed `hierarchical`),
  layers on 39% of its faces against 100%, and snappyHexMesh still printed
  "Finished meshing without any errors". The value is the cell count against
  the cap.
- snappyHexMesh did not print "Finished meshing without any errors", or its
  final check counted a face in error.

On a pass, the value is the cell count against `aero_max_global_cells`.

**What does not fail it.** A relaxed quality control in the case's own
snappyHexMeshDict: the pack replaces the controls. P0 tried the design's first
known-bad controls: `maxNonOrtho 180` and all ten controls relaxed gave 0 faces
in error on the spheroid (a smooth body snaps cleanly), and `nSolveIter 0` gave
0 faces in error on and off the grid. Neither is a control.

## Layers

Layer coverage is the last "Extruding N out of M faces (x%)" line of
snappyHexMesh's log. It is reported, never judged here: what layers are for is
y+, which `aero.wall_treatment` judges. P0: spheroid 100%; motorBike L0 56.5%,
L1 64.8%, L2 71.5% (tutorial dict).

## Ranks and reproducibility

- Open MPI counts physical cores. On a 7-core machine `mpirun -np 10` stops
  with "There are not enough slots available"; the pack always passes
  `--oversubscribe`.
- **Decompose with `hierarchical`, not `scotch`.** P0 found two identical
  parallel runs giving the same cell count and other processor meshes, and read
  it as snappyHexMesh. P3 measured the cause: `scotch` split one bit-identical
  mesh three ways in three runs (10445/10287/10342/10479 cells, then
  10442/10316/10459/10336, ...), and the drag area's U_I moved with it (0.0065%,
  0.0063%, 0.0064%). A verdict whose bytes move on identical inputs is "two
  outcomes for one rho" to the verdict cache. With `hierarchical`, three runs of
  snappyHexMesh in parallel and of the solve gave the same meshes and the same
  history, bit for bit. The rank count still moves the mesh (spheroid: 41 574
  cells on 4 ranks with `hierarchical`; 41 546 to 41 588 with `scotch`).
- A run on a rank with another HOME hung in P0 with the master's banner still
  saying "Disallowing". The rank probe asks every rank; the timeout
  (`aero_timeout_s`) kills the whole process group.

## Timings (P0 and P3)

| Case | Cells | snappyHexMesh |
|---|---|---|
| spheroid L0, 4 ranks, an idle machine | 41 574 | 2.5 s |
| spheroid L0, 2 ranks | 41 574 | 12.6 s |
| motorBike L0, 12 ranks (tutorial dict) | 354 182 | 89.5 s |
| motorBike L0, 2 ranks (etc dict) | 346 181 | 339 s |
| motorBike L1 / L2, 12 ranks | 909 730 / 2 618 934 | 199 s / 529 s |

## The mesh ladder (aero.mesh_independence, aero.drag_area)

Three meshes of one case: the case's own (L0) and two refinements.

- **The background block** is multiplied by `aero_ladder_ratio` (default 1.5)
  per level along every direction, rounded half up and at least one cell more
  than the level below: the spheroid's (28 12 8), (42 18 12), (63 27 18); the
  demo's (32 16 12), (48 24 18), (72 36 27). snappyHexMesh refines by levels of
  the background cell, so every cell of the mesh scales with it.
- **A `distance` refinement region's distances** are divided by r^k, so the
  band of finest cells around the body holds the same number of cells at every
  level (the spheroid's 0.03 m becomes 0.02 and 0.0133333 m). They are written
  to six significant digits, the precision `foamDictionary -expand` prints:
  the first run wrote 0.019999999999999997, OpenFOAM read 0.02, and every
  refined level was refused as another case. An `inside` region is a place and
  is kept as written. Rejected: distances kept in metres (the band would grow
  from about 2 to 4.3 cells across the spheroid's ladder: three meshes not
  refined alike).
- **Layers in metres are refused** (`relativeSizes false`): they would not
  scale with the cells.
- Each level is meshed as `aero.mesh_quality` meshes (the pack's quality limits,
  the cell cap) and must pass its rule. Then, **before any solve**, the cells
  must increase and each effective ratio, (N_fine / N_coarse)^(1/3), must be at
  least 1.3 (Celik et al. 2008, Step 2). A ladder that fails here costs three
  meshes and no solve.

Measured (P6, the spheroid, 4 ranks, `hierarchical`):

| Ratio | Cells (L0, L1, L2) | Effective ratios |
|---|---|---|
| 1.5 | 41 574, 132 094, 386 302 | 1.470, 1.430 |
| 1.3 (`narrow_ladder`) | 41 574, 78 726, 176 196 | 1.237, 1.308: fails before any solve |
| 1.5, radii x1.125 (`bigger_body`) | 44 626, 141 285, 408 434 | 1.469, 1.443 |

P0's box at ratio 1.3 gave 1.249 and 1.293; the motorBike's tutorial ladder at
1.5, 1.42 and 1.37.
