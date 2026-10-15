# SPDX-License-Identifier: Apache-2.0
"""The front page's baked data (architecture phase 5, SPEC 29, 30, 32).

The map is order, never geometry: no coordinate anywhere, every claim of the
composition a node, contiguous orders, stops that name nodes, the graph's edges
and no others, the generated board, zone and station rules, and a status flip
that moves no order. A rebuild that judged nothing new changes no tracked byte.
Evidence an evaluator wrote reaches the page, and a fresh clone keeps the copy.
The bracket shows the outline: four boards, seven lines, its text current.

What slipped through before this: the reference map baked hand-placed pixel
positions and its own claim lists, so a claim added to a board never reached
it, and every page build rewrote its tracked data with a new timestamp.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_map.py'
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from unittest import mock

import _env
import _projects
from nopekit import claims as claims_mod
from nopekit import graph, page, site, store
from nopekit.models import Verdict
from test_site_truth import _bracket, _Res, bake, bake_project, resolved

_COORDINATES = {"x", "y", "cx", "cy", "left", "top", "width", "height"}


#: Maps keyed by names, not by schema keys: a value named `width` is a name.
_ID_MAPS = {"values", "evaluators", "edges", "via", "claims", "tokens"}


def _keys(node, out=None, *, ids: bool = False) -> set:
    out = set() if out is None else out
    if isinstance(node, dict):
        for key, value in node.items():
            if not ids:
                out.add(key)
            _keys(value, out, ids=key in _ID_MAPS and isinstance(value, dict) and not ids)
    elif isinstance(node, list):
        for value in node:
            _keys(value, out)
    return out


class TheMapIsBaked(_env.EnvCase):
    """(SPEC 29) Order is baked, geometry is rendered."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _bracket(cls)
        cls.baked = bake_project(cls.root)

    def test_no_coordinate_anywhere(self):
        for name, doc in (("map.json", self.baked.map_doc), ("page.json", self.baked.page_doc)):
            with self.subTest(name):
                self.assertEqual(_keys(doc) & _COORDINATES, set())

    def test_every_claim_is_a_node_and_the_orders_are_contiguous(self):
        nodes = self.baked.map_doc["nodes"]
        claims = [n for n in nodes if n["kind"] == "claim"]
        self.assertEqual(sorted(n["key"] for n in claims), sorted(self.baked.composed))
        self.assertEqual(sorted(n["order"] for n in claims), list(range(len(claims))))
        for board in (n for n in nodes if n["kind"] == "board"):
            rows = sorted(n["row"] for n in claims if n["board"] == board["key"])
            self.assertEqual(rows, list(range(len(rows))), board["key"])
        for kind in ("requirement", "zone", "station", "board"):
            orders = [n["order"] for n in nodes if n["kind"] == kind]
            self.assertEqual(orders, list(range(len(orders))), kind)

    def test_stops_and_via_name_nodes_and_edges_are_the_graphs(self):
        ids = {n["id"] for n in self.baked.map_doc["nodes"]}
        for line in self.baked.map_doc["lines"]:
            self.assertTrue(set(line["stops"]) <= ids, line)
            self.assertEqual(line["stops"][-1], f"claim:{line['claim']}")
            self.assertTrue(set(line["via"]) <= set(line["stops"]), line)
        world = resolved(self.root)
        edges = world[4].to_dict()["edges"]
        for type_, found in self.baked.map_doc["edges"].items():
            self.assertIn(type_, page.MAP_EDGE_TYPES)
            self.assertEqual(found, edges[type_])
        self.assertNotIn("requires", self.baked.map_doc["edges"])

    def test_the_brackets_layout(self):
        doc = self.baked.map_doc
        stations = [n for n in doc["nodes"] if n["kind"] == "station"]
        self.assertEqual([(n["key"], n["generated"]) for n in stations],
                         [("allowable", False), ("@slenderness", True)],
                         "a recorded station, then the value two claims' evaluators read")
        self.assertEqual([n["key"] for n in doc["nodes"] if n["kind"] == "board"],
                         ["strength", "prints", "pump", "outdoors"])
        line = next(item for item in doc["lines"] if item["claim"] == "C1")
        self.assertEqual(line["stops"], ["requirement:R1", "zone:load",
                                         "station:@slenderness", "claim:C1"])
        self.assertIn("unread", doc)
        groups = self.baked.page_doc["next"]["milestones"]
        self.assertEqual([g["next"] for g in groups], [True])

    def test_a_whole_read_makes_no_station(self):
        real = graph.served_reads

        def whole(resolution, registry):
            found = dict(real(resolution, registry))
            found["bracket.bearing"] = ((),)
            found["bracket.bending_stress"] = ((),)
            return found

        with mock.patch.object(graph, "served_reads", whole):
            baked = bake_project(self.root)
        lines = {line["claim"]: line for line in baked.map_doc["lines"]}
        self.assertEqual(lines["C3"]["reads_all"], "values")
        generated = [n["key"] for n in baked.map_doc["nodes"]
                     if n["kind"] == "station" and n["generated"]]
        self.assertEqual(generated, ["@slenderness"], "a whole read made a station")

    def test_no_board_records_make_one_board_of_claims(self):
        baked = bake_project(self.root, view=lambda v: dataclasses.replace(v, groups=[]))
        boards = [n for n in baked.map_doc["nodes"] if n["kind"] == "board"]
        self.assertEqual([(b["key"], b["title"], b["generated"]) for b in boards],
                         [("other", "Claims", True)])
        zones = [n for n in baked.map_doc["nodes"] if n["kind"] == "zone"]
        self.assertEqual([(z["key"], z["title"]) for z in zones], [("other", "Choices")])

    def test_a_status_flip_moves_no_order(self):
        def structure(doc):
            return [(n["id"], n["order"], n.get("row"), n.get("column"))
                    for n in doc["nodes"]], [(l["claim"], l["order"], l["stops"])
                                             for l in doc["lines"]]

        flipped = bake_project(self.root, resolution=lambda r: dataclasses.replace(
            r, stale_gates=frozenset(r.rows)))
        self.assertNotEqual([n["token"] for n in flipped.map_doc["nodes"] if "token" in n],
                            [n["token"] for n in self.baked.map_doc["nodes"] if "token" in n])
        self.assertEqual(structure(flipped.map_doc), structure(self.baked.map_doc))

    def test_the_same_state_gives_the_same_bytes(self):
        real = os.listdir
        again = bake_project(self.root, fresh=True)
        with mock.patch.object(os, "listdir", lambda p=".": list(reversed(real(p)))):
            shuffled = bake_project(self.root, fresh=True)
        for one, two in ((self.baked.map_doc, again.map_doc),
                         (self.baked.map_doc, shuffled.map_doc),
                         (self.baked.page_doc, shuffled.page_doc)):
            self.assertEqual(json.dumps(one, sort_keys=True), json.dumps(two, sort_keys=True))

    def test_seeded_ledgers_bake(self):
        import test_export
        for seed in range(0, 200, 10):
            ledger, stale = test_export.seeded(seed)
            baked = bake(ledger, _Res(stale_gates=stale))
            self.assertEqual(_keys(baked.map_doc) & _COORDINATES, set())
            self.assertEqual(sum(1 for n in baked.map_doc["nodes"] if n["kind"] == "claim"),
                             len(ledger.claims), seed)


# --------------------------------------------------------------------------- #
def _tracked(root: str) -> dict:
    site_dir = os.path.join(root, "site")
    found = {}
    for directory, _dirs, names in os.walk(site_dir):
        for name in names:
            path = os.path.join(directory, name)
            rel = os.path.relpath(path, site_dir).replace(os.sep, "/")
            if rel == "data/build.json":
                continue
            with open(path, "rb") as fh:
                found[rel] = (fh.read(), os.stat(path).st_mtime_ns)
    return found


class ARebuildThatJudgedNothingChangesNothing(_env.EnvCase):
    """(SPEC 32) Two builds differ only in the ignored `build.json`; a check
    of cache hits then a build moves nothing tracked; `state.json` holds no
    clock."""

    def test_two_builds_and_a_check_between(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        for argv in (["site", "init"], ["site", "build"]):
            self.assertEqual(_env.nopekit(argv, cwd=root).returncode, 0)
        before = _tracked(root)
        self.assertEqual(_env.nopekit(["site", "build"], cwd=root).returncode, 0)
        self.assertEqual(_tracked(root), before)
        self.assertIn(_env.nopekit(["check"], cwd=root).returncode, (0, 1))
        self.assertEqual(_env.nopekit(["site", "build"], cwd=root).returncode, 0)
        self.assertEqual(_tracked(root), before, "a check of cache hits moved the page")
        with open(os.path.join(root, "site", "data", "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
        self.assertNotIn("built", state["meta"])
        for row in state["verdicts"]:
            self.assertNotIn("when", row)
            self.assertNotIn("age_s", row)
        with open(os.path.join(root, "site", "data", "build.json"), encoding="utf-8") as fh:
            clock = json.load(fh)
        self.assertTrue(clock["built"])
        self.assertEqual(sorted(clock["verdicts"]), sorted(r["gate"] for r in state["verdicts"]))
        if shutil.which("git"):
            # The bracket's root ignores its whole built page; a project that
            # publishes its page tracks site/ and ignores only the clock.
            with open(os.path.join(root, ".gitignore"), encoding="utf-8") as fh:
                kept = [line for line in fh.read().splitlines(keepends=True)
                        if "site/" not in line]
            with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as fh:
                fh.write("".join(kept))
            _env.git(["init", "--quiet"], cwd=root)
            proc = _env.git(["check-ignore", "site/data/build.json"], cwd=root)
            self.assertEqual(proc.returncode, 0, "build.json is not ignored")
            proc = _env.git(["check-ignore", "site/data/map.json"], cwd=root)
            self.assertNotEqual(proc.returncode, 0, "map.json is ignored")


# --------------------------------------------------------------------------- #
class EvidenceReachesThePage(_env.EnvCase):
    """(SPEC 30) Evidence a verdict names is planned for the page from where it
    lives: under `.nopekit/out/` it is copied, keyed by its entry; on a fresh
    clone the earlier copy is kept; outside the project, out of `.nopekit/out/`
    through `..` or a link, hidden, ignored by git, too large or a directory it
    is named and never copied; clashing names get their own file; and the words
    baked beside one that is not copied never read this machine's disk."""

    def _plan(self, root: str, evidence: list, **kw) -> list:
        verdict = Verdict(gate="g.one", claims=["C1"], passed=True, evidence=evidence)
        view = dataclasses.replace(store.load(root), verdicts=[verdict])

        class Entry:
            name = "abc123-def456"

        class Row:
            entry = Entry()

        return page.evidence_plan(root, view, _Res(stale_gates=frozenset(),
                                                   rows={"g.one": Row()}), **kw)

    def test_each_place_evidence_can_be(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        out = store.out_dir(root)
        os.makedirs(os.path.join(out, "folder"), exist_ok=True)
        with open(os.path.join(out, "small.json"), "w") as fh:
            fh.write('{"deflection": 0.7}\n')
        with open(os.path.join(out, "big.bin"), "wb") as fh:
            fh.write(b"0" * (page.EVIDENCE_MAX_BYTES + 1))
        plan = self._plan(root, ["<out>/small.json", "<out>/big.bin", "<out>/folder",
                                 "<tmp>/x.json", "/etc/passwd", "../outside.txt",
                                 "<out>/gone.json", "<out>/small.json"])
        actions = [(p.name, p.action, p.href) for p in plan]
        dest = "assets/evidence/g.one/abc123-def456/"
        self.assertEqual(actions, [
            ("small.json", "copy", dest + "small.json"), ("big.bin", "none", None),
            ("folder", "none", None), ("x.json", "none", None), ("passwd", "none", None),
            ("outside.txt", "none", None), ("gone.json", "none", None),
            ("small.json", "copy", dest + "small-2.json")])
        said = page._site_words()["evidence"]
        # The baked words depend on the path only; why is the build's warning.
        self.assertEqual([p.missing for p in plan[1:7]],
                         [said["not_copied"], said["not_copied"], said["outside"],
                          said["outside"], said["outside"], said["not_copied"]])
        self.assertIn("cap", plan[1].reason)
        self.assertIn("directory", plan[2].reason)
        self.assertIn("not on this computer", plan[6].reason)
        # A fresh clone: the source is gone, the entry-keyed copy is kept.
        target = os.path.join(root, "site", *(dest + "gone.json").split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w") as fh:
            fh.write("{}\n")
        [kept] = [p for p in self._plan(root, ["<out>/gone.json"])]
        self.assertEqual((kept.action, kept.href), ("keep", dest + "gone.json"))

    def test_nothing_leaves_its_place(self):
        """`<out>/..` and a link in `.nopekit/out/` never reach a file outside
        it; a bare path never reaches a hidden or a git-ignored file (review of
        phase 5: each was copied into the published site)."""
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        out = store.out_dir(root)
        os.makedirs(out, exist_ok=True)
        secret = os.path.join(os.path.dirname(root), "outside.txt")
        with open(secret, "w") as fh:
            fh.write("a secret\n")
        with open(os.path.join(root, ".env"), "w") as fh:
            fh.write("TOKEN=1\n")
        with open(os.path.join(root, "private.log"), "w") as fh:
            fh.write("log\n")
        linked = hasattr(os, "symlink")
        if linked:
            try:
                os.symlink(secret, os.path.join(out, "link.txt"))
            except OSError:
                linked = False
        said = page._site_words()["evidence"]
        plan = self._plan(root, ["<out>/../../outside.txt", "<out>/../../../outside.txt",
                                 ".env", "private.log"] + (["<out>/link.txt"] if linked else []),
                          ignored=lambda rel: rel == "private.log")
        for item in plan:
            with self.subTest(item.path):
                self.assertEqual((item.action, item.source, item.dest), ("none", None, None))
        self.assertEqual([p.missing for p in plan[:2]], [said["outside"], said["outside"]])
        self.assertIn("hidden", plan[2].reason)
        self.assertIn("git ignores it", plan[3].reason)
        if linked:
            self.assertIn("link", plan[4].reason)

    def test_names_that_clash_get_their_own_file(self):
        """`a.json`, `x/a.json` and `a-2.json`; `a b.json` and `a_b.json`;
        `Plot.png` and `plot.png`: each its own destination, case ignored
        (review of phase 5: two of each planned one file)."""
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        out = store.out_dir(root)
        names = ["a.json", "x/a.json", "a-2.json", "a b.json", "a_b.json", "Plot.png",
                 "plot.png"]
        for name in names:
            path = os.path.join(out, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as fh:
                fh.write(name + "\n")
        plan = self._plan(root, [f"<out>/{n}" for n in names])
        dests = [p.dest for p in plan]
        self.assertTrue(all(dests), dests)
        self.assertEqual(len({d.casefold() for d in dests}), len(names), dests)

    def test_through_a_build(self):
        """A verdict names `<out>/sag.json`: the build copies it to the href
        page.json and state.json link, a second build moves no byte, and a
        fresh clone (the source gone) keeps the copy (review of phase 5: no
        build ever copied evidence in a test, so a cleaner that removed every
        copy went unseen)."""
        from test_site_truth import _fresh_registry, _main, _snapshot
        from nopekit import verdicts as verdicts_mod
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        out = store.out_dir(root)
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, "sag.json"), "w") as fh:
            fh.write('{"sag": 0.7, "units": "mm"}\n')
        real = verdicts_mod.view

        def with_evidence(*a, **kw):
            found = real(*a, **kw)
            return dataclasses.replace(found, verdicts=[
                dataclasses.replace(v, evidence=["<out>/sag.json"])
                if v.gate == "bracket.deflection" else v for v in found.verdicts])

        def build() -> dict:
            _fresh_registry(self)
            with mock.patch.object(verdicts_mod, "view", with_evidence):
                code, said = _main("site", "build", "-C", root, "--json")
            self.assertEqual(code, 0, said)
            return json.loads(said)

        _fresh_registry(self)
        self.assertEqual(_main("site", "init", "-C", root)[0], 0)
        summary = build()
        self.assertEqual(summary["evidence"]["copied"], 1)
        with open(os.path.join(root, "site", "data", "page.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        [row] = [e for e in doc["claims"]["C1"]["evaluators"] if e["id"] == "bracket.deflection"]
        [item] = row["evidence"]
        self.assertTrue(item["href"].startswith("assets/evidence/bracket.deflection/"))
        copy = os.path.join(root, "site", *item["href"].split("/"))
        with open(copy, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"sag": 0.7, "units": "mm"})
        with open(os.path.join(root, "site", "data", "state.json"), encoding="utf-8") as fh:
            state = json.load(fh)
        [vrow] = [v for v in state["verdicts"] if v["gate"] == "bracket.deflection"]
        self.assertEqual(vrow["evidence_assets"], [item["href"]])
        site_dir = os.path.join(root, "site")
        before = {k: v for k, v in _snapshot(site_dir).items() if not k.endswith("build.json")}
        self.assertEqual(build()["wrote"], [])
        after = {k: v for k, v in _snapshot(site_dir).items() if not k.endswith("build.json")}
        self.assertEqual(after, before)
        os.remove(os.path.join(out, "sag.json"))
        summary = build()
        self.assertEqual(summary["evidence"]["kept"], 1)
        self.assertTrue(os.path.isfile(copy), "a fresh clone lost the copy")
        after = {k: v for k, v in _snapshot(site_dir).items() if not k.endswith("build.json")}
        self.assertEqual(after, before, "a fresh clone baked other bytes")


# --------------------------------------------------------------------------- #
class TheBracketShowsTheOutline(_env.EnvCase):
    """(SPEC 28, 30) The reference project's page: four boards in requirement
    order, seven lines, its stations, every piece of text current with no
    unmatched number and no register problem. Red here after a status moved:
    read the text again, then `nopekit site stamp --all` in examples/bracket."""

    def test_the_outline(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        self.assertEqual(_env.nopekit(["site", "init"], cwd=root).returncode, 0)
        proc = _env.nopekit(["site", "build", "--json"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        summary = json.loads(proc.stdout)
        self.assertEqual(summary["map"]["lines"], 7)
        self.assertEqual(summary["outline"]["current"], page.OUTLINE)
        self.assertEqual(summary["outline"]["marker"], page.OUTLINE, "the shell's marker")
        with open(os.path.join(root, "site", "data", "map.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual([n["key"] for n in doc["nodes"] if n["kind"] == "board"],
                         ["strength", "prints", "pump", "outdoors"])
        self.assertEqual([n["key"] for n in doc["nodes"] if n["kind"] == "station"],
                         ["allowable", "@slenderness"])
        self.assertEqual({p["subject"]: p["stamp"] for p in summary["prose"]},
                         {s: "current" for s in ("intro", "next", "outdoors", "prints",
                                                  "pump", "strength")},
                         "the bracket's text is behind: read it again, then `nopekit site "
                         "stamp --all` in examples/bracket")
        for piece in summary["prose"]:
            self.assertEqual((piece["unmatched"], piece["register"], piece["problems"]),
                             ([], [], []), piece["file"])


if __name__ == "__main__":
    unittest.main()
