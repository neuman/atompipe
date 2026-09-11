# The correlation set, and where each one is allowed to be used

Every Nusselt correlation is a curve fit to somebody's experiment over a stated
range of Rayleigh or Reynolds number. Outside that range it still returns a
number, and the number is not a measurement. `thermal.convection` therefore
reports the band with every verdict and **FAILS** when the operating point is
outside it — see "Why out-of-band is a failure" at the end.

All properties are evaluated at the **film temperature** `T_f = (T_s + T_inf)/2`,
which is the evaluation point every correlation here was fitted at. Evaluating at
the bulk temperature instead is a quiet ~10% error and it always errs optimistic.

## The dimensionless group cheat sheet

```
Ra = g * beta * |Ts - Tinf| * L^3 / nu^2 * Pr       Rayleigh   (natural)
Re = V * L / nu                                     Reynolds   (forced)
Pr = nu / alpha                                     Prandtl    (fluid only)
Nu = h * L / k                                      Nusselt    (the answer)
Bi = h * Lc / k_solid                               Biot       (NOT Nu: k is the SOLID's)
```

`Nu` and `Bi` look identical and are not. `Nu` uses the **fluid's** conductivity
and tells you how much better convection is than pure conduction in the fluid.
`Bi` uses the **solid's** and tells you whether the solid has one temperature.
Confusing them is the single most common error in this domain and it is usually
invisible because both produce plausible numbers.

`beta` is the volumetric expansion coefficient: exactly `1/T` in kelvin for an
ideal gas, and a tabulated property for a liquid (water's is ~6x different between
280 K and 360 K, so this is not a detail).

Characteristic length `L` depends on the geometry and is not negotiable:

| Geometry | L |
|---|---|
| Vertical plate | height |
| Horizontal plate | area / perimeter |
| Horizontal cylinder | diameter |
| Flat plate in flow | streamwise length |
| Cylinder in cross flow | diameter |
| Lumped body (for Bi) | volume / surface area |

## Natural convection

### Vertical plate — Churchill & Chu
```
Nu = { 0.825 + 0.387*Ra^(1/6) / [1 + (0.492/Pr)^(9/16)]^(8/27) }^2
```
Valid over **all Ra**, which is why it is the default for an unknown vertical
surface. Accuracy is best above Ra ~ 1e4; below that the boundary layer is
comparable with the plate and the fit is loose. Laminar up to Ra ~ 1e9, turbulent
above.

### Horizontal plate, hot face UP (or cold face down) — McAdams
```
Nu = 0.54 * Ra^(1/4)     1e4 <= Ra <= 1e7      L = A/P
Nu = 0.15 * Ra^(1/3)     1e7 <  Ra <= 1e11
```
The buoyant plume leaves freely, so this is the good case.

### Horizontal plate, hot face DOWN (or cold face up) — McAdams
```
Nu = 0.27 * Ra^(1/4)     1e5 <= Ra <= 1e10     L = A/P
```
Half the coefficient of the face-up case, because the hot fluid is trapped
against the plate and has to escape sideways. A heatsink mounted facing downward
loses roughly half its natural-convection capability, and this is the correlation
that says so.

### The sign of dT chooses between those two, and the gate enforces it

The geometry names say *hot*, and the physics does not care about the word. What
decides which correlation applies is **where the buoyant plume goes**:

| Surface | Fluid | Plume | Correlation |
|---|---|---|---|
| Hot plate, face up | cooler | leaves freely upward | `0.54 Ra^(1/4)` |
| Cold plate, face **down** | warmer | leaves freely downward | `0.54 Ra^(1/4)` |
| Hot plate, face down | cooler | trapped, escapes sideways | `0.27 Ra^(1/4)` |
| Cold plate, face **up** | warmer | trapped, escapes sideways | `0.27 Ra^(1/4)` |

`Ra` is computed from `|dT|` — it is a magnitude — so the sign is gone by the time
the correlation is chosen, and a dispatcher that reads only the geometry string
will hand a *cold* plate facing up the free-plume form and over-predict `h` by
exactly 2x, in the non-conservative direction, using nothing but correct
correlations. A 5 degC plate facing up into 25 degC air gets 5.0 W/m2K where the
answer is 2.5.

So `natural_nusselt` takes the **signed** surface-minus-fluid difference and
swaps `horizontal_plate_hot_up` <-> `horizontal_plate_hot_down` when the surface
is the colder one. The substitution is reported in the verdict rather than done
quietly — `[cold-surface substitution]` appears in the correlation name and the
detail line says which pair was swapped and by how many kelvin — because a
verdict that names the correlation the user *asked* for rather than the one that
*ran* cannot be checked by the person reading it.

This bites chilled plates, condenser and evaporator surfaces, cold-side enclosure
walls, and every winter case where the inside face of a roof is warmer than the
ceiling below it. The vertical plate and the horizontal cylinder are symmetric in
the sign and are left alone.

### Horizontal cylinder — Churchill & Chu
```
Nu = { 0.60 + 0.387*Ra^(1/6) / [1 + (0.559/Pr)^(9/16)]^(8/27) }^2      Ra <= 1e12
L = diameter
```

### Sanity band for air
Natural convection in air lands at **2-25 W/m2K**. Below 2 means a tiny dT or a
tiny object; above 25 means something is forcing the flow and the natural
correlation is the wrong one.

## Forced convection

### Flat plate, laminar — Blasius / Pohlhausen
```
Nu = 0.664 * Re^(1/2) * Pr^(1/3)      1e3 <= Re <= 5e5,  Pr >= 0.6
```
This gate refuses below Re = 1e3: the boundary layer becomes comparable with the
plate, the similarity solution stops describing it, and buoyancy usually dominates
anyway — the honest answer there is to use the natural-convection path.

Note `h ~ sqrt(V)`: halving the flow costs 30% of h, not 50%. This is why a fan
that drops to a third of speed is a bigger problem than people expect and a fan
upgrade is a smaller win than people hope.

### Flat plate, mixed laminar/turbulent
```
Nu = (0.037*Re^0.8 - 871) * Pr^(1/3)      5e5 < Re <= 1e8,  0.6 <= Pr <= 60
```
The `-871` is the laminar leading-edge correction assuming transition at
Re_x,c = 5e5. Turbulent `h ~ V^0.8`, so the return on velocity is much better once
you are past transition — a reason to trip the boundary layer deliberately.

### Cylinder in cross flow — Churchill & Bernstein
```
Nu = 0.3 + [0.62*Re^(1/2)*Pr^(1/3)] / [1 + (0.4/Pr)^(2/3)]^(1/4)
         * [1 + (Re/282000)^(5/8)]^(4/5)              Re*Pr > 0.2
```
Single correlation across the whole range. The `0.3` is the conduction floor at
vanishing Re.

### Sanity band for air
Forced convection in air lands at **10-200 W/m2K**; in water, **500-15000**. A
forced-air result of 400 W/m2K is an input error, not a discovery.

## Radiation, for comparison

```
q = sigma * (T1^4 - T2^4) / [ (1-e1)/(e1*A1) + 1/(A1*F12) + (1-e2)/(e2*A2) ]
h_rad = q / (A1 * (T1 - T2))
```
For a high-emissivity surface near room temperature, `h_rad` is **5-6 W/m2K** —
comparable with natural convection in air, which means ignoring radiation in a
still-air problem is a ~50% error. For a polished metal surface it is ~0.3
W/m2K and ignoring it is fine. The emissivity table in `materials.md` decides
which world you are in.

The two-surface denominator collapses to `1/(e1*A1*F12)` only when the surround is
much larger or black. In a tight enclosure — a board in a metal box — the full
form is roughly a factor of two different, and the simple form is the one
everybody uses out of habit.

## Fins

```
m   = sqrt(h*P / (k*A_c))
L_c = L + t/2                        (adiabatic-tip correction)
eta = tanh(m*L_c) / (m*L_c)          EFFICIENCY   - how much of the fin works
eps = eta * A_fin / A_c              EFFECTIVENESS - whether the fin was worth it
eps_ceiling = sqrt(k*P / (h*A_c))    effectiveness of an infinitely long fin
```

Use `eps`, not `eta`, to decide anything. A short thick fin scores well on
efficiency precisely because it is barely a fin. The ceiling is the number to
check first: it depends only on material, section and h, and when it is below the
target, no length helps.

`eps < 1` means the fin removes LESS heat than the bare base it covers. The
condition is `k*P < h*A_c`, which is reached by low conductivity, a thick short
section, or a high h. All three arrive together in a moulded polymer fin in a
liquid — which is exactly the negative control for `thermal.fin_efficiency`.

Rules of thumb: `eps >= 2` to be worth the material; `mL_c` in the range 1-2 is
the economic sweet spot (beyond ~3 the tip contributes almost nothing and you are
paying for decoration).

## Lumped capacitance

```
Lc  = V / As
Bi  = h*Lc / k_solid
tau = rho*V*cp / (h*As)
T(t) = T_inf + (T_0 - T_inf) * exp(-t/tau)
```

`Bi <= 0.1` is the licence. It bounds the internal temperature difference to
roughly 10% of the surface-to-fluid difference — about where "the part has a
temperature" stops being a defensible sentence. Above it the surface responds
while the core has not started, `tau` under-predicts the time to reach the core,
and any single-node network built on the same body is reporting an average that
exists nowhere in the part.

63% of the step in `1*tau`, 86% in `2*tau`, 95% in `3*tau`, 99% in `5*tau`.

## Why out-of-band is a failure and not a warning

A gate exists to settle a claim and to be capable of failing. A verdict that said
"h = 41 W/m2K (note: Reynolds number outside the correlation's range)" would be
read by every downstream reader as a measurement with a caveat, and caveats do not
survive being copied into a summary. The number produced outside the fitted band
is arithmetic on a fit that was never checked there; nothing measured it. So the
gate reports FAIL with the band in the detail line, and the reader either changes
the geometry, changes the correlation, or escalates to a solver.

## Sources

Churchill & Chu (1975) for the vertical plate and horizontal cylinder; McAdams
(1954) for the horizontal plates; Churchill & Bernstein (1977) for the cylinder in
cross flow; Blasius/Pohlhausen for the laminar flat plate. All are reproduced in
Incropera & DeWitt, *Fundamentals of Heat and Mass Transfer*, whose property
tables A.4 (air) and A.6 (water) are the source of the interpolation tables in
`gates/_thermal_physics.py`.
