# SPDX-License-Identifier: Apache-2.0
"""Tier-1 mesh gates: overhang angle and unsupported bridge span.

These two need the actual triangles, so they need ``trimesh`` and ``numpy``. Both
are declared in ``requires_python`` and imported LAZILY inside the gate bodies, so
this module imports cleanly on a machine that has neither. When they are absent
the spine's ``availability()`` reports SKIPPED with the missing module named, the
claim resolves BLOCKED, and it stays visible in the readiness report. That is the
whole point: a gate that quietly downgraded to a cheaper approximation would turn
"we did not check this" into "this is fine" (rule 4).

Frames and units
----------------
Lengths are mm. The mesh is read in its **print orientation**: the model is
responsible for exporting the part the way it will sit on the bed. The build
direction is ``build_axis`` from the projection, defaulting to +Z; every angle
below is measured against that axis, so a project that prints along a different
axis gets the right answer without re-exporting.

Angle convention: the **overhang angle** of a face is its inclination away from
the build direction, in degrees. A vertical wall is 0 deg. A 45 deg chamfer
underside is 45 deg. A flat ceiling is 90 deg. This is the number a slicer's
"support overhang threshold" refers to.

Both gates read the mesh through :func:`_load_mesh`, which refuses one that is not
a solid — not watertight, or wound inside out. That refusal is a FAIL and not a
skip: every number below is read off a face normal, and a face normal only means
"outward" if the winding says so. See :func:`_solid_defect`.
"""
from __future__ import annotations

import math
import os
from typing import Any, Iterable, Sequence

from atompipe.gates import gate, GateContext
from atompipe.models import NegativeControl, Tier, Verdict

# --------------------------------------------------------------------------- #
# domain constants
# --------------------------------------------------------------------------- #

OVERHANG_LIMIT_DEG_DEFAULT = 45.0
"""Steepest face a machine will print without support, degrees from vertical.

45 deg is the classic threshold and the conservative one: each layer is offset by
half a bead and still lands on solid material beneath it. Well-cooled PLA on a
part-cooling-fan machine reaches 50-55; ABS in a hot chamber with weak cooling
does not reach 45. Projects override ``overhang_limit_deg`` and should record
which machine and material the number came from. Rejected: 60 deg as a default —
it is reachable on a good machine with a tuned profile, and adopting it as the
default means every pack user inherits one person's tuning."""

OVERHANG_AREA_ALLOW_FRAC_DEFAULT = 0.005
"""Overhanging area tolerated, as a fraction of total surface area.

One face past the limit is a nub; a hundred is a surface. A tessellated cylinder
or fillet will always have a sliver of geometry a fraction of a degree past any
threshold, and failing a part for that is how a gate gets switched off. Half a
percent of surface area is small enough that a real unsupported region — the
underside of a boss, a horizontal hole's ceiling — clears it easily, and large
enough that tessellation noise does not. The verdict always reports the worst
angle, the face count and the absolute area, so a nub is visible even when it
does not fail."""

BRIDGE_CEILING_DEG_DEFAULT = 80.0
"""Overhang angle at which a face stops being a steep wall and starts being a
ceiling to bridge across. Above 80 deg the slicer's bridging logic takes over from
its support logic; below it the material is still climbing."""

MAX_BRIDGE_MM_DEFAULT = 30.0
"""Unsupported horizontal span a machine will bridge acceptably, mm.

30 mm is the span at which a well-cooled bridge is still flat enough to build on.
Longer bridges print — 50 to 100 mm is commonly demonstrated — but they sag, the
first solid layer above them is lumpy, and anything dimensional on that face is
lost. Chamfering the span to 45 deg or splitting the part is almost always
cheaper than supporting it. Projects override ``max_bridge_mm``.

This figure applies to a **bridge** — a ceiling anchored on opposite sides, where
the strand is pulled taut between two landings. It is not the allowance for a
cantilever; see ``MAX_CANTILEVER_MM_DEFAULT``."""

MAX_CANTILEVER_MM_DEFAULT = 2.0
"""Unsupported horizontal projection off a SINGLE anchor, mm.

A bridge and a cantilever are not the same problem and must not share a number. A
bridge is a strand under tension between two landings: it is pulled straight, it
cools straight, and 30 mm of it is routine. A cantilevered ceiling is anchored at
one end and lands on nothing, so the strand has no second attachment to pull
against — it droops under its own weight the moment it leaves the nozzle, curls up
into the path of the next pass, and the layer above lands on a ridge. The length
that survives is roughly the length that cools before it sags, which on ordinary
part cooling is a couple of millimetres, not tens.

2 mm is a little over four beads at a 0.42 mm line width, which is about what a
horizontal hole's crown or a small ledge gets away with unsupported. Rejected:
0 mm — every tessellated fillet and every hole crown produces a sliver of
one-sided ceiling, and a gate that fails all of them is a gate people switch off;
and 5 mm, which is demonstrably printable but arrives visibly curled and is not
something to certify silently. Projects override ``max_cantilever_mm`` with the
material and cooling it was measured on."""

CANTILEVER_HALF_PLANE_TOL_DEG = 5.0
"""How far the anchors around the worst point may fall short of surrounding it
before the region is called a cantilever, degrees.

The test is whether the directions from the worst point to its anchors leave a
gap wider than a half-plane: 180 deg exactly for a perfect bridge (two anchors
dead opposite), more when everything holding the region up is on one side. The
tolerance keeps a bridge whose two landings are slightly skew — a tapered slot, a
tessellated arch — from tipping into the cantilever branch on a fraction of a
degree. Rejected: 0 (the perfect-bridge case sits exactly on the boundary and
floating point puts it on either side of it) and 45 (wide enough to let a genuine
corner ledge, whose two perpendicular walls span 90 deg, be scored as a bridge)."""

BED_TOLERANCE_MM = 0.05
"""How close to the lowest point a face must be to count as sitting ON the bed.

This exclusion is not cosmetic. The bottom face of any part is, geometrically, a
90 deg overhang facing straight down; without excluding it every solid ever
modelled fails the overhang gate and the gate becomes noise."""

_MISSING = object()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _look(ctx: GateContext, names: Sequence[str], default: Any = _MISSING) -> Any:
    for name in names:
        value = ctx.param(name, _MISSING)
        if value is not _MISSING and value is not None:
            return value
    return default


def _skip(gate_id: str, reason: str) -> Verdict:
    return Verdict(gate=gate_id, passed=False, skipped=True, skip_reason=reason)


def _build_axis(ctx: GateContext):
    """Unit build direction and an orthonormal basis for the bed plane.

    Returned as plain tuples so the caller can hand them to numpy without this
    helper importing it.
    """
    raw = _look(ctx, ("build_axis", "layer_normal", "print_axis"), None)
    vec = [0.0, 0.0, 1.0]
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        try:
            candidate = [float(v) for v in raw]
        except (TypeError, ValueError):
            candidate = []
        if len(candidate) == 3 and math.sqrt(sum(c * c for c in candidate)) > 0:
            vec = candidate
    n = math.sqrt(sum(c * c for c in vec))
    return tuple(c / n for c in vec)


def _load_mesh(ctx: GateContext, gate_id: str):
    """``(mesh, path, None)`` or ``(None, None, verdict)``.

    A missing ``mesh_path`` and a path that does not exist both SKIP rather than
    error: in both cases the gate did not measure the design, and the claim must
    resolve BLOCKED rather than FAIL. A mesh that exists and will not parse is a
    different animal and is allowed to raise — that is a broken artifact, and a
    broken artifact is a real finding.

    A mesh that loads but is **not a solid** is the third case, and it FAILS
    rather than skipping — see :func:`_solid_defect`.
    """
    import trimesh                                    # noqa: PLC0415 - lazy on purpose

    path = _look(ctx, ("mesh_path", "stl_path", "part_mesh", "geometry_path"), _MISSING)
    if path is _MISSING:
        return None, None, _skip(
            gate_id,
            "the projection has no mesh_path / stl_path (the exported part mesh in "
            "its print orientation); generate the mesh and add the path to the model",
        )
    path = str(path)
    if not os.path.isabs(path):
        path = os.path.join(ctx.root or os.curdir, path)
    if not os.path.isfile(path):
        return None, None, _skip(gate_id, f"mesh_path points at {path}, which does "
                                          f"not exist — nothing was measured")

    loaded = trimesh.load_mesh(path, process=True)
    if isinstance(loaded, trimesh.Scene):
        try:
            loaded = loaded.dump(concatenate=True)
        except TypeError:                              # older trimesh
            loaded = trimesh.util.concatenate(loaded.dump())
    if getattr(loaded, "faces", None) is None or len(loaded.faces) == 0:
        return None, None, _skip(gate_id, f"{os.path.basename(path)} loaded with no faces")

    defect = _solid_defect(loaded, os.path.basename(path))
    if defect is not None:
        return None, None, Verdict(
            gate=gate_id, passed=False, measured=round(float(loaded.volume), 1),
            limit=0.0, units="mm^3 signed volume", detail=defect,
        )
    return loaded, path, None


def _solid_defect(mesh, name: str) -> str | None:
    """A one-line description of why this mesh is not a solid, or None.

    **Why this FAILS the gate rather than skipping it.** Every number both mesh
    gates produce is read off ``face_normals``, and a face normal only means
    "outward" if the winding says so. Flip the winding and the signed volume goes
    negative, every overhang angle comes out mirrored, and a part covered in 70
    deg overhangs reports ``worst face 0.0 deg`` — a confident green about a
    quantity that was never measured. That is not "the gate could not run", which
    is what a skip means; it is a defect in the artifact the project handed over,
    and it is exactly the kind of finding a readiness report exists to carry.

    The pack's own fixture builder has asserted this on the solids it generates
    since the day it was written, with a comment explaining that mirrored normals
    would make a control "work" for the wrong reason. The project's mesh gets the
    same check, for the same reason.

    ``is_winding_consistent`` is deliberately NOT part of the test: an STL is a
    soup of independent triangles, and a perfectly good solid comes back from the
    round trip with that flag false while ``is_watertight`` and a positive signed
    volume both hold. Testing it would fail honest meshes, and a gate that fails
    honest input gets switched off.
    """
    import numpy as np                                 # noqa: PLC0415

    if not mesh.is_watertight:
        edges = np.sort(mesh.edges, axis=1)
        _, counts = np.unique(edges, axis=0, return_counts=True)
        open_edges = int((counts != 2).sum())
        return (f"{name} is not watertight: {open_edges} edge(s) are not shared by "
                f"exactly two faces, so it has holes or self-intersects. Inside and "
                f"outside are undefined on such a mesh, which makes every face "
                f"normal — and so every overhang and bridge number below — "
                f"meaningless. Repair the mesh or re-export it as a solid")
    if mesh.volume <= 0:
        return (f"{name} has non-positive signed volume ({mesh.volume:.1f} mm^3): its "
                f"faces are wound inside out. Every overhang angle would come out "
                f"mirrored, so a part that is nothing but steep overhangs reports "
                f"0.0 deg and passes. Flip the normals (trimesh: fix_normals) and "
                f"re-export")
    return None


def _face_angles(mesh, axis):
    """Overhang angle per face, in degrees, against the build axis.

    ``asin`` of the downward component of the unit normal: 0 for a vertical wall,
    90 for a face pointing straight at the bed. Upward-facing faces come back
    negative and are simply never selected.
    """
    import numpy as np                                 # noqa: PLC0415

    b = np.asarray(axis, dtype=float)
    comp = np.clip(mesh.face_normals @ b, -1.0, 1.0)
    return np.degrees(np.arcsin(-comp)), comp


def _anchors_surround(vectors, tol_deg: float) -> bool:
    """Do these directions surround the origin, or do they all lie to one side?

    ``vectors`` are the in-plane directions from the worst point of a ceiling
    region to the nearest point on each of its anchored edges. Sort them by angle
    and look at the widest gap between neighbours: a point held between two
    landings has a gap of exactly 180 deg (the two anchors are opposite); a point
    hanging off a single wall — or off two walls meeting at a corner — leaves
    everything on one side and a gap wider than a half-plane.

    That distinction is the whole physical difference between a bridge and a
    cantilever, and it is why this is a direction test rather than a count of
    anchored edges. A ceiling's wall side is triangulated into several boundary
    edges, so "one anchored edge" and "anchored on one side" are not the same
    statement, and counting edges gets an L-shaped corner ledge wrong.
    """
    import numpy as np                                 # noqa: PLC0415

    v = np.asarray(vectors, dtype=float)
    v = v[np.linalg.norm(v, axis=1) > 1e-9]
    if len(v) == 0:
        return True                                    # the point IS an anchor
    ang = np.sort(np.degrees(np.arctan2(v[:, 1], v[:, 0])))
    gaps = np.append(np.diff(ang), ang[0] + 360.0 - ang[-1])
    return float(gaps.max()) <= 180.0 + tol_deg


def _on_bed(mesh, axis):
    """Boolean mask of faces lying in the first layer, which are not overhangs."""
    import numpy as np                                 # noqa: PLC0415

    b = np.asarray(axis, dtype=float)
    height = mesh.vertices @ b
    lowest = float(height.min())
    return height[mesh.faces].max(axis=1) <= lowest + BED_TOLERANCE_MM


# --------------------------------------------------------------------------- #
# fdm.overhang
# --------------------------------------------------------------------------- #
@gate(
    id="fdm.overhang",
    title="Unsupported faces within the printable overhang angle",
    claims=["manufacturability", "fdm", "additive", "printability"],
    tier=Tier.BUILD,
    settles="overhang angle",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:steep_cone",
        note="a cone stood on its apex with a 70-degree half angle: every side "
             "face is 70 deg from vertical, well past the limit, and nothing "
             "else about the solid is wrong — it is watertight, on the bed, and "
             "the right size",
    ),
)
def overhang(ctx: GateContext) -> Verdict:
    """Face normals past the unsupported-angle limit, by worst angle AND by area.

    Both numbers are reported because they mean different things. The worst angle
    says how bad the geometry gets; the area says how much of the part is like
    that. One face at 89 deg is a nub that will print as a small blob. A hundred
    faces at 60 deg is a surface that will print as strings, and the part either
    needs support (and the scar that comes with it) or a different orientation.

    The gate fails on AREA, against ``OVERHANG_AREA_ALLOW_FRAC_DEFAULT``, because
    that is the number that decides whether the part is printable. The angle is in
    the verdict so a human can tell a nub from a surface without opening the mesh.

    Two classes of face are excluded, both deliberately:

    * **First-layer faces.** The bottom of the part is a 90 deg overhang onto the
      bed, which is where it is supposed to be.
    * **Flat ceilings**, at or past ``BRIDGE_CEILING_DEG_DEFAULT``. A slicer does
      not support those, it bridges them, and whether that works is a question
      about span rather than angle. ``fdm.bridge_span`` owns them.

    The ceiling exclusion has a reporting trap in it and the verdict closes it.
    A part whose only downward geometry is a flat ceiling has nothing left in this
    gate's selection, so the worst *supportable* angle is 0.0 deg — true, and read
    on its own it says "this part has no overhangs" about a part with a 90 deg face
    on it. So the verdict reports BOTH: the worst angle this gate judged, and the
    steepest downward face on the part regardless of who owns it.

    It also refuses to run at all when ``overhang_limit_deg`` is set at or past
    ``bridge_ceiling_deg``, because the two selections then have no gap between
    them and no geometry can trip the gate — see the verdict at the top of the
    body.

    What this does NOT settle: whether supports can be *removed* afterwards. A
    steep face inside a closed pocket passes this gate and traps its support
    forever. See ``lenses.md``.
    """
    import numpy as np                                 # noqa: PLC0415

    mesh, mesh_path, bail = _load_mesh(ctx, "fdm.overhang")
    if bail is not None:
        return bail

    axis = _build_axis(ctx)
    limit = float(_look(ctx, ("overhang_limit_deg", "max_overhang_deg"),
                        OVERHANG_LIMIT_DEG_DEFAULT))
    allow = float(_look(ctx, ("overhang_area_allow_frac",),
                        OVERHANG_AREA_ALLOW_FRAC_DEFAULT))
    ceiling_deg = float(_look(ctx, ("bridge_ceiling_deg",),
                              BRIDGE_CEILING_DEG_DEFAULT))

    if limit >= ceiling_deg:
        # Not a measurement, a refusal. Every face past `limit` is also past
        # `ceiling_deg`, so it is handed to fdm.bridge_span as a ceiling and this
        # gate's selection is empty by construction: it would return "0 faces
        # past it, 0.00% of surface" on a part made entirely of 90 deg overhangs
        # and call that a pass. A gate that cannot fail is a logger (rule 5), so
        # it says so instead of returning a green it has not earned.
        return Verdict(
            gate="fdm.overhang", passed=False, measured=round(limit, 1),
            limit=round(ceiling_deg, 1), units="deg",
            detail=f"INERT CONFIGURATION: overhang_limit_deg {limit:.0f} is at or past "
                   f"bridge_ceiling_deg {ceiling_deg:.0f}, so every face this gate could "
                   f"fail on is already excluded as a ceiling and no geometry can ever "
                   f"trip it. Lower overhang_limit_deg below bridge_ceiling_deg, or "
                   f"raise bridge_ceiling_deg if the machine really does bridge from "
                   f"{limit:.0f} deg",
        )

    angles, _ = _face_angles(mesh, axis)
    areas = mesh.area_faces
    total_area = float(areas.sum())
    bed = _on_bed(mesh, axis)

    ceilings = (angles >= ceiling_deg) & (~bed)      # bridges, not supports
    past = (angles > limit) & (~ceilings) & (~bed)
    n_past = int(past.sum())
    area_past = float(areas[past].sum())
    frac = area_past / total_area if total_area > 0 else 0.0
    candidates = angles[(angles > 0.0) & (~ceilings) & (~bed)]
    worst = float(candidates.max()) if candidates.size else 0.0
    # The worst angle INCLUDING the ceilings this gate handed away. Without it the
    # verdict on a part whose only downward geometry is a flat ceiling reads
    # "worst face 0.0 deg" — true of what this gate measured and badly misleading
    # about the part, which has a 90 deg face on it.
    downward = angles[(angles > 0.0) & (~bed)]
    worst_all = float(downward.max()) if downward.size else 0.0

    report = ctx.out_path("fdm-overhang.txt")
    order = np.argsort(-angles * past)
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(f"# fdm.overhang — {mesh_path}\n")
        fh.write(f"# build axis {axis}, limit {limit} deg, {len(mesh.faces)} faces, "
                 f"{total_area:.1f} mm^2 total surface\n")
        fh.write(f"# {n_past} faces past the limit, {area_past:.2f} mm^2 "
                 f"({frac * 100:.3f}% of surface)\n")
        fh.write("face_index\tangle_deg\tarea_mm2\tcentroid_x\tcentroid_y\tcentroid_z\n")
        centroids = mesh.triangles_center
        for i in order[:200]:
            if not past[i]:
                break
            c = centroids[i]
            fh.write(f"{int(i)}\t{angles[i]:.2f}\t{areas[i]:.4f}\t"
                     f"{c[0]:.3f}\t{c[1]:.3f}\t{c[2]:.3f}\n")

    return Verdict(
        gate="fdm.overhang",
        passed=frac <= allow,
        measured=round(frac, 5),
        limit=round(allow, 5),
        units="area fraction",
        detail=f"worst supportable face {worst:.1f} deg vs {limit:.0f} deg limit; "
               f"{n_past} faces past it covering {area_past:.1f} mm^2 = "
               f"{frac * 100:.2f}% of surface (allowance {allow * 100:.2f}%); "
               f"steepest downward face on the part {worst_all:.1f} deg, "
               f"{int(ceilings.sum())} at or past {ceiling_deg:.0f} deg excluded as "
               f"ceilings — they are fdm.bridge_span's",
        evidence=[report],
    )


# --------------------------------------------------------------------------- #
# fdm.bridge_span
# --------------------------------------------------------------------------- #
@gate(
    id="fdm.bridge_span",
    title="Unsupported horizontal spans within the bridgeable maximum",
    claims=["manufacturability", "fdm", "additive", "printability"],
    tier=Tier.BUILD,
    settles="bridge span",   # and the cantilever case, which is the same measurement
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:long_bridge",
        note="an arch whose flat ceiling spans three times the limit between two "
             "properly anchored legs, so the gate has to measure a real bridge "
             "rather than notice a cantilever — the span is the only thing "
             "wrong: the solid is watertight, sits on the bed and fits the "
             "build volume",
    ),
)
def bridge_span(ctx: GateContext) -> Verdict:
    """Longest unsupported horizontal span the printer would have to bridge.

    The measurement, stated plainly so a reader can judge it:

    1. Select near-horizontal downward faces — overhang angle at or past
       ``BRIDGE_CEILING_DEG_DEFAULT``. These are ceilings. Faces in the first
       layer are excluded; they are the bed.
    2. Group them into connected regions by shared edges. One region is one
       ceiling.
    3. Find each region's boundary edges, and call an edge **anchored** when the
       face on the other side of it descends — that is where the ceiling meets a
       wall that carries it down to material below. A boundary edge whose
       neighbour rises is a free edge: the ceiling simply ends there with nothing
       under it.
    4. Take the point of the region furthest, in the bed plane, from its nearest
       anchor, and ask what is holding that point up — see
       :func:`_anchors_surround`. If the anchors surround it, it is the middle of
       a **bridge** and the span is twice that distance, because the strand runs
       landing to landing. If they all lie to one side, it is the tip of a
       **cantilever**: the span is that distance once, and it is measured against
       ``MAX_CANTILEVER_MM_DEFAULT`` instead, which is more than an order of
       magnitude smaller.

    That third case is not a refinement, it is the commonest support question
    there is. A 15 mm shelf projecting off a wall into thin air used to be scored
    as "a 30 mm bridge" and compared against a bridge limit, which passed it —
    while the overhang gate had already handed its 90 deg underside away as a
    ceiling. A cantilever is not half a bridge of twice the length: there is no
    second landing, the strand is unsupported at its free end from the first pass,
    and it droops and curls instead of pulling taut.

    This is an approximation and worth knowing the edges of. It measures the
    *geometry* of the unsupported region, not what a particular slicer will do
    with it: a slicer may anchor a bridge on an infill line inside the region, or
    lay the bridge diagonally, both of which shorten the real span. It will not
    find a span that only exists between two separately-printed islands. A region
    with no anchored edge at all — a ceiling hanging off nothing — is reported as
    UNANCHORED against a limit of zero, because no span is short enough to save a
    ceiling that lands on nothing at all.

    What this does NOT settle: whether the bridge will *look* acceptable, or
    whether a dimensional feature on the bridged face survives. A 25 mm bridge
    passes and still sags half a millimetre in the middle.
    """
    import numpy as np                                 # noqa: PLC0415

    mesh, mesh_path, bail = _load_mesh(ctx, "fdm.bridge_span")
    if bail is not None:
        return bail

    axis = _build_axis(ctx)
    limit = float(_look(ctx, ("max_bridge_mm", "bridge_limit_mm"),
                        MAX_BRIDGE_MM_DEFAULT))
    cantilever_limit = float(_look(ctx, ("max_cantilever_mm",),
                                   MAX_CANTILEVER_MM_DEFAULT))
    ceiling_deg = float(_look(ctx, ("bridge_ceiling_deg",),
                              BRIDGE_CEILING_DEG_DEFAULT))

    angles, _ = _face_angles(mesh, axis)
    sel = (angles >= ceiling_deg) & (~_on_bed(mesh, axis))
    n_sel = int(sel.sum())
    if n_sel == 0:
        return Verdict(
            gate="fdm.bridge_span", passed=True, measured=0.0, limit=round(limit, 2),
            units="mm",
            detail=f"no ceiling faces at or past {ceiling_deg:.0f} deg off the bed — "
                   f"nothing to bridge ({len(mesh.faces)} faces checked)",
        )

    b = np.asarray(axis, dtype=float)
    u = np.array([1.0, 0.0, 0.0]) if abs(b[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = u - b * (u @ b)
    u /= np.linalg.norm(u)
    v = np.cross(b, u)
    verts = mesh.vertices
    plane = np.column_stack((verts @ u, verts @ v))     # every vertex in bed coords
    height = verts @ b

    # ---- edge bookkeeping: which faces share which edge --------------------- #
    edges = mesh.edges_sorted
    _, edge_id = np.unique(edges, axis=0, return_inverse=True)
    edge_id = np.asarray(edge_id).ravel()
    face_of = np.repeat(np.arange(len(mesh.faces)), 3)
    order = np.argsort(edge_id, kind="stable")
    eid_sorted, face_sorted = edge_id[order], face_of[order]
    starts = np.searchsorted(eid_sorted, np.arange(eid_sorted[-1] + 1), side="left")
    ends = np.searchsorted(eid_sorted, np.arange(eid_sorted[-1] + 1), side="right")
    edge_verts = edges[order[starts]]                   # one vertex pair per edge id

    # ---- connected regions of ceiling faces --------------------------------- #
    parent = {int(f): int(f) for f in np.flatnonzero(sel)}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    shared = np.flatnonzero((ends - starts) == 2)
    for eid in shared:
        a, c = int(face_sorted[starts[eid]]), int(face_sorted[starts[eid] + 1])
        if sel[a] and sel[c]:
            ra, rc = find(a), find(c)
            if ra != rc:
                parent[ra] = rc

    regions: dict[int, list[int]] = {}
    for f in parent:
        regions.setdefault(find(f), []).append(f)

    centroids = mesh.triangles_center
    areas = mesh.area_faces
    worst_ratio = -1.0
    worst_span, worst_note, worst_area, worst_h = 0.0, "no ceiling region", 0.0, 0.0
    worst_limit = limit
    rows: list[str] = []

    for root, faces in regions.items():
        faces_arr = np.asarray(faces)
        region_mask = np.zeros(len(mesh.faces), dtype=bool)
        region_mask[faces_arr] = True

        # boundary edges of the region: edges used by exactly one of its faces
        eids = edge_id.reshape(-1, 3)[faces_arr].ravel()
        uniq, counts = np.unique(eids, return_counts=True)
        boundary = uniq[counts == 1]

        anchors = []
        for eid in boundary:
            lo, hi = starts[eid], ends[eid]
            mid_h = float(height[edge_verts[eid]].mean())
            for k in range(lo, hi):
                f = int(face_sorted[k])
                if region_mask[f]:
                    continue
                if float(centroids[f] @ b) < mid_h - 1e-9:
                    anchors.append(edge_verts[eid])
                    break

        # sample the region densely enough that its middle is represented
        tri = mesh.faces[faces_arr]
        sample_idx = np.unique(tri)
        samples = np.vstack((plane[sample_idx], centroids[faces_arr] @ np.column_stack((u, v))))
        for a, c in ((0, 1), (1, 2), (2, 0)):
            samples = np.vstack((samples, 0.5 * (plane[tri[:, a]] + plane[tri[:, c]])))

        area = float(areas[faces_arr].sum())
        z = float((centroids[faces_arr] @ b).mean())

        if not anchors:
            lo, hi = samples.min(axis=0), samples.max(axis=0)
            span = float(np.linalg.norm(hi - lo))
            note, region_limit = "UNANCHORED", 0.0
        else:
            seg = np.asarray(anchors)                   # (A, 2) vertex index pairs
            p0, p1 = plane[seg[:, 0]], plane[seg[:, 1]]
            d = p1 - p0
            denom = np.einsum("ij,ij->i", d, d)
            denom[denom == 0] = 1e-12
            diff = samples[:, None, :] - p0[None, :, :]
            t = np.clip(np.einsum("ijk,jk->ij", diff, d) / denom, 0.0, 1.0)
            closest = p0[None, :, :] + t[:, :, None] * d[None, :, :]
            offset = closest - samples[:, None, :]      # (S, A, 2) toward each anchor
            dist = np.linalg.norm(offset, axis=2).min(axis=1)
            far = int(np.argmax(dist))
            reach = float(dist[far])
            if _anchors_surround(offset[far], CANTILEVER_HALF_PLANE_TOL_DEG):
                # Held on both sides: the worst point is the middle of a bridge.
                span, region_limit = 2.0 * reach, limit
                note = f"BRIDGE, {len(anchors)} anchored edge(s) around it"
            else:
                # Everything holding it up is on one side: the worst point is the
                # free tip of a cantilever and the span is its projection, once.
                span, region_limit = reach, cantilever_limit
                note = f"CANTILEVER, {len(anchors)} anchored edge(s) all to one side"

        ratio = (span / region_limit) if region_limit > 0 else (
            float("inf") if span > 0 else 0.0)
        rows.append(f"{len(faces_arr)}\t{area:.2f}\t{z:.2f}\t{span:.2f}\t"
                    f"{region_limit:.2f}\t{note}")
        if ratio > worst_ratio:
            worst_ratio = ratio
            worst_span, worst_note, worst_area, worst_h = span, note, area, z
            worst_limit = region_limit

    report = ctx.out_path("fdm-bridge-span.txt")
    with open(report, "w", encoding="utf-8") as fh:
        fh.write(f"# fdm.bridge_span — {mesh_path}\n")
        fh.write(f"# build axis {axis}, ceiling >= {ceiling_deg} deg, bridge limit "
                 f"{limit} mm, cantilever limit {cantilever_limit} mm\n")
        fh.write(f"# {len(regions)} ceiling region(s) from {n_sel} faces\n")
        fh.write("faces\tarea_mm2\theight_mm\tspan_mm\tlimit_mm\tanchoring\n")
        fh.write("\n".join(rows) + "\n")

    limit_note = ("no span is acceptable" if worst_limit <= 0
                  else f"{worst_limit:.0f} mm limit")
    return Verdict(
        gate="fdm.bridge_span",
        passed=worst_ratio <= 1.0,
        measured=round(worst_span, 2),
        limit=round(worst_limit, 2),
        units="mm",
        detail=f"worst unsupported span {worst_span:.1f} mm vs {limit_note} "
               f"({worst_note}) on a {worst_area:.0f} mm^2 ceiling at {worst_h:.1f} mm; "
               f"{len(regions)} ceiling region(s) from {n_sel} faces, bridges judged "
               f"at {limit:.0f} mm and cantilevers at {cantilever_limit:.0f} mm",
        evidence=[report],
    )
