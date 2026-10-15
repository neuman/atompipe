# SPDX-License-Identifier: Apache-2.0
"""graph.py — the falsification graph, typed (SPEC decision 19).

One graph, built from what the project already holds: the records, the
registry, the resolution, and the verdict entries the resolution served (their
read sets — never the ignored `obs/`, which a fresh clone does not have). Nodes
are requirements, claims, evaluators, values, instruction files, inputs,
milestones and decisions; edges are typed, and every edge type has exactly one
source:

=============  ==================================  =========================================
type           from -> to                          source
=============  ==================================  =========================================
serves         claim -> requirement                ``Claim.requirements``
settles        evaluator -> claim                  ``claims.effective_gates`` (coverage)
reads          evaluator -> value                  the served entry's ``reads["params"]``
derives        value -> value (choice -> derived)  the trace (phase 3b); none without one
sources        input or assumption -> value        ``artifacts.value_grounding``
rests_on       claim -> assumption claim           computed: reads, closed over derives
resolves       physical claim -> assumption        ``Claim.resolves``
contradicts    claim -> evaluator                  ``Resolution.track`` (sealed fails)
needs          evaluator -> evaluator              ``GateSpec.needs``
requires       milestone -> claim                  ``Milestone.requires``
decides        decision -> value or claim          ``params_changed``, ``claims_changed``
=============  ==================================  =========================================

**Structure, never status.** A node carries what it IS (a claim's kind, an
evaluator's pack, basis and tier, a value's role and digest), and no status:
statuses are `tokens`, beside the graph, joined by id — the round record holds
both, and the site's map calls both. *Rejected:* statuses inside the nodes (two
homes for one status in one file, and a flip of C1 diffing as a nested
multi-line change instead of `"C1": "failing"`).

**No edge changes a status.** `claims.compose` never reads this module; a
`rests_on` edge says what a pass stands on, and amber (phase 3b) is shown
beside Checked, never instead of it (invariant 12,
`test_graph.AnEdgeChangesNoStatus`).

**Deterministic.** Nodes sort by `NODE_KINDS`, then by `store._natural` of the
key; edges by `EDGE_TYPES`, then source, then target, in node order. Every set
is iterated sorted. No clock, no git, no file writes, no words — tokens and
ids only, so the same records, cache and design give the same bytes on every
machine and every Python (`test_graph.TheGraphIsDeterministic`).

**The trace slots in.** `derives` edges come from phase 3b's trace (`Trace`),
and `rests_on` already closes a read value upward over them; with no trace the
graph says so (`trace: null`, `derives: {}`) and each `rests_on` edge is a
direct read. What slipped through before this module: no record linked C1's
pass to the assumption its load came from, so an assumption nobody confirmed
sat under a Checked claim with nothing on any channel saying so.

The public surface is what a site build calls (the map, the next phase):
`build` and `tokens`, or `of`, which reads the design the way an article does.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Any, Collection, Iterable, Mapping, NamedTuple, Protocol

from . import artifacts, claims, gates, verdicts
from .models import ClaimKind
from .store import _natural
from .util import seal

#: The graph's schema, in `to_dict` and the round record. Bumped only when a
#: node's attrs or an edge type change meaning; a reader of a newer one says so.
SCHEMA = 1

#: Node kinds, in the order nodes sort (the map's columns run requirement ->
#: claim -> evaluator -> value; the rest follow).
NODE_KINDS: tuple[str, ...] = ("requirement", "claim", "evaluator", "value", "instruction",
                               "input", "milestone", "decision")

#: Edge types, in the order edges sort (SPEC 19's nine, plus `serves` and
#: `decides`, which the records already hold).
EDGE_TYPES: tuple[str, ...] = ("serves", "settles", "reads", "derives", "sources",
                               "rests_on", "resolves", "contradicts", "needs", "requires",
                               "decides")

#: A value node's role: a choice (a `Config` field), a derived value (a key
#: `build()` returned), or absent — the projection does not hold it (the model
#: did not load, a constant only `PARAMS` declares, an orphan record, a key an
#: evaluator asked for and did not find).
VALUE_ROLES: tuple[str, ...] = ("choice", "derived", "absent")


class Node(NamedTuple):
    """One node: ``id`` (``<kind>:<key>``, `node_id`), ``kind`` (`NODE_KINDS`),
    ``attrs`` (JSON scalars, one schema per kind)."""

    id: str
    kind: str
    attrs: Mapping[str, Any]


class Edge(NamedTuple):
    """One typed edge (`EDGE_TYPES`), from node id ``source`` to ``target``."""

    type: str
    source: str
    target: str


class Trace(Protocol):
    """What phase 3b's trace hands the graph: ``key``, the instructions' digest
    it was observed under, and ``derives``, ``(choice name, derived name)``
    pairs — which derived values move when a choice moves."""

    key: str
    derives: Iterable[tuple[str, str]]


def node_id(kind: str, key: str) -> str:
    """``<kind>:<key>`` — the one spelling of a node id."""
    if kind not in NODE_KINDS:
        raise ValueError(f"not a node kind: {kind!r} (one of {', '.join(NODE_KINDS)})")
    return f"{kind}:{key}"


def _split(nid: str) -> tuple[str, str]:
    kind, _, key = nid.partition(":")
    return kind, key


def _node_order(nid: str) -> tuple:
    kind, key = _split(nid)
    rank = NODE_KINDS.index(kind) if kind in NODE_KINDS else len(NODE_KINDS)
    return rank, _natural(key)


@dataclass(frozen=True)
class Graph:
    """The typed graph: ``nodes`` and ``edges`` in their sorted order;
    ``trace`` — the trace's key, or ``None`` ("derivation not traced yet");
    ``instructions`` — the seal of the instruction nodes' digests, or ``None``
    when the model's code was not recorded."""

    nodes: tuple
    edges: tuple
    trace: str | None = None
    instructions: str | None = None

    def __post_init__(self) -> None:
        by_id = {n.id: n for n in self.nodes}
        out: dict[tuple, list[str]] = {}
        into: dict[tuple, list[str]] = {}
        for edge in self.edges:
            out.setdefault((edge.source, edge.type), []).append(edge.target)
            into.setdefault((edge.target, edge.type), []).append(edge.source)
        object.__setattr__(self, "_by_id", by_id)
        object.__setattr__(self, "_out", out)
        object.__setattr__(self, "_into", into)

    def node(self, nid: str) -> Node | None:
        return self._by_id.get(nid)                          # type: ignore[attr-defined]

    def out(self, nid: str, type: str | None = None) -> tuple[str, ...]:
        """The targets of ``nid``'s edges (of ``type``), in edge order."""
        types = EDGE_TYPES if type is None else (type,)
        found: list[str] = []
        for t in types:
            found += [x for x in self._out.get((nid, t), ()) if x not in found]  # type: ignore
        return tuple(found)

    def into(self, nid: str, type: str | None = None) -> tuple[str, ...]:
        """The sources of the edges into ``nid`` (of ``type``), in edge order."""
        types = EDGE_TYPES if type is None else (type,)
        found: list[str] = []
        for t in types:
            found += [x for x in self._into.get((nid, t), ()) if x not in found]  # type: ignore
        return tuple(found)

    def values(self, role: str | None = None) -> tuple[Node, ...]:
        return tuple(n for n in self.nodes if n.kind == "value"
                     and (role is None or n.attrs.get("role") == role))

    def read_by(self, name: str) -> tuple[str, ...]:
        """The evaluator ids whose served verdict read value ``name``, natural order."""
        return tuple(_split(src)[1] for src in self.into(node_id("value", name), "reads"))

    def sourced_from(self, name: str) -> tuple[str, ...]:
        """The node ids that source value ``name`` (inputs and assumptions), node order."""
        return self.into(node_id("value", name), "sources")

    def rests_on(self, cid: str) -> tuple[str, ...]:
        """The assumption claim ids claim ``cid`` rests on."""
        return tuple(_split(t)[1] for t in self.out(node_id("claim", cid), "rests_on"))

    def via(self, cid: str, aid: str) -> tuple[tuple[str, str, str], ...]:
        """Why ``cid`` rests on ``aid``: ``(evaluator, value read, value sourced)``
        triples, sorted — the read value, and the value the assumption sources
        that it derives from (the same value until a trace adds derives edges)."""
        source = node_id("claim", aid)
        found: set[tuple[str, str, str]] = set()
        for ev in self.into(node_id("claim", cid), "settles"):
            for value in self.out(ev, "reads"):
                for up in _upward(self, value):
                    if source in self.into(up, "sources"):
                        found.add((_split(ev)[1], _split(value)[1], _split(up)[1]))
        return tuple(sorted(found, key=lambda t: (_natural(t[0]), _natural(t[1]),
                                                   _natural(t[2]))))

    def to_dict(self) -> dict:
        """``{"schema", "trace", "instructions", "nodes": {id: attrs},
        "edges": {type: {source: [targets]}}}`` — every edge type present, ``{}``
        when empty, so one edge is one line of an indented diff."""
        edges: dict[str, dict[str, list[str]]] = {t: {} for t in EDGE_TYPES}
        for edge in self.edges:
            edges[edge.type].setdefault(edge.source, []).append(edge.target)
        return {"schema": SCHEMA, "trace": self.trace, "instructions": self.instructions,
                "nodes": {n.id: dict(n.attrs) for n in self.nodes}, "edges": edges}


def upward(graph: Graph, value: str) -> list[str]:
    """``value`` (a node id) and every value it derives from over ``derives``
    edges, transitively (a choice a derived value moves with) — the closure
    ``rests_on`` reads, and the site's map closes a line's reads over
    (architecture phase 5). Just ``[value]`` until a trace adds derives edges."""
    seen = [value]
    stack = [value]
    while stack:
        here = stack.pop()
        for up in graph.into(here, "derives"):
            if up not in seen:
                seen.append(up)
                stack.append(up)
    return seen


#: The private name phase 3a's callers use.
_upward = upward


# --------------------------------------------------------------------------- #
# the sources each edge reads
# --------------------------------------------------------------------------- #
def value_names(path: Any, choices: Collection[str],
                derived: Collection[str] = ()) -> tuple[str, ...]:
    """The value names one recorded param path reads — THE path rule for
    ``reads``, ``read_by`` and ``served_reads``: ``[]`` (the gate took the whole
    of ``ctx.params`` — ``.copy()``, ``.items()``, ``json.dumps``) reads every
    value the flat projection holds, every choice and every name in
    ``derived``; ``["config", k, ...]`` reads choice ``k``; ``["config"]`` alone
    reads every choice (the gate took the whole dict); ``[k, ...]`` reads ``k``;
    anything else reads nothing. Deeper keys are not followed (a gate walking a
    BOM would otherwise read every line item that shares a value's name —
    `modelio.param_readers`' rule).

    What slipped through (review of phase 3a): the bare ``[]`` read nothing, so
    an evaluator that took ``ctx.params.copy()`` drew no ``reads`` edge — its
    claim rested on no assumption and ``why load_n`` said "read by: none" over
    a value it had read. ``derived`` is `derived_names`' (the projection's
    derived keys); without it a whole read still reads every choice."""
    if not isinstance(path, (list, tuple)):
        return ()
    if not path:
        names = {str(c) for c in choices} | {str(d) for d in derived}
        return tuple(sorted(names, key=_natural))
    if not isinstance(path[0], str):
        return ()
    if path[0] == "config":
        if len(path) == 1:
            return tuple(sorted((str(c) for c in choices), key=_natural))
        return (path[1],) if isinstance(path[1], str) else ()
    return (path[0],)


def derived_names(projection: Any) -> tuple[str, ...]:
    """The projection's derived keys, as ``ctx.params`` holds them at its top
    level (`modelio.flat_params`), less a derived ``config`` that only echoes
    the inputs (the reference model returns it; its content is the choices) —
    what a read of the whole ``ctx.params`` reads beside the choices."""
    if not isinstance(projection, Mapping):
        return ()
    config = dict(projection.get("config") or {})
    derived = dict(projection.get("derived") or {})
    return tuple(sorted((str(k) for k, v in derived.items()
                         if not (k == "config" and v == config)), key=_natural))


def served_reads(resolution: Any, registry: Any) -> dict[str, tuple[tuple, ...]]:
    """``{gate id: (path, ...)}`` — the param paths of the verdict entry each
    REGISTERED gate's row stands on (``Row.entry``), sorted, each once. Never
    ``Resolution.read_sets`` and never ``obs/``: the entry a resolution served is
    in the tracked cache, so a fresh clone draws the same lines. A gate with no
    entry has none; one skipped for a missing tool, or under a remembered crash,
    keeps the entry its row names, so a missing tool does not erase what the
    evaluator read (S-30's shape)."""
    registered = {spec.id for spec in _specs(registry)}
    out: dict[str, tuple[tuple, ...]] = {}
    for gid in sorted(registered, key=_natural):
        row = (getattr(resolution, "rows", None) or {}).get(gid)
        entry = getattr(row, "entry", None)
        if entry is None:
            continue
        params = (getattr(entry, "reads", None) or {}).get("params") or ()
        paths = {tuple(item[0]) for item in params
                 if isinstance(item, (list, tuple)) and item
                 and isinstance(item[0], (list, tuple))}
        out[gid] = tuple(sorted(paths, key=lambda p: tuple(_natural(str(k)) for k in p)))
    return out


def value_sources(ledger: Any, views: Iterable[Any]) -> dict[str, tuple[str, ...]]:
    """``{value name: (node id, ...)}`` — what sources each value, from the one
    grounding map (`artifacts.value_grounding`: the extractions, the param
    records and `PARAMS`): an input id as ``input:<id>``, an assumption claim's
    id that is not an input's as ``claim:<id>`` (the value IS that assumption),
    any other id dropped (the index and doctor name it). A grounding target
    that is a claim id and no value's name is a claim's grounding, not a value's,
    and is left out. Node order."""
    views = list(views)
    inputs = {a.id for a in getattr(ledger, "inputs", None) or ()}
    kinds = {c.id: c.kind for c in getattr(ledger, "claims", None) or ()}
    names = {v.name for v in views}
    out: dict[str, tuple[str, ...]] = {}
    for name, ids in artifacts.value_grounding(ledger, views).items():
        if name in kinds and name not in names:
            continue
        found: list[str] = []
        for aid in ids:
            if aid in inputs:
                found.append(node_id("input", aid))
            elif kinds.get(aid) == ClaimKind.ASSUMPTION:
                found.append(node_id("claim", aid))
        if found:
            out[name] = tuple(sorted(set(found), key=_node_order))
    return out


def observe(views: Iterable[Any], *, ledger: Any, resolution: Any, registry: Any,
            choices: Collection[str] = (), derived: Collection[str] = ()) -> list:
    """Each `modelio.ParamView` with ``read_by`` and ``sourced_from`` filled — the
    observed view's two graph lists (SPEC 10), by the rule `Graph.read_by` and
    `Graph.sourced_from` use (`test_graph.ObservedViewAgreesWithTheGraph`).
    ``choices`` are the model's choice names, for a read of the whole
    ``config``; ``derived`` (`derived_names`) the rest of what a read of the
    whole ``ctx.params`` reads."""
    views = list(views)
    readers: dict[str, set[str]] = {}
    for gid, paths in served_reads(resolution, registry).items():
        for path in paths:
            for name in value_names(path, choices, derived):
                readers.setdefault(name, set()).add(gid)
    sources = value_sources(ledger, views)
    return [dataclasses.replace(view,
                                read_by=tuple(sorted(readers.get(view.name, ()),
                                                     key=_natural)),
                                sourced_from=tuple(sources.get(view.name, ())))
            for view in views]


# --------------------------------------------------------------------------- #
# build
# --------------------------------------------------------------------------- #
def _specs(registry: Any) -> list:
    if registry is None:
        return []
    specs = registry.specs() if hasattr(registry, "specs") else list(registry)
    return list(specs)


def _scalar(value: Any) -> bool:
    """A value the graph writes as itself: a finite int, float or bool."""
    if isinstance(value, bool) or isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _instruction_key(spelled: str) -> str:
    return spelled[len("<root>/"):] if spelled.startswith("<root>/") else spelled


def build(view: Any, resolution: Any, registry: Any, *, projection: Any, design: Any,
          views: Iterable[Any] = (), bases: Mapping[str, str] | None = None,
          trace: Trace | None = None) -> Graph:
    """The graph of ``view`` (`cli._resolved`'s: the records with the
    resolution's verdicts and standings) under ``resolution`` and ``registry``.

    ``projection`` gives the values' roles and digests (``None``: every value is
    absent); ``design`` is `verdicts.design_of`'s (``None``: no instruction
    node); ``views`` the parameter views (a `PARAMS` constant or an orphan record
    is a value node too); ``bases`` each input's proposer basis
    (`cli._input_bases`); ``trace`` phase 3b's. Pure: no clock, no git, no file
    read beyond what the arguments already hold."""
    views = list(views)
    bases = dict(bases or {})
    anchors = getattr(resolution, "anchors", None)
    config = dict(projection.get("config") or {}) if isinstance(projection, Mapping) else {}
    derived = dict(projection.get("derived") or {}) if isinstance(projection, Mapping) else {}
    choices = set(config)
    top_derived = derived_names(projection)

    nodes: dict[str, Node] = {}
    edges: set[Edge] = set()

    def add(kind: str, key: str, attrs: Mapping[str, Any]) -> str:
        nid = node_id(kind, key)
        nodes.setdefault(nid, Node(nid, kind, dict(attrs)))
        return nid

    for requirement in getattr(view, "requirements", None) or ():
        add("requirement", requirement.id, {})
    removed_state = verdicts.REMOVED
    for claim in getattr(view, "claims", None) or ():
        try:
            by = claims.terminal_of(claim)
        except Exception:                                   # noqa: BLE001 - shown as declared
            by = str(getattr(claim, "terminal", "") or "")
        add("claim", claim.id, {
            "claim_kind": getattr(claim.kind, "value", str(claim.kind)),
            "by": by,
            "critical": bool(claim.critical),
            "removed": getattr(getattr(claim, "standing", None), "state", "") == removed_state})
    specs = _specs(registry)
    for spec in specs:
        add("evaluator", spec.id, {"pack": str(spec.pack or ""), "basis": gates.basis_of(spec),
                                   "tier": int(spec.tier), "registered": True})
    for artifact in getattr(view, "inputs", None) or ():
        add("input", artifact.id, {"proposer": str(getattr(artifact, "proposer", "") or ""),
                                   "basis": str(bases.get(artifact.id, "") or "")})
    for milestone in getattr(view, "milestones", None) or ():
        add("milestone", milestone.id, {})
    for decision in getattr(view, "decisions", None) or ():
        add("decision", decision.id, {})
    code = (design or {}).get("model") if isinstance(design, Mapping) else None
    for spelled, digest in sorted((code or {}).items()):
        add("instruction", _instruction_key(str(spelled)), {"digest": str(digest or "")})

    def unregistered(gid: str) -> str:
        return add("evaluator", gid, {"pack": None, "basis": None, "tier": None,
                                      "registered": False})

    # -- value names, from every source that names one -------------------- #
    reads = served_reads(resolution, registry)
    sources = value_sources(view, views)
    derives = sorted({(str(a), str(b)) for a, b in (getattr(trace, "derives", None) or ())})
    named: set[str] = set(config)
    for paths in reads.values():
        for path in paths:
            named.update(value_names(path, choices, top_derived))
    named.update(sources)
    for a, b in derives:
        named.update((a, b))
    named.update(v.name for v in views)
    for decision in getattr(view, "decisions", None) or ():
        named.update(str(n) for n in decision.params_changed or ())
    for name in sorted(named, key=_natural):
        if name in config:
            role, value = "choice", config[name]
        elif name in derived and not (name == "config" and derived[name] == config):
            role, value = "derived", derived[name]
        else:
            role, value = "absent", None
        attrs: dict[str, Any] = {"role": role,
                                 "digest": (None if role == "absent"
                                            else verdicts.digest_value(value, anchors))}
        if role != "absent" and _scalar(value):
            attrs["value"] = value
        add("value", name, attrs)

    def edge(type_: str, source: str, target: str) -> None:
        if source in nodes and target in nodes:
            edges.add(Edge(type_, source, target))

    claim_list = list(getattr(view, "claims", None) or ())
    kinds = {c.id: c.kind for c in claim_list}
    for claim in claim_list:
        for rid in getattr(claim, "requirements", None) or ():
            edge("serves", node_id("claim", claim.id), node_id("requirement", rid))
    for cid, gids in claims.effective_gates(view, registry).items():
        for gid in gids:
            edge("settles", node_id("evaluator", gid), node_id("claim", cid))
    for gid, paths in reads.items():
        for path in paths:
            for name in value_names(path, choices, top_derived):
                edge("reads", node_id("evaluator", gid), node_id("value", name))
    for a, b in derives:
        edge("derives", node_id("value", a), node_id("value", b))
    for name, found in sources.items():
        for source in found:
            edge("sources", source, node_id("value", name))
    for claim in claim_list:
        if claim.kind != ClaimKind.PHYSICAL:
            continue
        for aid in getattr(claim, "resolves", None) or ():
            if kinds.get(aid) == ClaimKind.ASSUMPTION and aid != claim.id:
                edge("resolves", node_id("claim", claim.id), node_id("claim", aid))
    for gid, found in sorted((getattr(resolution, "track", None) or {}).items()):
        for contradiction in found:
            source = node_id("claim", str(contradiction.claim))
            if source not in nodes or not gid:
                continue
            target = node_id("evaluator", gid)
            if target not in nodes:
                unregistered(gid)
            edge("contradicts", source, target)
    for spec in specs:
        for need in getattr(spec, "needs", None) or ():
            target = node_id("evaluator", str(need))
            if target not in nodes:
                unregistered(str(need))
            edge("needs", node_id("evaluator", spec.id), target)
    for milestone in getattr(view, "milestones", None) or ():
        for cid in getattr(milestone, "requires", None) or ():
            edge("requires", node_id("milestone", milestone.id), node_id("claim", str(cid)))
    for decision in getattr(view, "decisions", None) or ():
        for name in decision.params_changed or ():
            edge("decides", node_id("decision", decision.id), node_id("value", str(name)))
        for cid in decision.claims_changed or ():
            edge("decides", node_id("decision", decision.id), node_id("claim", str(cid)))

    # -- rests_on: computed over the edges above, never stored ------------- #
    ordered_nodes = tuple(sorted(nodes.values(), key=lambda n: _node_order(n.id)))
    partial = Graph(ordered_nodes, tuple(_sorted_edges(edges)))
    for claim in claim_list:
        cid = node_id("claim", claim.id)
        closure: list[str] = []
        for ev in partial.into(cid, "settles"):
            for value in partial.out(ev, "reads"):
                for up in _upward(partial, value):
                    if up not in closure:
                        closure.append(up)
        for value in closure:
            for source in partial.into(value, "sources"):
                kind, aid = _split(source)
                if kind == "claim" and aid != claim.id \
                        and kinds.get(aid) == ClaimKind.ASSUMPTION:
                    edges.add(Edge("rests_on", cid, source))

    return Graph(ordered_nodes, tuple(_sorted_edges(edges)),
                 trace=(str(getattr(trace, "key", "") or "") or None) if trace is not None
                 else None,
                 instructions=seal(code) if code else None)


def _sorted_edges(edges: Iterable[Edge]) -> list[Edge]:
    return sorted(edges, key=lambda e: (EDGE_TYPES.index(e.type), _node_order(e.source),
                                        _node_order(e.target)))


def of(root: str, view: Any, resolution: Any, registry: Any, *, projection: Any, model: Any,
       views: Iterable[Any] = (), bases: Mapping[str, str] | None = None,
       trace: Trace | None = None) -> Graph:
    """`build`, with the design read as an article reads it
    (`verdicts.design_of`, over ``resolution``'s anchors) — the call a site
    build makes."""
    import os
    anchors = getattr(resolution, "anchors", None) or verdicts.Anchors(
        root=os.path.abspath(root))
    design = verdicts.design_of(root, projection, model, anchors=anchors,
                                resolution=resolution)
    return build(view, resolution, registry, projection=projection, design=design,
                 views=views, bases=bases, trace=trace)


# --------------------------------------------------------------------------- #
# tokens: the statuses beside the graph
# --------------------------------------------------------------------------- #
class Tokens(NamedTuple):
    """The status tokens beside the graph, keyed by id — every one from its one
    producer: ``claims`` (`claims.STATUS_KEY` of the composition, ``errored``
    for a crash), ``requirements`` (`report.requirement_statuses`),
    ``evaluators`` (``{outcome, state, current, entry}``), ``milestones`` and
    ``readiness`` (`claims.unresolved`: ``ready`` or ``not-ready``), ``counts``
    (`claims.summarise`'s, with ``errored``), ``disagree`` (the claims and
    requirements whose status and evidence disagree — never a silent
    ``checked``)."""

    claims: dict
    requirements: dict
    evaluators: dict
    milestones: dict
    readiness: str
    counts: dict
    disagree: dict


def _token(status: Any, errored: bool) -> str:
    return "errored" if errored else claims.STATUS_KEY[status]


def tokens(view: Any, resolution: Any, registry: Any, *,
           composed: Mapping[str, Any] | None = None) -> Tokens:
    """The tokens of ``view`` as `status` composes it: ``composed`` defaults to
    `claims.compositions` over ``resolution``'s stale gates — never a sweep's
    overlay, so `merge` (phase 4) can recompute it without running anything."""
    from . import report                         # a reader's module: not at import
    stale = getattr(resolution, "stale_gates", frozenset())
    if composed is None:
        composed = claims.compositions(view, registry=registry, stale_gates=stale)
    cover = claims.effective_gates(view, registry)
    claim_tokens = {cid: _token(c.status, c.errored)
                    for cid, c in sorted(composed.items(), key=lambda kv: _natural(kv[0]))}
    found = report.requirement_statuses(view, composed, cover)
    requirement_tokens = {rid: _token(row.status, row.errored)
                          for rid, row in sorted(found.items(), key=lambda kv: _natural(kv[0]))}
    by_gate: dict[str, Any] = {}
    for verdict in getattr(view, "verdicts", None) or ():
        by_gate.setdefault(verdict.gate, verdict)
    rows = getattr(resolution, "rows", None) or {}
    evaluators: dict[str, dict] = {}
    for gid in sorted((spec.id for spec in _specs(registry)), key=_natural):
        row = rows.get(gid)
        entry = getattr(row, "entry", None)
        evaluators[gid] = {
            "outcome": claims.outcome_key(by_gate.get(gid)),
            "state": str(getattr(row, "state", "") or "never") if row is not None else "never",
            "current": bool(row is not None and row.fresh and gid not in stale),
            "entry": entry.name if entry is not None else None}
    milestones = {m.id: ("ready" if claims.unresolved(view, composed, m).ready else "not-ready")
                  for m in sorted(getattr(view, "milestones", None) or (),
                                  key=lambda m: _natural(m.id))}
    readiness = "ready" if claims.unresolved(view, composed).ready else "not-ready"
    summary = claims.summarise(view, registry, stale_gates=stale)
    counts = {**{k: int(v) for k, v in summary["counts"].items()},
              "errored": int(summary["errored"])}
    by_id = {c.id: c for c in getattr(view, "claims", None) or ()}
    disagree_claims = [cid for cid in claim_tokens
                       if cid in by_id and report._disagreement(view, by_id[cid],
                                                                composed[cid], cover)]
    disagree_requirements = [rid for rid in requirement_tokens if found[rid].disagree]
    return Tokens(claim_tokens, requirement_tokens, evaluators, milestones, readiness,
                  counts, {"claims": disagree_claims, "requirements": disagree_requirements})


__all__ = [
    "SCHEMA", "NODE_KINDS", "EDGE_TYPES", "VALUE_ROLES",
    "Node", "Edge", "Trace", "Graph", "Tokens",
    "node_id", "value_names", "derived_names", "served_reads", "value_sources", "observe",
    "build", "tokens", "of", "upward",
]
