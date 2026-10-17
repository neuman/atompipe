# SPDX-License-Identifier: Apache-2.0
"""Write ``esd_guard.kicad_sch``, the schematic the pack's known-good board was
drawn from. Not a gate and not run by any test: ``make_baseline.py`` calls it
first, then links each footprint on the board to its symbol here, so
``pcb.parity`` has a schematic and a board that agree and ``pcb.erc`` has a
schematic KiCad's ERC passes.

**Symbols come from KiCad's installed library**, copied into the file's
``lib_symbols`` the way eeschema caches them (a derived symbol such as
USBLC6-2SC6, which ``extends`` USBLC6-2P6, is flattened into one), so the
schematic carries every pin's name and electrical type without the library.

**Connections are labels and power symbols on pin ends**, no wires: the data
pair on global labels ``DP`` and ``DM`` (a global label's net is its own name,
as the board's nets are), GND and VBUS on KiCad's power symbols. Each power net
carries one PWR_FLAG, the schematic's statement that something outside drives
it (the USB host); without it ERC reads two power inputs with no source.

Every UUID is a ``uuid5`` of a fixed name, so two runs write the same bytes.
"""
from __future__ import annotations

import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(os.path.dirname(HERE))
sys.dont_write_bytecode = True        # never leave a __pycache__ in the pack it describes
sys.path.insert(0, os.path.join(PACK, "gates"))
import _kicad as K                                                 # noqa: E402

SYMBOLS = "/usr/share/kicad/symbols"
OUT = os.path.join(HERE, "esd_guard.kicad_sch")
PROJECT = "esd_guard"

#: KiCad 9.0's schematic format, the version eeschema 9.0.9 writes.
SCH_VERSION = "20250114"

_NS = uuid.UUID("5f0c3a52-9b1e-4f43-8f0e-2a6b1d0c7e11")


def uid(name: str) -> str:
    return str(uuid.uuid5(_NS, name))


ROOT_UUID = uid("sheet:root")

#: (ref, value, lib, symbol, footprint, (x, y) mm on the sheet). The footprints
#: are make_baseline.py's, as "library:name" (what the board's footprint says).
PARTS = [
    ("J1", "USB_IN", "Connector_Generic", "Conn_01x04",
     "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", (63.5, 88.9)),
    ("U1", "USBLC6-2SC6", "Power_Protection", "USBLC6-2SC6",
     "Package_TO_SOT_SMD:SOT-23-6", (127.0, 88.9)),
    ("J2", "USB_OUT", "Connector_Generic", "Conn_01x04",
     "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical", (190.5, 88.9)),
]

#: ref -> {pin: net}: make_baseline.py's NETS, which the board is drawn from.
NETS = {
    "J1": {"1": "DP", "2": "GND", "3": "DM", "4": "VBUS"},
    "J2": {"1": "DP", "2": "GND", "3": "DM", "4": "VBUS"},
    "U1": {"1": "DP", "6": "DP", "3": "DM", "4": "DM", "2": "GND", "5": "VBUS"},
}

POWER_NETS = ("GND", "VBUS")
#: The pin each power net's PWR_FLAG sits on: the input header's, where the
#: host's supply arrives.
FLAGGED = {"GND": ("J1", "2"), "VBUS": ("J1", "4")}


def symbol_uuids() -> dict[str, str]:
    """{ref: the UUID of its symbol}, what a footprint's ``(path "/<uuid>")``
    names on the board."""
    return {ref: uid(f"symbol:{ref}") for ref, *_ in PARTS}


def _library_symbol(lib: str, name: str) -> list:
    """``lib:name`` as eeschema caches it in a schematic: renamed with its
    library, and a derived symbol flattened onto its parent (the parent's
    body and pins, the child's properties, units renamed to the child)."""
    tree = K.load_tree(os.path.join(SYMBOLS, lib + ".kicad_sym"))
    syms = {str(s[1]): s for s in K.children(tree, "symbol")}
    sym = syms[name]
    parent_name = K.value(sym, "extends")
    if parent_name:
        parent = syms[str(parent_name)]
        props = {str(p[1]): p for p in K.children(sym, "property")}
        body = []
        for x in parent[2:]:
            if isinstance(x, list) and K.head(x) == "property" and str(x[1]) in props:
                body.append(props.pop(str(x[1])))
            elif isinstance(x, list) and K.head(x) == "symbol":
                unit = list(x)
                unit[1] = K.Q(name + str(x[1])[len(str(parent_name)):])
                body.append(unit)
            else:
                body.append(x)
        sym = ["symbol", K.Q(name), *body, *props.values()]
        # Properties go before the unit bodies, as eeschema writes them.
        sym = ([x for x in sym if not (isinstance(x, list) and K.head(x) == "symbol")]
               + [x for x in sym if isinstance(x, list) and K.head(x) == "symbol"])
    out = ["symbol", K.Q(f"{lib}:{name}")]
    for x in sym[2:]:
        if isinstance(x, list) and K.head(x) == "in_bom":
            out.append(["exclude_from_sim", "no"])    # KiCad 8's key, before in_bom
        out.append(x)
    return out


def _pins(lib_sym: list) -> dict[str, tuple[float, float]]:
    """{pin number: (x, y)} of each pin's connection point, in the symbol's own
    frame (y up)."""
    found: dict[str, tuple[float, float]] = {}

    def walk(node):
        for x in node:
            if isinstance(x, list):
                if K.head(x) == "pin":
                    at = K.child(x, "at")
                    found[str(K.value(x, "number"))] = (float(at[1]), float(at[2]))
                walk(x)
    walk(lib_sym)
    return found


def _effects(hide: bool = False, justify: str | None = None) -> list:
    node = ["effects", ["font", ["size", "1.27", "1.27"]]]
    if justify:
        node.append(["justify", justify])
    if hide:
        node.append(["hide", "yes"])
    return node


def _prop(key: str, val: str, x: float, y: float, hide: bool = False) -> list:
    return ["property", K.Q(key), K.Q(val), ["at", _n(x), _n(y), "0"], _effects(hide)]


def _n(v: float) -> str:
    return f"{round(v, 4):g}"


def _placed(lib_id: str, ref: str, value: str, footprint: str, x: float, y: float,
            pins: list[str], key: str, angle: int = 0) -> list:
    """One placed symbol, with the instance record that names it in this
    project."""
    return ["symbol",
            ["lib_id", K.Q(lib_id)],
            ["at", _n(x), _n(y), str(angle)],
            ["unit", "1"],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            ["dnp", "no"],
            ["uuid", K.Q(uid(key))],
            _prop("Reference", ref, x, y - 7.62, hide=ref.startswith("#")),
            _prop("Value", value, x, y + 7.62),
            _prop("Footprint", footprint, x, y, hide=True),
            _prop("Datasheet", "", x, y, hide=True),
            *[["pin", K.Q(p), ["uuid", K.Q(uid(f"{key}:pin:{p}"))]] for p in pins],
            ["instances", ["project", K.Q(PROJECT),
                           ["path", K.Q("/" + ROOT_UUID),
                            ["reference", K.Q(ref)], ["unit", "1"]]]]]


def _global_label(net: str, x: float, y: float, left: bool) -> list:
    return ["global_label", K.Q(net),
            ["shape", "bidirectional"],
            ["at", _n(x), _n(y), "180" if left else "0"],
            ["fields_autoplaced", "yes"],
            _effects(justify="right" if left else "left"),
            ["uuid", K.Q(uid(f"label:{net}:{x}:{y}"))],
            ["property", K.Q("Intersheetrefs"), K.Q("${INTERSHEET_REFS}"),
             ["at", _n(x), _n(y), "0"], _effects(hide=True)]]


def build() -> list:
    libs = {}
    for _ref, _val, lib, sym, _fp, _xy in PARTS:
        libs[f"{lib}:{sym}"] = _library_symbol(lib, sym)
    for name in (*POWER_NETS, "PWR_FLAG"):
        libs[f"power:{name}"] = _library_symbol("power", name)

    items: list = []
    sym_uuids = symbol_uuids()
    ends: dict[tuple[str, str], tuple[float, float]] = {}
    for ref, val, lib, sym, fp, (x, y) in PARTS:
        pins = _pins(libs[f"{lib}:{sym}"])
        node = _placed(f"{lib}:{sym}", ref, val, fp, x, y, sorted(pins), f"symbol:{ref}")
        assert K.value(node, "uuid") == sym_uuids[ref]
        items.append(node)
        for num, (px, py) in pins.items():
            ends[(ref, num)] = (x + px, y - py)       # the sheet's y runs down

    n_pwr = n_flg = 0
    for (ref, num), (x, y) in sorted(ends.items()):
        net = NETS[ref].get(num)
        if net is None:
            continue
        if net in POWER_NETS:
            n_pwr += 1
            items.append(_placed(f"power:{net}", f"#PWR0{n_pwr}", net, "", x, y, ["1"],
                                 f"power:{ref}:{num}", angle=0))
            if FLAGGED.get(net) == (ref, num):
                n_flg += 1
                items.append(_placed("power:PWR_FLAG", f"#FLG0{n_flg}", "PWR_FLAG", "",
                                     x, y, ["1"], f"flag:{net}"))
        else:
            centre_x = dict((r, xy[0]) for r, *_rest, xy in PARTS)[ref]
            items.append(_global_label(net, x, y, left=x < centre_x))

    return ["kicad_sch",
            ["version", SCH_VERSION],
            ["generator", K.Q("eeschema")],
            ["generator_version", K.Q("9.0")],
            ["uuid", K.Q(ROOT_UUID)],
            ["paper", K.Q("A4")],
            ["lib_symbols", *libs.values()],
            *items,
            ["sheet_instances", ["path", K.Q("/"), ["page", K.Q("1")]]],
            ["embedded_fonts", "no"]]


def write(path: str = OUT) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(K.dump(build()) + "\n")
    return path


if __name__ == "__main__":
    print(f"wrote {write()}")
