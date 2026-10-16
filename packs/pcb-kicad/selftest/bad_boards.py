# SPDX-License-Identifier: Apache-2.0
"""Known-bad fixtures for pcb-kicad. One physical change each, to the baseline board.

`nopekit gate selftest` requires every gate to FAIL here. A gate that passes its
own fixture is broken, and a green verdict from it means nothing.

**Sealed.** Every fixture starts from this pack's own ``selftest/baseline.json``
and ``selftest/assets/esd_guard.kicad_pcb``, never from the host's projection or
the host's board, and hands the gate an empty ledger. A control whose severity
depended on the host's board would fire in some projects and not in others.

**Generated, from the limit the gate judges by.** Each bad board is the baseline
board parsed by the pack's own reader, one thing changed, and written back under
the CALLER's ``out_dir`` (``<out_dir>/pcb-kicad/known-bad/<fixture>/``), with the
baseline's project file beside it so KiCad applies the same rules. Never into this
directory: a fixture that writes into the pack it is proving makes the proof
depend on whether the pack is writable. ``narrow_power`` derives its width from
the baseline's own rise limit and current with the gate's own formula, so lifting
the limit cannot quietly turn the control into a pass.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil

from nopekit.modelio import load_path
from nopekit.models import Ledger

_PACK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASELINE_PATH = os.path.join(_PACK_DIR, "selftest", "baseline.json")
_ASSETS = os.path.join(_PACK_DIR, "selftest", "assets")
K = load_path(os.path.join(_PACK_DIR, "gates", "_kicad.py"))

#: How far past its limit ``narrow_power`` lands: 15%, the margin the mutation
#: pass uses, so the control does not sit on the rounding of the verdict.
MARGIN = 1.15

_PATH_KEYS = ("pcb_board",)


def _baseline() -> dict:
    """The baseline projection, documentation keys stripped and every path made
    absolute against this pack."""
    with open(_BASELINE_PATH, encoding="utf-8") as fh:
        params = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
    for key in _PATH_KEYS:
        if key in params:
            params[key] = os.path.join(_PACK_DIR, str(params[key]))
    return params


def _variant(ctx, name: str, edit) -> object:
    """A context whose board is the baseline board after ``edit(tree)``."""
    params = _baseline()
    src = params["pcb_board"]
    tree = K.load_tree(src)
    edit(tree, params)
    stem = os.path.basename(src)[:-len(".kicad_pcb")]
    board = ctx.out_path("pcb-kicad", "known-bad", name, stem + ".kicad_pcb")
    stage = os.path.dirname(board)
    with open(board, "w", encoding="utf-8") as fh:
        fh.write(K.dump(tree) + "\n")
    shutil.copyfile(src[:-len(".kicad_pcb")] + ".kicad_pro",
                    os.path.join(stage, stem + ".kicad_pro"))
    params["pcb_board"] = board
    return dataclasses.replace(ctx, params=params, ledger=Ledger())


def _net_code(tree, name: str) -> int:
    for n in K.children(tree, "net"):
        if len(n) >= 3 and str(n[2]) == name:
            return int(n[1])
    raise KeyError(name)


def _footprint(tree, ref: str):
    for fp in K.children(tree, "footprint"):
        for prop in K.children(fp, "property"):
            if len(prop) >= 3 and prop[1] == "Reference" and str(prop[2]) == ref:
                return fp
    raise KeyError(ref)


def _segments(tree, net: str):
    code = str(_net_code(tree, net))
    return [s for s in K.children(tree, "segment") if K.value(s, "net") == code]


def _segment_from(tree, net: str, x: float, y: float):
    """The ``net`` segment that starts or ends at (x, y) mm: picked by where it
    is, never by its place in the file, which KiCad may reorder on any save."""
    for seg in _segments(tree, net):
        for end in ("start", "end"):
            px, py = (float(v) for v in K.child(seg, end)[1:3])
            if abs(px - x) < 1e-6 and abs(py - y) < 1e-6:
                return seg
    raise KeyError(f"no {net} segment at ({x}, {y})")


#: Header J1's pin 1 (D+) and pin 3 (D-), mm: make_baseline.py's PARTS and NETS.
J1_DP, J1_DM = (4.0, 4.0), (4.0, 9.08)


def split_pin_pair(ctx):
    """pcb.pin_names — U1 pin 6 moved from D+ to D-.

    The USBLC6-2SC6 joins pins 1 and 6 inside (both ``I/O1``). With D+ on pin 1
    and D- on pin 6 the part shorts the data pair. The tracks are untouched, so
    the copper stays legal: only the pad's net changes, as it would on a board
    whose netlist assigned pins by number from a misread datasheet.
    """
    def edit(tree, _params):
        dm = _net_code(tree, "DM")
        for pad in K.children(_footprint(tree, "U1"), "pad"):
            if str(pad[1]) == "6":
                net = K.child(pad, "net")
                net[1:] = [str(dm), K.Q("DM")]
    return _variant(ctx, "split_pin_pair", edit)


def narrow_power(ctx):
    """pcb.net_width — every VBUS track narrowed to the width at which IPC-2221
    puts the baseline's VBUS current ``MARGIN`` past the baseline's rise limit."""
    def edit(tree, params):
        amps = float(params["pcb_net_currents_a"]["VBUS"])
        target = float(params["pcb_temp_rise_limit_c"]) * MARGIN
        oz = float(params.get("pcb_copper_oz_outer", 1.0))
        width = K.width_for_rise_mm(amps, target, oz, True)
        width = round(width, 4)
        if K.temp_rise_c(amps, width, oz, True) <= target / MARGIN:
            raise AssertionError("narrow_power: the derived width does not cross the limit")
        for seg in _segments(tree, "VBUS"):
            K.child(seg, "width")[1] = f"{width:g}"
    return _variant(ctx, "narrow_power", edit)


def fat_track(ctx):
    """pcb.drc — the D+ track from J1 to U1 pin 1 widened to 1.0 mm. U1's pins sit
    0.95 mm apart, so the wide copper runs into the ground pad below pin 1."""
    def edit(tree, _params):
        seg = _segment_from(tree, "DP", *J1_DP)
        K.child(seg, "width")[1] = "1"
    return _variant(ctx, "fat_track", edit)


def open_net(ctx):
    """pcb.unconnected — the D- track from J1 to U1 pin 3 deleted."""
    def edit(tree, _params):
        tree.remove(_segment_from(tree, "DM", *J1_DM))
    return _variant(ctx, "open_net", edit)


def orphaned_net(ctx):
    """pcb.board_readable — VBUS dropped from the board's net table, so its tracks,
    via and pads name a net code the board no longer defines."""
    def edit(tree, _params):
        code = str(_net_code(tree, "VBUS"))
        for n in K.children(tree, "net"):
            if n[1] == code:
                tree.remove(n)
                break
    return _variant(ctx, "orphaned_net", edit)
