# SPDX-License-Identifier: Apache-2.0
"""A stand-in OpenFOAM v2606 and Open MPI for tests/test_aero_openfoam.py: every
tool aero-openfoam runs, in one script, dispatched on the name it runs as.

It grows no codec and computes no flow. It replays the bytes the real tools
wrote on the baseline spheroid (``tests/aero_fixtures/``: snappyHexMesh's and
checkMesh's logs, trimmed to the lines the gates read, each line verbatim) under
a banner shaped as v2606 prints it, and changes only what a test's mode asks
for. The mode is ``$WM_PROJECT_DIR/standin.json``; each tool it runs is appended
to ``$WM_PROJECT_DIR/calls``.

The banner follows the environment as the real one does: the trapping line only
with ``FOAM_SIGFPE=true``, the disallowing line only when
``$HOME/.OpenFOAM/2606/controlDict`` sets ``allowSystemOperations 0``, and
``nProcs`` the rank count ``mpirun`` was given.

``mpirun`` runs an OpenFOAM tool in its own process (with ``STANDIN_NPROCS``)
and answers the rank probe as each rank would, from the mode. It starts no
process: a test's subprocess goes through ``tests/_env.run``.

Not a test module: its name starts with ``_``, as tests/_env.py's does.
"""
import json
import os
import re
import runpy
import signal
import sys
import time

ROOT = os.environ.get("WM_PROJECT_DIR", "")
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "aero_fixtures")
with open(os.path.join(ROOT, "standin.json"), encoding="utf-8") as fh:
    MODE = json.load(fh)
TOOL = os.environ.get("STANDIN_TOOL") or os.path.basename(sys.argv[0])
with open(os.path.join(ROOT, "calls"), "a", encoding="utf-8") as fh:
    fh.write(TOOL + "\n")
FOAM_TOOLS = ("blockMesh", "decomposePar", "snappyHexMesh", "checkMesh", "foamDictionary",
              "surfaceCheck", "surfaceFeatureExtract", "potentialFoam", "simpleFoam")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return fh.read()


def banner() -> str:
    n = os.environ.get("STANDIN_NPROCS", "1")
    lines = ["/*---------------------------------------------------------------------------*\\",
             "| =========                 |                                                 |",
             "| \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox           |",
             "|  \\\\    /   O peration     | Version:  2606                                  |",
             "\\*---------------------------------------------------------------------------*/",
             f"Build  : _standin-20260618 OPENFOAM={MODE.get('api', 2606)} version=2606",
             f"Exec   : {TOOL} {' '.join(sys.argv[1:])}", f"Case   : {os.getcwd()}",
             f"nProcs : {MODE.get('nprocs_banner', n)}"]
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
    lines.append("// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //")
    return "\n".join(lines) + "\n"


def end(text: str = "") -> None:
    print(text, end="")
    if not MODE.get(TOOL, {}).get("no_end"):
        print("\nEnd\n")
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
    if how == "hang":
        sys.stdout.flush()
        time.sleep(600)


def block_mesh():
    """Cells and box of the staged blockMeshDict, read as simply as the
    baseline's is written (no macros)."""
    text = open(os.path.join("system", "blockMeshDict")).read()
    counts = [tuple(int(n) for n in m) for m in
              re.findall(r"hex\s*\([\d\s]+\)\s*\((\d+)\s+(\d+)\s+(\d+)\)", text)]
    body = re.search(r"vertices\s*\((.*?)\);", text, re.S)
    verts = [tuple(float(c) for c in v.split()) for v in re.findall(r"\(([^()]+)\)", body.group(1))]
    lo = [min(v[k] for v in verts) for k in range(3)]
    hi = [max(v[k] for v in verts) for k in range(3)]
    return sum(a * b * c for a, b, c in counts), lo, hi


# --------------------------------------------------------------------------- #
# mpirun
# --------------------------------------------------------------------------- #
if TOOL == "mpirun":
    args = sys.argv[1:]
    n, i = 1, 0
    while i < len(args):
        if args[i] == "-np":
            n = int(args[i + 1])
            i += 2
        elif args[i] == "-x":
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            break
    cmd = args[i:]
    probe = MODE.get("probe", {})
    if os.path.basename(cmd[0]) in FOAM_TOOLS:
        # One process for every rank, as the stand-in computes nothing: the
        # tool runs in this one, so its exit, its signal and its End are
        # mpirun's.
        os.environ.update(STANDIN_TOOL=os.path.basename(cmd[0]), STANDIN_NPROCS=str(n))
        sys.argv = cmd
        runpy.run_path(__file__, run_name="__main__")
        sys.exit(0)
    # The rank probe (``_par.rank_probe``): what ``printf`` prints on each
    # rank, from each rank's environment as the mode sets it.
    if cmd[:2] != ["/bin/sh", "-c"] or "OMPI_COMM_WORLD_RANK" not in cmd[2]:
        sys.stderr.write(f"stand-in mpirun: not a command it knows: {cmd}\n")
        sys.exit(2)
    for rank in range(n):
        if rank == probe.get("missing_rank"):
            continue
        home = "/elsewhere" if rank == probe.get("home_rank") else os.environ.get("HOME", "")
        fpe = "" if rank == probe.get("fpe_rank") else os.environ.get("FOAM_SIGFPE", "")
        print(f"rank={rank}|{home}|{fpe}")
    sys.exit(0)


# --------------------------------------------------------------------------- #
# the OpenFOAM tools
# --------------------------------------------------------------------------- #
if TOOL == "foamDictionary":
    # ``foamDictionary -expand FILE``: the file with every include and macro
    # applied, and no banner. The stand-in's cases hold none, so the file
    # itself; ``expand_append`` adds what a merge would.
    rel = sys.argv[-1]
    text = open(rel).read()
    text += MODE.get("expand_append", {}).get(rel, "")
    print(text)
    sys.exit(0)

print(banner(), end="")
fail_if_asked()

if TOOL == "blockMesh":
    cells, lo, hi = block_mesh()
    cells += MODE.get("blockMesh", {}).get("cells_delta", 0)
    end(f"Creating block mesh topology\n  nCells: {cells}\n  boundingBox: "
        f"({lo[0]:g} {lo[1]:g} {lo[2]:g}) ({hi[0]:g} {hi[1]:g} {hi[2]:g})\n")

if TOOL == "surfaceFeatureExtract":
    end("Extracting features\n")

if TOOL == "surfaceCheck":
    lo, hi = MODE.get("surfaceCheck", {}).get(
        "box", [[-0.291665, -0.350289, -4.232e-05], [1.75115, 0.332267, 1.35152]])
    for k in range(23):          # the real one writes about 23 files where it runs
        open(f"standin_part_{k}.obj", "w").close()
    end(f"Statistics:\nTriangles    : 331653 in 67 region(s)\nVertices     : 132871\n"
        f"Bounding Box : ({lo[0]} {lo[1]} {lo[2]}) ({hi[0]} {hi[1]} {hi[2]})\n")

if TOOL == "decomposePar":
    text = open(os.path.join("system", "decomposeParDict")).read()
    n = int(re.search(r"numberOfSubdomains\s+(\d+)", text).group(1))
    for k in range(n):
        os.makedirs(f"processor{k}/0", exist_ok=True)
        os.makedirs(f"processor{k}/constant", exist_ok=True)
    end(f"Decomposing mesh\nNumber of processors: {n}\n")

if TOOL == "snappyHexMesh":
    m = MODE.get("snappyHexMesh", {})
    # The capped log when the mode asks for it, or when the staged cap is below
    # the cells the baseline meshed to, as the real snappyHexMesh stops there:
    # so the pack's own cell_cap control fails on the stand-in, and a project
    # check qualifies aero.mesh_quality on it (OneSetOfInputsIsOneEntry).
    base = fixture("snappy_baseline.log")
    cells = int(re.findall(r"^Layer mesh : cells:(\d+)", base, re.M)[-1])
    cap = re.search(r"^\s*maxGlobalCells\s+(\d+);",
                    open(os.path.join("system", "snappyHexMeshDict")).read(), re.M)
    capped = m.get("log") == "capped" or (cap is not None and int(cap.group(1)) < cells)
    text = fixture("snappy_capped.log") if capped else base
    for old, new in m.get("replace", []):
        text = text.replace(old, new)
    print(text, end="")
    sys.exit(0)

if TOOL == "checkMesh":
    m = MODE.get("checkMesh", {})
    text = fixture("checkMesh_baseline.log")
    try:
        cells = re.findall(r"^Layer mesh : cells:(\d+)", open("log.snappyHexMesh").read(), re.M)
    except OSError:
        cells = []
    if cells:
        text = re.sub(r"^(\s+cells:\s+)\d+", lambda g: g.group(1) + cells[-1], text,
                      count=1, flags=re.M)
    for old, new in m.get("replace", []):
        text = text.replace(old, new)
    print(text, end="")
    sys.exit(0)

if TOOL == "potentialFoam":
    end("Calculating potential flow\n")

if TOOL == "simpleFoam":
    # The drag-area history the real simpleFoam wrote on the baseline
    # (spheroid_coefficient.dat, 300 iterations), cut at the staged endTime:
    # the first iterations of a longer run are those of a shorter one.
    m = MODE.get("simpleFoam", {})
    control = open(os.path.join("system", "controlDict")).read()
    budget = int(float(re.search(r"^endTime\s+(\S+);", control, re.M).group(1)))
    text = fixture("spheroid_coefficient.dat")
    head = [ln for ln in text.splitlines() if ln.startswith("#")]
    rows = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
    if budget > len(rows):
        sys.stderr.write(f"stand-in: the fixture holds {len(rows)} iterations, not {budget}\n")
        sys.exit(2)
    rows = rows[:budget]
    out = os.path.join("postProcessing", "forceCoeffs1", "0")
    os.makedirs(out, exist_ok=True)
    body = "\n".join(head) + "\n" + "\n".join(rows[:budget - m.get("rows_short", 0)]) + "\n"
    for old_text, new_text in m.get("replace", []):
        body = body.replace(old_text, new_text)
    with open(os.path.join(out, "coefficient.dat"), "w") as fh:
        fh.write(body)
    if "surfaces1" in control and not m.get("no_pictures"):
        files = [f"postProcessing/surfaces1/{budget}/{n}.vtp"
                 for n in ("body", "wakeIso", "wakeCut1", "wakeCut2", "wakeCut3")]
        files += [f"postProcessing/sets/{n}/{budget}/track0.vtp" for n in ("tracksCentre",
                                                                            "tracksFar")]
        for name in files:
            os.makedirs(os.path.dirname(name), exist_ok=True)
            with open(name, "w") as fh:
                fh.write(f"<!-- stand-in {name}, {budget} iterations -->\n")
    log = ["SIMPLE: no convergence criteria found. Calculations will run for "
           f"{budget} steps.\n"]
    for it in range(1, budget + 1):
        r = max(1e-6, 0.2 * 0.97 ** it)
        if it == budget and m.get("residual_climb"):
            r *= m["residual_climb"]
        log.append(f"Time = {it}\n")
        for f in ("Ux", "Uy", "Uz", "p", "omega", "k"):
            log.append(f"smoothSolver:  Solving for {f}, Initial residual = {r:.10g}, Final "
                       f"residual = {r / 10:.10g}, No Iterations 2")
        if it <= m.get("bounding", 0):
            log.append("bounding omega, min: -75096.5 max: 394078169 average: 1379.3")
        log.append("ExecutionTime = 0.01 s  ClockTime = 0 s\n")
    end("\n".join(log) + "\n")

sys.stderr.write(f"stand-in: unknown tool {TOOL}\n")
sys.exit(2)
