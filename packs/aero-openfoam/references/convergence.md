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
settled from iteration 134; L1 and L2 from 145 and 127.

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
