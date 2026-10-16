# SPDX-License-Identifier: Apache-2.0
"""pcb-kicad — gates for a printed circuit board drawn in KiCad.

    pcb.board_readable   tier 0  the board is a KiCad file this reader knows (the guard)
    pcb.pin_names        tier 0  pins the library gives one name carry one net
    pcb.net_width        tier 0  each current-carrying net's narrowest track, IPC-2221
    pcb.drc              tier 1  KiCad's design rule check, every severity
    pcb.unconnected      tier 1  KiCad's count of connections the copper never makes

**Where each verdict comes from.** The two tier-1 gates are KiCad's own answer:
``kicad-cli pcb drc``'s exit code and its report's count (basis established), on a
copy of the board staged under the gate's out directory. They read inside a
subprocess the trace cannot see into, so they are opaque and re-run on every check
where ``kicad-cli`` exists, as openmodelica's ``omc`` gates do. The tier-0 gates read
the board with the pack's own reader (``_kicad.py``), so they run where KiCad is not
installed and every file they decide on is keyed. ``pcb.pin_names`` judges against
the library's pin names that KiCad copied onto the board from the schematic, and
``pcb.net_width`` against IPC-2221's heating curve: both sourced.

**What slipped through, and which gate it is for** (from an autonomous board
pipeline this pack was extracted from; references/what-slipped-through.md):

- ``pcb.drc``: every gate in that pipeline ran at error severity, so a warning could
  never fail it. The pin-1 warning on a ribbon connector was 21.4 mm of silk on an
  8 mm strip, and its fab would have clipped it. This gate runs every severity, and
  a waiver is KiCad's own exclusion, recorded in the project file.
- ``pcb.drc``, ``pcb.unconnected``: the fab export there ignored kicad-cli's exit code
  and read a report file another script also wrote, so a failed run could pass on a
  stale one. These read the exit code and the report this run wrote, and a
  disagreement between the two is an error.
- ``pcb.net_width``: a power width was set in code that never reached the board, and
  the battery path shipped at 0.2 mm for weeks of "0 violations, 0 unconnected". No
  rule check can see a width nobody asked for.
- ``pcb.pin_names``: an ESD array's flow-through pins were wired D+ to pin 1 and D- to
  pin 6, which the part joins inside. The copper was legal; a person reading the
  datasheet found it.

**Missing inputs skip; they never default.** Which board, which nets carry how much
current, and how hot a trace may run are the project's to say.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import Counter

from nopekit.gates import gate, GateContext
from nopekit.modelio import load_path as _load_path
from nopekit.models import NegativeControl, Tier, Verdict

_HERE = os.path.dirname(os.path.abspath(__file__))
K = _load_path(os.path.join(_HERE, "_kicad.py"))

#: The newest board file version this reader was written and checked against:
#: KiCad 9.0's (``(version 20241229)``, unchanged through 9.0.9). A newer file may
#: have moved what the reader looks for (KiCad has changed how a track names its net
#: before), so the guard fails closed on it rather than read it on trust. Rejected:
#: accepting any version (a reader that silently finds no tracks on a new format
#: reports a clean board); a ceiling per minor release (the format version, not the
#: application's, is what moves).
MAX_BOARD_VERSION = 20241229

#: The oldest: KiCad 6 (``20211014``), the first S-expression board format with
#: ``pinfunction`` on pads. KiCad 5's is a different file and is refused.
MIN_BOARD_VERSION = 20211014

#: kicad-cli pcb drc's severity flags, by the word a project writes.
SEVERITY_FLAGS = {"all": "--severity-all", "error": "--severity-error",
                  "warning": "--severity-warning"}

#: ``kicad-cli pcb drc --exit-code-violations`` exits 5 when it found anything, 0
#: when it found nothing. Any other code is kicad-cli failing, never a verdict.
EXIT_CLEAN, EXIT_VIOLATIONS = 0, 5

#: Two minutes for a DRC: a 4-layer 115-footprint board takes about 2 s, so only a
#: hang reaches it. A timeout is a skip (nothing was shown), never a fail.
DEFAULT_DRC_TIMEOUT_S = 120.0

#: Copper weight when the project states none: 1 oz outer, 0.5 oz inner, what a
#: fab quotes without being asked. The verdict says "[pack default]" when used.
DEFAULT_OZ_OUTER = 1.0
DEFAULT_OZ_INNER = 0.5


def _skip(gid: str, reason: str) -> Verdict:
    return Verdict(gate=gid, passed=False, skipped=True, skip_reason=reason)


def _board_path(ctx: GateContext) -> str | None:
    rel = ctx.param("pcb_board")
    if not rel:
        return None
    rel = str(rel)
    return rel if os.path.isabs(rel) else os.path.join(ctx.root, rel)


_NO_BOARD = ("no pcb_board: the .kicad_pcb this pack checks, relative to the project "
             "root — this pack will not guess which board you mean")


def _evidence(ctx: GateContext, name: str, payload: dict) -> list[str]:
    path = ctx.out_path("pcb-kicad", f"{name}.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return [path]


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #
@gate(
    id="pcb.board_readable",
    basis="model-only",
    title="The board is a KiCad file this pack's reader knows",
    claims=["pcb", "pcb-model-validity"],
    tier=Tier.INSTANT,
    settles="board file readability",
    negative_control=NegativeControl(
        fixture="selftest/bad_boards.py:orphaned_net",
        note="the baseline board with VBUS dropped from its net table, so the VBUS "
             "tracks name a net code the board no longer defines — what a script "
             "that rewrote the net table leaves behind",
    ),
)
def board_readable(ctx: GateContext) -> Verdict:
    """The validity guard: whether the tier-0 gates' numbers mean anything.

    It fails when the board is a file this reader was not written for (older than
    KiCad 6, newer than KiCad 9), does not parse, or has tracks or pads whose net
    code the net table does not define. In each case ``pcb.net_width`` would read
    a net's tracks wrongly or not at all, and a net with no tracks found reads as
    nothing to judge, which is a pass by omission. ``pcb.pin_names`` and
    ``pcb.net_width`` need it. KiCad's own gates do not: KiCad reads the file
    itself.
    """
    gid = "pcb.board_readable"
    path = _board_path(ctx)
    if path is None:
        return _skip(gid, _NO_BOARD)
    try:
        tree = ctx.load_file(path, loader=K.load_tree)
    except FileNotFoundError:
        return Verdict(gate=gid, passed=False, detail=f"no board at {path}")
    except (K.KicadFormatError, UnicodeDecodeError) as exc:
        return Verdict(gate=gid, passed=False, detail=f"the board does not parse: {exc}")
    if K.head(tree) != "kicad_pcb":
        return Verdict(gate=gid, passed=False,
                       detail=f"not a KiCad board: the file starts ({K.head(tree)} ...)")
    raw_version = K.value(tree, "version", default="")
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        return Verdict(gate=gid, passed=False,
                       detail=f"no readable (version ...) in the board: {raw_version!r}")
    problems = []
    if version > MAX_BOARD_VERSION:
        problems.append(f"file version {version} is newer than {MAX_BOARD_VERSION} "
                        f"(KiCad 9.0), the newest this reader was checked against")
    if version < MIN_BOARD_VERSION:
        problems.append(f"file version {version} is older than {MIN_BOARD_VERSION} "
                        f"(KiCad 6), the first with library pin names on pads")
    defined = {int(n[1]) for n in K.children(tree, "net")
               if len(n) >= 2 and str(n[1]).lstrip("-").isdigit()}
    orphans: Counter = Counter()
    for kind in ("segment", "arc", "via"):
        for item in K.children(tree, kind):
            net = K.child(item, "net")
            if net is not None and len(net) >= 2 and not isinstance(net[1], K.Q):
                try:
                    code = int(net[1])
                except ValueError:
                    continue
                if code not in defined:
                    orphans[code] += 1
    if orphans:
        problems.append(f"{sum(orphans.values())} track(s) or via(s) name net code(s) "
                        f"{sorted(orphans)} that the net table does not define")
    board = K.board_from_tree(tree)
    copper = sorted({t.layer for t in board.tracks})
    detail = (f"KiCad board version {version}: {len(board.nets)} net(s), "
              f"{len(board.footprints)} footprint(s), {len(board.tracks)} track(s) on "
              f"{', '.join(copper) or 'no layer'}")
    return Verdict(gate=gid, passed=not problems,
                   detail=detail + ("; " + "; ".join(problems) if problems else ""))


# --------------------------------------------------------------------------- #
# library pin names
# --------------------------------------------------------------------------- #
@gate(
    id="pcb.pin_names",
    basis="sourced",
    title="Pins the library gives one name carry one net",
    claims=["pcb", "pin-map", "netlist", "short-circuit"],
    tier=Tier.INSTANT,
    settles="library pin-name agreement",
    # Prerequisite pcb.board_readable: a board whose net table this reader cannot
    #    vouch for is one whose pad nets it may have read wrongly. Isolated: the guard
    #    passes this gate's own known-bad control (test_packs.ControlsAreIsolated).
    needs=["pcb.board_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_boards.py:split_pin_pair",
        note="the baseline board with U1 pin 6 moved from D+ to D-: the ESD array's "
             "two I/O1 pins now carry the two data lines, which the part joins inside",
    ),
)
def pin_names(ctx: GateContext) -> Verdict:
    """Every pin name a footprint repeats carries one net.

    A library symbol gives two pins one name when the part joins them inside: a
    flow-through ESD array's ``I/O1`` is pins 1 and 6, a regulator's ``GND`` is its
    tab and a pin. KiCad copies those names onto the board's pads as
    ``pinfunction`` when the board is updated from its schematic. Two different
    nets on one name is a short through the part, on copper every design rule
    accepts.

    The names are the library's, not this gate's: the gate only compares. A board
    drawn without a schematic carries none, and the gate skips (nothing to compare
    against), never passes. ``NC``-style names are ignored (``pcb_pin_names_ignore``)
    because an unused pin may legitimately sit on any net.
    """
    gid = "pcb.pin_names"
    path = _board_path(ctx)
    if path is None:
        return _skip(gid, _NO_BOARD)
    board = ctx.load_file(path, loader=K.load_board)
    ignore = ctx.param("pcb_pin_names_ignore", list(K.NO_FUNCTION_NAMES))
    conflicts, named, fps_named = K.pin_name_conflicts(board, ignore)
    if named == 0:
        return _skip(gid, "no pad on this board carries a library pin name "
                          "(pinfunction): it was not updated from a schematic, so there "
                          "is nothing to compare its nets against")
    ev = _evidence(ctx, "pin_names", {
        "footprints": len(board.footprints), "footprints_with_pin_names": fps_named,
        "named_pads": named, "ignored_names": list(ignore),
        "conflicts": [{"ref": r, "name": n, "nets": by} for r, n, by in conflicts]})
    if conflicts:
        worst = "; ".join(f"{r} {n}: " + ", ".join(f"{net} on {'/'.join(p)}"
                                                   for net, p in by.items())
                          for r, n, by in conflicts[:3])
        detail = (f"{len(conflicts)} pin name(s) carry more than one net, a short "
                  f"through the part: {worst}")
    else:
        detail = (f"every repeated pin name carries one net ({named} named pad(s) on "
                  f"{fps_named} of {len(board.footprints)} footprint(s))")
    return Verdict(gate=gid, passed=not conflicts, measured=len(conflicts), limit=0,
                   comparator="<=", units="pin names", detail=detail, evidence=ev)


# --------------------------------------------------------------------------- #
# trace heating
# --------------------------------------------------------------------------- #
@gate(
    id="pcb.net_width",
    basis="sourced",
    title="Each current-carrying net's narrowest track stays inside its heating limit",
    claims=["pcb", "trace-width", "current-capacity", "power-integrity"],
    tier=Tier.INSTANT,
    settles="trace temperature rise",
    # Prerequisite pcb.board_readable: a track whose net code the table does not
    #    define is a track this gate cannot attribute to a net, and a net it found
    #    no tracks for reads as nothing to judge. Isolated: the guard passes this
    #    gate's own known-bad control.
    needs=["pcb.board_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_boards.py:narrow_power",
        note="the baseline board with every VBUS track narrowed to the width at which "
             "IPC-2221 puts the baseline current 15% past the baseline's own rise limit",
    ),
)
def net_width(ctx: GateContext) -> Verdict:
    """IPC-2221's temperature rise of each named net's narrowest track.

    dT = (I / (k * A^0.725))^(1/0.44), A the track's cross-section in square mils
    (width x copper thickness), k 0.048 outside the stack and 0.024 inside
    (references/ipc-2221.md). ``pcb_net_currents_a`` names the nets and their
    currents, ``pcb_temp_rise_limit_c`` the rise a track may reach. The verdict is
    the worst track of any named net.

    Every track of the net is judged, not only the one the current takes: the
    board does not say which path is which. A net carried by a pour as well as by
    tracks is judged on its tracks, which is conservative. Vias, pads and pours are
    not judged at all (PACK.md, "cannot settle").
    """
    gid = "pcb.net_width"
    path = _board_path(ctx)
    if path is None:
        return _skip(gid, _NO_BOARD)
    currents = ctx.param("pcb_net_currents_a")
    if not isinstance(currents, dict) or not currents:
        return _skip(gid, "no pcb_net_currents_a: which nets carry how much current "
                          "({\"VBUS\": 0.5}) is a design fact this pack will not invent")
    limit = ctx.param("pcb_temp_rise_limit_c")
    if limit is None:
        return _skip(gid, "no pcb_temp_rise_limit_c: how hot a track may run above "
                          "ambient is a product decision this pack will not invent")
    limit = float(limit)
    oz_out = ctx.param("pcb_copper_oz_outer")
    oz_in = ctx.param("pcb_copper_oz_inner")
    defaulted = [name for name, v in (("outer", oz_out), ("inner", oz_in)) if v is None]
    oz_out = DEFAULT_OZ_OUTER if oz_out is None else float(oz_out)
    oz_in = DEFAULT_OZ_INNER if oz_in is None else float(oz_in)
    board = ctx.load_file(path, loader=K.load_board)

    rows, unrouted = [], []
    for net, amps in sorted(currents.items()):
        tracks = [t for t in board.tracks if t.net == net]
        if not tracks:
            unrouted.append(net)
            continue
        for t in tracks:
            outer = t.layer in K.OUTER_LAYERS
            rise = K.temp_rise_c(float(amps), t.width_mm, oz_out if outer else oz_in, outer)
            rows.append((rise, net, float(amps), t.width_mm, t.layer, outer))
    if not rows:
        return _skip(gid, f"none of {sorted(currents)} has a track on this board "
                          f"(carried by pours or pads alone?): nothing this gate can judge")
    rise, net, amps, width, layer, outer = max(rows)
    reported = round(rise, 1)
    passed = reported <= limit
    lo, hi = K.FIT_RANGE["temp_rise_c"]
    outside = []
    if not lo <= limit <= hi:
        outside.append(f"a {limit:g} C limit")
    if width / K.MM_PER_MIL > K.FIT_RANGE["width_mil"][1]:
        outside.append(f"a {width:g} mm track")
    if amps > K.FIT_RANGE["current_a"][1]:
        outside.append(f"{amps:g} A")
    ev = _evidence(ctx, "net_width", {
        "formula": "dT = (I / (k * A^0.725))^(1/0.44), A = width_mil * 1.378 * oz",
        "source": "IPC-2221 (2012) section 6.2; references/ipc-2221.md",
        "copper_oz": {"outer": oz_out, "inner": oz_in, "defaulted": defaulted},
        "limit_c": limit, "unrouted_nets": unrouted,
        "worst_per_net": {n: max((r for r in rows if r[1] == n), default=None)
                          for n in sorted({r[1] for r in rows})}})
    oz = oz_out if outer else oz_in
    detail = (f"{net}: narrowest {width:g} mm on {layer} rises {reported:g} C at "
              f"{amps:g} A (IPC-2221 {'external' if outer else 'internal'}, {oz:g} oz"
              f"{' [pack default]' if ('outer' if outer else 'inner') in defaulted else ''}) "
              f"vs {limit:g} C")
    if unrouted:
        detail += f"; no tracks on {', '.join(unrouted)} (not judged)"
    if outside:
        detail += f"; outside IPC-2221's fitted range: {', '.join(outside)}"
    return Verdict(gate=gid, passed=passed, measured=reported, limit=limit,
                   comparator="<=", units="C", detail=detail, evidence=ev)


# --------------------------------------------------------------------------- #
# KiCad's own checks
# --------------------------------------------------------------------------- #
def _drc(ctx: GateContext, gid: str, path: str, severity: str):
    """Run ``kicad-cli pcb drc`` on a staged copy; ``(code, report, evidence)`` or a
    skip/error Verdict.

    Staged under the gate's out directory, the board, its project file and its
    custom rules beside it: kicad-cli then writes nothing in the project, and the
    copy (a Python read) keys the three files even though the subprocess's own
    reads are invisible. The project file holds KiCad's DRC exclusions, which is
    where a waiver lives: a named, reviewable record, never a severity filter.
    """
    stem = path[:-len(".kicad_pcb")] if path.endswith(".kicad_pcb") else path
    name = os.path.basename(stem)
    staged = ctx.out_path("pcb-kicad", gid.replace(".", "_"), name + ".kicad_pcb")
    stage = os.path.dirname(staged)
    if not os.path.isfile(path):
        return Verdict(gate=gid, passed=False, detail=f"no board at {path}")
    shutil.copyfile(path, staged)
    for ext in (".kicad_pro", ".kicad_dru"):
        if os.path.isfile(stem + ext):
            shutil.copyfile(stem + ext, os.path.join(stage, name + ext))
    report = os.path.join(stage, "drc.json")
    if os.path.exists(report):
        os.remove(report)
    timeout = float(ctx.param("pcb_drc_timeout_s", DEFAULT_DRC_TIMEOUT_S) or
                    DEFAULT_DRC_TIMEOUT_S)
    argv = ["kicad-cli", "pcb", "drc", SEVERITY_FLAGS[severity], "--exit-code-violations",
            "--format", "json", "--units", "mm", "-o", report, staged]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
    except FileNotFoundError as exc:
        return _skip(gid, f"could not launch kicad-cli: {exc}")
    except subprocess.TimeoutExpired:
        return _skip(gid, f"kicad-cli pcb drc exceeded {timeout:g} s (pcb_drc_timeout_s) "
                          f"and was killed: nothing was shown")
    log = os.path.join(stage, "kicad-cli.log")
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(" ".join(argv) + f"\nexit {proc.returncode}\n{proc.stdout}\n{proc.stderr}")
    if proc.returncode not in (EXIT_CLEAN, EXIT_VIOLATIONS) or not os.path.isfile(report):
        return Verdict(gate=gid, passed=False,
                       error=f"kicad-cli pcb drc exited {proc.returncode} without a "
                             f"report: {(proc.stderr or proc.stdout).strip()[:200]}",
                       evidence=[log])
    with open(report, encoding="utf-8") as fh:
        doc = json.load(fh)
    return proc.returncode, doc, [report, log]


def _kinds(items) -> str:
    counts = Counter(f"{v.get('type', '?')} ({v.get('severity', '?')})" for v in items)
    return ", ".join(f"{n}x {k}" for k, n in counts.most_common(4))


@gate(
    id="pcb.drc",
    basis="established",
    title="KiCad's design rule check finds nothing, at every severity",
    claims=["pcb", "design-rules", "manufacturability", "clearance"],
    tier=Tier.BUILD,
    settles="design rule violations",
    requires_tools=["kicad-cli"],
    negative_control=NegativeControl(
        fixture="selftest/bad_boards.py:fat_track",
        note="the baseline board with U1's D+ track widened to 1.0 mm, which runs its "
             "copper into the ground pad beside it",
    ),
)
def drc(ctx: GateContext) -> Verdict:
    """``kicad-cli pcb drc --severity-all --exit-code-violations``: the verdict is
    KiCad's exit code. The report is read for the count and the kinds, and an exit
    code that disagrees with the report is an error, never a pass.

    ``pcb_drc_severity`` narrows it (``error``, ``warning``); the default is every
    severity, because a check at error severity cannot see a warning and the fab
    still prints it. To waive one finding, exclude it in KiCad: the exclusion is
    saved in the project file, by name, and this gate honours it.
    """
    gid = "pcb.drc"
    path = _board_path(ctx)
    if path is None:
        return _skip(gid, _NO_BOARD)
    severity = str(ctx.param("pcb_drc_severity", "all") or "all")
    if severity not in SEVERITY_FLAGS:
        return Verdict(gate=gid, passed=False,
                       error=f"pcb_drc_severity {severity!r} is not one of "
                             f"{sorted(SEVERITY_FLAGS)}")
    run = _drc(ctx, gid, path, severity)
    if isinstance(run, Verdict):
        return run
    code, doc, ev = run
    found = (list(doc.get("violations", [])) + list(doc.get("unconnected_items", []))
             + list(doc.get("schematic_parity", [])))
    if (code == EXIT_CLEAN) != (not found):
        return Verdict(gate=gid, passed=False, evidence=ev,
                       error=f"kicad-cli exited {code} but its report lists "
                             f"{len(found)} item(s): the two disagree")
    detail = (f"KiCad DRC at {severity} severities: "
              + (f"{len(found)} finding(s): {_kinds(found)}" if found else "nothing found"))
    return Verdict(gate=gid, passed=code == EXIT_CLEAN, measured=len(found), limit=0,
                   comparator="<=", units="findings", detail=detail, evidence=ev)


@gate(
    id="pcb.unconnected",
    basis="established",
    title="Every connection the netlist asks for is made in copper",
    claims=["pcb", "connectivity", "netlist"],
    tier=Tier.BUILD,
    settles="unconnected items",
    requires_tools=["kicad-cli"],
    negative_control=NegativeControl(
        fixture="selftest/bad_boards.py:open_net",
        note="the baseline board with the D- track from J1 to U1 deleted, leaving the "
             "data line open between the input header and the protector",
    ),
)
def unconnected(ctx: GateContext) -> Verdict:
    """KiCad's own count of unconnected items, from a DRC run at error severity
    (an unconnected item is always an error). Narrower than ``pcb.drc``: a claim
    that every net is complete binds here, and stays Checked through a silk
    warning that ``pcb.drc`` fails on."""
    gid = "pcb.unconnected"
    path = _board_path(ctx)
    if path is None:
        return _skip(gid, _NO_BOARD)
    run = _drc(ctx, gid, path, "error")
    if isinstance(run, Verdict):
        return run
    _code, doc, ev = run
    items = list(doc.get("unconnected_items", []))
    nets = sorted({i.get("description", "").split("[", 1)[-1].split("]", 1)[0]
                   for v in items for i in v.get("items", []) if "[" in i.get("description", "")})
    detail = (f"{len(items)} unconnected item(s) on {', '.join(nets[:6]) or '?'}"
              if items else "every connection the netlist asks for is made")
    return Verdict(gate=gid, passed=not items, measured=len(items), limit=0,
                   comparator="<=", units="items", detail=detail, evidence=ev)
