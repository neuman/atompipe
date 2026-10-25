# Wall treatment: y+ and the wall function

## The model at the wall

The pack runs k-omega SST with a wall function on the body: `nutUSpaldingWallFunction`
for nut (Spalding's single formula for the velocity profile from the wall to
the log layer: D. B. Spalding, "A single formula for the law of the wall",
*J. Appl. Mech.* 28(3):455-458, 1961), `omegaWallFunction` and
`kqRWallFunction`. The tutorial uses `nutkWallFunction`. The pack accepts it
on the ground, and `aero.wall_treatment` errors, before any tool runs, on a body
whose `0/nut` condition is not Spalding's: the guard's band below is his
formula's. It reads the condition under `aero_body_group`, and any other plain
key of `0/nut` that is not a patch of the box must state the same, because
OpenFOAM sets a patch by its own name, then by its groups (such as `wall`),
before a regular expression.

Spalding's formula holds through the viscous sublayer, the buffer layer and the
log layer, so the first cell may sit anywhere from y+ about 1 to the top of the
log layer. Above it, the first cell is outside the boundary layer the function
describes.

## The guard (aero.wall_treatment)

At least 90% of the body's area has y+ at most 300 (`YP_IN_MIN`, `YP_HI`).
300 is the top of the log layer at these Reynolds numbers: Pope, *Turbulent
Flows*, 2000, sec. 7.1.4 and Table 7.1, give the log-law region as y+ > 30 and
y/delta < 0.3. Above it the first cell's centre is in the outer layer, which
the wall function does not describe. The share is of the body's area, so the
small faces at an edge count by their size.

Rejected: 100% (every snapped corner of the motorBike past 300 would fail a
mesh whose drag the wall function does describe); 50% (half of the body could
sit outside its boundary layer); a floor at 30 (Spalding's formula holds below
it).

**The run.** The gate solves the base mesh again with the pack's wall
function objects (`gates/_fo.py`, `wall_functions`): forceCoeffs, solverInfo,
then at the last iteration `yPlus`, a `surfaces` object that writes the body
patches with y+ on each face (`interpolate false`: the face's own wall value),
and a `surfaceFieldValue` with `areaAverage(yPlus)` over the body group. The
run is held to aero.converged's rule too; a run that does not settle here is
an error.

**The route.** The gate reads the surface file (`_par.wall_surface`, standard
library: VTK XML, inline base64, uncompressed). The area of each face is its
vector area, half the norm of the sum of its edges' cross products. That is
the area OpenFOAM gives a face (`magSf`), planar or not. It sums the area with
y+ <= 300 over the total.

**The cross-check.** The surface's face count must equal OpenFOAM's `# Faces`.
Its area and its area-mean y+ must be within 1e-4 of OpenFOAM's `# Area` and
`areaAverage(yPlus)` (`WALL_AGREE`). Otherwise the gate errors, naming both.
Measured:

| Case | faces | area, gate / OpenFOAM (m^2) | area-mean y+, gate / OpenFOAM |
|---|---|---|---|
| motorBike L0 (P0) | 44 120 / 44 120 | 11.2488272 / 11.2488272 (2.9e-9 apart) | 87.2338338 / 87.2338341 (3.5e-9) |
| spheroid L0 (P6) | 2 396 / 2 396 | 0.63138190 / 0.63138190 (4e-9) | 121.153680 / 121.153680 |

The surface holds 32-bit floats, so the two are never exactly equal.

**What failed in P0.**

- The `expressions` route, `(yPlus <= 300) ? 1 : 0` then `areaAverage`,
  returned 1.0 for every case. The new field's wall patches are `calculated`
  and are set to the cell values next to them, and yPlus's cell values are 0,
  so the wall value never reaches the indicator (fvExpressionField.C v2606).
- ParaView's `CellSize` sums each face's triangles. On the motorBike's
  non-planar faces that is 11.340 m^2, 0.8% more than OpenFOAM's 11.249 m^2.
  The first draft of this page gave that 0.8% as the gate's own error.

## What P0 measured

| | L0 | L1 | L2 |
|---|---|---|---|
| motorBike, y+ <= 300 (area) | 96.4% | 99.4% | 99.97% |
| bands < 5 / 5-30 / 30-300 / > 300 | 1.0 / 27.9 / 67.5 / 3.6% | 2.4 / 39.9 / 57.2 / 0.6% | 3.7 / 49.2 / 47.1 / 0.03% |
| body area, vector area of each face (m^2) | 11.249 | 11.659 | 11.906 |

Spheroid baseline (P6, the gate on the real tools): 100% at every level of
its ladder, area-mean y+ 121 on the base mesh. Its `no_layers` control
(`addLayers false`) gives 35.58%, with y+ above 300 on 64.4% of the body:
fails, 15% past the limit is 78.3%. The 1.125 times larger body of the
`bigger_body` control gives 100%: the guard passes it, so the edge from
`aero.drag_area` is isolated.

The motorBike numbers above are on the tutorial's 2-layer meshes and its own
quality dictionary. The pack meshes to ESI's `meshQualityDict`, with fewer
layers. Measured (P6, the demo `examples/motorbike` on 6 ranks, the gate on the
real tools): 351 753 cells, layers on 42.3% of the body's faces, y+ at most 300
on 95.04% of 11.2435 m^2 (bands 0.555 / 22.4 / 72.1 / 4.96%), area-mean y+ 101.9
against OpenFOAM's 101.9: the guard passes, with a margin of 1.06.
