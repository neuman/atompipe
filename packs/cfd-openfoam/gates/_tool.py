# SPDX-License-Identifier: Apache-2.0
"""How cfd-openfoam finds and runs OpenFOAM, and how it reads what OpenFOAM
wrote. Standard library only.

Every rule here exists because a run can look finished when it is not. Each was
seen on ESI OpenFOAM v2606 (``2606.0~rc2``, build ``_481094f-20260618``) while
this pack was written:

- checkMesh exits 0 on ``Failed 4 mesh checks.`` (checkMesh.C ends ``return 0;``),
  so its exit code decides nothing; the text does.
- simpleFoam exits 0 and prints ``End`` when it runs out of iterations without
  meeting its residual targets. Only the line ``SIMPLE solution converged in N
  iterations`` says it converged.
- A diverging run dies on SIGFPE (exit -8) only while floating-point trapping is
  on, and a user's ``~/.OpenFOAM/<api>/controlDict`` can turn trapping off with no
  warning: the run then carries NaN on. So every tool runs with ``FOAM_SIGFPE``
  set and a private HOME, and a log whose header does not say trapping is on is
  an error.
- ``#calc``, ``#codeStream`` and ``coded*`` make OpenFOAM compile and run C++ from
  the case. The private HOME turns ``allowSystemOperations`` off, and a log whose
  header does not say it is off is an error.
- A re-run in a used directory writes ``surfaceFieldValue_0.dat`` beside the old
  file, and a reader can take the old one. Every run is in a fresh directory.
"""
from __future__ import annotations

import functools
import math
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field

#: The OpenFOAM API this pack was written and checked against. An install of
#: another API is refused (a skip that names it), never run on trust: ESI moves
#: function-object options and log lines between releases (v2606 itself wants
#: ``pointAndNormalDict`` inside a sampled plane, which older docs omit).
#: Rejected: any ESI release (one unchecked release can turn a reader's miss
#: into a pass); the Foundation's openfoam.org releases (another dialect: v13
#: has no simpleFoam, it runs ``foamRun`` with a ``solver`` entry).
SUPPORTED_APIS = (2606,)

#: The wrapper ESI's packages put on PATH, one per API. It is a shell script
#: that ends ``exec <install>/etc/openfoam "$@"``; the install is read from it.
WRAPPERS = tuple(f"openfoam{api}" for api in SUPPORTED_APIS)

#: Only the wrapper finds an install: availability (``requires_tools``) and the
#: gate must agree on what is there. Rejected: a ``simpleFoam`` on PATH as a
#: second way (the first draft's): availability then said a gate could run on
#: any release's simpleFoam, and the gate skipped itself on all but v2606, the
#: pattern PACK_FORMAT forbids; and a test's stand-in lost to the real install in
#: a shell that had sourced etc/bashrc. A self-built v2606 gets a two-line
#: wrapper (references/installing.md).

_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?nan|[-+]?inf)"


class Unavailable(Exception):
    """No OpenFOAM this pack can use: a skip, naming why."""


class RunError(Exception):
    """A tool ran and did not finish: an error, never a fail."""

    def __init__(self, message: str, evidence: list[str] | None = None):
        super().__init__(message)
        self.evidence = evidence or []


class Timeout(Exception):
    """A tool ran past its time and was killed: a skip, nothing was shown."""


# --------------------------------------------------------------------------- #
# finding the install
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Install:
    root: str          # the install directory (WM_PROJECT_DIR)
    api: int
    patch: str
    build: str         # from META-INFO/build-info, or ""
    via: str           # how it was found, for the skip and the evidence


def _api_info(root: str) -> dict:
    out: dict = {}
    for name in ("api-info", "build-info"):
        try:
            with open(os.path.join(root, "META-INFO", name), encoding="utf-8") as fh:
                out.update(re.findall(r"^(\w+)\s*=\s*(\S+)", fh.read(), re.M))
        except OSError:
            continue
    return out


def _from_wrapper(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(4096)
    except OSError:
        return None
    # v2606's: exec "/usr/lib/openfoam/openfoam2606"/etc/openfoam "$@"
    m = re.search(r'exec\s+"?(/[^"\s]+?)"?/etc/openfoam\b', text)
    return m.group(1) if m else None


def locate() -> Install:
    """The ESI OpenFOAM install to run, or :class:`Unavailable` naming why."""
    tried = []
    roots = []
    for name in WRAPPERS:
        path = shutil.which(name)
        if path:
            root = _from_wrapper(path)
            tried.append(f"{name} at {path}")
            if root:
                roots.append((root, f"{name} ({path})"))
    if not roots:
        raise Unavailable("no ESI OpenFOAM found: " + " nor ".join(WRAPPERS) + " is not on PATH"
                          + (f" or names no install ({', '.join(tried)})" if tried else ""))
    problems = []
    for root, via in roots:
        if not os.path.isfile(os.path.join(root, "etc", "bashrc")):
            problems.append(f"{via}: no etc/bashrc under {root}")
            continue
        info = _api_info(root)
        if "api" not in info:
            problems.append(f"{via}: {root} has no META-INFO/api-info, so it is not an ESI "
                            f"(openfoam.com) install; this pack does not run the openfoam.org "
                            f"releases")
            continue
        try:
            api = int(info["api"])
        except ValueError:
            problems.append(f"{via}: api-info says api={info['api']!r}")
            continue
        if api not in SUPPORTED_APIS:
            problems.append(f"{via}: OpenFOAM v{api}; this pack is checked on "
                            f"{', '.join('v%d' % a for a in SUPPORTED_APIS)} only")
            continue
        return Install(root=root, api=api, patch=str(info.get("patch", "")),
                       build=str(info.get("build", "")), via=via)
    raise Unavailable("; ".join(problems))


# --------------------------------------------------------------------------- #
# the environment
# --------------------------------------------------------------------------- #
#: The user controlDict every tool reads from the private HOME. Its one entry
#: turns off ``allowSystemOperations``, so a case that would compile and run
#: C++ (``#calc``, ``#codeStream``, ``coded*``) stops with an error. Measured:
#: ``-info-switch allowSystemOperations=0`` on the command line does NOT work on
#: v2606 (the switch is "unregistered"); this file does.
_USER_CONTROLDICT = ("FoamFile { version 2.0; format ascii; class dictionary; "
                     "object controlDict; }\nInfoSwitches { allowSystemOperations 0; }\n")

def home(out_dir: str, api: int) -> str:
    """A HOME of the gate's own under its out directory, holding only the user
    controlDict above. The person's own ``~/.OpenFOAM`` never reaches a run."""
    root = os.path.join(out_dir, "cfd-openfoam", "home")
    cfg = os.path.join(root, ".OpenFOAM", str(api), "controlDict")
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    try:
        with open(cfg, encoding="utf-8") as fh:
            same = fh.read() == _USER_CONTROLDICT
    except OSError:
        same = False
    if not same:
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(_USER_CONTROLDICT)
    return root


def environment(inst: Install, home_dir: str) -> dict:
    """The environment ``etc/bashrc`` makes, sourced from a bare environment
    (0.2 to 0.5 s; the wrapper costs that on every call). Never the caller's
    own: what this process inherited is not what the run reads."""
    return dict(_sourced(inst.root, home_dir))


@functools.lru_cache(maxsize=8)
def _sourced(root: str, home_dir: str) -> tuple:
    """Cached with functools, which the spine empties before every gate,
    fixture and known-good run: a module-level dict here (the first draft's)
    outlived the run that filled it, and ``doctor`` named it."""
    inst_root = root
    bare = {"HOME": home_dir, "PATH": "/usr/bin:/bin", "USER": "nopekit", "LC_ALL": "C"}
    try:
        proc = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c",
             'source "$1/etc/bashrc" >/dev/null 2>&1; env -0', "bash", inst_root],
            env=bare, stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
            timeout=120)
    except FileNotFoundError as exc:
        raise Unavailable(f"could not launch bash to source {inst_root}/etc/bashrc: {exc}")
    except subprocess.TimeoutExpired:
        raise Timeout(f"sourcing {inst_root}/etc/bashrc took over 120 s")
    env = {}
    for item in proc.stdout.split(b"\0"):
        if b"=" in item:
            k, v = item.split(b"=", 1)
            env[k.decode("utf-8", "replace")] = v.decode("utf-8", "replace")
    if not env.get("FOAM_APPBIN") or not env.get("WM_PROJECT_DIR"):
        raise RunError(f"sourcing {inst_root}/etc/bashrc set no FOAM_APPBIN/WM_PROJECT_DIR "
                       f"(bash exited {proc.returncode}: "
                       f"{proc.stderr.decode('utf-8', 'replace').strip()[:200]})")
    env["FOAM_SIGFPE"] = "true"
    env["HOME"] = home_dir
    return tuple(sorted(env.items()))


# --------------------------------------------------------------------------- #
# running one tool
# --------------------------------------------------------------------------- #
@dataclass
class Run:
    tool: str
    rc: int
    stdout: str
    stderr: str
    log: str
    seconds: float = 0.0


def _fatal(text: str) -> str:
    """The first FOAM FATAL message in ``text``, on one line."""
    m = re.search(r"--> FOAM FATAL (?:IO )?ERROR.*?\n(.*?)(?:\n\s*\n|\Z)", text, re.S)
    if not m:
        return ""
    return " ".join(m.group(1).split())[:300]


def run(env: dict, case: str, argv: list[str], timeout: float, *, banner: bool = True,
        log: str | None = None) -> Run:
    """``argv`` (a tool in ``$FOAM_APPBIN`` and its arguments) with the case as
    its working directory, its output written to ``<case>/log.<tool>`` (or
    ``<case>/<log>``).

    A tool that dies on a signal or exits non-zero is a :class:`RunError`, and
    so, with ``banner`` (every solver and mesher), is one that never prints
    ``End`` or whose banner does not show the safety switches; past ``timeout``
    a :class:`Timeout`. ``foamDictionary`` prints no banner and no End."""
    import time
    tool = argv[0]
    exe = os.path.join(env["FOAM_APPBIN"], tool)
    log = os.path.join(case, log or f"log.{tool}")
    if not os.path.isfile(exe):
        raise RunError(f"{tool} is not in FOAM_APPBIN ({env['FOAM_APPBIN']})")
    if re.search(r"[\s\"']", os.path.abspath(case)):
        # Measured: blockMesh exits 1 with "fileName::stripInvalid() called for
        # invalid fileName" when the case's path holds a space.
        raise RunError(f"OpenFOAM refuses a case whose path holds a space or a quote, and "
                       f"this one does ({os.path.abspath(case)}): move the project to a "
                       f"path without them")
    call = dict(env, PWD=os.path.abspath(case))
    t0 = time.perf_counter()
    try:
        proc = subprocess.run([exe, *argv[1:]], cwd=case, env=call, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, text=True,
                              errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        raise Timeout(f"{tool} ran past {timeout:g} s (cfd_timeout_s) and was killed")
    seconds = time.perf_counter() - t0
    with open(log, "w", encoding="utf-8") as fh:
        fh.write(proc.stdout)
        if proc.stderr:
            fh.write("\n--- stderr ---\n" + proc.stderr)
    r = Run(tool, proc.returncode, proc.stdout, proc.stderr, log, seconds)
    if proc.returncode < 0:
        sig = -proc.returncode
        why = (" (SIGFPE: a floating-point exception, which in a solver is divergence)"
               if sig == 8 else "")
        raise RunError(f"{tool} was killed by signal {sig}{why}", [log])
    if proc.returncode != 0:
        msg = _fatal(proc.stderr) or _fatal(proc.stdout) or (proc.stderr or proc.stdout).strip()[-300:]
        raise RunError(f"{tool} exited {proc.returncode}: {msg}", [log])
    if not banner:
        return r
    check_header(r)
    if not re.search(r"^End\s*$", proc.stdout, re.M):
        raise RunError(f"{tool} exited 0 without printing End", [log])
    return r


def check_header(r: Run) -> None:
    """The banner every OpenFOAM tool prints, held to what this pack set up.
    Each line missing means the run was not the run the pack asked for."""
    head = r.stdout[:6000]
    m = re.search(r"^Build\s*:\s*(\S+)\s+OPENFOAM=(\d+)", head, re.M)
    if not m or int(m.group(2)) not in SUPPORTED_APIS:
        raise RunError(f"{r.tool}'s banner names no supported OpenFOAM build "
                       f"({m.group(0) if m else 'no Build line'})", [r.log])
    if "trapFpe: Floating point exception trapping enabled" not in head:
        raise RunError(f"{r.tool} ran without floating-point trapping, so a diverging run "
                       f"could carry NaN to a number", [r.log])
    if "allowSystemOperations : Disallowing" not in head:
        raise RunError(f"{r.tool} ran with system operations allowed, so the case could "
                       f"compile and run its own code", [r.log])


# --------------------------------------------------------------------------- #
# reading what the tools wrote
# --------------------------------------------------------------------------- #
def block_mesh_cells(text: str) -> int:
    m = re.search(r"^\s*nCells:\s*(\d+)", text, re.M)
    if not m:
        raise ValueError("blockMesh's log has no nCells line")
    return int(m.group(1))


@dataclass
class MeshCheck:
    ok: bool
    cells: int
    directions: int            # geometric (non-empty/wedge) directions: 2 or 3
    non_ortho_deg: float
    skewness: float
    aspect_ratio: float
    failed: list[str] = field(default_factory=list)   # the *** lines


def check_mesh(text: str) -> MeshCheck:
    """checkMesh's text: every value this pack judges, or ValueError naming the
    one that is missing. The JSON (``-writeChecks json``) is not read: on v2606
    it disagrees with the text (a 75.96 degree mesh is ``Mesh OK.`` in the text
    and ``"fail"`` in the JSON, and its face-orientation count differs)."""
    def num(pattern: str, what: str) -> float:
        m = re.search(pattern + _NUM, text)
        if not m:
            raise ValueError(f"checkMesh's output has no {what}")
        return float(m.group(1))

    m = re.search(r"^\s*cells:\s+(\d+)\s*$", text, re.M)
    if not m:
        raise ValueError("checkMesh's output has no cell count")
    cells = int(m.group(1))
    m = re.search(r"Mesh has (\d) geometric \(non-empty/wedge\) directions", text)
    if not m:
        raise ValueError("checkMesh's output does not say how many directions the mesh has")
    hi_ar = re.search(r"High aspect ratio cells found, Max aspect ratio: " + _NUM, text)
    aspect = float(hi_ar.group(1)) if hi_ar else num(r"Max aspect ratio = ", "maximum aspect ratio")
    oks = re.findall(r"^Mesh OK\.\s*$", text, re.M)
    fails = re.findall(r"^Failed (\d+) mesh checks\.\s*$", text, re.M)
    if len(oks) + len(fails) != 1:
        raise ValueError(f"checkMesh's output has {len(oks) + len(fails)} verdict lines, not one")
    return MeshCheck(
        ok=bool(oks), cells=cells, directions=int(m.group(1)),
        non_ortho_deg=num(r"Mesh non-orthogonality Max: ", "maximum non-orthogonality"),
        skewness=num(r"Max skewness = ", "maximum skewness"),
        aspect_ratio=aspect,
        failed=[ln.strip() for ln in text.splitlines() if ln.strip().startswith("***")])


@dataclass
class SolverLog:
    converged_in: int | None      # the iteration the converged line names, or None
    last_iteration: int
    residuals: dict               # field component -> its last initial residual
    criteria: dict = field(default_factory=dict)   # field -> the tolerance the run used


def solver_log(text: str, algorithm: str = "SIMPLE") -> SolverLog:
    """What a steady solver's log says about how it stopped."""
    times = re.findall(r"^Time = (\S+)\s*$", text, re.M)
    if not times:
        raise ValueError("the solver's log has no iterations")
    last = times[-1]
    try:
        last_it = int(float(last))
    except ValueError:
        raise ValueError(f"the solver's last iteration is {last!r}")
    block = text[text.rindex(f"\nTime = {last}"):]
    residuals: dict = {}
    for name, value in re.findall(r"Solving for (\w+), Initial residual = " + _NUM, block):
        residuals.setdefault(name, float(value))       # the first solve of each field
    m = re.search(rf"^{algorithm} solution converged in (\d+) iterations", text, re.M)
    # The criteria the run itself reports, before its first iteration:
    #   SIMPLE: convergence criteria
    #       field p\t tolerance 1e-06
    criteria = {}
    head = re.search(rf"^{algorithm}: convergence criteria\s*\n((?:\s+field .*\n)*)", text, re.M)
    if head:
        for name, tol in re.findall(r"field (\S+)\s+tolerance " + _NUM, head.group(1)):
            criteria[name] = float(tol)
    return SolverLog(int(m.group(1)) if m else None, last_it, residuals, criteria)


@dataclass
class Series:
    """One function object's ``.dat`` file: its header lines and its rows."""
    header: dict
    columns: list[str]
    rows: list[list]


def _cell(text: str):
    text = text.strip()
    if text.startswith("("):
        return tuple(float(x) for x in text.strip("()").split())
    return float(text)


def read_dat(path: str) -> Series:
    """A ``surfaceFieldValue.dat`` (tab-separated, vectors in parentheses)."""
    with open(path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    header, columns, rows = {}, [], []
    for line in lines:
        if line.startswith("#"):
            body = line[1:].strip()
            if body.startswith("Time"):
                columns = [c.strip() for c in body.split("\t") if c.strip()]
            elif ":" in body:
                k, _, v = body.partition(":")
                header[k.strip()] = v.strip()
            continue
        if not line.strip():
            continue
        cells = [c for c in line.split("\t") if c.strip()]
        if len(cells) != len(columns):
            raise ValueError(f"{path}: a row has {len(cells)} values under {len(columns)} columns")
        rows.append([_cell(c) for c in cells])
    if not columns:
        raise ValueError(f"{path} has no column header")
    return Series(header, columns, rows)


def finite(*values: float) -> bool:
    return all(isinstance(v, (int, float)) and math.isfinite(v) for v in values)


# --------------------------------------------------------------------------- #
# staging
# --------------------------------------------------------------------------- #
#: The three directories OpenFOAM reads a case from. A stage copies only the
#: files the guard read from them: never ``constant/polyMesh`` (the mesh is built
#: here, from ``system/blockMeshDict``), a time directory but ``0``,
#: ``processor*``, ``postProcessing`` or ``dynamicCode``: a run must not read
#: what an earlier run left behind.
CASE_DIRS = ("0", "constant", "system")


def stage(src: str, dst: str, files: list[str]) -> list[str]:
    """Copy ``files`` (paths relative to the case at ``src``, the ones the
    guard read) into the empty directory ``dst``. The copy is a Python read, so
    every file the run will read is keyed, though the tools' own reads are not
    seen; and a run reads nothing the guard did not."""
    if os.path.isdir(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    for rel in files:
        os.makedirs(os.path.join(dst, os.path.dirname(rel)), exist_ok=True)
        with open(os.path.join(src, rel), "rb") as fh:
            data = fh.read()
        with open(os.path.join(dst, rel), "wb") as fh:
            fh.write(data)
    return list(files)
