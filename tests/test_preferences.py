# SPDX-License-Identifier: Apache-2.0
"""Invariant 13 (architecture phase 2, SPEC 14): a preference counts only through
the person's channel.

A ``preferred_against`` rejection names its person in ``by`` — a nominee, like a
claim's owner — and counts only when that person records it with ``nopekit prefer
<decision>``, typed in their own shell, confirming the decision's id. Each class
below tries to make it count another way: from an agent session or a pipe, under
another identity, by ``by`` alone, by a hand-written or tampered file, or after
the rejection the person read was edited. What it closes before it could slip
through: ``decide --rejected VALUE|WHY`` recorded no who, so a preference the
agent typed into a decision would have read as the person's — invariant 11's
owner laundering, through another file.
"""
from __future__ import annotations

import ast
import dataclasses
import json
import os
import unittest
from unittest import mock

import _decisions as D
import _env

from nopekit import claims, cli, page, report, store, util
from nopekit.models import Decision, PreferenceRecord, Rejection, ReturnCondition
from nopekit.util import NopekitError


def _preferences_file(root: str) -> str:
    return os.path.join(root, "preferences", f"{D.DECISION}.json")


def _state(root: str, index: int = 2) -> str:
    """The bracket decision's rejection ``index`` as `claims.preference_state`
    reads it off a raw load: ``recorded`` or ``not-recorded``."""
    ledger = store.load(root)
    decision = next(d for d in ledger.decisions if d.id == D.DECISION)
    return claims.preference_state(decision, decision.rejected[index]).state


def _prefer(root: str, **person) -> tuple[int, str, str]:
    with D.person(**person):
        return D.main(root, "prefer", D.DECISION)


def channel_problems(command, *, first: bool = False) -> list[str]:
    """Every way ``command`` (``cli.cmd_prefer`` or a planted one) lets a
    preference in through a channel that is not the person's own shell: an agent
    marker, a pipe, another identity, no identity, a mistyped id. Each scenario
    runs on one bracket and must write nothing at all. ``first`` stops at the
    first problem: a planted violator needs only to be caught."""
    import tempfile
    problems: list[str] = []
    scenarios = [(f"marker {name}", dict(marker=name)) for name in cli.AGENT_MARKERS]
    scenarios += [("a pipe", dict(tty=False)), ("another identity", dict(who=D.PAT_WHO)),
                  ("no identity", dict(who=None)), ("a mistyped id", dict(answer="print"))]
    base = tempfile.mkdtemp(prefix="nopekit-test-")
    try:
        root = D.bracket(os.path.join(base, "b"))
        before = D.tree(root)
        for label, person in scenarios:
            with D.person(**person), \
                    mock.patch.object(cli, "build_parser", _parser_with(command)):
                code, _out, _err = D.main(root, "prefer", D.DECISION)
            if code == 0 or os.path.exists(os.path.dirname(_preferences_file(root))):
                problems.append(f"{label}: exit {code}, preferences/ "
                                f"{'written' if os.path.exists(_preferences_file(root)) else 'absent'}")
                for path in (_preferences_file(root),):
                    if os.path.exists(path):
                        os.remove(path)
            if D.tree(root) != before:
                problems.append(f"{label}: the tree moved")
            if first and problems:
                break
    finally:
        _env._rmtree(base)
    return problems


def _moved(before: dict[str, bytes], after: dict[str, bytes]) -> list[str]:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


def one_record_problems(command) -> list[str]:
    """What ``command`` (``cli.cmd_prefer`` or a planted one), run in the
    person's own shell on a fresh bracket, writes beyond its one record,
    ``preferences/<decision>.json``."""
    import tempfile
    base = tempfile.mkdtemp(prefix="nopekit-test-")
    try:
        root = D.bracket(os.path.join(base, "b"))
        before = D.tree(root)
        with D.person(), mock.patch.object(cli, "build_parser", _parser_with(command)):
            code, _out, err = D.main(root, "prefer", D.DECISION)
        if code != 0:
            return [f"exit {code}: {err.strip()}"]
        return [f"wrote {p}" for p in _moved(before, D.tree(root))
                if p != f"preferences/{D.DECISION}.json"]
    finally:
        _env._rmtree(base)


def value_problems(command) -> list[str]:
    """Every way ``command`` records a preference the person did not name, on a
    bracket whose decision names Robin for two preferred_against rejections
    (PLA, index 0, and the aluminium bracket, index 2)."""
    import tempfile
    problems: list[str] = []
    base = tempfile.mkdtemp(prefix="nopekit-test-")
    try:
        root = D.bracket(os.path.join(base, "b"))
        D.edit_rejection(root, 0, type="preferred_against", by=D.PERSON)
        before = D.tree(root)

        def run(*value: str) -> tuple[int, str]:
            with D.person(), mock.patch.object(cli, "build_parser", _parser_with(command)):
                code, _out, err = D.main(root, "prefer", D.DECISION, *value)
            return code, err

        for label, value, said in (
                ("no --value", (), "names you for 2 preferred_against rejections"),
                ("an unknown --value", ("--value", "PETG"), "names you for no "
                                                            "preferred_against rejection")):
            code, err = run(*value)
            if code != 2 or said not in err:
                problems.append(f"{label}: exit {code}, {err.strip()!r}")
            if D.tree(root) != before:
                problems.append(f"{label}: the tree moved")
                return problems
        code, err = run("--value", D.ALU)
        if code != 0:
            return problems + [f"--value: exit {code}, {err.strip()!r}"]
        written = [e["value"] for e in D.read_json(_preferences_file(root))["preferences"]]
        if written != [D.ALU]:
            problems.append(f"--value {D.ALU!r} recorded {written}")
        if (_state(root, 2), _state(root, 0)) != ("recorded", "not-recorded"):
            problems.append(f"after --value: aluminium {_state(root, 2)}, "
                            f"PLA {_state(root, 0)}")
    finally:
        _env._rmtree(base)
    return problems


#: The real command and parser, held before any test patches them.
_REAL_PREFER = cli.cmd_prefer
_REAL_PARSER = cli.build_parser


def _parser_with(func):
    """``cli.build_parser`` with ``prefer`` dispatching to ``func``."""
    real = _REAL_PARSER

    def build():
        parser = real()
        for action in parser._subparsers._group_actions:
            choice = action.choices.get("prefer")
            if choice is not None:
                choice.set_defaults(func=func)
        return parser
    return build


class APreferenceIsAPersonsAct(_env.EnvCase):
    """(13) Only the person ``by`` names records a preference, typed in their own
    shell: refused from every agent marker, a pipe, another identity or none; who
    and when are never typed; the decision's id is typed or nothing is recorded."""

    def setUp(self):
        self.root = D.bracket(os.path.join(self.tmp(), "b"))

    def test_the_person_records_it_in_their_own_shell(self):
        self.assertEqual(_state(self.root), "not-recorded")
        before = D.tree(self.root)
        code, out, err = _prefer(self.root)
        self.assertEqual(code, 0, err)
        self.assertEqual(_moved(before, D.tree(self.root)),
                         [f"preferences/{D.DECISION}.json"], "prefer wrote its one record")
        data = D.read_json(_preferences_file(self.root))
        (entry,) = data["preferences"]
        self.assertEqual((entry["channel"], entry["who"], entry["name"], entry["value"]),
                         ("interactive", D.PERSON_WHO, D.PERSON, D.ALU))
        self.assertEqual(entry["prev"], "")
        self.assertIn(f"type {D.DECISION} to record it", err)
        self.assertIn("recorded Robin Okafor's preference", out)
        self.assertIn("preferred against, recorded by Robin Okafor", out)
        self.assertEqual(_state(self.root), "recorded")
        # A repeat writes nothing, exit 0.
        before = D.read_json(_preferences_file(self.root))
        code, out, _err = _prefer(self.root)
        self.assertEqual(code, 0)
        self.assertIn("already recorded", out)
        self.assertEqual(D.read_json(_preferences_file(self.root)), before)

    def test_a_planted_prefer_that_writes_more_is_caught(self):
        """Invariant 8's clause for this writer, on a run that succeeds: a
        ``prefer`` that also rewrote the decision it read is caught by the same
        before-and-after the real one passes above."""
        def rewrites_the_decision(args):
            code = _REAL_PREFER(args)
            ledger = store.load(args.dir)
            decision = next(d for d in ledger.decisions if d.id == args.id)
            store.write_record(args.dir, "decisions", dataclasses.replace(
                decision, summary=decision.summary + " (preferred)"))
            return code

        self.assertEqual(one_record_problems(_REAL_PREFER), [])
        self.assertNotEqual(one_record_problems(rewrites_the_decision), [],
                            "a prefer that rewrote the decision was not caught")

    def test_value_names_which_alternative(self):
        """A decision that names the person for two preferred_against
        rejections: with no ``--value`` it asks which and writes nothing, an
        unknown value writes nothing, and ``--value`` records exactly the one it
        names — the other stays not recorded. What it closes before it could
        slip through: no test passed ``--value``, so a ``prefer`` that took the
        first of them would have sealed the person's act against an alternative
        they did not name."""
        self.assertEqual(value_problems(_REAL_PREFER), [])

        def takes_the_first(args):
            args.value = "PLA"
            return _REAL_PREFER(args)

        def ignores_the_value(args):
            args.value = None
            return _REAL_PREFER(args)

        for name, planted in (("takes the first", takes_the_first),
                              ("ignores --value", ignores_the_value)):
            with self.subTest(name):
                self.assertNotEqual(value_problems(planted), [], f"{name} was not caught")

    def test_every_channel_but_the_persons_is_refused(self):
        self.assertEqual(channel_problems(cli.cmd_prefer), [])

    def test_each_refusal_says_why(self):
        for person, said in ((dict(marker="CLAUDECODE"), "CLAUDECODE is set in this shell"),
                             (dict(tty=False), "stdin is not a terminal"),
                             (dict(who=D.PAT_WHO), "only the person named records it"),
                             (dict(who=None), "no git identity here"),
                             (dict(answer="print"), "you typed 'print', not print-in-petg")):
            with self.subTest(person):
                code, _out, err = _prefer(self.root, **person)
                self.assertEqual(code, 2, err)
                self.assertIn(said, err)
                self.assertFalse(os.path.exists(_preferences_file(self.root)))

    def test_who_and_when_are_refused_before_the_project_is_read(self):
        nowhere = self.tmp()
        for flag, said in (("--who", "who records a preference is read from git's identity"),
                           ("--when", "a preference is dated when it is recorded")):
            with self.subTest(flag), D.person():
                code, _out, err = D.main(nowhere, "prefer", D.DECISION, flag, "Robin Okafor")
            self.assertEqual(code, 2)
            self.assertIn(said, err)
            self.assertNotIn("no nopekit project", err)

    def test_a_planted_prefer_that_skips_the_marker_is_caught(self):
        def skips_the_marker(args):
            with mock.patch.object(cli, "_agent_marker", lambda environ: ""):
                return _REAL_PREFER(args)

        def trusts_the_tty(args):
            with mock.patch.object(cli, "_channel",
                                   lambda tty, env, answer, cid: "interactive"):
                return skips_the_marker(args)

        for name, planted in (("skips the marker", skips_the_marker),
                              ("trusts the tty", trusts_the_tty)):
            with self.subTest(name):
                self.assertNotEqual(channel_problems(planted, first=True), [],
                                    f"{name} was not caught")

    # -- left for the gate: the real terminal and the real environment ----- #
    def test_a_pty_records_it_end_to_end(self):
        env = {"GIT_AUTHOR_NAME": D.PERSON, "GIT_AUTHOR_EMAIL": "robin@example.invalid",
               "GIT_COMMITTER_NAME": D.PERSON, "GIT_COMMITTER_EMAIL": "robin@example.invalid"}
        proc = _env.run_tty(["prefer", D.DECISION], cwd=self.root, answer=D.DECISION, env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(_state(self.root), "recorded")

    def test_the_markers_end_to_end(self):
        for name in ("CLAUDECODE", "CLAUDE_CODE_SESSION_ID", "AI_AGENT"):
            with self.subTest(name):
                proc = _env.nopekit(["prefer", D.DECISION], cwd=self.root, identity=True,
                                    env={name: "1"})
                self.assertEqual(proc.returncode, 2, proc.stderr)
                self.assertIn(name, proc.stderr)
        proc = _env.nopekit(["prefer", D.DECISION], cwd=self.root, identity=True)
        self.assertIn("stdin is not a terminal", proc.stderr)
        self.assertFalse(os.path.exists(os.path.dirname(_preferences_file(self.root))))


def preference_problems(judge) -> list[str]:
    """Every entry ``judge`` (``claims.preference_state`` or a planted one) counts
    that is not the person's own act for the rejection as it reads now."""
    decision = Decision(id="d", title="Pick PETG", rejected=[
        Rejection(value="alu", why="Robin prints", type="preferred_against", by=D.PERSON,
                  returns_if=ReturnCondition(claim="C3", quantity="margin", comparator="<",
                                             value=0.1)),
        Rejection(value="PLA", why="creeps", type="infeasible")])
    item = decision.rejected[0]
    good = PreferenceRecord(decision="d", value="alu", name=D.PERSON,
                            rejection_digest=claims.rejection_digest(decision, item),
                            who=D.PERSON_WHO, when="2026-10-14T16:00:00Z", channel="interactive")
    problems: list[str] = []
    if getattr(judge(dataclasses.replace(decision, preferences=(good,)), item), "state",
               "") != "recorded":
        problems.append("the person's own entry does not count")
    cases = {
        "by alone": (),
        "a pipe": (dataclasses.replace(good, channel="non-interactive"),),
        "an agent session": (dataclasses.replace(good, channel="agent-session s1"),),
        "a legacy channel": (dataclasses.replace(good, channel=""),),
        "who is not the name": (dataclasses.replace(good, who=D.PAT_WHO),),
        "another person's": (dataclasses.replace(good, name="Pat Other", who=D.PAT_WHO),),
        "another alternative": (dataclasses.replace(good, value="PLA"),),
        "the rejection as it read before": (
            dataclasses.replace(good, rejection_digest="0" * 64),),
    }
    for label, records in cases.items():
        found = judge(dataclasses.replace(decision, preferences=records), item)
        if getattr(found, "state", "") == "recorded":
            problems.append(f"{label}: counted")
    if judge(decision, decision.rejected[1]) is not None:
        problems.append("an infeasible rejection has a preference")
    return problems


class ANomineeAloneNeverCounts(_env.EnvCase):
    """(13) ``by`` names a nominee: until the person records it, every reader says
    *preferred against, not recorded by <name>*; a sealed entry from a pipe, an
    agent session, another identity or another person never counts."""

    def test_the_judge(self):
        self.assertEqual(preference_problems(claims.preference_state), [])

    def test_planted_judges_are_caught(self):
        real = claims.preference_state

        def trusts_by(decision, rejection):
            found = real(decision, rejection)
            return found._replace(state="recorded") if found is not None else None

        def skips_the_channel(decision, rejection):
            records = tuple(dataclasses.replace(r, channel="interactive")
                            for r in decision.preferences)
            return real(dataclasses.replace(decision, preferences=records), rejection)

        def skips_the_digest(decision, rejection):
            records = tuple(dataclasses.replace(
                r, rejection_digest=claims.rejection_digest(decision, rejection))
                for r in decision.preferences)
            return real(dataclasses.replace(decision, preferences=records), rejection)

        for name, planted in (("trusts by", trusts_by), ("skips the channel", skips_the_channel),
                              ("skips the digest", skips_the_digest)):
            with self.subTest(name):
                self.assertNotEqual(preference_problems(planted), [], f"{name} was not caught")

    def test_every_reader_says_not_recorded(self):
        root = D.bracket(os.path.join(self.tmp(), "b"))
        said = "preferred against, not recorded by Robin Okafor"
        _code, out, _err = D.main(root, "why", D.DECISION)
        self.assertIn(said, out)
        _code, out, _err = D.main(root, "decide", "--title", "Keep the arm", "--summary", "s",
                                  "--rejected", "a longer arm|Robin wants it short",
                                  "--type", "preferred_against", "--by", D.PERSON)
        self.assertIn(said, out)
        self.assertIn("Robin Okafor records it in their own shell: nopekit prefer keep-the-arm",
                      out)
        for argv in (("status", "--json"), ("check", "--json")):
            _code, out, _err = D.main(root, *argv)
            rows = [r for r in json.loads(out)["summary"]["rejections"]
                    if r["decision"] == D.DECISION and r["type"] == "preferred_against"]
            self.assertEqual([r["preference"] for r in rows],
                             [{"state": "not-recorded", "name": D.PERSON, "who": "", "when": ""}],
                             argv)
        from nopekit import site
        view, resolution = __import__("_physical").resolved(root)
        registry, _p = cli._registry(root, store.load(root), strict=False)
        state = site.state(root, view, registry, resolution=resolution)
        rows = [r for r in state["rejections"] if r["type"] == "preferred_against"
                and r["decision"] == D.DECISION]
        self.assertEqual(rows[0]["preference"]["state"], "not-recorded")
        # The marketing page (the two pages): the same phrase, capitalised, from
        # the same template; a resealed page that says *recorded by* before
        # `prefer` is refused; after the person's own `prefer`, the recorded one.
        site_phrase = "Preferred against, not recorded by Robin Okafor"
        self.assertEqual(site_phrase[:1].lower() + site_phrase[1:], said)
        self.assertEqual(report.HUMAN["rejection"]["not_recorded"].format(name=D.PERSON), said)
        for argv in (("site", "init"), ("site", "build")):
            code, out, err = D.main(root, *argv)
            self.assertEqual(code, 0, out + err)
        item = _page_rejection(root)
        self.assertEqual((item["type_word"], item["preference"]), (site_phrase, "not-recorded"))
        path = _page_json(root)
        honest = D.read_json(path)
        lie = json.loads(json.dumps(honest))
        planted = next(i for d in lie["decisions"] if d["id"] == D.DECISION
                       for i in d["rejected"] if i["type"] == "preferred_against")
        planted.update(type_word="Preferred against, recorded by Robin Okafor "
                                 "(2026-10-14T16:00:00Z)", preference="recorded")
        lie["self"] = page.seal(lie)
        D.write_json(path, lie)
        _code, out, _err = D.main(root, "site", "status", "--json")
        edited = json.loads(out)["edited"]
        self.assertTrue([e for e in edited if "edited by hand" in e], edited)
        D.write_json(path, honest)
        code, out, err = _prefer(root)
        self.assertEqual(code, 0, out + err)
        code, out, err = D.main(root, "site", "build")
        self.assertEqual(code, 0, out + err)
        item = _page_rejection(root)
        self.assertEqual(item["preference"], "recorded")
        self.assertTrue(item["type_word"].startswith("Preferred against, recorded by Robin "
                                                     "Okafor ("), item["type_word"])
        _code, why, _err = D.main(root, "why", D.DECISION)
        self.assertIn(item["type_word"][:1].lower() + item["type_word"][1:], why)

    def test_a_sealed_entry_from_another_channel_never_counts(self):
        root = D.bracket(os.path.join(self.tmp(), "b"))
        for label, entry in (
                ("a pipe", D.entry_for(root, channel="non-interactive")),
                ("an agent session", D.entry_for(root, channel="agent-session s1")),
                ("who is not the name", D.entry_for(root, who=D.PAT_WHO)),
                ("another person", D.entry_for(root, who=D.PAT_WHO, name="Pat Other"))):
            with self.subTest(label):
                store.append_sealed(root, "preferences", D.DECISION, "preferences", entry)
                self.assertEqual(_state(root), "not-recorded")
        store.append_sealed(root, "preferences", D.DECISION, "preferences", D.entry_for(root))
        self.assertEqual(_state(root), "recorded", "the control: the person's own entry")

    def test_a_gate_never_reads_a_preference(self):
        """A preference moves no status: the gate's copy of ``decisions`` holds no
        ``preferences``, so nothing a gate decides can turn on one — the decisions
        digest leaves the field out, and a field rho never keys on must not be on
        the copy either. What slipped through (review of phase 2): the copy held
        them, so a gate that branched on one kept its cached pass Fresh after
        ``nopekit prefer``."""
        root = D.bracket(os.path.join(self.tmp(), "b"))
        store.append_sealed(root, "preferences", D.DECISION, "preferences", D.entry_for(root))
        self.assertEqual(gate_seen_preferences(root), [])
        from nopekit import verdicts
        with mock.patch.object(verdicts, "_HIDDEN_FROM_THE_COPY", {}):
            self.assertNotEqual(gate_seen_preferences(root), [],
                                "a copy that keeps preferences was not caught")


def _page_json(root: str) -> str:
    return os.path.join(root, "site", "data", "page.json")


def _page_rejection(root: str) -> dict:
    """The bracket's preferred_against rejection as the marketing page bakes
    it (`page.json`'s ``decisions[].rejected[]``)."""
    doc = D.read_json(_page_json(root))
    [item] = [i for d in doc["decisions"] if d["id"] == D.DECISION for i in d["rejected"]
              if i["type"] == "preferred_against"]
    return item


def gate_seen_preferences(root: str) -> list[str]:
    """The preferences a gate's ``ctx.ledger.decisions`` shows on ``root``, which
    holds one recorded preference: none, or the field reached the gate. The
    loaded ledger must still hold it (the control), and the copy must leave it so."""
    from nopekit import verdicts
    ledger = store.load(root)
    held = next(d for d in ledger.decisions if d.id == D.DECISION).preferences
    if not held:
        raise AssertionError("the control: the loaded ledger holds no preference")
    trace = verdicts.GateTrace()
    seen = [f"{d.id}: {len(d.preferences)}"
            for d in verdicts.LedgerView(ledger, trace).decisions if d.preferences]
    if next(d for d in ledger.decisions if d.id == D.DECISION).preferences != held:
        seen.append("the source ledger lost its preferences")
    return seen


class ThePreferenceFileIsSealedAndChained(_env.EnvCase):
    """(13) ``preferences/<decision>.json`` is sealed and chained: a hand-written,
    edited, reordered, truncated or copied entry refuses the file on every
    command, naming the file, the entry and the command its person runs again;
    nothing but ``store.append_sealed`` writes it."""

    def setUp(self):
        self.root = D.bracket(os.path.join(self.tmp(), "b"))
        first = D.entry_for(self.root)
        second = dict(first, when="2026-10-15T09:00:00Z")
        self.good = D.chain([first, second], D.DECISION)

    def _refused(self, entries: list, *, where: str = "") -> str:
        D.write_preferences(self.root, D.DECISION, entries)
        with self.assertRaises(NopekitError) as caught:
            store.load(self.root)
        text = str(caught.exception)
        self.assertIn(f"preferences/{D.DECISION}.json", text)
        if where:
            self.assertIn(where, text)
        code, _out, err = D.main(self.root, "status")
        self.assertEqual(code, 2, "every command refuses the file")
        self.assertIn(f"preferences/{D.DECISION}.json", err)
        return text

    def test_the_sealed_file_reads(self):
        D.write_preferences(self.root, D.DECISION, self.good)
        self.assertEqual(_state(self.root), "recorded")

    def test_a_hand_written_unsealed_file_is_refused(self):
        text = self._refused([D.entry_for(self.root)], where="an entry with no seal")
        self.assertIn(f"nopekit prefer {D.DECISION} --value", text)

    def test_each_tampering_is_refused(self):
        a, b = self.good
        results_entry = {"passed": False, "when": "x", "who": D.PERSON_WHO, "prev": "",
                         "digest": "0" * 64}
        export_entry = {"milestone": "print-v1", "prev": "", "digest": "0" * 64}
        other = D.sealed(dict(a, decision="other-decision"), "other-decision", "")
        for label, entries, where in (
                ("an edited who", [dict(a, who=D.PAT_WHO), b], "its seal does not match"),
                ("a flipped name", [dict(a, name="Pat Other"), b], "its seal does not match"),
                ("a dropped middle entry", [b], "its link to the entry before it"),
                ("reordered entries", [b, a], "its link to the entry before it"),
                ("an entry from another decision's file", [other], "is a preference on"),
                ("a results entry pasted in", [results_entry], "unknown key"),
                ("an exports entry pasted in", [export_entry], "unknown key"),
                ("another decision's seal under this name",
                 [dict(other, decision=D.DECISION)], "its seal does not match")):
            with self.subTest(label):
                self._refused(entries, where=where)

    def test_the_writer_refuses_to_extend_a_broken_file(self):
        a, b = self.good
        D.write_preferences(self.root, D.DECISION, [dict(a, who=D.PAT_WHO), b])
        with self.assertRaises(NopekitError):
            store.append_sealed(self.root, "preferences", D.DECISION, "preferences",
                                D.entry_for(self.root))
        with self.assertRaises(ValueError):
            store.write_record(self.root, "preferences",
                               PreferenceRecord(decision=D.DECISION))

    def test_the_only_writer_is_append_sealed(self):
        self.assertEqual(preference_writers(), [])
        planted = {"rogue.py": "def save_preference(root, data):\n"
                               "    atomic_write_text(os.path.join(root, 'preferences', "
                               "'x.json'), data)\n"}
        self.assertEqual(preference_writers(planted), ["rogue.py:save_preference"])

    # -- left for the gate: a committed tamper walks git ------------------- #
    def test_a_committed_tamper_names_the_commit_to_restore(self):
        D.write_preferences(self.root, D.DECISION, self.good)
        _env.git(["init", "-q"], cwd=self.root)
        _env.git(["add", "-A"], cwd=self.root)
        _env.git(["commit", "-q", "-m", "sealed"], cwd=self.root, identity=True)
        a, b = self.good
        D.write_preferences(self.root, D.DECISION, [a, dict(b, who=D.PAT_WHO)])
        _env.git(["commit", "-q", "-am", "tampered"], cwd=self.root, identity=True)
        with self.assertRaises(NopekitError) as caught:
            store.load(self.root)
        self.assertIn("the newest commit whose", str(caught.exception))


_WRITERS = frozenset({"atomic_write_text", "atomic_write_json", "_write_if_changed",
                      "_write_once", "write_bytes", "write_text"})


def preference_writers(planted: dict[str, str] | None = None) -> list[str]:
    """``module:function`` for every function under ``src/nopekit`` that names
    ``"preferences"`` and calls a file writer, but ``store.append_sealed`` (the
    twin of ``test_records.export_writers``)."""
    sources = dict(planted or {})
    if planted is None:
        base = os.path.join(_env.REPO, "src", "nopekit")
        for name in sorted(os.listdir(base)):
            if name.endswith(".py"):
                with open(os.path.join(base, name), encoding="utf-8") as fh:
                    sources[name] = fh.read()
    hits = []
    for name, text in sources.items():
        if "preferences" not in text:
            continue
        lines = text.splitlines()
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.FunctionDef):
                continue
            # The literal in the function's own lines, before its subtree is
            # walked: most of cli.py's functions never name the kind.
            if "preferences" not in "\n".join(lines[node.lineno - 1:node.end_lineno]):
                continue
            names = any(isinstance(n, ast.Constant) and n.value == "preferences"
                        for n in ast.walk(node))
            writes = any(isinstance(n, ast.Call) and (
                getattr(n.func, "attr", None) in _WRITERS
                or getattr(n.func, "id", None) in _WRITERS) for n in ast.walk(node))
            if names and writes and (name, node.name) != ("store.py", "append_sealed"):
                hits.append(f"{name}:{node.name}")
    return hits


class APreferenceIsBoundToWhatThePersonRead(_env.EnvCase):
    """(13) A preference counts only while the rejection says what it said when
    its person recorded it — its value, its why, its return condition and the
    decision's title; reverting the edit records it again, and an edit to what
    the person did not read (the summary, the type, the input, another
    rejection) leaves it recorded."""

    def setUp(self):
        self.root = D.bracket(os.path.join(self.tmp(), "b"))
        D.write_preferences(self.root, D.DECISION, D.chain([D.entry_for(self.root)],
                                                           D.DECISION))
        self.assertEqual(_state(self.root), "recorded")
        self.original = D.read_json(D.decision_path(self.root))

    def _restore(self):
        D.write_json(D.decision_path(self.root), self.original)

    def test_each_edit_of_what_was_read_un_records_it(self):
        for label, edit in (
                ("the title", lambda: D.edit_decision(self.root, title="Print in PLA")),
                ("the why", lambda: D.edit_rejection(self.root, 2, why="it is heavy")),
                ("the condition", lambda: D.edit_rejection(
                    self.root, 2, returns_if={"claim": "C3", "quantity": "margin",
                                              "comparator": "<", "value": 0.5})),
                ("the condition's shape", lambda: D.edit_rejection(
                    self.root, 2, returns_if={"text": "when Robin buys a mill"}))):
            with self.subTest(label):
                edit()
                self.assertEqual(_state(self.root), "not-recorded")
                self._restore()
                self.assertEqual(_state(self.root), "recorded", "reverted, it counts again")

    def test_the_value_names_another_alternative(self):
        D.edit_rejection(self.root, 2, value="a cast aluminium bracket")
        self.assertEqual(_state(self.root), "not-recorded")
        self._restore()
        self.assertEqual(_state(self.root), "recorded")

    def test_another_person_named_un_records_it(self):
        D.edit_rejection(self.root, 2, by="Pat Other")
        self.assertEqual(_state(self.root), "not-recorded")

    def test_what_the_person_did_not_read_leaves_it_recorded(self):
        for label, edit in (
                ("the summary", lambda: D.edit_decision(self.root, summary="Something else")),
                ("an input", lambda: D.edit_rejection(self.root, 2, input="a-datasheet")),
                ("another rejection", lambda: D.edit_rejection(self.root, 0, why="it creeps")),
                ("the evidence", lambda: D.edit_rejection(self.root, 2, evidence="a quote"))):
            with self.subTest(label):
                edit()
                self.assertEqual(_state(self.root), "recorded")
                self._restore()

    def test_the_digest_covers_exactly_what_was_read(self):
        decision = store.load(self.root).decisions[0]
        item = decision.rejected[2]
        digest = claims.rejection_digest(decision, item)
        for change in (dict(type="dominated"), dict(input="x"), dict(evidence="y")):
            self.assertEqual(claims.rejection_digest(decision,
                                                     dataclasses.replace(item, **change)),
                             digest, change)
        self.assertEqual(claims.rejection_digest(
            dataclasses.replace(decision, summary="moved", body="moved"), item), digest)
        for change in (dict(value="z"), dict(why="z"), dict(returns_if=None)):
            self.assertNotEqual(claims.rejection_digest(
                decision, dataclasses.replace(item, **change)), digest, change)


class TheEarlierSealsAreUnmoved(_env.EnvCase):
    """Phase 2 adds a third sealed kind through the exports writer, extracted:
    an exports file P2.5b wrote still verifies and extends to the digest it did,
    its refusal reads byte for byte as before, and the results seal is unmoved.
    The pins were computed at e138fc8."""

    EXPORT = {"milestone": "print-v1", "when": "2026-10-04T10:00:00Z", "who": "Dana <d@x>",
              "channel": "interactive", "revision": "", "dirty": False, "requires": ["C1"],
              "claims": {}, "reran": [], "counted": {}, "article": {}, "package": {},
              "proceed": None}
    #: `store.append_sealed(root, "exports", "print-v1", "exports", EXPORT)` twice,
    #: at e138fc8: the two digests.
    EXPORT_DIGESTS = ("8fca8eb7b09382954d672d41f2810eb6d98e291813fb8be2bd50aabbf1355e79",
                      "d965f9802b582a8a1b9eee6be2b7fd9f868ea16266c098a2e8bfe400282d3979")
    #: A results entry's seal form at e138fc8.
    RESULT_DIGEST = "1ef7bb6fb0619a9d5d56f60fd657e02de99f92a41662e8f59f6e6d0cff4ed7af"
    #: The refusal of an export file whose first entry's who was edited, at e138fc8.
    EXPORT_REFUSAL = (
        'exports/print-v1.json: exports[0] — its seal does not match what it says — i'
        't was edited after it was recorded, or copied here from another file. Every '
        'command refuses this file until it is restored: no commit holds exports/prin'
        't-v1.json, so nothing can verify it as it is — restore it from where it was '
        'copied, or move it aside: the next `nopekit export print-v1` starts its reco'
        'rd again. A restore drops each export git does not hold: exports[0], an expo'
        'rt recorded 2026-10-04T10:00:00Z by Mallory <m@x> of article unnamed — its s'
        'eal does not hold, so what it said cannot be read back — a pass recorded on '
        'such an article counts again once `nopekit export print-v1` records it again'
        '; a fail on it counts regardless')

    def test_an_exports_file_extends_as_it_did(self):
        root = self.tmp()
        first = store.append_sealed(root, "exports", "print-v1", "exports", dict(self.EXPORT))
        second = store.append_sealed(root, "exports", "print-v1", "exports", dict(self.EXPORT))
        self.assertEqual((first["digest"], second["digest"]), self.EXPORT_DIGESTS)

    def test_the_exports_refusal_is_byte_identical(self):
        root = self.tmp()
        store.append_sealed(root, "exports", "print-v1", "exports", dict(self.EXPORT))
        path = os.path.join(root, "exports", "print-v1.json")
        data = D.read_json(path)
        data["exports"][0]["who"] = "Mallory <m@x>"
        D.write_json(path, data)
        with self.assertRaises(NopekitError) as caught:
            store.read_record(path, "exports")
        self.assertEqual(str(caught.exception), self.EXPORT_REFUSAL)

    def test_the_results_seal_is_unmoved(self):
        entry = {"passed": True, "when": "2026-10-04T10:00:00Z", "who": "Dana <d@x>",
                 "detail": "no crazing", "channel": "interactive", "prev": ""}
        self.assertEqual(util.seal(store._seal_form("C5", "results", entry)), self.RESULT_DIGEST)


if __name__ == "__main__":
    unittest.main()
