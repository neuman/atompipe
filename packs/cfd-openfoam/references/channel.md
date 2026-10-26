# The baseline channel and its controls

## The case

`selftest/assets/channel`: plane Poiseuille flow, 2D (one cell thick, front and
back `empty`).

| | |
|---|---|
| geometry | 100 mm long, 10 mm high (h); hydraulic diameter 2h = 20 mm |
| fluid | 10 cSt (nu 1e-5 m^2/s), 870 kg/m^3: a light hydraulic oil |
| inlet | uniform 10 mm/s (`fixedValue`), p `zeroGradient` |
| outlet | U `zeroGradient`, p fixed at 0 |
| walls | `noSlip` |
| mesh | one block, 50 x 10 x 1, uniform |
| schemes | steady; `bounded Gauss linearUpwind grad(U)`; Gauss linear |
| solution | GAMG for p, smoothSolver for U, both to 1e-12 at relTol 0.01; SIMPLEC (`consistent yes`); U relaxed 0.9 |
| planes | x = 25 mm and 75 mm, normal +x |

Re = U Dh / nu = 20. The exact pressure drop between the planes is 12 nu U dx /
h^2 = 6.0e-4 m^2/s^2, 0.522 Pa.

**Why a uniform inlet.** A parabolic inlet written as an expression needs a
correction term that depends on the cell size (face centres carry 1/(2 Ny^2) too
much flux), so it would change with each level of the ladder. A uniform inlet
develops within about one channel height, and the planes are past that: the
three meshes read the developed answer, 6.0e-4 / (1 + 2 / Ny^2), to 3e-6.

**Why these planes, not the patches.** The inlet patch's pressure is the first
cell's (`zeroGradient`), half a cell from the face, and it carries the entrance
loss: a first-order, inlet-shaped number. Planes inside the developed flow
converge at order 2 to the exact answer.

## The ladder

| Mesh | Cells | Pressure drop (m^2/s^2) | Against exact |
|---|---|---|---|
| 50 x 10 | 500 | 5.88235e-4 | -1.96% |
| 100 x 20 | 2000 | 5.97015e-4 | -0.50% |
| 200 x 40 | 8000 | 5.99252e-4 | -0.125% |

Each is 6.0e-4 / (1 + 2 / Ny^2) to within 3e-6 of itself: the error is the wall
cell's half-cell distance alone, with a trace of the uniform inlet's entrance. Observed order 1.97, GCI 0.16%,
extrapolated 6.0002e-4. The finest mesh gives 0.52135 Pa; with its GCI, 0.52218
Pa against the 0.6 Pa limit of the claim the baseline states (`_claims`).

## The known-bad controls (`selftest/bad_cases.py`)

Each is one dictionary entry changed, or one stated value, and each passes every
guard before its own gate, so the gate is shown to fail and not merely to be
skipped.

| Fixture | Gate | Change | Result |
|---|---|---|---|
| `coded_inlet` | `cfd.case_readable` | inlet U a `codedFixedValue` | refused: compiles C++ |
| `fast_flow` | `cfd.regime` | `cfd_velocity_m_s` for Re = 2300 x 1.15 | Re 2645, fails |
| `sheared` | `cfd.mesh_quality` | top wall slid 40 mm | 75.96 degrees against 65; checkMesh still says `Mesh OK.` |
| `cut_short` | `cfd.converged` | `endTime 5` | no converged line, 0.69% high; exit 0 |
| `coarse` | `cfd.mesh_independence` | start at 10 x 2 cells | GCI 5.6% against 1% |
| `thicker_fluid` | `cfd.pressure_drop` | nu 2e-5 (20 cSt) | 1.044 Pa against 0.6 |

**What a cut-short run looks like.** Stopped at iteration 2, the pressure drop
is 9.2% high; at 5, 0.69% high; at 10, 0.001% low; at 20, 0.0002% high. The run
converges at iteration 91. A value band cannot tell a cut run from a converged
one past about 10 iterations. Only the converged line can.
