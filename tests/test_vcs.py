# SPDX-License-Identifier: Apache-2.0
"""`vcs` is the only git edge, and it answers for the project it is asked about.

A git hook exports `GIT_DIR`, `GIT_INDEX_FILE` and `GIT_WORK_TREE` pointing at the
repository that ran the hook. An nopekit command started from one would, through
a naive `subprocess.run(["git", ...])`, report that repository's HEAD, index and
files as the project's — and a control entry's selftest walk, a verdict's age and
a signer's identity would all be facts about somewhere else. Each test below
plants the trap, shows it is real (a git that inherits the variables DOES answer
for the foreign repository), and then asks `vcs`.

The other half of the contract is that `vcs` never raises: no git, no repository,
a hung git — each is an answer (`None`, `{}`, `False`), because `verify.sh --dir`
checks a copy of the bracket with no `.git` and `test_site` runs `doctor` in a
bare temp directory (tests:H11).

Every repository here is built in a temp directory through `_env.git`; nothing
reads this checkout's own `.git`, which a `verify.sh --dir` copy does not have.
`vcs` runs in THIS process, so `setUp` pins what it inherits: no global or system
git config, no user excludes, no inherited `GIT_*` — the dev box's `~/.gitconfig`
must not decide what `ls_files` ignores.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p test_vcs.py -v
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import stat
import sys
import time
import unittest
from unittest import mock

from nopekit import vcs

import _env

#: The variables spec §4 U13 says the git edge strips. The test also plants every
#: variable the installed git lists in `git rev-parse --local-env-vars` — git's own
#: list of what picks a repository — so a newer git that adds one turns this red.
SPEC_STRIPPED = (
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_COMMON_DIR", "GIT_NAMESPACE",
    "GIT_CEILING_DIRECTORIES", "GIT_CONFIG_PARAMETERS",
)

#: What the git edge sets on every call.
SPEC_SET = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}


def _write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


class VcsIsTheOnlyGitEdge(_env.EnvCase):
    def setUp(self):
        environ = mock.patch.dict(os.environ)
        environ.start()
        self.addCleanup(environ.stop)
        for name in list(os.environ):
            if name.startswith(("GIT_", "CLAUDE")) or name in ("EMAIL", "XDG_CONFIG_HOME"):
                del os.environ[name]
        home = self.tmp()
        os.environ.update({"HOME": home, "XDG_CONFIG_HOME": home,
                           "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})

    # -- helpers ------------------------------------------------------------ #
    def _require_git(self) -> None:
        # Not an invariant class, so this skip is allowed; every CI runner and
        # every checkout of this repository has git. The no-git and hung-git
        # tests below run without one.
        if shutil.which("git") is None:
            self.skipTest("git is not on PATH")

    def _git(self, args, cwd, **kw):
        proc = _env.git(args, cwd=cwd, **kw)
        self.assertEqual(proc.returncode, 0, f"git {args}: {proc.stderr}")
        return proc.stdout

    def _repo(self, files: dict[str, str], *, when: str = "2021-01-01T00:00:00Z") -> str:
        self._require_git()
        repo = self.tmp()
        self._git(["init", "-q"], repo)
        if files:
            self._commit(repo, files, when=when)
        return repo

    def _commit(self, repo: str, files: dict[str, str], *, when: str) -> str:
        for rel, text in files.items():
            _write(os.path.join(repo, rel), text)
        self._git(["add", "--", *files], repo)
        self._git(["commit", "-qm", f"at {when}"], repo, identity=True,
                  env={"GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when})
        return self._git(["rev-parse", "HEAD"], repo).strip()

    def _not_a_repo(self) -> str:
        path = self.tmp()
        if shutil.which("git") is not None:
            self.assertNotEqual(
                _env.git(["rev-parse", "--git-dir"], cwd=path).returncode, 0,
                f"{path} is inside a git repository: this machine's temp directory "
                f"is, so a non-repository cannot be built here")
        return path

    def _fake_git(self, body: str) -> str:
        """A directory holding an executable ``git`` that runs ``body`` (Python)."""
        bindir = self.tmp()
        path = os.path.join(bindir, "git")
        _write(path, f"#!{sys.executable}\n{body}\n")
        os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return bindir

    # -- the spec's V: a foreign repository in the environment -------------- #
    def test_a_foreign_repository_in_the_environment_is_ignored(self):
        project = self._repo({"p.txt": "p\n"})
        self._git(["config", "user.name", "Project Person"], project)
        self._git(["config", "user.email", "project@nopekit.invalid"], project)
        project_head = self._git(["rev-parse", "HEAD"], project).strip()
        foreign = self._repo({"f.txt": "f\n", "g.txt": "g\n"}, when="2019-05-05T00:00:00Z")
        foreign_head = self._git(["rev-parse", "HEAD"], foreign).strip()
        plain = self._not_a_repo()

        planted = {
            "GIT_DIR": os.path.join(foreign, ".git"),
            "GIT_INDEX_FILE": os.path.join(foreign, ".git", "index"),
            "GIT_WORK_TREE": foreign,
            "GIT_CONFIG_PARAMETERS": "'user.name'='Foreign Hook' 'user.email'='hook@foreign.invalid'",
        }
        # The trap is real: a git that inherits these answers for the foreign
        # repository, even asked from inside the project, even from no repository.
        self.assertEqual(self._git(["rev-parse", "HEAD"], project, env=planted).strip(),
                         foreign_head)
        self.assertEqual(self._git(["rev-parse", "HEAD"], plain, env=planted).strip(),
                         foreign_head)
        self.assertIn("Foreign Hook",
                      self._git(["var", "GIT_AUTHOR_IDENT"], project, env=planted))

        with mock.patch.dict(os.environ, planted):
            self.assertEqual(vcs.git_head(project), project_head)
            self.assertTrue(vcs.is_repo(project))
            self.assertEqual(vcs.ls_files(project, []), ["p.txt"])
            self.assertEqual(vcs.ls_files(project, [], others=False), ["p.txt"])
            self.assertEqual(vcs.commit_times(project, ["p.txt", "f.txt"]),
                             {"p.txt": "2021-01-01T00:00:00Z"})
            self.assertEqual(vcs.ident(project), "Project Person <project@nopekit.invalid>")

            self.assertIsNone(vcs.git_head(plain), "a directory with no repository "
                              "answered with the inherited GIT_DIR's HEAD")
            self.assertFalse(vcs.is_repo(plain))
            self.assertIsNone(vcs.ls_files(plain, []))
            self.assertEqual(vcs.commit_times(plain, ["f.txt"]), {})

    def test_the_call_is_argv_with_a_clean_environment(self):
        """What the child actually receives, recorded by a stand-in git."""
        where = self.tmp()
        record = os.path.join(where, "record.json")
        bindir = self._fake_git(
            "import json, os, sys\n"
            f"json.dump({{'argv': sys.argv[1:], 'env': dict(os.environ)}}, open({record!r}, 'w'))\n"
            "print('0' * 40)")
        local = []
        if shutil.which("git") is not None:
            local = self._git(["rev-parse", "--local-env-vars"], where).split()
            self.assertIn("GIT_DIR", local, "git no longer lists its local variables")
        planted = {name: "planted" for name in (*SPEC_STRIPPED, *local)}
        planted.update(PATH=bindir, GIT_CONFIG_GLOBAL=os.devnull,
                       GIT_AUTHOR_NAME="A User", LC_ALL="xx_XX.UTF-8")
        with mock.patch.dict(os.environ, planted):
            head = vcs.git_head(where)

        self.assertTrue(os.path.isfile(record), "the stand-in git never ran — is the "
                        "temp directory mounted noexec?")
        self.assertEqual(head, "0" * 40, "vcs did not take the stand-in's answer")
        with open(record, encoding="utf-8") as fh:
            seen = json.load(fh)
        self.assertEqual(seen["argv"][:2], ["-C", where], "not argv form with -C root")
        leaked = sorted(name for name in (*SPEC_STRIPPED, *local) if name in seen["env"])
        self.assertEqual(leaked, [], "a repository-selecting variable reached git")
        for name, value in SPEC_SET.items():
            self.assertEqual(seen["env"].get(name), value, name)
        # What the user set on purpose is theirs: their config file, their name.
        self.assertEqual(seen["env"].get("GIT_CONFIG_GLOBAL"), os.devnull)
        self.assertEqual(seen["env"].get("GIT_AUTHOR_NAME"), "A User")

    # -- never raises ------------------------------------------------------- #
    def test_a_non_repository_is_none(self):
        plain = self._not_a_repo()
        _write(os.path.join(plain, "a.txt"), "a\n")
        self.assertFalse(vcs.is_repo(plain))
        self.assertIsNone(vcs.git_head(plain))
        self.assertIsNone(vcs.ls_files(plain, []))
        self.assertIsNone(vcs.ls_files(plain, ["a.txt"], others=False))
        self.assertEqual(vcs.commit_times(plain, ["a.txt"]), {})
        missing = os.path.join(plain, "no-such-dir")
        self.assertIsNone(vcs.git_head(missing))
        self.assertIsNone(vcs.ls_files(missing, []))
        self.assertIsNone(vcs.ident(missing))

    def test_a_forced_timeout_is_none(self):
        """A hung git (an fsmonitor daemon, a credential prompt) costs the timeout
        and reads as no answer — never a hang, never an exception."""
        project = self.tmp()
        bindir = self._fake_git("import time\ntime.sleep(60)")
        calls = {
            "git_head": lambda: vcs.git_head(project),
            "is_repo": lambda: vcs.is_repo(project),
            "ls_files": lambda: vcs.ls_files(project, []),
            "ident": lambda: vcs.ident(project),
            "commit_times": lambda: vcs.commit_times(project, ["x"]),
        }
        with mock.patch.dict(os.environ, {"PATH": bindir}), \
                mock.patch.object(vcs, "VCS_TIMEOUT_S", 0.5):
            for name, call in calls.items():
                with self.subTest(call=name):
                    started = time.perf_counter()
                    answer = call()
                    elapsed = time.perf_counter() - started
                    self.assertIn(answer, (None, {}, False))
                    # Waited for the timeout — so the stand-in did run and hang,
                    # rather than failing to start — and gave up long before it.
                    self.assertGreaterEqual(elapsed, 0.45, f"{name} returned in {elapsed:.2f}s")
                    self.assertLess(elapsed, 20, f"{name} waited {elapsed:.1f}s")

    def test_no_git_at_all_is_none(self):
        empty = self.tmp()
        with mock.patch.dict(os.environ, {"PATH": empty}):
            self.assertFalse(vcs.is_repo(empty))
            self.assertIsNone(vcs.git_head(empty))
            self.assertIsNone(vcs.ls_files(empty, []))
            self.assertIsNone(vcs.ident(empty))
            self.assertEqual(vcs.commit_times(empty, ["x"]), {})

    # -- each answer -------------------------------------------------------- #
    def test_git_head_and_is_repo(self):
        repo = self._repo({"a.txt": "a\n", "sub/b.txt": "b\n"})
        head = self._git(["rev-parse", "HEAD"], repo).strip()
        self.assertEqual(vcs.git_head(repo), head)
        self.assertEqual(vcs.git_head(os.path.join(repo, "sub")), head)
        self.assertTrue(vcs.is_repo(os.path.join(repo, "sub")))
        self.assertFalse(vcs.is_repo(os.path.join(repo, ".git")), "the git dir is not a work tree")

        unborn = self._repo({})
        _write(os.path.join(unborn, "new.txt"), "n\n")
        self.assertTrue(vcs.is_repo(unborn))
        self.assertIsNone(vcs.git_head(unborn), "no commit yet, so no HEAD")
        self.assertEqual(vcs.ls_files(unborn, []), ["new.txt"])

    def test_ls_files_is_tracked_plus_untracked_not_ignored(self):
        odd = "we ird\nname-é.json"       # a newline and a non-ASCII byte: -z keeps it exact
        repo = self._repo({
            ".gitignore": "*.log\nbuild/\n",
            "selftest/a.json": "{}\n",
            "selftest/sub/b.py": "x = 1\n",
            f"selftest/{odd}": "{}\n",
            "model/m.py": "m = 1\n",
        })
        _write(os.path.join(repo, "selftest", "new.json"), "{}\n")        # untracked
        _write(os.path.join(repo, "selftest", "run.log"), "noise\n")      # ignored
        _write(os.path.join(repo, "selftest", "build", "y.bin"), "y\n")   # ignored dir

        tracked = ["selftest/a.json", f"selftest/{odd}", "selftest/sub/b.py"]
        self.assertEqual(vcs.ls_files(repo, ["selftest"]),
                         sorted(tracked + ["selftest/new.json"]))
        self.assertEqual(vcs.ls_files(repo, ["selftest"], others=False), sorted(tracked))
        self.assertEqual(vcs.ls_files(os.path.join(repo, "selftest"), []),
                         sorted(["a.json", odd, "new.json", "sub/b.py"]),
                         "paths are relative to the root asked about")
        self.assertIn(".gitignore", vcs.ls_files(repo, []))
        self.assertEqual(vcs.ls_files(repo, "selftest"), vcs.ls_files(repo, ["selftest"]),
                         "a lone path was read as its characters")
        # A pathspec is a path, never a pattern: a glob that would match two
        # files matches none, because no file is literally named that.
        self.assertEqual(vcs.ls_files(repo, ["selftest/*.json"]), [])

    def test_commit_times_are_the_newest_commit_touching_each_path(self):
        repo = self._repo({"a.txt": "1\n", "d/x.txt": "x\n"}, when="2020-01-01T00:00:00Z")
        self._commit(repo, {"d/y.txt": "y\n"}, when="2021-06-01T00:00:00Z")
        self._commit(repo, {"a.txt": "2\n"}, when="2022-03-04T05:06:07Z")
        _write(os.path.join(repo, "untracked.txt"), "u\n")

        self.assertEqual(
            vcs.commit_times(repo, ["a.txt", "d", "d/x.txt", "./d/y.txt",
                                    "untracked.txt", "missing.txt"]),
            {"a.txt": "2022-03-04T05:06:07Z", "d": "2021-06-01T00:00:00Z",
             "d/x.txt": "2020-01-01T00:00:00Z", "./d/y.txt": "2021-06-01T00:00:00Z"})
        self.assertEqual(vcs.commit_times(repo, ["."]), {".": "2022-03-04T05:06:07Z"})
        self.assertEqual(vcs.commit_times(os.path.join(repo, "d"), ["x.txt", "y.txt"]),
                         {"x.txt": "2020-01-01T00:00:00Z", "y.txt": "2021-06-01T00:00:00Z"})
        self.assertEqual(vcs.commit_times(repo, []), {})
        self.assertEqual(vcs.commit_times(repo, "a.txt"), {"a.txt": "2022-03-04T05:06:07Z"})

    def test_a_shallow_boundary_has_no_time(self):
        """CI checks out one commit, whose diff against nothing 'adds' every file.
        Dating an old entry to the clone's tip would make it look younger than it
        is; a path last touched at the boundary has no time instead."""
        src = self._repo({"a.txt": "1\n", "b.txt": "b\n"}, when="2020-01-01T00:00:00Z")
        self._commit(src, {"a.txt": "2\n"}, when="2022-02-02T00:00:00Z")
        full = vcs.commit_times(src, ["a.txt", "b.txt"])
        self.assertEqual(full, {"a.txt": "2022-02-02T00:00:00Z", "b.txt": "2020-01-01T00:00:00Z"})

        url = pathlib.Path(src).as_uri()
        depth1 = os.path.join(self.tmp(), "depth1")
        self._git(["clone", "--quiet", "--depth", "1", url, depth1], os.path.dirname(depth1))
        self.assertEqual(vcs.commit_times(depth1, ["a.txt", "b.txt"]), {},
                         "a shallow tip dated files it only appears to add")

        depth2 = os.path.join(self.tmp(), "depth2")
        self._git(["clone", "--quiet", "--depth", "2", url, depth2], os.path.dirname(depth2))
        self.assertEqual(vcs.commit_times(depth2, ["a.txt", "b.txt"]),
                         {"a.txt": "2022-02-02T00:00:00Z"},
                         "a.txt's change is a real diff; b.txt is only at the boundary")

    def test_ident_drops_the_timestamp_and_never_invents_one(self):
        repo = self._repo({"a.txt": "a\n"})
        self.assertIsNone(vcs.ident(repo), "no identity is configured anywhere, and "
                          "useConfigOnly must stop git inventing user@host")
        self._git(["config", "user.name", "Local Person"], repo)
        # A name with no email: without useConfigOnly git fills the email in from
        # the login and host name (on a machine whose host name has a dot) and
        # answers with an address nobody chose.
        self.assertIsNone(vcs.ident(repo), "an email git made up from the host name")
        self._git(["config", "user.email", "local@nopekit.invalid"], repo)
        self.assertEqual(vcs.ident(repo), "Local Person <local@nopekit.invalid>")
        # The user's own environment is their git: `git commit` would use it too.
        with mock.patch.dict(os.environ, {"GIT_AUTHOR_NAME": "Env Person",
                                          "GIT_AUTHOR_EMAIL": "env@nopekit.invalid"}):
            self.assertEqual(vcs.ident(repo), "Env Person <env@nopekit.invalid>")


class TheWritingHalf(_env.EnvCase):
    """Architecture phase 6: the writing half — `init_repo`, `add`, `commit` and
    the reads that serve them. Explicit literal paths only, `--only` so what the
    person staged stays theirs, never a push, a config write or a bypassed hook,
    and never a raise: no git, a hung git and a refusal are each an answer."""

    setUp = VcsIsTheOnlyGitEdge.setUp
    _require_git = VcsIsTheOnlyGitEdge._require_git
    _git = VcsIsTheOnlyGitEdge._git
    _repo = VcsIsTheOnlyGitEdge._repo
    _commit = VcsIsTheOnlyGitEdge._commit
    _not_a_repo = VcsIsTheOnlyGitEdge._not_a_repo
    _fake_git = VcsIsTheOnlyGitEdge._fake_git

    def _identity(self):
        os.environ.update(_env.IDENTITY)

    def test_add_takes_a_literal_path(self):
        repo = self._repo({"keep.txt": "k\n"})
        _write(os.path.join(repo, "a.json"), "{}\n")
        _write(os.path.join(repo, "*.json"), "{}\n")
        self.assertEqual(vcs.add(repo, ["*.json"]), vcs.Wrote(True, None, ""))
        self.assertEqual(vcs.staged_paths(repo), ["*.json"])

    def test_commit_only_leaves_what_the_person_staged(self):
        repo = self._repo({"x.txt": "x\n", "other.txt": "o\n"})
        self._identity()
        _write(os.path.join(repo, "other.txt"), "the person's staged edit\n")
        self._git(["add", "other.txt"], repo)
        _write(os.path.join(repo, "x.txt"), "x2\n")
        _write(os.path.join(repo, "new.txt"), "n\n")
        os.makedirs(os.path.join(repo, "gone"), exist_ok=True)
        self.assertTrue(vcs.add(repo, ["x.txt", "new.txt"]).ok)
        made = vcs.commit(repo, ["x.txt", "new.txt"], "round 1: x", "the body")
        self.assertTrue(made.ok, made.why)
        self.assertEqual(made.oid, vcs.git_head(repo))
        shown = self._git(["show", "--name-only", "--format=%s%n%b", "HEAD"], repo)
        self.assertIn("round 1: x", shown)
        self.assertIn("the body", shown)
        self.assertEqual(sorted(line for line in shown.splitlines()
                                if line.endswith(".txt")), ["new.txt", "x.txt"])
        self.assertEqual(vcs.staged_paths(repo), ["other.txt"])

    def test_the_argv_never_pushes_bypasses_or_configures(self):
        where = self.tmp()
        log = os.path.join(where, "argv.jsonl")
        bindir = self._fake_git(
            "import json, sys\n"
            f"open({log!r}, 'a').write(json.dumps({{'argv': sys.argv[1:], "
            "'stdin': sys.stdin.read() if not sys.stdin.isatty() else ''}) + '\\n')\n"
            # `init_repo` starts one only on git's own "no repository here".
            "if 'rev-parse' in sys.argv:\n"
            "    sys.stderr.write('fatal: not a git repository (or any of the parent "
            "directories): .git\\n')\n"
            "    sys.exit(128)\n")
        with mock.patch.dict(os.environ, {"PATH": bindir}):
            self.assertTrue(vcs.add(where, ["claims/C1.json", "a b/c.json"]).ok)
            self.assertTrue(vcs.commit(where, ["claims/C1.json"], "round 1: s", "b").ok)
            vcs.init_repo(where)
        with open(log, encoding="utf-8") as fh:
            calls = [json.loads(line) for line in fh]
        writes = [c for c in calls if {"add", "commit", "init"} & set(c["argv"])]
        self.assertEqual(len(writes), 3, calls)
        for call in writes:
            argv = call["argv"]
            self.assertEqual(argv[:2], ["-C", where])
            for banned in ("--no-verify", "-n", "push", "config", "-A", "core.hooksPath"):
                self.assertNotIn(banned, argv)
            if "--all" in argv:
                self.assertIn("--pathspec-from-file=-", argv)
            if "add" in argv or "commit" in argv:
                self.assertIn("--literal-pathspecs", argv)
                self.assertIn("--pathspec-file-nul", argv)
        commit = next(c for c in writes if "commit" in c["argv"])
        self.assertEqual(commit["argv"][2:4], ["-c", "user.useConfigOnly=true"])
        self.assertIn("--only", commit["argv"])
        self.assertEqual(commit["stdin"], "claims/C1.json\0")
        add = next(c for c in writes if "add" in c["argv"])
        self.assertEqual(add["stdin"], "claims/C1.json\0a b/c.json\0")

    def test_a_hung_git_is_a_timeout(self):
        project = self.tmp()
        bindir = self._fake_git("import time\ntime.sleep(60)")
        with mock.patch.dict(os.environ, {"PATH": bindir}), \
                mock.patch.object(vcs, "VCS_WRITE_TIMEOUT_S", 0.5):
            started = time.perf_counter()
            found = vcs.commit(project, ["x"], "s", "b")
            elapsed = time.perf_counter() - started
        self.assertEqual(found, vcs.Wrote(False, None, "timeout"))
        self.assertGreaterEqual(elapsed, 0.45)
        self.assertLess(elapsed, 20)

    def test_no_git_is_an_answer(self):
        empty = self.tmp()
        with mock.patch.dict(os.environ, {"PATH": empty}):
            self.assertEqual(vcs.add(empty, ["x"]), vcs.Wrote(False, None, "no-git"))
            self.assertEqual(vcs.commit(empty, ["x"], "s", "b").why, "no-git")
            self.assertEqual(vcs.init_repo(empty).why, "no-git")
            self.assertIsNone(vcs.changed_paths(empty))
            self.assertIsNone(vcs.operation(empty))

    def test_init_repo_inside_a_repository_is_refused(self):
        repo = self._repo({"a.txt": "a\n"})
        inner = os.path.join(repo, "sub")
        os.makedirs(inner)
        self.assertEqual(vcs.init_repo(inner), vcs.Wrote(False, None, "inside a repository"))
        self.assertFalse(os.path.exists(os.path.join(inner, ".git")))
        fresh = self._not_a_repo()
        self.assertEqual(vcs.init_repo(fresh), vcs.Wrote(True, None, ""))
        self.assertTrue(vcs.is_repo(fresh))
        self.assertEqual(vcs.operation(fresh), "")

    def test_a_repository_is_started_only_on_gits_no(self):
        """Review of phase 6: `init_repo` and `init` asked `is_repo`, which reads
        every failure as "no", so git's "dubious ownership" refusal (WSL's
        /mnt/c, shared drives, container volumes) started a nested repository
        inside an existing one. `in_repository` tells "no" from "no answer"."""
        repo = self._repo({"a.txt": "a\n"})
        inner = os.path.join(repo, "sub")
        os.makedirs(inner)
        self.assertEqual(vcs.in_repository(inner), (True, ""))
        self.assertEqual(vcs.in_repository(self._not_a_repo()), (False, ""))
        with mock.patch.dict(os.environ, {"GIT_TEST_ASSUME_DIFFERENT_OWNER": "1"}):
            self.assertFalse(vcs.is_repo(inner), "the refusal this guards against")
            inside, why = vcs.in_repository(inner)
            self.assertIsNone(inside)
            self.assertIn("dubious ownership", why)
            made = vcs.init_repo(inner)
        self.assertFalse(made.ok)
        self.assertTrue(made.why.startswith("git did not answer: "), made.why)
        self.assertFalse(os.path.exists(os.path.join(inner, ".git")), "a nested repository")
        # A `.git` git will not read stands above: that is no "no" either.
        broken = self._not_a_repo()
        _write(os.path.join(broken, ".git"), "gitdir: /nonexistent/nopekit-test\n")
        below = os.path.join(broken, "proj")
        os.makedirs(below)
        inside, why = vcs.in_repository(below)
        self.assertIsNone(inside, why)
        self.assertFalse(vcs.init_repo(below).ok)
        self.assertFalse(os.path.exists(os.path.join(below, ".git")))
        # A hung git is no answer.
        bindir = self._fake_git("import time\ntime.sleep(60)")
        with mock.patch.dict(os.environ, {"PATH": bindir}), \
                mock.patch.object(vcs, "VCS_TIMEOUT_S", 0.5):
            self.assertIsNone(vcs.in_repository(self.tmp())[0])

    def test_the_committer_is_read_on_its_own(self):
        repo = self._repo({"a.txt": "a\n"})
        os.environ.update(_env.IDENTITY)
        self.assertEqual(vcs.committer_ident(repo), "nopekit tests <tests@nopekit.invalid>")
        os.environ.update({"GIT_COMMITTER_NAME": "Mallory",
                           "GIT_COMMITTER_EMAIL": "m@evil.example"})
        self.assertEqual(vcs.committer_ident(repo), "Mallory <m@evil.example>")
        self.assertEqual(vcs.ident(repo), "nopekit tests <tests@nopekit.invalid>")

    def test_changed_paths_are_the_subtree_relative_to_it(self):
        repo = self._repo({"top.txt": "t\n", "sub/kept.txt": "k\n", "sub/gone.txt": "g\n",
                           "sub/mod.txt": "m\n"})
        sub = os.path.join(repo, "sub")
        _write(os.path.join(repo, "top.txt"), "t2\n")
        _write(os.path.join(sub, "mod.txt"), "m2\n")
        os.remove(os.path.join(sub, "gone.txt"))
        _write(os.path.join(sub, "staged.txt"), "s\n")
        self._git(["add", "sub/staged.txt"], repo)
        _write(os.path.join(sub, "new.txt"), "n\n")
        _write(os.path.join(repo, ".gitignore"), "*.log\n")
        _write(os.path.join(sub, "noise.log"), "ignored\n")
        # An mtime alone is not a change.
        os.utime(os.path.join(sub, "kept.txt"), (1, 1))
        self.assertEqual(vcs.changed_paths(sub),
                         ["gone.txt", "mod.txt", "new.txt", "staged.txt"])
        self.assertEqual(vcs.staged_paths(sub), ["staged.txt"])
        self.assertIsNone(vcs.changed_paths(self._not_a_repo()))

    def test_operation_names_each(self):
        repo = self._repo({"a.txt": "a\n"})
        self.assertEqual(vcs.operation(repo), "")
        head = vcs.git_head(repo)
        for name, word in (("MERGE_HEAD", "merge"), ("CHERRY_PICK_HEAD", "cherry-pick"),
                           ("REVERT_HEAD", "revert"), ("BISECT_LOG", "bisect"),
                           ("rebase-merge", "rebase"), ("rebase-apply", "rebase")):
            with self.subTest(name=name):
                where = os.path.join(repo, ".git", name)
                if name.startswith("rebase"):
                    os.makedirs(where)
                else:
                    _write(where, head + "\n")
                self.assertEqual(vcs.operation(os.path.join(repo)), word)
                if os.path.isdir(where):
                    os.rmdir(where)
                else:
                    os.remove(where)
        self._git(["checkout", "-q", "--detach"], repo)
        self.assertEqual(vcs.operation(repo), "detached")
        self.assertIsNone(vcs.operation(self._not_a_repo()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
