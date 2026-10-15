# SPDX-License-Identifier: Apache-2.0
"""The typed graph (SPEC decision 19, architecture phase 3a).

Each edge type has one source, and only that source makes one; the graph is the
same bytes on every machine, every path and every Python; no edge moves a
status (invariant 12); the observed parameter view says what the graph says;
and a record pointer the graph cannot follow is named, never followed.

What slipped through before the graph: no record linked C1's pass to the
assumption its load came from (C6), so an assumption nobody confirmed sat under
a Checked claim with nothing on any channel saying so; and `Param.gates` was
read from `obs/`, which a fresh clone does not have, so the same project drew
different lines on two machines.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_graph.py'
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from typing import Any, NamedTuple
from unittest import mock

import _env
import _projects
from nopekit import claims as claims_mod
from nopekit import cli, graph, report as report_mod, store, util, verdicts
from nopekit.models import Claim, ClaimKind, ClaimStatus, PhysicalResult
from nopekit.util import NopekitError

NOW = "2026-10-15T00:00:00Z"


class World(NamedTuple):
    root: str
    ledger: Any
    registry: Any
    model: Any
    projection: Any
    view: Any
    resolution: Any
    views: list


def resolve(root: str) -> World:
    """The project at ``root`` as `status` resolves it, in process."""
    ledger = cli._load(root)
    registry, _ = cli._registry(root, ledger)
    model, projection, error = cli._projection_safe(root, ledger)
    view, resolution = cli._resolved(root, ledger, registry, projection, error, now=NOW,
                                     model=model)
    views = cli._shown_params(root, ledger, model, error, resolution, registry,
                              projection=projection)
    return World(root, ledger, registry, model, projection, view, resolution, views)


def graph_of(world: World, **kw: Any) -> graph.Graph:
    kw.setdefault("view", world.view)
    kw.setdefault("resolution", world.resolution)
    kw.setdefault("registry", world.registry)
    kw.setdefault("views", world.views)
    return graph.of(world.root, kw.pop("view"), kw.pop("resolution"), kw.pop("registry"),
                    projection=world.projection, model=world.model,
                    bases=cli._input_bases(world.root, world.ledger), **kw)


def _shared_bracket(cls: type) -> str:
    tmp = tempfile.mkdtemp(prefix="nopekit-graph-")
    cls.addClassCleanup(_env._rmtree, tmp)
    return _projects.bracket_copy(os.path.join(tmp, "bracket"), migrated=True)


def edges_of(built: graph.Graph, type_: str) -> set[tuple[str, str]]:
    return {(e.source, e.target) for e in built.edges if e.type == type_}


class _Stub(NamedTuple):
    key: str
    derives: tuple


class _Full(NamedTuple):
    """A trace as `derivation.TraceFile` hands it (architecture phase 3b)."""

    key: str
    round: int
    derives: tuple
    after: tuple


class _Registry:
    """A registry stand-in over ``specs`` — the duck type `claims._specs` reads."""

    def __init__(self, specs: list) -> None:
        self._specs = list(specs)

    def specs(self) -> list:
        return list(self._specs)

    def ids(self) -> list:
        return [s.id for s in self._specs]


# --------------------------------------------------------------------------- #
class EveryEdgeHasItsSource(_env.EnvCase):
    """Each edge type comes from its one source and nothing else, on the bracket
    and on planted violators."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.world = resolve(_shared_bracket(cls))
        cls.graph = graph_of(cls.world)

    def test_the_brackets_graph(self):
        g = self.graph
        self.assertIn(("claim:C1", "requirement:R1"), edges_of(g, "serves"))
        self.assertIn(("evaluator:bracket.deflection", "claim:C1"), edges_of(g, "settles"))
        self.assertTrue({("evaluator:bracket.deflection", "value:load_n"),
                         ("evaluator:bracket.deflection", "value:deflection")}
                        <= edges_of(g, "reads"))
        self.assertEqual(edges_of(g, "needs"),
                         {("evaluator:bracket.deflection", "evaluator:bracket.model_validity"),
                          ("evaluator:bracket.bending_stress",
                           "evaluator:bracket.model_validity")})
        self.assertEqual(edges_of(g, "requires"),
                         {("milestone:print-v1", f"claim:C{i}") for i in range(1, 5)})
        self.assertEqual(edges_of(g, "sources"), {("claim:C6", "value:load_n")})
        self.assertEqual(edges_of(g, "rests_on"), {("claim:C1", "claim:C6")})
        self.assertEqual(g.via("C1", "C6"), (("bracket.deflection", "load_n", "load_n"),))
        decision = next(d for d in self.world.ledger.decisions if d.id == "print-in-petg")
        self.assertEqual(edges_of(g, "decides"),
                         {("decision:print-in-petg", f"value:{n}")
                          for n in decision.params_changed}
                         | {("decision:print-in-petg", f"claim:{c}")
                            for c in decision.claims_changed})
        self.assertEqual(g.to_dict()["edges"]["derives"], {})
        self.assertIsNone(g.trace)
        self.assertIsNotNone(g.node("instruction:model/bracket.py"))
        self.assertIsNotNone(g.instructions)
        self.assertEqual(g.node("value:thickness").attrs["role"], "choice")
        self.assertEqual(g.node("value:deflection").attrs["role"], "derived")

    def test_the_design_is_the_articles_reading(self):
        """`verdicts.design_of` is `article_of`'s body, extracted: the bracket's
        article hash is the one c26fcd5 named before the extraction, and the seal
        of the design the graph and the round record read."""
        w = self.world
        article = verdicts.article_of(w.root, w.projection, w.model, resolution=w.resolution)
        design = verdicts.design_of(w.root, w.projection, w.model,
                                    anchors=w.resolution.anchors, resolution=w.resolution)
        self.assertEqual(article["hash"],
                         "4d7abe16745d2b34e0335fba57185a02bef309fe96808a611d43af6119913052")
        self.assertEqual(article["hash"], util.seal(design))
        self.assertEqual(self.graph.instructions, util.seal(design["model"]))

    def test_reads_are_the_served_entries(self):
        g = self.graph
        rows = self.world.resolution.rows
        for spec in self.world.registry.specs():
            entry = rows[spec.id].entry
            self.assertIsNotNone(entry, spec.id)
            names = {name for item in entry.reads["params"]
                     for name in graph.value_names(item[0], self.world.projection["config"])}
            self.assertEqual({t.split(":", 1)[1] for t in g.out(f"evaluator:{spec.id}",
                                                                 "reads")},
                             names, spec.id)

    def test_obs_and_the_last_read_sets_never_move_it(self):
        """A planted obs run naming other reads — what `Resolution.read_sets`
        carries — and a wiped `obs/` give the same graph."""
        before = self.graph.to_dict()
        planted = {"bracket.deflection": {("config", "thickness")},
                   "bracket.min_wall": {("config", "width")}}
        with mock.patch.object(verdicts, "last_read_sets", lambda root: planted):
            world = resolve(self.world.root)
        self.assertEqual(world.resolution.read_sets, planted)
        self.assertEqual(graph_of(world).to_dict(), before)
        _env._rmtree(os.path.join(self.world.root, ".nopekit", "obs"))
        self.assertEqual(graph_of(resolve(self.world.root)).to_dict(), before)

    def test_a_never_run_evaluator_has_a_node_and_no_reads(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)
        _env._rmtree(os.path.join(root, ".nopekit", "verdicts", "bracket.min_wall"))
        g = graph_of(resolve(root))
        self.assertIsNotNone(g.node("evaluator:bracket.min_wall"))
        self.assertEqual(g.out("evaluator:bracket.min_wall", "reads"), ())
        self.assertIn(("evaluator:bracket.min_wall", "claim:C4"), edges_of(g, "settles"))

    def test_the_whole_config_reads_every_choice(self):
        choices = self.world.projection["config"]
        self.assertEqual(set(graph.value_names(["config"], choices)), set(choices))
        self.assertEqual(graph.value_names(["config", "thickness", "x"], choices),
                         ("thickness",))
        self.assertEqual(graph.value_names(["deflection"], choices), ("deflection",))
        self.assertEqual(graph.value_names([3], choices), ())
        rows = dict(self.world.resolution.rows)
        row = rows["bracket.model_validity"]
        reads = dict(row.entry.reads, params=[[["config"], "x"]])
        rows["bracket.model_validity"] = dataclasses.replace(
            row, entry=dataclasses.replace(row.entry, reads=reads))
        g = graph_of(self.world,
                     resolution=dataclasses.replace(self.world.resolution, rows=rows))
        self.assertEqual({t.split(":", 1)[1]
                          for t in g.out("evaluator:bracket.model_validity", "reads")},
                         set(choices))

    def test_a_read_of_the_whole_params_reads_every_value(self):
        """A gate that takes ``ctx.params.copy()`` (or ``.items()``, or
        ``json.dumps``) records one bare path, ``[]`` — the whole level. That
        is a read of every value the flat projection holds, so the gate draws
        a ``reads`` edge to each, its claim rests on the assumption one of
        them is, and ``read_by`` names it. What slipped through (review of
        phase 3a): ``[]`` read nothing, and C1 rested on nothing."""
        trace = verdicts.GateTrace()
        bulk = verdicts.ParamTrace({"load_n": 1.0, "stress": 2.0}, trace)
        self.assertEqual(bulk.copy()["load_n"], 1.0)
        list(bulk.items())
        self.assertEqual(list(trace.params), [()])
        choices = self.world.projection["config"]
        derived = graph.derived_names(self.world.projection)
        self.assertIn("deflection", derived)
        self.assertNotIn("config", derived)
        self.assertEqual(set(graph.value_names([], choices, derived)),
                         set(choices) | set(derived))
        self.assertEqual(set(graph.value_names((), choices)), set(choices))
        rows = dict(self.world.resolution.rows)
        row = rows["bracket.deflection"]
        reads = dict(row.entry.reads, params=[[[], "x"]])
        rows["bracket.deflection"] = dataclasses.replace(
            row, entry=dataclasses.replace(row.entry, reads=reads))
        resolution = dataclasses.replace(self.world.resolution, rows=rows)
        g = graph_of(self.world, resolution=resolution)
        self.assertEqual({t.split(":", 1)[1]
                          for t in g.out("evaluator:bracket.deflection", "reads")},
                         set(choices) | set(derived))
        self.assertIn(("claim:C1", "claim:C6"), edges_of(g, "rests_on"))
        self.assertIn("bracket.deflection", g.read_by("load_n"))
        views = graph.observe(self.world.views, ledger=self.world.ledger,
                              resolution=resolution, registry=self.world.registry,
                              choices=choices, derived=derived)
        for view in views:
            self.assertEqual(view.read_by, g.read_by(view.name), view.name)
        load = next(v for v in views if v.name == "load_n")
        self.assertIn("bracket.deflection", load.read_by)

    def test_an_evaluators_crash_token_is_error(self):
        """The round record's evaluator outcome for a crash is `error` — a
        claim's is `errored` — and `outcome_key`'s docstring names every token
        it can return. What slipped through (review of phase 3a): it named
        `errored`, a token it never returns."""
        from nopekit.models import Verdict
        crashed = Verdict(gate="g.x", passed=False, error="boom")
        self.assertEqual(crashed.outcome, "error")
        self.assertEqual(claims_mod.outcome_key(crashed), "error")
        self.assertEqual(claims_mod.outcome_key(None), "unrun")
        doc = claims_mod.outcome_key.__doc__
        for token in (*claims_mod.OUTCOME_ORDER, "unrun"):
            self.assertIn(f"`{token}`", doc, token)
        self.assertNotIn("`errored`, `skipped`", doc)

    def test_a_contradiction_survives_a_deleted_claim_file(self):
        fail = PhysicalResult(passed=False, when=NOW, who="A Person", channel="interactive",
                              contradicts=[{"gate": "bracket.deflection", "code": "x",
                                            "inside": True}])
        gone = Claim(id="C9", statement="", kind=ClaimKind.PHYSICAL, critical=True,
                     physical_result=fail, results=(fail,))
        ledger = dataclasses.replace(self.world.ledger, removed=(gone,))
        resolution = dataclasses.replace(self.world.resolution,
                                         track=verdicts.track_record(ledger))
        view = verdicts.view(ledger, resolution)
        g = graph_of(self.world, view=view, resolution=resolution)
        self.assertTrue(g.node("claim:C9").attrs["removed"])
        self.assertEqual(edges_of(g, "contradicts"),
                         {("claim:C9", "evaluator:bracket.deflection")})

    def test_an_unregistered_prerequisite_is_a_node_registered_false(self):
        specs = [dataclasses.replace(s, needs=["pack.gone"]) if s.id == "bracket.min_wall"
                 else s for s in self.world.registry.specs()]
        g = graph_of(self.world, registry=_Registry(specs))
        node = g.node("evaluator:pack.gone")
        self.assertEqual(dict(node.attrs), {"pack": None, "basis": None, "tier": None,
                                            "registered": False})
        self.assertIn(("evaluator:bracket.min_wall", "evaluator:pack.gone"),
                      edges_of(g, "needs"))

    def test_a_pointer_to_no_assumption_makes_no_edge(self):
        view = self.world.view
        claims = [dataclasses.replace(c, resolves=["C1", "C6", "C99"]) if c.id == "C5" else c
                  for c in view.claims]
        params = [dataclasses.replace(p, grounded_by=["C1", "C99"]) for p in view.params]
        views = [dataclasses.replace(v, grounded_by=("C1", "C99")) if v.grounded_by else v
                 for v in self.world.views]
        g = graph_of(self.world, view=dataclasses.replace(view, claims=claims, params=params),
                     views=views)
        self.assertEqual(edges_of(g, "resolves"), {("claim:C5", "claim:C6")})
        self.assertEqual(edges_of(g, "sources"), set())
        self.assertEqual(edges_of(g, "rests_on"), set())
        # A measurable claim naming an assumption resolves nothing either.
        claims = [dataclasses.replace(c, resolves=["C6"]) if c.id == "C1" else c
                  for c in view.claims]
        g = graph_of(self.world, view=dataclasses.replace(view, claims=claims))
        self.assertEqual(edges_of(g, "resolves"), set())

    def test_an_input_sources_a_value_with_its_proposer_and_basis(self):
        """An input whose extraction grounds a choice is an `input:<id>` node
        carrying its proposer and the basis looked up from it, and a `sources`
        edge to the value — in the graph, the observed view and `why`. What
        slipped through (review of phase 3a): the bracket has no inputs, so
        dropping the input branch, or blanking proposer and basis, passed."""
        import hashlib
        import _decisions
        root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)
        os.makedirs(os.path.join(root, "inputs", "data"))
        with open(os.path.join(root, "inputs", "data", "arm.txt"), "wb") as fh:
            fh.write(b"the shelf is 60 mm deep\n")
        _decisions.write_json(os.path.join(root, "inputs", "shelf.json"), {
            "path": "inputs/data/arm.txt", "kind": "data",
            "sha256": hashlib.sha256(b"the shelf is 60 mm deep\n").hexdigest(),
            "extractions": [{"what": "the shelf is 60 mm deep", "grounds": ["arm_length"]}],
            "proposer": _decisions.PROPOSER_ID})
        base, _name = _decisions.fixture_pack(self.tmp())
        with mock.patch.dict(os.environ, {"NOPEKIT_PACK_PATH": base}):
            world = resolve(root)
            g = graph_of(world)
            _code, out, _err = _main(root, "why", "arm_length")
        node = g.node("input:shelf")
        self.assertIsNotNone(node)
        self.assertEqual(dict(node.attrs), {"proposer": _decisions.PROPOSER_ID,
                                            "basis": "sourced"})
        self.assertIn(("input:shelf", "value:arm_length"), edges_of(g, "sources"))
        self.assertEqual(g.sourced_from("arm_length"), ("input:shelf",))
        arm = next(v for v in world.views if v.name == "arm_length")
        self.assertEqual(arm.sourced_from, ("input:shelf",))
        self.assertIn("sourced from: input shelf", " ".join(out.split()))

    def test_every_edge_joins_two_nodes(self):
        ids = {n.id for n in self.graph.nodes}
        self.assertGreater(len(self.graph.edges), 20)
        for edge in self.graph.edges:
            self.assertIn(edge.source, ids, edge)
            self.assertIn(edge.target, ids, edge)
            self.assertIn(edge.type, graph.EDGE_TYPES)

    def test_a_trace_slots_in(self):
        """Phase 3b's trace only adds derives edges: rests_on already closes a
        read value over them, so C2 rests on C6 through the stress it read."""
        trace = _Stub("k" * 64, (("load_n", "stress_root"),))
        g = graph_of(self.world, trace=trace)
        self.assertEqual(g.trace, "k" * 64)
        self.assertEqual(edges_of(g, "derives"), {("value:load_n", "value:stress_root")})
        self.assertIn(("claim:C2", "claim:C6"), edges_of(g, "rests_on"))
        self.assertEqual(g.via("C2", "C6"), (("bracket.bending_stress", "stress_root",
                                               "load_n"),))
        self.assertIsNone(self.graph.trace)
        # Schema 2 (architecture phase 3b): the trace is an object; a stub with
        # no round and no after edges still slots in.
        self.assertEqual(g.to_dict()["schema"], 2)
        self.assertEqual(g.to_dict()["trace"], {"key": "k" * 64, "round": None})
        self.assertEqual(g.to_dict()["edges"]["after"], {})

    def test_after_edges_order_and_never_mean(self):
        """`after` (architecture phase 3b) orders derived values for drawing:
        `upstream`, `depths` and `direct_derives` read it; `rests_on` does
        not — the same edges with and without it."""
        derives = (("load_n", "stress_root"), ("thickness", "inertia"),
                   ("width", "inertia"), ("thickness", "stress_root"),
                   ("width", "stress_root"))
        bare = graph_of(self.world, trace=_Stub("k" * 64, derives))
        full = graph_of(self.world, trace=_Full("k" * 64, 4, derives,
                                                (("inertia", "stress_root"),)))
        self.assertEqual(edges_of(full, "after"), {("value:inertia", "value:stress_root")})
        self.assertEqual(full.to_dict()["trace"], {"key": "k" * 64, "round": 4})
        self.assertEqual(full.trace_round, 4)
        self.assertEqual(edges_of(full, "rests_on"), edges_of(bare, "rests_on"))
        self.assertEqual(graph.upstream(full, "value:stress_root"), ["value:inertia"])
        self.assertEqual(graph.depths(full)["stress_root"], 1)
        self.assertEqual(graph.depths(full)["inertia"], 0)
        direct = graph.direct_derives(full)
        self.assertIn(("load_n", "stress_root"), direct)
        self.assertIn(("thickness", "inertia"), direct)
        self.assertNotIn(("thickness", "stress_root"), direct,
                         "a choice that moves the value before it feeds that value")
        self.assertEqual(full.moves("thickness"), ("inertia", "stress_root"))
        self.assertEqual(full.moved_by("inertia"), ("thickness", "width"))
        self.assertEqual(graph.ties_of(full), [])


# --------------------------------------------------------------------------- #
def sentinel_words() -> Any:
    """`report.HUMAN` with every word table a sentinel can reach replaced."""
    import test_vocabulary
    return test_vocabulary.sentinel_human()


class TheGraphIsDeterministic(_env.EnvCase):
    """The same records, cache and design give the same graph bytes: whatever
    order a directory lists in, wherever the project lives, whatever the words
    say, and under any hash seed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.world = resolve(_shared_bracket(cls))
        cls.bytes = json.dumps(graph_of(cls.world).to_dict(), sort_keys=False)

    def test_listing_order_moves_nothing(self):
        real = os.listdir

        def reversed_listing(path="."):
            return list(reversed(sorted(real(path))))

        with mock.patch.object(os, "listdir", reversed_listing):
            again = json.dumps(graph_of(resolve(self.world.root)).to_dict())
        self.assertEqual(again, self.bytes)

    def test_another_path_moves_nothing(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "elsewhere", "b"),
                                      migrated=True)
        self.assertEqual(json.dumps(graph_of(resolve(root)).to_dict()), self.bytes)

    def test_words_move_nothing_and_no_statement_is_written(self):
        with mock.patch.object(report_mod, "HUMAN", sentinel_words()):
            again = json.dumps(graph_of(resolve(self.world.root)).to_dict())
        self.assertEqual(again, self.bytes)
        for claim in self.world.ledger.claims:
            self.assertNotIn(claim.statement, self.bytes)

    def test_two_hash_seeds_give_the_same_bytes(self):
        script = ("import json, sys; sys.path.insert(0, sys.argv[1]); import test_graph; "
                  "w = test_graph.resolve(sys.argv[2]); "
                  "print(json.dumps(test_graph.graph_of(w).to_dict()))")
        outs = []
        for seed in ("0", "12345"):
            proc = _env.run([sys.executable, "-c", script, _env.REPO + "/tests",
                             self.world.root], cwd=self.world.root,
                            env={"PYTHONHASHSEED": seed})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            outs.append(proc.stdout)
        self.assertEqual(outs[0], outs[1])
        self.assertEqual(outs[0].strip(), self.bytes)


# --------------------------------------------------------------------------- #
def status_facts(world: World) -> dict:
    """Everything a status reader says, from its one producer each."""
    stale = world.resolution.stale_gates
    composed = claims_mod.compositions(world.view, registry=world.registry, stale_gates=stale)
    cover = claims_mod.effective_gates(world.view, world.registry)
    summary = claims_mod.summarise(world.view, world.registry, stale_gates=stale)
    return {
        "claims": {cid: (str(c.status), str(c.cause), c.errored) for cid, c in composed.items()},
        "summary": {k: summary[k] for k in ("counts", "errored", "unresolved_ids",
                                            "all_required_checked", "requirements")},
        "requirements": {rid: (str(r.status), r.errored, r.disagree)
                         for rid, r in report_mod.requirement_statuses(
                             world.view, composed, cover).items()},
        "readiness": report_mod.readiness(world.view, composed)["ready"],
        "milestones": {m.id: claims_mod.unresolved(world.view, composed, m).ready
                       for m in world.view.milestones},
    }


def edge_status_problems(before: dict, after: dict) -> list[str]:
    """Every status fact that differs between two worlds that differ only in
    their edges (invariant 12: an edge says what a pass stands on; it moves no
    status)."""
    out = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            out.append(f"{key}: {before.get(key)!r} -> {after.get(key)!r}")
    return out


class AnEdgeChangesNoStatus(_env.EnvCase):
    """Invariant 12: no reader says more — or less — than the composition, and an
    edge is not a composition input. With and without `params/load_n.json` (C1
    rests on C6) and a physical claim's `resolves`, every status, count,
    requirement and readiness is the same."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _shared_bracket(cls)
        cls.with_edges = resolve(cls.root)
        path = os.path.join(cls.root, "params", "load_n.json")
        os.remove(path)
        cls.without = resolve(cls.root)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{\n  "grounded_by": [\n    "C6"\n  ]\n}\n')
        c5 = os.path.join(cls.root, "claims", "C5.json")
        with open(c5, encoding="utf-8") as fh:
            data = json.load(fh)
        data["resolves"] = ["C6"]
        with open(c5, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        cls.resolving = resolve(cls.root)

    def test_the_edges_exist(self):
        self.assertEqual(edges_of(graph_of(self.without), "rests_on"), set())
        g = graph_of(self.resolving)
        self.assertEqual(edges_of(g, "rests_on"), {("claim:C1", "claim:C6")})
        self.assertEqual(edges_of(g, "resolves"), {("claim:C5", "claim:C6")})

    def test_no_status_moves(self):
        base = status_facts(self.without)
        self.assertEqual(edge_status_problems(base, status_facts(self.with_edges)), [])
        self.assertEqual(edge_status_problems(base, status_facts(self.resolving)), [])
        self.assertEqual(
            graph.tokens(self.without.view, self.without.resolution, self.without.registry),
            graph.tokens(self.resolving.view, self.resolving.resolution,
                         self.resolving.registry))

    def test_a_composer_that_reads_an_edge_is_caught(self):
        resting = {cid for cid in ("C1",)
                   if graph_of(self.resolving).rests_on(cid)}
        real = claims_mod.compose

        def downgraded(claim, *args, **kwargs):
            found = real(claim, *args, **kwargs)
            if claim.id in resting:
                return claims_mod.Composed(ClaimStatus.UNCLAIMED,
                                           claims_mod.ClaimCause.NO_EVALUATOR)
            return found

        with mock.patch.object(claims_mod, "compose", downgraded):
            planted = status_facts(self.resolving)
        problems = edge_status_problems(status_facts(self.without), planted)
        self.assertTrue(any(p.startswith("claims:") for p in problems), problems)


# --------------------------------------------------------------------------- #
class ObservedViewAgreesWithTheGraph(_env.EnvCase):
    """`graph.observe` fills each parameter view's `read_by` and `sourced_from` by
    the graph's own rule, and the views `check` and the page write carry them."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.world = resolve(_shared_bracket(cls))

    def test_observe_says_what_the_graph_says(self):
        g = graph_of(self.world)
        self.assertTrue(self.world.views)
        for view in self.world.views:
            self.assertEqual(view.read_by, g.read_by(view.name), view.name)
            self.assertEqual(view.sourced_from, g.sourced_from(view.name), view.name)
        load = next(v for v in self.world.views if v.name == "load_n")
        self.assertEqual(load.read_by, ("bracket.deflection",))
        self.assertEqual(load.sourced_from, ("claim:C6",))
        self.assertEqual(load.to_dict()["sourced_from"], ["claim:C6"])

    def test_last_check_and_the_page_carry_them(self):
        root = self.world.root
        code, _out, err = _main(root, "check")
        self.assertIn(code, (0, 1), err)
        path = os.path.join(root, ".nopekit", "cache", "last_check.json")
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)["params"]
        self.assertEqual(rows["load_n"]["read_by"], ["bracket.deflection"])
        self.assertEqual(rows["load_n"]["sourced_from"], ["claim:C6"])
        for name, row in rows.items():
            self.assertIn("read_by", row, name)
            self.assertIn("sourced_from", row, name)
        from nopekit import site
        world = resolve(root)
        state = site.state(root, world.view, world.registry, now=NOW,
                           resolution=world.resolution, params=world.views)
        rows = {row["name"]: row for row in state["params"]}
        self.assertEqual(rows["load_n"]["read_by"], ["bracket.deflection"])
        self.assertEqual(rows["load_n"]["sourced_from"], ["claim:C6"])


#: `why <name>` and the lines its graph must give it (architecture phase 3a,
#: SPEC 10 and 19), on the bracket — C5 made to resolve C6 by `why_project`.
_WHY_LINES = (
    ("load_n", ("read by: bracket.deflection", "sourced from: assumption C6 (gap)")),
    ("C1", ("rests on: C6 (gap; bracket.deflection read load_n)",
            "rests on, through derived values: not traced yet")),
    ("C2", ("rests on, through derived values: not traced yet",)),
    ("deflection", ("value deflection = ", "(derived by build() in model/bracket.py)",
                    "read by: bracket.deflection", "derived from: not traced yet")),
    ("C5", ("resolves: C6 (gap)",)),
    ("C6", ("resolved by: C5 (pending build)",)),
)


def why_project(dest: str) -> str:
    """A bracket copy whose physical claim C5 resolves assumption C6, without
    its committed trace: these are the untraced words (architecture phase 3b's
    traced ones are `test_derivation`'s)."""
    root = _projects.bracket_copy(dest, migrated=True)
    _env._rmtree(os.path.join(root, ".nopekit", "trace"))
    path = os.path.join(root, "claims", "C5.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["resolves"] = ["C6"]
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return root


def why_problems(root: str) -> list[str]:
    """Each line of `_WHY_LINES` that `why` does not print, unwrapped."""
    problems = []
    for name, lines in _WHY_LINES:
        code, out, err = _main(root, "why", name)
        flat = " ".join(out.split())
        if code != 0:
            problems.append(f"why {name} exited {code}: {err}")
            continue
        for line in lines:
            if " ".join(line.split()) not in flat:
                problems.append(f"why {name}: no {line!r}")
    return problems


class WhySaysWhatTheGraphSays(_env.EnvCase):
    """`why` prints the graph's lines: what reads a value and what sources it,
    what a claim rests on (and that derivation is not traced yet), what it
    resolves and what resolves it, and a derived value an evaluator read. What
    slipped through (review of phase 3a): no test held one of these words, so a
    `why` handed no graph dropped every one and the suite stayed green."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.mkdtemp(prefix="nopekit-why-")
        cls.addClassCleanup(_env._rmtree, tmp)
        cls.root = why_project(os.path.join(tmp, "b"))

    def test_every_line(self):
        self.assertEqual(why_problems(self.root), [])
        _code, out, _err = _main(self.root, "why", "deflection")
        self.assertTrue(out.startswith("value deflection = "), out)

    def test_a_why_handed_no_graph_is_caught(self):
        from nopekit import decisions
        real = decisions.why

        def no_graph(*args, **kwargs):
            kwargs.pop("graph", None)
            return real(*args, **kwargs)

        with mock.patch.object(decisions, "why", no_graph):
            problems = why_problems(self.root)
        missed = {p.split(":", 1)[0].split()[1] for p in problems}
        self.assertEqual(missed, {name for name, _lines in _WHY_LINES}, problems)

    def test_swapped_lists_are_caught(self):
        from nopekit import decisions
        real = decisions._value_graph_lines

        def swapped(ledger, read_by, sourced_from, evidence):
            return real(ledger, sourced_from, read_by, evidence)

        with mock.patch.object(decisions, "_value_graph_lines", swapped):
            problems = why_problems(self.root)
        self.assertTrue(any("why load_n: no 'read by" in p for p in problems), problems)
        self.assertTrue(any("why load_n: no 'sourced from" in p for p in problems), problems)


def _main(root: str, *argv: str) -> tuple[int, str, str]:
    import contextlib
    import io
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["-C", root, *argv])
    return code, out.getvalue(), err.getvalue()


# --------------------------------------------------------------------------- #
def _claim_file(root: str, stem: str, data: dict) -> str:
    path = os.path.join(root, "claims", f"{stem}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path


class PointersAreChecked(_env.EnvCase):
    """What can never be right is refused by the strict reader; a pointer the
    graph cannot follow is read, and named by the index and doctor's `graph`
    row; a derived list written into a record is refused, naming its home."""

    PHYSICAL = {"statement": "the print holds", "kind": "physical"}

    def _refused(self, data: dict, stem: str = "C8") -> str:
        path = _claim_file(self.tmp(), stem, data)
        with self.assertRaises(NopekitError) as caught:
            store.read_record(path, "claims")
        return str(caught.exception)

    def test_the_strict_reader_refuses_what_can_never_be_right(self):
        label = "claims/C8.json"
        said = self._refused(dict(self.PHYSICAL, resolves="C6"))
        self.assertIn('"resolves" must be a list, each item a claim id (the stem of a file '
                      'in claims/) — not "C6"', said)
        said = self._refused(dict(self.PHYSICAL, resolves=["C 6"]))
        self.assertIn('"resolves"[0] "C 6" is not a claim id', said)
        said = self._refused(dict(self.PHYSICAL, resolves=["C6", "C6"]))
        self.assertIn('"resolves" names C6 twice', said)
        said = self._refused(dict(self.PHYSICAL, resolves=["C8"]))
        self.assertIn('"resolves" names C8 itself — a test resolves an assumption, never '
                      'itself', said)
        said = self._refused({"statement": "s", "kind": "measurable", "resolves": ["C6"]})
        self.assertIn('"resolves" is a physical claim\'s field — a physical test is what '
                      'replaces an assumption, and C8 is measurable', said)
        self.assertTrue(said.startswith(label) or label in said, said)
        path = _claim_file(self.tmp(), "C8", dict(self.PHYSICAL, resolves=["C6", "C99"]))
        self.assertEqual(store.read_record(path, "claims").resolves, ["C6", "C99"])

    def test_resolves_keeps_the_limit_check(self):
        """A physical claim with `resolves` is held to the text-limit refusal
        every claim is. What slipped through (review of phase 3a): the
        `resolves` check reassigned the reader's record kind, so a text limit
        beside it read, and `claim physical --measured` passed a value the
        typed limit refuted."""
        for key in ("limit", "limit_hi"):
            acceptance = {"quantity": "deflection", "comparator": "between",
                          "limit": 0.1, "limit_hi": 0.8, "units": "mm"}
            acceptance[key] = "0.8"
            for extra in ({}, {"resolves": ["C6"]}):
                said = self._refused(dict(self.PHYSICAL, acceptance=acceptance, **extra))
                self.assertIn(f'"acceptance.{key}" must be a number or null', said,
                              (key, extra))

    def test_the_index_names_each_pointer(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)
        with open(os.path.join(root, "params", "width.json"), "w", encoding="utf-8") as fh:
            json.dump({"grounded_by": ["C1", "nowhere"]}, fh)
        with open(os.path.join(root, "claims", "C5.json"), encoding="utf-8") as fh:
            c5 = json.load(fh)
        _claim_file(root, "C5", {**c5, "resolves": ["C6", "C2", "C99"]})
        problems = store.build_index(root)["problems"]
        self.assertIn("params/width.json: grounded_by names 'C1', a measurable claim — a value "
                      "is sourced from an input (inputs/<id>.json) or is an assumption (a claim "
                      "of kind assumption)", problems)
        # GLOSSARY's "sourced from" row: *grounded by* is its Never-say in prose
        # (the field name `grounded_by` is kept).
        self.assertFalse([p for p in problems if "grounded by" in p], problems)
        self.assertIn("params/width.json: grounded_by names 'nowhere', which has no "
                      "inputs/nowhere.json", problems)
        self.assertIn("claims/C5.json: resolves names 'C2', a measurable claim — a physical "
                      "test resolves an assumption (a claim of kind assumption)", problems)
        self.assertIn("claims/C5.json: resolves names 'C99', which has no claims/C99.json",
                      problems)
        self.assertFalse([p for p in problems if "'C6'" in p], problems)
        both = store.grounded_by_problem("params/x.json", "x", "C6", {"C6"},
                                         {"C6": "assumption"})
        self.assertEqual(both, "params/x.json: grounded_by names 'C6', which is both "
                               "inputs/C6.json and claims/C6.json — rename one; the graph "
                               "reads it as the input")
        self.assertIsNone(store.grounded_by_problem("p", "x", "C6", set(),
                                                    {"C6": "assumption"}))
        self.assertIsNone(store.grounded_by_problem("p", "x", "a", {"a"}, {}))

    def test_doctor_fails_on_a_pointer_and_is_ok_on_the_bracket(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)
        code, out, err = _main(root, "doctor", "--json")
        rows = [r for r in json.loads(out)["checks"] if r["check"] == "graph"]
        self.assertEqual([r["status"] for r in rows], ["ok"], rows)
        # The committed trace (architecture phase 3b): C1, C2 and C3 rest on
        # C6 through the values its load moves.
        self.assertIn("3 rests on", rows[0]["detail"])
        self.assertIn("derivation traced at round", rows[0]["detail"])
        _env._rmtree(os.path.join(root, ".nopekit", "trace"))
        code, out, err = _main(root, "doctor", "--json")
        rows = [r for r in json.loads(out)["checks"] if r["check"] == "graph"]
        self.assertIn("1 rests on", rows[0]["detail"])
        self.assertIn("derivation not traced yet", rows[0]["detail"])
        with open(os.path.join(root, "params", "load_n.json"), "w", encoding="utf-8") as fh:
            json.dump({"grounded_by": ["C1"]}, fh)
        code, out, err = _main(root, "doctor", "--json")
        rows = [r for r in json.loads(out)["checks"] if r["check"] == "graph"]
        self.assertEqual([r["status"] for r in rows], ["FAIL"], rows)
        self.assertEqual(code, 1)

    def test_a_derived_list_in_a_record_is_refused_naming_its_home(self):
        said = self._refused(dict(self.PHYSICAL, rests_on=["C6"]))
        self.assertIn('"rests_on" does not belong in this record — derived — a claim rests '
                      'on an assumption', said)
        for key in ("read_by", "sourced_from"):
            path = os.path.join(self.tmp(), "params", "load_n.json")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({key: ["x"]}, fh)
            with self.assertRaises(NopekitError) as caught:
                store.read_record(path, "params")
            self.assertIn(f'"{key}" does not belong in this record — derived',
                          str(caught.exception))


if __name__ == "__main__":
    unittest.main()
