# SPDX-License-Identifier: Apache-2.0
"""Writes ``views/turbo.json``: ParaView's own ``Turbo`` colour map preset,
exported by ParaView. Run by hand in pvbatch (never imported by nopekit, never
run by a build)::

    pvbatch62 packs/aero-openfoam/views/_export_preset.py \\
        packs/aero-openfoam/views/turbo.json

The file is what ``vtkSMTransferFunctionPresets.GetPresetAsString`` returns
for the preset, byte for byte (tabs and all): on ParaView 6.2.0 (the locked
build), sha256 ``05f02e23...c94f``, 256 points, ``ColorSpace`` RGB, no
``NanColor``. The pictures colour their surfaces and lines with the same
preset by name (``_scene3d.py``), and the page draws its colour legends from
this file (``_scales.py``). The scene reports the sha256 of the preset it
applied, and a picture is drawn only when that is the sha256 of this file: the
legend is the map that coloured the pixels.

This is cfd-openfoam's ``views/_export_preset.py`` with ``NAME`` and these
words changed: the two packs export one preset each.

*Rejected:* colour stops typed by hand; Google's published Turbo table or
matplotlib's ``turbo`` (other programs' copies of the map: the pixels are
ParaView's); exporting at build time (each build would depend on ParaView for
its legend, and the memo reads no tool).
"""
import sys

from paraview import servermanager as sm

NAME = "Turbo"


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
