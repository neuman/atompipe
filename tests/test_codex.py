# SPDX-License-Identifier: Apache-2.0
"""The Codex plugin: its manifest and its copy of the skills.

``skills/`` is Claude Code's and stays as it is; ``codex/skills/`` is written
from it by ``codex/sync.py`` and is an output. What this file holds against:
two skills that drift apart without anyone noticing (a command renamed in one,
a rule added to one), a copy that still names ``${CLAUDE_PLUGIN_ROOT}``, which
Codex is not documented to substitute in a skill, and a manifest that points at
files the plugin does not hold.

Not an invariant class: a wrong copy breaks an install, not a verdict. The
agent markers Codex sets are invariant 11's, in ``test_signing.CHANNEL_ROWS``.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import unittest

import _env

REPO = _env.REPO
MANIFEST = os.path.join(REPO, ".codex-plugin", "plugin.json")
CLAUDE_MANIFEST = os.path.join(REPO, ".claude-plugin", "plugin.json")
FIX = "python3 codex/sync.py"


def _sync():
    spec = importlib.util.spec_from_file_location(
        "nopekit_codex_sync", os.path.join(REPO, "codex", "sync.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: str) -> str:
    with open(path, encoding="utf-8", newline="") as fh:
        return fh.read()


def copy_problems(want: dict[str, str], have: dict[str, str | None]) -> list[str]:
    """Every copy that differs from what ``codex/sync.py`` writes, is missing, or
    has no source skill."""
    out = []
    for rel, text in want.items():
        if have.get(rel) is None:
            out.append(f"{rel} is missing; run {FIX}")
        elif have[rel] != text:
            out.append(f"{rel} is not what its source writes; run {FIX}")
    out += [f"{rel} has no source skill" for rel in have if rel not in want]
    return out


def _committed() -> dict[str, str | None]:
    base = os.path.join(REPO, "codex", "skills")
    out: dict[str, str | None] = {}
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        path = os.path.join(base, name, "SKILL.md")
        out[f"codex/skills/{name}/SKILL.md"] = _read(path) if os.path.isfile(path) else None
    return out


#: A path into the plugin, as the copy names it.
ROOTED = re.compile(r"<plugin-root>/(?P<path>[\w./-]*\w)")


def text_problems(rel: str, text: str) -> list[str]:
    """A ``${CLAUDE_PLUGIN_ROOT}`` left in a copy, and every ``<plugin-root>/…``
    path it names that the plugin does not hold."""
    out = []
    for n, line in enumerate(text.splitlines(), start=1):
        if "CLAUDE_PLUGIN_ROOT" in line:
            out.append(f"{rel}:{n}: names CLAUDE_PLUGIN_ROOT")
        for found in ROOTED.finditer(line):
            if not os.path.exists(os.path.join(REPO, *found.group("path").split("/"))):
                out.append(f"{rel}:{n}: <plugin-root>/{found.group('path')} is not in the plugin")
    return out


class TheCodexSkillsAreCurrent(unittest.TestCase):

    def test_the_copies_as_committed(self):
        self.assertEqual(copy_problems(_sync().expected(), _committed()), [])

    def test_a_drifted_copy_is_caught(self):
        want = _sync().expected()
        rel = "codex/skills/nopekit/SKILL.md"
        cases = {"stale": {**want, rel: want[rel].replace("nopekit doctor", "nopekit doc")},
                 "missing": {k: v for k, v in want.items() if k != rel},
                 "orphan": {**want, "codex/skills/gone/SKILL.md": "x"}}
        for name, have in cases.items():
            with self.subTest(name):
                self.assertNotEqual(copy_problems(want, have), [])

    def test_every_source_skill_has_a_copy(self):
        sources = {name for name in os.listdir(os.path.join(REPO, "skills"))
                   if os.path.isfile(os.path.join(REPO, "skills", name, "SKILL.md"))}
        self.assertEqual({rel.split("/")[2] for rel in _sync().expected()}, sources)


class TheCopyNamesThePluginsOwnFiles(unittest.TestCase):

    def test_the_copies_as_committed(self):
        out = []
        for rel, text in _sync().expected().items():
            out += text_problems(rel, text)
        self.assertEqual(out, [])

    def test_planted_paths_are_caught(self):
        for line in ("Read `${CLAUDE_PLUGIN_ROOT}/METHOD.md`.",
                     "Read `<plugin-root>/docs/NOT_A_DOC.md`."):
            with self.subTest(line):
                self.assertNotEqual(text_problems("x", line), [])

    def test_the_preamble_says_where_the_root_is(self):
        """"three levels above the directory holding this file" holds."""
        sync = _sync()
        self.assertIn("three levels above", sync.PREAMBLE)
        for rel in sync.expected():
            here = os.path.dirname(os.path.join(REPO, *rel.split("/")))
            root = os.path.normpath(os.path.join(here, "..", "..", ".."))
            self.assertTrue(os.path.isfile(os.path.join(root, ".codex-plugin", "plugin.json")),
                            rel)

    def test_the_front_matter_is_the_sources(self):
        """Codex picks a skill by its name and description: the same as Claude Code's."""
        for rel, text in _sync().expected().items():
            source = _read(os.path.join(REPO, "skills", rel.split("/")[2], "SKILL.md"))
            end = source.find("\n---\n", 4) + 5
            self.assertTrue(text.startswith(source[:end]), rel)

    def test_the_claude_skills_are_untouched(self):
        """The copy is written beside ``skills/``, never into it, and Claude Code's
        skill still names its root its own way."""
        sync = _sync()
        self.assertEqual(os.path.normpath(sync.SOURCE), os.path.join(REPO, "skills"))
        self.assertTrue(all(rel.startswith("codex/") for rel in sync.expected()))
        self.assertIn("${CLAUDE_PLUGIN_ROOT}",
                      _read(os.path.join(REPO, "skills", "nopekit", "SKILL.md")))


class TheCodexManifestIsThePlugins(unittest.TestCase):

    def setUp(self):
        with open(MANIFEST, encoding="utf-8") as fh:
            self.manifest = json.load(fh)
        with open(CLAUDE_MANIFEST, encoding="utf-8") as fh:
            self.claude = json.load(fh)

    def test_it_says_what_claude_codes_says(self):
        for key in ("name", "description", "homepage", "license", "author"):
            with self.subTest(key):
                self.assertEqual(self.manifest.get(key), self.claude.get(key))

    def test_its_version_is_the_packages(self):
        found = re.search(r'^version\s*=\s*"([^"]+)"',
                          _read(os.path.join(REPO, "pyproject.toml")), re.M)
        self.assertEqual(self.manifest.get("version"), found.group(1))

    def test_it_points_at_the_copies_and_the_one_hook(self):
        skills = os.path.normpath(os.path.join(REPO, self.manifest["skills"]))
        self.assertEqual(skills, os.path.join(REPO, "codex", "skills"))
        hooks = os.path.normpath(os.path.join(REPO, self.manifest["hooks"]))
        self.assertEqual(hooks, os.path.join(REPO, "hooks", "hooks.json"))


if __name__ == "__main__":
    unittest.main()
