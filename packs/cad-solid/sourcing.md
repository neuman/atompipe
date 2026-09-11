# Sourcing reality for solid geometry

The constraints that are not physics: what happens to your geometry between your
disk and somebody else's machine.

## Exchange formats

| Format | Carries | Loses | Use it for |
|---|---|---|---|
| STEP (AP214/AP242) | exact surfaces, assembly structure, units, sometimes colour and PMI | feature tree, parameters | anything a vendor will machine or re-model from |
| STL | triangles only | units, assemblies, colour, provenance | printing, and only after you have fixed the units by convention |
| 3MF | triangles, units, colour, multiple objects | exact surfaces | printing, when the far end supports it |
| OBJ | triangles, groups, materials | units, solidity guarantees | rendering, never manufacturing |
| IGES | surfaces | solidity — it is a surface format | legacy interchange only; expect to stitch |

**STL has no units.** A number in an STL file is a number. Every consumer assumes
millimetres by convention and nothing enforces it, so a metre-scale export arrives
as a 0.08 mm part and a quoting tool will accept it. State the units in the
filename if you have nowhere else to put them.

**Send STEP to a machinist, mesh to a printer.** A shop that has to re-model from a
mesh will quote for the re-modelling, and the part they make is their interpretation
of your tessellation.

## What the far end does to your file

Assume every recipient runs a repair pass you cannot see:

- Quoting tools re-mesh to their own tolerance to compute volume and bounding box.
  Your 41,200 mm³ may be quoted as a slightly different number. That is normal;
  a *large* discrepancy means one of you is reading a defect differently.
- Slicers repair aggressively — they will close holes, drop degenerate faces and
  re-orient windings, and then slice something that is not quite what you sent.
  A mesh that only works because the slicer repaired it works differently on the
  next slicer version.
- Some vendor portals silently reject non-manifold geometry with a generic error.
  Others accept it and print the repair. The second is worse.

This is the practical argument for validating the bytes you send rather than a
repaired in-memory copy: you are the only party in the chain who knows what the file
was supposed to be.

## Tessellation settings are a procurement decision

The chord-height and angular-deviation settings you export with determine file size,
surface quality on curves, and how much tessellation noise the clash tolerances have
to absorb. Pin them, record them, and re-run the sweep when they change:

- too coarse: visible faceting on curved surfaces, UNDER-reported wall thickness on
  curves (the ray leaves from a chord that sits inside the true surface, so it
  crosses `t*cos(pi/N)`, not `t` — 7.6% short at 8 facets around the curve; the
  error is conservative, and it is still an error you are calibrating margin
  against), clash noise that forces a loose tolerance which then hides real
  interference;
- too fine: files large enough that the vendor's uploader times out, and sweeps that
  stop being runnable in an inner loop.

Record the settings next to the part, not in somebody's export dialogue.

## Vendor and library models

- A supplier's STEP model of a bought-in component is a **marketing artifact as
  often as a dimensional one**. Envelopes get simplified, connectors get idealised,
  moulded draft disappears. If a clearance depends on it, measure the real part.
- Downloaded models frequently arrive as surface bodies or as non-solid assemblies.
  Run `cad.is_volume` on anything you did not build before you boolean against it.
- Licence terms on downloaded geometry are real and are usually ignored. Record the
  source and the terms with the file; a model redistributed inside a manufacturing
  package is redistribution.

## Lead time and the cost of being wrong

The reason these gates exist at the export boundary rather than as a report:

- A rejected upload costs a day. A quietly repaired upload costs a batch.
- Tooling and fixtures are cut from the geometry you sent, not the geometry you
  meant. An interference found after the tool is cut is a new tool.
- Printed prototypes are cheap and forgiving, which trains a habit that does not
  survive the first moulded or machined run. The gate that protects you there is the
  one that refuses to emit a manufacturing package, not the one that prints a
  warning.
