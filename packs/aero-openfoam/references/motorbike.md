# The motorBike geometry

## Where it comes from

`motorBike.obj.gz`, a motorcycle with a rider, ships with OpenFOAM in
`$FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz` (ESI v2606 at
`/usr/lib/openfoam/openfoam2606/tutorials/resources/geometry/`). The
`incompressible/simpleFoam/motorBike` tutorial meshes it with snappyHexMesh and
solves it with k-omega SST at 20 m/s.

**Licence.** It is part of the OpenFOAM tutorials, which are GPL-3.0-or-later
as OpenFOAM is. Its origin before OpenFOAM is not stated. nopekit is
Apache-2.0, so the file is never copied into a project or into this repository:
a project names it by its path in the install (`aero_geometry
"$FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz"`), and the gates copy it
only into their own scratch.

**Digest.** sha256
`8ee223c3c3256cd71da52b80eae6569ccf3167eec6f7c3542f83296a0a777aad` (v2606,
confirmed in P0). A project states it as `aero_geometry_sha256`; a file with
another digest is an error, naming both. A missing file is a skip.

## What surfaceCheck says (P0)

- 331 653 triangles in 67 regions, 132 871 vertices.
- Bounding box (-0.291665 -0.350289 -4.232e-05) to (1.75115 0.332267 1.35152):
  2.043 m long, 0.683 m wide, 1.352 m high; its lowest point 4.2e-5 m under the
  ground plane z = 0 (the tyres' contact).
- 60 941 illegal triangles, an open surface, 4 unconnected parts and 132 055
  normal zones: the surface is not closed. snappyHexMesh meshes it anyway;
  `surfaceCheck`'s complaints are not a gate.
- 1.0 s and 168 MB, and it writes about 23 files into its working directory.

The rasterised frontal area at 1 mm is 0.644 m^2; the tutorial's "Estimated"
reference area is 0.75 m^2. The pack's claim is CdA, which needs neither.

## The tutorial, as the pack reads it

The tutorial's case uses `#include` (initial conditions, inlet, patches),
`#includeEtc "caseDicts/meshQualityDict"` and function objects in its
controlDict. The pack's reader refuses all three. A project builds its case
from the tutorial with `foamDictionary -expand` on every file, then:

- removes `functions` from `system/controlDict` (the pack writes its own);
- keeps `#includeEtc "caseDicts/setConstraintTypes"` first in each 0/ file's
  `boundaryField` (the one directive allowed: expanded, it adds constraint
  types such as `processor` that the reader does not take);
- leaves out `decomposeParDict*` and `meshQualityDict` (the pack writes its
  own);
- sets `0/nut`'s `motorBikeGroup` to `nutUSpaldingWallFunction` (the design's
  choice; the tutorial's `nutkWallFunction` reads, and `aero.wall_treatment`
  errors on it: its y+ rule is Spalding's).

Read so, the tutorial case passes `aero.case_readable`, `aero.reference` and
`aero.regime` (Re 1.89e6 on lRef 1.42 m), and fails `aero.domain` on four
distances (see `domain.md`).

## The tutorial's own numbers (P0)

forceCoeffs with `Aref 1`: CdA 0.307547 m^2 at L0 (mean of iterations
1401-1500), 0.296363 at L1, 0.300742 at L2. The tutorial's own run (nutk, 12
ranks, iterations 401-500) reads Cd 0.4058 on 0.75 m^2: CdA 0.30433 m^2.
