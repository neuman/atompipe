# SPDX-License-Identifier: Apache-2.0
"""A stand-in OpenFOAM v2606 tool for tests/test_cfd_openfoam.py: blockMesh,
checkMesh and simpleFoam in one script, dispatched on the name it runs as.

Its output is shaped as v2606 wrote it while the pack was written (the banner,
checkMesh's lines, simpleFoam's residual and converged lines, the
surfaceFieldValue .dat). What it prints is set by ``$WM_PROJECT_DIR/standin.json``,
which the test writes. It reads the staged case the way the real tools do:
blockMesh and simpleFoam take the cell counts from ``system/blockMeshDict``,
simpleFoam its iteration budget from ``system/controlDict``, its residual
target from ``system/fvSolution`` and its function objects' names from the
controlDict.

The banner follows the environment as the real one does: the trapping line only
with ``FOAM_SIGFPE=true``, the disallowing line only when
``$HOME/.OpenFOAM/2606/controlDict`` sets ``allowSystemOperations 0``.

Not a test module: its name starts with ``_``, as tests/_env.py's does.
"""
import json
import math
import os
import re
import signal
import sys

ROOT = os.environ.get("WM_PROJECT_DIR", "")
with open(os.path.join(ROOT, "standin.json"), encoding="utf-8") as fh:
    MODE = json.load(fh)
TOOL = os.environ.get("STANDIN_TOOL") or os.path.basename(sys.argv[0])
with open(os.path.join(ROOT, "calls"), "a", encoding="utf-8") as fh:
    fh.write(TOOL + "\n")


def banner() -> str:
    lines = ["/*---------------------------------------------------------------------------*\\",
             "| =========                 |                                                 |",
             "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |",
             "|  \\\\    /   O peration     | Version:  2606                                  |",
             "\\*---------------------------------------------------------------------------*/",
             f"Build  : _standin-20260618 OPENFOAM={MODE.get('api', 2606)} version=2606",
             f"Exec   : {TOOL}", f"Case   : {os.getcwd()}", "nProcs : 1"]
    if os.environ.get("FOAM_SIGFPE") == "true" and "no-fpe" not in MODE.get("omit", []):
        lines.append("trapFpe: Floating point exception trapping enabled (FOAM_SIGFPE).")
    cfg = os.path.join(os.environ.get("HOME", ""), ".OpenFOAM", "2606", "controlDict")
    if os.path.isfile(cfg) and "allowSystemOperations 0" in open(cfg).read() \
            and "allowing" not in MODE.get("omit", []):
        lines.append("allowSystemOperations : Disallowing user-supplied system call operations")
    else:
        lines.append("--> FOAM Warning : allowSystemOperations : Allowing user-supplied "
                     "system call operations.")
    lines.append("")
    lines.append("// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //")
    return "\n".join(lines) + "\n"


def counts():
    text = open(os.path.join("system", "blockMeshDict")).read()
    return [tuple(int(n) for n in m) for m in
            re.findall(r"hex\s*\([\d\s]+\)\s*(?:\w+\s*)?\((\d+)\s+(\d+)\s+(\d+)\)", text)]


def end(text: str = "") -> None:
    if MODE.get(TOOL, {}).get("no_end"):
        sys.exit(0)
    print(text + "End\n")
    sys.exit(0)


def fail_if_asked():
    how = MODE.get(TOOL, {}).get("fail")
    if how == "fpe":
        sys.stdout.flush()
        os.kill(os.getpid(), signal.SIGFPE)
    if how == "fatal":
        sys.stderr.write("\n--> FOAM FATAL IO ERROR: (openfoam-2606)\nkeyword nu is undefined in "
                         "dictionary \"transportProperties\"\n\nfile: transportProperties\n\n")
        sys.exit(1)


if TOOL == "foamDictionary":
    # ``foamDictionary -expand FILE``: the real one prints the file with every
    # include and macro applied, and no banner. The stand-in's cases hold none,
    # so the file itself; ``expand_append`` adds what a merge would.
    rel = sys.argv[-1]
    text = open(rel).read()
    text += MODE.get("expand_append", {}).get(rel, "")
    print(text)
    sys.exit(0)

print(banner(), end="")
fail_if_asked()

if TOOL == "blockMesh":
    n = sum(a * b * c for a, b, c in counts())
    print(f"Creating block mesh topology\n  nCells: {n}\n  boundingBox: (0 0 0) (0.1 0.01 0.001)\n")
    end()

if TOOL == "checkMesh":
    m = MODE.get("checkMesh", {})
    n = sum(a * b * c for a, b, c in counts())
    out = [f"Mesh stats\n    points:           {2 * n}\n    cells:            {n}\n",
           "Checking geometry...",
           f"    Mesh has {m.get('directions', 2)} geometric (non-empty/wedge) directions (1 1 0)"]
    if "aspect" not in m.get("omit", []):
        ar = m.get("aspect", 2.0)
        out.append(f" ***High aspect ratio cells found, Max aspect ratio: {ar:g}, number of cells 1"
                   if ar > 1000 else f"    Max aspect ratio = {ar:g} OK.")
    if "non_ortho" not in m.get("omit", []):
        out.append(f"    Mesh non-orthogonality Max: {m.get('non_ortho', 0.0):g} average: 0")
    out.append(f"    Max skewness = {m.get('skew', 4.4e-16):g} OK.")
    out.append("")
    out.append("Mesh OK." if m.get("ok", True) else
               " ***Zero or negative cell volume detected.\n\nFailed 1 mesh checks.")
    print("\n".join(out) + "\n")
    end()

if TOOL == "simpleFoam":
    m = MODE.get("simpleFoam", {})
    control = open(os.path.join("system", "controlDict")).read()
    budget = int(float(re.search(r"^endTime\s+(\S+);", control, re.M).group(1)))
    solution = open(os.path.join("system", "fvSolution")).read()
    target = float(re.search(r"residualControl\s*\{\s*p\s+(\S+);", solution).group(1))
    names = re.findall(r"^\s*(nopekit_\w+)\s*$", control, re.M)
    ny = counts()[0][1]
    # The pressure drop this mesh converges to: a law in the level's Ny.
    law = m.get("dp", "poiseuille")
    if law == "poiseuille":
        dp = 6.0e-4 / (1 + 2.0 / ny ** 2)
    elif law == "diverging":
        dp = 6.0e-4 * (1 + 1e-4 * ny)
    elif law == "oscillating":
        dp = 6.0e-4 * (1 + 0.02 * (-1) ** int(round(math.log2(ny / 10))) / ny)
    elif law == "fourth_order":
        dp = 6.0e-4 / (1 + 200.0 / ny ** 4)
    elif law == "low_order":
        dp = 6.0e-4 * (1 + 0.05 / ny ** 0.7)
    elif law == "coarse":
        dp = 6.0e-4 / (1 + 50.0 / ny ** 2)
    else:
        dp = float(law)
    dp *= m.get("scale", 1.0)
    stop = int(m.get("converge_at", 60)) if ny not in m.get("never_at_ny", []) else budget + 1
    last = min(stop, budget)
    converged = stop <= budget
    u = m.get("u", 0.01)
    rows = []
    tail = m.get("settle_tail")       # a slow geometric creep that never stops
    for it in range(1, last + 1):
        if tail:
            settle = tail * 0.97 ** it
        else:
            settle = 0.0 if (converged and it > last - 12) else 0.3 * math.exp(-it / 4.0)
        rows.append((it, dp * (1 + settle)))
    for k, name in enumerate(names):
        d = os.path.join("postProcessing", name, "0")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "surfaceFieldValue.dat"), "w") as fh:
            fh.write(f"# Region type :   sampledSurface {name}\n# Faces           : 20\n"
                     f"# Area            : {m.get('area', 1e-05):.10e}\n"
                     f"# Scale factor    : 1.0000000000e+00\n"
                     f"# Time            \tareaAverage(p)    \tareaAverage(U)\n")
            for it, v in rows:
                p = v if k == 0 else 0.0
                fh.write(f"{it}                 \t{p:.10e}\t({u:.10e} 0 0)\n")
    res = m.get("final_residual", target / 2) if converged else 1e-3
    criteria = m.get("criteria", {"p": target, "U": target})
    print("SIMPLE: convergence criteria")
    for name, tol in criteria.items():
        print(f"    field {name}\t tolerance {tol:g}")
    print("")
    for it in range(1, last + 1):
        print(f"Time = {it}\n")
        r = res if it == last else 0.1
        print(f"smoothSolver:  Solving for Ux, Initial residual = {r:.10g}, Final residual = "
              f"{r / 100:.10g}, No Iterations 2")
        print(f"smoothSolver:  Solving for Uy, Initial residual = {r:.10g}, Final residual = "
              f"{r / 100:.10g}, No Iterations 2")
        print(f"GAMG:  Solving for p, Initial residual = {r:.10g}, Final residual = "
              f"{r / 100:.10g}, No Iterations 2")
        print("ExecutionTime = 0.01 s  ClockTime = 0 s\n")
    if converged:
        print(f"\nSIMPLE solution converged in {last} iterations\n")
    end()

sys.stderr.write(f"stand-in: unknown tool {TOOL}\n")
sys.exit(2)
