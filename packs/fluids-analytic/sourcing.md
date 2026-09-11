# Sourcing and real-world constraints — fluids

The things that make a fluid design orderable and serviceable rather than merely
correct. None of it is physics and none of it is in a datasheet.

## Pipe and tube: the size on the label is not the bore

- **Nominal size is a name, not a dimension.** "1 inch pipe", "DN25", "25 mm
  pipe" — none of those is an internal diameter. Schedule or pressure class sets
  the wall thickness, and the bore is what is left. Since Δp goes roughly as
  1/D⁵ at fixed flow, a 10% bore error is a 60% pressure-drop error. Get the
  internal diameter from the manufacturer's dimension table and record where it
  came from.
- **Tube is measured by outside diameter, pipe by nominal bore.** Mixing the two
  conventions in one bill of materials is a standing source of parts that do not
  fit and lines that do not flow.
- **Metric and imperial tube are not interchangeable**, and the near-misses are
  worse than the obvious mismatches: a compression fitting will appear to tighten
  onto the wrong-size tube and will leak under pressure later.
- **Availability is not uniform across sizes.** The common sizes are stocked
  everywhere and the intermediate ones are a special order with a lead time. If
  a design needs a size that is not in the local distributor's standard list,
  that is a schedule risk, and the honest fix is usually to move the design to
  the stocked size rather than to wait.

## Fittings and joints

- **Every fitting is a pressure drop.** They are also where leaks happen. A
  design with fewer, larger-radius bends is cheaper to build, cheaper to run and
  less likely to weep. Count the K total before congratulating yourself on a
  short run.
- **Thread standards look alike and are not.** Parallel and tapered threads of
  the same nominal size will start and then either leak or split the female
  part. Specify the standard, not the size.
- **Sealing method is part of the spec.** Thread sealant, PTFE tape, an O-ring
  face seal and a metal-to-metal cone are different decisions with different
  pressure and temperature limits, and different rules about whether the joint
  can be re-made.
- **Barbed fittings need the right clamp.** A hose that fits a barb by hand is
  not a joint. Pressure rating on a barb assumes a correctly sized clamp at the
  correct torque, and a worm-drive clamp on soft tubing will cut it over time.

## Materials in contact with the fluid

- **Chemical compatibility is a table lookup you must actually do.** Elastomer
  and plastic compatibility with the specific fluid, at temperature, decides
  whether a seal swells, hardens or dissolves. "It is just water" stops being
  true the moment there is glycol, a biocide, a surfactant or salt in it.
- **Galvanic pairs matter wherever two metals share an electrolyte.** Seawater is
  an excellent electrolyte. A dissimilar-metal joint below the waterline is a
  corrosion cell with a service life, and the anode is whichever part you did not
  intend to sacrifice.
- **UV kills plastics that live outside.** Unstabilised polymer tubing in
  sunlight becomes brittle in a season. Specify a UV-stabilised grade or shade it.
- **Temperature derates pressure.** A plastic pipe's pressure rating at 20 °C can
  halve by 60 °C. Rate the system at its hottest real condition, including a
  vehicle interior or a sealed enclosure in the sun.

## Pumps and the operating point

- **A pump has a curve, not a rating.** Head falls as flow rises. The system
  operates where the pump curve crosses the system curve — and the system curve is
  what `fluid.pipe_pressure_drop` computes. A budget stated as a single head
  number is a simplification; check the curve at the intended flow.
- **Priming and NPSH are separate constraints** from head. A pump that cannot
  lift its own prime, or that cavitates because the suction side is too
  restricted, meets its head spec and does not work.
- **Filters and strainers load up.** Their K rises with service. If the head
  budget only closes with a clean element, the system works until the first
  maintenance interval and then does not.
- **Lead times on pumps and valves are long** relative to the rest of a build,
  and specifying an unusual port size or voltage extends them further. Choose from
  what is stocked unless there is a reason not to, and record the reason.

## Buoyancy and flotation hardware

- **Sealed air volume and closed-cell foam fail differently.** A sealed void
  gives all its reserve buoyancy back for one puncture; closed-cell foam loses a
  few percent to water absorption over years and keeps working when damaged. If
  the design's survival depends on reserve buoyancy, that is a decision to record
  with its rejected alternative, not a detail.
- **Foam density is a trade, not a number to maximise.** Denser foam displaces
  the same volume and weighs more; the useful figure is net buoyancy per litre,
  and it falls as density rises. Very low density foams crush under hydrostatic
  pressure at depth.
- **Through-hull fittings are the design's weakest claim.** Every penetration
  below the waterline is a hole somebody has promised is sealed. Prefer fewer,
  larger, serviceable penetrations to many small ones, and treat the seal as a
  PHYSICAL claim settled by a real immersion test, never by a gate.
- **An IP rating is not a submersion rating, and a submersion rating is not a
  depth rating.** Ingress ratings are tested for a stated time at a stated depth,
  usually briefly and in fresh water, usually static. Continuous immersion,
  pressure cycling and warm water are all outside them.

## Assembly, service and the long tail

- **Can it be drained?** A system with no low-point drain must be dismantled to
  be emptied, and that is discovered in the first cold snap or the first shipment.
- **Can it be vented?** Trapped air in a high point stops flow, causes noise, and
  makes a pump lose prime. Every high point needs a vent or a deliberate slope.
- **Can a person reach the joint that will leak?** Serviceability is designed in
  at the routing stage and cannot be added later.
- **Where does a leak go?** Design the failure: a joint over an electronics bay is
  a different risk from the same joint over a drain, and moving it costs nothing
  on the drawing.
