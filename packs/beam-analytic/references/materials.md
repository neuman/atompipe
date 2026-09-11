# Materials for closed-form structural work

## Read this first

**The numbers below are order-of-magnitude values for early design. They are not
a certificate.** Every gate in this pack that reads from this table says so on
its own verdict line, and a PROVEN row in a readiness report that rests on a
table in a validator is not proven. Replace these with your supplier's data
before anything is ordered, and record which of the three tiers the number came
from (see `sourcing.md`): a mill certificate, a published typical value, or a
table.

Units: **MPa** for stress and modulus, dimensionless for Poisson's ratio.

---

## Metals — wrought, room temperature

| `material` | E (MPa) | yield (MPa) | nu | notes |
|---|---|---|---|---|
| `al_6061_t6` | 68 900 | 276 | 0.33 | the default engineering aluminium; welds well but the heat-affected zone drops to roughly annealed strength |
| `al_7075_t6` | 71 700 | 503 | 0.33 | much stronger, poor corrosion resistance, does not weld |
| `al_5052_h32` | 70 300 | 193 | 0.33 | sheet alloy, formable, good corrosion resistance |
| `steel_1018` | 205 000 | 370 | 0.29 | cold-drawn mild steel; hot-rolled is nearer 220 |
| `steel_4140_qt` | 205 000 | 655 | 0.29 | quenched and tempered; strength depends entirely on the temper |
| `steel_304` | 193 000 | 215 | 0.29 | austenitic stainless, annealed; work-hardens dramatically |
| `ti_6al4v` | 113 800 | 880 | 0.34 | high strength-to-weight, expensive, galls against itself |
| `brass_c360` | 97 000 | 310 | 0.34 | free-machining brass, half hard |

Two things to notice, because they drive design decisions:

- **Every aluminium alloy has essentially the same E.** Choosing 7075 over 6061
  roughly doubles the strength and changes the stiffness by 4%. If the problem is
  deflection or buckling, a stronger alloy buys you almost nothing; only section
  does.
- **Steel is three times stiffer than aluminium and roughly three times denser.**
  For an equal-stiffness beam of the same shape, aluminium generally wins on
  weight because depth is cheap and stiffness goes as depth cubed.

---

## Printed polymers (FDM) — and the mistake that breaks parts

### The blunt version

**Published polymer coupon numbers overstate a printed part's layer-normal
strength by roughly 30-50%, and using the coupon number is the most common way
an FDM part passes analysis and snaps in service.**

A filament spool's datasheet quotes a tensile strength measured on a specimen
that was either injection moulded or printed flat and pulled **along** the
extrusion direction. In that direction the material is close to bulk polymer. Pull
it **across** the layers instead and you are testing the weld between two beads
of plastic that touched briefly while one of them was cooling — and that bond is
typically 40-70% of the in-plane value, worse with a cold chamber, a fast print,
a wide layer, or any moisture in the filament.

So the table below carries **derated** numbers: what a reasonably printed part
can be expected to survive in the layer-normal direction, not what the spool
claims.

| `material` | E (MPa) | design stress (MPa) | shear (MPa) | nu | typical spool claim |
|---|---|---|---|---|---|
| `pla_fdm` | 2 900 | 22 | 14 | 0.36 | 50-60 MPa tensile |
| `petg_fdm` | 1 700 | 20 | 12 | 0.40 | 45-50 MPa |
| `abs_fdm` | 1 800 | 16 | 10 | 0.38 | 35-40 MPa |
| `asa_fdm` | 1 800 | 17 | 10 | 0.38 | 40 MPa |
| `pa12_fdm` | 1 300 | 22 | 14 | 0.40 | 45-50 MPa |
| `pc_fdm` | 2 000 | 30 | 18 | 0.38 | 60-65 MPa |

### What follows from that

- **Orientation is a structural parameter.** Which way a part is printed changes
  its strength by a factor of two. It must be recorded in the model with
  provenance and a rationale, not left to whoever loads the plate. The right
  sentence in a decision log reads: *printed on its side so the principal tension
  runs along the beads; printed upright the same part fails at the root layer.*
- **Design so the layers are in compression or shear-across-beads, not in tension
  across the bond.** Where that is impossible, put the load path through a metal
  insert or a through-bolt instead of through the plastic.
- **A tapped hole in a printed part is a suggestion.** Use heat-set inserts and
  take their pull-out data from the insert supplier's testing.
- **These materials creep.** A printed part under sustained load keeps deflecting
  for weeks. None of the numbers in this pack model that; a part that must hold a
  position for a year needs a much lower stress than a part that must survive an
  event.
- **Temperature matters immediately.** PLA loses useful stiffness in a warm car.
  A structural PLA part is an indoor, room-temperature part.
- **Infill is not a material.** A 20% infill part is a sandwich structure, not a
  solid one, and none of the section properties in this pack describe it. Either
  print the load-carrying section solid (enough perimeters that the walls *are*
  the section) or stop using closed-form analysis on it.

The honest summary: use this pack to find out whether a printed part is *nowhere
near* the limit. If it comes out between about 0.3 and 1.0 utilisation, print it
and break it — an afternoon with a scale and a lever settles more than any
analysis, and it is the only thing that measures **your** printer.

---

## Wood and panel products

Wood has no yield point; the values below are conservative **design bending
stresses** along the grain, and they vary by species, grade, moisture content and
duration of load far more than any metal does.

| `material` | E (MPa) | design bending (MPa) | shear (MPa) | E/G | notes |
|---|---|---|---|---|---|
| `plywood_birch` | 8 000 | 30 | 3.5 | 12 | in-plane, face grain parallel to span |
| `pine_softwood` | 9 000 | 14 | 1.7 | 16 | construction grade, along the grain |
| `oak_hardwood` | 12 000 | 25 | 2.5 | 14 | along the grain |
| `mdf` | 3 600 | 18 | 1.5 | 3 | no grain, but weak and very moisture sensitive |

Read the shear column carefully. **Wood's shear strength along the grain is
roughly a tenth of its bending strength**, which is why the von Mises `0.577 *
yield` estimate is catastrophically wrong here — it would overstate the shear
allowable by about five times. This is also why timber beams split horizontally
near supports rather than snapping in the middle, and why `beam.shear_stress` is
not a formality on a short wooden shelf. In aluminium it is: the normal and shear
allowables are in the ratio 1.73, so shear cannot govern above L/h 2.6 in any
support case this pack knows. In plywood the ratio is 8.6 and shear governs below
L/h 8.57 on simple supports under a distributed load, which is inside the regime
the pack calls valid. `references/formulae.md` section 3 has the table.

### The shear MODULUS, which is a different hole in the same wall

The column above is shear STRENGTH. Wood is just as non-isotropic in shear
STIFFNESS, and that one is easier to miss because nothing fails — the deflection
number simply comes out too small.

`beam.model_validity` estimates the shear deflection Euler-Bernoulli omits, and
that estimate carries `E/G`. For an isotropic solid `E/G = 2(1+nu)`, which is
2.6-2.7 and is exact for every metal in this pack. For wood it is not close:
softwood `G_LR` is about `E_L/16`, and a birch plywood panel's in-plane `G` is
roughly 650 MPa against an `E` of 8 000. Assuming isotropy on plywood reports
about 2.2% omitted shear deflection where the real figure is nearer 10% — a 4.5x
under-report, in the optimistic direction, on the gate this pack advertises as its
most valuable.

So the wood rows carry an `E/G` column and the gate uses it. Override it per model
with `e_over_g`, or give `shear_modulus_mpa` and let the pack divide.

**The printed polymers deliberately carry no value.** Bulk polymer is close to
isotropic in-plane so `2(1+nu)` is roughly right there, and the interlayer shear
modulus is measurably lower but no defensible table figure exists for it. Where a
value is missing the gate assumes isotropy, **says on its verdict line that it
did**, and states that its number is a lower bound. Disclosing beats inventing; a
number whose provenance is "an agent rounded it up to be safe" is exactly the kind
of value the method exists to keep out of a table.

Other wood-specific facts the formulae do not know:

- **Direction is everything.** Across the grain, wood is roughly a twentieth as
  strong in tension. Any load path that pulls across the grain is a mistake.
- **Duration of load.** Wood carries far less under a permanent load than under a
  brief one — design values differ by a factor of about 1.6 between a ten-year
  load and an instantaneous one.
- **Moisture.** Strength and stiffness fall as moisture content rises, and the
  piece moves dimensionally across the grain while staying nearly fixed along it.
- **Plywood is directional too.** Face-grain-parallel and face-grain-perpendicular
  differ by roughly a factor of two, and the value above is the parallel one.
- **Knots and grain runout** are the real failure sites and are not in any table.

---

## Choosing a safety factor

This pack defaults to 2.0 on yield and discloses it on every verdict line. That
is a reasonable number for a static, well-understood load in a well-characterised
metal. Move it, deliberately, for:

| condition | direction |
|---|---|
| load is estimated, not measured | up |
| impact, shock or vibration | up, substantially |
| cyclic loading | this pack does not cover it at all — see `lenses.md` |
| brittle material, or a layered/printed one | up |
| consequences of failure are injury | up, and get a second opinion |
| material from a certificate, load measured, static, ductile | 1.5 is defensible |

A safety factor is not a substitute for a lens you did not run. Doubling it to
cover an unanalysed stress concentration is a way of hiding the concentration,
and the part will still fail at the hole.
