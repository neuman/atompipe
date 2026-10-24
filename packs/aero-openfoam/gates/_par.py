# SPDX-License-Identifier: Apache-2.0
"""How aero-openfoam runs OpenFOAM on several ranks, and how it reads what
snappyHexMesh, checkMesh and the solver wrote. Standard library only.

The pack's additions to the helpers it copies from cfd-openfoam (``_tool.py``,
``_foam.py``, ``_gci.py``, ``_iter.py``, held byte-identical by
``tests/test_aero_openfoam.TheSharedHelpersHaveNotDrifted``) live here, so the
copies stay copies. One consequence of the copy, kept on purpose: a serial
tool's timeout message names ``cfd_timeout_s``, so ``aero.py`` re-words it.
The private HOME is this pack's own, ``<out>/aero-openfoam/home``: the caller
names the pack (``_tool.home(out, api, PACK)``). What slipped through P3-P5
(review, 2026-10-23): the copy named cfd-openfoam's HOME, so the two packs'
gates wrote one directory.

Every rule here was measured on ESI OpenFOAM v2606 with Open MPI 4.1.6 (P0,
2026-10-23):

- Open MPI counts physical cores: ``mpirun -np 10`` on this 7-core machine stops
  with "There are not enough slots available". Every run passes
  ``--oversubscribe``, as OpenFOAM's own ``RunFunctions`` does.
- The master's banner is not evidence for the other ranks. A rank started with
  another HOME (no ``allowSystemOperations 0``) left the master's banner saying
  "Disallowing", and the run HUNG (both ranks at 94% CPU for ten minutes). So
  every parallel run is preceded by :func:`rank_probe`, which asks each rank
  what HOME and FOAM_SIGFPE it holds, and every run has a timeout that kills the
  whole process group (a killed mpirun leaves its ranks running otherwise).
- P0 found snappyHexMesh not reproducible run to run (the same cell count,
  other processor meshes). P3 found the cause: ``scotch`` decomposed one
  bit-identical mesh three ways in three runs. With the pack's
  ``hierarchical`` decomposition (``_fo.decompose_dict``) three runs gave the
  same meshes and the same drag-area history, bit for bit, in parallel.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field

from nopekit.modelio import load_path as _load_path

_HERE = os.path.dirname(os.path.abspath(__file__))
T = _load_path(os.path.join(_HERE, "_tool.py"))

_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[-+]?nan|[-+]?inf)"


class Timeout(Exception):
    """A tool ran past its time and was killed: a skip, nothing was shown."""


# --------------------------------------------------------------------------- #
# running on several ranks
# --------------------------------------------------------------------------- #
def _mpirun(env: dict) -> str:
    path = shutil.which("mpirun", path=env.get("PATH", ""))
    if not path:
        raise T.RunError("no mpirun on the PATH OpenFOAM's etc/bashrc sets: a parallel run "
                         "needs the MPI OpenFOAM was built with")
    return path


def _mpi_argv(env: dict, n: int, cmd: list[str]) -> list[str]:
    """``mpirun`` with ``n`` ranks over ``cmd``. ``-x HOME -x FOAM_SIGFPE``
    hands every rank the gate's HOME and the trapping switch: on one host Open
    MPI passes the whole environment anyway (P0), across hosts only what ``-x``
    names. Rejected: ``--use-hwthread-cpus`` (it still refuses above 14)."""
    return [_mpirun(env), "--oversubscribe", "-np", str(int(n)), "-x", "HOME", "-x",
            "FOAM_SIGFPE", *cmd]


def _call(argv: list[str], case: str, env: dict, timeout: float, what: str):
    """``(rc, stdout, stderr, seconds)``; :class:`Timeout` past ``timeout``,
    with the whole process group killed."""
    t0 = time.perf_counter()
    proc = subprocess.Popen(argv, cwd=case, env=dict(env, PWD=os.path.abspath(case)),
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, errors="replace",
                            start_new_session=True)
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        proc.communicate()
        raise Timeout(f"{what} ran past {timeout:g} s (aero_timeout_s) and was killed, with "
                      f"every rank")
    return proc.returncode, out, err, time.perf_counter() - t0


#: The line Open MPI prints when a rank dies on a signal; 8 is SIGFPE, which
#: with trapping on is a diverging solver (``_tool.py``).
_RANK_SIGNAL = re.compile(r"exited on signal (\d+)")


def run_parallel(env: dict, case: str, argv: list[str], n: int, timeout: float, *,
                 log: str | None = None) -> "T.Run":
    """``argv`` (a tool in ``$FOAM_APPBIN`` and its arguments) on ``n`` ranks
    with ``-parallel``, the case as its working directory, its output in
    ``<case>/log.<tool>``. The same refusals as ``_tool.run`` (a signal, a
    non-zero exit, no ``End``, a banner without trapping or with system
    operations allowed), and the banner must say ``nProcs : n``."""
    tool = argv[0]
    exe = os.path.join(env["FOAM_APPBIN"], tool)
    path = os.path.join(case, log or f"log.{tool}")
    if not os.path.isfile(exe):
        raise T.RunError(f"{tool} is not in FOAM_APPBIN ({env['FOAM_APPBIN']})")
    if re.search(r"[\s\"']", os.path.abspath(case)):
        raise T.RunError(f"OpenFOAM refuses a case whose path holds a space or a quote, and "
                         f"this one does ({os.path.abspath(case)})")
    rc, out, err, seconds = _call(_mpi_argv(env, n, [exe, *argv[1:], "-parallel"]), case,
                                  env, timeout, tool)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out)
        if err:
            fh.write("\n--- stderr ---\n" + err)
    r = T.Run(tool, rc, out, err, path, seconds)
    sig = _RANK_SIGNAL.search(err) or _RANK_SIGNAL.search(out)
    if rc < 0 or sig:
        num = -rc if rc < 0 else int(sig.group(1))
        why = (" (SIGFPE: a floating-point exception, which in a solver is divergence)"
               if num == 8 else "")
        raise T.RunError(f"{tool} on {n} ranks: a rank was killed by signal {num}{why}", [path])
    if rc != 0:
        msg = T._fatal(err) or T._fatal(out) or (err or out).strip()[-300:]
        raise T.RunError(f"{tool} on {n} ranks exited {rc}: {msg}", [path])
    T.check_header(r)
    m = re.search(r"^nProcs\s*:\s*(\d+)", out[:6000], re.M)
    if not m or int(m.group(1)) != int(n):
        raise T.RunError(f"{tool}'s banner says nProcs {m.group(1) if m else '(none)'}, not the "
                         f"{n} ranks the pack asked for", [path])
    if not re.search(r"^End\s*$", out, re.M):
        raise T.RunError(f"{tool} exited 0 without printing End", [path])
    return r


#: What :func:`rank_probe` asks each rank to print: its rank, its HOME and its
#: FOAM_SIGFPE. ``OMPI_COMM_WORLD_RANK`` is Open MPI's, ``PMI_RANK`` MPICH's.
_PROBE = 'printf "rank=%s|%s|%s\\n" "${OMPI_COMM_WORLD_RANK:-$PMI_RANK}" "$HOME" "$FOAM_SIGFPE"'


def rank_probe(env: dict, case: str, n: int, timeout: float) -> str:
    """Every one of ``n`` ranks holds the gate's HOME (where the user
    controlDict turns ``allowSystemOperations`` off) and ``FOAM_SIGFPE=true``,
    asked of each rank through the same mpirun options the tools run with: the
    probe log's path, or :class:`T.RunError` naming the rank that differs.

    What slipped through P0: a rank given another HOME left the master's banner
    saying "Disallowing" and hung; only a question put to each rank sees it.
    Rejected: a ``#codeStream`` probe per rank (P0's Probe A: it shows OpenFOAM's
    own refusal, but an MPI_ABORT reports only the first rank to reach it, so it
    takes ``n`` failing runs to see every rank)."""
    path = os.path.join(case, "log.rankProbe")
    rc, out, err, _s = _call(_mpi_argv(env, n, ["/bin/sh", "-c", _PROBE]), case, env, timeout,
                             "the rank probe")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(out + (("\n--- stderr ---\n" + err) if err else ""))
    if rc != 0:
        raise T.RunError(f"the rank probe on {n} ranks exited {rc}: {(err or out).strip()[-300:]}",
                         [path])
    seen: dict[int, tuple] = {}
    for rank, home, fpe in re.findall(r"^rank=(\d*)\|(.*)\|(.*)$", out, re.M):
        if not rank.isdigit():
            raise T.RunError("the rank probe: a rank that does not say which it is", [path])
        seen[int(rank)] = (home, fpe)
    if sorted(seen) != list(range(int(n))):
        raise T.RunError(f"the rank probe heard from ranks {sorted(seen)}, not 0 to {n - 1}",
                         [path])
    for rank, (home, fpe) in sorted(seen.items()):
        if home != env.get("HOME"):
            raise T.RunError(f"rank {rank} runs with HOME {home!r}, not the gate's: its "
                             f"OpenFOAM could compile and run the case's code", [path])
        if fpe != "true":
            raise T.RunError(f"rank {rank} runs without FOAM_SIGFPE=true: a diverging run could "
                             f"carry NaN to a number", [path])
    return path


# --------------------------------------------------------------------------- #
# reading what the mesher and checkMesh wrote
# --------------------------------------------------------------------------- #
_COUNT_LINE = re.compile(r"^\s{2,}(\S.*?)\s*:\s*(\d+)\s*$")


def faces_in_error(text: str, which: int = -1) -> list[tuple[str, int]] | None:
    """The ``which``-th "Checking faces in error :" block (the last by default)
    as ``[(description, count)]``, in its order; None when there is none."""
    starts = [m.end() for m in re.finditer(r"^Checking faces in error :\s*$", text, re.M)]
    if not starts:
        return None
    rows = []
    for line in text[starts[which]:].splitlines()[1:]:
        m = _COUNT_LINE.match(line)
        if not m:
            break
        rows.append((m.group(1), int(m.group(2))))
    return rows


def thresholds(rows: list[tuple[str, int]]) -> tuple:
    """The numbers each description states (``(0..1)`` dropped), for holding a
    block to the dictionary it was judged against (``_fo.CHECKED``)."""
    out = []
    for desc, _n in rows:
        nums = re.findall(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?",
                          desc.replace("(0..1)", ""))
        out.append(tuple(float(x) for x in nums))
    return tuple(out)


@dataclass
class Snappy:
    """What snappyHexMesh's log says about how it finished."""
    finished_ok: bool            # "Finished meshing without any errors"
    cap: int | None              # the cell limit it reached, or None
    final: list | None           # the final mesh check's (description, count) rows
    cells: int | None            # cells of the last mesh it wrote
    layers: tuple | None         # (faces extruded, faces, percent) at the last layer pass


def snappy(text: str) -> Snappy:
    """snappyHexMesh's log, read. What slipped through P0: a mesher capped by
    ``maxGlobalCells`` still prints "Finished meshing without any errors" (the
    spheroid at 20 000: "No cells marked for refinement since reached limit
    20000.", 27 429 cells, layer coverage 41% against 100%), so the cap is read
    from its own line."""
    cap = re.findall(r"reached limit (\d+)", text)
    final = None
    m = re.search(r"^Checking final mesh \.\.\.\s*$", text, re.M)
    if m:
        final = faces_in_error(text[m.start():], 0)
    cells = re.findall(r"^(?:Layer|Snapped|Refined) mesh\s*:\s*cells:(\d+)", text, re.M)
    lay = re.findall(r"^Extruding (\d+) out of (\d+) faces \(" + _NUM + r"%\)", text, re.M)
    return Snappy(finished_ok=bool(re.search(r"^Finished meshing without any errors\s*$",
                                             text, re.M)),
                  cap=int(cap[-1]) if cap else None, final=final,
                  cells=int(cells[-1]) if cells else None,
                  layers=(int(lay[-1][0]), int(lay[-1][1]), float(lay[-1][2])) if lay else None)


def mesh_cells(text: str) -> int:
    m = re.search(r"^\s*cells:\s+(\d+)\s*$", text, re.M)
    if not m:
        raise ValueError("checkMesh's output has no cell count")
    return int(m.group(1))


# --------------------------------------------------------------------------- #
# reading what the solver wrote
# --------------------------------------------------------------------------- #
def iterations(text: str) -> list[str]:
    """The solver log split at each ``Time = N`` line: one block per
    iteration, in order."""
    return re.split(r"^Time = \S+\s*$", text, flags=re.M)[1:]


def initial_residuals(blocks: list[str]) -> dict:
    """``{field component: [the first initial residual in each iteration]}``."""
    out: dict = {}
    for b in blocks:
        seen = set()
        for name, v in re.findall(r"Solving for (\w+), Initial residual = " + _NUM, b):
            if name not in seen:
                seen.add(name)
                out.setdefault(name, []).append(float(v))
    return out


def bounding(blocks: list[str]) -> dict:
    """``{field: iterations in which the solver bounded it}`` (``bounding
    omega, min: ...``): kOmegaSST clipping a negative omega or k. Reported,
    never judged (the motorBike's L0 bounds omega in all 1500 iterations, min
    -1.75e5, and settles at 0.24%; P0)."""
    out: dict = {}
    for b in blocks:
        for name in sorted(set(re.findall(r"^bounding (\w+),", b, re.M))):
            out[name] = out.get(name, 0) + 1
    return out


def half_range(values: list[float], window: int):
    """``(U_I, lo, hi, mean)`` over the last ``window`` values: U_I = (max -
    min) / 2, the iterative uncertainty of an oscillating history (ITTC
    7.5-03-01-01, 2017: half the range between the oscillation's maximum and
    minimum; references/convergence.md). None when fewer than ``window``
    values, or any value not finite."""
    if window < 1 or len(values) < window:
        return None
    w = values[-window:]
    if not all(isinstance(v, float) and math.isfinite(v) for v in w):
        return None
    lo, hi = min(w), max(w)
    return 0.5 * (hi - lo), lo, hi, sum(w) / len(w)


def drift(values: list[float], window: int):
    """``(mean of the last window, mean of the window before)``, or None with
    fewer than two windows. What slipped through the half-range on its own (P0):
    the motorBike L0's window mean moved +0.59% between iteration 500 and 1000
    while U_I at 500 was 0.27%. Reported beside U_I; no source sets a limit."""
    if window < 1 or len(values) < 2 * window:
        return None
    a, b = values[-window:], values[-2 * window:-window]
    return sum(a) / window, sum(b) / window


@dataclass
class Coefficients:
    iterations: list = field(default_factory=list)
    cda: list = field(default_factory=list)
    header: dict = field(default_factory=dict)


def coefficients(path: str) -> Coefficients:
    """forceCoeffs' ``coefficient.dat``: the iteration and its Cd column (the
    drag area in m^2, with Aref 1). ValueError on a file without them, or an
    iteration written twice or out of order."""
    s = T.read_dat(path)
    if "Cd" not in s.columns or s.columns[0] != "Time":
        raise ValueError(f"{path}: no Time and Cd columns ({s.columns[:3]})")
    ic = s.columns.index("Cd")
    its = [row[0] for row in s.rows]
    if its != sorted(set(its)):
        raise ValueError(f"{path}: an iteration written twice or out of order")
    return Coefficients([int(round(t)) for t in its], [float(row[ic]) for row in s.rows],
                        dict(s.header))
