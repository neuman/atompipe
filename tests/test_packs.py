# SPDX-License-Identifier: Apache-2.0
"""Every shipped pack must validate, and every gate must prove it can fail.

This is the gate on the gates. A pack whose validators have never demonstrated
failure is a pack of loggers, and merging one would quietly convert atompipe from
a thing that checks designs into a thing that agrees with them.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import json
import os
import unittest

from atompipe import gates as gates_mod
from atompipe import packs as packs_mod
from atompipe.models import Ledger, ProjectMeta, Tier

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKS_DIR = os.path.join(REPO, "packs")

#: Text that must never appear anywhere in this repository. atompipe was extracted
#: from a parent project (see docs/ORIGINS.md) and carries its method, not its
#: content — a leaked identifier means a pack is documenting somebody else's device
#: instead of its own domain.
FORBIDDEN = ("cyberdeck", "gripster", "thumbdeck", "keymat", "snap dome")


def _pack_dirs():
    if not os.path.isdir(PACKS_DIR):
        return []
    return sorted(
        os.path.join(PACKS_DIR, name)
        for name in os.listdir(PACKS_DIR)
        if os.path.isdir(os.path.join(PACKS_DIR, name))
        and os.path.isfile(os.path.join(PACKS_DIR, name, "pack.json"))
    )


class PacksValidate(unittest.TestCase):
    def test_at_least_one_pack_ships(self):
        self.assertTrue(_pack_dirs(), "no packs found — packs/ is empty")

    def test_every_pack_validates(self):
        for path in _pack_dirs():
            with self.subTest(pack=os.path.basename(path)):
                problems = packs_mod.validate(path)
                self.assertEqual(problems, [], f"{os.path.basename(path)}: {problems}")

    def test_every_pack_ships_a_tier0_gate(self):
        """A pack of only expensive gates cannot be run in the inner loop, so it
        catches nothing while the design is still cheap to change (rule 10)."""
        for path in _pack_dirs():
            name = os.path.basename(path)
            with self.subTest(pack=name):
                registry = gates_mod.Registry()
                packs_mod.load_gates(name, registry, root=REPO)
                specs = registry.specs()
                self.assertTrue(specs, f"{name} registered no gates")
                self.assertTrue(
                    any(int(s.tier) == int(Tier.INSTANT) for s in specs),
                    f"{name} ships no tier-0 gate: "
                    f"{[(s.id, int(s.tier)) for s in specs]}")

    def test_every_pack_ships_a_validity_guard(self):
        """A pack of closed-form or correlation-based gates needs one gate that
        decides whether its other numbers mean anything.

        Slenderness guards beam theory; Biot guards lumped capacitance; Reynolds
        guards a drag correlation. Without one, the cheap gate silently becomes the
        wrong gate as the design moves out of the range it was valid for — and it
        keeps returning a confident pass the whole way.

        Packs that do not analyse anything (a sourcing or BOM pack has no model to
        outgrow) are exempt.
        """
        exempt = {"sourcing"}
        for path in _pack_dirs():
            name = os.path.basename(path)
            if name in exempt:
                continue
            with self.subTest(pack=name):
                registry = gates_mod.Registry()
                packs_mod.load_gates(name, registry, root=REPO)
                guards = [
                    s.id for s in registry.specs()
                    if any(w in f"{s.id} {s.settles} {s.title} {s.description}".lower()
                           for w in ("valid", "applicab", "regime", "guard", "polic",
                                     "assumption", "hygiene", "is_volume"))
                ]
                self.assertTrue(
                    guards,
                    f"{name} ships no validity guard — nothing tells a caller when the "
                    f"pack's own model has stopped applying (see docs/PACK_FORMAT.md)")

    def test_packs_publish_their_tag_vocabulary(self):
        """A claim can only bind correctly to a pack whose tag names are written
        down. `settles` is that vocabulary and it is what `atompipe gap` matches
        against, so an empty one makes the pack invisible to the capability-gap
        search that is supposed to find it."""
        for path in _pack_dirs():
            name = os.path.basename(path)
            with self.subTest(pack=name):
                manifest = packs_mod.read_manifest(path)
                self.assertTrue(
                    manifest.settles,
                    f"{name}: pack.json declares no `settles` vocabulary, so "
                    f"`atompipe gap` can never propose it for a capability gap")

class NegativeControlsFire(unittest.TestCase):
    """The central invariant, applied to every shipped gate."""

    def _ctx(self, root):
        """A context carrying the pack's own baseline projection.

        Without it a gate SKIPS for want of a parameter and its control never
        fires — so the gate ships unproven while the suite reads green. A skipped
        control is not a passing control, and the whole credibility of this
        project rests on that distinction, so every pack ships
        `selftest/baseline.json`: a plausible, physically coherent projection that
        every one of its gates PASSES. The fixtures then move one thing and the
        gate must flip to FAIL.
        """
        baseline_path = os.path.join(root, "selftest", "baseline.json")
        params: dict = {}
        if os.path.isfile(baseline_path):
            with open(baseline_path, "r", encoding="utf-8") as fh:
                params = json.load(fh)
        return gates_mod.GateContext(
            root=root, ledger=Ledger(meta=ProjectMeta(name="selftest")), model=None,
            params=params, out_dir=os.path.join(root, ".selftest-out"), tier=3,
            log=lambda _m: None, extra={})

    def test_every_pack_ships_a_baseline(self):
        """No baseline means the pack's controls cannot be exercised in CI."""
        for path in _pack_dirs():
            with self.subTest(pack=os.path.basename(path)):
                self.assertTrue(
                    os.path.isfile(os.path.join(path, "selftest", "baseline.json")),
                    f"{os.path.basename(path)}: no selftest/baseline.json — without a "
                    f"plausible projection its gates skip and its negative controls "
                    f"never fire, so nothing here is proven")

    def test_every_gate_passes_its_own_baseline(self):
        """The baseline is supposed to describe a GOOD design.

        A gate that fails on it means one of two things, and both need a human:
        the baseline is not actually good, or the gate is wrong. Either way the
        negative control below proves nothing, because the gate was already
        failing before the fixture touched anything.
        """
        for path in _pack_dirs():
            name = os.path.basename(path)
            if not os.path.isfile(os.path.join(path, "selftest", "baseline.json")):
                continue
            registry = gates_mod.Registry()
            packs_mod.load_gates(name, registry, root=REPO)
            ctx = self._ctx(path)
            for spec in registry.specs():
                _spec, fn = registry.get(spec.id)
                with self.subTest(gate=spec.id):
                    verdict = gates_mod.run_gate(spec, fn, ctx)
                    if verdict.skipped:
                        continue
                    self.assertTrue(
                        verdict.passed,
                        f"{spec.id} FAILS its own pack's baseline: "
                        f"{verdict.detail or verdict.error}")

    def test_every_gate_declares_a_negative_control(self):
        for path in _pack_dirs():
            name = os.path.basename(path)
            registry = gates_mod.Registry()
            packs_mod.load_gates(name, registry, root=REPO)
            for spec in registry.specs():
                with self.subTest(gate=spec.id):
                    self.assertIsNotNone(
                        spec.negative_control,
                        f"{spec.id} has no negative control — it should not have been "
                        f"registerable at all")

    def test_every_negative_control_fires_or_is_honestly_blocked(self):
        """Each gate must FAIL its own known-bad fixture.

        A gate whose dependency is absent reports SKIPPED, which is not a pass and
        not a failure — it is an absence of evidence, and it is allowed here
        because the alternative is refusing to run the suite anywhere the heavy
        tooling is not installed. It is reported so it cannot hide.
        """
        skipped: list[str] = []
        for path in _pack_dirs():
            name = os.path.basename(path)
            registry = gates_mod.Registry()
            packs_mod.load_gates(name, registry, root=REPO)
            ctx = self._ctx(path)
            for spec in registry.specs():
                entry = registry.get(spec.id)
                self.assertIsNotNone(entry, f"{spec.id} vanished from the registry")
                _spec, fn = entry
                with self.subTest(gate=spec.id):
                    verdict = gates_mod.selftest(spec, fn, ctx)
                    if verdict.skipped:
                        skipped.append(f"{spec.id} ({verdict.skip_reason})")
                        continue
                    self.assertTrue(
                        verdict.passed,
                        f"{spec.id} did NOT fail its known-bad fixture "
                        f"({spec.negative_control.fixture if spec.negative_control else '?'}): "
                        f"{verdict.detail or verdict.error} — the gate is a logger")
        if skipped:
            print(f"\n  note: {len(skipped)} control(s) skipped for missing tooling: "
                  f"{', '.join(skipped[:4])}"
                  + ("..." if len(skipped) > 4 else ""))


class ControlsAreSealed(unittest.TestCase):
    """A pack's negative control must fire in EVERY project, not just a friendly one.

    A pack ships to strangers. If its fixture layers the known-bad values over the
    host project's projection, a key the fixture never mentions can still arrive
    from the project and neutralise the control — and gates resolve synonym
    families and derived quantities, so this happens without anyone writing
    anything wrong.

    It was observed live: a hull fixture raised the centre of gravity to make a
    boat unstable, the host project happened to state a waterplane inertia (a
    perfectly honest thing to state, better than the pack's own fallback), the
    metacentric height came out strongly positive, and the gate PASSED ITS OWN
    KNOWN-BAD FIXTURE. A control whose severity depends on the host project's
    numbers is a control that passes in some repositories and fails in others,
    which is the same as having none.

    The probe: run every control against an EMPTY projection as well as against
    the pack's baseline. A sealed fixture states everything its gate reads and
    behaves identically; an inheriting one skips or flips. Project-local fixtures
    are exempt from this — deriving from the project's own model is correct there
    — but a pack's are not.
    """

    def test_controls_fire_without_a_host_projection(self):
        for path in _pack_dirs():
            name = os.path.basename(path)
            registry = gates_mod.Registry()
            packs_mod.load_gates(name, registry, root=REPO)
            baseline_path = os.path.join(path, "selftest", "baseline.json")
            with open(baseline_path, "r", encoding="utf-8") as fh:
                baseline = json.load(fh)

            def ctx_with(params):
                return gates_mod.GateContext(
                    root=path, ledger=Ledger(meta=ProjectMeta(name="sealed")),
                    model=None, params=params,
                    out_dir=os.path.join(path, ".selftest-out"), tier=3,
                    log=lambda _m: None, extra={})

            for spec in registry.specs():
                _spec, fn = registry.get(spec.id)
                with self.subTest(gate=spec.id):
                    rich = gates_mod.selftest(spec, fn, ctx_with(dict(baseline)))
                    bare = gates_mod.selftest(spec, fn, ctx_with({}))
                    if not rich.passed:
                        continue          # covered by the other suite
                    self.assertTrue(
                        bare.passed and not bare.skipped,
                        f"{spec.id}: its control fires against the pack baseline but "
                        f"{'skips' if bare.skipped else 'does NOT fire'} against an empty "
                        f"projection — the fixture is inheriting from the host project "
                        f"instead of stating everything its gate reads, so installing "
                        f"this pack in a different project can silently defuse it "
                        f"({bare.skip_reason or bare.detail})")


class NoLeakedProvenance(unittest.TestCase):
    """atompipe carries the method of its parent project, not its content."""

    def test_repo_is_clean(self):
        allowed = {os.path.join(REPO, "docs", "ORIGINS.md")}
        hits: list[str] = []
        for dirpath, dirnames, filenames in os.walk(REPO):
            dirnames[:] = [d for d in dirnames
                           if d not in {".git", "__pycache__", ".venv", "build", "dist"}
                           and not d.endswith(".egg-info")]
            for filename in filenames:
                if not filename.endswith((".py", ".md", ".json", ".toml", ".txt")):
                    continue
                full = os.path.join(dirpath, filename)
                if full in allowed or full == os.path.abspath(__file__):
                    continue
                try:
                    with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read().lower()
                except OSError:
                    continue
                for word in FORBIDDEN:
                    if word in text:
                        hits.append(f"{os.path.relpath(full, REPO)}: {word!r}")
        self.assertEqual(hits, [], f"leaked references: {hits}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
