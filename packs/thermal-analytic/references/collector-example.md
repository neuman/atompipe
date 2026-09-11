# Worked example: a glazed flat-plate collector, end to end

Every number below is reproducible by running this pack's gates against
`selftest/baseline.json` — the one projection this pack owns, the one CI verifies
every gate against, and the one `scaffold/reference_params.py` loads. There is no
second set of numbers to drift from it. The point of the example is not the
answer; it is the order the questions get asked in, and the one that gets asked
last and should have been first.

## The brief

A 2.4 m2 glazed flat-plate collector at latitude 40 N, mounted at 40 degrees
(= latitude, the year-round compromise) facing due south, feeding a store through
a glycol loop. It must deliver at least 1000 W at the design hour: a clear
midsummer noon with 35 degC outdoor air and a 55 degC store return. The loop uses
EPDM seals and inhibited propylene glycol.

The design hour is deliberately a **hot** one rather than a cold one. A winter
design hour tests whether the collector earns its keep; a hot one tests whether it
survives, and step 3 is why.

## Step 1 — is the geometry even right? (`solar.irradiance`)

Before any collector performance question, ask what reaches the plane. Site,
date, hour, tilt and orientation, nothing else:

```
latitude_deg 40, day_of_year 172 (21 Jun), solar_hour 12.0,
surface_tilt_deg 40, surface_azimuth_deg 0, ground_albedo 0.20
```

```
[ok] solar.irradiance : POA 932 W/m2 vs 800 required
     (beam 806 + diffuse 104 + ground 22); sun alt 73.4 deg az 0.0 deg,
     incidence 23.4 deg, AM 1.04; ASHRAE clear-day +-10%, albedo declared
```

Read the split, not the total. Beam is 86% of it, which means this result is
almost entirely a statement about **pointing**: the incidence angle is 23.4
degrees, `cos(theta)` is 0.92, and the plane is nearly normal to the beam.

Swing the azimuth 180 degrees and the same site, day and hour gives **611 W/m2**
— the beam survives at 484 W/m2 because at a 73-degree solar altitude a
back-tilted plane still catches the sun obliquely. Do the same thing on the
midwinter hour (day 355, everything else unchanged) and it gives **56 W/m2**, all
of it diffuse and ground reflection, because the incidence angle has passed 90
degrees and the beam term is exactly zero. That difference is why the negative
control for this gate checks what it actually did to POA instead of assuming a
rotation is always fatal — see step 5.

Note what this number is not: it is a **clear-sky** number. It says nothing about
how many clear hours June has at this site, and nothing at all about shading —
no horizon, no neighbouring building, no tree.

## Step 2 — useful heat (`solar.collector_output`)

```
collector_area_m2 2.4, collector_fr 0.78, collector_tau_alpha 0.76,
collector_ul_w_m2k 4.5, irradiance_w_m2 932,
collector_inlet_c 55, collector_ambient_c 35, collector_output_min_w 1000
```

```
[ok] solar.collector_output : 1157 W useful vs 1000 W required (eta=0.517);
     G=932 W/m2, dT=20 K, zero output below G=118 W/m2;
     stagnation would be 192 C — enforced by solar.stagnation
```

The arithmetic:

```
Q_u = F_R * A * (tau_alpha*G - U_L*dT)
    = 0.78 * 2.4 * (0.76*932 - 4.5*20)
    = 1.872 * (708.3 - 90.0) = 1157 W      eta = 1157 / (2.4*932) = 0.517
```

Three numbers in that verdict earn their place:

- **eta = 0.517.** Plausible for a glazed flat plate at a 20 K rise over ambient.
  Above ~0.7 means you have mistyped the optics; below 0.3 at a small dT means the
  loss coefficient is wrong.
- **Zero output below G = 118 W/m2.** The critical irradiance, `U_L*dT/tau_alpha`.
  Below it the collector is a radiator: it takes heat *out* of the store. This is
  the number that decides the controller's switch-on threshold, and a controller
  that runs the pump below it loses energy all day while appearing busy. It rises
  with the store return temperature, so it is worst late in a good day.
- **`irradiance_w_m2` is 932, which is what step 1 computed.** The two solar gates
  are describing one roof because that number was carried across by hand. Change
  the tilt and this one goes stale silently; there is no gate reconciling them
  (`thermal.h_agreement` does that job for the convective coefficient and nothing
  does it here). See PACK.md section 2.

## Step 3 — the number that should have been first (`solar.stagnation`)

```
[ok] solar.stagnation : stagnation 192 C vs 210 C survivable (+18 K headroom)
     = 35 C air + 0.76*932/4.5; independent of area and of F_R, and U_L is held
     constant, so this is a CONSERVATIVE bound — real U_L climbs with absorber
     temperature
```

Nobody asked for this. It is the absorber temperature with no flow at all,
`T_amb + tau_alpha*G/U_L`, and on this collector there are 18 kelvin between it
and what the seals and the fluid survive. Eighteen kelvin is not much: a 40 degC
afternoon instead of a 35 degC one spends five of them.

And 210 degC is itself a decision with a cost attached. Inhibited propylene
glycol degrades irreversibly somewhere around 120-140 degC into acidic products
that then attack the loop, so 210 assumes an accepted fluid-replacement interval
after any stagnation event, not that nothing happens.

Now the inversion. Stagnation depends on `tau_alpha/U_L` and **nothing else** —
not area, not `F_R`, not flow rate:

| Change | Useful heat | Stagnation |
|---|---|---|
| Better insulation (U_L 4.5 -> 2.5) | 1232 W, up | **318 degC**, far worse |
| Better optics (tau_alpha 0.76 -> 0.85) | 1315 W, up | **211 degC**, worse |
| Bigger collector (2.4 -> 4.0 m2) | 1929 W, up | 192 degC, unchanged |
| Waterlogged insulation (U_L -> 13.5) | 821 W, FAILS | 87 degC, safer |

**The better the collector, the more dangerous its stagnation.** A leaky
collector is a safe one. That is why `stagnation_limit_c` is required and the
gate skips without it rather than defaulting: a model that has not written down
what its seals and fluid survive has not been asked the question, and the pack
refuses to answer it on the model's behalf.

The fix is a design decision, not an analysis one: a dump load, drain-back, a
stagnation cover, a higher-temperature fluid, or an accepted fluid replacement
interval. Pick one and record why the others lost (method rule 3).

## Step 4 — why these are two gates and not one

Read the last two rows of that table again. **The one parameter either
inequality cares about moves them in opposite directions.** Raise `U_L` and
output fails while stagnation gets safer; halve it and stagnation fails while
output gets better.

They used to be one gate with one verdict, and that made an honest control
impossible. The shipped fixture raised `U_L` to falsify output — and in doing so
it *rescued* stagnation, so on a collector where stagnation was the binding
branch the gate's own known-bad input made it pass. A control that repairs the
failure mode it was supposed to plant is worse than no control, because the
selftest reports success. The combined verdict also reported `measured` and
`limit` in watts while refusing in degrees.

So: `solar.collector_output` owns the duty, `solar.stagnation` owns the survival,
each has its own fixture, and neither fixture can rescue the other gate.

## Step 5 — the falsification

```
[ok] solar.collector_output#selftest : correctly failed on waterlogged_insulation
     821 W useful vs 1000 W required (eta=0.367); zero output below G=355 W/m2

[ok] solar.stagnation#selftest : correctly failed on better_insulated_collector
     stagnation 350 C vs 210 C survivable (-140 K headroom)
     = 35 C air + 0.76*932/2.25
```

One physical change each, in opposite directions, each landing clear of the limit
it has to beat rather than at a hard-coded distance from it: the output fixture
raises `U_L` by at least 3x *and further if 3x would not clear the declared duty*,
and the stagnation fixture halves it *and further if halving would not clear the
declared seal limit*. That matters because the limits are the project's, not the
pack's — a collector with a 300 degC silicone-and-steel loop needs a deeper cut
before the control means anything, and it gets one.

## Step 6 — what none of this told you

- **Annual yield.** Clear-sky geometry times a design-hour efficiency is not
  kWh/year. You need a weather series.
- **Shading.** No horizon profile, no neighbour, no row-to-row self-shading.
- **Whether the store is big enough**, or what the loop does at part load.
- **Pressure drop and pump power**, which glycol makes materially worse.
- **Freezing.** 40% glycol protects to about -21 degC; what is the site minimum,
  and what happens in a power cut?
- **Incidence-angle modifier.** `tau_alpha` here is the normal-incidence value.
  Real glazing loses transmittance as incidence grows, noticeably past 50-60
  degrees, which matters for early and late hours — and for step 1's 23-degree
  incidence it is a small correction this pack does not make.
- **That `U_L` is constant.** It is evaluated at operating temperature and held
  there, while a real absorber's losses climb with its own temperature. The
  stagnation number is therefore an over-estimate by an unquantified margin. It
  is the conservative direction, which is the right one to be wrong in here, but
  it is not a measurement.
- **Whether the absorber coating is still the coating you specified** in year ten.

Those are `lenses.md` questions and a tier-2 tool's questions. See
`references/limits.md`.
