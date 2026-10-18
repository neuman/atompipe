# The grid convergence index, as `cfd.mesh_independence` computes it

Source: I. B. Celik, U. Ghia, P. J. Roache, C. J. Freitas, H. Coleman, P. E. Raad,
"Procedure for Estimation and Reporting of Uncertainty Due to Discretization in
CFD Applications", ASME J. Fluids Eng. 130(7):078001, 2008. Read from the
manuscript ASME hosts (JFENumAccuracy.pdf, pages 3-7). Roache's two-grid rule and
the constant-ratio closed form: NASA NPARC, "Examining Spatial (Grid)
Convergence" (grc.nasa.gov/www/wind/valid/tutorial/spatconv.html).

## The procedure

Grid 1 is the finest. h1 < h2 < h3.

1. **Cell size.** h = (V / N)^(1/D), D the dimension of the MESH: a one-cell-thick
   OpenFOAM case is D = 2 with N its cell count. So r21 = (N1 / N2)^(1/D).
2. **Ratio.** "It is desirable that ... r be greater than 1.3". Refinement must
   be systematic: every cell, not one region.
3. **Order.** eps21 = phi2 - phi1, eps32 = phi3 - phi2, s = sign(eps32 / eps21):
   p = |ln|eps32/eps21| + q(p)| / ln r21, q(p) = ln((r21^p - s) / (r32^p - s)).
4. **Extrapolation.** phi_ext = (r21^p phi1 - phi2) / (r21^p - 1).
5. **GCI.** e_a = |eps21 / phi1|; GCI_fine = 1.25 e_a / (r21^p - 1).

## The traps (none is stated in the paper)

1. **The absolute value gives a positive p to data that diverge.** At r = 2,
   (1.0, 1.1, 1.15) gives p = 1.000 and a GCI of 12.5%. `_gci.classify` decides
   the convergence type first (monotone, oscillatory, divergent); only monotone
   convergence goes on.
2. **The fixed-point iteration fails when r32 > r21**: 57 of 252 exact power-law
   cases. Bisection on Eq. (3a) as printed then finds a false second root (the
   reflection the absolute value makes). `_gci.py` falls back to bisection on the
   SIGNED branch, which recovers all 252.
3. **With p from the same three meshes, the asymptotic-range check means
   nothing.** GCI32 / (r^p GCI21) equals |phi1 / phi2| exactly, so it reads "in
   the asymptotic range" for any monotone data. Reported, never used.
4. **Loose solver tolerances move p.** The icoFoam cavity at the tutorial's
   tolerances read p = 2.30 on its fine triplet; at 1e-12, 1.93. The gate writes
   its own residual target and requires the iterative error to be ten times
   below eps21 (Celik, Appendix A).
5. **A refinement of one region converges to the wrong answer.** A cylinder
   case that refined only its wall cells "converged" with a GCI of 0.013% at a
   drag 0.37% off the benchmark. The ladder multiplies every block.

## What the gate requires

| Condition | Threshold | Source |
|---|---|---|
| every level converged | `cfd.converged`'s test, on each | Celik p. 2 |
| refinement ratio | effective r21, r32 at least 1.3 | Celik Step 2 |
| convergence type | monotone, by `classify`, never by the sign of p | Eca & Hoekstra 2008 |
| order | unique root, 0.95 to formal + 0.05 (formal 2; 1 when a div scheme is `upwind`) | Eca & Hoekstra 2008 |
| iterative error | at most 0.1 x eps21 | Celik, Appendix A |
| GCI_fine | at most `cfd_gci_max_pct` | the claim's: no source sets one |
| plane placement | each plane on a cell face or centre at every level | measured: OpenFOAM's sampled value is about 1% off a quarter of a cell away, and a ladder that moves the plane through the cells reads that as convergence |

`cfd.pressure_drop` then judges phi1 x (1 + GCI_fine), the top of the band.

## The published examples the arithmetic is held to

Celik Table 1 (backward-facing step, 2D, N = 18000/8000/4500 and 18000/4500/980),
reproduced by `tests/test_cfd_openfoam.py`:

| | column 1 | column 3 |
|---|---|---|
| phi1, phi2, phi3 | 6.063, 5.972, 5.863 | 6.0042, 5.9624, 6.0909 |
| p | 1.53 (1.53397) | 1.51 (1.50769) |
| phi_ext21 | 6.1685 (6.16850) | 6.0269 (6.02687) |
| GCI_fine21 | 2.2% (2.17499%) | 0.5% (0.47204%) |
| type | monotone | oscillatory |

Column 2 prints e_ext = 0.9%; its own values give 0.8465%. Not reproducible, so
not tested. r must come from the cell counts with D = 2: the printed r32 = 1.333
gives phi_ext 6.1682.

NPARC (inlet pressure recovery, r = 2): 0.97050, 0.96854, 0.96178 give p =
1.786170, phi at h = 0 0.97130, GCI12 0.103083%, GCI23 0.356249%.

## On the baseline

50 x 10, 100 x 20 and 200 x 40 cells: pressure drops 5.88235e-4, 5.97015e-4,
5.99252e-4 m^2/s^2, monotone at p = 1.97, extrapolated 6.00018e-4 against the
exact 6.0e-4, GCI_fine 0.16%. The `coarse` control (10 x 2 up) is monotone at p =
1.51 with a GCI of 5.6%.
