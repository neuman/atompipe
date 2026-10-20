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
from . import derivation as trace_logic
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

#: ``map.json``'s own schema (architecture phase 3b): zones and requirements
#: are no longer stops, stations carry a layer, feeds and taps are new.
#: ``page.json`` stays at `SCHEMA`.
MAP_SCHEMA = 2

#: The map's lanes, left to right: what was asked, the choices, the values
#: several lines share, the claims on their boards (SPEC 29).
LANES: tuple[str, ...] = ("requirements", "zones", "stations", "boards")

#: The graph's edge types the map carries. `requires` (a milestone's claims) is
#: next steps' and `decides` the technical record's: neither is drawn. Nor are
#: `derives` and `after` (architecture phase 3b): the feeds and the station
#: layers carry them, and on PETGasus about 2,000 derives edges would sit in
#: map.json for nothing the renderer reads.
MAP_EDGE_TYPES: tuple[str, ...] = tuple(t for t in graph_logic.EDGE_TYPES
                                        if t not in ("requires", "decides", "derives",
                                                     "after"))

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

#: The prose subjects that are not boards: the description, the next steps and,
#: from the two pages, the marketing page's story. Every list of them (the
#: stamp's argument, the reserved group ids, the build's messages, the pool's
#: bare page) derives from this tuple. `story` is stamped against what `intro`
#: is (every claim's token, the readiness, each milestone): a story names the
#: whole product. *Rejected:* a story stamped against nothing (it is the one
#: piece of the site written to persuade, so the flag matters most there); a
#: story per board (the boards' own prose is that).
PROSE_SUBJECTS = ("intro", "next", "story")

# Every prose subject is a reserved group id (`store.RESERVED_GROUP_IDS`), or a
# board of that name would take its file. Held here at import, because `store`
# cannot import this module: a subject added to one tuple and not the other
# fails every command at once, never one project later.
if not set(PROSE_SUBJECTS) <= set(store.RESERVED_GROUP_IDS):      # pragma: no cover
    raise RuntimeError(f"page.PROSE_SUBJECTS {PROSE_SUBJECTS} are not all in "
                       f"store.RESERVED_GROUP_IDS")

#: How many decisions the marketing page shows in full, newest first; the rest
#: sit in one collapsed block. Only a decision that changed a claim or a value
#: is shown (`featured`). Provenance: the reference product page shows four to
#: six choices before the evidence, and PETGasus has 14 decisions, most of them
#: long engineering text: all 14 would push the evidence off the page.
#: *Rejected:* every decision (a wall of text); the first five in record order
#: (a story reads the latest choice first, and record order is the file names').
DECISIONS_SHOWN = 5

#: Keys whose string values are words the build writes (scanned for the site's
#: register, `test_style`) and keys whose strings are record text, ids, tokens,
#: paths or the CLI's shared producers (exempt). Every string-valued key of
#: `page.json` and `map.json` is in exactly one (`test_style.EveryBakedKeyIsClassified`).
#: A recorded result's `why`, `recorded` and `heading` are words (follow-up
#: after phase 3b): they were the CLI's `result_facts`, exempt, and the drawer
#: said "a new article is needed, not a rerun" under the scan's nose.
#: The two pages added words (`headline`, `type_word`, `returns_word`,
#: `lost_label`, `decisions_more`) and record keys (a decision's `when`,
#: `params`, a rejection's `value`, `reason`, `input`, `returns_text`, the
#: `preference` and `returns` tokens, a value's `rationale`, `lost`,
#: `decisions`, `rejected`, `alternates`). A rejection's reason is `reason`,
#: never `why`: `why` is a word key, and the bracket's PLA reason holds an
#: em-dash the person wrote, which the scan would read as the build's.
WORD_KEYS = frozenset({
    "generated", "notice", "sentence", "limits", "label", "word", "value_text", "hint",
    "cause_text", "text", "kind_word", "by_word", "basis_word", "outcome_word", "missing",
    "term", "why", "recorded", "heading",
    "headline", "type_word", "returns_word", "lost_label", "decisions_more"})
RECORD_KEYS = frozenset({
    "schema", "name", "summary", "revision", "records_digest", "resolution_digest",
    "content_digest", "trace", "view", "kind", "title", "token", "id", "key", "lane",
    "line", "board", "claim_kind", "role", "units", "zone", "station", "ground", "basis",
    "pack", "outcome", "self", "reads_all", "claim", "status", "file", "subject", "as_of",
    "current_as_of", "stamp", "statement", "cause", "by", "how", "acceptance",
    "limit_text", "gate", "comparator", "source", "stale_reason", "detail", "href",
    "description", "article", "type", "src", "alt", "t", "num",
    "unit", "unmatched", "register", "problems", "lanes", "members", "claims", "marks",
    "stops", "values", "unread", "evaluators", "requirements", "rests_on", "resolves",
    "resolved_by", "commands", "legend", "nodes", "edges", "via", "steps", "milestones",
    "assumptions",
    # architecture phase 3b: the trace's structure and amber's tokens
    "stop_kind", "stop_kinds", "taps", "fed_by", "serves", "feeds", "layers", "layer",
    "depth", "head", "ties", "singles", "skipped", "choices", "to", "estimate", "idle",
    "moved", "enters", "amber", "assumption", "choice", "sign", "evaluator", "count",
    "source", "sources", "state", "rank", "sets", "unmoved", "unmeasured",
    # the two pages: the marketing page's record text and tokens
    "when", "params", "value", "reason", "rationale", "returns_text", "input",
    "preference", "returns", "decisions", "rejected", "lost", "alternates"})


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
    the choices no line reads and no feed carries; ``warnings``, in the CLI's
    register. From architecture phase 3b: ``feeds`` (zone -> station, the
    direct derives), ``layers`` (columns per station layer), each station's
    ``station_layer``, ``station_column`` and ``station_depth``, ``traced``,
    ``ties``, the barycentre ``zone_rank``, ``station_rank`` (within its
    layer) and ``requirement_rank``, the ``idle`` zones (no feed, no tap) and
    the feed ``crossings`` before and after the zones' pass."""

    boards: tuple
    zones: tuple
    stations: tuple
    board_of: dict
    zone_of: dict
    station_of: dict
    lines: tuple
    unread: tuple
    warnings: tuple
    feeds: tuple = ()
    layers: tuple = ()
    station_layer: Mapping = {}
    station_column: Mapping = {}
    station_depth: Mapping = {}
    traced: bool = False
    ties: tuple = ()
    zone_rank: Mapping = {}
    station_rank: Mapping = {}
    requirement_rank: Mapping = {}
    idle: tuple = ()
    crossings: Mapping = {}
    trace_key: str | None = None


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
    """The value names claim ``cid``'s settling evaluators read by a named
    path — directly: what the trace adds is drawn as stations upstream and
    feeds from the zones, never as more reads (architecture phase 3b) — and
    ``reads_all`` for a whole read."""
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
            named.update(graph_logic.value_names(path, choices, derived))
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


def _mean(values: Iterable[float]) -> float | None:
    found = list(values)
    return (sum(found) / len(found)) if found else None


def _barycentre_order(ids: list[str], centre: Mapping[str, float | None]) -> list[str]:
    """``ids`` sorted by their barycentre (the mean row of what they connect
    to), those with none after, ties and the rest in the stable order given:
    one layered barycentre pass, which reduces crossings between a fixed layer
    (the claims' rows) and the free one. *Rejected:* iterated sweeps (the
    claims' rows never move, so a second pass moves nothing) and a crossing
    minimiser (NP-hard, and its answer would move with a tie)."""
    index = {nid: i for i, nid in enumerate(ids)}
    return sorted(ids, key=lambda n: (centre.get(n) is None,
                                      centre.get(n) if centre.get(n) is not None else 0.0,
                                      index[n]))


def _crossings(pairs: list[tuple[int, float]]) -> int:
    """How many pairs of ``(left position, right position)`` segments cross."""
    count = 0
    for i, (a1, b1) in enumerate(pairs):
        for a2, b2 in pairs[i + 1:]:
            if (a1 - a2) * (b1 - b2) < 0:
                count += 1
    return count


#: An input's kind -> the source a value it grounds shows on the map (the
#: zone's bar, a choice's row). Provenance: the reference map's four grounds
#: (design choice, datasheet, estimate, assumption), read off the records —
#: never typed by hand: a value an assumption claim sources is an assumption;
#: one an input of a published or measured kind sources is "datasheet" (its
#: word says datasheet or measurement); one any other input sources (a sketch,
#: a photo, a link) is an estimate; one whose records name what lost to it (a
#: loser in the model's ``PARAMS`` or its param record) is a design choice;
#: and one with none of these has no source recorded. What slipped through
#: (review of phase 3b): "nothing sources it" read as a design choice, so a
#: motor mass from a vendor listing and a guessed margin were drawn as
#: deliberate choices. *Rejected:* a `ground` field on the param record (a
#: self-stated trust property launders itself, the reason `independence` is a
#: forbidden key); the rationale's text as the mark of a choice (it often says
#: "vendor listing").
SOURCE_OF_KIND: Mapping[str, str] = {
    "datasheet": "datasheet", "standard": "datasheet", "spec": "datasheet",
    "measurement": "datasheet", "data": "datasheet",
    "sketch": "estimate", "reference": "estimate", "screenshot": "estimate",
    "link": "estimate", "cad": "estimate", "other": "estimate"}

#: The sources, in the order a zone's bar draws them.
SOURCES: tuple[str, ...] = ("chosen", "datasheet", "estimate", "assumption", "unrecorded")


def source_of(built: Any, name: str, kinds: Mapping[str, str],
              params: Mapping[str, Any] | None = None) -> str:
    """A value's source category (`SOURCES`): ``assumption`` when an
    assumption claim sources it, else ``datasheet`` or ``estimate`` by the
    kind of the inputs that source it (`SOURCE_OF_KIND`), else ``chosen`` when
    its records name a loser (``params``' view ``rejected``), else
    ``unrecorded``."""
    found = built.into(graph_logic.node_id("value", name), "sources")
    split = [_split(s) for s in found]
    if any(kind == "claim" for kind, _key in split):
        return "assumption"
    categories = {SOURCE_OF_KIND.get(kinds.get(key, "other"), "estimate")
                  for kind, key in split if kind == "input"}
    if "datasheet" in categories:
        return "datasheet"
    if categories:
        return "estimate"
    if getattr((params or {}).get(name), "rejected", None):
        return "chosen"
    return "unrecorded"


def layout(view: Any, built: Any, *, projection: Any, params: Iterable[Any] = (),
           registry: Any = None, resolution: Any = None) -> Layout:
    """The map's structure (SPEC 17, 29) from the records, the graph and the
    reads the resolution served — never from a status, so a flip moves no row.

    Boards as `boards_of`. Zones: every zone record by ``(order, id)`` with
    its members (a choice in a second zone stays in the first), then the
    generated zone of the choices no zone holds that a line reads directly,
    that feed a station or that an assumption sources, in ``Config`` order; no
    zones with no model. Stations: station records, then a generated
    ``station:@<name>`` for each derived value no record holds that the
    settling evaluators of two or more claims read by a named path (a whole
    read never makes one).

    Traced (architecture phase 3b): each station's depth is the upper median
    of the `graph.depths` of the members its lines read directly (of every
    moved member when no line reads one), its layer the dense rank of the
    depths (a station nothing moved takes the last), its column the interval
    packing within its layer in barycentre order; a line stops at the stations
    holding what its evaluators read directly (``read``) and those holding
    what the trace puts before them (``upstream``), ordered by layer, column
    and station order, then its claim; a zone feeds a station when one of its
    choices moves one of the station's members directly
    (`graph.direct_derives`), and taps a line that reads a choice directly or
    a derived value no station holds. Untraced, the layer is phase 5's column
    and every station's column 0, so an untraced map keeps phase 5's order.
    The zones, the stations within a layer and the requirements carry a
    ``rank``: one barycentre pass against the claims' rows, ties in record
    order."""
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
    traced = getattr(built, "trace", None) is not None

    boards = boards_of(view)
    held = set(by_id)
    for group in store.groups_in_order(groups, "board"):
        for cid in group.members:
            if cid not in held:
                warnings.append(f"groups/{group.id}.json: board member {cid} has no "
                                f"claims/{cid}.json")
    board_of = {cid: board.id for board in boards for cid in board.members}
    rows = [cid for board in boards for cid in board.members]
    row_of = {cid: i for i, cid in enumerate(rows)}

    values_of: dict[str, list[str]] = {}
    whole_of: dict[str, str | None] = {}
    for cid in rows:
        values_of[cid], whole_of[cid] = _reads_of(cid, built, reads, choices, derived)
    touched = {name for names in values_of.values() for name in names}
    sourced = {_split(e.target)[1] for e in built.edges
               if e.type == "sources" and _split(e.source)[0] == "claim"}
    direct = graph_logic.direct_derives(built) if traced else set()
    fed_choices = {c for c, _v in direct}

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
                     if c not in zone_of and (c in touched or c in sourced or c in fed_choices))
        if rest:
            zones.append(Zone(OTHER, said["other_zone" if records else "all_zone"], "", True,
                              rest))
            for name in rest:
                zone_of[name] = f"zone:{OTHER}"
        unread = tuple(sorted((c for c in choices if c not in touched and c not in fed_choices),
                              key=_natural))

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

    station_ids = [f"station:{s.id}" for s in stations]
    station_rec = {f"station:{s.id}": s for s in stations}
    station_order = {nid: i for i, nid in enumerate(station_ids)}

    # -- each line's stops, read and upstream -------------------------------- #
    read_stops: dict[str, dict[str, list[str]]] = {}
    up_stops: dict[str, dict[str, list[str]]] = {}
    for cid in rows:
        here: dict[str, list[str]] = {}
        for name in values_of[cid]:
            sid = station_of.get(name)
            if sid is not None:
                here.setdefault(sid, []).append(name)
        read_stops[cid] = here
        ups: dict[str, list[str]] = {}
        if traced:
            for name in values_of[cid]:
                for nid in graph_logic.upstream(built, graph_logic.node_id("value", name)):
                    up = _split(nid)[1]
                    sid = station_of.get(up)
                    if sid is not None and sid not in here and up not in ups.get(sid, []):
                        ups.setdefault(sid, []).append(up)
        up_stops[cid] = ups
    spans: dict[str, list[int]] = {}
    for cid in rows:
        for sid in list(read_stops[cid]) + list(up_stops[cid]):
            spans.setdefault(sid, []).append(row_of[cid])
    centre = {sid: _mean(spans.get(sid) or ()) for sid in station_ids}

    # -- layers, columns and depths ------------------------------------------ #
    station_layer: dict[str, int] = {}
    station_column: dict[str, int] = {}
    station_depth: dict[str, int | None] = {}
    station_rank: dict[str, int] = {}
    if traced:
        value_depth = graph_logic.depths(built)
        read_here: dict[str, set[str]] = {}
        for cid in rows:
            for sid, names in read_stops[cid].items():
                read_here.setdefault(sid, set()).update(names)
        for sid in station_ids:
            members = [m for m in station_rec[sid].members
                       if m in value_depth and built.moved_by(m)]
            drawn = [m for m in members if m in read_here.get(sid, ())] or members
            found = sorted(value_depth[m] for m in drawn)
            station_depth[sid] = found[len(found) // 2] if found else None
        distinct = sorted({d for d in station_depth.values() if d is not None})
        last = len(distinct)
        for sid in station_ids:
            depth = station_depth[sid]
            station_layer[sid] = distinct.index(depth) if depth is not None else last
        layer_ids = sorted(set(station_layer.values()))
        dense = {layer: i for i, layer in enumerate(layer_ids)}
        station_layer = {sid: dense[layer] for sid, layer in station_layer.items()}
        layers: list[int] = []
        for layer in range(len(layer_ids)):
            members = [sid for sid in station_ids if station_layer[sid] == layer]
            ordered = _barycentre_order(members, centre)
            for i, sid in enumerate(ordered):
                station_rank[sid] = i
            cols = _columns(ordered, spans)
            station_column.update(cols)
            layers.append((max(cols.values()) + 1) if cols else 1)
    else:
        cols = _columns(station_ids, spans)
        for sid in station_ids:
            station_layer[sid] = cols[sid]
            station_column[sid] = 0
            station_depth[sid] = None
        layers = [1] * ((max(cols.values()) + 1) if cols else 0)
        for layer in range(len(layers)):
            members = [sid for sid in station_ids if station_layer[sid] == layer]
            for i, sid in enumerate(_barycentre_order(members, centre)):
                station_rank[sid] = i

    def stop_key(sid: str) -> tuple:
        return (station_layer.get(sid, 0), station_column.get(sid, 0), station_order[sid])

    # -- feeds: the direct derives, zone by station -------------------------- #
    choice_index = {c: i for i, c in enumerate(choices)}
    zone_ids = [f"zone:{z.id}" for z in zones]
    feeds_found: dict[tuple[str, str], list[str]] = {}
    for c, v in sorted(direct):
        zid = zone_of.get(c)
        sid = station_of.get(v)
        if zid is None or sid is None:
            continue
        found = feeds_found.setdefault((zid, sid), [])
        if c not in found:
            found.append(c)
    zone_index = {zid: i for i, zid in enumerate(zone_ids)}
    feeds = tuple({"zone": zid, "to": sid,
                   "choices": sorted(cs, key=lambda c: choice_index.get(c, 10 ** 6))}
                  for (zid, sid), cs in sorted(feeds_found.items(),
                                               key=lambda kv: (zone_index.get(kv[0][0], 10 ** 6),
                                                               station_order[kv[0][1]])))

    # -- what an assumption sets, and what a physical claim settles --------- #
    # An assumption's row joins the stations its sourced choices move
    # directly, and a physical claim's the stations of the assumptions it
    # resolves (``sets``): drawn as springs, never as stops, so they move no
    # station. What slipped through (review of phase 3b): eleven rows of
    # PETGasus ended in a stub that joined nothing.
    sourced_by: dict[str, set[str]] = {}
    for e in built.edges:
        if e.type == "sources" and _split(e.source)[0] == "claim":
            sourced_by.setdefault(_split(e.source)[1], set()).add(_split(e.target)[1])
    sets_of: dict[str, list[str]] = {}
    for cid in rows:
        found = {station_of[v] for c, v in direct
                 if c in sourced_by.get(cid, ()) and v in station_of}
        sets_of[cid] = sorted(found, key=stop_key)
    for cid in rows:
        resolved = [_split(t)[1] for t in built.out(graph_logic.node_id("claim", cid),
                                                    "resolves")]
        if resolved and not sets_of[cid]:
            found = {sid for aid in resolved for sid in sets_of.get(aid, ())}
            sets_of[cid] = sorted(found, key=stop_key)

    requirement_ids = [r.id for r in getattr(view, "requirements", None) or ()]
    requirement_set = set(requirement_ids)
    lines: list[dict] = []
    for order, cid in enumerate(rows):
        claim = by_id[cid]
        values = values_of[cid]
        # An upstream stop is drawn only where it can sit before what the
        # line reads: one the layers put after its last read stop is left out
        # (review of phase 3b: C7 read the print mesh, then rode three
        # stations the order put "before" it to the right of it).
        last = max((stop_key(sid) for sid in read_stops[cid]), default=None)
        ups = [sid for sid in up_stops[cid] if last is None or stop_key(sid) < last]
        stops = sorted(list(read_stops[cid]) + ups, key=stop_key)
        stop_kind = {sid: ("read" if sid in read_stops[cid] else "upstream") for sid in stops}
        via = {sid: list(read_stops[cid].get(sid) or up_stops[cid].get(sid) or ())
               for sid in stops}
        taps: dict[str, list[str]] = {}
        for name in values:
            if name in config:
                zid = zone_of.get(name)
                if zid is not None and name not in taps.get(zid, []):
                    taps.setdefault(zid, []).append(name)
            elif name not in station_of:
                for c, v in sorted(direct):
                    if v == name and zone_of.get(c) is not None:
                        found = taps.setdefault(zone_of[c], [])
                        if c not in found:
                            found.append(c)
        tap_rows = [{"zone": zid, "choices": sorted(cs, key=lambda c: choice_index.get(c, 0))}
                    for zid, cs in sorted(taps.items(), key=lambda kv: zone_index.get(kv[0], 0))]
        fed = {t["zone"] for t in tap_rows} | {f["zone"] for f in feeds if f["to"] in stops}
        lines.append({"claim": cid, "order": order, "board": board_of[cid],
                      "stops": stops + [f"claim:{cid}"], "stop_kind": stop_kind, "via": via,
                      "values": values, "reads_all": whole_of[cid], "taps": tap_rows,
                      "serves": [rid for rid in getattr(claim, "requirements", None) or ()
                                 if rid in requirement_set],
                      "fed_by": sorted(fed, key=lambda z: zone_index.get(z, 0)),
                      "sets": list(sets_of.get(cid) or ()) if not stops else []})

    # -- one barycentre pass for the zones and the requirements -------------- #
    zone_y: dict[str, list[float]] = {}
    for feed in feeds:
        if centre.get(feed["to"]) is not None:
            zone_y.setdefault(feed["zone"], []).append(centre[feed["to"]])
    for line in lines:
        for tap in line["taps"]:
            zone_y.setdefault(tap["zone"], []).append(float(line["order"]))
    zone_centre = {zid: _mean(zone_y.get(zid) or ()) for zid in zone_ids}
    ranked_zones = _barycentre_order(zone_ids, zone_centre)
    zone_rank = {zid: i for i, zid in enumerate(ranked_zones)}
    before = _crossings([(zone_index[f["zone"]], centre[f["to"]]) for f in feeds
                         if centre.get(f["to"]) is not None])
    after_ = _crossings([(zone_rank[f["zone"]], centre[f["to"]]) for f in feeds
                         if centre.get(f["to"]) is not None])
    req_centre = {rid: _mean(row_of[c.id] for c in claim_list
                             if rid in (getattr(c, "requirements", None) or ())
                             and c.id in row_of) for rid in requirement_ids}
    requirement_rank = {rid: i for i, rid in enumerate(_barycentre_order(requirement_ids,
                                                                          req_centre))}
    idle = tuple(zid for zid in zone_ids
                 if not any(f["zone"] == zid for f in feeds)
                 and not any(t["zone"] == zid for line in lines for t in line["taps"]))
    found_trace = getattr(built, "trace", None)
    return Layout(tuple(boards), tuple(zones), tuple(stations), board_of, zone_of,
                  station_of, tuple(lines), unread, tuple(warnings), feeds=feeds,
                  layers=tuple(layers), station_layer=station_layer,
                  station_column=station_column, station_depth=station_depth,
                  traced=traced, ties=tuple(graph_logic.ties_of(built)) if traced else (),
                  zone_rank=zone_rank, station_rank=station_rank,
                  requirement_rank=requirement_rank, idle=idle,
                  crossings={"before": before, "after": after_},
                  trace_key=found_trace)


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
            "ready": {"ready": said["ready_word"], "not-ready": said["not_ready_word"]},
            "trace": {k: (dict(v) if isinstance(v, Mapping) else v)
                      for k, v in said["trace"].items()}}


def _word(token: str) -> str:
    status = next(s for s, k in claim_logic.STATUS_KEY.items()
                  if k == ("skipped" if token == "errored" else token))
    return report_logic.words(status, errored=token == "errored").word


def _marks(toks: Any, amber: Mapping[str, Any] | None = None) -> dict[str, list[str]]:
    """Each claim's marks: tokens shown beside its status, never instead of it
    — ``disagree``, then ``amber`` (architecture phase 3b) for a claim whose
    amber flips: a Checked pass that a ±10% move of an unconfirmed
    assumption's choice turns to a fail."""
    out: dict[str, list[str]] = {}
    for cid in (getattr(toks, "disagree", None) or {}).get("claims") or ():
        out.setdefault(cid, []).append("disagree")
    for cid, found in sorted((amber or {}).items(), key=lambda kv: _natural(kv[0])):
        if getattr(found, "state", None) == "flips":
            out.setdefault(cid, []).append("amber")
    return out


def _group_marks(members: Iterable[str], marks: Mapping[str, list[str]]) -> list[str]:
    """A board's or a requirement's marks: each mark one of its claims
    carries, in `_marks`' order."""
    found: list[str] = []
    for mark in ("disagree", "amber"):
        if any(mark in (marks.get(c) or ()) for c in members):
            found.append(mark)
    return found


def amber_word(state: str) -> str:
    """Amber's site word for ``state``."""
    said = _site_words()["trace"]
    return said.get(f"amber_{state.replace('-', '_')}", "")


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
    names the export a test on a built part needs. A Checked claim has
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
    for ``intro``, ``next`` and ``story`` (`PROSE_SUBJECTS`), every claim's,
    with ``_readiness`` and ``_m:<id>`` for each milestone.

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
    current_as_of}``; a file that names no board and no `PROSE_SUBJECTS` entry
    has subject None and stamp ``none``."""
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
#: The view kinds the marketing page's viewer can switch between: the kinds
#: page.js draws in its 3D viewer (a ``field`` is a model with values on it).
VIEWER_KINDS = ("model3d", "field")


def alternates(views: Iterable[Mapping[str, Any]], root: str = "",
               first: str | None = None) -> list[dict]:
    """The views the marketing page's viewer can show, ``[{view, title,
    bytes}]``: every ``model3d`` and ``field`` view in the baked views' order,
    ``first`` (the representation's) moved to the front, and a view whose
    ``src`` holds the same bytes as one before it left out (first wins).
    ``bytes`` is the size of the file ``src`` names under ``site/`` (the
    loading bar's denominator when the response has none), or None.

    What it closes before it could slip through: PETGasus bakes `print_part`
    and `assembly`, two model3d views whose GLB files hold the same bytes, and
    a "Views" control with two names for one model says there is a second
    design to look at. *Rejected:* deduplicating by ``src``
    (two paths can hold one file, and a viewgen that writes per-view copies
    would read as two models); listing every view kind (an image or a chart is
    no model to turn)."""
    site_dir = os.path.join(root, "site") if root else ""
    rows = [r for r in views or () if str(r.get("kind") or "") in VIEWER_KINDS]
    if first is not None:
        rows = ([r for r in rows if str(r.get("id") or "") == first]
                + [r for r in rows if str(r.get("id") or "") != first])
    out: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        vid = str(row.get("id") or "")
        src = str(row.get("src") or "")
        size: int | None = None
        key = f"view:{vid}"
        if site_dir and src and not src.startswith(("/", "\\")) and ":" not in src:
            path = os.path.join(site_dir, *src.split("/"))
            if os.path.isfile(path) and _inside(path, site_dir):
                with open(path, "rb") as fh:
                    key = "sha256:" + hashlib.sha256(fh.read()).hexdigest()
                size = os.path.getsize(path)
        if key in seen:
            continue
        seen.add(key)
        out.append({"view": vid, "title": str(row.get("title") or ""), "bytes": size})
    return out


def representation(views: Iterable[Mapping[str, Any]], root: str = "") -> dict:
    """The outline's representation: the first ``model3d`` view in the page's
    order, else the first ``image`` or ``diagram``, else a notice saying what
    view to add; with ``alternates`` (`alternates`, the two pages), the model
    views the marketing page's viewer can switch between, this one first."""
    views = list(views or ())
    for kinds in (("model3d",), ("image", "diagram")):
        for row in views:
            if str(row.get("kind") or "") in kinds:
                vid = str(row.get("id") or "")
                return {"view": vid, "kind": str(row.get("kind")),
                        "title": str(row.get("title") or ""), "notice": "",
                        "alternates": alternates(views, root, first=vid)}
    return {"view": None, "kind": None, "title": "",
            "notice": _site_words()["no_representation"],
            "alternates": alternates(views, root)}


def _board_token(members: Iterable[str], composed: Mapping[str, Any]) -> tuple[str, bool]:
    status, errored, _worst = claim_logic.worst_of(list(members), composed)
    return ("errored" if errored else claim_logic.STATUS_KEY[status]), errored


def _tally(members: Iterable[str], composed: Mapping[str, Any]) -> list[dict]:
    return report_logic.count_bits({cid: composed[cid] for cid in members if cid in composed})


def _amber_node(found: Any, line: Mapping[str, Any] | None, built: Any) -> dict | None:
    """A claim's baked amber: ``{state, word, enters}`` — ``enters`` the first
    stop of its line holding a value a flipping choice moves (null: the whole
    line) — or None when the claim has no amber."""
    if found is None:
        return None
    enters = None
    if found.state == "flips" and line is not None:
        moving = {f[1] for f in found.flips}
        for stop in line["stops"]:
            if not stop.startswith("station:"):
                continue
            names = line["via"].get(stop) or ()
            if any(any(c in moving for c in built.moved_by(n)) or n in moving for n in names):
                enters = stop
                break
    return {"state": found.state, "word": amber_word(found.state), "enters": enters}


def _amber_summary(amber: Mapping[str, Any]) -> str:
    states = [getattr(a, "state", "") for a in amber.values()]
    current = [s for s in states if s in ("flips", "unclear", "holds")]
    if not states or not current:
        return "none"
    return "current" if len(current) == len(states) else "partial"


def _estimate(built: Any, names: Iterable[str], toks: Any) -> list[str]:
    """The unconfirmed assumptions that source any of ``names``."""
    tokens = getattr(toks, "claims", None) or {}
    found: set[str] = set()
    for name in names:
        for source in built.into(graph_logic.node_id("value", name), "sources"):
            kind, key = _split(source)
            if kind == "claim" and trace_logic.unconfirmed(built, tokens, key):
                found.add(key)
    return sorted(found, key=_natural)


def trace_block(lay: Layout, built: Any, amber: Mapping[str, Any], trace: Any) -> dict:
    """``map.json``'s ``trace``: the key's first 12 hex, the round that traced
    it, ``traced``/``untraced``, the choices it did not move, the derived values
    it did not see move (``unmoved``), the counts of tied and single-mover
    values, amber's currency, and the notice and the sentences on what the
    trace did not move and did not see move, in the site's words. What slipped
    through (review of phase 3b): the map named the skipped choices and not the
    nine values no move changed, so a claim reading only those drew unjoined
    with no word why."""
    said = _site_words()["trace"]
    found = getattr(trace, "trace", None) if trace is not None else None
    traced = lay.traced and found is not None
    number = getattr(found, "round", None) if traced else None
    skipped = dict(getattr(found, "skipped", {}) or {}) if traced else {}
    unmoved = sorted(getattr(found, "unmoved", ()) or (), key=_natural) if traced else []
    if traced:
        notice = (said["notice_traced"].format(round=number) if number is not None
                  else said["notice_traced_no_round"])
    else:
        notice = said["notice_untraced"]
    names = sorted(skipped, key=_natural)
    parts = []
    if names:
        parts.append(said["skipped_one" if len(names) == 1 else "skipped"].format(
            n=len(names), names=", ".join(names)))
    if unmoved:
        parts.append(said["unmoved_one" if len(unmoved) == 1 else "unmoved"].format(
            n=len(unmoved), names=", ".join(unmoved)))
    return {"key": (getattr(built, "trace", None) or "")[:12] or None, "round": number,
            "state": "traced" if traced else "untraced", "skipped": skipped,
            "unmoved": unmoved,
            "ties": len(getattr(found, "ties", ()) or ()) if traced else 0,
            "singles": len(getattr(found, "singles", ()) or ()) if traced else 0,
            "amber": _amber_summary(amber), "notice": notice, "text": " ".join(parts)}


def _unseen(line: Mapping[str, Any], trace: Any) -> bool:
    """Whether a line joins nothing (no station, no zone feeds it) while it
    reads a value the trace did not see move: it then joins no zone because
    the trace saw nothing change, never because nothing reaches it (review of
    phase 3b: C10, reading the parts list, drew as an orphan stub)."""
    found = getattr(trace, "trace", None) if trace is not None else None
    if found is None or line.get("fed_by") or any(
            str(s).startswith("station:") for s in line.get("stops") or ()):
        return False
    unmoved = set(getattr(found, "unmoved", ()) or ())
    return any(v in unmoved for v in line.get("values") or ())


def _unmeasured(members: Iterable[str], trace: Any, traced: bool) -> list[str]:
    """The choices of a zone the trace did not measure: every one untraced;
    traced, the ones it did not move (a yes/no, a word) and the ones whose
    moved builds raised."""
    found = getattr(trace, "trace", None) if trace is not None else None
    if not traced or found is None:
        return list(members)
    out = []
    for name in members:
        row = (getattr(found, "observed", None) or {}).get(name)
        if name in (getattr(found, "skipped", None) or {}) or row is None \
                or any(row.get("raised") or ()):
            out.append(name)
    return out


def requirement_nodes(view: Any, lay: Layout, toks: Any,
                      marks: Mapping[str, list[str]]) -> list[dict]:
    """The map's requirement nodes, in the records' order (``order``; never
    ``rank``, which is the drawing's): each requirement's statement, its token
    from `graph.tokens`, its word, its marks (each mark a serving claim carries,
    ``disagree`` too when the requirement's own status and evidence disagree)
    and the claims that serve it. The one producer of a requirement row: the
    map's node and the marketing page's card (`requirement_row`) are both this.
    *Rejected:* a second loop in `bake_page` (two producers of one token, the
    drift invariant 12 forbids)."""
    nodes: list[dict] = []
    for i, requirement in enumerate(getattr(view, "requirements", None) or ()):
        nid = f"requirement:{requirement.id}"
        serving = [line["claim"] for line in lay.lines if requirement.id in line["serves"]]
        token = toks.requirements.get(requirement.id, "gap")
        found = _group_marks(serving, marks)
        if requirement.id in (toks.disagree.get("requirements") or ()) \
                and "disagree" not in found:
            found.insert(0, "disagree")
        nodes.append({"id": nid, "kind": "requirement", "key": requirement.id,
                      "lane": "requirements", "order": i,
                      "rank": lay.requirement_rank.get(requirement.id, i),
                      "title": requirement.statement, "token": token, "word": _word(token),
                      "errored": token == "errored", "marks": found, "claims": serving})
    return nodes


def requirement_row(node: Mapping[str, Any]) -> dict:
    """``page.json``'s requirement row: a map requirement node
    (`requirement_nodes`) renamed for the page, ``{id, statement, token, word,
    errored, marks, claims}`` — copied, never recomputed."""
    return {"id": node["key"], "statement": node["title"], "token": node["token"],
            "word": node["word"], "errored": node["errored"], "marks": list(node["marks"]),
            "claims": list(node["claims"])}


def _value_row(row: Mapping[str, Any]) -> dict | None:
    """A parameter of ``state.json``'s ``params`` (`modelio.ParamView.to_dict`)
    as the marketing page lists it: ``{name, value_text, rationale, lost:
    [{value_text, reason}]}``. A value is text (``0.5 mm``), ``""`` for a
    structure; a loser's value is text too, as written when it is text (the
    bracket writes ``4.0 mm``), so a losing value never joins the number pool
    and prose that quotes it is marked. What lost is the record's ``why``,
    under ``reason`` (record text)."""
    name = str(row.get("name") or "")
    if not name:
        return None
    units = str(row.get("units") or "")

    def text(value: Any) -> str:
        if value is None or isinstance(value, (dict, list, tuple)):
            return ""
        if isinstance(value, str):
            return value
        return f"{_num(value)} {units}".strip()

    lost = [{"value_text": text(item.get("value")), "reason": str(item.get("why") or "")}
            for item in row.get("rejected") or () if isinstance(item, Mapping)]
    return {"name": name, "value_text": text(row.get("value")),
            "rationale": str(row.get("rationale") or ""), "lost": lost}


def decision_rows(view: Any, composed: Mapping[str, Any], claims_out: Mapping[str, Any],
                  params: Iterable[Mapping[str, Any]]) -> tuple[list[dict], str, list[dict]]:
    """``(decisions, decisions_more, losers)`` for ``page.json`` (the two
    pages): every decision record, newest first (``when``, ties by id), with
    its claims' chips copied from the page's claim rows, the parameters it
    changed, what lost (`claims.rejection_rows`, the one producer, matched on
    ``(decision, index)``, in the site's words by `report.rejection_words(...,
    register="site")`) and how many lost; the label of the decisions past
    `DECISIONS_SHOWN`; and the parameters with a loser that no decision lists.

    Newest first because a story reads the latest choice first; the order is
    the records' dates, never a status. *Rejected:* oldest first (the first
    choice of a long project is its least interesting); sorting by status (the
    browser would read the order as a verdict, and invariant 14 keeps order
    out of its hands)."""
    said = _site_words()["rejection"]
    rows = {(r.decision, r.index): r for r in claim_logic.rejection_rows(view, composed)}
    by_name: dict[str, dict] = {}
    for row in params or ():
        shaped = _value_row(row) if isinstance(row, Mapping) else None
        if shaped is not None and shaped["name"] not in by_name:
            by_name[shaped["name"]] = shaped
    decisions = sorted(getattr(view, "decisions", None) or (), key=lambda d: _natural(d.id))
    decisions.sort(key=lambda d: str(getattr(d, "when", "") or ""), reverse=True)
    out: list[dict] = []
    attached: set[str] = set()
    featured_n = 0
    for decision in decisions:
        changed_claims = list(getattr(decision, "claims_changed", None) or ())
        changed_params = list(getattr(decision, "params_changed", None) or ())
        featured = bool(changed_claims or changed_params)
        shown = featured and featured_n < DECISIONS_SHOWN
        featured_n += 1 if featured else 0
        chips = []
        for cid in changed_claims:
            found = claims_out.get(cid)
            if found is None:
                continue
            chips.append({"claim": cid, "token": found["token"], "word": found["word"],
                          "errored": found["errored"], "marks": list(found["marks"])})
        rejected = []
        for i, item in enumerate(getattr(decision, "rejected", None) or ()):
            row = rows.get((decision.id, i))
            if row is None:
                continue
            type_word, returns_word = report_logic.rejection_words(row, view, register="site")
            rejected.append({
                "value": row.value, "reason": str(getattr(item, "why", "") or ""),
                "type": row.type, "type_word": type_word,
                "preference": row.preference.state if row.preference is not None else None,
                "returns": row.returns.state, "returns_word": returns_word,
                "returns_text": report_logic.condition_text(row.condition),
                "input": row.input or None})
        values = []
        for name in changed_params:
            if name in by_name:
                values.append({**by_name[name],
                               "lost": [dict(x) for x in by_name[name]["lost"]]})
                attached.add(name)
        n = len(rejected)
        out.append({"id": decision.id, "title": str(getattr(decision, "title", "") or ""),
                    "when": str(getattr(decision, "when", "") or ""),
                    "summary": str(getattr(decision, "summary", "") or ""),
                    "featured": featured, "shown": shown, "claims": chips,
                    "params": changed_params, "rejected": rejected,
                    "lost_label": ("" if n == 0 else said["lost_one"] if n == 1
                                   else said["lost"].format(n=n)),
                    "values": values})
    more = sum(1 for d in out if not d["shown"])
    more_label = ("" if more == 0 else said["more_one"] if more == 1
                  else said["more"].format(n=more))
    losers = [row for name, row in by_name.items() if row["lost"] and name not in attached]
    return out, more_label, losers


def bake_map(view: Any, lay: Layout, built: Any, toks: Any, composed: Mapping[str, Any], *,
             projection: Any, params: Iterable[Any] = (), registry: Any = None,
             payload: Mapping[str, Any] | None = None, name: str = "",
             records_digest: str = "", resolution_digest: str = "",
             amber: Mapping[str, Any] | None = None, trace: Any = None) -> dict:
    """``map.json`` (SPEC 29, map schema 2): nodes with kind, lane, order and
    rank, lines with their stops, taps and the requirements they serve, the
    feeds, the values, the evaluators and the typed edges — tokens and words
    beside them, never a position. ``amber`` (`derivation.amber_states`) and
    ``trace`` (`derivation.TraceRead`) are architecture phase 3b's: a claim
    whose amber flips carries the ``amber`` mark, beside its status."""
    said = _site_words()
    amber = dict(amber or {})
    marks = _marks(toks, amber)
    params = {p.name: p for p in params or ()}
    config = dict(projection.get("config") or {}) if isinstance(projection, Mapping) else {}
    derived = dict(projection.get("derived") or {}) if isinstance(projection, Mapping) else {}
    by_id = {c.id: c for c in getattr(view, "claims", None) or ()}
    floor = _floor_values(view, composed, registry)
    kinds = {a.id: str(getattr(a.kind, "value", a.kind) or "other")
             for a in getattr(view, "inputs", None) or ()}
    line_of = {line["claim"]: line for line in lay.lines}
    view_verdicts = list(getattr(view, "verdicts", None) or ())

    def units_of(name: str) -> str:
        return _units_of(name, config, derived, params, built, view_verdicts)

    nodes: list[dict] = requirement_nodes(view, lay, toks, marks)
    traced_now = lay.traced and getattr(trace, "trace", None) is not None
    unmeasured_of = {f"zone:{z.id}": _unmeasured(z.members, trace, traced_now)
                     for z in lay.zones}
    for i, zone in enumerate(lay.zones):
        nid = f"zone:{zone.id}"
        ground = {"chosen": 0, "input": 0, "assumption": 0}
        sources = {key: 0 for key in SOURCES}
        assumptions: list[str] = []
        for member in zone.members:
            ground[_ground(built, member)] += 1
            sources[source_of(built, member, kinds, params)] += 1
            for source in built.into(graph_logic.node_id("value", member), "sources"):
                kind, key = _split(source)
                if kind == "claim" and key not in assumptions:
                    assumptions.append(key)
        fed = [line["claim"] for line in lay.lines if nid in line["fed_by"]]
        nodes.append({"id": nid, "kind": "zone", "key": zone.id, "lane": "zones", "order": i,
                      "rank": lay.zone_rank.get(nid, i), "title": zone.title,
                      "line": zone.line, "generated": zone.generated,
                      "members": list(zone.members), "count": len(zone.members),
                      "moved": [m for m in zone.members if built.moves(m)],
                      "ground": ground, "sources": sources,
                      "assumptions": sorted(assumptions, key=_natural),
                      "estimate": _estimate(built, zone.members, toks),
                      # idle only when the trace measured every choice: a
                      # zone the trace could not see into is not measured
                      # (review of phase 3b: an untraced map said "no line uses
                      # these choices" of six zones the claims ride)
                      "idle": nid in lay.idle and not unmeasured_of[nid],
                      "unmeasured": unmeasured_of[nid] if nid in lay.idle else [],
                      "feeds": [f["to"] for f in lay.feeds if f["zone"] == nid],
                      "taps": [line["claim"] for line in lay.lines
                               if any(t["zone"] == nid for t in line["taps"])],
                      "claims": fed})
    for i, station in enumerate(lay.stations):
        nid = f"station:{station.id}"
        riders = [line for line in lay.lines if nid in line["stops"]]
        counts = {m: sum(1 for line in lay.lines if m in line["values"])
                  for m in station.members}
        # The head is the most-read member that is a finite number (a
        # structure shows no value); with none, the most-read member.
        # What slipped through (review of phase 3b): a list was chosen over a
        # scalar beside it, and three stations showed no value.
        ordered = sorted(station.members, key=lambda m: (
            _finite(derived.get(m, config.get(m))) is None, -counts[m],
            station.members.index(m)))
        head = ordered[0] if ordered else None
        depth = lay.station_depth.get(nid)
        nodes.append({"id": nid, "kind": "station", "key": station.id, "lane": "stations",
                      "order": i, "layer": lay.station_layer.get(nid, 0),
                      "column": lay.station_column.get(nid, 0),
                      "rank": lay.station_rank.get(nid, 0),
                      "depth": depth, "title": station.title, "line": station.line,
                      "generated": station.generated, "members": list(station.members),
                      "head": head,
                      "value_text": (_value_text(head, config, derived, params,
                                                 units=units_of(head), bare=False)
                                     if head is not None else ""),
                      "fed_by": [f["zone"] for f in lay.feeds if f["to"] == nid],
                      "claims": [line["claim"] for line in riders],
                      "stop_kinds": {line["claim"]: line["stop_kind"][nid] for line in riders}})
    for i, board in enumerate(lay.boards):
        token, errored = _board_token(board.members, composed)
        nodes.append({"id": f"board:{board.id}", "kind": "board", "key": board.id,
                      "lane": "boards", "order": i, "title": board.title, "line": board.line,
                      "generated": board.generated, "token": token, "word": _word(token),
                      "errored": errored, "marks": _group_marks(board.members, marks),
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
                                          if v["binding"]), ""),
                      "amber": _amber_node(amber.get(cid), line, built)})

    lines = [{"claim": line["claim"], "order": line["order"], "board": line["board"],
              "token": toks.claims[line["claim"]],
              "errored": toks.claims[line["claim"]] == "errored",
              "marks": list(marks.get(line["claim"]) or ()), "stops": list(line["stops"]),
              "stop_kind": dict(line["stop_kind"]),
              "via": {k: list(v) for k, v in line["via"].items()},
              "taps": [dict(t) for t in line["taps"]], "fed_by": list(line["fed_by"]),
              "serves": list(line["serves"]), "values": list(line["values"]),
              "reads_all": line["reads_all"], "sets": list(line.get("sets") or ()),
              "unseen": _unseen(line, trace),
              "amber": _amber_node(amber.get(line["claim"]), line, built)}
             for line in lay.lines]

    names = set(lay.zone_of) | set(lay.station_of)
    for line in lay.lines:
        names.update(line["values"])
    touched = {n for line in lay.lines for n in line["values"]}
    values: dict[str, dict] = {}
    for vname in sorted(names, key=_natural):
        node = built.node(graph_logic.node_id("value", vname))
        values[vname] = {
            "role": (node.attrs.get("role") if node is not None else "absent"),
            "value_text": _value_text(vname, config, derived, params, units=units_of(vname)),
            "units": units_of(vname),
            "zone": lay.zone_of.get(vname), "station": lay.station_of.get(vname),
            "ground": _ground(built, vname), "source": source_of(built, vname, kinds, params),
            "read": vname in touched}

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
    requirement_ids = [r.id for r in getattr(view, "requirements", None) or ()]
    lanes = ["requirements"] if requirement_ids else []
    if lay.zones:
        lanes.append("zones")
    if lay.stations:
        lanes.append("stations")
    lanes.append("boards")
    feeds = [{"zone": f["zone"], "to": f["to"], "choices": list(f["choices"]),
              "estimate": _estimate(built, f["choices"], toks)} for f in lay.feeds]
    doc = {"schema": MAP_SCHEMA, "generated": said["generated"],
           "meta": {"name": name, "records_digest": records_digest,
                    "resolution_digest": resolution_digest},
           "trace": trace_block(lay, built, amber, trace), "lanes": lanes,
           "columns": {"requirements": 0}, "layers": list(lay.layers), "legend": legend,
           "nodes": nodes, "lines": lines, "feeds": feeds, "values": values,
           "evaluators": evaluators, "edges": edges, "unread": list(lay.unread)}
    return doc


def _ground(built: Any, name: str) -> str:
    sources = built.into(graph_logic.node_id("value", name), "sources")
    kinds = {_split(s)[0] for s in sources}
    return "assumption" if "claim" in kinds else "input" if "input" in kinds else "chosen"


def _finite(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _units_of(name: str, config: Mapping, derived: Mapping, params: Mapping, built: Any,
              verdicts: Iterable[Any]) -> str:
    """A value's units: its param's, else those of a served verdict whose
    evaluator read it (a ``reads`` edge) and reported it as its measured value
    or its limit — what an evaluator said of it, never a guess from its
    name; ``""`` when nothing says."""
    stated = str(getattr(params.get(name), "units", "") or "")
    if stated:
        return stated
    value = _finite(derived.get(name, config.get(name)))
    if value is None:
        return ""
    readers = {_split(nid)[1] for nid in built.into(graph_logic.node_id("value", name),
                                                     "reads")}
    for verdict in verdicts:
        if getattr(verdict, "gate", None) not in readers or not getattr(verdict, "units", ""):
            continue
        for found in (getattr(verdict, "measured", None), getattr(verdict, "limit", None)):
            number = _finite(found)
            if number is not None and math.isclose(number, value, rel_tol=1e-9,
                                                    abs_tol=1e-12):
                return str(verdict.units)
    return ""


def _value_text(name: str, config: Mapping, derived: Mapping, params: Mapping, *,
                units: str | None = None, bare: bool = True) -> str:
    """A value as a label shows it: the number and its units. ``bare=False``
    (a station's label) leaves a number with no units out, rather than show a
    bare number under the station's name (review of phase 3b: "Layout 22.5"
    was a radius in mm)."""
    if name in config:
        value = config[name]
    elif name in derived:
        value = derived[name]
    else:
        return ""
    if isinstance(value, (dict, list, tuple)) or value is None:
        return ""
    if units is None:
        units = str(getattr(params.get(name), "units", "") or "")
    if not units and not bare:
        return ""
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


def _amber_items(found: Any) -> list[dict]:
    """A claim's amber runs for the drawer and the floor: each flipping run's
    assumption, choice, direction, evaluator and value, in the site's
    words."""
    said = _site_words()["trace"]
    items = []
    for aid, choice, direction, gate, measured, limit, units in getattr(found, "flips", ()):
        sign = "-" if direction == 0 else "+"
        shown = value_text(measured, units or "", (f"{_num(limit)} {units or ''}".strip()
                                                   if isinstance(limit, (int, float))
                                                   and not isinstance(limit, bool) else ""),
                           None) if isinstance(measured, (int, float)) \
            and not isinstance(measured, bool) else ""
        items.append({"assumption": aid, "choice": choice, "sign": sign, "evaluator": gate,
                      "text": said["amber_item"].format(choice=choice,
                                                        step=found.step(choice, direction),
                                                        assumption=aid,
                                                        evaluator=gate or "its evaluator",
                                                        value_text=shown or "a fail")})
    return items


def bake_page(root: str, view: Any, lay: Layout, built: Any, toks: Any,
              composed: Mapping[str, Any], *, registry: Any = None,
              payload: Mapping[str, Any] | None = None, plan: Iterable[Evidence] = (),
              records_digest: str = "", resolution_digest: str = "",
              amber: Mapping[str, Any] | None = None) -> dict:
    """``page.json`` (SPEC 28, 30): the outline's data, every claim's floor
    row once (the floor and the drawer read it), the next steps and the
    words. The prose objects are filled by `bake_prose`. A claim's ``amber``
    (architecture phase 3b) is its amber state and flipping runs, or None."""
    said = _site_words()
    payload = payload or {}
    meta = getattr(view, "meta", None)
    amber = dict(amber or {})
    marks = _marks(toks, amber)
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
            facts = report_logic.result_facts(claim, counted, register="site")
            # `token` is the one key the drawer colours the block by
            # (`report.RESULT_TOKENS`), beside its word (follow-up after phase
            # 3b: the drawer read `counts` alone, and a counted fail read green).
            physical = {"counts": bool(facts["counts"]), "token": facts["token"],
                        "word": facts["word"], "why": facts["why"],
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
                None), cover=cover.get(cid) or (), tiers=tiers),
            "amber": ({"state": amber[cid].state, "word": amber_word(amber[cid].state),
                       "items": _amber_items(amber[cid])} if cid in amber else None)}

    sections = []
    for board in lay.boards:
        token, errored = _board_token(board.members, composed)
        sections.append({"board": board.id, "title": board.title, "line": board.line,
                         "generated": board.generated, "token": token, "word": _word(token),
                         "errored": errored,
                         "marks": _group_marks(board.members, marks),
                         "tally": _tally(board.members, composed),
                         "claims": list(board.members), "prose": None})

    unresolved = claim_logic.unresolved(view, composed)
    stale = bool((payload.get("meta") or {}).get("stale"))
    verdict = {"token": toks.readiness, "ready": bool(unresolved.ready),
               "sentence": report_logic._verdict_sentence(view, composed, registry, stale=False,
                                                          markdown=False, register="site"),
               # The marketing page's large line: the sentence's own first
               # sentence, from its builder (`report.site_headline`).
               "headline": report_logic.site_headline(view, composed),
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
    rebuild = [{"article": str(found.article)[:12], "claims": list(found.claims),
                "text": report_logic.site_rebuild_text(found)}
               for found in claim_logic.rebuild(view)]

    summary = str(getattr(meta, "summary", "") or "")
    # The two pages: the marketing page's rows, each from the producer the
    # engineering page already reads (the map's requirement node, the claim
    # rows above, `claims.rejection_rows`), baked here so `status_problems`
    # and every test that bakes in process see them.
    decisions, decisions_more, losers = decision_rows(view, composed, claims_out,
                                                      payload.get("params") or ())
    return {
        "schema": SCHEMA, "outline": OUTLINE, "generated": said["generated"],
        "meta": {"name": str(getattr(meta, "name", "") or ""), "summary": summary,
                 "revision": str(getattr(meta, "revision", "") or ""),
                 "records_digest": records_digest, "resolution_digest": resolution_digest,
                 "content_digest": content_digest(root)},
        "representation": representation(payload.get("views") or (), root),
        "verdict": verdict,
        "intro": None,
        "story": None,
        "description": {"summary": summary, "notice": said["notices"]["no_intro"]},
        "sections": sections,
        "claims": claims_out,
        "requirements": [requirement_row(node)
                         for node in requirement_nodes(view, lay, toks, marks)],
        "decisions": decisions,
        "decisions_more": decisions_more,
        "losers": losers,
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
                       f"(boards: {', '.join(b.id for b in lay.boards) or 'none'}; and "
                       f"{', '.join(PROSE_SUBJECTS)})")
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
        elif subject == "story":
            # The marketing page's story (the two pages). Its own branch: the
            # board fallback below would look a board named `story` up and
            # raise, since `story` is a reserved group id.
            page_doc["story"] = obj
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
                    pool: Any = None, amber: Mapping[str, Any] | None = None,
                    feeds: Iterable[Mapping[str, Any]] | None = None) -> list[str]:
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

    With ``amber`` (architecture phase 3b: the live `derivation.amber_states`)
    an ``amber`` mark must sit exactly on the claims whose amber flips now
    (and on a board, a requirement, a section, a decision chip or a step
    exactly when one of its claims flips), and every baked amber state (a claim node, a line, a page claim) must be
    the live one; with ``feeds`` (the live `layout`'s) each baked feed's
    ``estimate`` must be the live one — amber on a pass the trace does not
    flip, or a feed drawn as resting on a confirmed assumption, is the page
    saying more than the resolution.

    From the two pages, the marketing page's rows too (`_two_pages_problems`):
    a requirement row against its map node and `graph.tokens`, a requirement
    node's marks, the headline, a decision's claim chips and each rejection's
    tokens and site words against `claims.rejection_rows`.

    What slipped through before the words, the prose and the values were held
    here (review of phase 5): a milestone baked ``ready`` in green beside
    ``ready: false``, a failing board's chip worded *checked*, and a resealed
    page that showed stale prose as current, all read current."""
    problems: list[str] = []
    problems += _amber_problems(map_doc, page_doc, amber, feeds)
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

    req_disagree = set((getattr(toks, "disagree", None) or {}).get("requirements") or ())

    def requirement_disagree(key: str, row: Mapping[str, Any]) -> bool:
        # `requirement_nodes`' rule: its own disagreement, or a serving claim's.
        return key in req_disagree or any(str(c) in disagree for c in row.get("claims") or ())

    map_requirements: dict[str, Mapping[str, Any]] = {}
    for node in (map_doc or {}).get("nodes") or ():
        kind = node.get("kind")
        key = str(node.get("key"))
        if kind == "claim":
            check(f"claim:{key}", node.get("token"), want.get(key))
            check(f"claim:{key} disagree", "disagree" in (node.get("marks") or ()),
                  key in disagree)
        elif kind == "requirement":
            map_requirements[key] = node
            check(f"requirement:{key}", node.get("token"),
                  (getattr(toks, "requirements", None) or {}).get(key))
            # The two pages: a requirement's marks are held as a claim's are
            # (they were not: a requirement node could drop its disagree mark).
            check(f"requirement:{key} disagree", "disagree" in (node.get("marks") or ()),
                  requirement_disagree(key, node))
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
        # A recorded result's block: its token and word are the judge's
        # (`report.result_facts`), and a block where no result is recorded is
        # the page saying more (follow-up after phase 3b: a counted fail read
        # green, from `counts` alone, beside its Failing chip).
        physical = row.get("physical")
        recorded = getattr(claim, "physical_result", None) if claim is not None else None
        if isinstance(physical, Mapping) and recorded is None:
            problems.append(f"page claim {cid} shows a recorded result, and none is recorded")
        elif isinstance(physical, Mapping):
            facts = report_logic.result_facts(claim, recorded, register="site")
            check(f"page claim {cid} result", physical.get("token"), facts["token"])
            check(f"page claim {cid} result word", physical.get("word"), facts["word"])
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
    _two_pages_problems(problems, page_doc, view, composed, toks, map_requirements,
                        check=check, word_of=word_of, mark_of=mark_of,
                        requirement_disagree=requirement_disagree)
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


def _two_pages_problems(problems: list[str], page_doc: Mapping[str, Any], view: Any,
                        composed: Mapping[str, Any], toks: Any,
                        map_requirements: Mapping[str, Mapping[str, Any]], *,
                        check: Callable[[str, Any, Any], None],
                        word_of: Callable[[str, Mapping[str, Any]], None],
                        mark_of: Callable[[str, Mapping[str, Any], bool], None],
                        requirement_disagree: Callable[[str, Mapping[str, Any]], bool]
                        ) -> None:
    """Invariant 14 on the marketing page's rows (the two pages), appended to
    ``problems``: each requirement row's token, word and marks against
    `graph.tokens` and against its map node (the one producer); the headline
    against `report.site_headline` and as the start of the sentence, always
    (a page without one is named); the tally against `report.count_bits` and
    the limits line against `report.limits_line(register="site")`; each
    decision's claim chips against the claims' tokens; each rejection's type,
    preference and return tokens and its site words against
    `claims.rejection_rows` and `report.rejection_words(register="site")`,
    computed here, so the build and every reader of a baked page (`site
    status`, `status`, `doctor`) hold the same rows. A row the page leaves
    out says less, never more, so only what is baked is held; a row for no
    record is named. What it closes before it could slip through: a resealed
    page.json whose card reads "Preferred against, recorded by Robin Okafor"
    before Robin ran `nopekit prefer` (invariant 13), or a requirement chip
    in green over a failing claim."""
    want = dict(getattr(toks, "claims", None) or {})
    disagree = set((getattr(toks, "disagree", None) or {}).get("claims") or ())
    required = dict(getattr(toks, "requirements", None) or {})
    for row in page_doc.get("requirements") or ():
        if not isinstance(row, Mapping):
            continue
        key = str(row.get("id"))
        where = f"page requirement {key}"
        check(where, row.get("token"), required.get(key))
        word_of(where, row)
        mark_of(where, row, requirement_disagree(key, row))
        node = map_requirements.get(key)
        if node is not None:
            for mine, theirs in (("token", "token"), ("word", "word"), ("errored", "errored"),
                                 ("marks", "marks"), ("claims", "claims"),
                                 ("statement", "title")):
                check(f"{where} {mine} (its map node)", row.get(mine), node.get(theirs))
    # The verdict's lines above the fold on the marketing page, each held
    # against the producer `bake_page` calls, whether or not the key is baked.
    # What slipped through (review of SPEC 40): the headline was held only
    # when present, so a resealed page.json with no headline and a sentence
    # rewritten to "v0.1 is ready, as last evaluated." read current in `site
    # status`, `status` and `doctor`, and marketing.js drew that sentence's
    # lead as the hero's large line over a failing claim; a tally cut to one
    # "7 checked" chip and an empty limits line (the page's only "Checked
    # does not mean true") read current too.
    verdict = page_doc.get("verdict") or {}
    headline = verdict.get("headline")
    check("verdict headline", headline, report_logic.site_headline(view, composed))
    if not isinstance(headline, str) or not headline \
            or not str(verdict.get("sentence") or "").startswith(headline):
        problems.append("verdict headline is not the start of the verdict sentence")
    check("verdict tally", verdict.get("tally"), report_logic.count_bits(composed))
    check("verdict limits", verdict.get("limits"),
          report_logic.limits_line(view, register="site"))
    baked = page_doc.get("decisions") or ()
    if not baked:
        return
    records = {d.id: d for d in getattr(view, "decisions", None) or ()}
    rows = {(r.decision, r.index): r for r in claim_logic.rejection_rows(view, composed)}
    for decision in baked:
        if not isinstance(decision, Mapping):
            continue
        did = str(decision.get("id"))
        if did not in records:
            problems.append(f"decision {did} is on the page and in no record")
            continue
        for chip in decision.get("claims") or ():
            cid = str(chip.get("claim"))
            where = f"decision {did} claim {cid}"
            check(where, chip.get("token"), want.get(cid))
            word_of(where, chip)
            mark_of(where, chip, cid in disagree)
        for i, item in enumerate(decision.get("rejected") or ()):
            where = f"decision {did} rejection {i}"
            row = rows.get((did, i))
            if row is None:
                problems.append(f"{where} is on the page and in no record")
                continue
            type_word, returns_word = report_logic.rejection_words(row, view, register="site")
            check(f"{where} type", item.get("type"), row.type)
            check(f"{where} type word", item.get("type_word"), type_word)
            check(f"{where} preference", item.get("preference"),
                  row.preference.state if row.preference is not None else None)
            check(f"{where} return", item.get("returns"), row.returns.state)
            check(f"{where} return word", item.get("returns_word"), returns_word)


def _amber_problems(map_doc: Mapping[str, Any] | None, page_doc: Mapping[str, Any] | None,
                    amber: Mapping[str, Any] | None,
                    feeds: Iterable[Mapping[str, Any]] | None) -> list[str]:
    out: list[str] = []
    if amber is not None:
        live = {cid: getattr(found, "state", None) for cid, found in amber.items()}

        def held(where: str, cid: str, row: Mapping[str, Any]) -> None:
            if "marks" in row and ("amber" in (row.get("marks") or ())) != (
                    live.get(cid) == "flips"):
                out.append(f"{where} amber mark reads {'amber' in (row.get('marks') or ())}, "
                           f"amber now is {live.get(cid) or 'none'}")
            if "amber" in row:
                baked = (row.get("amber") or {}).get("state") if row.get("amber") else None
                if baked != live.get(cid):
                    out.append(f"{where} amber reads {baked}, amber now is {live.get(cid)}")

        def group(where: str, members: Iterable[Any], row: Mapping[str, Any]) -> None:
            # `_group_marks`' rule: a board, a requirement or a chip carries
            # ``amber`` exactly when one of its claims flips now.
            if "marks" not in row:
                return
            said = "amber" in (row.get("marks") or ())
            flips = any(live.get(str(c)) == "flips" for c in members or ())
            if said != flips:
                out.append(f"{where} amber mark reads {said}, amber now "
                           f"{'flips' if flips else 'flips on none of its claims'}")

        for node in (map_doc or {}).get("nodes") or ():
            if node.get("kind") == "claim":
                held(f"claim:{node.get('key')}", str(node.get("key")), node)
            elif node.get("kind") in ("requirement", "board"):
                group(f"{node.get('kind')}:{node.get('key')}", node.get("claims") or (), node)
        for line in (map_doc or {}).get("lines") or ():
            held(f"line {line.get('claim')}", str(line.get("claim")), line)
        for cid, row in ((page_doc or {}).get("claims") or {}).items():
            held(f"page claim {cid}", str(cid), row)
        # The marketing page's rows (the two pages). What slipped through
        # (review of SPEC 40): only claim nodes, lines and page claims were
        # held, so a requirement card or a decision chip could drop or add
        # ``amber`` and a resealed page read current, the 0.8%-margin pass on
        # unconfirmed assumptions as green as one at 80% (phase 3b's slip).
        for row in (page_doc or {}).get("requirements") or ():
            if isinstance(row, Mapping):
                group(f"page requirement {row.get('id')}", row.get("claims") or (), row)
        for section in (page_doc or {}).get("sections") or ():
            if isinstance(section, Mapping):
                group(f"section {section.get('board')}", section.get("claims") or (), section)
        for decision in (page_doc or {}).get("decisions") or ():
            if not isinstance(decision, Mapping):
                continue
            for chip in decision.get("claims") or ():
                if isinstance(chip, Mapping):
                    group(f"decision {decision.get('id')} claim {chip.get('claim')}",
                          [chip.get("claim")], chip)
        nxt = (page_doc or {}).get("next") or {}
        groups = list(nxt.get("milestones") or ()) + ([nxt["project"]]
                                                      if nxt.get("project") else [])
        steps = [s for g in groups for s in g.get("steps") or ()] + list(nxt.get("open") or ())
        for step in steps:
            if isinstance(step, Mapping):
                group(f"step {step.get('claim')}", [step.get("claim")], step)
    if feeds is not None and map_doc is not None:
        want = {(f["zone"], f["to"]): list(f.get("estimate") or ()) for f in feeds}
        for feed in map_doc.get("feeds") or ():
            key = (feed.get("zone"), feed.get("to"))
            if key not in want:
                out.append(f"feed {key[0]} -> {key[1]} is on the map and the trace draws none")
            elif list(feed.get("estimate") or ()) != want[key]:
                out.append(f"feed {key[0]} -> {key[1]} rests on {feed.get('estimate')}, the "
                           f"resolution says {want[key]}")
    return out


def live_feeds(lay: Layout, built: Any, toks: Any) -> list[dict]:
    """The feeds as `bake_map` bakes them, for `status_problems`' ``feeds``."""
    return [{"zone": f["zone"], "to": f["to"], "choices": list(f["choices"]),
             "estimate": _estimate(built, f["choices"], toks)} for f in lay.feeds]


def _prose_pieces(page_doc: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    pieces = [(str(s.get("board")), s["prose"]) for s in page_doc.get("sections") or ()
              if s.get("prose")]
    if page_doc.get("intro"):
        pieces.append(("intro", page_doc["intro"]))
    if (page_doc.get("next") or {}).get("prose"):
        pieces.append(("next", page_doc["next"]["prose"]))
    if page_doc.get("story"):
        pieces.append(("story", page_doc["story"]))
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
    "OUTLINE", "SCHEMA", "MAP_SCHEMA", "LANES", "MAP_EDGE_TYPES", "OTHER",
    "IMPLICIT_STATIONS_WARN", "SOURCE_OF_KIND", "SOURCES", "source_of", "trace_block",
    "amber_word", "live_feeds",
    "EVIDENCE_MAX_BYTES", "EVIDENCE_DIR", "PROSE_SUBJECTS", "WORD_KEYS", "RECORD_KEYS",
    "Board", "Zone", "Station", "Layout", "Evidence",
    "token_of", "boards_of", "layout", "value_text", "words_block", "evidence_plan",
    "evidence_assets", "settle", "subject_tokens", "named_in", "prose_named", "prose_files",
    "subjects", "stamp_state",
    "stamp_states", "content_digest", "seal", "representation", "bake_map", "bake_page",
    "bake_prose", "status_problems",
    # the two pages: the marketing page's rows
    "DECISIONS_SHOWN", "VIEWER_KINDS", "alternates", "requirement_nodes", "requirement_row",
    "decision_rows",
]
