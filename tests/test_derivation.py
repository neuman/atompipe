# SPDX-License-Identifier: Apache-2.0
"""The trace and amber (architecture phase 3b, SPEC 39): derivation observed by
perturbation, and a Checked pass an assumption's move flips.

The trace is keyed to its design and served only for it (invariant 7); it is
written once, whole, and never rewritten (invariant 8); amber moves no status,
exit code, readiness or export (invariant 12); the map draws what the trace
observed and no more (invariant 14); every build and every amber run happens in
a copy and writes nothing in the project (invariant 15); and the trace says
what it saw and no more — a choice it did not move or a value no move changed
is never said to be independent, and a trace a build did not finish is never
written (invariant 16).

What slipped through before this: the map drew each line from the values its
evaluators read, so 94 of PETGasus's 110 choices reached no claim and drew as
if nothing depended on them; and a pass at 0.8% margin on three unconfirmed
assumptions read as green as one at 80%.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_derivation.py'
"""
from __future__ import annotations

import ast
import contextlib
import re
import dataclasses
import enum
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from typing import Any
from unittest import mock

import _env
import _projects
from nopekit import claims as claims_mod
from nopekit import cli, derivation, graph, modelio, page, report, rounds, util, verdicts
from nopekit.util import NopekitError

NOW = "2026-10-15T00:00:00Z"
SRC = os.path.join(_env.REPO, "src", "nopekit")


def main(root: str, *argv: str) -> tuple[int, str, str]:
    """``nopekit <argv>`` in process against ``root``: (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["-C", root, *argv])
    return code, out.getvalue(), err.getvalue()


def bracket(test: Any, *, traced: bool = True) -> str:
    """A bracket copy as a clone holds it; without its committed trace when
    ``traced`` is False."""
    root = _projects.bracket_copy(os.path.join(test.tmp(), "b"), migrated=True)
    if not traced:
        _env._rmtree(os.path.join(root, ".nopekit", "trace"))
    return root


def amber_choices(root: str) -> dict:
    ledger = cli._load(root)
    model = modelio.load_model(root, ledger.meta.model_entry)
    out = {}
    for name, found in graph.value_sources(ledger, modelio.param_view(ledger, model)).items():
        aids = [nid.partition(":")[2] for nid in found if nid.startswith("claim:")]
        if aids:
            out[name] = aids
    return out


def trace_in_process(root: str, *, choices: Any = None, workers: int = 2, launch: Any = None,
                     round_: int | None = None, background: bool = False) -> derivation.Ran:
    """`nopekit model trace`'s run, in process: every build through
    `derivation.in_process` (or ``launch``) on its own copy."""
    ledger = cli._load(root)
    model = modelio.load_model(root, ledger.meta.model_entry)
    return derivation.run(root, plan=derivation.plan_of(model.config),
                          entry=ledger.meta.model_entry, amber_choices=amber_choices(root),
                          choices=choices, workers=workers,
                          launch=launch or derivation.in_process, now=NOW, round_=round_,
                          background=background)


def read_now(root: str) -> tuple:
    """``(traced, built, tokens, amber, view, resolution, registry)`` as
    `status` reads them, in process."""
    ledger = cli._load(root)
    registry, _ = cli._registry(root, ledger, strict=False)
    model, projection, error = cli._projection_safe(root, ledger)
    view, resolution = cli._resolved(root, ledger, registry, projection, error, now=NOW,
                                     model=model)
    traced = cli._trace_for(root, model, projection, resolution)
    params = cli._shown_params(root, ledger, model, error, resolution, registry,
                               projection=projection)
    built = graph.of(root, view, resolution, registry, projection=projection, model=model,
                     views=params, bases=cli._input_bases(root, ledger), trace=traced.trace)
    toks = graph.tokens(view, resolution, registry)
    amber = cli._amber_for(root, view, registry, built, toks.claims, traced)
    return traced, built, toks, amber, view, resolution, registry


def files_of(root: str) -> dict:
    """``{relpath: (bytes, mtime_ns)}`` of every file under ``root``."""
    out = {}
    for here, _dirs, names in os.walk(root):
        for name in names:
            path = os.path.join(here, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            with open(path, "rb") as fh:
                out[rel] = (fh.read(), os.stat(path).st_mtime_ns)
    return out


def edit(path: str, old: str, new: str) -> None:
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if old not in text:
        raise AssertionError(f"{old!r} is not in {path}")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new, 1))


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def trace_files(root: str) -> list[str]:
    folder = derivation.trace_dir(root)
    return sorted(os.listdir(folder)) if os.path.isdir(folder) else []


def tight_c3(root: str) -> None:
    """C3 Checked at a 2.5% margin (0.195 MPa against 0.2) on a bearing stress
    the load moves, and the load is assumption C6's: a +10% move flips it."""
    path = os.path.join(root, "claims", "C3.json")
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data["acceptance"]["limit"] = 0.2
    write_json(path, data)


# --------------------------------------------------------------------------- #
class TheTraceObserves(_env.EnvCase):
    """What a move is, how a move is stored, and what is never compared."""

    def test_the_nudge_table(self):
        class Kind(enum.Enum):
            A = 1

        table = [(14, (13, 15), ""), (25, (23, 27), ""), (1, (0, 2), ""), (-20, (-18, -22), ""),
                 (-20.0, (-18.0, -22.0), ""),
                 (60.0, (54.0, 66.0), ""), (True, (), "yes-no"), ("petg", (), "word"),
                 (None, (), "none"), ([1, 2], (), "structure"), ({"a": 1}, (), "structure"),
                 (Kind.A, (), "structure"), (float("nan"), (), "not-finite"),
                 (float("inf"), (), "not-finite"), (0, (), "zero"), (0.0, (), "zero")]
        for value, steps, skipped in table:
            with self.subTest(value=value):
                found = derivation.nudges("x", value)
                self.assertEqual((tuple(round(s, 9) for s in found.steps), found.skipped),
                                 (steps, skipped))
        self.assertEqual(derivation.nudges("x", 5.0, settable=False).skipped, "fixed")
        self.assertTrue(all(isinstance(s, int) for s in derivation.nudges("x", 14).steps))
        self.assertEqual(set(derivation.SKIP), set(report.HUMAN["trace"]["skip"]))

    def test_an_integers_move_says_its_size(self):
        """Review of phase 3b: ``n_bolts = 2`` moved to 1 and 3 and every label
        said ±10%; a negative integer's ``-10%`` was x1.1 where a negative
        real's was x0.9; a float field holding ``2`` moved to integers."""
        two = derivation.nudges("n", 2)
        self.assertEqual((two.steps, two.change), ((1, 3), (-0.5, 0.5)))
        self.assertEqual([derivation.step_word(d, two.change) for d in (0, 1)],
                         ["-50%", "+50%"])
        self.assertEqual([derivation.step_word(d, None) for d in (0, 1)], ["-10%", "+10%"])
        self.assertEqual(derivation.nudges("o", -20).change, (-0.1, 0.1))
        self.assertEqual(derivation.nudges("o", -20.0).change, (-0.1, 0.1),
                         "direction 0 is the factor below one for both types")

        @dataclasses.dataclass
        class Config:
            wall: float = 2
            count: int = 2
            maybe: "float | None" = 3

        plan = {n.name: n for n in derivation.plan_of(Config())}
        self.assertEqual(tuple(round(x, 9) for x in plan["wall"].steps), (1.8, 2.2))
        self.assertEqual(plan["count"].steps, (1, 3))
        self.assertEqual(tuple(round(x, 9) for x in plan["maybe"].steps), (2.7, 3.3))
        # The bracket's two bolts: the committed trace says the size it moved.
        traced = [n for n in os.listdir(derivation.trace_dir(_projects.BRACKET))
                  if ".amber." not in n]
        with open(os.path.join(derivation.trace_dir(_projects.BRACKET), traced[0]),
                  encoding="utf-8") as fh:
            row = json.load(fh)["observed"]["n_bolts"]
        self.assertEqual((row["steps"], row["change"]), ([1, 3], [-0.5, 0.5]))
        code, out, _err = main(bracket(self), "why", "n_bolts")
        self.assertIn("(an integer: moved \u221250% and +50%)", " ".join(out.split()))

    def test_two_equal_numbers_are_no_move(self):
        """Review of phase 3b: ``0`` and ``0.0``, and ``0.0`` and ``-0.0``,
        digest apart and each read as a structure's move."""
        def obs(x):
            return [verdicts.digest_value(x), x]

        for a, b in ((0, 0.0), (0.0, -0.0), (0, -0.0), (3, 3.0)):
            with self.subTest(a=a, b=b):
                self.assertNotEqual(obs(a)[0], obs(b)[0])
                self.assertIsNone(derivation.move_of(obs(a), obs(b)))
        self.assertEqual(derivation.move_of(obs(0), obs(0.5)), {"abs": 0.5})

    def test_a_file_or_a_mesh_compares_by_its_bytes(self):
        """Review of phase 3b: a path digested as its string and a mesh by its
        type, so a nudge that reshaped the frame's mesh moved nothing the
        trace could see."""
        root = self.tmp()
        os.makedirs(os.path.join(root, "build"))
        mesh = os.path.join(root, "build", "frame.stl")
        anchors = verdicts.Anchors(root=root)

        def seen(derived):
            projection = {"config": {}, "derived": derived}
            with mock.patch.object(graph, "derived_names", lambda p: tuple(derived)):
                return derivation.observe_values(projection, anchors)

        for spelled in ("build/frame.stl", mesh):
            with self.subTest(spelled=spelled):
                with open(mesh, "wb") as fh:
                    fh.write(b"solid a")
                before = seen({"mesh_path": spelled, "meshes": {"frame": spelled}})
                with open(mesh, "wb") as fh:
                    fh.write(b"solid b")
                after = seen({"mesh_path": spelled, "meshes": {"frame": spelled}})
                self.assertEqual(set(derivation.moves_between(before, after)),
                                 {"mesh_path", "meshes"})
        self.assertEqual(seen({"word": "petg"})["word"][0], verdicts.digest_value("petg"),
                         "a word that names no file is a word")

        class Array:
            def __init__(self, data: bytes, shape: tuple) -> None:
                self.data, self.shape, self.dtype = data, shape, "float64"

            def tobytes(self) -> bytes:
                return self.data

        class Mesh:
            def __init__(self, vertices: bytes) -> None:
                self.vertices, self.faces = Array(vertices, (1, 3)), Array(b"f", (1, 3))

        one, two = seen({"m": Mesh(b"v1")}), seen({"m": Mesh(b"v2")})
        self.assertEqual(derivation.moves_between(one, two), {"m": "#" + two["m"][0][:16]})
        self.assertEqual(derivation.moves_between(one, seen({"m": Mesh(b"v1")})), {})

    def test_how_a_move_is_stored(self):
        move = derivation.move_of
        self.assertEqual(move(["a", 10.0], ["b", 11.0]), 0.1)
        self.assertEqual(move(["a", -10.0], ["b", -9.0]), 0.1)
        self.assertEqual(move(["a", 0.0], ["b", 0.25]), {"abs": 0.25})
        self.assertEqual(move(["a", None], ["bbbbbbbbbbbbbbbbzz", None]), "#bbbbbbbbbbbbbbbb")
        self.assertEqual(move(["a", 1.0], None), "gone")
        self.assertEqual(move(None, ["b", 1.0]), "new")
        self.assertIsNone(move(["a", 1.0], ["a", 1.0]))
        self.assertIsNone(move(["a", 1.0], ["b", 1.0 + 1e-12]), "under the floor")
        self.assertEqual(move(["a", 3.0], ["b", 3.0 * 1.123456789]), 0.1235,
                         "four significant figures")

    def test_an_echoed_config_is_not_compared(self):
        projection = {"config": {"a": 1}, "derived": {"config": {"a": 1}, "b": 2.0}}
        self.assertEqual(set(derivation.observe_values(projection, None)), {"b"})

    def test_a_raise_is_stored_as_its_type(self):
        try:
            try:
                raise ValueError("at 0x7f3a /home/someone/model.py")
            except ValueError as exc:
                raise NopekitError("model/x.py: build(config) raised") from exc
        except NopekitError as wrapped:
            self.assertEqual(derivation._cause_type(wrapped), "ValueError")

    def test_an_unsteady_value_draws_no_edge(self):
        """Built twice, a value that differs between the two base builds is
        unsteady: compared by nothing, an edge to nothing."""
        root = bracket(self, traced=False)
        edit(os.path.join(root, "model", "bracket.py"), '        "mass_g": mass,',
             '        "mass_g": mass,\n        "noise": __import__("random").random(),')
        ran = trace_in_process(root)
        self.assertEqual(ran.state, "written", ran)
        self.assertIn("noise", ran.unsteady)
        state, found, _line = derivation.read_trace(derivation.trace_path(root, ran.key))
        self.assertEqual(state, "ok")
        self.assertNotIn("noise", {v for _c, v in found.derives})
        self.assertIn("noise", found.unsteady)


class TheOrderIsObserved(_env.EnvCase):
    """The order between derived values is inferred from who moves what, never
    read off the model's source; ties and single-mover values are named, never
    ordered."""

    def test_a_strict_subset_orders(self):
        found = derivation.after_order({"a": {"x", "y"}, "b": {"x", "y", "z"}, "c": {"x"},
                                        "d": {"x", "y"}})
        self.assertEqual(found.after, (("a", "b"), ("d", "b")))
        self.assertEqual(found.ties, (("a", "d"),))
        self.assertEqual(found.singles, ("c",))

    def test_the_floor_and_the_hasse_reduction(self):
        self.assertEqual(derivation.after_order({"a": {"x"}, "b": {"x", "y"}}).after, (),
                         "one mover orders nothing")
        found = derivation.after_order({"a": {"x", "y"}, "b": {"x", "y", "z"},
                                        "c": {"x", "y", "z", "w"}})
        self.assertEqual(found.after, (("a", "b"), ("b", "c")), "a -> c is implied")

    def test_a_move_the_rounding_hides_does_not_reverse_the_order(self):
        """Review of phase 3b, on PETGasus: seven clearances move the total
        weight by 0.022% and leave the hover power, rounded to 0.01 W, unmoved;
        with every move counted, weight could never sit before hover power.
        A move under `FAINT` still draws its derives edge."""
        moves = {"a": {"weight": [0.1, -0.1], "power": [0.1, -0.1]},
                 "b": {"weight": [0.05, -0.05], "power": [0.05, -0.05]},
                 "eff": {"power": [-0.09, 0.11]},
                 "clear": {"weight": [0.0002216, -0.0002216]}}
        doc = {"key": "k", "keyed_on": {}, "skipped": {}, "unmoved": [], "unsteady": [],
               "observed": {c: {"moves": m, "raised": [None, None]} for c, m in moves.items()}}
        found = derivation.TraceFile(doc, "x.json")
        self.assertIn(("weight", "power"), found.after)
        self.assertIn(("clear", "weight"), found.derives, "a faint move is still a move")
        self.assertEqual(found.movers("weight"), frozenset({"a", "b", "clear"}))
        exact = derivation.after_order({"weight": {"a", "b", "clear"},
                                        "power": {"a", "b", "eff"}})
        self.assertNotIn(("weight", "power"), exact.after, "the defect, with every move")

    def test_station_layers_by_the_median_read_and_unmoved_last(self):
        import test_site_truth
        root = bracket(self)
        view, *_rest = test_site_truth.resolved(root)
        from nopekit.models import Group
        groups = list(view.groups) + [
            Group(id="response", kind="station", title="Response",
                  members=["deflection", "stress_root"]),
            Group(id="margin", kind="station", title="Margin", members=["stress_margin"]),
            Group(id="constant", kind="station", title="Constant", members=["E"])]
        baked = test_site_truth.bake_project(
            root, view=lambda v: dataclasses.replace(v, groups=groups))
        layer = {n["key"]: (n["layer"], n["depth"]) for n in baked.map_doc["nodes"]
                 if n["kind"] == "station"}
        by_id = {n["id"]: n["layer"] for n in baked.map_doc["nodes"] if n["kind"] == "station"}
        self.assertEqual(layer["section"], (0, 0))
        self.assertEqual(layer["response"], (1, 1))
        self.assertEqual(layer["margin"], (2, 2))
        self.assertEqual(layer["constant"], (3, None), "a station nothing moved goes last")
        self.assertEqual(baked.map_doc["layers"][-1], 1)
        line = next(item for item in baked.map_doc["lines"] if item["claim"] == "C1")
        layers = [by_id[s] for s in line["stops"][:-1]]
        self.assertEqual(layers, sorted(layers), line["stops"])
        self.assertIn("station:response", line["stops"])

    def test_the_trace_reads_no_model_source(self):
        with open(os.path.join(SRC, "derivation.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        imported = {a.name.split(".")[0] for n in ast.walk(tree)
                    if isinstance(n, (ast.Import, ast.ImportFrom)) for a in n.names}
        self.assertNotIn("ast", imported)
        self.assertFalse({"compile", "exec", "eval"} & names)
        calls = {n.func.attr for n in ast.walk(tree)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
        self.assertIn("canonical_ast_digest", calls, "a source is only ever digested")


# --------------------------------------------------------------------------- #
class TheTraceIsKeyedToItsDesign(_env.EnvCase):
    """Invariant 7: a trace is keyed by the instructions' and every choice's
    digest, and served only for the design it was observed on."""

    def key(self, root: str) -> str:
        ledger = cli._load(root)
        model = modelio.load_model(root, ledger.meta.model_entry)
        projection = modelio.project(model)
        return derivation.current_key(root, model, projection,
                                      verdicts.Anchors(root=os.path.abspath(root)))

    def test_the_key_moves_with_what_it_is_keyed_on(self):
        root = bracket(self)
        model_py = os.path.join(root, "model", "bracket.py")
        base = self.key(root)
        moves = [
            ("a choice's value", '    bed_xy: float = 220.0', '    bed_xy: float = 250.0'),
            ("a skipped choice's value", '    material: str = "petg"',
             '    material: str = "pla"'),
            ("the code", "    min_wall = 3.0 * c.nozzle_d", "    min_wall = 2.0 * c.nozzle_d"),
        ]
        for what, old, new in moves:
            with self.subTest(what):
                edit(model_py, old, new)
                self.assertNotEqual(self.key(root), base, what)
                edit(model_py, new, old)
                self.assertEqual(self.key(root), base)
        edit(model_py, "    min_wall = 3.0 * c.nozzle_d",
             "    min_wall = 3.0 * c.nozzle_d   # a comment moves nothing")
        self.assertEqual(self.key(root), base, "a comment")
        sibling = os.path.join(root, "model", "lazy.py")
        with open(sibling, "w", encoding="utf-8") as fh:
            fh.write("def stiffness(x):\n    return 2 * x\n")
        self.assertNotEqual(self.key(root), base, "a sibling no global imports")
        os.unlink(sibling)
        with mock.patch.object(derivation, "HARNESS", derivation.HARNESS + 1):
            self.assertNotEqual(self.key(root), base, "the method's version")
        self.assertEqual(self.key(root), base)

    def test_data_build_reads_is_in_the_key(self):
        """Review of phase 3b: a model whose ``build()`` reads ``model/k.json``
        kept its old trace, edges and amber current after the file changed.
        The base build's reads are keyed; a reader checks them on disk."""
        root = bracket(self, traced=False)
        write_json(os.path.join(root, "model", "k.json"), {"k": 1.0})
        edit(os.path.join(root, "model", "bracket.py"), '        "mass_g": mass,',
             '        "mass_g": mass,\n        "kdata": __import__("json").load(open('
             '__import__("os").path.join(__import__("os").path.dirname(__file__), '
             '"k.json")))["k"] * c.width,')
        ran = trace_in_process(root)
        self.assertEqual(ran.state, "written", ran)
        traced, built, *_rest = read_now(root)
        self.assertEqual(traced.state, "current")
        self.assertEqual(list(traced.trace.keyed_on["data"]), ["model/k.json"])
        self.assertIn(("width", "kdata"), traced.trace.derives)
        write_json(os.path.join(root, "model", "k.json"), {"k": 3.0})
        traced, built, *_rest = read_now(root)
        self.assertEqual(traced.state, "none", "the data build() reads moved")
        self.assertIsNone(built.trace)
        self.assertFalse(any(e.type in ("derives", "after") for e in built.edges))
        again = trace_in_process(root)
        self.assertEqual(again.state, "written", again)
        self.assertNotEqual(again.key, ran.key)
        self.assertEqual(again.builds["reused"], 0, "no scratch row from the old data")
        self.assertEqual(read_now(root)[0].state, "current")

    def test_the_reader_and_the_worker_digest_the_same_files(self):
        """Review of phase 3b: a ``model/node_modules/helper.py`` (and a venv)
        were in the reader's key and not in the snapshot the worker keyed, so
        the trace was never served and every `round` started another."""
        root = bracket(self)
        base = self.key(root)
        for rel in ("model/node_modules/helper.py", "model/venv/lib/x.py"):
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            with open(os.path.join(root, rel), "w", encoding="utf-8") as fh:
                fh.write("def f():\n    return 1\n")
        with open(os.path.join(root, "model", "venv", "pyvenv.cfg"), "w") as fh:
            fh.write("home = /usr\n")
        self.assertEqual(self.key(root), base)
        self.assertEqual(read_now(root)[0].state, "current")
        self.assertEqual(trace_in_process(root).state, "current")

    def test_the_committed_trace_is_served_and_another_designs_never(self):
        root = bracket(self)
        traced, built, *_rest = read_now(root)
        self.assertEqual(traced.state, "current")
        self.assertTrue(built.edges and any(e.type == "derives" for e in built.edges))
        edit(os.path.join(root, "model", "bracket.py"), '    bed_xy: float = 220.0',
             '    bed_xy: float = 250.0')
        traced, built, *_rest = read_now(root)
        self.assertEqual(traced.state, "none", "the old design's trace is still on disk")
        self.assertTrue(trace_files(root))
        self.assertIsNone(built.trace)
        self.assertFalse(any(e.type in ("derives", "after") for e in built.edges))

    def test_a_file_that_does_not_read_is_never_served(self):
        root = bracket(self)
        traced, *_rest = read_now(root)
        path = derivation.trace_path(root, traced.key)
        with open(path, encoding="utf-8") as fh:
            good = json.load(fh)

        def sealed(doc: dict) -> dict:
            doc = dict(doc)
            doc["self"] = derivation.self_digest(doc)
            return doc

        plants = {
            "edited": dict(good, round=99),
            "newer": sealed(dict(good, schema=2)),
            "mismatch": sealed(dict(good, keyed_on=dict(good["keyed_on"], step=0.2))),
        }
        for state, doc in plants.items():
            with self.subTest(state):
                with open(path, "wb") as fh:
                    fh.write(derivation.render(doc))
                found, built, *_rest = read_now(root)
                self.assertEqual(found.state, "none")
                self.assertEqual([p[1] for p in found.problems], [state])
                self.assertIsNone(built.trace)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write('{"key": 1, "key": 2}')
        found, *_rest = read_now(root)
        self.assertEqual((found.state, [p[1] for p in found.problems]), ("none", ["unreadable"]))


class TheTraceIsWrittenOnce(_env.EnvCase):
    """Invariant 8: `model trace` writes a trace file and an amber file only as
    new paths, whole; it never rewrites one, refuses other bytes at its path,
    and the same design gives the same bytes on any number of workers."""

    def test_a_second_run_writes_nothing(self):
        root = bracket(self)
        before = files_of(os.path.join(root, ".nopekit", "trace"))
        ran = trace_in_process(root)
        self.assertEqual(ran.state, "current", ran)
        self.assertEqual(ran.written, ())
        self.assertEqual(files_of(os.path.join(root, ".nopekit", "trace")), before)

    def test_other_bytes_at_its_path_are_refused_and_untouched(self):
        root = bracket(self)
        traced, *_rest = read_now(root)
        path = derivation.trace_path(root, traced.key)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("not a trace\n")
        with self.assertRaises(NopekitError) as caught:
            trace_in_process(root)
        self.assertIn("reads unreadable", str(caught.exception))
        self.assertIn("Delete it to trace this design again", str(caught.exception))
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "not a trace\n")

    def test_one_worker_and_three_give_the_committed_bytes(self):
        committed = files_of(os.path.join(_projects.BRACKET, ".nopekit", "trace"))
        with open(os.path.join(_projects.BRACKET, ".nopekit", "trace",
                               next(n for n in committed if "amber" not in n)),
                  encoding="utf-8") as fh:
            round_ = json.load(fh)["round"]
        for workers in (1, 3):
            with self.subTest(workers=workers):
                root = bracket(self, traced=False)
                ran = trace_in_process(root, workers=workers, round_=round_)
                self.assertEqual(ran.state, "written", ran)
                found = files_of(os.path.join(root, ".nopekit", "trace"))
                self.assertEqual({k: v[0] for k, v in found.items()},
                                 {k: v[0] for k, v in committed.items()})


class TheTraceBuildsInACopy(_env.EnvCase):
    """Invariant 15, through the real command: every build runs in a
    subprocess on a copy of the project; a build that writes into the project
    leaves no trace file and is named; the temp directory must lie outside."""

    WRITES = ('        "mass_g": mass,',
              '        "mass_g": (__import__("os").makedirs(__import__("os").path.join('
              '__import__("os").path.dirname(__file__), "..", "build"), exist_ok=True), '
              'open(__import__("os").path.join(__import__("os").path.dirname(__file__), '
              '"..", "build", "out.txt"), "w").write("x"), mass)[2],')

    def test_a_build_that_writes_beside_its_model_writes_in_its_copy(self):
        root = bracket(self, traced=False)
        edit(os.path.join(root, "model", "bracket.py"), *self.WRITES)
        before = files_of(root)
        proc = _env.nopekit(["model", "trace", "--workers", "3"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        after = files_of(root)
        new = sorted(set(after) - set(before) - {".nopekit/ledger.json"})
        self.assertTrue(new and all(p.startswith((".nopekit/trace/", ".nopekit/cache/"))
                                    for p in new), new)
        self.assertFalse(os.path.exists(os.path.join(root, "build")))
        for rel, (data, mtime) in before.items():
            if rel.startswith(".nopekit/cache/"):
                continue
            with self.subTest(rel):
                self.assertEqual(after.get(rel), (data, mtime))
        self.assertFalse(os.path.exists(derivation.lock_path(root)))

    def test_a_build_that_writes_into_the_project_is_refused_and_named(self):
        """From a thread the build starts, as a model writing its meshes
        through a pool does (review of phase 3b: the watch lived on the
        worker's main thread alone)."""
        root = bracket(self, traced=False)
        target = os.path.join(root, "leak.txt")
        edit(os.path.join(root, "model", "bracket.py"), '        "mass_g": mass,',
             '        "mass_g": ((lambda t: (t.start(), t.join()))(__import__("threading").Thread('
             f'target=lambda: open({target!r}, "w").write("x"))), mass)[1],')
        proc = _env.nopekit(["model", "trace", "--workers", "2"], cwd=root)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("the base build wrote inside the project: leak.txt", proc.stdout)
        self.assertEqual(trace_files(root), [], "no tracked file")

    def test_the_model_runs_from_its_copy(self):
        root = bracket(self, traced=False)
        seen: list[str] = []

        def launch(job, job_path, timeout):
            ended = derivation.subprocess_launch(job, job_path, timeout)
            with open(job["out"], encoding="utf-8") as fh:
                seen.append(json.load(fh)["model_file"])
            return ended

        ran = trace_in_process(root, choices=["width"], launch=launch)
        self.assertEqual(ran.state, "partial", ran)
        self.assertTrue(seen)
        for path in seen:
            self.assertFalse(path.startswith(os.path.realpath(root) + os.sep), path)
            self.assertFalse(path.startswith(root + os.sep), path)

    def test_a_temp_directory_inside_the_project_is_refused(self):
        root = bracket(self, traced=False)
        inside = os.path.join(root, "tmpx")
        os.makedirs(inside)
        proc = _env.nopekit(["model", "trace"], cwd=root, env={"TMPDIR": inside})
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("is inside", proc.stderr)
        self.assertEqual(trace_files(root), [])


_WRITES: list[str] = []
_WATCHING = threading.local()


def _record_writes(event: str, args: tuple) -> None:
    if not getattr(_WATCHING, "on", False):
        return
    path = None
    if event == "open" and len(args) >= 2:
        mode, flags = args[1], args[2] if len(args) > 2 else 0
        writing = (any(c in mode for c in "wax+") if isinstance(mode, str)
                   else isinstance(flags, int) and bool(flags & (os.O_WRONLY | os.O_RDWR)))
        path = args[0] if writing else None
    elif event in ("os.remove", "os.rename", "os.replace", "os.mkdir", "shutil.rmtree"):
        path = args[0]
    if isinstance(path, (str, bytes, os.PathLike)):
        _WRITES.append(os.path.realpath(os.fsdecode(path)))


sys.addaudithook(_record_writes)


class AnAmberRunWritesNothing(_env.EnvCase):
    """Invariant 15: an amber run (the check run's rules on a moved design)
    writes nothing in the project and nothing in a pack directory; its gate
    scratch lands in its own copy."""

    def test_an_amber_evaluation_writes_only_in_its_copy(self):
        root = bracket(self)
        copy = os.path.join(self.tmp(), "copy")
        shutil.copytree(root, copy, symlinks=True)
        ledger = cli._load(copy)
        registry, _ = cli._registry(copy, ledger)
        packs_at = [os.path.realpath(p) for p in
                    (getattr(registry, "pack_dirs", None) or {}).values()]
        packs_at.append(os.path.realpath(os.path.join(_env.REPO, "packs")))
        model = modelio.load_model(copy, ledger.meta.model_entry)
        moved = derivation.apply(model, "load_n", 16.5)
        projection = modelio.project(moved)
        del _WRITES[:]
        _WATCHING.on = True
        try:
            with derivation._Watching(root, copy) as named:
                found = derivation._evaluate(copy, moved, projection, NOW)
        finally:
            _WATCHING.on = False
        real_root = os.path.realpath(root)
        self.assertEqual(named, [])
        self.assertEqual([p for p in _WRITES if p.startswith(real_root + os.sep)], [])
        for pack in packs_at:
            self.assertEqual([p for p in _WRITES if p.startswith(pack + os.sep)], [], pack)
        self.assertEqual(found["C3"]["token"], "checked")
        self.assertTrue(found["C3"]["by"])

    def test_a_worker_watches_every_thread(self):
        root = bracket(self)
        copy = os.path.join(self.tmp(), "copy")
        os.makedirs(copy)

        def write(name):
            with open(os.path.join(root, name), "w") as fh:
                fh.write("x")

        with derivation._Watching(root, copy, process_wide=True) as named:
            thread = threading.Thread(target=write, args=("from-a-thread.txt",))
            thread.start()
            thread.join()
        self.assertEqual(named, ["from-a-thread.txt"])
        with derivation._Watching(root, copy) as named:
            thread = threading.Thread(target=write, args=("unwatched.txt",))
            thread.start()
            thread.join()
        self.assertEqual(named, [], "in process the watch is the job's thread's alone")
        with open(os.path.join(SRC, "derivation.py"), encoding="utf-8") as fh:
            self.assertIn("_work(job, process_wide=True)", fh.read(),
                          "the subprocess worker watches every thread")

    def test_a_planted_write_is_named(self):
        root = bracket(self)
        copy = os.path.join(self.tmp(), "copy")
        os.makedirs(copy)
        with derivation._Watching(root, copy) as named:
            with open(os.path.join(root, "planted.txt"), "w") as fh:
                fh.write("x")
            with open(os.path.join(copy, "fine.txt"), "w") as fh:
                fh.write("x")
        self.assertEqual(named, ["planted.txt"])


# --------------------------------------------------------------------------- #
class APartialTraceIsNeverWritten(_env.EnvCase):
    """Invariant 16: a trace file is written only when every numeric choice was
    moved both ways; a build that timed out, died, or raised differently alone
    leaves none, and the scratch keeps what finished for the next run."""

    def test_a_timeout_leaves_no_file_and_a_resume_completes(self):
        root = bracket(self, traced=False)

        def stuck(job, job_path, timeout):
            if job["choice"] == "thickness" and job["dir"] == 1:
                return derivation.Launched(None, True, "")
            return derivation.in_process(job, job_path, timeout)

        ran = trace_in_process(root, launch=stuck)
        self.assertEqual(ran.state, "incomplete", ran)
        self.assertEqual(trace_files(root), [])
        held = derivation.scratch_state(root, ran.key)
        self.assertEqual([r[:2] for r in held["incomplete"]], [["thickness", 1]])
        again = trace_in_process(root)
        self.assertEqual(again.state, "written", again)
        self.assertGreaterEqual(again.builds["reused"], 20, again.builds)
        self.assertEqual(derivation.scratch_state(root, ran.key), {})

    def test_a_raise_that_differs_alone_is_incomplete(self):
        root = bracket(self, traced=False)
        calls = {"n": 0}

        def flaky(job, job_path, timeout):
            if job["choice"] == "width" and job["dir"] == 0:
                calls["n"] += 1
                if calls["n"] == 1:
                    with derivation._IN_PROCESS, open(job["out"], "w", encoding="utf-8") as fh:
                        json.dump({"ok": True, "values": None, "raised": "MemoryError",
                                   "raised_line": "", "wrote_project": [],
                                   "model_file": ""}, fh)
                    return derivation.Launched(0, False, "")
            return derivation.in_process(job, job_path, timeout)

        ran = trace_in_process(root, launch=flaky)
        self.assertEqual(ran.state, "incomplete", ran)
        self.assertEqual(calls["n"], 2, "run once more, alone")
        self.assertIn("an environmental failure", ran.incomplete[0][2])
        self.assertEqual(trace_files(root), [])

    def test_an_environmental_raise_is_never_kept(self):
        """Review of phase 3b: a raise judged environmental left its scratch
        row, and the next run wrote the transient MemoryError into the tracked
        trace that is never rewritten."""
        root = bracket(self, traced=False)
        calls = {"n": 0}

        def flaky(job, job_path, timeout):
            if job["choice"] == "width" and job["dir"] == 1:
                calls["n"] += 1
                if calls["n"] == 1:
                    with derivation._IN_PROCESS, open(job["out"], "w", encoding="utf-8") as fh:
                        json.dump({"ok": True, "values": None, "raised": "MemoryError",
                                   "raised_line": "", "wrote_project": [],
                                   "model_file": ""}, fh)
                    return derivation.Launched(0, False, "")
            return derivation.in_process(job, job_path, timeout)

        ran = trace_in_process(root, launch=flaky)
        self.assertEqual(ran.state, "incomplete", ran)
        self.assertIsNone(derivation._read_json(os.path.join(
            derivation.scratch_dir(root, ran.key), "width.json")), "no row for width")
        again = trace_in_process(root)
        self.assertEqual(again.state, "written", again)
        self.assertEqual(again.builds["reused"], 20, "width built again")
        state, found, _line = derivation.read_trace(derivation.trace_path(root, again.key))
        self.assertEqual(found.observed["width"]["raised"], [None, None])
        self.assertTrue(all(pair[1] is not None
                            for pair in found.observed["width"]["moves"].values()))

    def test_a_raise_confirmed_alone_is_kept(self):
        root = bracket(self, traced=False)

        def raising(job, job_path, timeout):
            if job["choice"] == "width" and job["dir"] == 0:
                with derivation._IN_PROCESS, open(job["out"], "w", encoding="utf-8") as fh:
                    json.dump({"ok": True, "values": None, "raised": "ValueError",
                               "raised_line": "", "wrote_project": [], "model_file": ""}, fh)
                return derivation.Launched(0, False, "")
            return derivation.in_process(job, job_path, timeout)

        ran = trace_in_process(root, launch=raising)
        self.assertEqual(ran.state, "written", ran)
        state, found, _line = derivation.read_trace(derivation.trace_path(root, ran.key))
        self.assertEqual(found.observed["width"]["raised"], ["ValueError", None])
        code, out, _err = main(root, "why", "width")
        self.assertIn("the \u221210% build raised ValueError", " ".join(out.split()))

    def test_a_nudge_that_writes_into_the_project_leaves_no_row(self):
        """Invariant 16, for a moved build (review of phase 3b: only the base
        build's write was ever tested, and a nudge's left its row for the
        next run to write into the trace)."""
        root = bracket(self, traced=False)

        def leaky(job, job_path, timeout):
            with derivation._IN_PROCESS:
                ended = derivation.in_process(job, job_path, timeout)
                if job["choice"] == "thickness" and job["dir"] == 0:
                    with open(job["out"], encoding="utf-8") as fh:
                        result = json.load(fh)
                    result["wrote_project"] = ["leak.txt"]
                    with open(job["out"], "w", encoding="utf-8") as fh:
                        json.dump(result, fh)
            return ended

        ran = trace_in_process(root, launch=leaky)
        self.assertEqual(ran.state, "incomplete", ran)
        self.assertEqual(trace_files(root), [])
        self.assertIn("thickness -10%: the build wrote inside the project: leak.txt",
                      ran.problems[0])
        self.assertIsNone(derivation._read_json(os.path.join(
            derivation.scratch_dir(root, ran.key), "thickness.json")))
        again = trace_in_process(root)
        self.assertEqual(again.state, "written", again)
        self.assertEqual(again.builds["reused"], 20, "thickness built again")

    def test_a_worker_that_dies_leaves_no_file(self):
        root = bracket(self, traced=False)

        def killed(job, job_path, timeout):
            if job["choice"] == "width" and job["dir"] == 1:
                return derivation.Launched(-9, False, "killed")
            return derivation.in_process(job, job_path, timeout)

        ran = trace_in_process(root, launch=killed)
        self.assertEqual(ran.state, "incomplete", ran)
        self.assertEqual(trace_files(root), [])
        self.assertEqual([r[:2] for r in ran.incomplete], [("width", 1)])
        self.assertIn("width +10%: the build process exited -9 with no result killed",
                      ran.incomplete[0][2])

    def test_choices_alone_write_no_tracked_file(self):
        root = bracket(self, traced=False)
        ran = trace_in_process(root, choices=["width"])
        self.assertEqual(ran.state, "partial", ran)
        self.assertEqual(trace_files(root), [])
        self.assertTrue(os.path.isfile(os.path.join(derivation.scratch_dir(root, ran.key),
                                                    "width.json")))

    def test_round_does_not_start_again_after_an_incomplete_background_run(self):
        root = bracket(self, traced=False)

        def stuck(job, job_path, timeout):
            if job["choice"] == "width":
                return derivation.Launched(None, True, "")
            return derivation.in_process(job, job_path, timeout)

        ran = trace_in_process(root, launch=stuck, background=True)
        self.assertEqual(ran.state, "incomplete")
        started: list = []
        with mock.patch.dict(os.environ, {derivation.BACKGROUND_ENV: "1"}):
            found = derivation.start_background(root, round_=3, key=ran.key,
                                                popen=lambda *a, **k: started.append(a))
        self.assertEqual((found[0], started), ("incomplete", []))
        code, out, _err = main(root, "status")
        self.assertIn("trace: incomplete for this design — 2 build(s) did not finish", out)


class UntracedIsNeverIndependent(_env.EnvCase):
    """Invariant 16: untraced says so on every channel; a choice the trace did
    not move and a value no move changed are said as such; nothing nopekit
    says calls a value independent."""

    def test_untraced_says_so(self):
        root = bracket(self, traced=False)
        code, out, _err = main(root, "status")
        self.assertIn(report.HUMAN["trace"]["status_none"], out)
        code, out, _err = main(root, "why", "deflection")
        self.assertIn("derived from: not traced yet", out)
        code, out, _err = main(root, "doctor", "--json")
        rows = [r for r in json.loads(out)["checks"] if r["check"] == "trace"]
        self.assertEqual([r["status"] for r in rows], ["warn"], rows)
        self.assertIn("not traced for this design", rows[0]["detail"])
        import test_site_truth
        baked = test_site_truth.bake_project(root, fresh=True)
        self.assertEqual(baked.map_doc["trace"]["state"], "untraced")
        self.assertEqual(baked.map_doc["trace"]["notice"],
                         report.HUMAN["site"]["trace"]["notice_untraced"])

    def test_what_the_trace_did_not_move_is_said_as_such(self):
        root = bracket(self)
        code, out, _err = main(root, "why", "E")
        self.assertEqual(code, 0, out)
        self.assertIn("not seen to move under any ±10% move", " ".join(out.split()))
        code, out, _err = main(root, "why", "material")
        self.assertIn("not moved by the trace: a word", out)
        # What the trace did observe, and the order it infers, said as such
        # (review of phase 3b: no test held these lines).
        traced, *_rest = read_now(root)
        code, out, _err = main(root, "why", "thickness")
        flat = " ".join(out.split())
        self.assertIn("moves: ", flat)
        self.assertIn(f"traced at round {traced.trace.round}", flat)
        later = next(b for _a, b in traced.trace.after)
        code, out, _err = main(root, "why", later)
        flat = " ".join(out.split())
        self.assertIn("derived from: ", flat)
        self.assertRegex(flat, r"after: .*\(inferred from the trace")
        # An assumption that sources a choice the trace does not move: C2
        # reads the material directly, so its amber cannot be judged.
        write_json(os.path.join(root, "params", "material.json"), {"grounded_by": ["C6"]})
        traced, built, toks, amber, *_rest = read_now(root)
        self.assertEqual(amber["C2"].state, "untraced")
        self.assertIn("the trace does not move material (a word)", amber["C2"].why)
        self.assertFalse(amber["C2"].rerun, "a choice the trace never moves asks no run")
        self.assertEqual(derivation.needed(traced, amber), "")

    def test_no_word_says_independent(self):
        def strings(node: Any) -> list[str]:
            if isinstance(node, str):
                return [node]
            if isinstance(node, (dict, type(report.HUMAN))):
                return [s for v in node.values() for s in strings(v)]
            if isinstance(node, (list, tuple)):
                return [s for v in node for s in strings(v)]
            return []

        found = [s for s in strings(report.HUMAN) if "independen" in s.lower()]
        self.assertEqual(found, [])
        import test_site_truth
        baked = test_site_truth.bake_project(bracket(self), fresh=True)
        import test_style
        words = test_style.baked_word_strings(baked.map_doc, "map.json")[0] + \
            test_style.baked_word_strings(baked.page_doc, "page.json")[0]
        self.assertEqual([w for w in words if "independen" in w[1].lower()], [])


# --------------------------------------------------------------------------- #
class AmberChangesNoStatus(_env.EnvCase):
    """Invariant 12: amber is said beside Checked and moves no status, exit
    code, readiness, JUnit outcome, report section or export."""

    _world: list = []

    @property
    def root(self) -> str:
        return self.world()[0]

    @property
    def ran(self) -> derivation.Ran:
        return self.world()[1]

    @classmethod
    def world(cls) -> tuple:
        """The bracket with C3 tightened and traced once, on first use: the
        source scan below needs none of it."""
        if not cls._world:
            tmp = tempfile.mkdtemp(prefix="nopekit-amber-")
            cls.addClassCleanup(_env._rmtree, tmp)
            root = _projects.bracket_copy(os.path.join(tmp, "b"), migrated=True)
            tight_c3(root)
            cls._world.append((root, trace_in_process(root)))
        return cls._world[0]

    def test_it_flips(self):
        self.assertEqual(self.ran.state, "written", self.ran)
        self.assertEqual(self.ran.amber["flips"], ["C3"])
        traced, built, toks, amber, *_rest = read_now(self.root)
        self.assertEqual(toks.claims["C3"], "checked")
        self.assertEqual(amber["C3"].state, "flips")
        self.assertEqual(amber["C3"].flips[0][:4], ("C6", "load_n", 1, "bracket.bearing"))
        # Review of phase 3b: the flip is said against the claim's 0.2 MPa,
        # which failed it, never the evaluator's own 15 MPa, a comfortable pass.
        self.assertEqual(amber["C3"].flips[0][4:], (0.214, 0.2, "MPa"))
        self.assertNotIn("C1", amber, "no amber on Failing")
        self.assertNotIn("C6", amber, "no amber on a Gap")
        code, out, _err = main(self.root, "status")
        self.assertIn("amber: C3 flips (C6 load_n +10%)", out)
        code, out, _err = main(self.root, "why", "C3")
        self.assertIn("amber: flips — load_n +10% (C6, not confirmed) gives bracket.bearing "
                      "0.214 against 0.2 MPa", " ".join(out.split()))
        # The report's `## Amber` and the JSON summaries carry it too (review
        # of phase 3b: nothing held them, and a report that dropped every flip
        # passed).
        code, out, _err = main(self.root, "report")
        section = out.split(f"## {report.HUMAN['trace']['report_heading']}\n", 1)
        self.assertEqual(len(section), 2, out)
        body = section[1].split("\n## ", 1)[0]
        self.assertIn("- C3: amber: flips — load_n +10% (C6, not confirmed) gives "
                      "bracket.bearing 0.214 against 0.2 MPa", body)
        self.assertIn(report.HUMAN["trace"]["report_line"], body)
        code, out, _err = main(self.root, "report", "--json")
        self.assertEqual(json.loads(out)["amber"]["C3"]["state"], "flips")
        code, out, _err = main(self.root, "status", "--json")
        doc = json.loads(out)
        self.assertEqual((doc["trace"]["state"], doc["amber"]["C3"]["state"]),
                         ("current", "flips"))

    def test_nothing_moves_without_it(self):
        def surfaces() -> dict:
            out: dict = {}
            code, text, _e = main(self.root, "status", "--json")
            doc = json.loads(text)
            out["status"] = (doc["claims"], doc["statuses"], doc["summary"])
            junit = os.path.join(self.tmp(), "j.xml")
            code, text, _e = main(self.root, "check", "--junit", junit)
            with open(junit, encoding="utf-8") as fh:
                xml = fh.read()
            out["check"] = (code, re.sub(r'(timestamp|time)="[^"]*"', "", re.sub(
                r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", "T", xml)))
            code, text, _e = main(self.root, "report", "--json")
            doc = json.loads(text)
            out["report"] = (doc["claims"], doc["summary"])
            code, text, _e = main(self.root, "report")
            out["sections"] = [line for line in text.splitlines()
                               if line.startswith("## ") and "Amber" not in line]
            code, text, _e = main(self.root, "export", "print-v1", "--dry-run")
            out["export"] = (code, text)
            ledger = cli._load(self.root)
            *_x, view, resolution, registry = read_now(self.root)
            composed = claims_mod.compositions(view, registry=registry,
                                               stale_gates=resolution.stale_gates)
            out["ready"] = claims_mod.unresolved(view, composed).ready
            return out

        with_amber = surfaces()
        for name in trace_files(self.root):
            if ".amber." in name:
                os.unlink(os.path.join(derivation.trace_dir(self.root), name))
        try:
            without = surfaces()
        finally:
            trace_in_process(self.root)
        self.assertEqual(with_amber, without)

    def test_claims_never_imports_the_trace(self):
        with open(os.path.join(SRC, "claims.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
                    for a in n.names} | {a.name.rsplit(".", 1)[-1] for n in ast.walk(tree)
                                         if isinstance(n, ast.Import) for a in n.names}
        self.assertNotIn("derivation", imported)

    def test_a_confirmed_assumption_carries_no_amber(self):
        traced, built, toks, amber, view, resolution, registry = read_now(self.root)
        subjects = derivation.amber_subjects(self.root, view, registry)
        owned = dict(toks.claims, C6="assumed")
        found = derivation.amber_states(traced, built=built, tokens=owned, subjects=subjects)
        self.assertNotIn("C3", found, "owned: Assumed through its owner")
        resolved = graph.Graph(built.nodes, built.edges + (graph.Edge(
            "resolves", "claim:C5", "claim:C6"),), trace=built.trace)
        passed = dict(toks.claims, C5="checked")
        found = derivation.amber_states(traced, built=resolved, tokens=passed,
                                        subjects=subjects)
        self.assertNotIn("C3", found, "resolved by a passing physical claim")


class AmberOnlyWhileCurrent(_env.EnvCase):
    """Invariant 16: amber is shown only while its trace is the design's and the
    evaluators' code and the acceptance conditions it ran under are the current
    ones; otherwise it says it is not current, naming what moved."""

    def flipped(self) -> str:
        root = bracket(self)
        tight_c3(root)
        self.assertEqual(trace_in_process(root).state, "written")
        return root

    def test_a_gate_edit(self):
        """Run with the committed amber file (run at 15 MPa) beside the one at
        0.2: the reason is read off the closest file, and names the gate.
        Review of phase 3b: C3 read Stale after the edit, so this test asserted
        nothing; with `check` run it is Checked at the new code."""
        root = self.flipped()
        edit(os.path.join(root, "gates", "structural.py"),
             "    stress, allowable = round(b, 3), round(allow, 3)   # judged as reported",
             "    stress, allowable = round(b, 4), round(allow, 4)   # judged as reported")
        self.assertIn(main(root, "check")[0], (0, 1))
        traced, built, toks, amber, *_rest = read_now(root)
        self.assertEqual(toks.claims.get("C3"), "checked")
        self.assertEqual((amber["C3"].state, amber["C3"].why),
                         ("not-current", "bracket.bearing changed"))
        code, out, _err = main(root, "why", "C3")
        self.assertNotIn("amber: flips", out)
        import test_site_truth
        baked = test_site_truth.bake_project(root, fresh=True)
        self.assertTrue(all("amber" not in n.get("marks", ()) for n in baked.map_doc["nodes"]))

    def test_an_acceptance_edit_beside_the_committed_amber(self):
        """The bracket's committed amber file ran C3 at its 15 MPa limit; at 14
        it is not current, and says so — no trace run needed to see it."""
        root = bracket(self)
        path = os.path.join(root, "claims", "C3.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["acceptance"]["limit"] = 14.0
        write_json(path, data)
        traced, built, toks, amber, *_rest = read_now(root)
        self.assertEqual((amber["C3"].state, amber["C3"].why),
                         ("not-current", "the acceptance condition changed"))
        self.assertEqual(amber["C2"].state, "holds")
        self.assertEqual(derivation.needed(traced, amber), "amber")

    def test_the_reason_comes_from_the_closest_file(self):
        """Review of phase 3b: the first amber file by name was asked, and a
        file run at another limit said "the acceptance condition changed" when
        only the evaluator's code had — whichever order the names sort in."""
        now = {"acceptance": "acc-now", "evaluators": {"g": "code-now"}}
        old_limit = {"acceptance": "acc-old", "evaluators": {"g": "code-old"}, "runs": {}}
        this_limit = {"acceptance": "acc-now", "evaluators": {"g": "code-old"}, "runs": {}}

        class Built:
            def rests_on(self, cid):
                return ["A1"]

            def into(self, nid, type=None):
                return ()

            def via(self, cid, aid):
                return [("g", "x", "choice")]

            def node(self, nid):
                return graph.Node(nid, "value", {"role": "choice"})

        trace = derivation.TraceFile({"key": "k", "keyed_on": {}, "skipped": {}, "unmoved": [],
                                      "unsteady": [], "observed": {"choice": {
                                          "moves": {}, "raised": [None, None]}}}, "k.json")
        for names in (("a.json", "b.json"), ("b.json", "a.json")):
            with self.subTest(names=names):
                ambers = (derivation.AmberFile(names[0], "k", 1, {"choice": ["A1"]},
                                               {"C1": old_limit}),
                          derivation.AmberFile(names[1], "k", 1, {"choice": ["A1"]},
                                               {"C1": this_limit}))
                read = derivation.TraceRead("current", "k", trace, (), ambers)
                found = derivation.amber_states(read, built=Built(), tokens={"C1": "checked"},
                                                subjects={"C1": now})
                self.assertEqual((found["C1"].state, found["C1"].why),
                                 ("not-current", "g changed"))

    def test_a_retrace_after_an_acceptance_edit_runs_again(self):
        """Review of phase 3b: the scratch's amber rows were reused whatever
        they ran against, so an amber file sealed at a 100 MPa limit said C3
        flipped on runs made at 0.2 MPa."""
        root = self.flipped()
        path = os.path.join(root, "claims", "C3.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["acceptance"]["limit"] = 100.0
        write_json(path, data)
        ran = trace_in_process(root)
        self.assertEqual(ran.state, "written", ran)
        self.assertGreater(ran.builds["run"], 1, "load_n built again for amber")
        traced, built, toks, amber, *_rest = read_now(root)
        self.assertEqual(amber["C3"].state, "holds")
        newest = [a for a in traced.ambers
                  if derivation._same_subject(a.claims.get("C3"), derivation.amber_subjects(
                      root, read_now(root)[4], read_now(root)[6])["C3"])]
        self.assertEqual(len(newest), 1)
        runs = newest[0].claims["C3"]["runs"]["load_n"]
        self.assertEqual([r["accept"][1] for r in runs], [100.0, 100.0])
        self.assertEqual([r["token"] for r in runs], ["checked", "checked"])

    def test_an_acceptance_edit(self):
        root = self.flipped()
        path = os.path.join(root, "claims", "C3.json")
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["acceptance"]["limit"] = 0.21
        write_json(path, data)
        traced, built, toks, amber, *_rest = read_now(root)
        self.assertEqual((amber["C3"].state, amber["C3"].why),
                         ("not-current", "the acceptance condition changed"))
        self.assertEqual(derivation.needed(traced, amber), "amber")
        code, out, _err = main(root, "status")
        self.assertIn("amber: C3 not current (the acceptance condition changed)", out)

    def test_a_choice_edit(self):
        root = self.flipped()
        edit(os.path.join(root, "model", "bracket.py"), '    bed_xy: float = 220.0',
             '    bed_xy: float = 250.0')
        traced, built, toks, amber, *_rest = read_now(root)
        # Untraced, C3 rests on nothing it does not read directly: no flip is
        # said, and the next round asks for a trace.
        self.assertNotEqual(getattr(amber.get("C3"), "state", None), "flips")
        self.assertEqual(derivation.needed(traced, amber), "trace")
        code, out, _err = main(root, "status")
        self.assertNotIn("C3 flips", out)
        self.assertIn(report.HUMAN["trace"]["status_none"], out)


class TheMapDrawsWhatTheTraceObserved(_env.EnvCase):
    """Invariant 14: the map's feeds are the trace's direct derives, its stops
    the trace's order, and its amber the live amber; the checker names a page
    that says otherwise."""

    @classmethod
    def setUpClass(cls) -> None:
        import test_site_truth
        cls.root = test_site_truth._bracket(cls)       # shared, read only
        cls.baked = test_site_truth.bake_project(cls.root)
        cls.world = test_site_truth.resolved(cls.root)
        cls.traced, cls.amber = test_site_truth._TRACES[cls.root]

    def test_stops_follow_the_layers(self):
        nodes = {n["id"]: n for n in self.baked.map_doc["nodes"]}
        for line in self.baked.map_doc["lines"]:
            keys = [(nodes[s]["layer"], nodes[s]["column"], nodes[s]["order"])
                    for s in line["stops"][:-1]]
            self.assertEqual(keys, sorted(keys), line)
            self.assertEqual(set(line["stop_kind"]), set(line["stops"][:-1]))
            self.assertTrue(set(line["stop_kind"].values()) <= {"read", "upstream"})

    def test_feeds_are_the_direct_derives(self):
        built = self.world[4]
        direct = graph.direct_derives(built)
        lay = self.baked.lay
        want: dict = {}
        for c, v in sorted(direct):
            z, s = lay.zone_of.get(c), lay.station_of.get(v)
            if z and s:
                want.setdefault((z, s), set()).add(c)
        found = {(f["zone"], f["to"]): set(f["choices"]) for f in self.baked.map_doc["feeds"]}
        self.assertEqual(found, want)
        self.assertTrue(found)
        for feed in self.baked.map_doc["feeds"]:
            sourced = {nid.partition(":")[2] for c in feed["choices"]
                       for nid in built.into(f"value:{c}", "sources")
                       if nid.startswith("claim:")}
            self.assertEqual(set(feed["estimate"]), sourced)

    def test_the_checker_names_each_planted_lie(self):
        view, resolution, registry = self.world[0], self.world[1], self.world[2]
        composed, toks = self.baked.composed, self.baked.toks
        feeds = page.live_feeds(self.baked.lay, self.world[4], toks)

        def problems(map_doc, page_doc, amber):
            return page.status_problems(map_doc, page_doc, view, composed, toks, amber=amber,
                                        feeds=feeds)

        self.assertEqual(problems(self.baked.map_doc, self.baked.page_doc, self.amber), [])
        marked = json.loads(json.dumps(self.baked.map_doc))
        node = next(n for n in marked["nodes"] if n.get("key") == "C2")
        node["marks"] = node["marks"] + ["amber"]
        self.assertTrue(any("amber mark" in p for p in problems(marked, self.baked.page_doc,
                                                                 self.amber)))
        flipping = dict(self.amber, C2=self.amber["C2"]._replace(state="flips"))
        self.assertTrue(problems(self.baked.map_doc, self.baked.page_doc, flipping))
        stray = json.loads(json.dumps(self.baked.page_doc))
        stray["claims"]["C4"]["amber"] = {"state": "holds", "word": "", "items": []}
        self.assertTrue(any("page claim C4 amber" in p
                            for p in problems(self.baked.map_doc, stray, self.amber)))
        estimate = json.loads(json.dumps(self.baked.map_doc))
        estimate["feeds"][0]["estimate"] = ["C6"]
        self.assertTrue(any("rests on" in p for p in problems(estimate, self.baked.page_doc,
                                                              self.amber)))


class TheMapSaysWhatTheTraceDidNotSee(_env.EnvCase):
    """The review of phase 3b's map findings: what the trace did not measure,
    did not see move or only infers is said as such on the map, and the rows
    and stations it can join are joined."""

    @classmethod
    def setUpClass(cls) -> None:
        import test_site_truth
        cls.T = test_site_truth
        cls.root = test_site_truth._bracket(cls)       # shared, read only
        cls.baked = test_site_truth.bake_project(cls.root)

    def test_an_untraced_zone_is_not_called_unused(self):
        """Untraced, a zone that feeds nothing says it was not measured, never
        "no line uses these choices" (review: six PETGasus zones said so)."""
        baked = self.T.bake_project(bracket(self, traced=False), fresh=True)
        zones = [n for n in baked.map_doc["nodes"] if n["kind"] == "zone"]
        self.assertTrue(zones)
        self.assertFalse(any(z["idle"] for z in zones))
        for zone in zones:
            if not zone["feeds"] and not zone["taps"]:
                self.assertEqual(zone["unmeasured"], zone["members"])

        class Trace:
            skipped = {"a": "word"}
            observed = {"b": {"raised": ["ValueError", None]}, "c": {"raised": [None, None]}}

        found = type("Read", (), {"trace": Trace()})()
        self.assertEqual(page._unmeasured(["a", "b", "c", "d"], found, True), ["a", "b", "d"])
        self.assertEqual(page._unmeasured(["c"], found, False), ["c"])

    def test_the_values_it_did_not_see_move_are_named(self):
        trace = self.baked.map_doc["trace"]
        self.assertEqual(trace["unmoved"], ["E", "material", "yield"])
        self.assertIn("The test did not see 3 shared values change: E, material, yield.",
                      trace["text"])
        line = {"stops": ["claim:C10"], "fed_by": [], "values": ["bom_path", "budget"]}
        seen = type("Read", (), {"trace": type("T", (), {"unmoved": ("bom_path",)})()})()
        self.assertTrue(page._unseen(line, seen))
        self.assertFalse(page._unseen(dict(line, fed_by=["zone:parts"]), seen))
        self.assertFalse(page._unseen(line, None), "untraced, the notice says it")

    def test_an_assumption_and_a_test_on_the_part_join_their_stations(self):
        """Review: every assumption row and every physical row ended in a stub
        that joined nothing."""
        view, resolution, registry, projection, built, params = self.T.resolved(self.root)
        traced, amber = self.T._TRACES[self.root]
        from nopekit.models import Group
        groups = list(view.groups) + [Group(id="response", kind="station", title="Response",
                                            members=["moment_root", "bearing_stress"])]
        view = dataclasses.replace(view, groups=groups)
        resolved_ = graph.Graph(built.nodes, built.edges + (graph.Edge(
            "resolves", "claim:C5", "claim:C6"),), trace=built.trace)
        baked = self.T.bake(view, resolution, registry, projection=projection, root=self.root,
                            built=resolved_, params=params, amber=amber, trace=traced)
        lines = {line["claim"]: line for line in baked.map_doc["lines"]}
        self.assertIn("station:response", lines["C6"]["sets"], "load_n moves the response")
        self.assertEqual(lines["C5"]["sets"], lines["C6"]["sets"], "C5 settles C6")
        self.assertEqual(lines["C1"]["sets"], [], "a line with stops has no springs")

    def test_a_source_nothing_records_is_not_a_design_choice(self):
        """Review: a vendor's motor mass, sourced by no record, read as a
        design choice."""
        def source(rejected):
            built = graph.Graph((), (), trace=None)
            view = modelio.ParamView(name="x", rejected=rejected)
            return page.source_of(built, "x", {}, {"x": view})

        self.assertEqual(source(()), "unrecorded")
        self.assertEqual(source(((object(), "model PARAMS"),)), "chosen")
        zones = {n["key"]: n for n in self.baked.map_doc["nodes"] if n["kind"] == "zone"}
        self.assertEqual(zones["printer"]["sources"]["unrecorded"], 3)
        with open(os.path.join(SRC, "site_template", "lib", "map.js"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn('["unrecorded", "g-none"]', text)
        self.assertIn("!used.has(k)", text, "the key shows only the sources some bar draws")

    def test_a_station_never_shows_a_bare_number(self):
        """Review: "Layout 22.5" was a radius in mm, and a list was chosen as
        the head over a scalar beside it."""
        stations = {n["key"]: n for n in self.baked.map_doc["nodes"] if n["kind"] == "station"}
        self.assertEqual(stations["allowable"]["value_text"], "15 MPa", "bracket.bearing's units")
        for node in stations.values():
            with self.subTest(node["key"]):
                text = node["value_text"]
                self.assertTrue(text == "" or re.search(r"[A-Za-z%]", text), text)
        derived = {"modes": [1.0, 2.0], "mode1": 282.0}
        self.assertEqual(page._value_text("mode1", {}, derived, {}, units="", bare=False), "")
        self.assertEqual(page._value_text("mode1", {}, derived, {}, units="Hz", bare=False),
                         "282 Hz")

    def test_the_renderer_marks_what_is_inferred_and_lights_what_rests(self):
        """The template side of the review: the phone list names an upstream
        stop apart from what a claim reads, the drawing fades the inferred part
        of a line, hovering an assumption lights the claims resting on it, and
        a row with `sets` draws its springs."""
        with open(os.path.join(SRC, "site_template", "lib", "map.js"), encoding="utf-8") as fh:
            text = fh.read()
        phone = text[text.index("export function mapList"):]
        self.assertIn('!== "upstream"', phone)
        self.assertIn("traceWords.upstream_rides", phone)
        self.assertIn('class: "upfade"', text)
        self.assertIn("if (restedBy.has(key)) return assumptionSet(key);", text)
        self.assertIn("...(restedBy.get(id) || [])", text)
        self.assertIn("spring ${", text)
        words = report.HUMAN["site"]["trace"]
        for key in ("upstream_rides", "unseen_line", "sets", "settles", "zone_unmeasured",
                    "unmoved", "unmoved_one"):
            self.assertIn(key, words)


# --------------------------------------------------------------------------- #
class RoundStartsTheTrace(_env.EnvCase):
    """`round` starts the trace in the background when the design has none,
    never when it is current, never twice, and never under the switch."""

    def test_round_starts_it_only_when_wanted(self):
        calls: list = []

        def fake(root, *, round_, key, popen=None):
            calls.append((round_, key))
            return "started", derivation.LOG_REL

        with mock.patch.object(derivation, "start_background", fake):
            root = bracket(self)
            code, out, _err = main(root, "round")
            self.assertEqual(calls, [], "current: nothing to start")
            root = bracket(self, traced=False)
            code, out, _err = main(root, "round")
        self.assertEqual(len(calls), 1, calls)
        self.assertIn("Tracing the derivation in the background (log .nopekit/out/trace.log).",
                      out)

    def test_the_background_start_refuses_what_it_should(self):
        root = bracket(self, traced=False)
        started: list = []

        def popen(*args, **kwargs):
            started.append(args[0])
            return None

        found = derivation.start_background(root, round_=3, key=None, popen=popen)
        self.assertEqual((found[0], started), ("off", []), "tests set the switch")
        with mock.patch.dict(os.environ, {derivation.BACKGROUND_ENV: "1"}):
            with mock.patch.object(derivation, "live_holder", lambda r: 4242):
                self.assertEqual(derivation.start_background(root, round_=3, key=None,
                                                             popen=popen),
                                 ("running", "4242"))
            found = derivation.start_background(root, round_=3, key=None, popen=popen)
        self.assertEqual(found, ("started", derivation.LOG_REL))
        self.assertEqual(started[0][-4:], ["-C", root, "--from-round", "3"])

    def test_a_module_in_the_projects_root_is_never_imported(self):
        """The background trace starts in nopekit's own directory with the
        project named by `-C`, and its workers move into their copies
        themselves: a `difflib.py` planted in the project's root is imported
        by neither. What slipped through (the merge of phase 3b into phase 6,
        a named limit until the follow-up after it): the start ran with the
        root as its cwd, each worker in its copy, and `-m` put that directory
        first on `sys.path` — what `hooks/stop.py` exists to stop. The planted
        module is shown to bite: the same command run from the root runs it."""
        root = bracket(self)
        marker = os.path.join(root, "planted-ran")
        with open(os.path.join(root, "difflib.py"), "w", encoding="utf-8") as fh:
            fh.write(f"open({marker!r}, 'a').close()\nraise SystemExit(7)\n")
        launched: list = []
        with mock.patch.dict(os.environ, {derivation.BACKGROUND_ENV: "1"}):
            found = derivation.start_background(
                root, round_=5, key=None, popen=lambda argv, **kw: launched.append((argv, kw)))
        self.assertEqual(found, ("started", derivation.LOG_REL))
        [(argv, kwargs)] = launched
        proc = _env.run(argv, cwd=kwargs["cwd"])
        self.assertFalse(os.path.exists(marker),
                         "the project's difflib.py ran: " + proc.stdout + proc.stderr)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("trace: current for this design", proc.stdout)
        self.assertEqual(argv[argv.index("-C") + 1], root)
        proc = _env.run(argv, cwd=root)
        self.assertEqual(proc.returncode, 7, "the planted module never ran from the root")
        self.assertTrue(os.path.exists(marker))

    def test_the_paragraph_and_the_record(self):
        said = report.HUMAN["round"]
        for state, key in (("started", "trace_started"), ("amber", "trace_amber"),
                           ("running", "trace_running")):
            self.assertIn(said[key].format(log="L").strip(),
                          report.round_paragraph("unchanged", 3, None, view=cli._load(
                              _projects.BRACKET), composed={}, check={"ran": False},
                              site={}, wrote=False, schema=1, path="p",
                              trace={"state": state, "log": "L"}))
        self.assertIn("amber", rounds.KEYS)
        self.assertEqual(rounds.MOVED[-1], rounds.TRACE)
        with open(os.path.join(_projects.BRACKET, *rounds.ROUND_REL.split("/")),
                  encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertTrue(doc["computed_from"]["trace"])
        self.assertEqual(doc["amber"]["holds"], ["C2", "C3"])
        self.assertEqual(doc["graph"]["trace"]["key"][:16],
                         next(n for n in trace_files(_projects.BRACKET)
                              if ".amber." not in n)[:16])


class RoundStartsARealTrace(_env.EnvCase):
    """`round` on an untraced bracket starts a real detached trace; it lands,
    and `status` then prints no `trace:` line."""

    def test_it_lands(self):
        root = bracket(self, traced=False)
        proc = _env.nopekit(["round"], cwd=root, env={derivation.BACKGROUND_ENV: None})
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("Tracing the derivation in the background", proc.stdout)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if not os.path.exists(derivation.lock_path(root)) and trace_files(root):
                break
            time.sleep(0.2)
        self.assertTrue(trace_files(root), "no trace landed in 60 s")
        proc = _env.nopekit(["status"], cwd=root)
        self.assertNotIn("trace:", proc.stdout)


class TheLockKeepsOneTrace(_env.EnvCase):
    """One trace at a time: a live holder is refused by name, a dead one is
    reaped, and a background run beside a live one exits quietly."""

    def plant(self, root: str, pid: int) -> None:
        path = derivation.lock_path(root)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"pid": pid, "host": util._HOST, "when": NOW, "command": "x"}, fh)

    def test_live_dead_and_background(self):
        root = bracket(self, traced=False)
        self.plant(root, os.getppid())
        with self.assertRaises(NopekitError) as caught:
            trace_in_process(root)
        self.assertIn(f"process {os.getppid()}", str(caught.exception))
        ran = derivation.run(root, plan=[], entry="model/bracket.py",
                             quiet_if_running=True)
        self.assertEqual(ran.state, "running")
        self.plant(root, 2 ** 22 + 12345)
        self.assertEqual(trace_in_process(root, choices=["width"]).state, "partial")


class TheTraceRefuses(_env.EnvCase):
    """What `model trace` refuses, each in one line, exit 2."""

    def test_each_refusal(self):
        root = bracket(self, traced=False)
        code, _out, err = main(root, "model", "trace", "--choices", "widht")
        self.assertEqual(code, 2)
        self.assertIn("--choices names widht, which is not a choice of model/bracket.py "
                      "(its Config); did you mean width?", err)
        code, _out, err = main(root, "model", "trace", "--workers", "0")
        self.assertEqual((code, "--workers must be 1 or more" in err), (2, True))
        edit(os.path.join(root, "model", "bracket.py"), "def build(", "def build(:")
        code, _out, err = main(root, "model", "trace")
        self.assertEqual(code, 2)
        self.assertIn("the model does not load, so nothing can be traced", err)
        legacy = _projects.bracket_copy(os.path.join(self.tmp(), "legacy"))
        code, _out, err = main(legacy, "model", "trace")
        self.assertEqual(code, 2)
        self.assertIn("still in the legacy ledger", err)


if __name__ == "__main__":
    unittest.main()
