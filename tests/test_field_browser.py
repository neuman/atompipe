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
const lit = new URLSearchParams(location.search).get("mode") === "lit";
createViewer({ host: document.getElementById("v"),
  view: { id: "f", kind: lit ? "model3d" : "field", src: "field.glb", meta: {} },
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


def drawn_counts(png: str) -> list[int]:
    """For each colour of `RAMP`, the pixels of ``png`` within `TOLERANCE`."""
    pixels = _pixels(png)
    return [sum(1 for p in pixels if all(abs(a - b) <= TOLERANCE for a, b in zip(p, rgb)))
            for rgb in RAMP]


@unittest.skipIf(_missing(), f"not walked: {_missing()}")
class TheBrowserDrawsTheField(_env.EnvCase):
    """(issue #15, B.6) A field drawn in the browser shows the bytes its file
    holds, within 2, and the lit mode does not."""

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        three = _three()
        if three is None:
            raise unittest.SkipTest("not walked: three.js 0.169.0 did not download")
        cls.site = tempfile.mkdtemp(prefix="nopekit-field-")
        shutil.copytree(os.path.join(three, "vendor"), os.path.join(cls.site, "vendor"))
        lib = os.path.join(cls.site, "lib")
        os.makedirs(lib)
        for name in ("viewer3d.js", "dom.js"):
            with open(os.path.join(lib, name), "w", encoding="utf-8") as fh:
                fh.write(_template.template_files(".js")[f"lib/{name}"])
        with open(os.path.join(cls.site, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(HARNESS)
        with open(os.path.join(cls.site, "field.glb"), "wb") as fh:
            fh.write(strip_glb())
        handler = lambda *a, **kw: _Quiet(*a, directory=cls.site, **kw)  # noqa: E731
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.site, ignore_errors=True)
        super().tearDownClass()

    def shot(self, mode: str) -> list[int]:
        out = os.path.join(self.tmp(), f"{mode}.png")
        profile = self.tmp()
        url = f"http://127.0.0.1:{self.server.server_address[1]}/index.html?mode={mode}"
        browser = _browser()
        shell = browser.endswith("chrome-headless-shell")
        _env.run([browser, *([] if shell else ["--headless=new"]), "--no-sandbox",
                  "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                  "--force-color-profile=srgb", "--force-device-scale-factor=1",
                  "--hide-scrollbars", "--window-size=480,360", "--virtual-time-budget=10000",
                  f"--user-data-dir={profile}", f"--screenshot={out}", url],
                 cwd=self.tmp(), timeout=120)
        self.assertTrue(os.path.isfile(out), "the browser wrote no screenshot")
        red = sum(1 for p in _pixels(out) if p == (255, 0, 0))
        self.assertLess(red, 1000, "the viewer reported an error (the page went red)")
        return drawn_counts(out)

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


if __name__ == "__main__":
    unittest.main()
