# SPDX-License-Identifier: Apache-2.0
"""aero-openfoam — gates for the drag of a body in an open stream, solved by
ESI OpenFOAM (openfoam.com) with snappyHexMesh, simpleFoam and k-omega SST.

    aero.case_readable  tier 0  the case is one this pack can run and vouch for (the guard)
    aero.reference      tier 0  the run is the stated flow: inlet speed, +x, the body a still wall
    aero.regime         tier 1  turbulent wall layers and incompressible: Reynolds and Mach numbers
    aero.domain         tier 1  the domain is large enough: Franke et al. 2007, Blocken 2015
    aero.mesh_quality   tier 1  snappyHexMesh, then checkMesh -meshQuality against the pack's limits
    aero.converged      tier 2  the base mesh solved: the drag area's iterative uncertainty (ITTC)
    aero.wall_treatment tier 2  y+ at most 300 on at least 90% of the body's area
    aero.mesh_independence tier 2  three meshes: Celik's GCI, the pack's order rule
    aero.drag_area      tier 2  the top of the finest mesh's band against the claim's limit

**The guards come first.** A drag number from a domain that squeezes the
flow, a mesh with folded faces or an air speed nobody stated is the standard
way to make an assumption look like proof. Each guard covers its own tag only,
never ``drag-area``: a guard judges its own quantity (Re, H, faces, %), not a
drag area, so a pass of every guard says nothing about a drag-area limit. What
slipped through P3-P5 (review, 2026-10-23): every guard covered ``drag-area``
before ``aero.drag_area`` existed, so the baseline's B1 (``<= 0.0042 m^2``)
read Checked at a measured 0.00443 m^2, its limit read by no evaluator. Only
``aero.drag_area`` covers ``drag-area`` and reads its limit; the guards reach a
drag-area claim as its prerequisites (``needs``).

**Where each verdict comes from.** The tier-0 gates read the case with the
pack's own dictionary reader (``_foam.py``), so they run where OpenFOAM is not
installed and every file they decide on is keyed. ``aero.domain`` reads the
blockMeshDict and the body's bounds (OpenFOAM's ``surfaceCheck`` for a surface
file; the dictionary for a sphere or a box), and ``aero.regime`` holds the
stated reference length to the same bounds. ``aero.mesh_quality`` is OpenFOAM's
own output on a staged copy: snappyHexMesh's log and ``checkMesh
-meshQuality``'s count of faces in error against the PACK's quality limits
(``_fo.QUALITY``), which snappyHexMesh also meshed to. Both run in a subprocess
the trace cannot see into, so they are opaque and re-run on every check where
OpenFOAM exists.

**What slipped through, and which gate it is for** (P0, 2026-10-23, on v2606):

- ``aero.mesh_quality``: plain checkMesh fails every motorBike mesh ("Failed 1
  mesh checks": skewness 8.13 against its fixed 4) and passes the tutorial's own
  meshes against the tutorial's own relaxed ``minFaceWeight 0.02``; with the
  etc dict's 0.05, 1 095 faces of the L0 mesh are in error. So the pack writes
  one set of limits for the mesher and the judge, and plain checkMesh's verdict
  line is never read.
- ``aero.mesh_quality``: a smooth body snaps cleanly whatever the limits
  (``maxNonOrtho 180`` and every control relaxed gave 0 faces in error on the
  spheroid), while a mesher that ran out of cells still printed "Finished
  meshing without any errors". The cell cap is read from its own line.
- ``aero.domain``: the motorBike tutorial's own domain fails every distance the
  sources set (upstream 3.5 H against 5 H, downstream 9.8 H against 15 H, sides
  2.7 H against 5 H); its blockage passes. The demo's domain grows, never the
  limit.
- every parallel tool: a rank with another HOME left the master's banner
  saying "Disallowing" and hung. See ``_par.rank_probe``.

**Missing inputs skip; they never default**, except the settings marked
``[pack default]`` in a verdict. Which case, which body, how fast, how long and
which surface file are the project's to say.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess

from nopekit.gates import gate, GateContext
from nopekit.modelio import load_path as _load_path
from nopekit.models import NegativeControl, Tier, Verdict

_HERE = os.path.dirname(os.path.abspath(__file__))
F = _load_path(os.path.join(_HERE, "_foam.py"))
T = _load_path(os.path.join(_HERE, "_tool.py"))
P = _load_path(os.path.join(_HERE, "_par.py"))
FO = _load_path(os.path.join(_HERE, "_fo.py"))
G = _load_path(os.path.join(_HERE, "_gci.py"))

PACK = "aero-openfoam"

#: The tag of the claim aero.drag_area will read its limit from
#: (``ctx.acceptance``): the drag area, CdA in m^2. No guard covers it: each
#: covers its own quantity's tag, and a guard's pass beside a drag-area claim
#: would be a Checked row whose limit no evaluator read (invariant 4; the
#: module docstring says what slipped through). Rejected: every gate covering
#: it (the design's first rule, safe only once aero.drag_area judges the
#: limit, and even then a guard reaches the claim through ``needs``); broad
#: tags (``cfd``, ``aerodynamics``): cfd-openfoam's review of issue #15 D2
#: found a claim tagged only broadly reading Checked on a pass judged against
#: another claim's limit.
DRAG_TAG = "drag-area"
#: The tag of each guard, its own quantity's. ``aero.case_readable`` has one
#: too, so no gate here covers nothing.
GUARD_TAGS = {"aero.case_readable": "case-readable", "aero.reference": "flow-reference",
              "aero.regime": "flow-regime", "aero.domain": "domain-size",
              "aero.mesh_quality": "mesh-quality", "aero.converged": "convergence",
              "aero.wall_treatment": "wall-treatment",
              "aero.mesh_independence": "mesh-independence"}

#: The solver this pack runs: steady, incompressible, isothermal. Rejected for
#: now: pimpleFoam (a transient run's mean drag needs a sampling window and a
#: statistical uncertainty this pack does not compute); the compressible
#: solvers (Mach is guarded below 0.3 instead).
APPLICATIONS = ("simpleFoam",)

#: The turbulence model this pack vouches for: k-omega SST (Menter 1994), RAS,
#: the motorBike tutorial's. Its wall treatment and y+ band are what
#: aero.wall_treatment judges, and its validity range is what aero.regime
#: guards. Rejected for now: every other RAS model (each needs its own y+ band
#: and its own Reynolds-number range); LES and DES (transient).
RAS_MODELS = ("kOmegaSST",)

#: The lowest Reynolds number, on the body's reference length, at which the
#: pack runs a fully turbulent model: 5e5, the textbook transition Reynolds
#: number of a flat plate (Schlichting & Gersten, Boundary-Layer Theory, 9th
#: ed. 2017, sec. 15.2: Re_x,crit about 5e5). k-omega SST as run here has no
#: transition model, so below it the model makes laminar layers turbulent and
#: the drag is wrong in sign of error unknown. Rejected: 1e5 (the lower end of
#: transition in a disturbed stream; a laminar body there is common); 3e6 (the
#: flat-plate value for a quiet stream; it refuses a cyclist at 10 m/s, which
#: the pack is for).
RE_MIN = 5e5

#: The Mach number below which density changes stay under about 5% (rho0/rho =
#: (1 + 0.2 Ma^2)^2.5 gives 4.5% at 0.3): the textbook limit for an
#: incompressible solver, as cfd-openfoam's ``MACH_MAX``. Rejected: 0.2
#: (stricter than any CFD guide asks).
MACH_MAX = 0.3

#: The units each guard reports its value in, by its own symbol, as
#: cfd-openfoam's guards do (issue #15, D3): the number a person checks
#: against a textbook, never a fraction of a limit.
RE_UNITS, MACH_UNITS, LENGTH_UNITS = "Re", "Mach", "m"
#: How much longer than the body along the flow ``aero_ref_length_m`` may be:
#: one part in 1e9, the reader's and surfaceCheck's rounding (the spheroid's
#: 1 m is 0.5 + 0.5). Rejected: any real slack (a length the body does not have
#: is the hole this closes).
LENGTH_SLACK = 1e-9
H_UNITS, PCT = "H", "%"
FACE_UNITS, CELL_UNITS = "faces", "cells"

# --------------------------------------------------------------------------- #
# the domain's limits (D4, sources quoted in references/domain.md)
# --------------------------------------------------------------------------- #
#: Distances from the body to the domain's boundaries, in H, the height of the
#: body's top above the ground. Franke et al. 2007 (COST Action 732 best
#: practice guideline, as quoted by Blocken 2015, Building and Environment
#: 91:219-245, sec. 5.1): "The inlet, lateral and top boundary should be at
#: least 5H_max away from the group of explicitly modeled buildings ... The
#: outflow boundary should be at least 15H_max away". Rejected: D4's draft in
#: body lengths (3 L upstream, 6 L downstream: the sources state H_max);
#: Tominaga et al. 2008's (AIJ) 10 H downstream (looser than Franke's; the pack
#: takes the stricter of two guidelines it cannot choose between).
UPSTREAM_MIN_H = 5.0
DOWNSTREAM_MIN_H = 15.0
SIDE_MIN_H = 5.0
TOP_MIN_H = 5.0

#: The blockage ratio, the body's frontal area over the domain's cross-section:
#: at most 3% (Franke et al. 2007; Tominaga et al. 2008 the same). The frontal
#: area is the body box's (width x height), an upper bound of the true one
#: (P0: the motorBike's rasterised frontal area 0.644 m^2 against its box's
#: 0.92 m^2), so a pass here is a pass on the true area. Rejected: rasterising
#: the surface (arithmetic on geometry no OpenFOAM tool reports).
BLOCKAGE_MAX_PCT = 3.0

#: The directional blockage ratios, Blocken 2015 sec. 5.1: the body's width
#: over the domain's, and its height over the domain's, each at most 17% ("the
#: square root of 3%"), applied with the distances above. Measured (P0): the
#: tutorial's BR_H 16.9%, passing by 0.6%.
DIRECTIONAL_MAX_PCT = 17.0

#: How far a body may reach below a ground wall and still count as resting on
#: it, as a fraction of H: 1%. The motorBike's tyres reach 4.2e-5 m under its
#: ground (3e-5 H; surfaceCheck, P0): the contact patch snappyHexMesh cuts off.
#: Rejected: none (the tutorial's own body would read as outside its domain);
#: any depth (a body sunk into the floor is another body than the one stated).
GROUND_CONTACT = 0.01

# --------------------------------------------------------------------------- #
# settings a project may state
# --------------------------------------------------------------------------- #
#: One hour per tool run. The motorBike's L2 solve, the costliest run of the
#: ladder, took 94 min on 8 ranks (P0), so a project running its own ladder
#: states more. A timeout is a skip (nothing was shown), never a fail.
DEFAULT_TIMEOUT_S = 3600.0

#: Ranks per parallel run: 8. P0 measured 7 physical cores on the machine the
#: pack was written on and ran 8 with ``--oversubscribe``; rank count moves the
#: converged CdA by about 1e-6 of itself (snappy's decomposition). Rejected: 12
#: (the tutorial's; Open MPI refuses it without ``--oversubscribe`` on 7 cores);
#: the machine's core count read at run time (a verdict keyed on the machine).
DEFAULT_RANKS = 8
#: The most ranks a run may ask for: 64, about nine times the machine P0 ran
#: on. Past it a run is either a cluster this pack has never run on or a
#: mistyped count that oversubscribes one host until the timeout. Rejected:
#: 256 (P3's first value: test_mutation's walk pushes aero_ranks up its ladder,
#: x30 and x100, and each such run would oversubscribe one host for minutes).
RANKS_MAX = 64

#: The cell cap snappyHexMesh may refine to (``maxGlobalCells``): 2e7, ten
#: times the motorBike tutorial's 2e6, so the design's L2 mesh (2 618 934 cells,
#: P0) is not capped. The pack writes it into the staged snappyHexMeshDict, so a
#: case cannot raise it and the verdict says which cap the mesh met. A mesh that
#: reached its cap is not the mesh its dictionary asks for, and fails (P0: the
#: spheroid capped at 20 000 cells lost layers on 60% of its surface).
#: Rejected: the tutorial's 2e6 (it caps the motorBike's L2).
DEFAULT_MAX_GLOBAL_CELLS = 20_000_000

#: ``maxLocalCells``, which the pack writes and no project states: not a cap.
#: snappyHexMesh's own comment (v2606 tutorial): "If local number of cells is
#: >= maxLocalCells on any processor switches from refinement followed by
#: balancing ... to (weighted) balancing before refinement." Measured (P3): the
#: spheroid at 2 000 meshes to the same 41 574 cells as at 2e6. 2e6 (the
#: design's) keeps the first path for every mesh the pack has run. Rejected:
#: the tutorial's 100 000 (the motorBike's L2 passes it on 8 ranks: the order of
#: refinement and balancing would change between ladder levels); a parameter,
#: ``aero_max_local_cells`` (P3's: a key no judgment needs, and each key a
#: verdict reads is a rung of test_mutation's walk, a full solve each in
#: aero.converged).
MAX_LOCAL_CELLS = 2_000_000


def _skip(gid: str, reason: str) -> Verdict:
    return Verdict(gate=gid, passed=False, skipped=True, skip_reason=reason)


def _error(gid: str, message: str, evidence=None) -> Verdict:
    return Verdict(gate=gid, passed=False, error=message, evidence=list(evidence or []))


_NO_CASE = ("no aero_case: the OpenFOAM case directory this pack runs, relative to the "
            "project root — this pack will not guess which case you mean")


def _case(ctx: GateContext) -> str | None:
    rel = ctx.param("aero_case")
    if not rel:
        return None
    rel = str(rel)
    return rel if os.path.isabs(rel) else os.path.join(ctx.root, rel)


#: Significant digits a verdict's value is reported to, as cfd-openfoam's
#: ``REPORTED_DIGITS`` and for its reason: decimal places round a small value
#: to zero.
REPORTED_DIGITS = 9


def _shown(value: float, holds, passed: bool, digits: int = REPORTED_DIGITS):
    """``value`` rounded to ``digits`` significant digits when the rounded value
    is on the same side of the limit as the verdict, else whole, else None
    (cfd-openfoam's rule: the number shown never contradicts the verdict)."""
    for candidate in (float(f"{value:.{digits}g}"), float(value)):
        if bool(holds(candidate)) == bool(passed):
            return candidate
    return None


def _number(ctx: GateContext, key: str):
    """The finite number ``key`` holds, None when absent, or a str naming what
    is wrong with it."""
    raw = ctx.param(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return f"{key} is {raw!r}, not a number"
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return f"{key} is {raw!r}, not a number"
    if not math.isfinite(v):
        return f"{key} is {raw!r}, not a finite number"
    return v


def _evidence(ctx: GateContext, gid: str, payload: dict) -> str:
    path = ctx.out_path(PACK, gid.replace(".", "_"), "summary.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# reading the case
# --------------------------------------------------------------------------- #
class CaseProblem(Exception):
    """The case is not one this pack can run: a fail of the guard, naming why."""


#: The files a case must hold. A file the pack does not read is a file whose
#: effect it cannot vouch for (cfd-openfoam's first draft passed a
#: constant/fvOptions momentum source that halved its answer).
REQUIRED_FILES = ("system/controlDict", "system/fvSchemes", "system/fvSolution",
                  "system/blockMeshDict", "system/snappyHexMeshDict",
                  "constant/transportProperties", "constant/turbulenceProperties",
                  "0/U", "0/p", "0/k", "0/omega", "0/nut")
#: Read when present; required when the body is a surface file (snappyHexMesh
#: snaps to the features it extracts).
FEATURE_DICT = "system/surfaceFeatureExtractDict"
#: Files the pack writes its own of, in the staged copy (``_fo``): the case's
#: are neither read nor staged.
REPLACED_FILES = ("system/meshQualityDict", "system/decomposeParDict")
#: Directories the pack builds again or takes from elsewhere: the mesh, and the
#: surface file and its features (staged from ``aero_geometry``, pinned by its
#: digest).
IGNORED_DIRS = ("constant/polyMesh", "constant/triSurface", "constant/extendedFeatureEdgeMesh")

#: The one directive a case may hold, as cfd-openfoam's: ESI's own
#: ``#includeEtc "caseDicts/setConstraintTypes"``, first in a 0/ file's
#: boundaryField. Every other directive is refused: OpenFOAM evaluates it and
#: this reader does not.
ALLOWED_DIRECTIVE = ("#includeEtc", "caseDicts/setConstraintTypes")

#: Where a quoted (regular-expression) keyword may stand: patch names, solver
#: field names, and snappyHexMesh's per-surface layer and region names (the
#: motorBike's ``"(lowerWall|motorBike).*"``).
REGEX_PARENTS = ("boundaryField", "solvers", "equations", "fields", "layers", "regions")

#: The only file whose ``$macros`` the reader resolves: blockMeshDict's
#: vertices and counts. Rejected: snappyHexMeshDict too (the design's draft):
#: OpenFOAM's expansion of it is held to the reader's whole parse before any
#: run (``_as_read``), and a macro makes the two differ.
MACRO_FILES = ("system/blockMeshDict",)

#: The boundary conditions a 0/ file may use: each takes its value from the
#: case as written. cfd-openfoam's list, with the wall functions k-omega SST
#: needs. Rejected: every type but ``coded*`` (cfd-openfoam's second review
#: passed values evaluated at run time); ``nutUWallFunction`` (P0 ran the
#: Spalding function and the tutorial's ``nutkWallFunction`` only).
BOUNDARY_TYPES = ("fixedValue", "zeroGradient", "noSlip", "slip", "empty", "symmetry",
                  "symmetryPlane", "cyclic", "fixedGradient", "calculated", "inletOutlet",
                  "totalPressure", "pressureInletOutletVelocity", "fixedFluxPressure",
                  "kqRWallFunction", "omegaWallFunction", "nutUSpaldingWallFunction",
                  "nutkWallFunction")

#: The snappyHexMesh geometry types the pack reads, by v2606's names and their
#: short aliases. A body (a refinement surface) is a sphere or spheroid, a box
#: or a surface file; a cylinder may only mark a refinement region. Rejected:
#: every other searchable type (each a new formula for the body's bounds).
GEOMETRY_TYPES = {"searchableSphere": "sphere", "sphere": "sphere",
                  "searchableBox": "box", "box": "box",
                  "searchableCylinder": "cylinder", "cylinder": "cylinder",
                  "triSurfaceMesh": "surface"}

#: Geometry keywords that move or resize the body after it is read. Refused:
#: the domain is judged on the body's bounds as written.
GEOMETRY_MOVES = ("transform", "scale", "solidBodyMotion")

ON_WORDS = ("yes", "on", "true", "y")


def _listing(case: str) -> list[str]:
    """Every entry under the case's 0/, constant/ and system/, as relative
    paths, by listing the directories (cfd-openfoam's rule: decided only on
    what the spine keys for a listing). A directory is listed with a trailing
    ``/`` and not entered: none is allowed but the ignored ones."""
    found = []
    with os.scandir(case) as it:
        tops = {e.name: e.is_dir() for e in it}
    for top in T.CASE_DIRS:
        if not tops.get(top):
            continue
        with os.scandir(os.path.join(case, top)) as it:
            entries = sorted(((e.name, e.is_dir()) for e in it))
        for name, is_dir in entries:
            sub = f"{top}/{name}"
            if is_dir:
                if sub not in IGNORED_DIRS:
                    found.append(sub + "/")
            else:
                found.append(sub)
    return found


def _read(case: str, rel: str):
    try:
        return F.read(F.case_file(case, rel))
    except (F.FoamFormatError, UnicodeDecodeError) as exc:
        raise CaseProblem(f"{rel} does not parse: {exc}")


def _tokens(value):
    """Every token of a value, through its lists (not its dictionaries)."""
    if isinstance(value, F.Tok):
        yield value
    elif isinstance(value, (list, F.FoamList)):
        for v in value:
            yield from _tokens(v)


def _allowed_directive(e) -> bool:
    value = e.value if isinstance(e.value, list) else []
    return (e.key == ALLOWED_DIRECTIVE[0] and len(value) == 1
            and isinstance(value[0], F.Tok) and value[0].kind == "string"
            and value[0].text == ALLOWED_DIRECTIVE[1])


def _check(d, rel: str, problems: list[str], parent: str = "", macros: bool = False) -> None:
    """Everything in a dictionary the reader cannot vouch for: a directive, a
    dictionary expansion, a macro (outside blockMeshDict), a computed value, a
    quoted keyword where a keyword the pack decides on could stand, a ``type``
    that is not a literal word, and every spelling of compiled code.
    cfd-openfoam's rule, over this pack's files.

    A keyword written twice in one dictionary is refused too. OpenFOAM merges
    a repeated dictionary and the reader (``_foam``, cfd-openfoam's bytes) keeps
    the last one, so the two would read different cases. What slipped through
    P3-P5 (review, 2026-10-23): a second ``geometry`` and
    ``castellatedMeshControls`` hid a wall box the width of the domain from the
    reader, and aero.domain, which runs no ``foamDictionary -expand``, judged
    the domain on the spheroid alone and passed. Rejected: merging in the
    reader (a second dictionary reader's rules, beside OpenFOAM's, for a
    spelling no case needs); leaving it to ``_as_read`` (aero.domain and the
    tier-0 gates never run it)."""
    seen: set = set()
    for i, e in enumerate(d.entries):
        where = f"{rel}: {parent + '/' if parent else ''}{e.key}"
        if not e.directive:
            if (e.key, e.quoted) in seen:
                problems.append(f"{where}: written twice in one dictionary; OpenFOAM merges "
                                f"the two and this pack's reader reads one")
            seen.add((e.key, e.quoted))
        if e.directive:
            if not (_allowed_directive(e) and parent == "boundaryField"
                    and rel.startswith("0/") and i == 0):
                problems.append(f"{rel}: {e.key}, a directive OpenFOAM evaluates and this "
                                f"pack's reader does not")
            continue
        if e.key.startswith("$"):
            problems.append(f"{rel}: {e.key}, a dictionary expanded in place")
            continue
        if e.quoted:
            try:
                stands_for_type = re.fullmatch(e.key, "type") is not None
            except re.error:
                stands_for_type = True
            if parent not in REGEX_PARENTS or stands_for_type:
                problems.append(f"{where}: a quoted keyword here could stand for a keyword "
                                f"the pack decides on")
        for tok in _tokens(e.value):
            low = tok.text.lower()
            if "coded" in low or "codestream" in low or low.startswith("#calc"):
                problems.append(f"{where}: {tok.text.split('{')[0]} compiles C++ from the case")
            elif tok.kind == "expr" or "${" in tok.text:
                problems.append(f"{where}: {tok.text[:30]} is computed by OpenFOAM, not read")
            elif tok.text.startswith("$") and not macros:
                problems.append(f"{where}: {tok.text} is a macro (only blockMeshDict may use "
                                f"them)")
        if e.key == "type" and not e.is_dict:
            w = [t for t in e.value if isinstance(t, F.Tok)]
            if len(w) != 1 or len(e.value) != 1 or w[0].kind != "word" \
                    or w[0].text.startswith("$"):
                problems.append(f"{where}: a type that is not one literal word")
            elif rel.startswith("0/") and w[0].text not in BOUNDARY_TYPES:
                problems.append(f"{where}: boundary condition {w[0].text}, not one whose value "
                                f"the pack can read ({', '.join(BOUNDARY_TYPES)})")
        for item in ([e.value] if e.is_dict else
                     [v for v in e.value if isinstance(v, F.FoamDict)]):
            _check(item, rel, problems, e.key, macros)
        for lst in (v for v in ([] if e.is_dict else e.value) if isinstance(v, F.FoamList)):
            for item in lst:
                if isinstance(item, F.FoamDict):
                    _check(item, rel, problems, e.key, macros)


def _resolve(t, bmd, what: str) -> float:
    """A number token, or a ``$macro`` naming one in the blockMeshDict."""
    if isinstance(t, F.Tok) and t.kind == "number":
        return float(t.text)
    if isinstance(t, F.Tok) and t.text.startswith("$"):
        try:
            v = F.scalar(F.FoamDict(entries=[F.Entry("n", [t], 0, 0)], parent=bmd), "n")
        except F.Unresolved as exc:
            raise CaseProblem(f"system/blockMeshDict: {what} {t.text}: {exc}")
        if v is not None:
            return v
    raise CaseProblem(f"system/blockMeshDict: {what} {getattr(t, 'text', '(a list)')!r} is not "
                      f"a number or a $macro naming one")


def _vector(items, what: str) -> tuple:
    v = F.vector(items) if isinstance(items, F.FoamList) else None
    if v is None or len(v) != 3:
        raise CaseProblem(f"{what} is not three numbers")
    return v


def _entry_vector(d, key: str, what: str):
    e = d.entry(key) if d is not None else None
    if e is None or e.is_dict or len(e.value) != 1:
        raise CaseProblem(f"{what}: no {key} (x y z)")
    return _vector(e.value[0], f"{what}: {key}")


class Case:
    """What the gates read from a case, read once: a strict subset of what
    OpenFOAM accepts, the subset this pack can read exactly as OpenFOAM does."""

    def __init__(self, case: str):
        if not os.path.isdir(case):
            raise CaseProblem(f"no case directory at {case}")
        self.path = case
        files = _listing(case)
        allowed = REQUIRED_FILES + (FEATURE_DICT,) + REPLACED_FILES
        extra = [f for f in files if f not in allowed]
        if extra:
            raise CaseProblem(f"the case holds {', '.join(extra[:3])}"
                              f"{' and more' if len(extra) > 3 else ''}: this pack reads only "
                              f"{', '.join(REQUIRED_FILES)} (and {FEATURE_DICT}) and will not "
                              f"vouch for a file it does not read")
        missing = [f for f in REQUIRED_FILES if f not in files]
        if missing:
            raise CaseProblem(f"the case has no {', '.join(missing)}")
        #: The files a stage copies: everything the reader read.
        self.files = [f for f in files if f not in REPLACED_FILES]
        self.trees = {rel: _read(case, rel) for rel in self.files}
        problems: list[str] = []
        for rel, d in self.trees.items():
            _check(d, rel, problems, macros=rel in MACRO_FILES)
        if problems:
            raise CaseProblem("; ".join(problems[:4]) + (
                f" (and {len(problems) - 4} more)" if len(problems) > 4 else ""))
        self._control(self.trees["system/controlDict"])
        self._physics()
        self._block_mesh()
        self._snappy(self.trees["system/snappyHexMeshDict"])
        if self.surface_files and FEATURE_DICT not in self.files:
            raise CaseProblem(f"the body is a surface file and the case has no {FEATURE_DICT}: "
                              f"snappyHexMesh snaps to the features it extracts")
        self._inlet()

    # -- system/controlDict ------------------------------------------------ #
    def _control(self, control) -> None:
        if control.entry("libs") is not None:
            raise CaseProblem("system/controlDict loads libraries ('libs'): code this pack "
                              "cannot vouch for")
        if control.entry("functions") is not None:
            # The pack's function objects are the only ones a run carries: a
            # case's own could hand the gate a number (cfd-openfoam's first
            # review: a merged scaleFactor 0.5 passed six gates at half the
            # answer). Refused rather than removed, so the case on disk is the
            # case that ran.
            raise CaseProblem("system/controlDict has its own functions: this pack writes "
                              "every function object a run carries, and refuses a case's own")
        self.application = F.word(control, "application")
        if self.application not in APPLICATIONS:
            raise CaseProblem(f"application {self.application!r}: this pack runs "
                              f"{', '.join(APPLICATIONS)} only")
        stop_at = F.word(control, "stopAt") or "endTime"
        if stop_at != "endTime":
            raise CaseProblem(f"stopAt {stop_at}: this pack reads the iteration budget from "
                              f"endTime")
        try:
            start = F.scalar(control, "startTime") or 0.0
            end = F.scalar(control, "endTime")
            dt = F.scalar(control, "deltaT")
        except F.Unresolved as exc:
            raise CaseProblem(f"system/controlDict: {exc}")
        if end is None or dt is None or dt <= 0 or end <= start:
            raise CaseProblem("system/controlDict needs endTime above startTime and a "
                              "positive deltaT")
        self.budget = int(round((end - start) / dt))

    # -- constant/ ---------------------------------------------------------- #
    def _physics(self) -> None:
        turb = self.trees["constant/turbulenceProperties"]
        self.simulation_type = F.word(turb, "simulationType")
        if self.simulation_type != "RAS":
            raise CaseProblem(f"simulationType {self.simulation_type!r}: this pack runs RAS "
                              f"(k-omega SST) only")
        ras = turb.sub("RAS")
        model = None if ras is None else (F.word(ras, "RASModel") or F.word(ras, "model"))
        if model not in RAS_MODELS:
            raise CaseProblem(f"RAS model {model!r}: this pack vouches for "
                              f"{', '.join(RAS_MODELS)} only")
        if (F.word(ras, "turbulence") or "on").lower() not in ON_WORDS:
            raise CaseProblem("RAS turbulence is off: the model is read and never solved")
        self.ras_model = model
        transport = self.trees["constant/transportProperties"]
        if F.word(transport, "transportModel") != "Newtonian":
            raise CaseProblem(f"transportModel {F.word(transport, 'transportModel')!r}: this "
                              f"pack reads a Newtonian nu only")
        try:
            self.nu = F.scalar(transport, "nu")
        except F.Unresolved as exc:
            raise CaseProblem(f"constant/transportProperties: {exc}")
        if self.nu is None or not (self.nu > 0 and math.isfinite(self.nu)):
            raise CaseProblem("constant/transportProperties has no positive nu")
        if self.trees["system/fvSolution"].sub("SIMPLE") is None:
            raise CaseProblem("system/fvSolution has no SIMPLE dictionary")

    # -- system/blockMeshDict ----------------------------------------------- #
    def _block_mesh(self) -> None:
        with open(F.case_file(self.path, "system/blockMeshDict"), encoding="utf-8") as fh:
            self.block_mesh_text = fh.read()
        bmd = F.parse(self.block_mesh_text)
        e = bmd.entry("vertices")
        if e is None or e.is_dict or len(e.value) != 1 or not isinstance(e.value[0], F.FoamList):
            raise CaseProblem("system/blockMeshDict has no vertices list")
        verts = []
        for v in e.value[0]:
            if not isinstance(v, F.FoamList) or len(v) != 3:
                raise CaseProblem("system/blockMeshDict: a vertex that is not (x y z)")
            verts.append(tuple(_resolve(t, bmd, "vertex coordinate") for t in v))
        if not verts:
            raise CaseProblem("system/blockMeshDict has no vertices")
        lo = tuple(min(v[k] for v in verts) for k in range(3))
        hi = tuple(max(v[k] for v in verts) for k in range(3))
        if any(not (v[k] in (lo[k], hi[k])) for v in verts for k in range(3)) \
                or any(hi[k] <= lo[k] for k in range(3)):
            raise CaseProblem("system/blockMeshDict is not one axis-aligned box: the pack "
                              "reads the domain as the box its vertices span, and every vertex "
                              "must be a corner of it")
        edges = bmd.entry("edges")
        if edges is not None and not edges.is_dict and any(
                isinstance(v, F.FoamList) and len(v) > 0 for v in edges.value):
            raise CaseProblem("system/blockMeshDict has curved edges")
        self.verts, self.box = verts, (lo, hi)
        self.counts = self._blocks(bmd, len(verts))
        self.patches = self._patches(bmd)

    def _blocks(self, bmd, nverts: int) -> list:
        e = bmd.entry("blocks")
        if e is None or e.is_dict or len(e.value) != 1 or not isinstance(e.value[0], F.FoamList):
            raise CaseProblem("system/blockMeshDict has no blocks list")
        items, out, i = list(e.value[0]), [], 0
        #: Where each block's ``(nx ny nz)`` stands in the blockMeshDict's text,
        #: for the mesh ladder's levels (``block_mesh_at``).
        self.count_spans = spans = []
        while i < len(items):
            it = items[i]
            if not (isinstance(it, F.Tok) and it.text == "hex"):
                raise CaseProblem("system/blockMeshDict: a block that is not 'hex ...'")
            j = i + 1
            if j >= len(items) or not isinstance(items[j], F.FoamList) or len(items[j]) != 8:
                raise CaseProblem("system/blockMeshDict: a hex block without its eight vertices")
            j += 1
            if j < len(items) and isinstance(items[j], F.Tok) and items[j].kind == "word" \
                    and not items[j].text.endswith("Grading"):
                j += 1
            if j >= len(items) or not isinstance(items[j], F.FoamList) or len(items[j]) != 3:
                raise CaseProblem("system/blockMeshDict: a hex block with no (nx ny nz) cell counts")
            spans.append((items[j].start, items[j].end))
            counts = []
            for t in items[j]:
                v = _resolve(t, bmd, "cell count")
                if v != int(v) or v < 1:
                    raise CaseProblem(f"system/blockMeshDict: cell count {v:g} is not a whole "
                                      f"number of cells")
                counts.append(int(v))
            out.append(tuple(counts))
            j += 1
            if j < len(items) and isinstance(items[j], F.Tok) and items[j].text.endswith("Grading"):
                j += 1
                if j < len(items) and isinstance(items[j], F.FoamList):
                    j += 1
            i = j
        if not out:
            raise CaseProblem("system/blockMeshDict has no blocks")
        return out

    def _patches(self, bmd) -> dict:
        """``{name: (type, [face vertex ids])}``."""
        e = bmd.entry("boundary")
        if e is None or e.is_dict or len(e.value) != 1 or not isinstance(e.value[0], F.FoamList):
            raise CaseProblem("system/blockMeshDict has no boundary list")
        items = list(e.value[0])
        if len(items) % 2:
            raise CaseProblem("system/blockMeshDict: the boundary list ends in the middle of an "
                              "entry")
        out = {}
        for name, body in zip(items[0::2], items[1::2]):
            if not isinstance(name, F.Tok) or not isinstance(body, F.FoamDict):
                raise CaseProblem("system/blockMeshDict: a boundary entry that is not "
                                  "'name { ... }'")
            faces = []
            fe = body.entry("faces")
            if fe is not None and not fe.is_dict and len(fe.value) == 1 \
                    and isinstance(fe.value[0], F.FoamList):
                for f in fe.value[0]:
                    if isinstance(f, F.FoamList) and all(
                            isinstance(t, F.Tok) and t.kind == "number" for t in f):
                        ids = tuple(int(float(t.text)) for t in f)
                        if any(not 0 <= k < len(self.verts) for k in ids):
                            raise CaseProblem("system/blockMeshDict: a boundary face that is "
                                              "not made of the vertices")
                        faces.append(ids)
            out[name.text] = (F.word(body, "type") or "", faces)
        return out

    def cells(self) -> int:
        return sum(a * b * c for a, b, c in self.counts)

    def block_mesh_at(self, counts: list) -> str:
        """The blockMeshDict's text with each block's ``(nx ny nz)`` replaced
        by ``counts``, every other byte kept (a macro elsewhere stays one)."""
        text = self.block_mesh_text
        for (a, b), (nx, ny, nz) in sorted(zip(self.count_spans, counts), reverse=True):
            text = text[:a] + f"({nx} {ny} {nz})" + text[b:]
        return text

    def side(self, axis: int, high: bool) -> list[str]:
        """The patches with a face on the box's ``axis`` side (low or high)."""
        want = self.box[1 if high else 0][axis]
        return [name for name, (_t, faces) in self.patches.items()
                if any(all(self.verts[k][axis] == want for k in f) for f in faces)]

    def ground(self):
        """The ground's height: the box's bottom when the patches there are one
        wall, else None (a body in free air)."""
        names = self.side(2, False)
        if len(names) == 1 and self.patches[names[0]][0] == "wall":
            return self.box[0][2]
        return None

    # -- system/snappyHexMeshDict ------------------------------------------- #
    def _snappy(self, d) -> None:
        for key in ("castellatedMesh", "snap"):
            if (F.word(d, key) or "").lower() not in ON_WORDS:
                raise CaseProblem(f"system/snappyHexMeshDict: {key} is not on: the pack meshes "
                                  f"by castellating and snapping to the body")
        self.add_layers = (F.word(d, "addLayers") or "").lower() in ON_WORDS
        geo = d.sub("geometry")
        if geo is None:
            raise CaseProblem("system/snappyHexMeshDict has no geometry")
        self.geometry = {}
        self.surface_files = []
        for e in geo.entries:
            if not e.is_dict or e.quoted:
                raise CaseProblem(f"system/snappyHexMeshDict: geometry {e.key} is not a "
                                  f"dictionary")
            kind = GEOMETRY_TYPES.get(F.word(e.value, "type") or "")
            if kind is None:
                raise CaseProblem(f"system/snappyHexMeshDict: geometry {e.key} is a "
                                  f"{F.word(e.value, 'type')!r}; the pack reads "
                                  f"{', '.join(sorted(set(GEOMETRY_TYPES)))}")
            moved = [k for k in GEOMETRY_MOVES if e.value.entry(k) is not None]
            if moved:
                raise CaseProblem(f"system/snappyHexMeshDict: geometry {e.key} is moved or "
                                  f"resized ({', '.join(moved)}): the pack reads the body as "
                                  f"written")
            name = e.key
            if kind == "surface":
                f = F.word(e.value, "file")
                path = f.strip('"') if f else e.key
                name = F.word(e.value, "name") or e.key
                self.surface_files.append(path)
                self.geometry[name] = ("surface", path)
            elif kind == "sphere":
                centre = e.value.entry("origin") or e.value.entry("centre")
                if centre is None:
                    raise CaseProblem(f"system/snappyHexMeshDict: sphere {e.key} has no origin")
                c = _vector(centre.value[0] if len(centre.value) == 1 else None,
                            f"geometry {e.key}: origin")
                r = e.value.entry("radius")
                if r is None or r.is_dict or len(r.value) != 1:
                    raise CaseProblem(f"system/snappyHexMeshDict: sphere {e.key} has no radius")
                if isinstance(r.value[0], F.FoamList):
                    rad = _vector(r.value[0], f"geometry {e.key}: radius")
                elif isinstance(r.value[0], F.Tok) and r.value[0].kind == "number":
                    rad = (float(r.value[0].text),) * 3
                else:
                    raise CaseProblem(f"system/snappyHexMeshDict: sphere {e.key}: radius is not "
                                      f"a number or three")
                if any(not x > 0 for x in rad):
                    raise CaseProblem(f"system/snappyHexMeshDict: sphere {e.key}: a radius that "
                                      f"is not positive")
                self.geometry[name] = ("sphere", (tuple(c[k] - rad[k] for k in range(3)),
                                                  tuple(c[k] + rad[k] for k in range(3))))
            elif kind == "box":
                lo = _entry_vector(e.value, "min", f"geometry {e.key}")
                hi = _entry_vector(e.value, "max", f"geometry {e.key}")
                self.geometry[name] = ("box", (lo, hi))
            else:
                self.geometry[name] = ("cylinder", None)
        cmc = d.sub("castellatedMeshControls")
        surfaces = None if cmc is None else cmc.sub("refinementSurfaces")
        if surfaces is None or not surfaces.entries:
            raise CaseProblem("system/snappyHexMeshDict names no refinementSurfaces: the pack "
                              "reads the body from them")
        self.bodies = {}
        self.patch_infos = {}
        for e in surfaces.entries:
            if not e.is_dict or e.quoted:
                raise CaseProblem(f"system/snappyHexMeshDict: refinement surface {e.key} is "
                                  f"not a dictionary")
            if e.key not in self.geometry:
                raise CaseProblem(f"system/snappyHexMeshDict: refinement surface {e.key} names "
                                  f"no geometry")
            kind = self.geometry[e.key][0]
            if kind == "cylinder":
                raise CaseProblem(f"system/snappyHexMeshDict: the body {e.key} is a cylinder; "
                                  f"a body is a sphere, a box or a surface file")
            infos, own = [], []
            for k, holder in enumerate([e.value] + [
                    r.value for r in (e.value.sub("regions") or F.FoamDict()).entries
                    if r.is_dict]):
                info = holder.sub("patchInfo")
                if info is not None:
                    groups = info.entry("inGroups")
                    names = [t.text for t in _tokens(groups.value)] if groups is not None \
                        and not groups.is_dict else []
                    infos.append((F.word(info, "type") or "", names))
                own.append(infos[-1] if info is not None else None)
            self.bodies[e.key] = infos
            #: ``[the surface's own patchInfo, then each region's]``, None where
            #: one states none: the patches each set of words reaches.
            self.patch_infos[e.key] = own

    def body_groups(self) -> dict:
        """``{group: [the patch types of the body patches in it]}``."""
        out: dict = {}
        for infos in self.bodies.values():
            for kind, groups in infos:
                for g in groups:
                    out.setdefault(g, []).append(kind)
        return out

    def body_patch_sets(self) -> dict:
        """``{surface: [the groups of each set of its patches]}``: the
        surface's own patchInfo first (None when it states none), then each
        region's. A wall patch is in the group ``wall`` too (OpenFOAM's
        ``wallPolyPatch`` adds it), so a literal ``wall`` entry in a 0/ file
        reaches it."""
        return {name: [None if info is None else
                       set(info[1]) | ({"wall"} if info[0] == "wall" else set())
                       for info in infos]
                for name, infos in self.patch_infos.items()}

    def body_box(self):
        """The bounding box of every body the dictionary states, or None when
        a body is a surface file (OpenFOAM's surfaceCheck reads that one)."""
        boxes = []
        for name in self.bodies:
            kind, data = self.geometry[name]
            if kind == "surface":
                return None
            boxes.append(data)
        return _union(boxes)

    # -- 0/U ---------------------------------------------------------------- #
    def _inlet(self) -> None:
        """The inlet: the one patch on the box's low-x side, the side the
        pack's drag direction (+x) enters through. Its 0/U entry is read for
        aero.reference."""
        names = self.side(0, False)
        lo = self.box[0][0]
        if len(names) != 1 or not all(all(self.verts[k][0] == lo for k in f)
                                       for f in self.patches[names[0]][1]):
            raise CaseProblem(f"the box's low-x side is not one patch of its own (it holds "
                              f"{', '.join(names) or 'none'}): the pack's air enters along +x "
                              f"through one inlet there")
        self.inlet = names[0]
        bf = self.trees["0/U"].sub("boundaryField")
        if bf is None:
            raise CaseProblem("0/U has no boundaryField")
        self.u_boundary = bf


def _union(boxes):
    if not boxes:
        return None
    return (tuple(min(b[0][k] for b in boxes) for k in range(3)),
            tuple(max(b[1][k] for b in boxes) for k in range(3)))


def _uniform_vector(entry_dict):
    """The vector a boundary condition's ``value uniform (x y z)`` states, or
    None."""
    e = entry_dict.entry("value") if entry_dict is not None else None
    if e is None or e.is_dict or len(e.value) != 2:
        return None
    if not (isinstance(e.value[0], F.Tok) and e.value[0].text == "uniform"):
        return None
    v = F.vector(e.value[1]) if isinstance(e.value[1], F.FoamList) else None
    return v if v is not None and len(v) == 3 else None


# --------------------------------------------------------------------------- #
# the surface file
# --------------------------------------------------------------------------- #
#: The marker of a surface file inside the OpenFOAM install's tutorials, the
#: motorBike's ``$FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz``: the
#: geometry is GPL-3+ as part of OpenFOAM and is never copied into a project.
TUTORIALS = "$FOAM_TUTORIALS/"


def _geometry(ctx: GateContext, case: Case):
    """For a case whose body is a surface file: ``(path, sha256)`` of the file
    ``aero_geometry`` names, checked against ``aero_geometry_sha256``; a Verdict
    (for the caller to stamp with its id) when it cannot be; None when no body
    is a surface file. ``aero_geometry`` resolves against the project root, or
    against the install's tutorials when it starts ``$FOAM_TUTORIALS/``."""
    if not case.surface_files:
        return None
    if len(set(os.path.basename(f) for f in case.surface_files)) != 1:
        return ("error", f"the case names {len(case.surface_files)} surface files; the pack "
                         f"stages one (aero_geometry)")
    raw = ctx.param("aero_geometry")
    pinned = ctx.param("aero_geometry_sha256")
    if not raw:
        return ("skip", "no aero_geometry: the surface file the case's snappyHexMeshDict "
                        f"names ({case.surface_files[0]})")
    if not pinned or not re.fullmatch(r"[0-9a-f]{64}", str(pinned)):
        return ("error", "aero_geometry_sha256 must be the 64 hex digits of the surface "
                         "file's sha256: the pack runs the body it was told, by content")
    raw = str(raw)
    if raw.startswith(TUTORIALS):
        try:
            inst = T.locate()
        except T.Unavailable as exc:
            return ("skip", f"aero_geometry is in the OpenFOAM tutorials and {exc}")
        path = os.path.join(inst.root, "tutorials", *raw[len(TUTORIALS):].split("/"))
    else:
        path = raw if os.path.isabs(raw) else os.path.join(ctx.root, raw)
    if not os.path.isfile(path):
        return ("skip", f"aero_geometry {raw}: no file at {path}")
    names = {os.path.basename(f) for f in case.surface_files}
    base = os.path.basename(path)
    if not ({base, base[:-3] if base.endswith(".gz") else base} & names):
        return ("error", f"aero_geometry is {base}, but the case's snappyHexMeshDict names "
                         f"{', '.join(sorted(names))}")
    with open(path, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()
    if digest != str(pinned):
        return ("error", f"aero_geometry's sha256 is {digest}, not the {pinned} "
                         f"aero_geometry_sha256 pins: another body than the one stated")
    return (path, digest)


def _geometry_or_verdict(ctx: GateContext, gid: str, case: Case):
    got = _geometry(ctx, case)
    if isinstance(got, tuple) and got[0] == "skip":
        return _skip(gid, got[1])
    if isinstance(got, tuple) and got[0] == "error":
        return _error(gid, got[1])
    return got


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #
@gate(
    id="aero.case_readable",
    basis="model-only",
    title="The OpenFOAM case is one this pack can run and vouch for",
    claims=[GUARD_TAGS["aero.case_readable"]],
    tier=Tier.INSTANT,
    settles="aero case readability",
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:coded_inlet",
        note="the baseline spheroid with its inlet velocity written as a codedFixedValue, "
             "C++ the case would compile and run",
    ),
)
def case_readable(ctx: GateContext) -> Verdict:
    """The case parses with the pack's reader, runs a solver and a physics this
    pack vouches for (simpleFoam, RAS k-omega SST, Newtonian), meshes with
    blockMesh and snappyHexMesh from a box and bodies this pack can read,
    compiles nothing, carries no function object of its own, and, when its body
    is a surface file, names one whose sha256 is the one stated.

    A case this pack cannot read is a fail here, never a guess downstream. A
    surface file that is absent is a skip; one with another digest is an
    error, naming both."""
    gid = "aero.case_readable"
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    try:
        case = Case(path)
    except CaseProblem as exc:
        return Verdict(gate=gid, passed=False, detail=str(exc))
    geo = _geometry_or_verdict(ctx, gid, case)
    if isinstance(geo, Verdict):
        return geo
    body = (f"surface file {os.path.basename(geo[0])} (sha256 {geo[1][:12]}...)" if geo else
            ", ".join(f"{n} ({case.geometry[n][0]})" for n in case.bodies))
    return Verdict(gate=gid, passed=True,
                   detail=f"{case.application}, RAS {case.ras_model}, nu {case.nu:g} m^2/s, "
                          f"{case.cells()} background cells, body {body}, layers "
                          f"{'on' if case.add_layers else 'off'}, budget {case.budget} "
                          f"iterations; nothing compiled, no function object of the case's")


def _settings_number(ctx, gid, key, what):
    """A positive number from ``key``, or a skip / error Verdict."""
    v = _number(ctx, key)
    if v is None:
        return _skip(gid, f"no {key}: {what}")
    if isinstance(v, str):
        return _error(gid, v)
    if not v > 0:
        return _error(gid, f"{key} is {v:g}; it must be positive")
    return v


_U_INF = ("aero_u_inf_m_s", "the speed of the air far from the body, m/s (the inlet's, along "
                            "+x)")
_L_REF = ("aero_ref_length_m", "the body's reference length, m: the Reynolds number's length")


@gate(
    id="aero.reference",
    basis="model-only",
    title="The run is the stated flow: the inlet at the stated speed along +x, the body a still wall",
    claims=[GUARD_TAGS["aero.reference"]],
    tier=Tier.INSTANT,
    settles="aero flow reference",
    needs=["aero.case_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:wrong_speed",
        note="the baseline spheroid with its inlet velocity 15% above the stated free stream",
    ),
)
def reference(ctx: GateContext) -> Verdict:
    """The inlet (the one patch on the box's low-x side) is a ``fixedValue``
    of exactly (U 0 0) with U = ``aero_u_inf_m_s``: the speed every
    coefficient is made dimensionless by, and the pack's drag direction +x.
    The body group ``aero_body_group`` is named on the body's patches, each of
    them a wall, every body patch is reached in 0/U by a literal entry naming
    one of its groups (never by a regular expression), and every boundary
    condition 0/U states for the body is ``noSlip`` or a zero ``fixedValue``: a
    body moving with the air reads no drag. A mismatch is a fail, naming it."""
    gid = "aero.reference"
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    u = _settings_number(ctx, gid, *_U_INF)
    if isinstance(u, Verdict):
        return u
    group = ctx.param("aero_body_group")
    if not group:
        return _skip(gid, "no aero_body_group: the patch group of the body's surfaces, the "
                          "drag is summed over (the motorBike's motorBikeGroup)")
    group = str(group)
    try:
        case = Case(path)
    except CaseProblem as exc:
        return _error(gid, f"the case does not read: {exc}")
    problems = []
    inlet = case.u_boundary.entry(case.inlet)
    kind = F.word(inlet.value, "type") if inlet is not None and inlet.is_dict else None
    vec = _uniform_vector(inlet.value) if inlet is not None and inlet.is_dict else None
    if kind != "fixedValue" or vec is None:
        problems.append(f"0/U's inlet {case.inlet} is {kind or 'not stated'}, not a fixedValue "
                        f"of one uniform velocity")
    else:
        if vec[1] != 0.0 or vec[2] != 0.0 or not vec[0] > 0:
            problems.append(f"the inlet velocity {vec} is not along +x, the pack's drag "
                            f"direction")
        if not abs(vec[0] - u) <= 1e-9 * u:
            problems.append(f"the inlet velocity is {vec[0]:g} m/s, but aero_u_inf_m_s says "
                            f"{u:g}: every coefficient is made dimensionless by the stated "
                            f"speed")
    groups = case.body_groups()
    if group not in groups:
        problems.append(f"no body surface is in the group {group} (aero_body_group): the "
                        f"groups are {', '.join(sorted(groups)) or 'none'}")
    elif any(k != "wall" for k in groups[group]):
        problems.append(f"a body patch in {group} is a {', '.join(sorted(set(groups[group])))}, "
                        f"not a wall")
    domain = set(case.patches)
    # Which entry OpenFOAM applies to a body patch (GeometricBoundaryField::
    # readField, v2606): its name, else the last literal entry naming one of its
    # groups, and only then the last regular expression that matches its name.
    # The pack reads the first two and never resolves the third: every body
    # patch must be reached by a literal entry naming one of its groups, so no
    # regular expression ever sets a body patch. What slipped through P3-P5
    # (review, 2026-10-23, on v2606): the loop below skipped every quoted key
    # that matched a domain patch, so ``"sph.*" {noSlip}`` then
    # ``"(upperWall|frontAndBack|spheroid)" {slip}`` passed as "sph.* still"
    # while OpenFOAM ran the spheroid as slip, at 68% less drag. Rejected:
    # resolving the expressions against the body's patch names (a surface
    # file's regions name its patches, and the pack does not read the file).
    literal = {e.key for e in case.u_boundary.entries
               if not e.directive and not e.quoted and e.is_dict}
    groups_of_body = set()
    for surface, sets in case.body_patch_sets().items():
        for k, names in enumerate(sets):
            where = f"the body surface {surface}" + (f" (region {k})" if k else "")
            if names is None:
                if k == 0:
                    problems.append(f"{where} states no patchInfo: the pack reads a body's "
                                    f"boundary conditions by its groups")
                continue
            groups_of_body |= names
            if not names & literal:
                problems.append(f"0/U names no group of {where} "
                                f"({', '.join(sorted(names)) or 'none'}) as a literal entry: "
                                f"OpenFOAM would set its patches from a regular expression, "
                                f"which this pack does not resolve")
    body_entries = []
    for e in case.u_boundary.entries:
        if e.directive or not e.is_dict:
            continue
        if e.quoted:
            try:
                if any(re.fullmatch(e.key, p) for p in domain):
                    continue
            except re.error:
                pass
        elif e.key in domain and e.key not in groups_of_body:
            continue
        body_entries.append(e)
    if not body_entries:
        problems.append(f"0/U states no boundary condition for the body (its group {group} or "
                        f"its surfaces)")
    for e in body_entries:
        bc = F.word(e.value, "type")
        if bc == "noSlip" or (bc == "fixedValue" and _uniform_vector(e.value) == (0.0, 0.0, 0.0)):
            continue
        problems.append(f"0/U's {e.key} is {bc}: the body must be a still wall (noSlip), or the "
                        f"run is not a body in a stream")
    said = (f"inlet patch {case.inlet} at {vec[0]:g} m/s along +x" if vec else "inlet unread") + \
        f", aero_u_inf_m_s {u:g}; body group {group}"
    if problems:
        return Verdict(gate=gid, passed=False, detail="; ".join(problems) + f" ({said})")
    return Verdict(gate=gid, passed=True,
                   detail=f"{said}, {len(groups[group])} wall patch(es), "
                          f"{', '.join(e.key for e in body_entries)} still")


@gate(
    id="aero.regime",
    basis="sourced",
    title="The flow is turbulent at the wall and incompressible: Reynolds and Mach numbers",
    claims=[GUARD_TAGS["aero.regime"]],
    tier=Tier.BUILD,
    settles="aero flow regime",
    needs=["aero.case_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:thick_air",
        note="the baseline spheroid in a fluid viscous enough that its Reynolds number is "
             "15% below 5e5",
    ),
)
def regime(ctx: GateContext) -> Verdict:
    """Re = U L / nu at least 5e5 (``RE_MIN``: k-omega SST without a transition
    model assumes turbulent wall layers) and Ma = U / c below 0.3, with nu read
    from the case and U (``aero_u_inf_m_s``), L (``aero_ref_length_m``) and c
    (``aero_sound_speed_m_s``) as the project states them, L no longer than
    the body along the flow (`LENGTH_UNITS`): the dictionary's box for a sphere
    or a box, OpenFOAM's ``surfaceCheck`` for a surface file. The value is the
    reference length when it is longer than the body, else the Reynolds number
    (``Re``), or the Mach number (``Mach``) when it alone fails.

    Tier 1, not 0: a surface file's length is surfaceCheck's (as in
    aero.domain), so this gate runs a tool for such a body and is then opaque.
    What slipped through P3-P5 (review, 2026-10-23): the stated length was
    held to nothing. On the 1 m spheroid with nu 1.5e-4, Re is 1.33e5, a
    laminar body; ``aero_ref_length_m`` 10 read Re 1.33e6 and passed, while
    aero.reference holds U to the inlet. Rejected: the body's largest extent
    (a body's height is no distance the air runs along its wall); bounding L
    in aero.domain only (a flow-regime claim would read Checked on a Reynolds
    number of a body that does not exist); reading the surface file's vertices
    here (arithmetic on geometry no OpenFOAM tool reports, in a second
    reader of every surface format)."""
    gid = "aero.regime"
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    vals = {}
    for key, what in (_U_INF, _L_REF,
                      ("aero_sound_speed_m_s", "the speed of sound in the air, m/s (343 at "
                                               "20 C)")):
        v = _settings_number(ctx, gid, key, what)
        if isinstance(v, Verdict):
            return v
        vals[key] = v
    try:
        case = Case(path)
    except CaseProblem as exc:
        return _error(gid, f"the case does not read: {exc}")
    u, length, c = vals["aero_u_inf_m_s"], vals["aero_ref_length_m"], vals["aero_sound_speed_m_s"]
    re_, ma = u * length / case.nu, u / c
    body = case.body_box()
    logs: list = []
    if body is None:
        s = _run_settings(ctx, gid, ("timeout",))
        if isinstance(s, Verdict):
            return s
        opened = _open(ctx, gid)
        if isinstance(opened, Verdict):
            return opened
        try:
            body, logs = _body_bounds(opened[1], ctx, gid, s, s["timeout"])
        except P.Timeout as exc:
            return _skip(gid, str(exc))
        except T.RunError as exc:
            return _error(gid, str(exc), exc.evidence)
    run = body[1][0] - body[0][0]
    problems = []
    too_long = not length <= run * (1 + LENGTH_SLACK)
    if too_long:
        problems.append(f"aero_ref_length_m {length:g} m is longer than the body along the "
                        f"flow ({run:.6g} m): no wall layer runs that far, so the Reynolds "
                        f"number on it is of another body")
    if not re_ >= RE_MIN:
        problems.append(f"Re {re_:.4g} is below {RE_MIN:g}: k-omega SST without a transition "
                        f"model makes laminar wall layers turbulent")
    if not ma < MACH_MAX:
        problems.append(f"Mach {ma:.3g} is not below {MACH_MAX:g}: an incompressible solver on "
                        f"a flow whose density changes")
    # The Reynolds number, unless Mach alone fails: then Mach. Re is a floor
    # and Mach a ceiling, so "the nearer of the two" (cfd-openfoam's rule, both
    # ceilings there) put a passing Mach under a value read against a floor.
    # What slipped through P3 (test_mutation's walk on the baseline): sound at
    # 177 m/s made Mach 0.113 the nearer, and the walk read 0.113 against 0.3 as
    # a Reynolds number 62% under its floor on a pass. Rejected: two values (one
    # per verdict); the nearer one (above).
    if too_long:
        top = run * (1 + LENGTH_SLACK)
        measured, limit, comp, units, holds = (length, run, "<=", LENGTH_UNITS,
                                               (lambda x: x <= top))
    elif ma >= MACH_MAX and re_ >= RE_MIN:
        measured, limit, comp, units, holds = ma, MACH_MAX, "<", MACH_UNITS, (lambda x: x < MACH_MAX)
    else:
        measured, limit, comp, units, holds = re_, RE_MIN, ">=", RE_UNITS, (lambda x: x >= RE_MIN)
    said = (f"Re {re_:.4g} = U L / nu: U {u:g} m/s, L {length:g} m (the body runs "
            f"{run:.6g} m along the flow), nu {case.nu:g} m^2/s from the case; limit "
            f"{RE_MIN:g}, flat-plate transition. Mach {ma:.3g} = U / c, c {c:g} m/s; limit "
            f"{MACH_MAX:g}")
    return Verdict(gate=gid, passed=not problems,
                   measured=_shown(measured, holds, not problems), limit=limit, comparator=comp,
                   units=units, detail="; ".join(problems) + f" ({said})" if problems else said,
                   evidence=list(logs))


# --------------------------------------------------------------------------- #
# running OpenFOAM
# --------------------------------------------------------------------------- #
def _open(ctx: GateContext, gid: str):
    """``(install, environment)`` or a skip/error Verdict."""
    try:
        inst = T.locate()
        env = T.environment(inst, T.home(ctx.out_dir, inst.api, PACK))
    except T.Unavailable as exc:
        return _skip(gid, str(exc))
    except T.Timeout as exc:
        return _skip(gid, str(exc))
    except T.RunError as exc:
        return _error(gid, str(exc))
    return inst, env


def _serial(env: dict, case: str, argv: list[str], timeout: float, **kw):
    """``_tool.run``, its timeout re-worded with this pack's parameter (the copy
    is cfd-openfoam's, byte for byte, and names ``cfd_timeout_s``)."""
    try:
        return T.run(env, case, argv, timeout, **kw)
    except T.Timeout:
        raise P.Timeout(f"{argv[0]} ran past {timeout:g} s (aero_timeout_s) and was killed")


def _positive(ctx, gid, key, default, *, integer=False, top=None):
    """``(value, marked default?)`` from ``key``, or an error Verdict."""
    v = _number(ctx, key)
    if v is None:
        return default, True
    if isinstance(v, str):
        return _error(gid, v)
    if not v > 0 or (integer and v != int(v)) or (top is not None and v > top):
        return _error(gid, f"{key} is {ctx.param(key)!r}; it must be a positive "
                           f"{'whole number' if integer else 'number'}"
                           + (f" up to {top:g}" if top is not None else ""))
    return (int(v) if integer else v), False


_SETTINGS = (("timeout", "aero_timeout_s", DEFAULT_TIMEOUT_S, False, None),
             ("ranks", "aero_ranks", DEFAULT_RANKS, True, RANKS_MAX),
             ("global", "aero_max_global_cells", DEFAULT_MAX_GLOBAL_CELLS, True, None))


def _run_settings(ctx: GateContext, gid: str, which=("timeout", "ranks", "global")):
    """``{case, geometry, marks}`` and the settings ``which`` names
    (``timeout``, ``ranks``, ``global``), or a Verdict: what every
    gate that runs OpenFOAM reads first. A gate reads only the settings it
    uses: each read is a key of its verdict (aero.domain, which runs at most
    surfaceCheck, read the ranks and the caps until P3's review)."""
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    out: dict = {"marks": []}
    for name, key, default, integer, top in _SETTINGS:
        if name not in which:
            continue
        got = _positive(ctx, gid, key, default, integer=integer, top=top)
        if isinstance(got, Verdict):
            return got
        out[name] = got[0]
        if got[1]:
            out["marks"].append(key)
    try:
        out["case"] = Case(path)
    except CaseProblem as exc:
        return _error(gid, f"the case does not read: {exc}")
    geo = _geometry_or_verdict(ctx, gid, out["case"])
    if isinstance(geo, Verdict):
        return geo
    out["geometry"] = geo
    return out


def _stage_dir(ctx: GateContext, gid: str, name: str) -> str:
    marker = ctx.out_path(PACK, gid.replace(".", "_"), name, ".stage")
    return os.path.dirname(marker)


def _write(stage: str, rel: str, text: str) -> None:
    path = F.case_file(stage, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def _edit(stage: str, rel: str, fn) -> None:
    path = F.case_file(stage, rel)
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    _write(stage, rel, fn(text))


def _prepare(stage: str, s: dict, functions: str | None = None) -> None:
    """A staged copy of the case with the pack's dictionaries written in: its
    quality limits (for snappyHexMesh and for checkMesh), its cell limits, its
    decomposition, its write precision, its function objects (``functions``,
    or none), and the surface file from ``aero_geometry``. Every other byte is
    the project's."""
    case = s["case"]
    T.stage(case.path, stage, case.files)
    if s["geometry"]:
        src, digest = s["geometry"]
        dst = F.case_file(stage, f"constant/triSurface/{os.path.basename(src)}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise T.RunError("the surface file changed between its digest and its copy")
        with open(dst, "wb") as fh:
            fh.write(data)
    _write(stage, "system/meshQualityDict", FO.quality_dict())
    _write(stage, "system/decomposeParDict", FO.decompose_dict(s["ranks"]))

    def snappy(text: str) -> str:
        text = F.put_entry(text, "meshQualityControls", FO.quality_controls())
        text = F.put_entry(text, "castellatedMeshControls/maxGlobalCells",
                           f"maxGlobalCells {s['global']};")
        return F.put_entry(text, "castellatedMeshControls/maxLocalCells",
                           f"maxLocalCells {MAX_LOCAL_CELLS};")
    _edit(stage, "system/snappyHexMeshDict", snappy)

    def control(text: str) -> str:
        text = F.put_entry(text, "writePrecision", f"writePrecision {FO.WRITE_PRECISION};")
        return text if functions is None else F.put_entry(text, "functions", functions)
    _edit(stage, "system/controlDict", control)


def _canon(v):
    """A dictionary, list or token as plain data, numbers as floats, keyword
    order kept for lists and dropped for dictionaries: two spellings of one
    value compare equal (cfd-openfoam's ``_canon``)."""
    if isinstance(v, F.FoamDict):
        return tuple(sorted((e.key, _canon(e.value)) for e in v.entries if e.key != "FoamFile"))
    if isinstance(v, (list, F.FoamList)):
        return tuple(_canon(x) for x in v)
    if isinstance(v, F.Tok):
        return float(v.text) if v.kind == "number" else v.text.strip('"')
    return repr(v)


#: The dictionaries OpenFOAM's expansion of the staged copy must equal the
#: reader's parse of it, whole. blockMeshDict is held instead to what blockMesh
#: reports (its cells and bounding box: its macros are expanded), the 0/ files
#: are not expanded (the allowed include adds the constraint patches), and the
#: two the pack writes are held to the pack's text.
WHOLE = ("system/controlDict", "system/fvSchemes", "system/fvSolution",
         "system/snappyHexMeshDict", "constant/transportProperties",
         "constant/turbulenceProperties", FEATURE_DICT)


def _as_read(env, stage: str, s: dict, timeout: float) -> list[str]:
    """OpenFOAM's own reading of the staged copy (``foamDictionary -expand``),
    held to the reader's parse of the same bytes: the logs, or T.RunError on
    any difference. The tier-0 reader refuses what it cannot evaluate; this is
    the second line, and it holds the pack's own dictionaries too. What slipped
    through cfd-openfoam's first draft: a ``#sinclude`` that MERGED a
    scaleFactor into the pack's function objects, which a text edit cannot see."""
    problems, logs = [], []
    for rel in WHOLE + REPLACED_FILES:
        if not os.path.isfile(F.case_file(stage, rel)):
            continue
        run = _serial(env, stage, ["foamDictionary", "-expand", rel], timeout, banner=False,
                      log=f"log.foamDictionary.{os.path.basename(rel)}")
        logs.append(run.log)
        try:
            theirs = F.parse(run.stdout)
            mine = F.read(F.case_file(stage, rel))
        except F.FoamFormatError as exc:
            raise T.RunError(f"foamDictionary's expansion of {rel} does not parse: {exc}",
                             [run.log])
        if _canon(theirs) != _canon(mine):
            problems.append(rel)
    if problems:
        raise T.RunError("OpenFOAM reads the staged case otherwise than the pack wrote and "
                         "read it: " + ", ".join(problems), logs)
    return logs


def _block_mesh(env, stage: str, case: Case, timeout: float, cells: int | None = None):
    """blockMesh, held to the reader's cells (``cells``: a ladder level's) and
    box."""
    want = case.cells() if cells is None else cells
    run = _serial(env, stage, ["blockMesh"], timeout)
    try:
        cells = T.block_mesh_cells(run.stdout)
    except ValueError as exc:
        raise T.RunError(str(exc), [run.log])
    m = re.search(r"boundingBox:\s*\(([^)]*)\)\s*\(([^)]*)\)", run.stdout)
    box = None
    if m:
        try:
            box = (tuple(float(x) for x in m.group(1).split()),
                   tuple(float(x) for x in m.group(2).split()))
        except ValueError:
            box = None
    if cells != want or box is None or any(
            abs(a - b) > 1e-9 * (1 + abs(b)) for p, q in zip(box, case.box) for a, b in zip(p, q)):
        raise T.RunError(f"blockMesh built {cells} cells in {box}; the reader read "
                         f"{want} in {case.box}", [run.log])
    return run


def _surface_box(env, scratch: str, geometry, timeout: float):
    """OpenFOAM's bounding box of a surface file (``surfaceCheck``), run in
    ``scratch``: it writes about 23 files where it runs (P0)."""
    src, _digest = geometry
    os.makedirs(scratch, exist_ok=True)
    name = os.path.basename(src)
    with open(src, "rb") as fh, open(os.path.join(scratch, name), "wb") as out:
        out.write(fh.read())
    run = _serial(env, scratch, ["surfaceCheck", name], timeout)
    m = re.search(r"^Bounding Box\s*:\s*\(([^)]*)\)\s*\(([^)]*)\)", run.stdout, re.M)
    try:
        lo = tuple(float(x) for x in m.group(1).split())
        hi = tuple(float(x) for x in m.group(2).split())
    except (AttributeError, ValueError):
        raise T.RunError("surfaceCheck printed no bounding box", [run.log])
    if len(lo) != 3 or len(hi) != 3 or not T.finite(*lo, *hi) or any(
            hi[k] < lo[k] for k in range(3)):
        raise T.RunError(f"surfaceCheck's bounding box {lo} {hi} is not a box", [run.log])
    return (lo, hi), run.log


def _body_bounds(env, ctx, gid, s: dict, timeout: float):
    """``(body box, [logs])``: the dictionary's for a sphere or a box,
    surfaceCheck's for a surface file (its own scratch, then the union)."""
    case = s["case"]
    box = case.body_box()
    if box is not None:
        return box, []
    scratch = _stage_dir(ctx, gid, "surfaceCheck")
    if os.path.isdir(scratch):
        shutil.rmtree(scratch)
    surf, log = _surface_box(env, scratch, s["geometry"], timeout)
    others = [d for n, (k, d) in ((n, case.geometry[n]) for n in case.bodies) if k != "surface"]
    return _union([surf, *others]), [log]


# --------------------------------------------------------------------------- #
# the domain
# --------------------------------------------------------------------------- #
def domain_measures(dom, body, ground):
    """``[(name, value, limit, comparator, units)]`` for a body box in a domain
    box: the distances in H (the body's top over the ground, or its own height
    in free air) and the blockage ratios in %. Pure arithmetic on two boxes, so
    the tests hold it on the numbers P0 measured."""
    (dx0, dy0, dz0), (dx1, dy1, dz1) = dom
    (bx0, by0, bz0), (bx1, by1, bz1) = body
    floor = ground if ground is not None else dz0
    h = bz1 - floor if ground is not None else bz1 - bz0
    width, height = by1 - by0, bz1 - bz0
    out = [("upstream", (bx0 - dx0) / h, UPSTREAM_MIN_H, ">=", H_UNITS),
           ("downstream", (dx1 - bx1) / h, DOWNSTREAM_MIN_H, ">=", H_UNITS),
           ("side", min(by0 - dy0, dy1 - by1) / h, SIDE_MIN_H, ">=", H_UNITS),
           ("top", (dz1 - bz1) / h, TOP_MIN_H, ">=", H_UNITS)]
    if ground is None:
        out.append(("bottom", (bz0 - dz0) / h, TOP_MIN_H, ">=", H_UNITS))
    out += [("blockage", 100.0 * width * height / ((dy1 - dy0) * (dz1 - dz0)),
             BLOCKAGE_MAX_PCT, "<=", PCT),
            ("lateral blockage", 100.0 * width / (dy1 - dy0), DIRECTIONAL_MAX_PCT, "<=", PCT),
            ("vertical blockage", 100.0 * (bz1 - floor) / (dz1 - floor), DIRECTIONAL_MAX_PCT,
             "<=", PCT)]
    return out, h


def _holds(value, limit, comp) -> bool:
    return value >= limit if comp == ">=" else value <= limit


@gate(
    id="aero.domain",
    basis="sourced",
    title="The domain is large enough around the body: distances and blockage (Franke et al. 2007)",
    claims=[GUARD_TAGS["aero.domain"]],
    tier=Tier.BUILD,
    settles="aero domain size",
    requires_tools=list(T.WRAPPERS),
    needs=["aero.case_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:short_wake",
        note="the baseline spheroid with its outlet moved upstream until the wake behind the "
             "body is 15% shorter than 15 H",
    ),
)
def domain(ctx: GateContext) -> Verdict:
    """The body's distances to the inlet (at least 5 H), the outlet (15 H), the
    sides and the top (5 H), with H the height of the body's top over the
    ground, and its blockage ratio (at most 3%) and directional blockage ratios
    (17%): Franke et al. 2007 and Blocken 2015 (references/domain.md). The
    domain is blockMeshDict's box; the body's bounds are the dictionary's for a
    sphere or a box, and OpenFOAM's ``surfaceCheck``'s for a surface file. The
    value is the measure nearest its own limit, in its own units (``H``,
    ``%``)."""
    gid = "aero.domain"
    s = _run_settings(ctx, gid, ())
    if isinstance(s, Verdict):
        return s
    case = s["case"]
    logs = []
    if case.body_box() is None:
        s = _run_settings(ctx, gid, ("timeout",))
        if isinstance(s, Verdict):
            return s
        opened = _open(ctx, gid)
        if isinstance(opened, Verdict):
            return opened
        _inst, env = opened
        try:
            body, logs = _body_bounds(env, ctx, gid, s, s["timeout"])
        except P.Timeout as exc:
            return _skip(gid, str(exc))
        except T.RunError as exc:
            return _error(gid, str(exc), exc.evidence)
    else:
        body = case.body_box()
    ground = case.ground()
    if ground is not None and body[0][2] < ground:
        # A body resting on the ground meets it in a contact patch, and a
        # surface file's tyres reach a little below it: the motorBike's lowest
        # point is 4.2e-5 m under its ground (surfaceCheck, P0), which snappy
        # cuts off. Up to GROUND_CONTACT of H counts as resting on the ground.
        sunk = ground - body[0][2]
        if sunk > GROUND_CONTACT * (body[1][2] - ground):
            return Verdict(gate=gid, passed=False,
                           detail=f"the body reaches {sunk:.3g} m below the ground (z "
                                  f"{body[0][2]:g} < {ground:g}): more than a contact patch")
        body = ((body[0][0], body[0][1], ground), body[1])
    if any(body[0][k] < case.box[0][k] or body[1][k] > case.box[1][k] for k in range(3)):
        return Verdict(gate=gid, passed=False,
                       detail=f"the body {body} is not inside the domain {case.box}")
    rows, h = domain_measures(case.box, body, ground)
    if not h > 0:
        return _error(gid, f"the body has no height over the ground ({h:g} m)")
    over = [r for r in rows if not _holds(r[1], r[2], r[3])]

    def margin(r):
        name, v, lim, comp, _u = r
        return v / lim if comp == ">=" else (lim / v if v > 0 else math.inf)
    binding = min(rows, key=margin)
    name, v, lim, comp, units = binding
    said = "; ".join(f"{n} {x:.3g} {u} ({c} {l:g})" for n, x, l, c, u in rows)
    ev = _evidence(ctx, gid, {"domain_box": case.box, "body_box": body, "ground_z_m": ground,
                              "h_m": h, "measures": {r[0]: r[1] for r in rows}})
    over_what = "the ground" if ground is not None else "its own bottom, in free air"
    detail = f"H {h:.4g} m (the body's top over {over_what}); {said}"
    passed = not over
    if over:
        detail = (", ".join(f"{n} {x:.3g} {u} against {c} {l:g}" for n, x, l, c, u in over)
                  + f" (Franke et al. 2007, Blocken 2015). {detail}")
    return Verdict(gate=gid, passed=passed,
                   measured=_shown(v, lambda x: _holds(x, lim, comp), passed), limit=lim,
                   comparator=comp, units=units, detail=detail, evidence=[ev, *logs])


# --------------------------------------------------------------------------- #
# the mesh
# --------------------------------------------------------------------------- #
class Mesh:
    """What one blockMesh + snappyHexMesh + checkMesh -meshQuality run left."""

    def __init__(self, snappy, quality, cells, logs, stage):
        self.snappy = snappy          # _par.Snappy
        self.quality = quality        # checkMesh's [(description, count)]
        self.cells = cells
        self.logs = logs
        self.stage = stage

    def problems(self, cap: int) -> list[str]:
        """Why this mesh fails the pack's rule, or []: snappyHexMesh finished
        without errors, its final check found no face in error, it reached no
        cell cap, and checkMesh -meshQuality counts no face in error against
        the pack's limits."""
        why = []
        sn = self.snappy
        if sn.cap is not None:
            why.append(f"snappyHexMesh stopped refining at its cell cap {sn.cap} "
                       f"(aero_max_global_cells {cap}): the mesh is not the one its dictionary "
                       f"asks for")
        if not sn.finished_ok:
            why.append("snappyHexMesh did not finish 'without any errors'")
        bad_final = [(d, n) for d, n in (sn.final or []) if n]
        if bad_final:
            why.append("snappyHexMesh's final check: " + ", ".join(
                f"{n} {d}" for d, n in bad_final))
        bad = [(d, n) for d, n in self.quality if n]
        if bad:
            why.append(f"checkMesh -meshQuality: {sum(n for _d, n in bad)} faces in error ("
                       + ", ".join(f"{n} {' '.join(d.split())}" for d, n in bad) + ")")
        return why

    def layers(self) -> str:
        lay = self.snappy.layers
        return "no layers" if lay is None else f"layers on {lay[2]:.3g}% of the body's faces"


def _mesh(env, stage: str, s: dict, timeout: float, cells: int | None = None) -> Mesh:
    """blockMesh, surfaceFeatureExtract (for a surface file), decomposePar, the
    rank probe, snappyHexMesh and checkMesh -meshQuality on the staged copy:
    a Mesh, or T.RunError / P.Timeout. snappyHexMesh reads the pack's quality
    limits (``_prepare``): P0 found a mesh built to the tutorial's own limits
    failing the pack's on 1 095 faces."""
    case, n = s["case"], s["ranks"]
    logs = list(_as_read(env, stage, s, timeout))
    logs.append(_block_mesh(env, stage, case, timeout, cells).log)
    if s["geometry"]:
        logs.append(_serial(env, stage, ["surfaceFeatureExtract"], timeout).log)
    logs.append(_serial(env, stage, ["decomposePar", "-force"], timeout).log)
    logs.append(P.rank_probe(env, stage, n, timeout))
    sn = P.run_parallel(env, stage, ["snappyHexMesh", "-overwrite"], n, timeout)
    logs.append(sn.log)
    check = P.run_parallel(env, stage, ["checkMesh", "-meshQuality", "-constant"], n, timeout)
    logs.append(check.log)
    return _read_mesh(sn.stdout, check.stdout, logs, stage, check.log)


def _read_mesh(snappy_text: str, check_text: str, logs: list, stage: str, check_log: str) -> Mesh:
    """A Mesh from what snappyHexMesh and checkMesh -meshQuality printed: the
    one reading of the two logs, whether the tools ran in this gate or a ladder
    record holds their logs (``_Record``). T.RunError when checkMesh judged
    against other limits than the pack's or printed no block or cell count."""
    rows = P.faces_in_error(check_text)
    if rows is None:
        raise T.RunError("checkMesh -meshQuality printed no 'Checking faces in error' block",
                         [check_log])
    if P.thresholds(rows) != FO.CHECKED:
        raise T.RunError(f"checkMesh judged against limits {P.thresholds(rows)}, not the "
                         f"pack's {FO.CHECKED}", [check_log])
    try:
        cells = P.mesh_cells(check_text)
    except ValueError as exc:
        raise T.RunError(str(exc), [check_log])
    return Mesh(P.snappy(snappy_text), rows, cells, logs, stage)


@gate(
    id="aero.mesh_quality",
    basis="established",
    title="snappyHexMesh builds a mesh with no face in error against the pack's quality limits",
    claims=[GUARD_TAGS["aero.mesh_quality"]],
    tier=Tier.BUILD,
    settles="aero mesh quality",
    requires_tools=list(T.WRAPPERS),
    needs=["aero.case_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:cell_cap",
        note="the baseline spheroid with aero_max_global_cells at 20 000, half its mesh: "
             "snappyHexMesh stops refining at the cap and still says it finished without errors",
    ),
)
def mesh_quality(ctx: GateContext) -> Verdict:
    """blockMesh, decomposePar, ``snappyHexMesh -overwrite -parallel`` and
    ``checkMesh -meshQuality -parallel`` on a staged copy, every one of them
    reading the pack's quality limits (``_fo.QUALITY``, ESI's own
    ``etc/caseDicts/meshQualityDict``) and the pack's cell limits
    (``aero_max_global_cells``, and ``MAX_LOCAL_CELLS``). Passes only when
    snappyHexMesh finished without errors, reached no cap and its final check
    found no face in error, and checkMesh counts no face in error.

    Plain checkMesh's verdict line is never read: its fixed skewness limit fails
    every motorBike mesh. Layer coverage is in the detail, not judged (P0: 56.5%
    on the motorBike L0, 100% on the spheroid; aero.wall_treatment judges what
    the layers are for, y+). The value is the cell count against the cap, or the
    faces in error against 0 on a fail."""
    gid = "aero.mesh_quality"
    s = _run_settings(ctx, gid)
    if isinstance(s, Verdict):
        return s
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    _inst, env = opened
    stage = _stage_dir(ctx, gid, "case")
    try:
        _prepare(stage, s)
        mesh = _mesh(env, stage, s, s["timeout"])
    except P.Timeout as exc:
        return _skip(gid, str(exc))
    except (T.RunError, ValueError, KeyError) as exc:
        return _error(gid, str(exc), getattr(exc, "evidence", []))
    why = mesh.problems(s["global"])
    marks = f" [pack default: {', '.join(s['marks'])}]" if s["marks"] else ""
    ev = _evidence(ctx, gid, {"cells": mesh.cells, "ranks": s["ranks"],
                              "cap_reached": mesh.snappy.cap,
                              "finished_ok": mesh.snappy.finished_ok,
                              "faces_in_error": {" ".join(d.split()): n for d, n in mesh.quality},
                              "layer_coverage_pct": (mesh.snappy.layers or (0, 0, None))[2],
                              "pack_default": s["marks"]})
    evidence = [ev, *mesh.logs]
    said = (f"{mesh.cells} cells on {s['ranks']} ranks, cap {s['global']}; {mesh.layers()} "
            f"(reported, not judged){marks}")
    if why:
        bad = sum(n for _d, n in mesh.quality)
        detail = "; ".join(why) + f" ({said})"
        if bad:
            return Verdict(gate=gid, passed=False, measured=float(bad), limit=0.0,
                           comparator="<=", units=FACE_UNITS, detail=detail, evidence=evidence)
        if mesh.snappy.cap is not None:
            v = _shown(float(mesh.cells), lambda x: x < s["global"], False)
            if v is not None:
                return Verdict(gate=gid, passed=False, measured=v, limit=float(s["global"]),
                               comparator="<", units=CELL_UNITS, detail=detail,
                               evidence=evidence)
        return Verdict(gate=gid, passed=False, detail=detail, evidence=evidence)
    return Verdict(gate=gid, passed=True,
                   measured=_shown(float(mesh.cells), lambda x: x < s["global"], True),
                   limit=float(s["global"]), comparator="<", units=CELL_UNITS,
                   detail=f"snappyHexMesh finished without errors, checkMesh -meshQuality: 0 "
                          f"faces in error against the pack's limits; {said}",
                   evidence=evidence)


# --------------------------------------------------------------------------- #
# convergence
# --------------------------------------------------------------------------- #
#: The window U_I is taken over: the last 100 iterations. P0 (2026-10-23)
#: measured the motorBike at W = 100 and W = 200: L0 0.24% and 0.27%, L2 1.09%
#: and 1.84%; the spheroid settles inside 150 iterations at every level. 100 is
#: longer than the spheroid's settling and the motorBike's limit-cycle period
#: (about 16 iterations on P0's cube), and short enough that a 300-iteration
#: baseline compares two windows for drift. Rejected: 200 (a baseline of 400+
#: iterations, and every window the motorBike L1 passed at 100 it fails at 200:
#: a longer window is a stricter claim, which the ceiling already states);
#: 30 (the design's first reading of the motorBike: a 30-iteration window ending
#: at 60 gave 1.26%, inside the transient).
WINDOW = 100

#: The iterative uncertainty's ceiling when the project states none: 1% of the
#: drag area (the author's choice D3, 2026-10-23: common RANS verification
#: practice; the motorBike L0 measured 0.24% at W = 100). Marked ``[pack
#: default]``.
DEFAULT_ITER_UNC_MAX_PCT = 1.0

#: How far any field's initial residual may climb at the last iteration over
#: the least it reached in the window: 10 times. The pack does not judge
#: residual levels (a limit cycle holds them up), only a climb: a run that
#: diverges or restarts in its last window. Measured (P0, every spheroid and
#: motorBike run, every window end from 110 to 1500): at most 5.7. Rejected:
#: the max over the min in the window (114 on a run still converging fast, the
#: spheroid x1.1 at 300: a fall, not a climb).
RESIDUAL_RISE_MAX = 10.0

#: forceCoeffs' reference length: 1 m. It scales only the moment
#: coefficients, which no gate reads; the drag area needs none. Rejected:
#: ``aero_ref_length_m`` (the design's: the Reynolds number's length, read by
#: aero.regime; read here too it was one more key on a drag area for a number
#: nothing judges, and one more rung of test_mutation's walk, a solve each).
L_REF = 1.0

#: The body's centre of rotation for forceCoeffs' moments: the origin. No gate
#: reads a moment, so no project states one. Rejected: a parameter (one more
#: input to key a drag area on, for a number nothing judges).
COFR = (0.0, 0.0, 0.0)


def _restore_zero(stage: str) -> None:
    """Each rank's ``0/`` replaced with the case's own fields after
    snappyHexMesh: decomposePar wrote them for the background mesh, whose
    patches snappy changed (OpenFOAM's ``restore0Dir -processor``). The case's
    0/ files name the body by its group and carry the constraint include, so
    the same files fit every rank."""
    src = os.path.join(stage, "0")
    ranks = sorted(n for n in os.listdir(stage) if re.fullmatch(r"processor\d+", n))
    if not ranks:
        raise T.RunError("decomposePar wrote no processor directories")
    for name in ranks:
        dst = os.path.join(stage, name, "0")
        if os.path.isdir(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)


def _last_dir(path: str):
    """The name of the numerically latest time directory under ``path``, or
    None."""
    best = None
    try:
        names = os.listdir(path)
    except OSError:
        return None
    for name in names:
        try:
            t = float(name)
        except ValueError:
            continue
        if math.isfinite(t) and os.path.isdir(os.path.join(path, name)) \
                and (best is None or t > best[0]):
            best = (t, name)
    return None if best is None else best[1]


def _fields(ctx: GateContext, stage: str):
    """``{stage, time, sha256}`` of the picture files the function objects
    wrote at the last iteration (``_fo.picture_files``), or None when they
    wrote none. ``stage`` is written ``<out>/...``, relative to the gate's out
    directory, as ``BoundContext.bind`` reads it. A file the run did not write
    is left out: the picture that needs it says so, and no verdict depends on
    it. The files stay in the out directory and are never cited as evidence:
    the body and the wake surface are about 3 MB each on the motorBike (P0),
    past what a page publishes."""
    time = _last_dir(os.path.join(stage, "postProcessing", FO.SURFACES))
    if time is None:
        return None
    rel = os.path.relpath(stage, ctx.out_path()).replace(os.sep, "/")
    sha = {}
    for name in FO.picture_files(time):
        path = F.case_file(stage, name)
        if os.path.isfile(path):
            sha[name] = _sha256(path)
    return {"stage": f"<out>/{rel}", "time": time, "sha256": sha}


def _coefficients(stage: str, u: float) -> "P.Coefficients":
    """forceCoeffs' history, held to the reference values the pack wrote:
    T.RunError on a file that is missing or reports another speed, length,
    area or drag direction."""
    return _coefficients_at(os.path.join(stage, "postProcessing", FO.FORCE, "0",
                                         "coefficient.dat"), u)


def _coefficients_at(path: str, u: float) -> "P.Coefficients":
    """``_coefficients`` of the file at ``path``."""
    if not os.path.isfile(path):
        raise T.RunError("simpleFoam wrote no forceCoeffs history: the body group may name "
                         "no patch", [])
    try:
        co = P.coefficients(path)
    except ValueError as exc:
        raise T.RunError(str(exc), [path])

    def num(key):
        try:
            return float(co.header.get(key, "nan"))
        except ValueError:
            return float("nan")
    drag = co.header.get("dragDir", "")
    if not (abs(num("magUInf") - u) <= 1e-9 * u and num("lRef") == L_REF
            and num("Aref") == 1.0 and F.vector(F.parse(f"d {drag};").entry("d").value[0])
            == (1.0, 0.0, 0.0)):
        raise T.RunError(f"forceCoeffs ran with magUInf {co.header.get('magUInf')}, lRef "
                         f"{co.header.get('lRef')}, Aref {co.header.get('Aref')}, dragDir "
                         f"{drag}: not the pack's", [path])
    if not co.cda or not T.finite(*co.cda):
        raise T.RunError("the drag area holds a value that is not finite", [path])
    return co


def _history(ctx: GateContext, gid: str, co) -> str:
    """The drag area's history beside summary.json: one row per iteration,
    ``iteration`` and ``cda_m2``. A CSV, never a list in summary.json
    (cfd-openfoam's rule: the site's prose scan reads every number of a JSON
    evidence file). The chart draws these numbers and computes none."""
    path = ctx.out_path(PACK, gid.replace(".", "_"), "history.csv")
    with open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write("iteration,cda_m2\n")
        for it, v in zip(co.iterations, co.cda):
            fh.write(f"{it},{v!r}\n")
    return path


@gate(
    id="aero.converged",
    basis="established",
    title="simpleFoam settled on the base mesh: the drag area's iterative uncertainty is inside its ceiling",
    claims=[GUARD_TAGS["aero.converged"]],
    tier=Tier.SOLVE,
    settles="aero solver convergence",
    requires_tools=list(T.WRAPPERS),
    needs=["aero.mesh_quality", "aero.regime", "aero.reference", "aero.domain"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:cut_short",
        note="the baseline spheroid with endTime 110: the window of 100 iterations closes "
             "inside the start-up, and the drag area still swings by about 11%",
    ),
)
def converged(ctx: GateContext) -> Verdict:
    """The case's own mesh (the base mesh, as aero.mesh_quality builds it),
    then ``potentialFoam -writephi`` and ``simpleFoam`` on ``aero_ranks``
    ranks, with the pack's function objects (``_fo.functions``). Passes only
    when the run printed ``End`` on every rank, the window of the last
    ``WINDOW`` iterations filled, no residual climbed more than
    ``RESIDUAL_RISE_MAX`` times over its window's least, and the drag area's
    iterative uncertainty U_I = (max - min) / 2 over the window (ITTC
    7.5-03-01-01, the oscillatory case) is at most ``aero_iter_unc_max_pct`` of
    its mean. The value is U_I in % against that ceiling.

    Reported, not judged: the drift of the window's mean from the window
    before, the iterations in which k-omega SST bounded omega or k, and the
    layer coverage. The same run writes the picture files (the body with Cp,
    CpT and the speed, the wake surface CpT = 0, three wake cuts, two sets of
    stream tracks), named with their sha256 in summary.json for a viewgen to
    bind: a figure drawn from them is this run's, on the base mesh."""
    gid = "aero.converged"
    s = _run_settings(ctx, gid)
    if isinstance(s, Verdict):
        return s
    u = _settings_number(ctx, gid, *_U_INF)
    if isinstance(u, Verdict):
        return u
    group = ctx.param("aero_body_group")
    if not group:
        return _skip(gid, "no aero_body_group: the patch group of the body's surfaces, the "
                          "drag is summed over")
    got = _positive(ctx, gid, "aero_iter_unc_max_pct", DEFAULT_ITER_UNC_MAX_PCT)
    if isinstance(got, Verdict):
        return got
    ceiling, default = got
    marks = list(s["marks"]) + (["aero_iter_unc_max_pct"] if default else [])
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    inst, env = opened
    stage = _stage_dir(ctx, gid, "case")
    n, timeout = s["ranks"], s["timeout"]
    try:
        box, box_logs = _body_bounds(env, ctx, gid, s, timeout)
        _prepare(stage, s, FO.functions(group=str(group), u_inf=u, l_ref=L_REF, cofr=COFR,
                                        box=box))
        mesh = _mesh(env, stage, s, timeout)
        bad = mesh.problems(s["global"])
        if bad:
            # aero.mesh_quality passed this recipe, or this gate would not run,
            # but the mesh solved here is built again in this gate's own stage:
            # it is judged where it is solved. (P0 read the meshes of two runs
            # as differing; P3 traced that to scotch, which the pack no longer
            # uses. The rule holds whatever the cause.)
            raise T.RunError("the mesh this run built fails the rule aero.mesh_quality passed: "
                             + "; ".join(bad), mesh.logs)
        _restore_zero(stage)
        pot = P.run_parallel(env, stage, ["potentialFoam", "-writephi"], n, timeout)
        sol = P.run_parallel(env, stage, ["simpleFoam"], n, timeout)
        co = _coefficients(stage, u)
    except P.Timeout as exc:
        return _skip(gid, str(exc))
    except (T.RunError, ValueError, KeyError, OSError) as exc:
        return _error(gid, str(exc), getattr(exc, "evidence", []))
    logs = [*box_logs, *mesh.logs, pot.log, sol.log]
    blocks = P.iterations(sol.stdout)
    if len(blocks) != len(co.cda) or co.iterations != list(range(1, len(co.cda) + 1)):
        return _error(gid, f"simpleFoam's log has {len(blocks)} iterations and forceCoeffs "
                           f"{len(co.cda)} rows: the history is not the run's", logs)
    hist = _history(ctx, gid, co)
    hr = P.half_range(co.cda, WINDOW)
    dr = P.drift(co.cda, WINDOW)
    bounded = P.bounding(blocks)
    payload = {"stage": f"<out>/{os.path.relpath(stage, ctx.out_path()).replace(os.sep, '/')}",
               "mesh_level": "base", "u_inf_m_s": u,
               "time": (_fields(ctx, stage) or {}).get("time"),
               "flow_dir": [1.0, 0.0, 0.0], "up_dir": [0.0, 0.0, 1.0],
               "ground_z_m": s["case"].ground(), "body_bbox": [list(box[0]), list(box[1])],
               "cells": mesh.cells, "ranks": n, "iterations": len(co.cda), "window": WINDOW,
               "history": os.path.basename(hist), "bounding": bounded,
               "layer_coverage_pct": (mesh.snappy.layers or (0, 0, None))[2],
               "fields": _fields(ctx, stage), "install": inst.root, "build": inst.build,
               "pack_default": marks}
    said = (f"{mesh.cells} cells (base mesh), {mesh.layers()}; "
            + (", ".join(f"{k} bounded in {v} iterations" for k, v in sorted(bounded.items()))
               or "nothing bounded") + " (reported, not judged)")
    mark = f" [pack default: {', '.join(marks)}]" if marks else ""
    if hr is None:
        ev = _evidence(ctx, gid, payload)
        return Verdict(gate=gid, passed=False, evidence=[ev, hist, *logs],
                       detail=f"the window never filled: {len(co.cda)} iterations, fewer than "
                              f"the {WINDOW} the iterative uncertainty is taken over; {said}")
    u_i, lo, hi, mean = hr
    if not mean > 0:
        return _error(gid, f"the drag area's mean over the window is {mean:.6g} m^2: a body "
                           f"in a stream has a positive drag", [hist, *logs])
    pct = 100.0 * u_i / mean
    drift_pct = None if dr is None else 100.0 * (dr[0] - dr[1]) / abs(dr[0])
    payload.update({"cda_mean_m2": mean, "cda_last_m2": co.cda[-1], "window_lo_m2": lo,
                    "window_hi_m2": hi, "u_i_m2": u_i, "u_i_pct": pct,
                    "drift_pct": drift_pct})
    ev = _evidence(ctx, gid, payload)
    climbs = []
    for name, series in sorted(P.initial_residuals(blocks).items()):
        w = series[-WINDOW:]
        least = min(w)
        if least > 0 and w[-1] > RESIDUAL_RISE_MAX * least:
            climbs.append(f"{name} {w[-1]:.3g} at the last iteration, {w[-1] / least:.3g} "
                          f"times its window's least")
    first = len(co.cda) - WINDOW + 1
    drift = ("drift not computed (fewer than two windows)" if drift_pct is None else
             f"drift {drift_pct:+.3g}% from the window before (reported, not judged)")
    passed = pct <= ceiling and not climbs
    detail = (f"U_I {pct:.3g}% of the drag area {mean:.6g} m^2 over iterations {first}-"
              f"{len(co.cda)} ({'within' if pct <= ceiling else 'past'} {ceiling:g}%){mark}; "
              f"{drift}; {said}")
    if climbs:
        detail = ("a residual climbs at the end of the run: " + "; ".join(climbs)
                  + f" (more than {RESIDUAL_RISE_MAX:g} times). " + detail)
        return Verdict(gate=gid, passed=False, detail=detail, evidence=[ev, hist, *logs])
    return Verdict(gate=gid, passed=passed,
                   measured=_shown(pct, lambda x: x <= ceiling, passed, 6), limit=ceiling,
                   comparator="<=", units=PCT, detail=detail, evidence=[ev, hist, *logs])


# --------------------------------------------------------------------------- #
# what a solve leaves, read once
# --------------------------------------------------------------------------- #
def _inlet_speed(case: Case) -> float:
    """The speed the case runs at: its inlet's ``fixedValue`` along +x. The
    gates that solve a ladder or the wall make the drag area dimensionless by
    it. aero.reference, before them, holds it to ``aero_u_inf_m_s``.
    T.RunError when the inlet is not one uniform velocity along +x (aero.reference
    passed it, or these gates would not run: the two disagreeing).

    Rejected: ``aero_u_inf_m_s`` itself (aero.converged's: here it is one more
    key, each a rung of test_mutation's walk and a whole ladder a rung, for a
    number aero.reference already holds equal to this one)."""
    e = case.u_boundary.entry(case.inlet)
    vec = None
    if e is not None and e.is_dict and F.word(e.value, "type") == "fixedValue":
        vec = _uniform_vector(e.value)
    if vec is None or vec[1] != 0.0 or vec[2] != 0.0 or not vec[0] > 0:
        raise T.RunError(f"the inlet {case.inlet} is not one uniform velocity along +x, which "
                         f"aero.reference passed")
    return float(vec[0])


def _solve(env, stage: str, n: int, timeout: float, u: float):
    """potentialFoam and simpleFoam on the meshed stage: ``(Coefficients,
    iteration blocks, [logs])``, or T.RunError / P.Timeout."""
    _restore_zero(stage)
    pot = P.run_parallel(env, stage, ["potentialFoam", "-writephi"], n, timeout)
    sol = P.run_parallel(env, stage, ["simpleFoam"], n, timeout)
    co = _coefficients(stage, u)
    blocks = P.iterations(sol.stdout)
    _same_run(co, blocks, [pot.log, sol.log])
    return co, blocks, [pot.log, sol.log]


def _same_run(co, blocks, logs) -> None:
    if len(blocks) != len(co.cda) or co.iterations != list(range(1, len(co.cda) + 1)):
        raise T.RunError(f"simpleFoam's log has {len(blocks)} iterations and forceCoeffs "
                         f"{len(co.cda)} rows: the history is not the run's", logs)


def _settling(co, blocks, ceiling: float) -> dict:
    """aero.converged's rule on one run, as numbers and reasons: ``{u_i_m2,
    u_i_pct, mean_m2, why}``, ``why`` empty when the window filled, no residual
    climbed past ``RESIDUAL_RISE_MAX`` times its window's least and U_I is at
    most ``ceiling`` % of the mean. T.RunError on a mean that is not positive."""
    hr = P.half_range(co.cda, WINDOW)
    if hr is None:
        return {"u_i_m2": None, "u_i_pct": None, "mean_m2": None,
                "why": [f"the window never filled: {len(co.cda)} iterations, fewer than the "
                        f"{WINDOW} the iterative uncertainty is taken over"]}
    u_i, _lo, _hi, mean = hr
    if not mean > 0:
        raise T.RunError(f"the drag area's mean over the window is {mean:.6g} m^2: a body in "
                         f"a stream has a positive drag")
    pct = 100.0 * u_i / mean
    why = []
    for name, series in sorted(P.initial_residuals(blocks).items()):
        w = series[-WINDOW:]
        least = min(w)
        if least > 0 and w[-1] > RESIDUAL_RISE_MAX * least:
            why.append(f"{name}'s residual climbs to {w[-1] / least:.3g} times its window's "
                       f"least at the last iteration")
    if not pct <= ceiling:
        why.append(f"U_I {pct:.3g}% of the drag area, past {ceiling:g}%")
    return {"u_i_m2": u_i, "u_i_pct": pct, "mean_m2": mean, "why": why}


# --------------------------------------------------------------------------- #
# the wall
# --------------------------------------------------------------------------- #
#: The top of the band in which the pack's wall function stands for the
#: boundary layer: y+ 300. Spalding's single formula (J. Appl. Mech. 28:455,
#: 1961), the pack's ``nutUSpaldingWallFunction``, holds from the wall through
#: the log layer, and the log layer ends at about y/delta 0.3, y+ a few hundred
#: at these Reynolds numbers (Pope, Turbulent Flows, 2000, sec. 7.1.4 and
#: Table 7.1: the log-law region y+ > 30, y/delta < 0.3). Above it the first
#: cell's centre is in the outer layer the function does not describe.
#: Rejected: 500 (the top some guides give at high Reynolds numbers; the
#: motorBike's 1.9e6 is not one); 30 as a floor too (Spalding's formula holds
#: in the viscous and buffer layers, so a low y+ is no fault of this model;
#: ``nutkWallFunction`` would need it, and the pack accepts that one only as
#: the tutorial's).
YP_HI = 300.0

#: The least share of the body's area that must have y+ at most `YP_HI`: 90%.
#: A body has stagnation points, separation lines and sharp edges where y+
#: falls or climbs whatever the mesh, so the rule is about the area the drag
#: comes from, not every face. Measured (P0, 2026-10-23): motorBike 96.4% at
#: L0 (the tutorial's 2-layer mesh), 99.4% at L1; the spheroid 100%; without
#: layers the spheroid 35.6%. Rejected: 100% (every snapped corner of the
#: motorBike past 300 would fail a mesh whose drag the wall function does
#: describe); 50% (half the body could sit outside the boundary layer the
#: drag depends on); weighting by face count (small faces at the edges would
#: count as much as the tank's).
YP_IN_MIN = 90.0

#: The bands the detail reports the area in: the viscous sublayer (y+ < 5),
#: the buffer layer (5-30), the log layer (30-300) and above (Pope, Table 7.1).
#: Reported, not judged; the picture's bands are the same (``_scales.YPLUS_BANDS``).
YPLUS_BANDS = (5.0, 30.0, 300.0)

#: How far the gate's own area and area-mean y+ of the body's surface may be
#: from OpenFOAM's ``surfaceFieldValue`` over the same patches: 1e-4 of each.
#: Measured (P0's motorBike L0, the vector area of each face): 2.9e-9 and
#: 3.5e-9 apart, with the face counts equal; the file holds 32-bit floats.
#: The two must agree or the surface the gate summed is not the body
#: OpenFOAM integrated: an error, naming both. Rejected: 1% (P0's first
#: route, ParaView's CellSize, was 0.8% off; a tolerance that wide passes a
#: surface that lost a part of the body); exact equality (32-bit points).
WALL_AGREE = 1e-4

YPLUS_UNITS = "%"


def _wall_stats(yplus_path: str, average_path: str) -> dict:
    """The body's y+ by area, from the surface OpenFOAM's ``surfaces``
    object wrote, held to OpenFOAM's own ``surfaceFieldValue`` of the same
    patches: ``{faces, area_m2, yplus_mean, yplus_mean_openfoam, in_pct,
    bands_pct}``, or T.RunError when they disagree."""
    try:
        wall = P.wall_surface(yplus_path, FO.YPLUS_FIELD)
        fv = P.field_value(average_path)
    except (ValueError, OSError) as exc:
        raise T.RunError(f"the body's y+ does not read: {exc}", [average_path])
    col = f"areaAverage({FO.YPLUS_FIELD})"
    theirs = fv.last.get(col)
    if not isinstance(theirs, float) or not math.isfinite(theirs):
        raise T.RunError(f"surfaceFieldValue wrote no {col}", [average_path])
    mine_area, mine_mean = wall.area, wall.mean()
    if len(wall.areas) != fv.faces or not (
            abs(mine_area - fv.area) <= WALL_AGREE * fv.area
            and abs(mine_mean - theirs) <= WALL_AGREE * abs(theirs)):
        raise T.RunError(
            f"the body's y+ surface is not the body OpenFOAM integrated: {len(wall.areas)} "
            f"faces, {mine_area:.9g} m^2, area-mean y+ {mine_mean:.9g} against OpenFOAM's "
            f"{fv.faces} faces, {fv.area:.9g} m^2, {theirs:.9g} (more than {WALL_AGREE:g} "
            f"apart)", [average_path])
    edges = (None,) + YPLUS_BANDS + (math.inf,)
    bands = [wall.share(lo, hi) for lo, hi in zip(edges, edges[1:])]
    return {"faces": len(wall.areas), "area_m2": mine_area, "yplus_mean": mine_mean,
            "yplus_mean_openfoam": theirs, "in_pct": wall.share(None, YP_HI),
            "bands_pct": bands}


def _bands_said(w: dict) -> str:
    b = w["bands_pct"]
    return (f"y+ < 5 on {b[0]:.3g}%, 5-30 on {b[1]:.3g}%, 30-300 on {b[2]:.3g}%, above 300 on "
            f"{b[3]:.3g}% of {w['area_m2']:.6g} m^2; area-mean y+ {w['yplus_mean']:.4g} "
            f"(OpenFOAM's {w['yplus_mean_openfoam']:.4g})")


@gate(
    id="aero.wall_treatment",
    basis="sourced",
    title="The wall function applies on the body: y+ at most 300 on at least 90% of its area",
    claims=[GUARD_TAGS["aero.wall_treatment"]],
    tier=Tier.SOLVE,
    settles="aero wall treatment",
    requires_tools=list(T.WRAPPERS),
    # A guard of the drag area, behind the run it measures: y+ of a run that
    # did not settle is the y+ of no flow.
    needs=["aero.converged"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:no_layers",
        note="the baseline spheroid meshed without its layers: the first cells stand off the "
             "body, and y+ is past 300 on most of its area",
    ),
)
def wall_treatment(ctx: GateContext) -> Verdict:
    """The base mesh solved again, with OpenFOAM's ``yPlus`` and the body's
    y+ surface (``_fo.wall_functions``): the share of the body group's area
    whose y+ is at most `YP_HI` must be at least `YP_IN_MIN` %. Each face's
    area is its vector area on the surface OpenFOAM wrote (``interpolate
    false``: the face's own wall value), and the area and the area-mean y+ are
    held to OpenFOAM's ``surfaceFieldValue`` of the same patches
    (`WALL_AGREE`). The value is the share in %.

    The run is held to aero.converged's rule too (the window, the residuals,
    U_I): this gate solves its own copy, and a run that did not settle where
    aero.converged's did is the two disagreeing, an error. Reported, not
    judged: the bands of y+ and the layer coverage. The same run writes the
    body's y+ surface, named with its sha256 in summary.json for the
    picture (``aero.wall``)."""
    gid = "aero.wall_treatment"
    s = _run_settings(ctx, gid)
    if isinstance(s, Verdict):
        return s
    group = ctx.param("aero_body_group")
    if not group:
        return _skip(gid, "no aero_body_group: the patch group of the body's surfaces, y+ is "
                          "summed over")
    got = _positive(ctx, gid, "aero_iter_unc_max_pct", DEFAULT_ITER_UNC_MAX_PCT)
    if isinstance(got, Verdict):
        return got
    ceiling, default = got
    marks = list(s["marks"]) + (["aero_iter_unc_max_pct"] if default else [])
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    _inst, env = opened
    stage = _stage_dir(ctx, gid, "case")
    n, timeout = s["ranks"], s["timeout"]
    try:
        u = _inlet_speed(s["case"])
        _prepare(stage, s, FO.wall_functions(group=str(group), u_inf=u))
        mesh = _mesh(env, stage, s, timeout)
        bad = mesh.problems(s["global"])
        if bad:
            raise T.RunError("the mesh this run built fails the rule aero.mesh_quality passed: "
                             + "; ".join(bad), mesh.logs)
        co, blocks, run_logs = _solve(env, stage, n, timeout, u)
        settle = _settling(co, blocks, ceiling)
        if settle["why"]:
            raise T.RunError("the run this gate solved fails the rule aero.converged passed: "
                             + "; ".join(settle["why"]), run_logs)
        time = _last_dir(os.path.join(stage, "postProcessing", FO.SURFACES))
        if time is None:
            raise T.RunError("simpleFoam wrote no y+ surface of the body", run_logs)
        files = FO.wall_files(time)
        wall = _wall_stats(F.case_file(stage, files["yplus"]), F.case_file(stage, files["average"]))
    except P.Timeout as exc:
        return _skip(gid, str(exc))
    except (T.RunError, ValueError, KeyError, OSError) as exc:
        return _error(gid, str(exc), getattr(exc, "evidence", []))
    logs = [*mesh.logs, *run_logs]
    rel = os.path.relpath(stage, ctx.out_path()).replace(os.sep, "/")
    payload = {"mesh_level": "base", "u_inf_m_s": u, "cells": mesh.cells, "ranks": n,
               "iterations": len(co.cda), "u_i_pct": settle["u_i_pct"],
               "layer_coverage_pct": (mesh.snappy.layers or (0, 0, None))[2],
               "yplus_top": YP_HI, "yplus_in_pct": wall["in_pct"],
               "yplus_bands_pct": dict(zip(("below_5", "5_to_30", "30_to_300", "above_300"),
                                           wall["bands_pct"])),
               "faces": wall["faces"], "area_m2": wall["area_m2"],
               "yplus_mean": wall["yplus_mean"], "yplus_mean_openfoam": wall["yplus_mean_openfoam"],
               "fields": {"stage": f"<out>/{rel}", "time": time,
                          "sha256": {files["yplus"]: _sha256(F.case_file(stage, files["yplus"]))}},
               "pack_default": marks}
    ev = _evidence(ctx, gid, payload)
    share = wall["in_pct"]
    passed = share >= YP_IN_MIN
    mark = f" [pack default: {', '.join(marks)}]" if marks else ""
    detail = (f"y+ at most {YP_HI:g} on {share:.4g}% of the body's area "
              f"({'at least' if passed else 'under'} {YP_IN_MIN:g}%); {_bands_said(wall)}; "
              f"{mesh.cells} cells (base mesh), {mesh.layers()} (reported, not judged){mark}")
    return Verdict(gate=gid, passed=passed,
                   measured=_shown(share, lambda x: x >= YP_IN_MIN, passed, 6), limit=YP_IN_MIN,
                   comparator=">=", units=YPLUS_UNITS, detail=detail, evidence=[ev, *logs])


# --------------------------------------------------------------------------- #
# the mesh ladder
# --------------------------------------------------------------------------- #
#: The ladder's refinement ratio when the project states none: 1.5 on every
#: block direction, so the background cells are 1, 1/1.5 and 1/2.25 of the
#: case's (the design's (20 8 8), (30 12 12), (45 18 18) on the tutorial's
#: block). snappyHexMesh refines by levels of its background cell, so every
#: cell of the mesh scales with it. Measured (P0): the motorBike's effective
#: ratios from cells 1.42 and 1.37, the spheroid's 1.43 and 1.47, past Celik's
#: 1.3. Marked ``[pack default]``. Rejected: 2 (Celik's example; the finest of
#: the motorBike would hold about 22 million cells, past the cap); 1.3 (the
#: effective ratio of P0's box ladder came out 1.25 and 1.29, under Celik's
#: 1.3, because the surface cells round to whole levels).
DEFAULT_LADDER_RATIO = 1.5
#: The ratios a project may state: 1.1 (the NASA NPARC floor quoted in
#: ``_gci.py``; below it rounding makes two levels one mesh) to 2.0 (the
#: finest mesh costs r^6 times the base mesh's cells, 64 at 2).
LADDER_RATIO_MIN, LADDER_RATIO_MAX = 1.1, 2.0

#: The least effective ratio between two levels, from their cell counts
#: ((N1/N2)^(1/3), Celik et al. 2008 Eq. 1-2): Celik's Step 2, "desirable that
#: the grid refinement factor ... be greater than 1.3". Judged after meshing,
#: before any solve: a ladder whose meshes are too alike fails without the hours
#: of solving it would cost. P0: ratio 1.3 on the box gave 1.25 and 1.29.
R_EFF_MIN = G.R_MIN_RECOMMENDED

#: The observed order the ladder must show, cfd-openfoam's ``P_MIN`` and
#: ``P_SLACK``: at least 0.95, and up to the scheme's formal order + 0.05 for
#: Celik's band at the observed order with Fs 1.25. Below 0.95 the meshes are
#: not in the asymptotic range, and a fail.
P_MIN, P_SLACK = 0.95, 0.05

#: The order rule above formal + `P_SLACK`. Eca & Hoekstra 2014 (J. Comput.
#: Phys. 262:104-130, sec. 2.4.1 and the summary of sec. 4): "A value of p
#: greater than the formal order of grid convergence (i.e. p > 2) is likely to
#: cause too small error estimates. In that case, delta_RE is dropped and
#: replaced by delta_1 or delta_2" (the error fitted at a fixed order, 1 or 2),
#: and "If 0.5 <= p < 2.1 and sigma < Delta_phi, Fs = 1.25. Otherwise, Fs =
#: 3." With three meshes the pack takes the formal order itself on the two
#: finest, Roache's two-grid GCI with an assumed order (Roache 1998,
#: Verification and Validation in Computational Science and Engineering, ch. 5;
#: ``_gci.gci_two_grid``, Fs = 3): GCI = 3 |eps21 / phi1| / (r21^p_formal - 1).
#: Measured: the spheroid's observed order is 2.72, where Celik's band at that
#: order is 4.1% and at the formal 2 with Fs 3 it is 15.6%. Rejected: refusing
#: the ladder (the design's first rule: every honest ladder of the baseline
#: was refused); the observed order with Fs 1.25 (Eca & Hoekstra: too small);
#: Eca & Hoekstra's least-squares choice between delta_1 and delta_2 (their
#: procedure "relies on the availability of at least four data points"; with
#: three, each fit has one degree of freedom, and the first-order fit of a
#: second-order scheme is the smaller error estimate of the two).
FS_FORMAL = G.FS_TWO_GRID

#: How far under the change between the two finest meshes the finest's
#: iterative uncertainty must be: a tenth (Celik et al. 2008, App. A, as
#: cfd-openfoam's ``ITERATIVE_FRACTION``). P0's motorBike: 0.75, a fail.
NOISE_FRACTION = 0.1

#: The share of their cell size a ``distance`` refinement region's distances
#: keep at each level: they are scaled with the background cell (1/r per
#: level), so the band of the finest cells around the body holds the same
#: number of cells on every mesh. P0's spheroid ladder did this and converged
#: monotonically. Rejected: distances kept in metres (the band of level-5
#: cells around the spheroid would grow from 2 to 4.3 cells across the
#: ladder: three meshes refined unlike one another, which Celik's procedure
#: assumes away). An ``inside`` region is a place, kept as written.

#: The format of a ladder record (``_Record``): its version, in its key.
RECORD_VERSION = 1

#: The files of the pack's code a record is keyed on: a record of another
#: version of the pack is never read.
_CODE = ("aero.py", "_par.py", "_fo.py", "_foam.py", "_tool.py", "_gci.py")

#: This process's mark on the ladder records it writes: a record is read only
#: by the process whose mark its manifest holds (``_Record``). Set once, at
#: import, and never written again. *Rejected:* a module dict of the records
#: this process wrote, shared across out directories (P6's second draft): a
#: memo the spine cannot empty (``nopekit doctor``'s ``memos`` row), where the
#: spine empties each memo it can before a gate runs, so that every cross-gate
#: channel is a file a trace sees.
_PROCESS = hashlib.sha256(os.urandom(32)).hexdigest()

GCI_UNITS = "%"
DRAG_UNITS = "m^2"
#: The comparators aero.drag_area judges: an upper limit. Its value is the top
#: of the band (the mesh's and the iterations' error on the side that fails),
#: the failing side only of an upper limit. cfd-openfoam's ``DP_COMPARATORS``,
#: for its reason. Rejected: the band's bottom for ">=" (no claim of this
#: pack has needed a lower limit on a drag area).
DRAG_COMPARATORS = ("<=", "<")


def _formal_order(case: Case) -> int:
    """1 when the momentum convection scheme (``div(phi,U)``, else
    ``default``) is first-order upwind, else 2: cfd-openfoam's rule for its
    reason (a first-order k or omega scheme does not set the drag's order)."""
    div = case.trees["system/fvSchemes"].sub("divSchemes")
    entry = None if div is None else div.entry("div(phi,U)") or div.entry("default")
    return 1 if entry is not None and "upwind" in F.words(entry) else 2


def _level_counts(case: Case, r: float, k: int) -> list:
    """Every block's cell counts at level ``k``: each direction times r^k,
    rounded half up, and at least one more cell than the level below
    (cfd-openfoam's ``counts``, for its reason: round-half-even left a
    direction at 2 -> 3 -> 3)."""
    out = []
    for old in case.counts:
        new = []
        for n in old:
            v = n
            for j in range(1, k + 1):
                v = max(v + 1, math.floor(n * r ** j + 0.5))
            new.append(v)
        out.append(tuple(new))
    return out


def _ladder_problems(case: Case) -> list[str]:
    """Why this case cannot be refined alike at every level, or []."""
    snappy = case.trees["system/snappyHexMeshDict"]
    layers = snappy.sub("addLayersControls")
    if case.add_layers and layers is not None and \
            (F.word(layers, "relativeSizes") or "true").lower() not in ON_WORDS:
        return ["addLayersControls has relativeSizes off: its layers are in metres, so the "
                "ladder's meshes would not be refined alike"]
    return []


def _scaled_regions(text: str, case: Case, f: float) -> str:
    """snappyHexMeshDict's text with each ``distance`` refinement region's
    distances divided by ``f`` (the level's r^k)."""
    regions = case.trees["system/snappyHexMeshDict"].sub("castellatedMeshControls/"
                                                          "refinementRegions")
    for e in (regions.entries if regions is not None else ()):
        if not e.is_dict or (F.word(e.value, "mode") or "") != "distance":
            continue
        lv = e.value.entry("levels")
        if lv is None or lv.is_dict or len(lv.value) != 1 or \
                not isinstance(lv.value[0], F.FoamList):
            raise T.RunError(f"refinement region {e.key}: no levels ((distance level) ...)")
        pairs = []
        for pair in lv.value[0]:
            v = F.vector(pair) if isinstance(pair, F.FoamList) else None
            if v is None or len(v) != 2:
                raise T.RunError(f"refinement region {e.key}: a level that is not (distance "
                                 f"level)")
            # Six significant digits, the precision foamDictionary -expand
            # prints at: OpenFOAM's reading and the reader's are then one
            # number (``_as_read``). What slipped through the first ladder
            # run: 0.03 / 1.5 written as 0.019999999999999997 read back as
            # 0.02, and every refined level was refused as another case.
            pairs.append(f"({v[0] / f:.6g} {int(v[1])})")
        text = F.set_entry(text, f"castellatedMeshControls/refinementRegions/{e.key}/levels",
                           "(" + " ".join(pairs) + ")")
    return text


#: What a ladder record holds of each level: the logs the meshes and the run
#: are judged from, and the files of the drag area and the wall.
RECORD_FILES = ("log.snappyHexMesh", "log.checkMesh", "log.simpleFoam", "coefficient.dat",
                "bodyYPlus.vtp", "surfaceFieldValue.dat")


def _digest_tree(path: str) -> list:
    out = []
    for dirpath, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            full = os.path.join(dirpath, name)
            out.append([os.path.relpath(full, path).replace(os.sep, "/"), _sha256(full)])
    return out


def _stdout_of(text: str) -> str:
    """A log's tool output without the stderr ``_par.run_parallel`` appends."""
    cut = text.rfind("\n--- stderr ---\n")
    return text if cut < 0 else text[:cut]


class Level:
    """One mesh of the ladder, read from its record: what the gates judge."""

    def __init__(self, k: int, counts: list, mesh: "Mesh", co, blocks, wall: dict, files: dict):
        self.k, self.counts, self.mesh, self.co, self.blocks = k, counts, mesh, co, blocks
        self.wall, self.files = wall, files

    @property
    def cells(self) -> int:
        return self.mesh.cells


class _Record:
    """A ladder solved: each level's logs, histories and wall files, copied
    under ``<out>/aero-openfoam/ladder/<key>/`` with a manifest of their
    sha256, keyed on every byte the tools read (``key``).

    **Why a record, and why only in the process that wrote it.**
    aero.drag_area judges the same three solves aero.mesh_independence just
    made, in the same check run (its prerequisite runs first, ``needs``), and
    solving them again would double the longest run of the pack (the
    motorBike's ladder is about 2.4 h, P0). So each gate that solves a ladder
    writes its record, and each gate judges only a record, whether it solved
    it now or found it: the hit and the miss read the same files through the
    same code. A record is read only by the process that wrote it
    (``_PROCESS``, in its manifest): every ``check``, ``export`` and ``gate
    selftest`` solves each ladder at least once, so the boundary that spends
    re-executes the solve, and no file under ``.nopekit/out`` from before the
    command can stand in for one (a planted record names no process that is
    running). A record lives in the out directory of the run that wrote it, so
    within one process it serves the runs that share that directory: the
    known-good control's four goalpost runs (the first solves, the next three
    read its record), and aero.drag_area's check run behind
    aero.mesh_independence's. So the path a check run takes is the one the
    qualification's goalpost runs take. What it rests on: P3 measured the
    pack's runs bit for bit the same on the same inputs (``hierarchical``;
    P0's scotch was not), so a record keyed on the inputs is the run they
    would give.

    *Rejected:* a record any later process may read (a run store: it needs
    ``export`` and ``--force`` to bypass it, a spine change, the design's P9);
    module memory (S-27's channel, which no trace sees); solving twice (twice
    the cost of the slowest gate, for the same numbers)."""

    def __init__(self, ctx: GateContext, key: str):
        self.key = key
        self.dir = os.path.join(os.path.dirname(ctx.out_path(PACK, "ladder", ".records")),
                                key[:32])

    def read(self):
        """``{levels: [{k, counts, files: {name: path}}]}`` when the record
        is whole, unchanged, this key's and this process's, else None."""
        where = self.dir
        try:
            with open(os.path.join(where, "manifest.json"), encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("version") != RECORD_VERSION \
                or data.get("key") != self.key or data.get("process") != _PROCESS:
            return None
        out = []
        try:
            for k, lv in enumerate(data.get("levels") or ()):
                files = {}
                for name, sha in (lv.get("files") or {}).items():
                    path = os.path.join(where, f"level{k}", name)
                    if not os.path.isfile(path) or _sha256(path) != sha:
                        return None
                    files[name] = path
                if lv.get("k") != k or sorted(files) != sorted(RECORD_FILES):
                    return None
                out.append({"k": k, "counts": [tuple(int(n) for n in c) for c in lv["counts"]],
                            "files": files})
        except (AttributeError, KeyError, TypeError, ValueError):
            return None
        return {"levels": out} if len(out) == 3 else None

    def write(self, levels: list) -> None:
        """``levels``: ``[(k, counts, {name: source path})]``. Written whole
        beside the record and moved into place, so a record is never half one."""
        tmp = self.dir + ".writing"
        _rm(tmp)
        manifest = {"version": RECORD_VERSION, "key": self.key, "process": _PROCESS,
                    "levels": []}
        for k, counts, sources in levels:
            dst = os.path.join(tmp, f"level{k}")
            os.makedirs(dst)
            files = {}
            for name in RECORD_FILES:
                shutil.copyfile(sources[name], os.path.join(dst, name))
                files[name] = _sha256(os.path.join(dst, name))
            manifest["levels"].append({"k": k, "counts": [list(c) for c in counts],
                                       "files": files})
        with open(os.path.join(tmp, "manifest.json"), "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, sort_keys=True)
        _rm(self.dir)
        os.replace(tmp, self.dir)


def _rm(path: str) -> None:
    """``path`` removed by ``rm -rf``, whether or not it is there: never a
    look at what an earlier run left (``_tool.stage``'s rule, for its reason:
    ``shutil.rmtree`` reads the old folders as inputs of this run)."""
    done = subprocess.run(["rm", "-rf", "--", path], stdin=subprocess.DEVNULL,
                          stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if done.returncode != 0:
        raise T.RunError(f"rm could not remove {path}: "
                         f"{done.stderr.decode(errors='replace').strip()}")


def _read_level(lv: dict, u: float) -> Level:
    """A Level from a record's files: the one reading of a solved level."""
    f = lv["files"]
    with open(f["log.snappyHexMesh"], encoding="utf-8", errors="replace") as fh:
        snappy_text = _stdout_of(fh.read())
    with open(f["log.checkMesh"], encoding="utf-8", errors="replace") as fh:
        check_text = _stdout_of(fh.read())
    with open(f["log.simpleFoam"], encoding="utf-8", errors="replace") as fh:
        solver_text = _stdout_of(fh.read())
    logs = [f["log.snappyHexMesh"], f["log.checkMesh"], f["log.simpleFoam"]]
    mesh = _read_mesh(snappy_text, check_text, logs, os.path.dirname(f["log.checkMesh"]),
                      f["log.checkMesh"])
    co = _coefficients_at(f["coefficient.dat"], u)
    blocks = P.iterations(solver_text)
    _same_run(co, blocks, logs)
    wall = _wall_stats(f["bodyYPlus.vtp"], f["surfaceFieldValue.dat"])
    return Level(lv["k"], lv["counts"], mesh, co, blocks, wall, f)


def _ladder(ctx: GateContext, gid: str):
    """The case's mesh and two refinements of it, each meshed with the
    pack's dictionaries and held to aero.mesh_quality's rule, then (only when
    every mesh passes, the cells increase and each effective ratio is at least
    `R_EFF_MIN`) each solved with the wall's function objects: ``(settings,
    ratio, marks, u, [Level coarse..fine], record key)``; ``(problems,
    evidence)`` when the meshes refuse the ladder before any solve; or a
    Verdict (a skip, an error)."""
    s = _run_settings(ctx, gid)
    if isinstance(s, Verdict):
        return s
    group = ctx.param("aero_body_group")
    if not group:
        return _skip(gid, "no aero_body_group: the patch group of the body's surfaces, the "
                          "drag is summed over")
    got = _positive(ctx, gid, "aero_ladder_ratio", DEFAULT_LADDER_RATIO)
    if isinstance(got, Verdict):
        return got
    r, r_default = got
    if not LADDER_RATIO_MIN <= r <= LADDER_RATIO_MAX:
        return _error(gid, f"aero_ladder_ratio {r:g} is outside [{LADDER_RATIO_MIN:g}, "
                           f"{LADDER_RATIO_MAX:g}]: below, rounding makes two levels one mesh; "
                           f"above, the finest mesh costs r^6 times the base mesh's cells")
    marks = list(s["marks"]) + (["aero_ladder_ratio"] if r_default else [])
    case = s["case"]
    why = _ladder_problems(case)
    if why:
        return why, []
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    inst, env = opened
    n, timeout = s["ranks"], s["timeout"]
    try:
        u = _inlet_speed(case)
        stages, counts_of = [], []
        functions = FO.wall_functions(group=str(group), u_inf=u)
        for k in range(3):
            stage = _stage_dir(ctx, gid, f"level{k}")
            counts = _level_counts(case, r, k)
            _prepare(stage, s, functions)
            if k:
                _write(stage, "system/blockMeshDict", case.block_mesh_at(counts))
                _edit(stage, "system/snappyHexMeshDict",
                      lambda text, f=r ** k: _scaled_regions(text, case, f))
            stages.append(stage)
            counts_of.append(counts)
        h = hashlib.sha256()
        code = [[name, _sha256(os.path.join(_HERE, name))] for name in _CODE]
        h.update(json.dumps({"version": RECORD_VERSION, "install": [inst.root, inst.build],
                             "ranks": n, "code": code,
                             "levels": [_digest_tree(st) for st in stages]},
                            sort_keys=True).encode())
        key = h.hexdigest()
        record = _Record(ctx, key)
        found = record.read()
        if found is None:
            got = _solve_ladder(env, case, s, stages, counts_of, u, timeout)
            if isinstance(got, tuple):
                return got
            record.write(got)
            found = record.read()
            if found is None:
                raise T.RunError("the ladder's record did not read back as it was written")
        levels = [_read_level(lv, u) for lv in found["levels"]]
    except P.Timeout as exc:
        return _skip(gid, str(exc))
    except (T.RunError, ValueError, KeyError, OSError) as exc:
        return _error(gid, str(exc), getattr(exc, "evidence", []))
    return s, r, marks, u, levels, key


def _solve_ladder(env, case: Case, s: dict, stages: list, counts_of: list, u: float,
                  timeout: float):
    """Mesh every level, judge the meshes, then solve every level:
    ``[(k, counts, {record file: path})]``, or ``(problems, logs)`` when the
    meshes refuse the ladder before any solve."""
    n = s["ranks"]
    meshes = [_mesh(env, stage, s, timeout, cells=_cells_of(counts_of[k]))
              for k, stage in enumerate(stages)]
    why = []
    for k, mesh in enumerate(meshes):
        bad = mesh.problems(s["global"])
        if bad:
            why.append(f"level {k} ({mesh.cells} cells) fails aero.mesh_quality's rule: "
                       + "; ".join(bad))
    cells = [m.cells for m in meshes]
    logs = [p for m in meshes for p in m.logs]
    if not why and not cells[0] < cells[1] < cells[2]:
        why.append(f"the refined meshes do not have more cells ({cells[0]}, {cells[1]}, "
                   f"{cells[2]})")
    if not why:
        r10, r21 = (cells[1] / cells[0]) ** (1 / 3), (cells[2] / cells[1]) ** (1 / 3)
        if r10 < R_EFF_MIN or r21 < R_EFF_MIN:
            why.append(f"effective refinement ratios {r10:.4g} and {r21:.4g} from the cells "
                       f"({cells[0]}, {cells[1]}, {cells[2]}): under {R_EFF_MIN:g} (Celik et "
                       f"al. 2008, Step 2), judged before any solve")
    if why:
        return why, logs
    out = []
    for k, (stage, mesh) in enumerate(zip(stages, meshes)):
        _co, _blocks, _logs = _solve(env, stage, n, timeout, u)
        time = _last_dir(os.path.join(stage, "postProcessing", FO.SURFACES))
        if time is None:
            raise T.RunError(f"level {k}: simpleFoam wrote no y+ surface of the body", _logs)
        files = FO.wall_files(time)
        out.append((k, counts_of[k], {
            "log.snappyHexMesh": os.path.join(stage, "log.snappyHexMesh"),
            "log.checkMesh": os.path.join(stage, "log.checkMesh"),
            "log.simpleFoam": os.path.join(stage, "log.simpleFoam"),
            "coefficient.dat": os.path.join(stage, "postProcessing", FO.FORCE, "0",
                                            "coefficient.dat"),
            "bodyYPlus.vtp": F.case_file(stage, files["yplus"]),
            "surfaceFieldValue.dat": F.case_file(stage, files["average"])}))
    return out


def _cells_of(counts: list) -> int:
    return sum(a * b * c for a, b, c in counts)


def _judge_ladder(case: Case, levels: list, ceiling: float, cap: int) -> dict:
    """Celik et al. 2008 on the three drag areas (each level's window mean),
    with the pack's order rule: ``{why, res, gci_pct, rule, p_used, fs,
    phi_ext, noise, settle}``. ``why`` lists every reason the band is not
    believed: a level that fails aero.mesh_quality's or aero.converged's rule,
    cells that do not increase, an effective ratio under `R_EFF_MIN`, a
    convergence that is not monotone, an order under `P_MIN`, the finest
    level's U_I not a tenth of the change between the two finest."""
    why = []
    settle = []
    for lv in levels:
        st = _settling(lv.co, lv.blocks, ceiling)
        settle.append(st)
        if st["why"]:
            why.append(f"level {lv.k} ({lv.cells} cells) is not converged: {st['why'][0]}")
        bad = lv.mesh.problems(cap)
        if bad:
            why.append(f"level {lv.k} ({lv.cells} cells) fails aero.mesh_quality's rule: "
                       + "; ".join(bad))
    out = {"why": why, "res": None, "gci_pct": None, "rule": None, "p_used": None,
           "fs": None, "phi_ext": None, "noise": None, "settle": settle}
    if why:
        return out
    fine = list(reversed(levels))
    cells = [lv.cells for lv in fine]
    phi = [st["mean_m2"] for st in reversed(settle)]
    noise = max(st["u_i_m2"] for st in settle)
    out["noise"] = noise
    if not cells[0] > cells[1] > cells[2]:
        why.append(f"the refined meshes do not have more cells ({cells[2]}, {cells[1]}, "
                   f"{cells[0]})")
        return out
    res = G.gci(phi, cells=cells, dim=3, noise=noise)
    out["res"] = res
    said = (f"drag areas {phi[2]:.6g}, {phi[1]:.6g}, {phi[0]:.6g} m^2 coarse to fine on "
            f"{cells[2]}, {cells[1]}, {cells[0]} cells")
    if res.r21 < R_EFF_MIN or res.r32 < R_EFF_MIN:
        why.append(f"effective refinement ratios {res.r32:.4g} and {res.r21:.4g}: under "
                   f"{R_EFF_MIN:g} (Celik Step 2)")
    if res.convergence != G.MONOTONE_CONVERGENCE:
        why.append(f"{res.convergence} ({said}): Richardson extrapolation needs monotone "
                   f"convergence")
        return out
    if not res.p_converged or res.p is None:
        why.append(f"no unique observed order solves Celik's Eq. (3) ({said})")
        return out
    formal = _formal_order(case)
    if res.p < P_MIN:
        why.append(f"observed order {res.p:.3g} is under {P_MIN:g} ({said}): the meshes are "
                   f"not in the asymptotic range")
    u_fine = settle[-1]["u_i_m2"]
    if not u_fine <= NOISE_FRACTION * abs(res.eps21):
        why.append(f"the finest mesh's iterative uncertainty {u_fine:.3g} m^2 is not a tenth "
                   f"of the change between the two finest meshes {abs(res.eps21):.3g} m^2 "
                   f"(Celik App. A)")
    if why:
        return out
    if res.p > formal + P_SLACK:
        gci = G.gci_two_grid(phi[0], phi[1], res.r21, formal, fs=FS_FORMAL)
        a = res.r21 ** formal
        out.update(rule="formal", p_used=float(formal), fs=FS_FORMAL,
                   phi_ext=(a * phi[0] - phi[1]) / (a - 1.0))
    else:
        if res.gci_fine21 is None:
            why.append("the GCI could not be computed: " + "; ".join(res.warnings))
            return out
        gci = res.gci_fine21
        out.update(rule="observed", p_used=res.p, fs=res.fs, phi_ext=res.phi_ext21)
    out["gci_pct"] = 100.0 * gci
    return out


def _ladder_evidence(ctx, gid, case, levels, j, r, key, extra) -> list[str]:
    """summary.json (what the ladder picture draws: each level's cells,
    relative cell size and drag area, the extrapolation and the band's top),
    a history CSV per level, and each level's logs from the record."""
    finest = levels[-1].cells if levels else None
    rows = []
    for lv, st in zip(levels, j["settle"] if j else [{}] * len(levels)):
        rows.append({"k": lv.k, "cells": lv.cells, "counts": [list(c) for c in lv.counts],
                     "h_rel": (finest / lv.cells) ** (1.0 / 3.0),
                     "cda_m2": st.get("mean_m2"), "u_i_m2": st.get("u_i_m2"),
                     "u_i_pct": st.get("u_i_pct"), "iterations": len(lv.co.cda),
                     "yplus_in_pct": lv.wall["in_pct"],
                     "layer_coverage_pct": (lv.mesh.snappy.layers or (0, 0, None))[2]})
    payload = {"ladder_ratio": r, "record": key, "levels": rows,
               "formal_order": _formal_order(case), "window": WINDOW}
    if j and j.get("res") is not None:
        res = j["res"]
        payload["gci"] = {k: v for k, v in vars(res).items()}
    if j and j.get("gci_pct") is not None:
        payload.update(order_rule=j["rule"], order_used=j["p_used"], safety_factor=j["fs"],
                       gci_fine_pct=j["gci_pct"], cda_ext_m2=j["phi_ext"], h_rel_ext=0.0,
                       band_top_m2=rows[-1]["cda_m2"] * (1.0 + j["gci_pct"] / 100.0))
    payload.update(extra)
    hists = []
    for lv in levels:
        path = ctx.out_path(PACK, gid.replace(".", "_"), f"history_level{lv.k}.csv")
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write("iteration,cda_m2\n")
            for it, v in zip(lv.co.iterations, lv.co.cda):
                fh.write(f"{it},{v!r}\n")
        hists.append(path)
    logs = [p for lv in levels for p in lv.mesh.logs]
    return [_evidence(ctx, gid, payload), *hists, *logs]


@gate(
    id="aero.mesh_independence",
    basis="sourced",
    title="Three meshes agree: the drag area converges, and its grid convergence index is inside its limit",
    claims=[GUARD_TAGS["aero.mesh_independence"]],
    tier=Tier.SOLVE,
    settles="aero mesh independence",
    requires_tools=list(T.WRAPPERS),
    # A guard of the drag area, behind the base mesh's run: a ladder whose
    # first mesh does not settle shows nothing about the mesh.
    needs=["aero.converged"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:narrow_ladder",
        note="the baseline spheroid with a ladder ratio of 1.3: the surface cells round to "
             "whole levels, the effective ratios fall under Celik's 1.3, and the gate fails "
             "before it solves",
    ),
)
def mesh_independence(ctx: GateContext) -> Verdict:
    """The case's mesh and two refinements of it, each block direction times
    ``aero_ladder_ratio`` per level and each ``distance`` refinement region
    scaled with it, meshed with the pack's dictionaries and held to
    aero.mesh_quality's rule. Then, before any solve: the cells increase and
    each effective ratio from the cells is at least `R_EFF_MIN`. Then each
    level is solved and held to aero.converged's rule, and Celik et al.
    2008's GCI is taken on the three drag areas (``_gci.gci``, dim 3, the
    noise the largest U_I): the convergence must be monotone, the observed
    order at least `P_MIN`, the finest level's U_I at most a tenth of the
    change between the two finest; above the formal order + `P_SLACK` the band
    is taken at the formal order with Fs 3 (`FS_FORMAL`). The fine-grid GCI
    must be at most ``aero_gci_max_pct``. The value is the GCI in %.

    Reported, not judged: each level's y+ share, layer coverage and U_I. The
    asymptotic-range ratio is reported in the summary and never used (with the
    order observed on the same three meshes it is phi1/phi2,
    ``_gci.asymptotic_ratio``)."""
    gid = "aero.mesh_independence"
    lim = _number(ctx, "aero_gci_max_pct")
    if lim is None:
        return _skip(gid, "no aero_gci_max_pct: the largest mesh error band the claim "
                          "tolerates, in percent of the drag area (no source sets one for "
                          "every body)")
    if isinstance(lim, str):
        return _error(gid, lim)
    if not lim > 0:
        return _error(gid, f"aero_gci_max_pct is {lim:g}; it must be positive")
    got = _positive(ctx, gid, "aero_iter_unc_max_pct", DEFAULT_ITER_UNC_MAX_PCT)
    if isinstance(got, Verdict):
        return got
    ceiling, default = got
    got = _ladder(ctx, gid)
    if isinstance(got, Verdict):
        return got
    if len(got) == 2:
        why, logs = got
        return Verdict(gate=gid, passed=False, detail="; ".join(why)[:600], evidence=list(logs))
    s, r, marks, _u, levels, key = got
    marks = marks + (["aero_iter_unc_max_pct"] if default else [])
    case = s["case"]
    j = _judge_ladder(case, levels, ceiling, s["global"])
    ev = _ladder_evidence(ctx, gid, case, levels, j, r, key, {"pack_default": marks})
    cells = "/".join(str(lv.cells) for lv in levels)
    mark = f" [pack default: {', '.join(marks)}]" if marks else ""
    ys = ", ".join(f"{lv.wall['in_pct']:.4g}%" for lv in levels)
    tail = (f"{cells} cells (ratio {r:g}){mark}; y+ at most {YP_HI:g} on {ys} of the body "
            f"(reported, not judged)")
    if j["why"] or j["gci_pct"] is None:
        return Verdict(gate=gid, passed=False, detail="; ".join(j["why"])[:600] + f" ({tail})",
                       evidence=ev)
    res, gci = j["res"], j["gci_pct"]
    passed = gci <= lim
    rule = (f"observed order {res.p:.3g} above the formal {_formal_order(case)} + {P_SLACK:g}: "
            f"the band at the formal order with Fs {FS_FORMAL:g} (Eca and Hoekstra 2014)"
            if j["rule"] == "formal" else
            f"observed order {res.p:.3g}, Fs {j['fs']:g} (Celik et al. 2008)")
    return Verdict(gate=gid, passed=passed,
                   measured=_shown(gci, lambda x: x <= lim, passed, 6), limit=lim,
                   comparator="<=", units=GCI_UNITS,
                   detail=f"GCI {gci:.3g}% of the finest drag area "
                          f"{'within' if passed else 'past'} {lim:g}%: monotone, {rule}; drag "
                          f"area {res.phi[0]:.6g} m^2 on the finest mesh, {j['phi_ext']:.6g} at "
                          f"zero cell size; {tail}",
                   evidence=ev)


# --------------------------------------------------------------------------- #
# the drag area
# --------------------------------------------------------------------------- #
@gate(
    id="aero.drag_area",
    basis="established",
    title="The drag area of the finest mesh, with its mesh and iteration error bands, is under the limit",
    claims=[DRAG_TAG],
    tier=Tier.SOLVE,
    settles="drag area from cfd",
    requires_tools=list(T.WRAPPERS),
    # Its guards: the meshes agree, and the wall function applies. Each guard
    # passes this gate's own known-bad control (a bigger body): its edge is
    # isolated.
    needs=["aero.mesh_independence", "aero.wall_treatment"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:bigger_body",
        note="the baseline spheroid with every radius 15% larger: the drag area grows by "
             "about a third, past the baseline's limit",
    ),
)
def drag_area(ctx: GateContext) -> Verdict:
    """The drag area CdA (m^2, forceCoeffs with Aref 1) of the finest mesh of
    aero.mesh_independence's ladder, judged at the top of its band against the
    limit of the claim tagged ``drag-area`` (``ctx.acceptance``, the only gate
    of the pack that reads one): top = CdA_fine x (1 + GCI_fine) + U_I,fine, the
    mesh's band and the iterations' half-range added, never root-summed (the
    two are not independent errors of known distribution; a sum is the bound
    that holds whatever they are). The claim's units must be ``m^2`` and its
    comparator ``<=`` or ``<``, or the gate errors before it meshes anything.
    The value is the top, in m^2, the gate's own units.

    The ladder is the one aero.mesh_independence solved in this same run when
    it is there (``_Record``: the same inputs, read through the same code),
    else this gate solves it. A ladder that gives no band here, where
    aero.mesh_independence passed, is the two disagreeing: an error. Reported,
    not judged: the drag force F_D = 0.5 rho U^2 CdA in N, with
    ``aero_rho_kg_m3`` where the project states it."""
    gid = "aero.drag_area"
    acc = ctx.acceptance(DRAG_TAG)
    comparator = acc.comparator.value
    if str(acc.units or "").strip() != DRAG_UNITS:
        return _error(gid, f"the claim tagged {DRAG_TAG} states its limit in "
                           f"{str(acc.units or '')!r}; this gate computes the drag area in "
                           f"{DRAG_UNITS} (forceCoeffs with Aref 1): state the limit in "
                           f"{DRAG_UNITS}")
    if comparator not in DRAG_COMPARATORS:
        return _error(gid, f"the claim tagged {DRAG_TAG} states {comparator} {acc.limit:g} "
                           f"{DRAG_UNITS}; this gate judges only an upper limit "
                           f"({' or '.join(DRAG_COMPARATORS)}): the top of the band is the "
                           f"failing side only there")
    rho = _number(ctx, "aero_rho_kg_m3")
    if isinstance(rho, str):
        return _error(gid, rho)
    if rho is not None and not rho > 0:
        return _error(gid, f"aero_rho_kg_m3 is {rho:g}; it must be positive")
    got = _positive(ctx, gid, "aero_iter_unc_max_pct", DEFAULT_ITER_UNC_MAX_PCT)
    if isinstance(got, Verdict):
        return got
    ceiling, _default = got
    got = _ladder(ctx, gid)
    if isinstance(got, Verdict):
        return got
    if len(got) == 2:
        why, logs = got
        return _error(gid, "the meshes refuse the ladder aero.mesh_independence passed: "
                      + "; ".join(why)[:400], logs)
    s, r, marks, u, levels, key = got
    j = _judge_ladder(s["case"], levels, ceiling, s["global"])
    if j["why"] or j["gci_pct"] is None:
        return _error(gid, "the ladder gives no band here, where aero.mesh_independence passed: "
                      + "; ".join(j["why"])[:400],
                      _ladder_evidence(ctx, gid, s["case"], levels, j, r, key, {}))
    cda = j["res"].phi[0]
    if not cda > 0:
        return _error(gid, f"the finest mesh's drag area is {cda:.6g} m^2: a body in a stream "
                           f"has a positive drag")
    u_i = j["settle"][-1]["u_i_m2"]
    gci = j["gci_pct"]
    top = cda * (1.0 + gci / 100.0) + u_i
    force = None if rho is None else 0.5 * rho * u * u * cda
    ev = _ladder_evidence(ctx, gid, s["case"], levels, j, r, key,
                          {"cda_fine_m2": cda, "u_i_fine_m2": u_i, "top_m2": top,
                           "u_inf_m_s": u, "rho_kg_m3": rho, "force_n": force})
    passed = acc.holds(top)
    said_force = ("" if force is None else
                  f"; drag force {force:.4g} N at {u:g} m/s in air of {rho:g} kg/m^3 "
                  f"(reported, not judged)")
    return Verdict(gate=gid, passed=passed, measured=_shown(top, acc.holds, passed),
                   limit=acc.limit, comparator=comparator, units=DRAG_UNITS,
                   detail=f"drag area {cda:.6g} m^2 on the finest mesh ({levels[-1].cells} "
                          f"cells) + GCI {gci:.3g}% + U_I {u_i:.3g} m^2 = {top:.6g} m^2, "
                          f"{'within' if passed else 'past'} {acc.limit:g} m^2 "
                          f"({j['rule']} order {j['p_used']:.3g}, Fs {j['fs']:g}){said_force}",
                   evidence=ev)
