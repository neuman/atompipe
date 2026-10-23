# SPDX-License-Identifier: Apache-2.0
"""The aero pack's 3D pictures, run by pvbatch (never imported by nopekit).

``pvbatch --force-offscreen-rendering _scene3d.py <job.json>`` reads the
surfaces and tracks OpenFOAM's function objects wrote (copies that
``flow3d.py`` made of the bound files), draws the scene the job names, and
writes the PNG, the glTF when the job names one (``gltf``), and
``result.json`` beside the job::

    {"done": <sha256 of job.json>, "gl_renderer": <the GL renderer string>,
     "paraview": <version>, "png_sha256": <sha256 of the PNG>, "size": [w, h],
     "preset_sha256": <sha256 of the preset as ParaView exports it>,
     "bounds": <the body's bounds>, "camera": {position, focal, up, angle},
     "counts": {<piece>: <cells drawn>}, "scales": {<name>: {"ticks", "tick_texts"}},
     "band_colours": [[r, g, b], ...] (the wall scene),
     "gltf_sha256": <sha256 of the glTF, when asked>, "gltf_counts": {...}}

The scenes (``job["scene"]``):

- ``hero``: the body coloured by Cp (OpenFOAM's ``static(p)_coeff``) and
  OpenFOAM's ``streamLine`` tracks as tubes coloured by speed (its
  ``mag(U)``), each through its own lookup table of the Turbo preset, lit,
  over a floor and a gradient sky. With ``gltf``, the same run exports the
  3D file: the body triangulated and decimated, the tracks decimated and drawn
  as 4-sided tubes, each coloured as in the still.
- ``twin``: the hero's body and tubes at the hero's camera on white, with no
  floor, no sky and no FXAA (test only: the colour-truth anchor of the lit
  hero). ``variant`` ``unlit`` draws each pixel in a colour of the key;
  ``lit`` the hero's light; ``tonemap`` unlit with ParaView's tone mapping.
  The two last are the negative controls of the colour test.
- ``surface_cp``: the body alone, coloured by Cp, unlit, on white, at the
  hero's camera.
- ``wake``: OpenFOAM's iso-surface of total pressure coefficient 0, coloured
  by speed, lit, with the body in grey, from behind.
- ``wake_cuts``: OpenFOAM's three cuts across the wake, each clipped where its
  total pressure coefficient is above the job's ``cut_clip`` (the air with
  all of its energy), coloured by that coefficient unlit, with the body in
  grey and lit, from behind.
- ``wall``: the body coloured by OpenFOAM's ``yPlus`` in bands: ParaView's
  Threshold splits the cells at the job's band edges, and each band is drawn
  unlit in the colour the Turbo lookup table gives the middle of its share of
  the key (``band_at``). The result names each band's colour.

What each step is, measured on ParaView 6.2.0 (llvmpipe) while it was
written, on the motorBike L0 function-object files of the design's P0:

- **The body.** XMLPolyDataReader, MergeBlocks, ExtractSurface and
  SurfaceNormals (feature angle 50, splitting on, consistency off: the
  surface's own orientation is kept). The display culls front faces:
  OpenFOAM's patch normals point out of the fluid, into the body, so the faces
  toward the camera are back faces, and of the two coincident faces of each
  ``-shadow`` baffle the one toward the camera is kept. Measured: drawn with
  both faces, the baffles speckled.
- **The colours.** ``ApplyPreset`` by name; RGB; continuous; a fixed range;
  the job's ``over`` above, ``under`` below, NaN ``over`` (Turbo has no
  NanColor, and ParaView's default reads as green: measured). In the PNGs,
  ``InterpolateScalarsBeforeMapping`` 1: the value is interpolated across
  each triangle and then mapped, so every pixel is a colour of the table.
  Measured on the L0 files: the unlit Cp still's farthest pixel 0.65 of a
  byte from the ramp; with it 0 (the colours mapped at the vertices, then
  blended), 15% of the pixels more than 2 off, up to 90 (a grey vertex
  below the scale blended with a blue one). On the glTF's displays it is 0:
  each vertex takes its table colour, which is what makes the exporter write
  ``COLOR_0`` and not a texture (measured: with it 1, ``TEXCOORD_0`` and a
  4.09 MB file).
- **The light.** ParaView's light kit with a key light warmth of 0.5 (white:
  the hue of each colour survives), FXAA on the lit scenes (the hero, the
  wake) and off on the others, so their coloured pixels are the key's. Tone
  mapping and SSAO off: each moved every colour (SSAO also whitened the sky
  and added grain); shadows need OSPRay, which the build does not have.
- **The camera** is set from the body's bounds and the job's numbers, then
  set again after the first Render (the first Render resets it).
- **The bytes.** ParaView's PNG carries a text chunk; Pillow writes the
  pixels again with no chunk but the image's, so two runs write the same
  bytes.
- **The ticks.** matplotlib's ``MaxNLocator`` and ``ScalarFormatter``, as in
  cfd-openfoam's ``_scene.py``.

*Rejected:* ParaView's StreamTracer (the tracks would be ParaView's
arithmetic, not OpenFOAM's); a Calculator for |U|/U_inf or for Cp (OpenFOAM
wrote both fields); a colour bar in the PNG (the page draws the legend from
the same scale); Threshold for the wake cuts (blocky edges, measured in
``d_wake_slices.png``: Clip by scalar cuts each cell at the value).
"""
import hashlib
import json
import math
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
    scene = job["scene"]
    variant = job.get("variant", "")
    width, height = (int(v) for v in job["size"])
    look = job["look"]
    over = [c / 255.0 for c in job["over"]]
    under = [c / 255.0 for c in job["under"]]
    counts = {}

    def lut(name, lo, hi):
        table = pv.GetColorTransferFunction(name)
        table.ApplyPreset(job["preset"], True)
        table.ColorSpace = "RGB"
        table.Discretize = 0
        table.AutomaticRescaleRangeMode = "Never"
        table.RescaleTransferFunction(float(lo), float(hi))
        table.UseAboveRangeColor = 1
        table.AboveRangeColor = over
        table.UseBelowRangeColor = 1
        table.BelowRangeColor = under
        table.NanColor = over
        return table

    def unlit(display):
        display.Ambient = 1.0
        display.Diffuse = 0.0
        display.Specular = 0.0

    def coloured(source, view, field, name, *, lit, specular=(0.0, 1.0), vertex=False):
        """Show ``source`` coloured by ``field`` through the job's range for
        ``name``. The table is set after ``ColorBy``: measured, ``ColorBy``
        rescales a table to the data's range (the hero's tubes drew the free
        stream orange on [0, 27.6] m/s, the range of the tracks)."""
        shown = pv.Show(source, view)
        pv.ColorBy(shown, ("POINTS", field))
        table = tables[name] = lut(field, *ranges[name])
        shown.LookupTable = table
        shown.InterpolateScalarsBeforeMapping = 0 if vertex else 1
        if lit:
            shown.Specular, shown.SpecularPower = float(specular[0]), float(specular[1])
        else:
            unlit(shown)
        pv.HideScalarBarIfNotNeeded(table, view)
        return shown

    def grey(source, view):
        shown = pv.Show(source, view)
        shown.ColorArrayName = ["POINTS", ""]
        g = float(look["body_grey"])
        shown.DiffuseColor = [g, g, g]
        shown.AmbientColor = [g, g, g]
        shown.Specular = float(look["body_specular"])
        shown.BackfaceRepresentation = "Cull Frontface"
        return shown

    # -- the body ---------------------------------------------------------- #
    # The wall scene's body is its y+ surface (the same patch, cell values).
    body_reader = pv.XMLPolyDataReader(FileName=[job["yplus"] if scene == "wall" else job["body"]])
    body = pv.SurfaceNormals(Input=pv.ExtractSurface(Input=pv.MergeBlocks(Input=body_reader)),
                             FeatureAngle=50.0, Splitting=1, Consistency=0)
    body_reader.UpdatePipeline()
    b = body_reader.GetDataInformation().GetBounds()
    counts["body"] = int(body_reader.GetDataInformation().GetNumberOfCells())
    L, W, H = b[1] - b[0], b[3] - b[2], b[5] - b[4]
    centre = [(b[0] + b[1]) / 2, (b[2] + b[3]) / 2, (b[4] + b[5]) / 2]
    ground = job.get("ground_z")
    ground = float(ground) if ground is not None else b[4]

    # -- the view ---------------------------------------------------------- #
    plain = scene in ("twin", "surface_cp", "wall")
    view = pv.CreateRenderView()
    view.ViewSize = [width, height]
    view.OrientationAxesVisibility = 0
    view.UseColorPaletteForBackground = 0
    if plain:
        view.BackgroundColorMode = "Single Color"
        view.Background = [1.0, 1.0, 1.0]
    else:
        view.BackgroundColorMode = "Gradient"
        view.Background = list(look["background"])
        view.Background2 = list(look["background2"])
    view.KeyLightWarmth = float(look["key_light_warmth"])
    # FXAA on the lit scenes alone: on the cuts it blended each cut's edge
    # with the floor, and 1% of the cuts' pixels left the ramp (measured).
    view.UseFXAA = 1 if (look["fxaa"] and scene in ("hero", "wake")) else 0
    # The tonemap twin takes ParaView's default tone mapping (type 3,
    # vtkToneMappingPass's GenericFilmic); the property is an index, not a name.
    view.UseToneMapping = 1 if variant == "tonemap" else 0

    if not plain:
        floor_look = look["floor"]
        x0, x1 = b[0] - floor_look["upstream_l"] * L, b[1] + floor_look["downstream_l"] * L
        side = floor_look["side_l"] * L
        floor = pv.Plane(Origin=[x0, centre[1] - side, ground], Point1=[x1, centre[1] - side, ground],
                         Point2=[x0, centre[1] + side, ground])
        shown = pv.Show(floor, view)
        shown.ColorArrayName = ["POINTS", ""]
        shown.DiffuseColor = [float(floor_look["grey"])] * 3
        shown.Ambient = float(floor_look["ambient"])
        shown.Diffuse = float(floor_look["diffuse"])

    ranges = job.get("ranges") or {}
    fields = job["fields"]
    tables = {}
    lit_scene = scene in ("hero", "wake", "wake_cuts") or variant == "lit"
    spec = look["specular"]
    tracks = None

    if scene in ("hero", "twin", "surface_cp"):
        shown = coloured(body, view, fields["cp"], "cp",
                         lit=scene == "hero" or variant == "lit", specular=spec["body"])
        shown.BackfaceRepresentation = "Cull Frontface"
    if scene in ("hero", "twin"):
        readers = [pv.XMLPolyDataReader(FileName=[path]) for path in job["tracks"]]
        tracks = pv.AppendGeometry(Input=readers)
        tracks.UpdatePipeline()
        counts["tracks"] = int(tracks.GetDataInformation().GetNumberOfCells())
        tube = pv.Tube(Input=tracks, Radius=float(job["tube"]["radius_l"]) * L,
                       NumberofSides=int(job["tube"]["sides"]), Capping=1)
        coloured(tube, view, fields["speed"], "speed",
                 lit=scene == "hero" or variant == "lit", specular=spec["tubes"])
    if scene == "wake":
        grey(body, view)
        wake_reader = pv.XMLPolyDataReader(FileName=[job["wake"]])
        wake = pv.SurfaceNormals(Input=pv.ExtractSurface(Input=wake_reader),
                                 FeatureAngle=50.0, Splitting=0, Consistency=1)
        wake_reader.UpdatePipeline()
        counts["wake"] = int(wake_reader.GetDataInformation().GetNumberOfCells())
        coloured(wake, view, fields["speed"], "speed", lit=True, specular=spec["wake"])
    if scene == "wake_cuts":
        grey(body, view)
        counts["cuts"] = []
        for path in job["cuts"]:
            reader = pv.XMLPolyDataReader(FileName=[path])
            # Keeps the part below the value (Invert 1, ParaView's default).
            clip = pv.Clip(Input=reader, ClipType="Scalar", Scalars=["POINTS", fields["cpt"]],
                           Value=float(job["cut_clip"]), Invert=1)
            clip.UpdatePipeline()
            counts["cuts"].append(int(clip.GetDataInformation().GetNumberOfCells()))
            coloured(pv.ExtractSurface(Input=clip), view, fields["cpt"], "cpt", lit=False)
    band_colours = []
    if scene == "wall":
        reader = pv.XMLPolyDataReader(FileName=[job["yplus"]])
        table = lut("band_probe", 0.0, 1.0)
        mapper = table.GetClientSideObject()
        edges = [float(e) for e in job["bands"]] + [1e30]
        counts["bands"] = []
        for lo, hi, at in zip(edges, edges[1:], job["band_at"]):
            rgb = [0.0, 0.0, 0.0]
            mapper.GetColor(float(at), rgb)
            band_colours.append([int(round(255 * c)) for c in rgb])
            piece = pv.Threshold(Input=reader, Scalars=["CELLS", fields["yplus"]],
                                 LowerThreshold=lo, UpperThreshold=hi,
                                 ThresholdMethod="Between")
            piece.UpdatePipeline()
            counts["bands"].append(int(piece.GetDataInformation().GetNumberOfCells()))
            shown = pv.Show(pv.ExtractSurface(Input=piece), view)
            shown.ColorArrayName = ["POINTS", ""]
            shown.AmbientColor = list(rgb)
            shown.DiffuseColor = list(rgb)
            unlit(shown)
            shown.BackfaceRepresentation = "Cull Frontface"

    # -- the camera -------------------------------------------------------- #
    cam = job["camera"]
    focal = [centre[0] + cam["focal"][0] * L, centre[1] + cam["focal"][1] * W,
             centre[2] + cam["focal"][2] * H]
    dist = cam["distance_diag"] * math.sqrt(L * L + W * W + H * H)
    az, el = math.radians(cam["azimuth_deg"]), math.radians(cam["elevation_deg"])
    position = [focal[0] + dist * math.cos(el) * math.cos(az),
                focal[1] + dist * math.cos(el) * math.sin(az),
                focal[2] + dist * math.sin(el)]

    def set_camera():
        view.CameraPosition = position
        view.CameraFocalPoint = focal
        view.CameraViewUp = [0.0, 0.0, 1.0]
        view.CameraViewAngle = float(cam["view_angle_deg"])

    set_camera()
    pv.Render(view)
    set_camera()
    pv.Render(view)
    shot = os.path.join(out_dir, "paraview.png")
    pv.SaveScreenshot(shot, view, ImageResolution=[width, height], CompressionLevel=9)
    png = os.path.join(out_dir, job["png"])
    Image.open(shot).convert("RGB").save(png, format="PNG", optimize=False, compress_level=9)
    with open(png, "rb") as fh:
        png_sha = _sha256(fh.read())

    result = {"done": _sha256(raw), "paraview": pv.GetParaViewSourceVersion(),
              "png_sha256": png_sha, "size": [width, height],
              "preset_sha256": _sha256(_preset_text(job["preset"]).encode("utf-8")),
              "bounds": list(b), "counts": counts, "lit": lit_scene,
              "camera": {"position": position, "focal": focal, "up": [0.0, 0.0, 1.0],
                         "angle": float(cam["view_angle_deg"])}}
    scales = {}
    for name in tables:
        values, texts = _ticks(float(ranges[name][0]), float(ranges[name][1]), int(job["ticks"]))
        scales[name] = {"ticks": values, "tick_texts": texts}
    result["scales"] = scales
    if band_colours:
        result["band_colours"] = band_colours

    # -- the 3D file (the hero only) --------------------------------------- #
    if job.get("gltf") and scene == "hero":
        opts = job["gltf_opts"]
        for source in list(pv.GetSources().values()):
            pv.Hide(source, view)
        light = pv.Decimate(Input=pv.Triangulate(Input=body),
                            TargetReduction=float(opts["body_reduction"]))
        coloured(light, view, fields["cp"], "cp", lit=True, specular=spec["body"],
                 vertex=True)
        lines = pv.Tube(Input=pv.DecimatePolyline(Input=tracks,
                                                  TargetReduction=float(opts["track_reduction"])),
                        Radius=float(job["tube"]["radius_l"]) * L,
                        NumberofSides=int(opts["sides"]), Capping=1)
        coloured(lines, view, fields["speed"], "speed", lit=True, specular=spec["tubes"],
                 vertex=True)
        set_camera()
        pv.Render(view)
        target = os.path.join(out_dir, job["gltf"])
        pv.ExportView(target, view=view, InlineData=1, SaveNormal=0, SaveBatchId=0,
                      SaveNaNValues=0)
        with open(target, "rb") as fh:
            result["gltf_sha256"] = _sha256(fh.read())
        gl_counts = {}
        for name, source in (("body", light), ("tubes", lines)):
            source.UpdatePipeline()
            info = source.GetDataInformation()
            gl_counts[name] = {"points": int(info.GetNumberOfPoints()),
                               "cells": int(info.GetNumberOfCells())}
        result["gltf_counts"] = gl_counts

    caps = view.GetRenderWindow().ReportCapabilities() or ""
    gl = ""
    for line in caps.splitlines():
        if "renderer string" in line:
            gl = line.split(":", 1)[1].strip()
            break
    result["gl_renderer"] = gl
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)


if __name__ == "__main__":
    main(sys.argv[1])
