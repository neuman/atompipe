# SPDX-License-Identifier: Apache-2.0
"""cfd-openfoam's figures: charts bound to cfd.pressure_drop's verdict entry.

    cfd-openfoam.ladder   the pressure drop on each mesh against its cell size,
                          the Richardson value at zero cell size and the GCI band
    cfd-openfoam.settle   how much the pressure drop changed at each iteration,
                          on each mesh, with the tolerance and each estimate

**Every number is the run's.** Each chart is a payload of numbers that
cfd.pressure_drop wrote into its evidence (``summary.json`` and the
``history_level{k}.csv`` files), read here and never computed: the spine
refuses a chart number that no verified evidence file of the entry holds, and
a chart that holds a limit. The spine adds the claim's limit line and the
judged point from the floor, and bakes the whole Vega-Lite spec (GitHub #15,
Phase 1); this module draws nothing. What slipped through before Phase 1: a
chart took its margin from the view's own limit, so a pack limit beside the
claim's was a second limit on the page.

**No tool.** Both charts need only the evidence, so they are on the page
wherever cfd.pressure_drop ran, ParaView or not. The stills and the 3D view
(Phase 2, P2.3 and P2.4) need pvbatch, found and checked by `_pv.py`.

**Captions** are site text (ASD-STE100) and say what the chart shows, never a
status: the chips beside the figure say that. "Open" is a status word, so the
Richardson point is "the circle with no fill".
"""
from __future__ import annotations

import csv
import importlib.util
import json
import math
import os
import sys

from nopekit.models import View, ViewKind
from nopekit.site import viewgen

GATE = "cfd.pressure_drop"


def _load_pv():
    """``views/_pv.py`` under a name of this pack's own: the loader puts the
    pack root on ``sys.path``, not ``views/``, and a bare ``import _pv`` would
    take another pack's ``_pv`` if one were first."""
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

#: ``nopekit doctor``'s row for the tool the stills and the 3D view draw with:
#: found or not, the ParaView build, and its renderer control
#: (``_pv.doctor_check``). It runs ``pvbatch --version`` and runs no control.
TOOL_CHECKS = {_pv.WRAPPER: _pv.doctor_check}

#: What the page says each chart is drawn from (the ViewSpec description, the
#: figure's provenance line).
PROVENANCE = "OpenFOAM solved each mesh. The chart shows the numbers of that run."

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
