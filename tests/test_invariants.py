# SPDX-License-Identifier: Apache-2.0
"""The honesty invariants.

These are not ordinary unit tests. Everything atompipe claims rests on four
properties, and if any of them breaks the tool becomes a machine for laundering
assumption into apparent proof — which is strictly worse than having no tool.

    (a) a SKIPPED gate is never reported as a pass
    (b) an ERRORED gate is never reported as a pass
    (c) the registry refuses a gate with no negative control
    (d) the readiness report never lists an unrun or skipped gate under PROVEN

Each test below tries to VIOLATE one of them. Run with:

    PYTHONPATH=src python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import unittest

from atompipe import claims as claims_mod
from atompipe import gates as gates_mod
from atompipe import report as report_mod
from atompipe.models import (
    Acceptance, Claim, ClaimKind, ClaimStatus, Comparator, GateSpec, Ledger,
    NegativeControl, PhysicalResult, ProjectMeta, Tier, Verdict,
)


def _claim(cid="C1", kind=ClaimKind.MEASURABLE, **kw):
    return Claim(
        id=cid,
        statement=kw.pop("statement", "the thing holds"),
        kind=kind,
        acceptance=kw.pop("acceptance", Acceptance(
            quantity="deflection", comparator=Comparator.LE, limit=0.5, units="mm")),
        gates=kw.pop("gates", ["g.one"]),
        **kw,
    )


def _ledger(*claims_, verdicts=()):
    return Ledger(
        meta=ProjectMeta(name="t", revision="v0.1"),
        claims=list(claims_),
        verdicts=list(verdicts),
    )


class _Reg:
    """Minimal registry stand-in: report/claims only ever read specs off it."""

    def __init__(self, specs=()):
        self._specs = list(specs)

    def specs(self):
        return list(self._specs)

    def for_claim(self, claim_id, tags=()):
        out = []
        for s in self._specs:
            names = set(s.claims or [])
            if claim_id in names or (set(tags or ()) & names):
                out.append(s)
        return out

    def get(self, gid):
        for s in self._specs:
            if s.id == gid:
                return s, (lambda ctx: Verdict(gate=gid, passed=True))
        return None


SPEC = GateSpec(id="g.one", claims=["C1"], tier=Tier.INSTANT,
                negative_control=NegativeControl(fixture="x:y"))


# --------------------------------------------------------------------------- #
class SkipIsNotPass(unittest.TestCase):
    """(a) A gate whose tool is missing has proven nothing."""

    def test_verdict_ok_is_false_when_skipped(self):
        v = Verdict(gate="g.one", passed=True, skipped=True,
                    skip_reason="requires openfoam (not on PATH)")
        self.assertFalse(v.ok, "a skipped verdict must never read as ok, even if "
                               "passed=True was set")

    def test_claim_with_only_skipped_gates_is_blocked(self):
        v = Verdict(gate="g.one", claims=["C1"], passed=True, skipped=True,
                    skip_reason="requires openfoam (not on PATH)")
        st = claims_mod.resolve_status(_claim(), [v])
        self.assertEqual(st, ClaimStatus.BLOCKED)
        self.assertNotEqual(st, ClaimStatus.PASS)

    def test_skipped_gate_renders_as_skip(self):
        v = Verdict(gate="g.one", passed=True, skipped=True, skip_reason="no tool")
        self.assertIn("skip", v.render())
        self.assertNotIn("[ok", v.render())


class ErrorIsNotPass(unittest.TestCase):
    """(b) A gate that crashed has proven nothing. An error is not a failure either —
    a failure is a measurement, a crash is an absence of one."""

    def test_verdict_ok_is_false_when_errored(self):
        v = Verdict(gate="g.one", passed=True, error="ZeroDivisionError: ...")
        self.assertFalse(v.ok)

    def test_claim_with_errored_gate_does_not_pass(self):
        v = Verdict(gate="g.one", claims=["C1"], passed=True,
                    error="TypeError: unsupported operand")
        st = claims_mod.resolve_status(_claim(), [v])
        self.assertNotEqual(st, ClaimStatus.PASS)

    def test_crashing_gate_produces_error_verdict_not_a_pass(self):
        reg = gates_mod.Registry()

        @gates_mod.gate(id="g.boom", claims=["C1"], registry=reg,
                        negative_control=NegativeControl(fixture="x:y"))
        def boom(ctx):
            raise ZeroDivisionError("deliberate")

        spec, fn = reg.get("g.boom")
        ctx = gates_mod.GateContext(root=".", ledger=_ledger(_claim()), model=None,
                                    params={}, out_dir=".", tier=0,
                                    log=lambda m: None, extra={})
        v = gates_mod.run_gate(spec, fn, ctx)
        self.assertTrue(v.error, "a crashing gate must record the error")
        self.assertFalse(v.ok)
        self.assertFalse(v.passed)


class RegistryRefusesLoggers(unittest.TestCase):
    """(c) A gate that cannot demonstrate failure is a logger. Rule 5, mechanical."""

    def test_register_without_negative_control_raises(self):
        reg = gates_mod.Registry()
        with self.assertRaises(Exception) as cm:
            @gates_mod.gate(id="g.nocontrol", claims=["C1"], registry=reg)
            def nocontrol(ctx):
                return True
        msg = str(cm.exception).lower()
        self.assertIn("negative", msg,
                      "the refusal must say WHAT is missing, not just that something is")

    def test_register_with_negative_control_succeeds(self):
        reg = gates_mod.Registry()

        @gates_mod.gate(id="g.ok", claims=["C1"], registry=reg,
                        negative_control=NegativeControl(fixture="x:y"))
        def ok(ctx):
            return True

        self.assertIsNotNone(reg.get("g.ok"))

    def test_gate_cannot_lie_about_its_own_identity(self):
        """run_gate overwrites identity fields from the spec, so a gate returning a
        verdict naming a different gate cannot smuggle it into the ledger."""
        reg = gates_mod.Registry()

        @gates_mod.gate(id="g.honest", claims=["C1"], tier=Tier.SOLVE, registry=reg,
                        negative_control=NegativeControl(fixture="x:y"))
        def liar(ctx):
            return Verdict(gate="g.something_else", passed=True, tier=Tier.INSTANT,
                           claims=["C_other"])

        spec, fn = reg.get("g.honest")
        ctx = gates_mod.GateContext(root=".", ledger=_ledger(_claim()), model=None,
                                    params={}, out_dir=".", tier=0,
                                    log=lambda m: None, extra={})
        v = gates_mod.run_gate(spec, fn, ctx)
        self.assertEqual(v.gate, "g.honest")
        self.assertEqual(v.tier, Tier.SOLVE)
        self.assertEqual(v.claims, ["C1"])


class ReportNeverOverclaims(unittest.TestCase):
    """(d) The readiness report is the deliverable. It must refuse to call anything
    proven that was not."""

    def _render(self, ledger, reg):
        return report_mod.render_markdown(ledger, reg)

    @staticmethod
    def _proven_section(md):
        """Just the PROVEN section body — NOT the headline verdict.

        The headline legitimately names claims that are unproven (that is its job:
        to say what is outstanding). The invariant under test is narrower: nothing
        unproven may appear in the PROVEN table.
        """
        if "## What is PROVEN" not in md:
            return ""
        body = md.split("## What is PROVEN", 1)[1]
        return body.split("\n## ", 1)[0]

    def test_skipped_gate_is_not_in_proven_section(self):
        v = Verdict(gate="g.one", claims=["C1"], passed=True, skipped=True,
                    skip_reason="requires openfoam")
        md = self._render(_ledger(_claim(), verdicts=[v]), _Reg([SPEC]))
        self.assertNotIn("g.one", self._proven_section(md),
                         "a skipped gate appeared in the PROVEN section")

    def test_unrun_gate_is_not_in_proven_section(self):
        md = self._render(_ledger(_claim()), _Reg([SPEC]))
        self.assertNotIn("g.one", self._proven_section(md))

    def test_physical_claim_never_proven(self):
        c = _claim("C9", kind=ClaimKind.PHYSICAL, gates=[])
        self.assertEqual(claims_mod.resolve_status(c, []), ClaimStatus.UNVERIFIED)
        md = self._render(_ledger(c), _Reg([]))
        self.assertNotIn("C9", self._proven_section(md))

    def test_verdict_says_so_when_something_blocks(self):
        """The one-sentence verdict must lead with the problem, not bury it."""
        v = Verdict(gate="g.one", claims=["C1"], passed=False, detail="0.70 vs 0.50")
        md = self._render(_ledger(_claim(), verdicts=[v]), _Reg([SPEC]))
        head = md.split("## ")[0].lower()
        self.assertTrue(
            any(w in head for w in ("not ready", "fail", "block", "not verified",
                                    "gap", "outstanding", "unresolved", "never")),
            f"the headline verdict hid a failing critical claim: {head!r}")


class StatusPrecedence(unittest.TestCase):
    """The derivation table from SPINE_CONTRACT.md, exactly."""

    def test_assumption_is_asserted(self):
        c = _claim("C2", kind=ClaimKind.ASSUMPTION, gates=[])
        self.assertEqual(claims_mod.resolve_status(c, []), ClaimStatus.ASSERTED)

    def test_physical_with_result(self):
        c = _claim("C3", kind=ClaimKind.PHYSICAL, gates=[])
        c.physical_result = PhysicalResult(passed=True, when="2026-01-01")
        self.assertEqual(claims_mod.resolve_status(c, []), ClaimStatus.VERIFIED)
        c.physical_result = PhysicalResult(passed=False, when="2026-01-01")
        self.assertEqual(claims_mod.resolve_status(c, []), ClaimStatus.REFUTED)

    def test_no_covering_gate_is_unclaimed(self):
        self.assertEqual(
            claims_mod.resolve_status(_claim(gates=[]), []), ClaimStatus.UNCLAIMED)

    def test_gate_exists_but_never_ran_is_pending(self):
        self.assertEqual(claims_mod.resolve_status(_claim(), []), ClaimStatus.PENDING)

    def test_failure_beats_success(self):
        vs = [Verdict(gate="g.one", claims=["C1"], passed=True),
              Verdict(gate="g.two", claims=["C1"], passed=False)]
        c = _claim(gates=["g.one", "g.two"])
        self.assertEqual(claims_mod.resolve_status(c, vs), ClaimStatus.FAIL)

    def test_stale_is_not_pass(self):
        v = Verdict(gate="g.one", claims=["C1"], passed=True)
        self.assertEqual(
            claims_mod.resolve_status(_claim(), [v], stale=True), ClaimStatus.STALE)

    def test_clean_pass(self):
        v = Verdict(gate="g.one", claims=["C1"], passed=True)
        self.assertEqual(claims_mod.resolve_status(_claim(), [v]), ClaimStatus.PASS)

    def test_blocking_statuses_exclude_pass_and_verified(self):
        from atompipe.models import BLOCKING_STATUSES
        self.assertNotIn(ClaimStatus.PASS, BLOCKING_STATUSES)
        self.assertNotIn(ClaimStatus.VERIFIED, BLOCKING_STATUSES)
        self.assertIn(ClaimStatus.UNCLAIMED, BLOCKING_STATUSES)
        self.assertIn(ClaimStatus.BLOCKED, BLOCKING_STATUSES)
        self.assertIn(ClaimStatus.STALE, BLOCKING_STATUSES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
