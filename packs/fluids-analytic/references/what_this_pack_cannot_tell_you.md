# What this pack cannot tell you

Everything here is closed form, hydrostatic, steady, single-phase and
incompressible. That covers a surprising amount of real engineering and it stops
abruptly. This file is the list of places it stops, each with the class of tool
that can go further and the tier that tool lives at.

Read it as a menu for the extension protocol, not as a list of excuses. When a
claim lands in one of these sections, the honest move is: name the unvalidated
quantity, classify it, pick the standard tool, install it pinned with a smoke
test, wrap it with a negative control, and emit a pack. Do not stretch a gate in
this pack to cover it.

**And run the analytic gates first anyway.** Every item below is a question worth
spending a solver on only after the cheap questions are settled and the design has
stopped moving.

---

## Planing — tier 2

Above roughly Froude number 0.4 (Fr = v/√(gL)) a hull begins to be supported by
dynamic pressure on its bottom rather than by displacement. The waterline
shortens, the trim angle becomes a governing variable, the centre of pressure
moves aft, and every hydrostatic number in this pack becomes a statement about a
boat at rest that is no longer the boat you have.

*What answers it:* empirical planing methods (Savitsky-type prediction, which
takes deadrise, loading coefficient and trim and returns resistance and running
attitude) — cheap, and genuinely tier 1 if you implement the correlations; or a
free-surface CFD run for the general case, which is tier 2. Towing-tank testing
is tier 3.

*Symptom you are in this territory:* the design has a speed target and
`v/√(gL)` is above about 0.4.

## Wave-making resistance — tier 2

`fluid.drag` computes form drag on a body in an unbounded stream. A
surface-piercing hull also makes waves, and the energy in those waves is
resistance. Near hull speed (Fr ≈ 0.4) the wave-making term can exceed everything
else combined, and it depends on Froude number and hull form — not on Reynolds
number, and not on any Cd.

*What answers it:* a potential-flow / thin-ship wave-resistance code (Michell
integral, or a panel method with a free-surface boundary condition) at tier 1–2;
free-surface RANS CFD at tier 2; a tank test at tier 3. Series data for a known
hull family is often better than all of them and costs an afternoon of reading.

## Free-surface effects of internal liquid — tier 1

Liquid free to move inside the hull reduces GM by i/V per tank, where i is the
second moment of the liquid's free surface. `fluid.metacentric` reports **solid
GM** and does not know your tanks exist.

*What answers it:* arithmetic you can do today — this is a tier-1 gate somebody
should write, taking a list of tanks and subtracting Σ(ρ_liquid·i)/(ρ·V) from GM.
Until it exists, do it by hand and record the corrected GM as a parameter with
provenance. A wide, shallow, part-full tank across the full beam can remove the
entire margin the design thought it had.

## Dynamic stability, capsize and roll — tier 2

GM and GZ in this pack are static, at one angle, in flat water. None of these
questions is answered by them:

- the **angle of vanishing stability**, past which the hull stays over
- the **area under the GZ curve** — the energy it takes to capsize
- the **roll period** and whether it resonates with the seaway
- **downflooding angle** — the heel at which a vent or hatch goes under
- recovery from a **knockdown** or from **inverted**

*What answers it:* full hydrostatics software computing a GZ curve at each heel
from the actual hull geometry (tier 1–2, and the standard answer for anything
that carries people); a time-domain seakeeping code for roll response (tier 2);
an inclining experiment plus a roll-decay test for the real KG and damping
(tier 3, and the only thing that settles it).

## Trim, longitudinal stability and the flotation attitude — tier 1

This is the nearest thing to the pack that the pack does not do, and it is the
one most likely to be assumed away, because it sits immediately behind three
gates that all go green.

Everything hydrostatic here is **transverse**. `waterplane_inertia_m4` is the
transverse second moment about the centreline; BM, GM and GZ are transverse; and
the draft is a single number, V/Awp, which is another way of saying the pack
assumes the hull floats level. It never asks where the longitudinal centre of
gravity is, it never compares it to the longitudinal centre of buoyancy, and it
has no longitudinal GM.

A hull whose LCG is forward or aft of its LCB trims until the two line up, and
then:

- the **lowest deck edge** is materially lower than `fluid.freeboard`'s single
  figure, which is the average — so the gate that claims to measure reserve is
  the one being optimistic,
- the **waterline length and shape change**, so Awp and therefore BM are not what
  was stated,
- and **downflooding** arrives at the low end first, at a heel the transverse
  numbers call comfortable.

*What answers it:* a longitudinal moment balance, which is closed form and
genuinely tier 0–1 — sum the moments of every mass about a datum, find LCG, find
LCB from the immersed shape, and solve for the trim that equalises them; then
hydrostatics software (tier 1) for the real thing, which computes the whole
hydrostatic table at each draft and trim from the actual hull. An inclining
experiment (tier 3) settles the real KG and LCG and nothing else does.

*Symptom you are in this territory:* anything heavy is not amidships — an engine
aft, a battery bank forward, a crane, a winch, a person who moves.

## Static lift, the pump duty point and pipe networks — tier 0–1

Three separate gaps on the same gate.

**Static lift** is now modelled, but only as a number you state:
`fluid.pipe_pressure_drop` subtracts `static_lift_m` from the head supplied
before comparing anything, with the sign convention positive-upward. What it
cannot do is find the lift for you, and it does not know about pressurised
vessels at either end.

**The duty point** is not found at all. The gate takes `pump_head_m` as the head
at this flow. A real centrifugal pump's head falls as flow rises, and the
operating point is where its curve crosses the system curve (static lift plus a
loss term going as roughly Q²). State a head from the curve at the flow you
actually intend, or the gate is comparing a loss at one flow against a head at
another.

*What answers it:* plot the system curve from this gate at three or four flows
and cross it with the manufacturer's pump curve — tier 0, half an hour, and the
standard method.

**Networks.** One bore, one length, one ΣK. Branches, manifolds, parallel paths,
rings and anything where the flow split is an unknown rather than an input are
outside this gate. Applying it to each leg of a branched system and adding the
answers is wrong, because the legs do not carry the flow you assumed.

*What answers it:* Hardy Cross or a linear-theory network solve (tier 0–1, and
implementable in a page); EPANET or an equivalent for anything with pumps,
tanks and controls (tier 1).

## Slamming and wave impact — tier 2

A hull re-entering after a wave sees a pressure pulse that is set by impact
velocity and deadrise, is over in milliseconds, and can be many times the static
pressure at the same depth. It sizes bottom panels and it breaks things that were
comfortable in every steady calculation.

*What answers it:* classification-society scantling rules (tier 1, and the
sensible first answer — they encode decades of this); explicit-dynamics FEA with
a fluid-structure coupling or an SPH impact model (tier 2); drop tests (tier 3).

## Yaw, course-keeping and manoeuvring at speed — tier 2

Directional stability is a balance between the hydrodynamic side force on the
hull and the restoring moment from whatever is aft. Nothing in this pack has any
concept of a lateral plane, a yaw rate, or a rudder.

*What answers it:* manoeuvring coefficient estimation from hull-form regressions
(tier 1); captive-model or rotating-arm CFD to get the derivatives (tier 2);
free-running model tests (tier 3).

## Sloshing — tier 2

The transient counterpart of the free-surface correction: liquid in a partly
filled tank moving in resonance with the vessel's motion, producing impact loads
on the tank walls and a time-varying moment nobody accounted for.

*What answers it:* volume-of-fluid CFD (tier 2), or baffles and a rule of thumb
(tier 0, and usually the right engineering answer — divide the tank).

## Vortex shedding and vortex-induced vibration — tier 2

A bluff body in a steady stream sheds vortices at a frequency f ≈ St·v/D, with
Strouhal number about 0.2 for a cylinder over a wide Reynolds range. If that
frequency approaches a structural natural frequency, the body resonates and the
oscillating side force is comparable to the steady drag this pack computed. Struts,
masts, tow cables and periscopes have all been lost this way, and
`fluid.drag` reports a comfortable steady number the whole time.

*What answers it:* a Strouhal-frequency check against modal analysis (tier 0–1 —
and this is worth writing as a gate the moment you have a slender member in a
steady flow); unsteady CFD with a structural coupling (tier 2).

## Cavitation — tier 2

Where local pressure falls below the vapour pressure of the liquid, vapour
cavities form and then collapse, which erodes metal, makes noise, and destroys
propeller and pump performance. Bernoulli plus a vapour-pressure table gives a
first cut on a known velocity field; this pack does not compute a velocity field.

*What answers it:* cavitation-number screening against published inception data
(tier 0–1); a cavitating CFD model or a cavitation tunnel (tier 2–3).

## Water hammer and transients — tier 2

`fluid.pipe_pressure_drop` is steady state. Close a valve quickly and the pressure
surge is roughly ρ·a·Δv, with a the wave speed in the pipe (order 1000 m/s in
rigid pipe with water) — which for a 2 m/s line is a couple of megapascals,
against a steady drop measured in kilopascals. Three orders of magnitude, and the
steady gate is silent.

*What answers it:* the Joukowsky equation for an upper bound (tier 0, and do it
now — it is one line); method-of-characteristics transient analysis for the real
surge with reflections (tier 1–2).

## Two-phase and cavitating flow, and free-surface flow in channels — tier 2

Any entrained air, boiling, condensation, slurry, or a pipe that is not running
full. The friction factor in this pack describes a single-phase liquid filling
the bore. Partly filled pipe is open-channel flow and wants Manning or
Chezy — different equations entirely.

*What answers it:* two-phase correlations (Lockhart-Martinelli and its
descendants) at tier 1; multiphase CFD at tier 2; open-channel hydraulics at
tier 0–1 with the right formula.

## Compressible flow — tier 1

Everything here assumes constant density. That fails for a gas above roughly
Mach 0.3, and it fails for any long gas line where the pressure drop is a
significant fraction of the absolute pressure — because the gas expands as it
goes and the velocity rises along the run.

*What answers it:* isothermal or adiabatic compressible pipe-flow relations
(Fanno flow), which are still closed form (tier 0–1); a compressible solver for
anything with shocks (tier 2).

## Buoyancy-driven and thermally coupled flow — tier 2

Natural convection, thermosiphons, stack effect, stratification. There is no
temperature anywhere in this pack.

*What answers it:* dimensionless screening with Rayleigh and Grashof numbers plus
published Nusselt correlations (tier 0–1, and usually enough); conjugate heat
transfer CFD (tier 2).

## Added mass and unsteady loads — tier 1

A body accelerating in a fluid drags fluid with it, so it behaves as if it were
heavier — for a sphere, by half the mass of the fluid it displaces. This changes
natural frequencies and acceleration loads and it is invisible to every steady
calculation here.

*What answers it:* published added-mass coefficients by shape (tier 0–1);
potential-flow panel codes for an arbitrary shape (tier 1–2).

## Boundary-layer transition, roughness and fouling — tier 2

Where the boundary layer transitions sets skin friction, and this pack's Cd table
assumes smooth bodies in low-turbulence flow. A fouled hull can carry several
times the skin friction of a clean one, and surface roughness moves the drag
crisis to a different Reynolds number entirely.

*What answers it:* flat-plate friction lines with a roughness allowance (tier 0–1
— the standard ship-resistance approach); transition-modelling CFD (tier 2);
and in practice, a fouling allowance from operating experience.

---

## The standing caveat

A clean sweep of this pack means the closed-form arithmetic is satisfied, at one
loading condition, at rest, in still water, with correlations used inside the
ranges they were fitted over. It is not a seaworthy vessel, not a commissioned
system, and not a substitute for putting the thing in water with a person
watching. Say that in the readiness report, every time.
