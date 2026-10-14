# SPDX-License-Identifier: Apache-2.0
"""Requirements are records (architecture phase 1, SPEC decision 12).

What the person asked for, in their words, is ``requirements/<id>.json``; a
claim names the requirements it serves. A requirement's status is never stored:
``claims.requirement_statuses`` derives it — the worst of its claims, in the
composition's own order (a crash's Skipped above a plain one), Gap with none —
and every reader asks it. *Ready* never reads a requirement: milestones require
claims.

* ``ARequirementIsNeverMoreResolvedThanItsClaims`` (invariant 4) — over every
  status ``compose`` can give, a requirement reads its worst claim, never more.
* ``EveryReaderAgreesOnARequirement`` (invariant 12) — status, the report,
  ``summarise``, the JSON rows, ``state.json`` and ``why`` say what the one
  producer says, in ``report.HUMAN``'s words.
* ``ReadinessStaysTheClaims`` (invariant 12) — a Gap or Failing requirement
  beside Checked required claims leaves *ready* and the readiness sentence
  exactly as they were.

What slipped through the design read: a requirement's status folded in
``status``, ``why`` and the site separately would be three producers (R-5,
S-69), and a best-of fold reads Checked over a failing claim.

Expected values are typed literals (D-7).
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import os
import re
import tempfile
import unittest
from typing import Any, Callable, Mapping
from unittest import mock

import _env
import _projects
import test_invariants as TI
import test_vocabulary as TV
from nopekit import claims as claims_mod
from nopekit import decisions as decisions_mod
from nopekit import report as report_mod
from nopekit import site as site_mod
from nopekit.models import (Claim, ClaimKind, ClaimStatus, Ledger, ProjectMeta,
                            Requirement, Verdict)


# --------------------------------------------------------------------------- #
# the checker: a requirement against the claims that serve it
# --------------------------------------------------------------------------- #
def requirement_problems(found: Mapping[str, Any], composed: Mapping[str, Any],
                         ledger: Ledger) -> list[str]:
    """Every requirement of ``ledger`` whose ``found`` row says more or other
    than the claims that serve it: with none, anything but Gap; with some, a
    status, a crash mark or a set of worst ids that is not the most severe
    rank's (``claims.severity``, the composition's own order)."""
    out: list[str] = []
    for requirement in ledger.requirements:
        rid = requirement.id
        row = found.get(rid)
        if row is None:
            out.append(f"{rid}: no status")
            continue
        serving = [c.id for c in ledger.claims if rid in c.requirements and c.id in composed]
        if list(row.claims) != serving:
            out.append(f"{rid}: serves {list(row.claims)}, not {serving}")
        if not serving:
            if row.status is not ClaimStatus.UNCLAIMED or row.errored or row.worst:
                out.append(f"{rid}: no claim serves it, and it reads {row.status.value}")
            continue
        rank = min(claims_mod.severity(composed[cid]) for cid in serving)
        worst = [cid for cid in serving if claims_mod.severity(composed[cid]) == rank]
        if list(row.worst) != worst:
            out.append(f"{rid}: worst {list(row.worst)}, not {worst}")
        first = composed[worst[0]]
        if (row.status, row.errored) != (first.status, first.errored):
            out.append(f"{rid}: reads {row.status.value} (errored {row.errored}), not "
                       f"{first.status.value} (errored {first.errored})")
    return out


def _every_status_world() -> tuple[Ledger, Any, dict, frozenset, dict]:
    """`test_invariants`' every-status ledger with one requirement per claim
    that does not read Checked, each served by that claim and by K1 (Checked),
    and the requirements this file's rows name."""
    ledger, reg, owners, stale = TI._every_status_ledger()
    composed = claims_mod.compositions(ledger, registry=reg, owners=owners, stale_gates=stale)
    resolved = (ClaimStatus.PASS, ClaimStatus.VERIFIED)
    others = [c.id for c in ledger.claims if composed[c.id].status not in resolved]
    serves: dict[str, list[str]] = {}
    rows: dict[str, list[str]] = {}
    for n, cid in enumerate(others, start=1):
        rows[f"R{n}"] = [cid, "K1"]
    n = len(others)
    rows[f"R{n + 1}"] = ["K1", "K30"]          # all Checked (a pass, an article's pass)
    rows[f"R{n + 2}"] = []                      # no claim
    rows[f"R{n + 3}"] = ["K6", "K8"]            # a tie at Gap
    rows[f"R{n + 4}"] = ["K5", "K4"]            # a crash above a plain skip
    rows[f"R{n + 5}"] = ["K4", "K2"]            # Failing above a crash
    for rid, cids in rows.items():
        for cid in cids:
            serves.setdefault(cid, []).append(rid)
    claims = [dataclasses.replace(c, requirements=serves.get(c.id, []) + (
        ["R99"] if c.id == "K1" else [])) for c in ledger.claims]
    world = dataclasses.replace(ledger, claims=claims, requirements=[
        Requirement(id=rid, statement=f"what {rid} asks", source="interview") for rid in rows])
    return world, reg, owners, stale, {"others": n}


class ARequirementIsNeverMoreResolvedThanItsClaims(unittest.TestCase):
    """(invariant 4) A requirement reads the worst status among the claims that
    serve it, in the composition's own order, and Gap with none — never more
    resolved than any of them."""

    def setUp(self) -> None:
        self.ledger, reg, owners, stale, self.facts = _every_status_world()
        self.composed = claims_mod.compositions(self.ledger, registry=reg, owners=owners,
                                                stale_gates=stale)
        self.found = claims_mod.requirement_statuses(self.ledger, self.composed)

    def test_each_reads_its_worst_claim(self):
        self.assertEqual(requirement_problems(self.found, self.composed, self.ledger), [])
        resolved = (ClaimStatus.PASS, ClaimStatus.VERIFIED)
        for n in range(1, self.facts["others"] + 1):
            rid = f"R{n}"
            (cid,) = [c for c in self.found[rid].claims if c != "K1"]
            with self.subTest(rid=rid, claim=cid):
                self.assertNotIn(self.found[rid].status, resolved)
                self.assertEqual((self.found[rid].status, self.found[rid].errored),
                                 (self.composed[cid].status, self.composed[cid].errored))
                self.assertEqual(self.found[rid].worst, (cid,))

    def test_the_typed_rows(self):
        n = self.facts["others"]
        got = {k: (self.found[f"R{n + i}"].key, self.found[f"R{n + i}"].errored,
                   self.found[f"R{n + i}"].worst) for i, k in enumerate(
                       ("all checked", "no claim", "tie", "crash over skip",
                        "failing over crash"), start=1)}
        self.assertEqual(got, {
            "all checked": ("checked", False, ("K1", "K30")),
            "no claim": ("gap", False, ()),
            "tie": ("gap", False, ("K6", "K8")),
            "crash over skip": ("skipped", True, ("K4",)),
            "failing over crash": ("failing", False, ("K2",)),
        })
        self.assertNotIn("R99", self.found, "a pointer to no requirement serves nothing")
        self.assertEqual(list(self.found), [r.id for r in self.ledger.requirements])

    def test_a_planted_fold_is_caught(self):
        real = claims_mod.requirement_statuses

        def best_of(ledger, composed):
            out = dict(real(ledger, composed))
            for rid, row in out.items():
                if row.claims:
                    best = max(row.claims, key=lambda c: claims_mod.severity(composed[c]))
                    out[rid] = row._replace(status=composed[best].status,
                                            errored=composed[best].errored, worst=(best,))
            return out

        def first_claim(ledger, composed):
            out = dict(real(ledger, composed))
            for rid, row in out.items():
                if row.claims:
                    one = composed[row.claims[0]]
                    out[rid] = row._replace(status=one.status, errored=one.errored,
                                            worst=(row.claims[0],))
            return out

        def plain_skip(ledger, composed):
            out = dict(real(ledger, composed))
            rank = claims_mod.SEVERITY_ORDER.index
            for rid, row in out.items():
                if row.claims:
                    key = min(rank(claims_mod.STATUS_KEY[composed[c].status])
                              for c in row.claims)
                    worst = tuple(c for c in row.claims
                                  if rank(claims_mod.STATUS_KEY[composed[c].status]) == key)
                    out[rid] = row._replace(status=composed[worst[0]].status,
                                            errored=composed[worst[0]].errored, worst=worst)
            return out

        def gap_is_checked(ledger, composed):
            out = dict(real(ledger, composed))
            for rid, row in out.items():
                if not row.claims:
                    out[rid] = row._replace(status=ClaimStatus.PASS)
            return out

        for label, fold in (("best of", best_of), ("first claim", first_claim),
                            ("a plain skip over a crash", plain_skip),
                            ("no claim reads checked", gap_is_checked)):
            with self.subTest(fold=label):
                self.assertTrue(requirement_problems(fold(self.ledger, self.composed),
                                                     self.composed, self.ledger),
                                f"{label} was accepted")


# --------------------------------------------------------------------------- #
# invariant 12: every reader agrees
# --------------------------------------------------------------------------- #
def _small_world() -> tuple[Ledger, Any]:
    """Five claims, five requirements: R1 failing (C2), R2 checked, R3 no
    claim, R4 a Gap beside a pending build (C4), R5 a crash beside a pass (C5)."""
    spec = TI.SPEC
    reg = TI._Reg([dataclasses.replace(spec, id=g, claims=[c])
                   for g, c in (("g.a", "C1"), ("g.b", "C2"), ("g.c", "C5"))])
    claims = [
        Claim(id="C1", statement="passes", gates=["g.a"], requirements=["R1", "R2", "R5"]),
        Claim(id="C2", statement="fails", gates=["g.b"], requirements=["R1"]),
        Claim(id="C3", statement="a real part", kind=ClaimKind.PHYSICAL, requirements=["R4"]),
        Claim(id="C4", statement="assumed", kind=ClaimKind.ASSUMPTION, rationale="r",
              requirements=["R4"]),
        Claim(id="C5", statement="crashes", gates=["g.c"], requirements=["R5"]),
    ]
    verdicts = [Verdict(gate="g.a", claims=["C1"], passed=True),
                Verdict(gate="g.b", claims=["C2"], passed=False, detail="0.7 mm"),
                Verdict(gate="g.c", claims=["C5"], error="RuntimeError: boom")]
    requirements = [Requirement(id=f"R{n}", statement=f"the person's words {n}",
                                source="interview") for n in range(1, 6)]
    return Ledger(meta=ProjectMeta(name="t", revision="v0.1"), claims=claims,
                  verdicts=verdicts, requirements=requirements), reg


def _lets_c2_pass(claim, verdicts, **kw):
    """A resolver regression, planted: C2 — failing on its evidence — composed
    Checked. `report._disagreement` (D18) is what still sees it."""
    found = _REAL_COMPOSE(claim, verdicts, **kw)
    if claim.id == "C2":
        return dataclasses.replace(found, status=ClaimStatus.PASS,
                                   cause=claims_mod.ClaimCause.CHECKED, cites=(), verdict=None)
    return found


_REAL_COMPOSE = claims_mod.compose


def disagreement_problems(ledger: Ledger, registry: Any,
                          want: Mapping[str, list[str]]) -> list[str]:
    """Every requirement channel that shows a requirement in ``want`` without
    naming the serving claims ``want`` lists as disagreeing with their evidence
    (D18): `status`'s line, the report's section, the JSON rows (`status
    --json`'s), `state.json` and `why`. Prefixed by channel."""
    from nopekit import cli as cli_mod
    composed = claims_mod.compositions(ledger, registry=registry)
    out: list[str] = []
    said = "status and evidence disagree"

    line = next(ln for ln in report_mod.render_terminal(ledger, registry).splitlines()
                if ln.startswith("requirements "))
    items = {m.group("id"): m.group("ids") or "" for m in map(
        _ITEM.match, line.split(" — ", 1)[1].split(" · ")) if m}
    md = report_mod.render_markdown(ledger, registry).splitlines()
    resolution = mock.Mock(verdicts=ledger.verdicts, stale_gates=frozenset(), rows={})
    state = site_mod.state(tempfile.gettempdir(), ledger, registry, resolution=resolution,
                           params=[])
    page = {r["id"]: r.get("disagree") for r in state["requirements"]}
    rows = {r["id"]: r.get("disagree")
            for r in cli_mod._requirement_rows(ledger, composed, registry)}
    for rid, cids in want.items():
        if said not in items.get(rid, "") or any(c not in items[rid] for c in cids):
            out.append(f"status: {rid} reads {items.get(rid)!r}")
        row = next((ln for ln in md if ln.startswith(f"- **{rid}** ")), "")
        if said not in row or any(c not in row for c in cids):
            out.append(f"report: {rid} reads {row!r}")
        if rows.get(rid) != cids:
            out.append(f"json: {rid} disagree {rows.get(rid)!r}")
        if page.get(rid) != cids:
            out.append(f"state.json: {rid} disagree {page.get(rid)!r}")
        why = decisions_mod.why(ledger, rid, composed=composed)
        if f"{said} on {', '.join(cids)}" not in why:
            out.append(f"why: {rid} names no disagreement")
    return out


def _many_world(*, failing_from: int = 9) -> tuple[Ledger, Any]:
    """Ten requirements: C1 (Checked) serves R1..R8, C2..C5 (Failing) serve
    R9, nothing serves R10; with ``failing_from`` lower, C2 serves R<that>..R9
    instead of C1."""
    spec = TI.SPEC
    reg = TI._Reg([dataclasses.replace(spec, id=f"g.{n}", claims=[f"C{n}"])
                   for n in range(1, 6)])
    serves_c1 = [f"R{n}" for n in range(1, min(failing_from, 9))]
    serves_c2 = [f"R{n}" for n in range(failing_from, 10)]
    claims = [Claim(id="C1", statement="passes", gates=["g.1"], requirements=serves_c1)]
    claims += [Claim(id=f"C{n}", statement="fails", gates=[f"g.{n}"],
                     requirements=serves_c2 if n == 2 else ["R9"]) for n in range(2, 6)]
    verdicts = [Verdict(gate="g.1", claims=["C1"], passed=True)]
    verdicts += [Verdict(gate=f"g.{n}", claims=[f"C{n}"], passed=False, detail="0.7 mm")
                 for n in range(2, 6)]
    requirements = [Requirement(id=f"R{n}", statement=f"the person's words {n}",
                                source="interview") for n in range(1, 11)]
    return Ledger(meta=ProjectMeta(name="t", revision="v0.1"), claims=claims,
                  verdicts=verdicts, requirements=requirements), reg


#: What the small world's requirements read: (status value, errored, worst).
SMALL_WORLD = {
    "R1": ("fail", False, ["C2"]),
    "R2": ("pass", False, ["C1"]),
    "R3": ("unclaimed", False, []),
    "R4": ("unclaimed", False, ["C4"]),
    "R5": ("blocked", True, ["C5"]),
}

_ITEM = re.compile(r"^(?P<id>R\d+) (?P<word>[^()]+?)(?: \((?P<ids>[^)]*)\))?$")
_MORE = re.compile(r"^\+(?P<k>\d+) more(?: \((?P<u>\d+) unresolved\))?$")
_RESOLVED = (ClaimStatus.PASS, ClaimStatus.VERIFIED)


def _rank(row: Any) -> int:
    """A requirement row's place in `claims.SEVERITY_ORDER` (a crash as
    `errored`), a disagreement first — the order `status`'s capped line keeps."""
    if getattr(row, "disagree", ()):
        return -1
    key = "errored" if row.errored else claims_mod.STATUS_KEY[row.status]
    return claims_mod.SEVERITY_ORDER.index(key)


def line_problems(line: str, found: Mapping[str, Any], want: Mapping[str, str]) -> list[str]:
    """`status`'s requirements line against the producer: every item it names
    in the producer's word; `+N more` counting exactly the ones it leaves out,
    with how many of them are unresolved; and none it leaves out more urgent
    than one it names (review of phase 1: a failing R9 read `+1 more` under
    eight checked ones)."""
    out: list[str] = []
    items = line.split(" — ", 1)[1].split(" · ")
    said = {m.group("id"): m.group("word") for m in map(_ITEM.match, items) if m}
    more = [m for m in map(_MORE.match, items) if m]
    if len(said) + len(more) != len(items):
        out.append(f"status: an item neither a requirement nor +N more in {items}")
    wrong = {rid: word for rid, word in said.items() if want.get(rid) != word}
    if wrong:
        out.append(f"status says {wrong}, the producer {want}")
    hidden = [rid for rid in want if rid not in said]
    if not hidden:
        if more:
            out.append(f"status: {more[0].group(0)} with every requirement named")
        return out
    if len(more) != 1 or int(more[0].group("k")) != len(hidden):
        out.append(f"status leaves out {hidden}, and says {[m.group(0) for m in more]}")
        return out
    left = sum(1 for rid in hidden if found[rid].status not in _RESOLVED or
               getattr(found[rid], "disagree", ()))
    if int(more[0].group("u") or 0) != left:
        out.append(f"status: {more[0].group(0)}, and {left} of {hidden} are unresolved")
    if said and min(_rank(found[r]) for r in hidden) < max(_rank(found[r]) for r in said):
        worst = min(hidden, key=lambda r: _rank(found[r]))
        out.append(f"status hides {worst} ({want[worst]}) behind {more[0].group(0)}")
    return out
_MD_ROW = re.compile(r"^- \*\*(?P<id>R\d+)\*\* \*\((?P<word>[^)]+)\)\* ")


def agreement_problems(ledger: Ledger, registry: Any) -> list[str]:
    """Every channel that words a requirement otherwise than
    ``claims.requirement_statuses`` over the compositions: `status`'s line, the
    report's section, `summarise`, `requirement_json`, `state.json` and `why`."""
    composed = claims_mod.compositions(ledger, registry=registry)
    found = claims_mod.requirement_statuses(ledger, composed)
    want = {rid: report_mod.status_word(r.status, errored=r.errored) for rid, r in found.items()}
    out: list[str] = []

    terminal = report_mod.render_terminal(ledger, registry)
    lines = [ln for ln in terminal.splitlines() if ln.startswith("requirements ")]
    if len(lines) != 1:
        out.append(f"status: {len(lines)} requirements lines")
    else:
        out += line_problems(lines[0], found, want)

    md = report_mod.render_markdown(ledger, registry)
    rows = {m.group("id"): m.group("word") for m in map(_MD_ROW.match, md.splitlines()) if m}
    if rows != want:
        out.append(f"the report says {rows}, the producer {want}")

    summary = claims_mod.summarise(ledger, registry)["requirements"]
    if {rid: (r["status"], r["errored"]) for rid, r in summary.items()} != {
            rid: (r.status.value, r.errored) for rid, r in found.items()}:
        out.append(f"summarise says {summary}")

    resolution = mock.Mock(verdicts=ledger.verdicts, stale_gates=frozenset(), rows={})
    state = site_mod.state(tempfile.gettempdir(), ledger, registry, resolution=resolution,
                           params=[])
    page = {r["id"]: (r["status"], r["word"]) for r in state["requirements"]}
    if page != {rid: (r.status.value, want[rid]) for rid, r in found.items()}:
        out.append(f"state.json says {page}")
    for requirement in ledger.requirements:
        row = report_mod.requirement_json(requirement, found[requirement.id])
        if (row["status"], row["word"]) != (found[requirement.id].status.value,
                                            want[requirement.id]):
            out.append(f"requirement_json says {row}")
        head = decisions_mod.why(ledger, requirement.id, composed=composed).splitlines()[0]
        if not head.endswith(f"[{want[requirement.id]}]"):
            out.append(f"why {requirement.id}: {head!r}")
    return out


class EveryReaderAgreesOnARequirement(_env.EnvCase):
    """(invariant 12) No reader shows a requirement more resolved than the one
    producer says, nor in other words than ``report.HUMAN``'s."""

    def test_the_small_world_reads_as_typed(self):
        ledger, reg = _small_world()
        composed = claims_mod.compositions(ledger, registry=reg)
        found = claims_mod.requirement_statuses(ledger, composed)
        self.assertEqual({rid: (r.status.value, r.errored, list(r.worst))
                          for rid, r in found.items()}, SMALL_WORLD)

    def test_every_channel_agrees(self):
        ledger, reg = _small_world()
        self.assertEqual(agreement_problems(ledger, reg), [])
        line = next(ln for ln in report_mod.render_terminal(ledger, reg).splitlines()
                    if ln.startswith("requirements "))
        self.assertEqual(line, "requirements 5 — R1 failing (C2) · R2 checked · R3 gap (no "
                               "claim) · R4 gap (C4) · R5 skipped, errored (C5)")

    def test_the_words_are_humans(self):
        ledger, reg = _small_world()
        with mock.patch.object(report_mod, "HUMAN", TV.sentinel_human()):
            line = next(ln for ln in report_mod.render_terminal(ledger, reg).splitlines()
                        if ln.startswith("requirements "))
            md = report_mod.render_markdown(ledger, reg)
        self.assertIn("R1 zzfailing (C2)", line)
        self.assertIn("R3 zzgap (no claim)", line)
        self.assertIn("## Zzrequirements", md)
        self.assertIn("- **R2** *(zzchecked)*", md)

    def test_the_page_takes_its_rows_from_the_producer(self):
        tree = ast.parse(inspect.getsource(site_mod.state))
        calls = {node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertIn("requirement_statuses", calls)
        values = [node.values[node.keys.index(key)] for node in ast.walk(tree)
                  if isinstance(node, ast.Dict)
                  for key in node.keys
                  if isinstance(key, ast.Constant) and key.value == "requirements"]
        self.assertEqual(len(values), 1)
        (value,) = values
        self.assertIsInstance(value, ast.ListComp)
        self.assertEqual(getattr(value.elt.func, "attr", ""), "requirement_json")

    def test_a_section_that_folds_statuses_itself_is_caught(self):
        ledger, reg = _small_world()

        def first_claim(ledger_, composed, cover=None):
            out = ["## Requirements", ""]
            for requirement in ledger_.requirements:
                serving = [c for c in ledger_.claims if requirement.id in c.requirements]
                status = composed[serving[0].id].status if serving else ClaimStatus.PASS
                out.append(f"- **{requirement.id}** *({report_mod.word(status)})* x — y")
            return out + [""]

        with mock.patch.object(report_mod, "_section_requirements", first_claim):
            self.assertTrue(agreement_problems(ledger, reg))

    def test_a_disagreeing_claim_is_named_under_its_requirement(self):
        """D18 carried up (review of phase 1): a resolver that calls failing C2
        Checked — the case every claim row lists as "status and evidence
        disagree" — leaves R1 Checked by the composition, and no requirement
        reader may print that bare."""
        ledger, reg = _small_world()
        with mock.patch.object(claims_mod, "compose", _lets_c2_pass):
            self.assertEqual(disagreement_problems(ledger, reg, {"R1": ["C2"]}), [])
            line = next(ln for ln in report_mod.render_terminal(ledger, reg).splitlines()
                        if ln.startswith("requirements "))
        self.assertIn("R1 checked (status and evidence disagree: C2) · R2 checked", line)

    def test_a_requirement_reader_that_drops_the_disagreement_is_caught(self):
        ledger, reg = _small_world()

        def bare(ledger_, composed, cover):
            return claims_mod.requirement_statuses(ledger_, composed)

        with mock.patch.object(claims_mod, "compose", _lets_c2_pass), \
                mock.patch.object(report_mod, "requirement_statuses", bare):
            found = disagreement_problems(ledger, reg, {"R1": ["C2"]})
        self.assertEqual(sorted(p.split(":", 1)[0] for p in found),
                         ["json", "report", "state.json", "status", "why"])

    def test_a_capped_line_names_the_worst_first(self):
        """(review of phase 1) Ten requirements, the failing one ninth: the
        line keeps it, worst first, and `+N more` says how many it left out and
        how many of those are unresolved; three worst ids, then `+N more`."""
        ledger, reg = _many_world()
        line = next(ln for ln in report_mod.render_terminal(ledger, reg).splitlines()
                    if ln.startswith("requirements "))
        self.assertEqual(line, "requirements 10 — R9 failing (C2, C3, C4, +1 more) · R10 gap "
                               "(no claim) · R1 checked · R2 checked · R3 checked · R4 "
                               "checked · R5 checked · R6 checked · +2 more")
        self.assertEqual(agreement_problems(ledger, reg), [])
        unresolved, reg2 = _many_world(failing_from=1)
        line = next(ln for ln in report_mod.render_terminal(unresolved, reg2).splitlines()
                    if ln.startswith("requirements "))
        self.assertTrue(line.endswith(" · +2 more (2 unresolved)"), line)
        self.assertEqual(agreement_problems(unresolved, reg2), [])

    def test_a_line_cut_in_record_order_is_caught(self):
        ledger, reg = _many_world()
        composed = claims_mod.compositions(ledger, registry=reg)
        found = claims_mod.requirement_statuses(ledger, composed)
        want = {rid: report_mod.status_word(r.status, errored=r.errored)
                for rid, r in found.items()}
        record_order = ("requirements 10 — R1 checked · R2 checked · R3 checked · R4 checked "
                        "· R5 checked · R6 checked · R7 checked · R8 checked · +2 more")
        self.assertIn("status hides R9 (failing) behind +2 more",
                      line_problems(record_order, found, want))
        self.assertIn("status: +2 more, and 2 of ['R9', 'R10'] are unresolved",
                      line_problems(record_order, found, want))
        uncounted = record_order.replace("+2 more", "+1 more")
        self.assertTrue(line_problems(uncounted, found, want))

    def test_the_bracket_end_to_end(self):
        root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)
        want = {"R1": ("fail", ["C1"]), "R2": ("unclaimed", ["C7"]),
                "R3": ("unverified", ["C5"]), "R4": ("pass", ["C4"])}
        for args in (["status", "--json"], ["report", "--json"]):
            with self.subTest(command=args[0]):
                doc = json.loads(_env.nopekit(args, cwd=root).stdout)
                self.assertEqual({r["id"]: (r["status"], r["worst"])
                                  for r in doc["requirements"]}, want)
                self.assertEqual({rid: r["status"] for rid, r in
                                  doc["summary"]["requirements"].items()},
                                 {rid: s for rid, (s, _w) in want.items()})
        why = _env.nopekit(["why", "R1"], cwd=root).stdout.splitlines()
        self.assertEqual(why[0], "requirement  R1  [failing]")
        self.assertIn("  [FAIL ] C1 Tip sags no more than 0.5 mm at rated load — "
                      "bracket.deflection : 0.700 mm at 15 N (limit 0.5 mm)", why)


# --------------------------------------------------------------------------- #
# invariant 12: ready stays the claims'
# --------------------------------------------------------------------------- #
def _ready_world(*, requirements: bool) -> tuple[Ledger, Any]:
    """C1 required and Checked; C2 not required and Failing; with
    ``requirements``, R1 served by nobody (Gap) and R2 by C2 (Failing)."""
    spec = TI.SPEC
    reg = TI._Reg([dataclasses.replace(spec, id="g.a", claims=["C1"]),
                   dataclasses.replace(spec, id="g.b", claims=["C2"])])
    claims = [Claim(id="C1", statement="passes", gates=["g.a"]),
              Claim(id="C2", statement="fails", gates=["g.b"], critical=False,
                    requirements=["R2"] if requirements else [])]
    return Ledger(meta=ProjectMeta(name="t", revision="v0.1"), claims=claims,
                  verdicts=[Verdict(gate="g.a", claims=["C1"], passed=True),
                            Verdict(gate="g.b", claims=["C2"], passed=False)],
                  requirements=[Requirement(id="R1", statement="It looks tidy"),
                                Requirement(id="R2", statement="It is light")]
                  if requirements else []), reg


def readiness_problems(unresolved: Callable[..., Any]) -> list[str]:
    """Every way a requirement moves *ready*: `unresolved`, `summarise`'s
    `all_required_checked`, or the readiness sentence `status` prints."""
    out: list[str] = []
    seen = {}
    for with_requirements in (False, True):
        ledger, reg = _ready_world(requirements=with_requirements)
        composed = claims_mod.compositions(ledger, registry=reg)
        with mock.patch.object(claims_mod, "unresolved", unresolved):
            found = claims_mod.unresolved(ledger, composed)
            summary = claims_mod.summarise(ledger, reg)
            sentence = report_mod.render_terminal(ledger, reg).splitlines()[1]
        seen[with_requirements] = (found.ready, summary["all_required_checked"], sentence)
    if not seen[False][0]:
        out.append("the world without requirements is not ready")
    if seen[True] != seen[False]:
        out.append(f"requirements moved ready: {seen[False]} -> {seen[True]}")
    return out


class ReadinessStaysTheClaims(unittest.TestCase):
    """(invariant 12) *Ready* is the claims a milestone requires (or the
    required ones), through ``claims.unresolved``: a Gap or Failing requirement
    never moves it, nor the sentence that says it."""

    def test_a_gap_and_a_failing_requirement_move_nothing(self):
        self.assertEqual(readiness_problems(claims_mod.unresolved), [])
        ledger, reg = _ready_world(requirements=True)
        found = claims_mod.requirement_statuses(ledger, claims_mod.compositions(
            ledger, registry=reg))
        self.assertEqual({rid: r.key for rid, r in found.items()},
                         {"R1": "gap", "R2": "failing"})

    def test_no_junit_suite_for_requirements(self):
        self.assertEqual(report_mod._JUNIT_SUITES,
                         ("gates", "claims.critical", "claims.not-critical"))

    def test_an_unresolved_that_reads_requirements_is_caught(self):
        real = claims_mod.unresolved

        def strict(ledger, composed, milestone=None):
            found = real(ledger, composed, milestone)
            rolled = claims_mod.requirement_statuses(ledger, composed)
            if any(r.key != "checked" for r in rolled.values()):
                return found._replace(ready=False)
            return found

        self.assertTrue(readiness_problems(strict))


# --------------------------------------------------------------------------- #
# not an invariant class: the words
# --------------------------------------------------------------------------- #
class RequirementWords(_env.EnvCase):
    """The bracket's requirements as each channel prints them, verbatim."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.root = _projects.bracket_copy(os.path.join(tempfile.mkdtemp(
            prefix="nopekit-req-words-"), "b"), migrated=True)

    def run_(self, *args: str) -> str:
        return _env.nopekit(list(args), cwd=self.root).stdout

    def test_the_status_line(self):
        self.assertIn("\nrequirements 4 — R1 failing (C1) · R2 gap (C7) · R3 pending build "
                      "(C5) · R4 checked\n", self.run_("status"))

    def test_the_report_section(self):
        md = self.run_("report")
        section = md.split("## Requirements\n", 1)[1].split("\n## ", 1)[0]
        self.assertIn("- **R1** *(failing)* Hold the pump on the shelf without breaking, and "
                      "without a sag anyone can see — C1 failing · C6 gap · C2, C3 checked",
                      section)
        self.assertIn("- **R4** *(checked)* Print it myself, in PETG, on my 220 mm printer — "
                      "C4 checked", section)
        self.assertLess(md.index("## Failing, stale, skipped or open"),
                        md.index("## Requirements"))
        self.assertLess(md.index("## Requirements"), md.index("## Reproduce"))

    def test_why_a_requirement_and_a_claim(self):
        why = self.run_("why", "R2").splitlines()
        self.assertEqual(why[:4], ["requirement  R2  [gap]",
                                   "  The pump running must not make the shelf shake or buzz",
                                   "  source: interview", ""])
        claim = self.run_("why", "C5")
        self.assertIn("\n  serves: R3\n", claim)
        self.assertIn("\nMECHANISM\n  measurement — Hang a printed bracket", claim)
        c1 = self.run_("why", "C1")
        self.assertIn("  evaluators it expects: bracket.deflection, bracket.model_validity", c1)

    def test_an_unknown_name_names_requirements(self):
        proc = _env.nopekit(["why", "R9"], cwd=self.root)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no parameter, claim or requirement named 'R9'", proc.stderr)


if __name__ == "__main__":
    unittest.main()
