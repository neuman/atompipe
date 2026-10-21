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


if __name__ == "__main__":
    unittest.main()
