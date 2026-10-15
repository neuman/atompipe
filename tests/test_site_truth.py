# SPDX-License-Identifier: Apache-2.0
"""Invariant 14: the site never says more than the resolution, and stamped prose
is flagged when behind (architecture phase 5, SPEC 28-33).

Every status, word, count, order, margin and *ready* that `site build` bakes
into `site/data/` comes from `claims.compose` through `graph.tokens`,
`claims.unresolved` and `claims.margin`, on the resolution every reader uses.
These classes try to break that from each side: a baked token that differs
from the composition, prose stamped against an older resolution shown
unflagged, a number in prose that no baked file holds shown unflagged, and a
milestone's next steps that are not the predicate's (invariant 12).

What slipped through before them: the reference page decided its go/no-go in
the browser from a hand-kept claim list, so a claim added to a board never
reached it; and nothing kept prose from saying a claim passes after it failed.

Every expectation here is computed by the test itself, from the compositions
and `claims.unresolved`, never through `page.status_problems` — the checker the
build uses is held to the same answers, not trusted for them.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_site_truth.py'
"""
from __future__ import annotations

import contextlib
import dataclasses
import io
import json
import os
import re
import shutil
import tempfile
import unittest
from typing import Any, NamedTuple
from unittest import mock

import _env
import _projects
import test_export
from nopekit import claims as claims_mod
from nopekit import cli, gates as gates_mod, graph, page, prose, report, site, store, verdicts
from nopekit.models import Group

NOW = "2026-10-15T00:00:00Z"


class Baked(NamedTuple):
    view: Any
    composed: dict
    toks: Any
    lay: Any
    map_doc: dict
    page_doc: dict


class _Res(NamedTuple):
    """A resolution stand-in for an in-memory ledger: its stale gates, no rows."""

    stale_gates: frozenset
    rows: dict = {}
    track: dict = {}
    anchors: Any = None
    verdicts: list = []


def bake(view: Any, resolution: Any, registry: Any = None, *, projection: Any = None,
         root: str = "", built: Any = None, params: Any = ()) -> Baked:
    """`map.json` and `page.json` of ``view`` under ``resolution``, in process,
    as `site.build` bakes them (no prose, no evidence copy)."""
    composed = claims_mod.compositions(view, registry=registry,
                                       stale_gates=frozenset(resolution.stale_gates))
    toks = graph.tokens(view, resolution, registry, composed=composed)
    if built is None:
        built = graph.build(view, resolution, registry, projection=projection, design=None,
                            views=params)
    lay = page.layout(view, built, projection=projection, params=params, registry=registry,
                      resolution=resolution)
    payload = {"meta": {"stale": bool(resolution.stale_gates)}, "verdicts": [], "views": []}
    map_doc = page.bake_map(view, lay, built, toks, composed, projection=projection,
                            params=params, registry=registry, payload=payload)
    page_doc = page.bake_page(root or tempfile.gettempdir(), view, lay, built, toks, composed,
                              registry=registry, payload=payload)
    return Baked(view, composed, toks, lay, map_doc, page_doc)


#: Each project's resolution, once per process: the in-process rows only read
#: it (every variant is a `dataclasses.replace`), and resolving the bracket is
#: most of what a row costs (the fast tier's budget).
_WORLDS: dict[str, tuple] = {}


def resolved(root: str, *, fresh: bool = False) -> tuple:
    """``(view, resolution, registry, projection, built, params)`` of the project
    at ``root``, as `status` resolves it, in process — remembered per root
    unless ``fresh``."""
    if not fresh and root in _WORLDS:
        return _WORLDS[root]
    ledger = cli._load(root)
    registry, _ = cli._registry(root, ledger)
    model, projection, error = cli._projection_safe(root, ledger)
    view, resolution = cli._resolved(root, ledger, registry, projection, error, now=NOW,
                                     model=model)
    params = cli._shown_params(root, ledger, model, error, resolution, registry,
                               projection=projection)
    built = graph.of(root, view, resolution, registry, projection=projection, model=model,
                     views=params, bases=cli._input_bases(root, ledger))
    _WORLDS[root] = (view, resolution, registry, projection, built, params)
    return _WORLDS[root]


def bake_project(root: str, *, fresh: bool = False, **changes: Any) -> Baked:
    view, resolution, registry, projection, built, params = resolved(root, fresh=fresh)
    if "view" in changes:
        view = changes.pop("view")(view)
    if "resolution" in changes:
        resolution = changes.pop("resolution")(resolution)
    return bake(view, resolution, registry, projection=projection, root=root, built=built,
                params=params)


# -- the test's own answers ------------------------------------------------- #
def _token(found: Any) -> str:
    return "errored" if found.errored else claims_mod.STATUS_KEY[found.status]


def _worst(ids: list, composed: dict) -> str:
    """The worst token among ``ids``, by `SEVERITY_ORDER`, computed here; Gap
    with none."""
    tokens = [_token(composed[c]) for c in ids if c in composed]
    if not tokens:
        return "gap"
    return min(tokens, key=claims_mod.SEVERITY_ORDER.index)


def disagreements(baked: Baked) -> list[str]:
    """Every place the baked documents say a status, a *ready*, a margin or a
    mark other than the compositions and the predicate — computed here."""
    out: list[str] = []
    composed, view, toks = baked.composed, baked.view, baked.toks
    want = {cid: _token(found) for cid, found in composed.items()}
    disagree = set(toks.disagree.get("claims") or ())

    def check(where: str, said: Any, expected: Any) -> None:
        if said != expected:
            out.append(f"{where}: {said!r}, expected {expected!r}")

    nodes = baked.map_doc["nodes"]
    check("claim nodes", sorted(n["key"] for n in nodes if n["kind"] == "claim"),
          sorted(want))
    for node in nodes:
        if node["kind"] == "claim":
            check(f"claim:{node['key']}", node["token"], want[node["key"]])
            check(f"claim:{node['key']} marks", "disagree" in node["marks"],
                  node["key"] in disagree)
        elif node["kind"] == "board":
            check(f"board:{node['key']}", node["token"], _worst(node["claims"], composed))
        elif node["kind"] == "requirement":
            check(f"requirement:{node['key']}", node["token"],
                  toks.requirements.get(node["key"]))
    for line in baked.map_doc["lines"]:
        check(f"line {line['claim']}", line["token"], want[line["claim"]])
    for cid, row in baked.page_doc["claims"].items():
        check(f"floor {cid}", row["token"], want[cid])
        claim = next(c for c in view.claims if c.id == cid)
        for value in row["values"]:
            if value.get("gate") is None:
                continue
            verdict = next(v for v in claims_mod.covering_verdicts(claim, view.verdicts)
                           if v.gate == value["gate"])
            fraction = claims_mod.margin(verdict).fraction
            check(f"floor {cid} {value['gate']} margin", value["margin"],
                  None if fraction is None else float(f"{fraction:.6g}"))
            if value["compared"]:
                # The words beside a compared value: inside the CLAIM's limit
                # only when the claim's condition holds it (review of phase 5).
                state = claims_mod.cross_check(claim, verdict).state
                text = value["value_text"]
                if state == "fails":
                    check(f"floor {cid} {value['gate']} words", "inside the limit" in text, False)
                if state == "holds":
                    check(f"floor {cid} {value['gate']} words", "past the limit" in text, False)
    site_words = report.HUMAN["site"]
    word = {token: row["word"] for token, row in baked.page_doc["words"]["tokens"].items()}
    for section in baked.page_doc["sections"]:
        check(f"section {section['board']}", section["token"],
              _worst(section["claims"], composed))
        check(f"section {section['board']} word", section["word"], word[section["token"]])
    for cid, row in baked.page_doc["claims"].items():
        check(f"floor {cid} word", row["word"], word[row["token"]])
    found = claims_mod.unresolved(view, composed)
    check("verdict ready", baked.page_doc["verdict"]["ready"], bool(found.ready))
    project = baked.page_doc["next"]["project"]
    if project is not None:
        check("project ready", project["ready"], bool(found.ready))
        check("project token", project["token"], "ready" if found.ready else "not-ready")
        check("project word", project["word"],
              site_words["ready_word" if found.ready else "not_ready_word"])
    by_id = {m.id: m for m in getattr(view, "milestones", None) or ()}
    for group in baked.page_doc["next"]["milestones"]:
        expected = claims_mod.unresolved(view, composed, by_id[group["id"]])
        check(f"milestone {group['id']} ready", group["ready"], bool(expected.ready))
        check(f"milestone {group['id']} token", group["token"],
              "ready" if expected.ready else "not-ready")
        check(f"milestone {group['id']} word", group["word"],
              site_words["ready_word" if expected.ready else "not_ready_word"])
        check(f"milestone {group['id']} steps", sorted(s["claim"] for s in group["steps"]),
              sorted(c.id for c in expected.unresolved))
        check(f"milestone {group['id']} missing", [m["claim"] for m in group["missing"]],
              list(expected.missing))
        for step in group["steps"]:
            check(f"step {step['claim']}", step["token"], want[step["claim"]])
            check(f"step {step['claim']} marks", "disagree" in step["marks"],
                  step["claim"] in disagree)
    return out


_SHARED: list[str] = []


def _bracket(cls: type) -> str:
    """One migrated bracket copy per process, for the in-process rows that only
    read it (they bake from `resolved`, which remembers it): copying and
    resolving it once is what keeps these rows inside the fast tier's budget.
    A row that writes into its project copies its own."""
    if not _SHARED:
        import atexit
        tmp = tempfile.mkdtemp(prefix="nopekit-site-truth-")
        atexit.register(_env._rmtree, tmp)
        _SHARED.append(_projects.bracket_copy(os.path.join(tmp, "bracket"), migrated=True))
    return _SHARED[0]


def _fresh_registry(case: unittest.TestCase) -> None:
    saved = gates_mod.REGISTRY
    gates_mod.REGISTRY = gates_mod.Registry()
    case.addCleanup(setattr, gates_mod, "REGISTRY", saved)


def _main(*argv: str) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue() + err.getvalue()


def _snapshot(folder: str) -> dict:
    found: dict[str, tuple] = {}
    for directory, _dirs, names in os.walk(folder):
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as fh:
                found[os.path.relpath(path, folder)] = (fh.read(), os.stat(path).st_mtime_ns)
    return found


# --------------------------------------------------------------------------- #
class TheSiteNeverSaysMoreThanTheResolution(_env.EnvCase):
    """(invariant 14) Every token, *ready*, margin and mark on the map, the
    floor, the sections and next steps is the composition's, over a matrix of
    states; a planted producer is refused whole; a hand edit reads *edited by
    hand*; the map and the round record agree."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _bracket(cls)

    def test_the_bracket_and_its_variants(self):
        def stale_all(resolution):
            return dataclasses.replace(resolution, stale_gates=frozenset(resolution.rows))

        def tightened_c3(view):
            claims = [dataclasses.replace(c, acceptance=dataclasses.replace(
                c.acceptance, limit=0.1)) if c.id == "C3" else c for c in view.claims]
            return dataclasses.replace(view, claims=claims)

        def missing_id(view):
            milestone = dataclasses.replace(view.milestones[0], id="spare",
                                            requires=["C1", "C99"])
            return dataclasses.replace(view, milestones=[*view.milestones, milestone])

        states = {"the bracket at 7 mm": {}, "every gate stale": {"resolution": stale_all},
                  "a milestone with a missing id": {"view": missing_id},
                  "C3 tightened below its evaluator's limit": {"view": tightened_c3}}
        for name, changes in states.items():
            with self.subTest(name):
                baked = bake_project(self.root, **changes)
                self.assertEqual(disagreements(baked), [])
                self.assertEqual(page.status_problems(baked.map_doc, baked.page_doc,
                                                      baked.view, baked.composed,
                                                      baked.toks), [])
        baked = bake_project(self.root, resolution=stale_all)
        self.assertIn("stale", {n["token"] for n in baked.map_doc["nodes"]
                                if n["kind"] == "claim"}, "the stale state reached no claim")

    def test_a_failing_claim_never_reads_inside_its_limit(self):
        """C3's limit tightened to 0.1 MPa, below the 15 MPa bracket.bearing
        judges against: C3 reads failing, and no word beside its value, on the
        floor or on the map, says it is inside the limit (S-35 on the page,
        review of phase 5: it read "99% inside the limit")."""
        def tightened(view):
            claims = [dataclasses.replace(c, acceptance=dataclasses.replace(
                c.acceptance, limit=0.1)) if c.id == "C3" else c for c in view.claims]
            return dataclasses.replace(view, claims=claims)

        baked = bake_project(self.root, view=tightened)
        row = baked.page_doc["claims"]["C3"]
        self.assertEqual(row["token"], "failing")
        [value] = [v for v in row["values"] if v["gate"] == "bracket.bearing"]
        self.assertIn("0.1 MPa", value["value_text"])
        self.assertIn("past the limit", value["value_text"])
        self.assertNotIn("inside", value["value_text"])
        node = next(n for n in baked.map_doc["nodes"] if n["key"] == "C3")
        self.assertNotIn("inside", node["value_text"])
        self.assertEqual(disagreements(baked), [])
        planted = json.loads(json.dumps(baked.page_doc))
        [v] = [v for v in planted["claims"]["C3"]["values"] if v["gate"] == "bracket.bearing"]
        v["value_text"] = "0.195 MPa against a limit of 0.1 MPa, 99% inside the limit"
        self.assertTrue(page.status_problems(baked.map_doc, planted, baked.view, baked.composed,
                                             baked.toks))
        self.assertTrue(disagreements(baked._replace(page_doc=planted)))

    def test_a_forced_disagreement_is_marked(self):
        with mock.patch.object(report, "_disagreement",
                               lambda view, claim, composed, cover: claim.id == "C2"):
            baked = bake_project(self.root)
        self.assertEqual(disagreements(baked), [])
        node = next(n for n in baked.map_doc["nodes"] if n["key"] == "C2")
        self.assertEqual((node["token"], node["marks"]), ("checked", ["disagree"]))
        board = next(n for n in baked.map_doc["nodes"] if n["key"] == "strength")
        self.assertEqual(board["marks"], ["disagree"])

    def test_every_eighth_seeded_ledger(self):
        found: list[str] = []
        for seed in range(0, 400, 8):
            ledger, stale = test_export.seeded(seed)
            baked = bake(ledger, _Res(stale_gates=stale))
            found += [f"seed {seed}: {p}" for p in disagreements(baked)]
            found += [f"seed {seed}: checker: {p}" for p in page.status_problems(
                baked.map_doc, baked.page_doc, baked.view, baked.composed, baked.toks)]
        self.assertEqual(found[:12], [], f"{len(found)} disagreements")

    def test_the_checker_names_each_planted_lie(self):
        """`page.status_problems` names a claim, a line, a floor row, a board, a
        section, a step, *ready* and a mark the resolution does not say."""
        baked = bake_project(self.root)
        plants = {
            "claim node": lambda m, p: next(n for n in m["nodes"]
                                            if n["key"] == "C1").update(token="checked"),
            "line": lambda m, p: m["lines"][0].update(token="checked"),
            "board": lambda m, p: next(n for n in m["nodes"]
                                       if n["key"] == "strength").update(token="checked"),
            "requirement": lambda m, p: next(n for n in m["nodes"]
                                             if n["key"] == "R1").update(token="checked"),
            "floor row": lambda m, p: p["claims"]["C1"].update(token="checked"),
            "section": lambda m, p: p["sections"][0].update(token="checked"),
            "step": lambda m, p: p["next"]["milestones"][0]["steps"][0].update(
                token="checked"),
            "ready": lambda m, p: p["verdict"].update(ready=True),
            "milestone ready": lambda m, p: p["next"]["milestones"][0].update(ready=True),
            "mark": lambda m, p: next(n for n in m["nodes"]
                                      if n["key"] == "C1").update(marks=["disagree"]),
            "milestone token": lambda m, p: p["next"]["milestones"][0].update(token="ready"),
            "milestone word": lambda m, p: p["next"]["milestones"][0].update(word="ready"),
            "section word": lambda m, p: p["sections"][0].update(word="checked"),
            "floor word": lambda m, p: p["claims"]["C1"].update(word="checked"),
            "step mark": lambda m, p: p["next"]["milestones"][0]["steps"][0].update(
                marks=["disagree"]),
        }
        for name, plant in plants.items():
            with self.subTest(name):
                map_doc = json.loads(json.dumps(baked.map_doc))
                page_doc = json.loads(json.dumps(baked.page_doc))
                plant(map_doc, page_doc)
                self.assertTrue(page.status_problems(map_doc, page_doc, baked.view,
                                                     baked.composed, baked.toks), name)
                self.assertTrue(disagreements(baked._replace(map_doc=map_doc,
                                                             page_doc=page_doc)), name)

    def test_the_project_group_is_held_too(self):
        """With no milestone the project's group says *ready*: its ready, token
        and word are the predicate's, and a planted one is named."""
        def no_milestones(view):
            return dataclasses.replace(view, milestones=[])

        baked = bake_project(self.root, view=no_milestones)
        self.assertIsNotNone(baked.page_doc["next"]["project"])
        self.assertEqual(disagreements(baked), [])
        for plant in ({"ready": True}, {"token": "ready"}, {"word": "ready"}):
            with self.subTest(plant):
                planted = json.loads(json.dumps(baked.page_doc))
                planted["next"]["project"].update(plant)
                self.assertTrue(page.status_problems(baked.map_doc, planted, baked.view,
                                                     baked.composed, baked.toks))
                self.assertTrue(disagreements(baked._replace(page_doc=planted)))

    def test_a_planted_producer_is_refused_whole(self):
        """`site build` with a `bake_map` that says C1 is checked raises, and no
        file under `site/data/` changes, by bytes or mtime."""
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        _fresh_registry(self)
        self.assertEqual(_main("site", "init", "-C", root)[0], 0)
        self.assertEqual(_main("site", "build", "-C", root)[0], 0)
        data = os.path.join(root, "site", "data")
        before = _snapshot(data)
        real = page.bake_map

        def lying(*a, **kw):
            doc = real(*a, **kw)
            for node in doc["nodes"]:
                if node.get("key") == "C1":
                    node["token"] = "checked"
            return doc

        gates_mod.REGISTRY = gates_mod.Registry()
        with mock.patch.object(page, "bake_map", lying):
            code, said = _main("site", "build", "-C", root)
        self.assertEqual(code, 2, said)
        self.assertIn("the page would say more than the resolution", said)
        self.assertIn("claim:C1 reads checked", said)
        self.assertEqual(_snapshot(data), before, "a refused build wrote under site/data/")

    def test_a_hand_edit_reads_edited_by_hand(self):
        """A hand-edited `map.json` reads *edited by hand* in `site status` and a
        FAIL in doctor's `site` row, with the seal broken and resealed."""
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        for argv in (["site", "init"], ["site", "build"]):
            self.assertEqual(_env.nopekit(argv, cwd=root).returncode, 0)
        path = os.path.join(root, "site", "data", "map.json")
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        for node in doc["nodes"]:
            if node.get("key") == "C1":
                node["token"] = "checked"
        for resealed in (False, True):
            with self.subTest(resealed=resealed):
                if resealed:
                    doc["self"] = page.seal(doc)
                with open(path, "w", encoding="utf-8") as fh:
                    json.dump(doc, fh)
                info = json.loads(_env.nopekit(["site", "status", "--json"], cwd=root).stdout)
                self.assertTrue(info["edited"], info)
                self.assertIn("edited by hand", info["edited"][0])
                rows = json.loads(_env.nopekit(["doctor", "--json"], cwd=root).stdout)["checks"]
                [row] = [r for r in rows if r["check"] == "site"]
                self.assertEqual(row["status"], "FAIL", row)
                line = [t for t in _env.nopekit(["status"], cwd=root).stdout.splitlines()
                        if t.startswith("site:")]
                self.assertIn("edited by hand", line[0])

    def test_the_map_and_the_round_record_agree(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        self.assertEqual(_env.nopekit(["site", "init"], cwd=root).returncode, 0)
        proc = _env.nopekit(["round"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        with open(os.path.join(root, "site", "data", "map.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        with open(os.path.join(root, ".nopekit", "round.json"), encoding="utf-8") as fh:
            record = json.load(fh)
        self.assertEqual({n["key"]: n["token"] for n in doc["nodes"] if n["kind"] == "claim"},
                         record["claims"])
        self.assertEqual({n["key"]: n["token"] for n in doc["nodes"]
                          if n["kind"] == "requirement"}, record["requirements"])


# --------------------------------------------------------------------------- #
def stamp_problems(baked: Baked, root: str) -> list[str]:
    """Each baked prose piece whose stamp state or notice is not what an
    independent recomputation of its digest says — computed here, with
    `prose.stamp_digest` over the tokens this function gathers itself."""
    out: list[str] = []
    marks = {cid: ["disagree"] for cid in baked.toks.disagree.get("claims") or ()}

    def tok(cid: str) -> str:
        token = baked.toks.claims[cid]
        return f"{token}:{','.join(marks[cid])}" if cid in marks else token

    pieces = [(s["board"], s["prose"]) for s in baked.page_doc["sections"] if s["prose"]]
    if baked.page_doc["intro"]:
        pieces.append(("intro", baked.page_doc["intro"]))
    if baked.page_doc["next"]["prose"]:
        pieces.append(("next", baked.page_doc["next"]["prose"]))
    for subject, piece in pieces:
        if subject in ("intro", "next"):
            tokens = {cid: tok(cid) for cid in baked.toks.claims}
            tokens["_readiness"] = baked.toks.readiness
            tokens.update({f"_m:{m}": t for m, t in baked.toks.milestones.items()})
        else:
            [section] = [s for s in baked.page_doc["sections"] if s["board"] == subject]
            # A board's text is stamped against its claims AND every claim it
            # names, read here from its own runs (review of phase 5).
            named = []
            for block in piece["blocks"]:
                lists = (block.get("items") or []) if block["type"] in ("ul", "ol") else [
                    block.get("caption") or [] if block["type"] == "figure"
                    else block.get("runs") or []]
                for runs in lists:
                    named += [r["claim"] for r in runs if "claim" in r
                              and r["claim"] not in section["claims"] and r["claim"] not in named]
            tokens = {cid: tok(cid) for cid in section["claims"]}
            tokens.update({f"@{cid}": tok(cid) for cid in named})
        with open(os.path.join(root, "site", "content", f"{subject}.md"),
                  encoding="utf-8") as fh:
            as_of = prose.parse_front_matter(fh.read()).as_of
        want = ("unstamped" if not as_of else
                "current" if as_of == prose.stamp_digest(subject, tokens) else "stale")
        if piece["stamp"] != want:
            out.append(f"{subject}: baked {piece['stamp']}, the digest says {want}")
        if (piece["notice"] == "") != (want == "current"):
            out.append(f"{subject}: the notice is {piece['notice']!r} for a {want} piece")
    return out


def _write(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)


class StampedProseIsFlaggedWhenBehind(_env.EnvCase):
    """(invariant 14) Prose reads current only while its stamp equals the digest
    of its claims' tokens now; a moved claim, a regroup and a missing stamp each
    flag it; a planted stamp state is named by an independent recomputation;
    `site stamp` writes only the `as_of` line."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _bracket(cls)

    def _bake(self, **changes: Any) -> tuple[Baked, list]:
        baked = bake_project(self.root, **changes)
        rows = page.bake_prose(self.root, baked.page_doc, baked.lay, baked.toks,
                               prose.number_pool([baked.map_doc, baked.page_doc]))
        return baked, rows

    def test_the_brackets_text_is_current(self):
        baked, rows = self._bake()
        self.assertEqual({r["subject"]: r["stamp"] for r in rows},
                         {s: "current" for s in ("intro", "next", "outdoors", "prints",
                                                  "pump", "strength")},
                         "the bracket's text is stamped: `nopekit site stamp --all`")
        self.assertEqual(stamp_problems(baked, self.root), [])
        self.assertEqual([s["prose"]["notice"] for s in baked.page_doc["sections"]],
                         ["", "", "", ""])

    def test_a_moved_claim_flags_its_board_and_no_other(self):
        real = graph.tokens

        def flipped(*a, **kw):
            found = real(*a, **kw)
            return found._replace(claims={**found.claims, "C1": "checked"})

        with mock.patch.object(graph, "tokens", flipped):
            baked, rows = self._bake()
        states = {r["subject"]: r["stamp"] for r in rows}
        self.assertEqual(states["strength"], "stale")
        self.assertEqual(states["outdoors"], "current")
        self.assertEqual(states["intro"], "stale", "intro reads every claim's token")
        section = next(s for s in baked.page_doc["sections"] if s["board"] == "strength")
        self.assertEqual(section["prose"]["notice"],
                         report.HUMAN["site"]["notices"]["prose_stale"])
        self.assertEqual(stamp_problems(baked, self.root), [])

    def test_a_regroup_flags_the_board(self):
        def regroup(view):
            groups = [dataclasses.replace(g, members=[m for m in g.members if m != "C6"])
                      if g.id == "strength" else g for g in view.groups]
            groups.append(Group(id="assumed", kind="board", title="Assumed",
                                members=["C6"], order=9))
            return dataclasses.replace(view, groups=groups)

        baked, rows = self._bake(view=regroup)
        self.assertEqual({r["subject"]: r["stamp"] for r in rows}["strength"], "stale")
        self.assertEqual(stamp_problems(baked, self.root), [])

    def test_unstamped_text_is_flagged(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        _write(os.path.join(root, "site", "content", "pump.md"), "The pump runs.\n")
        baked = bake_project(root)
        rows = page.bake_prose(root, baked.page_doc, baked.lay, baked.toks,
                               prose.number_pool([baked.map_doc]))
        self.assertEqual({r["subject"]: r["stamp"] for r in rows}["pump"], "unstamped")
        section = next(s for s in baked.page_doc["sections"] if s["board"] == "pump")
        self.assertEqual(section["prose"]["notice"],
                         report.HUMAN["site"]["notices"]["prose_unstamped"])
        self.assertEqual(stamp_problems(baked, root), [])

    def test_a_claim_named_from_another_board_moves_the_stamp(self):
        """prints.md names C1 (on strength): stamped now, it reads stale once
        C1's token moves, though prints holds no claim of strength's. In
        process, over a content folder of its own beside the shared bracket.
        What slipped through (review of phase 5): a board's stamp held its own
        claims only, so "C1 fails" read current after C1 passed."""
        folder = self.tmp()
        baked = bake_project(self.root)
        body = "C1 fails, so the arm must be thicker before the print.\n"
        named = page.prose_named(body, baked.toks.claims)
        self.assertEqual(named, ["C1"])
        as_of = prose.stamp_digest("prints", page.subject_tokens(
            "prints", baked.lay.boards, baked.toks, named=named))
        _write(os.path.join(folder, "site", "content", "prints.md"),
               prose.stamp_text(body, as_of))
        rows = page.bake_prose(folder, baked.page_doc, baked.lay, baked.toks,
                               prose.number_pool([baked.map_doc]))
        self.assertEqual({r["subject"]: r["stamp"] for r in rows}, {"prints": "current"})
        real = graph.tokens

        def flipped(*a, **kw):
            found = real(*a, **kw)
            return found._replace(claims={**found.claims, "C1": "checked"})

        with mock.patch.object(graph, "tokens", flipped):
            baked = bake_project(self.root)
        rows = page.bake_prose(folder, baked.page_doc, baked.lay, baked.toks,
                               prose.number_pool([baked.map_doc]))
        self.assertEqual({r["subject"]: r["stamp"] for r in rows}, {"prints": "stale"})
        self.assertEqual(stamp_problems(baked, folder), [])

    def test_site_stamp_stamps_a_named_claim_too(self):
        """`site stamp prints` over text that names C1 writes the digest the
        build reads current: the command and the build stamp one set."""
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        path = os.path.join(root, "site", "content", "prints.md")
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        _write(path, text + "\nC1 fails, so the arm must be thicker before the print.\n")
        proc = _env.nopekit(["site", "stamp", "prints"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        baked = bake_project(root, fresh=True)
        rows = page.bake_prose(root, baked.page_doc, baked.lay, baked.toks,
                               prose.number_pool([baked.map_doc]))
        self.assertEqual({r["subject"]: r["stamp"] for r in rows}["prints"], "current")
        with open(path, encoding="utf-8") as fh:
            as_of = prose.parse_front_matter(fh.read()).as_of
        self.assertNotEqual(as_of, prose.stamp_digest("prints", page.subject_tokens(
            "prints", baked.lay.boards, baked.toks)), "the stamp left out the named claim")

    def test_the_checker_reads_the_baked_prose(self):
        """`page.status_problems` names a stale piece baked as current, a notice
        taken away, an `as_of` that is not the file's, and a number run whose
        `match` is not the scan's: a resealed page cannot show behind text as
        current (invariant 14's second half, review of phase 5)."""
        real = graph.tokens

        def flipped(*a, **kw):
            found = real(*a, **kw)
            return found._replace(claims={**found.claims, "C1": "checked"})

        with mock.patch.object(graph, "tokens", flipped):
            baked, _rows = self._bake()
        bare = json.loads(json.dumps(baked.page_doc))
        for section in bare["sections"]:
            section["prose"] = None
        bare["intro"] = None
        bare["next"]["prose"] = None
        pool = prose.number_pool([baked.map_doc, bare])
        with open(os.path.join(self.root, "site", "content", "strength.md"),
                  encoding="utf-8") as fh:
            as_of = {"strength": prose.parse_front_matter(fh.read()).as_of}

        def problems(doc: dict) -> list:
            # Only the prose's: the flipped token moves C1 on the map but not
            # in the compositions, which the step rows are held to.
            return [p for p in page.status_problems(
                baked.map_doc, doc, baked.view, baked.composed, baked.toks,
                prose_as_of=as_of, pool=pool) if p.startswith("prose")]

        self.assertEqual(problems(baked.page_doc), [])

        def strength(doc: dict) -> dict:
            return next(s for s in doc["sections"] if s["board"] == "strength")["prose"]

        def first_number(doc: dict) -> dict:
            return prose.number_runs(strength(doc)["blocks"])[0]

        plants = {
            "stale shown current": lambda d: strength(d).update(stamp="current", notice=""),
            "notice removed": lambda d: strength(d).update(notice=""),
            "as_of moved": lambda d: strength(d).update(as_of="0" * 16),
            "number match flipped": lambda d: first_number(d).update(
                match=not first_number(d)["match"]),
        }
        for name, plant in plants.items():
            with self.subTest(name):
                doc = json.loads(json.dumps(baked.page_doc))
                plant(doc)
                self.assertTrue(problems(doc), name)

    def test_a_planted_stamp_state_is_named(self):
        real = graph.tokens

        def flipped(*a, **kw):
            found = real(*a, **kw)
            return found._replace(claims={**found.claims, "C1": "checked"})

        with mock.patch.object(graph, "tokens", flipped), \
                mock.patch.object(page, "stamp_state", lambda as_of, current: "current"):
            baked, _rows = self._bake()
        self.assertTrue(any(p.startswith("strength:") for p in stamp_problems(baked,
                                                                               self.root)))

    def test_site_stamp_writes_only_the_as_of_line(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        content = os.path.join(root, "site", "content")
        path = os.path.join(content, "strength.md")
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        planted = text.replace(prose.parse_front_matter(text).as_of, "0" * 16).replace(
            "\n", "\r\n")
        _write(path, planted)
        records = {rel: data for rel, data in _projects_files(root).items()}
        proc = _env.nopekit(["site", "stamp", "strength"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertRegex(proc.stdout, r"site/content/strength\.md: as_of [0-9a-f]{16} \(was "
                                      r"0{16}, stale\)")
        after = _projects_files(root)
        moved = sorted(rel for rel in set(records) | set(after)
                       if records.get(rel) != after.get(rel))
        self.assertEqual(moved, ["site/content/strength.md"])
        with open(path, encoding="utf-8", newline="") as fh:
            new = fh.read()
        old_lines, new_lines = planted.split("\r\n"), new.split("\r\n")
        self.assertEqual(len(old_lines), len(new_lines), "a line was added or removed")
        self.assertEqual([i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b],
                         [1], "a line other than as_of moved")
        proc = _env.nopekit(["site", "stamp", "strength"], cwd=root)
        self.assertIn("already current", proc.stdout)
        for argv, needle in ((["site", "stamp", "nowhere"], "no board named 'nowhere'"),
                             (["site", "stamp"], "site stamp needs a board name")):
            proc = _env.nopekit(argv, cwd=root)
            self.assertEqual(proc.returncode, 2, proc.stdout)
            self.assertIn(needle, proc.stderr)
        os.remove(os.path.join(content, "pump.md"))
        proc = _env.nopekit(["site", "stamp", "pump"], cwd=root)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("site/content/pump.md does not exist", proc.stderr)
        proc = _env.nopekit(["site", "stamp", "--all", "--json"], cwd=root)
        self.assertEqual(json.loads(proc.stdout)["stamped"], [])


class TheReadersSayTheTextIsBehind(_env.EnvCase):
    """`site status`, `status` and `doctor` over a built bracket: stamped text
    reads ok; text edited after the build reads the page stale; text stamped
    against older results is doctor's `site text` warning, naming the command;
    and a page resealed to show behind text as current reads edited by hand.
    What slipped through (review of phase 5): none of these had a test, so a
    doctor that always said every text was stamped went green."""

    def test_the_readers(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        for argv in (["site", "init"], ["site", "build"]):
            self.assertEqual(_env.nopekit(argv, cwd=root).returncode, 0)

        def doctor_row(name: str) -> dict:
            rows = json.loads(_env.nopekit(["doctor", "--json"], cwd=root).stdout)["checks"]
            [row] = [r for r in rows if r["check"] == name]
            return row

        def site_status() -> dict:
            return json.loads(_env.nopekit(["site", "status", "--json"], cwd=root).stdout)

        row = doctor_row("site text")
        self.assertEqual(row["status"], "ok", row)
        self.assertIn("each stamped against the current results", row["detail"])
        self.assertFalse(site_status()["stale"])

        path = os.path.join(root, "site", "content", "strength.md")
        with open(path, encoding="utf-8", newline="") as fh:
            text = fh.read()
        _write(path, text + "\nThe arm is printed flat on the bed.\n")
        info = site_status()
        self.assertTrue(info["stale"], info)
        self.assertIn("the text in site/content/ changed since the site was built",
                      info["stale_reason"])

        as_of = prose.parse_front_matter(text).as_of
        _write(path, text.replace(as_of, "0" * 16))
        row = doctor_row("site text")
        self.assertEqual(row["status"], "warn", row)
        self.assertIn("site/content/strength.md is written before the latest results",
                      row["detail"])
        self.assertIn("`nopekit site stamp strength`", row["detail"])

        # Built with the stale text, then the page resealed to show it current.
        self.assertEqual(_env.nopekit(["site", "build"], cwd=root).returncode, 0)
        page_path = os.path.join(root, "site", "data", "page.json")
        with open(page_path, encoding="utf-8") as fh:
            doc = json.load(fh)
        [section] = [s for s in doc["sections"] if s["board"] == "strength"]
        self.assertEqual(section["prose"]["stamp"], "stale")
        section["prose"].update(stamp="current", notice="")
        doc["self"] = page.seal(doc)
        with open(page_path, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        info = site_status()
        self.assertTrue(info["edited"], info)
        self.assertIn("prose strength reads current", info["edited"][0])
        self.assertEqual(doctor_row("site")["status"], "FAIL")


def _projects_files(root: str) -> dict[str, bytes]:
    """Every file under ``root`` but the ignored outputs a command rebuilds."""
    out: dict[str, bytes] = {}
    for directory, dirs, names in os.walk(root):
        rel_dir = os.path.relpath(directory, root).replace(os.sep, "/")
        if rel_dir.startswith((".nopekit/cache", ".nopekit/obs", ".nopekit/out")):
            continue
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in names:
            rel = os.path.relpath(os.path.join(directory, name), root).replace(os.sep, "/")
            if rel in (".nopekit/ledger.json",) or name.endswith(".lock"):
                continue
            with open(os.path.join(directory, name), "rb") as fh:
                out[rel] = fh.read()
    return out


# --------------------------------------------------------------------------- #
#: The test's own copy of the pool's key rules (structure left out, counts and
#: fractions tagged), written out here so a change to `prose`'s sets is caught.
_STRUCTURE = {"schema", "outline", "order", "column", "columns", "severity", "rank", "row",
              "index", "tier"}
_COUNTS = {"n", "errored", "counts", "by_key", "ground", "tally", "legend", "n_claims",
           "n_critical", "n_gaps", "n_gates"}
_FRACTIONS = {"margin", "fraction"}


def independent_unmatched(blocks: list, docs: list) -> list[str]:
    """Each `num` run whose baked `match` differs from a match computed here:
    its own pool (every finite numeric leaf but structure keys, absolute, with
    the units of the object holding it, a count or a fraction) and its own rule
    (half a unit of the last decimal; a unit must agree or be unstated; a
    count only for a bare number; a percent against a fraction times 100)."""
    pool: list[tuple[float, str]] = []

    def walk(node: Any, tag: str) -> None:
        if isinstance(node, dict):
            stated = node.get("units", node.get("unit"))
            own = (str(stated).strip().replace("µ", "u") if isinstance(stated, str)
                   else tag if tag in ("#count", "#fraction") else "")
            for key, value in node.items():
                if key in _STRUCTURE:
                    continue
                walk(value, "#count" if key in _COUNTS or own == "#count"
                     else "#fraction" if key in _FRACTIONS else own)
        elif isinstance(node, list):
            for value in node:
                walk(value, tag)
        elif isinstance(node, (int, float)) and not isinstance(node, bool):
            pool.append((abs(float(node)), tag))

    for doc in docs:
        walk(doc, "")
    out: list[str] = []
    for run in prose.number_runs(blocks):
        text = run["num"].replace(",", "").replace("−", "-")
        x = abs(float(text))
        mantissa, _e, exponent = text.lower().partition("e")
        decimals = (len(mantissa.split(".", 1)[1]) if "." in mantissa else 0) - int(exponent or 0)
        tol = 0.5 * 10 ** -decimals + 1e-9 * max(1.0, x)
        unit = run["unit"].replace("µ", "u")

        def near(y: float, want: float) -> bool:
            return abs(y - want) <= tol

        if unit == "%":
            hit = any((t in ("#fraction", "") and near(y * 100, x))
                      or (t in ("", "%") and near(y, x)) for y, t in pool)
        elif unit:
            hit = any(t in (unit, "") and near(y, x) for y, t in pool)
        else:
            hit = any(near(y, x) for y, _t in pool)
        if hit != run["match"]:
            out.append(f"{run['t']}: baked {run['match']}, the pool says {hit}")
    return out


class ANumberNoBakedFileHoldsIsFlagged(unittest.TestCase):
    """(invariant 14) Every number in prose matches a baked number at its
    precision or is marked; identifiers, code and paths are never scanned; a
    planted matcher that matches everything is caught by an independent pool."""

    POOL = prose.number_pool([{"measured": 0.6997084548104956, "limit": 0.5,
                               "margin": -0.3994, "values": [1200, 220]}])

    def scan(self, text: str) -> tuple[list, list]:
        blocks, _problems = prose.parse_markdown(text, claims=["C1"])
        return prose.scan_numbers(blocks, self.POOL)

    def test_the_precision_rule(self):
        for written, decimals, percent, want in (("0.70", 2, False, True),
                                                 ("0.7", 1, False, True),
                                                 ("0.700", 3, False, True),
                                                 ("0.69", 2, False, False),
                                                 ("40", 0, True, True),
                                                 ("1,200", 0, False, True),
                                                 ("−0.40", 2, False, True),
                                                 ("12", 0, False, False)):
            with self.subTest(written):
                self.assertIs(prose.matches(written, decimals, percent, self.POOL), want)

    def test_what_is_scanned_and_what_is_not(self):
        _blocks, unmatched = self.scan(
            "C1 sags 0.70 mm, 40% past. A 12mm arm on a 3D print, v0.1, `0.41`, "
            "[a 9.9 link](https://example.com/0.41) and 1,200 N.\n\n"
            "![arm](content/img/arm-0.41.png \"the arm\")\n")
        self.assertEqual(unmatched, ["12 mm", "9.9"])

    def test_joined_units_and_bare_fractions_are_read(self):
        """A number joined to any letters but an identifier suffix is read with
        those letters as its unit, a fraction with no leading 0 and a power of
        ten are read, and none of these matches a pool that holds no such value
        (review of phase 5: each read as unmarked)."""
        for text, want in (("The pump moves 12L/h.", ["12 L/h"]),
                           ("It carries 40Nm at the root.", ["40 Nm"]),
                           ("The tip sags .9 mm.", [".9 mm"]),
                           ("It lasts about 5e4 cycles.", ["5e4"]),
                           ("The tip sags 3.2mm.", ["3.2 mm"]),
                           ("A 3D print, the 1st print and an M3 bolt.", [])):
            with self.subTest(text):
                self.assertEqual(self.scan(text)[1], want)

    def test_a_unit_must_agree_and_structure_never_matches(self):
        """A count matches a bare number only, a fraction a percentage, a value
        its own unit or one no key states; a row, an index or a tier matches
        nothing (review of phase 5: "3 mm" matched a count of 3 claims, "40%" a
        limit of 40 N, and every small integer a row)."""
        pool = prose.number_pool([
            {"nodes": [{"row": 3, "index": 5, "tier": 6}], "legend": [{"token": "gap", "n": 4}]},
            {"limit": 40, "units": "N"}, {"measured": 0.7, "units": "mm", "margin": -0.25},
            {"value": 2.0, "units": ""}])
        for text, unit, percent, want in (("3", "", False, False), ("5", "", False, False),
                                          ("6", "", False, False), ("4", "", False, True),
                                          ("4", "mm", False, False), ("40", "N", False, True),
                                          ("40", "", True, False), ("25", "", True, True),
                                          ("0.70", "mm", False, True), ("0.70", "N", False, False),
                                          ("2", "kg", False, True), ("0.25", "mm", False, False)):
            with self.subTest(f"{text} {unit}{'%' if percent else ''}"):
                self.assertIs(prose.matches(text, prose._precision(text), percent, pool, unit),
                              want)
        blocks, _ = prose.parse_markdown("The tip sags 3 mm. The arm sags 4 mm. 4 claims.")
        _blocks, unmatched = prose.scan_numbers(blocks, pool)
        self.assertEqual(unmatched, ["3 mm", "4 mm"])

    def test_the_prose_never_matches_itself(self):
        blocks, unmatched = self.scan("The tip moves 0.4321 mm.")
        self.assertEqual(unmatched, ["0.4321 mm"])
        doc = {"blocks": blocks}
        self.assertNotIn(0.4321, prose.number_pool([doc]).values,
                         "a number in prose is a string, never a pooled leaf")

    def test_a_planted_matcher_is_caught(self):
        text = "The tip sags 0.41 mm and 0.70 mm."
        blocks, _ = prose.parse_markdown(text)
        honest, _ = prose.scan_numbers(blocks, self.POOL)
        docs = [{"measured": 0.6997084548104956}]
        self.assertEqual(independent_unmatched(honest, docs), [])
        with mock.patch.object(prose, "matches", lambda *a: True):
            lying, unmatched = prose.scan_numbers(blocks, self.POOL)
        self.assertEqual(unmatched, [])
        self.assertEqual(independent_unmatched(lying, docs),
                         ["0.41 mm: baked True, the pool says False"])

    def test_an_asset_the_build_removes_vouches_for_nothing(self):
        """An old evidence copy under site/assets/ holds 0.4512; prose quotes it.
        The build that removes the copy marks the number already, and a second
        build with nothing new judged writes no byte (review of phase 5: the
        pool read the copy before the cleaner removed it, so the number passed
        once, and the next build marked it and rewrote page.json)."""
        root = _projects.bracket_copy(os.path.join(tempfile.mkdtemp(prefix="nopekit-num-"),
                                                   "bracket"), migrated=True)
        self.addCleanup(_env._rmtree, os.path.dirname(root))
        _fresh_registry(self)
        self.assertEqual(_main("site", "init", "-C", root)[0], 0)
        old = os.path.join(root, "site", "assets", "evidence", "bracket.deflection", "oldentry",
                           "result.json")
        _write(old, '{"deflection": 0.4512, "units": "mm"}\n')
        path = os.path.join(root, "site", "content", "prints.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        _write(path, text + "\nAn older print sagged 0.4512 mm.\n")
        code, said = _main("site", "build", "-C", root, "--json")
        self.assertEqual(code, 0, said)
        summary = json.loads(said)
        self.assertFalse(os.path.exists(old), "the cleaner kept an asset no view or verdict links")
        [piece] = [p for p in summary["prose"] if p["subject"] == "prints"]
        self.assertEqual(piece["unmatched"], ["0.4512 mm"])
        site_dir = os.path.join(root, "site")
        before = {k: v for k, v in _snapshot(site_dir).items() if not k.endswith("build.json")}
        _fresh_registry(self)
        code, said = _main("site", "build", "-C", root, "--json")
        self.assertEqual(code, 0, said)
        self.assertEqual(json.loads(said)["wrote"], [])
        after = {k: v for k, v in _snapshot(site_dir).items() if not k.endswith("build.json")}
        self.assertEqual(after, before, "a build that judged nothing new moved a byte")

    def test_through_a_build(self):
        root = _projects.bracket_copy(os.path.join(tempfile.mkdtemp(prefix="nopekit-num-"),
                                                   "bracket"), migrated=True)
        self.addCleanup(_env._rmtree, os.path.dirname(root))
        path = os.path.join(root, "site", "content", "strength.md")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        _write(path, text + "\nThe tip sags 0.41 mm on the next print.\n")
        _fresh_registry(self)
        self.assertEqual(_main("site", "init", "-C", root)[0], 0)
        code, said = _main("site", "build", "-C", root)
        self.assertEqual(code, 0, said)
        self.assertIn("site/content/strength.md: 0.41 mm matches no number the site bakes; "
                      "the page marks it", said)
        with open(os.path.join(root, "site", "data", "page.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
        [section] = [s for s in doc["sections"] if s["board"] == "strength"]
        runs = [r for b in section["prose"]["blocks"] for r in b.get("runs", ())]
        self.assertIn({"num": "0.41", "unit": "mm", "match": False, "t": "0.41 mm"}, runs)
        self.assertEqual(section["prose"]["unmatched"], ["0.41 mm"])


# --------------------------------------------------------------------------- #
class NextStepsAreThePredicate(unittest.TestCase):
    """(invariant 12) Next steps are `claims.unresolved`'s: each milestone's
    steps its unresolved claims in severity order, its `ready` the predicate's,
    an id no claim holds under `missing`, `next` on the first milestone that is
    not ready; with no milestone, the required claims' group."""

    def test_over_the_seeds(self):
        found: list[str] = []
        reached = set()
        for seed in range(0, 400, 4):
            ledger, stale = test_export.seeded(seed)
            baked = bake(ledger, _Res(stale_gates=stale))
            composed, nxt = baked.composed, baked.page_doc["next"]
            milestones = sorted(test_export._milestones_of(ledger),
                                key=lambda m: store._natural(m.id))
            if not milestones:
                expected = claims_mod.unresolved(ledger, composed)
                group = nxt["project"]
                if [s["claim"] for s in group["steps"]] != [
                        c.id for c in report.in_severity(ledger, composed, expected.unresolved)]:
                    found.append(f"seed {seed}: the project's steps")
                if group["ready"] is not bool(expected.ready):
                    found.append(f"seed {seed}: the project's ready")
                continue
            first = next((m.id for m in milestones
                          if not claims_mod.unresolved(ledger, composed, m).ready), None)
            for group, milestone in zip(nxt["milestones"], milestones):
                expected = claims_mod.unresolved(ledger, composed, milestone)
                reached.add(bool(expected.ready))
                if group["id"] != milestone.id:
                    found.append(f"seed {seed}: milestone order")
                if [s["claim"] for s in group["steps"]] != [
                        c.id for c in report.in_severity(ledger, composed, expected.unresolved)]:
                    found.append(f"seed {seed} {milestone.id}: steps")
                if [m["claim"] for m in group["missing"]] != list(expected.missing):
                    found.append(f"seed {seed} {milestone.id}: missing")
                if group["ready"] is not bool(expected.ready):
                    found.append(f"seed {seed} {milestone.id}: ready")
                if group["next"] is not (milestone.id == first):
                    found.append(f"seed {seed} {milestone.id}: next")
            if nxt["project"] is not None:
                found.append(f"seed {seed}: a project group beside milestones")
        self.assertEqual(found[:12], [], f"{len(found)} disagreements")
        self.assertEqual(reached, {True, False}, "the seeds reached one answer only")

    def test_every_cause_has_its_steps(self):
        """`page.settle`'s table is exhaustive over `ClaimCause`, and every
        command it names parses with the CLI's parser."""
        parser = cli.build_parser()
        for cause in claims_mod.ClaimCause:
            self.assertIn(cause.value, page._SETTLE, cause)
            key, commands = page._SETTLE[cause.value]
            for command in commands:
                argv = command.format(id="C1", gate="g.one", authority="Dana",
                                      authority_arg="Dana", milestone="print-v1",
                                      tier_flag=" --tier 2").split()
                self.assertEqual(argv[0], "nopekit")
                with contextlib.redirect_stderr(io.StringIO()):
                    args = parser.parse_args(argv[1:])
                if argv[1:3] == ["claim", "physical"] and "pass" in argv:
                    # The pass `claim physical` takes: its evidence always, a
                    # judgment its authority (review of phase 5: the page
                    # printed a pass the command refuses for no --evidence).
                    self.assertTrue(args.evidence, command)
                    if key == "judgment":
                        self.assertEqual(args.authority, "Dana", command)
            if key is not None:
                self.assertIn(key, report.HUMAN["site"]["settle"])

    def test_a_built_article_with_no_milestone_says_how_to_build_it(self):
        """A physical claim no milestone requires: no `export` command, the text
        that names a milestone file, and the pass with its evidence."""
        claim = mock.Mock(id="C5", authority="")
        composed = mock.Mock(cause=claims_mod.ClaimCause("no-article"), verdict=None, cites=[])
        said = report.HUMAN["site"]["settle"]
        found = page.settle(claim, composed, milestone=None)
        self.assertEqual(found["text"], said["article_free"].format(id="C5"))
        self.assertEqual(found["commands"],
                         ["nopekit claim physical C5 pass --evidence <file>"])
        found = page.settle(claim, composed, milestone="print-v1")
        self.assertEqual(found["text"], said["article"].format(id="C5"))
        self.assertEqual(found["commands"][0], "nopekit export print-v1")


# --------------------------------------------------------------------------- #
# the template side: the browser computes no truth
# --------------------------------------------------------------------------- #
#: What a page script must never do (SPEC 32, invariant 14), as patterns over
#: its CODE (`_template.js_code`: comments gone, each string's text blanked, a
#: template literal's `${...}` kept). Each has a planted violator below.
BROWSER_TRUTH = {
    # A verdict row's flags beside its status: the resolver's word is `status`.
    # `.error` is read as a flag when it decides (`?`, `&&`, `!`); its text as
    # a fallback (`v.error || v.detail`) is a word, not a decision.
    "a verdict flag": re.compile(r"\.(?:passed|skipped)\b|\.error\b\s*(?:\?|&&)|!\s*[\w.$]*\.error\b"),
    # Arithmetic against a limit: the margin is `claims.margin`'s, baked.
    "arithmetic on a limit": re.compile(
        r"\b\w*[lL]imit\w*(?:\.\w+)*\s*[-+*/%](?![=*/>])|[-+*/%]\s*(?:\w+\.)*\w*[lL]imit\w*\b"),
    # A worst-of or an all-of over statuses: a board's token, readiness.
    "every or some over a status": re.compile(
        r"\.(?:every|some)\s*\([^;]*?\.(?:status|token|outcome|key)\b"),
    # A sort keyed on a status: the reading order is baked (`order`, `severity`).
    "a sort over a status": re.compile(
        r"\.sort\s*\([^;]*?(?:\.(?:status|token|outcome)\b|[A-Z_]{4,}\s*\[)"),
    # An age judged in the browser: `aged` and `mixed_age` are build.json's.
    "an age compared": re.compile(r"\bage_s\b\s*[<>]=?|[<>]=?\s*[\w.]*\bage_s\b"),
}


def browser_truth(sources: dict) -> list:
    """Each line of a page script that computes truth: ``name:line: rule``."""
    import _template
    out = []
    for name, text in sources.items():
        code = _template.js_code(text)
        for number, line in enumerate(code.splitlines(), 1):
            for rule, pattern in BROWSER_TRUTH.items():
                if pattern.search(line):
                    out.append(f"{name}:{number}: {rule}: {line.strip()[:90]}")
    return out


class TheBrowserComputesNoTruth(unittest.TestCase):
    """(invariant 14, the template side) No page script computes a status, a
    margin, readiness, a reading order or an age: every one is in a baked file
    (SPEC 32). The scan reads every `.js` file the template ships, the front
    page's and the technical record's, and a planted violator of each rule is
    caught. What slipped through before phase 5: the template ranked anchored
    verdicts by their `error`, `passed` and `skipped` flags beside the
    resolver's status, sorted verdict rows by a status table of its own,
    subtracted a chart's limit from its value, and judged ages against a day."""

    @classmethod
    def setUpClass(cls) -> None:
        import _template
        cls.sources = _template.template_files(".js")

    def test_the_template_computes_no_truth(self):
        self.assertIn("lib/map.js", self.sources)
        self.assertIn("page.js", self.sources)
        self.assertEqual(browser_truth(self.sources), [])

    def test_a_planted_violator_of_each_rule_is_caught(self):
        planted = {
            "a verdict flag": "const rank = (a) => (a.verdict.error ? 0 : !a.verdict.passed ? 1 : 2);",
            "arithmetic on a limit": "const gap = current.y - limit.value;",
            "every or some over a status": 'const go = rows.every((c) => c.token === "checked");',
            "a sort over a status": "rows.sort((a, b) => RANK[a.status] - RANK[b.status]);",
            "an age compared": "const old = v.age_s >= 86400;",
        }
        self.assertEqual(sorted(planted), sorted(BROWSER_TRUTH))
        for rule, line in planted.items():
            with self.subTest(rule):
                source = dict(self.sources)
                source["page.js"] = source["page.js"] + "\n" + line + "\n"
                found = browser_truth(source)
                self.assertTrue(any(f": {rule}: " in f for f in found), found)

    def test_a_violator_in_a_comment_or_a_string_is_not_code(self):
        source = {"page.js": "// a.verdict.passed ? 1 : 0\nconst t = \"v.age_s >= 1\";\n"
                             "const u = `${x.age_s >= 2}`;\n"}
        found = browser_truth(source)
        self.assertEqual(len(found), 1, found)
        self.assertIn("an age compared", found[0])

    def test_the_lexer_reads_the_whole_template(self):
        """A quote the lexer misreads (inside a regex literal) would swallow
        code as string text and hide it from the scan: the code it reads must
        keep every function the template defines."""
        import _template
        for name, text in self.sources.items():
            with self.subTest(name):
                defined = re.findall(r"^(?:export )?(?:async )?function (\w+)", text, re.M)
                code = _template.js_code(text)
                for fn in defined:
                    self.assertRegex(code, rf"function {fn}\b", f"{name}: {fn} read as a string")


if __name__ == "__main__":
    unittest.main()


# --------------------------------------------------------------------------- #
def chip_calls_without_marks(sources: dict) -> list[str]:
    """Each `tokenChip(` call (in code, comments and strings blanked) whose
    arguments never name `marks`: a token drawn without the bake's marks."""
    import _template
    out = []
    for path, text in sources.items():
        code = _template.js_code(text)
        for found in re.finditer(r"\btokenChip\s*\(", code):
            if re.match(r"\s*token\s*,", code[found.end():]) and "export function" in \
                    code[max(0, found.start() - 20):found.start()]:
                continue                                 # the definition
            depth, at = 1, found.end()
            while depth and at < len(code):
                depth += {"(": 1, ")": -1}.get(code[at], 0)
                at += 1
            if "marks" not in code[found.end():at]:
                line = code.count("\n", 0, found.start()) + 1
                out.append(f"{path}:{line}: tokenChip without marks")
    return out


class TheTemplateShowsWhatItIsGiven(unittest.TestCase):
    """The template side of the review of phase 5, read from its sources: every
    chip carries the bake's marks; the map's rows grow with their text; the
    open drawer leaves the claims lane in view; a lit line keeps its status
    colour; the phone caption names cards; an unmatched number is said in
    words; the technical record fits a phone. Each rule has the defect it
    holds out named beside it."""

    @classmethod
    def setUpClass(cls) -> None:
        import _template
        cls.js = _template.template_files(".js")
        cls.css = _template.template_files(".css")
        cls.html = _template.template_files(".html")

    def _rules(self, css: str, selector: str) -> list[str]:
        """The bodies of the rules one of whose selectors is ``selector`` or
        holds it as a class (``hl2`` matches ``.track.hl2``)."""
        out = []
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
            selectors = [s.strip() for s in m.group(1).split(",")]
            if any(s == selector or re.search(rf"{re.escape(selector)}(?![\w-])", s)
                   for s in selectors):
                out.append(m.group(2))
        return out

    def test_every_chip_carries_its_marks(self):
        """A disagreeing claim, board or requirement is never a plain chip: on
        a phone, in a board's heading, in next steps, in the drawer (review of
        phase 5: the phone list and the headings drew a plain green chip)."""
        self.assertEqual(chip_calls_without_marks(self.js), [])
        planted = dict(self.js)
        planted["lib/sections.js"] += ("\nconst c = tokenChip(sec.token, sec.word, "
                                       "{ errored: 1 });\n")
        self.assertEqual(len(chip_calls_without_marks(planted)), 1)
        format_js = self.js["lib/format.js"]
        self.assertIn('marks || []).includes("disagree")', format_js)
        map_js = self.js["lib/map.js"]
        listed = map_js[map_js.index("export function mapList"):]
        self.assertIn("tokenChip(node.token", listed, "the phone list draws its own chip")
        drawn = map_js[map_js.index("---- capsules"):map_js.index("---- boards")]
        self.assertIn('(node.marks || []).includes("disagree")', drawn,
                      "a requirement's capsule drops its mark")

    def test_the_rows_grow_with_their_text(self):
        """Row and header sizes come from `metricsFor` at the drawn scale, and
        a resize to another size draws again (review of phase 5: at 900 px each
        title sat on its status line)."""
        map_js = self.js["lib/map.js"]
        body = map_js[map_js.index("export function renderMap"):]
        self.assertNotRegex(body, r"\b(?:ROW_H|HDR_H)\b",
                            "a row or header drawn at its 1400 px size")
        self.assertIn("metricsFor(", body)
        self.assertIn("onRescale", self.js["page.js"])

    def test_the_open_drawer_keeps_the_claims_in_view(self):
        """No rule fixes the map's width or scrolls its frame while the drawer
        is open (review of phase 5: a 1400 px map in an 840 px frame hid every
        glyph and word)."""
        css = self.css["map.css"]
        for body in self._rules(css, "drawer-open"):
            self.assertNotIn("overflow-x", body)
            self.assertNotRegex(body, r"(?<![-\w])width:\s*\d+px")
        self.assertFalse([b for b in self._rules(css, "drawer-open") if "1400px" in b])

    def test_a_lit_line_keeps_its_status_colour(self):
        """A line lit because the selected one rests on it is never repainted
        (review of phase 5: the accent made a gap read as pending build)."""
        for body in self._rules(self.css["map.css"], "hl2"):
            self.assertNotRegex(body, r"(?<![-\w])stroke\s*:")

    def test_the_phone_caption_names_cards(self):
        index = self.html["index.html"]
        phone = re.search(r'class="cap cap-phone">([^<]*)<', index)
        self.assertTrue(phone, "no phone caption")
        self.assertNotRegex(phone.group(1), r"\b(?:line|Point)\b")
        self.assertIn("body.map-phone .maptools .cap-desk { display: none; }", self.css["map.css"])

    def test_an_unmatched_number_is_said_in_words(self):
        """The mark is not the gap glyph, stays with its number, and the text
        under the prose says what it means (review of phase 5: a bare "?" that
        wrapped alone, its meaning in a tooltip only)."""
        page_css = self.css["page.css"]
        [mark] = self._rules(page_css, ".nk-unmatched::after")
        self.assertNotIn('"?"', mark.replace(" ", ""))
        self.assertNotIn('" ?"', mark)
        self.assertTrue(any("nowrap" in b for b in self._rules(page_css, ".nk-unmatched")))
        self.assertIn("notices.unmatched_note", self.js["lib/sections.js"])
        self.assertIn("unmatched_note", report.HUMAN["site"]["notices"])

    def test_the_technical_record_fits_a_phone(self):
        """The sheet's column may shrink, a verdict's value wraps and the badge
        stacks below 860 px (review of phase 5: 452 px wide at 390)."""
        style = self.css["style.css"]
        sheet = [b for b in self._rules(style, ".sheet") if "display: grid" in b]
        self.assertTrue(sheet and all("minmax(0, 1fr)" in b for b in sheet), sheet)
        phone = style[style.index("@media (max-width: 860px)"):]
        phone = phone[:phone.index("\n}\n")]
        self.assertRegex(phone, r"\.verdict-measure\s*\{\s*white-space:\s*normal")
        self.assertRegex(phone, r"\.made-with\s*\{\s*flex-direction:\s*column")
