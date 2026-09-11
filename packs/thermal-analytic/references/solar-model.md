# The clear-sky model: what it is, what it costs you, how to feed it

`solar.irradiance` implements the ASHRAE clear-day model with an isotropic
transposition onto a tilted plane. Everything is closed form; there is no network
call, no weather file, and no dependency.

## The model

```
declination   delta = 23.45 * sin(360*(284 + n)/365)              [Cooper]
hour angle    omega = 15 * (solar_hour - 12)                      [deg, + afternoon]
altitude      sin(alt) = sin(d)sin(phi) + cos(d)cos(phi)cos(omega)

beam normal   I_bn = CN * A * exp(-B / sin(alt))                  [ASHRAE]
incidence     cos(theta) = Duffie & Beckman eq 1.6.2 (expanded, no quadrant logic)

on the tilt:
  beam     = I_bn * max(0, cos(theta))
  diffuse  = C * I_bn * (1 + cos(beta)) / 2                       [isotropic sky]
  ground   = rho * I_bn * (C + sin(alt)) * (1 - cos(beta)) / 2    [isotropic ground]
  POA      = beam + diffuse + ground
```

`beta` is the surface tilt from horizontal, `phi` the latitude, `rho` the ground
albedo, `CN` a clearness number (1.0 = the standard clear atmosphere).

## The ASHRAE coefficients

| Month | A [W/m2] | B | C |
|---|---|---|---|
| Jan | 1230 | 0.142 | 0.058 |
| Feb | 1215 | 0.144 | 0.060 |
| Mar | 1186 | 0.156 | 0.071 |
| Apr | 1136 | 0.180 | 0.097 |
| May | 1104 | 0.196 | 0.121 |
| Jun | 1088 | 0.205 | 0.134 |
| Jul | 1085 | 0.207 | 0.136 |
| Aug | 1107 | 0.201 | 0.122 |
| Sep | 1152 | 0.177 | 0.092 |
| Oct | 1193 | 0.160 | 0.073 |
| Nov | 1221 | 0.149 | 0.063 |
| Dec | 1234 | 0.142 | 0.057 |

`A` is an apparent extraterrestrial irradiance (it is larger in winter because
the earth is nearer the sun, and it is not the solar constant). `B` is an
atmospheric extinction coefficient, larger in summer because the air holds more
water vapour. `C` is the diffuse fraction of the beam.

## Error band — state it whenever you quote a number from this gate

- **Beam: roughly +-10%** against measured clear-day data at mid-latitudes near
  sea level, degrading at high air mass (early morning, late afternoon, winter at
  high latitude) where the exponential is most sensitive to `B`.
- **Diffuse: considerably worse than 10%.** The isotropic sky assumption ignores
  circumsolar brightening and horizon brightening, and it under-predicts the
  diffuse on a surface pointed at the sun. On a tilted plane facing the sun the
  diffuse term is a small part of the total, so the total survives; on a surface
  facing away it is nearly all of the total, and the error rides with it.
- **Altitude.** The coefficients assume a sea-level, moderately dusty atmosphere.
  At elevation the real beam is stronger — roughly 5-10% per 1500 m — and this
  model under-predicts. Raise `clearness_number` if you have local data to justify
  it, and record the justification.
- **Humidity and aerosol.** Humid or hazy air gets less beam and more diffuse than
  this model gives. Coastal and urban sites over-predict on beam.
- **Cooper's declination** is good to about +-0.5 degree, which is negligible
  against everything above.
- **Leap years** shift the month boundary by a day, worth well under 1%.

## What it emphatically is not

**It is a clear-sky model.** It does not know about cloud, and cloud is most of
the variance in most climates. This gate answers *"is the geometry right?"* — is
the tilt sensible, is the azimuth correct, does the sun clear the obstruction at
the design hour, is the winter design-hour irradiance enough. It cannot answer
*"how much energy will this collect in a year?"*, and a design that treats POA at
the design hour as a yield estimate will be wrong by whatever fraction of hours
are actually clear.

For yield you need a measured or satellite-derived weather series (TMY, PVGIS,
NSRDB or equivalent) and an hourly simulation. That is a tier-2 job with a data
dependency; see `references/limits.md`.

It also does not model **shading** of any kind — no horizon profile, no
neighbouring building, no row-to-row self-shading, no tree that will be taller in
five years. A shading study is geometry work on the actual site.

## Solar time versus clock time

`solar_hour` is **solar time**: noon is the sun crossing the local meridian. It is
not what a watch says. The conversion belongs in your model, not in the gate, and
it is:

```
solar_time = clock_time
           + 4 * (local_longitude - standard_meridian_longitude)   [minutes; both
                                                          longitudes EAST POSITIVE]
           + E                                                     [minutes]
           - 60 if daylight saving is in force                     [minutes]

E = 229.2 * (0.000075 + 0.001868 cos(B) - 0.032077 sin(B)
             - 0.014615 cos(2B) - 0.04089 sin(2B))                 [equation of time]
B = 360*(n - 81)/364    degrees
```

**Mind the sign, and mind which way the longitudes are counted.** Duffie &
Beckman eq. 1.5.3 writes this term as `4*(L_st - L_loc)` with both longitudes in
degrees **WEST**. Everything else in this pack is east-positive — `+90` is west
only for a *surface azimuth*, and `latitude_deg` is north-positive — so the term
is written east-positive here to match, which flips the order of the subtraction.
The two forms are the same equation. Mixing them is a 2 x 4 x (degrees off the
meridian) minute error, and it is silent.

The check that settles it: **a site EAST of its time-zone meridian sees the sun
cross earlier than the meridian does, so its solar time runs AHEAD of the clock.**

Worked, because a bare formula plus a convention label is what produced the
ambiguity in the first place:

| Site | Longitude | Zone meridian | Longitude term | Solar time |
|---|---|---|---|---|
| Berlin | 13.4 E | 15 E (CET) | `4*(13.4 - 15)` = **-6.4 min** | 6.4 min BEHIND the clock |
| Vienna | 16.4 E | 15 E (CET) | `4*(16.4 - 15)` = **+5.6 min** | 5.6 min AHEAD of the clock |
| Vigo | 8.7 W = -8.7 | 0 (UTC/WET) | `4*(-8.7 - 0)` = **-34.8 min** | 34.8 min behind the clock |

Berlin is west of its own meridian, so its noon is late: clock 12:00 CET is
11:53.6 solar time before the equation of time is applied. A formula that
returned +6.4 min there would put the sun 12.8 minutes on the wrong side of the
meridian, which is 3.2 degrees of hour angle.

The equation of time swings between about -14 and +16 minutes over the year, and
the longitude term is 4 minutes per degree away from the time-zone meridian. At
the edge of a wide time zone the two can combine to over half an hour, which moves
a morning or afternoon design hour materially. Getting this wrong is the most
common error in solar geometry work and it is completely silent: every number
still looks reasonable.

No gate can catch it. `solar_hour` arrives at `solar.irradiance` already
converted, which is deliberate — the gate has no business knowing the site's time
zone or its daylight-saving rules — but it means this conversion is the one input
in the pack with no falsification control anywhere. Check it against the table
above every time, and record which convention your model used (rule 3).

## Frame conventions, once more

- `latitude_deg`: north positive.
- `longitude`: **east positive** (Berlin 13.4, Vigo -8.7). The pack never reads a
  longitude — it is needed only for the solar-time conversion above — but the
  conversion is in your model and the convention has to be written down
  somewhere, so it is written down here and in PACK.md section 4.
- `surface_azimuth_deg`: **0 = due south, +90 = west, -90 = east.** In the
  southern hemisphere the equator-facing orientation is **180**, not 0. The
  reported solar azimuth uses the same convention.
- `surface_tilt_deg`: from horizontal. 0 = flat, 90 = vertical.
- `day_of_year`: 1-365.

## Sanity checks you can do in your head

- Extraterrestrial normal irradiance is ~1361 W/m2. Any beam-normal result above
  that is an error, full stop.
- Clear-sky beam normal at sea level at noon is typically 850-1000 W/m2.
- Global horizontal on a clear summer noon at mid-latitude is ~950-1050 W/m2.
- POA on a well-aimed surface can exceed global horizontal — that is the whole
  point of tilting — but not by more than about 30% at mid-latitude.
- A rough optimum annual tilt is the latitude; tilt ~ latitude + 15 favours
  winter, latitude - 15 favours summer. If the gate disagrees with that by a lot,
  check the azimuth sign first.
