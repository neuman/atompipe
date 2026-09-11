# Lenses: how to attack a printed part before you print it

Five dimensions. Run them independently, before anything goes on the bed, and let
the findings change the numbers. The point is not to confirm the design; it is to
find the print that fails at hour nine.

Questions here are deliberately uncomfortable. A lens that a design passes
effortlessly was aimed wrong.

---

## 1. Part orientation

This is the decision. It sets strength, surface finish, support, and time — all
four, simultaneously, and usually in opposition. Everything else on this page is
downstream of it.

- Which way does the load run through the part, and where does it cross a layer
  boundary? Name the specific plane you expect it to break on. If you cannot name
  one, you have not chosen an orientation, you have accepted one.
- What did this orientation cost? There is always a cost. If the answer is "nothing",
  the alternatives were not tried.
- Which surface is the *visible* one, and is it the one lying on the bed (glossy or
  textured, dimensionally best) or the one facing up (layer-stepped on any curve)?
  Those are different products.
- Is there a curved or angled feature that becomes a staircase in this orientation?
  At what layer height does the stepping become visible? Have you looked at it, or
  calculated it?
- If the part were rotated 90°, would it still fit the bed — and is `fdm.bed_fit`'s
  answer based on the orientation you actually intend to print, or the one the model
  happened to be drawn in?
- Would printing it on end fix the layer alignment and create a tall thin tower that
  wobbles, needs a brim, and knocks off at hour six? Which failure would you rather
  have?
- Are you printing it as one part because it is one part, or because splitting it
  and joining it afterwards never got considered? A split along the right plane can
  remove every support in the design.

## 2. Support removal access

Supports that cannot be removed are not supports. They are a permanent feature you
did not draw.

- For every supported region: can a tool physically reach it? Which tool? Through
  what opening, and at what angle?
- Is there any support *inside* a closed or nearly closed cavity? `fdm.overhang`
  cannot see the difference between a face you can reach and one you cannot.
- What does the supported surface look like afterwards? A scarred face is fine on a
  hidden side and a defect on a sealed one. Which face is it here?
- Is a supported surface also a *sealing*, *bearing*, or *mating* surface? Support
  scarring changes dimensions by a tenth of a millimetre or two, unpredictably.
- Would a 45° chamfer or a teardrop profile remove the support entirely? On a
  horizontal hole, replacing the top of the circle with a chamfer or a point costs
  nothing and removes both the support and the bridge.
- If the part needs soluble support, has anyone confirmed the machine has a second
  extruder, the material, the dissolving bath, and the hours? That is a process
  change, not a slicer setting.

## 3. First-layer adhesion and warp on large flat parts

The part is held to the bed by its first layer alone, and shrinkage pulls at the
corners with a lever whose length is the part.

- How large is the flat footprint, in mm², and in what material? A 150 mm ABS plate
  will lift; a 150 mm PLA plate probably will not. Where is the line for this
  material, and has anyone here ever crossed it?
- Are there sharp corners in the footprint? Corners lift first. Would a 3–5 mm
  radius or a mouse-ear pad cost anything?
- Is the part tall and thin, or does it have a small footprint relative to its
  height? What happens when the nozzle catches the top of it on a travel move at
  hour four?
- Does the brim fit? `fdm.bed_fit` checks the bed minus the brim, but only if the
  projection carries `brim_mm` honestly. Does it?
- Is the first layer also a *functional* surface? An elephant-foot squish of 0.1–0.3
  mm on the bottom edge is normal, and it will eat any clearance designed at the
  bottom face.
- If it warps, what fails: cosmetics, a seal, or a fit? The third one means the
  design depends on something nobody has controlled.

## 4. Post-processing

Every finishing step is a manufacturing operation with a cost, a tolerance and a
failure rate. Count them.

- What happens between "printed" and "usable"? Support removal, brim trimming,
  drilling, tapping, heat-set inserts, sanding, vapour smoothing, painting,
  annealing — list them and total the time. Does the part still make sense?
- Are holes printed to size, or printed undersize and drilled? A printed hole is
  undersize and out of round; a drilled one is neither. Which does this design
  assume, and does the model carry the drill allowance?
- Are threads printed, tapped, or heat-set inserts? Printed threads in a coarse
  pitch work once or twice. Inserts need a hole with the right taper and a soldering
  iron with a temperature that does not melt the boss.
- Does any step apply heat — annealing, insert installation, vapour? What does that
  do to dimensions? Annealed PLA shrinks measurably and unevenly.
- Is the surface going to be painted or glued? Layer lines are a poor substrate, and
  PETG in particular resists most adhesives.
- How many operations does a reprint cost? A part that takes six hours to print and
  forty minutes to finish has a real unit cost, and that number should be in the
  ledger before anyone designs the second revision.

## 5. Can this be printed at all, in ANY orientation, without supports?

Ask it plainly, because the answer is often no and nobody checked.

- Rotate the part through the six axis-aligned orientations in your head, and the
  interesting diagonal. Is there one with no unsupported region? If yes, what did
  it cost in strength and finish? If no, say so out loud — the design has committed
  to supports, and everything in lens 2 now applies.
- Are there internal voids that are completely enclosed? Those cannot be supported
  *or* cleaned, and the slicer will happily print them with whatever is trapped
  inside.
- Is there a horizontal hole larger than the bridge limit? Its ceiling is an
  unsupported span in every orientation where the hole is horizontal.
- Does the part have overhangs facing in *opposite* directions? Then no single
  rotation fixes it, and the honest choices are supports, a chamfer, or a split.
- If the answer to all of this is "we will just use supports", has anyone priced the
  removal time and the surface damage against the cost of splitting the part into
  two pieces that each print clean?
- And finally: is this the right process at all? A part that needs supports
  everywhere, holds a tight tolerance, and lives outdoors under load is describing
  a machined or moulded part. Saying so early is cheaper than saying so on the
  fourth revision.
