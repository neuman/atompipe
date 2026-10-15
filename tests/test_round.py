# SPDX-License-Identifier: Apache-2.0
"""The round record, `.nopekit/round.json`, and `nopekit round` (SPEC 18, 24).

Only `round` writes the record, and only when what it holds moved (invariant 8);
nothing reads it for truth (invariants 8 and 12); what it holds is what the
composition says (invariant 12); a record the project has moved past says so
(invariant 7); its bytes are the same on every path and under any hash seed;
and `round` never blocks — it is the Stop hook's future body.

What slipped through in the design this replaced: a tracked summary `check`
rewrote would have made every check a tracked write, and one a reader trusted
would have been a second producer of every status (S-41: the committed
readiness report had drifted from its ledger).

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_round.py'
"""
from __future__ import annotations

import ast
import contextlib
import functools
import io
import json
import os
import re
import tempfile
import unittest
from typing import Any
from unittest import mock

import _env
import _projects
from nopekit import claims as claims_mod
from nopekit import cli, graph, report as report_mod, rounds, util
from nopekit.models import ClaimStatus

NOW = "2026-10-15T00:00:00Z"

#: The round the bracket's committed record holds: it moves each time the
#: bracket's cache is regenerated (architecture phase 5 wrote round 2), so the
#: tests read it rather than repeat it.
with open(os.path.join(_projects.BRACKET, ".nopekit", "round.json"), encoding="utf-8") as _fh:
    R = json.load(_fh)["round"]
SRC = os.path.join(_env.REPO, "src", "nopekit")


def main(root: str, *argv: str) -> tuple[int, str, str]:
    """``nopekit <argv>`` in process against ``root``: (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["-C", root, *argv])
    return code, out.getvalue(), err.getvalue()


def record_path(root: str) -> str:
    return os.path.join(root, *rounds.ROUND_REL.split("/"))


def stamp(root: str) -> tuple[bytes, int, int] | None:
    """The round record's bytes, mtime and inode — a rewrite of equal bytes is
    still a write."""
    path = record_path(root)
    if not os.path.isfile(path):
        return None
    st = os.stat(path)
    with open(path, "rb") as fh:
        return fh.read(), st.st_mtime_ns, st.st_ino


def bracket(dest: str) -> str:
    return _projects.bracket_copy(dest, migrated=True)


def _edit_json(path: str, **changes: Any) -> None:
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    data.update(changes)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def resolved(root: str):
    ledger = cli._load(root)
    registry, _ = cli._registry(root, ledger)
    model, projection, error = cli._projection_safe(root, ledger)
    view, resolution = cli._resolved(root, ledger, registry, projection, error, now=NOW,
                                     model=model)
    return ledger, registry, model, projection, view, resolution


def round_state(root: str) -> rounds.RoundState:
    ledger, registry, model, projection, view, resolution = resolved(root)
    return cli._round_state(root, ledger, model, projection, resolution, registry, view)


# --------------------------------------------------------------------------- #
#: The commands that read or sweep and must never write the round record: each
#: `check` spelling, the readers, and the site. `round` is the one writer.
_NOT_ROUND = (("check",), ("check", "--force"), ("check", "--only", "bracket.deflection"),
              ("check", "--json"), ("check", "--no-record"), ("status",), ("status", "--json"),
              ("report",), ("why", "C1"), ("why", "deflection"), ("doctor",), ("inputs",),
              ("site", "init"), ("site", "build"))


def untouched_problems(root: str, runs: Any) -> list[str]:
    """Each command in ``runs`` (argv tuples, or callables) that left the round
    record other than it found it — bytes, mtime or inode."""
    problems = []
    for argv in runs:
        before = stamp(root)
        if callable(argv):
            argv()
            name = getattr(argv, "__name__", "callable")
        else:
            main(root, *argv)
            name = " ".join(argv)
        if stamp(root) != before:
            problems.append(f"`{name}` wrote {rounds.ROUND_REL}")
    return problems


class OnlyRoundWritesTheRoundRecord(_env.EnvCase):
    """Invariant 8: only `round` writes `.nopekit/round.json`, at most once a run,
    and only when what it holds moved."""

    def test_no_other_command_writes_it(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        self.assertIsNotNone(stamp(root), "the bracket commits a round record")
        self.assertEqual(untouched_problems(root, _NOT_ROUND), [])
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith(f"round {R} stands: nothing it records moved."), out)

    def test_round_writes_the_next_round_and_names_the_flip(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        _edit_json(os.path.join(root, "claims", "C1.json"),
                   acceptance={"quantity": "tip deflection", "comparator": "<=",
                               "limit": 0.8, "units": "mm"})
        before = stamp(root)
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertNotEqual(stamp(root), before)
        self.assertTrue(out.startswith(f"round {R + 1}: C1 failing -> checked"), out)
        self.assertIn("Wrote .nopekit/round.json.", out)
        with open(record_path(root), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual((doc["round"], doc["claims"]["C1"]), (R + 1, "checked"))

    def test_a_check_that_writes_it_is_caught(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        _edit_json(os.path.join(root, "claims", "C7.json"), rationale="edited by hand")
        real = cli._check_run

        def writes_it(root_, ledger, **kw):
            ran = real(root_, ledger, **kw)
            body, _now = cli._round_inputs(root_, cli._load(root_), ran.registry, ran.model,
                                           ran.projection, ran.view, ran.resolution)
            rounds.write(root_, body)
            return ran

        with mock.patch.object(cli, "_check_run", writes_it):
            problems = untouched_problems(root, [("check",)])
        self.assertEqual(problems, [f"`check` wrote {rounds.ROUND_REL}"])


# --------------------------------------------------------------------------- #
def _uses(tree: ast.AST) -> list[tuple[str, str, int]]:
    """``(top-level function, attribute, line)`` for every ``rounds.<x>`` — a
    call, or a name read (``rounds.ROUND_REL``) — ``<module>`` outside any
    function."""
    found = []

    def visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            here = owner
            if owner == "<module>" and isinstance(child, (ast.FunctionDef,
                                                          ast.AsyncFunctionDef)):
                here = child.name
            if isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name) \
                    and child.value.id == "rounds":
                found.append((here, child.attr, child.lineno))
            visit(child, here)

    visit(tree, "<module>")
    return found


#: What reaches the record's bytes: asking `rounds` about it, or holding its
#: path. Only `cmd_round` (which writes it and says where), `_round_state`
#: (`status` and `doctor`'s one question) and `build_parser` (the help names
#: the file) may. What slipped through (review of phase 3a): only `read` and
#: `state` calls were held, so a reader that opened `rounds.path_of(root)` or
#: joined `rounds.ROUND_REL` itself passed.
_RECORD_ACCESS = frozenset({"read", "state", "write", "path_of", "ROUND_REL", "ROUND_NAME"})
_RECORD_ACCESS_ALLOWED = frozenset({("cli", "cmd_round"), ("cli", "_round_state"),
                                    ("cli", "build_parser")})


def round_reader_problems(sources: dict[str, str]) -> list[str]:
    """Every way a module under ``sources`` (``{module name: source}``) could read
    the round record for truth: naming its file (only `rounds` may), importing
    `rounds` (only `cli` may) or a name from it (none may: the attribute is what
    is held), or reaching the record (`_RECORD_ACCESS`) from anywhere but
    `_RECORD_ACCESS_ALLOWED`."""
    problems = []
    for name, source in sorted(sources.items()):
        problems += _module_problems(name, source)
    return problems


@functools.lru_cache(maxsize=None)
def _module_problems(name: str, source: str) -> tuple[str, ...]:
    """`round_reader_problems` of one module, cached by its source: the planted
    row re-reads only the modules it plants into."""
    problems: list[str] = []
    tree = ast.parse(source)
    if name != "rounds":
        # A docstring may say where the record lives; a value may not.
        prose = {id(n.value) for n in ast.walk(tree)
                 if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in prose and "round.json" in node.value:
                problems.append(f"{name}:{node.lineno}: names round.json")
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imports |= {alias.name for alias in node.names}
            if (node.module or "").endswith("rounds"):
                imports.add("rounds")
                if name != "rounds":
                    problems.append(f"{name}:{node.lineno}: imports "
                                    f"{', '.join(a.name for a in node.names)} from rounds")
        elif isinstance(node, ast.Import):
            imports |= {alias.name.rsplit(".", 1)[-1] for alias in node.names}
    if "rounds" in imports and name not in ("cli", "rounds"):
        problems.append(f"{name}: imports rounds")
    for func, attr, line in _uses(tree):
        if attr in _RECORD_ACCESS and (name, func) not in _RECORD_ACCESS_ALLOWED:
            problems.append(f"{name}:{line}: {func} reaches rounds.{attr}")
    return tuple(problems)


def _sources() -> dict[str, str]:
    out = {}
    for entry in sorted(os.listdir(SRC)):
        if entry.endswith(".py"):
            with open(os.path.join(SRC, entry), encoding="utf-8") as fh:
                out[entry[:-3]] = fh.read()
    return out


def _clockless(doc: Any) -> Any:
    """``doc`` without the build's clock (``built``) and each verdict's age."""
    if isinstance(doc, dict):
        return {k: _clockless(v) for k, v in doc.items() if k not in ("built", "age_s")}
    if isinstance(doc, list):
        return [_clockless(v) for v in doc]
    return doc


def forge(root: str) -> None:
    """A round record every claim of which reads checked, ready, and resealed —
    so it reads current: the forgery a reader that trusted it would believe."""
    with open(record_path(root), encoding="utf-8") as fh:
        doc = json.load(fh)
    doc["claims"] = {cid: "checked" for cid in doc["claims"]}
    doc["requirements"] = {rid: "checked" for rid in doc["requirements"]}
    doc["readiness"] = "ready"
    doc["milestones"] = {m: "ready" for m in doc["milestones"]}
    doc["self"] = rounds.self_digest(doc)
    with open(record_path(root), "wb") as fh:
        fh.write(rounds.render(doc))


class NothingReadsTheRoundRecordForTruth(_env.EnvCase):
    """Invariants 8 and 12: the record is an output. No module but `rounds` names
    its file, none but `cli` imports `rounds`, only `cmd_round` and
    `_round_state` ask it anything — and a forged record, resealed so it reads
    current, moves no status, no count, no readiness and no exit code."""

    def test_the_spine_reads_it_nowhere(self):
        self.assertEqual(round_reader_problems(_sources()), [])

    def test_a_planted_reader_is_caught(self):
        sources = _sources()
        sources["claims"] += ("\n\ndef _peek(root):\n    from . import rounds\n"
                              "    return rounds.read(root)\n")
        sources["planted"] = "PATH = '.nopekit/round.json'\n"
        sources["cli"] += ("\n\ndef cmd_report_planted(args):\n"
                           "    return json.load(open(rounds.path_of(args.root)))['claims']\n"
                           "\n\ndef _joined(root):\n"
                           "    return json.load(open(os.path.join(root, rounds.ROUND_REL)))\n"
                           "\n\ndef _named(root):\n"
                           "    from .rounds import path_of\n    return path_of(root)\n")
        problems = round_reader_problems(sources)
        self.assertTrue(any(p.startswith("claims: imports rounds") for p in problems), problems)
        self.assertTrue(any("_peek reaches rounds.read" in p for p in problems), problems)
        self.assertTrue(any("cmd_report_planted reaches rounds.path_of" in p
                            for p in problems), problems)
        self.assertTrue(any("_joined reaches rounds.ROUND_REL" in p for p in problems),
                        problems)
        self.assertTrue(any("imports path_of from rounds" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("planted:1: names round.json") for p in problems),
                        problems)

    def test_a_forged_record_moves_nothing(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        ledger, registry, model, projection, view, resolution = resolved(root)

        def facts() -> tuple:
            _l, reg, _m, _p, view_, res = resolved(root)
            composed = claims_mod.compositions(view_, registry=reg,
                                               stale_gates=res.stale_gates)
            summary = claims_mod.summarise(view_, reg, stale_gates=res.stale_gates)
            text = report_mod.render_terminal(view_, reg, stale_gates=res.stale_gates)
            code, out, _err = main(root, "status", "--json")
            status = json.loads(out)
            status.pop("round")
            status.pop("last_check", None)
            return ({c: (str(x.status), x.errored) for c, x in composed.items()},
                    summary, text, status)

        def readers() -> dict:
            """What `report`, `claim list`, `why`, `gap` and `site build` say."""
            said = {}
            for argv in (("report",), ("report", "--json"), ("claim", "list", "--json"),
                         ("why", "C1"), ("gap", "--json")):
                code, out, err = main(root, *argv)
                said[" ".join(argv)] = (code, out)
            code, _out, err = main(root, "site", "build")
            self.assertEqual(code, 0, err)
            with open(os.path.join(root, "site", "data", "state.json"),
                      encoding="utf-8") as fh:
                said["site build"] = _clockless(json.load(fh))
            return said

        self.assertEqual(main(root, "site", "init")[0], 0)
        shown = readers()
        before = facts()
        forge(root)
        # Resealed, it reads as no hand edit — and still never as current: what
        # it records is not what `round` would write now (review of phase 3a).
        found = round_state(root)
        self.assertEqual((found.state, found.moved), ("behind", ("resolution",)))
        # `facts` before `readers`: the page `status` reports on is the one
        # built before the forgery, so its build time cannot move.
        self.assertEqual(facts(), before)
        self.assertEqual(readers(), shown)

    def test_check_and_export_ignore_a_forged_record(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        def junit_now() -> str:
            with open(os.path.join(root, report_mod.JUNIT_DEFAULT), encoding="utf-8") as fh:
                text = fh.read()
            # The clock and the run's durations are the run's, never the record's.
            return re.sub(r'="\d{4}-\d\d-\d\dT[^"]*Z"|(timestamp|time)="[^"]*"', "", text)

        before = _env.nopekit(["check", "--junit"], cwd=root)
        junit = junit_now()
        forge(root)
        after = _env.nopekit(["check", "--junit"], cwd=root)
        junit_after = junit_now()
        self.assertEqual((before.returncode, after.returncode), (1, 1))
        self.assertEqual(junit_after, junit)
        dry = _env.nopekit(["export", "print-v1", "--dry-run"], cwd=root)
        self.assertEqual(dry.returncode, 1, dry.stdout + dry.stderr)


# --------------------------------------------------------------------------- #
def round_status_problems(doc: dict, view: Any, composed: dict, summary: dict,
                          requirements: dict) -> list[str]:
    """Every token in ``doc`` (a round record, or `body`) that is not what its one
    producer says over ``view``: a claim's `STATUS_KEY` (or `errored`), a
    requirement's, the counts, readiness per milestone and for the project."""
    problems = []

    def token(status: Any, errored: bool) -> str:
        return "errored" if errored else claims_mod.STATUS_KEY[status]

    want = {cid: token(c.status, c.errored) for cid, c in composed.items()}
    if doc.get("claims") != want:
        problems.append(f"claims: {doc.get('claims')} != {want}")
    want = {rid: token(r.status, r.errored) for rid, r in requirements.items()}
    if doc.get("requirements") != want:
        problems.append(f"requirements: {doc.get('requirements')} != {want}")
    counts = dict(summary["counts"], errored=summary["errored"])
    if doc.get("counts") != counts:
        problems.append(f"counts: {doc.get('counts')} != {counts}")
    ready = "ready" if claims_mod.unresolved(view, composed).ready else "not-ready"
    if doc.get("readiness") != ready:
        problems.append(f"readiness: {doc.get('readiness')} != {ready}")
    for milestone in view.milestones:
        ready = "ready" if claims_mod.unresolved(view, composed, milestone).ready \
            else "not-ready"
        if (doc.get("milestones") or {}).get(milestone.id) != ready:
            problems.append(f"milestone {milestone.id}: != {ready}")
    return problems


class TheRoundRecordSaysWhatTheCompositionSays(_env.EnvCase):
    """Invariant 12: the round record says no more and no less than the
    composition — a crash as `errored`, Pending build and an unowned assumption
    as not ready, and a status the evidence contradicts in `disagree`, never a
    silent `checked`."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.mkdtemp(prefix="nopekit-round-")
        cls.addClassCleanup(_env._rmtree, tmp)
        cls.root = bracket(os.path.join(tmp, "b"))
        (cls.ledger, cls.registry, cls.model, cls.projection, cls.view,
         cls.resolution) = resolved(cls.root)

    def _facts(self, composed=None):
        res = self.resolution
        composed = composed or claims_mod.compositions(self.view, registry=self.registry,
                                                       stale_gates=res.stale_gates)
        summary = claims_mod.summarise(self.view, self.registry, stale_gates=res.stale_gates)
        cover = claims_mod.effective_gates(self.view, self.registry)
        return composed, summary, report_mod.requirement_statuses(self.view, composed, cover)

    def test_the_record_is_the_composition(self):
        body, _now = cli._round_inputs(self.root, self.ledger, self.registry, self.model,
                                       self.projection, self.view, self.resolution)
        composed, summary, requirements = self._facts()
        self.assertEqual(round_status_problems(body, self.view, composed, summary,
                                               requirements), [])
        self.assertEqual(body["readiness"], "not-ready")       # C5 pending build, C6 gap
        self.assertEqual(body["claims"]["C5"], "pending_build")
        self.assertEqual(body["disagree"], {"claims": [], "requirements": []})
        with open(record_path(self.root), encoding="utf-8") as fh:
            committed = json.load(fh)
        self.assertEqual(round_status_problems(committed, self.view, composed, summary,
                                               requirements), [])

    def test_a_crash_reads_errored(self):
        composed, _summary, _req = self._facts()
        crashed = dict(composed, C2=claims_mod.Composed(ClaimStatus.BLOCKED,
                                                         claims_mod.ClaimCause.ERRORED))
        found = graph.tokens(self.view, self.resolution, self.registry, composed=crashed)
        self.assertEqual(found.claims["C2"], "errored")
        self.assertEqual(found.requirements["R1"], "failing")

    def test_a_resolver_that_lies_is_caught(self):
        real = claims_mod.compose

        def lying(claim, *args, **kwargs):
            found = real(claim, *args, **kwargs)
            if claim.id == "C1":
                return claims_mod.Composed(ClaimStatus.PASS, claims_mod.ClaimCause.CHECKED)
            return found

        with mock.patch.object(claims_mod, "compose", lying):
            found = graph.tokens(self.view, self.resolution, self.registry)
        self.assertEqual(found.claims["C1"], "checked")
        self.assertIn("C1", found.disagree["claims"], found.disagree)
        body, _now = cli._round_inputs(self.root, self.ledger, self.registry, self.model,
                                       self.projection, self.view, self.resolution)
        body["claims"]["C1"] = "checked"
        composed, summary, requirements = self._facts()
        self.assertTrue(round_status_problems(body, self.view, composed, summary,
                                              requirements))


# --------------------------------------------------------------------------- #
#: Each edit after a round, and what the record must say moved.
def _edit_record(root: str) -> None:
    _edit_json(os.path.join(root, "claims", "C7.json"), rationale="edited after the round")


def _new_entry(root: str) -> None:
    folder = os.path.join(root, ".nopekit", "verdicts", "bracket.deflection")
    name = next(n for n in sorted(os.listdir(folder)) if not n.startswith("control-"))
    with open(os.path.join(folder, name), "rb") as fh:
        data = fh.read()
    with open(os.path.join(folder, "0000000000000000-00000000.json"), "wb") as fh:
        fh.write(data)


def _edit_model(root: str) -> None:
    path = os.path.join(root, "model", "bracket.py")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace("    bed_xy: float = 220.0", "    bed_xy: float = 250.0", 1))


_MOVES = ((_edit_record, ("records",)), (_new_entry, ("verdicts",)), (_edit_model, ("design",)))


def behind_problems(make: Any) -> list[str]:
    """Each edit in `_MOVES`, on a fresh copy ``make()`` returns, that the round
    record's state does not name as moved."""
    problems = []
    for edit, moved in _MOVES:
        root = make()
        if round_state(root).state != "current":
            problems.append(f"{edit.__name__}: the copy's record was not current to begin")
            continue
        edit(root)
        found = round_state(root)
        if (found.state, found.moved) != ("behind", moved):
            problems.append(f"{edit.__name__}: {found.state} {found.moved}, not behind {moved}")
    return problems


def doctor_round_row(root: str) -> dict:
    """`doctor --json`'s `round` row, in process."""
    code, out, err = main(root, "doctor", "--json")
    rows = [row for row in json.loads(out)["checks"] if row["check"] == "round"]
    if len(rows) != 1:
        raise AssertionError(f"doctor printed {len(rows)} round rows: {out}{err}")
    return rows[0]


class ABehindRoundRecordSaysSo(_env.EnvCase):
    """Invariant 7: a round record the project has moved past is never shown as
    current — `status` says what moved; a token edited by hand, a record that
    does not read, and one a newer nopekit wrote each say so, and `round` never
    rewrites the newer one."""

    def test_status_says_current_then_what_moved(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        code, out, err = main(root, "status")
        self.assertIn(f"round record: round {R}, current with the records, the verdict cache "
                      "and the design", out)
        _edit_record(root)
        code, out, err = main(root, "status")
        self.assertIn(f"round record: round {R}, behind the records — the records moved since "
                      "it was written; `nopekit round` writes the next", out)
        doc = json.loads(main(root, "status", "--json")[1])["round"]
        self.assertEqual(doc, {"state": "behind", "round": R, "moved": ["records"], "why": ""})

    def test_each_input_is_seen(self):
        self.assertEqual(behind_problems(lambda: bracket(os.path.join(self.tmp(), "b"))), [])

    def test_a_state_blind_to_the_cache_is_caught(self):
        real = rounds.state

        def blind(root, computed_now, content=None):
            held = (rounds.read(root).doc or {}).get("computed_from") or {}
            return real(root, dict(computed_now, verdicts=held.get("verdicts")))

        with mock.patch.object(rounds, "state", blind):
            problems = behind_problems(lambda: bracket(os.path.join(self.tmp(), "b")))
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("_new_entry: current"), problems)

    def test_edited_unreadable_and_newer(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        path = record_path(root)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace('"C1": "failing"', '"C1": "checked"'))
        self.assertEqual(round_state(root).state, "edited")
        self.assertIn(f"round record: round {R}, edited by hand — its digest does not match "
                      "what it holds", main(root, "status")[1])
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<<<<<<< HEAD\n" + text + "=======\n" + text + ">>>>>>> theirs\n")
        found = round_state(root)
        self.assertEqual(found.state, "unreadable")
        self.assertIn("round record: does not read (", main(root, "status")[1])
        # A schema bumped by hand, beside a forged token, is an edit: the seal
        # rule holds at every schema, so a record whose seal fails was never
        # written by any nopekit — and `round` writes it again. What slipped
        # through (review of phase 3a): `newer` was decided before the seal.
        doc = json.loads(text)
        doc["schema"] = 2
        doc["claims"]["C1"] = "checked"
        doc["readiness"] = "ready"
        with open(path, "wb") as fh:
            fh.write(rounds.render(doc))
        self.assertEqual(round_state(root).state, "edited")
        self.assertIn(f"round record: round {R}, edited by hand", main(root, "status")[1])
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith(f"round {R + 1}: the last round record was edited by hand"),
                        out)
        with open(path, encoding="utf-8") as fh:
            rewritten = json.load(fh)
        self.assertEqual((rewritten["schema"], rewritten["claims"]["C1"],
                          rewritten["readiness"]), (1, "failing", "not-ready"))
        # One a newer nopekit sealed reads newer, and is never rewritten.
        doc = json.loads(text)
        doc["schema"] = 2
        doc["self"] = rounds.self_digest(doc)
        newer = rounds.render(doc)
        with open(path, "wb") as fh:
            fh.write(newer)
        self.assertEqual(round_state(root).state, "newer")
        before = stamp(root)
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertEqual(stamp(root), before)
        self.assertIn("was written by a newer nopekit (schema 2)", out)

    def test_an_evaluator_edit_reads_behind(self):
        """A move none of the three digests covers — an evaluator's code — that
        moves the resolution reads behind, naming it, in `status` and
        `doctor`. What slipped through (review of phase 3a): after a gate-code
        edit `status` listed C2, C3 and C4 Stale beside "round 1, current"."""
        root = bracket(os.path.join(self.tmp(), "b"))
        with open(os.path.join(root, "gates", "structural.py"), "a", encoding="utf-8") as fh:
            fh.write("\n\ndef _added_after_the_round():\n    return None\n")
        found = round_state(root)
        self.assertEqual((found.state, found.moved), ("behind", ("resolution",)))
        out = main(root, "status")[1]
        self.assertIn(f"round record: round {R}, behind the records — the resolution (an "
                      "evaluator's code, its controls, a pack or a tool) moved since it was "
                      "written", out)
        row = doctor_round_row(root)
        self.assertEqual(row["status"], "warn", row)
        self.assertIn("the resolution (an evaluator's code", row["detail"])

    def test_doctor_says_what_status_says(self):
        """`doctor`'s `round` row: ok while current, a warning naming what moved
        once behind, and "edited by hand" over a hand edit — never a FAIL."""
        root = bracket(os.path.join(self.tmp(), "b"))
        row = doctor_round_row(root)
        self.assertEqual(row["status"], "ok", row)
        self.assertEqual(row["detail"], f"round {R}, current with the records, the verdict "
                                        "cache and the design")
        _edit_record(root)
        row = doctor_round_row(root)
        self.assertEqual(row["status"], "warn", row)
        self.assertIn(f"round {R}, behind the records — the records moved", row["detail"])
        path = record_path(root)
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text.replace('"C1": "failing"', '"C1": "checked"'))
        row = doctor_round_row(root)
        self.assertEqual(row["status"], "warn", row)
        self.assertIn(f"round {R}, edited by hand", row["detail"])


# --------------------------------------------------------------------------- #
class TheRoundRecordIsByteStable(_env.EnvCase):
    """The same records, cache and design give the same round record, wherever
    the project lives, whatever the words say, under any hash seed; a second
    round writes nothing; and the record is tracked, never ignored."""

    def _fresh_round(self, root: str) -> bytes:
        os.remove(record_path(root))
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err + out)
        with open(record_path(root), "rb") as fh:
            return fh.read()

    def test_two_paths_and_any_words_give_the_same_bytes(self):
        one = self._fresh_round(bracket(os.path.join(self.tmp(), "b")))
        two_root = bracket(os.path.join(self.tmp(), "elsewhere", "deeper", "b"))
        import test_vocabulary
        with mock.patch.object(report_mod, "HUMAN", test_vocabulary.sentinel_human()):
            two = self._fresh_round(two_root)
        self.assertEqual(one, two)
        before = stamp(two_root)
        self.assertEqual(main(two_root, "round")[0], 0)
        self.assertEqual(stamp(two_root), before, "a second round rewrote the record")
        for word in ("checked", "failing"):
            self.assertIn(f'"{word}"', one.decode("utf-8"))
        self.assertNotIn("Tip sags", one.decode("utf-8"))

    def test_it_is_tracked_in_an_init_project(self):
        root = self.tmp()
        self.assertEqual(_env.git(["init", "-q"], cwd=root).returncode, 0)
        self.assertEqual(main(root, "init")[0], 0)
        proc = _env.git(["check-ignore", "-q", rounds.ROUND_REL], cwd=root)
        self.assertEqual(proc.returncode, 1, "the round record is ignored in a new project")

    def test_two_hash_seeds_give_the_same_bytes(self):
        outs = []
        for seed in ("0", "4242"):
            root = bracket(os.path.join(self.tmp(), f"s{seed}"))
            os.remove(record_path(root))
            proc = _env.nopekit(["round"], cwd=root, env={"PYTHONHASHSEED": seed})
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with open(record_path(root), "rb") as fh:
                outs.append(fh.read())
        self.assertEqual(outs[0], outs[1])


# --------------------------------------------------------------------------- #
def round_escape_problems(source: str) -> list[str]:
    """Whether `cmd_round` in ``source`` lets a `NopekitError` escape: its locked
    work must sit inside a `try` that catches `NopekitError`."""
    tree = ast.parse(source)
    func = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                 and n.name == "cmd_round"), None)
    if func is None:
        return ["no cmd_round"]
    for node in ast.walk(func):
        if not isinstance(node, ast.Try):
            continue
        caught = {getattr(h.type, "id", None) for h in node.handlers}
        locked = any(isinstance(s, ast.With) and "_lock" in ast.dump(s) for s in node.body)
        if "NopekitError" in caught and locked:
            return []
    return ["cmd_round's locked work is not inside a try that catches NopekitError"]


class RoundNeverBlocks(_env.EnvCase):
    """`round` is the Stop hook's future body, and a hook's exit 2 blocks the
    turn: it exits 0 whatever the project says, and 1 only on a crash."""

    def test_a_failing_claim(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertIn("1 failing", out)

    def test_a_held_lock_writes_nothing(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        lock = os.path.join(root, ".nopekit", cli.LOCK_NAME)
        with open(lock, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getppid(), "host": util._HOST, "when": NOW,
                       "command": "nopekit check"}, fh)
        _edit_record(root)
        before = stamp(root)
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("round not run: "), out)
        self.assertEqual(stamp(root), before)

    def test_a_model_that_does_not_load(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        self.assertEqual(main(root, "site", "init")[0], 0)
        self.assertEqual(main(root, "site", "build")[0], 0)
        state_json = os.path.join(root, "site", "data", "state.json")
        with open(state_json, "rb") as fh:
            page = fh.read()
        with open(os.path.join(root, "model", "bracket.py"), "a", encoding="utf-8") as fh:
            fh.write("\nthis is not python\n")
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertIn("Tier-0 check not run: ", out)
        self.assertIn("Wrote .nopekit/round.json.", out)
        # No page over a model `site build` refuses (review of phase 3a).
        self.assertIn(" Site not built: ", out)
        self.assertNotIn("Site built", out)
        with open(state_json, "rb") as fh:
            self.assertEqual(fh.read(), page, "round rebuilt the page over a broken model")
        with open(record_path(root), encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["computed_from"]["design"], "")

    def test_a_pack_that_does_not_import_writes_no_record(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        with open(os.path.join(root, "gates", "zz_broken.py"), "w", encoding="utf-8") as fh:
            fh.write("raise RuntimeError('this gate module does not import')\n")
        before = stamp(root)
        code, out, err = main(root, "round")
        self.assertEqual(code, 0, err)
        self.assertTrue(out.startswith("round not run: "), out)
        self.assertEqual(stamp(root), before)

    def test_outside_a_project(self):
        code, out, err = main(self.tmp(), "round")
        self.assertEqual(code, 0, err)
        self.assertEqual(out.strip(), "round: no nopekit project here — nothing to record.")

    def test_no_refusal_escapes(self):
        with open(os.path.join(SRC, "cli.py"), encoding="utf-8") as fh:
            source = fh.read()
        self.assertEqual(round_escape_problems(source), [])
        planted = ("def cmd_round(args):\n    root = 1\n    with _lock(root):\n"
                   "        return 0\n")
        self.assertTrue(round_escape_problems(planted))


# --------------------------------------------------------------------------- #
def _changes(claims=(), requirements=(), verdicts=(), instructions=(), moved=()):
    return rounds.Changes(True, "", tuple(claims), tuple(requirements), tuple(verdicts),
                          tuple(instructions), None, tuple(moved))


class RoundSummary(_env.EnvCase):
    """`round`'s one paragraph, word for word, and its `--json`."""

    @classmethod
    def setUpClass(cls) -> None:
        tmp = tempfile.mkdtemp(prefix="nopekit-round-")
        cls.addClassCleanup(_env._rmtree, tmp)
        cls.root = bracket(os.path.join(tmp, "b"))
        _l, cls.registry, _m, _p, cls.view, res = resolved(cls.root)
        cls.composed = claims_mod.compositions(cls.view, registry=cls.registry,
                                               stale_gates=res.stale_gates)

    def _say(self, shape, changes, **kw):
        kw.setdefault("check", {"ran": True, "executed": 0, "cached": 6})
        kw.setdefault("site", {"present": False})
        kw.setdefault("wrote", shape != "unchanged")
        return report_mod.round_paragraph(shape, kw.pop("number", 2), changes, view=self.view,
                                          composed=self.composed, schema=1,
                                          path=rounds.ROUND_REL, **kw)

    def test_the_sentences(self):
        flips = [rounds.Flip("C1", "failing", "checked"), rounds.Flip("C8", None, "gap"),
                 rounds.Flip("C7", "gap", None)]
        said = self._say("written", _changes(claims=flips, verdicts=["bracket.deflection"]))
        self.assertEqual(said, "round 2: C1 failing -> checked, C8 new (gap), C7 gone (was "
                               "gap); 1 new verdict (bracket.deflection). 7 claims · 3 checked "
                               "· 1 failing · 2 gaps · 1 pending build. NOT ready, as last "
                               "evaluated: 4 of 7 required claims are unresolved. Tier-0 "
                               "check: 0 run, 6 from the cache. Wrote .nopekit/round.json.")
        said = self._say("unchanged", _changes(), number=3)
        self.assertTrue(said.startswith("round 3 stands: nothing it records moved. "), said)
        self.assertFalse(said.endswith("Wrote .nopekit/round.json."), said)
        said = self._say("written", _changes(moved=["records", "design"]))
        self.assertTrue(said.startswith("round 2: no status moved (the records and the "
                                        "design moved). "), said)
        said = self._say("first", _changes(), number=1,
                         site={"present": True, "built": True, "warnings": 2})
        self.assertIn("round 1: the first round record.", said)
        self.assertIn(" Site built with 2 warnings — `nopekit site build` lists them.", said)
        said = self._say("replaced", rounds.Changes(False, "edited", (), (), (), (), None, ()),
                         check={"ran": False, "why": "the model does not load."})
        self.assertIn("round 2: the last round record was edited by hand, so nothing is "
                      "compared.", said)
        self.assertIn("Tier-0 check not run: the model does not load.", said)

    def test_the_caps_and_a_crash(self):
        flips = [rounds.Flip(f"C{i}", "checked", "failing") for i in range(1, 11)]
        flips[0] = rounds.Flip("C1", "checked", "errored")
        said = self._say("written", _changes(claims=flips,
                                             verdicts=[f"g.{i}" for i in range(6)]))
        self.assertIn("C1 checked -> skipped, errored", said)
        self.assertIn("C8 checked -> failing, and 2 more;", said)
        self.assertNotIn("C9 checked", said)
        self.assertIn("6 new verdicts (g.0, g.1, g.2, g.3, +2 more)", said)

    def test_the_json(self):
        root = bracket(os.path.join(self.tmp(), "b"))
        code, out, err = main(root, "round", "--json")
        self.assertEqual(code, 0, err)
        doc = json.loads(out)
        self.assertEqual(set(doc), {"round", "written", "path", "previous", "changes",
                                    "counts", "readiness", "check", "site", "summary"})
        self.assertEqual((doc["round"], doc["written"], doc["path"]),
                         (R, False, rounds.ROUND_REL))
        self.assertEqual(set(doc["changes"]), {"compared", "replaced", "claims", "requirements",
                                               "verdicts", "instructions",
                                               "instructions_unrecorded", "readiness",
                                               "moved"})
        self.assertTrue(doc["summary"].startswith(f"round {R} stands"), doc["summary"])

    def test_what_changed_end_to_end(self):
        """`changes()` over a real run: a claim's flip and its requirement's, the
        verdict its re-keyed evaluator filed, a readiness change, and the
        instruction file a model edit moved — in `--json` and in the paragraph.
        What slipped through (review of phase 3a): only the paragraph's first
        flip was held, so `changes()` could drop requirements, new verdicts,
        instructions or readiness and every test stayed green."""
        root = bracket(os.path.join(self.tmp(), "b"))
        path = record_path(root)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        # The last round said ready, sealed as `round` seals it: this round
        # must say readiness moved.
        doc["readiness"] = "ready"
        with open(path, "wb") as fh:
            fh.write(rounds.render(rounds.sealed(doc, 1)))
        _edit_json(os.path.join(root, "claims", "C1.json"),
                   acceptance={"quantity": "tip deflection", "comparator": "<=",
                               "limit": 0.8, "units": "mm"})
        code, out, err = main(root, "round", "--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        changes = found["changes"]
        self.assertIn({"id": "C1", "from": "failing", "to": "checked"}, changes["claims"])
        self.assertIn("R1", {f["id"] for f in changes["requirements"]}, changes)
        r1 = next(f for f in changes["requirements"] if f["id"] == "R1")
        self.assertEqual(r1["from"], "failing", changes)
        self.assertNotEqual(r1["to"], "failing", changes)
        self.assertIn("bracket.deflection", changes["verdicts"])
        self.assertEqual(changes["readiness"], {"from": "ready", "to": "not-ready"})
        self.assertEqual((changes["instructions"], changes["instructions_unrecorded"]),
                         ([], False))
        summary = found["summary"]
        self.assertIn("C1 failing -> checked", summary)
        self.assertIn(f"R1 failing -> {report_mod.status_token_word(r1['to'])}", summary)
        self.assertRegex(summary, r"\d+ new verdicts? \([^)]*bracket\.deflection")
        self.assertNotIn("instructions", summary)
        # A model edit moves its file.
        _edit_model(root)
        code, out, err = main(root, "round", "--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        self.assertEqual(found["changes"]["instructions"], ["instruction:model/bracket.py"])
        self.assertIn("instructions moved (model/bracket.py)", found["summary"])

    def test_a_model_that_stops_loading_moved_no_instruction(self):
        """A model that stops loading records no instruction node; that is not
        every file moving. What slipped through (review of phase 3a): the
        paragraph said "instructions moved (model/bracket.py)" for a model
        whose bytes had not changed — a third-party import missing here."""
        root = bracket(os.path.join(self.tmp(), "b"))
        with open(os.path.join(root, "model", "bracket.py"), encoding="utf-8") as fh:
            text = fh.read()
        with mock.patch.object(cli, "_projection_safe",
                               lambda root_, ledger: (None, None, "no module named 'planted'")):
            code, out, err = main(root, "round", "--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        with open(os.path.join(root, "model", "bracket.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), text)
        self.assertEqual(found["changes"]["instructions"], [])
        self.assertTrue(found["changes"]["instructions_unrecorded"])
        self.assertIn("instructions not recorded (the model does not load)", found["summary"])
        self.assertNotIn("instructions moved", found["summary"])


# --------------------------------------------------------------------------- #
_COSTLIER_GATE = '''\
# SPDX-License-Identifier: Apache-2.0
"""Planted by tests/test_round.py: an evaluator a tier-0 round must never run."""
from nopekit.gates import gate
from nopekit.models import NegativeControl, Tier, Verdict


@gate(id="bracket.costlier", title="a tier-1 evaluator", claims=["costlier"],
      tier=Tier.BUILD,
      negative_control=NegativeControl(fixture="selftest/bad_configs.py:quarter_thickness",
                                       note="planted"))
def costlier(ctx):
    """The tip deflection against C1's limit, as a slower build would."""
    value = float(ctx.params["deflection"])
    return Verdict(gate="bracket.costlier", passed=value <= 0.5, measured=value,
                   limit=0.5, units="mm")
'''


class RoundRunsTierZero(_env.EnvCase):
    """`round` runs a tier-0 check exactly as `check --tier 0` does: a costlier
    evaluator is neither run nor filed, and the counts are the same. What
    slipped through (review of phase 3a): every bracket gate is tier 0, so a
    round that ran every tier — FEA on every turn, once it is the Stop hook —
    passed every test."""

    def _project(self) -> str:
        root = bracket(os.path.join(self.tmp(), "b"))
        with open(os.path.join(root, "gates", "zz_costlier.py"), "w",
                  encoding="utf-8") as fh:
            fh.write(_COSTLIER_GATE)
        return root

    def _filed(self, root: str) -> list[str]:
        folder = os.path.join(root, ".nopekit", "verdicts", "bracket.costlier")
        return sorted(os.listdir(folder)) if os.path.isdir(folder) else []

    def test_round_never_runs_a_costlier_evaluator(self):
        root = self._project()
        code, out, err = main(root, "round", "--json")
        self.assertEqual(code, 0, err)
        found = json.loads(out)
        self.assertTrue(found["check"]["ran"], found)
        self.assertEqual(self._filed(root), [])
        twin = self._project()
        code, out, err = main(twin, "check", "--tier", "0", "--json")
        self.assertIn(code, (0, 1), err)
        self.assertEqual(self._filed(twin), [])
        checked = json.loads(out)
        counts = checked.get("counts") or checked.get("summary", {}).get("counts") or {}
        self.assertEqual((found["check"]["executed"], found["check"]["cached"]),
                         (int(counts.get("executed", 0)), int(counts.get("cached", 0))),
                         (found["check"], counts))
        # The control: a check that runs every tier files the costlier entry.
        code, _out, err = main(twin, "check", "--tier", "1")
        self.assertIn(code, (0, 1), err)
        self.assertTrue(self._filed(twin), "the planted tier-1 evaluator never ran at tier 1")


if __name__ == "__main__":
    unittest.main()
