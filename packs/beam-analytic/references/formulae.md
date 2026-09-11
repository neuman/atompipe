# Closed-form beam formulae, their assumptions, and where each one breaks

Everything in `gates/_beam_analytic_lib.py` is here, with the assumption that
makes it true and the condition that makes it false. Units throughout: **mm, N,
MPa (N/mm^2), mm^4**.

---

## 1. The four coefficients

Every support case in this pack is one row of this table. `P` is the **total**
applied load in newtons — for a distributed case that is the whole load
`W = w*L`, not the intensity.

```
deflection      delta_max = k_d * P * L^3 / (E*I)
peak moment     M_max     = k_m * P * L
peak shear      V_max     = k_v * P
shear defl.     delta_s   = k_s * alpha * P * L / (G*A)      [estimate]
```

| `beam_case` | k_d | k_m | k_v | k_s | where M peaks |
|---|---|---|---|---|---|
| `cantilever_end` | 1/3 | 1 | 1 | 1 | root |
| `cantilever_udl` | 1/8 | 1/2 | 1 | 1/2 | root |
| `simply_supported_centre` | 1/48 | 1/4 | 1/2 | 1/4 | mid-span |
| `simply_supported_udl` | 5/384 | 1/8 | 1/2 | 1/8 | mid-span |
| `fixed_fixed_centre` | 1/192 | 1/8 | 1/2 | 1/4 | ends **and** centre (equal) |
| `fixed_fixed_udl` | 1/384 | 1/12 | 1/2 | 1/8 | ends (mid-span is WL/24) |
| `propped_cantilever_udl` | 1/185 | 1/8 | 5/8 | 1/8 | the built-in end |

Notes that matter more than the numbers:

- **1/3 to 1/48 is a factor of sixteen.** The support condition is worth more
  than almost any section change you can afford. Getting it wrong is the largest
  single error available in this whole pack, which is why `lenses.md` spends a
  section on it.
- `fixed_fixed_*` assumes the ends are **genuinely** built in and that what they
  are built into does not rotate. Real bolted joints land somewhere between
  `fixed_fixed` and `simply_supported`, and there is no coefficient for "mostly".
  When in doubt, run both and see whether the answer changes your decision.
- `propped_cantilever_udl`'s `k_d` of 1/185 is the standard 0.0054 approximation
  for the maximum deflection, which occurs at about 0.42L from the propped end,
  not at mid-span.
- `k_v` is the *reaction-side* peak shear. For `propped_cantilever_udl` the
  built-in end carries 5/8 of the load and the prop carries 3/8.

### Where the coefficients stop being true

- The load is at the station the case says it is. A point load at 0.3L on a
  simple beam is not `k_m = 1/4`.
- The section is prismatic. A tapered or stepped beam needs integration.
- One load case at a time. Two loads superpose linearly (that is legitimate and
  cheap) — but only while everything is elastic and deflections are small.
- Supports do not settle and do not rotate.

---

## 2. Bending stress

```
sigma = M * c / I            (= M / Z, with Z = I/c the section modulus)
```

True for pure bending of a symmetric prismatic section, linear-elastic, plane
sections remaining plane, load in a principal plane through the shear centre.

**Breaks when:**

- there is any geometric feature at the peak-moment station — hole, notch, step,
  fillet, keyway. The formula gives the *nominal* stress; the real peak is
  `K_t * sigma` and `K_t` is roughly 2.2 for a well-radiused hole, 3 and rising
  without limit as an inside corner radius goes to zero.
- the section is unsymmetric about the bending axis, or the load is not in a
  principal plane (then you need biaxial bending, and the neutral axis is not
  where you think it is).
- the section is open (channel, angle, C) and the load does not pass through the
  **shear centre**, which for an open section is not the centroid. It twists.
- the material yields. Everything here is elastic; past yield the stress
  redistributes and the formula over-predicts stress while under-predicting
  deflection.
- the beam is very short: near a support, within roughly one section depth, the
  stress field is not beam-like at all (Saint-Venant).

---

## 3. Transverse shear

```
tau = V * Q / (I * t)
```

`Q` is the first moment of the area above the neutral axis, `t` the width at the
neutral axis. This pack computes both from the section:

| section | A | I | Q at NA | t at NA | tau_max | alpha |
|---|---|---|---|---|---|---|
| rectangle b x h | b*h | b*h^3/12 | b*h^2/8 | b | 1.5 V/A | 1.2 |
| solid round d | pi d^2/4 | pi d^4/64 | d^3/12 | d | 1.33 V/A | 10/9 |
| tube D, wall t | pi(D^2-d^2)/4 | pi(D^4-d^4)/64 | (D^3-d^3)/12 | 2t | ~2 V/A | 2.0 |

(`d = D - 2t` is the bore; `alpha` is the shear shape factor used only in the
shear-deflection estimate.)

**When shear matters — worked, not asserted.** Bending stress carries an `L` and
shear does not. For a rectangle, exactly:

```
sigma = k_m*P*L*(h/2) / (b*h^3/12) = 6*k_m*P*L / (b*h^2)
tau   = 1.5 * k_v*P / (b*h)
sigma / tau = 4 * (k_m/k_v) * (L/h)
```

so as a member gets shorter, shear gains on bending linearly and eventually wins.
Shear GOVERNS when `tau/tau_allow > sigma/sigma_allow`, i.e. below

```
L/h  =  R / (4 * k_m/k_v),        R = sigma_allow / tau_allow
```

| `beam_case` | k_m/k_v | metal, R = 1/0.577 = 1.73 | plywood, R = 30/3.5 = 8.6 |
|---|---|---|---|
| `cantilever_end` | 1 | **0.43** | 2.14 |
| `cantilever_udl` | 1/2 | **0.87** | 4.29 |
| `simply_supported_centre` | 1/2 | **0.87** | 4.29 |
| `simply_supported_udl` | 1/4 | **1.73** | 8.57 |
| `fixed_fixed_centre` | 1/4 | **1.73** | 8.57 |
| `propped_cantilever_udl` | 1/5 | **2.17** | 10.71 |
| `fixed_fixed_udl` | 1/6 | **2.60** | 12.86 |

Read the metal column against this pack's own validity floor of L/h = 5: **for a
solid metal section `beam.shear_stress` cannot be the binding constraint anywhere
inside the regime this pack declares valid.** The cantilever crossover is at
L/h 0.43, not 5.

An earlier version of this section said the crossover was "in the neighbourhood
of L/h = 4-6 — the same place `beam.model_validity` starts refusing the deflection
number... one physical boundary appearing in two gates". That was wrong by about
eleven times for a cantilever, and the unity built on it was invented. The pack's
own fixture was the evidence: to make shear trip in aluminium the control had to
abandon the cantilever, go to `fixed_fixed_centre` and drop to L/h 1.2.

Printed polymers are on the metal side of this, not the wood side: the table's
derated shear values are 0.6-0.64 of the design stress, so R is about 1.6 and
shear governs even later than it does for a metal.

**Where the gate does earn its place:** wood and any other material whose shear
strength is a small fraction of its bending strength (the plywood column above,
and softwood is the same); thin-webbed explicit sections, where `Q/t` carries the
web width directly and no `L/h` argument applies; and bond lines, welds and
printed layer boundaries, where the stress is right and the allowable is a
different and much lower number.

### The relationship with `beam.model_validity` — the real one

There IS a connection between this gate and the validity gate, and it runs the
opposite way to the one claimed above. Shear deflection is

```
delta_s/delta_b = (k_s/k_d) * alpha * (E/G) * I/(A*L^2)
```

which for a rectangle is `0.1 * (k_s/k_d) * (E/G) * (h/L)^2`, so it stays under
the validity gate's 10% ceiling only above

```
L/h  =  sqrt( (k_s/k_d) * (E/G) / (10 * 0.10) )  =  sqrt( (k_s/k_d) * (E/G) )
```

The two things that make shear STRESS govern — a low shear strength (wood) and a
stiff support case (large `k_v/k_m`, which comes with a large `k_s/k_d`) — are the
same two things that make shear DEFLECTION large. Tabulating both bounds for
every case and every material in this pack's table, the regions do not overlap
anywhere: `cantilever_end` in plywood governs below L/h 2.14 and needs L/h 6.0 for
the 10% ceiling; `simply_supported_udl` in plywood governs below 8.57 and needs
10.73; `fixed_fixed_udl` governs below 12.86 and needs 24.

> **Wherever `beam.shear_stress` binds, the deflection numbers are already
> untrustworthy.** That is why the shear gate's own negative control also fails
> `beam.model_validity`, and why it is not possible to build one that does not.

**Breaks when:**

- the load is applied within about one section depth of a support (the shear is
  carried in direct compression, not beam shear, and this over-predicts).
- the "shear allowable" is not a section property. Along a glue line, a weld, a
  wood grain or a printed layer boundary the material has a *different and much
  lower* shear strength, and `tau = VQ/It` is still the right stress but you are
  comparing it to the wrong allowable. See `materials.md`.
- the web is thin enough to buckle in shear before it yields.

### The shear allowable this pack uses

In order: a stated `allowable_shear_mpa`; a stated `shear_strength_mpa / SF`; the
material table's measured shear (present for wood and printed polymer); and only
then `0.577 * yield / SF`. That last is the von Mises relation and it is for
**ductile metals**. Applied to plywood it overstates the allowable by roughly
five times. The verdict line always says which route was taken.

---

## 4. Euler buckling, and why it is usually wrong on its own

```
P_cr = pi^2 * E * I_min / (K*L)^2
```

Three things about this formula are counter-intuitive and all three cause real
failures:

1. **Strength does not appear.** A high-strength alloy buckles at the same load
   as a mild one of the same section, because `E` barely differs between them.
   Swapping to a stronger material does nothing for a buckling problem.
2. **`I_min` is the weak axis.** A rectangle bent the strong way buckles about
   the other one. Using the bending `I` on a 2:1 section overstates capacity by
   four. The pack computes `I_min` itself for `rect`, `circle` and `tube`; on an
   explicit `I_mm4` section it **refuses** — `beam.buckling` skips naming
   `i_min_mm4` — because the explicit route is exactly the one a caller reaches
   for an extrusion, a channel or a built-up member, where `I_min/I` is least
   likely to be 1 and the error is unconservative. If your section really is
   symmetric, state `i_min_mm4 = I_mm4`; that is one line and it is a design
   statement, not a formality. (This used to fall back to the bending `I`
   silently, which was the precise error the paragraph above warns about.)
3. **`K` is the whole answer.** Squared, so an error is squared with it.

| end condition | theoretical K | recommended K | this pack's `column_end_condition` |
|---|---|---|---|
| pinned-pinned | 1.0 | 1.0 | `pinned_pinned` |
| fixed-free (cantilever column) | 2.0 | 2.1 | `fixed_free` |
| fixed-pinned | 0.7 | 0.80 | `fixed_pinned` |
| fixed-fixed | 0.5 | 0.65 | `fixed_fixed` |

The recommended values are higher because no real joint is a perfect restraint,
and the difference is always in the unconservative direction if you take the
theoretical number.

### The Johnson cut-off

Euler assumes the column is still elastic when it goes unstable. Below the
transition slenderness

```
lambda = K*L / r,     r = sqrt(I_min/A),     lambda_1 = sqrt(2*pi^2*E / sigma_y)
```

it is not — the member squashes before it buckles, and Euler over-predicts,
sometimes by a great deal. For `lambda < lambda_1` this pack uses the Johnson
parabola instead:

```
sigma_cr = sigma_y - sigma_y^2 * lambda^2 / (4*pi^2*E)      P_cr = sigma_cr * A
```

which meets Euler tangentially at `lambda_1` and reduces to plain squash strength
at `lambda = 0`. `beam.buckling` prints which branch it used, because "Euler" on
a stubby column is a warning sign in itself.

**Still not covered:** initial bow and eccentricity (a real column is never
straight — the secant formula or a code column curve handles this and typically
costs 10-25% of capacity), lateral-torsional buckling of a deep thin beam, local
buckling of a thin tube or plate wall, and any post-buckling behaviour at all.

---

## 5. Bearing

```
sigma_br = P / (n * d * t)
```

`d` is the **bolt shank** diameter, not the hole, and `t` the thickness of the
material the bolt bears against. The stress distribution around a loaded hole is
nothing like uniform; this is a conventional average that design practice has
calibrated allowables against, not a real peak stress.

This pack uses `yield / SF` as the allowable, which is conservative for a ductile
metal with adequate edge distance (practice often permits up to ~1.5x yield in
bearing because local yielding simply redistributes) and is **not** conservative
for brittle or layered materials, where local yielding splits things instead.

**Not checked here at all:** shear-out and tear-out at the free edge (keep edge
distance e/d >= 2), net-section tension through the hole line, bolt shear, thread
stripping in the parent material, preload, prying, and whether the load really
shares equally between fasteners — for a stiff plate on four bolts it does not.

---

## 6. Euler-Bernoulli vs reality: the shear-deflection omission

Every deflection in this pack ignores shear deformation. The estimate
`beam.model_validity` prints is:

```
delta_s / delta_b = (k_s/k_d) * alpha * 2*(1+nu) * I / (A*L^2)
```

`E` cancels — only the RATIO `E/G` survives — which is why the validity gate needs
no modulus. It does **not** need no material: `E/G` is 2(1+nu) = 2.6-2.7 only for
an ISOTROPIC solid. For a rectangular METAL cantilever the expression reduces to
about `0.80*(h/L)^2`:

| L/h | omitted shear deflection (rect. cantilever, metal) |
|---|---|
| 20 | ~0.2% |
| 10 | ~0.8% |
| 6 | ~2.2% |
| 5 | ~3.2% |
| 3 | ~8.9% |
| 2 | ~20% |
| 1.2 | ~55% |

**Two multipliers move that whole column, and both were previously ignored.**

- **The support case.** `k_s/k_d` runs from 3 (`cantilever_end`) to 48
  (`fixed_fixed_centre` and `fixed_fixed_udl`) — a factor of sixteen. A
  fixed-fixed beam's bending deflection is small, so shear is a much bigger share
  of it. `beam.model_validity` computes the case's own number rather than the
  cantilever one.
- **The material.** `E/G` is 2.6-2.7 for every metal here, and it is **not** that
  for wood. Softwood `G_LR` is about `E_L/16`; a birch plywood panel's in-plane
  `G` is roughly `E/12`. The `e_over_g` column in the material table carries those
  (12 plywood, 16 pine, 14 oak, 3 MDF); assuming isotropy on plywood under-reports
  the omission by about 4.5x. Printed polymers deliberately carry no value: bulk
  polymer is near-isotropic in-plane, the interlayer shear modulus is lower, and
  no defensible table figure exists — so the gate discloses the assumption on its
  verdict line and its number is a stated LOWER BOUND rather than an invention.
  Supply `e_over_g` or `shear_modulus_mpa` and it stops assuming.

So a birch plywood beam on simple supports under a distributed load, at a
perfectly respectable L/h of 6, omits about **32%** of its deflection:
`(0.125/(5/384)) * 1.2 * 12 * (1000/120) / 60^2 = 0.32`. This is why the validity
gate applies a second criterion — the omission itself, capped at 10% — and not
L/h alone. L/h is geometry; the omission is geometry times case times material.

Below L/h = 5 the member is not really a beam. Between 5 and about 10, apply
judgement; for a metal the closed form is a few percent optimistic and that is
usually smaller than the uncertainty in the load. Above 10, for a metal, the
omission is noise. For timber, shear deflection stays significant to L/h 15-20,
which is why timber codes carry a shear-deflection term and this pack's 10%
ceiling refuses there.

---

## 7. Superposition, and the cheap way to get further

Everything here is linear, so for any combination of loads on the same beam you
may add the deflections and add the moments. Two point loads, a point load plus a
distributed load, a load plus a moment — all superpose exactly, for free, with no
solver, while the material stays elastic and the deflections stay small.

That is worth remembering before anyone installs anything: a surprising fraction
of "we need FEA" is actually "we need two table lookups and a plus sign".
