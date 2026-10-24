# SPDX-License-Identifier: Apache-2.0
"""The colour scales, cameras and sizes of aero-openfoam's pictures: pack
constants, times at most one value aero.converged wrote into its summary (the
free-stream speed). Standard library only.

One scale object gives both the colours of the pixels (``_scene3d.py``
colours the surfaces and lines on its ``lo`` and ``hi``) and the page's HTML
legend (its ``stops``, ``ticks`` and words), so the two cannot disagree. A
figure with two scales (the hero: Cp on the body, speed on the tracks) states
them as ``scales``, each ``on`` a surface or lines (design P2).

**The colours are ParaView's.** The map is ParaView 6.2's ``Turbo`` preset,
applied by name in the scene. The legend's stops come from ``turbo.json``, the
preset as ParaView exported it (``_export_preset.py``), never from colours
typed here; the scene reports the sha256 of the preset it applied, and
``flow3d.py`` draws nothing unless it is this file's.

**No end is a limit.** ``lo`` and ``hi`` are the constants below, or a
factor times a value of the summary, and ``source`` names each value and its
factor: ``lo = sum(source[i].lo * summary[source[i].key])``, and the same for
``hi``; a scale with no ``source`` is the constants alone. A claim's limit
never reaches a viewgen (the spine withholds it), and the spine refuses an end
equal to a limit of a claim the gate covers.

**Turbo for 3D only.** cfd-openfoam's 2D stills keep Viridis. *Rejected:*
Viridis here (the author's choice of 2026-10-22: the 3D pictures read as the
CFD pictures people know); Jet and Rainbow (lightness that is not monotone
draws bands the field does not have); Cool to Warm (a second map on one
page). Turbo is not perceptually uniform either, so each legend carries its
values as ticks.
"""
from __future__ import annotations

import hashlib
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))

#: ParaView 6.2's ``Turbo`` (Anton Mikhailov's map, 256 points, RGB).
PRESET = "Turbo"
#: The preset as ParaView 6.2.0 exported it, byte for byte (sha256
#: ``05f02e23...c94f``).
PRESET_FILE = os.path.join(HERE, "turbo.json")
#: Past the top of a scale magenta, below the bottom grey, NaN magenta: no
#: Turbo colour is near either. Turbo has no NanColor, and ParaView's default
#: NaN colour on this table reads as one of its greens (measured).
#: *Rejected:* the end colours (a value past the scale would read as a value at
#: its end; the renderer control fails a renderer that does this).
OVER = (255, 0, 255)
UNDER = (128, 128, 128)
#: The legend's gradient takes every 4th of the preset's 256 points (and the
#: last): 65 stops. Measured against the whole table, linear in RGB as the
#: preset and a CSS gradient both are, each stop rounded to a byte: at most
#: 0.95 of a byte off in any channel at any point. *Rejected:* all 256 (about
#: 10 KB a scale in page.json, two scales on the hero, and each claim the gate
#: covers carries every figure); every 8th (2.3 off).
STOP_EVERY = 4

#: Cp on [-1.5, 1.05], OpenFOAM's ``static(p)_coeff`` (the ``pressure`` function
#: object, mode staticCoeff, pInf 0, the free-stream speed and rhoInf 1): a
#: pack constant, no summary value, as OpenFOAM did the arithmetic. 1 is the
#: stagnation value. Measured on the motorBike's L0 body (P0): point Cp -2.73
#: to 0.98, 0.10% of the area below -1.5, which draws grey and the legend
#: names. The top is 1.05, not 1: what slipped through the two branches
#: (merged 2026-10-23) is that 1.0 is also aero.converged's own default
#: ceiling (``aero_iter_unc_max_pct``, 1%), its verdict limit, and the spine
#: refuses a colour range with an end equal to a limit of the entry (a colour
#: range taken from a limit): on the motorBike demo's first build the hero and
#: the Cp still were refused, while the tests, which held the ends against C1's
#: 0.35 alone, stayed green. 1.05 still holds the stagnation value with no
#: magenta. *Rejected:* [-1.5, 1] (above); [-1, 1] (the design's first choice:
#: 0.78% of the area grey, the helmet's and the arms' suction peaks lost);
#: [-3, 1] (no grey, but Cp 0 sits at 0.75 of the ramp and the whole body reads
#: one orange, ``hero_speed_0_2.0.png``); [-2, 1] (one yellow-green body).
CP_RANGE = (-1.5, 1.05)
#: |U| on the tracks, on [0, 2.0] times the summary's ``u_inf_m_s``: the free
#: stream sits at the middle of the ramp (green), the wake reads blue, and
#: nothing measured lies past the top. Measured on OpenFOAM's tracks at L0
#: (P0): at most 1.38 U_inf, 31% of the points within 10% of U_inf. The wake
#: surface has its own range (`WAKE_SPEED_FACTORS`). *Rejected:* (0, 1.3)
#: (the free stream at 0.77 of the ramp: the
#: tubes drew one orange, ``hero_speed_0_1.3.png``); (0.4, 1.6) (grey wake
#: segments, ``hero_speed_0.4_1.6.png``); absolute m/s (fits one speed only);
#: a ratio |U|/U_inf on the legend (a division the pack would compute: the
#: ticks are values of OpenFOAM's ``mag(U)`` in m/s).
SPEED_FACTORS = (0.0, 2.0)
#: |U| on the wake surface (CpT = 0), on [0, 1.0] times ``u_inf_m_s``: from
#: air at rest to the free stream. Measured on the demo's L0 wakeIso.vtp
#: (2026-10-23, area-weighted): median 6.3 m/s, 95% below 11.0 m/s, 99% below
#: 14.4 m/s, at most 20.3 m/s at U_inf 20, and less than 0.01% of the area above U_inf,
#: which draws magenta and the legend names. What slipped through P3-P5
#: (review, 2026-10-23): the wake took the tracks' (0, 2.0), so 95% of the
#: surface sat in the lowest 27% of the ramp, and the picture read as one
#: blue shape whose light and shade moved its colours more than its speeds
#: did (the P0 note "at most 1.32 U_inf on the wake surface" was not
#: measured on this surface). *Rejected:* (0, 2.0) (above); (0, 0.6) (5% of
#: the area magenta); a range from the run's own values (a scale that moves
#: with each result, and a number the pack would compute).
WAKE_SPEED_FACTORS = (0.0, 1.0)
#: CpT on [-0.2, 1.05], OpenFOAM's ``total(p)_coeff``: 1 is air with all of its
#: free-stream energy, 0 the edge of the wake surface. Measured on the L0
#: cuts: -0.115 to 1.040, so 1.05 holds the top with no magenta. *Rejected:*
#: [-0.2, 1] (its top is aero.converged's default verdict limit, 1%, and the
#: spine refuses the cuts whole: see `CP_RANGE`); [0, 1] (the cut through the
#: seat's wake holds values below 0: grey patches).
CPT_RANGE = (-0.2, 1.05)
#: The cuts hide the air with CpT above this: the free stream, which would fill
#: each plane from wall to wall in one red. A drawing choice, which the caption
#: states. Measured on L0: kept 310, 275 and 307 cells of about 1330 a cut.
#: *Rejected:* 1.0 (numerical CpT a little over 1 left speckle at the plane's
#: edges); Threshold (whole cells: blocky edges, ``d_wake_slices.png``).
CPT_CUT_CLIP = 0.95
#: y+ in four bands, edges 5, 30 and 300: the viscous sublayer (y+ < 5), the
#: buffer layer (5 to 30) and the log layer (30 to 300) of a smooth wall (Pope,
#: Turbulent Flows, 2000, sec. 7.1.4), the last edge the wall-treatment guard's
#: own (y+ <= 300). Each band one Turbo colour, the preset's colour at the
#: middle of the band's quarter of the ramp (`BAND_AT`), drawn flat: a band is
#: a fact about the wall model, not a value to read off a ramp. *Rejected:* a
#: continuous log scale (the eye reads the band edges, not 87 or 120); bands
#: of equal ratio (the physics' edges are 5, 30 and 300).
YPLUS_BANDS = (0.0, 5.0, 30.0, 300.0)
BAND_AT = (0.125, 0.375, 0.625, 0.875)

#: The cameras, in the body's box (length L along the flow, +x; width W; height
#: H, up +z): the focal point is the box centre plus ``focal`` times (L, W, H);
#: the camera sits ``distance_diag`` box diagonals from it, ``azimuth_deg``
#: from the flow direction toward +y, ``elevation_deg`` above the ground.
#: The hero's is the design's d_hero3 recast on the box (P0: within 2 cm of
#: d_hero3's): from the front and the left, a 3/4 view, the tracks running
#: across the picture. *Rejected:* a side view (the tracks cross the body and
#: hide it); the horizontal rake's view (``hero_cull_grad.png``: a sheet
#: through the bike).
HERO_CAMERA = {"focal": [0.11, 0.0, -0.06], "azimuth_deg": -138.0, "elevation_deg": 13.0,
               "distance_diag": 1.76, "view_angle_deg": 27.0}
#: The body alone (Cp, y+): the hero's direction, aimed near the box centre
#: and nearer, so the body fills the picture. Measured: at the hero's camera
#: the body filled the left half and the right half was empty (the tracks fill
#: it on the hero); at 1.15 and 1.4 diagonals the front wheel, nearest the
#: camera, ran off the bottom.
BODY_CAMERA = {"focal": [0.0, 0.0, -0.08], "azimuth_deg": -138.0, "elevation_deg": 13.0,
               "distance_diag": 1.55, "view_angle_deg": 27.0}
#: The wake surface, from behind and from the left of the bike: the surface
#: runs back from the rider toward the camera. The bike faces -x and +z is up,
#: so its left is -y, where a negative azimuth puts the camera (as the hero's).
#: What slipped through P3-P5 (review, 2026-10-23): this comment and the alt
#: text said "from the right"; a camera moved to match them would mirror the
#: picture. From the design's wake.py, brought nearer (1.6 diagonals, not
#: 1.87).
WAKE_CAMERA = {"focal": [0.3, 0.0, -0.1], "azimuth_deg": -42.0, "elevation_deg": 20.0,
               "distance_diag": 1.6, "view_angle_deg": 30.0}
#: The three cuts, from behind and from the left, far enough that the third
#: cut (2.3 L behind the box centre on the motorBike) is in the picture.
#: *Rejected:* the design's first frame (the third cut out of the picture,
#: ``d_wake_slices.png``); 55 degrees from the flow (each cut seen nearly edge
#: on).
CUTS_CAMERA = {"focal": [1.0, 0.0, -0.1], "azimuth_deg": -35.0, "elevation_deg": 22.0,
               "distance_diag": 2.4, "view_angle_deg": 30.0}

#: The two rakes that seed OpenFOAM's ``streamLine`` tracks, in the body's box,
#: as the hero draws them (P0, ``tracksCentre`` and ``tracksFar``): a line of
#: ``points`` seeds from ``start`` to ``end``, each a fraction of (L, W, H)
#: from the box's minimum corner, x before the box. The centre rake rises
#: through the middle of the bike; the far one runs beside its far side. The
#: gate seeds its function objects from its own copy (``gates/_fo.RAKES``: a
#: pack's views/ and gates/ load nothing from each other), and
#: ``TheViewsReadWhatTheGateWrites`` holds the two equal on two boxes, so the
#: picture's tracks are where this file says. *Rejected:* a horizontal rake
#: (``hero_cull_grad.png``: a flat sheet through the bike) and a near-side rake
#: (it hid the body, ``d_hero.png``). Measured on L0: 60 + 18 tracks, 68 441
#: points. (P0 seeded the centre rake about y = 0, 9 mm from the middle of the
#: motorBike's box; here it is about the box's middle, so a body off y = 0
#: keeps its rake.)
RAKES = {
    "tracksCentre": {"start": [-0.08, 0.45, 0.04], "end": [-0.08, 0.55, 1.07], "points": 60},
    "tracksFar": {"start": [-0.08, 0.91, 0.04], "end": [-0.08, 0.985, 0.89], "points": 18},
}

#: The stream tubes: radius 0.0022 L (4.5 mm on the bike), 10 sides. At 1600
#: px a tube is about 4 px across, and at a phone's 358 px figure width at
#: least 1 CSS px (``d_hero3_phone2x.png``). *Rejected:* 0.001 L (gone on a
#: phone); 0.005 L (the tubes hid the body).
TUBE = {"radius_l": 0.0022, "sides": 10}
#: The hero's 3D file: the body triangulated and decimated by 0.75, the tracks
#: decimated by 0.95 and drawn as 4-sided tubes. Measured on L0 (P0): 1.50 MB
#: with all 78 tracks, under the 2 MiB cap. *Rejected:* track decimation 0.8
#: (the design's: 3.69 MB) and 0.9 (2.23 MB); fewer tracks (the 3D view would
#: not be the still's flow).
GLTF = {"body_reduction": 0.75, "track_reduction": 0.95, "sides": 4}

#: Every picture is 1600 x 1000: the stills' width (cfd-openfoam), 16:10 for a
#: card. Measured: 1.1 to 1.2 MB a PNG at L0, under the 2 MiB cap.
SIZE = (1600, 1000)
#: At most this many intervals between a legend's ticks (matplotlib's
#: ``MaxNLocator``, in the scene): Cp -1.5 to 1 by 0.5, speed 0 to 40 by 10.
#: *Rejected:* 5 (with Cp's top at 1.05 the locator's 0.5 steps need six
#: intervals, and it fell back to steps of 1: a legend of -1, 0 and 1 only,
#: measured 2026-10-23).
TICK_BINS = 6

#: How the lit pictures look (design 6.1, each measured on d_hero3): the light
#: kit's key light at warmth 0.5 (white: the hue survives the light), FXAA on
#: (the hero and the wake; the scene draws the others without it, so each
#: coloured pixel is a colour of the key), a sky from white to (0.80, 0.85, 0.91), a floor of grey
#: 0.9 (ambient 0.25, diffuse 0.75) from 5 L before the body to 10 L behind
#: it and 5 L to each side, so its far edge is on the horizon, the body grey
#: 0.78 where it is not coloured. *Rejected:* SSAO (it whitened the sky and
#: added grain); tone mapping (it moved every colour); shadows (no OSPRay in
#: the build).
LOOK = {"key_light_warmth": 0.5, "fxaa": True,
        "background": [1.0, 1.0, 1.0], "background2": [0.80, 0.85, 0.91],
        "floor": {"upstream_l": 5.0, "downstream_l": 10.0, "side_l": 5.0, "grey": 0.9,
                  "ambient": 0.25, "diffuse": 0.75},
        "body_grey": 0.78, "body_specular": 0.3,
        "specular": {"body": [0.35, 50.0], "tubes": [0.3, 40.0], "wake": [0.25, 30.0]}}

#: What the legend calls each quantity, its units, and OpenFOAM's field.
CP = {"quantity": "pressure coefficient Cp", "units": "", "field": "static(p)_coeff"}
SPEED = {"quantity": "air speed", "units": "m/s", "field": "mag(U)"}
CPT = {"quantity": "total pressure coefficient CpT", "units": "", "field": "total(p)_coeff"}
YPLUS = {"quantity": "wall value y+", "units": "", "field": "yPlus"}


def preset_sha256() -> str:
    """The sha256 of ``turbo.json``: what the scene's preset must be."""
    with open(PRESET_FILE, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _hex(colour) -> str:
    return "#" + "".join(f"{int(c):02x}" for c in colour)


def _rows() -> list[list[float]]:
    with open(PRESET_FILE, encoding="utf-8") as fh:
        points = json.load(fh)["RGBPoints"]
    return [points[i:i + 4] for i in range(0, len(points), 4)]


def stops() -> list[dict]:
    """The legend's gradient: ``[{"at", "colour"}]`` from the exported
    preset's RGBPoints, each colour rounded to a byte."""
    rows = _rows()
    keep = sorted(set(range(0, len(rows), STOP_EVERY)) | {len(rows) - 1})
    return [{"at": float(rows[i][0]),
             "colour": _hex(round(255 * c) for c in rows[i][1:4])} for i in keep]


def preset_colour(at: float) -> tuple[int, int, int]:
    """The exported preset's colour at ``at`` in [0, 1]: the two points
    either side, linear in RGB (the preset's ColorSpace), each channel rounded
    to a byte. What a band's colour on the legend is."""
    rows = _rows()
    at = min(max(float(at), rows[0][0]), rows[-1][0])
    k = next(j for j in range(len(rows) - 1) if rows[j][0] <= at <= rows[j + 1][0])
    span = rows[k + 1][0] - rows[k][0]
    f = (at - rows[k][0]) / span if span else 0.0
    return tuple(int(round(255 * (a + (b - a) * f)))
                 for a, b in zip(rows[k][1:4], rows[k + 1][1:4]))


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) \
        and math.isfinite(value)


def _short(value: float) -> str:
    return f"{value:.3g}"


def _ramp(kind: dict, lo: float, hi: float, source: list[dict], *, over_word: str,
          under_word: str, source_text: str, under: bool) -> dict | None:
    if not (_number(lo) and _number(hi) and hi > lo):
        return None
    return {"quantity": kind["quantity"], "units": kind["units"], "lo": lo, "hi": hi,
            "stops": stops(), "over": _hex(OVER), "under": _hex(UNDER) if under else "",
            "over_word": over_word.format(hi=_short(hi), units=kind["units"]).strip(),
            "under_word": under_word.format(lo=_short(lo), units=kind["units"]).strip(),
            "ticks": [], "source": source, "source_text": source_text}


def cp(summary: dict | None = None) -> dict | None:
    """The scale of Cp on the body: `CP_RANGE`, constants alone."""
    return _ramp(CP, CP_RANGE[0], CP_RANGE[1], [],
                 over_word="more than {hi}", under_word="less than {lo}", under=True,
                 source_text="At Cp = 1, the air stops on the surface. The scale is the same "
                             "for each design.")


def speed(summary: dict) -> dict | None:
    """The scale of |U| on [0, 2] times the summary's free-stream speed, or
    None when the summary has none above zero. No under colour on the legend:
    no speed is less than 0."""
    u = summary.get("u_inf_m_s") if isinstance(summary, dict) else None
    if not (_number(u) and u > 0):
        return None
    source = [{"key": "u_inf_m_s", "lo": SPEED_FACTORS[0], "hi": SPEED_FACTORS[1]}]
    return _ramp(SPEED, SPEED_FACTORS[0] * u, SPEED_FACTORS[1] * u, source,
                 over_word="faster than {hi} {units}", under_word="", under=False,
                 source_text="The scale is from 0 to two times the speed of the air far "
                             "from the bike.")


def wake_speed(summary: dict) -> dict | None:
    """The scale of |U| on the wake surface: `WAKE_SPEED_FACTORS` times the
    summary's free-stream speed, or None when the summary has none above
    zero."""
    u = summary.get("u_inf_m_s") if isinstance(summary, dict) else None
    if not (_number(u) and u > 0):
        return None
    source = [{"key": "u_inf_m_s", "lo": WAKE_SPEED_FACTORS[0], "hi": WAKE_SPEED_FACTORS[1]}]
    return _ramp(SPEED, WAKE_SPEED_FACTORS[0] * u, WAKE_SPEED_FACTORS[1] * u, source,
                 over_word="faster than {hi} {units}", under_word="", under=False,
                 source_text="The scale is from 0 to the speed of the air far from the "
                             "bike.")


def cpt(summary: dict | None = None) -> dict | None:
    """The scale of CpT on the wake cuts: `CPT_RANGE`, constants alone."""
    return _ramp(CPT, CPT_RANGE[0], CPT_RANGE[1], [],
                 over_word="more than {hi}", under_word="less than {lo}", under=True,
                 source_text="At CpT = 1, the air has all of its energy. The scale is the "
                             "same for each design.")


def yplus(summary: dict | None = None) -> dict:
    """The y+ bands as a key: each band's colour flat over its quarter of the
    bar (two stops at each edge), a tick at each inner edge. No ``lo`` or
    ``hi``: the bar is not a linear scale, so it states no ends."""
    colours = [_hex(preset_colour(at)) for at in BAND_AT]
    edges = [i / len(colours) for i in range(len(colours) + 1)]
    bar = []
    for i, colour in enumerate(colours):
        bar += [{"at": edges[i], "colour": colour}, {"at": edges[i + 1], "colour": colour}]
    ticks = [{"at": edges[i], "value": YPLUS_BANDS[i], "text": f"{YPLUS_BANDS[i]:g}"}
             for i in range(1, len(colours))]
    return {"quantity": YPLUS["quantity"], "units": "", "stops": bar, "over": "", "under": "",
            "over_word": "", "under_word": "", "ticks": ticks, "source": [],
            "source_text":
                "Each colour is one band of y+. The wall model of the solver is made for "
                "the bands below 300."}


#: Every scale this pack draws, by name: what `TheScaleIsAPackConstant` walks,
#: so a scale added here is held to the rule with no test edit.
SCALES = {"cp": cp, "speed": speed, "wake_speed": wake_speed, "cpt": cpt, "yplus": yplus}


def on(scale: dict, where: str) -> dict:
    """``scale`` as one entry of a figure's ``scales``: ``on`` a surface or
    lines."""
    return {**scale, "on": where}


def with_ticks(scale: dict, values, texts) -> dict:
    """``scale`` with the scene's ticks: ``[{"at", "value", "text"}]``, ``at``
    the tick's place on the gradient from 0 to 1."""
    lo, hi = scale["lo"], scale["hi"]
    ticks = [{"at": (v - lo) / (hi - lo), "value": v, "text": str(t)}
             for v, t in zip(values, texts) if _number(v) and lo <= v <= hi]
    return {**scale, "ticks": ticks}


def rakes(bbox) -> dict:
    """``{name: {"start", "end", "points"}}`` in metres for a body box
    ``[xmin, xmax, ymin, ymax, zmin, zmax]``: `RAKES` placed on it."""
    lo = [bbox[0], bbox[2], bbox[4]]
    size = [bbox[1] - bbox[0], bbox[3] - bbox[2], bbox[5] - bbox[4]]
    return {name: {"start": [lo[i] + rake["start"][i] * size[i] for i in range(3)],
                   "end": [lo[i] + rake["end"][i] * size[i] for i in range(3)],
                   "points": rake["points"]}
            for name, rake in RAKES.items()}
