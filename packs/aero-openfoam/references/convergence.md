# Convergence: when a steady run of an external flow has settled

## The iterative uncertainty

A steady RANS run of a body in a stream rarely settles to one value. Its drag
area swings about a mean, often for ever: a limit cycle, the steady solver's
trace of an unsteady wake. The pack measures how much it swings.

**ITTC 7.5-03-01-01** (*Uncertainty Analysis in CFD Verification and Validation,
Methodology and Procedures*, International Towing Tank Conference, 2017
revision; its iterative-convergence step) gives, for an oscillating history,
the iterative uncertainty as half the range between the maximum and the minimum
of the oscillation:

    U_I = (S_U - S_L) / 2

The pack takes S_U and S_L over the last W iterations of the drag area
(`_par.half_range`) and states U_I in percent of the window's mean.

Rejected: cfd-openfoam's estimate of the change still to come (`_iter.py`, Eca
and Hoekstra's): it reads a steady decay, and an external flow's history is a
limit cycle, which it calls "still moving" for ever. The copy of `_iter.py` is
kept byte-identical for its drift test only.

## The window and the limit

The window is 100 iterations. The ceiling is `aero_iter_unc_max_pct`, 1% by
default (the author's choice, D3: common RANS verification practice), and the
baseline states it.

A run shorter than the window fails: "the window never filled". It is not an
error: the run did what it was told and showed nothing.

## What P0 measured (v2606, 2026-10-23)

motorBike, tutorial settings, Spalding wall function, 1500 iterations:

| | L0 | L1 | L2 |
|---|---|---|---|
| cells | 354 182 | 909 730 | 2 618 934 |
| CdA, mean of the last 100 (m^2) | 0.307547 | 0.296363 | 0.300742 |
| U_I at W = 100 | 0.24% | 0.83% | 1.09% |
| U_I at W = 200 | 0.27% | 1.02% | 1.84% |
| first window end with U_I <= 1% | 148 | 204 | 926 |
| U_I <= 1% on every later end from | 148 | 1417 | never |
| omega bounded, iterations of 1500 | 1500 | 6 | 706 |

L0 settles by about 150 iterations. L1 and L2 keep a limit cycle that does not
decay: a longer run does not help. The motorBike's mesh-independence study
therefore fails at L2, and the demo ships C1 Failing at
`aero.mesh_independence` with its reason (D6).

The spheroid baseline settles fast: U_I 0.002% at L0 (W = 100, end 400),
settled from iteration 134; L1 and L2 from 145 and 127. As the selftest runs it
(4 ranks, `hierarchical`, end 300): U_I 0.0148%, the drag area 0.00443257 m^2,
the same to the last digit in three runs.

**Where a cut-short run lands.** On the spheroid, endTime 110 gives U_I 11.1%;
every end up to 131 gives at least 1.15%. On the motorBike L0, every end up to
130 gives at least 1.15%.

## Drift

The half-range misses a slow drift: on the motorBike's L0 the window mean moved
+0.59% between iteration 500 and 1000 while U_I at 500 was 0.27%. The pack
reports the drift (the mean of the last window against the mean of the one
before) beside U_I. No source found sets a limit on it, so it is reported, not
judged.

## Residuals

The pack does not judge residual levels: a limit cycle holds them up. It judges
only a residual that climbs at the end: the last iteration's initial residual of
any field more than 10 times the least in the window is a run that diverges or
restarts. P0 measured at most 5.7 times on every spheroid and motorBike run, at
every end from 110 to 1500.

## omega bounding

k-omega SST clips omega where it goes negative ("bounding omega, min: ..."). The
motorBike's L0 does this on every iteration (min -1.75e5) and still settles to
0.24%. The count of bounded iterations is reported, not judged.

## The grid convergence index (aero.mesh_independence)

Each level of the ladder (`references/meshing.md`) is solved and held to the
rule above. The drag area of each level is its window's mean. The pack then
follows Celik et al. 2008 (ASME J. Fluids Eng. 130:078001; `gates/_gci.py`,
cfd-openfoam's copy, byte for byte), with the cell counts in 3D:

1. **Monotone convergence** (eps32/eps21 > 0 in Celik's numbering, finest
   first). Oscillatory or divergent fails: Richardson extrapolation needs
   monotone convergence. This is how the motorBike demo reads Failing (P0:
   0.3075, 0.2964, 0.3007 m^2).
2. **A difference inside the noise is unresolved**: the noise is the largest
   U_I of the three levels.
3. **The observed order p at least 0.95** (cfd-openfoam's `P_MIN`).
4. **The finest level's U_I at most a tenth of |eps21|** (Celik App. A).
5. **The band.** With p up to the formal order + 0.05 (the formal order is 2
   for a second-order `div(phi,U)`, 1 for upwind), Celik's Eq. 7 at the
   observed order with Fs = 1.25. Above it, the band at the formal order with
   Fs = 3: GCI = 3 |eps21 / phi1| / (r21^2 - 1), Roache's two-grid GCI with an
   assumed order on the two finest meshes (Roache 1998, *Verification and
   Validation in Computational Science and Engineering*; `_gci.gci_two_grid`).
   The rule is Eca and Hoekstra 2014 (J. Comput. Phys. 262:104-130), sec.
   2.4.1: "A value of p greater than the formal order of grid convergence
   (i.e. p > 2) is likely to cause too small error estimates. In that case,
   delta_RE is dropped and replaced by delta_1 or delta_2"; and their summary:
   "If 0.5 <= p < 2.1 and sigma < Delta_phi, Fs = 1.25. Otherwise, Fs = 3."
   The pack takes their delta_2 (the error at the formal order) on the two
   finest meshes. Rejected: their least-squares choice between delta_1 and
   delta_2 (it "relies on the availability of at least four data points");
   refusing the ladder (every honest ladder of the baseline was refused); the
   observed order with Fs 1.25 (their "too small").
6. **The GCI of the finest at most `aero_gci_max_pct`.** No source sets one
   value for every body. The demo states 5% (D3, the author's choice); the
   baseline states 20% (its band at the formal order is 15.7%).

The asymptotic-range ratio GCI32 / (r^p GCI21) is written in the summary and
never used: with p observed on the same three meshes it equals phi1/phi2.

**aero.drag_area** judges the top of the band: CdA_fine (1 + GCI) + U_I,fine,
a sum, never a root-sum-square (the two are not independent errors of known
distribution). Its claim must be in m^2 with `<=` or `<`.

### Measured (P6, the spheroid, 4 ranks, 300 iterations a level)

| | L0 | L1 | L2 |
|---|---|---|---|
| cells | 41 574 | 132 094 | 386 302 |
| CdA, window mean (m^2) | 0.00443257 | 0.00384200 | 0.00364309 |
| U_I | 0.0148% | 0.0018% | 0.00022% |

Monotone, r21 1.430, r32 1.470, observed p 2.712 (above 2.05): the band at
p = 2 with Fs 3 is 15.67% (Celik's at p 2.71 would be 4.1%). U_I,fine /
|eps21| = 4e-5. Extrapolated 0.00345275 m^2. Top of the band 0.00421412
m^2 against B1's 0.0044.

On the 1.125 times larger body (`bigger_body`): 0.00541140, 0.00475847,
0.00447759 m^2, observed p 2.0528, 0.003 above 2.05, so the formal-order
band: GCI 18.28%, top 0.00529625 m^2, 1.204 times B1's limit. Its landing
hangs on that 0.003: at the observed order the band would be 7.3% and the top
0.00481 m^2, 1.09 times the limit, still a fail but not 15% past it. The
meshes are bit for bit the same run to run (`hierarchical`), so the number
moves only with the ranks, the build or the case.
At 1.15 times the finest mesh cycled (U_I 0.53% of its drag area, 0.114 of
|eps21| against 0.1), so `aero.mesh_independence` failed it and the control never reached
`aero.drag_area`; at 1.1 the window between the baseline's top and 15% under
the control's was 2.8%.
