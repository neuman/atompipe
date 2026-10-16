# SPDX-License-Identifier: Apache-2.0
"""Groups on the readers (architecture phase 5, SPEC 17, 33, 36).

Boards, zones and stations are records; doctor FAILs on what the index names
and on a zone member the model does not choose; `why` resolves a group and a
claim's board; `site serve --watch` rebuilds the page when a record moves and
says so in `build.json`; `init` and `site badge` write the Made-with-nopekit
block at the bottom of a README and nothing else.

What slipped through before groups were records: the reference map's boards
were JavaScript lists no record held, so a claim added to a board never reached
it; and a project's README never said what made it.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_groups.py'
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import unittest
from unittest import mock

import _env
import _projects
from nopekit import cli, site, store


def _write_json(path: str, data: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")


def _doctor_row(root: str, name: str) -> dict:
    rows = json.loads(_env.nopekit(["doctor", "--json"], cwd=root).stdout)["checks"]
    [row] = [r for r in rows if r["check"] == name]
    return row


class GroupsOnTheReaders(_env.EnvCase):
    """(SPEC 17) doctor's `groups` row, `why` on a group and on a claim."""

    def test_doctor_and_why(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        row = _doctor_row(root, "groups")
        self.assertEqual(row["status"], "ok", row)
        self.assertIn("4 board(s), 4 zone(s), 2 station(s)", row["detail"])
        proc = _env.nopekit(["why", "strength"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("board strength: Holds the pump   (groups/strength.json)", proc.stdout)
        self.assertIn("claims: C1 failing · C2 checked · C3 checked · C6 gap", proc.stdout)
        self.assertIn("text: site/content/strength.md (current)", proc.stdout)
        proc = _env.nopekit(["why", "arm"], cwd=root)
        self.assertIn("zone arm: Arm shape", proc.stdout)
        self.assertIn("thickness = 7.0 mm", proc.stdout)
        proc = _env.nopekit(["why", "allowable"], cwd=root)
        self.assertIn("design_stress", proc.stdout)
        self.assertIn("read by: bracket.bearing, bracket.bending_stress", proc.stdout)
        proc = _env.nopekit(["why", "C1"], cwd=root)
        self.assertIn("board: strength (Holds the pump)", proc.stdout)

    def test_doctor_fails_on_what_the_records_and_the_model_refuse(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        _write_json(os.path.join(root, "groups", "second.json"),
                    {"kind": "board", "title": "Second", "members": ["C1", "C42"]})
        _write_json(os.path.join(root, "groups", "arm.json"),
                    {"kind": "zone", "title": "Arm shape", "members": ["arm_len", "width"]})
        row = _doctor_row(root, "groups")
        self.assertEqual(row["status"], "FAIL", row)
        self.assertIn("'C42', which has no claims/C42.json", row["detail"])
        self.assertIn("C1 sits on 2 boards", row["detail"])
        self.assertIn("zone arm names arm_len, which is not a choice of the model (did you "
                      "mean arm_length?)", row["detail"])
        index = store.build_index(root)
        self.assertTrue(any("C42" in p for p in index["problems"]), index["problems"])
        self.assertFalse(any("arm_len" in p for p in index["problems"]),
                         "the index judged the model")

    def test_claims_on_no_board_warn(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        os.remove(os.path.join(root, "groups", "pump.json"))
        row = _doctor_row(root, "groups")
        self.assertEqual(row["status"], "warn", row)
        self.assertIn("1 claim(s) on no board (C7)", row["detail"])


# --------------------------------------------------------------------------- #
class WatchRebuilds(_env.EnvCase):
    """(SPEC 33) The watcher rebuilds when a record moves, in a fresh process,
    marks `build.json` live, never runs `check`, and keeps the last page when a
    build fails."""

    def _read(self, root: str) -> dict:
        with open(os.path.join(root, "site", "data", "build.json"), encoding="utf-8") as fh:
            return json.load(fh)

    def _wait(self, root: str, predicate, timeout: float = 90.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                found = self._read(root)
            except (OSError, ValueError):
                found = {}
            if predicate(found):
                return found
            time.sleep(0.2)
        self.fail(f"build.json never changed: {found}")

    def test_an_edit_rebuilds_and_a_broken_model_keeps_the_page(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        for argv in (["site", "init"], ["site", "build"]):
            self.assertEqual(_env.nopekit(argv, cwd=root).returncode, 0)
        first = self._read(root)
        self.assertFalse(first["live"])
        verdicts = os.path.join(root, ".nopekit", "verdicts")
        entries = sorted(os.listdir(os.path.join(verdicts, "bracket.deflection")))
        env = _env.clean_env(home=self.tmp())
        stop = threading.Event()
        with mock.patch.dict(os.environ, env, clear=True):
            # The snapshot the page was built from, taken before the edit, as
            # `site serve --watch` takes it before its first build.
            thread = threading.Thread(target=cli._watch_loop,
                                      args=(root, 0.2, stop, site.watch_snapshot(root)),
                                      daemon=True)
            thread.start()
            try:
                path = os.path.join(root, "claims", "C7.json")
                with open(path, encoding="utf-8") as fh:
                    data = json.load(fh)
                data["statement"] = "First mode stays clear of the pump"
                _write_json(path, data)
                after = self._wait(root, lambda d: d.get("live") is True)
                self.assertTrue(after["ok"], after)
                with open(os.path.join(root, "site", "data", "page.json"),
                          encoding="utf-8") as fh:
                    shown = json.load(fh)["claims"]["C7"]["statement"]
                self.assertEqual(shown, "First mode stays clear of the pump")
                model = os.path.join(root, "model", "bracket.py")
                with open(model, "a", encoding="utf-8") as fh:
                    fh.write("\nthis is not python\n")
                failed = self._wait(root, lambda d: d.get("ok") is False)
                self.assertEqual(failed["id"], after["id"], "a failed build lost the page's id")
                self.assertTrue(failed["error"])
            finally:
                stop.set()
                thread.join(timeout=30)
        self.assertEqual(sorted(os.listdir(os.path.join(verdicts, "bracket.deflection"))),
                         entries, "the watcher ran an evaluator")


# --------------------------------------------------------------------------- #
class TheBadgeIsWritten(_env.EnvCase):
    """(SPEC 36) `init` writes the block at the bottom of a README, creating it
    when absent; `site badge` adds it to an older project; a second run changes
    nothing; every other byte stays; doctor suggests it."""

    def test_init_creates_and_keeps(self):
        root = os.path.join(self.tmp(), "fresh")
        proc = _env.nopekit(["init", "--name", "fresh", "--summary", "A test rig.", "-C", root],
                            cwd=self.tmp())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("README.md", proc.stdout)
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text, "# fresh\n\nA test rig.\n\n" + store.README_BADGE_BLOCK)
        self.assertIn("https://github.com/neuman/nopekit", text)
        self.assertEqual(_doctor_row(root, "readme")["status"], "ok")
        proc = _env.nopekit(["site", "badge"], cwd=root)
        self.assertIn("already carries", proc.stdout)
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)

    def test_an_older_readme_gains_it_once(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        user = "# My bracket\n\nMy own words, with a trailing space. \n"
        with open(os.path.join(root, "README.md"), "w", encoding="utf-8") as fh:
            fh.write(user)
        self.assertEqual(_doctor_row(root, "readme")["status"], "warn")
        proc = _env.nopekit(["site", "badge"], cwd=root)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(text, user + "\n" + store.README_BADGE_BLOCK)
        _env.nopekit(["site", "badge"], cwd=root)
        with open(os.path.join(root, "README.md"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)
        self.assertTrue(store.ensure_readme_badge(root) is False)

    def test_a_quoted_marker_or_a_lost_end_never_costs_text(self):
        """A README that quotes the begin marker, or whose end marker a person
        deleted, keeps every line of its own across two runs; the second run
        writes nothing; doctor reads only a whole block (review of phase 5: the
        second run deleted everything from the quote to the appended block)."""
        root = self.tmp()
        path = os.path.join(root, "README.md")
        for name, user in (
                ("quoted", "# X\n\nThe badge block starts with `" + store.README_BADGE_BEGIN
                 + "`.\n\n## Important section\n\nKeep me.\n"),
                ("lost end", "# X\n\n" + store.README_BADGE_BEGIN + "\n<img src=\"old.png\">\n"
                 "\n## Important section\n\nKeep me.\n")):
            with self.subTest(name):
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(user)
                self.assertFalse(store.readme_has_badge(user))
                self.assertTrue(store.ensure_readme_badge(root))
                self.assertFalse(store.ensure_readme_badge(root))
                with open(path, encoding="utf-8", newline="") as fh:
                    text = fh.read()
                self.assertEqual(text, user + "\n" + store.README_BADGE_BLOCK)
                self.assertTrue(store.readme_has_badge(text))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("# X\n\nThe block starts with " + store.README_BADGE_BEGIN + ".\n")
        root_project = _projects.bracket_copy(os.path.join(self.tmp(), "bracket"), migrated=True)
        shutil.copyfile(path, os.path.join(root_project, "README.md"))
        self.assertEqual(_doctor_row(root_project, "readme")["status"], "warn")

    def test_a_crlf_readme_keeps_its_line_endings(self):
        """The block goes into a CRLF README in CRLF, and a CRLF block is left
        as it is (review of phase 5: LF lines were added, and a CRLF checkout's
        block was rewritten on every run)."""
        root = self.tmp()
        path = os.path.join(root, "README.md")
        with open(path, "wb") as fh:
            fh.write(b"A\r\nB\r\n")
        self.assertTrue(store.ensure_readme_badge(root))
        with open(path, "rb") as fh:
            data = fh.read()
        self.assertEqual(data, b"A\r\nB\r\n\r\n"
                         + store.README_BADGE_BLOCK.replace("\n", "\r\n").encode("utf-8"))
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertFalse(store.ensure_readme_badge(root))


if __name__ == "__main__":
    unittest.main()
