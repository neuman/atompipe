# SPDX-License-Identifier: Apache-2.0
"""A still of one solved field, and its 3D file, run by pvbatch (never imported
by nopekit).

``pvbatch --force-offscreen-rendering _scene.py <job.json>`` reads the case
the job names (a copy that ``flow.py`` made of the bound files: the mesh,
the field at its time and a controlDict of its own), cuts it at the middle of
its thickness (normal to the job's ``look``, the 2D case's thin axis),
colours each cell of the cut by the field with ParaView's own preset on the
job's range, draws the trace of each measuring plane as a black line, and
writes the PNG, the glTF of the cut when the job names one (``gltf``), and
``result.json`` beside the job::

    {"done": <sha256 of job.json>, "gl_renderer": <the GL renderer string>,
     "paraview": <version>, "png_sha256": <sha256 of the PNG>, "size": [w, h],
     "preset_sha256": <sha256 of the preset as ParaView exports it>,
     "cut_cells": <the cells of the cut>,
     "marks": [{"at": <x of the plane's line / image width>, "px": <x in px>}],
     "ticks": [<tick value>, ...], "tick_texts": [<its text>, ...],
     "window": [the picture's half width and half height about the cut's centre,
                as -w, w, -h, h, in metres along right and up],
     "gltf_sha256": <sha256 of the glTF, when asked>}

What each step is, and what was measured on ParaView 6.2.0 while it was
written:

- **The cells' own colours.** The faceted recipe of the renderer control
  (``_control.py``): ExtractSurface, Shrink 1.0, CellDatatoPointData, with
  ``InterpolateScalarsBeforeMapping`` 0, so each cell is one flat colour,
  and the display unlit (lit is about 22% darker at the same value).
- **The preset by name, the legend from its export.** ``ApplyPreset`` takes
  the job's preset; the result names the sha256 of that preset as ParaView
  exports it, and ``flow.py`` draws only when it is the sha256 of the
  committed ``viridis.json`` the page's legend is made from.
- **Past the scale.** Above it the job's ``over`` colour, below it
  ``under``, NaN ``over``: never the end colours (the control fails a
  renderer that clips).
- **A continuous table** (``Discretize`` 0). ParaView's default quantises the
  map to 256 colours; the page's gradient is continuous. Measured: with it,
  every one of the baseline's 7840 cells away from the lines drew the
  preset's colour for its value to the byte.
- **The planes.** ParaView slices the cut by each measuring plane, so the
  line is the plane's trace inside the fluid, whatever its normal. VTK draws
  a line over the cells it lies on (its coincident-topology offset);
  measured: a line moved toward the camera drew the same bytes, so none is
  moved. 6 px drew 6 px wide.
- **The frame.** A parallel camera on the whole cut plus 5% on each side, so
  a corner cell is always in the picture; the width is the job's, the height
  the cut's aspect, at most the job's ``max_height``. The camera looks along
  the job's ``look`` with the job's ``right`` (the flow, upstream to
  downstream) to the right of the picture, so each plane's line is vertical
  and its mark's ``at`` is its place along the flow. The first Render resets
  the camera to the bounding sphere, so the camera is set after it (as in
  the control). What slipped through (review of P2): the camera always
  looked down z with y up, so a flow along y put both planes' marks at the
  middle of the picture, one over the other, and a case thin along y was cut
  through its height, one row of cells drawn as the field; and a domain
  taller than wide was drawn 1600 x 16000 px.
- **The bytes.** ParaView's PNG carries a text chunk (``Application
  ParaView``); Pillow reads the pixels and writes them again with no chunk
  but the image's, so two runs on the locked build write the same bytes.
- **The ticks.** matplotlib's ``MaxNLocator`` picks round values inside the
  range and its ``ScalarFormatter`` writes them, so the legend's numbers come
  from a library and not from code of this pack.
- **The 3D file** (P2.4) is ParaView's own glTF exporter on the same view,
  after the still, with the planes' lines hidden: ``InlineData`` 1 (its
  buffers inside it as ``data:`` URIs; ParaView writes no GLB), and no
  normals, batch ids or NaN texture. The faceted recipe is what makes it a
  valid glTF: each cell owns its four vertices, all in its own colour, so
  ``POSITION`` and ``COLOR_0`` have one count. Measured on the baseline's
  8000 cells: 940 KB, no error and no warning from the Khronos validator
  2.0.0-dev.3.10, every cell's ``COLOR_0`` the preset's sRGB bytes for its
  value to the byte, two exports byte-identical. ParaView's default export
  (the cut coloured by ``CELLS``) fails the validator
  (``MESH_PRIMITIVE_UNEQUAL_ACCESSOR_COUNT``). The page draws the file as it
  is, in the viewer's field mode (``lib/viewer3d.js``).

*Rejected:* a colour bar in the PNG (two legends can disagree; the page draws
one from the same scale, C7); the planes' lines in the 3D file (WebGL draws a
glTF line 1 px wide whatever ParaView's width, and the field mode gives a
line no colour of the legend); the stops of the committed export as the lookup
table (the pixels would then not be the preset's own, and an edited file
would colour the picture to match itself); ParaView's ``Magnitude`` of U or a
Calculator for static pressure (OpenFOAM computed both: no arithmetic of a
picture is a number no gate checks).
"""
import hashlib
import json
import os
import sys

from paraview import servermanager as sm
from paraview import simple as pv
from PIL import Image


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _preset_text(name):
    presets = sm.vtkSMTransferFunctionPresets.GetInstance()
    for index in range(presets.GetNumberOfPresets()):
        if presets.GetPresetName(index) == name:
            return presets.GetPresetAsString(index)
    raise SystemExit(f"ParaView has no preset named {name!r}")


def _ticks(lo, hi, bins):
    from matplotlib.ticker import MaxNLocator, ScalarFormatter
    span = hi - lo
    values = [float(v) for v in MaxNLocator(nbins=bins, steps=[1, 2, 2.5, 5, 10])
              .tick_values(lo, hi) if lo - 1e-9 * span <= v <= hi + 1e-9 * span]
    fmt = ScalarFormatter(useOffset=False)
    fmt.set_scientific(False)
    fmt.create_dummy_axis()
    fmt.axis.set_view_interval(lo, hi)
    fmt.axis.set_data_interval(lo, hi)
    fmt.set_locs(values)
    return values, [str(fmt(v)) for v in values]


def main(job_path):
    with open(job_path, "rb") as fh:
        raw = fh.read()
    job = json.loads(raw.decode("utf-8"))
    out_dir = os.path.dirname(os.path.abspath(job_path))
    lo, hi = job["range"]
    width = int(job["width"])

    reader = pv.OpenFOAMReader(FileName=os.path.join(job["case"], "system", "controlDict"))
    reader.MeshRegions = ["internalMesh"]
    reader.CellArrays = [job["field"]]
    reader.Createcelltopointfiltereddata = 0
    time = float(job["time"])
    if time not in [float(t) for t in reader.TimestepValues]:
        raise SystemExit(f"the case holds no time {job['time']}: {reader.TimestepValues}")
    reader.UpdatePipeline(time)
    b = reader.GetDataInformation().GetBounds()
    cx, cy, cz = (b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2
    look = [float(v) for v in job["look"]]
    right = [float(v) for v in job["right"]]
    up = [float(v) for v in job["up"]]
    corners = [(x, y, z) for x in b[0:2] for y in b[2:4] for z in b[4:6]]

    def extent(axis):
        along = [c[0] * axis[0] + c[1] * axis[1] + c[2] * axis[2] for c in corners]
        return max(along) - min(along)

    # dx along the flow (the picture's width), dy across it (its height).
    dx, dy = extent(right), extent(up)
    size = max(b[1] - b[0], b[3] - b[2], b[5] - b[4], 1e-9)

    cut = pv.Slice(Input=reader)
    cut.SliceType = "Plane"
    cut.SliceType.Origin = [cx, cy, cz]
    cut.SliceType.Normal = look
    cut.Triangulatetheslice = 0
    surface = pv.ExtractSurface(Input=cut)
    shrunk = pv.Shrink(Input=surface, ShrinkFactor=1.0)
    points = pv.CellDatatoPointData(Input=shrunk)

    height = max(int(job.get("min_height", 1)),
                 min(int(job.get("max_height", width)), int(round(width * dy / dx))))
    view = pv.CreateRenderView()
    view.ViewSize = [width, height]
    view.OrientationAxesVisibility = 0
    view.Background = [1.0, 1.0, 1.0]
    try:
        view.UseColorPaletteForBackground = 0
    except AttributeError:
        pass
    view.ViewTime = time
    display = pv.Show(points, view)
    pv.ColorBy(display, ("POINTS", job["field"]))
    display.InterpolateScalarsBeforeMapping = 0
    display.Ambient = 1.0
    display.Diffuse = 0.0
    display.Specular = 0.0

    lut = pv.GetColorTransferFunction(job["field"])
    lut.ApplyPreset(job["preset"], True)
    lut.ColorSpace = "RGB"
    lut.Discretize = 0
    lut.AutomaticRescaleRangeMode = "Never"
    lut.RescaleTransferFunction(lo, hi)
    lut.UseAboveRangeColor = 1
    lut.AboveRangeColor = [c / 255.0 for c in job["over"]]
    lut.UseBelowRangeColor = 1
    lut.BelowRangeColor = [c / 255.0 for c in job["under"]]
    lut.NanColor = [c / 255.0 for c in job["over"]]
    pv.HideScalarBarIfNotNeeded(lut, view)

    lines = []
    for plane in job["planes"]:
        trace = pv.Slice(Input=surface)
        trace.SliceType = "Plane"
        trace.SliceType.Origin = list(plane["point"])
        trace.SliceType.Normal = list(plane["normal"])
        shown = pv.Show(trace, view)
        shown.ColorArrayName = ["POINTS", ""]
        shown.AmbientColor = [0.0, 0.0, 0.0]
        shown.DiffuseColor = [0.0, 0.0, 0.0]
        shown.Ambient = 1.0
        shown.Diffuse = 0.0
        shown.LineWidth = float(job["line_px"])
        lines.append(trace)

    pv.Render(view)
    view.CameraParallelProjection = 1
    view.CameraFocalPoint = [cx, cy, cz]
    view.CameraPosition = [cx + look[0] * 10.0 * size, cy + look[1] * 10.0 * size,
                           cz + look[2] * 10.0 * size]
    view.CameraViewUp = up
    view.CameraParallelScale = max(dx * height / width, dy) * 1.05 / 2
    pv.Render(view)
    shot = os.path.join(out_dir, "paraview.png")
    pv.SaveScreenshot(shot, view, ImageResolution=[width, height], CompressionLevel=9)
    png = os.path.join(out_dir, job["png"])
    Image.open(shot).convert("RGB").save(png, format="PNG", optimize=False, compress_level=9)
    with open(png, "rb") as fh:
        png_sha = _sha256(fh.read())

    cut_cells = int(cut.GetDataInformation().GetNumberOfCells())
    renderer = view.GetRenderer()
    marks = []
    for trace in lines:
        lb = trace.GetDataInformation().GetBounds()
        renderer.SetWorldPoint((lb[0] + lb[1]) / 2, (lb[2] + lb[3]) / 2, (lb[4] + lb[5]) / 2,
                               1.0)
        renderer.WorldToDisplay()
        x, _, _ = renderer.GetDisplayPoint()
        marks.append({"at": x / width, "px": x})
    half_w = view.CameraParallelScale * width / height
    half_h = view.CameraParallelScale

    gltf_sha = None
    if job.get("gltf"):
        for trace in lines:
            pv.Hide(trace, view)
        target = os.path.join(out_dir, job["gltf"])
        pv.ExportView(target, view=view, InlineData=1, SaveNormal=0, SaveBatchId=0,
                      SaveNaNValues=0)
        with open(target, "rb") as fh:
            gltf_sha = _sha256(fh.read())

    caps = view.GetRenderWindow().ReportCapabilities() or ""
    gl = ""
    for line in caps.splitlines():
        if "renderer string" in line:
            gl = line.split(":", 1)[1].strip()
            break
    ticks, texts = _ticks(lo, hi, int(job["ticks"]))
    result = {"done": _sha256(raw), "gl_renderer": gl,
              "paraview": pv.GetParaViewSourceVersion(), "png_sha256": png_sha,
              "size": [width, height], "cut_cells": cut_cells,
              "preset_sha256": _sha256(_preset_text(job["preset"]).encode("utf-8")),
              "marks": marks, "ticks": ticks, "tick_texts": texts,
              "window": [-half_w, half_w, -half_h, half_h]}
    if gltf_sha is not None:
        result["gltf_sha256"] = gltf_sha
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1])
