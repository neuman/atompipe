# SPDX-License-Identifier: Apache-2.0
"""The two steps of ``pcb.autoroute`` that need KiCad's ``pcbnew`` module, run by
the proposer in a Python that has it (KiCad's own on macOS and Windows, the
system's on Linux), never imported by nopekit:

    python3 _pcbnew_steps.py export <board> <dsn> [--rip-up]
    python3 _pcbnew_steps.py import <board> <ses> <out>

``export`` writes the board's Specctra DSN, the format Freerouting reads; with
``--rip-up`` it first deletes every track and via (and saves the board so,
since ``import`` must start from the same copper the router saw). ``import``
loads a Freerouting session onto the board and saves the result as ``out``.
Each prints one JSON line: the track and via counts, so the proposer can say
what moved. Both run on copies the proposer made outside the project:
``pcbnew.LoadBoard`` writes a ``.kicad_prl`` beside a board it opens.
"""
from __future__ import annotations

import json
import sys

import pcbnew


def _counts(board) -> dict:
    tracks = list(board.GetTracks())
    vias = sum(1 for t in tracks if t.GetClass() == "PCB_VIA")
    return {"tracks": len(tracks) - vias, "vias": vias}


def export(board_path: str, dsn: str, rip_up: bool) -> dict:
    board = pcbnew.LoadBoard(board_path)
    before = _counts(board)
    if rip_up:
        for item in list(board.GetTracks()):
            board.Delete(item)
        pcbnew.SaveBoard(board_path, board)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit("pcbnew.ExportSpecctraDSN failed")
    return {"before": before, "routed_from": _counts(board)}


def import_session(board_path: str, ses: str, out: str) -> dict:
    board = pcbnew.LoadBoard(board_path)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit("pcbnew.ImportSpecctraSES failed")
    pcbnew.SaveBoard(out, board)
    return {"after": _counts(board)}


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[0] == "export":
        result = export(argv[1], argv[2], "--rip-up" in argv[3:])
    elif len(argv) == 4 and argv[0] == "import":
        result = import_session(argv[1], argv[2], argv[3])
    else:
        print(__doc__, file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
