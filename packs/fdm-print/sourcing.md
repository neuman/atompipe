# Sourcing: filament, and what it actually does

The constraints here are not physics. They are what the material does in a room, on
a shelf, in a box in transit, in the sun. None of it is in a datasheet, and most of
it decides whether a design that passes every gate is a product.

## The honest note first

**Published coupon strength overstates a printed part by roughly 30–50% in the
layer-normal direction, and by 10–20% even in-plane.**

The tensile numbers a filament vendor prints on the spec sheet come from an
injection-moulded or extruded specimen, or from a printed one along its strongest
axis with the settings tuned for the test. A part printed on your machine has
voids between beads, a weld at every layer boundary that is worth about half the
bead, and a thermal history nothing like the coupon's. Use the published number to
compare two materials to each other. Do not use it as the allowable in a structural
calculation and then also let the part be loaded across its layers — that is the
same optimism applied twice. `fdm.layer_alignment` exists for exactly that stack of
errors.

If the load matters, the honest sequence is: derate, orient, and then **break one**.
A physical claim with a real result beats any amount of arithmetic.

## The materials

Temperatures are starting points; every machine and every spool differs by 10–15 °C.

| | PLA | PETG | ABS | ASA | TPU (95A) | PA-CF |
|---|---|---|---|---|---|---|
| Nozzle °C | 195–215 | 230–250 | 240–260 | 245–265 | 215–235 | 260–290 |
| Bed °C | 50–60 | 70–85 | 95–110 | 95–110 | 35–50 | 60–80 |
| Enclosure | no | helps | **required** | **required** | no | **required** |
| Warp tendency | very low | low | high | high | very low | moderate |
| Stringing | low | **high** | low | low | high | moderate |
| Moisture | slow | moderate | low | low | **fast** | **very fast** |
| UV outdoors | poor | moderate | **poor** | **good** | moderate | moderate |
| Heat (softens ~) | 55–60 °C | 75–80 °C | 95–100 °C | 95–100 °C | 60–80 °C | 130 °C+ |
| Density g/cm³ | 1.24 | 1.27 | 1.04 | 1.07 | 1.21 | 1.10 |
| Realistic tolerance | ±0.15 mm | ±0.2 mm | ±0.3 mm | ±0.3 mm | ±0.4 mm | ±0.3 mm |
| Layer-bond quality | fair | **good** | fair | fair | excellent | poor without drying |

"Realistic tolerance" is what a well-tuned hobby-class machine holds on a 50 mm
feature after the usual calibration, not what it holds on a 5 mm one. Small features
do better in absolute terms and worse in relative terms. Anything tighter than these
numbers needs either a designed-in adjustment, a post-machining step, or a different
process.

### PLA

The default, and it is the default for good reasons: it prints cold, it does not
warp, it holds detail, and it is stiff. It is also brittle, it creeps under sustained
load at room temperature, and it softens in a parked car. Anything that must hold a
load for months, or sees sun through a window, is the wrong application.

### PETG

The quiet best choice for functional parts that live indoors. Tougher than PLA, much
better layer adhesion (it is the one material where the layer-normal knockdown is
closer to 0.7 than 0.5), no enclosure needed, and it survives a hot car. It strings
badly, it is soft enough to scuff, and it sticks to smooth PEI hard enough to take
the sheet's coating with it — use a textured sheet or a glue-stick release layer.

### ABS

Chosen for heat resistance and because it can be vapour-smoothed and glued with
solvent. It also warps, cracks between layers on tall parts, needs a heated chamber
to do either of those less, and emits a smell that people in the room will comment
on. It degrades in sunlight — it yellows, then chalks, then cracks.

### ASA

ABS with the UV problem fixed. Same printing difficulty, same enclosure requirement,
same solvent behaviour, and **it is the honest answer for a part that lives
outdoors.** If a design says "outdoor" and the material says PLA or ABS, that is a
finding, not a preference.

Everything else is a compromise outdoors: PETG survives a season or two and slowly
loses toughness; polycarbonate is strong and yellows; PLA fails in months, faster if
it is also loaded.

### TPU

Flexible, and the layer bond is excellent because the material is a network rather
than a glass. It prints slowly — 6–20 mm/s on a bowden machine, because the
filament buckles in the tube instead of pushing — which is why a TPU part is often
a multi-hour print of something small. It absorbs water fast enough to matter within
a day of opening.

### PA-CF (carbon-filled nylon)

Stiff, dimensionally good for a nylon, genuinely strong in-plane — and the worst
material in this table for layer bonding unless it is bone dry. Nylon picks up water
from the air in hours, and wet nylon prints with visible steam, a rough surface and
a layer bond you can snap with your fingers. It needs a dryer running *during* the
print, not just before it. Carbon fill is also abrasive: a brass nozzle is gone in a
few hundred grams, so a hardened steel nozzle is not optional, and a hardened nozzle
usually means a slightly larger minimum wall.

## Procurement constraints that bite

- **Colour is not free.** A specific colour in a specific material from a specific
  vendor is a single SKU with a single stock level. Designing a two-colour product
  around a colour that is out of stock for six weeks is a real failure mode. Where
  possible, specify "any colour of X" and let the build choose.
- **Spool size sets the batch.** One kilogram is the unit. A part that eats 300 g
  means three parts per spool and a stub of filament that is not enough for a
  fourth. `fdm.print_time_est` reports grams for this reason.
- **Filament diameter tolerance** is a spec people ignore until it matters: ±0.05 mm
  is ordinary, ±0.02 mm is a premium line, and the cheap end of the market is
  sometimes ±0.10 mm, which shows up as visible flow variation on a surface.
- **Dryers are consumables in disguise.** A design that specifies nylon has
  specified a dryer, a sealed storage box and desiccant that needs regenerating. Say
  so in the bill of materials rather than discovering it on print day.
- **Hardened nozzles change the process.** Any filled filament — carbon, glass,
  glow, metallic, wood — needs one. The bore is usually a little rougher, which
  costs some surface finish, and a hardened 0.4 mm nozzle behaves like a slightly
  larger one for minimum-wall purposes.
- **Vendor formulations drift.** "PLA" from two vendors is two materials with the
  same name; "PLA+" and "Tough PLA" are marketing terms covering a wide range. If a
  print profile is tuned, record the vendor and the line, not just the polymer.
- **Recycled and bio-filled lines** vary batch to batch far more than virgin
  material. Fine for enclosures, poor for anything dimensional.

## What to record in the ledger

For any part whose material matters, record as parameters with provenance: the
polymer, the vendor and line, the nozzle and bed temperature actually used, whether
it was dried and for how long, the nozzle diameter and material, and the layer
height. A print that works and cannot be reproduced is an anecdote.
