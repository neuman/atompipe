# topology-simp

Propose where a part's material goes with **3D SIMP topology optimization**, then
check **one exported solid** independently with CalculiX. Geometry is in **mm**;
forces in **N**, elastic modulus and stress in **MPa**. The STL, support boxes,
load boxes and stress region all use the same coordinates. The optimizer's density
field and compliance score never settle a claim about the exported part.

## Propose, draw, check

1. The model writes a voxel problem: designable material, solid regions, keep-outs,
   support nodes, load cases, filter radius and a material budget.
2. `fea.topopt3d` proposes a density field, preview and optimization history.
3. Your model draws an actual part from that field. Thresholding, smoothing and
   thickening are design decisions: they can change its stiffness enormously.
4. The gates read that exported STL, mesh it independently, and judge its volume,
   displacement and stress. They work for a part drawn by hand too.

```sh
nopekit packs add topology-simp
nopekit propose fea.topopt3d --timeout 600 -- --problem build/problem.npz --variant first --iters 120
nopekit check --tier 2
```

`scaffold/cantilever.py` writes a small example problem and draws a field as an STL:

```sh
python3 packs/topology-simp/scaffold/cantilever.py --out /tmp/simp-demo
```

Use its `problem.npz` with the proposer, then run the same script with
`--field <proposed.npz> --out /tmp/simp-demo` to draw `part.stl`. The scaffold's
path above is relative to a Nopekit checkout; an installed pack has the same file
under its own directory. Copy it into your project's model to customize it.
Drawing a density field does not establish connectedness or manufacturability.

## What the gates settle

| Gate | Tier | Claim tag | Basis | Known-bad control |
|---|---|---|---|---|
| `simp.case_valid` | 0 | `simp-case` | model-only: finite material and boundary-data checks | negative elastic modulus |
| `simp.volume` | 1 | `simp-volume` | established: trimesh's solid volume | twice the beam width |
| `simp.displacement` | 2 | `simp-displacement` | established: CalculiX displacements | half the elastic modulus |
| `simp.stress` | 2 | `simp-stress` | established: CalculiX stresses | ten times the applied force |

The two static gates require `simp.case_valid`. Volume is independent: an invalid
support does not hide excess material. Every mesh-reading gate refuses a non-solid
or disconnected part. Missing tools read Skipped; malformed or unconverged solver
results read errored, never Passed.

Both static gates independently solve on the requested tetrahedral mesh and a
mesh requested at 0.65 times that size. The finer mesh must add elements; both
stress and displacement must agree within 5%. Every solve must balance its loads:
`|K u - f|`, assembled independently of CalculiX, at every free node must be
within 0.5% of the sum of applied force magnitudes. These are documented engineering
screening tolerances, not a validated error bound. See `references/validation.md`.

## Model projection

Use these exact keys; there are no fallback spellings. `simp.<key>` and
`topology-simp.<key>` are the standard scoped overrides, ahead of bare keys.

| Key | Meaning |
|---|---|
| `simp_case` | object with the seven fields below |
| `simp_volume_limit_mm3` | material-volume ceiling on the exported part |
| `simp_displacement_limit_mm` | maximum displacement magnitude anywhere in the part |
| `simp_stress_limit_mpa` | maximum von Mises stress **in the stated region only** |

`simp_case` contains:

- `mesh`: exported STL path, relative to the project root or absolute.
- `young_mpa`, `poisson`: isotropic elastic constants, finite with E > 0 and -1 < nu < 0.5.
- `mesh_mm`: positive target mesh size; the pack controls its own refinement.
- `support`: box `[[xmin,ymin,zmin],[xmax,ymax,zmax]]`. Selected nodes are fixed in XYZ;
  at least three must be non-collinear. Use a small tolerance around a surface.
- `loads`: list of `{"box": [...], "force_n": [fx,fy,fz]}`. Each force is the **total**
  patch force, divided equally among selected nodes. All patches act simultaneously.
  Empty patches or patches touching fixed nodes are refused.
- `stress_region`: box selecting where the stress claim applies. It must exclude
  the fixed and loaded nodes. The excluded part has no stress assertion from this gate.

The baseline JSON is a complete example. Limits come from the project, not the
optimizer. For claims, use the narrow tags above; the spine cross-checks each
reported measurement against the claim's own acceptance condition too.

## Tools and installation

The tier-0 gate needs only Python. Volume needs NumPy and trimesh. The static gates
also need Gmsh and **CalculiX 2.21 (`ccx`)**. The proposer needs NumPy, SciPy, Numba
and matplotlib; large systems also need pyamg. PARDISO is optional.

```sh
pip install numpy scipy numba pyamg matplotlib trimesh gmsh
sudo apt install calculix-ccx=2.21-1
```

The CalculiX command above is Ubuntu 24.04's package version. Other systems should
install CalculiX 2.21 and put `ccx` on PATH. Python packages were exercised at the
versions recorded in `references/validation.md`; use a virtual environment.
No fTetWild fallback is used: a difficult surface is refused rather than modified.

## What this pack cannot settle

- Linear static, isotropic elasticity only. No crash energy, contact, buckling,
  fatigue, plasticity, natural frequencies or printed-layer anisotropy is claimed.
- Displacements beyond 2% of the part diagonal are refused as outside this small-
  deformation screen. Passing this screen does not prove linear theory applies.
- A two-mesh agreement is not experimental validation or a formal error bound.
  Surface tessellation is held fixed; refine the exported surface separately.
- Patch loading is a numerical idealization, not a bolt, adhesive or contact model.
  All specified patches belong to one simultaneous load case; test other cases separately.
- Stress outside `stress_region` is not checked. Peak stresses at restraints and
  point loads can be singular; excluding them leaves real joint questions open.
- The density filter does not guarantee minimum walls in the exported part. Use
  `cad-solid` and `fdm-print` on that geometry and physical tests on the built article.
- The problem identifier is supplied by the model. Keep it tied to its actual
  inputs; this pack does not assert that an adopted field belongs to today's problem.

## Site view

`simp.part` shows the current exported geometry as a GLB, with the single node
`part`, in the unchanged model frame. It carries no stress colours or verdict.
Solver decks, logs, FRD results and the two-mesh summary are linked as evidence
from the static gates.

## Sources and further reading

- `references/proposer.md`: NPZ contract, warm starts, settings and scaling costs.
- `references/methods.md`: SIMP, projection, sparse solvers, meshing and elasticity sources.
- `references/upstream.json`: exact extraction commit, source paths and hashes.
- `references/validation.md`: controls, tolerances and measured smoke results.
- `lenses.md`: what an adversarial reviewer should question.

The SIMP proposer and solver helpers come from PETGasusDrone's Apache-2.0
`solid-fea` pack. The reusable gates and cantilever controls were added here;
PETGasus's drone-specific crash and vibration gates were not imported.
