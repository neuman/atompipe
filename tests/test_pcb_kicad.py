# SPDX-License-Identifier: Apache-2.0
"""pcb-kicad, run on real boards: what its selftest could not see.

What slipped through: the pack's first run on two real boards (script-generated,
4 layers, 87 and 114 footprints, no schematic) found three faults in the pack,
none of which its baseline exercises, and the review of their fixes found more.

- ``pcb.fab_rules`` counted silk on silk as past the fab's limits. KiCad reports
  silk on silk as ``silk_overlap``, the type the fab's silk-to-pad rule reports
  under, so the 18 overlaps ``pcb.drc`` found were counted again: 190 findings
  where 172 were the fab's. Its detail line read "Silkscreen overlap" three times,
  so nobody could see that no copper was past a limit. The baseline has no silk on
  silk. The first fix matched a pad on the file's text alone, and in review a
  silk line across a pad with no id, an uppercase id or a legacy stamp passed,
  where the count before it had failed. Older than these fixes, and found in
  their review: a project that set a rule type to "ignore" hid the fab's own rule
  of that type, a pad's ``(clearance 0.01)`` passed a 0.047 mm gap under the fab's
  0.1 mm, and a microvia's hole breach, reported under another type, passed.
- No tag let a claim bind ``pcb.unconnected`` alone. ``connectivity`` brings in
  ``pcb.parity``, which skips with no schematic, so "every connection is made"
  read Skipped beside a pass.
- ``pcb.net_width`` named the hottest track "narrowest" and one net of a tie, and
  the reader took an arc's chord as its length.

One class runs the real kicad-cli, where it is installed, on the one case a
stand-in cannot show: how KiCad itself resolves a local clearance override.

The fab cases run the real gate through a stand-in ``kicad-cli`` on PATH that
writes a report shaped as kicad-cli 9.0.9 wrote them (silk item first, pad
second), with the baseline's own ids. No KiCad is needed to run this file.

Run:  PYTHONPATH=src python3 -m unittest tests.test_pcb_kicad -v
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

from nopekit import gates as gates_mod
from nopekit import packs as packs_mod
from nopekit.modelio import load_path
from nopekit.models import Ledger, ProjectMeta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(REPO, "packs", "pcb-kicad")
ASSETS = os.path.join(PACK, "selftest", "assets")
BOARD = os.path.join(ASSETS, "esd_guard.kicad_pcb")

#: The pack's own reader, loaded as its gates and fixtures load it.
K = load_path(os.path.join(PACK, "gates", "_kicad.py"))


def _baseline() -> dict:
    with open(os.path.join(PACK, "selftest", "baseline.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    return {k: v for k, v in data.items() if not k.startswith("_")}


def _registry() -> gates_mod.Registry:
    registry = gates_mod.Registry()
    packs_mod.load_gates("pcb-kicad", registry, root=REPO, include_env=False,
                         include_user=False)
    return registry


def _run(registry, gid: str, root: str, params: dict):
    spec_fn = registry.get(gid)
    assert spec_fn is not None, f"{gid} is not in the pack"
    ctx = gates_mod.GateContext(
        root=root, ledger=Ledger(meta=ProjectMeta(name="pcb")), model=None,
        params=dict(params), out_dir=os.path.join(root, "out", gid), tier=1,
        log=lambda _m: None, extra={})
    return gates_mod.run_gate(*spec_fn, ctx)


def _footprint(tree, ref: str):
    for fp in K.children(tree, "footprint"):
        if K.footprint_ref(fp)[0] == ref:
            return fp
    raise KeyError(ref)


def _pad(tree, ref: str, number: str):
    for pad in K.children(_footprint(tree, ref), "pad"):
        if len(pad) > 1 and str(pad[1]) == number:
            return pad
    raise KeyError(f"{ref} pad {number}")


def _net_code(tree, name: str) -> str:
    return next(str(n[1]) for n in K.children(tree, "net") if len(n) >= 3 and str(n[2]) == name)


#: The baseline's own items: J1's pad 1 and two of its silkscreen children, so a
#: count that took every id under a footprint for a pad's would be caught.
TREE = K.load_tree(BOARD)
PAD = str(K.value(_pad(TREE, "J1", "1"), "uuid"))
SILK_REF = next(str(K.value(p, "uuid")) for p in K.children(_footprint(TREE, "J1"), "property")
                if p[1] == "Reference")
SILK_LINE = next(str(K.value(ln, "uuid")) for ln in K.children(_footprint(TREE, "J1"), "fp_line")
                 if str(K.value(ln, "layer")) == "F.SilkS")


def _silk_on_silk() -> dict:
    return {"description": "Silkscreen overlap", "severity": "warning", "type": "silk_overlap",
            "items": [{"description": "Segment of J1 on F.Silkscreen", "pos": {"x": 3.9, "y": 2.6},
                       "uuid": SILK_LINE},
                      {"description": "Reference field of J1", "pos": {"x": 4.0, "y": 2.4},
                       "uuid": SILK_REF}]}


def _silk_to_pad(pad: str = PAD, *, pad_first: bool = False,
                 words: str = "PTH pad 1 [DP] of J1", named: bool = False) -> dict:
    """KiCad 9.0.9 lists the silk item first and the pad second. Its words name the
    fab rule ("(fab_silk_to_pad clearance ...)"); here they do not unless ``named``,
    so that the pad's id alone must carry the count."""
    items = [{"description": "Segment of J1 on F.Silkscreen", "pos": {"x": 3.9, "y": 4.0},
              "uuid": SILK_LINE},
             {"description": words, "pos": {"x": 4.0, "y": 4.0}, "uuid": pad}]
    return {"description": "Silkscreen overlap" + (
                " (fab_silk_to_pad clearance 0.1500 mm; actual 0.0000 mm)" if named else ""),
            "severity": "warning", "type": "silk_overlap",
            "items": items[::-1] if pad_first else items}


def _text_height() -> dict:
    return {"description": "Text height out of range (rule 'fab_silk_text_height' min height "
                           "1.0000 mm; actual 0.8000 mm)",
            "severity": "warning", "type": "text_height",
            "items": [{"description": "Reference field of J1", "pos": {"x": 4.0, "y": 2.4},
                       "uuid": SILK_REF}]}


def _board_copy(root: str, text: str, stem: str = "b") -> str:
    """``text`` as ``<root>/<stem>.kicad_pcb``, with the baseline's project file
    and library tables beside it, as the gate stages them."""
    shutil.copyfile(os.path.join(ASSETS, "esd_guard.kicad_pro"),
                    os.path.join(root, stem + ".kicad_pro"))
    for name in ("sym-lib-table", "fp-lib-table"):
        shutil.copyfile(os.path.join(ASSETS, name), os.path.join(root, name))
    path = os.path.join(root, stem + ".kicad_pcb")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _board_text() -> str:
    with open(BOARD, encoding="utf-8") as fh:
        return fh.read()


def _pad_ids_rewritten(fn) -> str:
    """The baseline with every pad's ``(uuid "...")`` passed through ``fn`` (which
    returns the new text, or "" to drop it); no other id is touched."""
    text, out, i = _board_text(), [], 0
    pad_ids = {str(K.value(p, "uuid")) for fp in K.children(TREE, "footprint")
               for p in K.children(fp, "pad")}
    for m in re.finditer(r'\(uuid "([0-9a-f-]+)"\)', text):
        if m.group(1) in pad_ids:
            out.append(text[i:m.start()])
            out.append(fn(m.group(1)))
            i = m.end()
    out.append(text[i:])
    return "".join(out)


@unittest.skipIf(os.name == "nt", "the stand-in kicad-cli is a #! script")
class TheFabCountsOnlyItsOwnFindings(unittest.TestCase):
    """A silk overlap is left to pcb.drc only when shown to be silk on silk."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nopekit-pcb-fab-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        self.calls = os.path.join(self.dir, "calls")
        self.registry = _registry()
        self.params = _baseline()

    def _fab(self, violations: list, board: str = BOARD, *, runs: int = 1):
        report = os.path.join(self.dir, "report.json")
        with open(report, "w", encoding="utf-8") as fh:
            json.dump({"$schema": "https://schemas.kicad.org/drc.v1.json",
                       "coordinate_units": "mm", "kicad_version": "9.0.9",
                       "included_severities": ["error", "warning"],
                       "source": os.path.basename(board), "violations": violations,
                       "unconnected_items": [], "schematic_parity": []}, fh)
        cli = os.path.join(self.bin, "kicad-cli")
        with open(cli, "w", encoding="utf-8") as fh:
            fh.write(f"#!{sys.executable}\n"
                     f"import shutil, sys\n"
                     f"open({self.calls!r}, 'a').write('x')\n"
                     f"shutil.copyfile({report!r}, sys.argv[sys.argv.index('-o') + 1])\n"
                     f"sys.exit({5 if violations else 0})\n")
        os.chmod(cli, os.stat(cli).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        params = dict(self.params, pcb_board=board)
        with mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + os.environ["PATH"]}):
            verdict = _run(self.registry, "pcb.fab_rules", self.dir, params)
        # A stand-in that never ran (a noexec temp dir) skips the gate for the
        # wrong reason; the count keeps that from reading as the fix working.
        ran = 0
        if os.path.exists(self.calls):
            with open(self.calls, encoding="utf-8") as fh:
                ran = len(fh.read())
            os.remove(self.calls)
        self.assertEqual(ran, runs, "the stand-in kicad-cli was not launched as many times "
                                    "as the case expects")
        return verdict

    def test_silk_on_silk_is_pcb_drcs(self):
        verdict = self._fab([_silk_on_silk()])
        self.assertEqual(verdict.outcome, "pass", verdict.render())
        self.assertEqual(verdict.measured, 0)
        self.assertIn("1 other finding(s) in the same run are pcb.drc's", verdict.detail)

    def test_silk_to_pad_is_the_fabs_whichever_item_the_pad_is(self):
        for pad_first in (False, True):
            with self.subTest(pad_first=pad_first):
                verdict = self._fab([_silk_to_pad(pad_first=pad_first)])
                self.assertEqual(verdict.outcome, "fail", verdict.render())
                self.assertEqual(verdict.measured, 1)
                self.assertIn("1 finding(s) past its limits: 1x silk_overlap (silk_to_pad)",
                              verdict.detail)

    def test_the_pad_is_found_by_id_not_by_its_words(self):
        """kicad-cli translates item descriptions into the host's language."""
        verdict = self._fab([_silk_to_pad(words="Pastille 1 [DP] de J1")])
        self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1), verdict.render())

    def test_the_rule_named_in_the_words_counts_without_the_pad(self):
        """The run's own rule name is the file's string, never translated: a
        finding that names it is the fab's even where no item is a known pad."""
        verdict = self._fab([_silk_to_pad("00000000-0000-4000-8000-0000000000ff", named=True)])
        self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1), verdict.render())

    def test_a_kicad_7_board_matches_its_pads_by_tstamp(self):
        """The tstamp branch had no input: a pad_ids that read only ``uuid`` passed
        every test and would pass a KiCad 7 board with silk across a pad."""
        text = _board_text().replace("(version 20241229)", "(version 20221018)", 1)
        text = text.replace("(uuid ", "(tstamp ")
        self.assertNotIn("(uuid ", text)
        board = _board_copy(self.dir, text)
        self.assertEqual(K.pad_ids(K.load_tree(board)), K.pad_ids(TREE))
        verdict = self._fab([_silk_on_silk(), _silk_to_pad()], board=board)
        self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1), verdict.render())

    def test_an_id_kicad_rewrites_still_matches(self):
        """kicad-cli 9.0.9 reports an uppercase or undashed UUID lowercase and
        dashed, and an 8-digit legacy stamp as 00000000-0000-0000-0000-0000<stamp>."""
        legacy = iter(range(1000))
        cases = {
            "uppercase": lambda u: f'(uuid "{u.upper()}")',
            "undashed": lambda u: f'(uuid "{u.replace("-", "")}")',
            "legacy_stamp": lambda u: f'(tstamp "{0x5C3A1B00 + next(legacy):08X}")',
        }
        for name, rewrite in cases.items():
            with self.subTest(case=name):
                board = _board_copy(self.dir, _pad_ids_rewritten(rewrite), stem=name)
                tree = K.load_tree(board)
                ids, unknown = K.pad_ids(tree)
                self.assertEqual(unknown, 0)
                written = _pad(tree, "J1", "1")
                written = str(K.value(written, "uuid") or K.value(written, "tstamp"))
                reported = (f"00000000-0000-0000-0000-0000{written.lower()}"
                            if name == "legacy_stamp" else PAD)
                self.assertIn(reported, ids)
                verdict = self._fab([_silk_on_silk(), _silk_to_pad(reported)], board=board)
                self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1),
                                 verdict.render())
                self.assertNotIn("cannot be told", verdict.detail)

    def test_a_pad_kicad_cannot_name_never_lets_silk_pass(self):
        """A pad with no id, or one that is not a UUID, gets a random one from
        KiCad, so no report can name it: every silk overlap is counted then, and
        the line says why. The fab's silk-to-pad finding there carries a pad id
        nobody wrote and, here, no rule name."""
        for name, rewrite in (("no_id", lambda u: ""),
                              ("not_a_uuid", lambda u: '(uuid "pad-x")')):
            with self.subTest(case=name):
                board = _board_copy(self.dir, _pad_ids_rewritten(rewrite), stem=name)
                self.assertEqual(K.pad_ids(K.load_tree(board)), (set(), 14))
                verdict = self._fab([_silk_to_pad("4fdea1bf-0000-4000-8000-000000000001")],
                                    board=board)
                self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1),
                                 verdict.render())
                self.assertIn("1 silk overlap(s) counted although no pad is named in them: "
                              "14 pad(s) on the board get a random id from KiCad",
                              verdict.detail)

    def test_the_line_says_what_kind_each_finding_is_most_first(self):
        verdict = self._fab([_text_height(), _silk_on_silk(), _silk_to_pad(), _silk_to_pad()])
        self.assertEqual((verdict.outcome, verdict.measured), ("fail", 3), verdict.render())
        self.assertIn("3 finding(s) past its limits: 2x silk_overlap (silk_to_pad), "
                      "1x text_height (silk_text_height); 1 other finding(s) in the same run "
                      "are pcb.drc's", verdict.detail)
        self.assertNotIn("Silkscreen overlap", verdict.detail)

    def test_ids_kicad_keeps_in_other_spellings_still_match(self):
        """kicad-cli 9.0.9 keeps a braced UUID (without its braces) and a bare
        legacy stamp shorter than 8 digits (zero-filled); a padded id and a braced
        stamp get a random one."""
        short = iter(range(1000))
        braced = iter(range(1000))
        for name, rewrite, unknown in (
                ("braced", lambda u: f'(uuid "{{{u}}}")', 0),
                ("short_stamp", lambda u: f'(tstamp "{0x3A10 + next(short):X}")', 0),
                ("padded", lambda u: f'(uuid " {u}")', 14),
                ("braced_stamp", lambda u: f'(tstamp "{{{0x3A10 + next(braced):X}}}")', 14)):
            with self.subTest(case=name):
                board = _board_copy(self.dir, _pad_ids_rewritten(rewrite), stem=name)
                tree = K.load_tree(board)
                ids, found_unknown = K.pad_ids(tree)
                self.assertEqual((len(ids), found_unknown), (14 - unknown, unknown))
                verdict = self._fab([_silk_on_silk()], board=board)
                if unknown:
                    self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1),
                                     verdict.render())
                    continue
                self.assertEqual((verdict.outcome, verdict.measured), ("pass", 0),
                                 verdict.render())
                written = _pad(tree, "J1", "1")
                written = str(K.value(written, "uuid") or K.value(written, "tstamp"))
                reported = (PAD if name == "braced" else
                            "00000000-0000-0000-0000-0000" + written.lower().zfill(8))
                self.assertIn(reported, ids)
                verdict = self._fab([_silk_to_pad(reported)], board=board)
                self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1),
                                 verdict.render())

    def test_a_microvia_hole_breach_is_the_fabs(self):
        """KiCad 9.0.9 reports the fab's via-hole rule broken on a microvia as
        microvia_drill_out_of_range, with the board's words, not the rule's."""
        verdict = self._fab([{
            "description": "Microvia hole size out of range (board setup constraints min hole "
                           "0.1500 mm; actual 0.1200 mm)",
            "severity": "error", "type": "microvia_drill_out_of_range",
            "items": [{"description": "Micro via [VBUS] on F.Cu - In1.Cu",
                       "pos": {"x": 8.0, "y": 4.0}, "uuid": SILK_LINE}]}])
        self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1), verdict.render())
        self.assertIn("1x microvia_drill_out_of_range (via_hole/pth_hole/npth_hole)",
                      verdict.detail)

    def test_two_holes_on_one_centre_are_the_fabs(self):
        """KiCad 9.0.9 reports a via on top of another as holes_co_located and never
        tests hole_to_hole there."""
        verdict = self._fab([{
            "description": "Drilled holes co-located", "severity": "warning",
            "type": "holes_co_located",
            "items": [{"description": "Via [VBUS] on F.Cu - B.Cu", "pos": {"x": 8.0, "y": 4.0},
                       "uuid": SILK_LINE},
                      {"description": "Via [VBUS] on F.Cu - B.Cu", "pos": {"x": 8.0, "y": 4.0},
                       "uuid": SILK_REF}]}])
        self.assertEqual((verdict.outcome, verdict.measured), ("fail", 1), verdict.render())
        self.assertIn("1x holes_co_located (hole_to_hole/via_hole_to_hole)", verdict.detail)

    def test_a_project_kicad_cannot_read_is_an_error_never_a_run(self):
        """KiCad drops a project file it cannot parse and runs on defaults, the fab's
        clearance floor gone with it: a NaN or an overflowing number is refused."""
        with open(os.path.join(ASSETS, "esd_guard.kicad_pro"), encoding="utf-8") as fh:
            text = fh.read()
        # A value the fab run copies through unchanged: a minimum would be zeroed
        # or floored, and the bad number with it.
        anchor = '"board_outline_line_width": 0.05'
        self.assertEqual(text.count(anchor), 1)
        project = json.loads(text)
        project["board"]["design_settings"]["defaults"]["board_outline_line_width"] = float("nan")
        for name, written in (("nan", json.dumps(project)),
                              ("overflow", text.replace(anchor, '"board_outline_line_width": 1e999'))):
            with self.subTest(case=name):
                board = _board_copy(self.dir, _board_text(), stem=name)
                with open(os.path.join(self.dir, name + ".kicad_pro"), "w",
                          encoding="utf-8") as fh:
                    fh.write(written)
                # Through the stand-in, which must never be launched: the gate
                # errors before kicad-cli runs. (What slipped through: called
                # without it, this case skipped for the missing tool on CI, where
                # no kicad-cli is installed, and passed only where one was.)
                verdict = self._fab([], board=board, runs=0)
                self.assertEqual(verdict.outcome, "error", verdict.render())
                self.assertIn("a value KiCad cannot read", verdict.error)

    def test_a_project_with_rules_of_its_own_never_hears_pcb_drcs(self):
        """The project's own custom rules are left out of the fab run, and one of
        them may waive in pcb.drc what this run reports."""
        board = _board_copy(self.dir, _board_text())
        with open(os.path.join(self.dir, "b.kicad_dru"), "w", encoding="utf-8") as fh:
            fh.write('(version 1)\n(rule "silk_waived"\n\t(constraint silk_clearance)\n'
                     '\t(severity ignore))\n')
        verdict = self._fab([_silk_on_silk()], board=board)
        self.assertEqual((verdict.outcome, verdict.measured), ("pass", 0), verdict.render())
        self.assertIn("1 other finding(s) in the same run are not the fab's: pcb.drc judges "
                      "them under the project's own rules and severities", verdict.detail)
        self.assertNotIn("are pcb.drc's", verdict.detail)

    def test_the_clearance_floor_is_the_fabs(self):
        """The fab run's board minimum clearance is the fab's own, the floor KiCad
        holds a local override to; every other minimum is 0."""
        self._fab([])
        staged = [os.path.join(dp, f) for dp, _dn, fs in os.walk(os.path.join(self.dir, "out"))
                  for f in fs if f == "esd_guard.kicad_pro"]
        self.assertEqual(len(staged), 1, staged)
        with open(staged[0], encoding="utf-8") as fh:
            rules = json.load(fh)["board"]["design_settings"]["rules"]
        self.assertEqual(rules["min_clearance"], 0.1, "JLCPCB, 1-2 layers, 1 oz")
        self.assertEqual({k: v for k, v in rules.items() if k.startswith("min_")
                          and k not in ("min_clearance", "min_resolved_spokes")
                          and isinstance(v, (int, float)) and v != 0}, {})

    def test_a_type_the_project_ignores_is_never_called_pcb_drcs(self):
        """pcb.drc runs under the project's own severities, so silk on silk the
        project ignores, raised for the fab run, is said apart."""
        with open(os.path.join(ASSETS, "esd_guard.kicad_pro"), encoding="utf-8") as fh:
            project = json.load(fh)
        project["board"]["design_settings"]["rule_severities"]["silk_overlap"] = "ignore"
        board = _board_copy(self.dir, _board_text())
        with open(os.path.join(self.dir, "b.kicad_pro"), "w", encoding="utf-8") as fh:
            json.dump(project, fh)
        verdict = self._fab([_silk_on_silk()], board=board)
        self.assertEqual((verdict.outcome, verdict.measured), ("pass", 0), verdict.render())
        self.assertIn("1 other finding(s) of a type the project ignores (1x silk_overlap), "
                      "raised for this run only: pcb.drc does not see them", verdict.detail)
        self.assertNotIn("are pcb.drc's", verdict.detail)

    def test_an_ignored_rule_type_never_relaxes_the_fab(self):
        """KiCad does not test a type the project set to "ignore", even with
        --severity-all; the fab run raises each constrained type back to error."""
        with open(os.path.join(ASSETS, "esd_guard.kicad_pro"), encoding="utf-8") as fh:
            project = json.load(fh)
        severities = project["board"]["design_settings"]["rule_severities"]
        for kind in ("track_width", "silk_overlap", "clearance", "microvia_drill_out_of_range",
                     "holes_co_located", "unconnected_items"):
            severities[kind] = "ignore"
        board = _board_copy(self.dir, _board_text())
        with open(os.path.join(self.dir, "b.kicad_pro"), "w", encoding="utf-8") as fh:
            json.dump(project, fh)
        self._fab([], board=board)
        staged = [os.path.join(dp, f) for dp, _dn, fs in os.walk(os.path.join(self.dir, "out"))
                  for f in fs if f == "b.kicad_pro"]
        self.assertEqual(len(staged), 1, staged)
        with open(staged[0], encoding="utf-8") as fh:
            ran = json.load(fh)["board"]["design_settings"]["rule_severities"]
        raised = ("track_width", "silk_overlap", "clearance", "microvia_drill_out_of_range",
                  "holes_co_located")
        self.assertEqual({k: ran[k] for k in raised}, dict.fromkeys(raised, "error"))
        self.assertEqual(ran["unconnected_items"], "ignore", "not the fab's: left as it was")


@unittest.skipIf(shutil.which("kicad-cli") is None,
                 "how KiCad resolves a local clearance override needs the real kicad-cli")
class ALocalClearanceNeverRelaxesTheFab(unittest.TestCase):
    """The GND track from J1 ends inside U1's ground pad, 0.047 mm from U1 pad 1
    (D+): past JLCPCB's 0.1 mm. A ``(clearance 0.01)`` on that pad, or on U1, must
    not pass it: the fab run's board minimum is the fab's clearance, the one floor
    KiCad holds an override to."""

    SEGMENT = "\t\t(start 4 6.54)\n\t\t(end 13.8625 7.81)\n\t\t(width 0.25)"
    PAD1 = '\t\t\t(pintype "passive")\n\t\t\t(uuid "98a522d3-a31a-41b6-97e5-ddabad051743")'
    U1 = '\t\t(uuid "70a4bc33-beb2-419e-8f2d-627f2d44a86b")\n\t\t(at 15 7.81)'

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nopekit-pcb-override-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.registry = _registry()
        text = _board_text()
        for anchor in (self.SEGMENT, self.PAD1, self.U1):
            self.assertEqual(text.count(anchor), 1, f"the baseline moved: {anchor!r}")
        self.near = text.replace(self.SEGMENT,
                                 "\t\t(start 4 6.54)\n\t\t(end 13.6 7.38)\n\t\t(width 0.3)")

    def _fab(self, text: str, stem: str):
        board = _board_copy(self.dir, text, stem=stem)
        return _run(self.registry, "pcb.fab_rules", self.dir,
                    dict(_baseline(), pcb_board=board))

    def test_the_gap_is_past_the_fab_and_an_override_never_hides_it(self):
        pad_override = self.near.replace(self.PAD1, self.PAD1.replace(
            '\t\t\t(uuid', '\t\t\t(clearance 0.01)\n\t\t\t(uuid'))
        footprint_override = self.near.replace(self.U1, self.U1 + "\n\t\t(clearance 0.01)")
        for stem, text in (("no_override", self.near), ("pad_override", pad_override),
                           ("footprint_override", footprint_override)):
            with self.subTest(case=stem):
                verdict = self._fab(text, stem)
                self.assertEqual(verdict.outcome, "fail", verdict.render())
                self.assertIn("x clearance (clearance)", verdict.detail)


class ASilkRuleIsSilkToPad(unittest.TestCase):
    """The count reads a silk overlap as the fab's beside a pad, so the rule the run
    writes must be silk to pad too, or the two would disagree; and the run floors
    local clearance overrides at a row's one clearance rule, so a row has one."""

    def test_a_row_holds_one_clearance_rule_with_no_condition(self):
        one = {"name": "clearance", "constraint": "clearance", "min_mm": 0.1}
        for rules in ([one, dict(one, name="clearance_2", min_mm=0.15)],
                      [dict(one, condition="A.Type == 'Pad' && B.Type == 'Pad'")]):
            with self.subTest(rules=[r["name"] for r in rules]):
                with self.assertRaises(ValueError) as caught:
                    K.dru_text({"name": "t", "rules": rules}, "fab")
                self.assertIn("one clearance rule", str(caught.exception))
        self.assertEqual(K.fab_clearance_floor({"name": "t", "rules": [one]}), 0.1)

    def test_any_other_silk_rule_is_refused(self):
        for condition in (None, "A.Type == 'Text' && B.Type == 'Text'",
                          "B.Type == 'Pad' || A.Type == 'Pad'"):
            with self.subTest(condition=condition):
                rule = {"name": "silk", "constraint": "silk_clearance", "min_mm": 0.15}
                if condition:
                    rule["condition"] = condition
                with self.assertRaises(ValueError) as caught:
                    K.dru_text({"name": "t", "rules": [rule]}, "fab")
                self.assertIn(K.SILK_TO_PAD, str(caught.exception))

    def test_a_silk_rule_at_zero_is_refused(self):
        """At a minimum of 0 KiCad leaves the rule's name out of the finding."""
        rule = {"name": "silk", "constraint": "silk_clearance", "condition": K.SILK_TO_PAD,
                "min_mm": 0}
        with self.assertRaises(ValueError) as caught:
            K.dru_text({"name": "t", "rules": [rule]}, "fab")
        self.assertIn("above 0", str(caught.exception))

    def test_every_bundled_fab_file_writes(self):
        fab_dir = os.path.join(PACK, "gates", "fab")
        for name in sorted(os.listdir(fab_dir)):
            if not name.endswith(".json"):
                continue
            with open(os.path.join(fab_dir, name), encoding="utf-8") as fh:
                fab = json.load(fh)
            for row in fab["tables"]:
                with self.subTest(fab=name, row=row["name"]):
                    rules = list(fab.get("common", [])) + list(row["rules"])
                    text = K.dru_text({"name": row["name"], "rules": rules}, "fab")
                    if any(r["constraint"] == "silk_clearance" for r in rules):
                        self.assertIn(f'(condition "{K.SILK_TO_PAD}")', text)


class TheHottestTrackIsNamed(unittest.TestCase):
    """``pcb.net_width``'s line names the hottest stretch (its width, the layers it
    runs on, its length along the copper, the same copper once) and up to four
    stretches as hot, then how many more; never "narrowest". Expected lengths are
    worked here from the tracks' ends, not read back from the reader the gate uses."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="nopekit-pcb-width-")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.registry = _registry()
        self.params = _baseline()

    @staticmethod
    def _segments(tree, code: str, layer: str):
        return [s for s in K.children(tree, "segment")
                if K.value(s, "net") == code and str(K.value(s, "layer")) == layer]

    def _vbus(self, layer: str) -> float:
        """The length of the baseline's VBUS segments on ``layer``, from their ends."""
        total = 0.0
        for seg in self._segments(TREE, _net_code(TREE, "VBUS"), layer):
            (x0, y0), (x1, y1) = ((float(K.child(seg, e)[1]), float(K.child(seg, e)[2]))
                                  for e in ("start", "end"))
            total += math.hypot(x1 - x0, y1 - y0)
        return total

    def _width(self, edit=None) -> str:
        tree = K.load_tree(BOARD)
        if edit:
            edit(tree, _net_code(tree, "VBUS"))
        board = os.path.join(self.dir, "w.kicad_pcb")
        with open(board, "w", encoding="utf-8") as fh:
            fh.write(K.dump(tree))
        verdict = _run(self.registry, "pcb.net_width", self.dir,
                       dict(self.params, pcb_board=board))
        self.assertNotIn("narrowest", verdict.detail)
        return verdict.detail

    def test_the_baseline_names_both_nets_of_its_tie(self):
        """VBUS and GND both carry 0.5 A on 0.25 mm outer copper: equally hot."""
        detail = self._width()
        both = self._vbus("F.Cu") + self._vbus("B.Cu")
        self.assertTrue(detail.startswith(
            f"VBUS: hottest track 0.25 mm on B.Cu, F.Cu ({both:.1f} mm) rises "), detail)
        self.assertIn("; as hot: GND 0.25 mm on B.Cu, F.Cu (", detail)

    def test_a_stretch_hotter_only_past_the_printed_digit_is_named_too(self):
        """GND at 0.501 A runs a hair hotter than VBUS at 0.5 A on the same copper.
        Both print as the same rise, so a person who widened only GND would read
        the same number again: the line names both."""
        a = K.temp_rise_c(0.5, 0.25, 1.0, True)
        b = K.temp_rise_c(0.501, 0.25, 1.0, True)
        self.assertTrue(b > a and round(a, 1) == round(b, 1), (a, b))
        self.params["pcb_net_currents_a"] = {"VBUS": 0.5, "GND": 0.501}
        detail = self._width()
        self.assertTrue(detail.startswith("GND: hottest track 0.25 mm on B.Cu, F.Cu ("), detail)
        self.assertIn("; as hot: VBUS 0.25 mm on B.Cu, F.Cu (", detail)

    def test_past_four_ties_the_line_counts_the_rest(self):
        """Every net at 0.5 A, and one segment of each moved inside at the width
        that heats as 0.25 mm outside: eight stretches as hot. The line names four
        after the first, counts the other three, and the evidence lists all eight."""
        rise = K.temp_rise_c(0.5, 0.25, 1.0, True)
        inner = round(K.width_for_rise_mm(0.5, rise, 0.5, False), 4)
        self.assertEqual(round(K.temp_rise_c(0.5, inner, 0.5, False), 1), round(rise, 1))
        nets = ("DM", "DP", "GND", "VBUS")
        self.params["pcb_net_currents_a"] = dict.fromkeys(nets, 0.5)
        tree = K.load_tree(BOARD)
        for net in nets:
            code = _net_code(tree, net)
            seg = next(s for s in K.children(tree, "segment") if K.value(s, "net") == code)
            K.child(seg, "layer")[1] = K.Q("In1.Cu")
            K.child(seg, "width")[1] = f"{inner:g}"
        board = os.path.join(self.dir, "ties.kicad_pcb")
        with open(board, "w", encoding="utf-8") as fh:
            fh.write(K.dump(tree))
        verdict = _run(self.registry, "pcb.net_width", self.dir,
                       dict(self.params, pcb_board=board))
        self.assertEqual(verdict.detail.count("; as hot: "), 4, verdict.detail)
        self.assertIn("; and 3 more stretch(es) as hot (evidence: as_hot)", verdict.detail)
        with open(verdict.evidence[0], encoding="utf-8") as fh:
            as_hot = json.load(fh)["as_hot"]
        self.assertEqual(sorted((h["net"], h["side"]) for h in as_hot),
                         sorted((n, side) for n in nets for side in ("inner", "outer")))

    def test_a_tie_outside_the_fitted_range_is_named_with_its_net(self):
        """GND at 36 A on a track wide enough to heat as VBUS's 0.5 A on 0.25 mm:
        as hot, and past IPC-2221's fitted current and width, whichever of the two
        is the hotter below the printed digit."""
        rise = K.temp_rise_c(0.5, 0.25, 1.0, True)
        wide = round(K.width_for_rise_mm(36.0, rise, 1.0, True), 4)
        self.params["pcb_net_currents_a"] = {"VBUS": 0.5, "GND": 36.0}
        def edit(tree, _code):
            gnd = _net_code(tree, "GND")
            for seg in K.children(tree, "segment"):
                if K.value(seg, "net") == gnd:
                    K.child(seg, "width")[1] = f"{wide:g}"
        detail = self._width(edit)
        self.assertIn("as hot: ", detail)
        self.assertIn(f"outside IPC-2221's fitted range: a {wide:g} mm track (GND), 36 A (GND)",
                      detail)

    def test_a_wider_inner_track_is_the_hottest(self):
        """VBUS's front copper moved inside and widened to 0.3 mm: 0.25 mm still runs
        on the back, and the 0.3 mm inner track is the hotter. "Narrowest 0.3 mm"
        would be false."""
        def edit(tree, code):
            for seg in self._segments(tree, code, "F.Cu"):
                K.child(seg, "layer")[1] = K.Q("In1.Cu")
                K.child(seg, "width")[1] = "0.3"
        detail = self._width(edit)
        self.assertTrue(detail.startswith(
            f"VBUS: hottest track 0.3 mm on In1.Cu ({self._vbus('F.Cu'):.1f} mm) rises "), detail)
        self.assertIn("IPC-2221 internal", detail)

    def test_the_same_width_inside_is_named_apart_from_outside(self):
        """VBUS's front copper moved inside at its 0.25 mm: the back's 0.25 mm is
        the cooler copper and is no part of the hottest stretch."""
        def edit(tree, code):
            for seg in self._segments(tree, code, "F.Cu"):
                K.child(seg, "layer")[1] = K.Q("In1.Cu")
        detail = self._width(edit)
        self.assertTrue(detail.startswith(
            f"VBUS: hottest track 0.25 mm on In1.Cu ({self._vbus('F.Cu'):.1f} mm) rises "), detail)
        self.assertNotIn("B.Cu", detail)

    def test_a_wider_track_on_the_same_side_is_no_part_of_it(self):
        """VBUS's back copper widened to 0.5 mm: only the front's 0.25 mm is hottest
        (and as hot as GND's)."""
        def edit(tree, code):
            for seg in self._segments(tree, code, "B.Cu"):
                K.child(seg, "width")[1] = "0.5"
        detail = self._width(edit)
        self.assertTrue(detail.startswith(
            f"VBUS: hottest track 0.25 mm on F.Cu ({self._vbus('F.Cu'):.1f} mm) rises "), detail)
        self.assertIn("; as hot: GND 0.25 mm on B.Cu, F.Cu (", detail)

    def test_an_arc_is_measured_along_it_and_counted_once(self):
        """A 0.2 mm half-circle of radius 2 mm on VBUS, written twice: 2 pi mm of
        copper (6.3), not its 4 mm chord, and not 12.6."""
        def edit(tree, code):
            for _ in range(2):
                tree.append(["arc", ["start", "10", "20"], ["mid", "12", "22"],
                             ["end", "14", "20"], ["width", "0.2"], ["layer", K.Q("F.Cu")],
                             ["net", code], ["uuid", K.Q("00000000-0000-4000-8000-0000000000aa")]])
        detail = self._width(edit)
        self.assertTrue(detail.startswith(
            f"VBUS: hottest track 0.2 mm on F.Cu ({2 * math.pi:.1f} mm) rises "), detail)


class ABoardWithNoSchematicCanClaimItsCopper(unittest.TestCase):
    """``copper-connectivity`` binds ``pcb.unconnected`` and nothing else."""

    def test_the_tag_binds_one_gate(self):
        registry = _registry()
        self.assertEqual([s.id for s in registry.for_claim("C1", ["copper-connectivity"])],
                         ["pcb.unconnected"])
        # Why it is needed: the broader tag brings in the gate that needs a schematic.
        self.assertEqual(sorted(s.id for s in registry.for_claim("C1", ["connectivity"])),
                         ["pcb.parity", "pcb.unconnected"])


class TheTagTableIsTheGates(unittest.TestCase):
    """PACK.md's claim-tag table says which gates each tag binds; it is held to the
    gates' own ``claims``, so a tag added to a gate cannot go unsaid there."""

    def setUp(self):
        self.gates = {s.id: {c.lower() for c in s.claims} for s in _registry().specs()}

    def _table(self) -> dict[str, set[str]]:
        with open(os.path.join(PACK, "PACK.md"), encoding="utf-8") as fh:
            text = fh.read()
        section = text.split("## Claim tags", 1)[1].split("\n## ", 1)[0]
        table = {}
        for line in section.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) != 2 or not cells[0].startswith("`"):
                continue
            bound = (set(self.gates) if cells[1].startswith("every gate")
                     else set(re.findall(r"`([^`]+)`", cells[1])))
            for tag in re.findall(r"`([^`]+)`", cells[0]):
                table[tag] = bound
        return table

    def test_every_row_names_exactly_the_gates_that_list_it(self):
        table = self._table()
        tags = set().union(*self.gates.values())
        self.assertEqual(set(table), tags, "a tag a gate lists is missing from the table, "
                                           "or the table names one no gate lists")
        for tag, bound in table.items():
            with self.subTest(tag=tag):
                self.assertEqual(bound, {g for g, c in self.gates.items() if tag in c})


if __name__ == "__main__":
    unittest.main()
