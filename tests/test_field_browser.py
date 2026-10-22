# SPDX-License-Identifier: Apache-2.0
"""The field viewer draws the colours a field file holds (issue #15, B.6).

A field's colours are its data, and a legend beside it says which value each
colour is. So the page must show each vertex colour as the file holds it: no
light shading a face, no tone mapping, no colour conversion on the way out.
`lib/viewer3d.js`'s field mode does that with three.js's own pieces
(``MeshBasicMaterial`` with vertex colours and ``toneMapped: false``, no
lights, ``LinearSRGBColorSpace`` output). This test draws a GLB in a real
headless Chromium (SwiftShader) and reads the screenshot's pixels.

The GLB is built with trimesh (rule 0.2 of the issue's design: a trusted tool,
never a stdlib glTF writer), a strip of four quads, each one colour, its
COLOR_0 the colour's own sRGB bytes as UNSIGNED_BYTE: the layout ParaView 6.2's
glTF exporter writes (measured on 2026-10-21: the Grayscale map at 0.25 is the
byte 64). A colour is drawn true when at least `MIN_PIXELS` pixels of the
screenshot are within `TOLERANCE` of it in every channel. The same file drawn
in the model mode (three lights, the material's own shading) must fail that
check, so the test can fail.

`TheBrowserDrawsAParaViewField` (P2.4) does the same with ParaView's own
glTF, as cfd-openfoam publishes it: ``tests/cfd_fields/bands.gltf``, seven
bands of known values that ParaView 6.2.0 exported through the pack's
``views/_scene.py``. Each band must be drawn in the colour the exported
Viridis preset (``packs/cfd-openfoam/views/viridis.json``) gives its value,
within 2, magenta above the scale and grey below it.

Skipped, saying "not walked", when a piece is absent: the headless Chromium
under ``~/.cache/ms-playwright/`` (build 1228), trimesh and numpy, Pillow (to
read the PNG), or three.js 0.169.0 (fetched once from the CDN into a cache in
the system's temporary folder). Not an invariant class: it reads a browser
that CI does not have, and an invariant class never skips.
"""
from __future__ import annotations

import http.server
import json
import os
import pwd
import shutil
import socketserver
import sys
import tempfile
import threading
import unittest
import urllib.request

import _env
import _template

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from nopekit import site as site_mod  # noqa: E402

#: The headless browsers this test may drive, in order: Chromium build 1228's
#: headless shell (it honours ``--virtual-time-budget``, so a screenshot waits
#: for the model to load), then the full Chromium of the same build. Measured
#: on 2026-10-21: the full build with ``--headless=new`` ran 85 s on the
#: figure project's page and wrote no screenshot, and the shell wrote it in
#: 2.7 s. *Rejected:* Playwright (a Python package this repository does not
#: depend on).
#: Under the account's own home, never ``$HOME``: the suite runs each test
#: under a temporary one (`_env`).
_CACHE = os.path.join(pwd.getpwuid(os.getuid()).pw_dir, ".cache", "ms-playwright")
BROWSERS = (
    os.path.join(_CACHE, "chromium_headless_shell-1228", "chrome-headless-shell-linux64",
                 "chrome-headless-shell"),
    os.path.join(_CACHE, "chromium-1228", "chrome-linux64", "chrome"),
)

#: The four colours of the strip, as sRGB bytes: three greys (where a
#: conversion between linear and sRGB moves a byte most, 64 to 137 and back)
#: and viridis's middle stop.
RAMP = ((64, 64, 64), (128, 128, 128), (192, 192, 192), (33, 145, 140))

#: Within 2 of each byte: the design's tolerance (B.6), the room SwiftShader's
#: rasteriser and the 8-bit round trip need. *Rejected:* 0 (one rounding step
#: in the browser would fail a true drawing).
TOLERANCE = 2

#: The pixels a colour must cover to count as drawn: a column of the strip
#: covers some 2 000 at 480 x 360; 200 leaves the antialiased edges out.
MIN_PIXELS = 200

THREE_FILES = ("vendor/three.module.js", "vendor/jsm/loaders/GLTFLoader.js",
               "vendor/jsm/controls/OrbitControls.js",
               "vendor/jsm/utils/BufferGeometryUtils.js",
               "vendor/jsm/libs/meshopt_decoder.module.js")

HARNESS = """<!doctype html>
<html><head><meta charset="utf-8">
<style>html, body { margin: 0; background: #000; }
#v, .viewer-canvas { position: absolute; inset: 0; }
canvas { display: block; width: 100%; height: 100%; }</style>
<script type="importmap">{"imports": {"three": "./vendor/three.module.js",
"three/addons/": "./vendor/jsm/"}}</script>
</head><body><div id="v"></div>
<script type="module">
import { createViewer } from "./lib/viewer3d.js";
const query = new URLSearchParams(location.search);
const lit = query.get("mode") === "lit";
createViewer({ host: document.getElementById("v"),
  view: { id: "f", kind: lit ? "model3d" : "field", src: query.get("src") || "field.glb",
          meta: {} },
  field: !lit,
  onError: () => { document.body.style.background = "#ff0000"; } });
</script></body></html>
"""


def _browser() -> str | None:
    return next((b for b in BROWSERS if os.access(b, os.X_OK)), None)


def _missing() -> str:
    """Why the test cannot be walked here, or ``""``."""
    if _browser() is None:
        return "no headless Chromium under ~/.cache/ms-playwright/ (build 1228)"
    for module in ("trimesh", "numpy", "PIL"):
        try:
            __import__(module)
        except ImportError:
            return f"{module} is not installed"
    return ""


def _three() -> str | None:
    """A folder holding three.js 0.169.0's files at their vendored paths,
    fetched once into the system's temporary folder, or None (offline)."""
    cache = os.path.join(tempfile.gettempdir(), f"nopekit-test-three-{site_mod.THREE_VERSION}")
    urls = site_mod.vendor_urls()
    if all(os.path.isfile(os.path.join(cache, *p.split("/"))) for p in THREE_FILES):
        return cache
    staging = tempfile.mkdtemp(prefix="nopekit-three-")
    try:
        for relative in THREE_FILES:
            with urllib.request.urlopen(urls[relative], timeout=30) as response:
                body = response.read()
            target = os.path.join(staging, *relative.split("/"))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(body)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
        return None
    try:
        os.replace(staging, cache)
    except OSError:
        shutil.rmtree(staging, ignore_errors=True)
    return cache if os.path.isdir(cache) else None


def strip_glb() -> bytes:
    """Four unit quads in a row, each with its own four vertices in one colour
    of `RAMP`, as trimesh exports a mesh with vertex colours."""
    import numpy
    import trimesh
    vertices, faces, colours = [], [], []
    for i, rgb in enumerate(RAMP):
        base = len(vertices)
        vertices += [[i, 0, 0], [i + 1, 0, 0], [i + 1, 1, 0], [i, 1, 0]]
        faces += [[base, base + 1, base + 2], [base, base + 2, base + 3]]
        colours += [list(rgb) + [255]] * 4
    mesh = trimesh.Trimesh(vertices=numpy.array(vertices, dtype=float),
                           faces=numpy.array(faces), process=False,
                           vertex_colors=numpy.array(colours, dtype=numpy.uint8))
    return mesh.export(file_type="glb")


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


def _pixels(png: str) -> list[tuple]:
    """Every pixel of ``png`` as an RGB triple (Pillow reads the file)."""
    from PIL import Image
    with Image.open(png) as image:
        raw = image.convert("RGB").tobytes()
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def drawn_counts(png: str, colours=RAMP) -> list[int]:
    """For each of ``colours``, the pixels of ``png`` within `TOLERANCE`."""
    pixels = _pixels(png)
    return [sum(1 for p in pixels if all(abs(a - b) <= TOLERANCE for a, b in zip(p, rgb)))
            for rgb in colours]


#: The colour past each end of a field's scale, as the legend says them
#: (cfd-openfoam's ``_scales.OVER`` and ``UNDER``), typed here so that the
#: test reads no code of the pack.
OVER, UNDER = (255, 0, 255), (128, 128, 128)

#: ParaView's Viridis preset as it exported it (the legend's source).
PRESET = os.path.join(ROOT, "packs", "cfd-openfoam", "views", "viridis.json")


def preset_colour(value: float, lo: float, hi: float) -> tuple[int, int, int]:
    """The sRGB bytes the exported preset gives ``value`` on [lo, hi]: the
    two points of ``RGBPoints`` around it, linear between them in RGB (the
    table's ``ColorSpace``), each channel rounded; `OVER` above, `UNDER`
    below. Read here from the file, with no code of the pack."""
    import json
    with open(PRESET, encoding="utf-8") as fh:
        pts = json.load(fh)["RGBPoints"]
    rows = [pts[i:i + 4] for i in range(0, len(pts), 4)]
    t = (value - lo) / (hi - lo)
    if t > 1:
        return OVER
    if t < 0:
        return UNDER
    k = next(j for j in range(len(rows) - 1) if rows[j][0] <= t <= rows[j + 1][0])
    f = (t - rows[k][0]) / (rows[k + 1][0] - rows[k][0])
    return tuple(round(255 * (a + (c - a) * f)) for a, c in zip(rows[k][1:4], rows[k + 1][1:4]))


def serve_viewer(files: dict[str, bytes]):
    """``(folder, server)``: ``lib/viewer3d.js`` on a page of its own
    (`HARNESS`), with three.js 0.169.0 and ``files``, served on a free port of
    127.0.0.1. Raises SkipTest ("not walked") when three.js cannot be had."""
    three = _three()
    if three is None:
        raise unittest.SkipTest("not walked: three.js 0.169.0 did not download")
    site = tempfile.mkdtemp(prefix="nopekit-field-")
    shutil.copytree(os.path.join(three, "vendor"), os.path.join(site, "vendor"))
    lib = os.path.join(site, "lib")
    os.makedirs(lib)
    for name in ("viewer3d.js", "dom.js"):
        with open(os.path.join(lib, name), "w", encoding="utf-8") as fh:
            fh.write(_template.template_files(".js")[f"lib/{name}"])
    with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(HARNESS)
    for name, data in files.items():
        with open(os.path.join(site, name), "wb") as fh:
            fh.write(data)
    handler = lambda *a, **kw: _Quiet(*a, directory=site, **kw)  # noqa: E731
    server = socketserver.TCPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return site, server


def stop_viewer(site: str, server) -> None:
    server.shutdown()
    server.server_close()
    shutil.rmtree(site, ignore_errors=True)


def shoot(case: _env.EnvCase, server, mode: str, src: str, *,
          size: tuple[int, int] = (480, 360)) -> str:
    """The path of a headless Chromium screenshot of ``src`` drawn in the
    field mode, or in the model mode (lights, shading) when ``mode`` is
    ``lit``. The page goes red when the viewer reports an error."""
    out = os.path.join(case.tmp(), f"{mode}.png")
    profile = case.tmp()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html?mode={mode}&src={src}"
    browser = _browser()
    shell = browser.endswith("chrome-headless-shell")
    _env.run([browser, *([] if shell else ["--headless=new"]), "--no-sandbox",
              "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
              "--force-color-profile=srgb", "--force-device-scale-factor=1",
              "--hide-scrollbars", f"--window-size={size[0]},{size[1]}",
              "--virtual-time-budget=10000", f"--user-data-dir={profile}",
              f"--screenshot={out}", url], cwd=case.tmp(), timeout=120)
    case.assertTrue(os.path.isfile(out), "the browser wrote no screenshot")
    red = sum(1 for p in _pixels(out) if p == (255, 0, 0))
    case.assertLess(red, 1000, "the viewer reported an error (the page went red)")
    return out


class _ViewerPage(_env.EnvCase):
    """`serve_viewer` for the class, with the files `files` names, and
    `shot`: a screenshot of one of them (`shoot`)."""

    @classmethod
    def files(cls) -> dict[str, bytes]:
        raise NotImplementedError

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.site, cls.server = serve_viewer(cls.files())

    @classmethod
    def tearDownClass(cls) -> None:
        stop_viewer(cls.site, cls.server)
        super().tearDownClass()

    def shot(self, mode: str, src: str = "field.glb") -> str:
        return shoot(self, self.server, mode, src)


@unittest.skipIf(_missing(), f"not walked: {_missing()}")
class TheBrowserDrawsTheField(_ViewerPage):
    """(issue #15, B.6) A field drawn in the browser shows the bytes its file
    holds, within 2, and the lit mode does not."""

    @classmethod
    def files(cls) -> dict[str, bytes]:
        return {"field.glb": strip_glb()}

    def shot(self, mode: str, src: str = "field.glb") -> list[int]:
        return drawn_counts(super().shot(mode, src))

    def test_the_field_mode_draws_the_bytes_the_file_holds(self):
        counts = self.shot("field")
        for rgb, n in zip(RAMP, counts):
            self.assertGreaterEqual(n, MIN_PIXELS, f"{rgb} is drawn on {n} pixels: {counts}")

    def test_a_lit_mode_differs(self):
        """The control: the model mode's lights and shading move the colours,
        so the check above can fail."""
        counts = self.shot("lit")
        self.assertTrue(any(n < MIN_PIXELS for n in counts),
                        f"the lit drawing kept every colour of the ramp: {counts}")


#: ParaView 6.2.0's own glTF of seven bands of known values on the
#: baseline's coarsest mesh (`tests/cfd_fields/make_bands.py` made it with
#: the pack's ``views/_scene.py``; `test_cfd_views.TheRealStills` holds it to
#: what ParaView writes today).
BANDS = os.path.join(ROOT, "tests", "cfd_fields", "bands.gltf")


def _bands():
    """``make_bands`` (the band values and the scale), loaded from its file."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "nopekit_test_make_bands", os.path.join(ROOT, "tests", "cfd_fields", "make_bands.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _missing_paraview_page() -> str:
    if _browser() is None:
        return "no headless Chromium under ~/.cache/ms-playwright/ (build 1228)"
    try:
        __import__("PIL")
    except ImportError:
        return "PIL is not installed"
    return ""


@unittest.skipIf(_missing_paraview_page(), f"not walked: {_missing_paraview_page()}")
class TheBrowserDrawsAParaViewField(_ViewerPage):
    """(issue #15, P2.4) The page turns ParaView's own glTF as ParaView wrote
    it: each band of `BANDS` drawn in the field mode is the preset's colour
    for its value within 2, magenta above the scale and grey below it,
    as the legend says them. The model mode's lights move the colours, so
    the check can fail. Needs no ParaView: the file is the one it wrote."""

    @classmethod
    def files(cls) -> dict[str, bytes]:
        with open(BANDS, "rb") as fh:
            return {"bands.gltf": fh.read()}

    def colours(self) -> list[tuple]:
        bands = _bands()
        return [preset_colour(v, bands.LO, bands.HI) for v in bands.VALUES]

    def test_each_band_is_the_presets_colour_for_its_value(self):
        colours = self.colours()
        self.assertIn(OVER, colours)
        self.assertIn(UNDER, colours)
        counts = drawn_counts(self.shot("field", "bands.gltf"), colours)
        for rgb, n in zip(colours, counts):
            self.assertGreaterEqual(n, MIN_PIXELS, f"{rgb} is drawn on {n} pixels: {counts}")

    def test_a_lit_mode_differs(self):
        counts = drawn_counts(self.shot("lit", "bands.gltf"), self.colours())
        self.assertTrue(any(n < MIN_PIXELS for n in counts),
                        f"the lit drawing kept every band's colour: {counts}")


#: A page that mounts `scaleLegend` and `figureStill` from ``lib/figures.js``
#: with ``page.css``, in a box of each width, and writes what it measured
#: into ``#out`` as JSON: each tick's mark against its value's place on the
#: ramp, and each plane mark against its place on the picture, with the
#: picture's and the words' boxes.
LAYOUT = """<!doctype html>
<html><head><meta charset="utf-8"><link rel="stylesheet" href="page.css">
<style>body { margin: 0; padding: 20px; } .box { margin-bottom: 40px; }</style>
</head><body><pre id="out">pending</pre>
<script type="module">
import { scaleLegend, figureStill } from "./lib/figures.js";
const FIGS = __FIGS__;
const pic = "data:image/svg+xml," + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="160">' +
  '<rect width="1600" height="160" fill="#3a6"/></svg>');
const out = [];
for (const width of [1000, 300]) {
  for (const fig of FIGS) {
    const box = document.createElement("div");
    box.className = "box";
    box.style.width = width + "px";
    document.body.appendChild(box);
    const still = figureStill(fig, pic);
    box.appendChild(still);
    box.appendChild(scaleLegend(fig.scale));
    const img = still.querySelector("img");
    await img.decode();
    const r = img.getBoundingClientRect();
    const ramp = box.querySelector(".fig-ramp").getBoundingClientRect();
    const ticks = [...box.querySelectorAll(".fig-tick")].map((t, i) => {
      const at = fig.scale.ticks[i].at;
      const mark = t.getBoundingClientRect().left
        + parseFloat(getComputedStyle(t, "::before").left)
        + parseFloat(getComputedStyle(t, "::before").borderLeftWidth) / 2;
      const words = t.querySelector(".fig-tick-text").getBoundingClientRect();
      return { at, mark, want: ramp.left + at * ramp.width, left: words.left,
               right: words.right };
    });
    const marks = [...still.querySelectorAll(".fig-mark")].map((m, i) => {
      const at = fig.marks[i].at;
      const line = m.getBoundingClientRect().left
        + parseFloat(getComputedStyle(m, "::after").left)
        + parseFloat(getComputedStyle(m, "::after").borderLeftWidth) / 2;
      const words = m.querySelector(".fig-mark-text").getBoundingClientRect();
      return { at, line, want: r.left + at * r.width, top: words.top, bottom: words.bottom,
               left: words.left, right: words.right };
    });
    out.push({ width, img: { left: r.left, right: r.right, top: r.top },
               ramp: { left: ramp.left, right: ramp.right }, ticks, marks });
  }
}
document.getElementById("out").textContent = JSON.stringify(out);
</script></body></html>
"""

#: The two baseline stills' marks and scales, as page.json bakes them: the
#: speed's ticks at both ends of the ramp, the pressure's inside it.
LAYOUT_FIGS = [
    {"marks": [{"at": 0.2619, "text": "upstream plane"},
               {"at": 0.7381, "text": "downstream plane"}],
     "scale": {"quantity": "speed", "units": "m/s", "stops": [{"at": 0, "colour": "#440154"},
                                                              {"at": 1, "colour": "#fde725"}],
               "over": "#ff00ff", "ticks": [{"at": a, "text": t} for a, t in (
                   (0.0, "0.000"), (0.25, "0.005"), (0.5, "0.010"), (0.75, "0.015"),
                   (1.0, "0.020"))]}},
    {"marks": [{"at": 0.2619, "text": "upstream plane"},
               {"at": 0.7381, "text": "downstream plane"}],
     "scale": {"quantity": "static pressure", "units": "Pa",
               "stops": [{"at": 0, "colour": "#440154"}, {"at": 1, "colour": "#fde725"}],
               "over": "#ff00ff", "under": "#808080",
               "ticks": [{"at": 0.165, "text": "0.0"}, {"at": 0.4845, "text": "0.5"},
                         {"at": 0.804, "text": "1.0"}]}},
]


@unittest.skipIf(_browser() is None, "not walked: no headless Chromium under "
                                     "~/.cache/ms-playwright/ (build 1228)")
class TheLegendAndTheMarksSitOnTheirValues(_env.EnvCase):
    """(review of P2) In a real browser, with the real ``page.css``: each
    tick's mark on a still's legend is at its value's place on the ramp
    within 1 px, at an end of the ramp and inside it, in a box 1000 px and
    300 px wide; each plane's words sit above the picture, never on it, with
    their line at the plane's place within 1 px, and inside the box. What
    slipped through: the first and last ticks' marks moved with their words,
    17 px off on the speed legend and 9.5 px on the pressure's; and the plane
    words sat on a strip 29 px high on a phone, hiding most of it."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        site = tempfile.mkdtemp(prefix="nopekit-layout-")
        cls.addClassCleanup(shutil.rmtree, site, True)
        os.makedirs(os.path.join(site, "lib"))
        for rel, text in _template.template_files(".js").items():
            if rel.startswith("lib/"):
                with open(os.path.join(site, *rel.split("/")), "w", encoding="utf-8") as fh:
                    fh.write(text)
        with open(os.path.join(site, "page.css"), "w", encoding="utf-8") as fh:
            fh.write(_template.template_files(".css")["page.css"])
        with open(os.path.join(site, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(LAYOUT.replace("__FIGS__", json.dumps(LAYOUT_FIGS)))
        handler = lambda *a, **kw: _Quiet(*a, directory=site, **kw)  # noqa: E731
        server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.addClassCleanup(server.server_close)
        cls.addClassCleanup(server.shutdown)
        browser = _browser()
        profile = tempfile.mkdtemp(prefix="nopekit-layout-profile-")
        cls.addClassCleanup(shutil.rmtree, profile, True)
        shell = browser.endswith("chrome-headless-shell")
        done = _env.run([browser, *([] if shell else ["--headless=new"]), "--no-sandbox",
                         "--force-device-scale-factor=1", "--window-size=1200,1600",
                         "--virtual-time-budget=5000", f"--user-data-dir={profile}",
                         "--dump-dom",
                         f"http://127.0.0.1:{server.server_address[1]}/index.html"],
                        cwd=profile, timeout=120)
        import html
        import re
        found = re.search(r'<pre id="out">(.*?)</pre>', done.stdout, re.S)
        cls.measured = json.loads(html.unescape(found.group(1))) if found else None
        cls.dom = done.stdout[-2000:]

    def setUp(self):
        super().setUp()
        self.assertIsInstance(self.measured, list, self.dom)
        self.assertEqual(len(self.measured), 4)

    def test_each_tick_mark_is_at_its_value(self):
        for box in self.measured:
            for tick in box["ticks"]:
                with self.subTest(width=box["width"], at=tick["at"]):
                    self.assertAlmostEqual(tick["mark"], tick["want"], delta=1.0)
                    # Its words stay inside the legend's ramp.
                    self.assertGreaterEqual(tick["left"], box["ramp"]["left"] - 1)
                    self.assertLessEqual(tick["right"], box["ramp"]["right"] + 1)

    def test_each_plane_word_is_above_the_picture_over_its_line(self):
        for box in self.measured:
            for mark in box["marks"]:
                with self.subTest(width=box["width"], at=mark["at"]):
                    self.assertAlmostEqual(mark["line"], mark["want"], delta=1.0)
                    self.assertLessEqual(mark["bottom"], box["img"]["top"] + 0.5)
                    self.assertGreaterEqual(mark["left"], box["img"]["left"] - 1)
                    self.assertLessEqual(mark["right"], box["img"]["right"] + 1)
            words = sorted(box["marks"], key=lambda m: m["left"])
            for a, b in zip(words, words[1:]):
                self.assertLessEqual(a["right"], b["left"], "two plane words overlap")


if __name__ == "__main__":
    unittest.main()
