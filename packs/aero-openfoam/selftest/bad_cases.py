# SPDX-License-Identifier: Apache-2.0
"""Known-bad fixtures for aero-openfoam. One change each, to the baseline
spheroid or to what the project states about it.

`nopekit gate selftest` requires every gate to FAIL here. A gate that passes its
own fixture is broken, and a green verdict from it means nothing.

**Sealed.** Every fixture starts from this pack's own ``selftest/baseline.json``
and ``selftest/assets/spheroid``, never from the host's projection or case, and
hands the gate a ledger of the baseline's own claims (``_claims``) and nothing
of the host's: cfd-openfoam's rule, for its reason (a control whose severity
depends on the host fires in some projects and not in others). Built with
``Claim.from_dict``, never ``nopekit.packs``: cfd-openfoam found that import
loading the gate module twice into one registry.

**One edit, made with the pack's own writer.** Each bad case is the baseline
case copied under the CALLER's ``out_dir``
(``<out_dir>/aero-openfoam/known-bad/<fixture>/``) with one dictionary entry
changed by ``_foam.set_entry``, which keeps every other byte and raises when the
entry is not there; or one parameter changed. Never into this directory.

**Each is passed by the guards before its gate**, or its gate would read
Skipped, never Failing: ``wrong_speed``, ``thick_air`` and ``short_wake`` stay
readable, and ``cell_cap`` is a readable case.

**Where each lands** was measured in P0 (2026-10-23, OpenFOAM v2606) and is
derived here from the gate's own limit and the baseline's own numbers, so
moving either cannot quietly turn a control into a pass: each lands 15% past
its limit (``MARGIN``).
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
A = load_path(os.path.join(_PACK_DIR, "gates", "aero.py"))

#: How far past its limit a control lands: 15%, the margin the mutation pass
#: uses, so the control does not sit on the rounding of the verdict.
MARGIN = 1.15

#: The cell cap ``cell_cap`` states: 20 000, under half the 41 574 cells the
#: baseline meshes to. Measured (P0, 8 ranks): snappyHexMesh prints "No cells
#: marked for refinement since reached limit 20000." three times, ends at 27 429
#: cells with layers on 39% of the body, and still says "Finished meshing
#: without any errors". Rejected: P0's ``relaxed_quality`` (``maxNonOrtho
#: 180``) and relaxing all ten quality controls: the smooth spheroid snaps with
#: 0 faces in error either way, so neither fails; and the pack owns the quality
#: controls, so a case edit to them is overwritten.
CELL_CAP = 20000


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
    params["aero_case"] = os.path.join(_PACK_DIR, str(params["aero_case"]))
    return params


def _variant(ctx, name: str, edits: dict | None = None, params_edit=None):
    """A context whose case is the baseline's with ``edits`` (``{relative file:
    [(entry path, new value)]}``) applied, and whose parameters are the
    baseline's with ``params_edit(params)`` applied."""
    params = _baseline()
    src = params["aero_case"]
    marker = ctx.out_path("aero-openfoam", "known-bad", name, ".case")
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
    params["aero_case"] = dst
    if params_edit is not None:
        params_edit(params)
    return dataclasses.replace(ctx, params=params, ledger=Ledger(claims=_claims()))


def _case():
    return A.Case(_baseline()["aero_case"])


def coded_inlet(ctx):
    """aero.case_readable — the inlet velocity written as a codedFixedValue.

    A coded boundary condition is C++ the case compiles and runs inside the
    solver: it can set any value anywhere. The pack cannot read what it does, so
    the guard refuses the case rather than vouch for a number it shaped."""
    return _variant(ctx, "coded_inlet", {"0/U": [
        ("boundaryField/inlet",
         "type codedFixedValue; value uniform (20 0 0); name uniformInlet; "
         "code #{ operator==(vector(20, 0, 0)); #};")]})


def wrong_speed(ctx):
    """aero.reference — the inlet 15% faster than ``aero_u_inf_m_s`` (23 m/s
    against 20).

    forceCoeffs makes the drag dimensionless by the stated speed, so every
    coefficient would be 1.15^2 = 1.32 times too large, and the regime judged on
    a flow that is not the one run."""
    u = _baseline()["aero_u_inf_m_s"] * MARGIN
    return _variant(ctx, "wrong_speed", {"0/U": [
        ("boundaryField/inlet", f"type fixedValue; value uniform ({u!r} 0 0);")]})


def thick_air(ctx):
    """aero.regime — the air made viscous enough that Re = U L / nu is 15%
    below 5e5 (nu 4.6e-5 m^2/s against the baseline's 1.5e-5: Re 4.35e5).

    k-omega SST without a transition model would make the spheroid's laminar
    layers turbulent. Derived from the gate's own limit and the baseline's own
    speed and length."""
    b = _baseline()
    nu = b["aero_u_inf_m_s"] * b["aero_ref_length_m"] * MARGIN / A.RE_MIN
    return _variant(ctx, "thick_air", {"constant/transportProperties": [("nu", repr(nu))]})


def short_wake(ctx):
    """aero.domain — the outlet moved upstream until the domain behind the body
    is 15 H / 1.15 (6.85 m of H 0.525 m, the outlet at x 7.85 m against the
    baseline's 10 m, 17.1 H).

    Franke et al. 2007 ask for 15 H: a shorter wake meets the outlet's fixed
    pressure while the flow is still recovering. Every other distance is kept,
    so the outlet is the one measure that fails. Derived from the gate's own
    limit and the baseline's own body."""
    case = _case()
    (x0, y0, z0), (_x1, y1, z1) = case.box
    body = case.body_box()
    rows, h = A.domain_measures(case.box, body, case.ground())
    x1 = body[1][0] + A.DOWNSTREAM_MIN_H * h / MARGIN
    verts = " ".join(f"({x:.12g} {y:g} {z:g})" for z in (z0, z1)
                     for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    return _variant(ctx, "short_wake", {"system/blockMeshDict": [("vertices", f"( {verts} )")]})


def cell_cap(ctx):
    """aero.mesh_quality — ``aero_max_global_cells`` at 20 000 (``CELL_CAP``),
    under half the baseline's mesh.

    snappyHexMesh stops refining at the cap and still prints "Finished meshing
    without any errors": the mesh it wrote is not the one its dictionary asks
    for. A parameter, not a case edit: the pack owns the cap."""
    def edit(params):
        params["aero_max_global_cells"] = CELL_CAP
    return _variant(ctx, "cell_cap", params_edit=edit)


def cut_short(ctx):
    """aero.converged — endTime 110: the window of the last 100 iterations
    (iterations 11 to 110) closes inside the start-up.

    Measured: U_I 11.1% of the drag area at 110 (P0 on 8 ranks, and P4 on the
    baseline's 4 with the pack's decomposition), at least 1.15% at every end up
    to 131 (P0); the baseline's 300 reads 0.0148% (P4).
    The run exits 0 and prints End: only the history can refuse it. The case
    reads, meshes and is the stated flow, so every guard before it passes."""
    return _variant(ctx, "cut_short", {"system/controlDict": [("endTime", "110")]})


def no_layers(ctx):
    """aero.wall_treatment — ``addLayers false``: the spheroid meshed without
    its two layers, so the first cell off the body is a snapped surface cell.

    Measured (P0, 8 ranks): y+ at most 300 on 35.6% of the body's area, against
    the baseline's 100% and the limit's 90% (15% past it is 78.3%). The mesh
    passes aero.mesh_quality and the run settles (aero.converged): the wall is
    the one thing wrong."""
    return _variant(ctx, "no_layers", {"system/snappyHexMeshDict": [("addLayers", "false")]})


#: The ladder ratio ``narrow_ladder`` states: 1.3, Celik's floor for the
#: effective ratio, which the meshes then miss: snappyHexMesh refines the
#: background cells by whole levels, so the surface and wake cells of two
#: levels 1.3 apart in the block are less than 1.3 apart in count^(1/3). P0
#: measured 1.249 and 1.293 on its box; the spheroid's are in
#: references/selftest.md. Rejected: P0's ``coarse`` (a halved block): it is
#: a ladder the gate would solve, three solves for a control.
NARROW_RATIO = 1.3


def narrow_ladder(ctx):
    """aero.mesh_independence — ``aero_ladder_ratio`` 1.3 (``NARROW_RATIO``):
    three meshes whose effective refinement ratios, from their cells, fall
    under Celik's 1.3. The gate judges them after meshing and before any
    solve, so the control costs three meshes and no solve. A parameter, not a
    case edit: the ladder is the pack's."""
    def edit(params):
        params["aero_ladder_ratio"] = NARROW_RATIO
    return _variant(ctx, "narrow_ladder", params_edit=edit)


#: How much larger ``bigger_body`` makes the spheroid: every radius 1.125
#: times (exact in binary), its centre where it was. Measured (P6, 4 ranks, the
#: whole ladder): the top of its band 0.00529625 m^2 against the baseline's
#: 0.00421412, 1.257 times; B1's limit 0.0044 sits 4.4% over the baseline's
#: top, and the control lands 1.204 times past it. Rejected: 1.15 (the
#: design's, after P0's L0 alone: on the finest mesh the drag area cycles with
#: U_I 0.53%, past a tenth of the change between the two finest meshes, so
#: aero.mesh_independence fails it and the control never reaches this gate;
#: thickening only the cross-section by 1.15 cycled at 1.18%); 1.1 (P0's: the
#: top 1.182 times the baseline's, a window of 2.8% between the baseline's top
#: and 15% under the control's); a smaller ``aero_u_inf_m_s`` (forceCoeffs
#: would make the same flow dimensionless by another speed: aero.reference's
#: control, not a larger drag).
BODY_SCALE = 1.125


def bigger_body(ctx):
    """aero.drag_area — the spheroid's three radii times 1.125
    (``BODY_SCALE``), its centre where it was: the same shape with 27% more
    frontal area. Its drag area at the top of its band lands 20% past the
    baseline's limit (B1), measured; every guard before it passes (it is
    1.125 m long, still longer than ``aero_ref_length_m``; its domain still
    meets Franke et al. 2007; its y+ and its ladder pass, references/selftest.md)."""
    radii = A.Case(_baseline()["aero_case"]).geometry["spheroid"][1]
    lo, hi = radii
    r = tuple(0.5 * (hi[k] - lo[k]) * BODY_SCALE for k in range(3))
    return _variant(ctx, "bigger_body", {"system/snappyHexMeshDict": [
        ("geometry/spheroid/radius", f"({r[0]!r} {r[1]!r} {r[2]!r})")]})
