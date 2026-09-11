# SPDX-License-Identifier: Apache-2.0
"""Writes the three solids the baseline projection points at, and re-derives it.

``selftest/baseline.json`` is the pack's own KNOWN-GOOD projection: every gate in
the pack must pass on it, so that each negative control can be read as "the fixture
changed one thing and the gate flipped". A projection is only known-good if the
numbers in it and the geometry on disk are the same object, so both come from here:
run this module and it rewrites ``selftest/meshes/*.stl`` AND the derived block of
``selftest/baseline.json`` from those exact meshes.

    python3 packs/cad-solid/selftest/make_baseline_meshes.py

The part is a generic sealed equipment enclosure, four solids in one alloy:

* ``housing``       a die-cast open-top tray, 3 mm walls and a 3 mm floor;
* ``cover``         a 4 mm plate bolted flat onto the housing rim -- an INTENDED
                    face contact, which is what the clash allowlist is for;
* ``carriage``      a block that slides along X guided by the cavity side walls,
                    0.4 mm running clearance per side -- a SLIDING fit, which the
                    allowlist must refuse to cover;
* ``guide_roller``  a turned roller that stops the carriage at the -X end of its
                    travel. A revolved surface, so it is ORGANIC: its tessellation
                    carries chord error, and the pair tolerances it appears in are
                    the per-pair organic ones rather than the prismatic default.

Nothing about the object is specific to any project. It exists because the gates
need a plausible multi-part assembly with a real wall thickness, a real intended
contact, a real sliding fit and one curved part to measure.

Every solid is built as an explicit vertex/face list, never by a boolean. A boolean
kernel is entitled to emit slivers, and a sliver in the KNOWN-GOOD fixture would
make ``cad.degenerate_faces`` fail on the baseline for a reason that has nothing to
do with the design. The tray below is the 28-triangle tessellation a CAD exporter
actually produces for a rectangular pocket.

STL is deliberate: it is the format the pack has to treat as a soup (no vertex
identity, welded once on load), so the baseline exercises that path rather than
avoiding it. Coordinates are kept to values that survive the float32 round-trip
well inside the 1e-4 mm weld tolerance.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PACK = os.path.dirname(HERE)
MESH_DIR = os.path.join(HERE, "meshes")

# --- the enclosure, in millimetres ----------------------------------------- #
L, W, H = 96.0, 64.0, 34.0     # housing outer envelope
WALL = 3.0                     # side wall thickness (die-cast minimum + margin)
FLOOR = 3.0                    # floor thickness
COVER_T = 4.0                  # bolted cover plate thickness
RUN_CLEAR = 0.4                # per-side running clearance, carriage to cavity wall
CAR_L, CAR_H = 40.0, 8.0       # sliding carriage, X travel length and height
ROLLER_D, ROLLER_LEN = 12.0, 40.0          # guide roller, turned, axis along Y
ROLLER_X = 15.0                # roller axis, mm from the -X outer face
ROLLER_SECTIONS = 48           # facets around the roller; chord error ~0.013 mm


def _tray(length, width, height, wall, floor):
    """An open-top rectangular tray as an explicit 16-vertex, 28-triangle solid.

    Outer corner at the origin, cavity open at +Z. Every quad below is wound
    counter-clockwise seen from OUTSIDE THE MATERIAL, which for the four cavity
    walls and the cavity floor means their normals point into the cavity. The
    assertion at the end is not decoration: a hand-wound face table is exactly the
    thing that stays right until someone edits it, and ``cad.is_volume`` would then
    fail on the pack's own known-good input, which is the one place a gate failure
    is hardest to read. trimesh's own winding repair is not used because it needs
    scipy, which this pack does not require.
    """
    import trimesh

    x0, y0, z0 = 0.0, 0.0, 0.0
    x1, y1, z1 = length, width, height
    ix0, iy0 = x0 + wall, y0 + wall
    ix1, iy1 = x1 - wall, y1 - wall
    iz = z0 + floor

    verts = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),        # 0-3 outer base
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),        # 4-7 outer top
        (ix0, iy0, z1), (ix1, iy0, z1), (ix1, iy1, z1), (ix0, iy1, z1),  # 8-11 rim inner
        (ix0, iy0, iz), (ix1, iy0, iz), (ix1, iy1, iz), (ix0, iy1, iz),  # 12-15 cavity floor
    ]
    quads = [
        (0, 3, 2, 1),                     # outer base, normal -Z
        (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),   # outer sides
        (4, 5, 9, 8), (5, 6, 10, 9), (6, 7, 11, 10), (7, 4, 8, 11),  # top rim annulus
        (8, 9, 13, 12), (9, 10, 14, 13), (10, 11, 15, 14), (11, 8, 12, 15),  # cavity sides
        (12, 13, 14, 15),                 # cavity floor
    ]
    faces = []
    for a, b, c, d in quads:
        faces.append((a, b, c))
        faces.append((a, c, d))
    mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
    expected = length * width * height - (length - 2 * wall) * (width - 2 * wall) * (height - floor)
    assert mesh.is_volume, "tray face table is not a valid solid"
    assert abs(mesh.volume - expected) < 1e-6, f"tray volume {mesh.volume} != {expected}"
    return mesh


def _box(extents, centre):
    import numpy as np
    import trimesh

    transform = np.eye(4)
    transform[:3, 3] = np.asarray(centre, dtype=float)
    return trimesh.creation.box(extents=extents, transform=transform)


def build():
    """``{name: mesh}`` for the assembly, already placed in the assembly frame.

    Placed, not at local origins: ``cad.clash`` booleans whatever it is handed, and
    parts booleaned at their own origins either all clash or none do. Both answers
    are confident nonsense.
    """
    import numpy as np
    import trimesh

    housing = _tray(L, W, H, WALL, FLOOR)
    cover = _box((L, W, COVER_T), (L / 2.0, W / 2.0, H + COVER_T / 2.0))

    car_w = (W - 2.0 * WALL) - 2.0 * RUN_CLEAR      # guided by the cavity side walls
    carriage = _box((CAR_L, car_w, CAR_H), (L / 2.0, W / 2.0, FLOOR + CAR_H / 2.0))

    # Axis at one radius above the cavity floor: the TRUE cylinder is tangent to the
    # floor, and an inscribed tessellation of it sits strictly above that tangent
    # plane, so the roller rests on the floor without the facets cutting into it.
    axis_to_y = trimesh.transformations.rotation_matrix(np.pi / 2.0, (1.0, 0.0, 0.0))
    axis_to_y[:3, 3] = (ROLLER_X, W / 2.0, FLOOR + ROLLER_D / 2.0)
    roller = trimesh.creation.cylinder(
        radius=ROLLER_D / 2.0, height=ROLLER_LEN,
        sections=ROLLER_SECTIONS, transform=axis_to_y)
    return {"housing": housing, "cover": cover,
            "carriage": carriage, "guide_roller": roller}


def write_meshes(meshes=None):
    """Export each solid to ``selftest/meshes/<name>.stl``; returns the paths."""
    meshes = meshes or build()
    os.makedirs(MESH_DIR, exist_ok=True)
    written = {}
    for name, mesh in meshes.items():
        path = os.path.join(MESH_DIR, f"{name}.stl")
        mesh.export(path)
        written[name] = os.path.relpath(path, PACK).replace(os.sep, "/")
    return written


def derive(meshes=None):
    """The numbers ``cad.bounding`` reads, measured off the exported solids.

    Volume-weighted centroid, single material: the enclosure is one alloy and the
    carriage is the same alloy, so mass and volume are proportional and the centre
    of mass is the centroid of the union. If the parts were ever given different
    densities this would have to weight by mass instead, and the projection would
    have to carry them.
    """
    import numpy as np

    meshes = meshes or build()
    lows = np.min([m.bounds[0] for m in meshes.values()], axis=0)
    highs = np.max([m.bounds[1] for m in meshes.values()], axis=0)
    volumes = np.array([float(m.volume) for m in meshes.values()])
    centres = np.array([np.asarray(m.center_mass, dtype=float) for m in meshes.values()])
    com = (centres * volumes[:, None]).sum(axis=0) / volumes.sum()
    return {
        "bbox_mm": [round(float(v), 3) for v in (highs - lows)],
        "volume_mm3": round(float(volumes.sum()), 1),
        "com_mm": [round(float(v), 3) for v in com],
    }


def main():
    """Export the solids, then CHECK the projection against them. Never rewrites it.

    The check rather than a rewrite is deliberate. ``baseline.json`` is hand-written
    documentation as much as data -- it carries the ``_notes`` block that teaches the
    pack's vocabulary -- and a formatter that re-emits it would flatten that into a
    machine dump. So this module owns the geometry and reports any drift; a human
    edits the four numbers. Exit status is non-zero when they disagree.
    """
    paths = write_meshes()
    derived = derive()
    baseline_path = os.path.join(HERE, "baseline.json")
    with open(baseline_path, encoding="utf-8") as fh:
        baseline = json.load(fh)

    drift = []
    if baseline.get("meshes") != paths:
        drift.append(f"meshes: projection says {baseline.get('meshes')}, built {paths}")
    for key, value in derived.items():
        stated = baseline.get(key)
        same = (stated == value if not isinstance(value, list)
                else (isinstance(stated, list) and len(stated) == len(value)
                      and all(abs(float(a) - float(b)) <= 5e-4 for a, b in zip(stated, value))))
        if not same:
            drift.append(f"{key}: projection says {stated}, meshes measure {value}")

    print(json.dumps({"meshes": paths, **derived}, indent=2))
    if drift:
        print("\nDRIFT between selftest/baseline.json and the solids it points at:")
        for line in drift:
            print("  " + line)
        raise SystemExit(1)
    print("\nselftest/baseline.json agrees with the exported solids.")


if __name__ == "__main__":
    main()
