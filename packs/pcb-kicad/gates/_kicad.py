# SPDX-License-Identifier: Apache-2.0
"""pcb-kicad's reader for KiCad's own files, and the one formula it cites.

Standard library only, so the tier-0 gates run where KiCad is not installed (CI
among them) and every file they decide on is opened by Python, where the trace
sees it. ``kicad-cli`` reads its files in a subprocess the trace cannot see into,
which is why the gates that drive it are opaque and re-run on every check.

**The format.** ``.kicad_pcb``, ``.kicad_sch`` and ``.kicad_sym`` are KiCad's
S-expression files (dev-docs.kicad.org, "File Formats"): a list is ``(head
item...)``, an item is a list, a quoted string or a bare atom. :func:`parse`
keeps quoted strings apart from atoms (:class:`Q`) so :func:`dump` writes back a
file KiCad reads the same way: the known-bad fixtures are the baseline board with
one thing changed, written by this module at fixture time.

**What the board model keeps.** Only what a tier-0 gate decides on: the net table,
each footprint's reference and pads (number, net, the library pin name KiCad
calls ``pinfunction``, the pin type), and each copper track's net, width, layer
and length. Zones are counted, not modelled: a net carried by a pour as well as
by tracks is reported as such, never judged on the pour.

**The formula.** :func:`temp_rise_c` is IPC-2221's trace-heating curve fit,
cited in ``references/ipc-2221.md`` with the range it was fitted over.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------------------- #
# S-expressions
# --------------------------------------------------------------------------- #


class Q(str):
    """A string that was quoted in the file. Written back quoted, always: KiCad
    reads ``"1"`` (a pad number) and ``1`` (a net code) differently."""

    __slots__ = ()


class KicadFormatError(ValueError):
    """The bytes are not a KiCad S-expression file this reader understands."""


_DELIMS = frozenset("() \t\r\n")


def parse(text: str) -> list:
    """The first top-level expression of ``text``, as nested lists of
    :class:`Q` and plain ``str`` atoms. Raises :class:`KicadFormatError` on an
    unbalanced or unterminated file rather than return part of one: a gate that
    judged a truncated board would judge a different board."""
    stack: list[list] = []
    root: list | None = None
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
        elif c == "(":
            node: list = []
            if stack:
                stack[-1].append(node)
            elif root is None:
                root = node
            else:
                raise KicadFormatError(f"a second top-level expression at offset {i}")
            stack.append(node)
            i += 1
        elif c == ")":
            if not stack:
                raise KicadFormatError(f"unbalanced ')' at offset {i}")
            stack.pop()
            i += 1
        elif c == '"':
            j, out = i + 1, []
            while True:
                if j >= n:
                    raise KicadFormatError(f"unterminated string at offset {i}")
                ch = text[j]
                if ch == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    out.append({"n": "\n", "t": "\t", "r": "\r"}.get(nxt, nxt))
                    j += 2
                elif ch == '"':
                    break
                else:
                    out.append(ch)
                    j += 1
            if not stack:
                raise KicadFormatError(f"a string outside any expression at offset {i}")
            stack[-1].append(Q("".join(out)))
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in _DELIMS and text[j] != '"':
                j += 1
            if not stack:
                raise KicadFormatError(f"an atom outside any expression at offset {i}")
            stack[-1].append(text[i:j])
            i = j
    if stack or root is None:
        raise KicadFormatError("unbalanced: the file ends inside an expression"
                               if stack else "no expression in the file")
    return root


def _quote(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def dump(node, indent: int = 0) -> str:
    """``node`` as KiCad S-expression text, one child list per line."""
    if isinstance(node, Q):
        return _quote(node)
    if isinstance(node, str):
        return node
    pad = "\t" * indent
    if not any(isinstance(x, list) for x in node):
        return pad + "(" + " ".join(dump(x) for x in node) + ")"
    head = [dump(x) for x in node if not isinstance(x, list)]
    lines = [pad + "(" + " ".join(head)]
    for x in node:
        if isinstance(x, list):
            lines.append(dump(x, indent + 1))
    lines.append(pad + ")")
    return "\n".join(lines)


def head(node) -> str:
    return node[0] if isinstance(node, list) and node and isinstance(node[0], str) else ""


def children(node, name: str) -> list[list]:
    return [x for x in node if isinstance(x, list) and head(x) == name]


def child(node, name: str) -> list | None:
    for x in node:
        if isinstance(x, list) and head(x) == name:
            return x
    return None


def value(node, name: str, index: int = 1, default=None):
    """``(name v0 v1 ...)``'s item ``index`` (1 = the first after the head)."""
    c = child(node, name)
    if c is None or len(c) <= index:
        return default
    return c[index]


# --------------------------------------------------------------------------- #
# The board
# --------------------------------------------------------------------------- #

#: Layers whose copper is on the outside of the stack: IPC-2221's "external"
#: conductor. Every other ``*.Cu`` layer is internal.
OUTER_LAYERS = frozenset({"F.Cu", "B.Cu"})


@dataclass
class Pad:
    number: str
    net: str                    # "" when the pad is on no net
    pinfunction: str            # the library pin name, "" when the board has none
    pintype: str


@dataclass
class Footprint:
    ref: str
    value: str
    lib_id: str
    pads: list[Pad] = field(default_factory=list)


@dataclass
class Track:
    net: str
    width_mm: float
    layer: str
    length_mm: float
    kind: str                   # "segment" | "arc"


@dataclass
class Board:
    version: str
    nets: dict[int, str]
    footprints: list[Footprint]
    tracks: list[Track]
    vias: int
    zone_nets: list[str]        # one entry per copper zone, its net name


def _net_name(item, nets: dict[int, str]) -> str:
    """``(net 3 "DP")`` (a pad), ``(net 3)`` (a track, by code) or ``(net "DP")``."""
    if item is None or len(item) < 2:
        return ""
    first = item[1]
    if isinstance(first, Q):
        return str(first)
    if len(item) >= 3 and isinstance(item[2], Q):
        return str(item[2])
    try:
        return nets.get(int(first), "")
    except ValueError:
        return ""


def _xy(item) -> tuple[float, float]:
    return float(item[1]), float(item[2])


def _footprint_ref(fp: list) -> tuple[str, str]:
    ref = val = ""
    for prop in children(fp, "property"):          # KiCad 7 and later
        if len(prop) >= 3 and prop[1] == "Reference":
            ref = str(prop[2])
        elif len(prop) >= 3 and prop[1] == "Value":
            val = str(prop[2])
    for text in children(fp, "fp_text"):           # KiCad 6
        if len(text) >= 3 and text[1] == "reference" and not ref:
            ref = str(text[2])
        elif len(text) >= 3 and text[1] == "value" and not val:
            val = str(text[2])
    return ref, val


def board_from_tree(tree: list) -> Board:
    if head(tree) != "kicad_pcb":
        raise KicadFormatError(f"not a KiCad board: the file starts with ({head(tree)} ...)")
    nets: dict[int, str] = {}
    for item in children(tree, "net"):
        if len(item) >= 3:
            try:
                nets[int(item[1])] = str(item[2])
            except ValueError:
                pass
    footprints = []
    for fp in children(tree, "footprint"):
        ref, val = _footprint_ref(fp)
        pads = [Pad(number=str(p[1]) if len(p) > 1 else "",
                    net=_net_name(child(p, "net"), nets),
                    pinfunction=str(value(p, "pinfunction", default="") or ""),
                    pintype=str(value(p, "pintype", default="") or ""))
                for p in children(fp, "pad")]
        footprints.append(Footprint(ref=ref, value=val,
                                    lib_id=str(fp[1]) if len(fp) > 1 else "", pads=pads))
    tracks = []
    for seg in children(tree, "segment"):
        (x0, y0), (x1, y1) = _xy(child(seg, "start")), _xy(child(seg, "end"))
        tracks.append(Track(net=_net_name(child(seg, "net"), nets),
                            width_mm=float(value(seg, "width")),
                            layer=str(value(seg, "layer")),
                            length_mm=math.hypot(x1 - x0, y1 - y0), kind="segment"))
    for arc in children(tree, "arc"):
        (x0, y0), (x1, y1) = _xy(child(arc, "start")), _xy(child(arc, "end"))
        tracks.append(Track(net=_net_name(child(arc, "net"), nets),
                            width_mm=float(value(arc, "width")),
                            layer=str(value(arc, "layer")),
                            length_mm=math.hypot(x1 - x0, y1 - y0), kind="arc"))
    zone_nets = [_net_name(child(z, "net"), nets) or str(value(z, "net_name", default=""))
                 for z in children(tree, "zone")]
    return Board(version=str(value(tree, "version", default="")), nets=nets,
                 footprints=footprints, tracks=tracks,
                 vias=len(children(tree, "via")), zone_nets=zone_nets)


def load_board(path: str) -> Board:
    """The loader ``ctx.load_file`` calls: module-level, so every gate that asks
    for one board shares one parse and each records the file."""
    with open(path, "r", encoding="utf-8") as fh:
        return board_from_tree(parse(fh.read()))


def load_tree(path: str) -> list:
    with open(path, "r", encoding="utf-8") as fh:
        return parse(fh.read())


# --------------------------------------------------------------------------- #
# Library pin names
# --------------------------------------------------------------------------- #

#: Pin names that say "no function": a part's NC or DNC pins may legitimately sit
#: on different nets (a layout that routes through an unused pin), so sharing the
#: name says nothing. ``~`` is KiCad's hidden-name placeholder.
NO_FUNCTION_NAMES = ("NC", "DNC", "N.C.", "N/C", "~", "")


def pin_name_conflicts(board: Board, ignore=NO_FUNCTION_NAMES):
    """Every footprint pin name that two or more different nets share.

    A library symbol gives two pads one name when the part joins them inside:
    a flow-through ESD array's ``I/O1`` is pins 1 and 6, a regulator's ``GND``
    is its tab and a pin. Put two different nets on them and the part shorts the
    nets, which no design rule check can see, because the copper is legal.

    Returns ``(conflicts, named, footprints_named)``: conflicts as
    ``(ref, name, {net: [pad numbers]})``; ``named`` the count of pads that carry
    a name; ``footprints_named`` how many footprints carry at least one.
    """
    skip = {s.upper() for s in ignore}
    conflicts, named, fps_named = [], 0, 0
    for fp in board.footprints:
        groups: dict[str, dict[str, list[str]]] = {}
        any_name = False
        for pad in fp.pads:
            if pad.pinfunction:
                named += 1
                any_name = True
            name = pad.pinfunction.strip()
            if not name or name.upper() in skip or not pad.net:
                continue
            groups.setdefault(name, {}).setdefault(pad.net, []).append(pad.number)
        fps_named += any_name
        for name, by_net in sorted(groups.items()):
            if len(by_net) > 1:
                conflicts.append((fp.ref, name, {k: sorted(v) for k, v in sorted(by_net.items())}))
    return conflicts, named, fps_named


# --------------------------------------------------------------------------- #
# IPC-2221 trace heating
# --------------------------------------------------------------------------- #

#: IPC-2221 (2012), section 6.2, the curve fit to its conductor-sizing chart:
#: I = k * dT^0.44 * A^0.725, I in amperes, dT in degrees C, A the conductor's
#: cross-section in square mils. k = 0.048 for an external conductor, 0.024 for
#: an internal one (half: no free convection inside the stack). Fitted over
#: 0-35 A, widths to 400 mil, rises of 10-100 C, and 0.5-3 oz copper; outside
#: that the chart is extrapolation and the verdict says so. Rejected: IPC-2152
#: (2009), which is more accurate but is a family of charts with board-thickness,
#: plane and mounting corrections and no published closed form a reader can check
#: by hand. The 2221 fit is conservative against it for external layers.
K_EXTERNAL = 0.048
K_INTERNAL = 0.024
EXP_DT = 0.44
EXP_AREA = 0.725

#: One ounce of copper per square foot is 1.378 mil (35 um) thick: the IPC
#: convention every fab's "1 oz" means. Rejected: 1.4 mil, a common rounding.
MIL_PER_OZ = 1.378
MM_PER_MIL = 0.0254

#: The fitted range, for the verdict's warning (references/ipc-2221.md).
FIT_RANGE = {"current_a": (0.0, 35.0), "width_mil": (0.0, 400.0),
             "temp_rise_c": (10.0, 100.0), "copper_oz": (0.5, 3.0)}


def temp_rise_c(current_a: float, width_mm: float, copper_oz: float, outer: bool) -> float:
    """IPC-2221's predicted rise, degrees C, for ``current_a`` through one track."""
    if width_mm <= 0 or copper_oz <= 0:
        return math.inf
    area_mil2 = (width_mm / MM_PER_MIL) * (copper_oz * MIL_PER_OZ)
    k = K_EXTERNAL if outer else K_INTERNAL
    return (abs(current_a) / (k * area_mil2 ** EXP_AREA)) ** (1.0 / EXP_DT)


def width_for_rise_mm(current_a: float, temp_rise: float, copper_oz: float, outer: bool) -> float:
    """The width at which :func:`temp_rise_c` equals ``temp_rise``: its inverse."""
    k = K_EXTERNAL if outer else K_INTERNAL
    area_mil2 = (abs(current_a) / (k * temp_rise ** EXP_DT)) ** (1.0 / EXP_AREA)
    return area_mil2 / (copper_oz * MIL_PER_OZ) * MM_PER_MIL
