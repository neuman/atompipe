# Installing kicad-cli

The tier-0 gates (`pcb.board_readable`, `pcb.pin_names`, `pcb.net_width`) need
nothing. `pcb.drc` and `pcb.unconnected` need `kicad-cli` from KiCad 8 or 9 on PATH;
without it they read Skipped, never passed.

Check: `kicad-cli version` prints `9.0.x`.

| Platform | How |
|---|---|
| Ubuntu / Debian | `sudo add-apt-repository ppa:kicad/kicad-9.0-releases && sudo apt install kicad` |
| Fedora | `sudo dnf install kicad` |
| macOS | the installer from kicad.org; then `kicad-cli` is in `/Applications/KiCad/KiCad.app/Contents/MacOS/`, which must be put on PATH |
| Windows | the installer from kicad.org; `kicad-cli.exe` is in `C:\Program Files\KiCad\9.0\bin\` (Windows is untested with nopekit) |

The full KiCad install is about 1-2 GB with its libraries. The libraries matter for
`pcb.pin_names` only at design time: the names are copied onto the board, and the
gate reads the board.

The baseline's generator, `selftest/assets/make_baseline.py`, also needs KiCad's
`pcbnew` Python module (it ships with KiCad and runs under the system Python on
Linux). The gates never import it.
