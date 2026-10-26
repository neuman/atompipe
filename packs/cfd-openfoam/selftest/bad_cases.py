# SPDX-License-Identifier: Apache-2.0
"""Known-bad fixtures for cfd-openfoam. One change each, to the baseline
channel or to what the project states about it.

`nopekit gate selftest` requires every gate to FAIL here. A gate that passes its
own fixture is broken, and a green verdict from it means nothing.

**Sealed.** Every fixture starts from this pack's own ``selftest/baseline.json``
and ``selftest/assets/channel``, never from the host's projection or the host's
case, and hands the gate a ledger of the baseline's own claims (``_claims``, the
ones the known-good control reads) and nothing of the host's. A control whose
severity depended on the host's case, or on the host's limit, would fire in
some projects and not in others. Built with ``Claim.from_dict``, as a project's
``selftest/known_good.py`` builds its ``CLAIMS``. What slipped through with
``from nopekit.packs import baseline_claims`` here: ``tests/test_packs.py``,
run whole, loaded this file again and ran ``cfd.py`` again into a registry
that held it (``gate id 'cfd.case_readable' is already registered``), and
every control of the pack errored; each class alone passed. ``pack validate``
checks ``_claims`` with ``packs.baseline_claims``.

**One edit, made with the pack's own writer.** Each bad case is the baseline
case copied under the CALLER's ``out_dir``
(``<out_dir>/cfd-openfoam/known-bad/<fixture>/``) with one dictionary entry
changed by ``_foam.set_entry``, which keeps every other byte, and raises when the
entry is not there: a fixture that edits nothing is not a control. Never into
this directory: a fixture that writes into the pack it is proving makes the proof
depend on whether the pack is writable.

**Each is passed by the guards before its gate.** A known-bad control proves a
gate fails only when the gate runs; one its prerequisite refused would read
Skipped, never Failing. So ``cut_short`` meshes cleanly, ``coarse`` converges,
and ``thicker_fluid`` is laminar, converged and mesh-independent.
"""
from __future__ import annotations

import dataclasses
import json
import os
import shutil

from nopekit.modelio import load_path
from nopekit.models import Claim, Ledger

_PACK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASELINE_PATH = os.path.join(_PACK_DIR, "selftest", "baseline.json")
F = load_path(os.path.join(_PACK_DIR, "gates", "_foam.py"))
C = load_path(os.path.join(_PACK_DIR, "gates", "cfd.py"))

#: How far past its limit a control lands: 15%, the margin the mutation pass
#: uses, so the control does not sit on the rounding of the verdict.
MARGIN = 1.15


def _read() -> dict:
    with open(_BASELINE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def _claims() -> list:
    """The claims the baseline states, fresh each call."""
    return [Claim.from_dict(row) for row in _read().get("_claims") or ()]


def _baseline() -> dict:
    """The baseline projection, documentation keys stripped and the case path
    made absolute against this pack."""
    params = {k: v for k, v in _read().items() if not k.startswith("_")}
    params["cfd_case"] = os.path.join(_PACK_DIR, str(params["cfd_case"]))
    return params


def _variant(ctx, name: str, edits: dict | None = None, params_edit=None):
    """A context whose case is the baseline's with ``edits`` (``{relative file:
    [(entry path, new value)]}``) applied, and whose parameters are the
    baseline's with ``params_edit(params)`` applied."""
    params = _baseline()
    src = params["cfd_case"]
    marker = ctx.out_path("cfd-openfoam", "known-bad", name, ".case")
    dst = os.path.join(os.path.dirname(marker), "case")
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for rel, changes in (edits or {}).items():
        path = os.path.join(dst, *rel.split("/"))
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        for entry, value in changes:
            text = F.set_entry(text, entry, value)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    params["cfd_case"] = dst
    if params_edit is not None:
        params_edit(params)
    return dataclasses.replace(ctx, params=params,
                               ledger=Ledger(claims=_claims()))


def coded_inlet(ctx):
    """cfd.case_readable — the inlet velocity written as a codedFixedValue.

    A coded boundary condition is C++ the case compiles and runs inside the
    solver: it can set any value anywhere. The pack cannot read what it does, so
    the guard refuses the case rather than vouch for a number it shaped."""
    return _variant(ctx, "coded_inlet", {"0/U": [
        ("boundaryField/inlet",
         "type codedFixedValue; value uniform (0.01 0 0); name uniformInlet; "
         "code #{ operator==(vector(0.01, 0, 0)); #};")]})


def fast_flow(ctx):
    """cfd.regime — the channel stated at a mean velocity whose Reynolds number
    is 15% past 2300.

    Derived from the gate's own limit and the baseline's own length and
    viscosity, so moving either cannot quietly turn the control into a pass."""
    nu = F.scalar(F.read(os.path.join(_baseline()["cfd_case"], "constant",
                                      "transportProperties")), "nu")

    def edit(params):
        params["cfd_velocity_m_s"] = C.RE_LAMINAR_MAX * MARGIN * nu / params["cfd_length_m"]
    return _variant(ctx, "fast_flow", params_edit=edit)


def sheared(ctx):
    """cfd.mesh_quality — the top wall slid 40 mm downstream, four channel heights.

    Every cell is a parallelogram at atan(4) = 76.0 degrees of
    non-orthogonality: past the 65-degree limit by 17%, and inside checkMesh's
    own 90, so checkMesh still prints ``Mesh OK.``. The gate must fail on the
    limit, not on checkMesh's word."""
    return _variant(ctx, "sheared", {"system/blockMeshDict": [
        ("vertices",
         "( (0 0 0) (0.1 0 0) (0.04 0.01 0) (0.14 0.01 0) "
         "(0 0 0.001) (0.1 0 0.001) (0.04 0.01 0.001) (0.14 0.01 0.001) )")]})


def cut_short(ctx):
    """cfd.converged — endTime 5: simpleFoam stops at iteration 5 and exits 0.

    Its pressure drop reads 0.69% high, and stopped at iteration 10 it reads
    0.001% low: the number cannot tell a converged run from a cut one. The log
    can."""
    return _variant(ctx, "cut_short", {"system/controlDict": [("endTime", "5")]})


def coarse(ctx):
    """cfd.mesh_independence — the channel started on 10 x 2 cells, one cell from
    the wall to the middle. Each level converges; the pressure drop is still
    moving with the mesh."""
    return _variant(ctx, "coarse", {"system/blockMeshDict": [
        ("blocks", "( hex (0 1 3 2 4 5 7 6) (10 2 1) simpleGrading (1 1 1) )")]})


def thicker_fluid(ctx):
    """cfd.pressure_drop — a fluid twice as viscous, 20 cSt. A laminar pressure
    drop is proportional to viscosity: 0.522 Pa becomes 1.04 Pa, past the 0.6 Pa
    limit of the baseline's own claim. Still laminar (Re 10), still converged,
    still mesh-independent."""
    return _variant(ctx, "thicker_fluid", {"constant/transportProperties": [("nu", "2e-05")]})
