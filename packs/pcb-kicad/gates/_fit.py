# SPDX-License-Identifier: Apache-2.0
"""``pcb.enclosure_fit``'s geometry, run by the gate in a child process:

    python3 _fit.py <request.json>

The request names the board's STEP (as ``kicad-cli pcb export step`` wrote it),
the enclosure's STEP and where the board sits in the enclosure; the child prints
one JSON line: every named shape of the board's assembly (each footprint under
its reference, the board body under ``board``) with its distance to the enclosure
and the volume it shares with it, both OpenCascade's (BRepExtrema and a boolean
common, through CadQuery).

In a child, not in nopekit's process: an OpenCascade boolean can crash the
interpreter on bad geometry, and a crash here must read as this gate erroring,
not as the whole check run dying. It also keeps OpenCascade's imports out of the
gate's trace.
"""
from __future__ import annotations

import json
import sys


def _named_shapes(path: str) -> dict:
    """{name: shape} of the top assembly's components in a STEP file, read
    through OpenCascade's XCAF reader so each component keeps its name (KiCad
    names each footprint's model by its reference) and its placement. Shapes
    that share a name, or have none KiCad set, are fused into one compound."""
    import cadquery as cq
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    doc = TDocStd_Document(TCollection_ExtendedString("board"))
    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    if int(reader.ReadFile(path)) != 1:                    # IFSelect_RetDone
        raise RuntimeError(f"OpenCascade could not read {path}")
    reader.Transfer(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free = TDF_LabelSequence()
    tool.GetFreeShapes(free)
    found: dict[str, list] = {}

    def name_of(label) -> str:
        attr = TDataStd_Name()
        return attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""

    for i in range(1, free.Length() + 1):
        top = free.Value(i)
        comps = TDF_LabelSequence()
        tool.GetComponents_s(top, comps)
        if comps.Length() == 0:
            found.setdefault(name_of(top), []).append(cq.Shape.cast(tool.GetShape_s(top)))
        for j in range(1, comps.Length() + 1):
            comp = comps.Value(j)
            found.setdefault(name_of(comp), []).append(cq.Shape.cast(tool.GetShape_s(comp)))
    return {name: shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
            for name, shapes in found.items()}


def main(request_path: str) -> int:
    import cadquery as cq

    with open(request_path, encoding="utf-8") as fh:
        req = json.load(fh)
    refs = set(req["refs"])
    shapes = _named_shapes(req["board_step"])
    enclosure_wp = cq.importers.importStep(req["enclosure_step"])
    solids = enclosure_wp.solids().vals()
    if not solids:
        raise RuntimeError(f"no solid in {req['enclosure_step']}: an enclosure is a volume")
    enclosure = solids[0] if len(solids) == 1 else cq.Compound.makeCompound(solids)
    place = req["placement"]
    loc = cq.Location(cq.Vector(place["x"], place["y"], place["z"]), cq.Vector(0, 0, 1),
                      place["rot_z_deg"])
    board_parts = [s for n, s in shapes.items() if n not in refs]
    parts = {n: s for n, s in shapes.items() if n in refs}
    if board_parts:
        parts["board"] = (board_parts[0] if len(board_parts) == 1
                          else cq.Compound.makeCompound(board_parts))
    out = {}
    for name, shape in sorted(parts.items()):
        moved = shape.moved(loc)
        common = moved.intersect(enclosure)
        out[name] = {"clearance_mm": moved.distance(enclosure),
                     "interference_mm3": common.Volume() if common.Solids() else 0.0}
    print(json.dumps({"parts": out, "names": sorted(shapes)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
