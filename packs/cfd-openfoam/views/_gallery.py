# SPDX-License-Identifier: Apache-2.0
"""Writes the README's gallery picture of this pack,
``docs/img/packs/cfd-openfoam.png``: the two stills that a site build
published for the baseline, one above the other, each with its colour scale.
Run by hand in pvbatch (never imported by nopekit, never run by a build)::

    pvbatch62 packs/cfd-openfoam/views/_gallery.py \\
        <project>/site/assets/figures/cfd.pressure_drop/<entry> \\
        docs/img/packs/cfd-openfoam.png

``<project>`` is the pack's baseline wrapped as a project
(``tests/_projects.wrap_pack_baseline``), after ``nopekit check --tier 2``,
``site init`` and ``site build`` on ESI v2606 and the checked ParaView 6.2.0.
The folder holds the stills that ``_scene.py`` drew and their sidecars
(``*.view.json``). This script draws no field. It reads each sidecar, puts
its PNG into the picture pixel for pixel (``figimage``, no resampling), and
lets matplotlib draw the scale from the sidecar's own ``stops``, ``ticks``,
``over`` and ``under``: the stops that ``_scales.py`` read from
``viridis.json``, which ParaView exported. The plane names are the sidecar's
``marks``. So the picture shows what the page shows, and no number of its
own.

Measured on 2026-10-21 (ParaView 6.2.0, matplotlib 3.11 in its Python): about
1 s; two runs write the same bytes; each still's pixels, less its white
border, are in the picture with no change.

*Rejected:* a screenshot of the page (the chips and words of one build's
statuses, which go out of date in the README); one still alone (the speed
shows the flow, the pressure shows the drop the claim is about, and each
needs the other); a run of ``_scene.py`` from this script (a second drawing
of the same field, which can differ from the published one); matplotlib's
own ``viridis`` for the scale (another program's copy of the map).
"""
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
from matplotlib import colors, colorbar, pyplot  # noqa: E402
from PIL import Image, ImageChops  # noqa: E402

# The two stills, top to bottom: the speed shows the flow, the pressure the
# drop between the planes. The titles are the page's card titles with no
# "The", and the units are the sidecar's.
VIEWS = ("cfd-openfoam.speed", "cfd-openfoam.pressure")
TITLES = {"cfd-openfoam.speed": "Speed of the flow",
          "cfd-openfoam.pressure": "Static pressure"}
# Layout in px at DPI 100. MARGIN keeps the scale's end triangles and the
# last tick text inside the picture; FONT is 22 px so that the text is about
# 12 px high at the README's 900 px width.
DPI = 100
MARGIN = 60
TITLE_H = 56
LABEL_H = 44
BAR_GAP = 22
BAR_H = 30
TICK_H = 70
FONT = 22
INK = "#1d1d1f"


def _load(folder, view):
    with open(os.path.join(folder, view + ".view.json"), encoding="utf-8") as fh:
        side = json.load(fh)
    image = Image.open(os.path.join(folder, side["files"]["image"]["name"])).convert("RGB")
    # The still keeps 5% of white on each side of the cut (``_scene.py``'s
    # frame). The scale below it is as wide as the cut, so that white is
    # cut off; every other pixel stays as the still has it.
    box = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    marks = [{"text": m["text"], "x": m["at"] * image.size[0] - box[0]}
             for m in side.get("marks") or ()]
    return side, image.crop(box), marks


def main(folder, target):
    panels = [_load(folder, view) for view in VIEWS]
    width = max(image.size[0] for _, image, _ in panels) + 2 * MARGIN
    panel_h = [TITLE_H + LABEL_H + image.size[1] + BAR_GAP + BAR_H + TICK_H
               for _, image, _ in panels]
    height = sum(panel_h) + MARGIN // 2
    fig = pyplot.figure(figsize=(width / DPI, height / DPI), dpi=DPI, facecolor="white")
    pyplot.rcParams.update({"font.size": FONT, "font.family": "DejaVu Sans"})

    top = height - MARGIN // 2
    for (view, (side, image, marks)), h in zip(zip(VIEWS, panels), panel_h):
        scale = side["scale"]
        w, ih = image.size
        y_img = top - TITLE_H - LABEL_H - ih
        fig.text(MARGIN / width, (top - TITLE_H / 2) / height,
                 f"{TITLES[view]} ({scale['units']})", ha="left", va="center",
                 color=INK, fontsize=FONT + 4, fontweight="bold")
        fig.figimage(image, xo=MARGIN, yo=y_img, origin="upper")
        # Each plane's name above its line, so that no text hides the field.
        for mark in marks:
            fig.text((MARGIN + mark["x"]) / width, (y_img + ih + 8) / height,
                     f" {mark['text']} ", ha="center", va="bottom", color="white",
                     fontsize=FONT - 4,
                     bbox={"boxstyle": "round,pad=0.25", "fc": INK, "ec": "none"})
        y_bar = y_img - BAR_GAP - BAR_H
        ax = fig.add_axes([MARGIN / width, y_bar / height, w / width, BAR_H / height])
        cmap = colors.LinearSegmentedColormap.from_list(
            view, [(s["at"], s["colour"]) for s in scale["stops"]], N=1024)
        extend = {(True, True): "both", (True, False): "max",
                  (False, True): "min"}.get((bool(scale["over"]), bool(scale["under"])),
                                            "neither")
        if scale["over"]:
            cmap.set_over(scale["over"])
        if scale["under"]:
            cmap.set_under(scale["under"])
        bar = colorbar.ColorbarBase(ax, cmap=cmap, orientation="horizontal",
                                    norm=colors.Normalize(scale["lo"], scale["hi"]),
                                    extend=extend, extendfrac=0.015)
        bar.set_ticks([t["value"] for t in scale["ticks"]],
                      labels=[t["text"] for t in scale["ticks"]])
        bar.outline.set_visible(False)
        ax.tick_params(colors=INK, length=6, labelsize=FONT - 2)
        top -= h

    fig.savefig(target, dpi=DPI, facecolor="white", metadata={"Software": None})
    pyplot.close(fig)
    # Pillow writes the pixels again with no text chunk, as ``_scene.py`` does.
    with Image.open(target) as im:
        pixels = im.convert("RGB")
    pixels.save(target, optimize=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
