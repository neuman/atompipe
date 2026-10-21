# SPDX-License-Identifier: Apache-2.0
"""cfd-openfoam — gates for a flow solved by ESI OpenFOAM (openfoam.com).

    cfd.case_readable      tier 0  the case is one this pack can run and vouch for (the guard)
    cfd.regime             tier 0  laminar and incompressible: Reynolds and Mach numbers
    cfd.mesh_quality       tier 1  blockMesh, then checkMesh against stated limits
    cfd.converged          tier 2  simpleFoam met the pack's residual targets, and the number settled
    cfd.mesh_independence  tier 2  three meshes, each finer by a stated ratio: GCI (Celik et al. 2008)
    cfd.pressure_drop      tier 2  the static pressure drop between two planes, with its GCI band

**The guards come first.** A CFD number from a bad mesh, an unconverged run or
a mesh that still moves the answer is the standard way to make an assumption
look like proof. ``cfd.pressure_drop`` needs ``cfd.mesh_independence``, which
needs ``cfd.converged``, which needs ``cfd.mesh_quality`` and ``cfd.regime``,
which need ``cfd.case_readable``. A pressure drop never reaches a claim past a
guard that did not pass.

**Where each verdict comes from.** The tier-1 and tier-2 gates are OpenFOAM's own
output on a copy of the project's case staged under the gate's out directory:
checkMesh's text, simpleFoam's log, and the values of two ``surfaceFieldValue``
function objects THIS PACK writes into the copy (the project's own function
objects are removed, so a project cannot hand the gate its number). The pack also
writes its own residual targets into the copy. They read inside a subprocess the
trace cannot see into, so they are opaque and re-run on every check where
OpenFOAM exists. The GCI arithmetic (``_gci.py``) is the standard library's and is
held to the published worked examples. The tier-0 gates read the case with the
pack's own dictionary reader (``_foam.py``), so they run where OpenFOAM is not
installed and every file they decide on is keyed.

**What slipped through, and which gate it is for** (each found while this pack
was written, on v2606):

- ``cfd.converged``: simpleFoam exits 0 and prints ``End`` when it runs out of
  iterations. The baseline channel stopped at iteration 5 read its pressure drop
  0.69% high with exit 0; stopped at 10, 0.001% low. Its number looks right, so
  only the converged line can refuse it.
- ``cfd.mesh_quality``: checkMesh exits 0 on ``Failed 4 mesh checks.`` and passes
  non-orthogonality up to 90 degrees (70 to 90 is a warning). A 76-degree sheared
  mesh reads ``Mesh OK.``.
- ``cfd.mesh_independence``: Celik's Eq. (3a) returns a positive order for data
  that DIVERGE under refinement, and a refinement of the near-wall cells alone
  "converged" to a drag 0.37% off the benchmark with a GCI of 0.013%. The
  convergence is classified before the order is believed, and every cell is
  refined.
- every tool: a user's ``~/.OpenFOAM/2606/controlDict`` can turn floating-point
  trapping off, and a diverging run then carries NaN on; a case can compile and
  run its own C++. See ``_tool.py``.
- ``cfd.case_readable`` (the first review): the first reader judged a case by its
  literal text while OpenFOAM expands includes, conditions and macros and MERGES a
  repeated dictionary. A ``#sinclude`` merged ``scaleFactor 0.5`` into the pack's
  function objects and all six gates passed at half the pressure drop; an
  ``#if`` set the nu the solver ran (Re 4000 judged as Re 20); a constant/fvOptions
  source and a power-law laminar model passed as Newtonian. The reader now
  accepts a strict subset it can read exactly, and OpenFOAM's own expansion of the
  staged copy is held to it before every run.
- ``cfd.converged`` and ``cfd.mesh_independence`` (the same review): U relaxed to
  0.03 passed a run 9.7% from converged, and every count of 1 in a 2D case stayed
  1 on the ladder, so a one-cell wall layer was never refined.
- ``cfd.mesh_independence`` and ``cfd.pressure_drop`` (the second review):
  OpenFOAM's sampled plane reads a value whose error depends on where the plane
  falls in a cell; a ladder at r = 1.7 moved the planes through the cells, read
  that error as convergence, and passed a band under the exact pressure drop. A
  plane must now sit on a cell face or centre at every level. The same review
  found the convergence estimate fooled by an earlier oscillation and by a
  round-off floor applied too soon, and boundary conditions evaluated at run
  time (``exprFixedValue``, a ``uniformFixedValue`` table) let through.
- ``cfd.converged`` and ``cfd.mesh_independence`` (GitHub #15, Phase 0): the
  convergence estimate, the contraction of the last two windows of 10
  iterations, read real v2606 histories settled up to 23.4% from converged (a
  laminar pitzDaily under slow relaxation); ``_iter.py`` replaces it. The same
  phase found any ``upwind`` in divSchemes, even for a field a laminar run never
  solves, setting the formal order to 1, so a second-order ladder failed.

**Missing inputs skip; they never default**, except the limits marked
``[pack default]`` in a verdict. Which case, which planes, how fast, what density,
which limit and how much discretisation error the claim tolerates are the
project's to say.
"""
from __future__ import annotations

import csv
import json
import math
import os
import re

from nopekit.gates import gate, GateContext
from nopekit.modelio import load_path as _load_path
from nopekit.models import NegativeControl, Tier, Verdict

_HERE = os.path.dirname(os.path.abspath(__file__))
F = _load_path(os.path.join(_HERE, "_foam.py"))
T = _load_path(os.path.join(_HERE, "_tool.py"))
G = _load_path(os.path.join(_HERE, "_gci.py"))
I = _load_path(os.path.join(_HERE, "_iter.py"))

PACK = "cfd-openfoam"

#: The solvers this pack runs: steady, incompressible, isothermal. Phase 1 of
#: GitHub #15. Rejected for now: icoFoam and pimpleFoam (transient: the ladder
#: would also have to scale the time step, and "converged" means another thing),
#: buoyant and compressible solvers (other physics, other guards).
APPLICATIONS = ("simpleFoam",)

#: The turbulence model this pack vouches for: none. A laminar run needs no
#: wall function, no y+ band and no model constant, so the guards here are the
#: whole of it. Rejected for now: RAS (needs a y+ guard per wall treatment and a
#: Reynolds-number range per model; issue #15's operating context).
SIMULATION_TYPES = ("laminar",)

#: The Reynolds number, on the hydraulic diameter, below which this pack calls
#: a duct flow laminar: 2300, the textbook onset of transition in a pipe
#: (fluids-analytic's ``fluid.flow_regime`` uses the same). A laminar solver
#: past it solves a flow that is not there. Rejected: 2000 (a common conservative
#: value; it would refuse flows that are laminar in practice); 4000 (the end of
#: the transition band: laminar is not guaranteed anywhere in it). Internal
#: flow only: a body in an open stream has other limits (phase 2).
RE_LAMINAR_MAX = 2300.0

#: The Mach number below which density changes stay under about 5% (rho0/rho =
#: (1 + 0.2 Ma^2)^2.5 gives 4.5% at 0.3): the textbook limit for an
#: incompressible solver. Rejected: 0.2 (stricter than any CFD guide asks); none
#: (a 0.1 mm air passage at Re 2000 runs at about Mach 0.9).
MACH_MAX = 0.3

#: The loosest residual target cfd.converged will write: OpenFOAM's residuals
#: are normalised, start near 1, and Celik et al. 2008 (p. 2) ask for "at least
#: three (preferably four) orders of magnitude decrease"; 1e-4 is the fourth. A
#: looser target is refused, never run. Rejected: 1e-3 (the simpleFoam
#: tutorials' value; a channel at 1e-3 still moves its pressure drop in the
#: third digit).
RESIDUAL_TARGET_MAX = 1e-4

#: How settled the pressure drop must be: its estimated remaining change
#: (``_iter.remaining``, Eca & Hoekstra's iterative-error estimate read
#: pessimistically; GitHub #15, Phase 0) at most 1e-3 of itself. Residuals
#: measure the equations' imbalance, not the number a claim is about. Rejected: the
#: change over one window of 10 iterations taken as the error (it passed a run
#: 9.7% from converged); the contraction of the last two windows of 10 (until
#: P0.1: on real v2606 histories it read settled up to 23.4% from converged; see
#: _iter.py).
STABLE_TOL = 1e-3

#: How far the mean velocity through the upstream plane may sit from the one
#: the project states (cfd_velocity_m_s), which cfd.regime judged the Reynolds
#: number on: 2%. A mismatch means the regime was judged on another flow, and is
#: an error. Rejected: 10% (lets a quarter of the transition margin go).
VELOCITY_TOL = 0.02

#: The refinement ratios cfd.mesh_independence takes. Celik et al. 2008, Step
#: 2: "It is desirable that the grid refinement factor ... be greater than 1.3".
#: The ceiling, 3, is the cost: three levels at r=3 are 81x the cells in 2D and
#: 729x in 3D. Rejected: NPARC's floor of 1.1 (differences between grids sink
#: into the iterative noise).
REFINEMENT_MIN, REFINEMENT_MAX = 1.3, 3.0

#: The band of observed orders the GCI is believed in: 0.95 to the formal order
#: + 0.05 (Eca & Hoekstra, 3rd Lisbon Workshop 2008, for Fs = 1.25). An order
#: outside it means the meshes are not in the asymptotic range, and the
#: Richardson estimate is not to be trusted. Rejected: Klaij, Vaz & Eca 2014's
#: 0.5 to 2.1 ("unrealistic" outside); it accepts p = 0.6 with Fs = 1.25.
P_MIN, P_SLACK = 0.95, 0.05

#: The iterative error must be at least ten times below the discretisation
#: error it is compared with (Celik et al. 2008, Appendix A).
ITERATIVE_FRACTION = 0.1

#: The mesh-quality limits used when the project states none, marked
#: ``[pack default]`` in the verdict: OpenFOAM's own meshQualityDict defaults
#: (maxNonOrtho 65, maxInternalSkewness 4) and checkMesh's aspect-ratio limit
#: (1000). Rejected: checkMesh's non-orthogonality limit (70 is a warning only;
#: it fails at 90).
DEFAULT_MAX_NON_ORTHO_DEG = 65.0
DEFAULT_MAX_SKEWNESS = 4.0
DEFAULT_MAX_ASPECT_RATIO = 1000.0

#: The residual target when the project states none: 1e-6, marked ``[pack
#: default]``. The laminar channel prototype converged at p 1e-6 / U 1e-7 in 137
#: iterations and moved its pressure drop by under 1e-9 relative after.
DEFAULT_RESIDUAL_TARGET = 1e-6

#: The refinement ratio when the project states none: 2, so each level doubles
#: the cells along every refined direction and the cell count of a level is
#: exact. Marked ``[pack default]``.
DEFAULT_REFINEMENT_RATIO = 2.0

#: Ten minutes per tool run. The baseline's finest mesh solves in about 3 s; a
#: run past this is a hang or a case far outside what this pack is for. A
#: timeout is a skip (nothing was shown), never a fail.
DEFAULT_TIMEOUT_S = 600.0

#: What the pack's function objects are called in the staged copy.
UPSTREAM, DOWNSTREAM = "nopekit_upstream", "nopekit_downstream"

#: The precision the pack's function objects write their values at: 12, so 13
#: significant digits (they write in scientific notation). The convergence
#: estimate needs a change of ``_iter.ROUNDOFF`` (1e-8) of the value resolved,
#: and refuses a history printed in steps of one quantum (``_iter.STAIRS``).
#: Measured in GitHub #15 Phase 0: a converged laminar pitzDaily (nu 1e-3, ESI
#: v2606) read settled at 1702 cut points printed to 13 digits and at 18 printed
#: to 7. Rejected: the case's own writePrecision, which set it until P0.1 (6 when
#: the case states none, OpenFOAM's default: 7 digits, so a converged run almost
#: never reads settled, a false fail; the baseline states 10, but a project's
#: case need not).
WRITE_PRECISION = 12


def _skip(gid: str, reason: str) -> Verdict:
    return Verdict(gate=gid, passed=False, skipped=True, skip_reason=reason)


def _error(gid: str, message: str, evidence=None) -> Verdict:
    return Verdict(gate=gid, passed=False, error=message, evidence=list(evidence or []))


_NO_CASE = ("no cfd_case: the OpenFOAM case directory this pack runs, relative to the "
            "project root — this pack will not guess which case you mean")


def _case(ctx: GateContext) -> str | None:
    rel = ctx.param("cfd_case")
    if not rel:
        return None
    rel = str(rel)
    return rel if os.path.isabs(rel) else os.path.join(ctx.root, rel)


def _number(ctx: GateContext, key: str):
    """The finite number ``key`` holds, None when absent, or a str naming what
    is wrong with it."""
    raw = ctx.param(key)
    if raw is None:
        return None
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


def _history(ctx: GateContext, gid: str, name: str, dp: list, rho=None) -> str:
    """Write a pressure drop's history beside summary.json, as ``name``: one row per
    iteration (counted from 1), the value (``dp_pa`` when ``rho`` is given, else the
    solver's ``dp_m2_s2``) and ``change_pct``, 100 x |change from the iteration
    before| / |last value| (empty on the first row): the changes the estimate reads.
    A chart of the history and its estimate (GitHub #15, Phase 2) draws these
    numbers and computes none. A CSV, never a list in summary.json: the site's
    prose scan reads every number of a JSON evidence file as a match for a number
    in any unit, and a history is thousands of them (until P0.2, cfd.converged's
    summary held its whole history as a list)."""
    vals = dp if rho is None else [rho * v for v in dp]
    last = abs(vals[-1]) if vals else 0.0
    path = ctx.out_path(PACK, gid.replace(".", "_"), name)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        out = csv.writer(fh, lineterminator="\n")
        out.writerow(["iteration", "dp_m2_s2" if rho is None else "dp_pa", "change_pct"])
        for i, v in enumerate(vals):
            ok = i and 0 < last < math.inf
            out.writerow([i + 1, repr(v), repr(100.0 * abs(v - vals[i - 1]) / last) if ok else ""])
    return path


def _error_pct(dp: list):
    """The estimated remaining change as a percentage of the last value, for the
    evidence: None when there is no estimate (too few values, no steady decay, a
    value that is not finite; JSON holds no inf). The gate judges ``_settled``, not
    this number."""
    rem = I.remaining(dp)
    if rem is None or rem == math.inf or not (dp and 0 < abs(dp[-1]) < math.inf):
        return None
    return 100.0 * rem / abs(dp[-1])


# --------------------------------------------------------------------------- #
# reading the case
# --------------------------------------------------------------------------- #
class CaseProblem(Exception):
    """The case is not one this pack can run: a fail of the guard, naming why."""


#: The files a case may hold, and nothing else. A file the pack does not read is
#: a file whose effect it cannot vouch for. What slipped through the first
#: draft, which parsed every file but judged only a few: a constant/fvOptions
#: momentum source halved the pressure drop, and every gate passed. Rejected: a
#: list of files to refuse (fvOptions, fvModels, MRFProperties, porosity: each
#: release adds another).
REQUIRED_FILES = ("system/controlDict", "system/fvSchemes", "system/fvSolution",
                  "system/blockMeshDict", "constant/transportProperties",
                  "constant/turbulenceProperties", "0/U", "0/p")
#: Files no solver this pack runs reads.
INERT_FILES = ("system/decomposeParDict",)
#: A directory the pack ignores: the mesh it builds again from blockMeshDict.
IGNORED_DIRS = ("constant/polyMesh",)

#: The one directive a case may hold: the include ESI's own 0/ files carry in
#: each boundaryField, which sets the types of constraint patches (empty,
#: cyclic, wedge, symmetry) by patch group, from an install file. Every other
#: directive is refused: the reader does not evaluate it, and OpenFOAM does.
#: What slipped through the first draft: ``#if 1 / nu 5e-08; / #else / nu
#: 1e-05; / #endif``, read by the reader as nu 1e-05 (Re 20) while the solver
#: ran at Re 4000; a ``#sinclude`` that merged ``scaleFactor 0.5`` into the
#: pack's own function objects, so every gate passed at half the pressure drop;
#: and an include through a symlinked ``$FOAM_CASE`` that read a file outside
#: the case.
ALLOWED_DIRECTIVE = ("#includeEtc", '"caseDicts/setConstraintTypes"')

#: Where a quoted (regular-expression) keyword may stand: under patch names and
#: field names. Anywhere else it could stand for a keyword the pack decides on:
#: the first draft passed ``"typ(e)" codedFixedValue;``.
REGEX_PARENTS = ("boundaryField", "solvers", "equations", "fields")

#: The laminar stress model the pack vouches for: Stokes, a Newtonian fluid.
#: ``generalizedNewtonian`` (power law, Cross, ...) and the viscoelastic models
#: keep ``simulationType laminar`` and change the viscosity the Reynolds number
#: is judged on: the first draft passed a power-law case as Newtonian.
LAMINAR_MODELS = ("Stokes",)

#: The boundary conditions a 0/ file may use: each takes its value from the
#: case as written, nothing computed while the run goes. Rejected: allowing
#: every type but ``coded*`` (the second review passed ``exprFixedValue`` and a
#: ``uniformFixedValue`` table, values evaluated at run time that could differ
#: between the ladder's levels or iterations); ``flowRateInletVelocity`` (its rate
#: is a Function1, a table or an expression).
BOUNDARY_TYPES = ("fixedValue", "zeroGradient", "noSlip", "slip", "empty", "symmetry",
                  "symmetryPlane", "cyclic", "fixedGradient", "calculated", "inletOutlet",
                  "totalPressure", "pressureInletOutletVelocity", "fixedFluxPressure",
                  "surfaceNormalFixedValue", "movingWallVelocity")

#: momentumPredictor values that turn the U solve off. Then no U residual is
#: written, and a target for it says nothing.
OFF_WORDS = ("no", "off", "false", "n", "none")


def _listing(case: str) -> list[str]:
    """Every entry under the case's 0/, constant/ and system/, as relative
    paths, by listing the directories (never by asking whether a named file is
    there). A directory is listed with a trailing ``/`` and not entered: none is
    allowed but the ignored mesh.

    Decided only on what the spine keys for a listing (each name, and its kind
    or size, links followed). What slipped through the second review: a refusal
    of symbolic links decided on ``is_symlink()``, which no key holds, so a
    cached pass was served after a file was swapped for a link. A link is no
    longer refused: every byte read through it is keyed, the stage copies the
    bytes, and no include can follow one out of the case any more."""
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


def _check(d, rel: str, problems: list[str], parent: str = "", macros: bool = False) -> None:
    """Everything in a dictionary the reader cannot vouch for: a directive, a
    dictionary expansion, a macro (outside blockMeshDict), a computed value, a
    quoted keyword where a keyword the pack decides on could stand, a ``type``
    that is not a literal word, and every spelling of compiled code."""
    for e in d.entries:
        where = f"{rel}: {parent + '/' if parent else ''}{e.key}"
        if e.directive:
            if not (e.key == ALLOWED_DIRECTIVE[0] and F.words(e) == [ALLOWED_DIRECTIVE[1]]
                    and parent == "boundaryField" and rel.startswith("0/")):
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


def _vertices(bmd) -> list[tuple]:
    e = bmd.entry("vertices")
    if e is None or e.is_dict or len(e.value) != 1 or not isinstance(e.value[0], F.FoamList):
        raise CaseProblem("system/blockMeshDict has no vertices list")
    out = []
    for v in e.value[0]:
        if not isinstance(v, F.FoamList) or len(v) != 3:
            raise CaseProblem("system/blockMeshDict: a vertex that is not (x y z) (projected "
                              "vertices are not read)")
        out.append(tuple(_resolve(t, bmd, "vertex coordinate") for t in v))
    return out


def _blocks(bmd, nverts: int) -> list:
    """``[(count list, (nx, ny, nz), vertex ids, (grading word, its list or
    None))]`` for every block; CaseProblem on a form this reader will not scale."""
    e = bmd.entry("blocks")
    if e is None or e.is_dict or len(e.value) != 1 or not isinstance(e.value[0], F.FoamList):
        raise CaseProblem("system/blockMeshDict has no blocks list")
    out = []
    items = list(e.value[0])
    i = 0
    while i < len(items):
        it = items[i]
        if not (isinstance(it, F.Tok) and it.text == "hex"):
            raise CaseProblem(f"system/blockMeshDict: a block that is not 'hex ...' "
                              f"({getattr(it, 'text', type(it).__name__)!r})")
        j = i + 1
        if j >= len(items) or not isinstance(items[j], F.FoamList) or len(items[j]) != 8:
            raise CaseProblem("system/blockMeshDict: a hex block without its eight vertices")
        ids = []
        for t in items[j]:
            if not (isinstance(t, F.Tok) and t.kind == "number" and float(t.text).is_integer()
                    and 0 <= int(float(t.text)) < nverts):
                raise CaseProblem("system/blockMeshDict: a block vertex that is not one of the "
                                  "vertices")
            ids.append(int(float(t.text)))
        j += 1
        if j < len(items) and isinstance(items[j], F.Tok) and items[j].kind == "word" \
                and not items[j].text.endswith("Grading"):
            j += 1                                            # a zone name
        if j >= len(items) or not isinstance(items[j], F.FoamList) or len(items[j]) != 3:
            raise CaseProblem("system/blockMeshDict: a hex block with no (nx ny nz) cell counts")
        counts_list = items[j]
        counts = []
        for t in counts_list:
            v = _resolve(t, bmd, "cell count")
            if v != int(v) or v < 1:
                raise CaseProblem(f"system/blockMeshDict: cell count {v:g} is not a whole "
                                  f"number of cells")
            counts.append(int(v))
        j += 1
        grading = ("simpleGrading", None)
        if j < len(items) and isinstance(items[j], F.Tok) and items[j].text.endswith("Grading"):
            kind = items[j].text
            j += 1
            if j < len(items) and isinstance(items[j], F.FoamList):
                grading = (kind, items[j])
                j += 1
        out.append((counts_list, tuple(counts), tuple(ids), grading))
        i = j
    if not out:
        raise CaseProblem("system/blockMeshDict has no blocks")
    return out


def _patches(bmd) -> dict:
    """``{patch name: (type, [faces as vertex-id tuples])}`` from a
    blockMeshDict's boundary list."""
    e = bmd.entry("boundary")
    if e is None or e.is_dict or len(e.value) != 1 or not isinstance(e.value[0], F.FoamList):
        raise CaseProblem("system/blockMeshDict has no boundary list (the old 'patches' "
                          "form is not read)")
    items = list(e.value[0])
    if len(items) % 2:
        raise CaseProblem("system/blockMeshDict: the boundary list ends in the middle of an entry")
    out = {}
    for name, body in zip(items[0::2], items[1::2]):
        if not isinstance(name, F.Tok) or not isinstance(body, F.FoamDict):
            raise CaseProblem("system/blockMeshDict: a boundary entry that is not 'name { ... }'")
        faces = []
        fe = body.entry("faces")
        if fe is not None and not fe.is_dict and len(fe.value) == 1 \
                and isinstance(fe.value[0], F.FoamList):
            for f in fe.value[0]:
                if isinstance(f, F.FoamList) and all(
                        isinstance(t, F.Tok) and t.kind == "number" for t in f):
                    faces.append(tuple(int(float(t.text)) for t in f))
        out[name.text] = (F.word(body, "type") or "", faces)
    return out


def _sub(a, b):
    return tuple(x - y for x, y in zip(a, b))


def _unit(v):
    m = math.sqrt(sum(c * c for c in v))
    return None if m == 0 else tuple(c / m for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


class Case:
    """What the gates read from a case, read once: a strict subset of what
    OpenFOAM accepts, the subset this pack can read exactly as OpenFOAM does."""

    def __init__(self, case: str):
        if not os.path.isdir(case):
            raise CaseProblem(f"no case directory at {case}")
        self.path = case
        files = _listing(case)
        extra = [f for f in files if f not in REQUIRED_FILES + INERT_FILES]
        if extra:
            snappy = " (snappyHexMesh is phase 2 of issue #15)" if any(
                "snappyHexMeshDict" in f for f in extra) else ""
            raise CaseProblem(f"the case holds {', '.join(extra[:3])}"
                              f"{' and more' if len(extra) > 3 else ''}: this pack reads only "
                              f"{', '.join(REQUIRED_FILES)} and will not vouch for a file it "
                              f"does not read{snappy}")
        missing = [f for f in REQUIRED_FILES if f not in files]
        if missing:
            raise CaseProblem(f"the case has no {', '.join(missing)}")
        self.files = files
        trees = {rel: _read(case, rel) for rel in files}
        problems: list[str] = []
        for rel, d in trees.items():
            _check(d, rel, problems, macros=rel == "system/blockMeshDict")
        if problems:
            raise CaseProblem("; ".join(problems[:4]) + (
                f" (and {len(problems) - 4} more)" if len(problems) > 4 else ""))
        control = trees["system/controlDict"]
        if control.entry("libs") is not None:
            raise CaseProblem("system/controlDict loads libraries ('libs'): code this pack "
                              "cannot vouch for")
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
        turb = trees["constant/turbulenceProperties"]
        self.simulation_type = F.word(turb, "simulationType")
        if self.simulation_type not in SIMULATION_TYPES:
            raise CaseProblem(f"simulationType {self.simulation_type!r}: this pack runs "
                              f"laminar flow only (turbulence models are a later phase of "
                              f"issue #15)")
        laminar = turb.sub("laminar")
        if laminar is not None:
            model = F.word(laminar, "model") or F.word(laminar, "laminarModel")
            if model not in LAMINAR_MODELS:
                raise CaseProblem(f"laminar model {model!r}: this pack vouches for Stokes (a "
                                  f"Newtonian fluid) only")
        transport = trees["constant/transportProperties"]
        model = F.word(transport, "transportModel")
        if model != "Newtonian":
            raise CaseProblem(f"transportModel {model!r}: this pack reads a Newtonian nu only")
        try:
            self.nu = F.scalar(transport, "nu")
        except F.Unresolved as exc:
            raise CaseProblem(f"constant/transportProperties: {exc}")
        if self.nu is None or not (self.nu > 0 and math.isfinite(self.nu)):
            raise CaseProblem("constant/transportProperties has no positive nu")
        simple = trees["system/fvSolution"].sub("SIMPLE")
        if simple is None:
            raise CaseProblem("system/fvSolution has no SIMPLE dictionary")
        if (F.word(simple, "momentumPredictor") or "yes").lower() in OFF_WORDS:
            raise CaseProblem("momentumPredictor is off: U is never solved, so a residual "
                              "target for it says nothing")
        self.formal_order = _formal_order(trees["system/fvSchemes"])
        with open(F.case_file(case, "system/blockMeshDict"), encoding="utf-8") as fh:
            self.block_mesh_text = fh.read()
        bmd = F.parse(self.block_mesh_text)
        verts = _vertices(bmd)
        self.verts = verts
        edges = bmd.entry("edges")
        self.curved = edges is not None and not edges.is_dict and any(
            isinstance(v, F.FoamList) and len(v) > 0 for v in edges.value)
        self.blocks = _blocks(bmd, len(verts))
        self.patches = _patches(bmd)
        self.dim, self.thin = _thin_directions(verts, self.blocks, self.patches)

    def cells(self) -> int:
        return sum(a * b * c for _l, (a, b, c), _ids, _g in self.blocks)

    def counts(self, r: float, k: int) -> list[tuple]:
        """Every block's cell counts at ladder level ``k``: each direction
        multiplied by r^k, rounded half up, and at least one more cell than at
        the level below (the first draft's round-half-even left a direction at
        2 -> 3 -> 3 at r = 1.3); the one-cell direction of a 2D case stays one."""
        out = []
        for b, (_l, old, _ids, _g) in enumerate(self.blocks):
            new = []
            for d, n in enumerate(old):
                if self.thin[b] == d:
                    new.append(n)
                    continue
                v = n
                for j in range(1, k + 1):
                    v = max(v + 1, math.floor(n * r ** j + 0.5))
                new.append(v)
            out.append(tuple(new))
        return out


def _formal_order(schemes) -> int:
    """1 when the momentum convection scheme is first-order upwind, else 2: the
    scheme of ``div(phi,U)``, or ``default`` where the case gives none (the entry
    OpenFOAM uses for it). What slipped through until P0.1: any ``upwind`` in any
    divSchemes entry gave order 1, so a leftover ``div(phi,k)`` for a field a
    laminar run never solves set the band to 0.95-1.05, and a second-order run
    failed at its observed order 2."""
    div = schemes.sub("divSchemes")
    entry = None if div is None else div.entry("div(phi,U)") or div.entry("default")
    return 1 if entry is not None and "upwind" in F.words(entry) else 2


def _thin_directions(verts, blocks, patches):
    """``(mesh dimension, [the one-cell direction of each block, or None])``.

    2D only when the empty patches have faces, all parallel, and every block is
    one cell thick across them: the direction is found from the geometry, never
    from the patch type alone. What slipped through the first draft: it kept
    EVERY count of 1 in a 2D case at 1, so a one-cell wall layer was never
    refined and the ladder passed 3% below the exact answer; and an empty patch
    with no faces made a 3D mesh read as 2D."""
    if any(t == "wedge" for t, _f in patches.values()):
        raise CaseProblem("a wedge (axisymmetric) case: this pack reads planar 2D and 3D "
                          "cases only")
    normals = []
    for kind, faces in patches.values():
        if kind != "empty":
            continue
        for f in faces:
            if len(f) < 3 or max(f) >= len(verts):
                raise CaseProblem("system/blockMeshDict: an empty face that is not three or "
                                  "more of the vertices")
            n = _unit(_cross(_sub(verts[f[1]], verts[f[0]]), _sub(verts[f[2]], verts[f[0]])))
            if n is None:
                raise CaseProblem("system/blockMeshDict: an empty face of no area")
            normals.append(n)
    if not normals:
        return 3, [None] * len(blocks)
    axis = normals[0]
    if any(abs(_dot(n, axis)) < 0.999 for n in normals):
        raise CaseProblem("the empty patches are not parallel: not a planar 2D case")
    thin = []
    for _l, counts, ids, _g in blocks:
        v = [verts[i] for i in ids]
        dirs = [_unit(_sub(v[1], v[0])), _unit(_sub(v[3], v[0])), _unit(_sub(v[4], v[0]))]
        if any(d is None for d in dirs):
            raise CaseProblem("system/blockMeshDict: a block with a zero-length edge")
        align = [abs(_dot(d, axis)) for d in dirs]
        k = max(range(3), key=lambda i: align[i])
        if align[k] < 0.999 or counts[k] != 1:
            raise CaseProblem("a 2D case whose blocks are not one cell thick across the empty "
                              "patches")
        thin.append(k)
    return 2, thin


def _planes(ctx: GateContext):
    """The two planes from cfd_dp_planes, upstream first, each ``(point,
    unit normal)``; or a str naming what is wrong. A plane is written as the
    point on it nearest the origin, so two spellings of one plane are one."""
    raw = ctx.param("cfd_dp_planes")
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return "cfd_dp_planes must be two planes, upstream first"
    out = []
    for k, plane in enumerate(raw):
        where = "upstream" if k == 0 else "downstream"
        if not isinstance(plane, dict) or set(plane) != {"point", "normal"}:
            return f"cfd_dp_planes: the {where} plane must be {{\"point\": [x, y, z], " \
                   f"\"normal\": [x, y, z]}}"
        try:
            p = [float(v) for v in plane["point"]]
            n = [float(v) for v in plane["normal"]]
        except (TypeError, ValueError):
            return f"cfd_dp_planes: the {where} plane holds something that is not a number"
        if len(p) != 3 or len(n) != 3 or not T.finite(*p, *n):
            return f"cfd_dp_planes: the {where} plane needs three finite numbers in each"
        mag = math.sqrt(sum(c * c for c in n))
        if mag == 0:
            return f"cfd_dp_planes: the {where} plane's normal is zero"
        n = [c / mag for c in n]
        d = sum(a * b for a, b in zip(p, n))
        out.append(([d * c for c in n], n))
    return out


# --------------------------------------------------------------------------- #
# the guard
# --------------------------------------------------------------------------- #
@gate(
    id="cfd.case_readable",
    basis="model-only",
    title="The OpenFOAM case is one this pack can run and vouch for",
    claims=["cfd", "fluid-dynamics", "pressure-drop", "internal-flow"],
    tier=Tier.INSTANT,
    settles="cfd case readability",
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:coded_inlet",
        note="the baseline channel with its inlet velocity written as a codedFixedValue, "
             "C++ the case would compile and run",
    ),
)
def case_readable(ctx: GateContext) -> Verdict:
    """The case parses with the pack's reader, runs a solver and a physics this
    pack vouches for (simpleFoam, laminar, Newtonian), builds its mesh with
    blockMesh from cell counts this pack can scale, compiles nothing, reads no
    file outside itself, and names two measurement planes.

    A case this pack cannot read is a fail here, never a guess downstream: a
    reader that skipped what it did not understand could miss the line that
    changes the answer."""
    gid = "cfd.case_readable"
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    planes = _planes(ctx)
    if planes is None:
        return _skip(gid, "no cfd_dp_planes: the two planes, upstream first, between which "
                          "the pressure drop is measured")
    if isinstance(planes, str):
        return _error(gid, planes)
    try:
        case = Case(path)
    except CaseProblem as exc:
        return Verdict(gate=gid, passed=False, detail=str(exc))
    return Verdict(gate=gid, passed=True,
                   detail=f"{case.application}, {case.simulation_type}, nu {case.nu:g} m^2/s, "
                          f"{case.cells()} cells in {len(case.blocks)} block(s), "
                          f"{case.dim}D, {len(case.patches)} patches, budget "
                          f"{case.budget} iterations; nothing compiled, nothing read from "
                          f"outside the case")


@gate(
    id="cfd.regime",
    basis="sourced",
    title="The flow is laminar and incompressible: Reynolds and Mach numbers",
    claims=["cfd", "fluid-dynamics", "pressure-drop", "internal-flow", "flow-regime"],
    tier=Tier.INSTANT,
    settles="cfd flow regime",
    needs=["cfd.case_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:fast_flow",
        note="the baseline channel stated at a mean velocity whose Reynolds number is 15% "
             "past 2300",
    ),
)
def regime(ctx: GateContext) -> Verdict:
    """Re = U Dh / nu below 2300 and Ma = U / c below 0.3, with nu read from the
    case and U, Dh and c as the project states them. cfd.converged then holds
    the stated U to the velocity the run actually carried."""
    gid = "cfd.regime"
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    vals = {}
    for key, what in (("cfd_velocity_m_s", "the mean velocity through the upstream plane"),
                      ("cfd_length_m", "the hydraulic diameter of the passage (4 x area / "
                                       "wetted perimeter; twice the height of a 2D channel)"),
                      ("cfd_sound_speed_m_s", "the speed of sound in the fluid")):
        v = _number(ctx, key)
        if v is None:
            return _skip(gid, f"no {key}: {what}")
        if isinstance(v, str):
            return _error(gid, v)
        if v <= 0:
            return _error(gid, f"{key} is {v:g}; it must be positive")
        vals[key] = v
    try:
        case = Case(path)
    except CaseProblem as exc:
        return _error(gid, f"the case does not read: {exc}")
    u, dh, c = vals["cfd_velocity_m_s"], vals["cfd_length_m"], vals["cfd_sound_speed_m_s"]
    re_ = u * dh / case.nu
    ma = u / c
    problems = []
    if not re_ < RE_LAMINAR_MAX:
        problems.append(f"Re {re_:.4g} is not below {RE_LAMINAR_MAX:g}: a laminar solver on a "
                        f"flow that may be turbulent")
    if not ma < MACH_MAX:
        problems.append(f"Mach {ma:.3g} is not below {MACH_MAX:g}: an incompressible solver on "
                        f"a flow whose density changes")
    # The value is the worse of the two as a fraction of its limit, so a Mach
    # fail never reports a Reynolds number inside its limit (the first draft did).
    worst = max(re_ / RE_LAMINAR_MAX, ma / MACH_MAX)
    return Verdict(gate=gid, passed=not problems, measured=round(worst, 9),
                   limit=1.0, comparator="<", units="fraction of limit",
                   detail=("; ".join(problems) if problems else
                           f"Re {re_:.4g} (U {u:g} m/s, Dh {dh:g} m, nu {case.nu:g} m^2/s) "
                           f"below {RE_LAMINAR_MAX:g}; Mach {ma:.3g} below {MACH_MAX:g}"))


# --------------------------------------------------------------------------- #
# running OpenFOAM
# --------------------------------------------------------------------------- #
def _open(ctx: GateContext, gid: str):
    """``(install, environment)`` or a skip/error Verdict."""
    try:
        inst = T.locate()
        env = T.environment(inst, T.home(ctx.out_dir, inst.api))
    except T.Unavailable as exc:
        return _skip(gid, str(exc))
    except T.Timeout as exc:
        return _skip(gid, str(exc))
    except T.RunError as exc:
        return _error(gid, str(exc))
    return inst, env


def _timeout(ctx: GateContext):
    v = _number(ctx, "cfd_timeout_s")
    if v is None:
        return DEFAULT_TIMEOUT_S
    if isinstance(v, str) or v <= 0:
        return f"cfd_timeout_s must be a positive number of seconds, not {ctx.param('cfd_timeout_s')!r}"
    return v


def _stage_dir(ctx: GateContext, gid: str, name: str) -> str:
    marker = ctx.out_path(PACK, gid.replace(".", "_"), name, ".stage")
    return os.path.dirname(marker)


def _function_objects(planes) -> str:
    def one(name, point, normal):
        return f"""    {name}
    {{
        type            surfaceFieldValue;
        libs            (fieldFunctionObjects);
        writeControl    timeStep;
        writeInterval   1;
        writePrecision  {WRITE_PRECISION};
        log             false;
        writeFields     false;
        regionType      sampledSurface;
        name            {name};
        sampledSurfaceDict
        {{
            type        plane;
            planeType   pointAndNormal;
            pointAndNormalDict
            {{
                point   ({point[0]:.12g} {point[1]:.12g} {point[2]:.12g});
                normal  ({normal[0]:.12g} {normal[1]:.12g} {normal[2]:.12g});
            }}
            interpolate true;
        }}
        operation       areaAverage;
        fields          (p U);
    }}
"""
    (p0, n0), (p1, n1) = planes
    return ("// Written by nopekit's cfd-openfoam pack: the case's own function objects\n"
            "// were removed from this copy, so the numbers below are the pack's.\n"
            "functions\n{\n" + one(UPSTREAM, p0, n0) + one(DOWNSTREAM, p1, n1) + "}\n")


def _prepare(stage: str, case: Case, planes, target: float, counts=None) -> None:
    """The pack's edits to a staged copy: its residual targets, its function
    objects, and (for a refined level) its cell counts. Every other byte is the
    project's."""
    cd = F.case_file(stage, "system/controlDict")
    with open(cd, encoding="utf-8") as fh:
        text = fh.read()
    text = F.put_entry(text, "functions", _function_objects(planes))
    with open(cd, "w", encoding="utf-8") as fh:
        fh.write(text)
    fs = F.case_file(stage, "system/fvSolution")
    with open(fs, encoding="utf-8") as fh:
        text = fh.read()
    text = F.put_entry(text, "SIMPLE/residualControl",
                       f"// nopekit's targets, cfd_residual_target\n"
                       f"    residualControl\n    {{\n        p {target:g};\n"
                       f"        U {target:g};\n    }}")
    with open(fs, "w", encoding="utf-8") as fh:
        fh.write(text)
    if counts is not None:
        text = case.block_mesh_text
        for (lst, _old, _ids, _g), new in sorted(zip(case.blocks, counts),
                                             key=lambda x: -x[0][0].start):
            text = text[:lst.start] + "(" + " ".join(str(n) for n in new) + ")" + text[lst.end:]
        with open(F.case_file(stage, "system/blockMeshDict"), "w", encoding="utf-8") as fh:
            fh.write(text)


class Solve:
    """What one blockMesh + simpleFoam run left: the parsed log, the pack's two
    series and the cell count, with the logs' text for evidence."""

    def __init__(self, cells, log, up, down, logs):
        self.cells = cells
        self.log = log
        self.up = up
        self.down = down
        self.logs = logs          # the logs' paths, for evidence

    def dp(self) -> list[float]:
        """The kinematic static pressure drop, upstream minus downstream, per
        iteration (m^2/s^2)."""
        ip, jp = self.up.columns.index("areaAverage(p)"), self.down.columns.index("areaAverage(p)")
        down = {row[0]: row[jp] for row in self.down.rows}
        return [row[ip] - down[row[0]] for row in self.up.rows if row[0] in down]

    def u_normal(self, normal) -> float:
        """The mean velocity along the upstream plane's normal, signed: the
        normal says which way is downstream."""
        iu = self.up.columns.index("areaAverage(U)")
        u = self.up.rows[-1][iu]
        return sum(a * b for a, b in zip(u, normal))


def _canon(v):
    """A dictionary, list or token as plain data, numbers as floats, keyword
    order dropped: two spellings of one value compare equal."""
    if isinstance(v, F.FoamDict):
        return tuple(sorted((e.key, _canon(e.value)) for e in v.entries))
    if isinstance(v, (list, F.FoamList)):
        return tuple(_canon(x) for x in v)
    if isinstance(v, F.Tok):
        return float(v.text) if v.kind == "number" else v.text.strip('"')
    return repr(v)


def _expanded(env, stage: str, rel: str, timeout: float):
    """``rel`` as OpenFOAM itself reads it: ``foamDictionary -expand``, every
    include, macro, condition and merge applied."""
    run = T.run(env, stage, ["foamDictionary", "-expand", rel], timeout, banner=False,
                log=f"log.foamDictionary.{os.path.basename(rel)}")
    try:
        return F.parse(run.stdout)
    except F.FoamFormatError as exc:
        raise T.RunError(f"foamDictionary's expansion of {rel} does not parse: {exc}", [run.log])


def _as_read(env, stage: str, case: Case, planes, target: float, timeout: float) -> None:
    """OpenFOAM's own reading of the staged copy, held to what the pack wrote
    into it and what cfd.case_readable read from it; T.RunError on any
    difference. The tier-0 reader refuses what it cannot evaluate, and this is
    the second line: what slipped through the first draft was a ``#sinclude``
    that MERGED ``scaleFactor 0.5`` into the pack's own function objects (a text
    edit cannot see a merge), and an ``#if`` that set the nu the solver ran."""
    problems = []
    cd = _expanded(env, stage, "system/controlDict", timeout)
    want = F.parse(_function_objects(planes)).sub("functions")
    if cd.sub("functions") is None or _canon(cd.sub("functions")) != _canon(want):
        problems.append("system/controlDict's functions are not exactly the pack's two "
                        "function objects")
    if cd.entry("libs") is not None:
        problems.append("system/controlDict loads libraries")
    try:
        span = (F.scalar(cd, "endTime") - (F.scalar(cd, "startTime") or 0.0)) / F.scalar(cd, "deltaT")
    except (F.Unresolved, TypeError, ZeroDivisionError):
        span = None
    if F.word(cd, "application") != case.application or span is None \
            or int(round(span)) != case.budget:
        problems.append("system/controlDict's application or iteration budget")
    fs = _expanded(env, stage, "system/fvSolution", timeout)
    rc = fs.sub("SIMPLE/residualControl")
    want_rc = F.parse(f"r {{ p {target!r}; U {target!r}; }}").sub("r")
    if rc is None or _canon(rc) != _canon(want_rc):
        problems.append("system/fvSolution's residualControl is not the pack's")
    simple = fs.sub("SIMPLE")
    if simple is not None and (F.word(simple, "momentumPredictor") or "yes").lower() in OFF_WORDS:
        problems.append("momentumPredictor is off")
    tp = _expanded(env, stage, "constant/transportProperties", timeout)
    try:
        nu = F.scalar(tp, "nu")
    except F.Unresolved:
        nu = None
    if F.word(tp, "transportModel") != "Newtonian" or nu != case.nu:
        problems.append(f"constant/transportProperties: nu {nu} where the case reads "
                        f"{case.nu:g}")
    tu = _expanded(env, stage, "constant/turbulenceProperties", timeout)
    lam = tu.sub("laminar")
    if F.word(tu, "simulationType") not in SIMULATION_TYPES or (
            lam is not None and (F.word(lam, "model") or F.word(lam, "laminarModel"))
            not in LAMINAR_MODELS):
        problems.append("constant/turbulenceProperties is not laminar Stokes flow")
    if _formal_order(_expanded(env, stage, "system/fvSchemes", timeout)) != case.formal_order:
        problems.append("system/fvSchemes' convection schemes")
    if problems:
        raise T.RunError("OpenFOAM reads the staged case otherwise than the pack wrote and "
                         "read it: " + "; ".join(problems))


def _solve(stage: str, case: Case, planes, target: float, env, timeout: float) -> Solve:
    """blockMesh, checkMesh and simpleFoam in ``stage``, after OpenFOAM's own
    reading of it is held to the pack's: a Solve, or T.RunError / T.Timeout.

    No memo: the spine empties only functools caches before a run, so a
    module-level memo of runs would outlive the gate that filled it (the first
    draft's did, and ``doctor`` named it)."""
    _as_read(env, stage, case, planes, target, timeout)
    mesh = T.run(env, stage, ["blockMesh"], timeout)
    cells = T.block_mesh_cells(mesh.stdout)
    check = T.run(env, stage, ["checkMesh"], timeout)
    try:
        directions = T.check_mesh(check.stdout).directions
    except ValueError as exc:
        raise T.RunError(str(exc), [check.log])
    if directions != case.dim:
        raise T.RunError(f"checkMesh finds {directions} geometric directions; the case reads as "
                         f"{case.dim}D", [check.log])
    solver = T.run(env, stage, ["simpleFoam"], timeout)
    try:
        log = T.solver_log(solver.stdout)
    except ValueError as exc:
        raise T.RunError(str(exc), [solver.log])
    if log.criteria != {"p": target, "U": target}:
        raise T.RunError(f"simpleFoam ran to the convergence criteria {log.criteria}, not the "
                         f"pack's p and U at {target:g}", [solver.log])
    series = []
    for name in (UPSTREAM, DOWNSTREAM):
        dat = os.path.join(stage, "postProcessing", name, "0", "surfaceFieldValue.dat")
        if not os.path.isfile(dat):
            raise T.RunError(f"simpleFoam wrote no {name} values: the plane may miss the mesh",
                             [solver.log])
        try:
            s = T.read_dat(dat)
        except ValueError as exc:
            raise T.RunError(str(exc), [dat])
        if not s.rows or "areaAverage(p)" not in s.columns or "areaAverage(U)" not in s.columns:
            raise T.RunError(f"{name}: the function object wrote no p and U averages", [dat])
        try:
            area = float(s.header.get("Area", "nan"))
            scale = float(s.header.get("Scale factor", "nan"))
        except ValueError:
            area = scale = float("nan")
        if not (area > 0 and math.isfinite(area)):
            raise T.RunError(f"{name}: the plane cuts no part of the mesh (area "
                             f"{s.header.get('Area')})", [dat])
        if scale != 1.0:
            raise T.RunError(f"{name}: its values are scaled by {s.header.get('Scale factor')}",
                             [dat])
        times = [row[0] for row in s.rows]
        if times != sorted(set(times)):
            raise T.RunError(f"{name}: an iteration written twice or out of order", [dat])
        series.append(s)
    out = Solve(cells, log, series[0], series[1], [mesh.log, check.log, solver.log])
    if not T.finite(*out.dp()):
        raise T.RunError("the pressure drop holds a value that is not finite", [solver.log])
    return out


def _settings(ctx: GateContext, gid: str):
    """The case, the planes, the residual target and the timeout, or a Verdict."""
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    planes = _planes(ctx)
    if planes is None:
        return _skip(gid, "no cfd_dp_planes: the two planes, upstream first, between which the "
                          "pressure drop is measured")
    if isinstance(planes, str):
        return _error(gid, planes)
    target = _number(ctx, "cfd_residual_target")
    note = ""
    if target is None:
        target, note = DEFAULT_RESIDUAL_TARGET, " [pack default]"
    if isinstance(target, str):
        return _error(gid, target)
    if not 0 < target <= RESIDUAL_TARGET_MAX:
        return _error(gid, f"cfd_residual_target {target:g} is not in (0, {RESIDUAL_TARGET_MAX:g}]: "
                           f"a looser target is met by a solution still moving")
    timeout = _timeout(ctx)
    if isinstance(timeout, str):
        return _error(gid, timeout)
    try:
        case = Case(path)
    except CaseProblem as exc:
        return _error(gid, f"the case does not read: {exc}")
    return case, planes, target, note, timeout


def _settled(solve: Solve, target: float, budget: int) -> list[str]:
    """Why a run is not converged, or [] when it is: the converged line; p and
    U both solved at the last iteration, each initial residual at or below the
    target; and the pressure drop's estimated remaining change under
    STABLE_TOL of itself."""
    why = []
    log = solve.log
    if log.converged_in is None:
        why.append(f"no 'SIMPLE solution converged' line: the run stopped at iteration "
                   f"{log.last_iteration} of its {budget}-iteration budget")
    if "p" not in log.residuals or not any(k.startswith("U") for k in log.residuals):
        why.append(f"p and U were not both solved at the last iteration "
                   f"({', '.join(sorted(log.residuals)) or 'nothing'})")
    over = {k: v for k, v in log.residuals.items() if not v <= target}
    if over:
        why.append("initial residual above the target " + f"{target:g}: " + ", ".join(
            f"{k} {v:.3g}" for k, v in sorted(over.items())))
    dp = solve.dp()
    rem = I.remaining(dp)
    if not all(math.isfinite(v) for v in dp):
        # What slipped through until P0.1 (found by reading, in GitHub #15 Phase 0):
        # inf <= STABLE_TOL * abs(inf) is True, so a last value of inf read settled.
        why.append("the pressure drop is not a finite number at every iteration")
    elif rem is None:
        why.append(f"{len(dp)} iterations: fewer than the {2 * I.WINDOW_MIN + 1} needed to "
                   f"see the pressure drop settle")
    elif rem == math.inf:
        why.append("the pressure drop is still moving: its changes do not decrease at a "
                   "steady rate, so the gate cannot estimate the change still to come")
    elif not rem <= STABLE_TOL * abs(dp[-1]):
        why.append(f"the pressure drop is still moving: an estimated {rem:.3g} m^2/s^2 is "
                   f"still to come, more than {STABLE_TOL:g} of its value")
    return why


def _noise(solve: Solve) -> float:
    """The pressure drop's estimated remaining change: the iterative error the
    GCI is compared with."""
    return I.remaining(solve.dp())


# --------------------------------------------------------------------------- #
# mesh quality
# --------------------------------------------------------------------------- #
@gate(
    id="cfd.mesh_quality",
    basis="established",
    title="checkMesh finds the case's mesh sound, inside stated limits",
    claims=["cfd", "fluid-dynamics", "pressure-drop", "internal-flow", "mesh-quality"],
    tier=Tier.BUILD,
    settles="cfd mesh quality",
    requires_tools=list(T.WRAPPERS),
    needs=["cfd.case_readable"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:sheared",
        note="the baseline channel with its top wall slid 40 mm downstream: every cell "
             "sheared to 76 degrees of non-orthogonality, which checkMesh calls OK",
    ),
)
def mesh_quality(ctx: GateContext) -> Verdict:
    """blockMesh, then checkMesh, on a staged copy. Passes only on checkMesh's
    ``Mesh OK.`` with the worst non-orthogonality, skewness and aspect ratio each
    inside the project's limit (``cfd_max_non_ortho_deg``, ``cfd_max_skewness``,
    ``cfd_max_aspect_ratio``). The verdict's value is the worst of the three as a
    fraction of its limit. checkMesh's exit code is never read: it is 0 on a
    failed mesh."""
    gid = "cfd.mesh_quality"
    path = _case(ctx)
    if path is None:
        return _skip(gid, _NO_CASE)
    limits, marks = {}, []
    for key, default in (("cfd_max_non_ortho_deg", DEFAULT_MAX_NON_ORTHO_DEG),
                         ("cfd_max_skewness", DEFAULT_MAX_SKEWNESS),
                         ("cfd_max_aspect_ratio", DEFAULT_MAX_ASPECT_RATIO)):
        v = _number(ctx, key)
        if v is None:
            v = default
            marks.append(key)
        if isinstance(v, str):
            return _error(gid, v)
        if not v > 0:
            return _error(gid, f"{key} is {v:g}; a limit must be positive")
        limits[key] = v
    timeout = _timeout(ctx)
    if isinstance(timeout, str):
        return _error(gid, timeout)
    try:
        case = Case(path)
    except CaseProblem as exc:
        return _error(gid, f"the case does not read: {exc}")
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    _inst, env = opened
    stage = _stage_dir(ctx, gid, "case")
    T.stage(path, stage, case.files)
    try:
        T.run(env, stage, ["blockMesh"], timeout)
        run = T.run(env, stage, ["checkMesh"], timeout)
    except T.Timeout as exc:
        return _skip(gid, str(exc))
    except T.RunError as exc:
        return _error(gid, str(exc), exc.evidence)
    logs = [os.path.join(stage, "log.blockMesh"), run.log]
    try:
        mc = T.check_mesh(run.stdout)
    except ValueError as exc:
        return _error(gid, str(exc), logs)
    if not T.finite(mc.non_ortho_deg, mc.skewness, mc.aspect_ratio):
        return _error(gid, "checkMesh reported a value that is not finite", logs)
    if mc.directions != case.dim:
        return _error(gid, f"checkMesh finds {mc.directions} geometric directions; the case "
                           f"reads as {case.dim}D", logs)
    ratios = {"non-orthogonality": (mc.non_ortho_deg, limits["cfd_max_non_ortho_deg"], " deg"),
              "skewness": (mc.skewness, limits["cfd_max_skewness"], ""),
              "aspect ratio": (mc.aspect_ratio, limits["cfd_max_aspect_ratio"], "")}
    worst = max(v / lim for v, lim, _u in ratios.values())
    over = [n for n, (v, lim, _u) in ratios.items() if not v <= lim]
    ev = _evidence(ctx, gid, {"cells": mc.cells, "directions": mc.directions,
                              "mesh_ok": mc.ok, "failed_checks": mc.failed,
                              "values": {n: v for n, (v, _l, _u) in ratios.items()},
                              "limits": limits, "pack_default": marks})
    said = ", ".join(f"{n} {v:.4g}{u} of {lim:g}" for n, (v, lim, u) in ratios.items())
    default = f" [pack default: {', '.join(marks)}]" if marks else ""
    if not mc.ok:
        detail = (f"checkMesh failed {len(mc.failed)} check(s): "
                  f"{'; '.join(mc.failed)[:200]}; {said}{default}")
    elif over:
        detail = f"checkMesh said Mesh OK, but {', '.join(over)} past the limit: {said}{default}"
    else:
        detail = f"checkMesh: Mesh OK, {mc.cells} cells; {said}{default}"
    return Verdict(gate=gid, passed=mc.ok and not over, measured=round(worst, 6), limit=1.0,
                   comparator="<=", units="fraction of limit", detail=detail,
                   evidence=[ev, *logs])


# --------------------------------------------------------------------------- #
# convergence
# --------------------------------------------------------------------------- #
@gate(
    id="cfd.converged",
    basis="established",
    title="simpleFoam met the pack's residual targets, and the pressure drop settled",
    claims=["cfd", "fluid-dynamics", "pressure-drop", "internal-flow", "convergence"],
    tier=Tier.SOLVE,
    settles="cfd solver convergence",
    requires_tools=list(T.WRAPPERS),
    needs=["cfd.mesh_quality", "cfd.regime"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:cut_short",
        note="the baseline channel with endTime 5: simpleFoam stops at iteration 5 and "
             "exits 0, its pressure drop 0.69% high",
    ),
)
def converged(ctx: GateContext) -> Verdict:
    """simpleFoam on a staged copy, with the pack's residual targets
    (``cfd_residual_target``, for p and U) and the pack's function objects on
    the two planes. Passes only when the log says ``SIMPLE solution converged``,
    p and U were both solved at the last iteration, each initial residual at or
    below the target, and the pressure drop's estimated remaining change
    (``_iter.remaining``, from its whole history) is under 0.1% of it. The value
    is the iteration it converged at, against the case's own budget (endTime /
    deltaT).

    A run that dies on SIGFPE (divergence, with trapping on), exits non-zero or
    never prints End is an error. So is a run whose mean velocity through the
    upstream plane is not the ``cfd_velocity_m_s`` cfd.regime judged."""
    gid = "cfd.converged"
    got = _settings(ctx, gid)
    if isinstance(got, Verdict):
        return got
    case, planes, target, note, timeout = got
    u_stated = _number(ctx, "cfd_velocity_m_s")
    if u_stated is None:
        return _skip(gid, "no cfd_velocity_m_s: the mean velocity through the upstream plane")
    if isinstance(u_stated, str):
        return _error(gid, u_stated)
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    inst, env = opened
    stage = _stage_dir(ctx, gid, "case")
    T.stage(case.path, stage, case.files)
    _prepare(stage, case, planes, target)
    try:
        solve = _solve(stage, case, planes, target, env, timeout)
    except T.Timeout as exc:
        return _skip(gid, str(exc))
    except (T.RunError, ValueError) as exc:
        return _error(gid, str(exc), getattr(exc, "evidence", []))
    logs = list(solve.logs)
    u_run = solve.u_normal(planes[0][1])
    if not u_run > 0:
        # What slipped through the first draft: the velocity was taken as a
        # magnitude, so a flow crossing the plane against its normal (planes
        # swapped, or the flow reversed) matched the stated speed.
        return _error(gid, f"the flow crosses the upstream plane against its normal "
                           f"({u_run:.4g} m/s along it): the normal must point downstream", logs)
    if not abs(u_run - u_stated) <= VELOCITY_TOL * abs(u_stated):
        return _error(gid, f"the run carried {u_run:.4g} m/s through the upstream plane, but "
                           f"cfd_velocity_m_s says {u_stated:g}: cfd.regime judged the "
                           f"Reynolds number on a different flow", logs)
    why = _settled(solve, target, case.budget)
    log = solve.log
    at = log.converged_in if log.converged_in is not None else log.last_iteration
    dp = solve.dp()
    ev = _evidence(ctx, gid, {"converged_in": log.converged_in, "last_iteration":
                              log.last_iteration, "budget": case.budget, "target": target,
                              "residuals": log.residuals, "dp_m2_s2": dp[-1] if dp else None,
                              "iterative_error_pct": _error_pct(dp),
                              "convergence_tol_pct": STABLE_TOL * 100.0,
                              "u_upstream": u_run, "cells": solve.cells,
                              "install": inst.root, "build": inst.build})
    hist = _history(ctx, gid, "history.csv", dp)
    detail = ("; ".join(why) if why else
              f"converged at iteration {at} of {case.budget} to residual target {target:g}"
              f"{note}; pressure drop {dp[-1]:.6g} m^2/s^2, an estimated "
              f"{I.remaining(dp):.2g} m^2/s^2 still to come; {solve.cells} cells")
    if why:
        # No one-sided value: a run that stopped short, a residual over target and a
        # number still moving fail on different readings, and none is "iterations
        # past the budget" (with "<", the first draft's pass at 91 < 91 contradicted
        # itself; with "<=", its control's 5 <= 5 read inside the limit and failed).
        return Verdict(gate=gid, passed=False, detail=detail, evidence=[ev, hist, *logs])
    # "<=": a run that converges on the last iteration of its budget converged.
    return Verdict(gate=gid, passed=True, measured=float(at), limit=float(case.budget),
                   comparator="<=", units="iterations", detail=detail,
                   evidence=[ev, hist, *logs])


# --------------------------------------------------------------------------- #
# mesh independence
# --------------------------------------------------------------------------- #
class Level:
    def __init__(self, k: int, counts, solve: Solve, stage: str):
        self.k = k
        self.counts = counts
        self.solve = solve
        self.stage = stage


#: Corner indices of a hex block's two faces across each local direction.
_FACES = {0: ((0, 3, 4, 7), (1, 2, 5, 6)), 1: ((0, 1, 4, 5), (3, 2, 7, 6)),
          2: ((0, 1, 2, 3), (4, 5, 6, 7))}


def _uniform_along(grading, k: int) -> bool:
    """Whether a block's cells are evenly spaced along its local direction k."""
    kind, values = grading
    if values is None:
        return True
    flat = list(values)
    if kind == "simpleGrading" and len(flat) == 3:
        g = flat[k]
        return isinstance(g, F.Tok) and g.kind == "number" and float(g.text) == 1.0
    if kind == "edgeGrading" and len(flat) == 12:
        return all(isinstance(g, F.Tok) and g.kind == "number" and float(g.text) == 1.0
                   for g in flat[4 * k:4 * k + 4])
    return False


def _lattice(case: Case, planes, r: float) -> list[str]:
    """Why a plane does not sit at the same place in the cells on every level:
    each plane must be normal to an evenly graded block direction, with the
    blocks it crosses straight-edged, and fall on a cell face or a cell centre
    at every level of the ladder. [] when it does.

    What slipped through the second review: OpenFOAM's sampled plane reads a
    value whose error depends on where the plane falls in a cell (exact on a face
    or a centre; about 1% off at a quarter of a cell on 75 cells). A ladder at
    r = 1.7 put the planes at 0.75, 0 and 0.25 of a cell on its three levels,
    read the measurement's error as convergence at order 1.77, and passed a
    band 0.34% under the exact pressure drop."""
    why = []
    if case.curved:
        return ["the blockMeshDict has curved edges: the pack cannot place the planes in the "
                "cells"]
    levels = [case.counts(r, k) for k in range(3)]
    for name, (point, normal) in zip(("upstream", "downstream"), planes):
        sp = _dot(point, normal)
        crossed = 0
        for b, (_l, _counts, ids, grading) in enumerate(case.blocks):
            v = [case.verts[i] for i in ids]
            for k in range(3):
                axis = _unit(_sub(v[_FACES[k][1][0]], v[_FACES[k][0][0]]))
                if axis is None or abs(_dot(axis, normal)) < 0.999:
                    continue
                s0 = [_dot(v[i], normal) for i in _FACES[k][0]]
                s1 = [_dot(v[i], normal) for i in _FACES[k][1]]
                span = abs(s1[0] - s0[0])
                if span == 0:
                    continue
                lo, hi = min(s0[0], s1[0]), max(s0[0], s1[0])
                if not lo - 1e-12 * span <= sp <= hi + 1e-12 * span:
                    continue
                crossed += 1
                if max(s0) - min(s0) > 1e-9 * span or max(s1) - min(s1) > 1e-9 * span:
                    why.append(f"the {name} plane crosses block {b}, whose faces across it "
                               f"are not normal to it")
                    continue
                if not _uniform_along(grading, k):
                    why.append(f"the {name} plane crosses block {b}, graded along its normal")
                    continue
                t = (sp - s0[0]) / (s1[0] - s0[0])
                for lv, counts in enumerate(levels):
                    q = 2 * t * counts[b][k]
                    if abs(q - round(q)) > 1e-6:
                        why.append(f"the {name} plane sits {t * counts[b][k] % 1:.2f} of a "
                                   f"cell into block {b} on level {lv}: OpenFOAM's sampled "
                                   f"value there depends on where the plane falls in a cell, "
                                   f"so it must sit on a face or a centre at every level")
                        break
        if not crossed:
            why.append(f"the {name} plane is not normal to a block direction it crosses")
    return why


def _ladder(ctx: GateContext, gid: str):
    """The project's mesh and two refinements of it, each solved: ``(case,
    planes, target, note, ratio, rnote, [Level coarse..fine])`` or a Verdict.
    A level that does not converge is a fail of mesh independence, named."""
    got = _settings(ctx, gid)
    if isinstance(got, Verdict):
        return got
    case, planes, target, note, timeout = got
    r = _number(ctx, "cfd_refinement_ratio")
    rnote = ""
    if r is None:
        r, rnote = DEFAULT_REFINEMENT_RATIO, " [pack default]"
    if isinstance(r, str):
        return _error(gid, r)
    if not REFINEMENT_MIN <= r <= REFINEMENT_MAX:
        return _error(gid, f"cfd_refinement_ratio {r:g} is outside [{REFINEMENT_MIN:g}, "
                           f"{REFINEMENT_MAX:g}]: below, the meshes differ by less than the "
                           f"iterative noise; above, the finest mesh costs {REFINEMENT_MAX:g}^"
                           f"{2 * case.dim:d} times the first")
    misplaced = _lattice(case, planes, r)
    if misplaced:
        text = "; ".join(dict.fromkeys(misplaced))[:400]
        # A fail of mesh independence (not established); for pressure_drop, which
        # cfd.mesh_independence guards, the two gates disagreeing: an error.
        return (Verdict(gate=gid, passed=False, detail=text) if gid == "cfd.mesh_independence"
                else _error(gid, text))
    opened = _open(ctx, gid)
    if isinstance(opened, Verdict):
        return opened
    inst, env = opened
    levels = []
    for k in range(3):
        f = r ** k
        counts = case.counts(r, k)
        stage = _stage_dir(ctx, gid, f"level{k}")
        T.stage(case.path, stage, case.files)
        _prepare(stage, case, planes, target, counts if k else None)
        try:
            solve = _solve(stage, case, planes, target, env, timeout)
        except T.Timeout as exc:
            return _skip(gid, f"level {k}: {exc}")
        except (T.RunError, ValueError) as exc:
            return _error(gid, f"level {k} (x{f:g}): {exc}", getattr(exc, "evidence", []))
        levels.append(Level(k, counts, solve, stage))
    return case, planes, target, note, r, rnote, levels


def _gci(case: Case, levels: list, target: float):
    """``(GCIResult or None, [why the GCI is not believed], noise)`` over the
    ladder, fine first as Celik numbers it."""
    why = []
    for lv in levels:
        unsettled = _settled(lv.solve, target, case.budget)
        if unsettled:
            why.append(f"level {lv.k} ({lv.solve.cells} cells) is not converged: "
                       f"{unsettled[0]}")
    if why:
        return None, why, None
    fine = list(reversed(levels))
    cells = [lv.solve.cells for lv in fine]
    phi = [lv.solve.dp()[-1] for lv in fine]
    noise = max(_noise(lv.solve) for lv in levels)
    if not cells[0] > cells[1] > cells[2]:
        return None, [f"the refined meshes do not have more cells ({cells})"], noise
    res = G.gci(phi, cells=cells, dim=case.dim, noise=noise)
    if res.r21 < REFINEMENT_MIN or res.r32 < REFINEMENT_MIN:
        why.append(f"effective refinement ratios {res.r21:.3g} and {res.r32:.3g}: below "
                   f"{REFINEMENT_MIN:g} (Celik Step 2)")
    if res.convergence != G.MONOTONE_CONVERGENCE:
        why.append(f"{res.convergence} (pressure drops {phi[2]:.6g}, {phi[1]:.6g}, "
                   f"{phi[0]:.6g} m^2/s^2 coarse to fine): Richardson extrapolation needs "
                   f"monotone convergence")
        return res, why, noise
    if not res.p_converged or res.p is None:
        why.append("no unique observed order solves Celik's Eq. (3)")
        return res, why, noise
    p_max = case.formal_order + P_SLACK
    if not P_MIN <= res.p <= p_max:
        why.append(f"observed order {res.p:.3g} is outside [{P_MIN:g}, {p_max:g}] for a "
                   f"formal order {case.formal_order}: the meshes are not in the asymptotic "
                   f"range")
    if not noise <= ITERATIVE_FRACTION * abs(res.eps21):
        why.append(f"the iterative error {noise:.3g} is not ten times below the change "
                   f"between the two finest meshes {abs(res.eps21):.3g}")
    if res.gci_fine21 is None:
        why.append("the GCI could not be computed: " + "; ".join(res.warnings))
    return res, why, noise


def _ladder_evidence(ctx, gid, case, levels, res, noise, extra, rho=None) -> list[str]:
    """summary.json, a ``history_level{k}.csv`` per level (``_history``; in Pa when
    ``rho`` is given) and the logs. Each level holds its estimate as
    ``iterative_error_pct``, beside the ``convergence_tol_pct`` it was held to."""
    payload = {"dim": case.dim, "formal_order": case.formal_order,
               "levels": [{"k": lv.k, "cells": lv.solve.cells, "counts": lv.counts,
                           "converged_in": lv.solve.log.converged_in,
                           "dp_m2_s2": lv.solve.dp()[-1],
                           "iterative_error_pct": _error_pct(lv.solve.dp())} for lv in levels],
               "noise_m2_s2": noise, "convergence_tol_pct": STABLE_TOL * 100.0}
    if res is not None:
        payload["gci"] = {k: v for k, v in vars(res).items()}
    payload.update(extra)
    hists = [_history(ctx, gid, f"history_level{lv.k}.csv", lv.solve.dp(), rho)
             for lv in levels]
    logs = [p for lv in levels for p in lv.solve.logs]
    return [_evidence(ctx, gid, payload), *hists, *logs]


@gate(
    id="cfd.mesh_independence",
    basis="sourced",
    title="Three meshes agree: the grid convergence index (Celik et al. 2008) is inside its limit",
    claims=["cfd", "fluid-dynamics", "pressure-drop", "internal-flow", "mesh-independence"],
    tier=Tier.SOLVE,
    settles="cfd mesh independence",
    requires_tools=list(T.WRAPPERS),
    needs=["cfd.converged"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:coarse",
        note="the baseline channel on a 10 x 2 starting mesh: one cell from the wall to the "
             "middle, the pressure drop still moving with the mesh",
    ),
)
def mesh_independence(ctx: GateContext) -> Verdict:
    """The case's mesh and two refinements of it, each by
    ``cfd_refinement_ratio`` along every refined direction (block cell counts
    multiplied; a 2D case's one-cell direction stays one cell), each solved to
    the pack's residual target. Celik et al. 2008: the pressure drop between the
    planes must converge monotonically, at an observed order in [0.95, formal +
    0.05], with the iterative error ten times below the change between the two
    finest meshes, and the fine-grid GCI must be at most ``cfd_gci_max_pct``.

    The asymptotic-range ratio GCI32 / (r^p GCI21) is reported and never used:
    with the order observed on the same three meshes it equals phi1/phi2
    whatever the data (``_gci.asymptotic_ratio``)."""
    gid = "cfd.mesh_independence"
    lim = _number(ctx, "cfd_gci_max_pct")
    if lim is None:
        return _skip(gid, "no cfd_gci_max_pct: the largest discretisation error the claim "
                          "tolerates, in percent of the pressure drop (no source sets one "
                          "for every case)")
    if isinstance(lim, str):
        return _error(gid, lim)
    if not lim > 0:
        return _error(gid, f"cfd_gci_max_pct is {lim:g}; it must be positive")
    got = _ladder(ctx, gid)
    if isinstance(got, Verdict):
        return got
    case, _planes_, target, note, r, rnote, levels = got
    res, why, noise = _gci(case, levels, target)
    gci_pct = None if res is None or res.gci_fine21 is None else res.gci_fine21 * 100.0
    ev = _ladder_evidence(ctx, gid, case, levels, res, noise, {"gci_max_pct": lim})
    cells = "/".join(str(lv.solve.cells) for lv in levels)
    if gci_pct is None or why:
        return Verdict(gate=gid, passed=False, detail="; ".join(why)[:400] + f" ({cells} cells)",
                       evidence=ev)
    passed = gci_pct <= lim
    return Verdict(gate=gid, passed=passed, measured=round(gci_pct, 6), limit=lim,
                   comparator="<=", units="%",
                   detail=f"GCI {gci_pct:.3g}% {'within' if passed else 'past'} "
                          f"{lim:g}%: {cells} cells (ratio {r:g}{rnote}), monotone at observed "
                          f"order {res.p:.3g}, pressure drop {res.phi[0]:.6g} m^2/s^2 on the "
                          f"finest, {res.phi_ext21:.6g} extrapolated; target {target:g}{note}",
                   evidence=ev)


# --------------------------------------------------------------------------- #
# the analysis
# --------------------------------------------------------------------------- #
@gate(
    id="cfd.pressure_drop",
    basis="established",
    title="The static pressure drop between two planes, with its GCI band, is under the limit",
    claims=["cfd", "fluid-dynamics", "pressure-drop", "internal-flow"],
    tier=Tier.SOLVE,
    settles="pressure drop from cfd",
    requires_tools=list(T.WRAPPERS),
    needs=["cfd.mesh_independence"],
    negative_control=NegativeControl(
        fixture="selftest/bad_cases.py:thicker_fluid",
        note="the baseline channel with a fluid twice as viscous (20 cSt): the laminar "
             "pressure drop doubles",
    ),
)
def pressure_drop(ctx: GateContext) -> Verdict:
    """The area-averaged static pressure on the upstream plane minus that on the
    downstream plane, on the finest of the three meshes, times
    ``cfd_density_kg_m3`` (an incompressible solver's p is kinematic, m^2/s^2).
    The value judged is the top of its GCI band, dp x (1 + GCI), against
    ``cfd_dp_max_pa``: a pressure drop is a claim about at most, and the mesh's
    share of the error goes on the side that fails."""
    gid = "cfd.pressure_drop"
    vals = {}
    for key, what in (("cfd_density_kg_m3", "the fluid's density, which turns the solver's "
                                            "kinematic pressure into pascals"),
                      ("cfd_dp_max_pa", "the largest pressure drop the claim allows, Pa")):
        v = _number(ctx, key)
        if v is None:
            return _skip(gid, f"no {key}: {what}")
        if isinstance(v, str):
            return _error(gid, v)
        if not v > 0:
            return _error(gid, f"{key} is {v:g}; it must be positive")
        vals[key] = v
    got = _ladder(ctx, gid)
    if isinstance(got, Verdict):
        return got
    case, _planes_, target, _note, r, _rnote, levels = got
    res, why, noise = _gci(case, levels, target)
    rho, limit = vals["cfd_density_kg_m3"], vals["cfd_dp_max_pa"]
    if res is None or res.gci_fine21 is None or why:
        # cfd.mesh_independence passed on these same meshes, or this gate would
        # not have run: a GCI that does not hold here is the two disagreeing.
        return _error(gid, "the meshes give no GCI band: " + "; ".join(why)[:300],
                      _ladder_evidence(ctx, gid, case, levels, res, noise, {}, rho))
    if not res.phi[0] > 0:
        # What slipped through the first draft: the drop was taken as a
        # magnitude, so a pressure RISE between the planes (a pump, a diffuser,
        # the planes named in the wrong order) read as a drop under the limit.
        return _error(gid, f"the pressure on the downstream plane is not below the upstream "
                           f"one ({rho * res.phi[0]:.5g} Pa): a rise, or the planes in the "
                           f"wrong order",
                      _ladder_evidence(ctx, gid, case, levels, res, noise, {}, rho))
    dp_pa = rho * res.phi[0]
    top = dp_pa * (1.0 + res.gci_fine21)
    ev = _ladder_evidence(ctx, gid, case, levels, res, noise,
                          {"density_kg_m3": rho, "dp_pa": dp_pa, "band_top_pa": top,
                           "dp_ext_pa": rho * res.phi_ext21, "limit_pa": limit}, rho)
    passed = top <= limit
    return Verdict(gate=gid, passed=passed, measured=round(top, 9), limit=limit,
                   comparator="<=", units="Pa",
                   detail=f"pressure drop {dp_pa:.5g} Pa on the finest mesh "
                          f"({levels[-1].solve.cells} cells) + GCI {res.gci_fine21 * 100:.3g}% "
                          f"= {top:.5g} Pa, {'within' if passed else 'past'} {limit:g} Pa; "
                          f"{rho * res.phi_ext21:.5g} Pa extrapolated",
                   evidence=ev)
