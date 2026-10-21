# SPDX-License-Identifier: Apache-2.0
"""How cfd-openfoam finds, checks and runs ParaView's ``pvbatch`` to draw its
pictures. Standard library only; ParaView's own Python (with Pillow) runs the
scripts this module hands it, in a subprocess, never in nopekit's process.

No status depends on a picture. Everything here can only leave a picture out:
a missing, unchecked or failing ParaView is *unavailable* (a build warning),
and a run that did not finish as asked is an *error* of the picture. Neither
reaches a verdict, a claim or a count.

Every rule here was measured on ParaView 6.2.0 (conda-forge,
``py312ha24fc4a_1``) under WSL2 while this module was written:

- ParaView's Python reads the user's site-packages unless ``PYTHONNOUSERSITE``
  is set, and a user site with another numpy kills pvbatch with
  ``malloc(): invalid size`` (SIGABRT). So the run's environment is built from
  nothing, never inherited.
- Without ``GALLIUM_DRIVER=llvmpipe`` and ``LIBGL_ALWAYS_SOFTWARE=1`` Mesa may
  pick a GPU driver (D3D12 under WSL2), whose pixels differ by machine. With
  both set, two runs write byte-identical PNGs. The run's own ``result.json``
  must name llvmpipe, or its output is refused.
- pvbatch writes Mesa, X server and deprecation noise on stderr in every
  successful run, so stderr decides nothing.
- ParaView 6.2 calls matplotlib's viridis ``Viridis``; the name older ParaView
  used, ``Viridis (matplotlib)``, raises in ``ApplyPreset``.
- A lit display draws a cell about 22% darker than its colour on the scale,
  and a lookup table without an above-range colour draws a value past the
  scale in the end colour. The renderer control below catches both (planted
  and measured: the lit strip drew the middle cell (26, 111, 104) for
  (33, 144, 140), the clipped one drew (253, 231, 37) for magenta).

What the identity cannot see: the conda records are what the package manager
wrote, and the check reads them and hashes ``bin/pvbatch`` alone, so records
written by hand to name the locked packages pass it. The renderer control is
what then catches a renderer that draws other colours.
"""
from __future__ import annotations

import functools
import glob
import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass

HERE = os.path.dirname(os.path.abspath(__file__))

#: The launcher this pack finds ParaView through: a short shell script on PATH
#: whose exec line names ``<prefix>/bin/pvbatch`` (references/rendering.md).
#: Only the launcher: ParaView's ``bin/`` holds 426 programs, its own
#: ``python`` and ``pip`` among them, and on PATH it shadows the system ones.
#: Rejected: ``pvbatch`` on PATH (any ParaView build, and its ``bin/`` on PATH
#: with it); a path in a pack setting (a per-machine value in a project
#: record).
WRAPPER = "pvbatch62"

#: The ParaView builds this pack checked (its package sha256 values), beside
#: this file. Rejected: the ``--version`` banner alone (another 6.2.0 build
#: prints the same banner and may link another Mesa); the launcher's or
#: ``pvbatch``'s digest alone (28 KB of launcher, which identifies nothing of
#: the libraries that draw).
LOCK = os.path.join(HERE, "paraview.lock.json")

#: A JSON object, or a list of them, in the lock's ``accepted`` form, that
#: adds builds for this process. For tests and for a person trying a new
#: build. It is loud: every install it accepts says ``accepted_by:
#: environment`` and carries `UNCHECKED_WORD`.
EXTRA_LOCK_ENV = "NOPEKIT_PVBATCH_EXTRA_LOCK"

UNCHECKED_WORD = "A ParaView build that this pack did not check drew this picture."

#: The packages whose sha256 the lock holds. ParaView itself; Mesa's three
#: packages (the llvmpipe that draws, the gallium it runs in, the GL that
#: loads it); and Pillow, which reads the pixels of the renderer control.
#: Rejected: every package of the environment (265 of them; a rebuilt
#: libzlib would refuse a build that draws the same pixels), and ParaView
#: alone (the pixels are Mesa's).
LOCKED_PACKAGES = ("paraview", "mesalib", "mesa-libgallium", "mesa-llvmpipe", "pillow")

#: Seconds a pvbatch run may take before it is killed and the picture is left
#: out. Measured: 2.8 s for the renderer control, 0.7 s for ``--version``.
#: 120 s is the design's (B.3.2): far over the measured, and short enough that
#: a hung GL does not hold a ``site build`` for long.
TIMEOUT_S = 120
BANNER_TIMEOUT_S = 60



def sibling(stem: str):
    """``views/<stem>.py`` of this pack, loaded once under a name of the
    pack's own (``nopekit_cfd_openfoam<stem>``): the view loader puts the
    pack root on ``sys.path``, not ``views/``, and a bare ``import _scales``
    would take another pack's ``_scales`` if one were first. ``flow.py``
    loads this module the same way, so both share one copy of each."""
    name = f"nopekit_cfd_openfoam{stem}"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, f"{stem}.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module      # before exec: its dataclasses look it up
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


_scales = sibling("_scales")
#: The renderer control draws with the stills' map and their two colours past
#: the scale, from ``_scales.py`` (their provenance is there).
PRESET, OVER, UNDER = _scales.PRESET, _scales.OVER, _scales.UNDER
#: The fixture the control draws: 15 cells, t from -0.2 to 1.2 of [0, 1].
CONTROL_DATA = os.path.join(HERE, "fixture", "strip.vtk")
CONTROL_SCRIPT = os.path.join(HERE, "_control.py")
#: 600 x 120 px: each cell is 38 px wide and 38 px high, so its centre pixel
#: is 19 px from any edge an antialiased line could touch.
CONTROL_SIZE = (600, 120)
#: How far (per channel, in sRGB bytes) a cell inside the scale may be from
#: the lookup table's colour. Measured: 0 on the locked build. 1 allows one
#: rounding step of the float pipeline; the lit display it must catch is 33
#: off in green. Past the scale the colour must be exact: it is a flat colour,
#: never interpolated.
CONTROL_TOLERANCE = 1
#: The known pixel: viridis at 0.5 is (33, 145, 140), #21918c (matplotlib
#: 3.11.2's ``colormaps['viridis'](0.5)``, and ParaView 6.2's ``Viridis`` at
#: 0.5 with its default 256-colour table, both measured). It shows the preset
#: is viridis and not another map. The control draws with a continuous table
#: as the stills do (P2.3), and there the locked build draws (33, 144, 140),
#: half a byte from the table's point and inside `CONTROL_TOLERANCE`.
KNOWN = (0.5, (33, 145, 140))

#: The words a picture's absence says on the page and in ``doctor``.
NO_PICTURES = "The CFD pictures are not drawn. No status depends on them."
SEE = "See packs/cfd-openfoam/references/rendering.md."


class Unavailable(Exception):
    """No ParaView this pack can use here, or it ran past its time: the
    picture is left out, and the reason is said."""


class RunError(Exception):
    """pvbatch ran and did not finish as asked: the picture is left out."""


# --------------------------------------------------------------------------- #
# finding the install
# --------------------------------------------------------------------------- #
def prefix_from_wrapper(path: str) -> str | None:
    """The ParaView prefix the launcher's exec line names, or None. The
    launcher (references/rendering.md) ends::

        exec env -i HOME="$HOME" PATH=<prefix>/bin:/usr/bin:/bin ... \\
            <prefix>/bin/pvbatch --force-offscreen-rendering "$@"

    The prefix is the one before ``/bin/pvbatch``; a ``PATH=`` entry ends in
    ``/bin:`` and never matches."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read(8192)
    except OSError:
        return None
    for line in text.splitlines():
        if not re.match(r"\s*exec\b", line):
            continue
        found = re.findall(r"""(/[^\s"'=:]+?)/bin/pvbatch(?=["'\s]|$)""", line)
        if found:
            return found[-1]
    return None


@dataclass(frozen=True)
class Install:
    """A ParaView this pack may run: where it is, and which build it is."""
    prefix: str
    pvbatch: str
    via: str
    version: str
    build: str
    packages: tuple            # ((name, sha256), ...) of LOCKED_PACKAGES
    accepted_by: str           # "lock" or "environment"

    @property
    def name(self) -> str:
        return f"paraview-{self.version}-{self.build}"

    @property
    def identity(self) -> str:
        """``paraview-<version>-<build>:<sha12 of the paraview package>``."""
        sha = dict(self.packages).get("paraview", "")
        return f"{self.name}:{sha[:12]}"

    @property
    def tool_word(self) -> str:
        return UNCHECKED_WORD if self.accepted_by != "lock" else ""


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _accepted() -> list[tuple[dict, str]]:
    """``[(entry, accepted_by)]``: the lock's entries, then the environment's."""
    out: list[tuple[dict, str]] = []
    try:
        with open(LOCK, encoding="utf-8") as fh:
            lock = json.load(fh)
        out.extend((e, "lock") for e in lock.get("accepted") or () if isinstance(e, dict))
    except (OSError, ValueError, AttributeError):
        pass
    extra = os.environ.get(EXTRA_LOCK_ENV, "").strip()
    if extra:
        try:
            more = json.loads(extra)
        except ValueError:
            more = []
        for e in more if isinstance(more, list) else [more]:
            if isinstance(e, dict):
                out.append((e, "environment"))
    return out


def locate() -> Install:
    """The checked ParaView to run, or :class:`Unavailable` naming why."""
    path = shutil.which(WRAPPER)
    if not path:
        raise Unavailable(f"{WRAPPER} is not on PATH")
    prefix = prefix_from_wrapper(path)
    if not prefix:
        raise Unavailable(f"{WRAPPER} at {path} has no exec line that names "
                          f"<prefix>/bin/pvbatch")
    pvbatch = os.path.join(prefix, "bin", "pvbatch")
    try:
        st = os.stat(pvbatch)
        stamps = tuple((m, os.stat(m).st_mtime_ns, os.stat(m).st_size)
                       for m in _records(prefix))
    except OSError:
        raise Unavailable(f"{WRAPPER} at {path} names {pvbatch}, which is not there")
    extra = os.environ.get(EXTRA_LOCK_ENV, "")
    return _identity(prefix, f"{WRAPPER} ({path})", st.st_mtime_ns, st.st_size, stamps, extra)


def _records(prefix: str) -> list[str]:
    """The conda records that may be of a locked package: ``<name>-<digit>*.json``,
    never all 266 (vtk-base's alone lists 5392 files). Its name is read from
    inside each, so ``mesa-*`` cannot pass for another ``mesa-`` package."""
    out: list[str] = []
    for name in LOCKED_PACKAGES:
        out.extend(sorted(glob.glob(os.path.join(prefix, "conda-meta", f"{name}-[0-9]*.json"))))
    return out


@functools.lru_cache(maxsize=8)
def _identity(prefix: str, via: str, mtime: int, size: int, stamps: tuple,
              extra: str) -> Install:
    """The build at ``prefix``, held to the lock. Cached on the pvbatch file's
    and the conda records' mtime and size, and on the environment's extra
    lock: a reinstall in place moves them."""
    pvbatch = os.path.join(prefix, "bin", "pvbatch")
    records = {}
    for path in _records(prefix):
        try:
            with open(path, encoding="utf-8") as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(rec, dict) and rec.get("name") in LOCKED_PACKAGES:
            if rec["name"] in records:
                raise Unavailable(f"{prefix}/conda-meta holds two {rec['name']} records")
            records[rec["name"]] = rec
    pv = records.get("paraview")
    if pv is None:
        raise Unavailable(f"{prefix} has no conda record of paraview (conda-meta/"
                          f"paraview-*.json), so its build cannot be checked")
    version, build = str(pv.get("version", "")), str(pv.get("build", ""))
    name = f"paraview-{version}-{build}"
    # The pvbatch on disk is the one the paraview package put there.
    listed = [p for p in (pv.get("paths_data") or {}).get("paths") or ()
              if isinstance(p, dict) and p.get("_path") == "bin/pvbatch"]
    want = (listed[0].get("sha256_in_prefix") or listed[0].get("sha256")) if listed else None
    if not want:
        raise Unavailable(f"{name}'s conda record does not list bin/pvbatch")
    try:
        on_disk = _sha256(pvbatch)
    except OSError as exc:
        raise Unavailable(f"cannot read {pvbatch}: {exc}")
    if on_disk != want:
        raise Unavailable(f"{pvbatch} is not the file the {name} package installed "
                          f"(sha256 {on_disk[:12]}, the record says {want[:12]})")
    packages = tuple((n, str((records.get(n) or {}).get("sha256", ""))) for n in LOCKED_PACKAGES)
    accepted_by = ""
    for entry, by in _accepted():
        pkgs = entry.get("packages") or {}
        if (entry.get("paraview") == version and entry.get("build") == build
                and all(pkgs.get(n) == sha for n, sha in packages)):
            accepted_by = by
            break
    if not accepted_by:
        sha12 = dict(packages).get("paraview", "")[:12] or "no sha256"
        missing = [n for n, sha in packages if not sha]
        raise Unavailable(
            f"{WRAPPER} is ParaView build {name}:{sha12}, which this pack did not check"
            + (f" (no conda record of {', '.join(missing)})" if missing else "")
            + f": {os.path.basename(LOCK)} names the builds it checked")
    # The banner too, never alone: the lock says which build, the banner that
    # the program at that path runs as that build.
    banner = _banner(pvbatch)
    if f"paraview version {version}" not in banner:
        raise Unavailable(f"{pvbatch} --version says {banner.strip()[:80]!r}, not "
                          f"paraview version {version}")
    return Install(prefix=prefix, pvbatch=pvbatch, via=via, version=version, build=build,
                   packages=packages, accepted_by=accepted_by)


def _banner(pvbatch: str) -> str:
    with tempfile.TemporaryDirectory(prefix="nopekit-pv-") as home:
        try:
            proc = subprocess.run([pvbatch, "--version"], env=environment(home),
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE, text=True, errors="replace",
                                  timeout=BANNER_TIMEOUT_S, cwd=home)
        except subprocess.TimeoutExpired:
            raise Unavailable(f"{pvbatch} --version ran past {BANNER_TIMEOUT_S} s")
        except OSError as exc:
            raise Unavailable(f"cannot run {pvbatch}: {exc}")
    return proc.stdout


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #
def environment(home: str) -> dict:
    """The whole environment of a pvbatch run, built from nothing. No
    ``PYTHONPATH`` (the tests set one), no ``LD_LIBRARY_PATH``, no
    ``DISPLAY``: nothing of the caller's reaches ParaView. ``HOME`` is a new
    empty directory for each run, outside the project, so ParaView's own
    settings and caches (it writes ``~/.config/ParaView`` and ``~/.cache``)
    are never the person's and never land in the project."""
    return {"HOME": home, "PATH": "/usr/bin:/bin", "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1", "LC_ALL": "C", "GALLIUM_DRIVER": "llvmpipe",
            "LIBGL_ALWAYS_SOFTWARE": "1"}


def _signal_name(sig: int) -> str:
    try:
        return signal.Signals(sig).name
    except ValueError:
        return f"signal {sig}"


def run(inst: Install, script: str, job: dict, work: str, *,
        timeout: float = TIMEOUT_S) -> dict:
    """Run ``script`` in pvbatch on ``job`` (written as ``<work>/job.json``)
    and return its ``<work>/result.json``.

    Past ``timeout`` the run is killed and :class:`Unavailable`; killed by a
    signal or a nonzero exit, :class:`RunError`. A result is refused unless
    its ``done`` is the sha256 of this job's bytes (a result left by another
    run reads as this one) and its ``gl_renderer`` names llvmpipe (another GL
    draws other pixels on another machine)."""
    os.makedirs(work, exist_ok=True)
    job_path = os.path.join(work, "job.json")
    raw = json.dumps(job, indent=1, sort_keys=True).encode("utf-8")
    with open(job_path, "wb") as fh:
        fh.write(raw)
    result_path = os.path.join(work, "result.json")
    if os.path.exists(result_path):
        os.remove(result_path)
    log = os.path.join(work, "pvbatch.log")
    with tempfile.TemporaryDirectory(prefix="nopekit-pv-") as home, \
            open(log, "wb") as out:
        try:
            proc = subprocess.run(
                [inst.pvbatch, "--force-offscreen-rendering", script, job_path],
                env=environment(home), stdin=subprocess.DEVNULL, stdout=out,
                stderr=subprocess.STDOUT, timeout=timeout, cwd=work)
        except subprocess.TimeoutExpired:
            raise Unavailable(f"pvbatch ran past {timeout:g} s and was killed")
        except OSError as exc:
            raise Unavailable(f"cannot run {inst.pvbatch}: {exc}")
    if proc.returncode < 0:
        sig = -proc.returncode
        why = (" (SIGABRT is how pvbatch dies when its Python reads a user site; this run "
               "set PYTHONNOUSERSITE=1, so see its log)" if sig == signal.SIGABRT else "")
        raise RunError(f"pvbatch was killed by {_signal_name(sig)}{why}: {log}")
    if proc.returncode != 0:
        raise RunError(f"pvbatch exited {proc.returncode}: {_tail(log)}")
    try:
        with open(result_path, encoding="utf-8") as fh:
            result = json.load(fh)
    except (OSError, ValueError):
        raise RunError(f"pvbatch exited 0 and wrote no result.json: {log}")
    if not isinstance(result, dict) or result.get("done") != hashlib.sha256(raw).hexdigest():
        raise RunError("pvbatch's result.json is not this job's (its done is not the "
                       "sha256 of job.json)")
    gl = str(result.get("gl_renderer") or "")
    if "llvmpipe" not in gl:
        raise RunError(f"pvbatch drew with {gl or 'an unnamed GL renderer'}, not llvmpipe: "
                       f"its pixels are that machine's, so they are not used")
    return result


def _tail(log: str) -> str:
    try:
        with open(log, encoding="utf-8", errors="replace") as fh:
            lines = [ln.strip() for ln in fh.read().splitlines() if ln.strip()]
    except OSError:
        return log
    # Mesa's and the X server's lines say nothing about why a script failed.
    useful = [ln for ln in lines if not ln.startswith(("MESA", "("))]
    return (useful or lines or [log])[-1][:300]


# --------------------------------------------------------------------------- #
# the renderer control
# --------------------------------------------------------------------------- #
def _cells_in_fixture() -> int:
    with open(CONTROL_DATA, encoding="utf-8") as fh:
        m = re.search(r"^CELL_DATA\s+(\d+)", fh.read(), re.M)
    return int(m.group(1)) if m else 0


def control_job() -> dict:
    return {"data": CONTROL_DATA, "field": "t", "range": [0.0, 1.0], "preset": PRESET,
            "over": list(OVER), "under": list(UNDER), "size": list(CONTROL_SIZE)}


def _rgb(value) -> tuple | None:
    if (isinstance(value, list) and len(value) == 3
            and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255
                    for c in value)):
        return tuple(value)
    return None


def judge_control(result: dict) -> list[str]:
    """What is wrong with a renderer control's result, one line per cell;
    empty means the renderer draws the scale's colours.

    Judged here, in nopekit, from the pixels and the lookup table's colours
    the script reported: inside the scale each pixel within
    `CONTROL_TOLERANCE` of its colour, past it exactly `OVER` or `UNDER`,
    and the known pixel at `KNOWN`."""
    cells = result.get("cells")
    if not isinstance(cells, list) or not cells:
        return ["the control reported no cells"]
    problems: list[str] = []
    expected = _cells_in_fixture()
    if len(cells) != expected:
        problems.append(f"the control reported {len(cells)} cells of the strip's {expected}")
    seen = {"below": 0, "in": 0, "above": 0}
    known_seen = False
    for cell in cells:
        if not isinstance(cell, dict):
            problems.append("a control cell is not an object")
            continue
        where, pixel, want = cell.get("where"), _rgb(cell.get("pixel")), _rgb(cell.get("want"))
        value = cell.get("value")
        label = f"cell {cell.get('index')} (t = {value})"
        if where not in seen or pixel is None or want is None:
            problems.append(f"{label}: the control's report has no colour for it")
            continue
        seen[where] += 1
        if where == "in":
            if max(abs(a - b) for a, b in zip(pixel, want)) > CONTROL_TOLERANCE:
                problems.append(f"{label}: drew {pixel}, the scale's colour is {want} "
                                f"(a lit or tinted display)")
            if isinstance(value, (int, float)) and abs(value - KNOWN[0]) < 1e-9:
                known_seen = True
                if max(abs(a - b) for a, b in zip(want, KNOWN[1])) > CONTROL_TOLERANCE:
                    problems.append(f"{label}: the scale's colour at {KNOWN[0]} is {want}, "
                                    f"not viridis's {KNOWN[1]}")
        else:
            end = OVER if where == "above" else UNDER
            word = "above" if where == "above" else "below"
            if want != end or pixel != end:
                problems.append(f"{label}, {word} the scale: drew {pixel}, not the {word}-range "
                                f"colour {end} (the renderer clips a value past the scale)")
    for where, n in seen.items():
        if not n:
            problems.append(f"the control reported no cell {where} the scale"
                            if where != "in" else "the control reported no cell in the scale")
    if not known_seen:
        problems.append(f"the control reported no cell at t = {KNOWN[0]}")
    return problems


def _control_key(inst: Install) -> str:
    """What the control's outcome depends on: the build, the control's script
    and fixture, and what it is judged against."""
    parts = {"identity": inst.identity, "packages": list(inst.packages),
             "script": _sha256(CONTROL_SCRIPT), "data": _sha256(CONTROL_DATA),
             "job": control_job(), "tolerance": CONTROL_TOLERANCE, "known": list(KNOWN[1]),
             "judge": _sha256(os.path.abspath(__file__))}
    return hashlib.sha256(json.dumps(parts, sort_keys=True).encode("utf-8")).hexdigest()


def control_record(inst: Install, cache_dir: str) -> dict | None:
    """The cached control outcome for this build, or None when it never ran."""
    key = _control_key(inst)
    try:
        with open(os.path.join(cache_dir, f"{key[:12]}.json"), encoding="utf-8") as fh:
            rec = json.load(fh)
    except (OSError, ValueError):
        return None
    return rec if isinstance(rec, dict) and rec.get("key") == key else None


def control(inst: Install, cache_dir: str, *, timeout: float = TIMEOUT_S) -> dict:
    """The renderer control for this build: run once, then read from
    ``<cache_dir>/<key12>.json``. ``{"ok", "problems", "identity", ...}``.

    A run that did not finish (:class:`Unavailable`, :class:`RunError`) is
    raised and not kept: it says nothing about the renderer, and the next
    build tries again. A judged outcome, pass or fail, is kept: it is the
    same on every run of the same build, script and fixture, which all key
    it."""
    found = control_record(inst, cache_dir)
    if found is not None:
        return found
    key = _control_key(inst)
    with tempfile.TemporaryDirectory(prefix="nopekit-pv-control-") as work:
        result = run(inst, CONTROL_SCRIPT, control_job(), work, timeout=timeout)
    problems = judge_control(result)
    rec = {"key": key, "identity": inst.identity, "accepted_by": inst.accepted_by,
           "ok": not problems, "problems": problems, "gl_renderer": result.get("gl_renderer"),
           "png_sha256": result.get("png_sha256"), "cells": result.get("cells")}
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{key[:12]}.json")
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)
    return rec


def cache_dir(root: str) -> str:
    """Where a project keeps its control outcomes: ``.nopekit/cache/pvbatch/``,
    ignored by git (``cache/`` is in every project's ignore block)."""
    return os.path.join(root, ".nopekit", "cache", "pvbatch")


def ready(root: str) -> Install:
    """A ParaView whose build is checked and whose renderer control passed,
    or :class:`Unavailable` naming why (a failed control names its cells)."""
    inst = locate()
    try:
        rec = control(inst, cache_dir(root))
    except RunError as exc:
        raise Unavailable(f"the renderer control did not finish: {exc}")
    if not rec.get("ok"):
        raise Unavailable(f"{inst.name}'s renderer control failed: "
                          + "; ".join(rec.get("problems") or ()))
    return inst


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def doctor_check(root: str) -> tuple[bool, str]:
    """``nopekit doctor``'s row for pvbatch62. It runs ``--version`` and reads
    the cached control; it never runs the control (``doctor`` draws nothing)."""
    path = shutil.which(WRAPPER)
    if not path:
        return False, f"not found. {NO_PICTURES} {SEE}"
    try:
        inst = locate()
    except Unavailable as exc:
        return False, f"found at {path}, but {exc}. {NO_PICTURES} {SEE}"
    loud = (f", accepted through {EXTRA_LOCK_ENV}: a build this pack did not check"
            if inst.accepted_by != "lock" else "")
    rec = control_record(inst, cache_dir(root))
    if rec is None:
        return True, (f"found, {inst.name}{loud}; its renderer control has not run in "
                      f"this project")
    if not rec.get("ok"):
        return False, (f"found, {inst.name}{loud}, and its renderer control failed: "
                       + "; ".join(rec.get("problems") or ()) + f". {NO_PICTURES}")
    return True, f"found, {inst.name}{loud}, checked"
