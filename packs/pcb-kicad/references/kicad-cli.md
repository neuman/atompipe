# Driving kicad-cli: what `pcb.drc` and `pcb.unconnected` run

Both gates run, on a copy of the board staged under the gate's out directory:

    kicad-cli pcb drc <--severity-all|--severity-error|--severity-warning> \
        --exit-code-violations --format json --units mm -o drc.json <board>.kicad_pcb

## Why each flag

- `--exit-code-violations`: without it kicad-cli exits 0 whatever it found, and a
  script that forgets to read the report passes everything. With it: **0** nothing
  found, **5** something found. Any other code is kicad-cli failing to run (a file
  it cannot load, a crash): the gate errors, never passes.
- `--severity-all` (the default for `pcb.drc`): a run at error severity cannot see
  a warning. Silk off the board edge, a reference over a pad, text too small for
  the fab's printer: all warnings, all printed.
- `--format json`: the report the gate reads for the count and the kinds. It must be
  the report this run wrote: the gate deletes any old one first.
- `--units mm`: positions in the report are in the board's own unit.

`pcb.unconnected` runs at `--severity-error`: an unconnected item is always an error,
and a warning elsewhere on the board is not its business.

## The report

    {"violations": [...], "unconnected_items": [...], "schematic_parity": [...],
     "kicad_version": "9.0.9", "source": "...", "date": "...", ...}

Each item: `type` (`clearance`, `shorting_items`, `silk_edge_clearance`,
`courtyards_overlap`, `unconnected_items`, ...), `severity`, `description`, and the
`items` it names, each with a position and a description such as `Track [DM] on
F.Cu`. `schematic_parity` is filled only with `--schematic-parity` (a later gate).

## Waivers

KiCad stores DRC exclusions in the `.kicad_pro` (`board.design_settings.drc_exclusions`),
each naming the violation and the items. `kicad-cli` honours them unless
`--severity-exclusions` is given. That makes a waiver a reviewable line in a
tracked file. The gate copies the `.kicad_pro` and any `.kicad_dru` beside the board
into its stage, so the rules and exclusions it ran under are the project's.

A `.kicad_dru` rule can also relax a constraint. Read its `condition` before you
trust it: a rule written for one connector's shield pads with the condition
`A.NetName == 'GND'` relaxes every ground pad on the board.

## Cost and opacity

About 0.7 s for the baseline board, about 2.3 s for a 4-layer 115-footprint board.
The subprocess reads files the trace cannot see, so the gates are opaque: never
served from the cache, re-run on every check where kicad-cli exists, skipped where
it does not.

## Versions

Written against kicad-cli 9.0.9. KiCad 8 has the same `pcb drc` flags. KiCad 7's
kicad-cli has no `pcb drc` at all, so these gates error there rather than skip:
upgrade.
