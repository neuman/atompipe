# SIMP proposer: problem, method and cost

```sh
nopekit propose fea.topopt3d --timeout 14400 -- \
    --problem build/topopt3d/problem.npz --variant <name> [--iters 120] \
    [--warm <earlier field.npz>] [--c0-from <earlier field.npz>] \
    [--checkpoint <output path>]
```

The problem file (`numpy.savez`) holds:

| key | meaning |
|---|---|
| `nu` | Poisson ratio, strictly between -1 and 0.5 |
| `nx ny nz h origin` | the cell grid, mm |
| `region` | per cell: 0 designable, 1 must be solid, 2 must stay empty |
| `erel` | a solid cell's modulus relative to the frame's (a soft second material) |
| `cost` | budget charged per designable cell (more where material costs more than its mass) |
| `fixed_nodes` | node ids held in x, y and z |
| `load_k_dofs`, `load_k_vals`, `load_names`, `load_weights` | the load cases |
| `budget_mm3` | the designable volume budget, cost-weighted |
| `rmin_mm` | density-filter radius across; not a guaranteed printed wall thickness |
| `rmin_z_mm` | (optional; default `rmin_mm`) the radius up and down. Larger than `rmin_mm`, it lets members be thin across and still deep (blades) |
| `symmetry` | `D2`, `D4` or `none` |
| `problem_hash` | pins a field to the problem it was solved for (below) |

It writes `topopt3d-<variant>-<hash>.npz`: the projected density `rho`, the
design variables `x`, the problem's `region` and hash, the history, and `info`
(c0, the load case names, the warm start). Beside it go a PNG preview and a
JSON summary. `--checkpoint` writes `rho`, `x`, the hash and `info` (beta,
iteration, c0, load case names) every 10 iterations.

The proposer uses the hash only to tell a resume from a refine (below). The
model decides what a stale field means: PETGasus draws the chosen field
whatever its hash, and `gates/flight.py` (`topology_current`) fails when the
hash is not the current problem's.

### Method

methods.md has the sources.

- SIMP with penalty 3, a cone density filter (an ellipsoid when `rmin_z_mm`
  differs from `rmin_mm`) and a Heaviside projection, updated by optimality
  criteria. Each load case's compliance is divided by its value at the run's
  start (c0), and the weighted sum is minimised.
- The volume budget is continued from 30 % of the designable volume down to
  the target over the first 20 iterations. Started at a 2 % budget, the
  stiffness matrix is nearly singular and CG stalls.
- After that, beta doubles from 1 to 16: after 20 iterations at one beta, or
  after 10 once no design variable moves by 0.01. At beta 16 the run stops
  when no variable moves by 0.005, or at `--iters`.
- The move limit is 0.1, then 0.05 from beta 8 and 0.025 at 16. It halves when
  the objective zig-zags and grows back by 1.25x on each iteration that does
  not. Without the growth, the objective's rise at every beta step halved it
  for good: the 2 mm PETGasus run reached beta 16 at a quarter of its cap and
  stopped on the iteration cap, still improving ~4 % an iteration.
- `D2` symmetry averages the field and the sensitivities over the planes
  x = 0 and y = 0, so load cases placed at one corner design all four; `D4`
  also mirrors them across the diagonals.

### Warm starts

`--warm` takes an earlier run's beta.

- On the same problem (the same hash), it resumes from that run's `x` and c0.
  A checkpoint resumes from the same design (x stored as float16), beta and c0;
  the move limit, the iteration count and the history restart.
- On another problem (a finer grid, another filter radius), it takes that
  run's `rho`, interpolated onto the new grid. Before the first iteration it
  finds the `x` whose field, under the new filter, reproduces that `rho`. The
  first version took the coarse run's `x`, but `x` means a design only under
  the filter it was optimised with: the 1.33 mm PETGasus refine (rmin 3.5 mm)
  started from the `x` of a 2 mm run filtered at 5.0 mm, and began 63 % over
  its budget. Taking `rho` itself as `x` erodes it: 73 % under. The fitted
  start is 4 % under, and its field correlates 0.96 with the 2 mm design.
- On another problem the load cases are normalised by the new run's start,
  unless `--c0-from` names a run (a proposal or a checkpoint) whose c0 to
  keep. That keeps the coarse run's trade between the cases, instead of
  re-weighting them by how well the coarse design already serves each. Its
  load cases must match the problem's, by name where the file records them.

### Solves

`proposers/_fe3d.py` solves directly where memory allows:

| unknowns | solver |
|---|---|
| up to 600k, with `pypardiso` | PARDISO (MKL's multithreaded sparse LU) |
| up to 150k, without it | SuperLU |
| beyond | CG preconditioned by pyamg's smoothed-aggregation multigrid on the active nodes, with the rigid-body modes as its near-null space |

The CG path raises when it stops short of its tolerance: an unconverged solve
gives the optimiser wrong sensitivities, and it would act on them silently.
PARDISO stops at 600k unknowns because its factors grow about as n^(4/3): the
1.33 mm problem (365k) took about 7 GB, and the 1 mm one (~840k) ran a 21 GB
machine out of memory. Geometric multigrid, rediscretised and then Galerkin,
failed here: thin passive features ringed by empty cells have no smooth coarse
representation.

### Cost

PETGasus frame, 13 load cases, with PARDISO:

| cell | unknowns | per iteration | the run |
|---|---|---|---|
| 2 mm | ~112k | 5.5 s | 120 iterations, 11 min |
| 1.33 mm | ~365k | 34 s, about 7 GB | 60 iterations, 34 min, warm-started from the 2 mm run |
| 1 mm | ~840k | ran out of memory on a 21 GB machine | none |

So solve at 2 mm, then refine at 1.33 mm with `--warm` and `--c0-from` set to
the 2 mm run. Without `pypardiso`, the 1.33 mm problem goes to AMG-CG, which
takes many times longer once the members thin. At 81k unknowns, AMG-CG took
95 s for seven cases where SuperLU took about 36 s (33 s to factorise, then
0.4 s a case).


When invoked through Nopekit, output and checkpoint paths must stay inside
`NOPEKIT_PROPOSAL_DIR`. Standalone runs may specify `--out` and `--checkpoint`.

The extraction validates positive budgets and filter radii, active supports and
loads, finite material data, and symmetry-compatible masks before solving. It
retains the upstream settings and measured scaling costs above; those timings
are historical PETGasus measurements, not promises for other machines.
