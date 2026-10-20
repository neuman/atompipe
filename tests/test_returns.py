# SPDX-License-Identifier: Apache-2.0
"""Return conditions (SPEC 14, 15, §0.2; invariant 12): what would bring a
rejected alternative back, evaluated by ONE function against the resolution.

A structured condition is evaluated only while its claim reads Checked — a
condition on a claim that is not Checked says *cannot be evaluated: C1 is
<status>*, never a silent false (SPEC §6). ``margin`` and ``value`` come from
the verdict the composition reports, ``limit`` from the claim's acceptance
condition. ``check`` prints each one that holds — *may return* — and its exit
code never moves for it. Every reader says the same tokens.
"""
from __future__ import annotations

import dataclasses
import json
import os
import unittest

import _decisions as D
import _env

from nopekit import claims, cli, page, report, store
from nopekit.claims import Attribution, ClaimCause, Composed
from nopekit.models import (Acceptance, Claim, ClaimKind, ClaimStatus, Comparator, Ledger,
                            PhysicalResult, ReturnCondition, Standing, Verdict)


def _claim(cid: str = "C1", *, comparator: str = "<=", limit: float | None = 0.5,
           limit_hi: float | None = None, units: str = "mm", kind: str = "measurable",
           **extra) -> Claim:
    return Claim(id=cid, statement="the tip sags little", kind=ClaimKind(kind),
                 acceptance=Acceptance(quantity="tip deflection",
                                       comparator=Comparator(comparator), limit=limit,
                                       limit_hi=limit_hi, units=units), **extra)


def _verdict(gate: str = "g1", measured: float | None = 0.3, *, limit: float = 0.5,
             passed: bool = True, cid: str = "C1", **extra) -> Verdict:
    return Verdict(gate=gate, passed=passed, claims=[cid], measured=measured, limit=limit,
                   units="mm", comparator="<=", settles="tip deflection", **extra)


def _cond(**kw) -> ReturnCondition:
    base = {"claim": "C1", "quantity": "margin", "comparator": ">", "value": 0.3}
    base.update(kw)
    return ReturnCondition(**base)


def _state(condition, ledger: Ledger, **compose) -> claims.ReturnState:
    return claims.return_state(condition, ledger, claims.compositions(ledger, **compose))


#: Each composition that is not Checked, how to build it, and the status word
#: its condition must name.
def _unchecked() -> dict[str, tuple[Ledger, dict, str]]:
    owned = _claim(kind="assumption", owner="Dana", rationale="carried")
    return {
        "failing": (Ledger(claims=[_claim()], verdicts=[_verdict(measured=0.7, passed=False)]),
                    {}, "failing"),
        "acceptance": (Ledger(claims=[_claim(limit=0.2)], verdicts=[_verdict()]), {},
                       "failing"),
        "stale": (Ledger(claims=[_claim()], verdicts=[_verdict()]),
                  {"stale_gates": {"g1"}}, "stale"),
        "skipped": (Ledger(claims=[_claim()], verdicts=[_verdict(skipped=True,
                                                                 skip_reason="no tool")]),
                    {}, "skipped"),
        "errored": (Ledger(claims=[_claim()], verdicts=[_verdict(error="boom")]), {},
                    "skipped, errored"),
        "gap": (Ledger(claims=[_claim()]), {}, "gap"),
        "open": (Ledger(claims=[_claim(gates=["g1", "g2"])], verdicts=[_verdict()]), {},
                 "open"),
        "pending build": (Ledger(claims=[_claim(kind="physical")]), {}, "pending build"),
        "assumed": (Ledger(claims=[owned]),
                    {"owners": {"C1": Attribution("Dana", "carried")}}, "assumed"),
    }


def return_problems(evaluate) -> list[str]:
    """Every way ``evaluate`` (``claims.return_state`` or a planted one) says
    more than the resolution: a condition evaluated on a claim that is not
    Checked, or a Checked one read off a verdict the composition does not report."""
    problems: list[str] = []
    for label, (ledger, kw, word) in _unchecked().items():
        found = evaluate(_cond(comparator="<", value=10.0), ledger,
                         claims.compositions(ledger, **kw))
        if found.state != "cannot-evaluate" or found.why != "status":
            problems.append(f"{label}: {found.state} ({found.why})")
            continue
        row = claims.RejectionRow("d", 0, "v", "infeasible", "", "", _cond(), found, None)
        if report.return_words(row) != f"cannot be evaluated: C1 is {word}":
            problems.append(f"{label}: {report.return_words(row)!r}")
    ledger = Ledger(claims=[_claim()], verdicts=[_verdict("g1", 0.3), _verdict("g2", 0.45)])
    found = evaluate(_cond(comparator="<", value=0.2), ledger, claims.compositions(ledger))
    if (found.state, found.gate) != ("holds", "g2"):
        problems.append(f"the binding evaluator: {found.state} via {found.gate!r}")
    return problems


class AConditionReadsOnlyACheckedClaim(_env.EnvCase):
    """(12) A return condition is evaluated only on a claim the composition reads
    Checked — never on a Failing, Stale, Skipped, errored, Gap, Open, Pending
    build or Assumed one — and then only against what the composition reports."""

    def test_the_evaluator(self):
        self.assertEqual(return_problems(claims.return_state), [])

    def test_planted_evaluators_are_caught(self):
        real = claims.return_state

        def reads_any_verdict(condition, ledger, composed):
            if condition.quantity in ("margin", "value"):
                verdict = next((v for v in ledger.verdicts if v.measured is not None), None)
                if verdict is not None:
                    m = claims.margin(verdict).fraction
                    observed = m if condition.quantity == "margin" else verdict.measured
                    if observed is not None:
                        holds = Comparator(condition.comparator).holds(observed,
                                                                      condition.value)
                        return claims.ReturnState("holds" if holds else "does-not-hold",
                                                  claim=condition.claim, observed=observed,
                                                  gate=verdict.gate)
            return real(condition, ledger, composed)

        def forgets_stale(condition, ledger, composed):
            fresh = claims.compositions(ledger)
            return real(condition, ledger, fresh)

        def the_first_pass(condition, ledger, composed):
            found = real(condition, ledger, composed)
            if found.state in ("holds", "does-not-hold") and condition.quantity == "margin":
                first = ledger.verdicts[0]
                value = claims.margin(first).fraction
                holds = Comparator(condition.comparator).holds(value, condition.value)
                return found._replace(state="holds" if holds else "does-not-hold",
                                      observed=value, gate=first.gate)
            return found

        for name, planted in (("reads a Failing claim's verdict", reads_any_verdict),
                              ("reads a Stale one", forgets_stale),
                              ("takes the first pass", the_first_pass)):
            with self.subTest(name):
                self.assertNotEqual(return_problems(planted), [], f"{name} was not caught")

    def test_margin_value_and_limit_hold_and_do_not(self):
        ledger = Ledger(claims=[_claim()], verdicts=[_verdict()])
        for cond, state, observed in (
                (_cond(comparator=">", value=0.3), "holds", 0.4),
                (_cond(comparator="<", value=0.3), "does-not-hold", 0.4),
                (_cond(quantity="value", comparator="<", value=0.35), "holds", 0.3),
                (_cond(quantity="value", comparator=">=", value=0.35), "does-not-hold", 0.3),
                (_cond(quantity="limit", comparator=">=", value=0.5), "holds", 0.5),
                (_cond(quantity="limit", comparator=">", value=0.5), "does-not-hold", 0.5)):
            with self.subTest(cond):
                found = _state(cond, ledger)
                self.assertEqual(found.state, state)
                self.assertAlmostEqual(found.observed, observed)

    def test_the_words(self):
        ledger = Ledger(claims=[_claim()], verdicts=[_verdict()])
        cond = _cond(quantity="value", comparator="<", value=0.35)
        row = claims.RejectionRow("d", 0, "v", "dominated", "", "a-quote", cond,
                                  _state(cond, ledger), None)
        self.assertEqual(report.return_words(row, ledger),
                         "holds: C1 value < 0.35, now 0.3 mm (g1)")
        self.assertEqual(report.rejection_facts(row, ledger),
                         "dominated · holds: C1 value < 0.35, now 0.3 mm (g1) · "
                         "source: input a-quote")

    def test_what_cannot_be_evaluated_says_why(self):
        checked = Ledger(claims=[_claim()], verdicts=[_verdict()])
        band = Ledger(claims=[_claim(comparator="between", limit=0.1, limit_hi=0.5)],
                      verdicts=[_verdict()])
        unlimited = Ledger(claims=[_claim(limit=None)], verdicts=[_verdict()])
        cases = (
            (_cond(claim="C9"), checked, "no-claim", "cannot be evaluated: C9 is not a claim"),
            (_cond(quantity="limit"), band, "band",
             "cannot be evaluated: C1's acceptance condition is a band"),
            (_cond(quantity="limit"), unlimited, "no-limit",
             "cannot be evaluated: C1 states no limit"),
            (_cond(quantity="value"), unlimited, "no-value",
             "cannot be evaluated: no value of C1 is compared with its acceptance condition"))
        for cond, ledger, why, words in cases:
            with self.subTest(why):
                found = _state(cond, ledger)
                self.assertEqual((found.state, found.why), ("cannot-evaluate", why))
                row = claims.RejectionRow("d", 0, "v", "dominated", "", "", cond, found, None)
                self.assertEqual(report.return_words(row, ledger), words)
        text = claims.return_state(ReturnCondition(text="when it moves indoors"), checked,
                                   claims.compositions(checked))
        self.assertEqual(text.state, "not-machine-checkable")
        self.assertEqual(claims.return_state(None, checked, {}).state, "none")

    def test_a_judged_claim_has_no_value_and_an_article_does(self):
        judged = _claim(kind="assumption")
        ledger = Ledger(claims=[judged])
        composed = {"C1": Composed(ClaimStatus.VERIFIED, ClaimCause.JUDGED)}
        found = claims.return_state(_cond(), ledger, composed)
        self.assertEqual((found.state, found.why), ("cannot-evaluate", "no-value"))
        counted = PhysicalResult(passed=True, measured=0.3, units="mm")
        tested = _claim(kind="physical", physical_result=counted, results=(counted,),
                        standing=Standing("current", 0))
        ledger = Ledger(claims=[tested])
        composed = {"C1": Composed(ClaimStatus.VERIFIED, ClaimCause.ON_ARTICLE)}
        found = claims.return_state(_cond(quantity="value", comparator="<", value=0.35),
                                    ledger, composed)
        self.assertEqual((found.state, found.observed), ("holds", 0.3))
        found = claims.return_state(_cond(), ledger, composed)
        self.assertEqual(found.state, "holds")
        self.assertAlmostEqual(found.observed, 0.4)
        in_um = PhysicalResult(passed=True, measured=300.0, units="um")
        other = _claim(kind="physical", physical_result=in_um, results=(in_um,),
                       standing=Standing("current", 0))
        found = claims.return_state(_cond(quantity="value"), Ledger(claims=[other]), composed)
        self.assertEqual(found.why, "no-value", "a value in other units is not compared")
        unjudged = _claim(kind="physical", physical_result=counted, results=(counted,))
        found = claims.return_state(_cond(quantity="value"), Ledger(claims=[unjudged]),
                                    composed)
        self.assertEqual(found.why, "no-value", "a pass no judge stood behind has no value")

    def test_an_article_reads_the_pass_that_counts_not_the_newest(self):
        """A person's pass at 0.3 counts; a later pass at 0.45 typed from an agent
        session is recorded and counts for nothing (invariant 11). The claim stays
        Checked on entry 0, and ``physical_result`` — the newest entry, with no
        fail (``store._counting_result``) — is the uncounted one. A condition
        ``value > 0.4`` must read the counted 0.3 and not hold. What slipped
        through (review of phase 2): it read 0.45, and ``check`` said *may return*
        on a value the agent typed."""
        person = PhysicalResult(passed=True, measured=0.3, units="mm")
        agent = PhysicalResult(passed=True, measured=0.45, units="mm")
        tested = _claim(kind="physical", physical_result=agent, results=(person, agent),
                        standing=Standing("current", 0))
        ledger = Ledger(claims=[tested])
        composed = {"C1": Composed(ClaimStatus.VERIFIED, ClaimCause.ON_ARTICLE)}
        found = claims.return_state(_cond(quantity="value", comparator=">", value=0.4),
                                    ledger, composed)
        self.assertEqual((found.state, found.observed), ("does-not-hold", 0.3))
        found = claims.return_state(_cond(comparator="<", value=0.2), ledger, composed)
        self.assertEqual(found.state, "does-not-hold")
        self.assertAlmostEqual(found.observed, 0.4, msg="the margin is the counted pass's")
        moved = dataclasses.replace(tested, standing=Standing("article-moved", 0))
        found = claims.return_state(_cond(quantity="value"), Ledger(claims=[moved]), composed)
        self.assertEqual(found.why, "no-value", "a pass that does not stand has no value")

    def test_the_margin_is_the_verdicts_own(self):
        ledger = Ledger(claims=[_claim()], verdicts=[_verdict()])
        found = _state(_cond(), ledger)
        self.assertEqual(found.observed, claims.margin(ledger.verdicts[0]).fraction)


def _bracket_holding(root: str, comparator: str) -> None:
    """The bracket decision's preferred_against condition, C3's margin against
    0.1: `>` holds (C3's margin is about 0.99), `<` does not."""
    D.edit_rejection(root, 2, returns_if={"claim": "C3", "quantity": "margin",
                                         "comparator": comparator, "value": 0.1})


class MayReturnNeverMovesTheExitCode(_env.EnvCase):
    """(12) ``check`` prints *may return* for each condition that holds, after
    its code is fixed: the same exit code, the same statuses, the same summary but
    for the rejection rows, whether a condition holds or not."""

    def test_the_bracket_with_a_condition_that_holds_and_one_that_does_not(self):
        seen = {}
        for comparator in (">", "<"):
            root = D.bracket(os.path.join(self.tmp(), comparator.replace(">", "gt")
                                          .replace("<", "lt")))
            _bracket_holding(root, comparator)
            code, out, _err = D.main(root, "check", "--json")
            text_code, text, _err = D.main(root, "check")
            seen[comparator] = (code, json.loads(out), text_code, text)
        (hold_code, holds, hold_text_code, hold_text), (not_code, nots, not_text_code,
                                                         not_text) = seen[">"], seen["<"]
        self.assertEqual((hold_code, hold_text_code), (not_code, not_text_code))
        self.assertEqual(hold_code, 1, "C1 fails on purpose")
        self.assertEqual(len(holds["may_return"]), 1)
        self.assertEqual(nots["may_return"], [])
        self.assertEqual(hold_text.count("may return:"), 1)
        self.assertNotIn("may return:", not_text)
        self.assertIn("may return: a machined 6061 aluminium bracket — rejected in decision "
                      "print-in-petg (preferred against, not recorded by Robin Okafor); holds: "
                      "C3 margin > 0.1, now 0.98", hold_text)
        for key in ("blocking", "ready", "all_required_checked", "counts"):
            self.assertEqual(holds[key], nots[key], key)
        strip = lambda s: {k: v for k, v in s.items() if k != "rejections"}  # noqa: E731
        self.assertEqual(strip(holds["summary"]), strip(nots["summary"]))


class EveryReaderAgreesOnAReturnCondition(_env.EnvCase):
    """(12) ``why <decision>``, ``check --json``, ``status --json`` and
    ``state.json`` say one condition's state with the same tokens, from the one
    producer (``claims.rejection_rows``)."""

    def test_every_channel(self):
        root = D.bracket(os.path.join(self.tmp(), "b"))
        _bracket_holding(root, ">")
        D.main(root, "check")
        rows = {}
        for argv in (("check", "--json"), ("status", "--json")):
            _code, out, _err = D.main(root, *argv)
            rows[argv[0]] = [r for r in json.loads(out)["summary"]["rejections"]
                             if r["decision"] == D.DECISION]
        from nopekit import site
        import _physical
        view, resolution = _physical.resolved(root)
        registry, _p = cli._registry(root, store.load(root), strict=False)
        rows["state"] = [r for r in site.state(root, view, registry,
                                               resolution=resolution)["rejections"]
                         if r["decision"] == D.DECISION]
        self.assertEqual(rows["check"], rows["status"])
        self.assertEqual(rows["check"], rows["state"])
        tokens = [(r["type"], r["returns"]["state"]) for r in rows["check"]]
        self.assertEqual(tokens, [("infeasible", "not-machine-checkable"),
                                  ("unevaluated", "not-machine-checkable"),
                                  ("preferred_against", "holds")])
        _code, why, _err = D.main(root, "why", D.DECISION)
        composed = claims.compositions(view, registry=registry,
                                       stale_gates=resolution.stale_gates)
        for row in claims.rejection_rows(view, composed):
            if row.decision == D.DECISION:
                self.assertIn(report.rejection_facts(row, view), why)
        # The marketing page (the two pages): the same tokens, from the same
        # producer, and its words `rejection_words(register="site")`'s; a
        # resealed page whose return token says more is refused.
        for argv in (("site", "init"), ("site", "build")):
            code, out, err = D.main(root, *argv)
            self.assertEqual(code, 0, out + err)
        path = os.path.join(root, "site", "data", "page.json")
        doc = D.read_json(path)
        [decision] = [d for d in doc["decisions"] if d["id"] == D.DECISION]
        self.assertEqual([(i["type"], i["returns"]) for i in decision["rejected"]], tokens)
        for row in claims.rejection_rows(view, composed):
            if row.decision == D.DECISION:
                item = decision["rejected"][row.index]
                self.assertEqual(item["returns"], row.returns.state)
                self.assertEqual((item["type_word"], item["returns_word"]),
                                 report.rejection_words(row, view, register="site"))
        held = next(i for i in decision["rejected"] if i["returns"] == "holds")
        self.assertTrue(held["returns_word"].startswith("The return condition holds: "),
                        held["returns_word"])
        held.update(returns="does-not-hold")
        doc["self"] = page.seal(doc)
        D.write_json(path, doc)
        _code, out, _err = D.main(root, "site", "status", "--json")
        edited = json.loads(out)["edited"]
        self.assertTrue([e for e in edited if "return reads does-not-hold" in e], edited)


if __name__ == "__main__":
    unittest.main()
