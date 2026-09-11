# Reference project — wall bracket

The smallest project that still exercises every rule in `METHOD.md`, with **zero
dependencies**. Standard library only, like the spine. You can run the whole
pipeline on a fresh machine with nothing installed, which is the point of having a
reference project at all.

```bash
cd examples/bracket
atompipe check
```

## What you should see

```
[ok  ] bracket.bending_stress  : 3.7 MPa vs 15.0 MPa allowable (util 0.24, petg)
[ok  ] bracket.bearing         : 0.19 MPa on 77 mm^2 across 2 bolt(s), allowable 15.0 MPa
[ok  ] bracket.model_validity  : slenderness 8.6 (>= 5.0 for Euler-Bernoulli; ...)
[FAIL] bracket.deflection      : 0.700 mm at 15 N (limit 0.5 mm)
[ok  ] bracket.bed_fit        : 74 x 30 x 7 mm vs 204 mm usable (220 bed - 2x8 brim)
[ok  ] bracket.min_wall       : thinnest section 7.0 mm vs 1.2 mm minimum
```

**The failure is deliberate.** The default thickness is 7 mm and the arm sags 0.70 mm
against a 0.5 mm limit. Open `model/bracket.py`, change `thickness` to `8.0`, and run
`atompipe check` again — it goes green at 0.47 mm.

That is the entire loop: one parameter, one gate, one verdict. Everything else in
atompipe is this loop with more expensive gates attached.

## What it demonstrates

**Rule 1 — one source of truth.** `model/bracket.py` holds every input. Section
properties, stresses, deflections and the print footprint are all computed by
`build()`. No gate recomputes geometry.

**Rule 2 — derive, never duplicate.** `usable_bed = bed_xy - 2 * brim_mm`. The brim
allowance exists in one place, so it cannot drift.

**Rule 3 — provenance.** Every field in `Config` carries why it holds that value and
what was tried. `thickness` records that 4 mm misses by ~5x, that 8 mm passes, and
that the default is left marginal on purpose. Run `atompipe why thickness`.

**Rule 5 — falsification controls.** Six gates, six fixtures in
`selftest/bad_configs.py`, each changing exactly one physically meaningful thing in
the direction that gate cares about:

| Gate | Known-bad fixture |
|---|---|
| `bracket.deflection` | same bracket at 1/4 thickness (~64x worse) |
| `bracket.bending_stress` | same bracket at 20x load |
| `bracket.bearing` | one bolt in a thin plate, bearing area collapsed |
| `bracket.model_validity` | short deep arm where shear deflection stops being negligible |
| `bracket.bed_fit` | a 400 mm arm — nothing wrong but the footprint |
| `bracket.min_wall` | a 1.2 mm nozzle that cannot resolve the section |

```bash
atompipe gate selftest
```

Every gate must **fail** its fixture. One that passes is reported as broken.

**A gate that polices another gate.** `bracket.model_validity` checks that
Euler-Bernoulli is applicable at all — below a slenderness of about 5, shear
deflection stops being negligible and the deflection gate quietly becomes optimistic.
Any pack shipping closed-form analysis wants one of these. Without it, the cheap gate
silently becomes the wrong gate as the design moves.

**Rule 9 — honest reporting.** `atompipe report` separates what was proven from what
was not. The bracket's outdoor-durability claim is `physical`: no gate will ever
settle whether it survives two winters on a wall, and the report says so rather than
finding something adjacent to turn green.

## Files

```
model/bracket.py            the model: Config + build(). Runnable on its own.
gates/structural.py         six tier-0 gates, all pure arithmetic
selftest/bad_configs.py     one known-bad fixture per gate
```

## Try breaking it

- Set `material="alu6061"` — watch the deflection claim pass by a wide margin and the
  mass triple.
- Set `arm_length=120` — deflection goes as L³, so it fails by ~8x.
- Set `thickness=2.0` — now `bracket.min_wall` and `bracket.deflection` both trip, and
  `bracket.model_validity` warns that the remaining numbers are not trustworthy.
- Delete a gate's `negative_control` — the registry refuses to load it at all.
