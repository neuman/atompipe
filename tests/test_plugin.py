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


# --------------------------------------------------------------------------- #
# Architecture phase 6: the Stop hook and the skill a first session reads
# --------------------------------------------------------------------------- #
HOOK_COMMAND = 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 "${CLAUDE_PLUGIN_ROOT}/hooks/stop.py"'
#: The command the plugin shipped before the review of phase 6: `-m` puts the
#: session's cwd first on sys.path. Kept as the planted control below.
OLD_HOOK_COMMAND = 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT}/src" python3 -m nopekit round --hook'


def _read(rel: str) -> str:
    with open(os.path.join(_env.REPO, *rel.split("/")), encoding="utf-8") as fh:
        return fh.read()


def _subcommands() -> set[str]:
    import argparse
    from nopekit import cli
    parser = cli.build_parser()
    (sub,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return {c.dest for c in sub._choices_actions}


def command_table_problems(skill: str, subcommands: set[str]) -> list[str]:
    """The skill's `## Commands` block against the parser's top-level
    subcommands, both ways: one it names that does not exist, and one that
    exists and it never names."""
    at = skill.find("## Commands")
    if at < 0:
        return ["no ## Commands section"]
    fence = re.search(r"```[^\n]*\n(.*?)```", skill[at:], re.S)
    if fence is None:
        return ["## Commands holds no fenced block"]
    named = set()
    for line in fence.group(1).splitlines():
        found = re.match(r"^nopekit\s+([a-z][a-z-]*)", line.strip())
        if found:
            named.add(found.group(1))
    out = [f"the table names `nopekit {n}`, which is no command" for n in sorted(named - subcommands)]
    out += [f"the table never names `nopekit {n}`" for n in sorted(subcommands - named)]
    return out


#: The skill's sections, in the order a first session meets them (SPEC 37 with 21).
SKILL_HEADINGS = ("# nopekit", "## Make it runnable", "## 1. Interview first",
                  "## 2. First light and the live site", "## 3. Claims and boards",
                  "## 4. The loop", "## 5. Rounds", "## Rules that must not bend",
                  "## Commands", "## Reference")


class TheStopHookIsDeclared(unittest.TestCase):
    """The plugin's Stop hook runs `round --hook` from the plugin's own `src`,
    with a 300 s budget, and the command it runs parses."""

    def test_hooks_json(self):
        import json
        doc = json.loads(_read("hooks/hooks.json"))
        self.assertEqual(doc, {"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": HOOK_COMMAND, "timeout": 300}]}]}})
        from nopekit import cli
        launcher = _read("hooks/stop.py")
        found = re.search(r'main\(\[("[^"]+"(?:, "[^"]+")*)\]\)', launcher)
        self.assertIsNotNone(found, "hooks/stop.py calls no main([...])")
        words = [w.strip().strip('"') for w in found.group(1).split(",")]
        self.assertEqual(words, ["round", "--hook"])
        args = cli.build_parser().parse_args(words)
        self.assertIs(args.func, cli.cmd_round)
        self.assertTrue(args.hook)


#: Modules a session's cwd may hold, each named for a module the hook imports
#: (the standard library's, and nopekit itself). Each one, imported, leaves a
#: marker and exits 2 — Claude Code's "block the turn".
_PLANTED = ("difflib.py", "types.py", "queue.py", "select.py", "token.py", "json.py",
            "nopekit/__init__.py")


def planted_cwd_problems(command: str, plugin_root: str = _env.REPO) -> list[str]:
    """What goes wrong when the Stop hook ``command`` runs, as Claude Code runs
    it (a shell, ``CLAUDE_PLUGIN_ROOT`` set), from a directory holding a module
    for each of `_PLANTED`: a planted module that ran, an exit other than 0, or
    stdout other than one JSON object."""
    import json
    import shutil
    import tempfile
    cwd = tempfile.mkdtemp(prefix="nopekit-planted-")
    try:
        for rel in _PLANTED:
            path = os.path.join(cwd, *rel.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            marker = os.path.join(cwd, "RAN-" + rel.replace("/", "-"))
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"open({marker!r}, 'w').close()\nraise SystemExit(2)\n")
        proc = _env.run(["sh", "-c", command], cwd=cwd, input=json.dumps({"cwd": cwd}),
                        env={"CLAUDE_PLUGIN_ROOT": plugin_root})
        out = [f"the planted {name[4:]} ran" for name in sorted(os.listdir(cwd))
               if name.startswith("RAN-")]
        if proc.returncode != 0:
            out.append(f"exit {proc.returncode}")
        lines = proc.stdout.splitlines()
        try:
            if len(lines) != 1 or not isinstance(json.loads(lines[0]), dict):
                out.append(f"stdout is not one JSON object: {proc.stdout!r}")
        except ValueError:
            out.append(f"stdout is not one JSON object: {proc.stdout!r}")
        return out
    finally:
        shutil.rmtree(cwd, ignore_errors=True)


@unittest.skipUnless(os.name == "posix", "the hook command is a POSIX shell line")
class TheStopHookImportsNothingFromTheCwd(unittest.TestCase):
    """Review of phase 6: the hook ran `python3 -m nopekit`, and `-m` puts the
    session's cwd first on sys.path — so a `difflib.py` in any repository the
    plugin is installed for ran as code at every turn's end, and one that exited
    2 blocked the turn before the hook's catch-all existed."""

    def test_the_hook_as_shipped(self):
        self.assertEqual(planted_cwd_problems(HOOK_COMMAND), [])

    def test_the_old_command_is_caught(self):
        found = planted_cwd_problems(OLD_HOOK_COMMAND)
        self.assertTrue(any(p.startswith("the planted ") for p in found), found)
        self.assertIn("exit 2", found)

    def test_a_plugin_whose_nopekit_does_not_import_says_so(self):
        import json
        import shutil
        import tempfile
        plugin = tempfile.mkdtemp(prefix="nopekit-plugin-")
        self.addCleanup(shutil.rmtree, plugin, True)
        os.makedirs(os.path.join(plugin, "hooks"))
        shutil.copy(os.path.join(_env.REPO, "hooks", "stop.py"),
                    os.path.join(plugin, "hooks", "stop.py"))
        os.makedirs(os.path.join(plugin, "src", "nopekit"))
        with open(os.path.join(plugin, "src", "nopekit", "__init__.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("raise ImportError('a broken install')\n")
        proc = _env.run(["sh", "-c", HOOK_COMMAND], cwd=plugin, input="{}",
                        env={"CLAUDE_PLUGIN_ROOT": plugin})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(proc.stdout.splitlines()), 1, proc.stdout)
        said = json.loads(proc.stdout)["systemMessage"]
        self.assertIn("could not start (ImportError: a broken install)", said)


class TheSkillNamesEveryCommand(unittest.TestCase):
    def test_the_table_is_the_parser(self):
        self.assertEqual(command_table_problems(_read("skills/nopekit/SKILL.md"),
                                                _subcommands()), [])

    def test_a_missing_or_invented_command_is_caught(self):
        skill = "## Commands\n\n```\nnopekit init   # x\nnopekit frobnicate  # y\n```\n"
        found = command_table_problems(skill, {"init", "status"})
        self.assertIn("the table names `nopekit frobnicate`, which is no command", found)
        self.assertIn("the table never names `nopekit status`", found)


class TheSkillTeachesTheFirstSession(unittest.TestCase):
    """SPEC 37 with 21: the method plus a command table, in the order a first
    session needs it — interview, first light with the live site's URL, claims,
    the loop, rounds — and short enough to be read whole."""

    def test_the_order_and_the_words(self):
        skill = _read("skills/nopekit/SKILL.md")
        lines = skill.splitlines()
        at = [lines.index(heading) for heading in SKILL_HEADINGS]
        self.assertEqual(at, sorted(at), "the skill's sections are out of order")
        for phrase in ("requirements/R1.json", "site serve --watch", "URL", "site stamp",
                       "packs skills", "people", "round --hook", "ASD-STE100",
                       "say skip", "nopekit why", "nopekit propose <id>", "lenses.md",
                       "intro.md", "next.md"):
            self.assertIn(phrase, skill)
        self.assertLess(len(lines), 260)

    def test_the_turn_ends_with_a_check_before_the_stamp(self):
        """Review of phase 6: the steps stamped the boards before any check, so
        after a model edit the stamp digested Stale tokens, the hook's check
        moved them, and the round committed text stamped against results that
        no longer held."""
        skill = _read("skills/nopekit/SKILL.md")
        steps = skill[skill.index("**Before your turn ends:**"):skill.index("## Rules")]
        self.assertIn("nopekit check", steps)
        self.assertLess(steps.index("nopekit check"), steps.index("site stamp"))
        # The lenses are reached through a command that prints them.
        self.assertNotIn("lenses: `nopekit packs show", skill)

    def test_the_live_site_detaches_and_the_map_is_drawn(self):
        """The acceptance run after phase 3b: the agent ran `site serve --watch` as a
        background task (there one lives at most two hours, and under `claude -p` it
        keeps the turn from ending), wrote boards only (every choice drew in one
        generated zone, every shared value under its raw name), and kept its own
        files in directories a round's closed list never staged."""
        skill = _read("skills/nopekit/SKILL.md")
        first_light = skill[skill.index("## 2. First light"):skill.index("## 3. Claims")]
        self.assertIn("nopekit site serve --watch --detach", first_light)
        self.assertIn("background task", first_light)
        claims = skill[skill.index("## 3. Claims"):skill.index("## 4. The loop")]
        for said in ("groups/<id>.json", '"kind": "board"', "`zone`", "`station`",
                     "nopekit site build"):
            self.assertIn(said, claims)
        commits = skill[skill.index("## 5. Rounds"):skill.index("**Before your turn ends:**")]
        for said in ("git does not ignore", "named like a", ".gitignore"):
            self.assertIn(said, commits)
        table = skill[skill.index("## Commands"):]
        self.assertIn("nopekit site serve --watch --detach", table)


if __name__ == "__main__":
    unittest.main()
