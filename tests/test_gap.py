# SPDX-License-Identifier: Apache-2.0
"""`nopekit gap` lists every claim whose mechanism has yet to run (architecture
phase 1, SPEC decision 13).

Every claim is settleable; some are expensive. ``gap`` lists each claim that
reads Gap, Pending build or Assumed (``claims.MECHANISM_YET_TO_RUN``, read off
the composition ``status`` prints), physical and assumption claims included,
with its mechanism, any warning about the evaluators the mechanism names, and
the gap record that names it; ``gap --propose`` searches the packs with each
claim's quantity and its ``how``. What slipped through before: it listed only
``find_gaps``' Need records (an automated claim no evaluator covers), so the
bracket's untested outdoor claim and its unowned assumption read as no gap at
all. Still a read: no lock, no record (S-43, ``test_record_commands``).
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import io
import json
import os
import re
import tempfile
import unittest
from typing import Any
from unittest import mock

import _env
import _physical as P
import _projects
import test_invariants as TI
from nopekit import claims as claims_mod
from nopekit import cli as cli_mod
from nopekit import gates as gates_mod
from nopekit import packs as packs_mod
from nopekit import report as report_mod
from nopekit.models import ClaimStatus, Need, PackManifest

#: The bracket's `gap`, verbatim: three claims in severity order, each with its
#: mechanism, C7 with its gap record, then the footer.
BRACKET_GAP = (
    "[gap  ] C6 The load is static and centred on the arm — no owner recorded\n"
    "        mechanism: assumption — Watch what the shelf carries for a month: a load off "
    "the arm's centre line, or one that moves, fails this\n"
    "[gap  ] C7 First mode is clear of the pump that sits on the sh… — no evaluator\n"
    "        mechanism: automated — A closed-form estimate of the arm's first natural "
    "frequency with the shelf and the pump at its tip, against the pump's 50 Hz with "
    "margin\n"
    "        gap record N-C7 first mode (identified)\n"
    "[build] C5 Survives two winters outdoors without UV embrittlem… — needs an article\n"
    "        mechanism: measurement — Hang a printed bracket on an outside wall through two "
    "winters, then hang the rated 15 N on its tip and look at the root for cracks, crazing "
    "or whitening\n"
    "3 claims whose mechanism has yet to run: 2 gaps · 1 pending build. Name the quantity, "
    "try the analytic answer first, and only then propose a solver — with its real cost "
    "said out loud.\n")


def _tree(root: str) -> dict[str, str]:
    out = {}
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            path = os.path.join(base, name)
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            if rel == ".nopekit/ledger.json":
                continue                  # the ignored index a read may refresh
            with open(path, "rb") as fh:
                out[rel] = hashlib.sha256(fh.read()).hexdigest()
    return out


class GapListsEveryClaimWhoseMechanismHasYetToRun(_env.EnvCase):

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        import tempfile
        cls.root = _projects.bracket_copy(os.path.join(
            tempfile.mkdtemp(prefix="nopekit-gap-"), "b"), migrated=True)

    def gap(self, *args: str) -> str:
        proc = _env.nopekit(["gap", *args], cwd=self.root)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        return proc.stdout

    def test_the_bracket(self):
        self.assertEqual(self.gap(), BRACKET_GAP)

    def test_what_is_listed_is_the_compositions(self):
        ledger, reg, owners, stale = TI._every_status_ledger()
        composed = claims_mod.compositions(ledger, registry=reg, owners=owners,
                                           stale_gates=stale)
        listed = claims_mod.yet_to_run(ledger, composed)
        self.assertEqual({composed[c.id].status for c in listed},
                         {ClaimStatus.UNCLAIMED, ClaimStatus.UNVERIFIED, ClaimStatus.ASSERTED})
        self.assertEqual([c.id for c in listed],
                         ["K6", "K7", "K8", "K9", "K10", "K13", "K14", "K15", "K19", "K20",
                          "K23", "K24", "K29"])
        self.assertIn("K15", [c.id for c in listed], "an owned assumption is listed, assumed")
        for cid in ("K1", "K2", "K4", "K5", "K11", "K12", "K30"):
            self.assertNotIn(cid, [c.id for c in listed])

    def test_the_json_keeps_its_keys_and_adds_the_claims(self):
        doc = json.loads(self.gap("--json"))
        self.assertEqual([n["claim_ids"] for n in doc["gaps"]], [["C7"]])
        self.assertEqual(doc["n_gaps"], 1)
        self.assertEqual([(r["id"], r["key"], r["need"]) for r in doc["yet_to_run"]],
                         [("C6", "gap", None), ("C7", "gap", "N-C7"),
                          ("C5", "pending_build", None)])
        self.assertEqual(doc["n_yet_to_run"], 3)
        c5 = doc["yet_to_run"][2]
        self.assertEqual(c5["mechanism"]["by"], "")
        self.assertEqual(c5["by_word"], "measurement")
        self.assertTrue(c5["mechanism"]["how"].startswith("Hang a printed bracket"))

    def test_propose_says_a_pack_settles_only_a_modelled_part(self):
        text = self.gap("--propose")
        self.assertIn("        a pack's evaluator can check a modelled part of C5; its pass "
                      "never settles C5 — measurement does\n", text)
        self.assertIn("        a pack's evaluator can check a modelled part of C6; its pass "
                      "never settles C6 — assumption does\n", text)
        self.assertNotIn("modelled part of C7", text)

    def test_a_named_evaluator_that_does_not_settle_it_is_warned(self):
        root = P.project(os.path.join(self.tmp(), "warned"))
        P.edit_claim(root, "C7", mechanism={"how": "a closed-form estimate",
                                            "evaluators": ["acme.modal"]})
        text = _env.nopekit(["gap"], cwd=root).stdout
        self.assertIn("        warning: C7's mechanism names acme.modal, which is not "
                      "registered here — no status moves", text)

    def test_gap_takes_no_lock_and_writes_nothing(self):
        before = _tree(self.root)
        for args in ([], ["--json"], ["--propose"]):
            with self.subTest(args=args):
                self.gap(*args)
                self.assertEqual(_tree(self.root), before)


def gap_in_process(root: str, *args: str) -> str:
    """``nopekit gap <args>`` in this process — so a planted function reaches
    it — under the environment a test child gets (a temp ``HOME``, no user
    packs) and a fresh registry (`cli` loads into the module's)."""
    home = tempfile.mkdtemp(prefix="nopekit-gap-home-")
    saved = gates_mod.REGISTRY
    gates_mod.REGISTRY = gates_mod.Registry()
    out = io.StringIO()
    try:
        with mock.patch.dict(os.environ, _env.clean_env(home=home), clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = cli_mod.main(["gap", "-C", root, *args])
    finally:
        gates_mod.REGISTRY = saved
        _env._rmtree(home)
    if code != 0:
        raise AssertionError(f"gap {args} exited {code}: {out.getvalue()}")
    return out.getvalue()


#: The packs the bracket's C7 (first mode) is proposed under: none names "first
#: mode", so every one is found through its mechanism's how ("natural
#: frequency", "shelf", "pump"). Measured 2026-10-14 on the bundled packs.
C7_PACKS = ["fluids-analytic", "beam-analytic", "openmodelica", "thermal-analytic"]


def proposal_problems(doc: dict) -> list[str]:
    """`gap --json --propose` against decision 13: a gap record and each listed
    claim it names carry one pack list (one search), and C7's — a quantity no
    pack names — is found through its how (review of phase 1: the record was
    searched without it, `[]` beside four packs for the same need)."""
    out: list[str] = []
    listed = {r["id"]: [m["name"] for m in r["candidates_from_packs"]]
              for r in doc["yet_to_run"]}
    for need in doc["gaps"]:
        names = [m["name"] for m in need["candidates_from_packs"]]
        for cid in need["claim_ids"]:
            if cid in listed and listed[cid] != names:
                out.append(f"{need['id']} lists {names}, {cid} lists {listed[cid]}")
    if listed.get("C7") != C7_PACKS:
        out.append(f"C7 is proposed {listed.get('C7')}, not {C7_PACKS}")
    return out


class GapProposesWithTheHow(_env.EnvCase):
    """``gap --propose`` searches each claim's quantity and its how, and a gap
    record with the same search as the claims it names (decision 13)."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.root = _projects.bracket_copy(os.path.join(
            tempfile.mkdtemp(prefix="nopekit-gap-propose-"), "b"), migrated=True)

    def test_one_need_one_pack_list_found_through_the_how(self):
        doc = json.loads(gap_in_process(self.root, "--json", "--propose"))
        self.assertEqual(proposal_problems(doc), [])
        self.assertEqual([m["name"] for m in doc["gaps"][0]["candidates_from_packs"]],
                         C7_PACKS)
        text = gap_in_process(self.root, "--propose")
        block = text.split(" C7 ", 1)[1].split("\n[", 1)[0]
        self.assertEqual(re.findall(r"(?m)^ +pack +(\S+) ", block), C7_PACKS[:3])

    def test_a_search_that_drops_the_how_is_caught(self):
        real = claims_mod.proposal_query

        def no_how(claim, gaps, ledger=None):
            need, _how = real(claim, gaps, ledger)
            return need, ""

        with mock.patch.object(claims_mod, "proposal_query", no_how), \
                mock.patch.object(claims_mod, "need_how", lambda ledger, need: ""):
            doc = json.loads(gap_in_process(self.root, "--json", "--propose"))
        self.assertEqual(proposal_problems(doc), [f"C7 is proposed [], not {C7_PACKS}"])

    def test_two_lists_for_one_need_are_caught(self):
        doc = json.loads(gap_in_process(self.root, "--json", "--propose"))
        doc["gaps"][0]["candidates_from_packs"] = []
        self.assertEqual(proposal_problems(doc), [f"N-C7 lists [], C7 lists {C7_PACKS}"])


#: Every `[tag] <id>` header `gap` prints for a claim.
_HEAD = re.compile(r"^\[[^\]]+\] (?P<id>\S+) ")


def trigger_problems(text: str, settled: set[str]) -> list[str]:
    """Every claim of ``settled`` (physical, judged or assumed: its mechanism's
    `by` settles it) whose `gap --propose` block names the extension protocol's
    trigger, and a footer that says "propose a solver" over a list holding no
    automated claim (review of phase 1: EXTENSION_PROTOCOL never fires there)."""
    out: list[str] = []
    blocks: dict[str, list[str]] = {}
    current = None
    for line in text.splitlines():
        found = _HEAD.match(line)
        if found:
            current = found.group("id")
            blocks[current] = []
        elif current is not None and line.startswith(" "):
            blocks[current].append(line)
    for cid, lines in blocks.items():
        if cid in settled and any("extension protocol's trigger" in ln for ln in lines):
            out.append(f"{cid}: the protocol's trigger")
    if blocks and set(blocks) <= settled and "propose a solver" in text:
        out.append("the footer proposes a solver over settled claims only")
    return out


class TheProtocolFiresOnlyForAnAutomatedClaim(_env.EnvCase):
    """With no pack to propose, `gap --propose` names the extension protocol's
    trigger under an automated claim only; a physical, judged or assumed one is
    settled by its mechanism, and the footer says so when it is all there is."""

    def setUp(self) -> None:
        self.root = _projects.bracket_copy(os.path.join(self.tmp(), "b"), migrated=True)

    def propose(self) -> str:
        with mock.patch.object(packs_mod, "discover", lambda *a, **k: []):
            return gap_in_process(self.root, "--propose")

    def test_the_bracket_with_no_pack(self):
        text = self.propose()
        self.assertEqual(trigger_problems(text, {"C5", "C6"}), [])
        self.assertIn("        no installed pack checks a modelled part of this — and none "
                      "is needed: measurement settles it, never a solver\n", text)
        c7 = text.split(" C7 ", 1)[1].split("\n[", 1)[0]
        self.assertIn(report_mod.HUMAN["mechanism"]["no_match"], c7)
        self.assertIn("only then propose a solver", text)

    def test_settled_claims_alone(self):
        os.remove(os.path.join(self.root, "claims", "C7.json"))
        text = self.propose()
        self.assertEqual(trigger_problems(text, {"C5", "C6"}), [])
        self.assertTrue(text.endswith("2 claims whose mechanism has yet to run: 1 gap · 1 "
                                      "pending build. Each is settled by its mechanism — a "
                                      "test on an article, a person's judgment or an owner — "
                                      "never by a solver.\n"), text)

    def test_the_protocol_describes_this_gap(self):
        """The document the trigger line names says what `gap` lists now, and
        that it fires for an automated claim only."""
        path = os.path.join(_env.REPO, "docs", "EXTENSION_PROTOCOL.md")
        with open(path, encoding="utf-8") as fh:
            fires = fh.read().split("## When this fires", 1)[1].split("\n---", 1)[0]
        self.assertIn("every claim whose mechanism has yet to run", fires)
        self.assertIn("an **automated** claim", fires)
        self.assertNotIn("`nopekit gap` reports a **MEASURABLE** claim", fires)

    def test_the_trigger_under_a_settled_claim_is_caught(self):
        os.remove(os.path.join(self.root, "claims", "C7.json"))
        said = report_mod.HUMAN["mechanism"]
        older = dict(said, no_match_settled=said["no_match"], footer_settled=said["footer"])
        with mock.patch.object(report_mod, "HUMAN", {**report_mod.HUMAN, "mechanism": older}):
            text = self.propose()
        self.assertEqual(trigger_problems(text, {"C5", "C6"}),
                         ["C6: the protocol's trigger", "C5: the protocol's trigger",
                          "the footer proposes a solver over settled claims only"])


#: Logger planted beside the bracket (test_status_table's): passes everything,
#: its own known-bad control included, so `check` refuses it — and Q1, which it
#: alone covers, reads Gap only through the resolution (the cache's refusal).
LOGGER_GATE = '''\
"""Planted by tests/test_gap.py: a logger, refused at its first check."""
from nopekit.gates import gate
from nopekit.models import NegativeControl, Verdict


@gate(id="probe.logger", claims=["logger-only"],
      negative_control=NegativeControl(fixture="selftest/probe_bad.py:thin"))
def logs(ctx):
    return Verdict(gate="probe.logger", passed=True, detail="always")
'''
LOGGER_FIXTURE = '''\
"""Planted by tests/test_gap.py: the logger's known-bad control."""
import dataclasses

from nopekit.models import Ledger


def thin(ctx):
    return dataclasses.replace(ctx, params={"config": {"thickness": 1.0}},
                               ledger=Ledger(), extra={})
'''
ALONE = {"statement": "the logged quantity holds", "kind": "measurable",
         "tags": ["logger-only"], "critical": False,
         "acceptance": {"quantity": "q", "comparator": "<=", "limit": 1.0, "units": "mm"}}


def resolution_problems(status: dict, gap: dict) -> list[str]:
    """`gap --json`'s `yet_to_run` against `status --json`: the same claims,
    with the same keys — every claim `status` reads Gap, Pending build or
    Assumed, and no other (SPEC §8: `gap` resolves the cache exactly as `status`
    does)."""
    keys = {claims_mod.STATUS_KEY[s] for s in claims_mod.MECHANISM_YET_TO_RUN}
    want = {cid: v["key"] for cid, v in status["statuses"].items() if v["key"] in keys}
    got = {r["id"]: r["key"] for r in gap["yet_to_run"]}
    return [f"{cid}: status {want.get(cid)}, gap {got.get(cid)}"
            for cid in sorted(set(want) | set(got)) if want.get(cid) != got.get(cid)]


class GapResolvesAsStatusDoes(_env.EnvCase):
    """Where the verdict cache changes the answer — an evaluator `check`
    refused, so Q1 reads Gap only through the resolution — `gap` lists what
    `status` reads, and a `gap` that composes over the raw records is caught."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        tmp = tempfile.mkdtemp(prefix="nopekit-gap-resolved-")
        cls.addClassCleanup(_env._rmtree, tmp)
        cls.root = root = _projects.bracket_copy(os.path.join(tmp, "b"), migrated=True)
        for rel, text in (("gates/zz_logger.py", LOGGER_GATE),
                          ("selftest/probe_bad.py", LOGGER_FIXTURE),
                          ("claims/Q1.json", json.dumps(ALONE, indent=2))):
            with open(os.path.join(root, *rel.split("/")), "w", encoding="utf-8") as fh:
                fh.write(text)
        _env.nopekit(["check"], cwd=root)
        cls.status = json.loads(_env.nopekit(["status", "--json"], cwd=root).stdout)

    def test_gap_lists_what_status_reads(self):
        self.assertEqual(self.status["statuses"]["Q1"]["key"], "gap",
                         "the world: Q1 reads Gap only through the refusal")
        self.assertTrue(self.status["statuses"]["Q1"]["reason"].startswith("unqualified"),
                        self.status["statuses"]["Q1"])
        doc = json.loads(gap_in_process(self.root, "--json"))
        self.assertEqual(resolution_problems(self.status, doc), [])
        self.assertIn("Q1", [r["id"] for r in doc["yet_to_run"]])

    def test_a_gap_over_the_raw_records_is_caught(self):
        real = cli_mod._resolved

        def raw(root, ledger, *args, **kw):
            _view, resolution = real(root, ledger, *args, **kw)
            return ledger, dataclasses.replace(resolution, stale_gates=frozenset())

        with mock.patch.object(cli_mod, "_resolved", raw):
            doc = json.loads(gap_in_process(self.root, "--json"))
        self.assertIn("Q1: status gap, gap None", resolution_problems(self.status, doc))


def help_problems(helps: dict[str, str], tables: dict[str, str]) -> list[str]:
    """Every place that still describes `gap` as P2's (measurable claims with no
    gate) or `why` without requirements: `gap`'s and `why`'s help, and the
    command tables in README and the skill (review of phase 1)."""
    out: list[str] = []
    for where, text in {**helps, **tables}.items():
        if "gap" in where and ("no gate" in text or "mechanism" not in text):
            out.append(f"{where}: {text!r}")
        if "why" in where and "requirement" not in text:
            out.append(f"{where}: {text!r}")
    return out


def _helps() -> dict[str, str]:
    import argparse
    parser = cli_mod.build_parser()
    (sub,) = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    return {f"{c.dest} help": c.help for c in sub._choices_actions if c.dest in ("gap", "why")}


def _tables() -> dict[str, str]:
    """Each command table's row for `gap` and `why`: a code-block row (the
    command, then its words after two spaces or a `#`) or a markdown row
    (`` | `nopekit gap` | words | ``). What slipped through (README's rewrite,
    2026-10-16): only the code-block form was read, so the new markdown table
    went unread and a bare example line (`nopekit why thickness`) stood in."""
    out = {}
    for rel in ("README.md", "skills/nopekit/SKILL.md"):
        with open(os.path.join(_env.REPO, *rel.split("/")), encoding="utf-8") as fh:
            for line in fh:
                for cmd in ("gap", "why"):
                    if (re.match(rf"^\| `nopekit {cmd}\b", line)
                            or re.match(rf"^nopekit {cmd}\b.*?(\s{{2,}}|#)\S", line)):
                        out[f"{rel} {cmd}"] = line.strip()
    return out


class TheHelpDescribesTheGapItRuns(unittest.TestCase):
    """`gap` lists every claim whose mechanism has yet to run, and `why` takes a
    requirement id: their help and both command tables say so."""

    def test_the_help_and_the_tables(self):
        helps, tables = _helps(), _tables()
        self.assertEqual(set(helps), {"gap help", "why help"})
        self.assertEqual(set(tables), {"README.md gap", "README.md why",
                                       "skills/nopekit/SKILL.md gap",
                                       "skills/nopekit/SKILL.md why"})
        self.assertEqual(help_problems(helps, tables), [])
        older = {"gap help": "measurable claims no gate covers — how the system grows",
                 "why help": "one param or claim's full history, instead of the whole log"}
        self.assertEqual(len(help_problems(older, {})), 2)


class TheHowIsSearchedBelowTheQuantity(unittest.TestCase):
    """``packs.score`` with the mechanism's words: a pack named only by them
    scores above nothing, a quantity hit outranks them, and with no ``how``
    every score is what it was before phase 1."""

    PACK = PackManifest(name="modal", description="d", settles=["natural frequency"],
                        claim_classes=["vibration"])
    OTHER = PackManifest(name="beam", description="d", settles=["first mode"],
                         claim_classes=["structural"])

    def test_the_how_alone_scores(self):
        need = Need(id="", claim_ids=["C7"], quantity="first mode")
        self.assertEqual(packs_mod.score(need, self.PACK), 0.0)
        self.assertGreater(packs_mod.score(need, self.PACK,
                                           how="estimate the natural frequency"), 0.0)

    def test_a_quantity_hit_outranks_a_how_hit(self):
        need = Need(id="", claim_ids=["C7"], quantity="first mode")
        how = "estimate the natural frequency of the arm"
        self.assertGreater(packs_mod.score(need, self.OTHER, how=how),
                           packs_mod.score(need, self.PACK, how=how))
        self.assertEqual([m.name for m in packs_mod.match(need, [self.PACK, self.OTHER],
                                                          how=how)], ["beam", "modal"])

    def test_no_how_scores_as_before(self):
        need = Need(id="", claim_ids=["C1"], quantity="natural frequency",
                    claim_class="vibration")
        self.assertEqual(packs_mod.score(need, self.PACK), 19.0)
        self.assertEqual(packs_mod.score(need, self.PACK, how=""), 19.0)


if __name__ == "__main__":
    unittest.main()
