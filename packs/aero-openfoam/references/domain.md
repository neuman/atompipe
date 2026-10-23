# The domain: how far the boundaries must be from the body

`aero.domain` judges the box blockMeshDict spans against the body's bounds. Its
limits come from the urban-flow best-practice guidelines, the only published
rules found that state distances and a blockage for a body in an open stream
over a ground. Read on 2026-10-23 (P0) from Blocken (2015), section 5.1.

## The sources, quoted

**Blocken, B. (2015).** "Computational Fluid Dynamics for urban physics:
Importance, scales, possibilities, limitations and ten tips and tricks towards
accurate and reliable simulations." *Building and Environment* 91:219-245.
doi:10.1016/j.buildenv.2015.02.015. Author manuscript at Lirias (KU Leuven),
section 5.1, page 15.

On **Franke et al. 2007** (COST Action 732, *Best practice guideline for the
CFD simulation of flows in the urban environment*, ISBN 3-00-018312-4), as
Blocken quotes it:

> "The inlet, lateral and top boundary should be at least 5H max away from the
> group of explicitly modeled buildings, where H max is the height of the
> tallest building. The outflow boundary should be at least 15H max away from
> the group of explicitly modeled buildings, to allow for full wake flow
> development. The blockage ratio should not be larger than 3%. Note that this
> guideline is more stringent than the 5% limit imposed in wind-tunnel
> testing."

On **Tominaga et al. 2008** (AIJ guidelines):

> "The guidelines by Tominaga et al. also impose a maximum blockage ratio of
> 3%. They demand the lateral and top boundary of the domain to be at least
> 5H max away, ... and the outflow boundary to be at least 10H max downstream."

Blocken's own addition, the **directional blockage ratio**:

> "This new concept consists of the decomposition of both the blockage ratio
> and the 3% limit in the horizontal and vertical lateral direction, where the
> limit for each is the square root of 3%, i.e. about 17% ... These demands are
> more stringent than Eq. (12) but their satisfaction automatically leads to
> satisfaction of Eq. (12). They should be applied together with the Type-1
> requirements."

with BR = A_building / A_domain (Eq. 12), BR_L = L_building / L_domain and
BR_H = H_building / H_domain (Eqs. 13, 14), L the lateral (cross-stream) size.

The COST 732 PDF itself could not be fetched in P0 (a 404 at its Hamburg
address). The values above are as Blocken quotes them.

## What the gate judges

| Measure | Limit | Source |
|---|---|---|
| upstream: body's front to the inlet | >= 5 H | Franke 2007 |
| downstream: body's back to the outlet | >= 15 H | Franke 2007 (AIJ: 10 H; the stricter is taken) |
| side: the nearer of the two | >= 5 H | Franke 2007, AIJ |
| top | >= 5 H | Franke 2007, AIJ |
| bottom (only with no ground) | >= 5 H | the top's rule, for a body in free air |
| blockage: body box's frontal area / domain section | <= 3% | Franke 2007, AIJ |
| lateral blockage: body width / domain width | <= 17% | Blocken 2015 |
| vertical blockage: body top over ground / domain height over ground | <= 17% | Blocken 2015 |

**H** is the height of the body's top over the ground: the sources' H_max, "the
height of the tallest building", for a body that stands on the ground. A body
over the ground (the spheroid baseline) is measured the same way, to its top;
that is the stricter reading. A body in free air (no wall on the box's bottom)
uses its own height.

**The frontal area is the body box's**, width times height. It is an upper
bound of the true frontal area (the motorBike: 0.92 m^2 for the box, 0.644 m^2
rasterised at 1 mm in P0), so a blockage that passes on the box passes on the
body. No OpenFOAM tool reports a projected area, and the pack computes none.

**The body's bounds** are the dictionary's for a `searchableSphere` (origin
plus each of its three radii) or a `searchableBox`, and OpenFOAM's
`surfaceCheck` "Bounding Box" line for a surface file. `surfaceCheck` writes
about 23 files where it runs (P0), so the gate runs it in its own scratch
directory. A body that reaches below a ground wall by up to 1% of H counts as
resting on it (the motorBike's tyres: 4.2e-5 m, its contact patch).

## The motorBike tutorial, measured (P0)

Tutorial domain: blockMeshDict (-5 -4 0) to (15 4 8); body H 1.3515 m, width
0.6826 m, from `surfaceCheck` on `motorBike.obj.gz`.

| Measure | Tutorial | Limit | Result |
|---|---|---|---|
| upstream | 3.48 H | >= 5 H | fails |
| downstream | 9.80 H | >= 15 H | fails |
| side | 2.70 H | >= 5 H | fails |
| top | 4.92 H | >= 5 H | fails by 0.11 m |
| blockage (box) | 1.44% | <= 3% | passes |
| lateral / vertical blockage | 8.5% / 16.9% | <= 17% | passes (vertical by 0.6%) |

The demo project grows its domain, never the limit: x -8 to 24, y -8 to 8, z 0
to 12, block (32 16 12) (P0's smallest box that meets every limit with 1 m
cubes and whole-number refined blocks).

## The baseline spheroid

Domain x -4 to 10, y -3 to 3, z 0 to 4; body 1 m long, 0.25 m across, top 0.525
m over the ground. Upstream 7.62 H, downstream 17.1 H, side 5.48 H (the nearest,
9.5% inside), top 6.62 H, blockage 0.26%, lateral 4.2%, vertical 13.1%.
`short_wake` moves the outlet to x 7.85 m: downstream 13.0 H, 15% short of 15 H.
