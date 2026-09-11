# Pipe roughness, fitting K-factors, and the friction factor

## Absolute roughness ε

`pipe_roughness_m` is **absolute roughness in metres**. Every published table is
in millimetres or in feet; this is the unit slip that produces a friction factor
about 3x wrong with no symptom, so both columns are given here and the metres
column is the one to copy.

| Material | ε (mm) | `pipe_roughness_m` |
|---|---|---|
| Drawn tubing: glass, acrylic, drawn plastic (PVC, PE, PTFE) | 0.0015 | `1.5e-6` |
| Drawn copper, brass, aluminium | 0.0015 | `1.5e-6` |
| Smooth-bore rubber or silicone hose | 0.01 – 0.03 | `1e-5` – `3e-5` |
| Stainless steel, drawn | 0.015 | `1.5e-5` |
| Commercial steel, wrought iron | 0.045 | `4.5e-5` |
| Welded steel | 0.045 – 0.09 | `4.5e-5` – `9e-5` |
| Asphalted cast iron | 0.12 | `1.2e-4` |
| Galvanised iron | 0.15 | `1.5e-4` |
| Cast iron, new | 0.26 | `2.6e-4` |
| Wood stave | 0.18 – 0.9 | `1.8e-4` – `9e-4` |
| Concrete, smooth to coarse | 0.3 – 3.0 | `3e-4` – `3e-3` |
| Riveted steel | 0.9 – 9.0 | `9e-4` – `9e-3` |

### The bottom of this table has a bore limit on it

Colebrook-White, the Moody chart and Swamee-Jain are all bounded at about
**ε/D = 0.05**. That is the coarsest line the Moody chart plots and the edge of
the data Colebrook fitted; past it the "roughness" is a sizeable fraction of the
bore and the passage is an obstruction, not a rough pipe. The equation keeps
returning confident numbers there, which is exactly why `fluid.flow_regime`
**fails** outside it.

That bound is reachable from this very table, not just from a unit slip:

| Material | ε | ε/D = 0.05 at a bore of |
|---|---|---|
| Riveted steel, worst | `9e-3` m | 180 mm — anything narrower is off the chart |
| Concrete, coarse | `3e-3` m | 60 mm |
| Cast iron, new | `2.6e-4` m | 5.2 mm |
| Printed channel, 0.2 mm | `2e-4` m | 4 mm |

So a coarse-concrete culvert or a riveted main is fine at the diameter it is
actually built in and nonsense in a small bore — and the small bore is where
somebody reaches for these values when modelling a printed or cast passage.
`fluid.flow_regime` also range-checks the friction factor itself, refusing a
turbulent *f* outside **0.008–0.08**: fully-rough Colebrook at ε/D = 0.05 gives
f = 0.072, and smooth-pipe Colebrook at Re 1e8 gives 0.0082, so nothing physical
lies outside that band and a value that does means an input is wrong.

### Roughness values worth arguing about

- **Ageing is not a rounding error.** Corrosion, scale and biofilm grow ε over
  years — a decade in hard water or untreated seawater can multiply it by five to
  ten, and the effect on a mature system's head loss is larger than any modelling
  refinement you were considering. Design against the aged value; check the new
  value only to understand commissioning.
- **Additively manufactured channels are not in any table.** The bore of a
  printed passage is ridged at the layer pitch, anisotropic (worse across layers
  than along them), and dependent on print orientation and surface finish. The
  honest range is 0.05–0.2 mm for typical layer heights — which puts a 4 mm
  printed channel in the same relative-roughness territory as concrete. Do not
  quote a plastic-tubing value because the material is plastic. Measure a real
  channel, or record the assumption as an assumption.
- **Corrugated and convoluted hose is not a rough pipe.** Its loss is dominated by
  the geometry of the convolutions, not by a boundary-layer roughness effect, and
  Colebrook-White does not describe it. Effective ε values of 1–5 mm circulate,
  but the only defensible source is the manufacturer's own loss curve. Flexible
  ducting can carry several times the loss of smooth pipe of the same bore.
- **Bore, not nominal size.** "25 mm pipe" is a naming convention, not a
  measurement. Schedule, wall thickness and liner all reduce the internal
  diameter, and Δp goes roughly as 1/D⁵ at fixed flow. Use the internal diameter
  from the datasheet, and record where you got it.

## The friction factor

`fluid.pipe_pressure_drop` chooses:

- **Re < 2300 — laminar.** f = 64/Re. This is a derivation, not a correlation:
  exact for fully developed flow in a round pipe, and roughness does not appear
  in it at all.
- **2300 < Re < 4000 — the transition band.** Neither law holds. The flow trips
  intermittently and the real friction factor can sit anywhere between the
  laminar and turbulent curves — a spread of about two to one. `fluid.flow_regime`
  **fails** here on purpose. The fix is a design change (a different bore or a
  different flow), not a better correlation.
- **Re > 4000 — turbulent.** Colebrook-White, solved by iteration:

      1/√f = −2 log₁₀( ε/(3.7·D) + 2.51/(Re·√f) )

  The pack iterates on x = 1/√f, which makes the map a contraction over the whole
  engineering range, seeded from the explicit Swamee-Jain approximation:

      f₀ = 0.25 / [ log₁₀( ε/(3.7·D) + 5.74/Re^0.9 ) ]²

  Convergence is typically ten iterations to 1e-10, and the whole trace is written
  to the gate's evidence file. Swamee-Jain is itself within about 1% of
  Colebrook over 5e3 < Re < 1e8 and 1e-6 < ε/D < 1e-2, so it is a legitimate
  answer on its own; the pack iterates because it costs nothing and removes one
  argument. Note that it is used as the *seed* outside its own fitted ε/D range
  as well, and that is safe only because it is a seed — the iteration converges
  from wherever it starts, so a poor seed costs iterations and not accuracy. The
  range that actually has to be policed is Colebrook's own, and that is the
  ε/D ≤ 0.05 check above.

**Entrance length.** All of this describes *fully developed* flow. The developing
region is roughly 10–60 diameters long depending on regime, and its losses are
higher. In a short run of a few diameters between fittings, none of the flow is
fully developed and the friction-factor term is a rough guide at best — which is
another reason the minor losses matter more than people expect.

## Minor losses: K-factors

Δp_minor = ΣK · ½ρv². Sum the K values for everything in the line and give the
total as `minor_loss_k_total`.

| Fitting | K |
|---|---|
| Sharp-edged pipe entrance (from a tank) | 0.5 |
| Rounded / bellmouth entrance | 0.04 – 0.05 |
| Re-entrant (protruding) entrance | 0.8 – 1.0 |
| Pipe exit into a tank | 1.0 |
| 90° elbow, standard threaded | 0.9 |
| 90° elbow, long-radius flanged | 0.3 |
| 90° mitre bend, no vanes | 1.1 |
| 45° elbow | 0.4 |
| Tee, flow through run | 0.2 |
| Tee, flow through branch | 1.0 |
| Gate valve, fully open | 0.15 |
| Gate valve, half open | 2.1 |
| Globe valve, fully open | 10 |
| Ball valve, fully open (full bore) | 0.05 |
| Swing check valve | 2 |
| Strainer, clean | 2 – 5 |
| Sudden expansion | (1 − A₁/A₂)² |
| Sudden contraction | 0.5 · (1 − A₂/A₁) approx |

Three habits that pay:

- **Never let ΣK be silently zero.** In a short system the fittings routinely
  outweigh the straight run. The gate's one line says `sumK 0.00` and warns when
  no K was declared; treat that as a missing input, not a clean result.
- **Valves are not binary.** A globe valve open is 10; a half-closed gate valve is
  2.1 and a nearly closed one is hundreds. If the system is throttled in service,
  the K you designed with is not the K it runs at.
- **Strainers and filters age.** Their K rises as they load. If the head budget
  only closes with a clean strainer, the system works for a week.

## Reading the evidence file

Every run writes `fluid.pipe_pressure_drop.txt` into the gate's out dir with the
inputs, the Reynolds number, the regime, the full Colebrook iteration trace, and
the major/minor/total split in Pa, kPa and metres of head. That file is what makes
a PROVEN row auditable later: the verdict's one line says what happened, the file
says how.
