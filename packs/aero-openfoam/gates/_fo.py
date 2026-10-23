# SPDX-License-Identifier: Apache-2.0
"""The dictionaries aero-openfoam writes into every staged case, as text.

The pack owns these, never the case: the mesh-quality limits snappyHexMesh
meshes to and checkMesh judges against, the cell caps, the decomposition, the
write precision and every function object. A case's own versions are replaced
in the staged copy, and OpenFOAM's own reading of that copy
(``foamDictionary -expand``) must show exactly these values before any tool
runs (``aero._as_read``).

**OpenFOAM computes every number and every geometry a picture draws.** The
function objects below write the drag-area history (``forceCoeffs``), the
residuals (``solverInfo``), the speed (``mag``), the pressure coefficients
(``pressure``, static and total), the body surface, the wake iso-surface, the
three wake cuts (``surfaces``) and the stream tracks (``streamLine``). The
site's viewgens only draw these files; ParaView computes nothing (GitHub #15).

Standard library only. Every value carries where it came from; what was tried
and rejected is beside it.
"""
from __future__ import annotations

#: The mesh-quality limits: ESI v2606's own ``etc/caseDicts/meshQualityDict``,
#: value for value, in its order. snappyHexMesh reads them as it meshes (its
#: ``meshQualityControls``) and ``checkMesh -meshQuality`` reads them from
#: ``system/meshQualityDict`` to judge the result, so the mesher and the judge
#: hold one set of numbers. What slipped through P0 (measured, 2026-10-23): the
#: motorBike tutorial's own dict sets ``minFaceWeight 0.02``, its meshes pass it,
#: and 1 095 faces of its L0 mesh (2 084 at L1) fail the etc dict's 0.05; meshed
#: with the etc dict staged before snappy, L0 has 0 faces in error. Rejected:
#: the case's own limits (a case that relaxes ``maxNonOrtho`` to 180 then
#: passes its own judge: P0's ``relaxed_quality``); judging with plain
#: ``checkMesh`` (its fixed skewness limit 4 fails every motorBike mesh:
#: "Failed 1 mesh checks", skewness 8.13 on 29 faces at L2).
QUALITY = (
    ("maxNonOrtho", "65"),
    ("maxBoundarySkewness", "20"),
    ("maxInternalSkewness", "4"),
    ("maxConcave", "80"),
    ("minVol", "1e-13"),
    ("minTetQuality", "1e-15"),
    ("minArea", "-1"),
    ("minTwist", "0.02"),
    ("minDeterminant", "0.001"),
    ("minFaceWeight", "0.05"),
    ("minVolRatio", "0.01"),
    ("minTriangleTwist", "-1"),
    ("minEdgeLength", "-1"),
)

#: The thresholds ``checkMesh -meshQuality`` prints in its "Checking faces in
#: error" block when it reads :data:`QUALITY`, line by line, in its order, as
#: numbers (``(0..1)`` dropped). Measured on v2606 (P0, the spheroid L0): nine
#: lines. A block whose numbers differ was judged against another dictionary,
#: and is an error. Rejected: comparing the lines' text (snappyHexMesh and
#: checkMesh space them differently: ``>  65 degrees`` and ``> 65  degrees``).
CHECKED = ((65.0,), (1e-13,), (1e-15,), (80.0,), (4.0, 20.0), (0.05,), (0.01,), (0.02,),
           (0.001,))

#: snappyHexMesh's two smoothing controls beside the limits, the tutorial's
#: values (motorBike v2606). Not quality limits: how hard snappy works to meet
#: them. Rejected: the tutorial's ``relaxed { maxNonOrtho 75; }`` (a second,
#: looser set the layer stage may mesh to; the judge reads one set).
SMOOTHING = (("nSmoothScale", "4"), ("errorReduction", "0.75"))

#: The precision the pack's function objects write at: 12 (13 significant
#: digits). The iterative uncertainty is a half-range of the last iterations'
#: drag areas; on the spheroid baseline it is 1e-7 of the value (P0), so a
#: history printed at OpenFOAM's default 6 would read every window as flat or as
#: one quantum. Copied from cfd-openfoam's ``WRITE_PRECISION`` and its reason.
WRITE_PRECISION = 12


def quality_entries() -> str:
    return "".join(f"    {k} {v};\n" for k, v in QUALITY)


def quality_controls() -> str:
    """The ``meshQualityControls`` entry the pack writes into snappyHexMeshDict."""
    return ("meshQualityControls\n{\n    // nopekit's aero-openfoam: the pack's limits, never the "
            "case's\n" + quality_entries()
            + "".join(f"    {k} {v};\n" for k, v in SMOOTHING) + "}\n")


def quality_dict() -> str:
    """``system/meshQualityDict``: the limits checkMesh -meshQuality reads."""
    return ("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class dictionary;\n"
            "    object meshQualityDict;\n}\n// written by nopekit's aero-openfoam pack\n"
            + quality_entries())


def split(n: int) -> tuple:
    """``n`` ranks as (nx, ny, 1) slabs, nx >= ny, nx * ny = n, as square as
    ``n`` allows: the most along the flow, where the wake's cells are."""
    n = int(n)
    ny = max(d for d in range(1, int(n ** 0.5) + 1) if n % d == 0)
    return (n // ny, ny, 1)


def decompose_dict(n: int) -> str:
    """``system/decomposeParDict``: ``n`` ranks, ``hierarchical`` over the
    box's axes (``split``), x first. Deterministic: the same mesh gives the same
    processor meshes, so the same run gives the same drag-area history, bit for
    bit. What slipped through P3 (2026-10-23, measured on the spheroid): with
    ``scotch`` three decompositions of one bit-identical mesh gave three cell
    splits (10445/10287/10342/10479, 10442/10316/10459/10336, ...) and three
    U_I (0.0065%, 0.0063%, 0.0064%): a verdict entry's bytes moved run to run on
    identical inputs, which the cache reads as two outcomes for one rho.
    Rejected: ``scotch`` (above); ``simple`` (the same slabs with no order to
    the axes); the tutorial's ``hierarchical (3 2 1)`` (fixed at 6 ranks)."""
    nx, ny, nz = split(n)
    return ("FoamFile\n{\n    version 2.0;\n    format ascii;\n    class dictionary;\n"
            "    object decomposeParDict;\n}\n// written by nopekit's aero-openfoam pack\n"
            f"numberOfSubdomains {int(n)};\nmethod hierarchical;\n"
            f"coeffs\n{{\n    n ({nx} {ny} {nz});\n    order xyz;\n}}\n")


#: What the pack's function objects are called: their names are the paths their
#: files land under (``postProcessing/<name>/...``), which the summary names and
#: a viewgen binds.
FORCE, RESIDUALS, MAG, CP, CPT, SURFACES = ("forceCoeffs1", "solverInfo1", "mag1", "cp1",
                                            "cpt1", "surfaces1")
TRACKS = ("tracksCentre", "tracksFar")

#: The surfaces ``surfaces1`` writes, each to ``postProcessing/surfaces1/<time>/
#: <name>.vtp``. One ``cuttingPlane`` is one plane (P0: a multi-plane cut is not
#: a surface type), so the three wake cuts are three surfaces.
BODY, WAKE_ISO = "body", "wakeIso"
CUTS = ("wakeCut1", "wakeCut2", "wakeCut3")

#: OpenFOAM's own names for the fields the pressure objects write (P0, v2606):
#: ``static(p)_coeff`` (Cp) and ``total(p)_coeff`` (CpT). Every surface carries
#: every field of the ``surfaces1`` list: a per-surface ``fields`` entry is
#: ignored (P0), so none is written.
CP_FIELD, CPT_FIELD, SPEED_FIELD = "static(p)_coeff", "total(p)_coeff", "mag(U)"

#: Where the wake cuts stand behind the body: x_max + these x the body length.
#: From the design's d_hero3 scene (2026-10-22): 0.12 L shows the near wake
#: under the tail, 0.6 L its middle, 1.35 L where it has spread. A picture's
#: choice, stated, not a judgment: no gate reads a cut.
CUT_AT = (0.12, 0.6, 1.35)

#: The two seed rakes, as fractions of the body box (L, W, H; the design's
#: §6.1, measured on d_hero3): the centre rake a line upstream of the nose at
#: x_min - 0.08 L, y_c +- 0.05 W, from 0.04 H to 1.07 H over the box's bottom,
#: 60 points; the far rake on the +y side, from 0.82 to 0.97 of the half-width,
#: 0.04 H to 0.89 H, 18 points. Rejected: a horizontal rake (it read as a flat
#: sheet through the bike: hero_cull_grad.png) and a near-side rake (it hid the
#: body). ``type uniform; axis xyz`` because ESI v2606 has no ``lineUniform``
#: (P0).
RAKES = {
    "tracksCentre": {"x": -0.08, "y": (-0.05, 0.05), "z": (0.04, 1.07), "n": 60},
    "tracksFar": {"x": -0.08, "y": (0.82, 0.97), "z": (0.04, 0.89), "n": 18},
}


def _v(p) -> str:
    return "(" + " ".join(f"{float(c):.6g}" for c in p) + ")"


def rakes(box) -> dict:
    """``{name: (start, end, n)}`` for the two rakes over the body box
    ``((x0, y0, z0), (x1, y1, z1))``. The centre rake's y is about the box's
    centre line; the far rake's y is a fraction of the half-width from it."""
    (x0, y0, z0), (x1, y1, z1) = box
    length, width, height = x1 - x0, y1 - y0, z1 - z0
    yc = 0.5 * (y0 + y1)
    out = {}
    for name, r in RAKES.items():
        x = x0 + r["x"] * length
        if name == "tracksCentre":
            ya, yb = yc + r["y"][0] * width, yc + r["y"][1] * width
        else:
            ya, yb = yc + r["y"][0] * 0.5 * width, yc + r["y"][1] * 0.5 * width
        out[name] = ((x, ya, z0 + r["z"][0] * height), (x, yb, z0 + r["z"][1] * height), r["n"])
    return out


def cuts(box) -> list:
    """The three wake cuts' x positions behind the body box."""
    (x0, _y0, _z0), (x1, _y1, _z1) = box
    return [x1 + f * (x1 - x0) for f in CUT_AT]


def functions(*, group: str, u_inf: float, l_ref: float, cofr, box) -> str:
    """The ``functions`` entry aero.converged writes into the staged controlDict.

    forceCoeffs with ``Aref 1`` makes its Cd column the drag area CdA in m^2
    (Cd = F_D / (q Aref), so Cd x 1 m^2 = F_D / q). Rejected: the tutorial's
    "Estimated" Aref 0.75, a frontal area nobody measured (P0 rasterised 0.644
    m^2); a claim about CdA needs no area. ``rho rhoInf; rhoInf 1``: the
    incompressible p is kinematic, so with a density of 1 the coefficients are
    the ones the real density gives. Every picture object runs once, at the
    last iteration (``onEnd``)."""
    s = [f"    {FORCE}\n    {{\n        type forceCoeffs;\n        libs (forces);\n"
         f"        writeControl timeStep;\n        writeInterval 1;\n"
         f"        writePrecision {WRITE_PRECISION};\n        log false;\n"
         f"        patches ({group});\n        rho rhoInf;\n        rhoInf 1;\n"
         f"        liftDir (0 0 1);\n        dragDir (1 0 0);\n        CofR {_v(cofr)};\n"
         f"        pitchAxis (0 1 0);\n        magUInf {float(u_inf)!r};\n"
         f"        lRef {float(l_ref)!r};\n        Aref 1;\n    }}\n",
         f"    {RESIDUALS}\n    {{\n        type solverInfo;\n        libs (utilityFunctionObjects);\n"
         f"        fields (U p k omega);\n        writeResidualFields no;\n"
         f"        writeControl timeStep;\n        writeInterval 1;\n    }}\n",
         f"    {MAG}\n    {{\n        type mag;\n        libs (fieldFunctionObjects);\n"
         f"        field U;\n        executeControl onEnd;\n        writeControl onEnd;\n    }}\n"]
    for name, mode in ((CP, "staticCoeff"), (CPT, "totalCoeff")):
        s.append(f"    {name}\n    {{\n        type pressure;\n        libs (fieldFunctionObjects);\n"
                 f"        mode {mode};\n        p p;\n        U U;\n        rho rhoInf;\n"
                 f"        rhoInf 1;\n        pInf 0;\n        UInf ({float(u_inf)!r} 0 0);\n"
                 f"        executeControl onEnd;\n        writeControl onEnd;\n    }}\n")
    planes = "".join(
        f"            {name}\n            {{\n                type cuttingPlane;\n"
        f"                planeType pointAndNormal;\n"
        f"                pointAndNormalDict\n                {{\n"
        f"                    point ({x:.6g} 0 0);\n                    normal (1 0 0);\n"
        f"                }}\n                interpolate true;\n            }}\n"
        for name, x in zip(CUTS, cuts(box)))
    s.append(f"    {SURFACES}\n    {{\n        type surfaces;\n        libs (sampling);\n"
             f"        executeControl onEnd;\n        writeControl onEnd;\n"
             f"        surfaceFormat vtk;\n"
             f"        fields ({CP_FIELD} {CPT_FIELD} {SPEED_FIELD});\n"
             f"        surfaces\n        {{\n"
             f"            {BODY}\n            {{\n                type patch;\n"
             f"                patches ({group});\n                interpolate true;\n"
             f"            }}\n"
             f"            {WAKE_ISO}\n            {{\n                type isoSurface;\n"
             f"                isoField {CPT_FIELD};\n                isoValue 0;\n"
             f"                interpolate true;\n            }}\n"
             + planes + "        }\n    }\n")
    for name, (start, end, n) in rakes(box).items():
        s.append(f"    {name}\n    {{\n        type streamLine;\n        libs (fieldFunctionObjects);\n"
                 f"        executeControl onEnd;\n        writeControl onEnd;\n"
                 f"        setFormat vtk;\n        U U;\n        direction forward;\n"
                 f"        fields (U {SPEED_FIELD});\n        lifeTime 10000;\n"
                 f"        nSubCycle 5;\n        cloud {name}Cloud;\n"
                 f"        seedSampleSet\n        {{\n            type uniform;\n"
                 f"            axis xyz;\n            start {_v(start)};\n"
                 f"            end {_v(end)};\n            nPoints {int(n)};\n        }}\n    }}\n")
    return ("// Written by nopekit's aero-openfoam pack: the case's own function objects\n"
            "// are refused, so every number below is the pack's.\nfunctions\n{\n"
            + "".join(s) + "}\n")


def picture_files(time: str) -> list[str]:
    """The files the picture objects write at ``time``, relative to the case:
    the body, the wake iso-surface, the three cuts and the two track sets (under
    ``postProcessing/sets/<name>/``, not the function's own directory: P0)."""
    base = f"postProcessing/{SURFACES}/{time}"
    return ([f"{base}/{BODY}.vtp", f"{base}/{WAKE_ISO}.vtp"]
            + [f"{base}/{c}.vtp" for c in CUTS]
            + [f"postProcessing/sets/{t}/{time}/track0.vtp" for t in TRACKS])
