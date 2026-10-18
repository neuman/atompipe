# pcb-kicad

Checks a printed circuit board drawn in KiCad 6 to 9, and its schematic: KiCad's
own design rule check, connectivity, electrical rules check and schematic parity,
the library's pin names against the board's nets, trace heating per IPC-2221, a
fab's published limits, a measurement ngspice makes on the project's circuit
deck, and the populated board's fit in its enclosure.

**Before you trust a Checked claim from this pack,** know what it is: a board that
breaks none of KiCad's rules, with every connection made, no part shorting two of
its own nets, no named track running hotter than you allowed, drawn from a
schematic that breaks none of KiCad's electrical rules and that it matches, inside
the fab's limits, with a simulated value inside its band and every part clear of
the enclosure. It is not a
circuit that works. Nothing here has seen the board powered.

## What this pack settles

| Gate | Tier | Basis | Settles |
|---|---|---|---|
| `pcb.board_readable` | 0 | model-only | the board is a KiCad 6-9 file whose every track names a defined net (the guard) |
| `pcb.pin_names` | 0 | sourced | pins the library gives one name (an ESD array's `I/O1`, a part's several `GND`) carry one net |
| `pcb.net_width` | 0 | sourced | every track of each named net stays inside its temperature-rise limit, IPC-2221; the detail names the hottest stretch |
| `pcb.drc` | 1 | established | `kicad-cli pcb drc` finds nothing, at every severity by default |
| `pcb.unconnected` | 1 | established | KiCad finds no connection the netlist asks for and the copper does not make |
| `pcb.erc` | 1 | established | `kicad-cli sch erc` finds nothing in the schematic, at every severity by default |
| `pcb.parity` | 1 | established | KiCad finds no difference between the board and its schematic: parts, values, footprints, pad nets |
| `pcb.fab_rules` | 1 | sourced | KiCad's DRC with the fab's published minimums as the only custom rules finds nothing past them |
| `pcb.spice` | 1 | established | a `.meas` result of `ngspice -b` on the project's deck stays inside `pcb_spice_min` / `pcb_spice_max` |
| `pcb.enclosure_fit` | 1 | established | the board, every part's 3D model in place, shares no volume with the enclosure, and each part keeps its clearance (OpenCascade) |

The tier-0 gates read the board with this pack's own reader (`gates/_kicad.py`,
standard library only), so they run without KiCad, CI included. The tier-1 gates
run `kicad-cli` on a copy of the board or schematic (every sheet, the project file
and the library tables with it) under the gate's out directory: the verdict
is KiCad's exit code and its report's count, and if the two disagree the gate
errors. `pcb.spice` runs `ngspice -b` the same way, and `pcb.enclosure_fit` runs
`kicad-cli pcb export step` and then OpenCascade (through CadQuery) in a child
process. They read inside subprocesses the trace cannot see into, so they are
**opaque**: they re-run on every check where their tools exist (about a second
each on a small board; the fit about 4 s) and skip where they do not.

`pcb.pin_names` and `pcb.net_width` need `pcb.board_readable`: on a board this
reader cannot vouch for they are not run, and read Skipped, `prerequisite failed`.

## The proposer: `pcb.autoroute`

    nopekit propose pcb.autoroute -- --board hardware/main.kicad_pcb [--passes 20] [--rip-up]

Routes the board with Freerouting, headless and on one thread, on a copy outside
the project, and records two inputs: `<board>.routed.kicad_pcb` and
`<board>.autoroute.json` (the Freerouting version, passes, track counts before and
after, and what it reported unrouted). It settles nothing. Adopting the routed
board, by copying it over the project's board, is a decision; then `pcb.drc`,
`pcb.unconnected` and `pcb.parity` judge it like any other board. Nothing that draws
copper judges it: the source pipeline's own "gap closer" drew shorts.

It needs a Python that imports KiCad's `pcbnew` (`--kicad-python` or
`KICAD_PYTHON`; Linux's system Python, or KiCad's own on macOS and Windows), Java
21+ (`--java`, `JAVA`, `JAVA_HOME` or PATH) and the Freerouting jar (`--jar` or
`FREEROUTING_JAR`; checked with 2.2.4). Without one it exits 2, naming what to
set, and records nothing. Freerouting's analytics are switched off; it still asks
GitHub for a newer version when it starts.

Existing tracks go to the router as fixed wiring, so a hand-routed USB pair rides
through. `--rip-up` routes from nothing. A run that leaves nets open is still a
proposal: `pcb.unconnected` says which, and `--passes` is the knob (a retry of the
same input draws the same copper).

## What this pack CANNOT settle

Read this before you write a claim. Every one of these has passed a "0 violations,
0 unconnected" board in practice.

- **Whether the circuit is right.** DRC checks copper against rules. A pin map
  read wrongly from a datasheet, a missing pull-up, a regulator that cannot supply
  the load, a reversed diode: all legal copper, and all a clean ERC too. ERC
  checks how pins are tied (an open pin, a label nothing else shares, a power
  input nothing drives, two outputs together), never what the circuit does.
  `pcb.pin_names` catches one class (two nets on pins the part joins inside), and
  only for parts whose library symbol names those pins alike.
- **A board with no schematic.** A netlist built in a script has no ERC and no
  parity to check: `pcb.erc` and `pcb.parity` skip, and the script's dictionary is
  the only record of what connects to what. Tag a claim that every connection is
  made `copper-connectivity`, not `connectivity`, or `pcb.parity`'s skip holds it.
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
- **Fit beyond the solids.** `pcb.enclosure_fit` checks the parts' 3D models
  against the enclosure's solid at one placement. A model drawn wrong, a cable's
  bend radius, a plug's mating clearance, a tolerance stack, assembly order, a
  lid that flexes: none of them is in two solids. A part with no model skips
  the gate rather than pass it.
- **Whether the SPICE deck is the circuit.** ngspice solves the deck it is given.
  The deck is someone's model, typed by hand; `pcb.spice` refuses a run that
  dropped a line, and nothing more. Read the deck against the schematic.
- **Everything the fab checks.** `pcb.fab_rules` holds the minimums the fab
  publishes and KiCad can test: widths, spacing, drills, via pads, annular rings,
  edge clearance, silkscreen text, and silkscreen to pad (silk on silk is
  `pcb.drc`'s). Board size, mask webs, panelisation and the fab's
  own DFM review are not in it, and a fab's page changes: the file says the day
  it was read.
- **Anything about a built board.** Assembly, solder, first power-up: physical
  claims, Pending build until a person records a result.

## Claim tags

Gates list everything they bear on; a claim carries the narrowest tag that says
what it asserts.

| Tag | Bound by |
|---|---|
| `pcb` | every gate here (too broad for a claim: use a narrower one) |
| `design-rules`, `clearance` | `pcb.drc` |
| `manufacturability` | `pcb.drc`, `pcb.fab_rules` |
| `fab-limits` | `pcb.fab_rules` |
| `circuit-simulation` | `pcb.spice` |
| `enclosure-fit`, `packaging`, `interference` | `pcb.enclosure_fit` |
| `connectivity` | `pcb.unconnected`, `pcb.parity` |
| `copper-connectivity` | `pcb.unconnected` |
| `netlist` | `pcb.unconnected`, `pcb.pin_names`, `pcb.erc`, `pcb.parity` |
| `schematic`, `electrical-rules` | `pcb.erc` |
| `schematic-parity` | `pcb.parity` |
| `pin-map`, `short-circuit` | `pcb.pin_names` |
| `trace-width`, `current-capacity` | `pcb.net_width` |
| `power-integrity` | `pcb.net_width`, `pcb.spice` |
| `pcb-model-validity` | `pcb.board_readable` |

A claim "every connection is made" tagged `connectivity` stays Checked through a
silkscreen warning; tagged `pcb`, it would read Failing on it. On a board with no
schematic, tag it `copper-connectivity`: `connectivity` brings in `pcb.parity`,
which skips there, so the claim would read Skipped beside a pass.

## Units and frames

Millimetres for every length (KiCad's file unit), amperes, degrees C of rise above
ambient, ounces of copper per square foot (1 oz = 35 um = 1.378 mil). KiCad's
board frame is Y-down. `pcb.net_width` reports the rise in C against
`pcb_temp_rise_limit_c`. `pcb.spice` reports in `pcb_spice_units`, which the
project states: ngspice computes in SI (V, A, s) and the gate cannot tell which
quantity a `.meas` is.

**`pcb.enclosure_fit` judges the populated board in the enclosure's frame.** The
board is first as `kicad-cli pcb export step --user-origin 0x0mm` writes it: the
board file's (0, 0) at the origin, x right, **y up (KiCad's y negated)**, z up from
the board's bottom face. `pcb_board_placement` turns it `rot_z_deg` about z, then
moves it by `x`, `y`, `z` mm. The enclosure's STEP is its material (walls and lid),
in mm, in its own frame. The verdict is the nearest part's distance, in mm,
against `pcb_enclosure_clearance_mm`; any shared volume fails it, and the board
body may touch (standoffs) but not cut in.

## Pointing a project at its board

```json
"pcb_board": "hardware/main.kicad_pcb",
"pcb_net_currents_a": {"VBUS": 0.5, "VBAT": 1.2, "GND": 1.2},
"pcb_temp_rise_limit_c": 10.0,
"pcb_copper_oz_outer": 1.0,
"pcb_fab": "jlcpcb",
"pcb_spice_deck": "hardware/sim/vbus.cir",
"pcb_spice_measure": "vbus_min", "pcb_spice_min": 4.75, "pcb_spice_units": "V",
"pcb_enclosure_step": "cad/out/enclosure.step",
"pcb_board_placement": {"x": 2.0, "y": 17.0, "z": 4.0, "rot_z_deg": 0},
"pcb_enclosure_clearance_mm": 1.0
```

Each family skips without its keys: no fab named, no deck, no enclosure, no
placement or no clearance is a skip that says which key, never a default.

The board's `.kicad_pro` (rules, net classes, ERC and DRC exclusions),
`.kicad_dru` (custom rules) and `.kicad_sch` (the root schematic, with every sheet
under it), beside it with the same name, go to `kicad-cli` with it, and so do the
project's `sym-lib-table` and `fp-lib-table`. Keep those two in the project: on a
machine whose KiCad was never configured, ERC otherwise warns about every symbol
("library not in the current configuration"). `pcb_schematic` names another root
schematic for `pcb.erc`; `pcb.parity` always compares with the board's own, as
KiCad does.
**To waive a DRC or ERC finding, exclude it in KiCad** and commit the `.kicad_pro`:
the exclusion is then a named, reviewable record. Never narrow `pcb_drc_severity`
or `pcb_erc_severity` to make a warning go away; that hides every warning,
including the next one.

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
- `references/kicad-cli.md`: the DRC and ERC flags this pack uses, exit codes, the
  reports, parity.
- `references/fab-limits.md`: how `pcb.fab_rules` turns a fab's page into rules,
  JLCPCB's numbers, and how to add a fab.
- `references/enclosure-fit.md`: the frames, what kicad-cli leaves out, and what
  the fit measures.
- `references/spice.md`: what `pcb.spice` runs, refuses and reads.
- `references/what-slipped-through.md`: the defects the source pipeline's checks
  passed, and which gate here answers each.
- `references/installing.md`: getting `kicad-cli` (KiCad 9), ngspice, CadQuery,
  and the proposer's Java and Freerouting.
- `lenses.md`: how to attack a board before anyone orders it.
