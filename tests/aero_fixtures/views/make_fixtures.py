# SPDX-License-Identifier: Apache-2.0
"""Make the small function-object files of ``tests/aero_fixtures/views/``
from a real aero.converged run on the motorBike's base mesh. Run by hand in
the checked ParaView, never by a test::

    pvbatch62 tests/aero_fixtures/views/make_fixtures.py <postProcessing> <time> <out dir>

``<postProcessing>`` is the case's ``postProcessing/`` folder of an L0 solve
with the pack's function objects (ESI v2606), ``<time>`` its last time. The
committed files were made on 2026-10-23 from the design's P0 run (L0, 354 182
cells, 1500 iterations, ``mbd/p0/L0/postProcessing``, time 1500).

What it does, with ParaView's own filters and no arithmetic on a field:

- ``body.vtp``: the body surface triangulated and decimated by 0.95
  (``Decimate``: it keeps a subset of OpenFOAM's points and their values);
- ``tracksCentre.vtp``, ``tracksFar.vtp``: every track, each polyline
  decimated by 0.95 (``DecimatePolyline``: a subset of its points);
- ``wake.vtp``: the wake surface triangulated and decimated by 0.95;
- ``cut1.vtp`` .. ``cut3.vtp``: the three cuts as OpenFOAM wrote them;
- ``yplus.vtp``: the body's y+ surface, cells merged by ``QuadricClustering``
  with ``CopyCellData`` on (each kept cell keeps one of OpenFOAM's cell
  values).

Each is written compressed (``XMLPolyDataWriter``, zlib), with only the
array its picture reads. *Rejected:* the run's
files themselves (9 MB); a surface of our own with planted values (the
pictures would not be of OpenFOAM's flow, and the stand-in's bytes would be
of no real scene).
"""
import os
import sys

from paraview import simple as pv


def write(source, path, points=(), cells=()):
    """``source`` to ``path``, with only the arrays a picture reads."""
    writer = pv.XMLPolyDataWriter(Input=source, FileName=path)
    writer.ChooseArraysToWrite = 1
    writer.PointDataArrays = list(points)
    writer.CellDataArrays = list(cells)
    writer.CompressorType = "ZLib"
    writer.DataMode = "Appended"
    writer.EncodeAppendedData = 0
    writer.UpdatePipeline()


def main(post, time, out):
    os.makedirs(out, exist_ok=True)
    surfaces = os.path.join(post, "surfaces1", time)

    def read(path):
        return pv.ExtractSurface(Input=pv.MergeBlocks(Input=pv.XMLPolyDataReader(FileName=[path])))

    write(pv.ExtractSurface(Input=pv.Decimate(
        Input=pv.Triangulate(Input=read(os.path.join(surfaces, "body.vtp"))),
        TargetReduction=0.95)), os.path.join(out, "body.vtp"), points=["static(p)_coeff"])
    for name in ("tracksCentre", "tracksFar"):
        write(pv.ExtractSurface(Input=pv.DecimatePolyline(
            Input=read(os.path.join(post, "sets", name, time, "track0.vtp")),
            TargetReduction=0.95)), os.path.join(out, name + ".vtp"), points=["mag(U)"])
    write(pv.ExtractSurface(Input=pv.Decimate(
        Input=pv.Triangulate(Input=read(os.path.join(surfaces, "wakeIso.vtp"))),
        TargetReduction=0.95)), os.path.join(out, "wake.vtp"), points=["mag(U)"])
    for k in (1, 2, 3):
        write(pv.ExtractSurface(Input=read(os.path.join(surfaces, f"wakeCut{k}.vtp"))),
              os.path.join(out, f"cut{k}.vtp"), points=["total(p)_coeff"])
    clustered = pv.QuadricClustering(Input=read(os.path.join(surfaces, "bodyYPlus.vtp")))
    clustered.NumberofDimensions = [40, 14, 28]
    clustered.CopyCellData = 1
    write(pv.ExtractSurface(Input=clustered), os.path.join(out, "yplus.vtp"), cells=["yPlus"])


if __name__ == "__main__":
    main(*sys.argv[1:4])
