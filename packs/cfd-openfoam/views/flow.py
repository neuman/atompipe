# SPDX-License-Identifier: Apache-2.0
"""cfd-openfoam's figures: charts and stills bound to cfd.pressure_drop's
verdict entry.

    cfd-openfoam.ladder   the pressure drop on each mesh against its cell size,
                          the Richardson value at zero cell size and the GCI band
    cfd-openfoam.speed    a still of |U| (OpenFOAM's ``mag(U)``) on the finest mesh
    cfd-openfoam.pressure a still of the static pressure (OpenFOAM's ``static(p)``)
    cfd-openfoam.settle   how much the pressure drop changed at each iteration,
                          on each mesh, with the tolerance and each estimate

**Every number of a chart is the run's.** Each chart is a payload of numbers that
cfd.pressure_drop wrote into its evidence (``summary.json`` and the
``history_level{k}.csv`` files), read here and never computed: the spine
refuses a chart number that no verified evidence file of the entry holds, and
a chart that holds a limit. The spine adds the claim's limit line and the
judged point from the floor, and bakes the whole Vega-Lite spec (GitHub #15,
Phase 1); this module draws nothing. What slipped through before Phase 1: a
chart took its margin from the view's own limit, so a pack limit beside the
claim's was a second limit on the page.

**No tool for the charts.** Both charts need only the evidence, so they are
on the page wherever cfd.pressure_drop ran, ParaView or not.

**The stills** need pvbatch, found and checked by `_pv.py` (the build's
lock, then the renderer control). Each draws the finest level's solved field
from the files whose sha256 the verified summary names (``ctx.bind``): a copy
of the mesh and the field, with a controlDict of its own, so ParaView reads
those bytes and no other file of the run. ``_scene.py`` draws it in pvbatch,
on a scale of ``_scales.py`` (a pack constant times a value of the summary,
never a limit); the PNG is published only when the run says it applied the
preset the legend is made from. Without a checked ParaView the stills are
left out, said in the build's warnings, and no status moves. The 3D view is
P2.4.

**Captions** are site text (ASD-STE100) and say what a figure shows, never a
status: the chips beside the figure say that. "Open" is a status word, so the
Richardson point is "the circle with no fill".
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
from nopekit.site import viewgen

GATE = "cfd.pressure_drop"


def _load_pv():
    """``views/_pv.py`` under a name of this pack's own: the loader puts the
    pack root on ``sys.path``, not ``views/``, and a bare ``import _pv`` would
    take another pack's ``_pv`` if one were first. ``_pv.sibling`` loads
    ``_scales.py`` the same way."""
    name = "nopekit_cfd_openfoam_pv"
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

#: The scene pvbatch runs for a still (B.3.3).
SCENE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_scene.py")
#: The files whose bytes, with this module's, key a still's memo: the scene,
#: the scales and the preset the legend is made from. A changed scene draws
#: again. *Rejected:* ``_pv.py`` in the recipe (a word of ``doctor`` would
#: draw every picture again; the build and its control are checked on each
#: draw, and C6 keeps the tool's identity out of the key).
RECIPE = ("views/_scene.py", "views/_scales.py", "views/viridis.json")

#: ``nopekit doctor``'s row for the tool the stills and the 3D view draw with:
#: found or not, the ParaView build, and its renderer control
#: (``_pv.doctor_check``). It runs ``pvbatch --version`` and runs no control.
TOOL_CHECKS = {_pv.WRAPPER: _pv.doctor_check}

#: What the page says each chart is drawn from (the ViewSpec description, the
#: figure's provenance line).
PROVENANCE = "OpenFOAM solved each mesh. The chart shows the numbers of that run."

#: What the page says each still is drawn from.
PICTURE_PROVENANCE = "OpenFOAM calculated the fields. ParaView drew them."

SPEED_CAPTION = ("The speed of the flow on the finest mesh ({cells} cells), at the middle of "
                 "its thickness. Each cell shows its own value. The two lines across the flow "
                 "are the planes where the pressure drop is measured.")
PRESSURE_CAPTION = ("The static pressure on the finest mesh ({cells} cells), at the middle of "
                    "its thickness. Each cell shows its own value. The two lines across the "
                    "flow are the planes where the pressure drop is measured.")
SPEED_ALT = "The fluid coloured by the speed of the flow, with two lines across it."
PRESSURE_ALT = "The fluid coloured by the static pressure, with two lines across it."
#: The words at the two planes' lines on the still, in the order of the
#: summary's ``planes`` (cfd_dp_planes: upstream, then downstream). The
#: captions give the lines no colour: ParaView draws them black, and the
#: page draws its own mark over each (``lib/figures.js``), so on the page
#: they read white. What slipped through: "the two black lines" beside
#: two white ones.
PLANE_WORDS = ("upstream plane", "downstream plane")
#: The mesh files a still reads, beside the field at the last time.
MESH = tuple(f"constant/polyMesh/{name}"
             for name in ("points", "faces", "owner", "neighbour", "boundary"))
#: The controlDict of the copy: the reader needs the file; nothing of the
#: run's own controlDict is read. Measured: ParaView 6.2's OpenFOAMReader
#: lists the times and fields of a case from this header alone.
CONTROL_DICT = ("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class dictionary;\n"
                "    object controlDict;\n}\n")

LADDER_CAPTION = ("The pressure drop on each of the three meshes. The circle with no fill is "
                  "the value at zero cell size (Richardson extrapolation). The bar is the mesh "
                  "error band (GCI). The top of the bar is the value that is compared with the "
                  "limit.")

SETTLE_CAPTION = ("How much the pressure drop changed after each iteration, as a percentage "
                  "of the last value, on each mesh. The dotted line is the tolerance. Each "
                  "diamond is the estimate of the change that is still to come.")


def _summary(ctx):
    """The verified summary of the entry, or None, said in the warnings."""
    path = ctx.entry.path("summary.json")
    if path is None:
        ctx.note(f"the evidence on this computer is from another run: `nopekit check --force "
                 f"--only {GATE}` solves it again")
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


@viewgen(id="cfd-openfoam.ladder", kind=ViewKind.CHART, title="The pressure drop on each mesh",
         description=PROVENANCE, evidence_of=GATE, order=10)
def ladder(ctx):
    """``levels[].dp_pa`` against ``levels[].h_rel``, each point named by its
    cell count; ``dp_ext_pa`` at ``h_rel_ext`` with no fill; the GCI band at the
    finest level from ``dp_pa`` to ``band_top_pa``, and its top as a point, so the
    spine puts the judged point there (``page._series_x`` finds the judged value
    among the series). A run that gave no band (an error of the gate) draws its
    meshes alone.

    The y axis does not start at zero: the three meshes differ by about 0.4% of
    the drop on the baseline, and from zero they draw as one point. *Rejected:*
    a log y (its domain rounds to powers of ten, 0.1 to 1 Pa here, which hides
    the same 0.4%)."""
    summary = _summary(ctx)
    if summary is None:
        return None
    levels = [lv for lv in summary.get("levels") or ()
              if _number(lv.get("h_rel")) and _number(lv.get("dp_pa"))]
    if not levels:
        ctx.note(f"the summary of this result holds no pressure drop per mesh in Pa; "
                 f"`nopekit check --force --only {GATE}` runs it again")
        return None
    levels.sort(key=lambda lv: -lv["h_rel"])
    # Legend words short enough for Vega's legend (it cut "pressure drop on each
    # mesh" at 160 px), and in the order Vega sorts them, by text.
    series = [{"key": "meshes", "label": "each mesh",
               "points": [[lv["h_rel"], lv["dp_pa"]] for lv in levels],
               "labels": [f"{lv['cells']} cells" for lv in levels]}]
    data = {"series": series,
            "x": {"label": "cell size, relative to the finest mesh"},
            "y": {"label": "pressure drop", "units": "Pa", "zero": False}}
    finest = levels[-1]
    if _number(summary.get("dp_ext_pa")) and _number(summary.get("h_rel_ext")):
        series.append({"key": "richardson", "label": "zero cell size",
                       "points": [[summary["h_rel_ext"], summary["dp_ext_pa"]]],
                       "hollow": True})
    top = summary.get("band_top_pa")
    if _number(top) and _number(summary.get("dp_pa")):
        series.append({"key": "band_top", "label": "top of the GCI band",
                       "points": [[finest["h_rel"], top]]})
        data["band"] = [{"x": finest["h_rel"], "lo": summary["dp_pa"], "hi": top,
                         "label": "GCI band"}]
    return View(id="cfd-openfoam.ladder", kind=ViewKind.CHART, data=data,
                meta={"caption": LADDER_CAPTION})


def _history(path: str):
    """``[(iteration, change_pct)]`` from a history CSV: the rows with a change
    above zero. The first row has none, and a change of zero (an exact repeat)
    has no place on a log axis; both are left out, never replaced. *Rejected:*
    a floor value for a zero (a number no evidence file holds)."""
    out = []
    last = None
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            try:
                it = int(row["iteration"])
            except (KeyError, TypeError, ValueError):
                continue
            last = it
            try:
                change = float(row.get("change_pct") or "")
            except ValueError:
                continue
            if math.isfinite(change) and change > 0:
                out.append([it, change])
    return out, last


@viewgen(id="cfd-openfoam.settle", kind=ViewKind.CHART,
         title="How the pressure drop settled on each mesh",
         description=PROVENANCE, evidence_of=GATE, order=40)
def settle(ctx):
    """``change_pct`` against ``iteration`` from each ``history_level{k}.csv``,
    one series per mesh, on a log y; the tolerance ``convergence_tol_pct`` as a
    rule (a pack threshold on the estimate, never the claim's limit); and each
    mesh's ``iterative_error_pct`` as a diamond at its last iteration. A mesh
    with no estimate has no diamond. A history file the entry does not hold
    (another run's bytes) draws no chart: a chart with a mesh left out would
    read as the whole run."""
    summary = _summary(ctx)
    if summary is None:
        return None
    series, estimates = [], []
    for lv in summary.get("levels") or ():
        name = f"history_level{lv.get('k')}.csv"
        path = ctx.entry.path(name)
        if path is None:
            ctx.note(f"{name} of this result is not on this computer: `nopekit check --force "
                     f"--only {GATE}` runs it again")
            return None
        points, last = _history(path)
        # "mesh 1 (500 cells)": Vega sorts a legend by its text, and "2000 cells"
        # came before "500 cells".
        label = f"mesh {int(lv.get('k', 0)) + 1} ({lv.get('cells')} cells)"
        series.append({"key": f"level{lv.get('k')}", "label": label, "points": points})
        est = lv.get("iterative_error_pct")
        if last is not None and _number(est) and est > 0:
            estimates.append({"x": last, "y": est, "label": f"estimate, {label}"})
    if not series:
        ctx.note("the summary of this result holds no mesh levels")
        return None
    data = {"series": series, "estimates": estimates,
            "x": {"label": "iteration"},
            "y": {"label": "change of the pressure drop", "units": "%", "scale": "log"}}
    tol = summary.get("convergence_tol_pct")
    if _number(tol):
        data["rule"] = {"value": tol, "label": "tolerance"}
    return View(id="cfd-openfoam.settle", kind=ViewKind.CHART, data=data,
                meta={"caption": SETTLE_CAPTION})


# --------------------------------------------------------------------------- #
# the stills (P2.3)
# --------------------------------------------------------------------------- #
def _case(ctx, summary: dict, field: str, work: str) -> tuple[str, str] | None:
    """Copy the finest level's mesh and ``field`` at its last time into
    ``<work>/case``, each file bound to the sha256 the verified summary names
    and checked again as it is copied: ``(case, time)``, or None, said in the
    warnings."""
    fields = summary.get("fields") if isinstance(summary.get("fields"), dict) else {}
    stage, time = str(fields.get("stage") or ""), str(fields.get("time") or "")
    shas = fields.get("sha256") if isinstance(fields.get("sha256"), dict) else {}
    wanted = (f"{time}/{field}", *MESH)
    missing = [rel for rel in wanted if not shas.get(rel)]
    if not stage or not time or missing:
        ctx.note(f"the summary of this result names no {', '.join(missing) or 'solved case'}: "
                 f"`nopekit check --force --only {GATE}` runs it again")
        return None
    bound = ctx.bind({f"{stage}/{rel}": shas[rel] for rel in wanted})
    if bound is None:
        return None
    case = os.path.join(work, "case")
    for rel in wanted:
        with open(bound[f"{stage}/{rel}"], "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != shas[rel]:
            ctx.note(f"{rel} moved while it was copied: `nopekit check --force --only {GATE}` "
                     f"solves it again")
            return None
        target = os.path.join(case, *rel.split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "wb") as fh:
            fh.write(data)
    os.makedirs(os.path.join(case, "system"), exist_ok=True)
    with open(os.path.join(case, "system", "controlDict"), "w", encoding="utf-8") as fh:
        fh.write(CONTROL_DICT)
    return case, time


def _still(ctx, view_id: str, kind: dict, scale_of, caption: str, alt: str):
    """One still: the summary, its scale, the bound case, a checked ParaView,
    one pvbatch run of ``_scene.py``, and the PNG through ``write_asset``.

    A ParaView this pack cannot use (none, an unchecked build, a failed
    renderer control, a run past its time) leaves the still out with a
    warning; a run that did not finish as asked, or that applied another
    preset than the legend's, raises (an error of the picture). Neither moves
    a status."""
    summary = _summary(ctx)
    if summary is None:
        return None
    scale = scale_of(summary)
    if scale is None:
        ctx.note(f"the summary of this result holds no range for the {kind['quantity']}")
        return None
    planes = [p for p in summary.get("planes") or () if isinstance(p, dict)]
    levels = [lv for lv in summary.get("levels") or () if isinstance(lv, dict)]
    cells = levels[-1].get("cells") if levels else None
    with tempfile.TemporaryDirectory(prefix="nopekit-cfd-still-") as work:
        found = _case(ctx, summary, kind["field"], work)
        if found is None:
            return None
        case, time = found
        try:
            inst = _pv.ready(ctx.root)
        except _pv.Unavailable as exc:
            ctx.note(f"{exc}. {_pv.NO_PICTURES} {_pv.SEE}")
            return None
        png = "still.png"
        job = {"case": case, "time": time, "field": kind["field"],
               "range": [scale["lo"], scale["hi"]], "preset": _scales.PRESET,
               "over": list(_scales.OVER), "under": list(_scales.UNDER),
               "planes": [{"point": p.get("point"), "normal": p.get("normal")} for p in planes],
               "width": _scales.WIDTH_PX, "min_height": _scales.MIN_HEIGHT_PX,
               "line_px": _scales.LINE_PX, "ticks": _scales.TICK_BINS, "png": png}
        try:
            result = _pv.run(inst, SCENE, job, os.path.join(work, "run"))
        except _pv.Unavailable as exc:
            ctx.note(f"{exc}. {_pv.NO_PICTURES}")
            return None
        if result.get("preset_sha256") != _scales.preset_sha256():
            raise _pv.RunError(f"pvbatch applied a {_scales.PRESET} preset that is not "
                               f"views/viridis.json, so the legend would not be the colours of "
                               f"the picture: export it again (views/_export_preset.py)")
        with open(os.path.join(work, "run", png), "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != result.get("png_sha256"):
            raise _pv.RunError("the PNG on disk is not the one pvbatch's result names")
        marks = [m for m in result.get("marks") or () if isinstance(m, dict)]
        if len(marks) != len(planes) or not all(
                _number(m.get("at")) and 0 < m["at"] < 1 for m in marks):
            raise _pv.RunError(f"pvbatch placed {len(marks)} plane lines in the picture for "
                               f"{len(planes)} planes")
        src = ctx.write_asset(f"{view_id.rsplit('.', 1)[-1]}.png", data)
    scale = _scales.with_ticks(scale, result.get("ticks") or (), result.get("tick_texts") or ())
    words = [PLANE_WORDS[i] if i < len(PLANE_WORDS) else f"plane {i + 1}"
             for i in range(len(marks))]
    return View(id=view_id, kind=ViewKind.IMAGE, src=src,
                meta={"caption": caption.format(cells=cells), "alt": alt, "scale": scale,
                      "marks": [{"at": m["at"], "text": w} for m, w in zip(marks, words)],
                      "tool": {"identity": inst.identity, "accepted_by": inst.accepted_by}})


@viewgen(id="cfd-openfoam.speed", kind=ViewKind.IMAGE, title="The speed of the flow",
         description=PICTURE_PROVENANCE, evidence_of=GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=20)
def speed(ctx):
    """|U| on the finest mesh, from OpenFOAM's own ``mag(U)``."""
    return _still(ctx, "cfd-openfoam.speed", _scales.SPEED, _scales.speed, SPEED_CAPTION,
                  SPEED_ALT)


@viewgen(id="cfd-openfoam.pressure", kind=ViewKind.IMAGE, title="The static pressure",
         description=PICTURE_PROVENANCE, evidence_of=GATE, recipe=RECIPE,
         requires_tools=[_pv.WRAPPER], order=30)
def pressure(ctx):
    """Static p in Pa on the finest mesh, from OpenFOAM's own ``static(p)``
    (the ``pressure`` function object, rho the project's density)."""
    return _still(ctx, "cfd-openfoam.pressure", _scales.PRESSURE, _scales.pressure,
                  PRESSURE_CAPTION, PRESSURE_ALT)
