# SPDX-License-Identifier: Apache-2.0
"""cfd-openfoam: what its selftest cannot show.

The selftest shows each gate passing the baseline channel and failing one
known-bad case. These tests hold the rest:

- the GCI arithmetic against the published worked examples (Celik et al. 2008's
  Table 1, NASA NPARC's), and the traps in Celik's procedure the paper does not
  state: a positive order for diverging data, the fixed-point iteration that
  fails when r32 > r21;
- the dictionary reader and writer the gates and fixtures edit cases with;
- every refusal of ``cfd.case_readable``, at tier 0, with no OpenFOAM;
- every way a run can look finished when it is not, through a stand-in
  OpenFOAM (``tests/_cfd_standin.py``) whose output is shaped as v2606 wrote it:
  exit 0 without the converged line, SIGFPE, a FATAL error, no ``End``, a banner
  without trapping, a velocity the regime was not judged on, a checkMesh that
  says ``Mesh OK.`` past the project's limit or fails with every value inside
  it, a ladder that diverges, oscillates or converges at an order outside the
  band, a refined level that never converges, and an install that is the
  Foundation's or another ESI release;
- one class that runs the real OpenFOAM, where it is installed: the baseline
  against its exact answer, a ``#calc`` the private HOME stops, and a user
  controlDict that turns trapping off and never reaches the run.

What slipped through while the pack was written, each held here: checkMesh
exits 0 on a failed mesh; simpleFoam exits 0 when it runs out of iterations; the
wrapper's ``exec "/usr/lib/openfoam/openfoam2606"/etc/openfoam`` puts its quote
before ``/etc``, and the first reader of it found no install at all.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p test_cfd_openfoam.py -v
"""
from __future__ import annotations

import csv
import json
import math
import os
import shutil
import stat
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

import _env
from nopekit import claims as claims_mod
from nopekit import gates as gates_mod
from nopekit import packs as packs_mod
from nopekit.modelio import load_path
from nopekit.models import Comparator, Ledger, ProjectMeta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(REPO, "packs", "cfd-openfoam")
CHANNEL = os.path.join(PACK, "selftest", "assets", "channel")
STANDIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cfd_standin.py")

F = load_path(os.path.join(PACK, "gates", "_foam.py"))
G = load_path(os.path.join(PACK, "gates", "_gci.py"))
T = load_path(os.path.join(PACK, "gates", "_tool.py"))
I = load_path(os.path.join(PACK, "gates", "_iter.py"))
HISTORIES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cfd_histories")


def _baseline() -> dict:
    with open(os.path.join(PACK, "selftest", "baseline.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    params = {k: v for k, v in data.items() if not k.startswith("_")}
    params["cfd_case"] = CHANNEL
    return params


def _registry() -> gates_mod.Registry:
    registry = gates_mod.Registry()
    packs_mod.load_gates("cfd-openfoam", registry, root=REPO, include_env=False,
                         include_user=False)
    return registry


def _claims(limit=None, **acceptance) -> list:
    """The baseline's own claims (``_claims``), as the pack's controls read
    them; ``limit`` and ``acceptance`` move the pressure-drop claim's
    condition."""
    with open(os.path.join(PACK, "selftest", "baseline.json"), encoding="utf-8") as fh:
        claims = packs_mod.baseline_claims(json.load(fh))
    if limit is not None:
        acceptance["limit"] = limit
    for claim in claims:
        for key, value in acceptance.items():
            setattr(claim.acceptance, key, value)
    return claims


def _run(registry, gid: str, root: str, params: dict, *, tier: int = 2, claims=None):
    spec_fn = registry.get(gid)
    assert spec_fn is not None, f"{gid} is not in the pack"
    ctx = gates_mod.GateContext(
        root=root, ledger=Ledger(meta=ProjectMeta(name="cfd"),
                                 claims=_claims() if claims is None else claims), model=None,
        params=dict(params), out_dir=os.path.join(root, "out", gid.replace(".", "_")),
        tier=tier, log=lambda _m: None, extra={})
    return gates_mod.run_gate(*spec_fn, ctx)


def _copy_case(dst: str) -> str:
    shutil.copytree(CHANNEL, dst)
    return dst


def _edit(case: str, rel: str, entry: str, value: str) -> None:
    path = os.path.join(case, *rel.split("/"))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(F.set_entry(text, entry, value))


# --------------------------------------------------------------------------- #
# what the gates cover
# --------------------------------------------------------------------------- #
class EachGateCoversOnlyWhatItJudges(unittest.TestCase):
    """Review of issue #15's D2: every gate also covered ``cfd``,
    ``fluid-dynamics`` and ``internal-flow``, so a claim tagged ``cfd`` alone,
    "static pressure drop <= 0.5 Pa", read Checked — `check` said ready — on
    cfd.pressure_drop's pass against the 5 Pa of the claim tagged
    ``pressure-drop``. Now no gate here covers those tags: such a claim reads
    Gap, and the claim tagged ``pressure-drop`` keeps all six."""

    def test_a_claim_tagged_only_broadly_reads_gap(self):
        from nopekit.models import Acceptance, Claim, Verdict
        registry = _registry()
        broad = Claim(id="C2", statement="The static pressure drop is at most 0.5 Pa",
                      acceptance=Acceptance(quantity="static pressure drop",
                                            comparator=Comparator.LE, limit=0.5, units="Pa"),
                      tags=["cfd", "fluid-dynamics", "internal-flow"], critical=True)
        claims = [*_claims(5.0), broad]
        verdicts = [Verdict(gate=spec.id, claims=["C1"], passed=True)
                    for spec in (spec for spec, _fn in (registry.get(g)
                                                        for g in registry.ids()))]
        ledger = Ledger(meta=ProjectMeta(name="cfd"), claims=claims, verdicts=verdicts)
        cover = claims_mod.effective_gates(ledger, registry)
        self.assertEqual(list(cover.get("C2") or ()), [])
        self.assertEqual(sorted(cover.get("C1") or ()), sorted(registry.ids()))
        found = claims_mod.compositions(ledger, registry=registry)
        self.assertEqual(found["C2"].status, claims_mod.ClaimStatus.UNCLAIMED)


# --------------------------------------------------------------------------- #
# the GCI arithmetic
# --------------------------------------------------------------------------- #
class TheGciIsCeliksArithmetic(unittest.TestCase):
    """Each published number at its printed precision (references/gci.md)."""

    def test_celik_table_1_column_1_monotone(self):
        r = G.gci((6.063, 5.972, 5.863), cells=(18000, 8000, 4500), dim=2)
        self.assertEqual(r.convergence, G.MONOTONE_CONVERGENCE)
        self.assertAlmostEqual(r.r21, 1.5, places=6)
        self.assertEqual(round(r.p, 2), 1.53)
        self.assertEqual(round(r.phi_ext21, 4), 6.1685)
        self.assertEqual(round(r.e_a21 * 100, 1), 1.5)
        self.assertEqual(round(r.e_ext21 * 100, 1), 1.7)
        self.assertEqual(round(r.gci_fine21 * 100, 1), 2.2)

    def test_celik_table_1_column_3_oscillatory(self):
        r = G.gci((6.0042, 5.9624, 6.0909), cells=(18000, 4500, 980), dim=2)
        self.assertEqual(r.convergence, G.OSCILLATORY_CONVERGENCE)
        self.assertEqual(r.s, -1.0)
        self.assertEqual(round(r.p, 2), 1.51)
        self.assertEqual(round(r.phi_ext21, 4), 6.0269)
        self.assertEqual(round(r.gci_fine21 * 100, 1), 0.5)

    def test_column_2s_printed_r_is_rounded(self):
        """r must come from the cell counts: the printed r32 = 1.333 moves
        phi_ext to 6.1682, off the table's 6.1685."""
        r = G.gci((6.063, 5.972, 5.863), h=(1.0, 1.5, 1.5 * 1.333))
        self.assertEqual(round(r.phi_ext21, 4), 6.1682)

    def test_nparc_worked_example(self):
        p, f0, g12, g23, _ratio = G.gci_constant_r((0.97050, 0.96854, 0.96178), 2.0)
        self.assertEqual(round(p, 6), 1.786170)
        self.assertEqual(round(f0, 5), 0.97130)
        self.assertEqual(round(g12 * 100, 6), 0.103083)
        self.assertEqual(round(g23 * 100, 6), 0.356249)
        r = G.gci((0.97050, 0.96854, 0.96178), h=(1.0, 2.0, 4.0))
        self.assertAlmostEqual(r.p, p, places=6)

    def test_diverging_data_still_get_a_positive_order_and_are_named(self):
        """Eq. (3a)'s absolute value gives p = 1 to (1.0, 1.1, 1.15) at r = 2:
        the classifier, not the sign of p, is what refuses it."""
        r = G.gci((1.0, 1.1, 1.15), h=(1.0, 2.0, 4.0))
        self.assertEqual(r.convergence, G.MONOTONE_DIVERGENCE)
        self.assertAlmostEqual(r.p, 1.0, places=6)
        self.assertTrue(any("not an order" in w for w in r.warnings), r.warnings)

    def test_the_fixed_point_fails_where_r32_exceeds_r21_and_bisection_recovers(self):
        h1, r21, r32, p = 1.0, 1.1, 3.0, 2.0
        h = (h1, h1 * r21, h1 * r21 * r32)
        phi = tuple(1.0 + 0.1 * x ** p for x in h)
        _p, _s, _its, ok = G.apparent_order_fixed_point(phi[1] - phi[0], phi[2] - phi[1],
                                                        r21, r32)
        self.assertFalse(ok)
        r = G.gci(phi, h=h)
        self.assertEqual(r.p_method, "bisection")
        self.assertAlmostEqual(r.p, p, places=6)

    def test_the_asymptotic_ratio_is_phi1_over_phi2(self):
        r = G.gci((6.063, 5.972, 5.863), cells=(18000, 8000, 4500), dim=2)
        self.assertAlmostEqual(r.asymptotic_ratio, 6.063 / 5.972, places=12)

    def test_a_difference_inside_the_noise_is_unresolved(self):
        r = G.gci((1.0, 1.0001, 1.01), h=(1.0, 2.0, 4.0), noise=0.001)
        self.assertEqual(r.convergence, G.UNRESOLVED)
        self.assertIsNone(r.p)


# --------------------------------------------------------------------------- #
# the dictionary reader and writer
# --------------------------------------------------------------------------- #
class TheReaderReadsWhatOpenFOAMReads(unittest.TestCase):

    def test_scalar_forms(self):
        d = F.parse("a 1e-05; b [0 2 -1 0 0 0 0] 2; c c [0 2 -1 0 0 0 0] 3; d $a; "
                    "e #eval{ 2*3 }; s { x 4; y $..a; }")
        self.assertEqual(F.scalar(d, "a"), 1e-05)
        self.assertEqual(F.scalar(d, "b"), 2.0)
        self.assertEqual(F.scalar(d, "c"), 3.0)
        self.assertEqual(F.scalar(d, "d"), 1e-05)
        self.assertIsNone(F.scalar(d, "missing"))
        with self.assertRaises(F.Unresolved):
            F.scalar(d, "e")

    def test_a_regex_key_matches_whole(self):
        d = F.parse('"(U|k)" { solver x; } p { solver y; }')
        self.assertEqual(F.word(d.sub("U"), "solver"), "x")
        self.assertIsNone(d.sub("Ux"))

    def test_set_entry_keeps_every_other_byte(self):
        with open(os.path.join(CHANNEL, "system", "controlDict"), encoding="utf-8") as fh:
            text = fh.read()
        new = F.set_entry(text, "endTime", "5")
        self.assertEqual(F.scalar(F.parse(new), "endTime"), 5.0)
        self.assertEqual(new.replace("endTime         5;", "endTime         2000;"), text)
        with self.assertRaises(KeyError):
            F.set_entry(text, "noSuchEntry", "1")

    def test_put_entry_removes_every_repeat(self):
        """OpenFOAM MERGES a repeated dictionary keyword: replacing only the
        last ``functions`` would leave the first one's function objects running."""
        text = "a 1;\nfunctions { one { type x; } }\nb 2;\nfunctions { two { type y; } }\n"
        new = F.put_entry(text, "functions", "functions { mine { type z; } }")
        d = F.parse(new)
        self.assertEqual(d.sub("functions").keys(), ["mine"])
        self.assertEqual([e.key for e in d.entries], ["a", "b", "functions"])
        nested = F.put_entry("SIMPLE { x 1; residualControl { p 1e-2; } }",
                             "SIMPLE/residualControl", "residualControl { p 1e-6; }")
        self.assertEqual(F.scalar(F.parse(nested).sub("SIMPLE/residualControl"), "p"), 1e-6)

    def test_the_solver_log_reads_the_first_solve_and_the_criteria(self):
        text = ("SIMPLE: convergence criteria\n    field p\t tolerance 1e-06\n"
                "    field U\t tolerance 1e-06\n\nTime = 1\n\n"
                "GAMG:  Solving for p, Initial residual = 0.5, Final residual = 0.01, No Iterations 3\n"
                "GAMG:  Solving for p, Initial residual = 0.001, Final residual = 1e-5, No Iterations 2\n"
                "Time = 2\n\nsmoothSolver:  Solving for Ux, Initial residual = 1e-07, Final "
                "residual = 1e-9, No Iterations 1\nGAMG:  Solving for p, Initial residual = "
                "4e-07, Final residual = 1e-9, No Iterations 1\nGAMG:  Solving for p, Initial "
                "residual = 1e-09, Final residual = 1e-11, No Iterations 1\n\n"
                "SIMPLE solution converged in 2 iterations\n\nEnd\n")
        log = T.solver_log(text)
        self.assertEqual(log.criteria, {"p": 1e-06, "U": 1e-06})
        self.assertEqual(log.residuals, {"Ux": 1e-07, "p": 4e-07})
        self.assertEqual((log.converged_in, log.last_iteration), (2, 2))

    def test_check_mesh_and_dat_readers_refuse_what_they_cannot_read_whole(self):
        ok = ("    cells:            4\n    Mesh has 2 geometric (non-empty/wedge) directions\n"
              "    Max aspect ratio = 1 OK.\n    Mesh non-orthogonality Max: 0 average: 0\n"
              "    Max skewness = 0 OK.\nMesh OK.\n")
        self.assertTrue(T.check_mesh(ok).ok)
        with self.assertRaises(ValueError):
            T.check_mesh(ok + "Failed 1 mesh checks.\n")
        d = os.path.join(self.tmp() if hasattr(self, "tmp") else os.path.dirname(STANDIN), "x.dat")
        try:
            with open(d, "w") as fh:
                fh.write("# Time\tareaAverage(p)\n1\t0.5\t0.7\n")
            with self.assertRaises(ValueError):
                T.read_dat(d)
        finally:
            os.remove(d)

    def test_the_formal_order_is_the_momentum_schemes(self):
        """The order is ``div(phi,U)``'s, or ``default``'s where the case gives
        none. What slipped through until P0.1: any ``upwind`` in any divSchemes
        entry gave order 1 (``AFinishedLookingRunIsNotAPass`` holds the ladder
        that failed)."""
        C = _registry().get("cfd.converged")[1].__globals__
        order = lambda text: C["_formal_order"](F.parse("divSchemes { " + text + " }"))
        self.assertEqual(order("default none; div(phi,U) bounded Gauss linearUpwind grad(U); "
                               "div(phi,k) bounded Gauss upwind;"), 2)
        self.assertEqual(order("default none; div(phi,U) bounded Gauss upwind;"), 1)
        self.assertEqual(order('default none; "div\\(phi,.*\\)" bounded Gauss upwind;'), 1)
        self.assertEqual(order("default Gauss upwind;"), 1)
        self.assertEqual(order("default Gauss upwind; div(phi,U) Gauss linear;"), 2)

    def test_a_malformed_file_is_refused_whole(self):
        for text in ("a 1", "a { b 1;", "a (1 2;", "}"):
            with self.subTest(text=text), self.assertRaises(F.FoamFormatError):
                F.parse(text)


# --------------------------------------------------------------------------- #
# the iterative-error estimate
# --------------------------------------------------------------------------- #
def _histories(name: str) -> dict:
    """Real pressure-drop histories (``tests/cfd_histories``, each file's
    ``_provenance`` names the case, the solver and how it was run)."""
    with open(os.path.join(HISTORIES, name), encoding="utf-8") as fh:
        return json.load(fh)["histories"]


def _settles(s, cut: int) -> bool:
    """The gate's line on the first ``cut`` values: estimate <= STABLE_TOL x |last|."""
    rem = I.remaining(s[:cut])
    return rem is not None and rem <= 1e-3 * abs(s[cut - 1])


def _from_changes(change, n: int, extra: int = 40000) -> list:
    """phi_n = 1 + the sum of change(k) for k > n: a monotone history converging
    to 1 (GitHub #15 Phase 0's construction, the sum taken from the far end)."""
    d = [change(k) for k in range(n + extra)]
    tail = [0.0] * (len(d) + 1)
    for i in range(len(d) - 1, -1, -1):
        tail[i] = tail[i + 1] + d[i]
    return [1.0 + tail[i + 1] for i in range(n)]


class TheIterativeErrorEstimate(unittest.TestCase):
    """``_iter.remaining`` against the negative controls of GitHub #15 Phase 0
    (the judge's section 9). Each "never" is a history the estimator it
    replaced (``cfd._remaining`` until P0.1) read settled while more than 0.1%
    from its limit, at the cut points named in each test; each "must settle" is
    one it read settled too, kept so a stricter estimator cannot fail a converged
    run. The long histories are read at every cut point of a stride (the
    estimate costs a few milliseconds a cut on 6000 values)."""

    N = 3000

    def never(self, s, cuts, truth=None):
        """Not settled at any of ``cuts`` where the value is more than 0.1% from
        ``truth`` (every cut when there is none: a history that never converges)."""
        bad = [c for c in cuts if (truth is None or abs(s[c - 1] - truth) > 1e-3 * abs(truth))
               and _settles(s, c)]
        self.assertEqual(bad, [], "read settled at these cut points")

    # -- the plain readings ---------------------------------------------------
    def test_the_plain_readings(self):
        self.assertEqual(I.remaining([1.0] * 25), 0.0)
        self.assertIsNone(I.remaining([1.0] * 16))
        self.assertIsNotNone(I.remaining([1.0] * 17))
        creeping = [1.0 + 0.1 * 0.97 ** i for i in range(200)]
        # At least what is still to come, 0.1 x 0.97^199, and not twice it: C&F's
        # 1.25 and the slope's bound on a fit with no scatter.
        to_come = 0.1 * 0.97 ** 199
        self.assertGreaterEqual(I.remaining(creeping), to_come)
        self.assertLess(I.remaining(creeping), 2 * to_come)
        # An oscillation that does not decay, and a ramp: no decay to extrapolate.
        # (The estimator P0.1 replaced read the oscillation as its swing, 2e-3.)
        self.assertEqual(I.remaining([1.0 + 1e-3 * (-1) ** i for i in range(25)]), math.inf)
        self.assertEqual(I.remaining([1.0 + 1e-3 * i for i in range(25)]), math.inf)
        # A run that just moved 0.17%: at least that (an earlier draft passed one
        # 0.22% from converged).
        self.assertGreaterEqual(I.remaining([1.0 + 0.0017 * (20 - i) / 20 + 1e-7 * i * i
                                             for i in range(21)]), 0.0017)

    def test_a_flat_tail_with_too_little_before_it_reads_inf(self):
        """A flat tail after an exact repeat is a print step, not round-off, and
        goes to the fit; with fewer than WINDOW_MIN changes before it there is no
        decay to fit. What slipped through until the P0 review: that came back as
        None, and the gate said "fewer than the 17 needed" of 31 iterations."""
        s = [1.0, 1.0, 1.1, 1.2, 1.25, 1.27] + [1.27] * 25
        self.assertEqual(I.remaining(s), math.inf)
        C = _registry().get("cfd.converged")[1].__globals__
        solve = SimpleNamespace(log=SimpleNamespace(converged_in=31, last_iteration=31,
                                                    residuals={"p": 1e-7, "Ux": 1e-7}),
                                dp=lambda: s)
        self.assertEqual(C["_settled"](solve, 1e-6, 2000),
                         ["the pressure drop is still moving: its changes do not decrease at "
                          "a steady rate, so the gate cannot estimate the change still to come"])

    def test_a_value_that_is_not_a_number_is_never_settled(self):
        """The estimator P0.1 replaced read a NaN 11 values from the end as 0.0."""
        self.assertEqual(I.remaining([1.0] * 10 + [math.nan] + [1.0] * 20), math.inf)
        self.assertEqual(I.remaining([1.0] * 30 + [math.inf]), math.inf)

    def test_the_gate_refuses_a_last_value_of_inf(self):
        """inf <= STABLE_TOL x abs(inf) is True: without its own refusal the gate
        read a run whose last value is inf as settled."""
        C = _registry().get("cfd.converged")[1].__globals__
        for series in ([1.0] * 30 + [math.inf], [1.0] * 10 + [math.nan] + [1.0] * 20):
            with self.subTest(last=series[-1]):
                solve = SimpleNamespace(
                    log=SimpleNamespace(converged_in=31, last_iteration=31,
                                        residuals={"p": 1e-7, "Ux": 1e-7}),
                    dp=lambda s=series: s)
                why = C["_settled"](solve, 1e-6, 2000)
                self.assertEqual(why, ["the pressure drop is not a finite number at every "
                                       "iteration"])

    # -- synthetic: the limit is known ----------------------------------------
    def test_a_slow_mode_under_a_fast_one(self):
        """Two modes: the old estimator read it settled at cuts 28-43 and 220, up
        to 0.29% out; eh-faithful (no rate-change test) at cuts 21-37."""
        s = [1 + 0.3 * 0.7 ** n + 0.003 * 0.995 ** n for n in range(self.N)]
        self.never(s, range(17, 221), truth=1.0)

    def test_an_overshoot_before_its_turning_point(self):
        """Not settled at cuts 21-30, which the one-sided rate test read settled
        (the old estimator at 28-52), nor at 31-34, which SPEED_FLOOR 1e-5 let
        through until the P0 review. Cuts 35 and 36, just past the turning point,
        are the documented miss (``_iter.remaining``)."""
        s = [1 + 0.05 * 0.8 ** n - 0.003 * 0.997 ** n for n in range(self.N)]
        self.never(s, range(21, 35), truth=1.0)

    def test_a_slow_overshoot_before_its_turning_point(self):
        """SPEED_FLOOR's control (P0 review): two slow modes of opposite sign
        change by less than 1e-5 of the value per iteration long before
        round-off. Under the judged floor (1e-5) the dive test never fired, and
        these read settled near their extremum, 2.2% and 3.6% from the limit, at
        cuts 233-248 and 510-514. The cuts at the turning point itself (246 and
        248, 511-514) are the documented miss."""
        s = [1 + 0.05 * 0.995 ** n - 0.06 * 0.998 ** n for n in range(250)]
        self.never(s, range(17, 246), truth=1.0)
        s = [1 + 0.1 * 0.998 ** n - 0.12 * 0.999 ** n for n in range(520)]
        self.never(s, range(17, 511), truth=1.0)

    def test_a_power_law_creep(self):
        """1 + 0.05/sqrt(n+1) never decays geometrically: never settled. The old
        estimator read it settled from cut 266 on; without the rate test, or with
        a 5% slack on it, 2071 cuts."""
        s = [1 + 0.05 / math.sqrt(n + 1) for n in range(self.N)]
        self.never(s, range(17, self.N + 1, 13))

    def test_a_creep_under_a_fast_oscillation(self):
        """The model-free reading's control: not settled at cuts 73-109 but 76
        (every one of them settled by the old estimator, and without the reading,
        up to 0.44% out)."""
        s = [1 + 0.005 * 0.998 ** n + 0.05 * 0.9 ** n * (-1) ** n for n in range(self.N)]
        self.never(s, [c for c in range(73, 110) if c != 76], truth=1.0)

    def test_a_creep_printed_to_seven_digits(self):
        """STAIRS: 1 + 0.002 x 0.99995^n printed as OpenFOAM's default
        writePrecision 6 prints it moves one quantum about every ten iterations,
        always 0.17-0.20% from its limit. The old estimator read it settled at
        2980 of 2984 cuts; a round-off rule without the staircase test at 767."""
        s = [float("%.7g" % (1 + 0.002 * 0.99995 ** n)) for n in range(self.N)]
        self.never(s, range(17, self.N + 1, 13))

    def test_a_drift_above_the_round_off_floor(self):
        """1 + 2e-8 n never converges. The old estimator read it settled at 2980
        of 2984 cuts, ROUNDOFF 1e-7 at 187. (A drift of 5e-9 per iteration, under
        ROUNDOFF, is the documented miss.)"""
        s = [1 + 2e-8 * n for n in range(self.N)]
        self.never(s, range(17, self.N + 1, 13))

    def test_a_rate_that_slows(self):
        """eh-faithful's control: changes 0.05 x 0.85^k, then from k = 40 at
        0.995 per iteration. Not settled from cut 44 until the value is within
        0.1% (the old estimator read cuts 45 and 46 settled, 1.4% out). Cuts 39-43
        are the documented miss."""
        a2 = 0.05 * 0.85 ** 40
        s = _from_changes(lambda k: 0.05 * 0.85 ** k if k < 40 else a2 * 0.995 ** (k - 40),
                          self.N)
        self.never(s, range(44, 700), truth=1.0)

    # -- real v2606 histories -------------------------------------------------
    def test_the_packs_own_runs_settle(self):
        """Every history the selftest's cfd.converged judges must read settled at
        its stop. The coarse channel (the known-bad of cfd.mesh_independence)
        ends accelerating from 7e-6 to 5e-11 of its value, which SPEED_FLOOR lets
        through; the baseline's level 1 decays through troughs of 8e-9 of its
        value, which STAIRS reads as round-off; at ROUNDOFF 1e-9 the thicker
        fluid's level 1 read inf."""
        for fixture in ("case_baseline.json", "case_thicker_fluid.json", "coarse.json"):
            for name, s in _histories(fixture).items():
                with self.subTest(fixture=fixture, history=name):
                    self.assertTrue(_settles(s, len(s)), f"{name}: {I.remaining(s)}")

    def test_an_oscillation_that_decays_settles(self):
        """The running maximum's control: 1 + 0.1 x 0.995^n cos(2n) first reads
        settled at cut 2136 and reads settled at cut 3000 (between them, about
        half of the cuts read not settled). Fitted on the changes themselves, a
        window that starts in a trough reads as growing, and it never settled in
        3000 iterations."""
        s = [1 + 0.1 * 0.995 ** n * math.cos(2 * n) for n in range(self.N)]
        self.assertTrue(_settles(s, self.N))

    def test_real_turbulent_histories_never_settle(self):
        """The v2606 tutorials pitzDaily and pitzDailyExptInlet, 2000 iterations
        each, still moving: the old estimator read them settled at 94 and 234 of
        their cuts while more than 0.1% from their last values (up to 1.04% and
        2.46% from it)."""
        for name, s in _histories("pitz_dev.json").items():
            with self.subTest(name):
                self.never(s, range(17, len(s) + 1, 5))

    def test_a_laminar_pitzdaily_under_slow_relaxation_never_settles(self):
        """The strongest real control: laminar pitzDaily (nu 1e-3, U relaxed to
        0.3), the flow a laminar gate decides alone. The old estimator read it
        settled at cut points up to 23.4% from the converged value."""
        s = _histories("lam_nu1e-3_r.json")["lam_nu1e-3_r"]
        self.never(s, range(20, len(s) + 1, 20))


# --------------------------------------------------------------------------- #
# the tier-0 guard
# --------------------------------------------------------------------------- #
class TheGuardRefusesWhatItCannotVouchFor(_env.EnvCase):
    """Each refusal is a FAIL of cfd.case_readable, naming what it found."""

    def setUp(self):
        self.registry = _registry()
        self.params = _baseline()

    def _readable(self, case: str):
        return _run(self.registry, "cfd.case_readable", self.tmp(),
                    dict(self.params, cfd_case=case), tier=0)

    def test_the_baseline_reads(self):
        v = self._readable(CHANNEL)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("500 cells", v.detail)

    def test_each_refusal(self):
        cases = {
            "calc": ("system/controlDict", "endTime", "#calc \"2*1000\"", "#calc"),
            "turbulent": ("constant/turbulenceProperties", "simulationType", "RAS",
                          "laminar flow only"),
            "solver": ("system/controlDict", "application", "icoFoam", "simpleFoam only"),
            "power_law": ("constant/transportProperties", "transportModel", "powerLaw",
                          "Newtonian"),
            "stop_at": ("system/controlDict", "stopAt", "writeNow", "stopAt writeNow"),
            "computed_count": ("system/blockMeshDict", "blocks",
                               "( hex (0 1 3 2 4 5 7 6) (#eval{ 25*2 } 10 1) simpleGrading "
                               "(1 1 1) )", "computed"),
            "coded_source": ("0/p", "boundaryField/outlet",
                             "type codedMixed; refValue uniform 0;", "codedMixed"),
        }
        for name, (rel, entry, value, said) in cases.items():
            with self.subTest(name):
                case = _copy_case(os.path.join(self.tmp(), "case"))
                _edit(case, rel, entry, value)
                v = self._readable(case)
                self.assertEqual(v.outcome, "fail", v.render())
                self.assertIn(said, v.detail)

    def test_an_include_outside_the_case(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        path = os.path.join(case, "constant", "transportProperties")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('\n#include "../../elsewhere"\n')
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("#include, a directive OpenFOAM evaluates", v.detail)

    def _with_directive(self, line: str, *, rels=("0/U", "0/p"), where="boundaryField"):
        """A copy of the baseline with ``line`` written where ESI writes it:
        the first entry of each 0/ file's ``boundaryField`` (or at the top of
        the file, ``where=""``)."""
        case = _copy_case(os.path.join(self.tmp(), "case"))
        for rel in rels:
            path = os.path.join(case, *rel.split("/"))
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            if where == "boundaryField, last":
                head = "boundaryField\n{\n"
                self.assertEqual(text.count(head), 1, rel)
                at = text.index("\n}\n", text.index(head)) + 1
                text = text[:at] + "    " + line + "\n" + text[at:]
            elif where:
                head = "boundaryField\n{\n"
                self.assertEqual(text.count(head), 1, rel)
                text = text.replace(head, head + "    " + line + "\n\n")
            else:
                text = text.rstrip("\n") + "\n\n" + line + "\n"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        return self._readable(case)

    def test_the_one_allowed_directive_is_allowed(self):
        """What slipped through: the comparison held the quoted spelling and the
        reader's token holds none, so the include PACK.md allows, in every 0/
        file ESI writes, was refused."""
        v = self._with_directive('#includeEtc "caseDicts/setConstraintTypes"')
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertNotIn("#includeEtc", v.detail)

    def test_every_other_include_etc_is_refused(self):
        cases = {
            "one letter short": ('#includeEtc "caseDicts/setConstraintType"', "boundaryField",
                                 ("0/U",)),
            "one letter long": ('#includeEtc "caseDicts/setConstraintTypess"', "boundaryField",
                                ("0/U",)),
            "another file": ('#includeEtc "caseDicts/mesh/generation/meshQualityDict"',
                             "boundaryField", ("0/p",)),
            "unquoted": ("#includeEtc caseDicts/setConstraintTypes", "boundaryField",
                         ("0/U",)),
            "a path to it": ('#includeEtc "../caseDicts/setConstraintTypes"', "boundaryField",
                             ("0/U",)),
            "outside boundaryField": ('#includeEtc "caseDicts/setConstraintTypes"', "",
                                      ("0/U",)),
            "outside 0/": ('#includeEtc "caseDicts/setConstraintTypes"', "",
                           ("system/controlDict",)),
            "another directive": ('#include "caseDicts/setConstraintTypes"', "boundaryField",
                                  ("0/U",)),
            # Review of P1: read after the patches, an etc file found first in
            # the user's directory merged into them at run time.
            "after the patches": ('#includeEtc "caseDicts/setConstraintTypes"',
                                  "boundaryField, last", ("0/U",)),
        }
        for name, (line, where, rels) in cases.items():
            with self.subTest(name):
                v = self._with_directive(line, rels=rels, where=where)
                self.assertEqual(v.outcome, "fail", v.render())
                self.assertIn("a directive OpenFOAM evaluates", v.detail)

    def test_the_gates_home_holds_only_its_control_dict(self):
        """Review of P1: OpenFOAM finds ``#includeEtc "caseDicts/
        setConstraintTypes"`` in ``$HOME/.OpenFOAM/<api>/`` (then
        ``$HOME/.OpenFOAM/``) before the install, and the gate's HOME outlives
        its run. Whatever was planted there, a run's HOME holds the controlDict
        alone, with the pack's text."""
        out = self.tmp()
        root = os.path.join(out, "cfd-openfoam", "home")
        user = os.path.join(root, ".OpenFOAM")
        planted = {
            os.path.join(user, "2606", "caseDicts", "setConstraintTypes"):
                "inlet { type uniformFixedValue; uniformValue constant (2 0 0); }\n",
            os.path.join(user, "caseDicts", "setConstraintTypes"): "inlet { }\n",
            os.path.join(user, "controlDict"): "InfoSwitches { allowSystemOperations 1; }\n",
            os.path.join(root, ".bashrc"): "export FOAM_SIGFPE=false\n",
        }
        for path, text in planted.items():
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
        elsewhere = os.path.join(self.tmp(), "elsewhere")
        with open(elsewhere, "w", encoding="utf-8") as fh:
            fh.write("InfoSwitches { allowSystemOperations 1; }\n")
        cfg = os.path.join(user, "2606", "controlDict")
        os.symlink(elsewhere, cfg)
        for _ in range(2):
            self.assertEqual(T.home(out, 2606), root)
            found = sorted(os.path.relpath(os.path.join(d, f), root)
                           for d, dirs, files in os.walk(root) for f in files + [
                               x for x in dirs if os.path.islink(os.path.join(d, x))])
            self.assertEqual(found, [os.path.join(".OpenFOAM", "2606", "controlDict")])
            self.assertFalse(os.path.islink(cfg))
            with open(cfg, encoding="utf-8") as fh:
                self.assertEqual(fh.read(), T._USER_CONTROLDICT)
        with open(elsewhere, encoding="utf-8") as fh:
            self.assertIn("allowSystemOperations 1", fh.read())
        # A link where the user directory belongs is removed, never followed.
        shutil.rmtree(user)
        target = os.path.join(self.tmp(), "target")
        os.makedirs(os.path.join(target, "2606", "caseDicts"))
        with open(os.path.join(target, "2606", "caseDicts", "setConstraintTypes"), "w") as fh:
            fh.write("inlet { }\n")
        os.symlink(target, user)
        T.home(out, 2606)
        self.assertFalse(os.path.islink(user))
        self.assertTrue(os.path.exists(os.path.join(target, "2606", "caseDicts",
                                                    "setConstraintTypes")))
        self.assertFalse(os.path.exists(os.path.join(user, "2606", "caseDicts")))

    def _appended(self, rel: str, text: str):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        with open(os.path.join(case, *rel.split("/")), "a", encoding="utf-8") as fh:
            fh.write("\n" + text + "\n")
        return self._readable(case)

    def test_what_the_reader_does_not_evaluate_is_refused(self):
        """What slipped through the first draft, each now a fail: a condition
        that set the nu the solver ran, a merge into the pack's function
        objects, a coded type behind a macro or a regex key, a laminar model
        that is not Newtonian, U never solved."""
        cases = [
            ("constant/transportProperties", "#if 1\nnu 5e-08;\n#else\nnu 1e-05;\n#endif",
             "#if, a directive"),
            ("system/controlDict", '#sinclude "extra"', "#sinclude, a directive"),
            ("system/controlDict", "extra { functions { a { type x; } } }\n$extra;",
             "$extra, a dictionary expanded in place"),
            ("system/controlDict", 'libs ("libmine.so");', "loads libraries"),
            ("0/U", "kind codedFixedValue;", "compiles C++"),
            ("0/p", "level $kind;", "is a macro"),
            ("constant/turbulenceProperties",
             "laminar { model generalizedNewtonian; viscosityModel powerLaw; }",
             "laminar model 'generalizedNewtonian'"),
            ("system/fvSolution", "SIMPLE { momentumPredictor no; }", "momentumPredictor is off"),
            ("system/fvSchemes", '"div.*" { default none; }', "a quoted keyword here"),
        ]
        for rel, text, said in cases:
            with self.subTest(text=text):
                v = self._appended(rel, text)
                self.assertEqual(v.outcome, "fail", v.render())
                self.assertIn(said, v.detail)

    def test_a_regex_key_that_stands_for_type_is_refused(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "0/U", "boundaryField/inlet", '"typ(e)" fixedValue; value uniform (0.01 0 0);')
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("a quoted keyword here could stand for", v.detail)

    def test_only_the_files_the_pack_reads(self):
        for rel in ("constant/fvOptions", "system/extraFunctions", "constant/nuActual"):
            with self.subTest(rel):
                case = _copy_case(os.path.join(self.tmp(), "case"))
                with open(os.path.join(case, *rel.split("/")), "w") as fh:
                    fh.write(F.foam_file("dictionary", rel.split("/")[-1], "a 1;"))
                v = self._readable(case)
                self.assertEqual(v.outcome, "fail", v.render())
                self.assertIn(f"the case holds {rel}", v.detail)
        case = _copy_case(os.path.join(self.tmp(), "case"))
        os.remove(os.path.join(case, "system", "blockMeshDict"))
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("no system/blockMeshDict", v.detail)

    def test_a_directory_in_the_case_is_refused(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        os.makedirs(os.path.join(case, "constant", "triSurface"))
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("the case holds constant/triSurface/", v.detail)

    def test_a_linked_file_is_read_through_its_link(self):
        """A link is not refused (the second review: that refusal rested on a
        stat no key holds); its bytes are read, keyed and judged as any file's."""
        case = _copy_case(os.path.join(self.tmp(), "case"))
        target = os.path.join(self.tmp(), "p")
        shutil.copyfile(os.path.join(case, "0", "p"), target)
        with open(target, "a") as fh:
            fh.write("\nlevel #calc \"1\";\n")
        os.remove(os.path.join(case, "0", "p"))
        os.symlink(target, os.path.join(case, "0", "p"))
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("#calc", v.detail)

    def test_boundary_conditions_evaluated_at_run_time_are_refused(self):
        for value, said in (
                ('type exprFixedValue; value uniform (0.01 0 0); valueExpr "vector(0.01,0,0)";',
                 "exprFixedValue"),
                ("type uniformFixedValue; uniformValue table ((0 (0.01 0 0)) (2000 (0.01 0 0)));",
                 "uniformFixedValue")):
            with self.subTest(said):
                case = _copy_case(os.path.join(self.tmp(), "case"))
                _edit(case, "0/U", "boundaryField/inlet", value)
                v = self._readable(case)
                self.assertEqual(v.outcome, "fail", v.render())
                self.assertIn(f"boundary condition {said}", v.detail)

    def test_a_2d_case_refines_every_direction_but_the_thin_one(self):
        """What slipped through the first draft: every count of 1 in a 2D case
        stayed 1, so a one-cell wall layer was never refined and the ladder
        passed 3% below the exact answer."""
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/blockMeshDict", "blocks",
              "( hex (0 1 3 2 4 5 7 6) (50 1 1) simpleGrading (1 1 1) )")
        C = self.registry.get("cfd.case_readable")[1].__globals__
        c = C["Case"](case)
        self.assertEqual(c.dim, 2)
        self.assertEqual(c.counts(2.0, 1), [(100, 2, 1)])
        self.assertEqual(c.counts(1.3, 2), [(85, 3, 1)])

    def test_an_empty_patch_with_no_faces_is_not_2d(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        path = os.path.join(case, "system", "blockMeshDict")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("type empty;", "type symmetryPlane;")
        text = text.replace("boundary\n(", "boundary\n(\n    dummy { type empty; faces (); }")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        C = self.registry.get("cfd.case_readable")[1].__globals__
        self.assertEqual(C["Case"](case).dim, 3)

    def test_a_snappy_case_is_phase_two(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        with open(os.path.join(case, "system", "snappyHexMeshDict"), "w") as fh:
            fh.write(F.foam_file("dictionary", "snappyHexMeshDict", "castellatedMesh true;"))
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("snappyHexMesh", v.detail)

    def test_a_file_that_does_not_parse(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        with open(os.path.join(case, "system", "fvSchemes"), "a") as fh:
            fh.write("\nbroken {\n")
        v = self._readable(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("system/fvSchemes does not parse", v.detail)

    def test_block_counts_by_macro_are_read(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        path = os.path.join(case, "system", "blockMeshDict")
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        text = text.replace("scale   1;", "scale   1;\nnx 40;\nny 8;")
        text = text.replace("(50 10 1)", "($nx $ny 1)")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        v = self._readable(case)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("320 cells", v.detail)

    def test_a_mach_number_past_the_limit_fails_whatever_the_reynolds_number(self):
        params = dict(self.params, cfd_sound_speed_m_s=0.01 / (0.3 * 1.15))
        v = _run(self.registry, "cfd.regime", self.tmp(), params, tier=0)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("Mach", v.detail)
        # The Mach number in its own units against 0.3 (D3), never a fraction.
        self.assertEqual((v.units, v.limit, v.comparator), ("Mach", 0.3, "<"))
        self.assertAlmostEqual(v.measured, 0.3 * 1.15, places=9)

    def test_the_value_is_the_reynolds_number_against_its_limit(self):
        """(issue #15, D3) The value is Re in units ``Re`` against 2300, and the
        detail says on which speed and length it was computed. What slipped
        through before: "0.008696 fraction of limit" for Re 20."""
        v = _run(self.registry, "cfd.regime", self.tmp(), self.params, tier=0)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.units, v.limit, v.comparator), ("Re", 2300.0, "<"))
        self.assertAlmostEqual(v.measured, 0.01 * 0.02 / 1e-5, places=6)
        for said in ("U Dh / nu", "0.01 m/s", "0.02 m", "onset of transition"):
            self.assertIn(said, v.detail)
        self.assertGreater(claims_mod.margin(v).fraction, 0.99)

    def test_a_value_a_hair_under_its_limit_never_reads_at_it(self):
        """Review of issue #15's D3: regime judged the raw Re and reported nine
        digits, so Re 2299.9999999 read a pass at "2300 Re" against "< 2300"
        (Mach 0.3 the same): a pass at a value its own condition rejects."""
        cases = (("Re", dict(self.params, cfd_velocity_m_s=(2300 - 1e-7) * 1e-5 / 0.02),
                  2300.0),
                 ("Mach", dict(self.params, cfd_velocity_m_s=(0.3 - 1e-11) * 1400.0,
                               cfd_length_m=1e-9), 0.3))
        for units, params, limit in cases:
            with self.subTest(units):
                v = _run(self.registry, "cfd.regime", self.tmp(), params, tier=0)
                self.assertEqual((v.outcome, v.units, v.limit), ("pass", units, limit),
                                 v.render())
                self.assertLess(v.measured, limit)
                self.assertNotEqual(claims_mod.margin(v).why, "disagrees")

    def test_a_plane_with_no_normal_is_an_error(self):
        params = dict(self.params)
        params["cfd_dp_planes"] = [{"point": [0, 0, 0], "normal": [0, 0, 0]},
                                   self.params["cfd_dp_planes"][1]]
        v = _run(self.registry, "cfd.case_readable", self.tmp(), params, tier=0)
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("normal is zero", v.error)


# --------------------------------------------------------------------------- #
# the stand-in OpenFOAM
# --------------------------------------------------------------------------- #
def _exe(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_standin(directory: str) -> tuple[str, str]:
    """The stand-in OpenFOAM installed under ``directory``: ``(install root,
    bin)``, where ``bin`` holds only the ``openfoam2606`` wrapper, to put on
    PATH. Its mode is ``<install root>/standin.json`` (``{}`` here), and each
    tool it runs is appended to ``<install root>/calls``."""
    root = os.path.join(directory, "openfoam2606")
    appbin = os.path.join(root, "platforms", "linux64GccDPInt32Opt", "bin")
    os.makedirs(appbin)
    os.makedirs(os.path.join(root, "etc"))
    os.makedirs(os.path.join(root, "META-INFO"))
    with open(os.path.join(root, "etc", "bashrc"), "w") as fh:
        fh.write('root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                 'export WM_PROJECT_DIR="$root"\n'
                 'export FOAM_APPBIN="$root/platforms/linux64GccDPInt32Opt/bin"\n')
    with open(os.path.join(root, "META-INFO", "api-info"), "w") as fh:
        fh.write("api=2606\npatch=0\n")
    for tool in ("blockMesh", "checkMesh", "simpleFoam", "foamDictionary"):
        _exe(os.path.join(appbin, tool),
             f"#!{sys.executable}\nimport os, runpy\nos.environ['STANDIN_TOOL'] = "
             f"{tool!r}\nrunpy.run_path({STANDIN!r}, run_name='__main__')\n")
    bin_dir = os.path.join(directory, "bin")
    os.makedirs(bin_dir)
    # v2606's wrapper, quote and all.
    _exe(os.path.join(bin_dir, "openfoam2606"),
         f'#!/bin/sh\nexec "{root}"/etc/openfoam "$@"\n')
    with open(os.path.join(root, "standin.json"), "w") as fh:
        json.dump({}, fh)
    return root, bin_dir


@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
class AFinishedLookingRunIsNotAPass(_env.EnvCase):
    """Through the stand-in OpenFOAM: every way a run looks finished and is not."""

    def setUp(self):
        self.dir = self.tmp()
        self.root, self.bin = install_standin(self.dir)
        self.registry = _registry()
        self.params = _baseline()
        self.mode({})

    def api_info(self, text: str) -> None:
        with open(os.path.join(self.root, "META-INFO", "api-info"), "w") as fh:
            fh.write(text)

    def mode(self, mode: dict) -> None:
        with open(os.path.join(self.root, "standin.json"), "w") as fh:
            json.dump(mode, fh)

    def gate(self, gid: str, params: dict | None = None, *, runs: bool = True,
             claims=None):
        calls = os.path.join(self.root, "calls")
        if os.path.exists(calls):
            os.remove(calls)
        # The stand-in's wrapper and nothing else of OpenFOAM's: a shell that
        # sourced etc/bashrc puts the real install's bin on PATH.
        env = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin"}
        with mock.patch.dict(os.environ, env):
            v = _run(self.registry, gid, self.tmp(), dict(self.params, **(params or {})),
                     claims=claims)
        # A stand-in that never ran (a noexec temp dir) would skip or error the
        # gate for the wrong reason; the count keeps that from reading as a test.
        if v.outcome in ("pass", "fail") and runs:
            self.assertTrue(os.path.exists(calls), f"the stand-in never ran: {v.render()}")
        return v

    # -- finding the install -------------------------------------------------
    def test_the_wrapper_names_the_install(self):
        with mock.patch.dict(os.environ, {"PATH": self.bin + os.pathsep + "/usr/bin:/bin"}):
            inst = T.locate()
        self.assertEqual(inst.root, self.root)
        self.assertEqual(inst.api, 2606)

    def test_a_foundation_install_is_refused(self):
        os.remove(os.path.join(self.root, "META-INFO", "api-info"))
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "skipped", v.render())
        self.assertIn("not an ESI", v.skip_reason)

    def test_another_esi_release_is_refused(self):
        self.api_info("api=2512\npatch=0\n")
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "skipped", v.render())
        self.assertIn("v2512", v.skip_reason)

    # -- convergence ---------------------------------------------------------
    def test_a_converged_run_passes(self):
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "pass", v.render())
        # The judged value (D3): the estimated remaining change in % of the
        # pressure drop, against 0.1 %; the iteration is in the detail.
        self.assertEqual((v.units, v.limit, v.comparator), ("%", 0.1, "<="))
        summary = next(p for p in v.evidence if p.endswith("summary.json"))
        with open(summary, encoding="utf-8") as fh:
            self.assertEqual(v.measured, float(f"{json.load(fh)['iterative_error_pct']:.6g}"))
        self.assertLessEqual(v.measured, v.limit)
        self.assertIn("converged at iteration 60 of 2000", v.detail)

    def test_out_of_iterations_with_exit_0_and_end_fails(self):
        self.mode({"simpleFoam": {"converge_at": 5000}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("no 'SIMPLE solution converged' line", v.detail)
        self.assertIsNone(v.measured)

    def test_sigfpe_is_divergence_and_an_error(self):
        self.mode({"simpleFoam": {"fail": "fpe"}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("SIGFPE", v.error)

    def test_a_fatal_error_is_an_error_with_its_message(self):
        self.mode({"simpleFoam": {"fail": "fatal"}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("keyword nu is undefined", v.error)

    def test_no_end_is_an_error(self):
        self.mode({"simpleFoam": {"no_end": True}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("without printing End", v.error)

    def test_a_banner_without_trapping_is_an_error(self):
        self.mode({"omit": ["no-fpe"]})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("floating-point trapping", v.error)

    def test_a_run_at_another_velocity_is_an_error(self):
        self.mode({"simpleFoam": {"u": 0.05}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("different flow", v.error)

    def test_flow_against_the_upstream_normal_is_an_error(self):
        params = {"cfd_dp_planes": [{"point": [0.025, 0, 0], "normal": [-1, 0, 0]},
                                    self.params["cfd_dp_planes"][1]]}
        v = self.gate("cfd.converged", params)
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("against its normal", v.error)

    def test_a_pressure_rise_is_not_a_small_drop(self):
        self.mode({"simpleFoam": {"scale": -1.0}})
        v = self.gate("cfd.pressure_drop")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("a rise, or the planes in the wrong order", v.error)

    def test_a_plane_that_cuts_nothing_is_an_error(self):
        self.mode({"simpleFoam": {"area": 0.0}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("cuts no part of the mesh", v.error)

    def test_a_loose_residual_target_is_refused(self):
        v = self.gate("cfd.converged", {"cfd_residual_target": 1e-3})
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("looser target", v.error)

    def test_the_projects_function_objects_never_run(self):
        """The case's own function objects are removed from the copy, every
        repeat of the keyword: the numbers are the pack's."""
        case = _copy_case(os.path.join(self.tmp(), "case"))
        with open(os.path.join(case, "system", "controlDict"), "a") as fh:
            fh.write("\nfunctions { mine { type surfaceFieldValue; } }\n"
                     "functions { other { type forces; } }\n")
        v = self.gate("cfd.converged", {"cfd_case": case})
        self.assertEqual(v.outcome, "pass", v.render())
        staged = next(p for p in v.evidence if p.endswith("log.simpleFoam"))
        cd = F.read(os.path.join(os.path.dirname(staged), "system", "controlDict"))
        self.assertEqual(cd.sub("functions").keys(), ["nopekit_upstream", "nopekit_downstream"])

    # -- mesh quality --------------------------------------------------------
    def test_failed_mesh_checks_fail_whatever_the_values(self):
        self.mode({"checkMesh": {"ok": False}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("checkMesh failed", v.detail)
        # Every value inside its limit: no value, so none reads inside under a fail.
        self.assertEqual((v.measured, v.limit), (None, None))

    def test_mesh_ok_past_the_projects_limit_fails(self):
        self.mode({"checkMesh": {"non_ortho": 72.0}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("checkMesh said Mesh OK, but non-orthogonality", v.detail)
        # Degrees against degrees (D3), never "fraction of limit".
        self.assertEqual((v.measured, v.limit, v.units, v.comparator), (72.0, 65.0, "deg", "<="))

    def test_a_value_checkmesh_did_not_print_is_an_error(self):
        self.mode({"checkMesh": {"omit": ["non_ortho"]}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("non-orthogonality", v.error)

    def test_high_aspect_ratio_is_read_from_the_failed_line(self):
        self.mode({"checkMesh": {"aspect": 5000.0, "ok": False}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertEqual((v.measured, v.limit, v.units), (5000.0, 1000.0, "aspect ratio"))

    def test_a_pass_reports_the_value_nearest_its_limit(self):
        """(D3) A pass reports the one of the three nearest its own limit, in
        its own units, so it never shows more margin than the gate has: the
        aspect ratio when that is nearer, the non-orthogonality in degrees when
        that is."""
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.units, v.limit), ("aspect ratio", 1000.0))
        self.mode({"checkMesh": {"non_ortho": 60.0}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.measured, v.limit, v.units), (60.0, 65.0, "deg"))
        self.assertAlmostEqual(claims_mod.margin(v).fraction, 5.0 / 65.0)

    # -- mesh independence ---------------------------------------------------
    def test_a_poiseuille_ladder_passes(self):
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("500/2000/8000 cells", v.detail)
        self.assertIn("observed order 1.97", v.detail)

    def test_a_diverging_ladder_fails(self):
        self.mode({"simpleFoam": {"dp": "diverging"}})
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("monotone divergence", v.detail)

    def test_an_oscillating_ladder_fails(self):
        self.mode({"simpleFoam": {"dp": "oscillating"}})
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("oscillatory", v.detail)

    def test_an_order_outside_the_band_fails(self):
        self.mode({"simpleFoam": {"dp": "fourth_order"}})
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("outside [0.95, 2.05]", v.detail)

    def test_a_refined_level_that_never_converges_fails_and_is_named(self):
        self.mode({"simpleFoam": {"never_at_ny": [40]}})
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("level 2 (8000 cells) is not converged", v.detail)

    def test_a_ratio_outside_the_range_is_refused(self):
        for r in (1.1, 4.0):
            with self.subTest(r=r):
                v = self.gate("cfd.mesh_independence", {"cfd_refinement_ratio": r})
                self.assertEqual(v.outcome, "error", v.render())

    # -- the analysis --------------------------------------------------------
    def test_the_band_top_is_judged_not_the_value(self):
        """A limit between the pressure drop and its band's top fails."""
        dp_pa = 870.0 * 6.0e-4 / (1 + 2.0 / 40 ** 2)
        v = self.gate("cfd.pressure_drop", claims=_claims(dp_pa * 1.0005))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertGreater(v.measured, dp_pa * 1.0005)
        v = self.gate("cfd.pressure_drop")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual(v.units, "Pa")

    def test_the_limit_is_the_claims(self):
        """Issue #15 D2: the gate judges against the claim tagged pressure-drop, and
        reports that claim's limit and side. Until then it judged against
        cfd_dp_max_pa: a claim at 0.5 Pa beside the parameter at 0.6 read a
        pass at 0.52 Pa that the claim's own condition rejected."""
        good = self.gate("cfd.pressure_drop")
        self.assertEqual((good.outcome, good.limit, good.comparator), ("pass", 0.6, "<="))
        v = self.gate("cfd.pressure_drop", claims=_claims(0.5))
        self.assertEqual((v.outcome, v.limit, v.measured), ("fail", 0.5, good.measured),
                         v.render())
        self.assertIn("past 0.5 Pa", v.detail)
        v = self.gate("cfd.pressure_drop", claims=_claims(0.6, comparator=Comparator.LT))
        self.assertEqual((v.outcome, v.comparator), ("pass", "<"), v.render())
        # A stray parameter of the old name moves nothing.
        v = self.gate("cfd.pressure_drop", {"cfd_dp_max_pa": 0.1})
        self.assertEqual((v.outcome, v.limit), ("pass", 0.6), v.render())

    def test_a_limit_the_gate_cannot_judge_errors_before_a_run(self):
        """Another unit, a lower limit, or no claim tagged pressure-drop: an
        error, and no OpenFOAM tool runs."""
        calls = os.path.join(self.root, "calls")
        cases = (("kPa", _claims(units="kPa"), "states its limit in 'kPa'"),
                 ("no units", _claims(units=""), "states its limit in ''"),
                 ("lower limit", _claims(comparator=Comparator.GE), "only an upper limit"),
                 ("no claim", [], "no claim is named or tagged 'pressure-drop'"))
        for label, claims, said in cases:
            with self.subTest(label):
                v = self.gate("cfd.pressure_drop", claims=claims)
                self.assertEqual(v.outcome, "error", v.render())
                self.assertIn(said, v.error)
                self.assertFalse(os.path.exists(calls), "a tool ran")

    def test_a_tiny_drop_is_judged_whole(self):
        """Review of issue #15's D2: the gate judged ``round(top, 9)``, so a band
        top of 6.0e-13 Pa read 0.0 and passed a limit of 1e-13 Pa, its own
        detail saying "6.0021e-13 Pa, within 1e-13 Pa"."""
        v = self.gate("cfd.pressure_drop", {"cfd_density_kg_m3": 1e-9},
                      claims=_claims(1e-13))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertGreater(v.measured, 1e-13)
        v = self.gate("cfd.pressure_drop", {"cfd_density_kg_m3": 1e-9},
                      claims=_claims(1e-11))
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertAlmostEqual(v.measured / 6.0e-13, 1.0, places=2)
        self.assertNotEqual(claims_mod.margin(v).why, "disagrees")

    def test_the_summary_holds_no_limit(self):
        v = self.gate("cfd.pressure_drop")
        summary = self.evidence(v, "summary.json")
        self.assertFalse([k for k in summary if "limit" in k.lower()], sorted(summary))

    def test_a_ladder_past_the_gci_limit_fails_without_openfoam(self):
        """In CI the selftest skips this control: the stand-in holds the
        comparison of the GCI with its limit."""
        self.mode({"simpleFoam": {"dp": "coarse"}})
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertGreater(v.measured, v.limit)
        self.assertIn("past 1%", v.detail)

    def test_an_order_below_the_band_fails(self):
        self.mode({"simpleFoam": {"dp": "low_order"}})
        v = self.gate("cfd.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("observed order 0.7", v.detail)

    def test_an_upwind_entry_for_an_unsolved_field_leaves_the_order_second(self):
        """A divSchemes entry for a field a laminar run never solves (the
        turbulent tutorials carry ``div(phi,k) bounded Gauss upwind``) leaves the
        formal order 2. Until P0.1 it set the band to 0.95-1.05, and this ladder,
        which converges at order 2, failed."""
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/fvSchemes", "divSchemes",
              "default none; div(phi,U) bounded Gauss linearUpwind grad(U); "
              "div((nuEff*dev2(T(grad(U))))) Gauss linear; div(phi,k) bounded Gauss upwind;")
        v = self.gate("cfd.mesh_independence", {"cfd_case": case})
        self.assertEqual(v.outcome, "pass", v.render())

    # -- the evidence a chart draws (GitHub #15, P0.2) ------------------------
    def evidence(self, v, name: str):
        """The evidence file ``name`` of ``v``: a dict for JSON, rows for a CSV."""
        path = next(p for p in v.evidence if os.path.basename(p) == name)
        with open(path, encoding="utf-8", newline="") as fh:
            return json.load(fh) if name.endswith(".json") else list(csv.DictReader(fh))

    def assert_history(self, rows, column: str, error_pct, n: int | None = None, places=12):
        """The rows are the history the estimate read: iterations 1.., change_pct
        100 x |change| / |last| (none on the first row), and error_pct the
        estimate's reading of the same values as a percentage of the last. In Pa
        the values are the solver's times the density, each product rounded: where
        the reading is a round-off swing of about 3e-8 of the value (the real
        baseline), that moves it by up to about 1e-8 of itself. error_pct is the
        reading the gate judged, on the solver's own values."""
        vals = [float(r[column]) for r in rows]
        if n is not None:
            self.assertEqual(len(vals), n)
        self.assertEqual([int(r["iteration"]) for r in rows], list(range(1, len(vals) + 1)))
        self.assertEqual(rows[0]["change_pct"], "")
        for i in range(1, len(vals)):
            self.assertEqual(float(rows[i]["change_pct"]),
                             100.0 * abs(vals[i] - vals[i - 1]) / abs(vals[-1]))
        rem = I.remaining(vals)
        if rem is None or rem == math.inf:
            self.assertIsNone(error_pct)
        else:
            self.assertAlmostEqual(error_pct / (100.0 * rem / abs(vals[-1])), 1.0,
                                   places=places)

    def test_the_converged_run_writes_its_history_and_estimate(self):
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "pass", v.render())
        summary = self.evidence(v, "summary.json")
        rows = self.evidence(v, "history.csv")
        self.assertNotIn("dp", summary)          # the history is the CSV, never JSON
        self.assertEqual(summary["convergence_tol_pct"], 0.1)   # STABLE_TOL 1e-3
        self.assertEqual(float(rows[-1]["dp_m2_s2"]), summary["dp_m2_s2"])
        self.assertLessEqual(summary["iterative_error_pct"], summary["convergence_tol_pct"])
        self.assert_history(rows, "dp_m2_s2", summary["iterative_error_pct"], n=60)

    def test_an_unsettled_run_writes_its_estimate_too(self):
        self.mode({"simpleFoam": {"settle_tail": 0.05}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        summary = self.evidence(v, "summary.json")
        self.assertGreater(summary["iterative_error_pct"], summary["convergence_tol_pct"])
        self.assert_history(self.evidence(v, "history.csv"), "dp_m2_s2",
                            summary["iterative_error_pct"])
        self.mode({"simpleFoam": {"converge_at": 8}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIsNone(self.evidence(v, "summary.json")["iterative_error_pct"])

    def test_each_level_writes_its_history_and_estimate(self):
        for gid, column in (("cfd.mesh_independence", "dp_m2_s2"), ("cfd.pressure_drop", "dp_pa")):
            with self.subTest(gid=gid):
                v = self.gate(gid)
                self.assertEqual(v.outcome, "pass", v.render())
                summary = self.evidence(v, "summary.json")
                self.assertEqual(summary["convergence_tol_pct"], 0.1)   # STABLE_TOL 1e-3
                rho = summary.get("density_kg_m3", 1.0)
                for lv in summary["levels"]:
                    rows = self.evidence(v, f"history_level{lv['k']}.csv")
                    self.assertEqual(rows[0].keys(), {"iteration", column, "change_pct"})
                    self.assertAlmostEqual(float(rows[-1][column]) / (rho * lv["dp_m2_s2"]),
                                           1.0, places=12)
                    self.assertLessEqual(lv["iterative_error_pct"], summary["convergence_tol_pct"])
                    self.assert_history(rows, column, lv["iterative_error_pct"],
                                        n=lv["converged_in"], places=12 if rho == 1.0 else 6)

    # -- what the run itself says -------------------------------------------
    def test_the_converged_line_beside_a_residual_over_target_fails(self):
        self.mode({"simpleFoam": {"final_residual": 1e-5}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("initial residual above the target", v.detail)

    def test_the_converged_line_beside_a_creeping_number_fails(self):
        self.mode({"simpleFoam": {"settle_tail": 0.05}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("still moving", v.detail)

    def test_too_few_iterations_to_see_it_settle_fails(self):
        self.mode({"simpleFoam": {"converge_at": 8}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("fewer than the 17", v.detail)

    def test_a_run_to_other_criteria_is_an_error(self):
        self.mode({"simpleFoam": {"criteria": {"p": 0.05, "U": 1e-6}}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("convergence criteria", v.error)

    def test_a_merge_into_the_packs_function_objects_is_an_error(self):
        """What OpenFOAM reads, not what the pack wrote: a merged key."""
        self.mode({"expand_append": {"system/controlDict":
                   "\nfunctions { nopekit_downstream { scaleFactor 0.5; } }\n"}})
        v = self.gate("cfd.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("not exactly the pack's two function objects", v.error)

    def test_a_merge_into_residual_control_or_nu_is_an_error(self):
        """Each check of OpenFOAM's own reading, held by one merge the tier-0
        reader never sees (the second review deleted each and the suite stayed
        green)."""
        for rel, text, said in (
                ("system/fvSolution", "\nSIMPLE { residualControl { p 0.01; } }\n",
                 "residualControl"),
                ("system/fvSolution", "\nSIMPLE { momentumPredictor no; }\n",
                 "momentumPredictor is off"),
                ("constant/transportProperties", "\nnu 5e-08;\n", "nu 5e-08"),
                ("constant/transportProperties", "\ntransportModel powerLaw;\n",
                 "constant/transportProperties"),
                ("constant/turbulenceProperties",
                 "\nlaminar { model generalizedNewtonian; }\n", "not laminar Stokes"),
                ("system/controlDict", "\nlibs (mine);\n", "loads libraries"),
                ("system/controlDict", "\nendTime 5;\n", "iteration budget"),
                ("system/controlDict", "\napplication icoFoam;\n", "iteration budget"),
                ("system/fvSchemes", "\ndivSchemes { div(phi,U) bounded Gauss upwind; }\n",
                 "convection schemes")):
            with self.subTest(rel):
                self.mode({"expand_append": {rel: text}})
                v = self.gate("cfd.converged")
                self.assertEqual(v.outcome, "error", v.render())
                self.assertIn(said, v.error)

    def test_a_banner_that_allows_system_operations_is_an_error(self):
        self.mode({"omit": ["allowing"]})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("system operations allowed", v.error)

    def test_a_banner_from_another_release_is_an_error(self):
        self.mode({"api": 2512})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("no supported OpenFOAM build", v.error)

    def test_a_mesh_with_other_directions_than_the_case_is_an_error(self):
        self.mode({"checkMesh": {"directions": 3}})
        for gid in ("cfd.mesh_quality", "cfd.converged"):
            with self.subTest(gid):
                v = self.gate(gid)
                self.assertEqual(v.outcome, "error", v.render())
                self.assertIn("geometric directions", v.error)

    def test_a_plane_that_falls_off_the_cell_lattice_fails_the_ladder(self):
        """At r = 1.5 the baseline's planes fall a quarter of a cell into
        their cells on the next level, where OpenFOAM's sampled value carries an
        error the ladder would read as convergence."""
        # Refused before anything runs.
        v = self.gate("cfd.mesh_independence", {"cfd_refinement_ratio": 1.5}, runs=False)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("of a cell into block 0 on level 1", v.detail)
        self.assertFalse(os.path.exists(os.path.join(self.root, "calls")))
        v = self.gate("cfd.pressure_drop", {"cfd_refinement_ratio": 1.5}, runs=False)
        self.assertEqual(v.outcome, "error", v.render())

    def test_the_projects_limits_bind_on_mesh_ok(self):
        for key, value in (("cfd_max_skewness", 1e-20), ("cfd_max_aspect_ratio", 1.5)):
            with self.subTest(key):
                v = self.gate("cfd.mesh_quality", {key: value})
                self.assertEqual(v.outcome, "fail", v.render())
                self.assertIn("checkMesh said Mesh OK, but", v.detail)


# --------------------------------------------------------------------------- #
# the real OpenFOAM
# --------------------------------------------------------------------------- #
def _real_install():
    try:
        return T.locate()
    except T.Unavailable:
        return None


@unittest.skipIf(_real_install() is None, "ESI OpenFOAM v2606 is not installed")
class TheRealOpenFOAM(_env.EnvCase):
    """On the real v2606, where it is installed."""

    def setUp(self):
        self.registry = _registry()
        self.params = _baseline()

    def test_the_baseline_meets_its_exact_answer(self):
        v = _run(self.registry, "cfd.pressure_drop", self.tmp(), self.params)
        self.assertEqual(v.outcome, "pass", v.render())
        summary = next(p for p in v.evidence if p.endswith("summary.json"))
        with open(summary, encoding="utf-8") as fh:
            data = json.load(fh)
        exact = 12 * 1e-5 * 0.01 * 0.05 / 0.01 ** 2
        for lv in data["levels"]:
            ny = lv["counts"][0][1]
            # The uniform inlet's entrance reaches the planes at 3e-6 of the value.
            self.assertAlmostEqual(lv["dp_m2_s2"] / (exact / (1 + 2 / ny ** 2)), 1.0, places=5)
            # The history a chart draws, and the estimate beside it (P0.2).
            path = next(p for p in v.evidence if p.endswith(f"history_level{lv['k']}.csv"))
            with open(path, encoding="utf-8", newline="") as fh:
                dp_pa = [float(r["dp_pa"]) for r in csv.DictReader(fh)]
            self.assertEqual(len(dp_pa), lv["converged_in"])
            self.assertLessEqual(lv["iterative_error_pct"], data["convergence_tol_pct"])
            # In Pa each value is rounded once more (assert_history says why).
            self.assertAlmostEqual(lv["iterative_error_pct"] / (
                100 * I.remaining(dp_pa) / dp_pa[-1]), 1.0, places=6)
        self.assertAlmostEqual(data["gci"]["phi_ext21"] / exact, 1.0, places=3)

    def test_the_pack_writes_its_values_to_13_digits(self):
        """WRITE_PRECISION reaches the files the gate reads: the estimate needs a
        change of 1e-8 of the value resolved. Until P0.1 the case's own
        writePrecision set it (the baseline's 10: 11 digits)."""
        root = self.tmp()
        v = _run(self.registry, "cfd.converged", root, self.params)
        self.assertEqual(v.outcome, "pass", v.render())
        dats = [os.path.join(d, f) for d, _dirs, files in os.walk(root) for f in files
                if f == "surfaceFieldValue.dat"]
        self.assertEqual(len(dats), 2, dats)
        for dat in dats:
            with open(dat, encoding="utf-8") as fh:
                row = [line for line in fh if not line.startswith("#")][-1].split()
            digits = row[1].lstrip("-").split("e")[0].replace(".", "")
            self.assertEqual(len(digits), 13, row)

    def test_calc_is_stopped_at_run_time_too(self):
        """Past cfd.case_readable (run directly): the private HOME's
        allowSystemOperations 0 stops the compile."""
        inst = T.locate()
        out = self.tmp()
        env = T.environment(inst, T.home(out, inst.api))
        stage = _copy_case(os.path.join(out, "case"))
        _edit(stage, "system/controlDict", "endTime", '#calc "1000*2"')
        with self.assertRaises(T.RunError) as cm:
            T.run(env, stage, ["blockMesh"], 120)
        self.assertIn("case-supplied code", str(cm.exception))

    def test_openfoams_own_reading_catches_a_merge_the_reader_was_never_shown(self):
        """Past cfd.case_readable (staged directly): a #sinclude that merges a
        scaleFactor into the pack's function objects is an error at run time."""
        C = self.registry.get("cfd.converged")[1].__globals__
        inst = T.locate()
        out = self.tmp()
        env = T.environment(inst, T.home(out, inst.api))
        case = C["Case"](CHANNEL)
        planes = C["_planes"](gates_mod.GateContext(root=out, params=self.params, out_dir=out))
        stage = os.path.join(out, "stage")
        T.stage(CHANNEL, stage, case.files)
        C["_prepare"](stage, case, planes, 1e-6)
        with open(os.path.join(stage, "system", "extra"), "w") as fh:
            fh.write("functions { nopekit_downstream { scaleFactor 0.5; } }\n")
        with open(os.path.join(stage, "system", "controlDict"), "a") as fh:
            fh.write('\n#sinclude "extra"\n')
        with self.assertRaises(T.RunError) as cm:
            C["_as_read"](env, stage, case, planes, 1e-6, 120)
        self.assertIn("not exactly the pack's two function objects", str(cm.exception))

    def test_a_users_control_dict_never_reaches_a_run(self):
        """A ~/.OpenFOAM/2606/controlDict that turns trapping off, and one that
        allows system operations, change nothing: the run reads the gate's HOME."""
        home = self.tmp()
        cfg = os.path.join(home, ".OpenFOAM", "2606", "controlDict")
        os.makedirs(os.path.dirname(cfg))
        with open(cfg, "w") as fh:
            fh.write("FoamFile { version 2.0; format ascii; class dictionary; "
                     "object controlDict; }\nOptimisationSwitches { trapFpe 0; }\n"
                     "InfoSwitches { allowSystemOperations 1; }\n")
        with mock.patch.dict(os.environ, {"HOME": home}):
            v = _run(self.registry, "cfd.mesh_quality", self.tmp(), self.params, tier=1)
        self.assertEqual(v.outcome, "pass", v.render())
        log = next(p for p in v.evidence if p.endswith("log.checkMesh"))
        with open(log) as fh:
            text = fh.read()
        self.assertIn("trapFpe: Floating point exception trapping enabled", text)
        self.assertIn("allowSystemOperations : Disallowing", text)


if __name__ == "__main__":
    unittest.main()
