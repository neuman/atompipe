# pcb-kicad

Checks a printed circuit board drawn in KiCad 6 to 9: KiCad's own design rule
check and connectivity, the library's pin names against the board's nets, and
trace heating per IPC-2221.

**Before you trust a Checked claim from this pack,** know what it is: a board that
breaks none of KiCad's rules, with every connection made, no part shorting two of
its own nets, and no named track running hotter than you allowed. It is not a
circuit that works. Nothing here has seen the board powered.

## What this pack settles

| Gate | Tier | Basis | Settles |
|---|---|---|---|
| `pcb.board_readable` | 0 | model-only | the board is a KiCad 6-9 file whose every track names a defined net (the guard) |
| `pcb.pin_names` | 0 | sourced | pins the library gives one name (an ESD array's `I/O1`, a part's several `GND`) carry one net |
| `pcb.net_width` | 0 | sourced | the narrowest track of each named net stays inside its temperature-rise limit, IPC-2221 |
| `pcb.drc` | 1 | established | `kicad-cli pcb drc` finds nothing, at every severity by default |
| `pcb.unconnected` | 1 | established | KiCad finds no connection the netlist asks for and the copper does not make |

The tier-0 gates read the board with this pack's own reader (`gates/_kicad.py`,
standard library only), so they run without KiCad, CI included. The tier-1 gates
run `kicad-cli` on a copy of the board under the gate's out directory: the verdict
is KiCad's exit code and its report's count, and if the two disagree the gate
errors. They read inside a subprocess the trace cannot see into, so they are
**opaque**: they re-run on every check where `kicad-cli` exists (about a second
each on a small board) and skip where it does not.

`pcb.pin_names` and `pcb.net_width` need `pcb.board_readable`: on a board this
reader cannot vouch for they are not run, and read Skipped, `prerequisite failed`.

## What this pack CANNOT settle

Read this before you write a claim. Every one of these has passed a "0 violations,
0 unconnected" board in practice.

- **Whether the circuit is right.** DRC checks copper against rules. A pin map
  read wrongly from a datasheet, a missing pull-up, a regulator that cannot supply
  the load, a reversed diode: all legal copper. `pcb.pin_names` catches one class
  (two nets on pins the part joins inside), and only for parts whose library symbol
  names those pins alike.
- **Parts that are not in a library.** A footprint drawn without a schematic carries
  no pin names, and `pcb.pin_names` skips. Its pin map is a claim for a person (an
  expert judgment) or for a pin table recorded from the datasheet.
- **Current through vias, pads and pours.** `pcb.net_width` judges tracks only. A
  via carries its own current limit; a pour is wider than any track and is not
  judged at all, so a net carried mostly by a pour reads pessimistically.
- **What happens when someone plugs in the wrong thing.** A 16-way ribbon fits a
  20-way connector with 4 mm of slop and can put battery on ground. That is a
  mechanical fact with an electrical result, and no check here sees it.
- **RF, signal integrity, EMC.** Antenna detuning, impedance, crosstalk, return
  paths: not modelled.
- **Fit in the enclosure.** A board can be clean and the part on it taller than its
  cavity. That needs the STEP model and the enclosure (a later gate of this pack).
- **Anything about a built board.** Assembly, solder, first power-up: physical
  claims, Pending build until a person records a result.

## Claim tags

Gates list everything they bear on; a claim carries the narrowest tag that says
what it asserts.

| Tag | Bound by |
|---|---|
| `pcb` | every gate here (too broad for a claim: use a narrower one) |
| `design-rules`, `clearance`, `manufacturability` | `pcb.drc` |
| `connectivity` | `pcb.unconnected` |
| `netlist` | `pcb.unconnected`, `pcb.pin_names` |
| `pin-map`, `short-circuit` | `pcb.pin_names` |
| `trace-width`, `current-capacity`, `power-integrity` | `pcb.net_width` |
| `pcb-model-validity` | `pcb.board_readable` |

A claim "every connection is made" tagged `connectivity` stays Checked through a
silkscreen warning; tagged `pcb`, it would read Failing on it.

## Units and frames

Millimetres for every length (KiCad's file unit), amperes, degrees C of rise above
ambient, ounces of copper per square foot (1 oz = 35 um = 1.378 mil). KiCad's
board frame is Y-down. `pcb.net_width` reports the rise in C against
`pcb_temp_rise_limit_c`.

## Pointing a project at its board

```json
"pcb_board": "hardware/main.kicad_pcb",
"pcb_net_currents_a": {"VBUS": 0.5, "VBAT": 1.2, "GND": 1.2},
"pcb_temp_rise_limit_c": 10.0,
"pcb_copper_oz_outer": 1.0
```

The board's `.kicad_pro` (rules, net classes and DRC exclusions) and `.kicad_dru`
(custom rules), beside it with the same name, go to `kicad-cli` with it.
**To waive a DRC finding, exclude it in KiCad** and commit the `.kicad_pro`: the
exclusion is then a named, reviewable record. Never narrow `pcb_drc_severity` to
make a warning go away; that hides every warning, including the next one.

A board updated from its schematic ("Update PCB from Schematic") carries each pad's
library pin name. A board generated by a script must copy those names itself (the
baseline's `make_baseline.py` shows how), or `pcb.pin_names` has nothing to read.

## The physics, in one paragraph

A track's resistance heats it: R = rho L / (w t), and copper's rho is 1.7e-8 ohm m at
20 C, so 10 mm of 0.25 mm track in 1 oz copper is about 19 mOhm. IPC-2221 fits
the measured temperature rise of a track carrying steady current: I = k dT^0.44
A^0.725, A in square mils, k 0.048 on an outer layer and 0.024 inside the stack,
where nothing convects. The rise goes as I^2.27 and A^-1.65: halve the width and
it rises about 3.1 times, double the current and about 4.8 times. A 0.25 mm outer
track in 1 oz carries 0.5 A at 2.8 C and 1 A at about 13.5 C; the same track inside
the stack, same copper, runs about 4.8 times hotter at the same current. If a rise comes
back under 1 C or over 100 C, look at the units first.

## Where to look next

- `references/ipc-2221.md`: the formula, its fitted range, and why not IPC-2152.
- `references/kicad-cli.md`: the DRC flags this pack uses, exit codes, the report.
- `references/what-slipped-through.md`: the defects the source pipeline's checks
  passed, and which gate here answers each.
- `references/installing.md`: getting `kicad-cli` (KiCad 9).
- `lenses.md`: how to attack a board before anyone orders it.
