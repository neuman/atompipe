# SPDX-License-Identifier: Apache-2.0
"""aero-openfoam's figures (the motorBike design, P5 and P7): what the site
draws of an external-aero result.

Seven viewgens in ``packs/aero-openfoam/views/flow3d.py``: the hero (the body
by Cp, OpenFOAM's stream tracks as tubes by speed, lit, with its glTF), the
unlit Cp still, the drag area's settling history, the wake surface, the wake
cuts and the bodies of y+ in bands, all bound to aero.converged (the wall to
aero.wall_treatment), and the mesh ladder, bound to aero.mesh_independence.
The gates are another branch's: these tests build each entry's evidence by
hand, in the layout ``flow3d.py``'s docstring names, from small files the real
v2606 wrote on the motorBike's base mesh (``tests/aero_fixtures/views/``).

What these tests hold:

- the shared helpers are cfd-openfoam's: ``views/_pv.py`` byte for byte but
  for `KNOWN` (Turbo's 0.5 colour), ``_control.py``, the strip and the lock;
  and each pack loads its own ``_scales`` in one process;
- every constant of the job is the pack's (Turbo, the colours past the
  scale, the ranges, the bands), each legend is the exported preset's, the
  captions are site text that names the base mesh and holds no number, and
  each figure binds to the gate the design says;
- the charts need no tool, and every number they hold is the evidence's;
- through the stand-in pvbatch (``tests/_pv_standin.py``): each picture binds
  its files by the summary's digests and ParaView reads those copies alone;
  another run's file, an unchecked or missing ParaView, another preset, a PNG
  or a glTF that is not the run's, an empty piece and bands in other colours
  draw nothing, and say why; a glTF over the cap leaves the still;
- on the real ParaView 6.2.0 (``TheRealPictures``): the committed preset is
  ParaView's Turbo, the renderer control passes with Turbo, the unlit stills
  and the unlit twin of the hero hold every pixel to the Turbo ramp within 2
  while a lit twin and a tone-mapped twin fail that check, the lit hero keeps
  the twin's hue, two draws are byte-identical, the hero's glTF has COLOR_0 on
  the ramp, passes the Khronos validator and fits the cap, and the stand-in's
  committed files are what ParaView draws today.

The browser's lit and flat drawing of the hero's glTF is
``test_field_browser.TheBrowserDrawsTheHero``; the scales' rule, over every
scale of this pack, is ``test_figures.TheScaleIsAPackConstant``.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p test_aero_views.py -v
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

import _env
import _pv_standin as pv_standin
from nopekit import cli, page, prose
from nopekit import site as site_mod
from nopekit.models import View, ViewKind

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACK = os.path.join(REPO, "packs", "aero-openfoam")
VIEWS = os.path.join(PACK, "views")
CFD_VIEWS = os.path.join(REPO, "packs", "cfd-openfoam", "views")
FIXTURES = os.path.join(REPO, "tests", "aero_fixtures", "views")
STANDIN = os.path.join(FIXTURES, "standin")
GATE, WALL_GATE, LADDER_GATE = "aero.converged", "aero.wall_treatment", "aero.mesh_independence"
PICTURES = ("aero.hero", "aero.surface_cp", "aero.wake", "aero.wake_cuts", "aero.wall")
CHARTS = ("aero.history", "aero.ladder")
BINDS = {"aero.hero": GATE, "aero.surface_cp": GATE, "aero.history": GATE, "aero.wake": GATE,
         "aero.wake_cuts": GATE, "aero.wall": WALL_GATE, "aero.ladder": LADDER_GATE}
#: The files each picture reads (``flow3d.FILES`` roles).
ROLES = {"aero.hero": ("body", "tracksCentre", "tracksFar"), "aero.surface_cp": ("body",),
         "aero.wake": ("body", "wake"), "aero.wake_cuts": ("body", "cut1", "cut2", "cut3"),
         "aero.wall": ("yplus",)}
#: The base mesh's run time of the fixtures' entry (aero.converged's endTime).
TIME = "500"
#: The free-stream speed of the motorBike (aero_u_inf_m_s).
U_INF = 20.0
#: Typed here so that the colour tests read no code of the pack.
OVER, UNDER = (255, 0, 255), (128, 128, 128)
TURBO_JSON = os.path.join(VIEWS, "turbo.json")


def _views() -> site_mod.ViewRegistry:
    """The pack's views as a build loads them."""
    registry = site_mod.ViewRegistry()
    cli._load_viewgens(VIEWS, registry, pack="aero-openfoam", root=REPO)
    return registry


def _flow3d():
    _spec, fn = _views().get("aero.hero")
    return sys.modules[fn.__module__]


def _pv():
    _views()
    return sys.modules["nopekit_aero_openfoam_pv"]


def _scales():
    _views()
    return sys.modules["nopekit_aero_openfoam_scales"]


def _sha256(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _runs() -> dict:
    with open(os.path.join(FIXTURES, "runs.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _half_range(history, window):
    values = [v for _, v in history[-window:]]
    return 0.5 * (max(values) - min(values))


def make_entries(root: str, *, summary_edit=None) -> dict:
    """The three entries' evidence under ``root``'s ``.nopekit/out``, in the
    layout flow3d.py's docstring names: ``{gate: (BoundEntry, files)}``.
    ``summary_edit(gate, summary)`` may change a summary before it is
    written."""
    from nopekit import store
    out = store.out_dir(root)
    runs = _runs()
    history = runs["cda_history"]
    cells = [lv["cells"] for lv in runs["ladder"]]
    levels = [{"k": k, "cells": c, "h_rel": (cells[-1] / c) ** (1 / 3), "cda_m2": lv["cda_m2"]}
              for k, (c, lv) in enumerate(zip(cells, runs["ladder"]))]
    plan = {GATE: (("body", "tracksCentre", "tracksFar", "wake", "cut1", "cut2", "cut3"),
                   {"u_inf_m_s": U_INF, "ground_z_m": 0.0, "mesh_level": "base",
                    "history": "history.csv", "window": 100,
                    "u_i_m2": _half_range(history, 100)}),
            WALL_GATE: (("yplus",), {}),
            LADDER_GATE: ((), {"levels": levels})}
    files_of = _flow3d().FILES
    entries = {}
    for gate, (roles, extra) in plan.items():
        folder = gate.replace(".", "_")
        run = os.path.join(out, folder)
        shas = {}
        for role in roles:
            rel = files_of[role].format(time=TIME)
            target = os.path.join(run, "case", *rel.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copyfile(os.path.join(FIXTURES, role + ".vtp"), target)
            shas[rel] = _sha256(target)
        summary = {**extra}
        if roles:
            summary["fields"] = {"stage": f"<out>/{folder}/case", "time": TIME, "sha256": shas}
        if gate == GATE:
            summary["cda_history"] = history
        if summary_edit is not None:
            summary_edit(gate, summary)
        os.makedirs(run, exist_ok=True)
        files = {}
        rows = summary.pop("cda_history", None)
        if rows is not None:
            # As aero.converged writes it: a CSV beside summary.json, never a
            # list inside it (the gate's `_history`).
            csv_path = os.path.join(run, "history.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as fh:
                fh.write("iteration,cda_m2\n")
                fh.writelines(f"{it},{v!r}\n" for it, v in rows)
            files[os.path.relpath(csv_path, out).replace(os.sep, "/")] = csv_path
        path = os.path.join(run, "summary.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=1)
        files[os.path.relpath(path, out).replace(os.sep, "/")] = path
        entries[gate] = (site_mod.BoundEntry(gate=gate, name="0" * 16 + "-" + "0" * 8,
                                             fresh=True, files=files), files)
    return entries


def _summary_of(files: dict) -> str:
    """The summary.json among an entry's files (beside it, the history CSV)."""
    return next(p for p in files.values() if p.endswith("summary.json"))


def bound_context(root: str, entries: dict, view_id: str, scratch: str):
    """The BoundContext the spine hands ``view_id``'s viewgen."""
    entry, files = entries[BINDS[view_id]]
    shutil.rmtree(scratch, ignore_errors=True)
    os.makedirs(scratch)
    ctx = site_mod.BoundContext(root=root, entry=entry, scratch=scratch, view_id=view_id)
    ctx.digests = {portable: _sha256(path) for portable, path in files.items()}
    return ctx


def draw(root: str, entries: dict, view_id: str, scratch: str):
    """``(view, note, ctx, refusal)``: the viewgen run as the spine runs it,
    and the spine's refusal of what it returned (D1's limit of 0.35 m^2 among
    the limits it is held to)."""
    spec, fn = _views().get(view_id)
    ctx = bound_context(root, entries, view_id, scratch)
    view, note = site_mod.run_viewgen(spec, fn, ctx)
    refusal = site_mod._figure_refusal(spec, view, ctx, list(LIMITS)) if view is not None else None
    return view, note, ctx, refusal


#: The limits the spine holds every figure's colour ends against
#: (`site._gate_limits`): D1's 0.35 m^2 on C1, and the entry's own verdict limit,
#: aero.converged's default ceiling of 1 (%). What slipped through the two
#: branches: these tests held the ends against 0.35 alone, Cp's and CpT's tops
#: were 1.0, and the demo's first build refused the hero, the Cp still and the
#: cuts as "a colour range taken from a limit".
LIMITS = (0.35, 1.0)


def _turbo_rows():
    with open(TURBO_JSON, encoding="utf-8") as fh:
        pts = json.load(fh)["RGBPoints"]
    return [pts[i:i + 4] for i in range(0, len(pts), 4)]


def turbo_at(t: float) -> tuple[int, int, int]:
    """The exported preset's colour at ``t`` in [0, 1], read here."""
    rows = _turbo_rows()
    k = next(j for j in range(len(rows) - 1) if rows[j][0] <= t <= rows[j + 1][0])
    f = (t - rows[k][0]) / (rows[k + 1][0] - rows[k][0])
    return tuple(round(255 * (a + (c - a) * f)) for a, c in zip(rows[k][1:4], rows[k + 1][1:4]))


def off_ramp(pixels) -> "numpy.ndarray":
    """For each RGB pixel, its distance (the largest channel's, in bytes) to
    the nearest point of the Turbo ramp: the polyline through the exported
    preset's 256 points, read here with no code of the pack."""
    import numpy
    rows = numpy.array(_turbo_rows())[:, 1:] * 255.0
    a, b = rows[:-1][None], rows[1:][None]
    ab = b - a
    out = []
    pixels = numpy.asarray(pixels, dtype=float).reshape(-1, 3)
    for i in range(0, len(pixels), 20000):
        p = pixels[i:i + 20000][:, None, :]
        t = numpy.clip(((p - a) * ab).sum(-1) / numpy.maximum((ab * ab).sum(-1), 1e-12), 0, 1)
        out.append(numpy.abs(p - (a + t[..., None] * ab)).max(-1).min(-1))
    return numpy.concatenate(out) if out else numpy.zeros(0)


def drawn_pixels(png: str, background=(255, 255, 255)):
    """The pixels of ``png`` that are not ``background``, and those of them
    that are not exactly the colour past either end of the scale."""
    import numpy
    from PIL import Image
    with Image.open(png) as image:
        rgb = numpy.asarray(image.convert("RGB")).reshape(-1, 3)
    drawn = rgb[(rgb != numpy.array(background)).any(1)]
    special = (drawn == OVER).all(1) | (drawn == UNDER).all(1)
    return drawn, drawn[~special]


# --------------------------------------------------------------------------- #
# the shared helpers
# --------------------------------------------------------------------------- #
def _masked(path: str, name: str) -> str:
    """``path``'s text with the assignment to ``name`` and the ``#:`` comment
    block above it replaced by one marker line."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    lines = text.splitlines(keepends=True)
    node = next(n for n in ast.parse(text).body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
    first, last = node.lineno - 1, node.end_lineno
    while first > 0 and lines[first - 1].startswith("#:"):
        first -= 1
    return "".join(lines[:first] + [f"<{name}>\n"] + lines[last:])


class TheSharedHelpersHaveNotDrifted(_env.EnvCase):
    """The views' helpers are cfd-openfoam's, copied (design 1: never loaded
    across packs): ``_pv.py`` the same bytes but for `KNOWN` and its comment,
    ``_control.py``, the strip and the lock the same bytes. A fix in one copy
    that misses the other goes red here."""

    def test_pv_is_cfd_openfoams_but_for_the_known_colour(self):
        self.assertEqual(_masked(os.path.join(VIEWS, "_pv.py"), "KNOWN"),
                         _masked(os.path.join(CFD_VIEWS, "_pv.py"), "KNOWN"))

    def test_the_mask_sees_a_change_beside_the_known_colour(self):
        """The control: an edit outside `KNOWN` is not masked."""
        tmp = self.tmp()
        with open(os.path.join(VIEWS, "_pv.py"), encoding="utf-8") as fh:
            text = fh.read()
        planted = os.path.join(tmp, "_pv.py")
        with open(planted, "w", encoding="utf-8") as fh:
            fh.write(text.replace("CONTROL_TOLERANCE = 1", "CONTROL_TOLERANCE = 3"))
        self.assertNotEqual(_masked(planted, "KNOWN"),
                            _masked(os.path.join(CFD_VIEWS, "_pv.py"), "KNOWN"))

    def test_the_control_its_strip_and_the_lock_are_the_same_bytes(self):
        for rel in ("_control.py", "fixture/strip.vtk", "paraview.lock.json"):
            with self.subTest(rel):
                self.assertEqual(_sha256(os.path.join(VIEWS, *rel.split("/"))),
                                 _sha256(os.path.join(CFD_VIEWS, *rel.split("/"))))

    def test_the_known_colour_is_turbos_at_half(self):
        self.assertEqual(_pv().KNOWN, (0.5, turbo_at(0.5)))
        self.assertEqual(_pv().KNOWN[1], (163, 253, 60))

    def test_each_pack_loads_its_own_scales(self):
        """Both packs' views in one process: each ``_pv`` holds its own pack's
        preset, and names its own reference. What slipped through the first
        copy: a module name typed as cfd-openfoam's, so aero's ``_pv`` took
        cfd-openfoam's ``_scales`` (Viridis) when those views loaded first."""
        registry = site_mod.ViewRegistry()
        cli._load_viewgens(CFD_VIEWS, registry, pack="cfd-openfoam", root=REPO)
        cli._load_viewgens(VIEWS, registry, pack="aero-openfoam", root=REPO)
        cfd, aero = sys.modules["nopekit_cfd_openfoam_pv"], sys.modules["nopekit_aero_openfoam_pv"]
        self.assertEqual((cfd.PRESET, aero.PRESET), ("Viridis", "Turbo"))
        self.assertEqual(aero.SEE, "See packs/aero-openfoam/references/rendering.md.")
        self.assertEqual(cfd.SEE, "See packs/cfd-openfoam/references/rendering.md.")


# --------------------------------------------------------------------------- #
# the pack's constants, legends, captions and bindings (no tool)
# --------------------------------------------------------------------------- #
class TheJobIsThePacksConstants(_env.EnvCase):
    """Every number a scene draws with is a constant of ``_scales.py`` or the
    summary's free-stream speed, and every legend is the exported preset."""

    def job(self, scene: str, **kw) -> dict:
        f3 = _flow3d()
        return f3.job_for(scene, {r: f"/x/{r}.vtp" for r in f3.FILES},
                          {"u_inf_m_s": U_INF, "ground_z_m": 0.0},
                          camera=_scales().HERO_CAMERA, **kw)

    def test_the_job_is_the_scales_constants(self):
        job = self.job("hero", gltf="field.gltf")
        self.assertEqual(job["preset"], "Turbo")
        self.assertEqual((tuple(job["over"]), tuple(job["under"])), (OVER, UNDER))
        self.assertEqual(job["ranges"], {"cp": [-1.5, 1.05], "speed": [0.0, 2.0 * U_INF],
                                         "cpt": [-0.2, 1.05]})
        self.assertEqual(job["bands"], [0.0, 5.0, 30.0, 300.0])
        self.assertEqual(job["cut_clip"], 0.95)
        self.assertEqual(job["size"], [1600, 1000])
        self.assertEqual(job["gltf_opts"], {"body_reduction": 0.75, "track_reduction": 0.95,
                                            "sides": 4})
        self.assertFalse(job["look"].get("tone_mapping"))
        self.assertEqual(job["fields"], {"cp": "static(p)_coeff", "speed": "mag(U)",
                                         "cpt": "total(p)_coeff", "yplus": "yPlus"})

    def test_the_scene_applies_the_preset_continuous_with_both_end_colours(self):
        """The scene's own lookup table, read from its source: continuous, in
        RGB, the job's colours past each end and for NaN, a fixed range; and
        no tone mapping but the tonemap twin's."""
        with open(os.path.join(VIEWS, "_scene3d.py"), encoding="utf-8") as fh:
            text = fh.read()
        for line in ('table.Discretize = 0', 'table.ColorSpace = "RGB"',
                     'table.AutomaticRescaleRangeMode = "Never"', 'table.UseAboveRangeColor = 1',
                     'table.UseBelowRangeColor = 1', 'table.NanColor = over',
                     'view.UseToneMapping = 1 if variant == "tonemap" else 0'):
            self.assertIn(line, text)

    def test_each_legend_is_the_exported_preset(self):
        sc = _scales()
        rows = _turbo_rows()
        want = [{"at": float(rows[i][0]),
                 "colour": "#" + "".join(f"{round(255 * c):02x}" for c in rows[i][1:4])}
                for i in sorted(set(range(0, len(rows), 4)) | {len(rows) - 1})]
        for name in ("cp", "speed", "cpt"):
            with self.subTest(name):
                self.assertEqual(sc.SCALES[name]({"u_inf_m_s": U_INF})["stops"], want)
        bands = sc.yplus()
        self.assertEqual([s["colour"] for s in bands["stops"][::2]],
                         ["#" + "".join(f"{c:02x}" for c in turbo_at(at))
                          for at in (0.125, 0.375, 0.625, 0.875)])
        self.assertEqual([t["text"] for t in bands["ticks"]], ["5", "30", "300"])

    def test_the_speed_scale_is_two_free_streams(self):
        for u in (20.0, 33.0):
            scale = _scales().speed({"u_inf_m_s": u})
            self.assertEqual((scale["lo"], scale["hi"]), (0.0, 2.0 * u))
        self.assertIsNone(_scales().speed({}))

    def test_the_wake_is_drawn_from_rest_to_the_free_stream(self):
        """Review of P3-P5: on the tracks' scale (0 to two free streams) 95%
        of the wake surface sat in the lowest 27% of the ramp and drew one
        blue. The wake's job and its key both run from 0 to U_inf."""
        sc = _scales()
        scale = sc.wake_speed({"u_inf_m_s": U_INF})
        self.assertEqual((scale["lo"], scale["hi"]), (0.0, U_INF))
        self.assertEqual(self.job("wake")["ranges"]["speed"], [0.0, U_INF])
        self.assertEqual(self.job("hero")["ranges"]["speed"], [0.0, 2.0 * U_INF])
        self.assertIsNone(sc.wake_speed({}))
        # The measured spread the range is set from (the demo's L0 wakeIso,
        # area-weighted): its 95th percentile reaches past half the ramp.
        self.assertGreaterEqual(11.0 / scale["hi"], 0.5)

    def test_each_alt_text_names_the_side_its_camera_is_on(self):
        """Review of P3-P5: the wake's alt text said "from the right" from a
        camera on the bike's left. The bike faces -x with +z up, so its left
        is -y, and the camera sits at azimuth ``az`` from +x toward +y
        (``_scene3d.py``)."""
        import math
        f3, sc = _flow3d(), _scales()
        for alt, camera in ((f3.HERO_ALT, sc.HERO_CAMERA), (f3.WAKE_ALT, sc.WAKE_CAMERA)):
            with self.subTest(alt):
                az = math.radians(camera["azimuth_deg"])
                side = "left" if math.sin(az) < 0 else "right"
                end = "behind" if math.cos(az) > 0 else "front"
                self.assertIn(f"the {side}", alt)
                self.assertNotIn("the " + ({"left", "right"} - {side}).pop(), alt)
                self.assertIn(end, alt)

    def test_each_lit_caption_says_light_moves_the_colours_both_ways(self):
        """Review of P3-P5: the hero said only "darker", while its specular
        highlights make the nose and the helmet lighter than the key; the
        wake, lit too, said nothing."""
        f3 = _flow3d()
        for caption in (f3.HERO_CAPTION, f3.WAKE_CAPTION):
            with self.subTest(caption):
                self.assertIn("darker or lighter than the colours in the key", caption)

    def test_the_captions_are_site_text_of_the_base_mesh_with_no_number(self):
        f3 = _flow3d()
        texts = {"hero": (f3.HERO_CAPTION, f3.HERO_ALT),
                 "surface_cp": (f3.SURFACE_CAPTION, f3.SURFACE_ALT),
                 "wake": (f3.WAKE_CAPTION, f3.WAKE_ALT), "cuts": (f3.CUTS_CAPTION, f3.CUTS_ALT),
                 "wall": (f3.WALL_CAPTION, f3.WALL_ALT), "history": (f3.HISTORY_CAPTION, ""),
                 "ladder": (f3.LADDER_CAPTION, "")}
        for name, (caption, alt) in texts.items():
            with self.subTest(name):
                self.assertEqual(page.caption_status(caption), "")
                self.assertEqual(prose.register_problems(caption + " " + alt), [])
                self.assertEqual(prose.long_sentences(caption), [])
                self.assertFalse(any(c.isdigit() for c in caption + alt), caption)
                if name != "ladder":
                    self.assertIn("base mesh", caption)

    def test_the_wall_names_no_body(self):
        """Review of P6: the wall's caption and alt text said "the bike and the
        rider" and "a motorcycle" over every project's body, the baseline's
        spheroid too."""
        f3 = _flow3d()
        for text in (f3.WALL_CAPTION, f3.WALL_ALT):
            with self.subTest(text):
                for word in ("bike", "rider", "motorcycle"):
                    self.assertNotIn(word, text.lower())

    def test_every_figure_binds_to_its_gate(self):
        registry = _views()
        self.assertEqual({v: registry.get(v)[0].evidence_of for v in BINDS}, BINDS)
        for view_id in PICTURES:
            spec = registry.get(view_id)[0]
            self.assertEqual(spec.recipe, ("views/_scene3d.py", "views/_scales.py",
                                           "views/turbo.json"))
            self.assertEqual(spec.requires_tools, ("pvbatch62",))
        for view_id in CHARTS:
            self.assertEqual(registry.get(view_id)[0].requires_tools, ())

    def test_the_rakes_are_where_the_base_mesh_run_seeded_them(self):
        """`RAKES` on the motorBike's box are P0's seeds, within the 9 mm the
        centre rake moved from y = 0 to the box's middle."""
        bbox = [-0.291665, 1.75115, -0.350289, 0.332267, -4.232e-05, 1.35152]
        got = _scales().rakes(bbox)
        p0 = {"tracksCentre": ([-0.4551, -0.0341, 0.0541], [-0.4551, 0.0341, 1.4462], 60),
              "tracksFar": ([-0.4551, 0.2709, 0.0541], [-0.4551, 0.3221, 1.2029], 18)}
        for name, (start, end, points) in p0.items():
            self.assertEqual(got[name]["points"], points)
            for a, b in zip(got[name]["start"] + got[name]["end"], start + end):
                self.assertAlmostEqual(a, b, delta=0.01)


# --------------------------------------------------------------------------- #
# the charts (no tool)
# --------------------------------------------------------------------------- #
def _chart_numbers(data: dict) -> list[float]:
    out: list[float] = []

    def walk(node):
        if isinstance(node, bool):
            return
        if isinstance(node, (int, float)):
            out.append(float(node))
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    for key in site_mod.CHART_NUMBER_KEYS:
        walk(data.get(key))
    return out


class ChartsNeedNoTool(_env.EnvCase):
    """The history and the ladder draw from the verified evidence alone, with
    no ParaView; every number they hold is the evidence's; neither is of the
    judged quantity, so neither holds a limit or a judged point."""

    def setUp(self):
        super().setUp()
        self.root = self.tmp()
        self.entries = make_entries(self.root)
        self.environ = mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"})
        self.environ.start()
        self.addCleanup(self.environ.stop)

    def chart(self, view_id, entries=None):
        return draw(self.root, entries or self.entries, view_id, os.path.join(self.root, "s"))

    def test_both_charts_draw_and_pass_the_spines_check(self):
        for view_id in CHARTS:
            with self.subTest(view_id):
                view, note, ctx, refusal = self.chart(view_id)
                self.assertIsNotNone(view, note or ctx.notes)
                self.assertEqual(refusal, "")
                self.assertIs(view.data["judged"], False)
                self.assertFalse(site_mod._keys(view.data) & site_mod.CHART_FORBIDDEN_KEYS)

    def test_the_history_shows_the_window_the_gate_judged(self):
        view, _note, _ctx, _refusal = self.chart("aero.history")
        history = _runs()["cda_history"]
        run, window = view.data["series"]
        self.assertEqual(run["points"], history[-300:])
        self.assertEqual(window["points"], history[-100:])
        values = [v for _, v in history[-100:]]
        self.assertEqual([r["value"] for r in view.data["rule"]], [max(values), min(values)])

    def test_the_window_lines_carry_no_words_over_the_points(self):
        """Review of P3-P5: on a phone the spine put "highest in the window"
        at the right end of its line, and the words ran back over the
        iterations before the window, hidden by their points. The caption
        names the two lines; the chart draws no words on them."""
        view, _note, _ctx, _r = self.chart("aero.history")
        self.assertTrue(all(not r.get("label") for r in view.data["rule"]), view.data["rule"])
        spec = page.chart_spec(view.data, None, None)
        styles = [(layer.get("mark") or {}).get("style") for layer in spec["layer"]
                  if isinstance(layer.get("mark"), dict)]
        self.assertIn("nk-rule", styles)
        self.assertNotIn("nk-rule-label", styles)
        self.assertIn("The two dotted lines are the highest and the lowest value",
                      _flow3d().HISTORY_CAPTION)

    def test_a_window_that_is_not_the_gates_draws_no_chart(self):
        def edit(gate, summary):
            if gate == GATE:
                summary["u_i_m2"] *= 1.5
        view, _note, ctx, _r = self.chart("aero.history", make_entries(self.tmp(), summary_edit=edit))
        self.assertIsNone(view)
        self.assertTrue(any("not the window the gate judged" in n for n in ctx.notes), ctx.notes)

    def test_a_run_shorter_than_its_window_draws_no_chart(self):
        def edit(gate, summary):
            if gate == GATE:
                summary["cda_history"] = summary["cda_history"][:50]
                summary.pop("u_i_m2")
        view, _note, ctx, _r = self.chart("aero.history", make_entries(self.tmp(), summary_edit=edit))
        self.assertIsNone(view)
        self.assertTrue(any("never filled" in n for n in ctx.notes), ctx.notes)

    def test_the_ladder_draws_the_meshes_and_what_the_gate_computed(self):
        view, _note, _ctx, refusal = self.chart("aero.ladder")
        (meshes,) = view.data["series"]
        self.assertEqual([p[1] for p in meshes["points"]],
                         [lv["cda_m2"] for lv in _runs()["ladder"]])
        self.assertNotIn("band", view.data)

        def edit(gate, summary):
            if gate == LADDER_GATE:
                summary.update({"cda_ext_m2": 0.299, "h_rel_ext": 0.0, "band_top_m2": 0.304,
                                "band_bottom_m2": 0.296})
        view, _note, _ctx, refusal = self.chart("aero.ladder", make_entries(self.tmp(),
                                                                            summary_edit=edit))
        self.assertEqual(refusal, "")
        self.assertEqual(view.data["series"][1]["points"], [[0.0, 0.299]])
        self.assertEqual((view.data["band"][0]["lo"], view.data["band"][0]["hi"]),
                         (0.296, 0.304))

    def test_every_chart_number_is_in_the_evidence(self):
        for view_id in CHARTS:
            with self.subTest(view_id):
                view, _note, ctx, _r = self.chart(view_id)
                held = site_mod._evidence_numbers(ctx.entry.files.values())
                self.assertTrue(all(n in held for n in _chart_numbers(view.data)))

    def test_a_computed_number_is_refused_by_the_spine(self):
        """The control: a mean of the window (a number the viewgen would
        compute) is refused."""
        view, _note, ctx, _r = self.chart("aero.history")
        values = view.data["series"][1]["points"]
        planted = {**view.data, "rule": [{"value": sum(v for _, v in values) / len(values),
                                          "label": "mean"}]}
        spec = _views().get("aero.history")[0]
        refusal = site_mod._figure_refusal(spec, View(id="aero.history", kind=ViewKind.CHART,
                                                      data=planted, meta=view.meta), ctx, [0.35])
        self.assertIn("which no evidence file of this result holds", refusal)


# --------------------------------------------------------------------------- #
# the pictures, through the stand-in pvbatch
# --------------------------------------------------------------------------- #
@unittest.skipIf(os.name == "nt", "the stand-in pvbatch is a #! script")
class ThePicturesOnTheStandIn(_env.EnvCase):
    """Each picture through the stand-in pvbatch, from a BoundContext as the
    spine builds it. What is held here is the pack's path to a picture, not
    the pixels (those are `TheRealPictures`): what is bound, what is left out
    and why, and what is an error."""

    def setUp(self):
        super().setUp()
        self.pv = _pv()
        self.pv._identity.cache_clear()
        self.addCleanup(self.pv._identity.cache_clear)
        self.root = self.tmp()
        self.entries = make_entries(self.root)
        self.stand = pv_standin.install(self.tmp())
        patch = mock.patch.dict(os.environ, {
            "PATH": self.stand["bin"] + os.pathsep + "/usr/bin:/bin",
            self.pv.EXTRA_LOCK_ENV: self.stand["extra_lock"]})
        patch.start()
        self.addCleanup(patch.stop)

    def draw(self, view_id, entries=None):
        return draw(self.root, entries or self.entries, view_id, os.path.join(self.root, "s"))

    def mode(self, mode: str) -> None:
        pv_standin.set_mode(self.stand["prefix"], mode)
        shutil.rmtree(self.pv.cache_dir(self.root), ignore_errors=True)

    def scenes(self) -> list[dict]:
        return [c for c in pv_standin.calls(self.stand["prefix"]) if "scene_files" in c]

    def test_every_picture_draws_and_passes_the_spines_check(self):
        for view_id in PICTURES:
            with self.subTest(view_id):
                view, note, ctx, refusal = self.draw(view_id)
                self.assertIsNotNone(view, note or ctx.notes)
                self.assertEqual(refusal, "")
                self.assertEqual(view.src, view_id.rsplit(".", 1)[1] + ".png")
                self.assertEqual(_sha256(ctx.outputs[view.src][0]),
                                 _sha256(os.path.join(STANDIN, ROLES_SCENE[view_id] + ".png")))

    def test_the_hero_states_its_two_scales_its_light_and_its_3d_file(self):
        view, _note, ctx, _r = self.draw("aero.hero")
        self.assertEqual(sorted(ctx.outputs), ["hero.gltf", "hero.png"])
        self.assertEqual(view.meta["light"], "scene")
        self.assertNotIn("scale", view.meta)
        (cp, speed) = view.meta["scales"]
        self.assertEqual((cp["on"], cp["lo"], cp["hi"]), ("surface", -1.5, 1.05))
        self.assertEqual((speed["on"], speed["lo"], speed["hi"]), ("lines", 0.0, 2.0 * U_INF))
        self.assertEqual([t["value"] for t in speed["ticks"]], [0.0, 10.0, 20.0, 30.0, 40.0])
        self.assertEqual(page.scales_problem(None, view.meta["scales"], view.meta["light"]), "")
        self.assertEqual(_sha256(ctx.outputs["hero.gltf"][0]),
                         _sha256(os.path.join(STANDIN, "hero.gltf")))

    def test_the_unlit_pictures_say_so_and_carry_one_scale(self):
        for view_id, quantity in (("aero.surface_cp", "pressure coefficient Cp"),
                                  ("aero.wake_cuts", "total pressure coefficient CpT"),
                                  ("aero.wall", "wall value y+")):
            with self.subTest(view_id):
                view, _note, _ctx, _r = self.draw(view_id)
                self.assertEqual(view.meta["light"], "none")
                self.assertEqual(view.meta["scale"]["quantity"], quantity)

    def test_every_lit_picture_warns_that_light_moves_its_colours(self):
        for view_id in PICTURES:
            with self.subTest(view_id):
                view, _note, _ctx, _r = self.draw(view_id)
                if view.meta["light"] == "scene":
                    self.assertIn(_flow3d().LIGHT_SENTENCE, view.meta["caption"])

    def test_the_wake_states_its_own_scale_and_is_drawn_on_it(self):
        view, _note, _ctx, _r = self.draw("aero.wake")
        (speed,) = view.meta["scales"]
        self.assertEqual((speed["on"], speed["lo"], speed["hi"]), ("surface", 0.0, U_INF))
        (job,) = [c["job"] for c in self.scenes() if c["job"].get("scene") == "wake"]
        self.assertEqual(job["ranges"]["speed"], [0.0, U_INF])

    def test_paraview_reads_only_the_bound_files(self):
        for view_id in PICTURES:
            self.draw(view_id)
        entry_shas = {}
        for gate, (_entry, files) in self.entries.items():
            with open(_summary_of(files), encoding="utf-8") as fh:
                entry_shas.update((json.load(fh).get("fields") or {}).get("sha256") or {})
        for call in self.scenes():
            self.assertTrue(call["scene_files"])
            for path, sha in call["scene_files"].items():
                self.assertNotIn(os.path.realpath(self.root), os.path.realpath(path))
                self.assertIn(sha, entry_shas.values())

    def test_another_runs_file_draws_nothing_and_says_why(self):
        _entry, files = self.entries[GATE]
        with open(_summary_of(files), encoding="utf-8") as fh:
            stage = json.load(fh)["fields"]
        body = os.path.join(self.root, ".nopekit", "out", "aero_converged", "case",
                            *_flow3d().FILES["body"].format(time=TIME).split("/"))
        with open(body, "ab") as fh:
            fh.write(b" ")
        self.assertTrue(stage["sha256"])
        view, _note, ctx, _r = self.draw("aero.hero")
        self.assertIsNone(view)
        self.assertTrue(any("from another run" in n for n in ctx.notes), ctx.notes)
        self.assertEqual(self.scenes(), [])

    def test_a_summary_with_no_free_stream_draws_no_speed_picture(self):
        def edit(gate, summary):
            summary.pop("u_inf_m_s", None)
        entries = make_entries(self.tmp(), summary_edit=edit)
        view, _note, ctx, _r = draw(self.root, entries, "aero.hero", os.path.join(self.root, "s"))
        self.assertIsNone(view)
        self.assertTrue(any("u_inf_m_s" in n for n in ctx.notes), ctx.notes)

    def test_each_fault_of_a_run_is_an_error_and_draws_nothing(self):
        for mode, view_id, words in (
                ("other-preset", "aero.surface_cp", "is not views/turbo.json"),
                ("other-png", "aero.wake", "the PNG on disk is not the one"),
                ("other-field", "aero.hero", "the glTF on disk is not the one"),
                ("empty", "aero.hero", "pvbatch drew nothing of tracks"),
                ("other-bands", "aero.wall", "drew the y+ bands in")):
            with self.subTest(mode):
                self.mode(mode)
                view, note, _ctx, _r = self.draw(view_id)
                self.assertIsNone(view)
                self.assertTrue(note.startswith("error:") and words in note, note)

    def test_a_3d_file_over_the_cap_leaves_the_still(self):
        self.mode("huge-field")
        view, _note, ctx, refusal = self.draw("aero.hero")
        self.assertEqual(sorted(ctx.outputs), ["hero.png"])
        self.assertEqual(refusal, "")
        self.assertTrue(any("over the 2 MiB cap" in n for n in ctx.notes), ctx.notes)

    def test_an_unchecked_paraview_draws_nothing_and_says_why(self):
        os.environ.pop(self.pv.EXTRA_LOCK_ENV)
        view, _note, ctx, _r = self.draw("aero.surface_cp")
        self.assertIsNone(view)
        self.assertTrue(any("did not check" in n and "No status depends" in n
                            for n in ctx.notes), ctx.notes)

    def test_no_paraview_on_path_is_unavailable_before_the_viewgen_runs(self):
        os.environ["PATH"] = "/usr/bin:/bin"
        view, note, _ctx, _r = self.draw("aero.hero")
        self.assertIsNone(view)
        self.assertTrue(note.startswith("unavailable:") and "pvbatch62" in note, note)


class AnEmptyBandIsDrawnAndNoBandIsNot(unittest.TestCase):
    """The wall's y+ bands may be empty one by one (the spheroid has none
    under 5 and none over 300), never all together. What slipped through P6's
    first wall picture: each band was held to the cuts' rule, every one
    non-empty, and the spheroid's true picture was refused."""

    def test_the_bands_together(self):
        import tempfile
        f3, sc = _flow3d(), _scales()
        with tempfile.TemporaryDirectory() as work:
            data = b"\x89PNG stand-in"
            with open(os.path.join(work, "still.png"), "wb") as fh:
                fh.write(data)
            job = {"scene": "wall", "png": "still.png"}
            for bands, ok in (([0, 2396, 15, 0], True), ([0, 0, 0, 0], False)):
                result = {"preset_sha256": sc.preset_sha256(),
                          "png_sha256": hashlib.sha256(data).hexdigest(),
                          "counts": {"body": 2411, "bands": bands},
                          "band_colours": [sc.preset_colour(at) for at in sc.BAND_AT]}
                with self.subTest(bands=bands):
                    if ok:
                        self.assertEqual(f3._check_result(result, job, work), data)
                    else:
                        with self.assertRaises(_pv().RunError):
                            f3._check_result(result, job, work)


#: Each picture's scene, as the stand-in names its committed files.
@unittest.skipIf(os.name == "nt", "the stand-ins are #! scripts")
class TheViewsReadWhatTheGateWrites(_env.EnvCase):
    """aero.converged run through the stand-in OpenFOAM (``tests/_aero_standin.py``),
    and its own summary, history and picture files handed to every view bound
    to it, as the spine hands them: the contract in flow3d.py's docstring is
    what the gate writes, not a copy of it typed into `make_entries`. What
    slipped through the two branches (merged 2026-10-23): each side's tests
    held its own picture of summary.json, the views read ``cda_history`` and
    ``u_i`` and the gate wrote ``history.csv`` and ``u_i_m2``, and every test
    stayed green while the history chart drew nothing on a real run."""

    def setUp(self):
        super().setUp()
        import test_aero_openfoam as gate_tests
        from nopekit import gates as gates_mod, store
        from nopekit.models import Ledger, ProjectMeta
        self.root = self.tmp()
        _root, bin_dir = gate_tests.install_standin(self.tmp())
        with open(os.path.join(_root, "standin.json"), "w") as fh:
            json.dump({}, fh)
        self.pv = _pv()
        self.pv._identity.cache_clear()
        self.addCleanup(self.pv._identity.cache_clear)
        self.stand = pv_standin.install(self.tmp())
        patch = mock.patch.dict(os.environ, {
            "PATH": os.pathsep.join((bin_dir, self.stand["bin"], "/usr/bin:/bin")),
            self.pv.EXTRA_LOCK_ENV: self.stand["extra_lock"]})
        patch.start()
        self.addCleanup(patch.stop)
        registry = gate_tests._registry()
        out = store.out_dir(self.root)
        # The out directory a check hands a gate: the project's .nopekit/out,
        # which the summary's "<out>/" stage is relative to.
        ctx = gates_mod.GateContext(
            root=self.root, ledger=Ledger(meta=ProjectMeta(name="aero"),
                                          claims=gate_tests._claims()),
            model=None, params=gate_tests._baseline(), out_dir=out, tier=2,
            log=lambda _m: None, extra={})
        self.entries = {}
        # The base mesh's run, and P6's two: the wall's and the ladder's.
        for gate in (GATE, WALL_GATE, LADDER_GATE):
            verdict = gates_mod.run_gate(*registry.get(gate), ctx)
            self.assertEqual(verdict.outcome, "pass", verdict.render())
            files = {os.path.relpath(p, out).replace(os.sep, "/"): p for p in verdict.evidence
                     if os.path.realpath(p).startswith(os.path.realpath(out) + os.sep)}
            self.entries[gate] = (site_mod.BoundEntry(gate=gate, name="0" * 16 + "-" + "0" * 8,
                                                      fresh=True, files=files), files)

    def test_every_key_a_view_reads_is_one_the_gate_wrote(self):
        with open(_summary_of(self.entries[GATE][1]), encoding="utf-8") as fh:
            summary = json.load(fh)
        for key in ("u_inf_m_s", "ground_z_m", "fields", "history", "window", "u_i_m2"):
            self.assertIn(key, summary)
        f3 = _flow3d()
        want = {f3.FILES[r].format(time=summary["fields"]["time"])
                for r in ("body", "tracksCentre", "tracksFar", "wake", "cut1", "cut2", "cut3")}
        self.assertEqual(want, set(summary["fields"]["sha256"]))

    def test_the_rakes_are_the_gates(self):
        """``_scales.RAKES`` (what the page says the tracks are seeded from)
        is where ``_fo.rakes`` seeds OpenFOAM's streamLine, on any box: two
        copies of one constant, one in gates/ and one in views/, held equal
        here, not by a load across the two folders."""
        from nopekit.modelio import load_path
        fo = load_path(os.path.join(PACK, "gates", "_fo.py"))
        for box in (((-0.291665, -0.350289, -4.232e-05), (1.75115, 0.332267, 1.35152)),
                    ((0.0, -0.125, 0.275), (1.0, 0.125, 0.525))):
            (x0, y0, z0), (x1, y1, z1) = box
            views = _scales().rakes([x0, x1, y0, y1, z0, z1])
            for name, (start, end, n) in fo.rakes(box).items():
                with self.subTest(name=name, box=box):
                    self.assertEqual(views[name]["points"], n)
                    for a, b in zip(views[name]["start"] + views[name]["end"],
                                    list(start) + list(end)):
                        self.assertAlmostEqual(a, b, places=9)

    def test_the_history_draws_from_the_gates_own_csv(self):
        view, note, ctx, refusal = draw(self.root, self.entries, "aero.history",
                                        os.path.join(self.root, "s"))
        self.assertIsNotNone(view, note or ctx.notes)
        self.assertEqual(refusal, "")
        run, window = view.data["series"]
        self.assertEqual(len(window["points"]), 100)
        self.assertEqual(run["points"][-1][0], 300)

    def test_the_wall_draws_from_the_gates_own_surface(self):
        with open(_summary_of(self.entries[WALL_GATE][1]), encoding="utf-8") as fh:
            summary = json.load(fh)
        self.assertEqual(set(summary["fields"]["sha256"]),
                         {_flow3d().FILES["yplus"].format(time=summary["fields"]["time"])})
        view, note, ctx, refusal = draw(self.root, self.entries, "aero.wall",
                                        os.path.join(self.root, "s"))
        self.assertIsNotNone(view, note or ctx.notes)
        self.assertEqual(refusal, "")
        calls = [c for c in pv_standin.calls(self.stand["prefix"]) if "scene_files" in c]
        self.assertEqual(set(calls[-1]["scene_files"].values()),
                         set(summary["fields"]["sha256"].values()))

    def test_the_ladder_draws_from_the_gates_own_levels(self):
        with open(_summary_of(self.entries[LADDER_GATE][1]), encoding="utf-8") as fh:
            summary = json.load(fh)
        view, note, ctx, refusal = draw(self.root, self.entries, "aero.ladder",
                                        os.path.join(self.root, "s"))
        self.assertIsNotNone(view, note or ctx.notes)
        self.assertEqual(refusal, "")
        meshes, zero = view.data["series"]
        self.assertEqual([p[1] for p in meshes["points"]],
                         [lv["cda_m2"] for lv in summary["levels"]])
        self.assertEqual(zero["points"], [[0.0, summary["cda_ext_m2"]]])
        (band,) = view.data["band"]
        # Review of P6: the band went up from the finest value only, and the
        # value at zero cell size fell under it.
        fine, gci = summary["levels"][-1]["cda_m2"], summary["gci_fine_pct"] / 100
        self.assertEqual((band["lo"], band["hi"]),
                         (summary["band_bottom_m2"], summary["band_top_m2"]))
        self.assertEqual((band["lo"], band["hi"]), (fine * (1 - gci), fine * (1 + gci)))
        self.assertTrue(band["lo"] <= summary["cda_ext_m2"] <= band["hi"])

    def test_every_picture_bound_to_it_draws(self):
        for view_id in [v for v in PICTURES if BINDS[v] == GATE]:
            with self.subTest(view_id):
                view, note, ctx, refusal = draw(self.root, self.entries, view_id,
                                                os.path.join(self.root, "s"))
                self.assertIsNotNone(view, note or ctx.notes)
                self.assertEqual(refusal, "")
                calls = [c for c in pv_standin.calls(self.stand["prefix"]) if "scene_files" in c]
                self.assertTrue(calls)
                with open(_summary_of(self.entries[GATE][1]), encoding="utf-8") as fh:
                    shas = set(json.load(fh)["fields"]["sha256"].values())
                self.assertTrue(set(calls[-1]["scene_files"].values()) <= shas)


ROLES_SCENE = {"aero.hero": "hero", "aero.surface_cp": "surface_cp", "aero.wake": "wake",
               "aero.wake_cuts": "wake_cuts", "aero.wall": "wall"}


# --------------------------------------------------------------------------- #
# the real ParaView
# --------------------------------------------------------------------------- #
def _real_missing() -> str:
    if os.name == "nt" or not shutil.which("pvbatch62"):
        return "pvbatch62 is not on PATH"
    for module in ("numpy", "PIL"):
        try:
            __import__(module)
        except ImportError:
            return f"{module} is not installed in this python"
    pv = _pv()
    try:
        pv.locate()
    except pv.Unavailable as exc:
        return str(exc)
    return ""


def _hue(rgb):
    import numpy
    a = numpy.asarray(rgb, dtype=float) / 255
    mx, mn = a.max(-1), a.min(-1)
    d = numpy.maximum(mx - mn, 1e-9)
    s = numpy.where(mx > 0, (mx - mn) / numpy.maximum(mx, 1e-9), 0)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    h = numpy.where(mx == r, ((g - b) / d) % 6, numpy.where(mx == g, (b - r) / d + 2,
                                                            (r - g) / d + 4))
    return h * 60, s


def same_hue_share(lit_png: str, twin_png: str, *, within: float = 6.0,
                   background=(255, 255, 255)) -> float:
    """Of the pixels the unlit twin draws (not ``background``), at a
    saturation above 0.3 in both pictures, the share whose hue in ``lit_png``
    is within ``within`` degrees of the twin's."""
    import numpy
    from PIL import Image
    with Image.open(lit_png) as a, Image.open(twin_png) as b:
        lit, twin = numpy.asarray(a.convert("RGB")), numpy.asarray(b.convert("RGB"))
    mask = (twin != numpy.array(background)).any(-1)
    h1, s1 = _hue(lit)
    h2, s2 = _hue(twin)
    chosen = mask & (s1 > 0.3) & (s2 > 0.3)
    dh = numpy.abs(h1 - h2)
    dh = numpy.minimum(dh, 360 - dh)
    return float((dh[chosen] <= within).mean())


#: The share of the drawn pixels a picture may hold off the ramp: none. The
#: unlit stills are drawn with the colours interpolated before they are
#: mapped and no FXAA, so each pixel is a colour of the table. Measured on
#: the L0 files: the farthest drawn pixel 0.65 of a byte from the ramp; a lit
#: twin and a tone-mapped twin put every drawn pixel off it by more than 2.
RAMP_TOLERANCE = 2.0
#: The lit hero's hue against its twin's: at least 95% of the compared pixels
#: within 6 degrees. Measured on L0: 97.9% (FXAA blends the tubes' edges with
#: the floor and the sky; the specular highlights lose their saturation); the
#: tone-mapped twin 27.6%.
HUE_SHARE = 0.95


@unittest.skipIf(_real_missing(), f"not walked: {_real_missing()}")
class TheRealPictures(_env.EnvCase):
    """The scenes on the real ParaView 6.2.0, on the committed fixtures, each
    at the pack's size: the pixels are held to the exported Turbo preset here,
    with no code of the pack."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.dir = tempfile.mkdtemp(prefix="nopekit-test-")
        cls.f3 = _flow3d()
        cls.inst = cls.f3._pv.locate()
        cls.results = {}
        scenes = {"hero": ("HERO_CAMERA", ""), "twin": ("HERO_CAMERA", "unlit"),
                  "twin_lit": ("HERO_CAMERA", "lit"), "twin_tonemap": ("HERO_CAMERA", "tonemap"),
                  "surface_cp": ("BODY_CAMERA", ""), "wake_cuts": ("CUTS_CAMERA", ""),
                  "wall": ("BODY_CAMERA", "")}
        files = {r: os.path.join(FIXTURES, r + ".vtp") for r in cls.f3.FILES}
        for name, (camera, variant) in scenes.items():
            scene = "twin" if name.startswith("twin") else name
            job = cls.f3.job_for(scene, files, {"u_inf_m_s": U_INF, "ground_z_m": 0.0},
                                 camera=getattr(cls.f3._scales, camera), variant=variant,
                                 gltf="field.gltf" if name == "hero" else "")
            work = os.path.join(cls.dir, name)
            cls.results[name] = (job, cls.f3._pv.run(cls.inst, cls.f3.SCENE, job, work), work)

    @classmethod
    def tearDownClass(cls):
        _env._rmtree(cls.dir)
        super().tearDownClass()

    def png(self, name: str) -> str:
        return os.path.join(self.results[name][2], "still.png")

    def test_turbo_is_paraviews_turbo(self):
        work = self.tmp()
        target = os.path.join(work, "turbo.json")
        proc = _env.run([shutil.which("pvbatch62"), os.path.join(VIEWS, "_export_preset.py"),
                         target], cwd=work, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
        self.assertEqual(_sha256(target), _sha256(TURBO_JSON))
        self.assertEqual(_sha256(TURBO_JSON),
                         "05f02e232d73ca28d679ab8d8c5171de43ae855f2810a8d44d67cff673c4c94f")

    def test_the_renderer_control_passes_with_turbo(self):
        rec = self.f3._pv.control(self.inst, self.f3._pv.cache_dir(self.tmp()))
        self.assertTrue(rec["ok"], rec["problems"])

    def test_every_result_names_the_presets_digest_and_draws_every_piece(self):
        for name, (job, result, work) in self.results.items():
            with self.subTest(name):
                self.assertEqual(self.f3._check_result(result, job, work)[:8], b"\x89PNG\r\n\x1a\n")

    def test_the_unlit_stills_stay_on_the_ramp(self):
        for name in ("surface_cp", "twin"):
            with self.subTest(name):
                drawn, coloured = drawn_pixels(self.png(name))
                self.assertGreater(len(coloured), 10000)
                self.assertLessEqual(float(off_ramp(coloured).max()), RAMP_TOLERANCE)

    def test_the_wall_is_four_flat_bands_of_the_key(self):
        import numpy
        drawn, _ = drawn_pixels(self.png("wall"))
        bands = numpy.array([turbo_at(at) for at in (0.125, 0.375, 0.625, 0.875)])
        nearest = numpy.abs(drawn[:, None, :].astype(int) - bands[None]).max(-1).min(-1)
        self.assertLessEqual(int(nearest.max()), 1)
        self.assertTrue(all(n > 0 for n in self.results["wall"][1]["counts"]["bands"]))

    def test_the_cuts_are_unlit_on_the_ramp(self):
        """The cuts' pixels (the saturated ones: the body is grey, the floor
        and the sky near grey) are on the ramp."""
        import numpy
        from PIL import Image
        with Image.open(self.png("wake_cuts")) as image:
            rgb = numpy.asarray(image.convert("RGB")).reshape(-1, 3)
        _h, s = _hue(rgb)
        cut = rgb[s > 0.5]
        self.assertGreater(len(cut), 10000)
        self.assertGreater(float((off_ramp(cut) <= RAMP_TOLERANCE).mean()), 0.99)

    def test_a_lit_or_tone_mapped_twin_fails_the_ramp(self):
        for name in ("twin_lit", "twin_tonemap"):
            with self.subTest(name):
                _drawn, coloured = drawn_pixels(self.png(name))
                self.assertGreater(float((off_ramp(coloured) > RAMP_TOLERANCE).mean()), 0.9)

    def test_the_lit_hero_keeps_the_twins_hue(self):
        self.assertGreaterEqual(same_hue_share(self.png("hero"), self.png("twin")), HUE_SHARE)
        self.assertLess(same_hue_share(self.png("twin_tonemap"), self.png("twin")), HUE_SHARE)

    def test_the_same_bytes_twice(self):
        job, result, _work = self.results["hero"]
        again = self.f3._pv.run(self.inst, self.f3.SCENE, job, os.path.join(self.tmp(), "again"))
        self.assertEqual(again["png_sha256"], result["png_sha256"])
        self.assertEqual(again["gltf_sha256"], result["gltf_sha256"])

    def test_the_solid_has_vertex_colours_on_the_ramp(self):
        import numpy
        import trimesh
        import test_cfd_views
        path = os.path.join(self.results["hero"][2], "field.gltf")
        self.assertLessEqual(os.path.getsize(path), page.EVIDENCE_MAX_BYTES)
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        for mesh in doc["meshes"]:
            for prim in mesh["primitives"]:
                self.assertIn("COLOR_0", prim["attributes"])
                self.assertNotIn("TEXCOORD_0", prim["attributes"])
        scene = trimesh.load(path, process=False)
        colours = numpy.concatenate([numpy.asarray(g.visual.vertex_attributes["color"])[:, :3]
                                     for g in scene.geometry.values()])
        special = (colours == OVER).all(1) | (colours == UNDER).all(1)
        self.assertLessEqual(float(off_ramp(colours[~special]).max()), 1.0)
        report = test_cfd_views.khronos(self, path)
        self.assertEqual((report["errors"], report["warnings"]), (0, 0), report["codes"])

    def test_the_committed_standin_files_are_what_paraview_draws(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "nopekit_test_make_standin", os.path.join(FIXTURES, "make_standin.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out = self.tmp()
        module.main(out)
        for name in sorted(os.listdir(STANDIN)):
            with self.subTest(name):
                self.assertEqual(_sha256(os.path.join(out, name)),
                                 _sha256(os.path.join(STANDIN, name)))


if __name__ == "__main__":
    unittest.main()
