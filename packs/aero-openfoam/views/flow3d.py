# SPDX-License-Identifier: Apache-2.0
"""aero-openfoam's figures: the flow around the body on the base mesh, bound to
aero.converged's verdict entry, the wall's y+ bound to aero.wall_treatment's,
and the mesh ladder bound to aero.mesh_independence's.

    aero.hero        the body coloured by Cp and OpenFOAM's stream tracks as
                     tubes coloured by speed, lit, with its 3D file
    aero.surface_cp  the body coloured by Cp, unlit: each pixel a key colour
    aero.history     the drag area at each iteration, and the window the
                     iterative uncertainty is read from
    aero.wake        OpenFOAM's surface of total pressure coefficient 0 (the
                     edge of the wake), coloured by speed, lit
    aero.wake_cuts   three cuts across the wake, coloured by the total
                     pressure coefficient, unlit
    aero.wall        the body coloured by y+ in four bands, unlit
    aero.ladder      the drag area on each mesh of the ladder

``aero.wall`` and ``aero.ladder`` are registered with the gates they bind to
(`LATER`): until then they are drawn in the tests and listed nowhere.

**OpenFOAM computes every field and every geometry; ParaView only draws.**
Each picture reads the files the gate's function objects wrote (``surfaces``:
the body, the wake surface, the cuts; ``streamLine``: the tracks), bound by
the sha256 values the verified summary names (``ctx.bind``) and copied into a
scratch folder, so ParaView reads those bytes and no other file of the run.
``_scene3d.py`` draws them in pvbatch on the scales of ``_scales.py``. The
PNG is published only when the run says it applied the preset the legend is
made from; the wall's band colours only when each is the exported preset's
colour for its band. Without a checked ParaView the pictures are left out,
said in the build's warnings, and no status moves (``_pv.py``, the same file
as cfd-openfoam's but for `_pv.KNOWN`).

**Why aero.converged, not aero.drag_area.** A gate whose prerequisite failed
leaves no verdict entry (invariant 10), so pictures bound to the drag area
would vanish whenever any guard failed. Bound to the base-mesh solve, a design
that fails a later guard still shows its flow beside its Failing chip. Every
caption says "base mesh".

**The charts** need no tool. Every number is one the gate wrote into its
summary, read here and never computed; the spine refuses a chart number no
evidence file holds. Neither chart is of the judged quantity (``"judged":
false``): the claim's drag area is judged at the top of the fine mesh's band
by aero.drag_area, so neither draws its limit or a judged point.

**What each entry's summary holds** (``summary.json``, the contract with
``gates/aero.py``):

- aero.converged: ``u_inf_m_s``; ``ground_z_m`` (optional: the floor of the
  picture, else the bottom of the body); ``fields`` ``{"stage", "time",
  "sha256": {<path under stage>: <sha256>}}`` naming each file of `FILES`;
  ``history`` (the base name of the entry's evidence CSV, ``iteration,cda_m2``
  one row per iteration); ``window`` (the iterations of the last window, an
  integer); ``u_i_m2`` (half the range of CdA over the window, m^2). What
  slipped through the two branches (merged 2026-10-23): the views read a
  ``cda_history`` list and ``u_i`` in summary.json, the gate wrote the
  history as a CSV (a list in a JSON evidence file puts every number of the
  run in the prose scan's pool) and ``u_i_m2``, so the chart drew nothing on
  a real run; `TheViewsReadWhatTheGateWrites` now runs the gate's own
  summary through each view.
- aero.wall_treatment: ``fields`` as above, naming `FILES` ``yplus``.
- aero.mesh_independence: ``levels`` ``[{"k", "cells", "h_rel", "cda_m2"}]``,
  and, when the gate computed them, ``cda_ext_m2`` at ``h_rel_ext`` and the
  band from the finest ``cda_m2`` to ``band_top_m2``.

**Captions** are site text (ASD-STE100): what a figure shows, never a status
and no number (the chips beside the figure say the status).
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import json
import math
import os
import sys
import tempfile

from nopekit.models import View, ViewKind
from nopekit.page import EVIDENCE_MAX_BYTES as _MAX_BYTES
from nopekit.site import viewgen

GATE = "aero.converged"
WALL_GATE = "aero.wall_treatment"
LADDER_GATE = "aero.mesh_independence"


def _load_pv():
    """``views/_pv.py`` under this pack's own module name (``_pv.sibling``
    loads ``_scales.py`` the same way): the loader puts the pack root on
    ``sys.path``, not ``views/``, and a bare ``import _pv`` would take
    cfd-openfoam's when its views were loaded first."""
    name = "nopekit_aero_openfoam_pv"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_pv.py"))
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module      # before exec: its dataclasses look it up
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
    return sys.modules[name]


_pv = _load_pv()
_scales = _pv.sibling("_scales")

#: The scene pvbatch runs for every picture.
SCENE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scene3d.py")
#: The files whose bytes, with this module's, key a picture's memo: the scene,
#: the scales and the preset the legend is made from. *Rejected:* ``_pv.py``
#: (as in cfd-openfoam: the build and its control are checked on each draw).
RECIPE = ("views/_scene3d.py", "views/_scales.py", "views/turbo.json")

#: ``nopekit doctor``'s row for the tool the pictures draw with.
TOOL_CHECKS = {_pv.WRAPPER: _pv.doctor_check}

#: Where OpenFOAM's function objects write each file a picture reads, under
#: the run's case folder, at the last time. Measured on v2606 (P0):
#: ``surfaces`` writes ``postProcessing/<name>/<time>/<surface>.vtp``, and
#: ``streamLine`` writes under ``sets/``, not under its own name. One
#: ``cuttingPlane`` is one plane, so the three cuts are three surfaces.
FILES = {
    "body": "postProcessing/surfaces1/{time}/body.vtp",
    "tracksCentre": "postProcessing/sets/tracksCentre/{time}/track0.vtp",
    "tracksFar": "postProcessing/sets/tracksFar/{time}/track0.vtp",
    "wake": "postProcessing/surfaces1/{time}/wakeIso.vtp",
    "cut1": "postProcessing/surfaces1/{time}/wakeCut1.vtp",
    "cut2": "postProcessing/surfaces1/{time}/wakeCut2.vtp",
    "cut3": "postProcessing/surfaces1/{time}/wakeCut3.vtp",
    "yplus": "postProcessing/surfaces1/{time}/bodyYPlus.vtp",
}

#: What the page says each picture and each chart is drawn from.
PICTURE_PROVENANCE = "OpenFOAM calculated the fields, the surfaces and the paths. ParaView drew them."
CHART_PROVENANCE = "OpenFOAM solved the flow. The chart shows the numbers of that run."

HERO_CAPTION = ("The air comes from the front of the bike. This picture shows the base mesh. "
                "The colour on the bike and the rider shows the pressure of the air on the "
                "surface. The colour on the lines shows the speed of the air. Light and shade "
                "make some colours darker than the colours in the key.")
HERO_ALT = ("A motorcycle with a rider, seen from the front and the left. Coloured lines show "
            "the paths of the air around them.")
SURFACE_CAPTION = ("The colour shows the pressure of the air on the surface of the bike and the "
                   "rider, on the base mesh. The colours have no light or shade, so each colour "
                   "is the same as in the key.")
SURFACE_ALT = "A motorcycle with a rider, coloured by the pressure of the air on the surface."
WAKE_CAPTION = ("The surface shows the edge of the wake on the base mesh. In the wake, the air "
                "has less energy than the air that flows past. The colour shows the speed of "
                "the air on the surface.")
WAKE_ALT = ("A coloured surface that starts on the bike and the rider and goes back behind "
            "them, seen from behind and from the right.")
CUTS_CAPTION = ("Each cut is a plane across the flow behind the bike, on the base mesh. The "
                "colour shows the energy that is left in the air. The picture does not show "
                "the air that has all of its energy.")
CUTS_ALT = "A grey motorcycle with a rider, and three coloured planes across the air behind it."
WALL_CAPTION = ("The colour shows the wall value y+ on the bike and the rider, on the base "
                "mesh. Each cell shows its own band. The wall model applies in the bands below "
                "the top band.")
WALL_ALT = "A motorcycle with a rider, coloured in four bands of the wall value y+."
HISTORY_CAPTION = ("The drag area on the base mesh after each iteration, for the last part of "
                   "the run. The second colour shows the window that the result uses. The two "
                   "dotted lines are the highest and the lowest value in that window. The "
                   "iterative uncertainty is half of the distance between them.")
LADDER_CAPTION = ("The drag area on each mesh of the ladder, against the cell size relative "
                  "to the finest mesh. If the solver results give a value at zero cell size, "
                  "a circle with no fill shows it. A short bar at each end of a line at the "
                  "finest mesh then shows the mesh error band (GCI).")

#: How much of the run the history chart shows: the last this many windows.
#: Measured on L0 (P0): CdA falls from 1.03 at iteration 1 to 0.31 by
#: iteration 150, and over that span the window's half-range, about 0.0008 m^2,
#: is less than a pixel, so the two lines the caption names are one.
#: *Rejected:* the whole run (the window cannot be seen); the window alone (a
#: drift from one window to the next, which the gate reports, is not seen).
HISTORY_WINDOWS = 3


def _summary(ctx, gate: str):
    """The verified summary of the entry, or None, said in the warnings."""
    path = ctx.entry.path("summary.json")
    if path is None:
        ctx.note(f"summary.json: the file on this computer is from another run: `nopekit "
                 f"check --force --only {gate}` solves it again")
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _bind(ctx, summary: dict, roles: tuple[str, ...], work: str, gate: str):
    """Copy the files of ``roles`` into ``work``, each bound to the sha256
    the verified summary names and checked again as it is copied: ``{role:
    local path}``, or None, said in the warnings."""
    fields = summary.get("fields") if isinstance(summary.get("fields"), dict) else {}
    stage, time = str(fields.get("stage") or ""), str(fields.get("time") or "")
    shas = fields.get("sha256") if isinstance(fields.get("sha256"), dict) else {}
    wanted = {role: FILES[role].format(time=time) for role in roles}
    missing = [rel for rel in wanted.values() if not shas.get(rel)]
    if not stage or not time or missing:
        ctx.note(f"the summary of this result names no {', '.join(missing) or 'solved case'}: "
                 f"`nopekit check --force --only {gate}` runs it again")
        return None
    bound = ctx.bind({f"{stage}/{rel}": shas[rel] for rel in wanted.values()})
    if bound is None:
        return None
    out = {}
    for role, rel in wanted.items():
        with open(bound[f"{stage}/{rel}"], "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != shas[rel]:
            ctx.note(f"{rel} moved while it was copied: `nopekit check --force --only {gate}` "
                     f"solves it again")
            return None
        target = os.path.join(work, "files", role + ".vtp")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
        out[role] = target
    return out


def job_for(scene: str, files: dict, summary: dict, *, camera: dict,
            gltf: str = "", variant: str = "") -> dict:
    """The pvbatch job of one scene: the bound files, the pack's constants
    and the scales' ends. Public for the tests, which draw the twin of the
    hero with the hero's own job."""
    speed = _scales.speed(summary) or {}
    job = {"scene": scene, "body": files.get("body", ""),
           "tracks": [files[r] for r in ("tracksCentre", "tracksFar") if r in files],
           "wake": files.get("wake", ""),
           "cuts": [files[r] for r in ("cut1", "cut2", "cut3") if r in files],
           "yplus": files.get("yplus", ""),
           "fields": {"cp": _scales.CP["field"], "speed": _scales.SPEED["field"],
                      "cpt": _scales.CPT["field"], "yplus": _scales.YPLUS["field"]},
           "ranges": {"cp": list(_scales.CP_RANGE), "cpt": list(_scales.CPT_RANGE)},
           "bands": list(_scales.YPLUS_BANDS), "band_at": list(_scales.BAND_AT),
           "cut_clip": _scales.CPT_CUT_CLIP,
           "preset": _scales.PRESET, "over": list(_scales.OVER), "under": list(_scales.UNDER),
           "size": list(_scales.SIZE), "camera": camera, "look": _scales.LOOK,
           "tube": _scales.TUBE, "ground_z": summary.get("ground_z_m")
           if _number(summary.get("ground_z_m")) else None,
           "png": "still.png", "ticks": _scales.TICK_BINS}
    if speed:
        job["ranges"]["speed"] = [speed["lo"], speed["hi"]]
    if gltf:
        job["gltf"], job["gltf_opts"] = gltf, _scales.GLTF
    if variant:
        job["variant"] = variant
    return job


def _check_result(result: dict, job: dict, work: str) -> bytes:
    """The PNG's bytes, once the run's result says it drew what the job asked:
    the legend's preset, the PNG it names, a piece for each input, and on the
    wall each band in the exported preset's colour. Anything else raises
    :class:`_pv.RunError` (an error of the picture; no status moves)."""
    if result.get("preset_sha256") != _scales.preset_sha256():
        raise _pv.RunError(f"pvbatch applied a {_scales.PRESET} preset that is not "
                           f"views/turbo.json, so the legend would not be the colours of the "
                           f"picture: export it again (views/_export_preset.py)")
    with open(os.path.join(work, job["png"]), "rb") as fh:
        data = fh.read()
    if hashlib.sha256(data).hexdigest() != result.get("png_sha256"):
        raise _pv.RunError("the PNG on disk is not the one pvbatch's result names")
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    empty = [name for name, n in counts.items()
             if (n if isinstance(n, int) else min(n or [0])) <= 0]
    if not counts.get("body") or empty:
        raise _pv.RunError(f"pvbatch drew nothing of {', '.join(empty) or 'the body'}: the "
                           f"picture is not the result's flow")
    if job["scene"] == "wall":
        got = result.get("band_colours") or []
        want = [_scales.preset_colour(at) for at in _scales.BAND_AT]
        if len(got) != len(want) or any(
                max(abs(a - b) for a, b in zip(g, w)) > _pv.CONTROL_TOLERANCE
                for g, w in zip(got, want)):
            raise _pv.RunError(f"pvbatch drew the y+ bands in {got}, and the key's colours "
                               f"are {want}")
    return data


def _picture(ctx, view_id: str, gate: str, scene: str, roles: tuple[str, ...], *,
             camera: dict, caption: str, alt: str, light: str, scales: dict,
             as_list: tuple = (), gltf: str = ""):
    """One picture: the summary, its scales, the bound files, a checked
    ParaView, one pvbatch run of ``_scene3d.py``, and the PNG through
    ``write_asset``; with ``gltf``, the same run's 3D file too.

    ``scales`` maps the scene's names (``cp``, ``speed``, ``cpt``, ``yplus``)
    to the scale builders of ``_scales.py``; ``as_list`` names, for a figure
    with ``scales``, where each is drawn (``(("cp", "surface"), ...)``); with
    none, the one scale is the figure's ``scale``."""
    summary = _summary(ctx, gate)
    if summary is None:
        return None
    built = {name: fn(summary) for name, fn in scales.items()}
    missing = [name for name, scale in built.items() if not scale]
    if missing:
        ctx.note(f"the summary of this result holds no range for {', '.join(missing)} "
                 f"(the free-stream speed, u_inf_m_s)")
        return None
    with tempfile.TemporaryDirectory(prefix="nopekit-aero-picture-") as work:
        files = _bind(ctx, summary, roles, work, gate)
        if files is None:
            return None
        try:
            inst = _pv.ready(ctx.root)
        except _pv.Unavailable as exc:
            ctx.note(f"{exc}. {_pv.NO_PICTURES} {_pv.SEE}")
            return None
        job = job_for(scene, files, summary, camera=camera, gltf=gltf and "field.gltf")
        run = os.path.join(work, "run")
        try:
            result = _pv.run(inst, SCENE, job, run)
        except _pv.Unavailable as exc:
            ctx.note(f"{exc}. {_pv.NO_PICTURES}")
            return None
        data = _check_result(result, job, run)
        solid = None
        if gltf:
            with open(os.path.join(run, job["gltf"]), "rb") as fh:
                solid = fh.read()
            if hashlib.sha256(solid).hexdigest() != result.get("gltf_sha256"):
                raise _pv.RunError("the glTF on disk is not the one pvbatch's result names")
        src = ctx.write_asset(f"{view_id.rsplit('.', 1)[-1]}.png", data)
        # Measured before the write: over the cap, write_asset refuses, and the
        # spine then refuses the whole figure, the still with it.
        if solid is not None and len(solid) > _MAX_BYTES:
            ctx.note(f"its 3D file is {len(solid)} bytes, over the 2 MiB cap of a figure: "
                     f"the still is drawn without it")
        elif solid is not None:
            ctx.write_asset(gltf, solid)
    ticks = result.get("scales") if isinstance(result.get("scales"), dict) else {}
    for name, scale in built.items():
        if "lo" in scale:
            got = ticks.get(name) or {}
            built[name] = _scales.with_ticks(scale, got.get("ticks") or (),
                                             got.get("tick_texts") or ())
    meta = {"caption": caption, "alt": alt, "light": light,
            "tool": {"identity": inst.identity, "accepted_by": inst.accepted_by}}
    if as_list:
        meta["scales"] = [_scales.on(built[name], where) for name, where in as_list]
    else:
        (meta["scale"],) = built.values()
    return View(id=view_id, kind=ViewKind.IMAGE, src=src, meta=meta)


@viewgen(id="aero.hero", kind=ViewKind.IMAGE, title="The air around the bike",
         description=PICTURE_PROVENANCE, evidence_of=GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=10)
def hero(ctx):
    """The body by Cp and the tracks by speed, lit, and its 3D file: the
    same run exports ParaView's glTF of the body and the tracks (decimated,
    ``COLOR_0`` in the key's colours), which the page turns lit, with a
    toggle to its flat colours."""
    return _picture(ctx, "aero.hero", GATE, "hero",
                    ("body", "tracksCentre", "tracksFar"), camera=_scales.HERO_CAMERA,
                    caption=HERO_CAPTION, alt=HERO_ALT, light="scene",
                    scales={"cp": _scales.cp, "speed": _scales.speed},
                    as_list=(("cp", "surface"), ("speed", "lines")), gltf="hero.gltf")


@viewgen(id="aero.surface_cp", kind=ViewKind.IMAGE, title="The pressure on the surface",
         description=PICTURE_PROVENANCE, evidence_of=GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=20)
def surface_cp(ctx):
    """The body by Cp with no light: the picture whose pixels are the key's
    colours (the hero's are shaded)."""
    return _picture(ctx, "aero.surface_cp", GATE, "surface_cp", ("body",),
                    camera=_scales.BODY_CAMERA, caption=SURFACE_CAPTION, alt=SURFACE_ALT,
                    light="none", scales={"cp": _scales.cp})


@viewgen(id="aero.wake", kind=ViewKind.IMAGE, title="The wake",
         description=PICTURE_PROVENANCE, evidence_of=GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=40)
def wake(ctx):
    """OpenFOAM's iso-surface of CpT = 0 by speed, lit, the body grey."""
    return _picture(ctx, "aero.wake", GATE, "wake", ("body", "wake"),
                    camera=_scales.WAKE_CAMERA, caption=WAKE_CAPTION, alt=WAKE_ALT,
                    light="scene", scales={"speed": _scales.speed},
                    as_list=(("speed", "surface"),))


@viewgen(id="aero.wake_cuts", kind=ViewKind.IMAGE, title="Cuts across the wake",
         description=PICTURE_PROVENANCE, evidence_of=GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=50)
def wake_cuts(ctx):
    """OpenFOAM's three cuts by CpT, unlit, clipped above `CPT_CUT_CLIP`;
    the body grey and lit."""
    return _picture(ctx, "aero.wake_cuts", GATE, "wake_cuts", ("body", "cut1", "cut2", "cut3"),
                    camera=_scales.CUTS_CAMERA, caption=CUTS_CAPTION, alt=CUTS_ALT,
                    light="none", scales={"cpt": _scales.cpt})


#: The figures bound to gates this pack does not have yet (aero.wall_treatment
#: and aero.mesh_independence come with the design's P6): ``{view id: (the
#: viewgen's arguments, its function)}``. Drawn and tested now, registered with
#: their gates. What it closes: a figure registered before its gate is one
#: ``pack validate`` refuses ("a pack's figure draws its own gate's result"),
#: and a build would list it as never drawn. *Rejected:* registering them with
#: a stand-in gate (a gate with no negative control is refused, invariant 3).
LATER: dict = {}


def _later(**kwargs):
    def decorate(fn):
        LATER[kwargs["id"]] = (kwargs, fn)
        return fn
    return decorate


@_later(id="aero.wall", kind=ViewKind.IMAGE, title="The wall value y+",
         description=PICTURE_PROVENANCE, evidence_of=WALL_GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=60)
def wall(ctx):
    """OpenFOAM's ``yPlus`` on each cell of the body, in four bands, unlit."""
    return _picture(ctx, "aero.wall", WALL_GATE, "wall", ("yplus",),
                    camera=_scales.BODY_CAMERA, caption=WALL_CAPTION, alt=WALL_ALT,
                    light="none", scales={"yplus": _scales.yplus})


# --------------------------------------------------------------------------- #
# the charts
# --------------------------------------------------------------------------- #
def _cda_history(ctx, summary: dict) -> list:
    """``[[iteration, CdA in m^2], ...]`` from the entry's history CSV (the
    file summary.json's ``history`` names, verified with the entry), or []
    when there is none. A row whose numbers do not read is left out, never
    replaced (cfd-openfoam's ``settle`` rule)."""
    name = summary.get("history")
    path = ctx.entry.path(name) if isinstance(name, str) and name else None
    if path is None:
        return []
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                it, cda = int(row["iteration"]), float(row["cda_m2"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(cda):
                out.append([it, cda])
    return out


@viewgen(id="aero.history", kind=ViewKind.CHART,
         title="How the drag area settled on the base mesh",
         description=CHART_PROVENANCE, evidence_of=GATE, order=30)
def history(ctx):
    """``cda_history`` for the last `HISTORY_WINDOWS` windows, the window
    the gate judged as a second series, and a dotted line at its highest and
    at its lowest value: U_I is half the distance between them. A history
    whose window is not the summary's ``u_i`` draws no chart (it would not be
    the window the gate judged)."""
    summary = _summary(ctx, GATE)
    if summary is None:
        return None
    rows = _cda_history(ctx, summary)
    window = summary.get("window")
    if not rows or not isinstance(window, int) or isinstance(window, bool) or window < 2:
        ctx.note(f"the summary of this result holds no drag area history and window: "
                 f"`nopekit check --force --only {GATE}` runs it again")
        return None
    rows.sort(key=lambda r: r[0])
    if len(rows) < window:
        ctx.note("the run is shorter than its window: the window never filled")
        return None
    judged = rows[-window:]
    values = [r[1] for r in judged]
    top, bottom = max(values), min(values)
    u_i = summary.get("u_i_m2")
    if _number(u_i) and not math.isclose(0.5 * (top - bottom), u_i, rel_tol=1e-6,
                                         abs_tol=1e-15):
        ctx.note(f"the history's last {window} iterations are not the window the gate "
                 f"judged (its u_i): the chart is not drawn")
        return None
    shown = rows[-HISTORY_WINDOWS * window:]
    data = {"series": [
                {"key": "run", "label": "each iteration",
                 "points": [[r[0], r[1]] for r in shown]},
                {"key": "window", "label": "the window",
                 "points": [[r[0], r[1]] for r in judged]}],
            "judged": False,
            "rule": [{"value": top, "label": "highest in the window"},
                     {"value": bottom, "label": "lowest in the window"}],
            "x": {"label": "iteration"},
            "y": {"label": "drag area", "units": "m^2", "zero": False}}
    return View(id="aero.history", kind=ViewKind.CHART, data=data,
                meta={"caption": HISTORY_CAPTION})


@_later(id="aero.ladder", kind=ViewKind.CHART, title="The drag area on each mesh",
         description=CHART_PROVENANCE, evidence_of=LADDER_GATE, order=70)
def ladder(ctx):
    """``levels[].cda_m2`` against ``levels[].h_rel``, each point named by its
    cell count; ``cda_ext_m2`` at ``h_rel_ext`` with no fill, and the band
    from the finest ``cda_m2`` to ``band_top_m2``, when the gate computed
    them (cfd-openfoam's ladder, with the drag area's quantity and units).
    A ladder whose order or convergence the gate refused has no
    extrapolation and no band: the meshes alone are drawn.

    ``"judged": false``: this entry's evaluator judges the meshes and the GCI,
    not the drag area, so the spine draws no limit and no judged point here.
    *Rejected:* the claim's limit line (it is drag_area's, beside its own
    judged value, which this entry does not hold)."""
    summary = _summary(ctx, LADDER_GATE)
    if summary is None:
        return None
    levels = [lv for lv in summary.get("levels") or ()
              if isinstance(lv, dict) and _number(lv.get("h_rel")) and _number(lv.get("cda_m2"))]
    if not levels:
        ctx.note(f"the summary of this result holds no drag area per mesh in m^2: `nopekit "
                 f"check --force --only {LADDER_GATE}` runs it again")
        return None
    levels.sort(key=lambda lv: -lv["h_rel"])
    series = [{"key": "meshes", "label": "each mesh",
               "points": [[lv["h_rel"], lv["cda_m2"]] for lv in levels],
               "labels": [f"{lv.get('cells')} cells" for lv in levels]}]
    data = {"series": series, "legend": False, "judged": False,
            "x": {"label": "relative cell size"},
            "y": {"label": "drag area", "units": "m^2", "zero": False}}
    if _number(summary.get("cda_ext_m2")) and _number(summary.get("h_rel_ext")):
        series.append({"key": "richardson", "label": "zero cell size",
                       "points": [[summary["h_rel_ext"], summary["cda_ext_m2"]]],
                       "labels": ["zero cell size"], "hollow": True})
    top = summary.get("band_top_m2")
    if _number(top):
        data["band"] = [{"x": levels[-1]["h_rel"], "lo": levels[-1]["cda_m2"], "hi": top,
                         "label": "GCI band"}]
    return View(id="aero.ladder", kind=ViewKind.CHART, data=data,
                meta={"caption": LADDER_CAPTION})
