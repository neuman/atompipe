# SPDX-License-Identifier: Apache-2.0
"""The renderer control, run by pvbatch (never imported by nopekit).

``pvbatch --force-offscreen-rendering _control.py <job.json>`` draws the strip
in ``fixture/strip.vtk`` (15 cells, t from -0.2 to 1.2 of a unit scale) the
way the pack's stills are drawn: the faceted recipe, an unlit display, a
lookup table from ParaView's own preset with the above-range and below-range
colours, a parallel camera on the whole strip. Then Pillow (ParaView's own
Python has it) reads the centre pixel of each cell from the PNG, and the
script writes ``result.json`` beside the job:

    {"done": <sha256 of job.json>, "gl_renderer": <the GL renderer string>,
     "paraview": <version>, "png_sha256": <sha256 of the PNG>,
     "cells": [{"index", "value", "where": "below"|"in"|"above",
                "pixel": [r, g, b], "want": [r, g, b]}]}

``want`` is the lookup table's own colour for the cell's value (vtk's
``MapValue``), or the job's above or below colour. The script judges nothing:
``_pv.judge_control`` compares ``pixel`` with ``want`` in nopekit, so a fault
in this script cannot pass a renderer that draws other colours.

What the control finds: a renderer that lights the faces (measured: about 22%
darker on ParaView's default display), one that clips an out-of-range value
to the end colour (the picture would then hide that a value is past the
scale), and a GL that is not the llvmpipe this pack pins.
"""
import hashlib
import json
import os
import sys

from paraview import simple as pv
from PIL import Image


def _sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def main(job_path):
    with open(job_path, "rb") as fh:
        raw = fh.read()
    job = json.loads(raw.decode("utf-8"))
    out_dir = os.path.dirname(os.path.abspath(job_path))
    png = os.path.join(out_dir, "control.png")
    lo, hi = job["range"]
    over = [c / 255.0 for c in job["over"]]
    under = [c / 255.0 for c in job["under"]]
    width, height = job["size"]

    reader = pv.LegacyVTKReader(FileNames=[job["data"]])
    # The faceted recipe the stills use (measured on 6.2: ParaView's default
    # glTF export of cell data fails Khronos validation; this one passes, and
    # its colours are the cells' own).
    surface = pv.ExtractSurface(Input=reader)
    shrunk = pv.Shrink(Input=surface, ShrinkFactor=1.0)
    points = pv.CellDatatoPointData(Input=shrunk)

    view = pv.CreateRenderView()
    view.ViewSize = [width, height]
    view.OrientationAxesVisibility = 0
    view.Background = [1.0, 1.0, 1.0]
    try:
        view.UseColorPaletteForBackground = 0
    except AttributeError:
        pass
    display = pv.Show(points, view)
    pv.ColorBy(display, ("POINTS", job["field"]))
    display.InterpolateScalarsBeforeMapping = 0
    # Unlit (measured: lit is about 22% darker at the same value).
    display.Ambient = 1.0
    display.Diffuse = 0.0
    display.Specular = 0.0

    lut = pv.GetColorTransferFunction(job["field"])
    lut.ApplyPreset(job["preset"], True)
    lut.ColorSpace = "RGB"
    lut.AutomaticRescaleRangeMode = "Never"
    lut.RescaleTransferFunction(lo, hi)
    lut.UseAboveRangeColor = 1
    lut.AboveRangeColor = over
    lut.UseBelowRangeColor = 1
    lut.BelowRangeColor = under
    lut.NanColor = over

    # A parallel camera fitted to the strip's width plus 5%. Measured: the
    # first Render resets the camera to the bounding sphere (it drew the 15
    # cells 8 px wide each in a 600 px image), so it runs first.
    pv.Render(view)
    b = reader.GetDataInformation().GetBounds()
    cx, cy, cz = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2
    view.CameraParallelProjection = 1
    view.CameraFocalPoint = [cx, cy, cz]
    view.CameraPosition = [cx, cy, cz + 10.0 * max(b[1] - b[0], b[3] - b[2], 1.0)]
    view.CameraViewUp = [0.0, 1.0, 0.0]
    view.CameraParallelScale = max((b[1] - b[0]) * height / width, b[3] - b[2]) * 1.05 / 2
    pv.Render(view)
    pv.SaveScreenshot(png, view, ImageResolution=[width, height], CompressionLevel=9)

    renderer = view.GetRenderer()
    window = view.GetRenderWindow()
    caps = window.ReportCapabilities() or ""
    gl = ""
    for line in caps.splitlines():
        if "renderer string" in line:
            gl = line.split(":", 1)[1].strip()
            break

    data = pv.servermanager.Fetch(reader)
    values = data.GetCellData().GetArray(job["field"])
    # The lookup table's own bytes for each value: vtk maps a double array
    # through it, as it does when it draws.
    from paraview import vtk
    mapped = lut.GetClientSideObject().MapScalars(values, 0, -1)
    image = Image.open(png).convert("RGB")
    cells = []
    for i in range(data.GetNumberOfCells()):
        bounds = data.GetCell(i).GetBounds()
        centre = [(bounds[0] + bounds[1]) / 2, (bounds[2] + bounds[3]) / 2,
                  (bounds[4] + bounds[5]) / 2]
        renderer.SetWorldPoint(centre[0], centre[1], centre[2], 1.0)
        renderer.WorldToDisplay()
        x, y, _ = renderer.GetDisplayPoint()
        px, py = int(round(x)), int(round(height - 1 - y))
        value = values.GetValue(i)
        if value < lo:
            where, want = "below", list(job["under"])
        elif value > hi:
            where, want = "above", list(job["over"])
        else:
            where = "in"
            want = [int(mapped.GetComponent(i, k)) for k in range(3)]
        cells.append({"index": i, "value": value, "where": where,
                      "pixel": list(image.getpixel((px, py)))[:3], "want": want,
                      "at": [px, py]})

    result = {"done": hashlib.sha256(raw).hexdigest(), "gl_renderer": gl,
              "paraview": pv.GetParaViewSourceVersion(), "png_sha256": _sha256(png),
              "cells": cells}
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1])
