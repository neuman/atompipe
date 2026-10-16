# Lenses: attacking a board before anyone orders it

Each lens is a question a reviewer asks of THIS board, with the evidence it would
take to close it. A green DRC answers none of them.

## What a design rule check cannot see

- For each IC, open its datasheet's pinout table next to the board's pads. Which
  pins did someone type by number? A pin map typed by hand is a claim nobody
  checked; a symbol from KiCad's library is one KiCad's librarians checked.
- Where is the netlist from? A schematic run through ERC, or a dictionary in a
  script? A script's netlist has no electrical-rule check at all.
- Which nets carry power, and does each have a current in `pcb_net_currents_a`?
  A net that is not named is not judged.

## Pins the part joins inside

- Which parts repeat a pin name (ESD arrays, regulators with tab and pin, MCUs with
  several GND)? For each, do the repeated pins carry one net? If the part is not
  from the library, nothing here can tell.
- A flow-through protector protects only what flows through it. Does the data line
  enter on one side and leave on the other, or did a route bypass the part?

## A width nobody asked for

- Is the width you meant actually on the board? Grep the board file for the net's
  tracks. A width set in a script's constant, a net class that never reached the
  board, a rule the router was not given: each ships the default width silently.
- What does the battery or power loop's resistance add up to: tracks, connector,
  fuse, ribbon? A narrow track can be a third of a charge loop's resistance.

## Warnings the gate never read

- Was the DRC run at every severity? A check at error severity cannot see a silk
  label the fab will clip, a reference over a pad, or text too small to print.
- Is the report the one this run wrote? A gate that reads a report another script
  also writes can pass on yesterday's file.

## The waiver nobody named

- List every DRC exclusion in the `.kicad_pro` and every relaxed rule in the
  `.kicad_dru`. For each: what does it actually cover? A rule written for one
  connector's shield pads that matches every GND pad covers every GND pad.

## A connector that fits the wrong cable

- For each connector: what else fits it? A narrower ribbon in a wider housing, a
  reversed keyed plug forced in, a cable from the previous revision. Where does
  each wrong fit put power? Pin order is a safety decision.
- Is there a fuse between the cell and anything a wrong cable could reach?

## Parts not in the library

- For each custom footprint: who drew it, from which drawing, and was it measured
  against a real part? A pad pattern off by a mirror image is legal copper.
- Is the courtyard real? An optimistic courtyard hides a collision DRC would have
  found.

## Before the money is spent

- Has the fab's own DFM preview been read, rotations included? KiCad's rotation is
  not every fab's.
- Is any part's stock thin enough that the order can fail after the boards ship?
