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

    def test_a_fast_stream_fails_on_mach(self):
        v = _run(self.registry, "aero.regime", self.tmp(),
                 dict(_baseline(), aero_sound_speed_m_s=60.0), tier=0)
        self.assertEqual(v.outcome, "fail", v.render())
        self.assertEqual((v.units, v.comparator), ("Mach", "<"))
        self.assertGreaterEqual(v.measured, 0.3)


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


@unittest.skipIf(os.name == "nt", "the stand-in OpenFOAM is a #! script and a bash rc")
class _StandinCase(_env.EnvCase):
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


class AMeshIsJudgedByThePacksLimits(_StandinCase):
    """``aero.mesh_quality`` through the stand-in: what the real tools printed on
    the baseline, and each way a finished-looking mesh is not."""

    def test_the_baseline_passes_at_its_cell_count(self):
        v = self.gate("aero.mesh_quality")
        self.assertEqual(v.outcome, "pass", v.render())
        self.assertEqual((v.measured, v.units, v.comparator, v.limit),
                         (41546.0, "cells", "<", 2e7))
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
    env = T.environment(inst, T.home(dst, inst.api))
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
            v = _run(self.registry, gid, self.tmp(), self.params, tier=0)
            self.assertEqual(v.outcome, "pass", f"{gid}: {v.render()}")
        v = _run(self.registry, "aero.domain", self.tmp(), self.params, tier=1)
        self.assertEqual(v.outcome, "fail", v.render())
        for said in ("upstream 3.48 H", "downstream 9.8 H", "side 2.7 H", "top 4.92 H"):
            self.assertIn(said, v.detail)
        self.assertEqual((v.measured, v.units), (2.70044912, "H"))


if __name__ == "__main__":
    unittest.main()
