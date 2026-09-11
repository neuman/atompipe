# Material properties

Representative values for tier-0 work. **Every one of these is a starting point,
not a datasheet.** Real conductivity moves with density, moisture, temperature and
process; real emissivity moves with finish, oxidation and wavelength. Where a
number matters, replace it with one from the actual product's datasheet and record
the source on the parameter (method rule 3).

All at or near room temperature unless noted.

## Thermal conductivity, k [W/(m*K)]

### Metals
| Material | k | Notes |
|---|---|---|
| Silver | 429 | the benchmark nothing beats |
| Copper, pure | 401 | drops to ~390 with common alloying |
| Aluminium 1100 | 222 | |
| Aluminium 6061-T6 | 167 | the usual extrusion/heatsink number |
| Aluminium A380 die cast | 96 | castings are much worse than extrusions |
| Brass 70/30 | 110 | |
| Carbon steel, mild | 45-55 | |
| Stainless 304/316 | 14-16 | a stainless fastener is a thermal break |
| Titanium | 22 | |
| Solder, SAC305 | 58 | |

### Non-metals and structure
| Material | k | Notes |
|---|---|---|
| Alumina 96% | 25-30 | the substrate of choice when heat must leave |
| Glass, soda-lime | 1.0 | |
| Concrete, dense | 1.4-2.0 | |
| Brick, fired | 0.6-0.8 | |
| Gypsum board | 0.16-0.25 | |
| Softwood, across grain | 0.12-0.14 | the framing number that ruins U-values |
| Plywood | 0.13 | |
| Epoxy FR-4, through plane | 0.3 | ~10x higher in plane; anisotropy matters |
| ABS / PC / PA | 0.20-0.30 | this is why moulded "heatsinks" do not work |
| PTFE | 0.25 | |
| Water, liquid at 300 K | 0.61 | |
| Air, still at 300 K | 0.026 | |

### Insulation
| Material | k | Notes |
|---|---|---|
| Vacuum insulated panel | 0.004-0.008 | fragile; a single puncture takes it to ~0.02 |
| Aerogel blanket | 0.014-0.020 | dusty, expensive, compresses |
| PIR / polyiso board | 0.022-0.028 | ages upward as blowing agent diffuses out |
| XPS board | 0.029-0.035 | |
| EPS board | 0.033-0.038 | |
| Phenolic foam | 0.020-0.025 | |
| Mineral wool batt | 0.034-0.040 | k rises sharply if compressed |
| Glass wool batt | 0.032-0.040 | |
| Cellulose, blown | 0.038-0.042 | settles; derate for installed density |
| Sheep wool / wood fibre | 0.038-0.045 | |
| Still air cavity, sealed 20 mm | ~0.025 equivalent | |
| **Unsealed / convecting cavity** | **0.15-0.20 equivalent** | what "insulated" becomes when the batt is missing |

Moisture is the destroyer: mineral wool at 5% moisture by volume can lose a third
of its resistance, and it does not recover its original value after drying if it
has slumped.

## Density and specific heat (for time constants)

| Material | rho [kg/m3] | cp [J/(kg*K)] | rho*cp [kJ/(m3*K)] |
|---|---|---|---|
| Aluminium | 2700 | 900 | 2430 |
| Copper | 8930 | 385 | 3440 |
| Steel | 7850 | 460 | 3610 |
| Stainless 304 | 7900 | 500 | 3950 |
| Water | 997 | 4182 | 4170 |
| 40% propylene glycol | 1030 | 3600 | 3710 |
| Concrete | 2300 | 880 | 2020 |
| Brick | 1900 | 840 | 1600 |
| Softwood | 500 | 1600 | 800 |
| Mineral wool | 30-100 | 840 | 25-84 |
| Air (1 atm, 300 K) | 1.18 | 1007 | 1.19 |

`rho*cp` is the column to compare: it is the volumetric heat capacity, and it is
what sets a time constant once geometry is fixed. Note that water beats every
common metal per unit volume, and air is three orders of magnitude below all of
them — which is why an air-filled enclosure has essentially no thermal mass and
follows its walls.

## Total hemispherical emissivity, eps [-]

Longwave (room-temperature) emissivity unless noted. This is the property people
guess at, and the guess is usually 0.9 for everything, which is wrong for every
bare metal by a factor of ten.

| Surface | eps | Notes |
|---|---|---|
| Polished aluminium | 0.03-0.06 | a bare heatsink radiates almost nothing |
| Mill-finish aluminium | 0.07-0.15 | |
| Anodised aluminium, clear | 0.75-0.85 | anodising is an emissivity treatment |
| Anodised aluminium, black | 0.85-0.90 | same conductivity, far better radiation |
| Polished copper | 0.03 | |
| Oxidised copper | 0.6-0.8 | it changes in service |
| Stainless, polished | 0.15 | |
| Stainless, oxidised | 0.7-0.8 | |
| Galvanised steel, new | 0.23 | |
| Paint, any colour, matte | 0.85-0.95 | **visible colour tells you nothing about longwave eps** |
| White paint | 0.90 | high eps, low solar alpha — the cool-roof combination |
| Black paint | 0.95 | |
| Glass | 0.90 | opaque in the longwave; this is the greenhouse effect |
| Concrete, brick | 0.90-0.95 | |
| Human skin | 0.98 | |
| Selective solar absorber (black chrome, TiNOx) | **0.04-0.10** | with solar alpha 0.94-0.96 |
| Degraded / plain black absorber | 0.90 | the failure mode the radiation gate's control models |

### Solar absorptance, alpha [-]
Different property, different spectrum, and the pairing is the whole trick.

| Surface | alpha | eps | alpha/eps |
|---|---|---|---|
| Selective absorber (TiNOx-type) | 0.95 | 0.05 | 19 |
| Black paint | 0.95 | 0.90 | 1.06 |
| White paint | 0.25 | 0.90 | 0.28 |
| Polished aluminium | 0.15 | 0.05 | 3.0 |
| Anodised black aluminium | 0.88 | 0.88 | 1.0 |

High `alpha/eps` collects; low `alpha/eps` stays cool in sun. A polished metal
surface has a *high* ratio and gets surprisingly hot outdoors despite looking
reflective — it reflects visible light but cannot radiate the heat away either.

## Interface and contact resistance

Not a material property; a joint property. Supplied to
`thermal.steady_state_temp`, never predicted by it.

| Joint | R [K/W] for a ~1 cm2 device | R" [m2*K/W] |
|---|---|---|
| Dry metal-to-metal, hand tight | 2.0-4.0 | 2-4e-4 |
| Dry, torqued, flat, smooth | 0.8-1.5 | |
| Thermal grease, 50 um | 0.3-0.5 | 3-5e-5 |
| Thermal pad, 0.5 mm, 3 W/mK | 0.6-1.5 | |
| Phase-change pad | 0.25-0.4 | |
| Soldered | 0.05-0.1 | |
| Graphite sheet | 0.2-0.3 | |

The dry-versus-greased difference is typically 5-10x on the same joint, which is
why it is the negative control for the steady-state gate. Pads get worse with
age and with loss of clamp load; grease pumps out under thermal cycling.

## Heat transfer fluids

| Fluid | Useful range | cp [J/kgK] | k [W/mK] | Notes |
|---|---|---|---|---|
| Water | 0 to 100 degC | 4182 | 0.61 | best there is, and it freezes and boils |
| 30% propylene glycol | -13 to 105 | 3800 | 0.48 | ~5% output penalty in a collector |
| 40% propylene glycol | -21 to 105 | 3600 | 0.44 | ~8% penalty; viscosity hits pumping hard |
| 50% propylene glycol | -33 to 105 | 3400 | 0.41 | diminishing returns below this |
| Ethylene glycol | as above | 3300 | 0.40 | toxic; never in a potable circuit |
| Silicone / synthetic oil | -40 to 250+ | 1600-2000 | 0.13 | survives stagnation; poor cp, seeps everywhere |

Propylene glycol degrades irreversibly above roughly 120-140 degC and the
degradation products are acidic. That is a stagnation constraint, not an
operating one — see `lenses.md`.
