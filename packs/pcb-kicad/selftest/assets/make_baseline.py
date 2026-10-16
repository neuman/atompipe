# SPDX-License-Identifier: Apache-2.0
"""Regenerate ``esd_guard.kicad_pcb``, the pack's known-good board. Not a gate and
not run by any test: a record of how the committed board was made, so a reader can
make it again and diff.

    python3 packs/pcb-kicad/selftest/assets/make_baseline.py

Needs KiCad 9's ``pcbnew`` module and its stock libraries (/usr/share/kicad).

**The circuit.** A USB data-line protector between two 4-pin headers: J1 in, U1
(USBLC6-2SC6, the KiCad library's own symbol and SOT-23-6 footprint), J2 out. The
part is chosen for the defect it lets a control plant: its library symbol names
pins 1 and 6 ``I/O1`` and pins 3 and 4 ``I/O2``, because inside the part each pair
is one conductor. Wire D+ to pin 1 and D- to pin 6 and the part shorts the data
pair, on copper that passes every design rule.

**Pin names come from the library, not from this file.** Each pad's
``pinfunction`` is read out of KiCad's installed ``.kicad_sym`` for the symbol
(what "Update PCB from Schematic" copies onto a board), through the pack's own
reader. A board drawn without a schematic carries none, and ``pcb.pin_names``
then skips: it has nothing to compare against.

**The layout** is hand-placed so a reader can check it: both headers on the 2.54 mm
grid at x 4 and 26, U1 centred between header pins 2 and 3, the data pair and the
left ground on F.Cu, VBUS and the right ground on B.Cu through the headers' plated
holes, and one via beside U1 pin 5. Tracks 0.25 mm on KiCad's default rules
(0.2 mm clearance). It must pass ``kicad-cli pcb drc --severity-all`` with no
violation and nothing unconnected; the script runs that check and exits 1 if not.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(os.path.dirname(HERE))
sys.dont_write_bytecode = True        # never leave a __pycache__ in the pack it describes
sys.path.insert(0, os.path.join(PACK, "gates"))
import _kicad as K                                                 # noqa: E402

FOOTPRINTS = "/usr/share/kicad/footprints"
SYMBOLS = "/usr/share/kicad/symbols"
OUT = os.path.join(HERE, "esd_guard.kicad_pcb")

TRACK_MM = 0.25
VIA_MM, VIA_DRILL_MM = 0.6, 0.3

#: (ref, value, symbol lib, symbol, footprint lib, footprint, (x, y) mm)
PARTS = [
    ("J1", "USB_IN", "Connector_Generic", "Conn_01x04",
     "Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical", (4.0, 4.0)),
    ("U1", "USBLC6-2SC6", "Power_Protection", "USBLC6-2SC6",
     "Package_TO_SOT_SMD", "SOT-23-6", (15.0, 7.81)),
    ("J2", "USB_OUT", "Connector_Generic", "Conn_01x04",
     "Connector_PinHeader_2.54mm", "PinHeader_1x04_P2.54mm_Vertical", (26.0, 4.0)),
]

#: ref -> {pad: net}. Both headers: 1 D+, 2 GND, 3 D-, 4 VBUS. U1 flows through:
#: D+ in on pin 1 and out on pin 6 (both I/O1), D- on 3 and 4 (both I/O2).
NETS = {
    "J1": {"1": "DP", "2": "GND", "3": "DM", "4": "VBUS"},
    "J2": {"1": "DP", "2": "GND", "3": "DM", "4": "VBUS"},
    "U1": {"1": "DP", "6": "DP", "3": "DM", "4": "DM", "2": "GND", "5": "VBUS"},
}

VIA = (17.6, 7.81)

#: (net, layer, [(ref, pad) or (x, y), ...]) polylines between pad centres.
ROUTES = [
    ("DP", "F.Cu", [("J1", "1"), ("U1", "1")]),
    ("DP", "F.Cu", [("U1", "6"), ("J2", "1")]),
    # The part joins pins 1 and 6 (and 3 and 4) inside, and KiCad 9.0's footprint
    # has no way to say so from Python (jumper pad groups are not exposed), so DRC
    # reads each pair as two islands of one net. A tie under the body, between the
    # pad rows, is what a real layout draws; it clears pins 2 and 5 by 0.5 mm.
    ("DP", "F.Cu", [("U1", "1"), ("U1", "6")]),
    ("DM", "F.Cu", [("U1", "3"), ("U1", "4")]),
    ("GND", "F.Cu", [("J1", "2"), ("U1", "2")]),
    ("DM", "F.Cu", [("J1", "3"), ("U1", "3")]),
    ("DM", "F.Cu", [("U1", "4"), ("J2", "3")]),
    ("VBUS", "F.Cu", [("U1", "5"), VIA]),
    ("VBUS", "B.Cu", [VIA, (VIA[0], 11.62), ("J2", "4")]),
    ("VBUS", "B.Cu", [(VIA[0], 11.62), ("J1", "4")]),
    ("GND", "B.Cu", [("J1", "2"), ("J2", "2")]),
]

OUTLINE = [(0.0, 0.0), (30.0, 0.0), (30.0, 15.0), (0.0, 15.0)]


def library_pin_names(lib: str, symbol: str) -> dict[str, tuple[str, str]]:
    """{pin number: (name, electrical type)} from KiCad's installed symbol,
    following one ``extends`` (USBLC6-2SC6 extends USBLC6-2P6)."""
    tree = K.load_tree(os.path.join(SYMBOLS, lib + ".kicad_sym"))
    syms = {str(s[1]): s for s in K.children(tree, "symbol")}
    sym = syms[symbol]
    parent = K.value(sym, "extends")
    if parent:
        sym = syms[str(parent)]
    pins: dict[str, tuple[str, str]] = {}

    def walk(node):
        for x in node:
            if isinstance(x, list):
                if K.head(x) == "pin":
                    num = str(K.value(x, "number"))
                    pins.setdefault(num, (str(K.value(x, "name")), str(x[1])))
                walk(x)
    walk(sym)
    return pins


def mm(v: float) -> int:
    return pcbnew.FromMM(v)


def main() -> int:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(2)
    nets = {}
    for name in sorted({n for m in NETS.values() for n in m.values()}):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    placed = {}
    for ref, val, slib, sym, flib, fpname, (x, y) in PARTS:
        fp = pcbnew.FootprintLoad(os.path.join(FOOTPRINTS, flib + ".pretty"), fpname)
        fp.SetReference(ref)
        fp.SetValue(val)
        fp.SetPosition(pcbnew.VECTOR2I(mm(x), mm(y)))
        names = library_pin_names(slib, sym)
        for pad in fp.Pads():
            num = pad.GetNumber()
            if num in NETS[ref]:
                pad.SetNet(nets[NETS[ref][num]])
            name, ptype = names[num]
            pad.SetPinFunction(name)
            pad.SetPinType(ptype)
        board.Add(fp)
        placed[ref] = fp

    def point(p):
        if isinstance(p[0], str):
            pad = [q for q in placed[p[0]].Pads() if q.GetNumber() == p[1]][0]
            return pad.GetPosition()
        return pcbnew.VECTOR2I(mm(p[0]), mm(p[1]))

    layer = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}
    for net, lay, pts in ROUTES:
        for a, b in zip(pts, pts[1:]):
            t = pcbnew.PCB_TRACK(board)
            t.SetStart(point(a))
            t.SetEnd(point(b))
            t.SetWidth(mm(TRACK_MM))
            t.SetLayer(layer[lay])
            t.SetNet(nets[net])
            board.Add(t)
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(mm(VIA[0]), mm(VIA[1])))
    via.SetWidth(mm(VIA_MM))
    via.SetDrill(mm(VIA_DRILL_MM))
    via.SetNet(nets["VBUS"])
    board.Add(via)

    for a, b in zip(OUTLINE, OUTLINE[1:] + OUTLINE[:1]):
        e = pcbnew.PCB_SHAPE(board)
        e.SetShape(pcbnew.SHAPE_T_SEGMENT)
        e.SetStart(pcbnew.VECTOR2I(mm(a[0]), mm(a[1])))
        e.SetEnd(pcbnew.VECTOR2I(mm(b[0]), mm(b[1])))
        e.SetLayer(pcbnew.Edge_Cuts)
        e.SetWidth(mm(0.1))
        board.Add(e)

    pcbnew.SaveBoard(OUT, board)
    pro = OUT[:-len(".kicad_pcb")] + ".kicad_pro"
    if not os.path.isfile(pro):
        with open(pro, "w", encoding="utf-8") as fh:
            json.dump({"meta": {"filename": os.path.basename(pro), "version": 1}}, fh, indent=2)

    report = os.path.abspath(os.path.join(os.environ.get("TMPDIR", "/tmp"), "esd_guard_drc.json"))
    proc = subprocess.run(["kicad-cli", "pcb", "drc", "--severity-all", "--exit-code-violations",
                           "--format", "json", "-o", report, OUT],
                          capture_output=True, text=True)
    with open(report, encoding="utf-8") as fh:
        doc = json.load(fh)
    print(f"wrote {OUT}")
    print(f"drc exit {proc.returncode}: {len(doc['violations'])} violation(s), "
          f"{len(doc['unconnected_items'])} unconnected")
    for v in doc["violations"] + doc["unconnected_items"]:
        print(f"  {v['severity']:8} {v['type']}: {v['description']} — "
              + "; ".join(i["description"] for i in v["items"]))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
