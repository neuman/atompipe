# SPDX-License-Identifier: Apache-2.0
"""The plugin's paths (architecture phase 1: SPEC decision 37, its path half).

Claude Code substitutes ``${CLAUDE_PLUGIN_ROOT}`` — braced — in a plugin
skill's body; the unbraced ``$CLAUDE_PLUGIN_ROOT`` is not substituted, and the
variable is not in the Bash tool's environment, so an unbraced path reached the
shell as an empty string and the skill's first command imported nothing. And a
document a skill names by a bare ``METHOD.md`` or ``docs/…`` resolves against
the person's project, where neither exists. No ``bin/``: hosts other than the
CLI refuse a plugin that has one.

Not an invariant class: a wrong path breaks an install, not a verdict.
"""
from __future__ import annotations

import glob
import os
import re
import unittest

import _env

#: Where a path into the plugin can be written.
PLUGIN_GLOBS = ("skills/*/SKILL.md", "skills/*/*.md", ".claude-plugin/*.json",
                "hooks/*.json", "hooks/*")

UNBRACED = re.compile(r"\$CLAUDE_PLUGIN_ROOT(?!\w)")
#: A document of the plugin named by its repository path: METHOD.md or a
#: docs/<NAME>.md, with whatever precedes it.
DOC = re.compile(r"(?<![\w./-])(?P<prefix>\$\{CLAUDE_PLUGIN_ROOT\}/)?"
                 r"(?P<path>METHOD\.md|docs/[A-Z][A-Z_]*\.md)")
#: Shell state a skill tells the agent to set once (review of phase 1): the Bash
#: tool starts each call in a fresh shell, and a non-interactive shell expands
#: no alias, so the next bare `nopekit` read "command not found".
SESSION_STATE = re.compile(r"^\s*(?:export\s+\w+=|alias\s+\w+=)")
#: A plugin path joined into a search path with ':' — Windows splits PYTHONPATH
#: on ';', so the joined value imported nothing there. One entry, no separator.
JOINED = re.compile(r"PATH=[\"']?\$\{CLAUDE_PLUGIN_ROOT\}/[^\s\"'`:;]*[:;]")


def _files(root: str) -> dict[str, str]:
    out = {}
    for pattern in PLUGIN_GLOBS:
        for path in sorted(glob.glob(os.path.join(root, pattern))):
            if os.path.isfile(path):
                rel = os.path.relpath(path, root).replace(os.sep, "/")
                with open(path, encoding="utf-8") as fh:
                    out[rel] = fh.read()
    return out


def plugin_problems(files: dict[str, str], root: str = _env.REPO) -> list[str]:
    """Every unbraced ``$CLAUDE_PLUGIN_ROOT``; every METHOD.md or docs path a
    skill names that is not ``${CLAUDE_PLUGIN_ROOT}``-rooted, or names a file
    the repository does not hold; and a ``bin/`` at the root."""
    out: list[str] = []
    for rel, text in files.items():
        for n, line in enumerate(text.splitlines(), start=1):
            if UNBRACED.search(line):
                out.append(f"{rel}:{n}: unbraced $CLAUDE_PLUGIN_ROOT")
            if not rel.startswith("skills/"):
                continue
            if SESSION_STATE.search(line):
                out.append(f"{rel}:{n}: shell state set once does not reach the next "
                           f"Bash call")
            if JOINED.search(line):
                out.append(f"{rel}:{n}: a plugin path joined with a separator")
            for found in DOC.finditer(line):
                path = found.group("path")
                if not found.group("prefix"):
                    out.append(f"{rel}:{n}: {path} without ${{CLAUDE_PLUGIN_ROOT}}/")
                if not os.path.isfile(os.path.join(root, *path.split("/"))):
                    out.append(f"{rel}:{n}: {path} is not in the plugin")
    if os.path.isdir(os.path.join(root, "bin")):
        out.append("bin/ at the plugin root")
    return out


class PluginPathsAreBraced(unittest.TestCase):

    def test_the_plugin_as_shipped(self):
        files = _files(_env.REPO)
        self.assertIn("skills/nopekit/SKILL.md", files)
        self.assertIn("skills/pack-authoring/SKILL.md", files)
        self.assertEqual(plugin_problems(files), [])
        said = files["skills/nopekit/SKILL.md"]
        self.assertIn('PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m nopekit --version',
                      said)
        self.assertIn("`${CLAUDE_PLUGIN_ROOT}/METHOD.md`", said)
        named = {m.group("path") for text in files.values() for m in DOC.finditer(text)}
        self.assertEqual(named, {"METHOD.md", "docs/EXTENSION_PROTOCOL.md",
                                 "docs/PACK_FORMAT.md", "docs/SITE_CONTRACT.md"})

    def test_planted_paths_are_caught(self):
        rows = {
            "unbraced": ("skills/x/SKILL.md", 'PYTHONPATH="$CLAUDE_PLUGIN_ROOT/src"\n',
                         "unbraced"),
            "bare METHOD": ("skills/x/SKILL.md", "Read `METHOD.md` first.\n",
                            "METHOD.md without"),
            "bare docs": ("skills/x/SKILL.md", "See `docs/PACK_FORMAT.md`.\n",
                          "docs/PACK_FORMAT.md without"),
            "missing": ("skills/x/SKILL.md", "See `${CLAUDE_PLUGIN_ROOT}/docs/NOWHERE.md`.\n",
                        "docs/NOWHERE.md is not in the plugin"),
            "a manifest": (".claude-plugin/plugin.json", '{"x": "$CLAUDE_PLUGIN_ROOT/bin"}\n',
                           "unbraced"),
            # The skill's recipe before review of phase 1.
            "an export once": ("skills/x/SKILL.md",
                               'export PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src:$PYTHONPATH"\n',
                               "shell state"),
            "an alias": ("skills/x/SKILL.md", "alias nopekit='python3 -m nopekit'\n",
                         "shell state"),
            "a joined path": ("skills/x/SKILL.md",
                              'PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src:$P" python3 -m nopekit\n',
                              "joined with a separator"),
        }
        for label, (rel, text, needle) in rows.items():
            with self.subTest(label):
                found = plugin_problems({rel: text})
                self.assertTrue(any(needle in p for p in found), found)
        self.assertEqual(plugin_problems({"skills/x/SKILL.md":
                                          "See `${CLAUDE_PLUGIN_ROOT}/docs/PACK_FORMAT.md`; "
                                          "a project's `docs/decisions.md`.\n"}), [])

    def test_a_bin_directory_is_caught(self):
        import tempfile
        root = tempfile.mkdtemp(prefix="nopekit-plugin-")
        os.makedirs(os.path.join(root, "bin"))
        self.assertEqual(plugin_problems({}, root), ["bin/ at the plugin root"])
        os.rmdir(os.path.join(root, "bin"))
        os.rmdir(root)


if __name__ == "__main__":
    unittest.main()
