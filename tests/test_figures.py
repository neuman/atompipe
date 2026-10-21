# SPDX-License-Identifier: Apache-2.0
"""Figures and evidence bound to the verdict entry they are evidence of (issue #15).

A file the page links as a result's evidence is the bytes the run that wrote
that result left behind, told by content, never by name. ``check`` records, per
verdict entry it writes, the sha256 of every file the verdict cites
(``.nopekit/cache/evidence/<gate>/<entry>.json``, scratch git ignores), and
``site build`` copies a file under ``assets/evidence/<gate>/<entry>/`` only when
its bytes are that manifest's. A file with other bytes keeps the copy an
earlier build made, or is not on the page, and the build says why.

What slipped through before this: ``page.evidence_plan`` took the served entry
from the resolution and copied whatever ``.nopekit/out`` held under the name the
verdict cited. A design that went A, B, A served A's entry from the cache while
``.nopekit/out`` held B's files, so the page published B's bytes as A's evidence
and overwrote A's earlier copy with them.

The fixture is ``_projects.figure_project`` (design B.6): ``demo.drop`` writes a
summary and a field file whose bytes move with ``x``.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_figures.py'
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import sys
import unittest
from unittest import mock

import _env
import _projects
from nopekit import verdicts

GATE = "demo.drop"


def run(case: _env.EnvCase, root: str, *argv: str, code: int | None = 0, env=None):
    proc = _env.nopekit(list(argv), cwd=root, env=env)
    if code is not None:
        case.assertEqual(proc.returncode, code,
                         f"`nopekit {' '.join(argv)}` exited {proc.returncode}:\n"
                         f"{proc.stdout[-3000:]}\n{proc.stderr[-3000:]}")
    return proc


def entries(root: str) -> set[str]:
    """The entry names ``demo.drop``'s verdict cache holds."""
    folder = os.path.join(root, ".nopekit", "verdicts", GATE)
    try:
        return {name[:-len(".json")] for name in os.listdir(folder)
                if name.endswith(".json") and not name.startswith("control-")}
    except OSError:
        return set()


def check_at(case: _env.EnvCase, root: str, x: float, *argv: str) -> str:
    """``x`` set, ``nopekit check`` run; the entry the run wrote or hit, read
    from the cache: the one new entry, else the one ``status`` serves."""
    _projects.set_figure_x(root, x)
    before = entries(root)
    run(case, root, "check", *argv)
    new = entries(root) - before
    if new:
        case.assertEqual(len(new), 1, new)
        return new.pop()
    return served(case, root)


def served(case: _env.EnvCase, root: str) -> str:
    """The entry ``site build`` serves for ``demo.drop``, read from state.json's
    verdict row after a build, or from the one entry whose summary says ``x``."""
    with open(os.path.join(root, "model", "m.py"), encoding="utf-8") as fh:
        x = float([line for line in fh.read().splitlines()
                   if line.startswith("    x: float = ")][0].split("=")[1])
    hits = []
    for name in entries(root):
        with open(os.path.join(root, ".nopekit", "verdicts", GATE, name + ".json"),
                  encoding="utf-8") as fh:
            if json.load(fh)["verdict"]["measured"] == round(2.0 * x, 6):
                hits.append(name)
    case.assertEqual(len(hits), 1, hits)
    return hits[0]


def build(case: _env.EnvCase, root: str, **kw) -> dict:
    if not os.path.isdir(os.path.join(root, "site")):
        run(case, root, "site", "init")
    proc = run(case, root, "site", "build", "--json", **kw)
    return json.loads(proc.stdout)


def published(root: str, entry: str) -> bytes | None:
    """The bytes the page publishes as ``entry``'s summary, or None."""
    path = os.path.join(root, "site", "assets", "evidence", GATE, entry, "summary.json")
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def summary_bytes(root: str) -> bytes:
    with open(os.path.join(root, ".nopekit", "out", "demo", "summary.json"), "rb") as fh:
        return fh.read()


# --------------------------------------------------------------------------- #
class EvidenceIsBoundByContent(_env.EnvCase):
    """(Invariant 14) Evidence reaches the page only as the bytes the run that
    wrote its entry left: a cache hit over another run's files publishes none
    of them, and an earlier copy is kept, never overwritten."""

    def test_a_cache_hit_never_publishes_another_runs_bytes(self):
        """Check x=1 (A), x=2 (B), x=1 (a cache hit: `.nopekit/out` holds B's
        files), then build: A's evidence is not on the page, and the build says
        the file is from another run. Red before issue #15's P1.1: B's bytes
        were published under A's entry."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        b = check_at(self, root, 2.0)
        b_bytes = summary_bytes(root)
        self.assertNotEqual(a, b)
        self.assertEqual(check_at(self, root, 1.0), a)
        self.assertEqual(summary_bytes(root), b_bytes, "the cache hit ran the gate")
        summary = build(self, root)
        self.assertIsNone(published(root, a), "B's bytes were published as A's evidence")
        self.assertNotIn(b_bytes, published_bytes(root))
        self.assertEqual(summary["evidence"]["copied"], 0, summary["evidence"])
        self.assertTrue(any("from another run" in w and GATE in w
                            for w in summary["warnings"]), summary["warnings"])

    def test_an_earlier_copy_is_never_overwritten_by_another_runs_bytes(self):
        """A drawn from its own run, then B solved again (its files in
        `.nopekit/out`) and A a cache hit: the build keeps A's copy and never
        overwrites it with B's bytes (the old build rewrote any copy whose bytes
        differed)."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        a_bytes = summary_bytes(root)
        build(self, root)
        self.assertEqual(published(root, a), a_bytes)
        check_at(self, root, 2.0)
        b_bytes = summary_bytes(root)
        self.assertNotEqual(a_bytes, b_bytes)
        self.assertEqual(check_at(self, root, 1.0), a)
        summary = build(self, root)
        self.assertEqual(published(root, a), a_bytes, "A's copy was overwritten with B's")
        self.assertEqual((summary["evidence"]["copied"], summary["evidence"]["kept"]), (0, 1))
        self.assertTrue(any("from another run" in w for w in summary["warnings"]),
                        summary["warnings"])
        # Solved again, A's own bytes are copied under A once more.
        run(self, root, "check", "--force", "--only", GATE)
        self.assertEqual(summary_bytes(root), a_bytes)
        summary = build(self, root)
        self.assertEqual((summary["evidence"]["copied"], summary["evidence"]["kept"]), (1, 0))
        self.assertEqual(published(root, a), a_bytes)

    def test_a_no_record_run_binds_nothing(self):
        """`check --no-record` on B leaves B's files in `.nopekit/out` and writes
        no manifest: nothing of B's reaches the page."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        _projects.set_figure_x(root, 2.0)
        run(self, root, "check", "--no-record")
        b_bytes = summary_bytes(root)
        self.assertEqual(manifests(root), {a})
        build(self, root)
        self.assertNotIn(b_bytes, published_bytes(root), "a --no-record run was published")

    def test_an_errored_runs_evidence_never_lands_under_the_stale_entry(self):
        """A row whose shown verdict is a crash citing the file, over A's entry:
        the crash's bytes are never published under A, and A's copy stays."""
        from test_site_truth import _fresh_registry, _main
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        a_bytes = summary_bytes(root)
        build(self, root)
        self.assertEqual(published(root, a), a_bytes)
        with open(os.path.join(root, ".nopekit", "out", "demo", "summary.json"), "ab") as fh:
            fh.write(b"crashed\n")
        crash_bytes = summary_bytes(root)
        real = verdicts.view

        def crashed(*a_, **kw):
            found = real(*a_, **kw)
            return dataclasses.replace(found, verdicts=[
                dataclasses.replace(v, passed=False, error="planted crash",
                                    evidence=["<out>/demo/summary.json"])
                if v.gate == GATE else v for v in found.verdicts])

        _fresh_registry(self)
        with mock.patch.object(verdicts, "view", crashed):
            code, said = _main("site", "build", "-C", root, "--json")
        self.assertEqual(code, 0, said)
        self.assertNotIn(crash_bytes, published_bytes(root), "a crash's file was published")
        self.assertEqual(published(root, a), a_bytes)

    def test_a_fresh_clone_keeps_the_committed_copy(self):
        """No `.nopekit/out`, no `.nopekit/cache` (a clone): the copy a build
        made stays linked, and the page is the same bytes."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        a_bytes = summary_bytes(root)
        build(self, root)
        page_before = page_bytes(root)
        for scratch in ("out", "cache"):
            shutil.rmtree(os.path.join(root, ".nopekit", scratch))
        summary = build(self, root)
        self.assertEqual((summary["evidence"]["copied"], summary["evidence"]["kept"]), (0, 1))
        self.assertEqual(published(root, a), a_bytes)
        self.assertEqual(page_bytes(root), page_before, "a fresh clone baked other bytes")

    def test_a_copy_made_before_the_manifest_is_kept(self):
        """A copy made before this change, whose entry has no manifest here: it
        stays linked, and the file on this computer never replaces it."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        a_bytes = summary_bytes(root)
        build(self, root)
        shutil.rmtree(os.path.join(root, ".nopekit", "cache", "evidence"))
        summary = build(self, root)
        self.assertEqual((summary["evidence"]["copied"], summary["evidence"]["kept"]), (0, 1))
        self.assertTrue(any("no recorded run" in w for w in summary["warnings"]),
                        summary["warnings"])
        check_at(self, root, 2.0)
        self.assertEqual(check_at(self, root, 1.0), a)
        shutil.rmtree(os.path.join(root, ".nopekit", "cache", "evidence"))
        build(self, root)
        self.assertEqual(published(root, a), a_bytes)


def manifests(root: str) -> set[str]:
    """The entry names ``demo.drop``'s evidence manifests are written for."""
    folder = os.path.join(root, ".nopekit", "cache", "evidence", GATE)
    try:
        return {name[:-len(".json")] for name in os.listdir(folder)}
    except OSError:
        return set()


def published_bytes(root: str) -> list[bytes]:
    """The bytes of every file under ``site/assets/evidence``."""
    found = []
    for directory, _dirs, names in os.walk(os.path.join(root, "site", "assets", "evidence")):
        for name in names:
            with open(os.path.join(directory, name), "rb") as fh:
                found.append(fh.read())
    return found


def page_bytes(root: str) -> bytes:
    with open(os.path.join(root, "site", "data", "page.json"), "rb") as fh:
        return fh.read()


def tree(root: str, *, but: str) -> dict[str, bytes]:
    """Every file under ``root`` but ``but/`` and ``.git/``, by posix path."""
    found = {}
    for directory, dirs, names in os.walk(root):
        rel = os.path.relpath(directory, root).replace(os.sep, "/")
        if rel in (but, ".git") or rel.startswith((but + "/", ".git/")):
            dirs[:] = []
            continue
        for name in names:
            path = os.path.join(directory, name)
            with open(path, "rb") as fh:
                found[os.path.relpath(path, root).replace(os.sep, "/")] = fh.read()
    return found


# --------------------------------------------------------------------------- #
class TheEvidenceManifestIsScratch(_env.EnvCase):
    """(Invariant 8) The evidence manifest is scratch: `check` writes it only
    under `.nopekit/cache/`, which git ignores, for an entry it recorded, and
    never for a `--no-record` run or a control; `site build` writes nothing
    outside `site/` but what git ignores."""

    def test_check_writes_the_manifest_only_where_git_ignores(self):
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        rel = f".nopekit/cache/evidence/{GATE}/{a}.json"
        with open(os.path.join(root, *rel.split("/")), encoding="utf-8") as fh:
            doc = json.load(fh)
        body = summary_bytes(root)
        files = {"<out>/demo/summary.json": {"sha256": hashlib.sha256(body).hexdigest(),
                                             "bytes": len(body)}}
        self.assertEqual(doc, {"schema": 1, "gate": GATE, "entry": a, "files": files})
        self.assertEqual(verdicts.evidence_manifest(root, GATE, a), files)
        self.assertEqual(_env.git(["check-ignore", "-q", rel], cwd=root).returncode, 0,
                         f"{rel} is not ignored")
        listed = _env.git(["status", "--porcelain", "--untracked-files=all"], cwd=root).stdout
        self.assertNotIn(".nopekit/cache", listed)
        # The reader refuses a manifest of another gate or entry, and junk.
        other = os.path.join(root, ".nopekit", "cache", "evidence", GATE, "0" * 16 + "-"
                             + "0" * 8 + ".json")
        with open(other, "w", encoding="utf-8") as fh:
            json.dump({**doc, "entry": a}, fh)
        self.assertIsNone(verdicts.evidence_manifest(root, GATE, "0" * 16 + "-" + "0" * 8))
        with open(other, "w", encoding="utf-8") as fh:
            fh.write("{not json")
        self.assertIsNone(verdicts.evidence_manifest(root, GATE, "0" * 16 + "-" + "0" * 8))
        self.assertIsNone(verdicts.evidence_manifest(root, GATE, "../" + a))

    def test_no_record_and_controls_write_none(self):
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        run(self, root, "check", "--no-record")
        self.assertFalse(os.path.exists(os.path.join(root, ".nopekit", "cache", "evidence")))
        a = check_at(self, root, 1.0)
        # The known-good control, the known-bad one and the mutation ran too.
        self.assertTrue(any(name.startswith("control-") for name in
                            os.listdir(os.path.join(root, ".nopekit", "verdicts", GATE))))
        found = []
        for directory, _dirs, names in os.walk(os.path.join(root, ".nopekit", "cache",
                                                            "evidence")):
            found += [os.path.join(directory, name) for name in names]
        self.assertEqual([os.path.basename(p) for p in found], [a + ".json"])

    def test_site_build_writes_only_site_and_ignored_scratch(self):
        """And a bound viewgen's scratch (`.nopekit/out/figures/`) and its live
        3D file (`site/assets/live/`) are both where git ignores them."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        run(self, root, "site", "init")
        draw_settings(root, glb="live")
        before = tree(root, but="site")
        build(self, root, env=draw.env)
        after = tree(root, but="site")
        moved = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        live = ["site/" + p for p in figure_files(root) if p.startswith("assets/live/")]
        self.assertTrue([p for p in moved if p.startswith(".nopekit/out/figures/")], moved)
        self.assertEqual(len(live), 1, figure_files(root))
        for rel in moved + live:
            with self.subTest(rel):
                self.assertEqual(_env.git(["check-ignore", "-q", rel], cwd=root).returncode, 0,
                                 f"site build wrote {rel}, which git does not ignore")
        self.assertFalse([p for p in moved if p.startswith(".nopekit/cache/evidence/")],
                         "site build wrote a manifest")


# --------------------------------------------------------------------------- #
# An unbound viewgen that needs a tool, and the prose figures beside it
# --------------------------------------------------------------------------- #
STILL = "demo.still"
STILL_TOOL = "nopekit-test-still"

#: An UNBOUND viewgen (no `evidence_of`): it needs the tool `STILL_TOOL`, writes
#: a picture with `write_asset` and a payload over `site.VIEW_INLINE_MAX` (split
#: into `data/views/demo.still.json`), and crashes when `views/still.mode` says
#: `crash`. Strings only in its payload: no number of it may vouch for prose.
_STILL_VIEWGEN = '''\
import os

from nopekit.models import View, ViewKind
from nopekit.site import viewgen


@viewgen(id="demo.still", kind=ViewKind.IMAGE, title="A still",
         requires_tools=["nopekit-test-still"])
def still(ctx):
    """A still of the demo; it needs nopekit-test-still on PATH."""
    path = os.path.join(ctx.root, "views", "still.mode")
    mode = open(path, encoding="utf-8").read().strip() if os.path.exists(path) else "ok"
    if mode == "crash":
        raise RuntimeError("planted crash in the still")
    src = ctx.write_asset("demo_still.png", b"a still, drawn " + mode.encode())
    return View(id="demo.still", kind=ViewKind.IMAGE, src=src,
                data={"notes": ["note " + chr(97 + i % 26) * (1 + i % 7)
                                for i in range(900)]})
'''


def plant_still(case: _env.EnvCase, root: str) -> dict:
    """The still's viewgen in ``root/views/``; return the environment that puts
    its tool on PATH (`_env.run`'s ``env``)."""
    os.makedirs(os.path.join(root, "views"), exist_ok=True)
    with open(os.path.join(root, "views", "still.py"), "w", encoding="utf-8",
              newline="\n") as fh:
        fh.write(_STILL_VIEWGEN)
    tools = case.tmp()
    tool = os.path.join(tools, STILL_TOOL)
    with open(tool, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(tool, 0o755)
    return {"PATH": tools + os.pathsep + os.environ.get("PATH", "")}


def still_mode(root: str, mode: str) -> None:
    with open(os.path.join(root, "views", "still.mode"), "w", encoding="utf-8") as fh:
        fh.write(mode)


def plant_prose_figure(root: str, src: str) -> None:
    """``site/content/intro.md`` holding one figure at ``src`` (site-relative),
    and a picture there."""
    for rel, data in ((src, b"a picture the agent placed"),
                      ("content/intro.md", f"The demo.\n\n![A picture]({src})\n".encode())):
        path = os.path.join(root, "site", *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)


def baked(root: str, name: str) -> dict:
    with open(os.path.join(root, "site", "data", name), encoding="utf-8") as fh:
        return json.load(fh)


#: The keys under which a baked file names a file of the site.
LINK_KEYS = ("src", "href", "data_url", "field_src", "data_src")


def links(doc) -> list[str]:
    """Every site path ``doc`` links (`LINK_KEYS`), but a prose figure that
    says it is missing: never an address with a scheme, an anchor or a root."""
    found: list[str] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            said_missing = node.get("type") == "figure" and node.get("missing") is True
            for key, value in node.items():
                if key in LINK_KEYS and isinstance(value, str) and value and not said_missing:
                    if not (value.startswith(("#", "/")) or "://" in value
                            or value.startswith(("mailto:", "data:"))):
                        found.append(value)
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    return found


def dangling(root: str) -> list[str]:
    """Every link of ``state.json``, ``map.json`` and ``page.json`` whose file
    the build left absent."""
    out = []
    for name in ("state.json", "map.json", "page.json"):
        for rel in links(baked(root, name)):
            if not os.path.isfile(os.path.join(root, "site", *rel.split("/"))):
                out.append(f"{name}: {rel}")
    return out


def view_row(root: str, view_id: str) -> dict | None:
    return next((row for row in baked(root, "state.json")["views"]
                 if row.get("id") == view_id), None)


def intro_numbers(root: str) -> list[tuple]:
    """``(text, match)`` of each number run in ``page.json``'s intro."""
    out: list[tuple] = []

    def walk(node) -> None:
        if isinstance(node, dict):
            if "num" in node:
                out.append((node["t"], node["match"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(baked(root, "page.json")["intro"])
    return out


# --------------------------------------------------------------------------- #
class NothingTheBuildDeletesIsLinked(_env.EnvCase):
    """(Invariant 14) Every file the page links is on disk after the build that
    linked it: a view's picture and payload, an evidence copy, a prose figure.
    What slipped through: an unbound viewgen whose tool was missing left the
    keep set, so the cleaner deleted the picture it had drawn before; and a
    prose figure under `assets/` read present and the same build deleted it."""

    def test_every_href_the_page_bakes_exists_after_the_build(self):
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        tool = plant_still(self, root)
        check_at(self, root, 1.0)
        run(self, root, "site", "init")
        plant_prose_figure(root, "content/img/demo.png")
        # Two builds: drawn, then with the tool gone (the crash and the row
        # itself are `AMissingRendererMovesNoStatus`'s, left for the gate).
        for label, env in (("drawn", tool), ("no tool", None)):
            with self.subTest(label):
                build(self, root, env=env)
                self.assertEqual(dangling(root), [])
                row = view_row(root, STILL)
                self.assertIsNotNone(row, "the still left the page")
                self.assertTrue(row["src"] and row["data_url"], row)
        page = baked(root, "page.json")
        self.assertIn("content/img/demo.png", links(page))
        self.assertTrue(any(rel.startswith("assets/evidence/") for rel in links(page)))

    def test_a_prose_figure_under_assets_reads_missing(self):
        """A figure the agent put under `site/assets/`, where the cleaner deletes
        what no view links: it reads missing on the first build as on every
        later one, and the build says where figures go. Red before issue #15's
        P1.2: it read present, the same build deleted it, and the next build
        baked another page."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        run(self, root, "site", "init")
        plant_prose_figure(root, "assets/demo.png")
        summary = build(self, root)
        figures = [block for block in baked(root, "page.json")["intro"]["blocks"]
                   if block.get("type") == "figure"]
        self.assertEqual([(f["src"], f["missing"]) for f in figures],
                         [("assets/demo.png", True)])
        self.assertTrue(any("site/content/img/" in w for w in summary["warnings"]),
                        summary["warnings"])
        first = page_bytes(root)
        build(self, root)
        self.assertEqual(page_bytes(root), first, "the second build baked another page")
        self.assertEqual(dangling(root), [])


# --------------------------------------------------------------------------- #
class AMissingRendererMovesNoStatus(_env.EnvCase):
    """(Invariant 14) A renderer that is missing or crashes changes no status
    and deletes no picture the page showed: the view keeps the row and the file
    its last build had, and the build says so."""

    def test_statuses_equal_with_absent_crashing_hanging_oversize_renderer(self):
        """A still drawn, then its scene edited (so no memo) and built with the
        tool absent, crashing, hanging past its timeout and writing 2.1 MiB:
        every build exits 0, and the verdict rows, the claims, the resolution
        digest, `page.json` and `map.json` are the same five times; the still
        drawn first stays linked, and the stand-in ran in each leg it was
        on PATH for."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        first = resolution_view(root)
        state = baked(root, "state.json")
        legs = (("absent", None), ("crash", "crash"), ("hang", "hang"),
                ("oversize", "oversize"))
        for i, (label, mode) in enumerate(legs):
            with self.subTest(label):
                edit_scene(root, f"scene {i + 2}")
                draw_settings(root, **({"mode": mode, "timeout_s": 1} if mode else {}))
                calls = len(draw.calls())
                summary = build_in(self, root, draw.env if mode else no_tool_env())
                self.assertEqual(len(draw.calls()), calls + (1 if mode else 0))
                self.assertEqual(resolution_view(root), first)
                self.assertEqual(baked(root, "state.json"), state)
                self.assertEqual(dangling(root), [])
                self.assertTrue(any(PIC in w and "older scene" in w
                                    for w in summary["warnings"]), summary["warnings"])

    def test_a_committed_render_survives_a_build_without_the_tool(self):
        """Drawn, then built without the tool: at the same recipe (the memo),
        after a scene edit (kept, and said), and as a fresh clone (no
        `.nopekit/out`, no `.nopekit/cache`): the still and its row stay, and
        the page is the same bytes."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        files, state, page = figure_files(root), baked(root, "state.json"), page_bytes(root)
        for label in ("memo", "scene", "clone"):
            with self.subTest(label):
                if label == "scene":
                    edit_scene(root, "scene 2")
                if label == "clone":
                    for scratch in ("out", "cache"):
                        shutil.rmtree(os.path.join(root, ".nopekit", scratch))
                summary = build_in(self, root, no_tool_env())
                self.assertEqual(figure_files(root), files)
                self.assertEqual(baked(root, "state.json"), state)
                self.assertEqual(page_bytes(root), page)
                self.assertEqual(any(PIC in w and "older scene" in w
                                     for w in summary["warnings"]), label != "memo",
                                 summary["warnings"])

    def test_an_unbound_viewgen_that_is_unavailable_keeps_its_asset(self):
        """Drawn, then built with its tool gone: the row, the picture and the
        split payload stay as they were, and the build says "kept from the last
        build". Red before issue #15's P1.2: the view left `state.json` and the
        cleaner deleted its picture."""
        self._keeps_its_asset((("no tool", None),))

    def test_an_unbound_viewgen_that_crashes_keeps_its_asset(self):
        """The same with the tool present and the viewgen raising, then once
        more with the tool gone: a crash keeps the row as a missing tool does."""
        self._keeps_its_asset((("crash", "crash"), ("no tool", None)))

    def test_a_kept_row_is_kept_only_at_the_bytes_the_build_wrote(self):
        """Prose names 4.37 mm, which no baked number holds; a 4.37 is then
        added by hand to the still's view file. `site status` reads the file
        as edited by hand, and a build without the still's tool does not keep
        the row: the number stays marked, and the page reads current. Red
        before the review of P1: the build read the edited payload back,
        baked it, matched the number with it and resealed the page."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        tool = plant_still(self, root)
        check_at(self, root, 1.0)
        run(self, root, "site", "init")
        intro = os.path.join(root, "site", "content", "intro.md")
        with open(intro, "w", encoding="utf-8") as fh:
            fh.write("The plate is 4.37 mm thick.\n")
        build_in(self, root, tool)
        self.assertEqual(intro_numbers(root), [("4.37 mm", False)])
        row = view_row(root, STILL)
        payload = os.path.join(root, "site", *row["data_url"].split("/"))
        with open(payload, encoding="utf-8") as fh:
            doc = json.load(fh)
        doc["thickness"] = 4.37
        with open(payload, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        info = site_status(self, root)
        self.assertTrue(info["edited"] and STILL in info["edited"][0]
                        and "edited by hand" in info["edited"][0], info)
        summary = build_in(self, root, {})
        self.assertIsNone(view_row(root, STILL))
        self.assertTrue(any(STILL in w and "is not what the last build wrote" in w
                            for w in summary["warnings"]), summary["warnings"])
        self.assertEqual(intro_numbers(root), [("4.37 mm", False)])
        self.assertEqual(site_status(self, root)["edited"], [])
        self.assertEqual(dangling(root), [])

    def _keeps_its_asset(self, legs) -> None:
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        tool = plant_still(self, root)
        check_at(self, root, 1.0)
        build(self, root, env=tool)
        row = view_row(root, STILL)
        self.assertIsNotNone(row)
        files = {}
        for rel in (row["src"], row["data_url"]):
            with open(os.path.join(root, "site", *rel.split("/")), "rb") as fh:
                files[rel] = fh.read()
        state = baked(root, "state.json")
        for label, mode in legs:
            with self.subTest(label):
                if mode:
                    still_mode(root, mode)
                summary = build(self, root, env=tool if mode else None)
                self.assertEqual(view_row(root, STILL), row)
                for rel, data in files.items():
                    path = os.path.join(root, "site", *rel.split("/"))
                    self.assertTrue(os.path.isfile(path), f"{rel} was deleted")
                    with open(path, "rb") as fh:
                        self.assertEqual(fh.read(), data)
                self.assertFalse([p for p in summary["removed"] if STILL in p
                                  or "demo_still" in p], summary["removed"])
                self.assertTrue(any(STILL in w and "kept from the last build" in w
                                    for w in summary["warnings"]), summary["warnings"])
                self.assertEqual(baked(root, "state.json"), state)


# --------------------------------------------------------------------------- #
# Bound viewgens: a figure drawn from one verdict entry (issue #15, P1.3)
# --------------------------------------------------------------------------- #
PIC, CHART = "demo.pic", "demo.chart"
DRAW_TOOL = "nopekit-test-draw"
STANDIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_draw_standin.py")


class Draw:
    """The stand-in renderer (`tests/_draw_standin.py`) installed as
    ``nopekit-test-draw`` in a temporary folder: ``env`` puts it on PATH and
    names its call log; ``calls()`` reads the log."""

    def __init__(self, case: _env.EnvCase) -> None:
        tools = case.tmp()
        self.log = os.path.join(tools, "draw.log")
        tool = os.path.join(tools, DRAW_TOOL)
        with open(tool, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(f'#!/bin/sh\nexec "{sys.executable}" "{STANDIN}" "$@"\n')
        os.chmod(tool, 0o755)
        self.env = {"PATH": tools + os.pathsep + os.environ.get("PATH", ""),
                    "NOPEKIT_TEST_DRAW_LOG": self.log}

    def calls(self) -> list[dict]:
        try:
            with open(self.log, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except OSError:
            return []


def draw_settings(root: str, **cfg) -> None:
    """``views/draw.cfg``: what the figure project's bound viewgens do."""
    with open(os.path.join(root, "views", "draw.cfg"), "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)


def edit_scene(root: str, text: str) -> None:
    """A new recipe for the still (``views/_demo_scene.txt``): no memo."""
    with open(os.path.join(root, "views", "_demo_scene.txt"), "w", encoding="utf-8") as fh:
        fh.write(text + "\n")


def build_in(case: _env.EnvCase, root: str, env: dict | None = None) -> dict:
    """``site build --json`` in this process (each cold process costs ~1 s on
    the fast tier), with ``env``'s variables set and nothing else of this
    machine's PATH changed; the summary."""
    from test_site_truth import _fresh_registry, _main
    _fresh_registry(case)
    if not os.path.isdir(os.path.join(root, "site")):
        run(case, root, "site", "init")
    with mock.patch.dict(os.environ, dict(env or {})):
        if env is None:
            os.environ.pop("NOPEKIT_TEST_DRAW_LOG", None)
        code, said = _main("site", "build", "-C", root, "--json")
    case.assertEqual(code, 0, said[-3000:])
    return json.loads(said[said.index("{"):])


def no_tool_env() -> dict:
    """PATH without any folder that holds the stand-in."""
    keep = [p for p in os.environ.get("PATH", "").split(os.pathsep)
            if p and not os.path.exists(os.path.join(p, DRAW_TOOL))]
    return {"PATH": os.pathsep.join(keep)}


def figure_files(root: str) -> dict[str, bytes]:
    """Every file under ``site/assets/figures`` and ``assets/live``, by site path."""
    out = {}
    for top in ("figures", "live"):
        base = os.path.join(root, "site", "assets", top)
        for directory, _dirs, names in os.walk(base):
            for name in names:
                path = os.path.join(directory, name)
                with open(path, "rb") as fh:
                    out[os.path.relpath(path, os.path.join(root, "site"))
                        .replace(os.sep, "/")] = fh.read()
    return out


def binding(root: str, view_id: str) -> dict | None:
    row = view_row(root, view_id)
    return None if row is None else row.get("binding")


def sidecar_of(root: str, entry: str, view_id: str) -> dict:
    path = os.path.join(root, "site", "assets", "figures", GATE, entry, view_id + ".view.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


class AFigureIsItsEntrysEvidence(_env.EnvCase):
    """(Invariant 14) A bound figure is drawn only from its entry's verified
    evidence, published only under that entry's folder, and shown only while
    each file is the bytes its sidecar names, under an entry the cache holds.
    What slipped through before this: a picture was whatever a viewgen wrote,
    under one name per view, so nothing said which result it was of."""

    def test_a_render_from_another_runs_inputs_is_never_drawn(self):
        """Check A, check B, draw (B's picture), then A from the cache with B's
        files in `.nopekit/out`: the tool is never called for A, nothing is
        published under A, and the page shows B's picture as an older one."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        b = check_at(self, root, 2.0)
        build_in(self, root, draw.env)
        self.assertEqual([c["entry"] for c in draw.calls()], [b])
        self.assertEqual(check_at(self, root, 1.0), a)
        summary = build_in(self, root, draw.env)
        self.assertEqual([c["entry"] for c in draw.calls()], [b], "the tool drew A from B's files")
        self.assertFalse([p for p in figure_files(root) if f"/{a}/" in p],
                         "a figure was published under A")
        for view_id in (PIC, CHART):
            with self.subTest(view_id):
                self.assertEqual({k: binding(root, view_id)[k] for k in ("entry", "currency")},
                                 {"entry": b, "currency": "older"})
        self.assertTrue(any(PIC in w and "from another run" in w for w in summary["warnings"]),
                        summary["warnings"])
        self.assertEqual(dangling(root), [])

    def test_a_forced_run_draws_its_own_entry_again(self):
        """After the A, B, A sequence, `check --force` solves A again: A is
        drawn from its own files and read current, and B's folder goes."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        b = check_at(self, root, 2.0)
        build_in(self, root, draw.env)
        check_at(self, root, 1.0)
        run(self, root, "check", "--force", "--only", GATE)
        build_in(self, root, draw.env)
        self.assertEqual([c["entry"] for c in draw.calls()], [b, a])
        self.assertEqual(binding(root, PIC)["currency"], "current")
        self.assertEqual(binding(root, PIC)["entry"], a)
        self.assertFalse([p for p in figure_files(root) if f"/{b}/" in p])

    def test_inputs_that_move_during_the_render_are_discarded(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        draw_settings(root, mode="move-inputs")
        summary = build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1, "the stand-in did not run")
        self.assertIsNone(view_row(root, PIC))
        self.assertFalse([p for p in figure_files(root) if PIC in p])
        self.assertTrue(any(PIC in w and "the inputs moved while the picture was drawn" in w
                            for w in summary["warnings"]), summary["warnings"])
        self.assertEqual(binding(root, CHART)["currency"], "current")

    def test_every_figure_path_names_its_entry(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        draw_settings(root, glb="live")
        build_in(self, root, draw.env)
        found = figure_files(root)
        self.assertEqual({p.split("/")[1] for p in found}, {"figures", "live"})
        for rel in found:
            with self.subTest(rel):
                _assets, _top, gate, entry, name = rel.split("/")
                self.assertEqual((gate, entry), (GATE, a))
                self.assertIn(entry, entries(root))
                self.assertTrue(name.startswith((PIC + ".", CHART + ".")), name)
        for view_id in (PIC, CHART):
            row = view_row(root, view_id)
            for key in ("src", "data_url"):
                if row.get(key):
                    self.assertTrue(row[key].startswith(f"assets/figures/{GATE}/{a}/"), row)
            side = sidecar_of(root, a, view_id)
            self.assertEqual((side["gate"], side["entry"], side["view"]), (GATE, a, view_id))

    def test_a_render_naming_an_entry_the_cache_lacks_is_never_shown(self):
        """A folder copied under an entry the cache does not hold, its sidecars
        rewritten to name it: never shown, never linked, and named."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        fake = "f" * 16 + "-" + "e" * 8
        base = os.path.join(root, "site", "assets", "figures", GATE)
        shutil.copytree(os.path.join(base, a), os.path.join(base, fake))
        for view_id in (PIC, CHART):
            path = os.path.join(base, fake, view_id + ".view.json")
            with open(path, encoding="utf-8") as fh:
                doc = json.load(fh)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({**doc, "entry": fake}, fh)
        check_at(self, root, 2.0)
        summary = build_in(self, root, no_tool_env())
        self.assertEqual((binding(root, PIC)["entry"], binding(root, PIC)["currency"]),
                         (a, "older"))
        self.assertTrue(any(fake in w and "holds no entry" in w for w in summary["warnings"]),
                        summary["warnings"])
        shutil.rmtree(os.path.join(base, a))
        build_in(self, root, no_tool_env())
        self.assertIsNone(view_row(root, PIC))
        self.assertFalse([rel for name in ("state.json", "map.json", "page.json")
                          for rel in links(baked(root, name)) if fake in rel])
        self.assertEqual(dangling(root), [])

    def test_a_swapped_file_is_never_shown(self):
        """The still replaced under its own name: `site status` reads the page
        as edited by hand (P1.4), the next build does not show it (its bytes
        are not the sidecar's), and it is drawn again where the tool is."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        src = view_row(root, PIC)["src"]
        with open(os.path.join(root, "site", *src.split("/")), "wb") as fh:
            fh.write(b"\x89PNG\r\n\x1a\n another picture")
        edited = site_status(self, root)["edited"]
        self.assertTrue(edited and "edited by hand" in edited[0]
                        and f"figure {PIC} reads current" in edited[0], edited)
        summary = build_in(self, root, no_tool_env())
        self.assertIsNone(view_row(root, PIC))
        self.assertTrue(any("not the bytes the sidecar names" in w for w in summary["warnings"]),
                        summary["warnings"])
        build_in(self, root, draw.env)
        self.assertEqual((binding(root, PIC)["entry"], binding(root, PIC)["currency"]),
                         (a, "current"))
        self.assertEqual(len(draw.calls()), 2)

    def test_a_file_over_two_mib_is_never_written_or_linked(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        draw_settings(root, mode="oversize")
        summary = build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1, "the stand-in did not run")
        self.assertIsNone(view_row(root, PIC))
        self.assertTrue(any(PIC in w and "2 MiB" in w for w in summary["warnings"]),
                        summary["warnings"])
        for directory, _dirs, names in os.walk(root):
            for name in names:
                path = os.path.join(directory, name)
                if ".git" not in path.split(os.sep):
                    self.assertLessEqual(os.path.getsize(path), 2 * 1024 * 1024, path)
        # A file over the cap placed by hand, its sidecar resealed to match.
        draw_settings(root)
        build_in(self, root, draw.env)
        side = sidecar_of(root, a, PIC)
        big = b"\x89PNG\r\n\x1a\n" + b"\0" * (2 * 1024 * 1024 + 1)
        with open(os.path.join(root, "site", "assets", "figures", GATE, a,
                               side["files"]["image"]["name"]), "wb") as fh:
            fh.write(big)
        side["files"]["image"].update(sha256=hashlib.sha256(big).hexdigest(), bytes=len(big))
        with open(os.path.join(root, "site", "assets", "figures", GATE, a, PIC + ".view.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(side, fh)
        summary = build_in(self, root, no_tool_env())
        self.assertIsNone(view_row(root, PIC))
        self.assertTrue(any("over the" in w and PIC in w for w in summary["warnings"]),
                        summary["warnings"])

    def test_a_digest_no_evidence_file_holds_is_never_bound(self):
        """The field edited after the run, and the still binding it at the
        digest of the file on disk (a viewgen that hashes whatever is there):
        `bind` takes only a digest a verified evidence file of the result
        holds, so nothing is drawn or published. Red with that rule removed:
        the edited field was drawn and shown as the result's current picture."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        with open(os.path.join(root, ".nopekit", "out", "demo", "field.txt"), "ab") as fh:
            fh.write(b"edited by hand\n")
        draw_settings(root, bind="disk")
        summary = build_in(self, root, draw.env)
        self.assertTrue(any(PIC in w and "no evidence file of this result holds its digest"
                            in w for w in summary["warnings"]), summary["warnings"])
        self.assertEqual(draw.calls(), [])
        self.assertEqual(page_figure(root, PIC)["currency"], "none")
        self.assertFalse([p for p in figure_files(root) if f"/{PIC}." in p])

    def test_a_gate_id_the_site_spells_otherwise_shows_its_figure(self):
        """A gate id with a character the site's folder names replace
        (``demo+drop``, under ``assets/figures/demo_drop/``) is read in the
        verdict cache under the raw id, where the spine writes it: its figures
        read current, and a second build is the memo. Red before the review of
        P1: the cache "held no entry", the figures read none, and every build
        drew them again and deleted them."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        for rel in ("gates/demo.py", "views/demo_pic.py", "views/demo_chart.py"):
            path = os.path.join(root, *rel.split("/"))
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text.replace('"demo.drop"', '"demo+drop"'))
        run(self, root, "check")
        build_in(self, root, draw.env)
        for view_id in (PIC, CHART):
            with self.subTest(view_id):
                fig = page_figure(root, view_id)
                self.assertEqual((fig["gate"], fig["currency"]), ("demo+drop", "current"))
                self.assertTrue(fig["src"] or fig["data_src"])
        files = figure_files(root)
        self.assertTrue(files and all(p.startswith("assets/figures/demo_drop/") for p in files),
                        sorted(files))
        build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1, "the still was drawn again")
        self.assertEqual(figure_files(root), files)


# --------------------------------------------------------------------------- #
def resolution_view(root: str) -> tuple:
    """What a renderer may never move: the verdict rows, the claims and the
    resolution digest of ``state.json``, and ``map.json`` and ``page.json``
    whole."""
    state = baked(root, "state.json")
    return (state["verdicts"], state["claims"], state["meta"]["resolution_digest"],
            page_bytes(root), baked(root, "map.json"))


class ANoOpRebuildDrawsNothing(_env.EnvCase):
    """A build over a figure already drawn calls no renderer and writes no byte,
    and the watcher wakes on a run that solves the served entry again."""

    def test_a_second_build_writes_nothing_and_calls_nothing(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1)
        before = _snapshot_site(root)
        summary = build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1, "the memo called the tool again")
        self.assertEqual(summary["wrote"], [])
        self.assertEqual(_snapshot_site(root), before)
        self.assertEqual({n["view"]: n["status"] for n in summary["viewgens"]
                          if n["view"] in (PIC, CHART)}, {PIC: "memo", CHART: "memo"})

    def test_the_watcher_wakes_on_a_run_that_solves_the_entry_again(self):
        from nopekit import site
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"), figures=False)
        a = check_at(self, root, 1.0)
        before = site.watch_snapshot(root)
        rel = f".nopekit/cache/evidence/{GATE}/{a}.json"
        self.assertIn(rel, before)
        run(self, root, "check", "--force", "--only", GATE)
        self.assertNotEqual(site.watch_snapshot(root).get(rel), before[rel])


def _snapshot_site(root: str) -> dict:
    """Every file under ``site/`` but the ignored clock file: bytes and mtime."""
    found = {}
    base = os.path.join(root, "site")
    for directory, _dirs, names in os.walk(base):
        for name in names:
            path = os.path.join(directory, name)
            rel = os.path.relpath(path, base).replace(os.sep, "/")
            if rel == "data/build.json":
                continue
            with open(path, "rb") as fh:
                found[rel] = (fh.read(), os.stat(path).st_mtime_ns)
    return found


class OnePictureSetPerGate(_env.EnvCase):
    """One picture set per (view, served entry): an older folder is kept only
    while the served entry has none, and a GLB is committed only for an entry
    an export re-ran; otherwise it is live, ignored and named in build.json."""

    def test_an_older_folder_is_removed_once_the_served_one_is_drawn(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        b = check_at(self, root, 2.0)
        build_in(self, root, no_tool_env())
        self.assertEqual((binding(root, PIC)["entry"], binding(root, PIC)["currency"]),
                         (a, "older"))
        self.assertEqual((binding(root, CHART)["entry"], binding(root, CHART)["currency"]),
                         (b, "current"))
        self.assertTrue([p for p in figure_files(root) if f"/{a}/{PIC}." in p])
        self.assertFalse([p for p in figure_files(root) if f"/{a}/{CHART}." in p],
                         "the chart's older folder outlived the served one's picture")
        build_in(self, root, draw.env)
        self.assertEqual(binding(root, PIC)["entry"], b)
        self.assertEqual({p.split("/")[3] for p in figure_files(root)}, {b})

    def test_a_glb_is_committed_only_for_an_export_entry(self):
        from nopekit import store
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        draw_settings(root, glb="asset")
        build_in(self, root, draw.env)
        live = [p for p in figure_files(root) if p.startswith("assets/live/")]
        self.assertEqual(len(live), 1, figure_files(root))
        self.assertTrue(live[0].startswith(f"assets/live/{GATE}/{a}/{PIC}.")
                        and live[0].endswith(".glb"))
        self.assertFalse([p for p in figure_files(root)
                          if p.startswith("assets/figures/") and p.endswith(".glb")])
        self.assertEqual(_env.git(["check-ignore", "-q", "site/" + live[0]], cwd=root)
                         .returncode, 0, "the live GLB is not ignored")
        with open(os.path.join(root, "site", "data", "build.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["live_figures"], {f"{GATE}/{a}/{PIC}": live[0]})
        self.assertNotIn("field_src", view_row(root, PIC))
        self.assertNotIn(live[0], json.dumps([baked(root, n) for n in
                                              ("state.json", "map.json", "page.json")]))
        # An export re-ran A: the next build commits the GLB it drew, and
        # draws nothing.
        rho16, out8 = a.split("-")
        store.append_sealed(root, "exports", "m", "exports",
                            {"milestone": "m", "reran": [{"gate": GATE, "rho": rho16,
                                                          "out8": out8}]})
        build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1)
        committed = [p for p in figure_files(root)
                     if p.startswith(f"assets/figures/{GATE}/{a}/") and p.endswith(".glb")]
        self.assertEqual(len(committed), 1)
        self.assertEqual(view_row(root, PIC)["field_src"], committed[0])
        self.assertFalse([p for p in figure_files(root) if p.startswith("assets/live/")])
        self.assertFalse(sidecar_of(root, a, PIC)["files"]["field"]["live"])

    def test_a_gltf_with_its_bytes_inside_is_published_as_a_glb_is(self):
        """(P2.4) ParaView writes glTF, not GLB: a glTF whose buffers are
        ``data:`` URIs takes the GLB's path, live, then committed by an
        export, under its own suffix and bytes."""
        from nopekit import store
        import _draw_standin
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        draw_settings(root, glb="asset", solid="gltf")
        build_in(self, root, draw.env)
        live = [p for p in figure_files(root) if p.startswith("assets/live/")]
        self.assertEqual(len(live), 1, figure_files(root))
        self.assertTrue(live[0].endswith(".gltf"), live)
        self.assertEqual(figure_files(root)[live[0]], _draw_standin.GLTF)
        with open(os.path.join(root, "site", "data", "build.json"), encoding="utf-8") as fh:
            self.assertEqual(json.load(fh)["live_figures"], {f"{GATE}/{a}/{PIC}": live[0]})
        rho16, out8 = a.split("-")
        store.append_sealed(root, "exports", "m", "exports",
                            {"milestone": "m", "reran": [{"gate": GATE, "rho": rho16,
                                                          "out8": out8}]})
        build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1)
        committed = [p for p in figure_files(root)
                     if p.startswith(f"assets/figures/{GATE}/{a}/") and p.endswith(".gltf")]
        self.assertEqual(len(committed), 1, figure_files(root))
        self.assertEqual(figure_files(root)[committed[0]], _draw_standin.GLTF)
        self.assertEqual(view_row(root, PIC)["field_src"], committed[0])

    def test_a_gltf_that_names_a_file_outside_it_is_refused(self):
        """A glTF whose buffers are files beside it would make the page fetch
        bytes nothing published or hashed: the figure is refused whole."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        draw_settings(root, glb="asset", solid="gltf", mode="gltf-outside")
        summary = build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1)
        self.assertTrue(any("names a file outside it ('gltf_buffer_0.bin')" in w
                            for w in summary["warnings"]), summary["warnings"])
        self.assertEqual([p for p in figure_files(root) if f"/{PIC}." in p], [])
        self.assertEqual(binding(root, PIC), None)


# --------------------------------------------------------------------------- #
# The page's figures: which result, beside which status (issue #15, P1.4)
# --------------------------------------------------------------------------- #
CLAIM = "D1"


def page_figure(root: str, view_id: str, cid: str = CLAIM) -> dict | None:
    """``page.json``'s figure of ``view_id`` under claim ``cid``, or None."""
    return next((fig for fig in baked(root, "page.json")["claims"][cid].get("figures") or ()
                 if fig["view"] == view_id), None)


def claim_chip(root: str, cid: str = CLAIM) -> dict:
    """The claim's own chip on the page, as a figure carries it."""
    row = baked(root, "page.json")["claims"][cid]
    return {"id": cid, "token": row["token"], "word": row["word"], "errored": row["errored"],
            "marks": row["marks"]}


def plant_page(root: str, edit) -> None:
    """``page.json`` edited by ``edit(doc)`` and resealed: a forgery the seal
    alone does not catch."""
    from nopekit import page
    path = os.path.join(root, "site", "data", "page.json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    edit(doc)
    doc["self"] = page.seal(doc)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh)


def site_status(case: _env.EnvCase, root: str) -> dict:
    """`nopekit site status --json`, in this process."""
    from test_site_truth import _fresh_registry, _main
    _fresh_registry(case)
    code, said = _main("site", "status", "-C", root, "--json")
    case.assertEqual(code, 0, said[-3000:])
    return json.loads(said[said.index("{"):])


def set_limit(root: str, limit: float) -> None:
    """Claim D1's limit, rewritten in its record."""
    path = os.path.join(root, "claims", CLAIM + ".json")
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["acceptance"]["limit"] = limit
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2)


def refused_build(case: _env.EnvCase, root: str, env: dict | None = None) -> str:
    """``site build`` in this process, which must refuse the page whole."""
    from test_site_truth import _fresh_registry, _main
    _fresh_registry(case)
    with mock.patch.dict(os.environ, dict(env or {})):
        code, said = _main("site", "build", "-C", root, "--json")
    case.assertEqual(code, 2, said[-3000:])
    case.assertIn("the page would say more than the resolution", said)
    return said


class AFigureSaysWhichResultItIs(_env.EnvCase):
    """(Invariant 14) A figure on the page says which result it is: current
    only beside the fresh served entry, stale beside a served entry that is
    not current, older (with that other result's own outcome and value) when
    it is of another entry, and none when no single picture can be chosen. The
    build refuses, and `site status`, `status` and `doctor` read as edited by
    hand, a page that says another. What slipped through before this: a
    picture beside a status said nothing of the result it showed, so a still
    of an earlier design read as the current one's."""

    def test_a_new_entry_with_no_renderer_reads_older(self):
        """Drawn at A, then B checked with no renderer: the still reads older,
        of A, with A's own outcome and value and A's picture linked, beside the
        chips of B's composition; the chart, which needs no tool, reads current
        of B; and `site status` reads the page as current."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        b = check_at(self, root, 2.0)
        build_in(self, root, no_tool_env())
        pic, chart = page_figure(root, PIC), page_figure(root, CHART)
        self.assertEqual((pic["entry"], pic["currency"]), (a, "older"))
        self.assertEqual(pic["currency_word"], "This picture is from another result. The "
                         "result on this page has no picture yet.")
        self.assertEqual(pic["drawn_text"], "That other result: pass, 2 Pa.")
        self.assertEqual(pic["outcome"], "pass")
        self.assertTrue(pic["src"].startswith(f"assets/figures/{GATE}/{a}/"), pic["src"])
        self.assertTrue(os.path.isfile(os.path.join(root, "site", *pic["src"].split("/"))))
        self.assertEqual((chart["entry"], chart["currency"], chart["drawn_text"]),
                         (b, "current", ""))
        for fig in (pic, chart):
            self.assertEqual(fig["claims"], [claim_chip(root)])
        text = baked(root, "page.json")["claims"][CLAIM]["binding_text"]
        self.assertIn(f"its result {b}. This page shows that result.", text)
        self.assertIn(f"its result {a}. This page shows another result of {GATE}.", text)
        self.assertEqual(site_status(self, root)["edited"], [])

    def test_a_design_edit_reads_stale(self):
        """The design moved and nothing checked it again: the served entry is
        not current, and its figures say so, beside the evaluator's outcome."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        _projects.set_figure_x(root, 3.0)
        build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 1, "a stale entry was drawn again")
        page_doc = baked(root, "page.json")
        [row] = [e for e in page_doc["claims"][CLAIM]["evaluators"] if e["id"] == GATE]
        for view_id in (PIC, CHART):
            with self.subTest(view_id):
                fig = page_figure(root, view_id)
                self.assertEqual((fig["entry"], fig["currency"]), (a, "stale"))
                self.assertEqual(fig["currency_word"], "This picture is from the result on "
                                 "this page. That result is not current.")
                self.assertEqual((fig["outcome"], fig["outcome_word"]),
                                 (row["outcome"], row["outcome_word"]))

    def test_a_planted_currency_is_refused(self):
        """A bake that says current for an older picture is refused whole, and
        nothing under site/data/ moves; the same lie written into page.json and
        resealed reads edited by hand in `site status`, `status` and `doctor`."""
        from nopekit import page
        from test_site_truth import _fresh_registry, _main, _snapshot
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        check_at(self, root, 2.0)
        build_in(self, root, no_tool_env())
        self.assertEqual(page_figure(root, PIC)["currency"], "older")
        data = os.path.join(root, "site", "data")
        before = {k: v for k, v in _snapshot(data).items() if not k.endswith("build.json")}
        real = page.figure_row

        def lying(*a, **kw):
            fig = real(*a, **kw)
            if fig["currency"] == "older":
                fig.update(currency="current", currency_word=page.figure_currency_word(
                    "current"), drawn_text="")
            return fig

        with mock.patch.object(page, "figure_row", lying):
            said = refused_build(self, root, no_tool_env())
        self.assertIn(f"figure {PIC} reads current", said)
        self.assertEqual({k: v for k, v in _snapshot(data).items()
                          if not k.endswith("build.json")}, before)

        def forged(doc):
            for fig in [*doc["claims"][CLAIM]["figures"], doc["representation"]["figure"]]:
                if fig and fig["view"] == PIC:
                    fig.update(currency="current",
                               currency_word=page.figure_currency_word("current"))

        plant_page(root, forged)
        info = site_status(self, root)
        self.assertTrue(info["edited"] and "edited by hand" in info["edited"][0], info)
        self.assertIn(f"figure {PIC} reads current", info["edited"][0])
        _fresh_registry(self)
        code, said = _main("doctor", "-C", root, "--json")
        [row] = [r for r in json.loads(said[said.index("{"):])["checks"]
                 if r["check"] == "site"]
        self.assertEqual(row["status"], "FAIL", row)
        _fresh_registry(self)
        _code, said = _main("status", "-C", root)
        self.assertIn("edited by hand", [t for t in said.splitlines()
                                         if t.startswith("site:")][0])

    def test_site_status_reads_behind_after_a_check_that_moved_only_the_entry(self):
        """A check at another design moves no record, only the entry the
        resolution serves: the page is behind, never current."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        self.assertEqual(site_status(self, root)["stale"], False)
        check_at(self, root, 2.0)
        info = site_status(self, root)
        self.assertTrue(info["stale"], info)
        self.assertIn("what the page shows has changed since the site was built",
                      info["stale_reason"])

    def test_two_older_renders_after_a_merge_show_none(self):
        """Two earlier folders of the still and none of the served result (two
        branches merged): which is newer is a clock's question, so neither is
        shown; the page says no picture, and the build names both."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        base = os.path.join(root, "site", "assets", "figures", GATE)
        aside = os.path.join(self.tmp(), "a")
        shutil.copytree(os.path.join(base, a), aside)
        b = check_at(self, root, 2.0)
        build_in(self, root, draw.env)
        shutil.copytree(aside, os.path.join(base, a))
        check_at(self, root, 3.0)
        summary = build_in(self, root, no_tool_env())
        fig = page_figure(root, PIC)
        self.assertEqual((fig["currency"], fig["entry"], fig["src"]), ("none", "", ""))
        self.assertEqual(fig["currency_word"], "No picture of this result is on the page.")
        self.assertIsNone(view_row(root, PIC))
        self.assertTrue(any(a in w and b in w and "none is shown" in w
                            for w in summary["warnings"]), summary["warnings"])
        self.assertNotIn(PIC, baked(root, "page.json")["representation"]["view"] or "")
        self.assertEqual(dangling(root), [])

    def test_the_technical_page_says_the_same_word(self):
        """`state.json`'s binding of each bound view is the page's figure: its
        gate, entry, currency and sentence."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        check_at(self, root, 2.0)
        build_in(self, root, no_tool_env())
        for view_id in (PIC, CHART):
            with self.subTest(view_id):
                fig = page_figure(root, view_id)
                self.assertEqual(binding(root, view_id),
                                 {k: fig[k] for k in ("gate", "entry", "currency",
                                                      "currency_word")})

    def test_each_planted_sentence_outcome_and_digest_is_refused(self):
        """An older figure's sentences, outcome and digest, each planted alone
        (the currency left honest) and resealed: `site status` reads each as
        edited by hand, naming it; and a bake that says the other result failed
        is refused whole. What slipped through (review of P1): only a planted
        currency was tried, and the currency check caught it first, so deleting
        any of these five checks left every test green."""
        from nopekit import page
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        check_at(self, root, 2.0)
        build_in(self, root, no_tool_env())
        honest = page_figure(root, PIC)
        self.assertEqual((honest["currency"], honest["outcome"]), ("older", "pass"))
        path = os.path.join(root, "site", "data", "page.json")
        with open(path, "rb") as fh:
            built = fh.read()

        def on_pic(**fields):
            def edit(doc):
                for fig in [*doc["claims"][CLAIM]["figures"], doc["representation"]["figure"]]:
                    if fig and fig["view"] == PIC:
                        fig.update(fields)
            return edit

        def binding_text(doc):
            doc["claims"][CLAIM]["binding_text"] = doc["claims"][CLAIM]["binding_text"].replace(
                "another result of", "that result of")

        legs = (
            ("currency_word", on_pic(currency_word=page.figure_currency_word("current")),
             f"figure {PIC} says {page.figure_currency_word('current')!r}, its currency's "
             f"sentence is"),
            ("drawn_text", on_pic(drawn_text="That other result: fail, 2 Pa."),
             f"figure {PIC} says 'That other result: fail, 2 Pa.' of the result it was drawn "
             f"from"),
            ("outcome", on_pic(outcome="fail", outcome_word=page._outcome_word("fail")),
             f"figure {PIC} outcome reads fail, the result it shows is pass"),
            ("binding_text", binding_text, f"page claim {CLAIM} binding text reads"),
            ("sha256", on_pic(sha256="0" * 64),
             f"figure {PIC} names the sha256 {'0' * 64}, and its sidecar names"),
        )
        for label, edit, said in legs:
            with self.subTest(label):
                with open(path, "wb") as fh:
                    fh.write(built)
                plant_page(root, edit)
                info = site_status(self, root)
                self.assertTrue(info["edited"], info)
                self.assertIn("edited by hand", info["edited"][0])
                self.assertIn(said, info["edited"][0])
        with open(path, "wb") as fh:
            fh.write(built)
        self.assertEqual(site_status(self, root)["edited"], [])
        real = page.figure_row

        def lying(*args, **kw):
            fig = real(*args, **kw)
            if fig["currency"] == "older":
                fig.update(outcome="fail", outcome_word=page._outcome_word("fail"))
            return fig

        with mock.patch.object(page, "figure_row", lying):
            said = refused_build(self, root, no_tool_env())
        self.assertIn(f"figure {PIC} outcome reads fail, the result it shows is pass", said)
        self.assertEqual(page_figure(root, PIC)["entry"], a)

    def test_a_bound_solid_is_never_the_hero_as_a_plain_view(self):
        """A bound 3D view (``demo.solid``, its file live) beside the bound
        still: the hero is the still's figure, with its chips and its sentence,
        and the solid is no marketing alternate; a page resealed with the solid
        as a plain hero, or as an alternate, reads edited by hand. Red before
        the review of P1: the solid was the hero, with no figure, no chips, no
        currency and no file, and no check read it."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        with open(os.path.join(root, "views", "demo_solid.py"), "w", encoding="utf-8",
                  newline="\n") as fh:
            fh.write(_SOLID_VIEWGEN)
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        self.assertIsNotNone(binding(root, SOLID), "the solid drew no bound row")
        rep = baked(root, "page.json")["representation"]
        self.assertEqual((rep["view"], (rep["figure"] or {}).get("view")), (PIC, PIC))
        self.assertEqual(rep["figure"]["claims"], [claim_chip(root)])
        self.assertNotIn(SOLID, [alt["view"] for alt in rep["alternates"]])
        self.assertEqual(site_status(self, root)["edited"], [])
        path = os.path.join(root, "site", "data", "page.json")
        with open(path, "rb") as fh:
            built = fh.read()

        def plain_hero(doc):
            doc["representation"].update(view=SOLID, kind="model3d", title="The demo solid",
                                         figure=None, controls=None)

        def alternate(doc):
            doc["representation"]["alternates"].append(
                {"view": SOLID, "title": "The demo solid", "bytes": None})

        for label, edit, said in (
                ("hero", plain_hero,
                 f"representation {SOLID} is a bound view shown with no figure"),
                ("alternate", alternate,
                 f"representation alternate {SOLID} is a bound view")):
            with self.subTest(label):
                with open(path, "wb") as fh:
                    fh.write(built)
                plant_page(root, edit)
                info = site_status(self, root)
                self.assertTrue(info["edited"], info)
                self.assertIn(said, info["edited"][0])


SOLID = "demo.solid"

#: A BOUND 3D view of the figure project (``evidence_of="demo.drop"``): a stand-in
#: GLB from the run's summary, needing no tool. Its file is live (no export re-ran
#: the entry), so its row names no file.
_SOLID_VIEWGEN = '''\
from nopekit.models import View, ViewKind
from nopekit.site import viewgen


@viewgen(id="demo.solid", kind=ViewKind.MODEL3D, title="The demo solid",
         evidence_of="demo.drop")
def solid(ctx):
    """A stand-in solid of the demo, from the run's summary."""
    path = ctx.entry.path("summary.json")
    if path is None:
        return None
    with open(path, "rb") as fh:
        body = b"glTF" + b"\\x02\\x00\\x00\\x00" + fh.read()
    src = ctx.write_asset("solid.glb", body)
    return View(id="demo.solid", kind=ViewKind.MODEL3D, src=src,
                meta={"caption": "A solid of the demo."})
'''


class TheClaimsStatusSitsBesideEveryFigure(_env.EnvCase):
    """(Invariant 14) Every figure carries the chips of exactly the claims its
    gate covers, each the resolution's token, word and marks; a chart's limit
    and point are the floor's, never the pack's; a caption says no status. A
    page that says otherwise is refused by the build and read as edited by
    hand. What slipped through before this (F9): a chart took its margin from
    its own limit, so a pack's limit beside the claim's was a second limit on
    the page."""

    def test_every_figure_carries_its_claims_chips(self):
        """With a disagreement and an amber flip planted on D1, every figure
        and the representation's carry D1's chip with both marks, as the claim
        does, and the build's checker accepts the page."""
        from nopekit import derivation, graph
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        real = graph.tokens

        def disagreeing(*a, **kw):
            found = real(*a, **kw)
            return found._replace(disagree={**found.disagree, "claims": [CLAIM]})

        flips = {CLAIM: derivation.Amber("flips", (), (), (), "")}
        with mock.patch.object(graph, "tokens", disagreeing), \
                mock.patch.object(derivation, "amber_now", lambda *a, **kw: flips):
            build_in(self, root, draw.env)
        chip = claim_chip(root)
        self.assertEqual(chip["marks"], ["disagree", "amber"])
        figures = baked(root, "page.json")["claims"][CLAIM]["figures"]
        self.assertEqual(sorted(f["view"] for f in figures), [CHART, PIC])
        for fig in [*figures, baked(root, "page.json")["representation"]["figure"]]:
            with self.subTest(fig["id"]):
                self.assertEqual(fig["claims"], [chip])

    def test_a_planted_chip_is_refused(self):
        """A figure's chip, the representation's and its copy, each planted
        and resealed: each reads edited by hand."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        page_path = os.path.join(root, "site", "data", "page.json")
        with open(page_path, "rb") as fh:
            honest = fh.read()

        def figure_token(doc):
            doc["claims"][CLAIM]["figures"][0]["claims"][0].update(token="failing",
                                                                   word="failing")

        def hero_marks(doc):
            hero = doc["representation"]["figure"]
            hero["claims"][0]["marks"] = ["disagree"]
            for fig in doc["claims"][CLAIM]["figures"]:
                if fig["id"] == hero["id"]:
                    fig["claims"][0]["marks"] = ["disagree"]

        def hero_copy(doc):
            doc["representation"]["figure"]["caption"] = "Another picture."

        for label, edit, said in (("figure", figure_token, "chip D1 token reads failing"),
                                  ("hero", hero_marks, "chip D1 marks reads ['disagree']"),
                                  ("copy", hero_copy, "differs from the copy under D1")):
            with self.subTest(label):
                with open(page_path, "wb") as fh:
                    fh.write(honest)
                self.assertEqual(site_status(self, root)["edited"], [])
                plant_page(root, edit)
                edited = site_status(self, root)["edited"]
                self.assertTrue(edited and said in edited[0], edited)

    def test_a_missing_or_extra_claim_is_refused(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        build_in(self, root, draw.env)
        page_path = os.path.join(root, "site", "data", "page.json")
        with open(page_path, "rb") as fh:
            honest = fh.read()
        extra = {"id": "D2", "token": "checked", "word": "checked", "errored": False,
                 "marks": []}
        for label, claims in (("missing", []), ("extra", None)):
            with self.subTest(label):
                with open(page_path, "wb") as fh:
                    fh.write(honest)

                def edit(doc, claims=claims):
                    fig = doc["claims"][CLAIM]["figures"][0]
                    fig["claims"] = claims if claims is not None else [*fig["claims"], extra]

                plant_page(root, edit)
                edited = site_status(self, root)["edited"]
                self.assertTrue(edited and f"and {GATE} covers ['{CLAIM}']" in edited[0],
                                edited)

    def test_a_chart_limit_and_margin_are_the_floors(self):
        """The chart's limit and point are the floor row's for (D1, demo.drop):
        the claim's limit, which an edit moves while the evaluator's own limit
        stays 10 Pa, and the margin against it; a planted limit reads edited by
        hand."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        for limit, margin in ((10.0, "80% inside the limit"), (20.0, "90% inside the limit")):
            with self.subTest(limit=limit):
                set_limit(root, limit)
                build_in(self, root, draw.env)
                fig = page_figure(root, CHART)
                [row] = [v for v in baked(root, "page.json")["claims"][CLAIM]["values"]
                         if v["gate"] == GATE]
                self.assertEqual(row["limit"], 10.0, "the evaluator's own limit moved")
                chart = fig["chart"]
                self.assertEqual({k: chart[k] for k in ("limit", "current")}, {
                    "limit": {"value": limit, "comparator": "<=", "units": "Pa",
                              "label": f"Limit {limit:g} Pa"},
                    "current": {"x": 1.0, "y": 2.0, "margin_text": margin}})
                self.assertEqual(chart["current"]["margin_text"], row["margin_text"])
                # P1.5: the spec Vega-Lite draws holds the same limit and point
                # (G6 holds the spec too), and computes nothing.
                layers = chart["spec"]["layer"]
                self.assertEqual([l["encoding"]["y"]["datum"] for l in layers
                                  if l["mark"].get("style") == "nk-limit"], [limit])
                [point] = [l for l in layers if l["mark"].get("style") == "nk-current"]
                self.assertEqual((point["encoding"]["x"]["datum"],
                                  point["encoding"]["y"]["datum"]), (1.0, 2.0))
                from nopekit import page
                self.assertEqual(page.vega_forbidden(chart["spec"]), [])
        plant_page(root, lambda doc: page_figure_of(doc, CHART)["chart"]["limit"].update(
            value=10.0))
        edited = site_status(self, root)["edited"]
        self.assertTrue(edited and f"figure {CHART} chart reads" in edited[0], edited)
        plant_page(root, lambda doc: page_figure_of(doc, CHART)["chart"]["spec"]["layer"][0]
                   .update(transform=[{"calculate": "datum.y * 2", "as": "y"}]))
        edited = site_status(self, root)["edited"]
        self.assertTrue(edited and f"figure {CHART} chart spec holds 'calculate', 'transform'"
                        in edited[0], edited)

    def test_a_pack_limit_in_a_chart_is_refused(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        draw_settings(root, chart="planted-limit")
        summary = build_in(self, root, draw.env)
        self.assertTrue(any(CHART in w and "a chart's limit and its point are the claim's"
                            in w for w in summary["warnings"]), summary["warnings"])
        fig = page_figure(root, CHART)
        self.assertEqual((fig["currency"], fig["data_src"], fig["chart"]), ("none", "", {}))

    def test_a_caption_with_a_status_word_is_refused(self):
        """A caption that says a status is never published; one planted on the
        page reads edited by hand."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        draw_settings(root, caption="The field, checked against the limit.")
        summary = build_in(self, root, draw.env)
        self.assertTrue(any(PIC in w and "a caption may not say a status" in w
                            for w in summary["warnings"]), summary["warnings"])
        self.assertEqual(page_figure(root, PIC)["currency"], "none")
        draw_settings(root)
        build_in(self, root, draw.env)

        def edit(doc):
            for fig in [page_figure_of(doc, PIC), doc["representation"]["figure"]]:
                fig["caption"] = "The field is inside the limit."

        plant_page(root, edit)
        edited = site_status(self, root)["edited"]
        self.assertTrue(edited and "caption says 'inside the limit', a status" in edited[0],
                        edited)


def page_figure_of(doc: dict, view_id: str, cid: str = CLAIM) -> dict:
    return next(f for f in doc["claims"][cid]["figures"] if f["view"] == view_id)


#: A colour scale of the shape the CFD pack bakes (B.3.4), for the figure
#: project's still: ``hi`` a pack factor times the summary's ``u_ref``, never a
#: limit.
SCALE = {"quantity": "value", "units": "Pa", "lo": 0.0, "hi": 3.75,
         "stops": [{"at": 0.0, "colour": "#440154"}, {"at": 1.0, "colour": "#fde725"}],
         "over": "#ff00ff", "under": "#808080",
         "over_word": "Magenta shows a value over the top of the scale.",
         "under_word": "Grey shows a value under the bottom of the scale.",
         "ticks": [{"at": 0.4, "value": 1.5, "text": "1.5 Pa"}],
         "source": [{"key": "u_ref", "factor": 3.75}],
         "source_text": "The scale is 3.75 times the reference value of the run."}


class TheScaleIsAPackConstant(_env.EnvCase):
    """(Invariant 14) A figure's colour range is a pack constant times a value
    of its evidence, never a claim's limit: a limit edit moves no scale, and a
    range keyed to a limit or ending at one is refused; every number a chart
    draws is one its evidence holds."""

    def test_the_scale_never_moves_with_the_limit(self):
        """D1's limit doubled and the still drawn again (its scene edited): the
        sidecar's scale and the page's are the same bytes, while the chart's
        limit moved with the claim."""
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        a = check_at(self, root, 1.0)
        draw_settings(root, scale=SCALE)
        build_in(self, root, draw.env)
        scale = json.dumps(sidecar_of(root, a, PIC)["scale"], sort_keys=True)
        set_limit(root, 20.0)
        edit_scene(root, "scene 2")
        build_in(self, root, draw.env)
        self.assertEqual(len(draw.calls()), 2, "the still was not drawn again")
        self.assertEqual(json.dumps(sidecar_of(root, a, PIC)["scale"], sort_keys=True), scale)
        self.assertEqual(json.dumps(page_figure(root, PIC)["scale"], sort_keys=True), scale)
        self.assertEqual(page_figure(root, CHART)["chart"]["limit"]["value"], 20.0)

    def test_a_scale_keyed_to_a_limit_is_refused(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        for label, scale in (("source", {**SCALE, "source": [{"key": "limit_pa",
                                                              "factor": 1.0}]}),
                             ("end", {**SCALE, "hi": 10.0})):
            with self.subTest(label):
                draw_settings(root, scale=scale)
                summary = build_in(self, root, draw.env)
                self.assertTrue(any(PIC in w and "a colour range taken from a limit" in w
                                    for w in summary["warnings"]), summary["warnings"])
                self.assertEqual(page_figure(root, PIC)["currency"], "none")

    def test_a_bound_viewgen_reads_no_limit(self):
        """A bound viewgen's context holds every claim with no acceptance: the
        chart, asked to note each claim's limit it is handed, notes none. Red
        with the strip removed: it noted D1's 10.0, so a scale could be keyed to
        any multiple of it, which the refusal of a range that ends at a limit
        does not catch."""
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        draw_settings(root, note_limits=True)
        summary = build_in(self, root, no_tool_env())
        self.assertEqual([w for w in summary["warnings"] if "limits seen:" in w],
                         [f"view {CHART}: limits seen: {CLAIM}=None"])

    def test_every_chart_number_is_in_the_evidence(self):
        draw = Draw(self)
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        draw_settings(root, chart="computed")
        summary = build_in(self, root, draw.env)
        self.assertTrue(any(CHART in w and "which no evidence file of this result holds" in w
                            for w in summary["warnings"]), summary["warnings"])
        self.assertEqual(page_figure(root, CHART)["currency"], "none")


if __name__ == "__main__":
    unittest.main()
