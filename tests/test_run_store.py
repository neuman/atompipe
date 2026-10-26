# SPDX-License-Identifier: Apache-2.0
"""Issue #15's run store (the motorBike design's P9): a solve is reused by what
it read, and re-run at the boundary.

A full ``check --tier 2`` of the motorBike demo solves for about an hour, and
every OpenFOAM gate runs again at each check (its tools read files nopekit
cannot see, so its entry is never Fresh). ``GateContext.stored_run`` keeps each
solve in ``.nopekit/cache/runs/<key>/`` and serves it to the next check whose
staged inputs are the same. Each new place to serve a solve is a new place to
show a pass nothing earned, so three invariants are held here:

* 7 — ``TheRunStoreKeyIsWhatTheSolverRead``: any staged byte, the rank count,
  the argv, a tool's bytes, the install or the gate's code is another key; a
  qualification run keys its own fixture's bytes; a mutation run is handed no
  store; and a hit files the entry the solve filed, so it is never a second
  answer for one set of inputs.
* 8 — ``TheRunStoreIsScratch``: the store is under the ignored cache, and a
  check served from it leaves ``git status`` as the check that solved left it.
* 12 — ``TheBoundaryNeverReadsTheRunStore``: ``check --force``, ``export`` and
  ``export --dry-run`` solve again, and a run planted in the store is caught at
  the boundary.

The CLI tests run the aero-openfoam baseline through the stand-in OpenFOAM
(``tests/_aero_standin.py``), about 8 s a cold check. The real-tool test that a
second check of the spheroid baseline reuses its solve is in
``test_aero_openfoam.TheRunStoreOnTheRealTools`` (it skips where v2606 is not
installed, which an invariant class may not).
"""
from __future__ import annotations

import collections
import json
import os
import re
import sys
import tempfile
import unittest
from typing import Any

import _env
import _projects
from nopekit import gates as gates_mod
from nopekit import verdicts
from nopekit.gates import GateContext, RunStore
from nopekit.models import NegativeControl, Verdict
from nopekit.util import NopekitError
from nopekit.verdicts import GateTrace, Reads

from test_aero_openfoam import install_standin

CODE = "c" * 64


def _write(path: str, text: str) -> str:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _register(registry, gate_id, fn):
    gates_mod.gate(id=gate_id, registry=registry, claims=["C1"],
                   negative_control=NegativeControl(fixture="x:y"))(fn)
    return registry.get(gate_id)


#: The toy solver: a child process the trace cannot see into, which reads the
#: staged ``in.txt`` and writes ``out.txt`` and a ``log``.
SOLVER = ("import sys\n"
          "data = open('in.txt').read()\n"
          "open('out.txt', 'w').write(data.upper())\n"
          "open('log', 'w').write('ran\\n')\n")


#: The HOME the toy's tools run under: one directory for every run, so no run
#: makes (and lists, to remove) a temp HOME of its own (``_env.run``'s default).
TOY_HOME = tempfile.mkdtemp(prefix="nopekit-toy-home-")


def toy(ctx):
    """A gate shaped as aero-openfoam's: stage (``rm -rf``, then the inputs),
    the run store's run, the tools inside ``solving()``, then the outputs read
    from the stage on both paths."""
    stage = os.path.join(ctx.out_dir, "toy", "stage")
    _env.run(["rm", "-rf", "--", stage], cwd=ctx.root, home=TOY_HOME)
    os.makedirs(stage)
    _write(os.path.join(stage, "in.txt"), str(ctx.params["word"]))
    run = ctx.stored_run(stage, argv=[["toy"]], ranks=int(ctx.params.get("ranks", 1)))
    if not run.hit:
        with run.solving():
            done = _env.run([sys.executable, "-c", SOLVER], cwd=stage, home=TOY_HOME)
            assert done.returncode == 0, done.stderr
        run.keep([os.path.join(stage, "out.txt"), os.path.join(stage, "log")],
                 meta={"log": "log"})
    with open(os.path.join(stage, "out.txt"), encoding="utf-8") as fh:
        out = fh.read()
    return Verdict(gate="toy.solve", passed=out == "OK", detail=f"out {out}")


class _Toy(_env.EnvCase):
    def setUp(self):
        self.root = self.tmp()
        os.makedirs(os.path.join(self.root, ".nopekit"))
        self.out = os.path.join(self.root, ".nopekit", "out")
        self.store_dir = os.path.join(self.root, *gates_mod.RUN_STORE_DIR.split("/"))
        self.registry = gates_mod.Registry()
        self.spec, self.fn = _register(self.registry, "toy.solve", toy)
        self.anchors = verdicts.anchors_for(self.root, None, out_dir=self.out)

    def store(self, code: str = CODE) -> RunStore:
        return RunStore(directory=self.store_dir, gate="toy.solve", code=code)

    def ran(self, params: dict, store=None):
        """``(verdict, reads, store)`` of one traced run of the toy gate."""
        store = self.store() if store is None else store
        trace = GateTrace(anchors=self.anchors)
        ctx = GateContext(root=self.root, params=dict(params), out_dir=self.out, runs=store)
        v = gates_mod.run_gate(self.spec, self.fn, ctx, trace=trace)
        return v, Reads.from_trace(trace, anchors=self.anchors), store

    def stage(self, files: dict) -> str:
        stage = os.path.join(self.tmp(), "stage")
        for rel, text in files.items():
            _write(os.path.join(stage, *rel.split("/")), text)
        return stage

    def opened(self, stage: str, store=None, **kw):
        kw.setdefault("argv", [["blockMesh"], ["simpleFoam"]])
        kw.setdefault("ranks", 4)
        ctx = GateContext(root=self.root, out_dir=self.out,
                          runs=self.store() if store is None else store)
        return ctx.stored_run(stage, **kw)

    def kept(self, stage: str, **kw):
        """A run of ``stage`` stored with one output, ``out.txt``; its key."""
        run = self.opened(stage, **kw)
        self.assertFalse(run.hit)
        with run.solving():
            _write(os.path.join(stage, "out.txt"), "solved")
        run.keep([os.path.join(stage, "out.txt")])
        os.remove(os.path.join(stage, "out.txt"))
        return run.key


class TheRunStoreKeyIsWhatTheSolverRead(_Toy):
    """(7) A stored solve is served only to a run whose staged inputs, tools,
    rank count, argv and gate code are the ones it was solved from, and a hit
    files the entry its solve filed (the hit replays the solve's window)."""

    FILES = {"system/controlDict": "endTime 300;\n", "0/U": "uniform (20 0 0);\n"}

    def test_the_same_inputs_are_one_key_and_a_hit(self):
        stage = self.stage(self.FILES)
        key = self.kept(stage)
        again = self.opened(stage)
        self.assertEqual(again.key, key)
        self.assertTrue(again.hit)
        with open(os.path.join(stage, "out.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "solved", "the hit did not put the output back")

    def test_any_staged_byte_is_another_key(self):
        stage = self.stage(self.FILES)
        key = self.kept(stage)
        for rel, text in (("system/controlDict", "endTime 110;\n"),
                          ("0/U", "uniform (20 0 0); \n"),
                          ("constant/new", "")):
            with self.subTest(rel):
                path = os.path.join(stage, *rel.split("/"))
                was = self.FILES.get(rel)
                _write(path, text)
                run = self.opened(stage)
                self.assertNotEqual(run.key, key)
                self.assertFalse(run.hit)
                if was is None:
                    os.remove(path)
                else:
                    _write(path, was)
        self.assertTrue(self.opened(stage).hit, "the inputs put back did not find the solve")

    def test_the_rank_count_argv_install_and_tools_are_keys(self):
        stage = self.stage(self.FILES)
        tool = os.path.join(self.tmp(), "simpleFoam")
        _write(tool, "v1")
        key = self.kept(stage, tool={"build": "a"}, binaries=[tool])
        same = self.opened(stage, tool={"build": "a"}, binaries=[tool])
        self.assertEqual((same.key, same.hit), (key, True))
        for name, kw in (("ranks", {"ranks": 8}),
                         ("argv", {"argv": [["blockMesh"], ["simpleFoam", "-x"]]}),
                         ("install", {"tool": {"build": "b"}})):
            with self.subTest(name):
                run = self.opened(stage, **{"tool": {"build": "a"}, "binaries": [tool], **kw})
                self.assertNotEqual(run.key, key)
                self.assertFalse(run.hit)
        _write(tool, "v2")
        run = self.opened(stage, tool={"build": "a"}, binaries=[tool])
        self.assertNotEqual(run.key, key, "a tool rebuilt in place found the old solve")
        self.assertFalse(run.hit)

    def test_the_gates_code_is_a_key(self):
        stage = self.stage(self.FILES)
        key = self.kept(stage)
        run = self.opened(stage, store=self.store(code="d" * 64))
        self.assertNotEqual(run.key, key)
        self.assertFalse(run.hit)

    def test_the_key_is_taken_before_any_tool_runs(self):
        """Design §15: inputs only. The key is the run's when it is opened, and
        the solve's outputs (snappyHexMesh's differ byte for byte from run to
        run) never enter it: a second solve that wrote other bytes finds the
        first one's run."""
        stage = self.stage(self.FILES)
        run = self.opened(stage)
        key = run.key
        with run.solving():
            _write(os.path.join(stage, "out.txt"), "solved once")
        run.keep([os.path.join(stage, "out.txt")])
        self.assertEqual(run.key, key)
        _write(os.path.join(stage, "out.txt"), "solved again, other bytes")
        os.remove(os.path.join(stage, "out.txt"))
        again = self.opened(stage)
        self.assertEqual((again.key, again.hit), (key, True))

    def test_a_stored_run_whose_bytes_moved_is_never_served(self):
        stage = self.stage(self.FILES)
        key = self.kept(stage)
        kept = os.path.join(self.store_dir, key, "files", "0", "out.txt")
        with open(kept, "a", encoding="utf-8") as fh:
            fh.write("forged")
        self.assertFalse(self.opened(stage).hit)

    def test_an_output_that_is_a_staged_input_is_refused(self):
        stage = self.stage(self.FILES)
        run = self.opened(stage)
        with run.solving():
            pass
        with self.assertRaises(NopekitError):
            run.keep([os.path.join(stage, "0", "U")])

    def test_a_hit_files_the_entry_the_solve_filed(self):
        """A hit replays what the solve's window recorded, so its reads — and
        so its rho — are the solve's: two check runs of one design file one
        entry, never a second answer for one set of inputs."""
        miss, reads_miss, store = self.ran({"word": "ok"})
        self.assertEqual((miss.outcome, store.hits), ("pass", []), miss.render())
        hit, reads_hit, store = self.ran({"word": "ok"})
        self.assertEqual(hit.outcome, "pass", hit.render())
        self.assertEqual(len(store.hits), 1, "the second run solved again")
        self.assertTrue(any(c.startswith("subprocess:") for c in reads_miss.opaque))
        self.assertEqual(reads_hit.keyed(), reads_miss.keyed())
        self.assertEqual(verdicts.rho("toy.solve", "s", CODE, reads_hit),
                         verdicts.rho("toy.solve", "s", CODE, reads_miss))
        off, reads_off, _store = self.ran({"word": "ok"}, store=RunStore())
        self.assertEqual(reads_off.keyed(), reads_miss.keyed(),
                         "a run with the store off read otherwise than one with it on")

    def test_another_input_value_is_its_own_solve(self):
        self.ran({"word": "ok"})
        v, _reads, store = self.ran({"word": "no"})
        self.assertEqual((v.outcome, store.hits), ("fail", []), v.render())

    def test_a_window_that_reads_a_parameter_is_refused(self):
        def reads_in_window(ctx):
            stage = os.path.join(ctx.out_dir, "s")
            os.makedirs(stage, exist_ok=True)
            run = ctx.stored_run(stage, argv=[], ranks=1)
            with run.solving():
                ctx.params.get("word")
            return True
        spec, fn = _register(self.registry, "toy.peeks", reads_in_window)
        v = gates_mod.run_gate(spec, fn, GateContext(root=self.root, params={"word": "x"},
                                                     out_dir=self.out, runs=self.store()))
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("read a parameter", v.error)

    def test_a_mutation_run_is_handed_no_store(self):
        """A mutation pass writes nothing in the project (invariant 15), and the
        store is in the project: the walk's runs get none, though the
        known-good half's context carries the sweep's."""
        seen = []

        def records(ctx):
            seen.append(ctx.runs)
            return True
        spec, fn = _register(self.registry, "toy.walked", records)
        good = GateContext(root=self.root, params={"a": 1.0}, out_dir=self.out,
                           runs=self.store())
        walk_out = self.tmp()
        gates_mod._mutated_run(spec, fn, good, {"a": 1.0}, ("a",), 2.0, walk_out,
                               GateTrace(kind="control"))
        self.assertEqual(seen, [None])

    def test_a_fixture_never_hands_its_gate_a_store(self):
        """``gates.selftest`` hands the gate the spine's store, whatever the
        context it was handed or the fixture built: a store of another's
        choosing is never the one a control reads."""
        planted = RunStore(directory=os.path.join(self.tmp(), "elsewhere"), gate="toy.fixtured",
                           code=CODE)
        seen = []

        def records(ctx):
            seen.append(ctx.runs)
            return False
        _write(os.path.join(self.root, "selftest", "fx.py"), "def make(ctx):\n    return {}\n")
        gates_mod.gate(id="toy.fixtured", registry=self.registry, claims=["C1"],
                       negative_control=NegativeControl(fixture="selftest/fx.py:make"))(records)
        spec, fn = self.registry.get("toy.fixtured")
        handed = GateContext(root=self.root, out_dir=self.out, runs=planted)
        gates_mod.selftest(spec, fn, handed, fixture_root=self.root)
        self.assertEqual(seen, [None])
        mine = self.store()
        gates_mod.selftest(spec, fn, handed, fixture_root=self.root, runs=mine)
        self.assertIs(seen[-1], mine)

    def test_a_fixtures_one_edit_is_another_key(self):
        """A qualification run is never served a solve its fixture's inputs did
        not produce, even staged in the same place: aero.converged on the
        baseline, then on cut_short's one edit (endTime 110), then on the
        baseline's bytes from another case directory — through the stand-in,
        one out directory, one store. The edit misses and fails; the same
        bytes hit."""
        tool, bin_ = install_standin(os.path.join(self.tmp(), "tool"))
        from unittest import mock
        from test_aero_openfoam import SPHEROID, _baseline, _claims, _registry
        from nopekit.models import Ledger, ProjectMeta
        registry = _registry()
        spec, fn = registry.get("aero.converged")
        store = lambda: self.store()  # noqa: E731
        calls = os.path.join(tool, "calls")

        def converged(case: str):
            if os.path.exists(calls):
                os.remove(calls)
            runs = store()
            ctx = GateContext(root=self.root, ledger=Ledger(meta=ProjectMeta(name="aero"),
                                                            claims=_claims()),
                              params=dict(_baseline(), aero_case=case), out_dir=self.out,
                              tier=2, runs=runs)
            with mock.patch.dict(os.environ, {"PATH": bin_ + os.pathsep + "/usr/bin:/bin"}):
                v = gates_mod.run_gate(spec, fn, ctx)
            if not os.path.exists(calls):
                return v, runs.hits, []
            with open(calls, encoding="utf-8") as fh:
                return v, runs.hits, fh.read().split()

        import shutil
        good, hits, ran = converged(SPHEROID)
        self.assertEqual((good.outcome, hits), ("pass", []), good.render())
        cut = shutil.copytree(SPHEROID, os.path.join(self.tmp(), "cut"))
        control = os.path.join(cut, "system", "controlDict")
        with open(control, encoding="utf-8") as fh:
            text = fh.read()
        _write(control, re.sub(r"(?m)^endTime\s+300;", "endTime 110;", text))
        bad, hits, ran = converged(cut)
        self.assertEqual(bad.outcome, "fail", bad.render())
        self.assertEqual(hits, [], "the known-bad edit was served the known-good solve")
        self.assertIn("simpleFoam", ran)
        same, hits, ran = converged(shutil.copytree(SPHEROID, os.path.join(self.tmp(), "same")))
        self.assertEqual((same.outcome, len(hits)), ("pass", 1), same.render())
        self.assertNotIn("simpleFoam", ran)
        self.assertEqual(same.measured, good.measured)


# --------------------------------------------------------------------------- #
# the stand-in project
# --------------------------------------------------------------------------- #
class StandinProject:
    """The aero-openfoam baseline wrapped as a project, run through the
    stand-in OpenFOAM, with every tool it ran counted."""

    def __init__(self, test: _env.EnvCase, *, git: bool = False):
        self.test = test
        base = test.tmp()
        self.tool, bin_ = install_standin(os.path.join(base, "tool"))
        self.env = {"PATH": bin_ + os.pathsep + "/usr/bin:/bin"}
        self.root = _projects.wrap_pack_baseline("aero-openfoam", os.path.join(base, "proj"))
        self.git = git
        if git:
            for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "-m", "base"]):
                proc = _env.git(args, cwd=self.root, identity=True)
                test.assertEqual(proc.returncode, 0, proc.stderr)

    def run(self, *args: str, code: int | None = 0) -> Any:
        calls = os.path.join(self.tool, "calls")
        if os.path.exists(calls):
            os.remove(calls)
        proc = _env.nopekit(list(args), cwd=self.root, env=self.env, timeout=900,
                            identity=self.git)
        if code is not None:
            self.test.assertEqual(proc.returncode, code,
                                  f"nopekit {' '.join(args)}:\n{proc.stdout[-4000:]}\n"
                                  f"{proc.stderr[-3000:]}")
        return proc

    def check(self, *args: str, code: int | None = 0) -> Any:
        return self.run("check", "--tier", "2", *args, code=code)

    def calls(self) -> collections.Counter:
        try:
            with open(os.path.join(self.tool, "calls"), encoding="utf-8") as fh:
                return collections.Counter(fh.read().split())
        except OSError:
            return collections.Counter()

    def store_dir(self) -> str:
        return os.path.join(self.root, *gates_mod.RUN_STORE_DIR.split("/"))

    def manifests(self) -> dict:
        out = {}
        where = self.store_dir()
        for key in sorted(os.listdir(where)) if os.path.isdir(where) else ():
            path = os.path.join(where, key, "manifest.json")
            if os.path.isfile(path):
                with open(path, encoding="utf-8") as fh:
                    out[key] = json.load(fh)
        return out

    def stored(self, gate: str) -> list[str]:
        return [k for k, m in self.manifests().items() if m["gate"] == gate]

    def staged(self, key: str, name: str) -> list[str]:
        """The texts of the files named ``name`` the stored run's window read."""
        out = []
        for path in self.manifests()[key]["trace"]["files_read"]:
            if os.path.basename(path) == name and os.path.isfile(path):
                with open(path, encoding="utf-8", errors="replace") as fh:
                    out.append(fh.read())
        return out

    def check_run(self, gate: str) -> str:
        """The key of ``gate``'s check run (not a control's): its window wrote
        under the sweep's own out directory."""
        mine = os.path.join(self.root, ".nopekit", "out", "aero-openfoam",
                            gate.replace(".", "_")) + os.sep
        found = [k for k in self.stored(gate)
                 if any(p.startswith(mine) for p in self.manifests()[k]["trace"]["files_written"])]
        self.test.assertEqual(len(found), 1, found)
        return found[0]

    def verdicts(self, gate: str) -> str:
        return os.path.join(self.root, ".nopekit", "verdicts", gate)


class TheRunStoreIsScratch(_env.EnvCase):
    """(8) The store is under the ignored cache: a check that keeps a solve
    there, and a check served from it, write no record, and the second leaves
    ``git status`` exactly as the first did."""

    def test_the_store_is_in_the_cache_the_spine_ignores(self):
        """In process (~0.1 s): the store's directory is under ``.nopekit/cache/``,
        which the ignore block every project gets (``store``) names, as git reads
        it."""
        from nopekit import store
        self.assertTrue(gates_mod.RUN_STORE_DIR.startswith(".nopekit/cache/"))
        root = self.tmp()
        _write(os.path.join(root, ".nopekit", ".gitignore"), store._NOPEKIT_IGNORE_BLOCK)
        self.assertEqual(_env.git(["init", "-q"], cwd=root).returncode, 0)
        rel = f"{gates_mod.RUN_STORE_DIR}/{'a' * 64}/files/0/log.simpleFoam"
        proc = _env.git(["check-ignore", "-q", rel], cwd=root)
        self.assertEqual(proc.returncode, 0, f"{rel} is not ignored")

    def test_the_store_is_under_the_ignored_cache(self):
        self.assertTrue(gates_mod.RUN_STORE_DIR.startswith(".nopekit/cache/"))
        project = StandinProject(self, git=True)
        project.check()
        self.assertTrue(project.manifests(), "the check kept no solve")
        some = next(iter(project.manifests()))
        rel = f"{gates_mod.RUN_STORE_DIR}/{some}/manifest.json"
        proc = _env.git(["check-ignore", "-q", rel], cwd=project.root)
        self.assertEqual(proc.returncode, 0, f"{rel} is not ignored")
        status = _env.git(["status", "--porcelain", "--untracked-files=all"],
                          cwd=project.root).stdout
        self.assertNotIn("cache/runs", status)

    def test_a_check_served_from_the_store_writes_nothing_git_sees(self):
        project = StandinProject(self, git=True)
        project.check()
        for args in (["add", "-A"], ["commit", "-q", "-m", "first check"]):
            proc = _env.git(args, cwd=project.root, identity=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        second = project.check()
        self.assertIn("reused", second.stdout)
        self.assertEqual(project.calls()["simpleFoam"], 0,
                         f"the second check solved again: {project.calls()}")
        status = _env.git(["status", "--porcelain", "--untracked-files=all"],
                          cwd=project.root).stdout
        self.assertEqual(status, "", "a check served from the store moved what git sees")


class TheBoundaryNeverReadsTheRunStore(_env.EnvCase):
    """(12) The boundary re-executes: ``check --force``, ``export`` and ``export
    --dry-run`` solve every run again with the store full, and a run planted in
    the store — served by ``check``, which says *reused* — is caught there."""

    MILESTONE = "m"

    def project(self) -> StandinProject:
        project = StandinProject(self, git=True)
        project.check()
        _write(os.path.join(project.root, "milestones", f"{self.MILESTONE}.json"),
               json.dumps({"description": "the drag area's base-mesh run",
                           "requires": [self.converged_claim(project)]}, indent=2) + "\n")
        return project

    @staticmethod
    def converged_claim(project: StandinProject) -> str:
        """The wrapped claim aero.converged covers (one per gate, by its tag)."""
        registry = gates_mod.Registry()
        from nopekit import packs as packs_mod
        packs_mod.load_gates("aero-openfoam", registry, root=_env.REPO,
                             include_env=False, include_user=False)
        tags = set(registry.get("aero.converged")[0].claims)
        for name in sorted(os.listdir(os.path.join(project.root, "claims"))):
            with open(os.path.join(project.root, "claims", name), encoding="utf-8") as fh:
                claim = json.load(fh)
            if tags & set(claim.get("tags") or ()):
                return name[:-len(".json")]
        raise AssertionError(f"no claim carries {tags}")

    def test_the_sweep_hands_force_a_disabled_store(self):
        s = verdicts._Session(root="/p", now=None, anchors=None, digests=None, held={},
                              verified={}, record=False, when="")
        self.assertFalse(verdicts._run_store(s, None, None).enabled)

    def test_force_solves_again(self):
        project = self.project()
        cold = project.calls()
        forced = project.check("--force")
        self.assertNotIn("reused", forced.stdout)
        self.assertGreater(project.calls()["simpleFoam"], 0)
        plain = project.check()
        self.assertIn("reused", plain.stdout)
        self.assertEqual(project.calls()["simpleFoam"], 0, cold)

    def test_export_and_its_dry_run_solve_again(self):
        project = self.project()
        for args in (["--dry-run"], []):
            with self.subTest(args=args):
                proc = project.run("export", self.MILESTONE, *args, code=None)
                self.assertNotIn("reused", proc.stdout)
                self.assertGreater(project.calls()["simpleFoam"], 0,
                                   f"export {args} was served the store:\n{proc.stdout[-3000:]}")

    def test_a_planted_run_is_caught_at_the_boundary(self):
        """The base mesh's run cut short (endTime 110) fails; its stored run
        forged to a settled history — its bytes and its manifest made to agree
        — is served by ``check``, which reads it pass and says *reused*, and
        ``export`` solves it again and judges its own solve: the claim is not
        checked there, and the export is refused."""
        project = StandinProject(self, git=True)
        control = os.path.join(project.root, "selftest", "assets", "spheroid", "system",
                               "controlDict")
        with open(control, encoding="utf-8") as fh:
            text = fh.read()
        self.assertEqual(len(re.findall(r"(?m)^endTime\s+300;", text)), 1)
        _write(control, re.sub(r"(?m)^endTime\s+300;", "endTime 110;", text))
        real = project.check("--only", "aero.converged", code=None)
        self.assertRegex(real.stdout, r"(?m)^\[FAIL\] aero\.converged : ", real.stdout[-3000:])
        claim = self.converged_claim(project)
        _write(os.path.join(project.root, "milestones", f"{self.MILESTONE}.json"),
               json.dumps({"description": "the drag area's base-mesh run",
                           "requires": [claim]}, indent=2) + "\n")
        key = project.check_run("aero.converged")
        manifest = os.path.join(project.store_dir(), key, "manifest.json")
        with open(manifest, encoding="utf-8") as fh:
            data = json.load(fh)
        rows = [r for r in data["files"] if r[1].endswith("coefficient.dat")]
        self.assertEqual(len(rows), 1, data["files"])
        path = os.path.join(project.store_dir(), key, "files", str(rows[0][0]),
                            *rows[0][1].split("/"))
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        settled = next(line.split("\t")[1] for line in lines
                       if line[:1].isdigit() and int(float(line.split("\t")[0])) == 11)
        forged = []
        for line in lines:
            cols = line.split("\t")
            if line[:1].isdigit() and int(float(cols[0])) > 11:
                cols[1] = settled
            forged.append("\t".join(cols))
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(forged) + "\n")
        rows[0][2] = gates_mod._digest_file(path)
        with open(manifest, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        for name in os.listdir(project.verdicts("aero.converged")):
            if not name.startswith("control-"):
                os.remove(os.path.join(project.verdicts("aero.converged"), name))
        served = project.check("--only", "aero.converged", code=None)
        self.assertRegex(served.stdout, r"(?m)^\[ok  \] aero\.converged : .*reused",
                         served.stdout[-3000:])
        self.assertEqual(project.calls()["simpleFoam"], 0, "the check solved the planted run")
        for args in (["--dry-run"], []):
            with self.subTest(args=args):
                proc = project.run("export", self.MILESTONE, *args, "--json", code=1)
                self.assertGreater(project.calls()["simpleFoam"], 0)
                doc = json.loads(proc.stdout)
                self.assertIn(("unresolved", claim),
                              [(r.get("kind"), r.get("subject")) for r in doc["refusals"]],
                              proc.stdout[-3000:])
                self.assertFalse(doc["written"])


if __name__ == "__main__":
    unittest.main()
