# SPDX-License-Identifier: Apache-2.0
"""Known-bad meshes for the tier-1 printability gates.

Each fixture writes a small solid to the run's output directory and returns a
context whose ``mesh_path`` points at it. Everything else in the projection is
left alone, so a failing verdict can only be about the geometry that changed.

The solids are generated rather than checked in for two reasons. They stay
parametric — the arch's gap is written as a number next to the limit it has to
beat, so a project that raises ``max_bridge_mm`` does not silently turn its own
negative control into a passing fixture. And they stay honest about what is wrong
with them: each one is watertight, sits on the bed, and fits any reasonable build
volume. The only thing wrong is the thing the gate under test measures.

``trimesh`` and ``numpy`` are imported here, not at module scope, so this file can
be read and imported on a machine without them. The spine only calls a fixture
after ``availability()`` has confirmed the gate's dependencies exist.
"""
from __future__ import annotations

import json as _json
import os as _os

import dataclasses
import math


# --------------------------------------------------------------------------- #
# mesh builders
# --------------------------------------------------------------------------- #
def _cone(half_angle_deg: float, height: float, *, apex_down: bool, segments: int = 64):
    """A right circular cone, apex on the bed or base on the bed.

    The half angle IS the overhang angle of the side surface. A cone standing on
    its apex with a half angle of ``a`` presents every side face at ``a`` degrees
    from vertical; the same cone on its base presents them at ``a`` degrees the
    other way and overhangs nothing. That equivalence is what makes this a clean
    control: one flip changes the overhang and nothing else.
    """
    import numpy as np
    import trimesh

    radius = height * math.tan(math.radians(half_angle_deg))
    theta = np.linspace(0.0, 2.0 * math.pi, segments, endpoint=False)
    ring = np.column_stack((radius * np.cos(theta), radius * np.sin(theta),
                            np.full(segments, height)))
    verts = np.vstack(([[0.0, 0.0, 0.0]], ring, [[0.0, 0.0, height]]))

    # Winding is written out by hand rather than repaired with fix_normals(),
    # which needs a graph backend the pack does not declare. Outwardness is then
    # asserted, not assumed: see _assert_solid.
    faces = []
    for i in range(segments):
        j = (i + 1) % segments
        faces.append((0, 1 + j, 1 + i))                       # side, normal outward+down
        faces.append((segments + 1, 1 + i, 1 + j))            # cap, normal up
    mesh = trimesh.Trimesh(vertices=verts, faces=np.asarray(faces), process=True)
    if apex_down is False:
        mesh.apply_transform(trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0]))
        mesh.apply_translation([0.0, 0.0, -mesh.bounds[0][2]])
    _assert_solid(mesh, "cone")
    return mesh


def _arch(gap: float, *, width: float = 140.0, height: float = 40.0,
          clear: float = 20.0, depth: float = 40.0):
    """Two legs and a slab: a flat ceiling ``gap`` mm wide, ``clear`` mm off the bed.

    Built as an explicit prism rather than a boolean union of boxes, because a
    union leaves the slab's underside spanning the whole width including the part
    over the legs, and the fixture would then be testing the wrong number.

    Every corner of every cap rectangle is also a vertex of the outline, so the
    solid is watertight with no T-junctions — which matters, because the gate
    decides whether a ceiling edge is anchored by looking at the face on the other
    side of it, and a T-junction is an edge with no other side.
    """
    import numpy as np
    import trimesh

    a = (width - gap) / 2.0
    b = a + gap
    if a <= 0:
        raise ValueError(f"gap {gap} leaves no legs inside a {width} mm width")
    w, h, c = width, height, clear

    outline = [(0, 0), (a, 0), (a, c), (b, c), (b, 0), (w, 0),
               (w, c), (w, h), (b, h), (a, h), (0, h), (0, c)]
    rects = [
        [(0, 0), (a, 0), (a, c), (0, c)],          # left leg
        [(b, 0), (w, 0), (w, c), (b, c)],          # right leg
        [(0, c), (a, c), (a, h), (0, h)],          # slab, over the left leg
        [(a, c), (b, c), (b, h), (a, h)],          # slab, over the gap  <- the bridge
        [(b, c), (w, c), (w, h), (b, h)],          # slab, over the right leg
    ]

    index: dict[tuple[float, float], tuple[int, int]] = {}
    verts: list[tuple[float, float, float]] = []

    def vid(pt):
        key = (round(float(pt[0]), 6), round(float(pt[1]), 6))
        if key not in index:
            index[key] = (len(verts), len(verts) + 1)
            verts.append((key[0], 0.0, key[1]))
            verts.append((key[0], depth, key[1]))
        return index[key]

    # The outline is counter-clockwise in the (x, z) plane and the prism runs along
    # +y, which fixes every winding below. Written out by hand rather than repaired
    # with fix_normals(), which needs a graph backend the pack does not declare.
    faces = []
    for i, p in enumerate(outline):                 # side walls
        q = outline[(i + 1) % len(outline)]
        p0, p1 = vid(p)
        q0, q1 = vid(q)
        faces.append((p0, q1, q0))
        faces.append((p0, p1, q1))
    for rect in rects:                              # the two end caps
        c0, c1, c2, c3 = (vid(pt) for pt in rect)
        faces.append((c0[0], c1[0], c2[0]))         # y = 0, normal -y
        faces.append((c0[0], c2[0], c3[0]))
        faces.append((c0[1], c2[1], c1[1]))         # y = depth, normal +y
        faces.append((c0[1], c3[1], c2[1]))

    mesh = trimesh.Trimesh(vertices=np.asarray(verts, dtype=float),
                           faces=np.asarray(faces), process=True)
    _assert_solid(mesh, f"arch(gap={gap})")
    return mesh


def _assert_solid(mesh, what: str) -> None:
    """A fixture that is broken in an unintended way proves nothing.

    If this raises, the spine reports the selftest as ERRORED — the control is
    gone, so the gate is unproven. That is the correct outcome and it is loud. It
    is never a pass.
    """
    if not mesh.is_watertight:
        raise ValueError(f"fixture {what} is not watertight; it would be bad in the "
                         f"wrong way and the control would prove nothing")
    if mesh.volume <= 0:
        # Signed volume is computed from the winding, so a negative one means the
        # normals point inward — every overhang angle would come out mirrored and
        # the control would "work" for the wrong reason.
        raise ValueError(f"fixture {what} has non-positive signed volume "
                         f"({mesh.volume:.3f}): its faces are wound inside out")


# ---------------------------------------------------------------------------
# SEALED FIXTURES
#
# A control must fire in EVERY project, not just a friendly one. Layering the
# known-bad values over the host project's projection looks safe — the override
# wins on every key it states — but gates resolve synonym families and derived
# quantities, so a key the fixture never mentions can still arrive from the
# project and neutralise the control.
#
# It was observed live in a sibling pack: a fixture raised a hull's centre of
# gravity to make it unstable, the host project happened to state a waterplane
# inertia (an honest thing to state, better than the pack's own fallback), and
# the gate PASSED ITS OWN KNOWN-BAD FIXTURE. A control whose severity depends on
# the host project's numbers passes in some repositories and fails in others,
# which is the same as having none.
#
# So the base here is the pack's OWN baseline.json, and nothing is inherited.
# `tests/test_packs.py::ControlsAreSealed` runs every control against an empty
# projection to keep it that way.
# ---------------------------------------------------------------------------
_BASELINE_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                               "baseline.json")


def _baseline() -> dict:
    """The pack's own plausible-good projection, documentation keys stripped."""
    try:
        with open(_BASELINE_PATH, "r", encoding="utf-8") as handle:
            loaded = _json.load(handle)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in loaded.items() if not k.startswith("_")}


def _stage(ctx, mesh, name: str):
    """Write the solid beside the run's other evidence and point the model at it."""
    path = ctx.out_path("selftest", name)
    mesh.export(path)
    params = _baseline()
    params["mesh_path"] = path
    return dataclasses.replace(ctx, params=params)


# --------------------------------------------------------------------------- #
# the controls
# --------------------------------------------------------------------------- #
def steep_cone(ctx):
    """fdm.overhang — a cone stood on its apex, 70 degrees from vertical.

    Every one of the side faces is at 70 degrees, against a default limit of 45,
    and together they are the entire outer surface: not a nub, a surface. The
    solid is watertight, 66 mm across, 12 mm tall and sits on the bed, so no other
    gate in this pack has anything to say about it.

    The height is deliberately small. A tall cone would also be a bed-adhesion and
    a bridge question, and a control that trips three gates cannot tell you which
    one is working.
    """
    return _stage(ctx, _cone(70.0, 12.0, apex_down=True), "steep_cone.stl")


def long_bridge(ctx):
    """fdm.bridge_span — a flat ceiling spanning 90 mm between two legs.

    Three times the default 30 mm maximum. The ceiling is anchored properly at
    both ends, so the gate has to measure the span rather than notice that
    something is hanging in space; that is the harder case and the one worth
    controlling for.

    The gap is read against the limit the gate will actually enforce — the
    baseline's ``max_bridge_mm``, the same projection the fixture is staged
    against — so the fixture cannot be quietly neutralised by raising the limit:
    it is always three times whatever the gate is being asked to enforce. (It read
    ``ctx.param`` for that number before, which took it from the host project
    while the rest of the projection came from the baseline: two different
    machines describing one fixture.)
    """
    base = _baseline()
    limit = float(base.get("max_bridge_mm", base.get("bridge_limit_mm", 30.0)))
    gap = 3.0 * limit
    return _stage(ctx, _arch(gap, width=gap + 50.0), f"arch_gap_{gap:.0f}mm.stl")
