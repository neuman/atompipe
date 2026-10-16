# SPDX-License-Identifier: Apache-2.0
"""Every claim names its mechanism (architecture phase 1, SPEC decision 13).

A claim file says how it settles in one object, ``"mechanism": {"by", "how",
"evaluators"}``: ``by`` is where its evidence bottoms out (the terminal, held to
``TERMINALS_BY_KIND`` exactly as ``terminal`` was), ``how`` says in words what
would settle it (a physical claim's written test, the older ``note``), and
``evaluators`` names the evaluators it expects — a cross-check, never coverage.
In memory the claim stays flat (``models.CLAIM_MECHANISM``): ``Claim.terminal``
is ``by``, ``Claim.note`` is ``how``. The classes here try to break what that
must not move:

* ``TheSealSurvivesTheNewSpelling`` (invariant 11) — the sealed claim digest a
  person's pass is bound to keeps its P2.5a form, so a claim file moved to the
  mechanism form stays bound; the pointers and the expectations are not sealed.
* ``TheMechanismMovesNoKey`` (invariant 7) — both spellings key a gate alike; a
  requirement edit re-keys only the gates that read the requirements, and a
  mechanism or pointer edit only those that read that claim (``ctx.ledger
  .claim(id)``) or the claims whole.
* ``AMechanismNeverMovesAStatus`` (invariant 4) — the evaluators a mechanism
  names add no evaluator to a claim and move no status (S-37: a claim file that
  held coverage was rewritten by ``check`` on every run).

What slipped through before (the design read of decision 13): the evaluator
list was to join coverage, which would have let a word in a claim file settle
it; and renaming ``terminal``/``note`` would have moved the seal under every
recorded physical pass, so each read "test it again".

Expected values are typed literals, never computed with the code under test
(D-7); the digests were taken at 94b9963, before phase 1.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil
import tempfile
import unittest
from typing import Any, Callable
from unittest import mock

import _env
import _physical as P
import test_invariants as TI
from nopekit import cli as cli_mod
from nopekit import claims as claims_mod
from nopekit import store, verdicts
from nopekit.models import Acceptance, Claim, ClaimKind, Ledger, Requirement
from nopekit.util import NopekitError


#: `claims.claim_digest(Claim.from_dict(d))` for each older-spelled dict, at
#: 94b9963 — the seal every recorded result and attribution is bound to.
SEALED: tuple[tuple[dict, str], ...] = (
    ({"id": "C8", "statement": "Safe to mount above a sleeping area", "kind": "assumption",
      "terminal": "human", "authority": "Dana Reviewer", "rationale": "r"},
     "f520d21a54cfe8b277dc0225721ae85411d1b70449117906c7bb3cc3147f8226"),
    ({"id": "C9", "statement": "The printed hook holds a coat for a month", "kind": "physical",
      "note": "a coat on the hook for thirty days; look for creep at the root"},
     "3ba88d4731cdcd3319558eae57e8721265f32b301875f3f076c517b67e0ff14a"),
    ({"id": "C1", "statement": "Tip sags no more than 0.5 mm at rated load",
      "kind": "measurable", "terminal": "solver",
      "acceptance": {"quantity": "tip deflection", "comparator": "<=", "limit": 0.5,
                     "units": "mm"}},
     "f767558b27bb53ca2b8586c02e04ae4963066ab0a1c056c494e7b15279661c23"),
    ({"id": "C5", "statement": "Survives two winters outdoors without UV embrittlement",
      "kind": "physical", "note": "outdoor rack, two winters, visual check of the root for "
                                  "crazing"},
     "6c7067ec434bf183f9c8ad3d2f7a2e0c3e7b0908386b319bf9c0e4e1fd9ce927"),
)

#: `verdicts._claim_digest` (what a gate reading a claim keys on) and
#: `claims.claim_digest` for claims built in memory, at 94b9963.
RECORD_FORM: tuple[tuple[Callable[[], Claim], str, str], ...] = (
    (lambda: Claim(id="C1", statement="Tip sags no more than 0.5 mm at rated load",
                   acceptance=Acceptance(quantity="tip deflection", limit=0.5, units="mm"),
                   tags=["stiffness"]),
     "22e2e638644f7147d7599a955d1f6dfb6cb0b2c6bafe1c2a0d6cbc9e2621813d",
     "f767558b27bb53ca2b8586c02e04ae4963066ab0a1c056c494e7b15279661c23"),
    (lambda: Claim(id="C5", statement="Survives two winters outdoors", kind=ClaimKind.PHYSICAL,
                   note="outdoor rack, two winters"),
     "679262b3c3a692b574956ec5d99b88af16b05a0a9128361682db1670e380760a",
     "6f28b9e6a379b6ca1f593e3c0716eb432097ab834d18dac042d5046bb8bd9449"),
    (lambda: Claim(id="C9", statement="Meets the venue fire rules", kind=ClaimKind.PHYSICAL,
                   terminal="human", authority="Dana Reviewer", note="the venue checklist"),
     "9a69adcf45e0ac476dc4ae1da9a38f2a85dfe4b0d992bb70f5a0d96b615f4e6f",
     "c6fd25210e70910ded177ba2c550b97d2b64516191c45d62862170d2d51affe9"),
    (lambda: Claim(id="C6", statement="The load is static", kind=ClaimKind.ASSUMPTION,
                   rationale="no fatigue term"),
     "600d7dfe030cbe9af964724d6d60267673d66a777a797f7a8034ea6925346d97",
     "1c6b23c2bf3d576ffe82799cd58be65d35558a91cf7ce87be65d4fd5b7a5cd98"),
)


def mechanism_form(data: dict, *, mixed: bool = False) -> dict:
    """``data`` respelled: ``terminal`` -> ``mechanism.by``, ``note`` ->
    ``mechanism.how``; ``mixed`` moves only ``note`` (one spelling per member)."""
    out = {k: v for k, v in data.items() if k not in ("terminal", "note")}
    mechanism = {}
    if "terminal" in data:
        if mixed:
            out["terminal"] = data["terminal"]
        else:
            mechanism["by"] = data["terminal"]
    if "note" in data:
        mechanism["how"] = data["note"]
    if mechanism:
        out["mechanism"] = mechanism
    return out


def read_as_file(data: dict, root: str | None = None) -> Claim:
    """``data`` written as ``claims/<id>.json`` and read back by the strict reader."""
    root = root or tempfile.mkdtemp(prefix="nopekit-mechanism-")
    path = os.path.join(root, "claims", f"{data['id']}.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({k: v for k, v in data.items() if k != "id"}, fh)
    return store.read_record(path, "claims")


def seal_problems(digest: Callable[[Claim], str]) -> list[str]:
    """Every way ``digest`` (a `claim_digest`) fails invariant 11 across the new
    spelling: a pinned seal moved in either spelling; the pointers or the
    expectations sealed (a re-test asked for nothing a person attested); a
    changed ``how`` or ``by`` not sealed (a pass surviving an edit of its test)."""
    out: list[str] = []
    root = tempfile.mkdtemp(prefix="nopekit-seal-")
    try:
        for data, want in SEALED:
            for label, form in (("older keys", data), ("mechanism", mechanism_form(data)),
                                ("mixed", mechanism_form(data, mixed=True))):
                got = digest(read_as_file(form, root))
                if got != want:
                    out.append(f"{data['id']} in the {label} spelling seals {got[:12]}, "
                               f"not {want[:12]}")
            pointed = dict(mechanism_form(data), requirements=["R1", "R2"])
            pointed.setdefault("mechanism", {})["evaluators"] = ["acme.span"]
            if digest(read_as_file(pointed, root)) != want:
                out.append(f"{data['id']}: naming evaluators or requirements moved the seal")
        base = Claim.from_dict(SEALED[1][0])
        if digest(dataclasses.replace(base, note="a different test")) == digest(base):
            out.append("a changed `how` is not sealed")
        if digest(dataclasses.replace(base, terminal="human")) == digest(base):
            out.append("a changed `by` is not sealed")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    return out


# --------------------------------------------------------------------------- #
# invariant 11
# --------------------------------------------------------------------------- #
class TheSealSurvivesTheNewSpelling(_env.EnvCase):
    """(invariant 11) The seal keeps its P2.5a form — ``terminal`` is
    ``mechanism.by``, ``note`` is ``mechanism.how`` — so a claim file moved to the
    mechanism form stays bound, and only an edit of what a person attested
    reads Stale."""

    def test_the_seal_form_is_pinned(self):
        for data, want in SEALED:
            with self.subTest(claim=data["id"]):
                self.assertEqual(claims_mod.claim_digest(Claim.from_dict(data)), want)
        for make, _form, want in RECORD_FORM:
            claim = make()
            with self.subTest(claim=claim.id, built="in memory"):
                self.assertEqual(claims_mod.claim_digest(claim), want)
        self.assertEqual(seal_problems(claims_mod.claim_digest), [])

    def test_pointers_and_expectations_are_not_sealed(self):
        base = Claim.from_dict(SEALED[1][0])
        self.assertEqual(
            claims_mod.claim_digest(dataclasses.replace(base, evaluators=["acme.span"],
                                                        requirements=["R1"])),
            SEALED[1][1])

        real = claims_mod.claim_digest

        def seals_requirements(claim: Claim) -> str:
            return real(claim) + ",".join(getattr(claim, "requirements", None) or ())

        def drops_how(claim: Claim) -> str:
            return real(dataclasses.replace(claim, note=""))

        for label, planted in (("seals the requirements", seals_requirements),
                               ("drops the how", drops_how)):
            with self.subTest(planted=label):
                self.assertTrue(seal_problems(planted), f"a digest that {label} was accepted")

    def test_a_recorded_pass_stays_bound_across_the_rewrite(self):
        """End to end, a person's shell (a pty): C5 written as an older spine
        wrote it (a top-level ``note``), a pass recorded on it, then the file
        rewritten by hand to the mechanism form with the requirement it serves —
        still Checked on its article. Then its test edited: Stale, claim-moved."""
        root = P.project(os.path.join(self.tmp(), "b"))
        P.edit_claim(root, "C5", mechanism=None, requirements=None, note=P.C5_NOTE)
        P.tty(root, "claim", "physical", "C5", "pass", "--detail", "no cracking",
              "--evidence", P.EVIDENCE, answer="C5", code=0)

        def reads() -> tuple[str, str]:
            doc = json.loads(P.run(root, "status", "--json", code=0).stdout)
            return doc["claims"]["C5"], doc["statuses"]["C5"]["cause"]

        self.assertEqual(reads(), ("verified", "on-article"))
        P.edit_claim(root, "C5", note=None, mechanism={"how": P.C5_NOTE},
                     requirements=["R3"])
        self.assertEqual(reads(), ("verified", "on-article"),
                         "the same claim, respelled, must stay bound")
        P.edit_claim(root, "C5", mechanism={"how": "a glance at the root after one winter"})
        self.assertEqual(reads(), ("stale", "claim-moved"))


# --------------------------------------------------------------------------- #
# invariant 7
# --------------------------------------------------------------------------- #
#: Four planted readers: what a gate reading the requirements, a goalpost, one
#: claim and the claims whole would record through ``ctx.ledger``. ``g.one``
#: (review of phase 1): CLAUDE.md said a mechanism or pointer edit re-keyed only
#: the whole-claims readers, and with no single-claim reader here nothing held
#: the sentence — a gate that read `claim("C1")` re-keys too.
READERS: dict[str, Callable[[Any], Any]] = {
    "g.req": lambda view: list(view.requirements),
    "g.acc": lambda view: view.acceptance("C1"),
    "g.one": lambda view: view.claim("C1"),
    "g.all": lambda view: list(view.claims),
}


def _ledger() -> Ledger:
    return Ledger(
        claims=[Claim(id="C1", statement="Tip sags no more than 0.5 mm",
                      acceptance=Acceptance(quantity="tip deflection", limit=0.5, units="mm"),
                      note="closed-form cantilever deflection", requirements=["R1"]),
                Claim(id="C5", statement="Survives two winters", kind=ClaimKind.PHYSICAL)],
        requirements=[Requirement(id="R1", statement="It holds the pump", source="interview"),
                      Requirement(id="R2", statement="It does not buzz",
                                  source="interview")])


def _keyed(ledger: Ledger, reader: Callable[[Any], Any]) -> dict[str, str]:
    trace = verdicts.GateTrace()
    reader(verdicts.LedgerView(ledger, trace))
    return dict(trace.ledger)


#: Each edit, and the readers it must re-key — exactly those.
EDITS: tuple[tuple[str, Callable[[Ledger], None], set], ...] = (
    ("a requirement's words",
     lambda ledger: setattr(ledger.requirements[0], "statement", "It holds the pump, still"),
     {"g.req"}),
    ("a requirement added",
     lambda ledger: ledger.requirements.append(Requirement(id="R3", statement="It survives")),
     {"g.req"}),
    ("a claim's pointer", lambda ledger: setattr(ledger.claims[0], "requirements", ["R1", "R2"]),
     {"g.one", "g.all"}),
    ("a claim's how", lambda ledger: setattr(ledger.claims[0], "note", "a finite element run"),
     {"g.one", "g.all"}),
    ("a claim's evaluators", lambda ledger: setattr(ledger.claims[0], "evaluators", ["g.x"]),
     {"g.one", "g.all"}),
    ("another claim's evaluators",
     lambda ledger: setattr(ledger.claims[1], "evaluators", ["g.x"]), {"g.all"}),
    ("C1's limit", lambda ledger: setattr(ledger.claims[0], "acceptance",
                                          Acceptance(quantity="tip deflection", limit=0.75,
                                                     units="mm")),
     {"g.acc", "g.one", "g.all"}),
)


def rekey_problems() -> list[str]:
    """Every edit that re-keys another set of readers than ``EDITS`` says, and
    every reader that recorded nothing (a read nobody traced is never stale)."""
    out: list[str] = []
    for label, edit, want in EDITS:
        before = _ledger()
        keyed = {gid: _keyed(before, reader) for gid, reader in READERS.items()}
        for gid, reads in keyed.items():
            if not reads:
                out.append(f"{gid} recorded no read")
        after = _ledger()
        edit(after)
        moved = {gid for gid, reads in keyed.items()
                 if any(verdicts._ledger_now(after, key) != digest
                        for key, digest in reads.items())}
        if moved != want:
            out.append(f"{label} re-keyed {sorted(moved)}, not {sorted(want)}")
    return sorted(set(out))


class TheMechanismMovesNoKey(unittest.TestCase):
    """(invariant 7) A verdict is keyed by what its gate read: both spellings of a
    claim key it alike, a claim that names no mechanism members digests as
    before phase 1, and an edit re-keys exactly the gates that read what moved."""

    def test_the_record_form_is_pinned(self):
        for make, form, sealed in RECORD_FORM:
            claim = make()
            with self.subTest(claim=claim.id):
                self.assertEqual(verdicts._claim_digest(claim), form)
                self.assertEqual(verdicts._claim_digest(
                    dataclasses.replace(claim, evaluators=[], requirements=[])), form)

    def test_both_spellings_key_alike(self):
        root = tempfile.mkdtemp(prefix="nopekit-spellings-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        judged = {"id": "C9", "statement": "Meets the venue fire rules", "kind": "physical",
                  "terminal": "human", "authority": "Dana Reviewer",
                  "note": "the venue checklist"}
        for data in (judged, *(d for d, _w in SEALED)):
            forms = {label: read_as_file(form, root) for label, form in (
                ("older keys", data), ("mechanism", mechanism_form(data)),
                ("mixed", mechanism_form(data, mixed=True)))}
            with self.subTest(claim=data["id"]):
                self.assertEqual(len({verdicts._claim_digest(c) for c in forms.values()}), 1)
                self.assertEqual(len({verdicts._ledger_digest("claims", [c])
                                      for c in forms.values()}), 1)
        self.assertEqual(verdicts._claim_digest(read_as_file(mechanism_form(judged), root)),
                         RECORD_FORM[2][1])

    def test_a_requirement_edit_re_keys_only_its_readers(self):
        self.assertEqual(rekey_problems(), [])

    def test_an_untraced_requirements_read_is_caught(self):
        untraced = verdicts._LEDGER_WHOLE - {"requirements"}
        with mock.patch.object(verdicts, "_LEDGER_WHOLE", untraced):
            found = rekey_problems()
        self.assertIn("g.req recorded no read", found)

    def test_a_single_claim_key_blind_to_the_mechanism_is_caught(self):
        """Planted: a `claim:<id>` digest that drops the pointers and the how —
        the sentence CLAUDE.md said before review. The table catches it."""
        real = verdicts._claim_digest

        def blind(claim):
            return real(dataclasses.replace(claim, note="", evaluators=[], requirements=[]))

        with mock.patch.object(verdicts, "_claim_digest", blind):
            found = rekey_problems()
        self.assertIn("a claim's how re-keyed ['g.all'], not ['g.all', 'g.one']", found)


# --------------------------------------------------------------------------- #
# invariant 4
# --------------------------------------------------------------------------- #
def _named(ledger: Ledger, evaluators: list[str]) -> Ledger:
    return dataclasses.replace(ledger, claims=[
        dataclasses.replace(c, evaluators=list(evaluators)) for c in ledger.claims])


def status_moves(compositions: Callable[..., dict]) -> list[str]:
    """Every claim of the every-status ledger whose composition moves when its
    mechanism names evaluators — unregistered (``acme.none``), registered and
    filed elsewhere (``g.k1``, K1's), or its own. (A ``how`` is not among them:
    it is sealed, invariant 11, so editing it moves a judged claim back to Gap
    — `TheSealSurvivesTheNewSpelling` holds that half.)"""
    ledger, reg, owners, stale = TI._every_status_ledger()
    base = compositions(ledger, registry=reg, owners=owners, stale_gates=stale)
    out: list[str] = []
    for label, names in (("unregistered", ["acme.none"]), ("filed elsewhere", ["g.k1"]),
                         ("its own", None)):
        if names is None:
            named = dataclasses.replace(ledger, claims=[
                dataclasses.replace(c, evaluators=[f"g.{c.id.lower()}"])
                for c in ledger.claims])
        else:
            named = _named(ledger, names)
        got = compositions(named, registry=reg, owners=owners, stale_gates=stale)
        for cid, found in got.items():
            if found != base[cid]:
                out.append(f"{cid} ({label}): {base[cid].status.value}/{base[cid].cause.value}"
                           f" -> {found.status.value}/{found.cause.value}")
    return out


class AMechanismNeverMovesAStatus(unittest.TestCase):
    """(invariant 4) The evaluators a claim's mechanism names are a cross-check:
    they add no evaluator to a claim, and no status moves — whatever they name."""

    def test_every_status_is_unmoved(self):
        self.assertEqual(status_moves(claims_mod.compositions), [])

    def test_a_passing_evaluator_filed_elsewhere_settles_nothing(self):
        ledger, reg, owners, stale = TI._every_status_ledger()
        named = _named(ledger, ["g.k1"])
        found = claims_mod.compositions(named, registry=reg, owners=owners,
                                        stale_gates=stale)["K6"]
        self.assertEqual((found.status.value, found.cause.value), ("unclaimed", "no-evaluator"))
        self.assertEqual([p.kind for p in claims_mod.mechanism_problems(named, reg)
                          if p.claim == "K6"], ["uncovered"])

    def test_a_resolver_that_counts_the_mechanism_is_caught(self):
        real_compose = claims_mod.compose

        def counted(ledger, *, registry=None, stale=False, stale_gates=(), owners=None):
            covered = claims_mod.effective_gates(ledger, registry)
            out = {}
            for claim in ledger.claims:
                named = list(getattr(claim, "evaluators", None) or ())
                vouched = [dataclasses.replace(v, claims=[*v.claims, claim.id])
                           if v.gate in named else v for v in ledger.verdicts]
                claim = dataclasses.replace(
                    claim, gates=sorted(set(covered.get(claim.id, [])) | set(named)))
                out[claim.id] = real_compose(claim, vouched, stale=stale,
                                             stale_gates=frozenset(stale_gates),
                                             owners=owners)
            return out

        moved = status_moves(counted)
        self.assertTrue(any(p.startswith("K6 (filed elsewhere): unclaimed/no-evaluator -> "
                                         "pass/") for p in moved), moved)


# --------------------------------------------------------------------------- #
# not an invariant class: the reader's rules
# --------------------------------------------------------------------------- #
class _ReaderCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="nopekit-mechanism-reader-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def read(self, data: dict, cid: str = "C1") -> Claim:
        return read_as_file(dict(data, id=cid), self.root)

    def refused(self, data: dict, *needles: str, cid: str = "C1") -> str:
        with self.assertRaises(NopekitError) as caught:
            self.read(data, cid)
        text = str(caught.exception)
        self.assertIn(f"claims/{cid}.json", text)
        for needle in needles:
            self.assertIn(needle, text)
        return text


class AMechanismCannotLowerTheBar(_ReaderCase):
    """``mechanism.by`` is held to ``TERMINALS_BY_KIND`` exactly as ``terminal``
    is (``test_physical.ATerminalCannotLowerTheBar``), and each refusal names the
    spelling the file used."""

    def test_each_pair_outside_the_table_is_refused(self):
        rows = {
            "measurable + human": ({"statement": "s", "mechanism": {"by": "human"}},
                                   "closed_form, solver, datasheet"),
            "physical + none": ({"statement": "s", "kind": "physical",
                                 "mechanism": {"by": "none"}}, "measurement, human"),
            "assumption + solver": ({"statement": "s", "kind": "assumption",
                                     "mechanism": {"by": "solver"}}, "none, human"),
        }
        for label, (data, allowed) in rows.items():
            with self.subTest(label):
                self.refused(data, '"mechanism.by"', allowed, "never lower it")

    def test_a_display_word_is_refused_with_its_value(self):
        self.refused({"statement": "s", "mechanism": {"by": "simulation"}},
                     '"mechanism.by" "simulation" is not a terminal', '"solver"')

    def test_an_authority_needs_a_human_by(self):
        text = self.refused({"statement": "s", "kind": "physical", "authority": "Dana",
                             "mechanism": {"by": "measurement"}}, '"authority"')
        self.assertIn('"mechanism": {"by": "human"}', text)
        judged = self.read({"statement": "s", "kind": "physical", "authority": "Dana",
                            "mechanism": {"by": "human", "how": "the venue checklist"}})
        self.assertEqual((judged.terminal, judged.authority, judged.note),
                         ("human", "Dana", "the venue checklist"))

    def test_a_declared_automated_by_composes_as_undeclared(self):
        claim = self.read({"statement": "s", "mechanism": {"by": "closed_form"}})
        self.assertEqual(claims_mod.terminal_of(claim), "")


class BothSpellingsRead(_ReaderCase):
    """The older ``terminal`` and ``note`` read as ``by`` and ``how``; one member
    said under both names, an unknown member, a top-level ``evaluators`` and a
    malformed member are refused; the writer folds the mechanism at ``note``'s
    slot and writes the requirements last."""

    def test_each_refusal_names_its_fix(self):
        rows = (
            ({"statement": "s", "evaluators": ["g.a"]}, '"evaluators" belongs inside "mechanism"'),
            ({"statement": "s", "mechanism": "closed form"}, '"mechanism" must be an object'),
            ({"statement": "s", "mechanism": {"hwo": "x"}},
             'unknown key "hwo" at mechanism (did you mean "how"?)'),
            ({"statement": "s", "terminal": "solver", "mechanism": {"by": "solver"}},
             '"terminal" and "mechanism.by" both say'),
            ({"statement": "s", "note": "x", "mechanism": {"how": "x"}},
             '"note" and "mechanism.how" both say'),
            ({"statement": "s", "mechanism": {"how": 3}}, '"mechanism.how" must be text'),
            ({"statement": "s", "mechanism": {"evaluators": "g.a"}},
             '"mechanism.evaluators" must be a list'),
            ({"statement": "s", "mechanism": {"evaluators": [" g.a"]}},
             '"mechanism.evaluators"[0] " g.a" is not an evaluator id'),
            ({"statement": "s", "mechanism": {"evaluators": ["g.a", "g.a"]}},
             '"mechanism.evaluators" names g.a twice'),
            ({"statement": "s", "mechansim": {"how": "x"}},
             'unknown key "mechansim" (did you mean "mechanism"?)'),
        )
        for data, needle in rows:
            with self.subTest(needle):
                self.refused(data, needle)

    def test_an_empty_mechanism_reads_as_absent(self):
        claim = self.read({"statement": "s", "mechanism": {}})
        self.assertEqual((claim.terminal, claim.note, claim.evaluators), ("", "", []))

    def test_different_members_in_different_spellings_read(self):
        claim = self.read({"statement": "s", "kind": "physical", "terminal": "human",
                           "authority": "Dana", "mechanism": {"how": "the checklist",
                                                              "evaluators": ["g.a"]}})
        self.assertEqual((claim.terminal, claim.note, claim.evaluators),
                         ("human", "the checklist", ["g.a"]))

    def test_the_lenient_reader_reads_the_mechanism(self):
        claim = Claim.from_dict({"id": "C1", "statement": "s",
                                 "mechanism": {"by": "solver", "how": "h",
                                               "evaluators": ["g.a"]}})
        self.assertEqual((claim.terminal, claim.note, claim.evaluators),
                         ("solver", "h", ["g.a"]))

    def test_the_writer_folds_at_the_notes_slot(self):
        claim = Claim(id="C1", statement="s", tags=["t"], note="the how", terminal="solver",
                      owner="Sam", evaluators=["g.a"], requirements=["R1"])
        path = store.write_record(self.root, "claims", claim)
        with open(path, encoding="utf-8") as fh:
            pairs = json.load(fh, object_pairs_hook=list)
        self.assertEqual([k for k, _v in pairs],
                         ["statement", "kind", "tags", "mechanism", "owner", "requirements"])
        self.assertEqual(dict(pairs)["mechanism"],
                         [("by", "solver"), ("how", "the how"), ("evaluators", ["g.a"])])
        with open(path, "rb") as fh:
            first = fh.read()
        store.write_record(self.root, "claims", store.read_record(path, "claims"))
        with open(path, "rb") as fh:
            self.assertEqual(fh.read(), first, "a second write changed a byte")

    def test_a_claim_with_no_mechanism_writes_todays_bytes(self):
        claim = Claim(id="C2", statement="s", tags=["t"])
        path = store.write_record(self.root, "claims", claim)
        with open(path, encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), {"statement": "s", "kind": "measurable",
                                             "tags": ["t"]})

    def test_the_index_row_shows_the_mechanism(self):
        root = os.path.join(self.root, "p")
        os.makedirs(root)
        _env.nopekit(["init", "--name", "p"], cwd=root)
        with open(os.path.join(root, "claims", "C1.json"), "w", encoding="utf-8") as fh:
            json.dump({"statement": "s", "kind": "physical", "note": "a look"}, fh)
        (row,) = store.build_index(root)["claims"]
        self.assertEqual(row["mechanism"], {"how": "a look"})
        self.assertNotIn("note", row)


def advice_problems(text: str) -> list[str]:
    """Every mechanism warning in ``text`` that advises changing coverage to
    match the list — tagging the claim for the evaluator it names. Tags are
    coverage; the list is a cross-check (S-37), so the only fixes are the name,
    or an evaluator that computes the claim's own quantity."""
    import re
    return [line for line in text.splitlines()
            if "mechanism names" in line and re.search(r"\btag", line)]


class MechanismWarnings(_env.EnvCase):
    """``check`` and ``doctor`` warn when a mechanism names an evaluator that is
    not registered here or does not cover the claim; no status moves and the
    exit code is unchanged."""

    def test_check_and_doctor_warn_and_move_nothing(self):
        root = P.project(os.path.join(self.tmp(), "b"))
        before = P.run(root, "check", "--json", code=1)
        doc_before = json.loads(before.stdout)
        path = os.path.join(root, "claims", "C3.json")
        mechanism = P.read_json(path)["mechanism"]
        P.edit_claim(root, "C3", mechanism=dict(
            mechanism, evaluators=["bracket.bearing", "acme.span", "bracket.deflection"]))
        text = P.run(root, "check", code=1).stdout
        self.assertIn("warning: C3's mechanism names acme.span, which is not registered "
                      "here — no status moves", text)
        self.assertRegex(text, r"(?m)^warning: C3's mechanism names bracket\.deflection, which "
                               r"is not one of C3's evaluators \(it is filed under [^)]*"
                               r"stiffness[^)]*\) — no status moves; it settles another "
                               r"claim's quantity: fix the name in claims/C3\.json")
        self.assertEqual(advice_problems(text), [])
        doc = json.loads(P.run(root, "check", "--json", code=1).stdout)
        self.assertEqual([(p["claim"], p["evaluator"], p["kind"])
                          for p in doc["mechanism_problems"]],
                         [("C3", "acme.span", "unregistered"),
                          ("C3", "bracket.deflection", "uncovered")])
        self.assertEqual(doc["summary"]["counts"], doc_before["summary"]["counts"])
        doctor = json.loads(P.run(root, "doctor", "--json", code=0).stdout)
        (row,) = [r for r in doctor["checks"] if r["check"] == "mechanisms"]
        self.assertEqual(row["status"], "warn")

    def test_no_warning_advises_tagging(self):
        """(review of phase 1) Following "tag C7 for it" made C7 (first mode)
        read Checked on the bearing-stress pass. Every mechanism string, and a
        planted one in the older words, through the checker."""
        from nopekit import report as report_mod
        problem = claims_mod.MechanismProblem(claim="C7", evaluator="bracket.bearing",
                                              kind="uncovered",
                                              filed=("structural", "bearing"))
        said = report_mod.HUMAN["mechanism"]
        words = report_mod.mechanism_problem_words(problem)
        self.assertEqual(advice_problems("warning: " + words), [])
        for key in ("unregistered", "uncovered", "doctor_warn"):
            with self.subTest(key=key):
                self.assertNotRegex(said[key], r"\btag")
        older = ("warning: C7's mechanism names bracket.bearing, which is not one of C7's "
                 "evaluators (it is filed under structural) — no status moves; tag C7 for "
                 "it, or fix the name in claims/C7.json")
        self.assertEqual(advice_problems(older), [older])

    def test_doctor_names_an_unserved_requirement(self):
        root = P.project(os.path.join(self.tmp(), "b"))
        P.write_json(os.path.join(root, "requirements", "R5.json"),
                     {"statement": "It looks tidy", "source": "interview"})
        doctor = json.loads(P.run(root, "doctor", "--json", code=0).stdout)
        (row,) = [r for r in doctor["checks"] if r["check"] == "requirements"]
        self.assertEqual(row["status"], "warn")
        self.assertIn("R5", row["detail"])


def label_problems(markdown: str, label: str) -> list[str]:
    """Every report line that labels a mechanism twice — its own bold label,
    then ``label`` (`HUMAN["mechanism"]["line"]`'s, review of phase 1:
    `**Mechanism:** mechanism: automated — …`)."""
    return [line for line in markdown.splitlines()
            if "**Mechanism:**" in line and line.split("**Mechanism:**", 1)[1].lstrip()
            .startswith(label)]


class TheMechanismIsLabelledOnce(unittest.TestCase):
    """The report's gap section labels a claim's mechanism once; `gap` keeps
    its `mechanism:` label, `why` its MECHANISM heading."""

    def test_the_bracket_report(self):
        from nopekit import report as report_mod
        ledger = store.load(os.path.join(_env.REPO, "examples", "bracket"))
        label = report_mod.HUMAN["mechanism"]["line"].split("{", 1)[0]
        md = report_mod.render_markdown(ledger, None)
        self.assertIn("  - **Mechanism:** automated — A closed-form estimate", md)
        self.assertEqual(label_problems(md, label), [])
        self.assertTrue(report_mod.mechanism_line(ledger.claim("C7")).startswith(
            "mechanism: automated — "))
        real = report_mod.mechanism_body
        with mock.patch.object(report_mod, "mechanism_body", lambda c: label + real(c)):
            planted = report_mod.render_markdown(ledger, None)
        self.assertEqual(len(label_problems(planted, label)), md.count("**Mechanism:**"))
        self.assertGreater(md.count("**Mechanism:**"), 1)


if __name__ == "__main__":
    unittest.main()
