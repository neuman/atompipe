# Adversarial lenses — fluids

Run these before anything is built. Every one of them has changed a number on a
real design, and none of them costs anything but an hour of arguing. The most
expensive mistakes in this domain are the ones that get wet.

Attack from each heading independently. A reviewer who holds all seven in mind at
once finds none of them.

---

## 1. Loading condition — which one did you check?

You almost certainly checked the one on the drawing. That is rarely the one that
sinks.

- **Empty.** Draft is minimal, freeboard is maximal, and the centre of gravity
  may be *higher* than when loaded if the payload lives in the bilge. An empty
  hull can be the least stable one. Did you run the gates at empty?
- **Design load.** The one in the model. Fine.
- **Full.** Every tank full, every locker full, maximum crew, maximum payload,
  and the mass that always appears late — cable, fasteners, sealant, paint,
  water absorbed by foam, mud. What is the real all-up mass, and who weighed it?
- **Swamped.** The compartment is full of water and the vessel is floating on
  whatever sealed volume remains. Does anything float then? If the answer is "we
  will not let that happen", that is an assumption, not a claim — record it.
- **Asymmetric.** Everyone on one side. One tank full, the other empty. The
  righting arm you computed assumed the mass was on the centreline.

Run `fluid.buoyancy`, `fluid.freeboard` and `fluid.metacentric` at **each**
condition, not just the design one. They cost a millisecond each. There is no
excuse for having checked only one.

## 2. Free surface — liquid that is free to move inside the hull

This is the lens that catches people who did everything else right.

A part-full tank is not ballast. When the vessel heels, the liquid in it runs
downhill, moving the centre of gravity in the direction of the heel and
*reducing* GM by roughly i/V — where i is the second moment of the **free surface
of the liquid** and V is the vessel's displaced volume. The effect depends on the
tank's width cubed and not at all on how much liquid is in it: a tank with
twenty litres sloshing in it is as bad as one with two hundred, and a wide
shallow tank is far worse than a deep narrow one.

Ask:

- Which volumes inside the hull can hold liquid and are not full? Tanks, bilge,
  sumps, the void under a floor, a battery box that has ever had condensation in
  it.
- Is any of them wide? A single full-beam tank can wipe out the whole GM margin
  the design has.
- Would a baffle or two longitudinal divisions fix it? (Dividing a tank into n
  equal-width cells divides the free-surface effect by n².)
- Has the free-surface correction actually been subtracted from the GM the gate
  reported? `fluid.metacentric` does **not** know your tanks exist. It reports
  solid GM. If you have not subtracted the correction by hand, the gate's margin
  is fictitious.

## 3. Static versus dynamic stability — a positive GM is not "it stays upright"

`fluid.metacentric` answers one question: does a righting moment appear at an
infinitesimal heel. That is necessary and nowhere near sufficient.

- **At what angle does the righting arm peak, and at what angle does it vanish?**
  The angle of vanishing stability is the one that matters in a knockdown, and no
  gate in this pack can find it. A GZ curve from full hydrostatics can.
- **When does the deck edge immerse?** Past that angle the waterplane collapses
  and the righting arm can fall off a cliff. A stiff, high-GM hull can reach deck
  immersion sooner than a tender one.
- **How much energy is under the curve?** A gust does work; resisting it takes
  area under GZ, not a value at one angle. Two hulls with identical GM can have
  very different capsize energy.
- **What is the roll period, and what is the wave period?** A high GM means a
  short, violent roll period — uncomfortable, hard on the structure, and
  dangerous if it matches the seaway. Stiffer is not safer.
- **Does it come back from 90 degrees, or from inverted?** If the answer matters,
  this pack cannot tell you and will not pretend to.

## 4. Where the centre of mass actually is — after the battery moves

The KG in the model is a number somebody typed. Attack it directly.

- **Where did KG come from?** A weight study with every item and its height, or a
  guess? If it was a guess, the GM is a guess and the margin is decoration.
- **What moves?** The battery that gets relocated for cable routing. The ballast
  that gets trimmed at commissioning. The crew who stand up. The payload that is
  loaded on deck because it did not fit below. Every one of those is a KG change
  nobody re-ran the gate for.
- **What gets added later?** A mast, a light bar, a canopy, a second sensor, a
  bigger motor. Additions go **up**, almost always, because that is where the
  space is. Run `fluid.metacentric` with a plausible future addition on top and
  see how much margin was actually there.
- **Is the KG datum the same one the draft uses?** Two people measuring from two
  datums is the error that no arithmetic catches. Say which surface is zero, in
  the model, in words.
- **Did the model's mass and the real mass ever get reconciled?** Weigh the
  thing. A 15% mass error is normal in a first build and it moves both draft and
  KG.

- **Where is the mass fore and aft?** Every gate in this pack is transverse and
  derives ONE uniform draft, so it assumes level flotation and cannot see trim.
  Sum the moments of every item about a datum, find the longitudinal centre of
  gravity, and compare it with the centre of the immersed volume. If they are not
  over each other the hull floats down by the head or the stern, the lowest deck
  edge is below the freeboard the gate reported, and downflooding arrives there
  first. This is arithmetic, not a solver — do it.

## 5. When it takes water

Assume it floods. What then?

- **Which compartment floods first, and does the hull still float with it full?**
  Reserve buoyancy in a *sealed* volume is what answers that; volume that
  communicates with the flooded space is not reserve.
- **Is the "watertight" volume in the model actually watertight?** A cable gland,
  a vent, a hatch with a compressed foam seal, a printed part with a seam, a
  fastener through the hull below the waterline. Each is a hole until somebody
  proves it is not, and that proof is a PHYSICAL claim — a real object in real
  water — not a gate.
- **Does the flooded condition capsize it before it sinks it?** Water in a
  compartment is the worst possible free surface: full beam, full length, no
  baffles. Many vessels go over before they go down.
- **Where does water that gets aboard go, and how does it leave?** A deck that
  holds a hundred litres in a corner has added a hundred kilos in the worst
  place.
- **Foam or air?** Sealed air volumes fail closed-loop: one puncture and the
  reserve is gone. Closed-cell foam fails gracefully and absorbs a few percent
  water over years. If the design's survival depends on reserve buoyancy, which
  kind is it, and was that a decision or an accident?

## 6. Flow regime — is the correlation being used where it was measured?

Every number `fluid.drag` and `fluid.pipe_pressure_drop` produce rests on a
correlation fitted over a range.

- **What is the Reynolds number, and did anyone look at it?** If the answer is
  "no", the Cd is a number with no regime and the friction factor may be off by
  an order of magnitude.
- **Does the design cross a regime boundary during operation?** A vessel that
  cruises at Re 3e5 also starts from rest. A pump that is throttled runs down
  into the transition band. The gates check the stated operating point; the
  design has a range.
- **Is the reference area for the Cd the one this pack assumes?** Frontal. Not
  wetted, not planform.
- **Is the shape actually the tabulated shape?** A cylinder with a fairing, a
  cylinder in the wake of another cylinder, a cylinder near a free surface, and a
  cylinder near a wall all have different Cd from "cylinder".

- **Is the roughness in metres, and is ε/D on the chart?** A table value copied
  in millimetres is a factor of a thousand and never looks wrong. Colebrook and
  the Moody chart stop at ε/D ≈ 0.05, which a coarse-concrete or riveted-steel ε
  crosses in any small bore — `fluid.flow_regime` refuses past it, and refuses a
  turbulent f outside 0.008–0.08 for the same reason.

## 7. The system around the number

- **Is the pump curve a point or a curve?** `fluid.pipe_pressure_drop` compares
  against a head you stated. A real pump delivers less head as flow rises; the
  operating point is where the two curves cross, not where you hoped.
- **Has the elevation been paid before the friction?** Static lift is a demand on
  head, not a supply of it, and the two have opposite signs. State it as
  `static_lift_m`; a pump with a 10 m curve point lifting 8 m has 2 m for the
  pipe. Getting that backwards inflates the budget and the verdict looks calmer
  than the system is.
- **Is it one pipe?** The gate models one bore, one length, one ΣK. A branch, a
  manifold or a parallel path does not carry the flow you assumed, and applying
  the gate leg by leg and adding the answers is wrong.
- **Do the minor losses get counted?** In a short system, bends, valves,
  strainers and the entry can outweigh the straight run. A `sumK` of zero in a
  verdict is a red flag, not a clean result.
- **What happens as things foul?** Roughness grows, strainers clog, K rises. Was
  the budget checked against the aged system or the new one?
- **What is the consequence of being wrong by 30%?** If a 30% error is a slightly
  slow boat, ship it. If it is a pump that cannot prime, spend the extra day. The
  right amount of rigour is set by the cost of the error, and that is a question
  only the reviewer can ask.
