# Wall treatment: y+ and the wall function

## The model at the wall

The pack runs k-omega SST with a wall function on the body: `nutUSpaldingWallFunction`
for nut (Spalding's single formula for the velocity profile from the wall to
the log layer: D. B. Spalding, "A single formula for the law of the wall",
*J. Appl. Mech.* 28(3):455-458, 1961), `omegaWallFunction` and
`kqRWallFunction`. The tutorial uses `nutkWallFunction`; the pack accepts both.

Spalding's formula holds through the viscous sublayer, the buffer layer and the
log layer, so the first cell may sit anywhere from y+ about 1 to the top of the
log layer. Above it, the first cell is outside the boundary layer the function
describes.

## The guard (aero.wall_treatment, P6)

At least 90% of the body's area has y+ at most 300: the top of the log layer
(Pope, *Turbulent Flows*, 2000, Table 7.1: the log-law region from y+ about 30
to y/delta about 0.3; 300 is the common working ceiling for wall functions). The
area is the body's, weighted by face area.

**The route.** OpenFOAM's `yPlus` function object writes y+ on the wall; the
`surfaces` object samples it on the body patches (`interpolate false`: cell
values) to a vtp, and the gate sums the face areas with y+ <= 300 over the total.
It cross-checks the vtp's area and its area-mean y+ against OpenFOAM's own
`surfaceFieldValue` `areaIntegrate` and `areaAverage(yPlus)`: 0.8% and 0.1%
apart on the motorBike's L0, exact on a box.

**What failed in P0.** The `expressions` route, `(yPlus <= 300) ? 1 : 0` then
`areaAverage`, returned 1.0 for every case: the new field's wall patches are
`calculated` and are set to the cell values next to them, and yPlus's cell
values are 0, so the wall value never reaches the indicator (fvExpressionField.C
v2606). It is not used.

## What P0 measured

| | L0 | L1 | L2 |
|---|---|---|---|
| motorBike, y+ <= 300 (area) | 96.4% | 99.4% | 99.97% |
| bands < 5 / 5-30 / 30-300 / > 300 | 1.0 / 27.9 / 67.5 / 3.6% | 2.4 / 39.9 / 57.2 / 0.6% | 3.7 / 49.2 / 47.1 / 0.03% |
| body area in the vtp (m^2) | 11.340 | 11.722 | 11.955 |

Spheroid baseline: 100% at every level (mean y+ 121, 79, 53). Its `no_layers`
control (addLayers false) gives 35.6%.
