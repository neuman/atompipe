# SPDX-License-Identifier: Apache-2.0
"""page.py — the front page's baked data (architecture phase 5, SPEC 28-33).

`nopekit site build` writes two files for the front page beside `state.json`
(the technical record): ``site/data/map.json``, the grounding map, and
``site/data/page.json``, the outline around it — the verdict sentence, one
section per board with its floor and its prose, the next steps and the words.
This module computes both from what every reader already holds: the
resolution, the compositions over it (`claims.compositions`), the status tokens
beside the graph (`graph.tokens`), the typed graph itself (`graph.build`, the
map's only source of structure) and the groups (SPEC 17).

**Order is baked, geometry is rendered** (SPEC 29). A node carries a lane, an
order index and a column (an index, never a pixel); no file here holds an x or
a y. A status flip never moves an order, a row or a column: structure decides
them, and statuses sit beside them as tokens.

**The browser computes no truth** (SPEC 32, invariant 14). Every status, word,
count, margin and *ready* on the page is here, from its one producer: a claim's
token is `graph.tokens`', a board's is `claims.worst_of` over its claims, a
milestone's steps are `claims.unresolved`'s, a margin is `claims.margin`'s.
`status_problems` is the one checker: the build refuses a page it finds wrong,
and `site status`, `status` and `doctor` read a hand-edited page with it.

What slipped through before this module: the reference page decided its
go/no-go in the browser from a hand-kept claim list, so a claim added to a board
never reached it; and the template ranked anchored verdicts by their `passed`
flag beside the resolver's word.

Pure apart from reading ``site/content/`` and the evidence files' presence and
size; no clock, no git, no network. It never imports `site` (which imports it).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import posixpath
import shlex
from typing import Any, Callable, Iterable, Mapping, NamedTuple

from . import claims as claim_logic
from . import graph as graph_logic
from . import prose as prose_logic
from . import report as report_logic
from . import store
from .claims import ClaimCause, ClaimStatus
from .models import ClaimKind
from .store import _natural

#: The outline this module bakes for (`site.OUTLINE_MARKER` carries it in the
#: shell), and the schema of both files. Bumped only when a key changes meaning.
OUTLINE = 1
SCHEMA = 1

#: The map's lanes, left to right: what was asked, the choices, the values
#: several lines share, the claims on their boards (SPEC 29).
LANES: tuple[str, ...] = ("requirements", "zones", "stations", "boards")

#: The graph's edge types the map carries. `requires` (a milestone's claims) is
#: next steps' and `decides` the technical record's: neither is drawn.
MAP_EDGE_TYPES: tuple[str, ...] = tuple(t for t in graph_logic.EDGE_TYPES
                                        if t not in ("requires", "decides"))

#: The generated board (claims on no board) and zone (choices in no zone).
OTHER = "other"

#: Past this many generated stations the build warns. Provenance: the
#: reference map has 11 hubs, and past about 8 station columns the drawing is
#: wider than 1400 px. *Rejected:* no cap (silent clutter: a model whose
#: evaluators share many intermediates would draw a station per value).
IMPLICIT_STATIONS_WARN = 8

#: The largest evidence file the build copies into ``site/assets/``.
#: Provenance: the site is committed, so a mesh copied for each verdict entry
#: grows the repository on every re-run; PETGasus's largest evidence file is
#: about 0.3 MiB. *Rejected:* no cap (an STL on every check); a total cap (which
#: file loses would then depend on listing order).
EVIDENCE_MAX_BYTES = 2 * 1024 * 1024

#: Where the evidence lands, under ``site/``.
EVIDENCE_DIR = "assets/evidence"

#: The prose subjects that are not boards.
PROSE_SUBJECTS = ("intro", "next")

#: Keys whose string values are words the build writes (scanned for the site's
#: register, `test_style`) and keys whose strings are record text, ids, tokens,
#: paths or the CLI's shared producers (exempt). Every string-valued key of
#: `page.json` and `map.json` is in exactly one (`test_style.EveryBakedKeyIsClassified`).
WORD_KEYS = frozenset({
    "generated", "notice", "sentence", "limits", "label", "word", "value_text", "hint",
    "cause_text", "text", "kind_word", "by_word", "basis_word", "outcome_word", "missing",
    "term"})
RECORD_KEYS = frozenset({
    "schema", "name", "summary", "revision", "records_digest", "resolution_digest",
    "content_digest", "trace", "view", "kind", "title", "token", "id", "key", "lane",
    "line", "board", "claim_kind", "role", "units", "zone", "station", "ground", "basis",
    "pack", "outcome", "self", "reads_all", "claim", "status", "file", "subject", "as_of",
    "current_as_of", "stamp", "statement", "cause", "by", "how", "acceptance",
    "limit_text", "gate", "comparator", "source", "stale_reason", "detail", "href", "why",
    "recorded", "heading", "description", "article", "type", "src", "alt", "t", "num",
    "unit", "unmatched", "register", "problems", "lanes", "members", "claims", "marks",
    "stops", "values", "unread", "evaluators", "requirements", "rests_on", "resolves",
    "resolved_by", "commands", "legend", "nodes", "edges", "via", "steps", "milestones",
    "assumptions"})


class Board(NamedTuple):
    id: str
    title: str
    line: str
    generated: bool
    members: tuple


class Zone(NamedTuple):
    id: str
    title: str
    line: str
    generated: bool
    members: tuple


class Station(NamedTuple):
    id: str                      # the record's id, or "@<name>" when generated
    title: str
    line: str
    generated: bool
    members: tuple


class Layout(NamedTuple):
    """The map's structure: ``boards``, ``zones`` and ``stations`` in order;
    ``board_of`` (claim id -> board id), ``zone_of`` and ``station_of`` (value
    name -> node id); ``lines``, one per claim in board-row order; ``unread``,
    the choices no line touches; ``warnings``, in the CLI's register."""

    boards: tuple
    zones: tuple
    stations: tuple
    board_of: dict
    zone_of: dict
    station_of: dict
    lines: tuple
    unread: tuple
    warnings: tuple


def _site_words() -> Mapping[str, Any]:
    return report_logic.HUMAN["site"]


def token_of(composed: Any) -> str:
    """A claim's token: `claims.STATUS_KEY`, ``errored`` for a crash —
    `graph.tokens`' rule."""
    return "errored" if composed.errored else claim_logic.STATUS_KEY[composed.status]


def _split(nid: str) -> tuple[str, str]:
    kind, _, key = nid.partition(":")
    return kind, key


# --------------------------------------------------------------------------- #
# groups and the layout
# --------------------------------------------------------------------------- #
def boards_of(view: Any) -> tuple:
    """The boards, from the records alone: board records by ``(order, id)``,
    each with the members a claim holds (a claim on a second board stays on the
    first), then the generated board ``other`` with every claim on no board, in
    natural order — a removed claim's fail included — only when one exists. Its
    title is "Other" beside board records, "Claims" with none."""
    said = _site_words()
    claim_ids = [c.id for c in getattr(view, "claims", None) or ()]
    held = set(claim_ids)
    records = store.groups_in_order(getattr(view, "groups", None) or (), "board")
    out: list[Board] = []
    placed: set[str] = set()
    for group in records:
        members = []
        for cid in group.members:
            if cid in held and cid not in placed:
                members.append(cid)
                placed.add(cid)
        out.append(Board(group.id, group.title, group.line or "", False, tuple(members)))
    rest = tuple(sorted((cid for cid in claim_ids if cid not in placed), key=_natural))
    if rest:
        out.append(Board(OTHER, said["other_board" if records else "all_board"], "", True,
                         rest))
    return tuple(out)


def _reads_of(cid: str, built: Any, reads: Mapping[str, tuple], choices: list,
              derived: tuple) -> tuple[list[str], str | None]:
    """The value names claim ``cid``'s settling evaluators read by a named path,
    closed upward over ``derives``; and ``reads_all`` for a whole read."""
    named: set[str] = set()
    whole: str | None = None
    for ev in built.into(graph_logic.node_id("claim", cid), "settles"):
        gid = _split(ev)[1]
        for path in reads.get(gid, ()):
            if not path:
                whole = "values"
                continue
            if path[0] == "config" and len(path) == 1:
                whole = whole or "choices"
                continue
            for name in graph_logic.value_names(path, choices, derived):
                for nid in graph_logic.upward(built, graph_logic.node_id("value", name)):
                    named.add(_split(nid)[1])
    return sorted(named, key=_natural), whole


def _columns(nodes: list[str], spans: Mapping[str, list[int]]) -> dict[str, int]:
    """Greedy interval packing: each node, in order, takes the first column in
    which no node already placed has a span that meets its own (closed
    intervals). A node no line visits takes column 0."""
    taken: list[list[tuple[int, int]]] = []
    out: dict[str, int] = {}
    for nid in nodes:
        rows = spans.get(nid) or []
        if not rows:
            out[nid] = 0
            continue
        lo, hi = min(rows), max(rows)
        for col, intervals in enumerate(taken):
            if all(hi < a or lo > b for a, b in intervals):
                intervals.append((lo, hi))
                out[nid] = col
                break
        else:
            taken.append([(lo, hi)])
            out[nid] = len(taken) - 1
    return out


def layout(view: Any, built: Any, *, projection: Any, params: Iterable[Any] = (),
           registry: Any = None, resolution: Any = None) -> Layout:
    """The map's structure (SPEC 17, 29) from the records, the graph and the
    reads the resolution served — never from a status, so a flip moves no row.

    Boards as `boards_of`. Zones: zone records by ``(order, id)`` with their
    members (a choice in a second zone stays in the first), then the generated
    zone of the choices no zone holds that a line touches or an assumption
    sources, in ``Config`` order; no zones with no model. Stations: station
    records, then a generated ``station:@<name>`` for each derived value no
    record holds that the settling evaluators of two or more claims read by a
    named path (a whole read never makes one). A line stops at its
    requirements, the zones and the stations of the values it reads, then its
    claim."""
    said = _site_words()
    warnings: list[str] = []
    config = dict(projection.get("config") or {}) if isinstance(projection, Mapping) else {}
    has_model = isinstance(projection, Mapping) and isinstance(projection.get("config"),
                                                               Mapping)
    choices = list(config)
    derived = graph_logic.derived_names(projection)
    # Every derived key, read or not: a station may name a value no evaluator
    # reads (it is no graph node), and that is not a mistake.
    derived_all = set(derived) | set(
        (projection.get("derived") or {}) if isinstance(projection, Mapping) else ())
    role = {_split(n.id)[1]: n.attrs.get("role") for n in built.nodes if n.kind == "value"}
    reads = graph_logic.served_reads(resolution, registry)
    groups = getattr(view, "groups", None) or ()
    claim_list = list(getattr(view, "claims", None) or ())
    by_id = {c.id: c for c in claim_list}

    boards = boards_of(view)
    held = set(by_id)
    for group in store.groups_in_order(groups, "board"):
        for cid in group.members:
            if cid not in held:
                warnings.append(f"groups/{group.id}.json: board member {cid} has no "
                                f"claims/{cid}.json")
    board_of = {cid: board.id for board in boards for cid in board.members}
    rows = [cid for board in boards for cid in board.members]

    values_of: dict[str, list[str]] = {}
    whole_of: dict[str, str | None] = {}
    for cid in rows:
        values_of[cid], whole_of[cid] = _reads_of(cid, built, reads, choices, derived)
    touched = {name for names in values_of.values() for name in names}
    sourced = {_split(e.target)[1] for e in built.edges
               if e.type == "sources" and _split(e.source)[0] == "claim"}

    zones: list[Zone] = []
    zone_of: dict[str, str] = {}
    unread: tuple = ()
    if has_model:
        records = store.groups_in_order(groups, "zone")
        for group in records:
            members = []
            for name in group.members:
                if name in zone_of:
                    warnings.append(f"groups/{group.id}.json: choice {name} is also in zone "
                                    f"{_split(zone_of[name])[1]}; the map puts it there")
                    continue
                if name not in config:
                    warnings.append(f"groups/{group.id}.json: zone member {name} is not a "
                                    f"choice of the model")
                zone_of[name] = f"zone:{group.id}"
                members.append(name)
            zones.append(Zone(group.id, group.title, group.line or "", False, tuple(members)))
        rest = tuple(c for c in choices
                     if c not in zone_of and (c in touched or c in sourced))
        if rest:
            zones.append(Zone(OTHER, said["other_zone" if records else "all_zone"], "", True,
                              rest))
            for name in rest:
                zone_of[name] = f"zone:{OTHER}"
        unread = tuple(sorted((c for c in choices if c not in touched), key=_natural))

    stations: list[Station] = []
    station_of: dict[str, str] = {}
    for group in store.groups_in_order(groups, "station"):
        members = []
        for name in group.members:
            if name in zone_of or name in station_of:
                continue
            if has_model and name not in derived_all:
                warnings.append(f"groups/{group.id}.json: station member {name} is not a "
                                f"derived value of the model")
            station_of[name] = f"station:{group.id}"
            members.append(name)
        stations.append(Station(group.id, group.title, group.line or "", False,
                                tuple(members)))
    readers: dict[str, set[str]] = {}
    for cid in rows:
        for name in values_of[cid]:
            readers.setdefault(name, set()).add(cid)
    generated = sorted((name for name, cids in readers.items()
                        if len(cids) >= 2 and role.get(name) == "derived"
                        and name not in station_of and name not in zone_of), key=_natural)
    for name in generated:
        stations.append(Station(f"@{name}", name, "", True, (name,)))
        station_of[name] = f"station:@{name}"
    if len(generated) > IMPLICIT_STATIONS_WARN:
        warnings.append(f"{len(generated)} shared values became stations on the map: name the "
                        f"ones that matter in groups/<id>.json (\"kind\": \"station\")")

    requirement_ids = [r.id for r in getattr(view, "requirements", None) or ()]
    requirement_set = set(requirement_ids)
    zone_ids = [f"zone:{z.id}" for z in zones]
    station_ids = [f"station:{s.id}" for s in stations]
    lines: list[dict] = []
    for order, cid in enumerate(rows):
        claim = by_id[cid]
        values = values_of[cid]
        stops = [f"requirement:{rid}" for rid in getattr(claim, "requirements", None) or ()
                 if rid in requirement_set]
        via: dict[str, list[str]] = {}
        for nid in zone_ids + station_ids:
            names = [n for n in values if zone_of.get(n) == nid or station_of.get(n) == nid]
            if names:
                stops.append(nid)
                via[nid] = names
        stops.append(f"claim:{cid}")
        lines.append({"claim": cid, "order": order, "board": board_of[cid], "stops": stops,
                      "via": via, "values": values, "reads_all": whole_of[cid]})
    return Layout(tuple(boards), tuple(zones), tuple(stations), board_of, zone_of,
                  station_of, tuple(lines), unread, tuple(warnings))


# --------------------------------------------------------------------------- #
# words and numbers
# --------------------------------------------------------------------------- #
def _num(value: Any) -> str:
    """A value as the page shows it: `report._num`'s, four significant figures
    for a fraction of a measurement."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return report_logic._num(value)
    if isinstance(value, int):
        return str(value)
    if not math.isfinite(value):
        return report_logic._num(value)
    if abs(value) >= 1e4:
        return str(int(round(value)))
    return f"{value:.4g}"


def _pct(fraction: float) -> str:
    pct = abs(fraction) * 100.0
    return f"{round(pct)}%" if pct >= 1 else f"{pct:.2f}%"


def value_text(measured: Any, units: str, limit_text: str, margin: float | None) -> str:
    """``0.6997 mm against a limit of 0.5 mm, 40% past the limit`` — the claim's
    limit (S-35: never the verdict's), the margin `claims.margin` gave."""
    said = _site_words()
    if limit_text:
        text = said["value"].format(measured=_num(measured), units=units or "",
                                    limit=limit_text)
    else:
        text = said["value_bare"].format(measured=_num(measured), units=units or "")
    text = " ".join(text.split())
    if margin is not None and limit_text:
        if margin == 0:
            text += said["margin_at"]
        elif margin > 0:
            text += said["margin_inside"].format(pct=_pct(margin))
        else:
            text += said["margin_past"].format(pct=_pct(margin))
    return text


def words_block() -> dict:
    """``page.json``'s ``words``: each token's word, term and hint, and the
    tables the page labels with (lanes, kinds, mechanism, basis, outcome,
    headings, notices)."""
    said = _site_words()
    tokens: dict[str, dict] = {}
    for token in claim_logic.SEVERITY_ORDER:
        status = next(s for s, k in claim_logic.STATUS_KEY.items()
                      if k == ("skipped" if token == "errored" else token))
        row = report_logic.words(status, errored=token == "errored")
        tokens[token] = {"word": row.word, "term": row.term, "hint": said["hint"][token]}
    return {"tokens": tokens, "lanes": dict(said["lanes"]), "kinds": dict(said["kinds"]),
            "by": dict(said["by"]), "basis": dict(said["basis"]),
            "outcome": dict(said["outcome"]), "headings": dict(said["headings"]),
            "notices": dict(said["notices"]),
            "ready": {"ready": said["ready_word"], "not-ready": said["not_ready_word"]}}


def _word(token: str) -> str:
    status = next(s for s, k in claim_logic.STATUS_KEY.items()
                  if k == ("skipped" if token == "errored" else token))
    return report_logic.words(status, errored=token == "errored").word


def _marks(toks: Any) -> dict[str, list[str]]:
    """Each claim's marks: tokens shown beside its status, never instead of it
    (``disagree`` today; phase 3b's ``amber``)."""
    out: dict[str, list[str]] = {}
    for cid in (getattr(toks, "disagree", None) or {}).get("claims") or ():
        out.setdefault(cid, []).append("disagree")
    return out


def _outcome_word(status: str) -> str:
    said = _site_words()["outcome"]
    return said.get({"error": "errored", "prerequisite": "skipped",
                     "prerequisite-errored": "errored"}.get(status, status), status)


# --------------------------------------------------------------------------- #
# evidence (SPEC 30)
# --------------------------------------------------------------------------- #
class Evidence(NamedTuple):
    """One evidence path a verdict names, planned for the page: ``path`` as
    recorded; ``source`` the file now (or None); ``dest`` its place under
    ``site/`` (or None); ``href`` what the page links (or None); ``missing``
    the page's words when there is none; ``action`` ``copy``, ``keep`` or
    ``none``; ``reason`` why it is not on the page, in the build's words, for
    the build's warnings only (it reads this machine's disk, so it is never
    baked)."""

    gate: str
    entry: str
    path: str
    name: str
    source: str | None
    dest: str | None
    href: str | None
    missing: str
    action: str
    reason: str = ""


def _component(text: str) -> str:
    safe = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in str(text))
    safe = safe.lstrip(".") or "_"
    return safe[:128]


def _size_words(n: int) -> str:
    from .util import human_bytes
    return human_bytes(n)


def _inside(path: str, folder: str) -> bool:
    """Whether ``path`` resolves inside ``folder`` (links followed)."""
    real, base = os.path.realpath(path), os.path.realpath(folder)
    return real.startswith(base + os.sep)


def _free_name(name: str, taken: set[str]) -> str:
    """``name`` made a file name, with ``-2``, ``-3`` before its extension
    until no name in ``taken`` equals it ignoring case."""
    safe = _component(name)
    stem, dot, ext = safe.rpartition(".")
    count = 1
    shown = safe
    while shown.casefold() in taken:
        count += 1
        shown = f"{stem}-{count}.{ext}" if dot and stem else f"{safe}-{count}"
    taken.add(shown.casefold())
    return shown


def evidence_plan(root: str, view: Any, resolution: Any, registry: Any = None, *,
                  ignored: Callable[[str], bool] | None = None) -> list:
    """Every evidence path of every verdict whose row stands on a cache entry,
    planned: ``<out>/rest`` resolves under ``.nopekit/out/`` and must stay
    there, links followed; a bare relative path resolves under the root and
    must stay inside it, with no hidden part (``.env``, ``.git/``) and not
    ignored by git (``ignored``, the caller's: a relative path it calls
    ignored is never published); ``<out:controls>/``, ``<tmp>/``, ``~/``,
    ``<pack:…>/``, absolute paths and a ``..`` part are never published. The
    copy lands at ``assets/evidence/<gate>/<entry>/<name>``, keyed by the entry
    it came from, so a fresh clone (no ``.nopekit/out/``) keeps the copy a
    build made and links it; names that clash in one entry, ignoring case,
    gain ``-2``, ``-3``. Plans only: `site.build` copies.

    The words baked beside a path that is not on the page depend only on the
    path (outside the project, or not on the page); why a file inside is not
    copied (too large, a directory, gone, ignored, a link out) reads this
    disk, so it is ``reason``, for the build's warnings.

    What slipped through (review of phase 5): ``<out>/../../x`` and a link in
    ``.nopekit/out/`` published any file the builder could read; a bare path
    published a git-ignored ``.env``; ``a.json``, ``x/a.json`` and ``a-2.json``
    planned one destination; and a fresh clone baked other words than the
    machine that ran the check, so the same records gave other bytes."""
    said = _site_words()["evidence"]
    out_root = store.out_dir(root)
    rows = getattr(resolution, "rows", None) or {}
    plan: list[Evidence] = []
    for verdict in getattr(view, "verdicts", None) or ():
        row = rows.get(verdict.gate)
        entry = getattr(row, "entry", None)
        entry_name = getattr(entry, "name", "") if entry is not None else ""
        taken: set[str] = set()
        for path in verdict.evidence or ():
            text = str(path)
            name = posixpath.basename(text.replace("\\", "/").rstrip("/")) or "evidence"
            source: str | None = None
            outside = False
            reason = ""
            if text.startswith("<out>/"):
                parts = text[len("<out>/"):].replace("\\", "/").split("/")
                if ".." in parts or not any(parts):
                    outside = True
                else:
                    candidate = os.path.join(out_root, *[p for p in parts if p])
                    if os.path.lexists(candidate) and not _inside(candidate, out_root):
                        reason = "it leaves .nopekit/out/ through a link"
                    else:
                        source = candidate
            elif text.startswith(("<", "~")) or os.path.isabs(text):
                outside = True
            else:
                parts = [p for p in text.replace("\\", "/").split("/") if p not in ("", ".")]
                if not parts or ".." in parts:
                    outside = True
                elif any(p.startswith(".") for p in parts):
                    reason = "a hidden file is never published"
                elif ignored is not None and ignored("/".join(parts)):
                    reason = "git ignores it, so it is never published"
                else:
                    candidate = os.path.join(root, *parts)
                    if os.path.lexists(candidate) and not _inside(candidate, root):
                        reason = "it leaves the project through a link"
                    else:
                        source = candidate
            if outside or not entry_name:
                plan.append(Evidence(verdict.gate, entry_name, text, name, None, None, None,
                                     said["outside"] if outside else said["not_copied"],
                                     "none", "" if outside else "no cache entry holds it"))
                continue
            shown = _free_name(name, taken)
            dest = posixpath.join(EVIDENCE_DIR, _component(verdict.gate),
                                  _component(entry_name), shown)
            on_site = os.path.join(root, "site", *dest.split("/"))
            if reason:
                pass
            elif source is not None and os.path.isdir(source):
                reason = "it is a directory"
            elif source is not None and os.path.isfile(source):
                size = os.path.getsize(source)
                if size > EVIDENCE_MAX_BYTES:
                    reason = (f"it is {_size_words(size)}, over the "
                              f"{_size_words(EVIDENCE_MAX_BYTES)} cap")
                else:
                    plan.append(Evidence(verdict.gate, entry_name, text, name, source, dest,
                                         dest, "", "copy"))
                    continue
            elif os.path.isfile(on_site):
                plan.append(Evidence(verdict.gate, entry_name, text, name, None, dest, dest, "",
                                     "keep"))
                continue
            else:
                reason = "it is not on this computer (run the check to write it)"
            plan.append(Evidence(verdict.gate, entry_name, text, name, None, None, None,
                                 said["not_copied"], "none", reason))
    return plan


def evidence_assets(plan: Iterable[Evidence]) -> dict[str, list[str]]:
    """``{gate: [href or "", ...]}``, aligned with each verdict's ``evidence``."""
    out: dict[str, list[str]] = {}
    for item in plan:
        out.setdefault(item.gate, []).append(item.href or "")
    return out


# --------------------------------------------------------------------------- #
# next steps (SPEC 28)
# --------------------------------------------------------------------------- #
#: Each cause -> (the settle text's key, the commands). `{tier_flag}` is
#: ` --tier N` when the claim's costliest covering evaluator is above
#: `nopekit check`'s default tier (0). A test holds the table exhaustive.
#: The pass a person records, as `claim physical` takes it: a pass on a
#: physical claim needs its evidence, and a judgment its authority's name.
#: What slipped through (review of phase 5): the page printed `nopekit claim
#: physical C5 pass`, which the command refuses ("a pass on C5 needs
#: --evidence <file>"), so the one command a reader copied failed.
_PHYSICAL_PASS = "nopekit claim physical {id} pass --evidence <file>"
_JUDGED_PASS = "nopekit claim physical {id} pass --authority {authority_arg} --evidence <file>"

_SETTLE: dict[str, tuple[str | None, tuple[str, ...]]] = {
    "failed": ("fix", ("nopekit why {id}", "nopekit check{tier_flag}")),
    "acceptance": ("fix", ("nopekit why {id}", "nopekit check{tier_flag}")),
    "physical-fail": ("built_fail", ("nopekit why {id}",)),
    "judged-fail": ("built_fail", ("nopekit why {id}",)),
    "contradiction": ("built_fail", ("nopekit why {id}",)),
    "errored": ("crash", ("nopekit gate show {gate}", "nopekit check{tier_flag}")),
    "prerequisite-errored": ("crash", ("nopekit gate show {gate}", "nopekit check{tier_flag}")),
    "skipped": ("tool", ("nopekit doctor", "nopekit check{tier_flag}")),
    "prerequisite": ("tool", ("nopekit doctor", "nopekit check{tier_flag}")),
    "unqualified": ("run", ("nopekit check{tier_flag}",)),
    "unrun": ("run", ("nopekit check{tier_flag}",)),
    "invalidated": ("run", ("nopekit check{tier_flag}",)),
    "outside-context": ("outside", ("nopekit why {id}",)),
    "fallback": ("outside", ("nopekit why {id}",)),
    "no-evaluator": ("find", ("nopekit gap --propose",)),
    "no-owner": ("owner", ("nopekit claim physical {id} assume",)),
    "owner-unattributed": ("owner", ("nopekit claim physical {id} assume",)),
    "no-reason": ("reason", ("nopekit why {id}",)),
    "owned": ("owned", ("nopekit gap",)),
    "no-article": ("article", ("nopekit export {milestone}", _PHYSICAL_PASS)),
    "article-moved": ("article", ("nopekit export {milestone}", _PHYSICAL_PASS)),
    "physical-pass": ("article", ("nopekit export {milestone}", _PHYSICAL_PASS)),
    "article-unjudged": ("article", ("nopekit export {milestone}", _PHYSICAL_PASS)),
    "no-authority": ("no_authority", ("nopekit why {id}",)),
    "authority-unattributed": ("judgment", (_JUDGED_PASS,)),
    "awaiting-judgment": ("judgment", (_JUDGED_PASS,)),
    "judgment-moved": ("judgment", (_JUDGED_PASS,)),
    "claim-moved": ("judgment", (_JUDGED_PASS,)),
    "checked": (None, ()),
    "on-article": (None, ()),
    "judged": (None, ()),
}


def settle(claim: Any, composed: Any, *, milestone: str | None = None,
           cover: Iterable[str] = (), tiers: Mapping[str, int] | None = None) -> dict:
    """What settles ``claim`` now, by its composition's cause: ``{text,
    commands}`` in the site's words. ``cover`` the claim's covering evaluators
    (`claims.effective_gates`), ``tiers`` each evaluator's tier; ``milestone``
    names the export a test on a built article needs. A Checked claim has
    none."""
    cause = str(getattr(composed.cause, "value", composed.cause))
    key, commands = _SETTLE[cause]
    if key is None:
        return {"text": "", "commands": []}
    cover = list(cover)
    tier = max((int((tiers or {}).get(g, 0) or 0) for g in cover), default=0)
    verdict = getattr(composed, "verdict", None)
    gate = (getattr(verdict, "gate", "") or (list(composed.cites)[0] if composed.cites else "")
            or (cover[0] if cover else ""))
    authority = str(getattr(claim, "authority", "") or "")
    values = {"id": claim.id, "gate": gate, "authority": authority or "its expert",
              "authority_arg": shlex.quote(authority) if authority else "<name>",
              "milestone": milestone or "", "tier_flag": f" --tier {tier}" if tier > 0 else ""}
    said = _site_words()["settle"]
    if key == "article" and not milestone:
        # No milestone names the claim, so no `export` builds its article: the
        # text says how to build one, and how to let `export` build it.
        key = "article_free"
    out = []
    for command in commands:
        if "{milestone}" in command and not milestone:
            continue
        if "{gate}" in command and not gate:
            continue
        out.append(command.format(**values))
    return {"text": said[key].format(**values), "commands": out}


# --------------------------------------------------------------------------- #
# stamps (SPEC 30)
# --------------------------------------------------------------------------- #
def _tok(cid: str, toks: Any, marks: Mapping[str, list[str]]) -> str:
    token = (getattr(toks, "claims", None) or {}).get(cid, "gap")
    found = marks.get(cid) or []
    return f"{token}:{','.join(found)}" if found else token


def subject_tokens(subject: str, boards: Iterable[Board], toks: Any,
                   named: Iterable[str] = ()) -> dict:
    """What a piece of prose is stamped against: a board's ``{claim id:
    token[:marks]}`` for its claims, and ``{"@<id>": token[:marks]}`` for each
    claim its text names that is on another board (``named``, `named_in`);
    for ``intro`` and ``next``, every claim's, with
    ``_readiness`` and ``_m:<id>`` for each milestone.

    A board's prose may name and link a claim on another board; that claim's
    token is in the stamp, so its flip flags the text. What slipped through
    (review of phase 5): the stamp held the board's own claims only, so
    "C1 fails" in prints.md read current after C1 passed."""
    marks = _marks(toks)
    claims = getattr(toks, "claims", None) or {}
    if subject in PROSE_SUBJECTS:
        out = {cid: _tok(cid, toks, marks) for cid in claims}
        out["_readiness"] = getattr(toks, "readiness", "")
        for mid, token in (getattr(toks, "milestones", None) or {}).items():
            out[f"_m:{mid}"] = token
        return out
    board = next((b for b in boards if b.id == subject), None)
    if board is None:
        raise KeyError(subject)
    out = {cid: _tok(cid, toks, marks) for cid in board.members}
    # A named claim off the board is keyed ``@<id>``, so moving a claim off the
    # board that its text still names moves the stamp too (a regroup).
    for cid in named:
        if cid in claims and cid not in board.members:
            out[f"@{cid}"] = _tok(cid, toks, marks)
    return out


def named_in(blocks: Iterable[Mapping[str, Any]]) -> list[str]:
    """The claim ids a piece of prose names (its ``claim`` runs, in text
    order, each once): what `subject_tokens` adds to a board's stamp."""
    out: list[str] = []
    for run in prose_logic.all_runs(blocks):
        cid = run.get("claim")
        if isinstance(cid, str) and cid not in out:
            out.append(cid)
    return out


def prose_named(body: str, claim_ids: Iterable[str]) -> list[str]:
    """`named_in` over a file's body, parsed as the build parses it."""
    blocks, _problems = prose_logic.parse_markdown(body, claims=claim_ids)
    return named_in(blocks)


def content_dir(root: str) -> str:
    return os.path.join(root, "site", "content")


def prose_files(root: str) -> list[tuple[str, str]]:
    """``(subject, path)`` for every ``site/content/*.md``, natural order."""
    folder = content_dir(root)
    if not os.path.isdir(folder):
        return []
    found = [(name[:-3], os.path.join(folder, name)) for name in os.listdir(folder)
             if name.endswith(".md") and os.path.isfile(os.path.join(folder, name))]
    return sorted(found, key=lambda pair: _natural(pair[0]))


def subjects(boards: Iterable[Board]) -> list[str]:
    return [b.id for b in boards] + list(PROSE_SUBJECTS)


def stamp_state(as_of: str | None, current: str) -> str:
    if not as_of:
        return "unstamped"
    return "current" if as_of == current else "stale"


def stamp_states(root: str, view: Any, toks: Any) -> list[dict]:
    """Each prose file's stamp now: ``{file, subject, stamp, as_of,
    current_as_of}``; a file that names no board, intro or next has subject
    None and stamp ``none``."""
    boards = boards_of(view)
    known = set(subjects(boards))
    out: list[dict] = []
    for subject, path in prose_files(root):
        rel = f"site/content/{subject}.md"
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            found = prose_logic.parse_front_matter(fh.read())
        if subject not in known:
            out.append({"file": rel, "subject": None, "stamp": "none", "as_of": found.as_of,
                        "current_as_of": None})
            continue
        named = prose_named(found.body, getattr(toks, "claims", None) or {})
        current = prose_logic.stamp_digest(subject, subject_tokens(subject, boards, toks,
                                                                   named=named))
        out.append({"file": rel, "subject": subject, "stamp": stamp_state(found.as_of, current),
                    "as_of": found.as_of, "current_as_of": current})
    return out


def content_digest(root: str) -> str:
    """A seal over ``{relpath: sha256}`` of every file under ``site/content/``,
    so a reader can say the page was built from other text."""
    folder = content_dir(root)
    files: dict[str, str] = {}
    if os.path.isdir(folder):
        for directory, dirnames, filenames in os.walk(folder):
            dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
            for name in sorted(filenames):
                if name.startswith("."):
                    continue
                path = os.path.join(directory, name)
                rel = os.path.relpath(path, folder).replace(os.sep, "/")
                with open(path, "rb") as fh:
                    files[rel] = hashlib.sha256(fh.read()).hexdigest()
    text = json.dumps(files, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(("nopekit-content-v1\n" + text).encode("utf-8")).hexdigest()


def seal(doc: Mapping[str, Any]) -> str:
    """sha256 of ``nopekit-page-v1`` and the canonical JSON of ``doc`` without
    ``self`` — the seal `map.json` and `page.json` carry, so a hand edit reads
    *edited by hand*."""
    body = {k: v for k, v in doc.items() if k != "self"}
    text = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)
    return hashlib.sha256(("nopekit-page-v1\n" + text).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# the bake
# --------------------------------------------------------------------------- #
def representation(views: Iterable[Mapping[str, Any]]) -> dict:
    """The outline's representation: the first ``model3d`` view in the page's
    order, else the first ``image`` or ``diagram``, else a notice saying what
    view to add."""
    views = list(views or ())
    for kinds in (("model3d",), ("image", "diagram")):
        for row in views:
            if str(row.get("kind") or "") in kinds:
                return {"view": str(row.get("id") or ""), "kind": str(row.get("kind")),
                        "title": str(row.get("title") or ""), "notice": ""}
    return {"view": None, "kind": None, "title": "",
            "notice": _site_words()["no_representation"]}


def _board_token(members: Iterable[str], composed: Mapping[str, Any]) -> tuple[str, bool]:
    status, errored, _worst = claim_logic.worst_of(list(members), composed)
    return ("errored" if errored else claim_logic.STATUS_KEY[status]), errored


def _tally(members: Iterable[str], composed: Mapping[str, Any]) -> list[dict]:
    return report_logic.count_bits({cid: composed[cid] for cid in members if cid in composed})


def bake_map(view: Any, lay: Layout, built: Any, toks: Any, composed: Mapping[str, Any], *,
             projection: Any, params: Iterable[Any] = (), registry: Any = None,
             payload: Mapping[str, Any] | None = None, name: str = "",
             records_digest: str = "", resolution_digest: str = "") -> dict:
    """``map.json`` (SPEC 29): nodes with kind, lane, order and column, lines
    with their stops, the values, the evaluators and the typed edges — tokens
    and words beside them, never a position."""
    said = _site_words()
    marks = _marks(toks)
    params = {p.name: p for p in params or ()}
    config = dict(projection.get("config") or {}) if isinstance(projection, Mapping) else {}
    derived = dict(projection.get("derived") or {}) if isinstance(projection, Mapping) else {}
    by_id = {c.id: c for c in getattr(view, "claims", None) or ()}
    floor = _floor_values(view, composed, registry)

    def spans(prefix: str) -> dict[str, list[int]]:
        out: dict[str, list[int]] = {}
        for line in lay.lines:
            for stop in line["stops"]:
                if stop.startswith(prefix):
                    out.setdefault(stop, []).append(line["order"])
        return out

    nodes: list[dict] = []
    requirement_ids = [f"requirement:{r.id}" for r in getattr(view, "requirements", None) or ()]
    req_cols = _columns(requirement_ids, spans("requirement:"))
    for i, requirement in enumerate(getattr(view, "requirements", None) or ()):
        nid = f"requirement:{requirement.id}"
        serving = [line["claim"] for line in lay.lines if nid in line["stops"]]
        token = toks.requirements.get(requirement.id, "gap")
        found = ["disagree"] if any(marks.get(c) for c in serving) or requirement.id in (
            toks.disagree.get("requirements") or ()) else []
        nodes.append({"id": nid, "kind": "requirement", "key": requirement.id,
                      "lane": "requirements", "order": i, "column": req_cols[nid],
                      "title": requirement.statement, "token": token, "word": _word(token),
                      "errored": token == "errored", "marks": found, "claims": serving})
    zone_ids = [f"zone:{z.id}" for z in lay.zones]
    zone_cols = _columns(zone_ids, spans("zone:"))
    for i, zone in enumerate(lay.zones):
        nid = f"zone:{zone.id}"
        ground = {"chosen": 0, "input": 0, "assumption": 0}
        assumptions: list[str] = []
        for member in zone.members:
            ground[_ground(built, member)] += 1
            for source in built.into(graph_logic.node_id("value", member), "sources"):
                kind, key = _split(source)
                if kind == "claim" and key not in assumptions:
                    assumptions.append(key)
        nodes.append({"id": nid, "kind": "zone", "key": zone.id, "lane": "zones", "order": i,
                      "column": zone_cols[nid], "title": zone.title, "line": zone.line,
                      "generated": zone.generated, "members": list(zone.members),
                      "ground": ground, "assumptions": sorted(assumptions, key=_natural),
                      "claims": [line["claim"] for line in lay.lines if nid in line["stops"]]})
    station_ids = [f"station:{s.id}" for s in lay.stations]
    station_cols = _columns(station_ids, spans("station:"))
    for i, station in enumerate(lay.stations):
        nid = f"station:{station.id}"
        text = ""
        if len(station.members) == 1:
            text = _value_text(station.members[0], config, derived, params)
        nodes.append({"id": nid, "kind": "station", "key": station.id, "lane": "stations",
                      "order": i, "column": station_cols[nid], "title": station.title,
                      "line": station.line, "generated": station.generated,
                      "members": list(station.members), "value_text": text,
                      "claims": [line["claim"] for line in lay.lines if nid in line["stops"]]})
    for i, board in enumerate(lay.boards):
        token, errored = _board_token(board.members, composed)
        nodes.append({"id": f"board:{board.id}", "kind": "board", "key": board.id,
                      "lane": "boards", "order": i, "title": board.title, "line": board.line,
                      "generated": board.generated, "token": token, "word": _word(token),
                      "errored": errored,
                      "marks": ["disagree"] if any(marks.get(c) for c in board.members) else [],
                      "claims": list(board.members), "tally": _tally(board.members, composed)})
    rows_in: dict[str, int] = {}
    for line in lay.lines:
        cid = line["claim"]
        claim = by_id[cid]
        token = toks.claims[cid]
        rows_in[line["board"]] = rows_in.get(line["board"], -1) + 1
        nodes.append({"id": f"claim:{cid}", "kind": "claim", "key": cid, "lane": "boards",
                      "board": line["board"], "order": line["order"],
                      "row": rows_in[line["board"]],
                      "severity": claim_logic.SEVERITY_ORDER.index(token),
                      "title": claim.statement,
                      "claim_kind": str(getattr(claim.kind, "value", claim.kind)),
                      "critical": bool(claim.critical), "token": token, "word": _word(token),
                      "errored": token == "errored", "marks": list(marks.get(cid) or ()),
                      "value_text": next((v["value_text"] for v in floor.get(cid, ())
                                          if v["binding"]), "")})

    lines = [{"claim": line["claim"], "order": line["order"],
              "token": toks.claims[line["claim"]],
              "errored": toks.claims[line["claim"]] == "errored",
              "marks": list(marks.get(line["claim"]) or ()), "stops": list(line["stops"]),
              "via": {k: list(v) for k, v in line["via"].items()}, "values": list(line["values"]),
              "reads_all": line["reads_all"]} for line in lay.lines]

    names = set(lay.zone_of) | set(lay.station_of)
    for line in lay.lines:
        names.update(line["values"])
    touched = {n for line in lay.lines for n in line["values"]}
    values: dict[str, dict] = {}
    for vname in sorted(names, key=_natural):
        node = built.node(graph_logic.node_id("value", vname))
        values[vname] = {
            "role": (node.attrs.get("role") if node is not None else "absent"),
            "value_text": _value_text(vname, config, derived, params),
            "units": str(getattr(params.get(vname), "units", "") or ""),
            "zone": lay.zone_of.get(vname), "station": lay.station_of.get(vname),
            "ground": _ground(built, vname), "read": vname in touched}

    rows = {r.get("gate"): r for r in (payload or {}).get("verdicts") or ()}
    evaluators: dict[str, dict] = {}
    for gid in sorted(toks.evaluators, key=_natural):
        node = built.node(graph_logic.node_id("evaluator", gid))
        attrs = dict(node.attrs) if node is not None else {}
        row = rows.get(gid) or {}
        outcome = str(row.get("status") or "unrun")
        evaluators[gid] = {
            "basis": str(attrs.get("basis") or "undeclared"), "pack": str(attrs.get("pack") or ""),
            "tier": int(attrs.get("tier") or 0), "registered": bool(attrs.get("registered", True)),
            "outcome": outcome, "outcome_word": _outcome_word(outcome),
            "current": bool(toks.evaluators[gid].get("current")),
            "claims": [_split(t)[1] for t in built.out(graph_logic.node_id("evaluator", gid),
                                                       "settles")]}
    edges = {t: v for t, v in built.to_dict()["edges"].items() if t in MAP_EDGE_TYPES}
    legend = []
    counted: dict[str, int] = {}
    for token in toks.claims.values():
        counted[token] = counted.get(token, 0) + 1
    for token in claim_logic.SEVERITY_ORDER:
        if counted.get(token):
            legend.append({"token": token, "n": counted[token]})
    lanes = ["requirements"] if requirement_ids else []
    if lay.zones:
        lanes.append("zones")
    if lay.stations:
        lanes.append("stations")
    lanes.append("boards")
    columns = {"requirements": (max(req_cols.values()) + 1) if req_cols else 0,
               "zones": (max(zone_cols.values()) + 1) if zone_cols else 0,
               "stations": (max(station_cols.values()) + 1) if station_cols else 0}
    doc = {"schema": SCHEMA, "generated": said["generated"],
           "meta": {"name": name, "records_digest": records_digest,
                    "resolution_digest": resolution_digest},
           "trace": built.trace, "lanes": lanes, "columns": columns, "legend": legend,
           "nodes": nodes, "lines": lines, "values": values, "evaluators": evaluators,
           "edges": edges, "unread": list(lay.unread)}
    return doc


def _ground(built: Any, name: str) -> str:
    sources = built.into(graph_logic.node_id("value", name), "sources")
    kinds = {_split(s)[0] for s in sources}
    return "assumption" if "claim" in kinds else "input" if "input" in kinds else "chosen"


def _value_text(name: str, config: Mapping, derived: Mapping, params: Mapping) -> str:
    if name in config:
        value = config[name]
    elif name in derived:
        value = derived[name]
    else:
        return ""
    if isinstance(value, (dict, list, tuple)) or value is None:
        return ""
    units = str(getattr(params.get(name), "units", "") or "")
    return f"{_num(value)} {units}".strip()


def _floor_values(view: Any, composed: Mapping[str, Any], registry: Any) -> dict:
    """``{claim id: [value row, ...]}`` — measured against limit for every
    covering verdict with a finite value, the binding one marked."""
    out: dict[str, list[dict]] = {}
    for claim in getattr(view, "claims", None) or ():
        found = composed.get(claim.id)
        if found is None:
            continue
        verdicts = report_logic._claim_verdicts(view, claim)
        compared = set(claim_logic.compared_gates(claim, view.verdicts))
        value = claim_logic.claim_value(claim, found, view.verdicts)
        binding_gate = getattr(value, "gate", None)
        if binding_gate is None and found.status is not ClaimStatus.PASS:
            own = getattr(found, "verdict", None)
            if own is not None and own.gate in compared:
                binding_gate = own.gate
        limit_text = report_logic.limit_words(claim.acceptance)
        acc = claim.acceptance
        rows: list[dict] = []
        for verdict in verdicts:
            measured = verdict.measured
            if isinstance(measured, bool) or not isinstance(measured, (int, float)) \
                    or not math.isfinite(measured):
                continue
            margin = claim_logic.margin(verdict).fraction
            margin = None if margin is None else float(f"{margin:.6g}")
            comparator = getattr(verdict, "comparator", "") or ""
            # The claim's limit beside a value compared with it (S-35: never
            # the verdict's), with the margin against that same limit; a value
            # of another quantity beside its own limit and its own margin.
            # `margin` stays the verdict's (`claims.margin`, beside its own
            # `limit` and `comparator`); only the words pair the claim's limit
            # with the claim's margin. What slipped through (review of phase
            # 5): the words put the claim's limit beside the evaluator's own
            # margin, so C3 tightened to 0.1 MPa read "0.195 MPa against a
            # limit of 0.1 MPa, 99% inside the limit" under Failing.
            if verdict.gate in compared:
                shown_limit = limit_text
                held = claim_logic.cross_check(claim, verdict).state == "holds"
                shown_margin = claim_logic._margin_of(
                    measured, getattr(acc, "limit", None), _comparator(acc), held).fraction
                shown_margin = (None if shown_margin is None
                                else float(f"{shown_margin:.6g}"))
            else:
                shown_limit = (f"{_num(verdict.limit)} {verdict.units or ''}".strip()
                               if isinstance(verdict.limit, (int, float))
                               and not isinstance(verdict.limit, bool) else "")
                shown_margin = margin
            rows.append({"gate": verdict.gate, "measured": measured,
                         "units": str(verdict.units or ""),
                         "limit": verdict.limit if isinstance(verdict.limit, (int, float))
                         and not isinstance(verdict.limit, bool) else None,
                         "limit_hi": getattr(acc, "limit_hi", None)
                         if _comparator(acc) == "between" else None,
                         "comparator": str(getattr(comparator, "value", comparator)),
                         "margin": margin, "compared": verdict.gate in compared,
                         "binding": verdict.gate == binding_gate,
                         "value_text": value_text(measured, str(verdict.units or ""),
                                                  shown_limit, shown_margin)})
        token = token_of(found)
        counted = _counted_result(claim)
        if token == "checked" and counted is not None and isinstance(
                getattr(counted, "measured", None), (int, float)) \
                and not isinstance(counted.measured, bool) \
                and str(getattr(counted, "units", "") or "") == str(
                    getattr(acc, "units", "") or ""):
            margin = claim_logic._margin_of(counted.measured, getattr(acc, "limit", None),
                                            _comparator(acc), True).fraction
            margin = None if margin is None else float(f"{margin:.6g}")
            rows.append({"gate": None, "source": "article", "measured": counted.measured,
                         "units": str(counted.units or ""),
                         "limit": getattr(acc, "limit", None),
                         "limit_hi": None, "comparator": _comparator(acc),
                         "margin": margin, "compared": True, "binding": not any(
                             r["binding"] for r in rows),
                         "value_text": value_text(counted.measured, str(counted.units or ""),
                                                  limit_text, margin)})
        out[claim.id] = rows
    return out


def _comparator(acceptance: Any) -> str:
    comparator = getattr(acceptance, "comparator", None)
    return str(getattr(comparator, "value", comparator) or "")


def _counted_result(claim: Any) -> Any:
    standing = getattr(claim, "standing", None)
    index = getattr(standing, "counted", None)
    results = list(getattr(claim, "results", ()) or ())
    if index is None or not isinstance(index, int) or not (0 <= index < len(results)):
        return None
    return results[index]


def _step(claim: Any, found: Any, *, milestone: str | None, cover: Mapping[str, list],
          tiers: Mapping[str, int], marks: Mapping[str, list[str]] | None = None) -> dict:
    token = token_of(found)
    done = settle(claim, found, milestone=milestone, cover=cover.get(claim.id) or (),
                  tiers=tiers)
    return {"claim": claim.id, "token": token, "word": _word(token),
            "errored": token == "errored", "marks": list((marks or {}).get(claim.id) or ()),
            "statement": claim.statement,
            "how": str(getattr(claim, "note", "") or ""), "text": done["text"],
            "commands": done["commands"]}


def bake_page(root: str, view: Any, lay: Layout, built: Any, toks: Any,
              composed: Mapping[str, Any], *, registry: Any = None,
              payload: Mapping[str, Any] | None = None, plan: Iterable[Evidence] = (),
              records_digest: str = "", resolution_digest: str = "") -> dict:
    """``page.json`` (SPEC 28, 30): the outline's data, every claim's floor
    row once (the floor and the drawer read it), the next steps and the
    words. The prose objects are filled by `bake_prose`."""
    said = _site_words()
    payload = payload or {}
    meta = getattr(view, "meta", None)
    marks = _marks(toks)
    cover = claim_logic.effective_gates(view, registry)
    tiers = {spec.id: int(spec.tier) for spec in report_logic._specs(registry)}
    floor = _floor_values(view, composed, registry)
    vrows = {r.get("gate"): r for r in payload.get("verdicts") or ()}
    plan_by_gate: dict[str, list[Evidence]] = {}
    for item in plan:
        plan_by_gate.setdefault(item.gate, []).append(item)
    bases = report_logic._bases(registry)
    by_id = {c.id: c for c in getattr(view, "claims", None) or ()}
    first_milestone = sorted((m for m in getattr(view, "milestones", None) or ()),
                             key=lambda m: _natural(m.id))

    claims_out: dict[str, dict] = {}
    for line in lay.lines:
        cid = line["claim"]
        claim = by_id[cid]
        found = composed[cid]
        token = toks.claims[cid]
        try:
            by = str(getattr(claim, "terminal", "") or "") or claim_logic.terminal_of(claim)
        except Exception:                             # noqa: BLE001 - shown as declared
            by = str(getattr(claim, "terminal", "") or "")
        by = by or "automated"
        evaluators = []
        for gid in sorted(cover.get(cid) or (),
                          key=lambda g: (int((vrows.get(g) or {}).get("order", 10 ** 6)),
                                         _natural(g))):
            row = vrows.get(gid) or {}
            outcome = str(row.get("status") or "unrun")
            basis = str(row.get("basis") or bases.get(gid, "undeclared"))
            evaluators.append({
                "id": gid, "basis": basis,
                "basis_word": said["basis"].get(basis, said["basis"]["undeclared"]),
                "outcome": outcome, "outcome_word": _outcome_word(outcome),
                "order": int(row.get("order", len(vrows))) if row else len(vrows),
                "current": bool(row.get("fresh")) if row else False,
                "stale_reason": str(row.get("stale_reason") or ""),
                "detail": str(row.get("detail") or ""),
                "evidence": [{"name": item.name, "source": item.path, "href": item.href,
                              "missing": item.missing} for item in plan_by_gate.get(gid, ())]})
        physical = None
        counted = getattr(claim, "physical_result", None)
        if counted is not None:
            facts = report_logic.result_facts(claim, counted)
            physical = {"counts": bool(facts["counts"]), "why": facts["why"],
                        "recorded": facts["recorded"], "heading": facts["heading"]}
        claims_out[cid] = {
            "id": cid, "statement": claim.statement,
            "claim_kind": str(getattr(claim.kind, "value", claim.kind)),
            "kind_word": said["kinds"].get(str(getattr(claim.kind, "value", claim.kind)), ""),
            "critical": bool(claim.critical), "board": line["board"],
            "requirements": list(getattr(claim, "requirements", None) or ()),
            "token": token, "word": _word(token), "errored": token == "errored",
            "marks": list(marks.get(cid) or ()), "hint": said["hint"][token],
            "cause": str(found.cause.value), "cause_text": said["cause"][str(found.cause.value)],
            "mechanism": {"by": by, "by_word": said["by"].get(by, ""),
                          "how": str(getattr(claim, "note", "") or ""),
                          "evaluators": list(getattr(claim, "evaluators", None) or ())},
            "acceptance": claim.acceptance.render() if claim.kind == ClaimKind.MEASURABLE
            or getattr(claim.acceptance, "quantity", "") else "",
            "limit_text": report_logic.limit_words(claim.acceptance),
            "values": floor.get(cid, []),
            "evaluators": evaluators, "physical": physical,
            "rests_on": list(built.rests_on(cid)),
            "resolves": list(getattr(claim, "resolves", None) or ()),
            "resolved_by": [_split(s)[1] for s in built.into(graph_logic.node_id("claim", cid),
                                                              "resolves")],
            "settle": settle(claim, found, milestone=next(
                (m.id for m in first_milestone if cid in (getattr(m, "requires", None) or ())),
                None), cover=cover.get(cid) or (), tiers=tiers)}

    sections = []
    for board in lay.boards:
        token, errored = _board_token(board.members, composed)
        sections.append({"board": board.id, "title": board.title, "line": board.line,
                         "generated": board.generated, "token": token, "word": _word(token),
                         "errored": errored,
                         "marks": ["disagree"] if any(marks.get(c) for c in board.members)
                         else [],
                         "tally": _tally(board.members, composed),
                         "claims": list(board.members), "prose": None})

    unresolved = claim_logic.unresolved(view, composed)
    stale = bool((payload.get("meta") or {}).get("stale"))
    verdict = {"token": toks.readiness, "ready": bool(unresolved.ready),
               "sentence": report_logic._verdict_sentence(view, composed, registry, stale=False,
                                                          markdown=False, register="site"),
               "limits": report_logic.limits_line(view, register="site"),
               "tally": report_logic.count_bits(composed), "stale": stale,
               "notice": said["notices"]["invalidated"] if stale else ""}

    milestones = sorted(getattr(view, "milestones", None) or (), key=lambda m: _natural(m.id))
    groups = []
    seen_next = False
    required_anywhere: set[str] = set()
    for milestone in milestones:
        found = claim_logic.unresolved(view, composed, milestone)
        required_anywhere.update(getattr(milestone, "requires", None) or ())
        is_next = (not found.ready) and not seen_next
        seen_next = seen_next or is_next
        token = toks.milestones.get(milestone.id, "ready" if found.ready else "not-ready")
        groups.append({
            "id": milestone.id, "description": str(getattr(milestone, "description", "") or ""),
            "token": token, "ready": bool(found.ready),
            "word": said["ready_word" if found.ready else "not_ready_word"], "next": is_next,
            "sentence": report_logic._verdict_sentence(view, composed, registry, stale=False,
                                                       markdown=False, milestone=milestone,
                                                       register="site"),
            "steps": [_step(c, composed[c.id], milestone=milestone.id, cover=cover, tiers=tiers,
                            marks=marks)
                      for c in report_logic.in_severity(view, composed, found.unresolved)],
            "missing": [{"claim": cid, "text": said["settle"]["missing"].format(
                milestone=milestone.id, id=cid)} for cid in found.missing]})
    project = None
    if not milestones:
        project = {"id": None, "description": "", "token": toks.readiness,
                   "ready": bool(unresolved.ready),
                   "word": said["ready_word" if unresolved.ready else "not_ready_word"],
                   "next": not unresolved.ready, "sentence": verdict["sentence"],
                   "steps": [_step(c, composed[c.id], milestone=None, cover=cover, tiers=tiers,
                                   marks=marks)
                             for c in report_logic.in_severity(view, composed,
                                                               unresolved.unresolved)],
                   "missing": []}
    resolved_tokens = ("checked",)
    if milestones:
        open_claims = [c for c in getattr(view, "claims", None) or ()
                       if c.id not in required_anywhere
                       and toks.claims.get(c.id) not in resolved_tokens]
    else:
        open_claims = [c for c in getattr(view, "claims", None) or ()
                       if not c.critical and toks.claims.get(c.id) not in resolved_tokens]
    open_steps = [_step(c, composed[c.id], milestone=None, cover=cover, tiers=tiers,
                        marks=marks)
                  for c in report_logic.in_severity(view, composed, open_claims)]
    rebuild = []
    for found in claim_logic.rebuild(view):
        from .verdicts import _stale_text
        rebuild.append({"article": str(found.article)[:12], "claims": list(found.claims),
                        "text": said["rebuild"].format(
                            article=str(found.article)[:12], claims=", ".join(found.claims),
                            moves=_stale_text(found.moved) if found.moved else "the design")})

    summary = str(getattr(meta, "summary", "") or "")
    return {
        "schema": SCHEMA, "outline": OUTLINE, "generated": said["generated"],
        "meta": {"name": str(getattr(meta, "name", "") or ""), "summary": summary,
                 "revision": str(getattr(meta, "revision", "") or ""),
                 "records_digest": records_digest, "resolution_digest": resolution_digest,
                 "content_digest": content_digest(root)},
        "representation": representation(payload.get("views") or ()),
        "verdict": verdict,
        "intro": None,
        "description": {"summary": summary, "notice": said["notices"]["no_intro"]},
        "sections": sections,
        "claims": claims_out,
        "next": {"milestones": groups, "project": project, "open": open_steps,
                 "rebuild": rebuild, "prose": None},
        "words": words_block(),
        "problems": [],
    }


def bake_prose(root: str, page_doc: dict, lay: Layout, toks: Any, pool: Any) -> list[dict]:
    """Fill ``page_doc``'s prose objects from ``site/content/`` and return one
    summary row per file: ``{file, subject, stamp, unmatched, register,
    problems}``. A file for no subject goes to ``page.problems``."""
    said = _site_words()
    known = subjects(lay.boards)
    claim_ids = list(page_doc.get("claims") or ())
    sections = {s["board"]: s for s in page_doc.get("sections") or ()}
    rows: list[dict] = []

    def exists(path: str) -> bool:
        return os.path.isfile(os.path.join(root, "site", *path.split("/")))

    for subject, path in prose_files(root):
        rel = f"content/{subject}.md"
        if subject not in known:
            problem = (f"site/content/{subject}.md names no board: it is not on the page "
                       f"(boards: {', '.join(b.id for b in lay.boards) or 'none'}; and intro, "
                       f"next)")
            page_doc["problems"].append(problem)
            rows.append({"file": f"site/{rel}", "subject": None, "stamp": "none",
                         "unmatched": [], "register": [], "problems": [problem]})
            continue
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            text = fh.read()
        front = prose_logic.parse_front_matter(text)
        blocks, problems = prose_logic.parse_markdown(front.body, exists=exists,
                                                      claims=claim_ids)
        blocks, unmatched = prose_logic.scan_numbers(blocks, pool)
        register: list[str] = []
        for chunk in prose_logic.blocks_text(blocks):
            register += prose_logic.register_problems(chunk)
            register += [f"long sentence: {s}" for s in prose_logic.long_sentences(chunk)]
        current = prose_logic.stamp_digest(subject, subject_tokens(
            subject, lay.boards, toks, named=named_in(blocks)))
        state = stamp_state(front.as_of, current)
        notice = ("" if state == "current" else said["notices"]["prose_stale"]
                  if state == "stale" else said["notices"]["prose_unstamped"])
        obj = {"file": rel, "subject": subject, "as_of": front.as_of, "current_as_of": current,
               "stamp": state, "notice": notice, "blocks": blocks, "unmatched": unmatched,
               "register": register, "problems": list(front.problems) + problems}
        if subject == "intro":
            page_doc["intro"] = obj
            page_doc["description"]["notice"] = ""
        elif subject == "next":
            page_doc["next"]["prose"] = obj
        else:
            sections[subject]["prose"] = obj
        rows.append({"file": f"site/{rel}", "subject": subject, "stamp": state,
                     "unmatched": unmatched, "register": register,
                     "problems": list(front.problems) + problems})
    if page_doc.get("description", {}).get("summary") and page_doc.get("intro") is None:
        page_doc["description"]["notice"] = ""
    return rows


# --------------------------------------------------------------------------- #
# invariant 14's checker
# --------------------------------------------------------------------------- #
def status_problems(map_doc: Mapping[str, Any] | None, page_doc: Mapping[str, Any] | None,
                    view: Any, composed: Mapping[str, Any], toks: Any, *,
                    prose_as_of: Mapping[str, str | None] | None = None,
                    pool: Any = None) -> list[str]:
    """Every place ``map_doc`` or ``page_doc`` says a status, a *ready*, a word
    or a mark the resolution does not: a claim's token on the map, a line, a
    floor row, a board's section or a next step against `graph.tokens`; a
    board's against `claims.worst_of` over its claims; a requirement's against
    `graph.tokens`; the verdict, the project's and each milestone's *ready*
    and token against `claims.unresolved`; every baked status word against its
    token's; a ``disagree`` mark against `graph.tokens`; a compared value's
    words that put it inside a limit its claim's condition rejects, or past one
    it meets; and each baked piece of prose whose stamp state or notice is not
    what the digest of its claims now says. With ``prose_as_of`` (``{subject:
    as_of}``, read from ``site/content/`` now) a baked ``as_of`` must equal the
    file's; with ``pool`` (`prose.number_pool` over the baked documents, as the
    build pools them) every number run's ``match`` must be the scan's. The
    build refuses a page this names; `site status`, `status` and `doctor` read
    a hand-edited page with it (invariant 14).

    What slipped through before the words, the prose and the values were held
    here (review of phase 5): a milestone baked ``ready`` in green beside
    ``ready: false``, a failing board's chip worded *checked*, and a resealed
    page that showed stale prose as current, all read current."""
    problems: list[str] = []
    want = dict(getattr(toks, "claims", None) or {})
    disagree = set((getattr(toks, "disagree", None) or {}).get("claims") or ())
    said_site = _site_words()

    def check(where: str, said: Any, expected: Any) -> None:
        if said != expected:
            problems.append(f"{where} reads {said}, the resolution says {expected}")

    def word_of(where: str, row: Mapping[str, Any]) -> None:
        token = row.get("token")
        if "word" in row and isinstance(token, str):
            try:
                expected = _word(token)
            except StopIteration:
                problems.append(f"{where} has the token {token}, which is no status")
                return
            check(f"{where} word", row.get("word"), expected)

    for node in (map_doc or {}).get("nodes") or ():
        kind = node.get("kind")
        key = str(node.get("key"))
        if kind == "claim":
            check(f"claim:{key}", node.get("token"), want.get(key))
            check(f"claim:{key} disagree", "disagree" in (node.get("marks") or ()),
                  key in disagree)
        elif kind == "requirement":
            check(f"requirement:{key}", node.get("token"),
                  (getattr(toks, "requirements", None) or {}).get(key))
        elif kind == "board":
            token, _errored = _board_token(node.get("claims") or (), composed)
            check(f"board:{key}", node.get("token"), token)
        if kind in ("claim", "requirement", "board"):
            word_of(f"{kind}:{key}", node)
    for line in (map_doc or {}).get("lines") or ():
        check(f"line {line.get('claim')}", line.get("token"), want.get(str(line.get("claim"))))
        word_of(f"line {line.get('claim')}", line)
    if page_doc is None:
        return problems
    by_id = {c.id: c for c in getattr(view, "claims", None) or ()}
    inside = said_site["margin_inside"].split("}", 1)[-1].strip()
    past = said_site["margin_past"].split("}", 1)[-1].strip()
    def mark_of(where: str, row: Mapping[str, Any], expected: bool) -> None:
        if "marks" in row:
            check(f"{where} disagree", "disagree" in (row.get("marks") or ()), expected)

    for cid, row in (page_doc.get("claims") or {}).items():
        check(f"page claim {cid}", row.get("token"), want.get(cid))
        word_of(f"page claim {cid}", row)
        mark_of(f"page claim {cid}", row, cid in disagree)
        claim = by_id.get(cid)
        for value in row.get("values") or ():
            if claim is None or not value.get("compared") or value.get("gate") is None:
                continue
            verdict = next((v for v in claim_logic.covering_verdicts(claim, view.verdicts)
                            if v.gate == value.get("gate")), None)
            if verdict is None:
                continue
            state = claim_logic.cross_check(claim, verdict).state
            text = str(value.get("value_text") or "")
            if state == "fails" and inside in text:
                problems.append(f"page claim {cid} {verdict.gate} says {inside!r}, and the "
                                f"claim's condition rejects its value")
            elif state == "holds" and past in text:
                problems.append(f"page claim {cid} {verdict.gate} says {past!r}, and the "
                                f"claim's condition accepts its value")
    for section in page_doc.get("sections") or ():
        token, _errored = _board_token(section.get("claims") or (), composed)
        check(f"section {section.get('board')}", section.get("token"), token)
        word_of(f"section {section.get('board')}", section)
        mark_of(f"section {section.get('board')}", section,
                any(c in disagree for c in section.get("claims") or ()))
    unresolved = claim_logic.unresolved(view, composed)
    verdict = page_doc.get("verdict") or {}
    check("verdict ready", verdict.get("ready"), bool(unresolved.ready))
    check("verdict token", verdict.get("token"), getattr(toks, "readiness", None))
    nxt = page_doc.get("next") or {}

    def ready_group(where: str, group: Mapping[str, Any], ready: bool, token: Any) -> None:
        check(f"{where} ready", group.get("ready"), ready)
        check(f"{where} token", group.get("token"), token)
        check(f"{where} word", group.get("word"),
              said_site["ready_word" if ready else "not_ready_word"])

    milestones = {m.id: m for m in getattr(view, "milestones", None) or ()}
    for group in nxt.get("milestones") or ():
        milestone = milestones.get(group.get("id"))
        if milestone is None:
            problems.append(f"milestone {group.get('id')} is on the page and in no record")
            continue
        found = claim_logic.unresolved(view, composed, milestone)
        ready_group(f"milestone {milestone.id}", group, bool(found.ready),
                    (getattr(toks, "milestones", None) or {}).get(
                        milestone.id, "ready" if found.ready else "not-ready"))
        check(f"milestone {milestone.id} steps", [s.get("claim") for s in group.get("steps")
                                                  or ()],
              [c.id for c in report_logic.in_severity(view, composed, found.unresolved)])
    if nxt.get("project"):
        ready_group("project", nxt["project"], bool(unresolved.ready),
                    getattr(toks, "readiness", None))
    groups = list(nxt.get("milestones") or ()) + ([nxt["project"]] if nxt.get("project") else [])
    for group in groups:
        for step in group.get("steps") or ():
            check(f"step {step.get('claim')}", step.get("token"), want.get(str(step.get("claim"))))
            word_of(f"step {step.get('claim')}", step)
            mark_of(f"step {step.get('claim')}", step, str(step.get("claim")) in disagree)
    for step in nxt.get("open") or ():
        check(f"open step {step.get('claim')}", step.get("token"),
              want.get(str(step.get("claim"))))
        word_of(f"open step {step.get('claim')}", step)
        mark_of(f"open step {step.get('claim')}", step, str(step.get("claim")) in disagree)
    problems += _prose_problems(page_doc, view, toks, prose_as_of=prose_as_of, pool=pool)
    return problems


def _prose_pieces(page_doc: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    pieces = [(str(s.get("board")), s["prose"]) for s in page_doc.get("sections") or ()
              if s.get("prose")]
    if page_doc.get("intro"):
        pieces.append(("intro", page_doc["intro"]))
    if (page_doc.get("next") or {}).get("prose"):
        pieces.append(("next", page_doc["next"]["prose"]))
    return pieces


def _prose_problems(page_doc: Mapping[str, Any], view: Any, toks: Any, *,
                    prose_as_of: Mapping[str, str | None] | None, pool: Any) -> list[str]:
    """Invariant 14's second half on a baked page: each piece's stamp and
    notice against the digest of what it is about now (its board's claims and
    the claims it names), its ``as_of`` against the file's, and each number
    run's ``match`` against the scan."""
    said = _site_words()["notices"]
    boards = boards_of(view)
    known = set(subjects(boards))
    out: list[str] = []
    for subject, piece in _prose_pieces(page_doc):
        if subject not in known:
            out.append(f"prose {subject} is on the page and names no board")
            continue
        blocks = piece.get("blocks") or []
        as_of = piece.get("as_of")
        if prose_as_of is not None and subject in prose_as_of \
                and prose_as_of[subject] != as_of:
            out.append(f"prose {subject} was baked at as_of {as_of}, and the file says "
                       f"{prose_as_of[subject]}")
        current = prose_logic.stamp_digest(subject, subject_tokens(
            subject, boards, toks, named=named_in(blocks)))
        state = stamp_state(as_of, current)
        notice = ("" if state == "current" else said["prose_stale"] if state == "stale"
                  else said["prose_unstamped"])
        if piece.get("stamp") != state:
            out.append(f"prose {subject} reads {piece.get('stamp')}, its digest says {state}")
        if piece.get("notice") != notice:
            out.append(f"prose {subject} shows the notice {piece.get('notice')!r} for a "
                       f"{state} piece")
        if pool is not None:
            for run in prose_logic.number_runs(blocks):
                found = prose_logic.run_matches(run, pool)
                if bool(run.get("match")) != found:
                    out.append(f"prose {subject}: {run.get('t')} reads match "
                               f"{run.get('match')}, the scan says {found}")
    return out


__all__ = [
    "OUTLINE", "SCHEMA", "LANES", "MAP_EDGE_TYPES", "OTHER", "IMPLICIT_STATIONS_WARN",
    "EVIDENCE_MAX_BYTES", "EVIDENCE_DIR", "PROSE_SUBJECTS", "WORD_KEYS", "RECORD_KEYS",
    "Board", "Zone", "Station", "Layout", "Evidence",
    "token_of", "boards_of", "layout", "value_text", "words_block", "evidence_plan",
    "evidence_assets", "settle", "subject_tokens", "named_in", "prose_named", "prose_files",
    "subjects", "stamp_state",
    "stamp_states", "content_digest", "seal", "representation", "bake_map", "bake_page",
    "bake_prose", "status_problems",
]
