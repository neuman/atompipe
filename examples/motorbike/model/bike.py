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
    is 8 (with --oversubscribe). The ranks move the time, not the result: the
    pack decomposes with `hierarchical`, so one mesh gives one history."""

    aero_iter_unc_max_pct: float = 1.0
    """% of the mean drag area: the largest iterative uncertainty U_I = (max -
    min) / 2 over the last 100 iterations that aero.converged accepts (the
    author's choice, design decision D3: common practice for RANS verification).
    Measured on the tutorial's base mesh: 0.24% at iteration 1500 (2026-10-23)."""

    aero_timeout_s: float = 3600.0
    """s each OpenFOAM tool may run before it is stopped with every rank, and
    the gate skips. The base mesh's solve took about 4 min on 10 ranks (2026-10-23);
    an hour is far past it, so only a hung rank reaches it."""


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
