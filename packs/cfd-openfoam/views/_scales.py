# SPDX-License-Identifier: Apache-2.0
"""The colour scales of cfd-openfoam's stills: pack constants times a value
cfd.pressure_drop wrote into its summary (GitHub #15, design B.3.4).

One scale object gives both the colours of the pixels (``_scene.py`` colours
the cells on its ``lo`` and ``hi``) and the page's HTML legend (its
``stops``, ``ticks`` and words), so the two cannot disagree. Standard library
only.

**The colours are ParaView's.** The map is ParaView 6.2's ``Viridis`` preset
(matplotlib's viridis), applied by name in the scene. The legend's stops come
from ``viridis.json``, the preset as ParaView exported it
(``_export_preset.py`` says how it was made), never from colours typed here;
the scene reports the sha256 of the preset it applied, and ``flow.py`` draws
nothing unless it is this file's. What slipped through the design's first
draft: five viridis stops typed by hand, a second copy of the map that
nothing held to the pixels.

**No end is a limit.** ``lo`` and ``hi`` are the factors below times values
of the summary, and ``source`` names each value and its factor for each end:
``lo = sum(source[i].lo * summary[source[i].key])``, and the same for ``hi``.
A claim's limit never reaches a viewgen (the spine withholds it), and the
spine refuses an end equal to a limit of a claim the gate covers: a colour
keyed to the limit would be a second verdict on the claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: ParaView 6.2's name for matplotlib's viridis: perceptually uniform, and
#: readable with the common colour-vision deficiencies. Measured: ParaView 6.2
#: has no preset named "Viridis (matplotlib)", the name of older versions, and
#: ``ApplyPreset`` raises on it. *Rejected:* "Cool to Warm", ParaView's
#: default (a diverging map: its white middle reads as a zero the field does
#: not have); "Jet"/"Rainbow" (not uniform: bands that are not in the field).
PRESET = "Viridis"
#: The preset as ParaView 6.2.0 exported it, byte for byte.
PRESET_FILE = os.path.join(HERE, "viridis.json")
#: Past the top of the scale: magenta, as no viridis colour is near it.
#: Below the bottom: grey. NaN draws as past the top. *Rejected:* the end
#: colours (a value past the scale would look like a value at its end, which
#: hides it; the renderer control fails a renderer that does this).
OVER = (255, 0, 255)
UNDER = (128, 128, 128)
#: The legend's gradient takes every 4th of the preset's 256 points (and the
#: last): 65 stops. Measured against the whole table, with each stop rounded
#: to a byte as CSS takes it: at most 0.72 of a byte off in any channel at any
#: point. *Rejected:* all 256 (about 10 KB a still in page.json, and each
#: claim the gate covers carries both stills: 12 copies on the baseline);
#: every 8th (1.7 off); every 16th (4.9 off).
STOP_EVERY = 4

#: |U| on [0, SPEED_FACTOR * u_upstream_m_s]. ``u_upstream_m_s`` is the mean
#: speed through the upstream plane, which cfd.converged holds equal to the
#: stated ``cfd_velocity_m_s``. Laminar flow between plates peaks at 1.5
#: times its mean, in a round pipe at 2.0 times, so the core of a developed
#: flow is inside the scale and a jet or a separation faster than 2 times the
#: mean is magenta. Measured on the baseline: 0.00075 to 0.01498 m/s on
#: [0, 0.02]. *Rejected:* absolute m/s constants (they fit the baseline only:
#: another project's flow is all one colour or all magenta); ParaView's
#: automatic range (a value past the scale never shows, and a colour means
#: another value on each run); ``cfd_velocity_m_s`` read live (a new
#: parameter read would re-key cfd.pressure_drop for a picture).
SPEED_FACTOR = 2.0

#: Static p on [p_down + PRESSURE_LO * dp, p_down + PRESSURE_HI * dp], with
#: dp = p_up - p_down the measured pressure drop between the planes. Measured
#: on the baseline (8000 cells): p_down - 0.50 dp at the outlet, p_down + 1.48
#: dp across the inlet, and 6 cells past the top, the inlet's corners to
#: p_down + 2.62 dp, where the uniform inlet meets the walls. That corner rise
#: grows as the mesh is refined, so no fixed top holds it: those cells are
#: magenta, and the legend says what magenta is. *Rejected:* [-0.25, 1.25]
#: (both ends of the baseline out of the scale); [-1, 3] (holds this mesh's
#: corners with half the scale for the rest, and a finer mesh passes it
#: again); an anchor on the dynamic pressure (the ratio of a laminar dp to
#: half rho U^2 changes with Re, so no one factor fits); the claim's limit
#: (the colour would be a second verdict).
PRESSURE_LO, PRESSURE_HI = -1.0, 2.0

#: The still is 1600 px wide, and as high as the cut's aspect makes it (160 px
#: for the baseline's 10 to 1 channel), but not less than MIN_HEIGHT_PX.
#: 1600 px puts 7.6 px across each of the finest baseline cells (0.5 mm of a
#: 105 mm frame), so each cell is a block of its own colour and its centre
#: pixel can be read (the colour-truth test reads every cell). *Rejected:*
#: 800 px (3.8 px a cell: a plane's line covers two cells); a fixed height
#: (a long channel would be a line, and a square case a band).
WIDTH_PX = 1600
MIN_HEIGHT_PX = 64
#: Each measuring plane's line, in px (B.3.3: at least 6 px at 1600 px wide).
#: Measured: 6 drew 6 px wide.
LINE_PX = 6
#: At most this many intervals between the legend's ticks (matplotlib's
#: ``MaxNLocator``, in the scene). Measured on the baseline: 5 ticks for the
#: speed (0 to 0.02 by 0.005), 3 for the pressure (0 to 1 by 0.5).
TICK_BINS = 5

#: What the legend calls the two quantities, and their units.
SPEED = {"quantity": "speed", "units": "m/s", "field": "mag(U)"}
PRESSURE = {"quantity": "static pressure", "units": "Pa", "field": "static(p)"}


def preset_sha256() -> str:
    """The sha256 of ``viridis.json``: what the scene's preset must be."""
    with open(PRESET_FILE, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _hex(colour) -> str:
    return "#" + "".join(f"{int(c):02x}" for c in colour)


def stops() -> list[dict]:
    """The legend's gradient: ``[{"at", "colour"}]`` from the exported
    preset's RGBPoints (x in [0, 1], then r, g, b in [0, 1]), each colour
    rounded to a byte."""
    with open(PRESET_FILE, encoding="utf-8") as fh:
        points = json.load(fh)["RGBPoints"]
    rows = [points[i:i + 4] for i in range(0, len(points), 4)]
    keep = sorted(set(range(0, len(rows), STOP_EVERY)) | {len(rows) - 1})
    return [{"at": float(rows[i][0]),
             "colour": _hex(round(255 * c) for c in rows[i][1:4])} for i in keep]


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _short(value: float) -> str:
    return f"{value:.3g}"


def _scale(kind: dict, summary: dict, source: list[dict], *, over_word: str,
           under_word: str, source_text: str, under: bool) -> dict | None:
    if not all(_number(summary.get(s["key"])) for s in source):
        return None
    lo = sum(s["lo"] * summary[s["key"]] for s in source)
    hi = sum(s["hi"] * summary[s["key"]] for s in source)
    if not (_number(lo) and _number(hi) and hi > lo):
        return None
    return {"quantity": kind["quantity"], "units": kind["units"], "lo": lo, "hi": hi,
            "stops": stops(), "over": _hex(OVER), "under": _hex(UNDER) if under else "",
            "over_word": over_word.format(hi=_short(hi), units=kind["units"]),
            "under_word": under_word.format(lo=_short(lo), units=kind["units"]),
            "ticks": [], "source": source, "source_text": source_text}


def speed(summary: dict) -> dict | None:
    """The scale of |U|, or None when the summary has no upstream speed above
    zero. It has no under colour on the legend: no speed is less than 0 (the
    lookup table keeps grey there all the same)."""
    return _scale(SPEED, summary, [{"key": "u_upstream_m_s", "lo": 0.0, "hi": SPEED_FACTOR}],
                  over_word="faster than {hi} {units}", under_word="", under=False,
                  source_text=("The scale is from 0 to two times the mean speed through the "
                               "upstream plane."))


def pressure(summary: dict) -> dict | None:
    """The scale of static p, or None when the summary has no pressure on a
    plane or no drop between them."""
    return _scale(PRESSURE, summary,
                  [{"key": "p_down_pa", "lo": 1.0 - PRESSURE_LO, "hi": 1.0 - PRESSURE_HI},
                   {"key": "p_up_pa", "lo": PRESSURE_LO, "hi": PRESSURE_HI}],
                  over_word="more than {hi} {units}", under_word="less than {lo} {units}",
                  under=True,
                  source_text=("The scale is from one pressure drop below the pressure on the "
                               "downstream plane to two pressure drops above it."))


def with_ticks(scale: dict, values, texts) -> dict:
    """``scale`` with the scene's ticks: ``[{"at", "value", "text"}]``, ``at``
    the tick's place on the gradient from 0 to 1."""
    lo, hi = scale["lo"], scale["hi"]
    ticks = [{"at": (v - lo) / (hi - lo), "value": v, "text": str(t)}
             for v, t in zip(values, texts) if _number(v) and lo <= v <= hi]
    return {**scale, "ticks": ticks}
