# SPDX-License-Identifier: Apache-2.0
"""Known-bad geometry for the mesh gates. One defect each, in the gate's direction.

Every fixture returns ``{"meshes": {...}}``, which the selftest machinery merges
into ``ctx.extra``; the gates look there before the projection, so the gate under
test runs on this geometry and the project's own parts are left alone.

The discipline that makes these worth anything: each function starts from a CLEAN
box and changes exactly one physically meaningful thing, in the direction the gate
under test claims to detect. A corrupt file or an empty mesh would prove the gates
handle garbage — which is not the claim any of them makes.

trimesh is imported inside each function, never at module level. Two reasons: the
selftest machinery declines to load a fixture at all when the gate's tooling is
missing, and a module-level import would make this file unreadable on the very
machine where the honest answer is SKIPPED.

Where a fixture necessarily trips a second gate as well, its docstring says so.
``sliver_pair`` duplicates one corner of a closed box and repoints a subset of the
faces meeting there, which is what a tessellator does when it emits a rim vertex
twice: the surface stays geometrically closed and goes topologically open, so
``cad.watertight`` fails it as well. That is not a side effect to apologise for, it
is the same defect seen by the other gate — but what the control has to show is that
the gate under test trips for the reason the fixture planted, which for
``cad.degenerate_faces`` is the repair count.
"""
from __future__ import annotations

BOX_MM = 20.0          # a part-sized cube; big enough that mm-scale defects are real
SLIVER_OFFSET_MM = 1e-6    # a duplicated vertex, well inside the 1e-4 mm weld tolerance


import json as _json
import os as _os

_BASELINE_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "baseline.json")


def _baseline() -> dict:
    """The pack's OWN plausible-good projection — never the host project's.

    A fixture that reads its severity from the host project is a control that
    passes in some repositories and fails in others, which is the same as having
    none. See tests/test_packs.py::ControlsAreSealed.
    """
    try:
        with open(_BASELINE_PATH, "r", encoding="utf-8") as handle:
            loaded = _json.load(handle)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in loaded.items() if not k.startswith("_")}


def _sealed(ctx, meshes: dict):
    """A context carrying the pack's own projection AND the known-bad geometry.

    Returning a bare ``{"meshes": ...}`` dict merges only into ``ctx.extra`` and
    leaves the gate reading its THRESHOLD from the host project — the same
    defusal hole as an inherited projection, in a different shape. A wall gate
    handed a quarter-thickness plate and no minimum-wall figure does not fail; it
    skips, and a skip is not a control.
    """
    import dataclasses
    return dataclasses.replace(ctx, params=_baseline(),
                               extra=dict(ctx.extra or {}, meshes=meshes))


def _box(extents, translate=(0.0, 0.0, 0.0)):
    """A clean, watertight, correctly wound box at a placement."""
    import numpy as np
    import trimesh

    transform = np.eye(4)
    transform[:3, 3] = np.asarray(translate, dtype=float)
    return trimesh.creation.box(extents=extents, transform=transform)


def holed_box(ctx):
    """cad.watertight — a box with its +Z facet deleted.

    Two triangles removed and nothing else touched: 4 open edges on an otherwise
    perfect part. This is the shape of the defect that matters, because a mesh with
    a hole booleans to an empty intersection without raising, and a part that
    collides with nothing is the answer everybody was hoping for.
    """
    import numpy as np

    mesh = _box((BOX_MM, BOX_MM, BOX_MM))
    top = np.isclose(np.asarray(mesh.triangles_center)[:, 2], BOX_MM / 2.0)
    mesh.update_faces(~top)
    return _sealed(ctx, {"holed_box": mesh})


def flipped_facet(ctx):
    """cad.is_volume — a closed box with one triangle wound backwards.

    Still watertight: every edge is still used by exactly two faces, so
    ``cad.watertight`` passes this happily. It is not a volume, it cannot be
    booleaned, and its signed volume is wrong by twice that facet's contribution.
    This is precisely the case that watertightness cannot see, which is why the two
    gates are separate.
    """
    mesh = _box((BOX_MM, BOX_MM, BOX_MM))
    faces = mesh.faces.copy()
    faces[0] = faces[0][::-1]
    mesh.faces = faces
    return _sealed(ctx, {"flipped_box": mesh})


def sliver_pair(ctx):
    """cad.degenerate_faces — ONE corner of the box emitted twice by the tessellator.

    This is the defect PACK.md names, planted on the box rather than beside it: a
    real corner of a closed surface is written a second time 1e-6 mm away, a subset
    of the faces that meet there is repointed at the copy, and one face spans the
    two. One physical change, two consequences, both of which this gate is the one
    that sees:

    * **adjacency splits.** The faces on either side of the duplicated corner are
      no longer neighbours even though they touch everywhere, so the surface is
      topologically open where it is geometrically closed — every algorithm that
      walks adjacency (offset, slicing, thickness, boolean) now works across a seam.
      The two copies weld back together at 1e-4 mm: one repair.
    * **a sliver appears only after the weld.** The face spanning the two copies has
      an area of 0.5 * 1e-6 mm * 20 mm = 1e-5 mm^2 — about a thousand times the
      1e-8 mm^2 zero-area threshold, so it survives an area test comfortably. Weld
      the corner and its two ends become one point and its area is exactly zero.
      A drop-then-weld implementation finds nothing here and reports a clean part;
      weld-then-drop finds it. That ordering is what this fixture exists to prove.

    An earlier version of this fixture put the sliver at ``(BOX_MM, 0, 0)`` — 10 mm
    clear of a box spanning [-10, 10], floating in empty space. The gate detected
    it, but a disconnected triangle appended to a file is "added garbage", not the
    adjacency split the pack documents, and it proved nothing about a duplicated rim
    vertex on a closed surface. It is rebuilt on the geometry here so the claim and
    the evidence are the same statement.

    Also trips cad.watertight, and now genuinely for the documented reason: the
    repointed faces carry their edges to the copy, so those edges are used once
    instead of twice. Geometrically closed, topologically open. The measurement that
    matters to THIS gate is the repair count.
    """
    import numpy as np
    import trimesh

    box = _box((BOX_MM, BOX_MM, BOX_MM))
    vertices = np.asarray(box.vertices, dtype=float)
    faces = np.asarray(box.faces).copy()

    half = BOX_MM / 2.0
    corner = int(np.argmin(np.linalg.norm(vertices - [half, half, half], axis=1)))
    # The far end of one box EDGE from that corner: a real vertex 20 mm away, so
    # the spanning face is as long as the part and still 1e-6 mm wide.
    arm = int(np.argmin(np.linalg.norm(vertices - [-half, half, half], axis=1)))

    duplicate = len(vertices)
    vertices = np.vstack([vertices, vertices[corner] + [0.0, 0.0, SLIVER_OFFSET_MM]])

    incident = np.nonzero((faces == corner).any(axis=1))[0]
    for row in incident[: max(1, len(incident) // 2)]:       # a SUBSET: the split
        faces[row][faces[row] == corner] = duplicate
    faces = np.vstack([faces, [[corner, duplicate, arm]]])

    # process=False or trimesh welds the duplicate on construction and hands the
    # gate a repaired mesh — the fixture would then be testing nothing.
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
    return _sealed(ctx, {"split_corner_box": mesh})


def overlapping_pair(ctx):
    """cad.clash — two valid solids sharing 800 mm^3 of material.

    Both boxes are watertight, consistently wound, degenerate-free volumes. The only
    thing wrong is where the second one is: 18 mm along X from a 20 mm box, so they
    share a 2 x 20 x 20 mm slab. That is three orders of magnitude past any
    tessellation tolerance this gate carries, and no allowlist entry covers it.
    """
    a = _box((BOX_MM, BOX_MM, BOX_MM))
    b = _box((BOX_MM, BOX_MM, BOX_MM), translate=(BOX_MM - 2.0, 0.0, 0.0))
    return _sealed(ctx, {"block_a": a, "block_b": b})


def thin_plate(ctx):
    """cad.wall_thickness — a plate at a quarter of the project's own minimum wall.

    A closed, valid, correctly wound solid whose only fault is being too thin, taken
    from the limit in the projection so the fixture tracks whatever process the
    project is actually using. Thickness enters deflection as a cube and wall
    failures as a threshold; a quarter is unambiguous without being a caricature.
    """
    limit = _baseline().get("min_wall_mm")
    limit = float(limit) if isinstance(limit, (int, float)) and limit > 0 else 1.2
    return _sealed(ctx, {"thin_plate": _box((30.0, 30.0, limit / 4.0))})
