# Fab limits: what `pcb.fab_rules` runs

`pcb.fab_rules` holds a board to the minimums its fab publishes, through KiCad's
own DRC. The numbers live in a fab file, `gates/fab/<name>.json`; the gate turns the
row for the board into a `.kicad_dru` and runs `kicad-cli pcb drc --severity-all` on
a staged copy.

## The run

1. Pick the row: the board's copper layer count (its layer table's `*.Cu` entries)
   and `pcb_copper_oz_outer` (1 oz when absent, said as `[pack default]`). A row's
   `layers` is inclusive; its `oz` is `(lo, hi]`. No row is a skip.
2. Write the row, after the file's `common` rules, as the staged board's
   `.kicad_dru`, each rule named `fab_<name>`. The project's own `.kicad_dru` is
   left out of this run: a rule written to relax a constraint for one net would
   relax the fab too.
3. Copy the `.kicad_pro` with every board-setup minimum (`min_*`) set to 0. Net
   classes, exclusions and everything else stay.
4. Count the findings whose type is one the rules constrain. Everything else in
   the run (silk overlaps, unconnected items) is `pcb.drc`'s.

Why zero the project's minimums: a finding's text does not reliably say which
rule raised it. KiCad 9.0.9 reported a 0.085 mm track as `board setup constraints
min width 0.1000 mm`, the fab rule's number under the board's name. With the
board's own floors at 0, a finding of a constrained type can only be the fab's.

| Constraint | Reported as |
|---|---|
| `track_width` | `track_width` |
| `clearance` | `clearance` |
| `edge_clearance` | `copper_edge_clearance` |
| `hole_size` | `drill_out_of_range` |
| `via_diameter` | `via_diameter` |
| `annular_width` | `annular_width` |
| `hole_to_hole` | `hole_to_hole` |
| `text_height`, `text_thickness` | `text_height`, `text_thickness` |
| `silk_clearance` | `silk_overlap` |

Each was read off a report from one deliberate breach (`gates/_kicad.py`,
`CONSTRAINT_TYPES`).

## JLCPCB (`jlcpcb.json`)

From jlcpcb.com/capabilities/pcb-capabilities, read 2026-10-17, each number quoted
in the file beside it. Where the page gives a recommended and an absolute
minimum, the file uses the absolute: this is the fab's floor, not good practice.

| | 1-2 layers, 1 oz | 1-2 layers, 2 oz | multilayer, 1 oz | multilayer, 2 oz |
|---|---|---|---|---|
| track, spacing | 0.10 mm | 0.16 mm | 0.09 mm | 0.15 mm |
| plated-hole annular ring | 0.18 mm | 0.254 mm | 0.15 mm | 0.254 mm |

Every row: via drill 0.15 mm, via pad 0.25 mm, plated hole 0.15 mm, non-plated
hole 0.50 mm, hole to hole 0.45 mm (via to via 0.20 mm), copper to a routed edge
0.20 mm, silkscreen text 1.0 mm high and 0.15 mm stroke, silkscreen 0.15 mm from a
pad. Not checked: board size (KiCad has no constraint), soldermask web and BGA pads
(they depend on the mask colour and finish ordered), the 0.1 mm drills sold as an
option on boards 1 mm thick or less.

## Adding a fab

Copy `jlcpcb.json`, keep its shape, and quote every number from the fab's page
with the day you read it. Point `pcb_fab` at the file (a path from the project
root), or add it to `gates/fab/` in a pull request. The gate's known-bad control
reads the baseline's own fab, so a new file needs no new fixture; it does need a
row for a 2-layer 1 oz board if it is to be the baseline's.
