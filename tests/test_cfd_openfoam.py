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

import json
import os
import shutil
import stat
import sys
import unittest
from unittest import mock

import _env
from nopekit import gates as gates_mod
from nopekit import packs as packs_mod
from nopekit.modelio import load_path
from nopekit.models import Ledger, ProjectMeta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(REPO, "packs", "cfd-openfoam")
CHANNEL = os.path.join(PACK, "selftest", "assets", "channel")
STANDIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_cfd_standin.py")

F = load_path(os.path.join(PACK, "gates", "_foam.py"))
G = load_path(os.path.join(PACK, "gates", "_gci.py"))
T = load_path(os.path.join(PACK, "gates", "_tool.py"))


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


def _run(registry, gid: str, root: str, params: dict, *, tier: int = 2):
    spec_fn = registry.get(gid)
    assert spec_fn is not None, f"{gid} is not in the pack"
    ctx = gates_mod.GateContext(
        root=root, ledger=Ledger(meta=ProjectMeta(name="cfd")), model=None,
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

    def test_the_remaining_change_is_estimated_from_the_tail(self):
        C = _registry().get("cfd.converged")[1].__globals__
        settled = [1.0] * 25
        self.assertEqual(C["_remaining"](settled), 0.0)
        self.assertIsNone(C["_remaining"]([1.0] * 20))
        creeping = [1.0 + 0.1 * 0.97 ** i for i in range(200)]
        rem = C["_remaining"](creeping)
        self.assertAlmostEqual(rem, 0.1 * 0.97 ** 199, delta=0.1 * 0.97 ** 199 * 0.05)
        # An oscillation: what it still swings by, whatever its period.
        self.assertAlmostEqual(C["_remaining"]([1.0 + 1e-3 * (-1) ** i for i in range(25)]),
                               2e-3, places=12)
        # Moving one way and not slowing: never settled.
        self.assertEqual(C["_remaining"]([1.0 + 1e-3 * i for i in range(25)]), float("inf"))
        # A run that just moved 0.17% after a larger oscillation: at least that.
        tail = [1.0 + 0.02 * (-1) ** i for i in range(10)] + [1.0 + 1e-3 * 0.7 ** i
                                                              for i in range(21)]
        self.assertGreaterEqual(C["_remaining"](tail), 0.0)
        self.assertGreaterEqual(C["_remaining"]([1.0 + 0.0017 * (20 - i) / 20 + 1e-7 * i * i
                                                 for i in range(21)]), 0.0017)

    def test_a_malformed_file_is_refused_whole(self):
        for text in ("a 1", "a { b 1;", "a (1 2;", "}"):
            with self.subTest(text=text), self.assertRaises(F.FoamFormatError):
                F.parse(text)


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
        self.assertAlmostEqual(v.measured, 1.15, places=6)

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


@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
class AFinishedLookingRunIsNotAPass(_env.EnvCase):
    """Through the stand-in OpenFOAM: every way a run looks finished and is not."""

    def setUp(self):
        self.dir = self.tmp()
        self.root = os.path.join(self.dir, "openfoam2606")
        appbin = os.path.join(self.root, "platforms", "linux64GccDPInt32Opt", "bin")
        os.makedirs(appbin)
        os.makedirs(os.path.join(self.root, "etc"))
        os.makedirs(os.path.join(self.root, "META-INFO"))
        with open(os.path.join(self.root, "etc", "bashrc"), "w") as fh:
            fh.write('root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                     'export WM_PROJECT_DIR="$root"\n'
                     'export FOAM_APPBIN="$root/platforms/linux64GccDPInt32Opt/bin"\n')
        self.api_info("api=2606\npatch=0\n")
        for tool in ("blockMesh", "checkMesh", "simpleFoam", "foamDictionary"):
            _exe(os.path.join(appbin, tool),
                 f"#!{sys.executable}\nimport os, runpy\nos.environ['STANDIN_TOOL'] = "
                 f"{tool!r}\nrunpy.run_path({STANDIN!r}, run_name='__main__')\n")
        self.bin = os.path.join(self.dir, "bin")
        os.makedirs(self.bin)
        # v2606's wrapper, quote and all.
        _exe(os.path.join(self.bin, "openfoam2606"),
             f'#!/bin/sh\nexec "{self.root}"/etc/openfoam "$@"\n')
        self.registry = _registry()
        self.params = _baseline()
        self.mode({})

    def api_info(self, text: str) -> None:
        with open(os.path.join(self.root, "META-INFO", "api-info"), "w") as fh:
            fh.write(text)

    def mode(self, mode: dict) -> None:
        with open(os.path.join(self.root, "standin.json"), "w") as fh:
            json.dump(mode, fh)

    def gate(self, gid: str, params: dict | None = None, *, runs: bool = True):
        calls = os.path.join(self.root, "calls")
        if os.path.exists(calls):
            os.remove(calls)
        # The stand-in's wrapper and nothing else of OpenFOAM's: a shell that
        # sourced etc/bashrc puts the real install's bin on PATH.
        env = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin"}
        with mock.patch.dict(os.environ, env):
            v = _run(self.registry, gid, self.tmp(), dict(self.params, **(params or {})))
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
        self.assertEqual(v.measured, 60.0)
        self.assertEqual(v.limit, 2000.0)

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

    def test_mesh_ok_past_the_projects_limit_fails(self):
        self.mode({"checkMesh": {"non_ortho": 72.0}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("checkMesh said Mesh OK, but non-orthogonality", v.detail)
        self.assertAlmostEqual(v.measured, 72.0 / 65.0, places=5)

    def test_a_value_checkmesh_did_not_print_is_an_error(self):
        self.mode({"checkMesh": {"omit": ["non_ortho"]}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("non-orthogonality", v.error)

    def test_high_aspect_ratio_is_read_from_the_failed_line(self):
        self.mode({"checkMesh": {"aspect": 5000.0, "ok": False}})
        v = self.gate("cfd.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertAlmostEqual(v.measured, 5.0)

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
        v = self.gate("cfd.pressure_drop", {"cfd_dp_max_pa": dp_pa * 1.0005})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertGreater(v.measured, dp_pa * 1.0005)
        v = self.gate("cfd.pressure_drop")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual(v.units, "Pa")

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
        self.assertIn("fewer than the 21", v.detail)

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
        self.assertAlmostEqual(data["gci"]["phi_ext21"] / exact, 1.0, places=3)

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
