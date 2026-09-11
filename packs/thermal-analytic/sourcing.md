# Sourcing: the thermal constraints that are not physics

A design can be thermally correct and unorderable. This file is the knowledge that
makes it buildable, and almost none of it is in a datasheet.

## Insulation

- **Thickness comes in steps, not in millimetres.** Board insulation is sold in a
  short list of thicknesses (commonly 25, 50, 75, 100, 150 mm). A model that
  derives 63 mm will be built as 50 or as 75, and it should be the model that
  makes that choice, not the installer. Round in the model and record which way
  and why.
- **Aged versus initial k.** PIR and polyiso are quoted at an aged value in some
  markets and an initial value in others; the difference is 10-20% and it is the
  aged value you will live with. Check which one your table is.
- **Compression destroys it.** Batt insulation squeezed into a cavity thinner than
  its nominal loses resistance faster than the thickness ratio, because the
  conduction path through the fibres shortens while the trapped air is squeezed
  out. Specify the cavity to the batt, not the batt to the cavity.
- **Fire rating usually decides the material before thermal performance does.**
  In many jurisdictions combustible insulation is prohibited above a certain
  building height or in certain cavities regardless of its k. Check the
  requirement before optimising the number.
- **Vacuum panels cannot be cut, drilled or fixed through.** One puncture takes
  them from ~0.005 to ~0.02 W/mK. They must be sized and ordered to the exact
  finished dimension, with long lead times, and any site adaptation is a redesign.
- **Aerogel blanket is expensive, dusty and compresses under fixings.** It buys
  thickness in places where thickness is the constraint; do not use it where a
  cheap board fits.

## Glazing and covers

- Solar glass is normally **low-iron tempered**, because ordinary float glass
  loses several percent of transmittance to iron absorption and because an
  untempered cover fails dangerously under thermal shock and hail. Low-iron
  tempered is a stock item in standard sizes and a long-lead custom item outside
  them.
- Tempered glass **cannot be cut or drilled after tempering.** Every hole, notch
  and edge treatment must be in the order.
- Polycarbonate is cheap, unbreakable and yellows under UV. Acrylic holds
  clarity longer and cracks. Both creep at stagnation temperatures. For anything
  that will stagnate, glass is usually the only honest answer.
- Anti-reflective coatings add a few percent of transmittance and a real premium,
  and some are not durable outdoors for the life of the collector. Ask for the
  warranty terms, not just the transmittance.

## Absorber coatings

- Selective coatings (black chrome, sputtered TiNOx-type) are applied by a
  **coating house on strip or sheet, before fabrication.** You cannot spray them
  on an assembly, and the coater's line width sets the maximum absorber width.
- Minimum order quantities on sputtered strip are real and can be measured in
  coils. Prototype quantities usually mean buying pre-coated absorber fin stock
  from a distributor at a large premium, or accepting black paint for the
  prototype and re-testing later — which changes both `alpha` and `eps` and
  invalidates the earlier collector numbers.
- Paint is not a substitute for a selective coating. High emissivity cuts output
  at temperature; see `references/materials.md`.

## Heat transfer fluids

- **Propylene glycol, not ethylene**, for anything that can contact a potable
  circuit, and for anything indoors. Ethylene is cheaper, marginally better
  thermally, and toxic.
- Buy **inhibited** glycol formulated for solar or HVAC service, not automotive
  antifreeze. The inhibitor packages are different and the automotive ones do not
  survive stagnation.
- Glycol has a **service life**, shortened dramatically by stagnation events. Plan
  a test and replacement interval and make it accessible — a fill and drain point
  that requires dismantling the array will not be used.
- Glycol cuts specific heat by ~10-20% and raises viscosity substantially at low
  temperature. The pump sized on water will not deliver on 40% glycol on a cold
  morning. This is a system consequence of a freeze-protection decision.
- Silicone and synthetic oils survive stagnation and will find every joint that is
  not rated for them. Seal material is a fluid decision.

## Seals and gaskets

- **EPDM** is the default for solar glazing gaskets: good UV and ozone resistance,
  useful to about 150 degC continuous, and it is incompatible with petroleum oils.
- **Silicone** goes higher (200 degC+) and has poor tear strength and poor
  resistance to some fluids.
- **Viton/FKM** goes higher still, costs many times more, and has poor low-
  temperature flexibility — a real problem in a freezing climate.
- The seal temperature limit is a **stagnation** limit, not an operating one, and
  it is frequently the binding constraint on the whole collector. Decide it before
  the optics.

## Thermal interface materials

- Grease is the best performer and the worst to assemble: it pumps out under
  thermal cycling, it migrates, and it is unpleasant in volume production.
- Pads are repeatable, assembly-friendly, thicker and worse. Their quoted
  resistance assumes a clamp pressure — check what pressure, and whether your
  fastener actually delivers it after the stack has expanded.
- Phase-change pads split the difference and have a shelf life and a storage
  temperature requirement.
- **All of them have a minimum order quantity in sheet form and a die-cutting
  charge** for a custom shape. Prototype quantities come from a distributor's
  precut stock, which constrains you to their shapes.
- Anything applied by hand has an assembly variance that is often larger than the
  difference between two candidate materials. Specify a process, not just a part.

## Heatsinks

- Extruded profiles are cheap **in the extruder's existing die list** and
  expensive outside it. Design to a stock profile and cut to length; a custom die
  is a tooling charge and a minimum run.
- Extrusion aspect ratio is limited — roughly 8:1 fin height to gap in common
  practice. A drawing with taller, thinner fins than that is a skived, bonded or
  folded-fin part at a different price and lead time.
- Die-cast heatsinks have roughly half the conductivity of extruded (see
  `references/materials.md`), and the fin efficiency calculation must use the
  casting alloy's k, not the handbook aluminium figure.
- **Anodising is a separate operation with its own minimum charge and lead time**,
  and it is what buys you the emissivity. Black anodising and clear anodising have
  nearly the same longwave emissivity; the colour is cosmetic. Do not pay for
  black expecting thermal benefit over clear.
- Fin pitch that is serviceable in a dusty environment is much coarser than fin
  pitch that is optimal in a clean one. Ask where it lives before optimising.

## Fans and pumps

- A fan's published curve is free air or a standardised chamber. Your system
  impedance moves the operating point down the curve, and a fan chosen on peak
  flow may deliver a fraction of it.
- Fans are a **wear item with a published L10 life at a stated temperature**, and
  that life roughly halves for every 10-15 K above it. A fan inside the hot
  enclosure it is cooling lives a short life.
- Bearing type sets both life and orientation constraints — some sleeve bearings
  are not rated for horizontal-shaft operation.
- Long-term availability is poor. Fans go end-of-life faster than the products
  they cool, and a footprint-compatible replacement is not thermally equivalent.
  Design the mount to a standard frame size, not to a part number.

## Sensors

- A temperature limit is defined at a point (junction, case, surface, fluid) and
  you can rarely measure at that point. The difference is a thermal resistance and
  it belongs in the model, with provenance.
- Sensor tolerance stacks with placement error and with self-heating. A +-2 K
  sensor protecting a 5 K margin is not protecting anything.
- A sensor in a thermowell has its own time constant, often minutes. If that is
  comparable with the process, the control loop will oscillate and nobody will
  know why.

## Lead times worth knowing before you commit

| Item | Typical | Note |
|---|---|---|
| Stock extruded heatsink, cut | days | |
| Custom extrusion die | weeks + tooling | |
| Anodising | 1-2 weeks | separate vendor, separate minimum |
| Low-iron tempered glass, standard size | days-weeks | |
| Tempered glass, custom | weeks | no post-temper machining |
| Selectively coated absorber strip | weeks, MOQ in coils | |
| Vacuum insulated panels | weeks, made to size | no site adaptation |
| Die-cut TIM, custom shape | weeks + tooling | |
| Inhibited glycol | days | check inhibitor spec, not just concentration |
