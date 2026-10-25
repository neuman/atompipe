# SPDX-License-Identifier: Apache-2.0
"""bike.py: the motorBike demo's model.

OpenFOAM's motorBike tutorial body (a motorcycle with a rider) in still
sea-level air at 72 km/h, run by the aero-openfoam pack: snappyHexMesh,
simpleFoam with k-omega SST, the pack's function objects, and the guards
around them. The question the person asked is R1's: is the drag area at most
0.35 m^2.

The model holds the choices the pack's gates read. The case itself is
`case/` (the tutorial, expanded by `foamDictionary -expand`, its domain
grown and Spalding's wall function on the body: README.md says how it was
made). The body is not in this repository: `aero_geometry` names it in the
OpenFOAM install and `aero_geometry_sha256` pins its bytes, so a run on
another body is an error, not a result.

Standard library only. `python3 model/bike.py` prints what `build()` gives
the gates.

Frame: OpenFOAM's. Metres, seconds. +x the direction the air flows (from the
front of the bike to its back), +z up, the ground at z = 0.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass
class Config:
    """Every input the gates read. Nothing outside this dataclass is an input."""

    # --- the body and the case ---
    aero_case: str = "case"
    """The OpenFOAM case, against the project root. Each gate copies it into its
    own scratch and runs there; nothing is written into case/."""

    aero_geometry: str = "$FOAM_TUTORIALS/resources/geometry/motorBike.obj.gz"
    """The body's surface file, in the OpenFOAM install. It is part of the
    OpenFOAM tutorials (GPL-3.0-or-later, its origin before OpenFOAM not stated),
    so it is never copied into this Apache-2.0 repository: the gates copy it into
    their scratch only. A copy under the project was the rejected alternative."""

    aero_geometry_sha256: str = "8ee223c3c3256cd71da52b80eae6569ccf3167eec6f7c3542f83296a0a777aad"
    """The sha256 of motorBike.obj.gz in ESI OpenFOAM v2606 (measured on
    2026-10-23). Another file at the same path is an error naming both
    digests: the drag area is of this body, by content."""

    aero_body_group: str = "motorBikeGroup"
    """The patch group snappyHexMesh puts the body's 67 regions in (the
    tutorial's `inGroups`): the drag is summed over it, and the pictures draw it."""

    # --- the flow ---
    aero_u_inf_m_s: float = 20.0
    """m/s: R1's 72 km/h. The air comes to the bike at this speed in the model;
    on the road the bike moves through still air at it, the same flow seen from
    the bike. The case's inlet says (20 0 0), and aero.reference holds the two
    equal."""

    aero_ref_length_m: float = 1.42
    """m: the tutorial's own reference length (its forceCoeffs `lRef`, the
    wheelbase), used for the Reynolds number only: Re = 20 x 1.42 / 1.5e-5 =
    1.9e6, past the 5e5 aero.regime asks for turbulent wall layers. The drag area
    needs no length. What lost is in PARAMS."""

    aero_sound_speed_m_s: float = 340.3
    """m/s: the ISA sea-level speed of sound (15 degC), for the Mach number:
    20 / 340.3 = 0.059, far below the 0.3 past which the incompressible solver
    would not hold. The air's viscosity is the tutorial's, nu 1.5e-5 m^2/s in
    case/constant/transportProperties (ISA sea level: 1.46e-5)."""

    # --- the run ---
    aero_ranks: int = 6
    """MPI ranks for each parallel run. The machine the demo was measured on has
    7 physical cores, and other work shares it: 6 leaves one. The pack's default
    is 8 (with --oversubscribe). The ranks move the time, and the mesh and the
    drag area a little (about 1e-6 of it, the pack's DEFAULT_RANKS note): the
    pack decomposes with `hierarchical`, so one mesh on one rank count gives
    one history."""

    aero_iter_unc_max_pct: float = 1.0
    """% of the mean drag area: the largest iterative uncertainty U_I = (max -
    min) / 2 over the last 100 iterations that aero.converged accepts (the
    author's choice, design decision D3: common practice for RANS verification).
    Measured on the tutorial's base mesh: 0.24% at iteration 1500 (2026-10-23).
    On this project's meshes at iteration 500 (2026-10-25): 0.603% on the base
    mesh (358654 cells), and 1.98% on the ladder's finest (2674337 cells), which
    fails C7 before any GCI is computed."""

    aero_rho_kg_m3: float = 1.225
    """kg/m^3: ISA sea-level air (15 degC, 101 325 Pa), R1's "still sea-level
    air". aero.drag_area reports the drag force with it, F_D = 0.5 rho U^2 CdA
    (0.35 m^2 is about 86 N at 20 m/s); no gate judges a force, and the drag
    area itself needs no density (the solver's pressure is kinematic)."""

    aero_ladder_ratio: float = 1.5
    """The mesh ladder's ratio: each level's background block is 1.5 times
    finer in every direction, (32 16 12), (48 24 18), (72 36 27), and
    snappyHexMesh refines every cell with it. The tutorial's own ladder at 1.5
    gave effective ratios 1.42 and 1.37 from its cells (2026-10-23), past the
    1.3 Celik et al. 2008 ask. What lost is in PARAMS."""

    aero_gci_max_pct: float = 5.0
    """% of the finest mesh's drag area: the largest mesh error band (GCI)
    aero.mesh_independence accepts (the author's choice, design decision D3:
    common practice for RANS verification). This project's ladder ran on
    2026-10-25 (500 iterations a level, 6 ranks): 0.29925, 0.29625 and 0.30206
    m^2 on 358654, 926215 and 2674337 cells, which does not converge in one
    direction, and its finest mesh did not settle under 1% (U_I 1.98%). So no
    GCI is computed, and C7 reads Failing whatever this number is, first for
    the level that did not settle. P0's ladder of the tutorial's own case (its
    box, block (20 8 8) and 1500 iterations a level, 2026-10-23) did the same
    (0.3075, 0.2964, 0.3007 m^2; U_I 1.09% on its finest)."""

    aero_timeout_s: float = 10800.0
    """s each OpenFOAM tool may run before it is stopped with every rank, and
    the gate skips. The longest single run is the ladder's finest solve. P0's
    finest tutorial mesh (2.6 million cells) took 5613 s for 1500 iterations on
    8 ranks, and this base mesh's 500 iterations took about 6 min on 6 ranks
    (2026-10-23): about an hour for the finest level's 500 on 6 ranks. This
    project's finest level (2674337 cells) took 1587 s for its 500 on 6 ranks
    (2026-10-25), and the whole ladder 3256 s. Three hours leaves room for a
    machine shared with other work, so only a hung rank reaches it. What lost
    is in PARAMS."""


CONFIG = Config()


# --- what lost ----------------------------------------------------------------
# Only the fields with a real loser are listed; each docstring says why THIS
# value. No entry states a value of the model: the dataclass owns every value.
PARAMS = [
    {"name": "aero_ref_length_m", "units": "m", "rejected": [
        {"value": "2.04 m", "why": "the body's length in x, nose to the rear tyre; "
                                   "the wheelbase is the tutorial's and is what a "
                                   "reader of OpenFOAM's case compares with"}]},
    {"name": "aero_ranks", "units": "", "rejected": [
        {"value": "12", "why": "the tutorial's count; on 7 physical cores it needs "
                               "--oversubscribe, and with other work on the "
                               "machine each rank waits for a core"}]},
    {"name": "aero_ladder_ratio", "units": "", "rejected": [
        {"value": "2", "why": "Celik's example ratio; the finest mesh of the "
                              "motorBike would hold about 22 million cells, past the "
                              "pack's cap of 20 million"},
        {"value": "1.3", "why": "the effective ratio from the cells comes out under "
                                "1.3 (P0's box: 1.25 and 1.29), and the ladder fails "
                                "before it solves"}]},
    {"name": "aero_gci_max_pct", "units": "%", "rejected": [
        {"value": "20", "why": "the pack's selftest baseline states it for its "
                               "spheroid, whose band at the formal order is 15.7%; a "
                               "drag area known to 20% does not answer R1's 0.35 m^2"}]},
    {"name": "aero_timeout_s", "units": "s", "rejected": [
        {"value": "3600", "why": "measured on the base mesh only; the finest level's "
                                 "solve is estimated at about an hour on 6 ranks, so "
                                 "an hour would stop a healthy run and the ladder "
                                 "would read Skipped, not judged"}]},
    {"name": "aero_geometry", "units": "", "rejected": [
        {"value": "a copy under the project", "why": "GPL-3.0-or-later with its origin "
                                                    "not stated; this repository is "
                                                    "Apache-2.0"}]},
]


def build(config: Config | None = None) -> dict:
    """The values the gates read, as a flat dict. Pure, no I/O: the case and the
    body are read by the gates themselves, from the paths above."""
    return asdict(config or CONFIG)


if __name__ == "__main__":       # a model you cannot run by hand is a model nobody checks
    import json
    print(json.dumps(build(), indent=2))
