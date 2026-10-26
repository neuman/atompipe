# Validation and limits

## Extraction and independent checks

The extracted SIMP proposer uses its own cubic Hex8 elements. The falsifiers use a
separately exported STL and CalculiX C3D10 tetrahedra. They never read the proposer's
compliance, history, density or a claimed optimizer verdict. `upstream.json` pins
the extraction commit and original file hashes. Drone-specific modal and impact
models, and the orientation proposer, were not imported.

## Controls run on 2026-10-26

`nopekit gate selftest --pack topology-simp` qualified all four gates: each baseline
passed and its known-bad control failed, with zero skipped controls. The baseline
is a 40 × 8 × 8 mm cantilever, E = 1000 MPa, nu = 0.3, under a 1 N end-patch load.
The material is artificial, for a reproducible control, not a filament recommendation.
`selftest/make_assets.py` regenerates the control surfaces.

| Gate | Baseline | Known-bad change |
|---|---|---|
| case valid | finite material and specified patches | E = -1000 MPa |
| volume | 2560 mm³ under 3000 mm³ | double width: 5120 mm³ |
| displacement | 0.06516 mm under 0.1 mm | half E: twice the displacement |
| stress | 0.4106 MPa under 1 MPa, in 8 ≤ x ≤ 32 mm | load ×10: stress ×10 |

The fine mesh held 25,813 quadratic tetrahedra. Its independently reassembled
free-node equilibrium residual was 0.0401% of applied load. A Timoshenko estimate
for end displacement is 0.06445 mm; CalculiX's answer is about 1.1% larger.
These values come from the run behind the README figure. Different library
versions may mesh differently.

`make_figure.py` reruns that case and renders the real stress field. The image
shows the full field, including restraint singularities; the caption limits the
stress assertion to its interior region.

## Numerical refusal rules

- Tetrahedral quality at least 0.02; maximum edge at most 2× the requested size.
  These screens come from the upstream solver-corruption incident.
- Gmsh retries with tighter size targets. No relaxed quality threshold or
  surface-changing mesher fallback. The 2 mm baseline initially missed the 5%
  stress test; it was refined to 1.5 mm instead of widening acceptance.
- The requested second mesh is 0.65× the first and must add elements. Both
  quantities must change by at most 5%, relative to the finer mesh.
- Static free-node equilibrium residual at most 0.5% of the sum of applied force
  magnitudes, from independently assembled stiffness using the same deck.
- Small-deformation screen: displacement ≤2% of the part diagonal.

These percentages are engineering screening choices, **not error bounds or
validated universal tolerances**. Refining the volume mesh cannot catch a poorly
tessellated surface; supply independently refined exports too. Stress outside the
selected region remains unjudged. A passing deformation screen does not prove
linear elasticity applies to the application.

## Exercised tools

CalculiX 2.21 (Ubuntu package 2.21-1), Gmsh 4.13.1, trimesh 5.1.0, NumPy 2.4.6,
SciPy 1.18.1, Numba 0.68.0, pyamg 5.2.1, matplotlib 3.10.9. PARDISO was absent:
the optimizer used SuperLU. Numerical tests compare its displacement to a beam
calculation; the independent structural controls run the real CalculiX executable.

The example optimizer was run for 140 iterations on a 20 × 8 × 6 grid with 2 mm
cells and a 35% designable-volume budget. It reached beta 16 but hit its cap with
0.025 design-variable change: **not converged**. Its thresholded voxel STL was not
watertight. This is a rejected proposal, not a validated example part. Completing
the process and lowering its objective do not establish structural readiness.
