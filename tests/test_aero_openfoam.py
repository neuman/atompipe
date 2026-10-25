# SPDX-License-Identifier: Apache-2.0
"""aero-openfoam: what its selftest cannot show.

The selftest shows each gate passing the baseline spheroid and failing one
known-bad case. These tests hold the rest:

- the helpers copied from cfd-openfoam are still its bytes
  (``TheSharedHelpersHaveNotDrifted``);
- every refusal of ``aero.case_readable`` and every mismatch ``aero.reference``
  and ``aero.regime`` look for, at tier 0, with no OpenFOAM;
- the domain's arithmetic on the numbers P0 measured on the motorBike tutorial;
- every way a mesh can look finished when it is not, through a stand-in
  OpenFOAM and mpirun (``tests/_aero_standin.py``) that replays the real tools'
  logs from the baseline (``tests/aero_fixtures/``): plain checkMesh's "Failed 1
  mesh checks" with no face in error, one face in error, a cell cap reached
  under "Finished meshing without any errors", a checkMesh judged against
  another dictionary, a merge OpenFOAM's expansion shows and the reader never
  saw, a banner with the wrong rank count or without its safety lines, a rank
  with another HOME, a rank that dies on SIGFPE, a run that hangs;
- one class that runs the real OpenFOAM, where it is installed: the motorBike
  tutorial, expanded as references/motorbike.md says, read by the reader and
  measured against the domain limits with OpenFOAM's own surfaceCheck.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p test_aero_openfoam.py -v
"""
from __future__ import annotations

import json
import math
import os
import re
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
PACK = os.path.join(REPO, "packs", "aero-openfoam")
CFD = os.path.join(REPO, "packs", "cfd-openfoam")
SPHEROID = os.path.join(PACK, "selftest", "assets", "spheroid")
STANDIN = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_aero_standin.py")

F = load_path(os.path.join(PACK, "gates", "_foam.py"))
T = load_path(os.path.join(PACK, "gates", "_tool.py"))
P = load_path(os.path.join(PACK, "gates", "_par.py"))
FO = load_path(os.path.join(PACK, "gates", "_fo.py"))

#: The motorBike tutorial's surface file, by its digest (references/motorbike.md).
MOTORBIKE_SHA256 = "8ee223c3c3256cd71da52b80eae6569ccf3167eec6f7c3542f83296a0a777aad"


def _baseline() -> dict:
    with open(os.path.join(PACK, "selftest", "baseline.json"), encoding="utf-8") as fh:
        data = json.load(fh)
    params = {k: v for k, v in data.items() if not k.startswith("_")}
    params["aero_case"] = SPHEROID
    return params


def _claims() -> list:
    with open(os.path.join(PACK, "selftest", "baseline.json"), encoding="utf-8") as fh:
        return packs_mod.baseline_claims(json.load(fh))


def _registry() -> gates_mod.Registry:
    registry = gates_mod.Registry()
    packs_mod.load_gates("aero-openfoam", registry, root=REPO, include_env=False,
                         include_user=False)
    return registry


def _module(registry):
    """The loaded gate module's globals (its Case, its constants)."""
    return registry.get("aero.case_readable")[1].__globals__


def _run(registry, gid: str, root: str, params: dict, *, tier: int = 2):
    spec_fn = registry.get(gid)
    assert spec_fn is not None, f"{gid} is not in the pack"
    ctx = gates_mod.GateContext(
        root=root, ledger=Ledger(meta=ProjectMeta(name="aero"), claims=_claims()), model=None,
        params=dict(params), out_dir=os.path.join(root, "out", gid.replace(".", "_")),
        tier=tier, log=lambda _m: None, extra={})
    return gates_mod.run_gate(*spec_fn, ctx)


def _copy_case(dst: str) -> str:
    shutil.copytree(SPHEROID, dst)
    return dst


def _edit(case: str, rel: str, entry: str, value: str) -> None:
    path = os.path.join(case, *rel.split("/"))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(F.set_entry(text, entry, value))


def _append(case: str, rel: str, text: str) -> None:
    with open(os.path.join(case, *rel.split("/")), "a", encoding="utf-8") as fh:
        fh.write(text)


def _replace(case: str, rel: str, old: str, new: str) -> None:
    """``old`` replaced by ``new`` in the case's ``rel``, which must hold it once."""
    path = os.path.join(case, *rel.split("/"))
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    assert text.count(old) == 1, f"{rel} holds {old!r} {text.count(old)} times"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text.replace(old, new))


def _bc(key: str, kind: str) -> str:
    """One 0/ boundaryField entry: ``key { type kind; }``."""
    return f"{key}\n    {{\n        type {kind};\n    }}"


#: The baseline's 0/U entries for the domain's slip walls and for the body, as
#: written: the reference tests rewrite them.
SLIP_WALLS = '"(upperWall|frontAndBack)"\n    {\n        type            slip;\n    }'
BODY_GROUP = "bodyGroup\n    {\n        type            noSlip;\n    }"


# --------------------------------------------------------------------------- #
# the copies
# --------------------------------------------------------------------------- #
class TheSharedHelpersHaveNotDrifted(unittest.TestCase):
    """The helpers aero-openfoam shares with cfd-openfoam are copies, never
    loads across packs (a path into ../cfd-openfoam would make that pack part
    of this one's code, and break this one installed alone). A copy that drifts
    is a fix made in one pack and missing from the other: each must stay
    cfd-openfoam's bytes. The pack's own additions live in ``_par.py`` and
    ``_fo.py``, which no copy shares."""

    SHARED = ("_foam.py", "_tool.py", "_gci.py", "_iter.py")

    def test_each_copy_is_cfd_openfoams_bytes(self):
        for name in self.SHARED:
            with open(os.path.join(CFD, "gates", name), "rb") as a, \
                    open(os.path.join(PACK, "gates", name), "rb") as b:
                self.assertEqual(a.read(), b.read(),
                                 f"gates/{name} has drifted from cfd-openfoam's: copy the "
                                 f"fix both ways (cp packs/cfd-openfoam/gates/{name} "
                                 f"packs/aero-openfoam/gates/)")

    def test_nothing_loads_across_packs(self):
        for name in os.listdir(os.path.join(PACK, "gates")):
            if name.endswith(".py"):
                with open(os.path.join(PACK, "gates", name), encoding="utf-8") as fh:
                    text = fh.read().replace("'", '"')
                for path in ("../cfd-openfoam", '"cfd-openfoam", "gates"', "packs/cfd-openfoam"):
                    self.assertNotIn(path, text, name)


# --------------------------------------------------------------------------- #
# the guard, at tier 0
# --------------------------------------------------------------------------- #
class TheCaseReaderRefusesWhatOpenFOAMWouldEvaluate(_env.EnvCase):
    """``aero.case_readable`` with no OpenFOAM: the baseline is read; each thing
    the reader would have to evaluate, or a file it does not read, is a fail
    naming it. cfd-openfoam's rules, on this pack's files."""

    def setUp(self):
        self.registry = _registry()
        self.params = _baseline()

    def gate(self, case: str):
        return _run(self.registry, "aero.case_readable", self.tmp(),
                    dict(self.params, aero_case=case), tier=0)

    def refused(self, edit, needle: str):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        edit(case)
        v = self.gate(case)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn(needle, v.detail)
        return v

    def test_the_baseline_reads(self):
        v = self.gate(SPHEROID)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("spheroid (sphere)", v.detail)

    def test_a_dictionary_written_twice_is_refused(self):
        """Review of P3-P5: OpenFOAM merges a second ``geometry`` into the
        first and the reader kept the last, so a wall box the width of the
        domain was meshed while aero.domain judged the spheroid alone."""
        def twice(case):
            _replace(case, "system/snappyHexMeshDict", "geometry\n{",
                     "geometry\n{\n    bigBox { type searchableBox; min (0 -3 0); "
                     "max (1 3 3); }")
            _append(case, "system/snappyHexMeshDict",
                    "\ngeometry\n{\n    spheroid { type searchableSphere; origin (0.5 0 0.4); "
                    "radius (0.5 0.125 0.125); }\n}\n")
        v = self.refused(twice, "geometry: written twice in one dictionary")
        self.assertIn("OpenFOAM merges the two", v.detail)

    def test_a_value_written_twice_is_refused(self):
        self.refused(lambda c: _append(c, "constant/transportProperties", "\nnu 1.5e-05;\n"),
                     "nu: written twice")

    def test_an_include_is_refused(self):
        self.refused(lambda c: _append(c, "system/fvSchemes", '\n#include "more"\n'),
                     "#include, a directive")

    def test_a_calc_is_refused(self):
        self.refused(lambda c: _edit(c, "system/controlDict", "endTime", '#calc "100*3"'),
                     "compiles C++")

    def test_a_macro_outside_block_mesh_is_refused(self):
        self.refused(lambda c: _edit(c, "system/fvSchemes", "divSchemes/div(phi,k)",
                                     "$turbulence"), "is a macro")

    def test_a_macro_in_snappy_is_refused(self):
        """Only blockMeshDict's macros are resolved: snappyHexMeshDict is held
        whole to OpenFOAM's expansion, which a macro would make differ."""
        self.refused(lambda c: _edit(c, "system/snappyHexMeshDict", "snapControls/nSolveIter",
                                     "$n"), "is a macro")

    def test_a_coded_condition_is_refused(self):
        self.refused(lambda c: _edit(c, "0/U", "boundaryField/inlet",
                                     "type codedFixedValue; value uniform (20 0 0); name x; "
                                     "code #{ #};"), "compiles C++")

    def test_the_cases_own_function_objects_are_refused(self):
        self.refused(lambda c: _append(c, "system/controlDict",
                                       "\nfunctions { f { type forceCoeffs; } }\n"),
                     "has its own functions")

    def test_a_file_the_reader_does_not_read_is_refused(self):
        def edit(c):
            with open(os.path.join(c, "constant", "fvOptions"), "w") as fh:
                fh.write("FoamFile { version 2.0; format ascii; class dictionary; "
                         "object fvOptions; }\n")
        self.refused(edit, "constant/fvOptions")

    def test_another_turbulence_model_is_refused(self):
        self.refused(lambda c: _edit(c, "constant/turbulenceProperties", "RAS/RASModel",
                                     "kEpsilon"), "RAS model 'kEpsilon'")

    def test_laminar_is_refused(self):
        self.refused(lambda c: _edit(c, "constant/turbulenceProperties", "simulationType",
                                     "laminar"), "runs RAS")

    def test_a_regex_keyword_standing_for_type_is_refused(self):
        self.refused(lambda c: _edit(c, "0/U", "boundaryField/inlet",
                                     '"typ(e)" fixedValue; value uniform (20 0 0);'),
                     "quoted keyword")

    def test_a_domain_that_is_not_one_box_is_refused(self):
        self.refused(lambda c: _edit(c, "system/blockMeshDict", "vertices",
                                     "( (-4 -3 0) (10 -3 0) (10 3 0) (-4 3 0) "
                                     "(-4 -3 4) (10 -3 4) (11 3 4) (-4 3 4) )"),
                     "not one axis-aligned box")

    def test_a_moved_body_is_refused(self):
        self.refused(lambda c: _edit(c, "system/snappyHexMeshDict", "geometry/spheroid",
                                     "type searchableSphere; origin (0.5 0 0.4); "
                                     "radius (0.5 0.125 0.125); "
                                     "transform { type cartesian; origin (1 0 0); }"),
                     "moved or resized")

    def test_a_cylinder_body_is_refused(self):
        self.refused(lambda c: _edit(c, "system/snappyHexMeshDict", "geometry/spheroid",
                                     "type searchableCylinder; point1 (0 0 0.4); "
                                     "point2 (1 0 0.4); radius 0.1;"), "is a cylinder")

    def test_a_surface_body_needs_its_feature_dict(self):
        self.refused(lambda c: _edit(c, "system/snappyHexMeshDict", "geometry/spheroid",
                                     "type triSurfaceMesh; file \"body.stl\";"),
                     "surfaceFeatureExtractDict")

    def test_no_inlet_on_the_low_x_side_is_refused(self):
        self.refused(lambda c: _edit(c, "system/blockMeshDict", "boundary",
                                     "( walls { type wall; faces ((3 7 6 2) (1 5 4 0) "
                                     "(0 4 7 3) (2 6 5 1) (0 3 2 1) (4 5 6 7)); } )"),
                     "air enters along +x")


def _surface_case(test, name: str = "body.stl") -> str:
    """The baseline with its spheroid replaced by a surface file and a feature
    dictionary: a case whose body the gates take from ``aero_geometry``."""
    case = _copy_case(os.path.join(test.tmp(), "case"))
    _edit(case, "system/snappyHexMeshDict", "geometry/spheroid",
          f'type triSurfaceMesh; file "{name}";')
    with open(os.path.join(case, "system", "surfaceFeatureExtractDict"), "w") as fh:
        fh.write(f'FoamFile {{ version 2.0; format ascii; class dictionary; '
                 f'object surfaceFeatureExtractDict; }}\n{name} {{ extractionMethod '
                 f'extractFromSurface; includedAngle 150; }}\n')
    return case


class TheGeometryIsBoundByDigest(_env.EnvCase):
    """A surface file is named by ``aero_geometry`` and pinned by
    ``aero_geometry_sha256``: absent is a skip (nothing was shown), another
    digest is an error naming both, and a file of another name than the case's
    snappyHexMeshDict names is an error."""

    def setUp(self):
        self.registry = _registry()
        self.dir = self.tmp()
        self.stl = os.path.join(self.dir, "body.stl")
        with open(self.stl, "w") as fh:
            fh.write("solid body\nendsolid body\n")
        import hashlib
        with open(self.stl, "rb") as fh:
            self.sha = hashlib.sha256(fh.read()).hexdigest()

    def gate(self, **params):
        case = _surface_case(self)
        return _run(self.registry, "aero.case_readable", self.tmp(),
                    dict(_baseline(), aero_case=case, **params), tier=0)

    def test_absent_is_a_skip(self):
        v = self.gate()
        self.assertEqual(v.outcome, "skipped", v.render())
        self.assertIn("no aero_geometry", v.skip_reason)
        v = self.gate(aero_geometry=os.path.join(self.dir, "nothing.stl"),
                      aero_geometry_sha256=self.sha)
        self.assertEqual(v.outcome, "skipped", v.render())

    def test_another_digest_is_an_error_naming_both(self):
        v = self.gate(aero_geometry=self.stl, aero_geometry_sha256="0" * 64)
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn(self.sha, v.error)
        self.assertIn("0" * 64, v.error)

    def test_the_pinned_file_passes(self):
        v = self.gate(aero_geometry=self.stl, aero_geometry_sha256=self.sha)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn(self.sha[:12], v.detail)

    def test_a_file_the_case_does_not_name_is_an_error(self):
        other = os.path.join(self.dir, "other.stl")
        shutil.copy(self.stl, other)
        v = self.gate(aero_geometry=other, aero_geometry_sha256=self.sha)
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("names body.stl", v.error)


class TheReferenceIsTheStatedFlow(_env.EnvCase):
    """``aero.reference``: the inlet at the stated speed along +x, the body
    group's patches walls, and the body still."""

    def setUp(self):
        self.registry = _registry()

    def gate(self, edit=None, **params):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        if edit:
            edit(case)
        return _run(self.registry, "aero.reference", self.tmp(),
                    dict(_baseline(), aero_case=case, **params), tier=0)

    def test_the_baseline_passes(self):
        v = self.gate()
        self.assertEqual(v.outcome, "pass", v.render())

    def test_an_inlet_off_axis_fails(self):
        v = self.gate(lambda c: _edit(c, "0/U", "boundaryField/inlet",
                                      "type fixedValue; value uniform (20 1 0);"))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("not along +x", v.detail)

    def test_a_body_that_moves_with_the_air_fails(self):
        v = self.gate(lambda c: _edit(c, "0/U", "boundaryField/bodyGroup", "type slip;"))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("still wall", v.detail)

    def test_a_group_nobody_is_in_fails(self):
        v = self.gate(aero_body_group="motorBikeGroup")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("no body surface is in the group motorBikeGroup", v.detail)

    def test_a_body_patch_that_is_not_a_wall_fails(self):
        v = self.gate(lambda c: _edit(c, "system/snappyHexMeshDict",
                                      "castellatedMeshControls/refinementSurfaces/spheroid/"
                                      "patchInfo/type", "patch"))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("not a wall", v.detail)

    def test_no_speed_is_a_skip(self):
        params = _baseline()
        del params["aero_u_inf_m_s"]
        v = _run(self.registry, "aero.reference", self.tmp(), params, tier=0)
        self.assertEqual(v.outcome, "skipped", v.render())

    def test_a_regular_expression_that_sets_the_body_fails(self):
        """Review of P3-P5, run on the real v2606: with no literal entry for the
        body's group, OpenFOAM takes the LAST expression that matches a body
        patch. ``"sph.*" noSlip`` then ``"(upperWall|frontAndBack|spheroid)"
        slip`` ran the spheroid as slip (68% less drag), and the gate passed
        it as "sph.* still"."""
        def regex(case):
            _replace(case, "0/U", BODY_GROUP, _bc('"sph.*"', "noSlip"))
            _replace(case, "0/U", SLIP_WALLS, _bc('"(upperWall|frontAndBack|spheroid)"', "slip"))
        v = self.gate(regex)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("0/U names no group of the body surface spheroid (bodyGroup, wall) as a "
                      "literal entry", v.detail)

    def test_a_still_expression_alone_is_not_read_either(self):
        v = self.gate(lambda c: _replace(c, "0/U", BODY_GROUP, _bc('"sph.*"', "noSlip")))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("which this pack does not resolve", v.detail)

    def test_the_literal_group_wins_over_a_later_expression(self):
        """OpenFOAM sets a patch from its group's literal entry before it tries
        any expression, so a later slip expression that names the body moves
        nothing: the gate passes it, as OpenFOAM runs it."""
        v = self.gate(lambda c: _replace(
            c, "0/U", SLIP_WALLS, _bc('"(upperWall|frontAndBack|spheroid)"', "slip")))
        self.assertEqual(v.outcome, "pass", v.render())

    def test_the_wall_group_reaches_the_body(self):
        """A wall patch is in the group ``wall`` (wallPolyPatch): a literal
        ``wall`` entry reaches the body, and is held to a still wall too."""
        v = self.gate(lambda c: _replace(c, "0/U", BODY_GROUP, _bc("wall", "noSlip")))
        self.assertEqual(v.outcome, "pass", v.render())
        v = self.gate(lambda c: _replace(c, "0/U", BODY_GROUP, _bc("wall", "slip")))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("0/U's wall is slip", v.detail)

    def test_a_body_with_no_patch_info_fails(self):
        v = self.gate(lambda c: _edit(c, "system/snappyHexMeshDict",
                                      "castellatedMeshControls/refinementSurfaces/spheroid",
                                      "level (4 4);"))
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("the body surface spheroid states no patchInfo", v.detail)


class TheRegimeReportsItsNearestLimit(_env.EnvCase):
    """``aero.regime``'s value is the number nearer its own limit, in its own
    units: a Mach fail never reports a Reynolds number inside its limit."""

    def setUp(self):
        self.registry = _registry()

    def test_the_baseline_reports_its_reynolds_number(self):
        v = _run(self.registry, "aero.regime", self.tmp(), _baseline(), tier=0)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.units, v.comparator, v.limit), ("Re", ">=", 5e5))
        self.assertAlmostEqual(v.measured, 20 * 1.0 / 1.5e-5, places=1)

    def test_a_length_longer_than_the_body_fails_on_the_length(self):
        """Review of P3-P5: the 1 m spheroid in air ten times thicker has Re
        1.33e5, a laminar body; a stated length of 10 m read Re 1.33e6 and
        passed. The length is now held to the body along the flow."""
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "constant/transportProperties", "nu", "1.5e-04")
        v = _run(self.registry, "aero.regime", self.tmp(),
                 dict(_baseline(), aero_case=case, aero_ref_length_m=10.0), tier=1)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertEqual((v.measured, v.limit, v.comparator, v.units), (10.0, 1.0, "<=", "m"))
        self.assertIn("longer than the body along the flow (1 m)", v.detail)
        v = _run(self.registry, "aero.regime", self.tmp(),
                 dict(_baseline(), aero_case=case), tier=1)
        self.assertEqual((v.outcome, v.units), ("fail", "Re"), v.render())
        self.assertAlmostEqual(v.measured, 20 * 1.0 / 1.5e-4, places=3)

    def test_the_bodys_own_length_passes(self):
        v = _run(self.registry, "aero.regime", self.tmp(),
                 dict(_baseline(), aero_ref_length_m=1.0), tier=1)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("the body runs 1 m along the flow", v.detail)

    def test_a_fast_stream_fails_on_mach(self):
        v = _run(self.registry, "aero.regime", self.tmp(),
                 dict(_baseline(), aero_sound_speed_m_s=60.0), tier=0)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertEqual((v.units, v.comparator), ("Mach", "<"))
        self.assertGreaterEqual(v.measured, 0.3)


class NoGuardSpeaksForTheDragArea(unittest.TestCase):
    """Invariant 4: a drag-area claim is never Checked on guards that judge
    other quantities. What slipped through P3-P5 (review, 2026-10-23): every
    guard covered ``drag-area`` before aero.drag_area existed, so with all six
    passing, the baseline's B1 (``<= 0.0042 m^2``) composed Checked, while the
    one drag area measured, 0.00443 m^2, is past its limit and no evaluator
    read it. Composed here with the registry's own coverage and passing
    verdicts in each guard's own units."""

    def setUp(self):
        self.registry = _registry()
        (self.claim,) = [c for c in _claims() if c.id == "B1"]

    def test_every_guard_passing_leaves_the_drag_area_unchecked(self):
        from nopekit import claims as claims_mod
        from nopekit.models import Verdict
        specs = self.registry.for_claim(self.claim.id, self.claim.tags)
        self.claim.gates = [s.id for s in specs]
        # Every gate of the pack passes but aero.drag_area, which has not run:
        # the guards, each in its own units.
        verdicts = [Verdict(gate=s.id, passed=True, claims=list(s.claims), measured=1e6,
                            limit=5e5, comparator=">=", units="Re")
                    for s in (self.registry.get(g)[0] for g in self.registry.ids())
                    if s.pack == "aero-openfoam" and s.id != "aero.drag_area"]
        composed = claims_mod.compose(self.claim, verdicts)
        self.assertNotEqual(composed.status, "pass",
                            f"{self.claim.id} reads Checked on {[s.id for s in specs]}")

    def test_no_gate_but_the_drag_area_gate_covers_its_tag(self):
        tag = _module(self.registry)["DRAG_TAG"]
        self.assertIn(tag, self.claim.tags)
        for gid in self.registry.ids():
            spec = self.registry.get(gid)[0]
            if spec.pack == "aero-openfoam" and gid != "aero.drag_area":
                with self.subTest(gid):
                    self.assertNotIn(tag, spec.claims)


# --------------------------------------------------------------------------- #
# the domain's arithmetic
# --------------------------------------------------------------------------- #
class TheDomainIsFrankes(unittest.TestCase):
    """``aero.domain``'s measures on two boxes, held to the numbers P0 measured
    on the motorBike tutorial (references/domain.md) and to the limits'
    sources."""

    def setUp(self):
        self.A = _module(_registry())

    def rows(self, dom, body, ground):
        rows, h = self.A["domain_measures"](dom, body, ground)
        return {r[0]: r[1] for r in rows}, h

    def test_the_motorbike_tutorial_fails_four_distances(self):
        body = ((-0.291665, -0.350289, 0.0), (1.75115, 0.332267, 1.35152))
        m, h = self.rows(((-5, -4, 0), (15, 4, 8)), body, 0.0)
        self.assertAlmostEqual(h, 1.35152)
        for name, want in (("upstream", 3.48), ("downstream", 9.80), ("side", 2.70),
                           ("top", 4.92), ("lateral blockage", 8.5), ("vertical blockage", 16.9)):
            self.assertAlmostEqual(m[name], want, delta=0.01 * want, msg=name)

    def test_the_limits_are_the_sources(self):
        A = self.A
        self.assertEqual((A["UPSTREAM_MIN_H"], A["DOWNSTREAM_MIN_H"], A["SIDE_MIN_H"],
                          A["TOP_MIN_H"], A["BLOCKAGE_MAX_PCT"], A["DIRECTIONAL_MAX_PCT"]),
                         (5.0, 15.0, 5.0, 5.0, 3.0, 17.0))

    def test_a_body_in_free_air_is_measured_by_its_own_height_and_below(self):
        m, h = self.rows(((-5, -5, -5), (20, 5, 5)), ((0, -0.5, -0.5), (1, 0.5, 0.5)), None)
        self.assertEqual(h, 1.0)
        self.assertIn("bottom", m)
        self.assertAlmostEqual(m["bottom"], 4.5)


# --------------------------------------------------------------------------- #
# the stand-in OpenFOAM and mpirun
# --------------------------------------------------------------------------- #
def _exe(path: str, text: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def install_standin(directory: str) -> tuple[str, str]:
    """The stand-in OpenFOAM installed under ``directory``: ``(install root,
    bin)``, ``bin`` holding only the ``openfoam2606`` wrapper, to put on PATH.
    Its etc/bashrc puts the stand-in's own ``mpirun`` first on the PATH it
    sets, as a real install's puts its MPI's."""
    root = os.path.join(directory, "openfoam2606")
    appbin = os.path.join(root, "platforms", "linux64GccDPInt32Opt", "bin")
    mpibin = os.path.join(root, "mpi", "bin")
    for d in (appbin, mpibin, os.path.join(root, "etc"), os.path.join(root, "META-INFO")):
        os.makedirs(d)
    with open(os.path.join(root, "etc", "bashrc"), "w") as fh:
        fh.write('root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"\n'
                 'export WM_PROJECT_DIR="$root"\n'
                 'export FOAM_APPBIN="$root/platforms/linux64GccDPInt32Opt/bin"\n'
                 'export PATH="$root/mpi/bin:$PATH"\n')
    with open(os.path.join(root, "META-INFO", "api-info"), "w") as fh:
        fh.write("api=2606\npatch=0\n")
    for tool, where in [(t, appbin) for t in (
            "blockMesh", "decomposePar", "snappyHexMesh", "checkMesh", "foamDictionary",
            "surfaceCheck", "surfaceFeatureExtract", "potentialFoam", "simpleFoam")] + [
            ("mpirun", mpibin)]:
        _exe(os.path.join(where, tool),
             f"#!{sys.executable}\nimport os, runpy\nos.environ['STANDIN_TOOL'] = "
             f"{tool!r}\nrunpy.run_path({STANDIN!r}, run_name='__main__')\n")
    bin_dir = os.path.join(directory, "bin")
    os.makedirs(bin_dir)
    _exe(os.path.join(bin_dir, "openfoam2606"), f'#!/bin/sh\nexec "{root}"/etc/openfoam "$@"\n')
    with open(os.path.join(root, "standin.json"), "w") as fh:
        json.dump({}, fh)
    return root, bin_dir


class _StandinBase(_env.EnvCase):
    """The stand-in's set-up. Undecorated, for the invariant classes, which may
    not skip (``test_meta.InvariantClassesNeverSkip``): they run where CI runs,
    on POSIX, and nowhere else is the pack's OpenFOAM supported."""

    def setUp(self):
        self.dir = self.tmp()
        self.root, self.bin = install_standin(self.dir)
        self.registry = _registry()
        self.params = _baseline()
        self.mode({})

    def mode(self, mode: dict) -> None:
        with open(os.path.join(self.root, "standin.json"), "w") as fh:
            json.dump(mode, fh)

    def calls(self) -> list[str]:
        try:
            with open(os.path.join(self.root, "calls")) as fh:
                return fh.read().split()
        except OSError:
            return []

    def gate(self, gid: str, params: dict | None = None):
        calls = os.path.join(self.root, "calls")
        if os.path.exists(calls):
            os.remove(calls)
        self.out = self.tmp()
        env = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin"}
        with mock.patch.dict(os.environ, env):
            v = _run(self.registry, gid, self.out, dict(self.params, **(params or {})), tier=1)
        if v.outcome in ("pass", "fail"):
            self.assertTrue(self.calls(), f"the stand-in never ran: {v.render()}")
        return v

    def staged(self, gid: str, rel: str) -> str:
        path = os.path.join(self.out, "out", gid.replace(".", "_"), "aero-openfoam",
                            gid.replace(".", "_"), "case", *rel.split("/"))
        with open(path, encoding="utf-8") as fh:
            return fh.read()


@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
class _StandinCase(_StandinBase):
    pass


class AMeshIsJudgedByThePacksLimits(_StandinCase):
    """``aero.mesh_quality`` through the stand-in: what the real tools printed on
    the baseline, and each way a finished-looking mesh is not."""

    def test_the_baseline_passes_at_its_cell_count(self):
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.measured, v.units, v.comparator, v.limit),
                         (41574.0, "cells", "<", 2e7))
        self.assertIn("layers on 100% of the body's faces", v.detail)
        calls = self.calls()
        for tool in ("blockMesh", "decomposePar", "snappyHexMesh", "checkMesh"):
            self.assertIn(tool, calls)
        self.assertLess(calls.index("decomposePar"), calls.index("snappyHexMesh"))

    def test_the_staged_dictionaries_are_the_packs(self):
        self.gate("aero.mesh_quality", {"aero_max_global_cells": 3_000_000})
        self.assertEqual(self.staged("aero.mesh_quality", "system/meshQualityDict"),
                         FO.quality_dict())
        self.assertEqual(self.staged("aero.mesh_quality", "system/decomposeParDict"),
                         FO.decompose_dict(4))
        snappy = F.parse(self.staged("aero.mesh_quality", "system/snappyHexMeshDict"))
        self.assertEqual(F.scalar(snappy.sub("castellatedMeshControls"), "maxGlobalCells"),
                         3_000_000)
        mqc = snappy.sub("meshQualityControls")
        self.assertEqual([(e.key, F.words(e)[0]) for e in mqc.entries],
                         list(FO.QUALITY) + list(FO.SMOOTHING))

    def test_plain_check_mesh_failure_is_not_the_judge(self):
        """"Failed 1 mesh checks" (plain checkMesh's fixed skewness limit) with
        no face in error against the pack's limits: a pass."""
        self.mode({"checkMesh": {"replace": [["Mesh OK.", " ***Max skewness = 8.13, 29 "
                                              "highly skew faces detected\n\nFailed 1 mesh "
                                              "checks."]]}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "pass", v.render())

    def test_one_face_in_error_fails(self):
        self.mode({"checkMesh": {"replace": [[
            "faces with interpolation weights (0..1)  <  0.05       : 0",
            "faces with interpolation weights (0..1)  <  0.05       : 1"]]}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertEqual((v.measured, v.units, v.comparator, v.limit), (1.0, "faces", "<=", 0.0))
        self.assertIn("1 faces in error", v.detail)

    def test_a_check_against_other_limits_is_an_error(self):
        """The tutorial's own dict (minFaceWeight 0.02): its meshes pass it and
        fail the pack's on 1 095 faces (P0)."""
        self.mode({"checkMesh": {"replace": [["(0..1)  <  0.05", "(0..1)  <  0.02"]]}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("not the pack's", v.error)

    def test_a_cap_reached_fails_though_snappy_says_it_finished(self):
        self.mode({"snappyHexMesh": {"log": "capped"}})
        v = self.gate("aero.mesh_quality", {"aero_max_global_cells": 20000})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("cell cap 20000", v.detail)
        self.assertEqual((v.measured, v.units, v.limit), (27408.0, "cells", 20000.0))
        self.assertIn("38.9%", v.detail)

    def test_a_face_in_error_in_snappys_final_check_fails(self):
        self.mode({"snappyHexMesh": {"replace": [[
            "faces with face twist < 0.02                           : 0",
            "faces with face twist < 0.02                           : 3"]]}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("final check: 3 faces with face twist", v.detail)

    def test_a_mesher_that_did_not_finish_fails(self):
        self.mode({"snappyHexMesh": {"replace": [["Finished meshing without any errors",
                                                  "Finished meshing with 2 illegal faces"]]}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("did not finish", v.detail)

    def test_a_merge_openfoam_reads_and_the_reader_never_saw_is_an_error(self):
        """What slipped through cfd-openfoam's first draft: an include that
        MERGES into the pack's own dictionaries. Here OpenFOAM's expansion of the
        staged snappyHexMeshDict holds a relaxed control the reader never read."""
        self.mode({"expand_append": {"system/snappyHexMeshDict":
                                     "\nmeshQualityControls { maxNonOrtho 180; }\n"}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("system/snappyHexMeshDict", v.error)
        self.assertNotIn("snappyHexMesh", self.calls())

    def test_a_block_mesh_that_is_not_the_one_read_is_an_error(self):
        self.mode({"blockMesh": {"cells_delta": 1}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("2689 cells", v.error)

    def test_a_cases_own_cap_never_reaches_the_mesher(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/snappyHexMeshDict", "castellatedMeshControls/maxGlobalCells", "1")
        v = self.gate("aero.mesh_quality", {"aero_case": case})
        self.assertEqual(v.outcome, "pass", v.render())
        snappy = F.parse(self.staged("aero.mesh_quality", "system/snappyHexMeshDict"))
        self.assertEqual(F.scalar(snappy.sub("castellatedMeshControls"), "maxGlobalCells"),
                         2e7)


@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
class OneSetOfInputsIsOneEntry(_env.EnvCase):
    """Two check runs of the same project, nothing changed between them, file
    one cache entry per gate. What slipped through P3-P5 (the motorbike demo's
    two check runs, 2026-10-23): aero.domain and aero.mesh_quality each wrote
    a second entry for the same inputs. The first run wrote the private
    HOME's controlDict and later runs read it (``_tool.home``), and a later
    run's removal of the last run's staged copy (``shutil.rmtree`` opens each
    folder by a name relative to its parent's descriptor) was read as files of
    the project. A cache committed after one run would then never hit on a
    fresh clone."""

    @classmethod
    def setUpClass(cls):
        import tempfile
        import _projects
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        _root, bin_ = install_standin(os.path.join(cls.dir, "tool"))
        env = {"PATH": bin_ + os.pathsep + "/usr/bin:/bin"}
        cls.root = _projects.wrap_pack_baseline("aero-openfoam", os.path.join(cls.dir, "proj"))
        cls.runs = [_env.nopekit(["check", "--tier", "2"], cwd=cls.root, env=env, timeout=900)
                    for _ in range(2)]

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)

    def test_each_gate_has_one_entry(self):
        for run in self.runs:
            self.assertIn("aero.mesh_quality", run.stdout, run.stdout[-3000:] + run.stderr[-3000:])
        cache = os.path.join(self.root, ".nopekit", "verdicts")
        gates = sorted(os.listdir(cache))
        self.assertIn("aero.domain", gates)
        self.assertIn("aero.mesh_quality", gates)
        self.assertIn("aero.converged", gates)
        for gid in gates:
            with self.subTest(gid):
                entries = [n for n in os.listdir(os.path.join(cache, gid))
                           if not n.startswith("control-")]
                self.assertEqual(len(entries), 1, entries)


class TheParallelBannerIsChecked(_StandinCase):
    """Every parallel run's banner says the ranks the pack asked for, trapping
    on and system operations off; and every rank is asked for its HOME and its
    FOAM_SIGFPE before the first parallel tool runs."""

    def test_another_rank_count_is_an_error(self):
        self.mode({"nprocs_banner": 3})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("nProcs 3", v.error)

    def test_no_trapping_is_an_error(self):
        self.mode({"omit": ["no-fpe"]})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("floating-point trapping", v.error)

    def test_system_operations_allowed_is_an_error(self):
        self.mode({"omit": ["allowing"]})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("system operations allowed", v.error)

    def test_the_home_is_the_packs_own(self):
        """Review of P3-P5: the copied ``_tool.home`` named cfd-openfoam's
        HOME, so an aero gate ran in ``<out>/cfd-openfoam/home``."""
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "pass", v.render())
        out = os.path.join(self.out, "out", "aero_mesh_quality")
        with open(os.path.join(out, "aero-openfoam", "home", ".OpenFOAM", "2606",
                               "controlDict"), encoding="utf-8") as fh:
            self.assertIn("allowSystemOperations 0", fh.read())
        self.assertFalse(os.path.exists(os.path.join(out, "cfd-openfoam")))

    def test_a_rank_with_another_home_is_an_error_before_any_parallel_tool(self):
        """P0's Probe B: a rank with another HOME left the master's banner
        saying "Disallowing" and hung."""
        self.mode({"probe": {"home_rank": 1}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("rank 1 runs with HOME '/elsewhere'", v.error)
        self.assertNotIn("snappyHexMesh", self.calls())

    def test_a_rank_without_trapping_is_an_error(self):
        self.mode({"probe": {"fpe_rank": 2}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("rank 2 runs without FOAM_SIGFPE", v.error)

    def test_a_rank_that_does_not_answer_is_an_error(self):
        self.mode({"probe": {"missing_rank": 3}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("heard from ranks [0, 1, 2]", v.error)

    def test_a_rank_killed_by_sigfpe_is_an_error(self):
        self.mode({"snappyHexMesh": {"fail": "fpe"}})
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("SIGFPE", v.error)

    def test_a_hang_is_a_skip_and_kills_every_rank(self):
        self.mode({"snappyHexMesh": {"fail": "hang"}})
        v = self.gate("aero.mesh_quality", {"aero_timeout_s": 3})
        self.assertEqual(v.outcome, "skipped", v.render())
        self.assertIn("aero_timeout_s", v.skip_reason)
        left = _env.run(["pgrep", "-f", self.root], cwd=self.dir)
        self.assertEqual(left.stdout.strip(), "", "a rank outlived its timeout")


class TheBodysBoundsAreOpenFOAMs(_StandinCase):
    """For a surface file, ``aero.domain`` reads the body's bounds from
    OpenFOAM's surfaceCheck, run in its own scratch: it writes files where it
    runs."""

    def test_a_surface_body_is_measured_by_surfacecheck(self):
        stl = os.path.join(self.dir, "body.stl")
        with open(stl, "w") as fh:
            fh.write("solid body\nendsolid body\n")
        import hashlib
        with open(stl, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        case = _surface_case(self)
        self.mode({"surfaceCheck": {"box": [[0, -0.1, 0.3], [1, 0.1, 0.5]]}})
        v = self.gate("aero.domain", {"aero_case": case, "aero_geometry": stl,
                                      "aero_geometry_sha256": sha})
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("surfaceCheck", self.calls())
        self.assertIn("H 0.5 m", v.detail)
        scratch = os.path.join(self.out, "out", "aero_domain", "aero-openfoam", "aero_domain",
                               "surfaceCheck")
        self.assertTrue(any(n.startswith("standin_part_") for n in os.listdir(scratch)))
        self.assertFalse(any(n.startswith("standin_part_") for n in os.listdir(case)))

    def test_a_body_sunk_into_the_ground_fails(self):
        stl = os.path.join(self.dir, "body.stl")
        with open(stl, "w") as fh:
            fh.write("solid body\nendsolid body\n")
        import hashlib
        with open(stl, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        case = _surface_case(self)
        self.mode({"surfaceCheck": {"box": [[0, -0.1, -0.05], [1, 0.1, 0.5]]}})
        v = self.gate("aero.domain", {"aero_case": case, "aero_geometry": stl,
                                      "aero_geometry_sha256": sha})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("below the ground", v.detail)

    def test_the_regime_holds_the_length_to_surfacechecks_body(self):
        """Review of P3-P5: for a surface file, aero.regime reads the body's
        length along the flow from surfaceCheck, as aero.domain does."""
        stl = os.path.join(self.dir, "body.stl")
        with open(stl, "w") as fh:
            fh.write("solid body\nendsolid body\n")
        import hashlib
        with open(stl, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        case = _surface_case(self)
        self.mode({"surfaceCheck": {"box": [[0.2, -0.1, 0.3], [1.0, 0.1, 0.5]]}})
        params = {"aero_case": case, "aero_geometry": stl, "aero_geometry_sha256": sha}
        v = self.gate("aero.regime", dict(params, aero_ref_length_m=0.8))
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("surfaceCheck", self.calls())
        self.assertIn("the body runs 0.8 m along the flow", v.detail)
        v = self.gate("aero.regime", dict(params, aero_ref_length_m=1.0))
        self.assertEqual((v.outcome, v.units, v.limit), ("fail", "m", 0.8), v.render())


# --------------------------------------------------------------------------- #
# convergence
# --------------------------------------------------------------------------- #
def _motorbike_history() -> list[float]:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aero_fixtures",
                        "motorbike_L0_cda.csv")
    with open(path, encoding="utf-8") as fh:
        return [float(line.split(",")[1]) for line in fh if line[:1].isdigit()]


class TheIterativeUncertaintyIsTheHalfRange(unittest.TestCase):
    """U_I = (max - min) / 2 over the last window (ITTC 7.5-03-01-01, the
    oscillatory case), held to what P0 measured on the motorBike tutorial's L0
    history (tests/aero_fixtures/motorbike_L0_cda.csv, 1500 iterations), and
    to a decaying oscillation whose limit is known."""

    def pct(self, values, window):
        u_i, _lo, _hi, mean = P.half_range(values, window)
        return 100.0 * u_i / mean

    def test_the_motorbike_numbers_p0_measured(self):
        cda = _motorbike_history()
        self.assertEqual(len(cda), 1500)
        self.assertAlmostEqual(self.pct(cda, 100), 0.24, delta=0.005)
        self.assertAlmostEqual(self.pct(cda, 200), 0.27, delta=0.005)
        first = next(e for e in range(100, 1501) if self.pct(cda[:e], 100) <= 1.0)
        self.assertEqual(first, 148)

    def test_the_half_range_misses_a_drift_the_drift_term_shows(self):
        """P0: the window mean moved +0.59% between iteration 500 and 1000
        while U_I at 500 read 0.27%."""
        cda = _motorbike_history()
        at500, at1000 = P.half_range(cda[:500], 100), P.half_range(cda[:1000], 100)
        self.assertAlmostEqual(100 * at500[0] / at500[3], 0.27, delta=0.005)
        self.assertAlmostEqual(100 * (at1000[3] - at500[3]) / at500[3], 0.59, delta=0.01)
        now, before = P.drift(cda[:1000], 100)
        self.assertNotEqual(now, before)

    def test_a_decaying_oscillation_is_covered(self):
        """A history c (1 + a r^i sin(2 pi i / T)) settles to c: the window's
        mean sits within U_I of it."""
        c = 0.3
        for a, r, period in ((0.05, 0.995, 16), (0.2, 0.99, 7), (0.01, 0.999, 31)):
            values = [c * (1 + a * r ** i * math.sin(2 * math.pi * i / period))
                      for i in range(1, 501)]
            u_i, lo, hi, mean = P.half_range(values, 100)
            self.assertLessEqual(abs(mean - c), u_i, (a, r, period))
            self.assertTrue(lo <= c <= hi, (a, r, period))

    def test_a_short_history_has_no_uncertainty(self):
        self.assertIsNone(P.half_range([1.0] * 99, 100))
        self.assertIsNone(P.half_range([1.0] * 99 + [float("nan")], 100))
        self.assertIsNone(P.drift([1.0] * 199, 100))


class TheGateSettlesOnTheBaseMesh(_StandinCase):
    """``aero.converged`` through the stand-in: the baseline's real history,
    cut where the staged endTime cuts it."""

    def test_the_baseline_passes_and_names_its_pictures(self):
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.units, v.comparator, v.limit), ("%", "<=", 1.0))
        summary = next(p for p in v.evidence if p.endswith("summary.json"))
        with open(summary, encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(v.measured, float(f"{data['u_i_pct']:.6g}"))
        self.assertAlmostEqual(data["u_i_pct"], 0.0148, delta=0.0005)
        self.assertEqual(data["mesh_level"], "base")
        self.assertEqual(data["body_bbox"], [[0.0, -0.125, 0.275], [1.0, 0.125, 0.525]])
        self.assertEqual(sorted(data["fields"]["sha256"]), sorted(FO.picture_files("300")))
        self.assertTrue(data["fields"]["stage"].startswith("<out>/"))
        self.assertFalse([k for k in data if "limit" in k or "max" in k],
                         "a picture's scale is never taken from a limit: the summary holds "
                         "none")
        hist = next(p for p in v.evidence if p.endswith("history.csv"))
        with open(hist, encoding="utf-8") as fh:
            self.assertEqual(len(fh.read().splitlines()), 301)
        self.assertIn("iterations 201-300", v.detail)
        calls = self.calls()
        self.assertLess(calls.index("snappyHexMesh"), calls.index("potentialFoam"))
        self.assertLess(calls.index("potentialFoam"), calls.index("simpleFoam"))

    def test_the_staged_function_objects_are_the_packs(self):
        """The case carries none (aero.case_readable refuses them); the staged
        controlDict carries exactly the pack's, at the stated speed and over the
        body's box."""
        self.gate("aero.converged")
        control = F.parse(self.staged("aero.converged", "system/controlDict"))
        want = F.parse(FO.functions(group="bodyGroup", u_inf=20.0, l_ref=1.0,
                                    cofr=(0.0, 0.0, 0.0),
                                    box=((0.0, -0.125, 0.275), (1.0, 0.125, 0.525))))
        A = _module(self.registry)
        self.assertEqual(A["_canon"](control.sub("functions")), A["_canon"](want.sub("functions")))
        self.assertEqual(F.scalar(control, "writePrecision"), 12)

    def test_a_merge_into_the_function_objects_is_an_error(self):
        self.mode({"expand_append": {"system/controlDict":
                                     "\nfunctions { forceCoeffs1 { Aref 0.75; } }\n"}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("system/controlDict", v.error)
        self.assertNotIn("simpleFoam", self.calls())

    def test_a_history_at_another_speed_is_an_error(self):
        self.mode({"simpleFoam": {"replace": [["# magUInf           : 2.000000000000e+01",
                                               "# magUInf           : 2.300000000000e+01"]]}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("not the pack's", v.error)

    def test_a_history_that_is_not_the_runs_is_an_error(self):
        self.mode({"simpleFoam": {"rows_short": 5}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("295 rows", v.error)

    def test_a_residual_that_climbs_at_the_end_fails(self):
        self.mode({"simpleFoam": {"residual_climb": 40}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("a residual climbs at the end", v.detail)
        self.assertIsNone(v.measured)

    def test_bounding_is_reported_and_never_judged(self):
        self.mode({"simpleFoam": {"bounding": 300}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertIn("omega bounded in 300 iterations", v.detail)

    def test_missing_pictures_move_nothing(self):
        self.mode({"simpleFoam": {"no_pictures": True}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "pass", v.render())

    def test_a_mesh_that_fails_the_rule_where_it_is_solved_is_an_error(self):
        """The mesh this gate solves on is built again in its own stage and
        judged again: one that fails the rule aero.mesh_quality passed is the two
        disagreeing."""
        self.mode({"snappyHexMesh": {"log": "capped"}})
        v = self.gate("aero.converged")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("fails the rule aero.mesh_quality passed", v.error)
        self.assertNotIn("simpleFoam", self.calls())


class ACutShortRunFails(_StandinCase):
    """A run that stopped early exits 0 and prints End: its history decides.
    It fails, never errors: the run did what it was told and settled nothing."""

    def case(self, end: str) -> str:
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/controlDict", "endTime", end)
        return case

    def test_the_control_lands_past_the_ceiling(self):
        v = self.gate("aero.converged", {"aero_case": self.case("110")})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertGreaterEqual(v.measured, 1.15 * v.limit)
        self.assertIn("iterations 11-110", v.detail)

    def test_a_window_that_never_filled_fails_with_no_value(self):
        v = self.gate("aero.converged", {"aero_case": self.case("60")})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("the window never filled: 60 iterations", v.detail)
        self.assertIsNone(v.measured)


# --------------------------------------------------------------------------- #
# the wall
# --------------------------------------------------------------------------- #
def _ascii_vtp(path: str, points, polys, values) -> None:
    """A VTK PolyData file in OpenFOAM's layout, ascii, with ``yPlus`` on its
    cells."""
    conn, offs = [], []
    for poly in polys:
        conn += poly
        offs.append(len(conn))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("<?xml version='1.0'?>\n<VTKFile type='PolyData' version='0.1' "
                 "byte_order='LittleEndian' header_type='UInt64'>\n  <PolyData>\n"
                 f"    <Piece NumberOfPoints='{len(points)}' NumberOfPolys='{len(polys)}'>\n"
                 "      <Points>\n        <DataArray type='Float32' Name='Points' "
                 "NumberOfComponents='3' format='ascii'>\n"
                 + " ".join(f"{c:g}" for p in points for c in p) +
                 "\n        </DataArray>\n      </Points>\n      <Polys>\n"
                 "        <DataArray type='Int32' Name='connectivity' format='ascii'>\n"
                 + " ".join(map(str, conn)) +
                 "\n        </DataArray>\n        <DataArray type='Int32' Name='offsets' "
                 "format='ascii'>\n" + " ".join(map(str, offs)) +
                 "\n        </DataArray>\n      </Polys>\n      <CellData>\n"
                 "        <DataArray type='Float32' Name='yPlus' format='ascii'>\n"
                 + " ".join(f"{v:g}" for v in values) +
                 "\n        </DataArray>\n      </CellData>\n    </Piece>\n  </PolyData>\n"
                 "</VTKFile>\n")


class TheYPlusFractionIsOpenFOAMs(_StandinCase):
    """``aero.wall_treatment``: the share of the body's area with y+ at most
    300, summed over the surface OpenFOAM wrote and held to OpenFOAM's own
    area and area mean of the same patches. P0 found the ``expressions`` route
    reading 1.0 on every case, and ParaView's ``CellSize`` 0.8% more area than
    OpenFOAM's faces: neither is the route."""

    def test_the_vector_area_is_openfoams_and_a_unit_cube_is_six(self):
        cube = [(x, y, z) for z in (0, 1) for y in (0, 1) for x in (0, 1)]
        faces = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2],
                 [1, 3, 7, 5]]
        path = os.path.join(self.tmp(), "cube.vtp")
        _ascii_vtp(path, cube, faces, [1, 2, 3, 400, 500, 600])
        w = P.wall_surface(path, "yPlus")
        self.assertAlmostEqual(w.area, 6.0, places=12)
        self.assertAlmostEqual(w.share(None, 300.0), 50.0, places=12)
        self.assertAlmostEqual(w.mean(), 251.0, places=9)
        # A face folded out of its plane: its vector area, as OpenFOAM's magSf,
        # is less than the sum of its two triangles' (ParaView's CellSize).
        bent = [(0, 0, 0), (1, 0, 0), (1, 1, 0.5), (0, 1, 0)]
        path = os.path.join(self.tmp(), "bent.vtp")
        _ascii_vtp(path, bent, [[0, 1, 2, 3]], [10])
        tri = 0.5 * math.sqrt(1.25) + 0.5 * math.sqrt(1.25)
        self.assertLess(P.wall_surface(path, "yPlus").area, tri)

    def test_a_compressed_or_appended_surface_is_refused(self):
        with open(os.path.join(REPO, "tests", "aero_fixtures", "views", "yplus.vtp"), "rb") as fh:
            data = fh.read()
        path = os.path.join(self.tmp(), "z.vtp")
        with open(path, "wb") as fh:
            fh.write(data)
        with self.assertRaises(ValueError):
            P.wall_surface(path, "yPlus")

    def test_the_baseline_passes_and_names_its_picture(self):
        v = self.gate("aero.wall_treatment")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.measured, v.limit, v.comparator, v.units), (100.0, 90.0, ">=", "%"))
        with open(next(p for p in v.evidence if p.endswith("summary.json"))) as fh:
            data = json.load(fh)
        self.assertEqual(sorted(data["fields"]["sha256"]),
                         ["postProcessing/surfaces1/300/bodyYPlus.vtp"])
        self.assertAlmostEqual(data["yplus_mean"], data["yplus_mean_openfoam"], places=4)
        self.assertEqual(data["faces"], 2396)
        self.assertFalse([k for k in data if "limit" in k or "max" in k])
        self.assertIn("(OpenFOAM's 121.2)", v.detail)

    def test_no_layers_fails_past_its_margin(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/snappyHexMeshDict", "addLayers", "false")
        v = self.gate("aero.wall_treatment", {"aero_case": case})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertLessEqual(v.measured * 1.15, v.limit)

    def test_a_surface_that_is_not_the_body_openfoam_integrated_is_an_error(self):
        for old, new in (("# Area              : 6.313818964463e-01",
                          "# Area              : 6.413818964463e-01"),
                         ("# Faces             : 2396", "# Faces             : 2395"),
                         ("1.211536800544e+02", "1.221536800544e+02")):
            with self.subTest(old):
                self.mode({"simpleFoam": {"wall_replace": [[old, new]]}})
                v = self.gate("aero.wall_treatment")
                self.assertEqual(v.outcome, "error", v.render())
                self.assertIn("not the body OpenFOAM integrated", v.error)

    def test_a_run_that_did_not_settle_here_is_an_error(self):
        self.mode({"simpleFoam": {"residual_climb": 40}})
        v = self.gate("aero.wall_treatment")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("fails the rule aero.converged passed", v.error)

    def test_a_body_on_another_wall_function_is_an_error_before_any_tool(self):
        """Review of P6: the rule (y+ at most 300, no floor) is Spalding's.
        A body on the tutorial's nutkWallFunction, under its group or under a
        key of its own patch, read Checked with no look at which one it had."""
        nut = "0/nut"
        for how in ("group", "patch", "wall group", "no group"):
            with self.subTest(how):
                case = _copy_case(os.path.join(self.tmp(), "case"))
                if how == "group":
                    _edit(case, nut, "boundaryField/bodyGroup/type", "nutkWallFunction")
                elif how == "no group":
                    _replace(case, nut, "    bodyGroup\n", "    \"body.*\"\n")
                else:
                    key = "spheroid" if how == "patch" else "wall"
                    _replace(case, nut, "    bodyGroup\n",
                             f"    {key}\n    {{\n        type            nutkWallFunction;\n"
                             f"        value           uniform 0;\n    }}\n    bodyGroup\n")
                v = self.gate("aero.wall_treatment", {"aero_case": case})
                self.assertEqual(v.outcome, "error", v.render())
                self.assertIn("0/nut", v.error)
                self.assertEqual(self.calls(), [], "refused before any tool")
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _replace(case, nut, "    bodyGroup\n",
                 "    spheroid\n    {\n        type            nutUSpaldingWallFunction;\n"
                 "        value           uniform 0;\n    }\n    bodyGroup\n")
        self.assertEqual(self.gate("aero.wall_treatment", {"aero_case": case}).outcome, "pass")


# --------------------------------------------------------------------------- #
# the ladder and the drag area
# --------------------------------------------------------------------------- #
class _LadderCase(_StandinBase):
    def gates(self, *gids, params=None, out=None):
        """Each of ``gids`` in order, in one out directory (a check run's)."""
        out = out or self.tmp()
        env = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin"}
        found = []
        with mock.patch.dict(os.environ, env):
            for gid in gids:
                calls = os.path.join(self.root, "calls")
                if os.path.exists(calls):
                    os.remove(calls)
                ctx = gates_mod.GateContext(
                    root=out, ledger=Ledger(meta=ProjectMeta(name="aero"), claims=self.claims()),
                    params=dict(self.params, **(params or {})), out_dir=os.path.join(out, "out"),
                    tier=2, log=lambda _m: None, extra={})
                found.append((gates_mod.run_gate(*self.registry.get(gid), ctx), self.calls()))
        return found

    def claims(self):
        return _claims()

    def summary(self, v) -> dict:
        with open(next(p for p in v.evidence if p.endswith("summary.json"))) as fh:
            return json.load(fh)


class EveryLadderLevelPassesTheGuards(_LadderCase):
    """``aero.mesh_independence`` through the stand-in, which replays the real
    ladder of the baseline (P6: 41 574, 132 094 and 386 302 cells): each level
    meshed and held to aero.mesh_quality's rule, the effective ratios judged
    before any solve, each level held to aero.converged's rule, then Celik's
    GCI with the pack's order rule."""

    def test_the_references_ladder_table_is_its_own_cells(self):
        """Review of P6: meshing.md gave bigger_body's effective ratios as
        1.469 and 1.443, and its own cells give 1.468 and 1.425 (1.443 gives a
        GCI of 17.4%, not the 18.28% the gate computed). Each row's ratios,
        (N_fine / N_coarse)^(1/3), from the cells the same row states."""
        with open(os.path.join(PACK, "references", "meshing.md"), encoding="utf-8") as fh:
            text = fh.read()
        rows = re.findall(r"^\| [^|]+ \| ([\d ]+), ([\d ]+), ([\d ]+) \| "
                          r"(\d\.\d{3}), (\d\.\d{3})", text, re.M)
        self.assertEqual(len(rows), 3, "the three measured ladders")
        for row in rows:
            with self.subTest(row):
                n = [int(c.replace(" ", "")) for c in row[:3]]
                said = [float(x) for x in row[3:]]
                self.assertEqual(said, [round((n[1] / n[0]) ** (1 / 3), 3),
                                        round((n[2] / n[1]) ** (1 / 3), 3)])

    def test_the_baseline_passes_on_the_formal_order(self):
        ((v, calls),) = self.gates("aero.mesh_independence")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.units, v.comparator, v.limit), ("%", "<=", 20.0))
        self.assertAlmostEqual(v.measured, 15.6741, places=3)
        self.assertIn("the band at the formal order with Fs 3", v.detail)
        self.assertEqual(calls.count("simpleFoam"), 3)
        data = self.summary(v)
        self.assertEqual([lv["cells"] for lv in data["levels"]], [41574, 132094, 386302])
        self.assertEqual([lv["counts"] for lv in data["levels"]],
                         [[[28, 12, 8]], [[42, 18, 12]], [[63, 27, 18]]])
        self.assertEqual((data["order_rule"], data["order_used"], data["safety_factor"]),
                         ("formal", 2.0, 3.0))
        # 2.712 on the real ladder; the stand-in's base mesh replays P3's history,
        # solved on 41 546 cells (``_aero_standin.HISTORIES``).
        self.assertAlmostEqual(data["gci"]["p"], 2.71, delta=0.005)
        fine = data["levels"][-1]
        self.assertEqual(fine["h_rel"], 1.0)
        self.assertEqual(data["band_top_m2"], fine["cda_m2"] * (1 + data["gci_fine_pct"] / 100))
        self.assertEqual(v.measured, float(f"{data['gci_fine_pct']:.6g}"))
        self.assertLess(data["cda_ext_m2"], fine["cda_m2"])
        self.assertFalse([k for k in data if "limit" in k or "max" in k])

    def test_the_refined_levels_are_the_packs(self):
        """Each block direction times r^k; each distance region's distance over
        r^k, at the precision OpenFOAM reads it back."""
        self.gates("aero.mesh_independence")
        out = self.tmp()
        self.gates("aero.mesh_independence", out=out)
        stage = os.path.join(out, "out", "aero-openfoam", "aero_mesh_independence", "level2")
        snappy = F.read(os.path.join(stage, "system", "snappyHexMeshDict"))
        levels = snappy.lookup("castellatedMeshControls/refinementRegions/spheroid/levels")
        self.assertEqual(F.vector(levels.value[0][0]), (0.0133333, 5.0))
        with open(os.path.join(stage, "system", "blockMeshDict")) as fh:
            self.assertIn("(63 27 18)", fh.read())

    def test_a_narrow_ladder_fails_before_any_solve(self):
        ((v, calls),) = self.gates("aero.mesh_independence", params={"aero_ladder_ratio": 1.3})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("effective refinement ratios 1.237 and 1.308", v.detail)
        self.assertIn("judged before any solve", v.detail)
        self.assertNotIn("simpleFoam", calls)
        self.assertEqual(calls.count("snappyHexMesh"), 3)

    def test_a_capped_level_fails_before_any_solve(self):
        self.mode({"snappyHexMesh": {"log": "capped"}})
        ((v, calls),) = self.gates("aero.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("fails aero.mesh_quality's rule", v.detail)
        self.assertNotIn("simpleFoam", calls)

    def test_an_oscillating_ladder_fails_with_its_reason(self):
        """The demo's way to Failing (D6): the motorBike's drag areas went
        0.3075, 0.2964, 0.3007 m^2 (P0). Here the two finer histories swap."""
        self.mode({"simpleFoam": {"by_cells": {"132094": "ladder/spheroid_L2.dat",
                                               "386302": "ladder/spheroid_L1.dat"}}})
        ((v, _calls),) = self.gates("aero.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("oscillatory convergence", v.detail)
        self.assertIsNone(v.measured)
        self.assertNotIn("band_top_m2", self.summary(v))

    def test_a_level_that_did_not_settle_fails(self):
        self.mode({"simpleFoam": {"residual_climb": 40}})
        ((v, _calls),) = self.gates("aero.mesh_independence")
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("level 0 (41574 cells) is not converged", v.detail)

    def test_above_the_formal_order_the_band_is_the_formal_orders(self):
        """Review of P6: the switch sat at formal + 0.05, so an observed order
        of 2.0 to 2.05 kept the observed order with Fs 1.25, the estimate Eca
        and Hoekstra 2014 drop above 2. Three drag areas on the baseline's
        cells, exactly phi0 + a h^p at p 2.03 and at 1.97."""
        from types import SimpleNamespace
        g = _module(self.registry)
        case = g["Case"](SPHEROID)
        cells = [41574, 132094, 386302]
        h = [(cells[-1] / n) ** (1.0 / 3.0) for n in cells]
        for p, rule, fs in ((2.03, "formal", 3.0), (1.97, "observed", 1.25)):
            with self.subTest(p):
                means = [0.0035 + 0.0002 * x ** p for x in h]
                settle = iter([{"why": [], "mean_m2": m, "u_i_m2": 1e-10, "u_i_pct": 1e-6}
                               for m in means])
                levels = [SimpleNamespace(k=k, cells=n, co=None, blocks=None,
                                          mesh=SimpleNamespace(problems=lambda _cap: []))
                          for k, n in enumerate(cells)]
                with mock.patch.dict(g, {"_settling": lambda *_a: next(settle)}):
                    j = g["_judge_ladder"](case, levels, 1.0, 20000000)
                self.assertEqual(j["why"], [])
                self.assertAlmostEqual(j["res"].p, p, places=6)
                self.assertEqual((j["rule"], j["fs"]), (rule, fs))
                lo, hi = (means[-1] * (1 + k * j["gci_pct"] / 100) for k in (-1, 1))
                self.assertTrue(lo <= j["phi_ext"] <= hi, (lo, j["phi_ext"], hi))

    def test_a_ladder_ratio_out_of_range_is_an_error(self):
        for r in (1.05, 2.5):
            with self.subTest(r):
                ((v, calls),) = self.gates("aero.mesh_independence",
                                           params={"aero_ladder_ratio": r})
                self.assertEqual(v.outcome, "error", v.render())
                self.assertNotIn("snappyHexMesh", calls)

    def test_layers_in_metres_fail(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/snappyHexMeshDict", "addLayersControls/relativeSizes", "false")
        ((v, calls),) = self.gates("aero.mesh_independence", params={"aero_case": case})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertIn("relativeSizes off", v.detail)
        self.assertFalse(calls)


class TheDragAreaIsJudgedAtTheTopOfItsBand(_LadderCase):
    """``aero.drag_area`` through the stand-in (invariant 4): the finest mesh's
    drag area plus its GCI band plus its iterative uncertainty, judged against
    the claim's limit, in m^2, the gate's own units."""

    def test_the_baseline_passes_at_the_top_of_its_band(self):
        ((v, calls),) = self.gates("aero.drag_area")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.units, v.comparator, v.limit), ("m^2", "<=", 0.0044))
        data = self.summary(v)
        top = data["cda_fine_m2"] * (1 + data["gci_fine_pct"] / 100) + data["u_i_fine_m2"]
        self.assertEqual(data["top_m2"], top)
        self.assertEqual(v.measured, float(f"{top:.9g}"))
        self.assertAlmostEqual(v.measured, 0.00421411818, places=11)
        self.assertAlmostEqual(data["force_n"], 0.5 * 1.225 * 20.0 ** 2 * data["cda_fine_m2"])
        self.assertEqual(calls.count("simpleFoam"), 3, "alone, it solves its own ladder")

    def test_every_pack_default_it_judges_on_is_said(self):
        """Review of P6: the ladder's marks and the iteration ceiling's were
        dropped here, while each guard said them."""
        for key in ("aero_ladder_ratio", "aero_iter_unc_max_pct"):
            with self.subTest(key):
                self.params = {k: v for k, v in _baseline().items() if k != key}
                ((v, _calls),) = self.gates("aero.drag_area")
                self.assertEqual(v.outcome, "pass", v.render())
                self.assertIn(f"[pack default: {key}]", v.detail)
                self.assertEqual(self.summary(v)["pack_default"], [key])
        self.params = _baseline()
        ((v, _calls),) = self.gates("aero.drag_area")
        self.assertNotIn("pack default", v.detail)
        self.assertEqual(self.summary(v)["pack_default"], [])

    def test_the_control_says_the_fixtures_scale(self):
        """Review of P6: the note said "15% larger ... about a third", the
        scale bad_cases.py measured and rejected."""
        bad = load_path(os.path.join(PACK, "selftest", "bad_cases.py"))
        note = self.registry.get("aero.drag_area")[0].negative_control.note
        self.assertIn(f"{100 * (bad.BODY_SCALE - 1):g}% larger", note)
        self.assertNotIn("15%", note)

    def test_a_bigger_body_lands_past_its_margin(self):
        case = _copy_case(os.path.join(self.tmp(), "case"))
        _edit(case, "system/snappyHexMeshDict", "geometry/spheroid/radius",
              "(0.5625 0.140625 0.140625)")
        ((v, _calls),) = self.gates("aero.drag_area", params={"aero_case": case})
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertGreaterEqual(v.measured, 1.15 * v.limit)

    def test_a_ladder_that_gives_no_band_here_is_an_error(self):
        self.mode({"simpleFoam": {"by_cells": {"132094": "ladder/spheroid_L2.dat",
                                               "386302": "ladder/spheroid_L1.dat"}}})
        ((v, _calls),) = self.gates("aero.drag_area")
        self.assertEqual(v.outcome, "error", v.render())
        self.assertIn("where aero.mesh_independence passed", v.error)


class ALadderRecordIsReadOnlyByItsProcess(_LadderCase):
    """Invariant 12's boundary re-executes the solve: aero.drag_area judges the
    ladder aero.mesh_independence solved in the same process (``_Record``),
    and never a record another process left, one whose bytes moved, or one of
    other inputs. Every check, export and selftest is a new process, so each
    solves its ladder at least once."""

    def test_behind_mesh_independence_it_judges_the_same_solves(self):
        (mi, _c1), (da, calls) = self.gates("aero.mesh_independence", "aero.drag_area")
        self.assertEqual((mi.outcome, da.outcome), ("pass", "pass"), da.render())
        self.assertNotIn("simpleFoam", calls)
        self.assertNotIn("snappyHexMesh", calls)
        self.assertEqual(self.summary(mi)["record"], self.summary(da)["record"])
        alone = self.gates("aero.drag_area")[0][0]
        self.assertEqual((alone.measured, alone.detail), (da.measured, da.detail))

    def test_a_record_of_another_process_or_another_byte_is_never_read(self):
        out = self.tmp()
        self.gates("aero.mesh_independence", out=out)
        ladder = os.path.join(out, "out", "aero-openfoam", "ladder")
        (record,) = os.listdir(ladder)
        manifest = os.path.join(ladder, record, "manifest.json")
        with open(manifest) as fh:
            data = json.load(fh)
        data["process"] = "0" * 64
        with open(manifest, "w") as fh:
            json.dump(data, fh)
        ((v, calls),) = self.gates("aero.drag_area", out=out)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual(calls.count("simpleFoam"), 3, "a planted record names no running process")
        coeff = os.path.join(ladder, record, "level2", "coefficient.dat")
        with open(coeff, "a") as fh:
            fh.write("\n")
        ((v, calls),) = self.gates("aero.drag_area", out=out)
        self.assertEqual(calls.count("simpleFoam"), 3, "a record whose bytes moved is not read")


    def test_another_input_byte_is_another_record(self):
        out = self.tmp()
        self.gates("aero.mesh_independence", out=out)
        ((v, calls),) = self.gates("aero.drag_area", params={"aero_ranks": 2}, out=out)
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual(calls.count("simpleFoam"), 3)


class TheDragGateStatesItsOwnUnits(_LadderCase):
    """Invariant 4: the claim restated in other units or as a lower limit is
    refused before any tool runs, never compared; the gate reports in m^2."""

    def setUp(self):
        super().setUp()
        self.edit = {}

    def claims(self):
        out = []
        for c in _claims():
            if c.id == "B1":
                for k, v in self.edit.items():
                    setattr(c.acceptance, k, v)
            out.append(c)
        return out

    def test_cm2_is_refused_before_any_mesh(self):
        from nopekit.models import Comparator
        for edit, said in (({"units": "cm^2", "limit": 44.0}, "states its limit in 'cm^2'"),
                           ({"comparator": Comparator(">=")}, "judges only an upper limit")):
            with self.subTest(edit):
                self.edit = edit
                ((v, calls),) = self.gates("aero.drag_area")
                self.assertEqual(v.outcome, "error", v.render())
                self.assertIn(said, v.error)
                self.assertEqual(calls, [])


class OnlyDragAreaReadsTheAcceptance(unittest.TestCase):
    """The design's rule since the review of P3-P5: one gate of the pack reads
    a claim's acceptance condition, the one that covers ``drag-area``."""

    def test_one_function_reads_it(self):
        import ast
        with open(os.path.join(PACK, "gates", "aero.py"), encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        readers = sorted({fn.name for fn in ast.walk(tree) if isinstance(fn, ast.FunctionDef)
                          for node in ast.walk(fn) if isinstance(node, ast.Attribute)
                          and node.attr in ("acceptance", "ledger")})
        self.assertEqual(readers, ["drag_area"])


class TheDragAreasGoalpostMovesNothingElse(_LadderCase):
    """Invariant 9's goalpost clause on aero.drag_area: its known-good control
    run again with B1's limit at x0.1, x0.5, x2 and x10 (``gates.goalpost_runs``,
    the qualification's own runs) reports the same value in the same units, and
    fails exactly where the moved limit is under it."""

    def test_the_four_moves(self):
        out = self.tmp()
        env = {"PATH": self.bin + os.pathsep + "/usr/bin:/bin"}
        spec, fn = self.registry.get("aero.drag_area")
        from nopekit import verdicts as verdicts_mod
        with mock.patch.dict(os.environ, env):
            ctx = gates_mod.GateContext(
                root=out, ledger=Ledger(meta=ProjectMeta(name="aero"), claims=_claims()),
                params=dict(self.params), out_dir=os.path.join(out, "out"), tier=2,
                log=lambda _m: None, extra={})
            trace = verdicts_mod.GateTrace(kind="control")
            good = gates_mod.run_gate(spec, fn, ctx, trace=trace)
            self.assertEqual(good.outcome, "pass", good.render())
            gates_mod.note_goalpost_sites(trace, trace, ctx.params, good)
            (runs,) = gates_mod.goalpost_runs(spec, fn, ctx, good, trace=trace)
        self.assertEqual((runs.measured, runs.units), (good.measured, "m^2"))
        got = {r.limit: (r.outcome, r.measured, r.units) for r in runs.runs}
        self.assertEqual(sorted(got), sorted(0.0044 * f for f in (0.1, 0.5, 2.0, 10.0)))
        for limit, (outcome, measured, units) in got.items():
            self.assertEqual((measured, units), (good.measured, "m^2"))
            self.assertEqual(outcome, "pass" if limit > good.measured else "fail", limit)


# --------------------------------------------------------------------------- #
# the real OpenFOAM
# --------------------------------------------------------------------------- #
def _real_install():
    try:
        return T.locate()
    except T.Unavailable:
        return None


def expanded_motorbike(inst, dst: str) -> str:
    """The v2606 motorBike tutorial as references/motorbike.md says a project
    builds it: every file through ``foamDictionary -expand``, the
    controlDict's functions removed, the one allowed include put back first in
    each 0/ file's boundaryField."""
    src = os.path.join(inst.root, "tutorials", "incompressible", "simpleFoam", "motorBike")
    work = os.path.join(dst, "work")
    shutil.copytree(src, work)
    shutil.copytree(os.path.join(work, "0.orig"), os.path.join(work, "0"))
    inc = '#includeEtc "caseDicts/setConstraintTypes"'
    for f in ("U", "p", "k", "omega", "nut"):
        path = os.path.join(work, "0", f)
        with open(path) as fh:
            text = fh.read().replace(inc, "")
        with open(path, "w") as fh:
            fh.write(text)
    env = T.environment(inst, T.home(dst, inst.api, "aero-openfoam"))
    case = os.path.join(dst, "case")
    for rel in ("0/U", "0/p", "0/k", "0/omega", "0/nut", "system/controlDict",
                "system/fvSchemes", "system/fvSolution", "system/blockMeshDict",
                "system/snappyHexMeshDict", "system/surfaceFeatureExtractDict",
                "constant/transportProperties", "constant/turbulenceProperties"):
        run = T.run(env, work, ["foamDictionary", "-expand", rel], 120, banner=False,
                    log=f"log.expand.{rel.replace('/', '_')}")
        text = run.stdout
        if rel == "system/controlDict":
            text = F.remove_entries(text, "functions")
        if rel.startswith("0/"):
            text = re.sub(r"(boundaryField\s*\{\n)", r"\1    " + inc + "\n", text, count=1)
        os.makedirs(os.path.join(case, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(case, rel), "w") as fh:
            fh.write(text)
    return case


@unittest.skipIf(_real_install() is None, "ESI OpenFOAM v2606 is not installed: not walked")
class TheRealAeroGates(_env.EnvCase):
    """On the real v2606, where it is installed: the motorBike tutorial, read
    as a project would state it, and its domain measured by surfaceCheck."""

    def setUp(self):
        self.registry = _registry()
        self.inst = _real_install()
        geometry = os.path.join(self.inst.root, "tutorials", "resources", "geometry",
                                "motorBike.obj.gz")
        if not os.path.isfile(geometry):
            self.skipTest("the install has no motorBike.obj.gz: not walked")
        self.case = expanded_motorbike(self.inst, self.tmp())
        self.params = {"aero_case": self.case,
                       "aero_geometry": "$FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz",
                       "aero_geometry_sha256": MOTORBIKE_SHA256,
                       "aero_u_inf_m_s": 20.0, "aero_ref_length_m": 1.42,
                       "aero_sound_speed_m_s": 343.0, "aero_body_group": "motorBikeGroup"}

    def test_the_expanded_tutorial_reads_and_its_domain_fails_four_distances(self):
        for gid in ("aero.case_readable", "aero.reference", "aero.regime"):
            v = _run(self.registry, gid, self.tmp(), self.params, tier=1)
            self.assertEqual(v.outcome, "pass", f"{gid}: {v.render()}")
        self.assertIn("the body runs 2.04282 m along the flow", v.detail)
        v = _run(self.registry, "aero.regime", self.tmp(),
                 dict(self.params, aero_ref_length_m=2.1), tier=1)
        self.assertEqual((v.outcome, v.units), ("fail", "m"), v.render())
        v = _run(self.registry, "aero.domain", self.tmp(), self.params, tier=1)
        self.assertEqual(v.outcome, "fail", v.render())
        for said in ("upstream 3.48 H", "downstream 9.8 H", "side 2.7 H", "top 4.92 H"):
            self.assertIn(said, v.detail)
        self.assertEqual((v.measured, v.units), (2.70044912, "H"))


if __name__ == "__main__":
    unittest.main()
