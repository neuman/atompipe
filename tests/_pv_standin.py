# SPDX-License-Identifier: Apache-2.0
"""A stand-in for ParaView's ``pvbatch`` (issue #15, B.6, W15): installed by
``tests/test_cfd_views.py`` as ``<tmp>/opt/pv/bin/pvbatch``, with a fake
``conda-meta/`` and a ``pvbatch62`` launcher on a temporary PATH, it plays the
part ParaView plays for cfd-openfoam's ``views/_pv.py``. It never runs inside
nopekit's process: ``_pv.run`` starts it as it starts pvbatch, in the scrubbed
environment, under its timeout.

It draws nothing. It writes committed fixture bytes (rule 0.4 of the issue's
design: a stand-in writes bytes a trusted tool made, and grows no codec): the
PNG and the cell readings that ParaView 6.2.0 (conda-forge
``py312ha24fc4a_1``, llvmpipe) wrote for the renderer control
(``packs/cfd-openfoam/views/_control.py`` on ``views/fixture/strip.vtk``) on
2026-10-21, and, for the planted faults, what the same ParaView drew with a lit
display and with no above-range colour.

Its install is ``<prefix>/bin/pvbatch`` (a three-line Python launcher that
calls ``main``), ``<prefix>/conda-meta/*.json`` and ``<prefix>/standin.json``,
which holds its mode (the environment is scrubbed, so the mode cannot come
from there). Each call appends one JSON line to ``<prefix>/calls.jsonl``: its
argv, its whole environment, what its HOME held and its cwd.

Modes: ``ok``; ``no-overrange`` (values past the scale drawn in the end
colours, so the renderer control must fail); ``lit`` (the lit display's
pixels); ``sigabrt`` (kills itself with SIGABRT); ``hang`` (sleeps past any
timeout); ``noise`` (stderr junk, exit 0, a good result); ``no-done`` (a result
whose ``done`` is another job's); ``gpu`` (reports a GL renderer other than
llvmpipe); ``crash`` (a traceback, exit 1); ``no-result`` (exit 0, nothing
written); ``dirty-home`` (writes into its HOME, then a good result). Its
``--version`` banner is ``standin.json``'s ``banner``.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import signal
import sys
import time

#: The renderer control's PNG as ParaView 6.2.0 wrote it (600 x 120, RGB).
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAlgAAAB4CAIAAAChNxuUAAAAFHRFWHRBcHBsaWNhdGlvbgBQYXJhVmlld5SC"
    "lFUAAAU8SURBVHja7d1PbuNkGMDh106cNP3HbECDRtAjjFgjseIAnGCOw44F5+AKzBVAvcBIsx2xgEnbNHZi"
    "syE7kCYRftt8eR5lWenTl9r++W3cthqGIQDgVNXeAgCEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACE"
    "EACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACEEACE"
    "EACEEACEEACEEACEEACEEACEEACEEAAONv30L3379u1yuVyv123btm3bdd1mZ7vT9/1Rvx2///zu/s+H1DuR"
    "aV3f3KSuOKlXX73IXLGqq+WXTeqKVXX3MveOsqruX26TVxy+WKVeLOr6688/ZK7Y1JNvXrzLXXH63eVt7oqL"
    "b2ep15x/jp+ffosPl/Ex4i7iPuIhYhXxGLGOaHev7hlfrJuI2e41jziLWEScR1xEXEZcR7yK+HGEEC6Xy9vb"
    "2yjaxc0sOYTD4jx5j92iyV7xrEpecRiGiNRF+2FI3mM/DMlv69lslbzHz5qP2cdqv0lfMftd/eccef9r9csP"
    "R3yx7iK6iPv//oI3+9wWfPqXrtfr4gfk7Tp9ok2foat+SN9jUID08sY2fcUTsrwsfIP73ETtEcK2bcsPYZsf"
    "wqH4FashKED/BCH0EMNo7s8L3+CdEB5RCIf8FYfyV6SIibA3EY53e/qwKL3044Sw67riD46+K38irAYTIUdx"
    "qArhmFalh3Cfhz32COFmsyn/VN+cwLSUnyUhNBEedj6GEI7m8az00gvh4SHMngiHE/hBpYmwkBCGH40WZD0r"
    "vfRCaCI0EVLCoSqEo2lLD+E+v+WwRwi32235p/r2FOYzJeQ4sjSYCIXw8A0K4RGFMEyEmAj/nc8IR9Q1hW9Q"
    "CA8/8bYnkKX0JV3MSilh/kToTRfCZxbCY/87op904vU+IzQR8nwOHDdR44VwWvoGxwkhAJRHCAEQQgAQQgAQ"
    "QgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgA4uRDWdfnVrOr0v3Zf5a8Y5a9IIQeOf1wymmZT+gbHCeFkMin/"
    "vmByAlnK/z/jLjqFlDD9P1m6hRqxE13hG5wJ4cEn3uQExiUTIUeSpdpNlBAK4UmEMP3qMlRKyGHfxfyJUAjH"
    "60Rb+gbHCeF0Oi3+2KinPiPUQZ7PoSqEQniouRAeHsLsB4Kq6hRmUFcdE+FB56OJcMROlB7CMyE0EZoI+f8P"
    "1fQQmghH7MRj4RtcjBPCpmmKPzbqJv1XROryPyM0ERZyduQ/LGMiHLETq8I3eD5OCGezWfHHxmSWHsIqf8UT"
    "mHopYyIUwvFuT89LD+GFEB5RCJ/iNttEyFFkaVL13vbROvFQ+AYvxwnhfD4v/tiYzPNDmL3i8ATpddUxER4W"
    "QhPhaK7uCt/g9R5fu8fzL1dXV69fv16v123btm3bdd1mZ7vT98d9B3f/PvtJqmqVfV/WrLrkv63UPA7Jn8vn"
    "P4tbP8WKyZV4bBcRy8wV/+quI/5IPVbr7EcCm3oR8QTDWXXzfbyJ+BhxF3Ef8RCxiniMWEe0u9dz/p37JmK2"
    "e80jziIWEecRFxGXEdcRr/Z5N4bBPRcAp8sPrQAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQ"
    "QgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQQgAQ"
    "QgAQQgAQQgAQQgAQQgAQQgAQQgA43N9NbX/UJjTGwQAAAABJRU5ErkJggg==")

#: ``(index, t, where, pixel, want)`` of each strip cell, as ParaView 6.2.0
#: reported them for the unlit display: the centre pixel and the lookup
#: table's colour for the cell's value.
CELLS = [
    (0, -0.2, "below", (128, 128, 128), (128, 128, 128)),
    (1, -0.1, "below", (128, 128, 128), (128, 128, 128)),
    (2, 0.0, "in", (68, 1, 84), (68, 1, 84)),
    (3, 0.1, "in", (72, 36, 117), (72, 36, 117)),
    (4, 0.2, "in", (65, 68, 135), (65, 68, 135)),
    (5, 0.3, "in", (53, 95, 141), (53, 95, 141)),
    (6, 0.4, "in", (42, 120, 142), (42, 120, 142)),
    (7, 0.5, "in", (33, 145, 140), (33, 145, 140)),
    (8, 0.6, "in", (34, 168, 132), (34, 168, 132)),
    (9, 0.7, "in", (68, 191, 112), (68, 191, 112)),
    (10, 0.8, "in", (122, 209, 81), (122, 209, 81)),
    (11, 0.9, "in", (189, 223, 38), (189, 223, 38)),
    (12, 1.0, "in", (253, 231, 37), (253, 231, 37)),
    (13, 1.1, "above", (255, 0, 255), (255, 0, 255)),
    (14, 1.2, "above", (255, 0, 255), (255, 0, 255)),
]

#: The pixels the same ParaView drew with a lit display (Ambient 0, Diffuse 1).
LIT = [(100, 99, 95), (100, 99, 95), (53, 1, 62), (56, 28, 87), (51, 52, 100),
       (41, 73, 105), (33, 93, 105), (26, 112, 104), (27, 130, 98), (53, 147, 83),
       (95, 161, 60), (148, 172, 28), (198, 178, 27), (200, 0, 189), (200, 0, 189)]

#: Past the scale with no above-range colour, the top end's colour (measured);
#: below it with none, the bottom end's (as a clipping renderer draws it).
CLIPPED = {"above": (253, 231, 37), "below": (68, 1, 84)}

GL = "llvmpipe (LLVM 23.1.3, 256 bits)"


def _mode(prefix: str) -> dict:
    try:
        with open(os.path.join(prefix, "standin.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _log(prefix: str, argv: list) -> None:
    home = os.environ.get("HOME", "")
    try:
        held = sorted(os.listdir(home)) if home else None
    except OSError:
        held = None
    with open(os.path.join(prefix, "calls.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"argv": argv, "env": dict(os.environ), "home_held": held,
                             "cwd": os.getcwd()}) + "\n")


def main(prefix: str) -> int:
    argv = sys.argv[1:]
    _log(prefix, argv)
    mode = _mode(prefix)
    if argv == ["--version"]:
        print(mode.get("banner", "paraview version 6.2.0"))
        return 0
    job_path = argv[-1]
    with open(job_path, "rb") as fh:
        raw = fh.read()
    out_dir = os.path.dirname(os.path.abspath(job_path))
    kind = mode.get("mode", "ok")
    if kind == "sigabrt":
        sys.stderr.write("malloc(): invalid size (unsorted)\n")
        sys.stderr.flush()
        os.kill(os.getpid(), signal.SIGABRT)
    if kind == "hang":
        time.sleep(3600)
    if kind == "crash":
        sys.stderr.write("Traceback (most recent call last):\n  File \"_control.py\"\n"
                         "RuntimeError: no preset with name Viridis present\n")
        return 1
    if kind == "no-result":
        return 0
    if kind == "noise":
        sys.stderr.write("MESA-EGL: warning: Not allowed to force software rendering\n"
                         "(   1.128s) [pvbatch ] WARN| bad X server connection. DISPLAY=\n" * 50)
    if kind == "dirty-home":
        with open(os.path.join(os.environ["HOME"], "left-behind"), "w") as fh:
            fh.write("a file a run left in its HOME\n")
    with open(os.path.join(out_dir, "control.png"), "wb") as fh:
        fh.write(PNG)
    cells = []
    for (index, value, where, pixel, want), lit in zip(CELLS, LIT):
        if kind == "no-overrange" and where != "in":
            pixel = CLIPPED[where]
        if kind == "lit":
            pixel = lit
        cells.append({"index": index, "value": value, "where": where, "pixel": list(pixel),
                      "want": list(want)})
    done = hashlib.sha256(raw if kind != "no-done" else raw + b" ").hexdigest()
    result = {"done": done,
              "gl_renderer": "D3D12 (NVIDIA GeForce RTX 4070)" if kind == "gpu" else GL,
              "paraview": "paraview version 6.2.0",
              "png_sha256": hashlib.sha256(PNG).hexdigest(), "cells": cells}
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    return 0


# --------------------------------------------------------------------------- #
# the install (test side)
# --------------------------------------------------------------------------- #
#: The paraview build the fake records name: the build the pack's lock holds,
#: so only the package sha256 values tell the stand-in from ParaView.
VERSION, BUILD = "6.2.0", "py312ha24fc4a_1"
PACKAGES = ("paraview", "mesalib", "mesa-libgallium", "mesa-llvmpipe", "pillow")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def install(directory: str, *, packages: dict | None = None) -> dict:
    """The stand-in under ``directory``: ``{"prefix", "bin", "packages",
    "extra_lock"}``. ``bin`` holds only the ``pvbatch62`` launcher, to put on
    PATH; ``packages`` the sha256 each fake conda record names (``packages=``
    overrides them); ``extra_lock`` the ``NOPEKIT_PVBATCH_EXTRA_LOCK`` value
    that accepts this build."""
    prefix = os.path.join(directory, "opt", "pv")
    os.makedirs(os.path.join(prefix, "bin"))
    os.makedirs(os.path.join(prefix, "conda-meta"))
    pvbatch = os.path.join(prefix, "bin", "pvbatch")
    here = os.path.dirname(os.path.abspath(__file__))
    with open(pvbatch, "w", encoding="utf-8") as fh:
        fh.write(f"#!{sys.executable}\nimport sys; sys.path.insert(0, {here!r})\n"
                 f"import _pv_standin; sys.exit(_pv_standin.main({prefix!r}))\n")
    os.chmod(pvbatch, 0o755)
    with open(pvbatch, "rb") as fh:
        pv_sha = _sha(fh.read())
    shas = {name: _sha(f"stand-in {name}".encode()) for name in PACKAGES}
    shas.update(packages or {})
    for name in PACKAGES:
        version = VERSION if name == "paraview" else "0"
        build = BUILD if name == "paraview" else "standin_0"
        record = {"name": name, "version": version, "build": build, "sha256": shas[name],
                  "paths_data": {"paths": []}}
        if name == "paraview":
            record["paths_data"]["paths"] = [{"_path": "bin/pvbatch", "path_type": "hardlink",
                                              "sha256": pv_sha, "sha256_in_prefix": pv_sha}]
        with open(os.path.join(prefix, "conda-meta", f"{name}-{version}-{build}.json"),
                  "w", encoding="utf-8") as fh:
            json.dump(record, fh)
    bin_dir = os.path.join(directory, "bin")
    os.makedirs(bin_dir)
    launcher = os.path.join(bin_dir, "pvbatch62")
    # The launcher of references/rendering.md, with the stand-in's prefix.
    with open(launcher, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\n# pvbatch62: the test stand-in\n"
                 f'exec env -i HOME="$HOME" PATH={prefix}/bin:/usr/bin:/bin PYTHONNOUSERSITE=1 '
                 f"GALLIUM_DRIVER=llvmpipe LIBGL_ALWAYS_SOFTWARE=1 {prefix}/bin/pvbatch "
                 f'--force-offscreen-rendering "$@"\n')
    os.chmod(launcher, 0o755)
    set_mode(prefix)
    lock = {"paraview": VERSION, "build": BUILD, "packages": shas}
    return {"prefix": prefix, "bin": bin_dir, "packages": shas, "extra_lock": json.dumps(lock)}


def set_mode(prefix: str, mode: str = "ok", *, banner: str = "paraview version 6.2.0") -> None:
    """The mode of the next calls, and the banner ``--version`` prints."""
    with open(os.path.join(prefix, "standin.json"), "w", encoding="utf-8") as fh:
        json.dump({"mode": mode, "banner": banner}, fh)


def calls(prefix: str) -> list[dict]:
    """Every call so far, oldest first."""
    try:
        with open(os.path.join(prefix, "calls.jsonl"), encoding="utf-8") as fh:
            return [json.loads(line) for line in fh if line.strip()]
    except OSError:
        return []
