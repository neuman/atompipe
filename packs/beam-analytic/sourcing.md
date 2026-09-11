# Sourcing reality for structural members

The constraints that are not physics. A section that analyses beautifully and
cannot be bought is a drawing, not a design.

## Stock comes in sizes, and the sizes are not continuous

A closed-form optimiser will happily tell you the answer is a 9.3 mm thick plate.
Nobody stocks 9.3 mm. Design to the stock size above your requirement and put the
spare margin in the report rather than pretending to a precision the supply chain
does not have.

- Metric flat bar and plate step in coarse increments, and the increments get
  coarser as the material gets thicker. The step *below* your number is a
  re-analysis, not a rounding.
- Extruded profiles are whatever the extruder has a die for. A custom die is a
  tooling charge and a minimum run measured in hundreds of metres.
- Tube is sold by outer diameter and wall, and the popular wall thicknesses are a
  short list. An unusual wall is a mill order.
- Sheet metal thickness is a gauge table, not a millimetre value, and the gauge
  tables differ by material.
- Timber and panel products are sold at nominal sizes that are not the actual
  sizes, and the actual size varies with moisture content.

## Availability is regional and it moves

- Common structural alloys are everywhere; the high-strength ones are not, and
  the lead time on a specific temper in a specific size can be months.
- Stainless in a given grade and finish is routinely the long pole in a small
  build.
- Engineering polymers in sheet or rod form are frequently minimum-order-quantity
  items even when the material itself is common.
- A supplier substituting "an equivalent grade" is normal, is usually fine, and
  is occasionally the reason a design that passed analysis fails. If the analysis
  depends on a specific yield, say so on the drawing and require the certificate.

## Certificates, and what a number on a website is worth

Three tiers of material provenance, and they are not interchangeable:

1. **A mill certificate** for the actual heat you received. This is a measurement.
2. **A published typical value** from the producer. This is a central estimate;
   the minimum can be meaningfully lower.
3. **A number in a table** — including this pack's — which is an order of
   magnitude for early design and nothing more.

If a claim in the readiness report depends on a material property, record which
of the three it came from. A PROVEN row resting on tier 3 is not proven, and
saying so is the whole point of the report.

## Process constrains section before strength does

- **Machined from solid**: nearly any section, at the cost of everything you cut
  away. Deep narrow pockets need a long thin cutter and will chatter; ask for the
  aspect ratio limit before designing to it.
- **Sheet metal**: bend radius has a minimum (roughly the material thickness for
  soft alloys, more for hard ones), bends need relief, and a bend near a hole
  distorts the hole. Flat patterns have a grain direction and bending across the
  grain cracks some tempers.
- **Extrusion**: constant section only, wall thickness must be reasonably uniform
  or the profile cools unevenly and twists.
- **Casting**: draft angles, uniform walls, and a fatigue performance well below
  wrought. Do not apply wrought numbers to a cast part.
- **Welding and brazing**: the heat-affected zone is weaker than the parent metal,
  sometimes dramatically so for heat-treated alloys, and the weakest point is
  right where the analysis assumed a fixed end.
- **Additive**: see `references/materials.md`. Orientation is a structural
  decision, not a print-farm one, and it must be recorded as a parameter with
  provenance rather than left to whoever loads the plate.

## Fasteners

- Standard sizes, standard lengths, standard grades. A length between standards
  means a custom part or a stack of washers.
- Grade matters and is frequently ignored: an unmarked commodity bolt and a high
  grade bolt of the same diameter differ by a factor of two or more in strength.
- In a polymer or a thin plate, the bolt is rarely the weak part — the thread
  engagement, the bearing wall, or the boss is. Threaded inserts are a real
  design element with their own installed-strength data; get it from the insert
  supplier, not from the plastic's datasheet.
- Corrosion pairs: a stainless fastener in an aluminium part is a galvanic cell
  wherever it gets wet. That is a lifetime constraint, not an assembly detail.

## The constraint nobody writes down

Ask what the shop actually has. A design that uses the offcut rack, the drill
sizes already in the cabinet and the one extrusion the supplier keeps in stock
gets built this week. The optimal design gets quoted, and then gets re-designed.
