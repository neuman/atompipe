# Drag coefficients, with the Reynolds range each is valid over

The important column in this table is not Cd. It is the range.

A drag coefficient is not a property of a shape. It is a property of a shape **at
a Reynolds number**, because Re decides where the boundary layer separates and
separation decides the wake and the wake is the drag. Quote a Cd outside the band
it was measured over and the arithmetic still returns a confident float. That is
the single most common silent error in this domain, and it is why
`fluid.drag` refuses to use a table value outside its band and
`fluid.flow_regime` fails the whole flow story when it happens.

Re = v·L/ν, with L the characteristic length named in the table.

## The table this pack ships

Every Cd here is referenced to **frontal area** — the projected area seen from
upstream — *except where the row's Reference-area column says otherwise*, and one
row does. `gates/flow.py` holds the machine-readable copy; this file is the one
with the caveats.

| `drag_shape_class` | Cd | Valid Re | Characteristic L | Reference area | Notes |
|---|---|---|---|---|---|
| `sphere` | 0.47 | 1e3 – 2e5 | diameter | πD²/4 | subcritical. Drag crisis near Re 3e5 |
| `sphere_supercritical` | 0.20 | 4e5 – 1e6 | diameter | πD²/4 | post-crisis, turbulent boundary layer |
| `cylinder_cross` | 1.20 | 1e4 – 2e5 | diameter | D·L | long circular cylinder, flow across the axis |
| `cylinder_cross_short` | 0.70 | 1e4 – 2e5 | diameter | D·L | L/D ≈ 2; free ends relieve the wake |
| `square_cylinder` | 2.05 | 1e4 – 1e6 | face width | D·L | sharp-edged square rod, face-on |
| `flat_plate_normal` | 1.17 | 1e4 – 1e7 | plate width | plate area | square or round plate normal to the flow |
| `disk_normal` | 1.17 | 1e4 – 1e7 | diameter | πD²/4 | same separation behaviour as the plate |
| `cube_face_on` | 1.05 | 1e4 – 1e6 | edge | face area | sharp-edged |
| `cube_edge_on` | 0.80 | 1e4 – 1e6 | edge | **face area a², NOT frontal** | rotated 45° about the vertical — see below |
| `hemisphere_open_upstream` | 1.42 | 1e4 – 1e6 | diameter | πD²/4 | cup facing the flow (anemometer cup) |
| `hemisphere_open_downstream` | 0.38 | 1e4 – 1e6 | diameter | πD²/4 | dome facing the flow |
| `streamlined_strut` | 0.10 | 1e5 – 1e7 | chord | t·L frontal | 2D fairing, thickness/chord ≈ 0.25 |
| `streamlined_body` | 0.05 | 1e5 – 1e7 | length | max frontal | body of revolution, fineness ≈ 4:1 |

These are the textbook consensus values for smooth bodies in a uniform, unbounded
stream with low turbulence. Treat them as ±10% at best, and worse near any band
edge.

### The two rows with a footnote

**`cube_edge_on` breaks the frontal-area convention, deliberately.** The
published 0.80 is referenced to the cube's plain face a², which is how the
measurement was reported. A cube yawed 45° about the vertical actually presents
√2·a² to the flow, so a reader who follows the blanket frontal-area rule and
computes the true projected area gets **41% too much drag** — the exact
factor-of-several, no-symptom error this file spends two paragraphs warning
about. Use A = a², the unrotated face. `gates/flow.py` carries the same warning
in the row's own note, because that is where the number is read from.

**`cylinder_cross_short` is 0.70, and it used to be 0.80.** Finite-length
circular cylinders lose Cd to end relief roughly as Hoerner's end-effect factor:
L/D 1 → ≈0.63, 2 → ≈0.68, 5 → ≈0.74, 10 → ≈0.82, 40 → ≈0.98, infinite → 1.20
(Çengel & Cimbala, *Fluid Mechanics*, Table 11-2; Hoerner, *Fluid-Dynamic Drag*,
ch. 3). The 0.80 this row shipped with is the L/D ≈ 10 value under an
"L/D ≈ 2" label — about 15% high against a table that declares itself ±10% at
best. Rejected alternative: keep 0.80 and relabel the row L/D ≈ 10. A short strut
with free ends is the case a reader actually reaches for, so the geometry stayed
and the number moved.

## Why the bands differ so much

**Sharp-edged bodies separate at their edges.** The separation point is fixed by
geometry, so the wake barely changes with Re and the Cd is nearly constant over
decades. That is why the cube, the square rod and the flat plate carry wide
bands: 1e4 to 1e6 or beyond.

**Rounded bodies separate wherever the boundary layer decides to.** As Re rises,
the boundary layer transitions to turbulent, sticks to the surface further round
the back, narrows the wake, and the Cd *falls* — abruptly. For a sphere it drops
from about 0.47 to about 0.2 across the drag crisis near Re 3e5, and for a
circular cylinder from about 1.2 to about 0.3. A factor of three, over less than
a decade of Re, in the direction that flatters your design if you get it wrong.
That is why the sphere and cylinder bands stop at 2e5 and this pack refuses to
extrapolate across the gap.

Two consequences worth carrying:

- **Roughness moves the crisis.** A dimpled or rough sphere trips its boundary
  layer early and gets the low-drag regime at a lower Re. This is why a golf ball
  is dimpled and why a "smooth sphere" table value is wrong for a rough one.
- **Below Re ≈ 1** none of this applies: the flow is creeping and drag is linear
  in velocity (Stokes), not quadratic. This pack's table starts at Re 1e3 for a
  reason. A small particle in a viscous fluid is a Stokes problem, not a Cd
  problem.

## What is deliberately not in this table

- **A flat plate parallel to the flow.** That is skin friction, not form drag, and
  it wants a friction line (Blasius laminar, or a turbulent flat-plate
  correlation) referenced to *wetted* area. Using a form-drag Cd with a frontal
  area for a plate edge-on gives nonsense.
- **Ship and boat hulls.** A surface-piercing hull's resistance is skin friction
  plus wave-making, and near hull speed the wave term dominates and depends on
  Froude number, not Reynolds. No single Cd exists. See
  `what_this_pack_cannot_tell_you.md`.
- **Aerofoils and wings.** Their coefficients are referenced to planform area and
  come as a function of angle of attack. Mixing one into this table's frontal-area
  convention is a factor-of-several error with no symptom.
- **Anything in a duct, near a wall, near a free surface, or in another body's
  wake.** Blockage, ground effect and wake interference all change Cd
  substantially, and none of them is a correction this pack applies.

## Using a Cd you measured or sourced yourself

Put it in the model as `drag_coefficient` and the gate uses it directly, saying
in its verdict that the regime is the model's to defend. When you do that, record
under the parameter's provenance (method rule 3):

- the **reference area** it is defined against,
- the **Reynolds range** it was measured over,
- the **source** — which figure, which report, which test,
- and what you rejected: the table value you did not use, and why.

A Cd with no recorded reference area is a number the next agent cannot use and
will re-derive differently.
