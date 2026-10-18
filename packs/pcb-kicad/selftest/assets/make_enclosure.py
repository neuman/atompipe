# SPDX-License-Identifier: Apache-2.0
"""Write ``enclosure.step``, the box ``pcb.enclosure_fit`` checks the baseline board
against. Not a gate and not run by any test: a record of how the committed file
was made.

    python3 packs/pcb-kicad/selftest/assets/make_enclosure.py

Needs CadQuery (2.8 checked).

**The box** is a closed shell, 2 mm walls, around a cavity sized from the
populated board as ``kicad-cli pcb export step --user-origin 0x0mm`` exports it:
x 0 to 30, y -15 to 0 (KiCad's y negated), the board's bottom face at z 0, the
header pins from z -1.405 to 10.135. The cavity leaves 2 mm beside the board at
each side, 2.595 mm under the pin tails and 2.365 mm over the pin tips: the
nearest part is a header, its pin tips 2.365 mm under the lid. The board is
placed at the enclosure's origin. CadQuery stamps the file with the day it was
written, so two runs differ in that line only.
"""
from __future__ import annotations

import os
import sys

import cadquery as cq

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
OUT = os.path.join(HERE, "enclosure.step")

WALL = 2.0
CAVITY = {"x": (-2.0, 32.0), "y": (-17.0, 2.0), "z": (-4.0, 12.5)}


def box(lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    return (cq.Workplane("XY").box(x1 - x0, y1 - y0, z1 - z0, centered=False)
            .translate((x0, y0, z0)))


def main() -> int:
    lo = tuple(CAVITY[a][0] for a in "xyz")
    hi = tuple(CAVITY[a][1] for a in "xyz")
    outer = box(tuple(v - WALL for v in lo), tuple(v + WALL for v in hi))
    shell = outer.cut(box(lo, hi))
    cq.exporters.export(shell, OUT)
    print(f"wrote {OUT}: volume {shell.val().Volume():.1f} mm^3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
