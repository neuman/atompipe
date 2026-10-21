# SPDX-License-Identifier: Apache-2.0
"""Make ``bands.gltf`` and ``bands_cells.gltf`` with the real ParaView (issue
#15, P2.4). Run by hand, and by `test_cfd_views.TheRealStills`, which holds
the committed files to what ParaView writes today::

    PYTHONPATH=src python3 tests/cfd_fields/make_bands.py <level0 stage> <out dir>

``<level0 stage>`` is the coarsest stage of a real cfd.pressure_drop run on
the pack's baseline (ESI v2606, 50 x 10 cells):
``.nopekit/out/cfd-openfoam/cfd_pressure_drop/level0``. ``pvbatch62`` must be
the checked ParaView 6.2.0 (``packs/cfd-openfoam/views/_pv.py``).

What it does, with no drawing code of its own: it copies the stage's mesh
into a case outside the project, writes a ``static(p)`` whose cells take
`VALUES` in seven bands across the flow (the band of a cell is its column
times seven over the columns), and runs the pack's own ``views/_scene.py``
on it through ``_pv.run``, on the scale 0 to 1, with no plane. The scene
writes ``bands.gltf``. Then it runs a copy of the scene that colours the cut
by ``CELLS`` with no faceted recipe (ParaView's default), which writes
``bands_cells.gltf``: the file the Khronos validator must refuse.

The values: one below the scale (grey), five inside it at 0.1, 0.3, 0.5,
0.7 and 0.9, one above it (magenta). *Rejected:* the run's own field (the
colour of a cell then needs its value, and the test would need the field
file too); the finest mesh (940 KB of base64 in the repository; 500 cells
make about 60 KB).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
VIEWS = os.path.join(os.path.dirname(os.path.dirname(HERE)), "packs", "cfd-openfoam", "views")

#: The band values, on the scale [`LO`, `HI`], from the inlet to the outlet.
VALUES = (-0.25, 0.1, 0.3, 0.5, 0.7, 0.9, 1.25)
LO, HI = 0.0, 1.0
#: The time directory of the planted field.
TIME = "1"
MESH = ("points", "faces", "owner", "neighbour", "boundary")

#: The two edits that make the scene ParaView's default export: the cut
#: itself, coloured by its cells (no Shrink, no CellDatatoPointData).
CELLS_EDITS = (("points = pv.CellDatatoPointData(Input=shrunk)", "points = cut"),
               ('pv.ColorBy(display, ("POINTS", job["field"]))',
                'pv.ColorBy(display, ("CELLS", job["field"]))'))


def _pv():
    name = "nopekit_cfd_openfoam_pv"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, os.path.join(VIEWS, "_pv.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return sys.modules[name]


def band_of(column: int, columns: int) -> int:
    """The band of a cell in ``column`` of ``columns``."""
    return column * len(VALUES) // columns


def _case(stage: str, work: str) -> str:
    """A copy of ``stage``'s mesh, with the planted field at `TIME`."""
    case = os.path.join(work, "case")
    for name in MESH:
        target = os.path.join(case, "constant", "polyMesh", name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(os.path.join(stage, "constant", "polyMesh", name), target)
    times = sorted((d for d in os.listdir(stage) if d.replace(".", "").isdigit()
                    and d != "0"), key=float)
    with open(os.path.join(stage, times[-1], "static(p)"), encoding="utf-8") as fh:
        text = fh.read()
    head, rest = text.split("internalField", 1)
    count, body = rest.split("(", 1)
    old, tail = body.split(")", 1)
    n = len(old.split())
    columns = n // 10
    values = [VALUES[band_of(i % columns, columns)] for i in range(n)]
    text = (head + "internalField" + count + "(\n" + "\n".join(repr(v) for v in values)
            + "\n)" + tail).replace(f'location    "{times[-1]}"', f'location    "{TIME}"')
    os.makedirs(os.path.join(case, TIME))
    with open(os.path.join(case, TIME, "static(p)"), "w", encoding="utf-8") as fh:
        fh.write(text)
    os.makedirs(os.path.join(case, "system"))
    with open(os.path.join(case, "system", "controlDict"), "w", encoding="utf-8") as fh:
        fh.write("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class dictionary;\n"
                 "    object controlDict;\n}\n")
    return case


def make(stage: str) -> dict[str, bytes]:
    """``{"bands.gltf": bytes, "bands_cells.gltf": bytes}`` from ``stage``."""
    pv = _pv()
    scales = pv.sibling("_scales")
    inst = pv.locate()
    out: dict[str, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="nopekit-bands-") as work:
        case = _case(stage, work)
        with open(os.path.join(VIEWS, "_scene.py"), encoding="utf-8") as fh:
            scene = fh.read()
        cells = scene
        for old, new in CELLS_EDITS:
            if cells.count(old) != 1:
                raise SystemExit(f"the scene no longer holds {old!r}")
            cells = cells.replace(old, new)
        planted = os.path.join(work, "_scene_cells.py")
        with open(planted, "w", encoding="utf-8") as fh:
            fh.write(cells)
        for name, script in (("bands.gltf", os.path.join(VIEWS, "_scene.py")),
                             ("bands_cells.gltf", planted)):
            job = {"case": case, "time": TIME, "field": "static(p)", "range": [LO, HI],
                   "preset": scales.PRESET, "over": list(scales.OVER),
                   "under": list(scales.UNDER), "planes": [], "width": scales.WIDTH_PX,
                   "min_height": scales.MIN_HEIGHT_PX, "line_px": scales.LINE_PX,
                   "ticks": scales.TICK_BINS, "png": "still.png", "gltf": name}
            run = os.path.join(work, name + ".run")
            pv.run(inst, script, job, run)
            with open(os.path.join(run, name), "rb") as fh:
                out[name] = fh.read()
    return out


def main(argv: list[str]) -> int:
    stage, target = argv
    for name, data in make(stage).items():
        with open(os.path.join(target, name), "wb") as fh:
            fh.write(data)
        print(f"{name}: {len(data)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
