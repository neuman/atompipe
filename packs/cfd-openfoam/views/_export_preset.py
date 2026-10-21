# SPDX-License-Identifier: Apache-2.0
"""Writes ``views/viridis.json``: ParaView's own ``Viridis`` colour map preset,
exported by ParaView. Run by hand in pvbatch (never imported by nopekit, never
run by a build)::

    pvbatch62 packs/cfd-openfoam/views/_export_preset.py \\
        packs/cfd-openfoam/views/viridis.json

The file is what ``vtkSMTransferFunctionPresets.GetPresetAsString`` returns
for the preset, byte for byte (tabs and all). The stills colour their
cells with the same preset by name (``_scene.py``), and the page draws its
colour legend from this file (``_scales.py``). The scene reports the sha256
of the preset it applied, and a picture is drawn only when that is the
sha256 of this file: the legend is the map that coloured
the pixels.

*Rejected:* colour stops typed by hand (the design's first draft had five);
matplotlib's ``viridis`` table (another program's copy of the map: the
pixels are ParaView's); exporting at build time (each build would depend on
ParaView for its legend, and the memo reads no tool).
"""
import sys

from paraview import servermanager as sm

NAME = "Viridis"


def main(target):
    presets = sm.vtkSMTransferFunctionPresets.GetInstance()
    for index in range(presets.GetNumberOfPresets()):
        if presets.GetPresetName(index) == NAME:
            text = presets.GetPresetAsString(index)
            break
    else:
        raise SystemExit(f"ParaView has no preset named {NAME!r}")
    with open(target, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


if __name__ == "__main__":
    main(sys.argv[1])
