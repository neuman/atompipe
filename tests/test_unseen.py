# SPDX-License-Identifier: Apache-2.0
"""Issue #15, D1 — "own word, keep stale": an evaluator nopekit cannot see into.

A solver's gate reads its inputs through subprocesses the tracer cannot see, so
its verdict entry is never Fresh outside the check run that ran it
(`verdicts.Unknown`, ``opaque inputs``). The author's decision: keep the claim
Stale and *ready* as the composition says, and give the case its own true cause
everywhere a reason is said.

What slipped through before it: right after `check` printed ``ready: every
required claim is checked``, `site build`, `status`, `report`, `doctor` and both
pages read the claims stale and NOT ready, and said "The design changed after the
result" of a design nobody had touched; `status` and `site build` printed ~2 KB
of channel paths each; and `check` said nothing to join its *ready* to theirs.

* ``UnseenMovesNoStatus`` (invariant 12) — the cause is the composition's and
  moves no status, no readiness and no blocking: a moved gate beside an unseen
  one leads, and the all-stale alias never reads unseen.
* ``TheResolverSaysWhichAreUnseen`` — `claims.unseen_gates` read off a REAL
  resolution, so a rewording of the resolver's ``opaque inputs`` turns it red.
* ``TheWordsAreTheirOwn`` — `reason`, the status lines, the report's failing
  section and the page's settle say the new words and never the old ones.
* ``TheCfdReadersSayIt`` — the whole loop on the stand-in OpenFOAM: `check`'s
  ready and its note, `status`, `report`, `site build`, `page.json` and `doctor`.
"""
from __future__ import annotations

import dataclasses
import json
import os
import unittest

import _env
import _projects
import test_cfd_openfoam as cfd_tests
import test_freshness as TF
import test_invariants as TI
from nopekit import claims as claims_mod
from nopekit import page as page_mod
from nopekit import report as report_mod
from nopekit.claims import ClaimCause, ClaimStatus
from nopekit.models import GateSpec, NegativeControl, Tier, Verdict

#: Words no reader may say of a claim Stale only for unseen inputs: the false
#: reason D1 removed, and the verdict word for a read set that moved.
OLD_WORDS = ("The design changed after the result", "invalidated",
             "older than the design")


def _spec(gid: str, tier: Tier = Tier.SOLVE) -> GateSpec:
    return GateSpec(id=gid, claims=["C1"], tier=tier,
                    negative_control=NegativeControl(fixture="x:y"))


def _one(*gates_: str, passed: bool = True):
    """C1, critical, covered by ``gates_``, each with a verdict."""
    claim = TI._claim("C1", gates=list(gates_), critical=True)
    verdicts = [Verdict(gate=g, claims=["C1"], passed=passed) for g in gates_]
    return TI._ledger(claim, verdicts=verdicts), TI._Reg([_spec(g) for g in gates_])


# --------------------------------------------------------------------------- #
class UnseenMovesNoStatus(unittest.TestCase):
    """(Invariant 12) `unseen` is a cause, never a status: the claim reads Stale
    with or without it, *ready* is the same predicate, and the claim blocks the
    same. What it must never become: a Fresh pass (the decision kept Stale), or a
    quieter word over a design that DID move."""

    def test_its_own_cause_beside_the_same_status(self):
        ledger, reg = _one("g.a")
        plain = claims_mod.compose(ledger.claims[0], ledger.verdicts, stale_gates={"g.a"})
        unseen = claims_mod.compose(ledger.claims[0], ledger.verdicts, stale_gates={"g.a"},
                                    unseen_gates={"g.a"})
        self.assertEqual((plain.status, plain.cause),
                         (ClaimStatus.STALE, ClaimCause.INVALIDATED))
        self.assertEqual((unseen.status, unseen.cause, unseen.cites),
                         (ClaimStatus.STALE, ClaimCause.UNSEEN, ("g.a",)))

    def test_ready_and_blocking_are_the_same(self):
        ledger, reg = _one("g.a")
        kw = {"stale_gates": {"g.a"}}
        plain = claims_mod.compositions(ledger, registry=reg, **kw)
        unseen = claims_mod.compositions(ledger, registry=reg, unseen_gates={"g.a"}, **kw)
        self.assertFalse(claims_mod.unresolved(ledger, plain).ready)
        self.assertEqual(claims_mod.unresolved(ledger, unseen),
                         claims_mod.unresolved(ledger, plain))
        self.assertTrue(claims_mod.blocks(unseen["C1"]), "an unseen Stale still stops check")
        self.assertEqual(claims_mod.blocking(ledger, reg, **kw)[0][1], ClaimStatus.STALE)

    def test_a_moved_gate_leads(self):
        """The design changing is the bigger fact: `invalidated`, citing it first."""
        ledger, _reg = _one("g.a", "g.b")
        found = claims_mod.compose(ledger.claims[0], ledger.verdicts,
                                   stale_gates={"g.a", "g.b"}, unseen_gates={"g.a"})
        self.assertEqual((found.status, found.cause, found.cites),
                         (ClaimStatus.STALE, ClaimCause.INVALIDATED, ("g.b", "g.a")))
        self.assertEqual(found.verdict.gate, "g.b")

    def test_the_all_stale_alias_is_never_unseen(self):
        ledger, _reg = _one("g.a")
        found = claims_mod.compose(ledger.claims[0], ledger.verdicts, stale=True,
                                   unseen_gates={"g.a"})
        self.assertEqual(found.cause, ClaimCause.INVALIDATED)

    def test_a_current_gate_is_never_made_stale(self):
        ledger, _reg = _one("g.a")
        found = claims_mod.compose(ledger.claims[0], ledger.verdicts, unseen_gates={"g.a"})
        self.assertEqual(found.status, ClaimStatus.PASS)

    def test_a_fail_stays_failing(self):
        ledger, _reg = _one("g.a", passed=False)
        found = claims_mod.compose(ledger.claims[0], ledger.verdicts, stale_gates={"g.a"},
                                   unseen_gates={"g.a"})
        self.assertEqual(found.status, ClaimStatus.FAIL)


# --------------------------------------------------------------------------- #
class _Row:
    def __init__(self, state, reason, opaque=()):
        self.state, self.stale_reason = state, reason
        self.entry = type("E", (), {"reads": {"opaque": list(opaque)}})()


class _Resolution:
    def __init__(self, rows):
        self.rows = rows
        self.stale_gates = frozenset(g for g, r in rows.items() if r.stale_reason)


class TheResolverSaysWhichAreUnseen(_env.EnvCase):
    """`claims.unseen_gates` against the resolver's own reasons."""

    def test_a_real_opaque_entry_is_unseen(self):
        """A REAL resolution: the spelling `claims.OPAQUE_REASON` copies is the
        resolver's, so a rewording there turns this red."""
        p = TF._Project(self)
        proj = TF._projection(tags={1, 2})
        p.record("t.opaque", proj)
        p.demonstrate("t.opaque", proj)
        p.record("t.defl", TF._PROJECTION)
        p.demonstrate("t.defl")
        resolution = p.resolve(proj)
        self.assertTrue(resolution.rows["t.opaque"].stale_reason.startswith(
            claims_mod.OPAQUE_REASON), resolution.rows["t.opaque"].stale_reason)
        self.assertEqual(claims_mod.unseen_gates(resolution), frozenset({"t.opaque"}))
        view = dataclasses.replace(p.ledger, verdicts=resolution.verdicts)
        found = claims_mod.compositions(view, registry=p.registry,
                                        stale_gates=resolution.stale_gates,
                                        unseen_gates=claims_mod.unseen_gates(resolution))
        self.assertEqual((found["C7"].status, found["C7"].cause),
                         (ClaimStatus.STALE, ClaimCause.UNSEEN))

    def test_a_model_that_does_not_load_is_not_unseen(self):
        p = TF._Project(self)
        p.record("t.defl", TF._PROJECTION)
        p.demonstrate("t.defl")
        resolution = p.resolve(None, model_error="SyntaxError: x")
        self.assertIn("t.defl", resolution.stale_gates)
        self.assertEqual(claims_mod.unseen_gates(resolution), frozenset())

    def test_only_the_resolvers_opaque_reason_on_an_unknown_row(self):
        op = claims_mod.OPAQUE_REASON
        resolution = _Resolution({
            "g.opaque": _Row("unknown", op + "subprocess:simpleFoam", ["subprocess:simpleFoam"]),
            "g.moved": _Row("stale", "config.load 10 -> 12"),
            "g.no-list": _Row("unknown", op + "subprocess:x"),
            "g.not-unknown": _Row("stale", op + "subprocess:x", ["subprocess:x"]),
            "g.dep": _Row("fresh", "prerequisite g.opaque invalidated: " + op + "subprocess:x"),
            "g.dep2": _Row("fresh", "prerequisite g.dep invalidated: prerequisite g.opaque "
                                    "invalidated: " + op + "subprocess:x"),
            "g.dep-moved": _Row("fresh", "prerequisite g.moved invalidated: config.load"),
            "g.current": _Row("fresh", ""),
        })
        self.assertEqual(claims_mod.unseen_gates(resolution),
                         frozenset({"g.opaque", "g.dep", "g.dep2"}))


# --------------------------------------------------------------------------- #
class TheWordsAreTheirOwn(unittest.TestCase):
    """Every reader's words for an unseen Stale: the new ones, never the old."""

    def setUp(self):
        self.ledger, self.reg = _one("g.a", "g.b")
        self.kw = {"stale_gates": frozenset({"g.a", "g.b"}),
                   "unseen_gates": frozenset({"g.a", "g.b"})}
        self.found = claims_mod.compositions(self.ledger, registry=self.reg, **self.kw)["C1"]

    def test_the_reason(self):
        for full in (False, True):
            text = report_mod.reason(self.found, self.ledger, self.ledger.claims[0], full=full,
                                     stale_reasons={"g.a": "opaque inputs: subprocess:x"})
            self.assertTrue(text.startswith("unseen inputs: g.a (+1 more)"), text)
            self.assertIn("only a check run can show", text)
            for old in OLD_WORDS:
                self.assertNotIn(old, text)

    def test_the_site_words(self):
        said = report_mod.HUMAN["site"]
        for text in (said["cause"]["unseen"], said["figure"]["unseen"],
                     said["notices"]["unseen"], said["notices"]["unseen_public"],
                     said["settle"]["unseen"]):
            for old in OLD_WORDS:
                self.assertNotIn(old, text)
        self.assertIn("cannot see", said["hint"]["stale"],
                      "the Stale hint is true of both of Stale's evaluator causes")
        done = page_mod.settle(self.ledger.claims[0], self.found, cover=["g.a", "g.b"],
                               tiers={"g.a": 2, "g.b": 1})
        self.assertEqual(done["commands"], ["nopekit check --tier 2"])
        self.assertIn("cannot see", done["text"])

    def test_the_status_lines(self):
        text = report_mod.render_terminal(self.ledger, self.reg, **self.kw)
        self.assertIn("gates: 2 ran, 2 with unseen inputs", text)
        self.assertIn("next: nopekit check --tier 2 ;", text)
        for old in OLD_WORDS:
            self.assertNotIn(old, text)
        plain = report_mod.render_terminal(self.ledger, self.reg,
                                           stale_gates=self.kw["stale_gates"])
        self.assertIn("2 invalidated", plain, "without the mark the old words stand")

    def test_the_failing_section(self):
        md = report_mod.render_markdown(self.ledger, self.reg, **self.kw)
        self.assertIn("Passed, but nopekit cannot see if the result is current", md)
        self.assertIn("Only a check run can show that it is current: "
                      "`nopekit check --tier 2`.", md)
        self.assertNotIn("not against the current inputs", md)
        self.assertNotIn("re-runs what moved", md)

    def test_invalidated_advice_carries_the_tier(self):
        """What slipped through (review of P2): `nopekit check` re-runs what
        moved — a tier-0 run that reaches no solver."""
        md = report_mod.render_markdown(self.ledger, self.reg,
                                        stale_gates=self.kw["stale_gates"])
        self.assertIn("`nopekit check --tier 2` re-runs what moved.", md)


# --------------------------------------------------------------------------- #
class TheCfdReadersSayIt(unittest.TestCase):
    """The loop on the stand-in OpenFOAM: `check --tier 2` says *ready* and, on
    the next line, that this ready is its own; every reader after it says
    Stale for unseen inputs, in a count and one example, with a command that
    reaches the solver."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        _inst, bin_ = cfd_tests.install_standin(os.path.join(cls.dir, "tool"))
        env = {"PATH": bin_ + os.pathsep + "/usr/bin:/bin"}
        cls.root = _projects.wrap_pack_baseline("cfd-openfoam", os.path.join(cls.dir, "proj"))
        run = lambda *argv: _env.nopekit(list(argv), cwd=cls.root, env=env,  # noqa: E731
                                          timeout=900)
        cls.check = run("check", "--tier", "2")
        cls.status = run("status")
        cls.status_json = run("status", "--json")
        cls.report = run("report")
        cls.init = run("site", "init")
        cls.build = run("site", "build")
        cls.doctor = run("doctor", "--json")
        with open(os.path.join(cls.root, "site", "data", "page.json"), encoding="utf-8") as fh:
            cls.page = json.load(fh)

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def test_check_says_its_ready_is_its_own(self):
        out = self.check.stdout
        self.assertEqual(self.check.returncode, 0, out[-2000:] + self.check.stderr[-2000:])
        lines = out.splitlines()
        at = lines.index("ready: every required claim is checked")
        self.assertTrue(lines[at + 1].startswith("note: this ready holds for this check run "
                                                 "only."), lines[at + 1])
        self.assertIn("read their claims stale", lines[at + 1])

    def test_status_says_unseen_in_a_count_and_one_example(self):
        out = self.status.stdout
        self.assertIn("unseen inputs:", out)
        self.assertIn("for example subprocess:", out)
        self.assertIn("next: nopekit check --tier 2 ;", out)
        for old in ("The design changed after the result", "invalidated:"):
            self.assertNotIn(old, out)
        self.assertNotIn("out:cfd-openfoam/", out, "the channel list is doctor's")
        self.assertLess(max(len(line) for line in out.splitlines()), 600)
        data = json.loads(self.status_json.stdout)
        causes = {row["cause"] for row in data["statuses"].values()
                  if row.get("key") == "stale"}
        self.assertEqual(causes, {"unseen"})
        self.assertFalse(data["summary"]["all_required_checked"],
                         "the decision keeps Stale: status is NOT ready")

    def test_the_report(self):
        out = self.report.stdout
        self.assertIn("Passed, but nopekit cannot see if the result is current", out)
        self.assertIn("`nopekit check --tier 2`", out)
        self.assertNotIn("The design changed after the result", out)

    def test_site_build_and_the_page(self):
        self.assertEqual(self.build.returncode, 0, self.build.stdout[-2000:]
                         + self.build.stderr[-2000:])
        last = self.build.stdout.splitlines()[-1]
        self.assertTrue(last.startswith("verdicts are STALE: "), last)
        self.assertIn("inputs that nopekit cannot see", last)
        self.assertTrue(last.endswith("`nopekit check --tier 2`"), last)
        self.assertNotIn("out:cfd-openfoam/", last)
        verdict = self.page["verdict"]
        self.assertEqual(verdict["notice"], report_mod.HUMAN["site"]["notices"]["unseen"]
                         .format(tier_flag=" --tier 2"))
        self.assertEqual(verdict["notice_public"],
                         report_mod.HUMAN["site"]["notices"]["unseen_public"])
        for cid, claim in self.page["claims"].items():
            with self.subTest(cid=cid):
                self.assertEqual((claim["token"], claim["cause"]), ("stale", "unseen"))
                self.assertEqual(claim["cause_text"],
                                 report_mod.HUMAN["site"]["cause"]["unseen"])
                self.assertEqual(claim["settle"]["commands"], ["nopekit check --tier 2"])

    def test_doctor_keeps_the_full_list(self):
        rows = {row["check"]: row for row in json.loads(self.doctor.stdout)["checks"]}
        row = rows["opaque-inputs"]
        self.assertEqual(row["status"], "warn")
        self.assertIn("inputs that nopekit cannot see", row["detail"])
        self.assertIn("subprocess:simpleFoam", row["detail"])


if __name__ == "__main__":
    unittest.main()
