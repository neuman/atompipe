# SPDX-License-Identifier: Apache-2.0
"""The live site outlives the shell that started it: `site serve --watch --detach`.

What slipped through (the acceptance run after phase 3b): the agent started
`nopekit site serve --watch` as a background task, and in that environment a
background task lives at most two hours, so the person's live page died
mid-session; under headless `claude -p` a background task that still runs keeps
the turn from ending at all. These tests hold what `--detach` promises instead:

* it returns at once and keeps none of the caller's descriptors, so the caller's
  pipes reach end of file — what a harness and `claude -p` wait for;
* the server is a session of its own, so the death of the starter's whole process
  group, which is how a harness ends a task, leaves it serving;
* a second `--detach` prints the running URL and starts nothing, `--stop` stops it,
  `site status` says whether one runs and where, and none of it writes a record;
* a record whose server is gone never makes `--stop` signal its pid, which the OS
  may have given to another process, and a server whose record is gone stops
  itself;
* a server that refuses before it listens is quoted in its own words, exit 2, and
  leaves no record;
* off POSIX, `--detach` and `--stop` say plainly that they are not supported yet.

Every child goes through `_env` (test_meta.NoSubprocessOutsideRun); the starter
that dies and the stranger whose pid a stale record names are `python -c` children
of `_env.run`, in the clean environment it gives every child.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_serve.py'
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import signal
import socket
import sys
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

import _env
import _projects
from nopekit import cli, site, store
from nopekit.util import NopekitError

#: The longest a `--detach` may take before its caller's pipes close. It binds
#: and records its address in about a second; a call that holds the caller's
#: pipe open runs into this and fails, naming the command.
DETACH_TIMEOUT_S = 60

#: A background task, as a harness runs one: a session of its own that starts the
#: detached server, says what the call printed, and is then killed with its whole
#: process group. `subprocess.run` with pipes returns only once every holder of
#: those pipes has closed them: a server that kept them reads "never closed".
_STARTER = r'''
import json, os, signal, subprocess, sys
os.setsid()
try:
    done = subprocess.run(sys.argv[1:], capture_output=True, text=True,
                          timeout=float(os.environ["DETACH_TIMEOUT"]))
    said = {"rc": done.returncode, "out": done.stdout, "err": done.stderr}
except subprocess.TimeoutExpired:
    said = {"rc": None, "out": "", "err": "the caller's pipes never closed"}
print(json.dumps(said), flush=True)
os.killpg(os.getpgrp(), signal.SIGKILL)
'''

#: A stranger: a live process in a session of its own, holding no pipe of its
#: starter's, whose pid a stale record will name.
_STRANGER = r'''
import subprocess, sys
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"],
                     start_new_session=True, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
print(p.pid, flush=True)
'''


def _status(url: str) -> int:
    with urllib.request.urlopen(url, timeout=10) as response:
        return response.status


def _refused(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2):
            return False
    except (urllib.error.URLError, OSError):
        return True


def _alive(pid: int) -> bool:
    """Whether ``pid`` runs: signal 0 answers, and on Linux it is no zombie."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
            return fh.read().rsplit(")", 1)[-1].split()[0] != "Z"
    except OSError:
        return True


def _records(root: str) -> dict:
    """``{path: (bytes, mtime_ns, inode)}`` of every record file (test_records'
    snapshot, for one project)."""
    out = {}
    paths = [os.path.join(root, store.NOPEKIT_DIR, store.PROJECT_NAME)]
    for kind in store.RECORD_DIRS:
        for directory, dirnames, names in os.walk(os.path.join(root, kind)):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            paths += [os.path.join(directory, name) for name in names]
    for path in paths:
        if os.path.isfile(path):
            st = os.stat(path)
            with open(path, "rb") as fh:
                out[os.path.relpath(path, root)] = (fh.read(), st.st_mtime_ns, st.st_ino)
    return out


@unittest.skipUnless(os.name == "posix", "--detach is POSIX only, and says so elsewhere")
class TheLiveSiteOutlivesItsStarter(_env.EnvCase):

    def setUp(self):
        self.home = self.tmp()
        self.root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["site", "init", "-C", self.root]), 0)
        self.addCleanup(self._stop_whatever_runs)

    def _stop_whatever_runs(self) -> None:
        if cli._serve_state(self.root).state in ("running", "starting"):
            self.serve("--stop")
        found = cli._serve_state(self.root)
        if found.pid and cli._serve_lock_held(self.root):
            with contextlib.suppress(OSError):
                os.kill(found.pid, signal.SIGKILL)

    def nopekit(self, *argv: str, timeout: float = DETACH_TIMEOUT_S):
        return _env.nopekit([*argv], cwd=self.root, home=self.home, timeout=timeout)

    def serve(self, *argv: str):
        return self.nopekit("site", "serve", "-C", self.root, *argv)

    def record_path(self) -> str:
        return os.path.join(self.root, *cli.SERVE_STATE_REL.split("/"))

    def record(self) -> dict:
        with open(self.record_path(), encoding="utf-8") as fh:
            return json.load(fh)

    def url_of(self, proc) -> str:
        found = re.search(site.SERVE_READY_RE, proc.stdout)
        self.assertIsNotNone(found, proc.stdout + proc.stderr)
        return found.group(1)

    def test_the_starters_death_leaves_it_serving(self):
        argv = [sys.executable, "-m", "nopekit", "site", "serve", "-C", self.root, "--watch",
                "--detach", "-p", "0"]
        task = _env.run([sys.executable, "-c", _STARTER, *argv], cwd=self.root, home=self.home,
                        env={"DETACH_TIMEOUT": DETACH_TIMEOUT_S},
                        timeout=DETACH_TIMEOUT_S + 60)
        self.assertEqual(task.returncode, -signal.SIGKILL, task.stdout + task.stderr)
        said = json.loads(task.stdout.splitlines()[0])
        self.assertEqual(said["rc"], 0, said)
        found = re.search(site.SERVE_READY_RE, said["out"])
        self.assertIsNotNone(found, said)
        url = found.group(1)
        doc = self.record()
        pid = doc["pid"]
        self.assertEqual((doc["url"], doc["watch"], doc["log"]), (url, True, cli.SERVE_LOG_REL))
        self.assertEqual(os.getsid(pid), pid, "the server is not a session of its own")
        self.assertNotEqual(os.getsid(pid), os.getsid(0))
        # The task and its whole process group are dead; the page is not.
        self.assertEqual(_status(url), 200)
        self.assertEqual(_status(url + "data/build.json"), 200)
        status = self.nopekit("site", "status", "-C", self.root)
        self.assertIn(f"live: serving at {url} (pid {pid}, watching", status.stdout)
        doctor = self.nopekit("doctor", "-C", self.root)
        self.assertIn(f"live at {url} (pid {pid})", doctor.stdout)

    def test_a_second_detach_starts_nothing_and_stop_stops_it(self):
        before = _records(self.root)
        first = self.serve("--watch", "--detach", "-p", "0")
        self.assertEqual(first.returncode, 0, first.stderr)
        url = self.url_of(first)
        pid = self.record()["pid"]
        self.assertIn(f"detached (pid {pid}, watching", first.stdout)
        self.assertEqual(_status(url), 200)
        again = self.serve("--watch", "--detach")
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.url_of(again), url)
        self.assertIn("already running", again.stdout)
        self.assertIn("nothing new was started", again.stdout)
        self.assertEqual(self.record()["pid"], pid)
        stopped = self.serve("--stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertIn(f"stopped the live site at {url} (pid {pid})", stopped.stdout)
        self.assertTrue(_refused(url), "the server answers after --stop")
        self.assertFalse(os.path.exists(self.record_path()))
        self.assertEqual(cli._serve_state(self.root).state, "none")
        status = self.nopekit("site", "status", "-C", self.root)
        self.assertIn("live: no detached server runs", status.stdout)
        twice = self.serve("--stop")
        self.assertEqual(twice.returncode, 0, twice.stderr)
        self.assertIn("no detached site server runs for this project", twice.stdout)
        after = _records(self.root)
        touched = sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))
        self.assertEqual(touched, [], "the detached server wrote a record")

    def test_a_record_whose_server_is_gone_never_signals_its_pid(self):
        """The pid alone is no witness: a record outlives its server (a crash,
        a reboot), and the OS hands its pid to another process. Only the lock
        the server holds says it runs."""
        stranger = int(_env.run([sys.executable, "-c", _STRANGER], cwd=self.root,
                                home=self.home).stdout.strip())

        def kill_stranger() -> None:
            with contextlib.suppress(OSError):
                os.kill(stranger, signal.SIGKILL)
        self.addCleanup(kill_stranger)

        def plant() -> None:
            os.makedirs(os.path.dirname(self.record_path()), exist_ok=True)
            with open(self.record_path(), "w", encoding="utf-8") as fh:
                json.dump({"pid": stranger, "host": "127.0.0.1", "port": 9,
                           "url": "http://127.0.0.1:9/", "watch": True, "started": "",
                           "node": socket.gethostname(), "log": cli.SERVE_LOG_REL}, fh)
        plant()
        self.assertTrue(_alive(stranger))
        self.assertEqual(cli._serve_state(self.root).state, "stale")
        status = self.nopekit("site", "status", "-C", self.root)
        self.assertIn(f"(the record of pid {stranger} is stale)", status.stdout)
        stop = self.serve("--stop")
        self.assertEqual(stop.returncode, 0, stop.stderr)
        self.assertIn(f"no detached site server runs for this project (the record of pid "
                      f"{stranger} was stale, and is removed)", stop.stdout)
        time.sleep(0.3)
        self.assertTrue(_alive(stranger), "--stop signalled the pid of a stale record")
        self.assertFalse(os.path.exists(self.record_path()))
        # A start over a stale record starts a server; it never reads "already".
        plant()
        started = self.serve("--detach", "-p", "0")
        self.assertEqual(started.returncode, 0, started.stderr)
        self.assertNotIn("already running", started.stdout)
        self.assertNotEqual(self.record()["pid"], stranger)
        self.assertTrue(_alive(stranger))

    def test_a_start_that_fails_says_why(self):
        """A server that refuses before it listens (here, a port another process
        holds) is quoted in its own words, exit 2, and leaves no record a reader
        could take for a running server."""
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            taken.listen(1)
            port = taken.getsockname()[1]
            started = self.serve("--detach", "-p", str(port))
        self.assertEqual(started.returncode, 2, started.stdout + started.stderr)
        self.assertIn(f"error: the live site did not start: port {port} on 127.0.0.1 is "
                      f"already in use", started.stderr)
        self.assertNotIn("start: error:", started.stderr)
        self.assertFalse(os.path.exists(self.record_path()))
        self.assertEqual(cli._serve_state(self.root).state, "none")

    def test_a_server_whose_record_is_gone_stops_itself(self):
        """A test's temporary project deleted with its server running, or a
        `git clean -X`, must not leave a server serving nothing for good."""
        first = self.serve("--detach", "-p", "0")
        self.assertEqual(first.returncode, 0, first.stderr)
        url = self.url_of(first)
        self.assertEqual(_status(url), 200)
        os.remove(self.record_path())
        deadline = time.monotonic() + 20
        while not _refused(url) or cli._serve_lock_held(self.root):
            if time.monotonic() > deadline:
                self.fail("the server still runs 20 s after its record was removed")
            time.sleep(0.2)
        with open(os.path.join(self.root, *cli.SERVE_LOG_REL.split("/")),
                  encoding="utf-8") as fh:
            self.assertIn("no longer names this server", fh.read())


class DetachSaysWhenItCannot(unittest.TestCase):
    """Off POSIX (no new session, no `flock`), `--detach` and `--stop` refuse in
    one plain sentence, and `site status` says the same."""

    def test_windows_is_told_plainly(self):
        root = os.path.join(os.path.dirname(__file__), "no-such-project")
        for argv in (["site", "serve", "--watch", "--detach"], ["site", "serve", "--stop"]):
            args = cli.build_parser().parse_args(argv)
            run = cli._serve_detach if args.detach else cli._serve_stop
            with mock.patch.object(os, "name", "nt"):
                with self.assertRaises(NopekitError) as caught:
                    run(root, args)
            self.assertIn("`--detach` is not supported on Windows yet", str(caught.exception))
        with mock.patch.object(os, "name", "nt"):
            found = cli._serve_state(root)
        self.assertEqual(found.state, "unsupported")
        self.assertEqual(cli._serve_line(found), "live: --detach is not supported on Windows yet")


if __name__ == "__main__":
    unittest.main()
