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
import unittest
from unittest import mock

import _env
import _projects
from nopekit import verdicts

GATE = "demo.drop"


def run(case: _env.EnvCase, root: str, *argv: str, code: int | None = 0):
    proc = _env.nopekit(list(argv), cwd=root)
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


def build(case: _env.EnvCase, root: str) -> dict:
    if not os.path.isdir(os.path.join(root, "site")):
        run(case, root, "site", "init")
    proc = run(case, root, "site", "build", "--json")
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
        root = _projects.figure_project(os.path.join(self.tmp(), "fig"))
        check_at(self, root, 1.0)
        run(self, root, "site", "init")
        before = tree(root, but="site")
        build(self, root)
        after = tree(root, but="site")
        moved = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        for rel in moved:
            with self.subTest(rel):
                self.assertEqual(_env.git(["check-ignore", "-q", rel], cwd=root).returncode, 0,
                                 f"site build wrote {rel}, which git does not ignore")
        self.assertFalse([p for p in moved if p.startswith(".nopekit/cache/evidence/")],
                         "site build wrote a manifest")


if __name__ == "__main__":
    unittest.main()
