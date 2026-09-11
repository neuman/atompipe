# SPDX-License-Identifier: Apache-2.0
"""Solid-geometry gates: is this actually a solid, and do the solids fit together?

Order in this file is the order the sweep runs, and it is deliberate. The cheap
arithmetic envelope check goes first; then the three mesh-validity gates, cheapest
and most fundamental first; then the two gates that are only meaningful on a mesh
that already passed those three. A pack that reports thin walls on a mesh which is
not even closed has measured nothing and said something.

trimesh is imported INSIDE the gate functions, never at module import. Two reasons,
both load-bearing:

* this module must import cleanly on a machine with no mesh library, so the pack is
  discoverable and `atompipe gate list` still works and says BLOCKED;
* the tier-0 gate (``cad.bounding``) declares no mesh dependency and must actually
  run there. A top-level ``import trimesh`` would take the whole module down and the
  cheap gate with it.

Every gate reads its numbers from ``ctx.params`` (the model projection) or from the
meshes the projection points at. Nothing here re-derives a model quantity: a gate
that recomputes a derived value is checking its own arithmetic instead of the
model's.
"""
from __future__ import annotations

import json
import math
import os
from typing import Any

from atompipe.gates import gate, GateContext
from atompipe.models import NegativeControl, Tier, Verdict


# --------------------------------------------------------------------------- #
# domain constants — properties of mesh geometry, not of any one project
# --------------------------------------------------------------------------- #

#: Vertex weld tolerance. Two vertices closer than this are the same vertex that a
#: tessellator emitted twice. Chosen an order of magnitude below the smallest
#: feature any of these gates claims to resolve (~1e-3 mm) and several orders above
#: float32 noise on a 100 mm part (~1e-5 mm), so it cannot weld a real feature shut
#: and cannot miss a duplicate. Rejected: 1e-3 mm, which welds the two sides of a
#: genuine 1 um-scale seam on a scaled-up model and reports a clean part; and
#: 1e-6 mm, which leaves float32-round-tripped STL duplicates unwelded so every
#: exported part looks defective.
WELD_TOL_MM = 1e-4

#: Below this, a triangle has no area. This is a NUMERIC zero, not a sliver test:
#: a 1e-6 mm^2 needle is about a hundred times larger than this and passes. See the
#: "what this pack cannot settle" section of PACK.md.
ZERO_AREA_MM2 = 1e-8

#: Per-pair intersection tolerance, prismatic default. Two planar faces meeting
#: face-to-face tessellate to coincident triangles; the boolean kernel resolves
#: them to slivers whose total volume stays well under a tenth of a cubic
#: millimetre on parts of ordinary size. Anything above this is geometry, not noise.
#:
#: A VOLUME tolerance alone is not enough and must never be read as one: it
#: forgives a fixed volume, so the penetration DEPTH it forgives grows without
#: bound as the contact area shrinks. At 0.2 mm^3 a 0.5 mm pin may be driven
#: 0.79 mm into a block — deeper than the pin is wide — and still read as clear.
#: That is why every pair is also checked against a depth tolerance below.
PRISMATIC_CLASH_TOL_MM3 = 0.2

#: Per-pair tolerance for a pair where either part is organic/curved (a printed
#: fillet, a lofted shell, a revolved boss). Chord-height error on a tessellated
#: curve is of order the chord deviation times the mating area, which reaches a few
#: cubic millimetres on a part of ordinary size (roughly 100 mm across) at default
#: export settings — that size is the constant's VALIDITY REGIME, and it is stated
#: in PACK.md as well as here because a reader calibrating a tolerance will not
#: read the source. On a part an order of magnitude larger the mating area grows
#: with it and this number is too small; the depth tolerance below is the
#: scale-free half of the pair and is what actually governs a slender contact.
#: Raising the GLOBAL tolerance to 3 mm^3 to silence one curved pair is how a real
#: 2 mm^3 interference between two flat plates gets hidden; that is why this is
#: per-pair.
ORGANIC_CLASH_TOL_MM3 = 3.0

#: Per-pair penetration DEPTH tolerance, prismatic default. This is the half of the
#: clash test that does not depend on how big the contact patch is: mean depth is
#: shared volume over contact area, so it stays the same physical statement on a
#: 5 mm pin and a 200 mm flange while a volume tolerance does not. 0.01 mm is the
#: linear deviation an ordinary exporter puts between two nominally coincident
#: planar faces at default settings (see sourcing.md), so it is the largest
#: apparent penetration that is definitely tessellation and not geometry.
#: Rejected: 0 mm, which fails every intended face contact on export noise alone;
#: and 0.1 mm, which is a real light press fit on a part of this size — forgiving
#: it would hide exactly the interference this gate exists to find.
PRISMATIC_CLASH_DEPTH_TOL_MM = 0.01

#: The same for a pair where either part is curved. The error here is the chord
#: height of the tessellated curve, not the exporter's planar deviation: at default
#: angular/chord settings that is a few hundredths of a millimetre on a part of
#: ordinary size. Rejected: sharing the prismatic 0.01 mm, which reports every
#: curved mating face in the assembly as an interference at default export
#: settings and trains everyone to widen the tolerance globally.
ORGANIC_CLASH_DEPTH_TOL_MM = 0.05

#: Bounding boxes are grown by this before the overlap pre-filter, so a pair that
#: is touching-to-within-tessellation-noise still reaches the boolean rather than
#: being filtered out by an arithmetic hair.
AABB_MARGIN_MM = 0.05

#: Ray budget for the wall-thickness sampler, as an exact ray COUNT. Above this many
#: faces the gate casts from an evenly spaced deterministic subset of exactly this
#: size rather than from every facet; a gate whose cost scales with tessellation
#: density stops being runnable exactly when the model gets detailed enough to need
#: it. Rejected: a stride (``n_faces // budget``), which is what this was — it gives
#: stride 1 for any face count below twice the budget, so the real ceiling was about
#: double the number stated here and the gate's cost was not the cost it declared.
MAX_WALL_SAMPLES = 4000

#: Formats that store a bag of triangles with no vertex identity. A file in one of
#: these has no topology until somebody welds it, so this pack welds it once at the
#: weld tolerance and says so in the verdict rather than pretending the file was
#: closed or that every repeated corner is a defect.
SOUP_SUFFIXES = (".stl",)

#: Keys, in order, that may carry the solid geometry.
_MESH_KEYS = ("meshes", "solids", "parts")

_MISSING_GEOMETRY = (
    "no solid geometry in the projection: looked for ctx.extra['meshes'] and params "
    "'meshes' / 'solids' / 'parts', each a {name: path-or-mesh} map (or a list of "
    "paths). Export the placed parts from the model and put the map in the "
    "projection — this gate will not guess a filename"
)


# --------------------------------------------------------------------------- #
# shared plumbing
# --------------------------------------------------------------------------- #
def _skipped(gate_id: str, reason: str) -> Verdict:
    """A gate that could not measure says so. It never returns a pass."""
    return Verdict(gate=gate_id, passed=False, skipped=True, skip_reason=reason)


def _mesh_sources(ctx: GateContext) -> tuple[dict[str, Any] | None, str]:
    """``({name: source}, where)`` or ``(None, reason)``.

    ``ctx.extra`` is consulted first so a negative-control fixture can hand a gate
    known-bad geometry without touching the projection. Then the projection, under
    any of three spellings, because a model that calls them ``solids`` is not wrong.
    """
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    for key in _MESH_KEYS:
        value = extra.get(key)
        if isinstance(value, dict) and value:
            return dict(value), f"ctx.extra[{key!r}]"
    for key in _MESH_KEYS:
        value = ctx.param(key)
        if isinstance(value, dict) and value:
            return dict(value), f"params[{key!r}]"
        if isinstance(value, (list, tuple)) and value:
            named = {}
            for i, item in enumerate(value):
                stem = os.path.splitext(os.path.basename(str(item)))[0] or f"part{i}"
                named[stem] = item
            return named, f"params[{key!r}]"
    return None, _MISSING_GEOMETRY


def _load_one(source: Any, root: str) -> tuple[Any, bool]:
    """``(mesh, welded_on_load)``. Accepts an in-memory mesh or a path.

    ``process=False`` is not an optimisation. The default load pipeline welds
    vertices and drops degenerate faces on the way in — it would repair, silently
    and in memory, the exact defects ``cad.degenerate_faces`` exists to report, and
    the gate would then certify a file that no other program will read the same way.
    Validate the bytes you are going to send.

    The exception is a **soup format**. An STL file is a bag of independent
    triangles with no vertex identity whatsoever: every corner is written three to
    six times and the topology exists only once somebody decides which corners are
    the same point. Loading one unprocessed and then counting duplicate vertices
    would report every STL ever exported as catastrophically defective, which is a
    true statement about the format and a useless one about the part. So a soup
    format is welded ONCE at the weld tolerance on load, that weld is recorded, and
    the gates say so in their verdicts — because the welded mesh is an
    interpretation of the file, not the file.
    """
    if hasattr(source, "faces") and hasattr(source, "vertices"):
        return source, False

    import trimesh

    path = str(source)
    if not os.path.isabs(path) and root:
        path = os.path.join(root, path)
    if not os.path.isfile(path):
        raise FileNotFoundError(path)
    loaded = trimesh.load_mesh(path, process=False)
    if hasattr(loaded, "geometry") and not hasattr(loaded, "faces"):   # a Scene
        parts = list(loaded.geometry.values())
        if not parts:
            raise ValueError(f"{path} contains no geometry")
        loaded = parts[0] if len(parts) == 1 else trimesh.util.concatenate(parts)

    if path.lower().endswith(SOUP_SUFFIXES):
        digits = max(0, int(round(-math.log10(WELD_TOL_MM))))
        try:
            loaded.merge_vertices(digits_vertex=digits)
        except TypeError:                              # older trimesh signature
            loaded.merge_vertices()
        return loaded, True
    return loaded, False


def _load_all(ctx: GateContext, gate_id: str):
    """``(meshes, welded_on_load, skip)``. Never invents geometry.

    ``welded_on_load`` names the parts that arrived in a soup format and were welded
    to give them a topology at all. Gates that report topology carry that fact into
    their detail line: a reader has to be able to tell a measurement of the file from
    a measurement of an interpretation of the file.
    """
    sources, where = _mesh_sources(ctx)
    if sources is None:
        return None, (), _skipped(gate_id, where)
    meshes: dict[str, Any] = {}
    welded: list[str] = []
    for name in sorted(sources, key=str):
        try:
            mesh, was_welded = _load_one(sources[name], ctx.root or "")
        except Exception as exc:                       # noqa: BLE001 - user data
            return None, (), _skipped(
                gate_id,
                f"part {name!r} from {where} could not be read "
                f"({type(exc).__name__}: {exc}) — nothing was measured",
            )
        meshes[str(name)] = mesh
        if was_welded:
            welded.append(str(name))
    if not meshes:
        return None, (), _skipped(gate_id, _MISSING_GEOMETRY)
    return meshes, tuple(welded), None


def _welded_note(welded) -> str:
    """One clause naming the interpretation, or nothing."""
    if not welded:
        return ""
    return (f"; {len(welded)} part(s) welded at {WELD_TOL_MM:g} mm on load "
            f"({', '.join(sorted(welded)[:3])}{'...' if len(welded) > 3 else ''}) — "
            f"a soup format has no vertex identity of its own")


def _edge_counts(mesh: Any) -> tuple[int, int, int]:
    """``(open_edges, nonmanifold_edges, n_faces)`` computed from the face table.

    Deliberately computed here with numpy rather than read off a trimesh property.
    The numbers have to survive a version bump, and "how many edges are used once"
    is four lines of arithmetic that cannot quietly change meaning under us.
    """
    import numpy as np

    faces = np.asarray(mesh.faces)
    if faces.size == 0:
        return 0, 0, 0
    edges = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
    edges = np.sort(edges, axis=1)
    _, counts = np.unique(edges, axis=0, return_counts=True)
    return int((counts == 1).sum()), int((counts > 2).sum()), int(len(faces))


def _write(ctx: GateContext, filename: str, payload: Any) -> str:
    """Bulk output to out_dir, returned as a path for ``Verdict.evidence``."""
    path = ctx.out_path("cad-solid", filename)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True, default=str)
    return path


# --------------------------------------------------------------------------- #
# tier 0 — arithmetic on the projection, runs with no mesh library at all
# --------------------------------------------------------------------------- #
def _as_triple(value: Any, allow_scalar: bool = False) -> list[float] | None:
    """``[x, y, z]`` from a 3-list, or from a scalar ONLY where that is meaningful.

    ``allow_scalar`` is true for a LIMIT, where "the same in every axis" is a real
    envelope — a 40 mm cube of clearance is a sentence somebody means. It is false
    for every MEASUREMENT (``bbox_mm``, ``com_mm``, ``com_target_mm``), where one
    number in place of three is not a compact spelling, it is two missing axes: a
    projection that writes ``bbox_mm: 96`` would otherwise get a confident PASS on
    a Y and Z this gate invented. A gate that refuses to guess a filename must not
    guess two thirds of a bounding box.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return [float(value)] * 3 if allow_scalar else None
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            return [float(v) for v in value]
        except (TypeError, ValueError):
            return None
    return None


def _triple_problem(name: str, value: Any, allow_scalar: bool) -> str:
    """Why a triple was rejected, named precisely enough to fix in one edit."""
    if value is None:
        return f"{name} is absent"
    if isinstance(value, (int, float)) and not isinstance(value, bool) and not allow_scalar:
        return (f"{name} is the single number {value!r}; it is a measurement, so it "
                f"needs all three axes [X, Y, Z] — this gate will not expand it to a cube")
    return f"{name} is {type(value).__name__} {value!r}, not a 3-list of mm"


@gate(
    id="cad.bounding",
    title="Bounding box, volume and centre of mass within their stated limits",
    claims=["geometry", "envelope", "packaging", "mechanical", "cad"],
    tier=Tier.INSTANT,
    settles="bounding box",
    negative_control=NegativeControl(
        fixture="selftest/bad_bounds.py:tall_part",
        note="the same part 15% past its stated Z envelope, taken from the "
             "projection's own limit; every other number is untouched, so only the "
             "height check trips",
    ),
)
def bounding(ctx: GateContext) -> Verdict:
    """Envelope arithmetic: does the part fit where it has to live, and balance there?

    This is the pack's tier-0 gate and the only one that runs without a mesh library.
    It checks the model's OWN numbers against the model's OWN limits — it does not
    open the geometry, so it cannot tell you that ``bbox_mm`` still matches the mesh
    that was exported. That agreement is a separate claim and needs a separate gate.

    Three sub-checks, reported as the worst utilisation of the three. Volume and
    centre of mass are optional and are named as unchecked in the detail line when
    the projection does not carry them; the bounding box is not optional, because a
    gate with nothing at all to compare would be a logger.
    """
    raw_bbox = ctx.param("bbox_mm")
    raw_limit = ctx.param("bbox_limit_mm")
    bbox = _as_triple(raw_bbox)
    limit = _as_triple(raw_limit, allow_scalar=True)
    if bbox is None or limit is None:
        problems = [_triple_problem(n, v, s) for n, v, s, ok in
                    (("bbox_mm", raw_bbox, False, bbox), ("bbox_limit_mm", raw_limit, True, limit))
                    if ok is None]
        return _skipped(
            "cad.bounding",
            f"{'; '.join(problems)} — nothing to compare, so nothing is claimed",
        )

    axes = ("X", "Y", "Z")
    ratios = [(b / l if l else math.inf, a, b, l) for a, b, l in zip(axes, bbox, limit)]
    worst_ratio, worst_axis, worst_val, worst_lim = max(ratios, key=lambda r: r[0])
    parts = [
        f"bbox {bbox[0]:.2f}x{bbox[1]:.2f}x{bbox[2]:.2f} vs "
        f"{limit[0]:.2f}x{limit[1]:.2f}x{limit[2]:.2f} mm "
        f"(worst {worst_axis} {worst_val:.2f}/{worst_lim:.2f} = {worst_ratio * 100:.0f}%)"
    ]
    worst = worst_ratio

    volume = ctx.param("volume_mm3")
    volume_limit = ctx.param("volume_limit_mm3")
    if isinstance(volume, (int, float)) and isinstance(volume_limit, (int, float)) and volume_limit:
        ratio = float(volume) / float(volume_limit)
        worst = max(worst, ratio)
        parts.append(f"vol {float(volume):.0f}/{float(volume_limit):.0f} mm^3 ({ratio * 100:.0f}%)")
    else:
        parts.append("vol not checked (volume_mm3/volume_limit_mm3 absent)")

    raw_com = ctx.param("com_mm")
    raw_target = ctx.param("com_target_mm")
    com = _as_triple(raw_com)
    com_target = _as_triple(raw_target)
    com_tol = ctx.param("com_tol_mm")
    if com and com_target and isinstance(com_tol, (int, float)) and com_tol:
        offset = math.dist(com, com_target)
        ratio = offset / float(com_tol)
        worst = max(worst, ratio)
        parts.append(f"com {offset:.2f}/{float(com_tol):.2f} mm off target ({ratio * 100:.0f}%)")
    elif (raw_com is not None and com is None) or (raw_target is not None and com_target is None):
        # Present but unusable is not the same as absent, and reporting it as
        # "not checked" would let a malformed centre of mass pass unremarked.
        bad = [_triple_problem(n, v, False) for n, v, ok in
               (("com_mm", raw_com, com), ("com_target_mm", raw_target, com_target))
               if v is not None and ok is None]
        parts.append(f"com NOT checked — {'; '.join(bad)}")
    else:
        parts.append("com not checked (com_mm/com_target_mm/com_tol_mm absent)")

    return Verdict(
        gate="cad.bounding",
        passed=worst <= 1.0,
        measured=round(worst, 4),
        limit=1.0,
        units="utilisation",
        detail="; ".join(parts),
    )


# --------------------------------------------------------------------------- #
# tier 1 — mesh validity. Run these before anything trusts the geometry.
# --------------------------------------------------------------------------- #
@gate(
    id="cad.watertight",
    title="Every solid is closed: no open edges, no non-manifold edges",
    claims=["geometry", "mesh", "cad", "manufacturability"],
    tier=Tier.BUILD,
    settles="mesh watertightness",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:holed_box",
        note="a box with the two triangles of its +Z facet deleted: 4 open edges, "
             "winding and every other facet untouched",
    ),
)
def watertight(ctx: GateContext) -> Verdict:
    """Closure, gated before anything downstream trusts the mesh.

    A surface with a hole in it is not a solid, and the damage is not confined to
    this check. A boolean intersection against a leaking mesh can return an empty
    result without raising, which reads downstream as "this part collides with
    nothing" — the most dangerous possible false negative, because it is the answer
    everyone wanted. Run this first and treat a failure here as poisoning every
    later verdict on the same part.

    Measures open edges (used by exactly one face) plus non-manifold edges (used by
    three or more). Both are zero on a solid; the two are reported separately
    because they have different causes — a hole versus a self-intersecting or
    doubled surface — and different fixes.
    """
    meshes, welded, skip = _load_all(ctx, "cad.watertight")
    if skip is not None:
        return skip

    rows = []
    total = 0
    for name, mesh in meshes.items():
        open_edges, nonmanifold, n_faces = _edge_counts(mesh)
        total += open_edges + nonmanifold
        rows.append({
            "part": name, "faces": n_faces, "open_edges": open_edges,
            "nonmanifold_edges": nonmanifold,
            "trimesh_is_watertight": bool(getattr(mesh, "is_watertight", False)),
        })

    worst = max(rows, key=lambda r: r["open_edges"] + r["nonmanifold_edges"])
    evidence = [_write(ctx, "watertight.json", rows)] if total else []
    return Verdict(
        gate="cad.watertight",
        passed=total == 0,
        measured=float(total),
        limit=0.0,
        units="edges",
        detail=f"{total} bad edge(s) across {len(rows)} part(s), limit 0 — worst "
               f"{worst['part']}: {worst['open_edges']} open, "
               f"{worst['nonmanifold_edges']} non-manifold of {worst['faces']} faces"
               + _welded_note(welded),
        evidence=evidence,
    )


@gate(
    id="cad.is_volume",
    title="Every solid is a volume: closed, consistently wound, positive volume",
    claims=["geometry", "mesh", "cad", "manufacturability"],
    tier=Tier.BUILD,
    settles="solid validity",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:flipped_facet",
        note="a closed box with one triangle's winding reversed: still watertight, "
             "no longer a volume — the case cad.watertight cannot see",
    ),
)
def is_volume(ctx: GateContext) -> Verdict:
    """Closed AND consistently wound AND enclosing a positive volume.

    Watertightness is necessary and not sufficient. A mesh can be perfectly closed
    with one facet wound backwards; nothing about its edges gives it away, and it
    cannot be booleaned at all — depending on the kernel it raises, returns garbage,
    or returns a signed volume of the wrong sign. Reported per part with the
    property that actually failed, because "not a volume" alone sends people
    re-exporting a file whose real problem was a mirrored transform.
    """
    meshes, welded, skip = _load_all(ctx, "cad.is_volume")
    if skip is not None:
        return skip

    rows = []
    bad = 0
    for name, mesh in meshes.items():
        closed = bool(getattr(mesh, "is_watertight", False))
        wound = bool(getattr(mesh, "is_winding_consistent", False))
        try:
            volume = float(mesh.volume)
        except Exception as exc:                       # noqa: BLE001 - kernel
            volume = float("nan")
            wound = wound and False
            ctx.log(f"cad.is_volume: {name} volume raised {type(exc).__name__}")
        ok = bool(getattr(mesh, "is_volume", False)) and math.isfinite(volume) and volume > 0.0
        if not ok:
            bad += 1
        reasons = []
        if not closed:
            reasons.append("not closed")
        if not wound:
            reasons.append("winding inconsistent")
        if not math.isfinite(volume):
            reasons.append("volume is not finite")
        elif volume <= 0.0:
            reasons.append(f"volume {volume:.3f} <= 0 (inside-out)")
        rows.append({"part": name, "is_volume": ok, "watertight": closed,
                     "winding_consistent": wound, "volume_mm3": volume,
                     "why": ", ".join(reasons) or "ok"})

    first_bad = next((r for r in rows if not r["is_volume"]), None)
    evidence = [_write(ctx, "is_volume.json", rows)] if bad else []
    detail = f"{bad} of {len(rows)} part(s) are not volumes, limit 0"
    if first_bad:
        detail += f" — {first_bad['part']}: {first_bad['why']}"
    else:
        detail += f" (total {sum(r['volume_mm3'] for r in rows):.0f} mm^3 enclosed)"
    detail += _welded_note(welded)
    return Verdict(
        gate="cad.is_volume",
        passed=bad == 0,
        measured=float(bad),
        limit=0.0,
        units="parts",
        detail=detail,
        evidence=evidence,
    )


def _drop_unreferenced(mesh: Any) -> None:
    """Remove vertices no face points at, in place. Best-effort across versions."""
    remove = getattr(mesh, "remove_unreferenced_vertices", None)
    if callable(remove):
        remove()


def _weld_and_drop(mesh: Any, digits: int, area_eps: float, max_passes: int = 8) -> tuple[int, int, int]:
    """Alternate welding and dropping until neither does anything.

    ``(welded_vertices, dropped_faces, passes)`` on a COPY; the caller's mesh is
    never mutated.

    The alternation is the whole point and the order matters. A sliver straddles a
    pair of duplicated vertices: before the weld it has a small but genuinely
    non-zero area and survives an area test; after the weld its two endpoints are
    one vertex and its area is exactly zero. Drop-then-weld finds nothing and
    reports a clean part. Weld-then-drop finds it — and then the drop can expose a
    further duplicate, which is why this loops rather than running once.

    UNREFERENCED vertices are cleared before every measurement, and that is not
    tidiness. ``merge_vertices`` also discards any vertex the previous pass's
    ``update_faces`` left pointing at nothing, so a raw vertex-count delta counts
    those as welds and the verdict then states a repair the mesh never needed:
    pass/fail is unchanged (still non-zero when non-zero) but the number a reader
    is supposed to act on is inflated. Clearing them first makes the delta mean
    only "duplicates merged".
    """
    import numpy as np

    work = mesh.copy()
    _drop_unreferenced(work)
    welded = dropped = passes = 0
    for _ in range(max_passes):
        before = len(work.vertices)
        try:
            work.merge_vertices(digits_vertex=digits)
        except TypeError:                              # older trimesh signature
            work.merge_vertices()
        this_weld = before - len(work.vertices)

        areas = np.asarray(work.area_faces, dtype=float)
        keep = areas > area_eps
        this_drop = int((~keep).sum())
        if this_drop:
            work.update_faces(keep)
            _drop_unreferenced(work)

        welded += this_weld
        dropped += this_drop
        passes += 1
        if this_weld == 0 and this_drop == 0:
            break
    return welded, dropped, passes


@gate(
    id="cad.degenerate_faces",
    title="No duplicate vertices and no zero-area triangles",
    claims=["geometry", "mesh", "cad", "manufacturability"],
    tier=Tier.BUILD,
    settles="degenerate faces",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:sliver_pair",
        note="one corner of a closed box emitted twice 1e-6 mm apart with a subset "
             "of its faces repointed at the copy: adjacency splits on a surface "
             "that is still geometrically closed, and the face spanning the two "
             "copies has non-zero area until the weld and exactly zero after it",
    ),
)
def degenerate_faces(ctx: GateContext) -> Verdict:
    """Weld duplicates at the weld tolerance, then drop zero-area faces, and repeat.

    A mesh can be geometrically closed and topologically open at the same time, on a
    part the CAD kernel calls valid: the tessellator emitted the rim vertex twice,
    so the two triangles either side of it are not neighbours even though they touch
    everywhere. Every downstream algorithm that walks adjacency — thickness, offset,
    slicing, boolean — then works on a surface with a seam through it.

    The measurement is the number of repairs this gate would have to make. Zero
    repairs is the only pass; anything above zero means the file on disk is not the
    file the kernel thinks it wrote, and it is reported without repairing anything,
    because a gate that silently fixes its input has removed the evidence.
    """
    meshes, welded, skip = _load_all(ctx, "cad.degenerate_faces")
    if skip is not None:
        return skip

    digits = max(0, int(round(-math.log10(WELD_TOL_MM))))
    rows = []
    total = 0
    for name, mesh in meshes.items():
        # NOT `welded`: that name already holds the parts welded on load, and
        # shadowing it here silently turns the verdict's own note into a crash.
        welds, drops, passes = _weld_and_drop(mesh, digits, ZERO_AREA_MM2)
        total += welds + drops
        rows.append({"part": name, "welded_vertices": welds, "dropped_faces": drops,
                     "passes": passes, "faces": int(len(mesh.faces))})

    worst = max(rows, key=lambda r: r["welded_vertices"] + r["dropped_faces"])
    evidence = [_write(ctx, "degenerate_faces.json", rows)] if total else []
    return Verdict(
        gate="cad.degenerate_faces",
        passed=total == 0,
        measured=float(total),
        limit=0.0,
        units="repairs",
        detail=f"{total} repair(s) needed across {len(rows)} part(s), limit 0 — worst "
               f"{worst['part']}: welded {worst['welded_vertices']} vertex/vertices at "
               f"{WELD_TOL_MM:g} mm, dropped {worst['dropped_faces']} face(s) below "
               f"{ZERO_AREA_MM2:g} mm^2 over {worst['passes']} pass(es)"
               + _welded_note(welded),
        evidence=evidence,
    )


# --------------------------------------------------------------------------- #
# tier 1 — measurements that are only meaningful on a valid solid
# --------------------------------------------------------------------------- #

#: Rays cast per numpy chunk, as a ray-times-triangle product. The fallback caster
#: below builds a (rays x triangles x 3) array, so the chunk size has to be set on
#: that product rather than on a ray count: 4000 rays against a 12-triangle box and
#: 4000 rays against a 200k-triangle casting are four orders of magnitude apart in
#: memory and identical in ray count. 2e6 keeps a chunk around 50 MB in float64.
_CAST_CHUNK_RT = 2_000_000

#: Parallel-ray cutoff for the fallback caster, as a COSINE. With a unit direction,
#: Moller-Trumbore's determinant is ``e1 . (d x e2)`` = 2*area*cos(ray, facet
#: normal): units of LENGTH^2, magnitude set by the FACET, never by the assembly.
#: Dividing it by the triangle's own 2*area leaves a dimensionless cosine, so the
#: test "is this ray edge-on to this triangle" means the same thing on a 1 mm part
#: and a 10 m one and cannot be moved by anything else in the file.
#:
#: REJECTED, and this is the whole reason the constant is written this way: a cutoff
#: scaled off ``mesh.scale`` (the bounding diagonal). ``1e-12 * scale**3`` is
#: dimensionally a volume being compared to an area — it grows as the cube of the
#: part's overall span while the quantity it gates stays fixed by facet size, so on
#: a large assembly with ordinary facets every triangle is classified "parallel",
#: every ray misses, and the gate SKIPS for a reason that has nothing to do with the
#: mesh. ``1e-12 * scale**2`` is dimensionally right and still wrong in kind: one
#: number derived from the assembly's diagonal cannot be correct for both the
#: largest and the smallest facet on the same mesh.
#:
#: 1e-12 is chosen as a cosine that no real geometry reaches: a facet that far
#: edge-on contributes a hit whose barycentric coordinates are pure float64 noise,
#: and a genuinely grazing surface is found by its neighbours, which are not.
_PARALLEL_COS_EPS = 1e-12


def _cast_first_hit(mesh: Any, origins: Any, directions: Any) -> tuple[Any, Any]:
    """``(locations, index_ray)`` of each ray's first forward hit.

    trimesh's own ray engines are used when one of them is importable. Neither is
    guaranteed: the pure-python engine culls candidates with an ``rtree`` index and
    the fast one needs an embree binding, and NEITHER is a dependency of trimesh.
    On a machine with just trimesh and numpy — exactly what this gate declares in
    ``requires_python`` — ``mesh.ray`` raises ``ModuleNotFoundError`` from inside the
    property, which reaches the spine as a CRASHED gate. A crash settles nothing and
    reads as "the design is wrong" rather than "the tool is missing", so the gate has
    to be able to do this itself with what it declared.

    The fallback is Möller-Trumbore, vectorised over triangles and chunked over
    rays: the same intersection test the engines implement, brute-forced over the
    whole face list instead of culled by a spatial index, which is why the
    accelerated engine is still preferred when it is present.

    The honest statement of how far that equivalence goes: the two paths agree to
    floating-point round-off on the hits they both find, and neither is an
    approximation of the other's geometry — but they are two implementations with
    two sets of edge-case rules (grazing facets, coincident surfaces, a ray that
    starts exactly on a face), so which one ran is a fact about the machine and
    ``selftest/check_ray_cast.py`` exists to keep the difference measured rather
    than assumed. Do not read "fallback" as "degraded"; read it as "the other one".
    """
    import numpy as np

    origins = np.asarray(origins, dtype=float)
    directions = np.asarray(directions, dtype=float)
    try:
        locations, index_ray, _ = mesh.ray.intersects_location(
            origins, directions, multiple_hits=False)
        return np.asarray(locations, dtype=float), np.asarray(index_ray, dtype=int)
    except ImportError:
        pass

    tri = np.asarray(mesh.triangles, dtype=float)
    if len(tri) == 0 or len(origins) == 0:
        return np.zeros((0, 3)), np.zeros(0, dtype=int)
    v0 = tri[:, 0, :]
    e1 = tri[:, 1, :] - v0
    e2 = tri[:, 2, :] - v0

    # Per-triangle parallel cutoff: |det| against this triangle's own 2*area makes
    # the test a cosine (see _PARALLEL_COS_EPS). Computed from e1/e2 rather than
    # read off `mesh.area_faces` so it is the same arithmetic, in the same order,
    # as the determinant it gates. A genuinely zero-area triangle gets a cutoff of
    # zero — and a determinant of zero — so `>` excludes it, which is correct: a
    # triangle with no area has no interior to hit.
    two_area = np.linalg.norm(np.cross(e1, e2), axis=1)
    det_eps = _PARALLEL_COS_EPS * two_area

    chunk = max(1, int(_CAST_CHUNK_RT // max(1, len(tri))))
    best = np.full(len(origins), np.inf)
    for start in range(0, len(origins), chunk):
        o = origins[start:start + chunk]
        d = directions[start:start + chunk]
        pvec = np.cross(d[:, None, :], e2[None, :, :])
        det = np.einsum("fj,rfj->rf", e1, pvec)
        live = np.abs(det) > det_eps[None, :]
        inv = np.where(live, 1.0 / np.where(live, det, 1.0), 0.0)
        tvec = o[:, None, :] - v0[None, :, :]
        u = np.einsum("rfj,rfj->rf", tvec, pvec) * inv
        qvec = np.cross(tvec, e1[None, :, :])
        v = np.einsum("rj,rfj->rf", d, qvec) * inv
        t = np.einsum("fj,rfj->rf", e2, qvec) * inv
        hit = live & (u >= 0.0) & (v >= 0.0) & (u + v <= 1.0) & (t > 0.0)
        best[start:start + chunk] = np.where(hit, t, np.inf).min(axis=1)

    index_ray = np.nonzero(np.isfinite(best))[0]
    locations = origins[index_ray] + directions[index_ray] * best[index_ray][:, None]
    return locations, index_ray


@gate(
    id="cad.wall_thickness",
    title="Thinnest wall found by inward ray casting, against the minimum",
    claims=["geometry", "mesh", "cad", "manufacturability", "wall"],
    tier=Tier.BUILD,
    settles="minimum wall thickness",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:thin_plate",
        note="a plate at a quarter of the project's own minimum wall; the same "
             "footprint, watertight, a valid volume, and too thin",
    ),
)
def wall_thickness(ctx: GateContext) -> Verdict:
    """Minimum wall by casting a ray inward from each facet along its own normal.

    Method, stated plainly because its limits matter more than its number: from the
    centroid of each facet — an evenly spaced, deterministic subset of exactly the
    ray budget once the face count exceeds it — a ray is cast along the inward
    normal and the distance to the first hit is the local thickness. The minimum
    over all samples is reported.

    What this does NOT measure, and nobody should assume it does:

    * It is a LOWER-BOUND SAMPLER, not a proof. It sees thickness only where a facet
      exists and only along that facet's normal. A thin region whose thinnest
      direction is not normal to any sampled facet is missed.
    * On a coarsely tessellated curved wall it UNDER-reports, by roughly
      ``t*(1 - cos(pi/N))`` for a wall of thickness ``t`` across an N-sided
      tessellation of the curve. The chord sits inside the true surface, so a ray
      leaving one chord and landing on the other crosses ``t*cos(pi/N)``, not ``t``.
      The error is conservative — false alarms, never false passes — but it is a
      real number: 16 facets around a curve cost 1.9% of the wall, 8 cost 7.6%.
      (An over-reporting regime exists and is a different mechanism: on an
      IRREGULAR tessellation a facet normal need not point at the opposing surface
      at all, and an oblique ray travels further than the wall is thick. Do not
      conflate the two — the chord effect is systematic and one-signed, the
      obliquity effect is not.)
    * It measures material, not clearance. A ray crossing an internal cavity reports
      the wall on this side and says nothing about the rib beyond it.
    * On an open or non-manifold mesh it is meaningless, so the gate refuses to run
      rather than returning a number — see ``cad.watertight``.

    For a proof rather than a sample, the domain tool is a medial-axis or
    sphere-inscription analysis; ``references/mesh_hygiene.md`` says what that costs.
    """
    limit = ctx.param("min_wall_mm")
    if not isinstance(limit, (int, float)) or isinstance(limit, bool) or limit <= 0:
        return _skipped(
            "cad.wall_thickness",
            "the projection does not define 'min_wall_mm' (a positive number, mm) — "
            "the minimum wall is a process decision the model must carry, and this "
            "gate will not invent one",
        )
    limit = float(limit)

    meshes, welded, skip = _load_all(ctx, "cad.wall_thickness")
    if skip is not None:
        return skip

    import numpy as np

    # `int(ctx.param(...) or MAX)` swallowed an explicit 0 and turned it into 4000,
    # so a projection asking for no sampling silently got the full budget. A ray
    # budget is a number the model states on purpose; an unusable one is a defect
    # in the projection, not something to paper over with a default.
    raw_budget = ctx.param("wall_samples")
    if raw_budget is None:
        budget = MAX_WALL_SAMPLES
    else:
        try:
            budget = int(raw_budget)
        except (TypeError, ValueError):
            budget = 0
        if budget <= 0:
            return _skipped(
                "cad.wall_thickness",
                f"'wall_samples' is {raw_budget!r}; it must be a positive integer "
                f"number of rays (omit it for the default {MAX_WALL_SAMPLES}) — a "
                f"budget of zero would measure nothing and report a pass",
            )
    rows = []
    worst_value = math.inf
    worst_part = ""
    worst_point: list[float] = []
    for name, mesh in meshes.items():
        if not bool(getattr(mesh, "is_watertight", False)):
            return _skipped(
                "cad.wall_thickness",
                f"part {name!r} is not watertight, so a ray cast from inside it can "
                f"escape and thickness is undefined — settle cad.watertight first",
            )

        centres = np.asarray(mesh.triangles_center, dtype=float)
        normals = np.asarray(mesh.face_normals, dtype=float)
        n_faces = len(centres)
        # Honour the budget exactly. `stride = n_faces // budget` gives stride 1 for
        # any face count below 2x the budget, so the real ceiling was about twice
        # the number the constant promises and the gate's cost was not the cost it
        # declared. An evenly spaced index of exactly min(n_faces, budget) samples
        # is deterministic in the same way a stride is, and is the stated budget.
        n_rays = min(n_faces, budget)
        idx = np.unique(np.linspace(0, n_faces - 1, n_rays).round().astype(int))
        eps = max(1e-6, float(getattr(mesh, "scale", 1.0)) * 1e-8)
        origins = centres[idx] - normals[idx] * eps
        directions = -normals[idx]

        locations, index_ray = _cast_first_hit(mesh, origins, directions)
        if len(index_ray) == 0:
            return _skipped(
                "cad.wall_thickness",
                f"no inward ray hit anything on part {name!r} ({len(idx)} rays) — the "
                f"ray engine returned nothing, so no thickness was measured",
            )
        # The ray origin is pushed eps ALONG THE INWARD direction, i.e. eps below
        # the surface it starts from (trimesh face normals point outward and the
        # origin is centre - normal*eps). The wall runs surface to surface, so the
        # thickness is eps + |hit - origin|: the correction ADDS back the sliver the
        # offset skipped. Subtracting it biased every reading low by 2*eps —
        # invisible at eps = 1e-6 mm on a mm-scale part, and the same order as the
        # tolerance being arbitrated once eps tracks mesh.scale on a metre-scale
        # assembly.
        travel = np.linalg.norm(
            np.asarray(locations, dtype=float) - origins[index_ray], axis=1)
        real = travel > 10.0 * eps
        if not real.any():
            return _skipped(
                "cad.wall_thickness",
                f"every inward ray on part {name!r} hit its own facet — the sampler "
                f"measured nothing",
            )
        distances = travel[real] + eps
        hit_rows = np.asarray(index_ray)[real]
        local_min = float(distances.min())
        where = origins[hit_rows[int(distances.argmin())]]
        rows.append({"part": name, "min_mm": local_min, "rays": int(len(idx)),
                     "hits": int(len(distances)), "faces": int(n_faces),
                     "at_mm": [round(float(c), 3) for c in where]})
        if local_min < worst_value:
            worst_value = local_min
            worst_part = name
            worst_point = [round(float(c), 3) for c in where]

    evidence = [_write(ctx, "wall_thickness.json", rows)]
    sampled = sum(r["hits"] for r in rows)
    cast = sum(r["rays"] for r in rows)
    return Verdict(
        gate="cad.wall_thickness",
        passed=worst_value >= limit,
        measured=round(worst_value, 4),
        limit=round(limit, 4),
        units="mm",
        detail=f"thinnest wall {worst_value:.3f} mm on {worst_part} at "
               f"({', '.join(f'{c:g}' for c in worst_point)}) vs {limit:.3f} mm minimum "
               f"({sampled}/{cast} inward face-normal rays hit; sampler, not a proof)",
        evidence=evidence,
    )


# --------------------------------------------------------------------------- #
# tier 1 — interference
# --------------------------------------------------------------------------- #
#: The back-ends trimesh can dispatch a boolean to, as (probe, human name). trimesh
#: does not implement booleans itself and declares NONE of these as a dependency, so
#: `pip install trimesh numpy` — exactly what this gate's requires_python states —
#: leaves ``trimesh.boolean.intersection`` raising from inside the call.
_BOOLEAN_ENGINES = (
    ("manifold3d", "manifold3d (pip install manifold3d)"),
    ("blender", "a headless Blender on PATH"),
    ("openscad", "OpenSCAD on PATH"),
)


def _boolean_engines() -> list[str]:
    """Human names of the boolean back-ends actually usable on this machine.

    This cannot be expressed as ``requires_python`` or ``requires_tools``: the gate
    needs ANY ONE of three unrelated things, and the availability mechanism ands
    its requirements together. So the disjunction is probed here, once, before the
    pair loop — and an empty result is a SKIP, never a verdict about the design.
    Probed and not imported where possible: the answer has to be obtainable on the
    machine where the answer is "none of them".
    """
    found: list[str] = []
    try:
        import importlib.util
        if importlib.util.find_spec("manifold3d") is not None:
            found.append(_BOOLEAN_ENGINES[0][1])
    except Exception:                                  # noqa: BLE001 - third-party import side effects
        pass
    try:
        import trimesh.interfaces as interfaces
        for attr, name in (("blender", _BOOLEAN_ENGINES[1][1]),
                           ("scad", _BOOLEAN_ENGINES[2][1])):
            iface = getattr(interfaces, attr, None)
            if iface is not None and bool(getattr(iface, "exists", False)):
                found.append(name)
    except Exception:                                  # noqa: BLE001 - third-party import side effects
        pass
    return found


def _pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _normalise_pair(entry: Any) -> tuple[str, str] | None:
    if isinstance(entry, dict):
        entry = entry.get("pair") or entry.get("parts")
    if isinstance(entry, str):
        for sep in ("|", ",", "/"):
            if sep in entry:
                bits = [p.strip() for p in entry.split(sep, 1)]
                return _pair_key(bits[0], bits[1])
        return None
    if isinstance(entry, (list, tuple)) and len(entry) == 2:
        return _pair_key(str(entry[0]).strip(), str(entry[1]).strip())
    return None


def _read_allowlist(ctx: GateContext, sliding: set[tuple[str, str]]) -> tuple[dict, list[str]]:
    """``(allowed, refusals)``. An entry this function refuses is a gate FAILURE.

    Three refusals, all of them earned the expensive way:

    * **no reason.** An allowlist entry without a stated reason is an unexplained
      permission to interfere, and nobody will ever dare delete it.
    * **a blanket entry** — ``"bracket vs anything"``, a ``"*"`` on either side.
      This is the single most effective way to hide real interference: one line
      switches the check off for a part and the report stays green forever.
    * **a sliding fit.** The pair whose whole job is to move relative to the other
      is the pair that most needs the check. An intended CONTACT is allowlistable;
      an intended MOTION is not, because "they touch" and "they jam" look identical
      to a boolean at one pose.
    """
    raw = ctx.param("clash_allow") or []
    if isinstance(raw, dict):
        raw = [dict(v or {}, pair=k) for k, v in raw.items()]
    allowed: dict[tuple[str, str], str] = {}
    refusals: list[str] = []
    for entry in raw if isinstance(raw, (list, tuple)) else []:
        reason = str((entry or {}).get("reason", "")).strip() if isinstance(entry, dict) else ""
        pair = _normalise_pair(entry)
        text = json.dumps(entry, default=str)[:80]
        if pair is None:
            refusals.append(f"unreadable allowlist entry {text}")
            continue
        if any(p in ("*", "any", "anything", "") for p in pair):
            refusals.append(
                f"blanket allowlist entry {pair[0]!r} vs {pair[1]!r} refused — a wildcard "
                f"switches interference checking off for a part and the report stays green")
            continue
        if not reason:
            refusals.append(f"allowlist entry {pair[0]!r} vs {pair[1]!r} has no reason")
            continue
        if pair in sliding:
            refusals.append(
                f"allowlist entry {pair[0]!r} vs {pair[1]!r} refused: declared a sliding "
                f"fit, and a pair that must MOVE is the pair that most needs this check")
            continue
        allowed[pair] = reason
    return allowed, refusals


@gate(
    id="cad.clash",
    title="No unintended interference between placed solids",
    claims=["geometry", "fit", "assembly", "interference", "mechanical", "cad"],
    tier=Tier.BUILD,
    settles="part interference",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/bad_meshes.py:overlapping_pair",
        note="two valid 20 mm boxes placed 18 mm apart: 800 mm^3 of shared material, "
             "nothing else about either part changed and no allowlist entry",
    ),
)
def clash(ctx: GateContext) -> Verdict:
    """Pairwise intersection volume, AABB pre-filtered, with a per-pair tolerance.

    The meshes must already be placed in the ASSEMBLY frame. Parts booleaned at
    their own local origins either all clash or none do, and both answers are
    confident nonsense — see PACK.md, "units and frames".

    Two numbers per pair, and both must be under tolerance. The intersection VOLUME
    is the measure — it goes to zero continuously as parts separate, which is what
    lets a tolerance absorb tessellation noise. But a fixed volume tolerance
    forgives an unbounded penetration DEPTH as the contact area shrinks (0.2 mm^3
    is a 0.5 mm pin driven 0.79 mm into a block), so the equivalent depth —
    volume over the largest face of the two parts' overlapping bounding boxes — is
    checked against its own tolerance as well. That depth is a LOWER bound on the
    real penetration: a pair that fails it is at least that far in.

    A boolean that raises ON A MACHINE THAT HAS AN ENGINE, or returns a negative or
    non-finite volume, is counted as a CLASH. That is not defensive coding, it is
    the failure mode: an inverted or corrupt input can make a kernel report a hugely
    negative intersection volume, and any code that compares a signed volume to a
    small positive tolerance will call that "well under tolerance" and report no
    clashes at all. The number that looks most like a pass is the one produced by
    the worst input.

    A machine with NO engine is the opposite situation and gets the opposite answer:
    the gate SKIPS. trimesh implements no booleans of its own and declares none of
    manifold3d, Blender or OpenSCAD as a dependency, so a bare `pip install trimesh`
    reaches the pair loop and every pair raises — which, counted as clashes, reports
    a missing tool as a broken design. That inversion is the one thing this pack
    exists to prevent, so the engines are probed once before any pair is touched.

    A part that is not a volume is also counted as a clash for the same reason as a
    raising kernel: the boolean's answer about it means nothing, and silence is the
    wrong way to say so.
    """
    meshes, welded, skip = _load_all(ctx, "cad.clash")
    if skip is not None:
        return skip
    if len(meshes) < 2:
        return _skipped(
            "cad.clash",
            f"only {len(meshes)} part(s) in the projection — interference needs at "
            f"least two placed solids; a single-part check would pass vacuously",
        )

    import numpy as np
    import trimesh

    engines = _boolean_engines()
    if not engines:
        return _skipped(
            "cad.clash",
            "no boolean engine is installed, so no pair could be intersected and no "
            "interference was measured: looked for "
            + ", ".join(name for _, name in _BOOLEAN_ENGINES)
            + ". trimesh implements no booleans itself and declares none of them as "
            "a dependency, so `pip install trimesh` alone is not enough for this gate",
        )
    ctx.log(f"cad.clash: boolean engine(s) available: {', '.join(engines)}")

    sliding = {p for p in (_normalise_pair(e) for e in (ctx.param("sliding_fits") or []))
               if p is not None}
    allowed, refusals = _read_allowlist(ctx, sliding)

    organic = {str(p) for p in (ctx.param("organic_parts") or [])}
    default_tol = ctx.param("clash_tolerance_mm3")
    default_tol = float(default_tol) if isinstance(default_tol, (int, float)) else PRISMATIC_CLASH_TOL_MM3
    per_pair_raw = ctx.param("clash_tolerances_mm3") or {}
    per_pair: dict[tuple[str, str], float] = {}
    if isinstance(per_pair_raw, dict):
        for key, value in per_pair_raw.items():
            pair = _normalise_pair(key)
            if pair is not None:
                per_pair[pair] = float(value)

    # The depth tolerance mirrors the volume one key for key, on purpose: the
    # argument against a global override ("raising it to silence one curved pair is
    # how a flat-plate interference stays hidden") is exactly as true for depth.
    default_depth = ctx.param("clash_depth_tol_mm")
    default_depth = (float(default_depth) if isinstance(default_depth, (int, float))
                     and not isinstance(default_depth, bool) else PRISMATIC_CLASH_DEPTH_TOL_MM)
    per_pair_depth_raw = ctx.param("clash_depth_tols_mm") or {}
    per_pair_depth: dict[tuple[str, str], float] = {}
    if isinstance(per_pair_depth_raw, dict):
        for key, value in per_pair_depth_raw.items():
            pair = _normalise_pair(key)
            if pair is not None:
                per_pair_depth[pair] = float(value)

    names = sorted(meshes)
    rows: list[dict[str, Any]] = []
    clashes: list[dict[str, Any]] = []
    worst_over = 0.0

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            pair = _pair_key(a, b)
            curved = a in organic or b in organic
            tol = per_pair.get(pair)
            if tol is None:
                tol = ORGANIC_CLASH_TOL_MM3 if curved else default_tol
            depth_tol = per_pair_depth.get(pair)
            if depth_tol is None:
                depth_tol = ORGANIC_CLASH_DEPTH_TOL_MM if curved else default_depth
            row: dict[str, Any] = {"a": a, "b": b, "tolerance_mm3": tol,
                                   "depth_tolerance_mm": depth_tol,
                                   "allowed": pair in allowed, "booleaned": False,
                                   "allow_reason": allowed.get(pair, "")}

            ma, mb = meshes[a], meshes[b]
            bad = [n for n, m in ((a, ma), (b, mb)) if not bool(getattr(m, "is_volume", False))]
            if bad:
                row.update(volume_mm3=None, depth_mm=None, verdict="clash",
                           why=f"{', '.join(bad)} is not a volume; the boolean's answer "
                               f"about this pair is meaningless")
                rows.append(row)
                if pair not in allowed:
                    clashes.append(row)
                continue

            lo_a, hi_a = np.asarray(ma.bounds, dtype=float)
            lo_b, hi_b = np.asarray(mb.bounds, dtype=float)
            gap = float(np.max(np.maximum(lo_a - hi_b, lo_b - hi_a)))
            if gap > AABB_MARGIN_MM:
                row.update(volume_mm3=0.0, depth_mm=0.0, verdict="clear",
                           why=f"bounding boxes {gap:.3f} mm apart, boolean not run")
                rows.append(row)
                continue

            row["booleaned"] = True
            try:
                inter = trimesh.boolean.intersection([ma, mb])
                volume = float(inter.volume) if inter is not None and len(inter.faces) else 0.0
            except Exception as exc:                   # noqa: BLE001 - kernel
                row.update(volume_mm3=None, depth_mm=None, verdict="clash",
                           why=f"boolean raised {type(exc).__name__}: {exc} — an "
                               f"un-booleanable pair is not a clear pair")
                rows.append(row)
                if pair not in allowed:
                    clashes.append(row)
                continue

            if not math.isfinite(volume) or volume < 0.0:
                row.update(volume_mm3=volume, depth_mm=None, verdict="clash",
                           why=f"boolean returned {volume} — a negative or non-finite "
                               f"intersection is a corrupt result, never a clear pair")
                rows.append(row)
                if pair not in allowed:
                    clashes.append(row)
                continue

            # Equivalent penetration depth. Only the overlap of the two bounding
            # boxes can carry shared material, so the widest plausible contact
            # patch is the LARGEST face of that box; mean depth over it is
            # volume/area. Taking the largest face makes this a LOWER bound on the
            # real penetration — the number errs towards forgiving, which is the
            # only direction a derived quantity may err in a gate that fails on it.
            lo = np.maximum(lo_a, lo_b)
            hi = np.minimum(hi_a, hi_b)
            ext = np.maximum(hi - lo, 0.0)
            contact = float(max(ext[0] * ext[1], ext[1] * ext[2], ext[0] * ext[2]))
            depth = (volume / contact) if contact > 0.0 else (0.0 if volume <= 0.0 else math.inf)

            over = volume - tol
            over_depth = depth - depth_tol
            row.update(volume_mm3=volume, depth_mm=depth, contact_mm2=contact,
                       verdict="clash" if (over > 0 or over_depth > 0) else "clear",
                       why=f"{volume:.4f} mm^3 vs {tol:g} mm^3 tolerance; "
                           f"{depth:.4f} mm equivalent depth over {contact:.2f} mm^2 "
                           f"vs {depth_tol:g} mm")
            rows.append(row)
            if over > 0 or over_depth > 0:
                worst_over = max(worst_over, over)
                if pair not in allowed:
                    clashes.append(row)

    evidence = [_write(ctx, "clash_pairs.json",
                       {"pairs": rows, "refused_allowlist_entries": refusals})]
    n_pairs = len(rows)
    booleaned = sum(1 for r in rows if r["booleaned"])
    # Worst first: an unmeasurable pair (None) outranks any measured volume, because
    # "the kernel could not answer" is a bigger problem than a known overlap.
    clashes.sort(key=lambda r: (isinstance(r.get("volume_mm3"), float),
                                -(r.get("volume_mm3") or 0.0)))
    worst = max((r for r in rows if isinstance(r.get("volume_mm3"), float)),
                key=lambda r: r["volume_mm3"], default=None)
    measured = max((r["volume_mm3"] for r in rows
                    if isinstance(r.get("volume_mm3"), float)), default=0.0)

    if refusals:
        detail = (f"{len(refusals)} allowlist entry/entries refused, so the allowlist "
                  f"is not trustworthy: {refusals[0]}")
        return Verdict(gate="cad.clash", passed=False, measured=float(len(refusals)),
                       limit=0.0, units="refused entries", detail=detail, evidence=evidence)

    if clashes:
        first = clashes[0]
        vol = first.get("volume_mm3")
        shown = f"{vol:.3f}" if isinstance(vol, float) else "unmeasurable"
        detail = (f"{len(clashes)} interfering pair(s) of {n_pairs} — worst reported "
                  f"{shown} mm^3 on {first['a']}/{first['b']} vs "
                  f"{first['tolerance_mm3']:g} mm^3 / "
                  f"{first['depth_tolerance_mm']:g} mm tolerance: {first['why']}")
        return Verdict(gate="cad.clash", passed=False, measured=float(len(clashes)),
                       limit=0.0, units="pairs", detail=detail, evidence=evidence)

    deepest = max((r["depth_mm"] for r in rows
                   if isinstance(r.get("depth_mm"), float)), default=0.0)
    detail = (f"0 interfering pairs of {n_pairs} ({booleaned} booleaned, rest AABB-clear); "
              f"largest shared volume {measured:.4f} mm^3"
              + (f" on {worst['a']}/{worst['b']} vs {worst['tolerance_mm3']:g} mm^3 tolerance"
                 if worst else "")
              + f"; deepest equivalent penetration {deepest:.4f} mm"
              + (f"; {len(allowed)} intended contact(s) allowlisted" if allowed else ""))
    return Verdict(gate="cad.clash", passed=True, measured=0.0, limit=0.0,
                   units="pairs", detail=detail, evidence=evidence)
