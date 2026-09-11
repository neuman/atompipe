# SPDX-License-Identifier: Apache-2.0
"""Shared arithmetic for the beam-analytic pack. Stdlib only, no gates here.

A leading-underscore file in ``gates/`` is a helper, not a gate module: the pack
loader skips it, so the tables and section maths below are imported once by
``beam.py`` instead of being registered twice.

Everything is closed form and every symbol carries its units in its name. The
unit system is fixed and is not negotiable inside a pack:

    length  mm        force  N        stress/modulus  MPa (= N/mm^2)
    area    mm^2      I      mm^4     angle           degrees

Those four combine so that ``P*L^3/(E*I)`` comes out in millimetres with no
conversion factor anywhere, which is the entire reason the system was chosen. A
pack that mixes metres into this produces answers wrong by 10^3 to 10^12 and
every one of them looks plausible.
"""
from __future__ import annotations

import math
from typing import Any, Iterable, Sequence

# --------------------------------------------------------------------------- #
# policy defaults
# --------------------------------------------------------------------------- #
# The pack draws a hard line between two kinds of missing number:
#
#   PHYSICAL quantities (span, load, modulus, yield, section) are never invented.
#   If the projection does not carry one, the gate SKIPS and names the key it
#   looked for. A default here would be a number the pack made up and the report
#   would present it as measurement.
#
#   POLICY quantities (safety factor, serviceability ratio, the K factor's
#   source, which load case) are choices, not facts. The pack carries a
#   documented default and DISCLOSES it in the verdict's detail line, because a
#   gate that silently picks a safety factor of 1.0 is worse than one that skips.
DEFAULT_SAFETY_FACTOR = 2.0     # yield/2 on a static, well-characterised load
DEFAULT_RATIO_LIMIT = 180.0     # L/180 - the loosest limit in common building use
DEFAULT_POISSON = 0.33          # only ever used for E/G in the shear-deflection estimate
DEFAULT_CASE = "cantilever_end" # the most demanding case for a given P and L
MIN_SLENDERNESS = 5.0           # L/h below which Euler-Bernoulli under-predicts
SHEAR_YIELD_FRACTION = 0.577    # von Mises: tau_y = sigma_y / sqrt(3), for ductile METALS

#: The largest share of the true deflection that ``beam.model_validity`` will let
#: Euler-Bernoulli omit and still call the theory applicable.
#:
#: WHY 10%. The omitted shear deflection is the one error in this pack that is
#: silent, systematic and always optimistic. At 10% the closed-form number is
#: inside the uncertainty of the load itself, which PACK.md already names as the
#: dominant unknown; past it the reported deflection is optimistic by more than
#: the reader's own input error and the number stops being a screening value.
#:
#: REJECTED 3%: that is what a rectangular metal cantilever shows at the L/h = 5
#: limit, so it is self-consistent for that one case — and it refuses most timber
#: and every stiff-support case (fixed-fixed at L/h 11) where the closed form is
#: still perfectly good for screening. REJECTED 25%: a quarter of the answer
#: missing is not "the theory applies", whatever the L/h says.
#:
#: This limit exists because L/h alone is NOT sufficient: L/h is geometry, and
#: the omission also carries the support case (k_s/k_d spans 3 to 48) and the
#: material's E/G (2.6 for a metal, 12-16 for wood). A plywood beam at L/h 6
#: passes the slenderness test and omits ~32% of its deflection.
MAX_SHEAR_DEFLECTION_FRACTION = 0.10

#: Plausibility bands for ``beam.input_sanity``. These are NOT design limits —
#: they are unit detectors, set wide enough that no real material or member is
#: refused and narrow enough that a metre/pascal/gigapascal slip cannot hide.
#:
#: E: 1 MPa is softer than any elastomer anyone puts a beam formula on; 1e6 MPa
#: is stiffer than diamond. REJECTED a 100 MPa floor (the reviewer's suggestion):
#: it refuses legitimate foam and elastomer work. Pascals for any metal land at
#: 1e11 and are caught; GIGApascals (68.9 for aluminium) are NOT caught by this
#: band, which is why the E/yield ratio below exists as well.
MODULUS_BAND_MPA = (1.0, 1.0e6)

#: Stress: 0.1 MPa is below the design stress of any structural material; 5000
#: MPa is above the strongest bulk alloy and fibre. Pascals land at 1e8+.
STRESS_BAND_MPA = (0.1, 5000.0)

#: E/sigma_y for real structural solids: 6061-T6 250, 4140 313, Ti-6Al-4V 129,
#: PLA 132, plywood 267, pine 643, annealed lead ~3200. The band below brackets
#: all of them with room. Its job is the ONE unit slip an absolute band cannot
#: see: a modulus in GPa beside a stress in MPa gives 68.9/276 = 0.25.
MODULUS_OVER_YIELD_BAND = (30.0, 5000.0)

#: Span: 1 mm is shorter than any member this pack's formulae describe (a
#: sub-millimetre "beam" is a MEMS problem with surface effects these formulae do
#: not carry); 1e5 mm is 100 m. A span stated in metres lands at 0.06 and is
#: caught. Section dimensions are deliberately NOT banded - a 0.4 mm wall and a
#: 0.5 mm deflection limit are both ordinary.
SPAN_BAND_MM = (1.0, 1.0e5)

#: Recommended (not theoretical) effective-length factors. The theoretical
#: values - 1.0 / 2.0 / 0.7 / 0.5 - assume the end restraint is perfect, and no
#: bolted or welded joint is. The recommended values below are what design codes
#: use for real connections; the difference is 5-30% of the critical load and it
#: is always in the unconservative direction if you take the theoretical number.
END_CONDITION_K = {
    "pinned_pinned": 1.00,
    "fixed_free": 2.10,       # cantilever column; theoretical 2.0
    "fixed_pinned": 0.80,     # theoretical 0.7
    "fixed_fixed": 0.65,      # theoretical 0.5
}

# --------------------------------------------------------------------------- #
# load cases
# --------------------------------------------------------------------------- #
#: name -> (k_d, k_m, k_v, k_s, description)
#:
#:   deflection   delta_max = k_d * P * L^3 / (E*I)
#:   moment       M_max     = k_m * P * L
#:   shear        V_max     = k_v * P
#:   shear defl   delta_s   = k_s * alpha * P * L / (G*A)      [estimate only]
#:
#: P is the TOTAL applied load in newtons for every case. For the ``_udl`` cases
#: that means the whole distributed load W = w*L, not the intensity w. One key,
#: one meaning; a pack that switches the meaning of ``load_n`` between cases
#: produces an error of exactly L, which is the hardest size of error to notice.
CASES: dict[str, tuple[float, float, float, float, str]] = {
    "cantilever_end": (
        1.0 / 3.0, 1.0, 1.0, 1.0,
        "cantilever, point load at the free end (M peaks at the root)",
    ),
    "cantilever_udl": (
        1.0 / 8.0, 0.5, 1.0, 0.5,
        "cantilever, load spread evenly over the span (M peaks at the root)",
    ),
    "simply_supported_centre": (
        1.0 / 48.0, 0.25, 0.5, 0.25,
        "simply supported, point load at mid-span (M peaks at mid-span)",
    ),
    "simply_supported_udl": (
        5.0 / 384.0, 0.125, 0.5, 0.125,
        "simply supported, load spread evenly (M peaks at mid-span)",
    ),
    "fixed_fixed_centre": (
        1.0 / 192.0, 0.125, 0.5, 0.25,
        "both ends built in, point load at mid-span (M equal at ends and centre)",
    ),
    "fixed_fixed_udl": (
        1.0 / 384.0, 1.0 / 12.0, 0.5, 0.125,
        "both ends built in, load spread evenly (M peaks at the ends)",
    ),
    "propped_cantilever_udl": (
        1.0 / 185.0, 0.125, 0.625, 0.125,
        "one end built in, one end propped, load spread evenly (M peaks at the built-in end)",
    ),
}

#: Spellings people actually type, folded onto the canonical names above.
CASE_ALIASES = {
    "cantilever": "cantilever_end",
    "cantilever_tip": "cantilever_end",
    "cantilever_point": "cantilever_end",
    "fixed_free": "cantilever_end",
    "cantilever_distributed": "cantilever_udl",
    "simply_supported": "simply_supported_centre",
    "simple": "simply_supported_centre",
    "ss_centre": "simply_supported_centre",
    "pinned_pinned_centre": "simply_supported_centre",
    "simply_supported_distributed": "simply_supported_udl",
    "ss_udl": "simply_supported_udl",
    "fixed_fixed": "fixed_fixed_centre",
    "built_in_centre": "fixed_fixed_centre",
    "clamped_centre": "fixed_fixed_centre",
    "propped_cantilever": "propped_cantilever_udl",
    "fixed_pinned_udl": "propped_cantilever_udl",
}

# --------------------------------------------------------------------------- #
# materials
# --------------------------------------------------------------------------- #
#: Order-of-magnitude design numbers so the pack is usable with nothing but a
#: material name. They are NOT a certificate. Every verdict that reads from this
#: table says so in its detail line, because a number whose provenance is "a
#: table in a validator" must never be mistaken for one whose provenance is a
#: mill cert or a coupon test.
#:
#: ``yield_mpa`` means yield for metals. For polymers and wood there is no yield
#: point in the metal sense, so the entry is a conservative DESIGN stress - see
#: references/materials.md, which also explains why every printed-polymer number
#: here is far below the figure on the filament spool's datasheet.
#:
#: ``shear_mpa`` is present only where the von Mises estimate (0.577 * yield) is
#: badly wrong: wood along the grain, and printed polymers across layers. Where
#: it is absent the shear gate says out loud that it estimated.
#:
#: ``e_over_g`` is the ratio of Young's modulus to the SHEAR modulus, and it is
#: present only where the isotropic relation E/G = 2(1+nu) is wrong. For a metal
#: that relation is exact by definition of an isotropic solid and gives 2.6-2.7.
#: Wood is not isotropic and is not close: softwood G_LR is about E_L/16 and a
#: birch plywood panel's in-plane G is roughly E/12, so assuming isotropy
#: UNDER-reports the omitted shear deflection by four to six times on exactly the
#: materials where shear deflection matters. Where the key is absent the validity
#: gate says on its own line that it assumed isotropy and that its number is a
#: lower bound. The printed polymers deliberately carry no value: bulk polymer is
#: close to isotropic in-plane, the interlayer shear modulus is lower and no
#: defensible table figure exists, so the pack discloses rather than invents.
MATERIALS: dict[str, dict[str, Any]] = {
    # -- metals (wrought, room temperature) -------------------------------- #
    "al_6061_t6":   {"E": 68900.0,  "yield": 276.0, "nu": 0.33, "kind": "metal"},
    "al_7075_t6":   {"E": 71700.0,  "yield": 503.0, "nu": 0.33, "kind": "metal"},
    "al_5052_h32":  {"E": 70300.0,  "yield": 193.0, "nu": 0.33, "kind": "metal"},
    "steel_1018":   {"E": 205000.0, "yield": 370.0, "nu": 0.29, "kind": "metal"},
    "steel_4140_qt": {"E": 205000.0, "yield": 655.0, "nu": 0.29, "kind": "metal"},
    "steel_304":    {"E": 193000.0, "yield": 215.0, "nu": 0.29, "kind": "metal"},
    "ti_6al4v":     {"E": 113800.0, "yield": 880.0, "nu": 0.34, "kind": "metal"},
    "brass_c360":   {"E": 97000.0,  "yield": 310.0, "nu": 0.34, "kind": "metal"},
    # -- printed polymers: DERATED for layer-normal loading ---------------- #
    "pla_fdm":      {"E": 2900.0, "yield": 22.0, "nu": 0.36, "shear_mpa": 14.0, "kind": "fdm"},
    "petg_fdm":     {"E": 1700.0, "yield": 20.0, "nu": 0.40, "shear_mpa": 12.0, "kind": "fdm"},
    "abs_fdm":      {"E": 1800.0, "yield": 16.0, "nu": 0.38, "shear_mpa": 10.0, "kind": "fdm"},
    "asa_fdm":      {"E": 1800.0, "yield": 17.0, "nu": 0.38, "shear_mpa": 10.0, "kind": "fdm"},
    "pa12_fdm":     {"E": 1300.0, "yield": 22.0, "nu": 0.40, "shear_mpa": 14.0, "kind": "fdm"},
    "pc_fdm":       {"E": 2000.0, "yield": 30.0, "nu": 0.38, "shear_mpa": 18.0, "kind": "fdm"},
    # -- wood and panel products: design stresses, along the grain --------- #
    "plywood_birch": {"E": 8000.0,  "yield": 30.0, "nu": 0.30, "shear_mpa": 3.5, "kind": "wood", "e_over_g": 12.0},
    "pine_softwood": {"E": 9000.0,  "yield": 14.0, "nu": 0.30, "shear_mpa": 1.7, "kind": "wood", "e_over_g": 16.0},
    "oak_hardwood":  {"E": 12000.0, "yield": 25.0, "nu": 0.30, "shear_mpa": 2.5, "kind": "wood", "e_over_g": 14.0},
    "mdf":           {"E": 3600.0,  "yield": 18.0, "nu": 0.30, "shear_mpa": 1.5, "kind": "wood", "e_over_g": 3.0},
}


# --------------------------------------------------------------------------- #
# missing-parameter discipline
# --------------------------------------------------------------------------- #
class MissingParam(Exception):
    """A physical quantity this gate needs is not in the projection.

    Raised, never defaulted. The gate catches it and returns a SKIPPED verdict
    naming the keys it looked for, so the claim resolves BLOCKED and stays
    visible. Inventing a modulus would turn "we did not check this" into a green
    tick, which is the precise failure the whole spine exists to prevent.
    """

    def __init__(self, names: Sequence[str], what: str) -> None:
        super().__init__(what)
        self.names = list(names)
        self.what = what

    @property
    def reason(self) -> str:
        return (f"the model projection does not provide {self.what}; looked for "
                f"{', '.join(self.names)} — add it to the model rather than letting "
                f"this gate guess")


def get(ctx: Any, names: Iterable[str], default: Any = None) -> Any:
    """First present value among ``names``, else ``default``. No coercion."""
    for name in names:
        value = ctx.param(name, None)
        if value is not None:
            return value
    return default


def num(ctx: Any, names: Sequence[str], what: str) -> float:
    """A required numeric parameter, or ``MissingParam``."""
    value = get(ctx, names)
    if value is None:
        raise MissingParam(names, what)
    try:
        return float(value)
    except (TypeError, ValueError):
        raise MissingParam(names, f"{what} as a number (got {value!r})") from None


def opt(ctx: Any, names: Sequence[str], fallback: float) -> tuple[float, bool]:
    """A policy parameter: ``(value, was_defaulted)``. The caller must disclose
    the default in its detail line — a silent policy default is a lie with a
    decimal point in it."""
    value = get(ctx, names)
    if value is None:
        return float(fallback), True
    try:
        return float(value), False
    except (TypeError, ValueError):
        raise MissingParam(names, f"{names[0]} as a number (got {value!r})") from None


def positive(value: float, names: Sequence[str], what: str) -> float:
    """Guard a dimension that divides. A zero or negative section dimension is a
    broken model, not a failing design, so it SKIPS with the key named rather
    than dividing by zero three lines later."""
    if not math.isfinite(value) or value <= 0.0:
        raise MissingParam(names, f"a positive {what} (got {value!r})")
    return value


#: Every load key in this pack, in its sign convention. Used by the guard below
#: and by ``beam.input_sanity``; one list, so a new load key cannot be added in
#: one place and forgotten in the other.
LOAD_KEYS: dict[str, tuple[tuple[str, ...], str]] = {
    "load_n": (
        ("load_n", "force_n", "applied_load_n", "transverse_load_n"),
        "the transverse load, POSITIVE in the direction it bends the member",
    ),
    "axial_load_n": (
        ("axial_load_n", "compression_n", "column_load_n", "axial_force_n"),
        "the axial load, POSITIVE in COMPRESSION",
    ),
    "bearing_load_n": (
        ("bearing_load_n", "joint_load_n", "fastener_load_n"),
        "the load into the joint, POSITIVE as a magnitude",
    ),
}


def unsigned_load(value: float, names: Sequence[str], sense: str) -> float:
    """Guard a LOAD's sign. This is the guard that was missing.

    Every geometric dimension in this pack goes through ``positive()``; the load
    family did not, and a model using the perfectly ordinary "downward is
    negative" convention got a full sweep of PASSes on a beam nobody had
    analysed — utilisation -0.65, tau -3.75 MPa, and a deflection ratio of L/inf
    from the "infinitely stiff is a pass" branch. That is method rule 4's
    decoration at pack scale, and it is worse than a skip because it resolves the
    claim PROVEN instead of BLOCKED.

    So: a negative load is REFUSED, not silently absolute-valued. ``abs()`` would
    be the tempting fix and it is wrong — on ``axial_load_n`` a negative number
    plausibly means TENSION, and a member in tension does not buckle at all, so
    folding the sign away would answer a question nobody asked. The pack cannot
    know which convention produced the minus sign, so it says which convention it
    needs and makes the caller state it.

    Zero is accepted and means literally no load: every gate then reports zero
    stress, which is true. Non-finite is refused.
    """
    if not math.isfinite(value):
        raise MissingParam(names, f"a finite load (got {value!r})")
    if value < 0.0:
        raise MissingParam(
            names,
            f"{sense} (got {value!r}). This pack takes every load as a positive "
            f"magnitude and will not guess which convention a minus sign came from: "
            f"under a downward-negative convention it is a sign convention, and on "
            f"an axial load it may mean TENSION, in which case buckling does not "
            f"apply at all and this gate is the wrong one to close the claim. State "
            f"the magnitude",
        )
    return value


# --------------------------------------------------------------------------- #
# the load case
# --------------------------------------------------------------------------- #
def case_of(ctx: Any) -> tuple[str, tuple[float, float, float, float, str], bool]:
    """``(name, coefficients, was_defaulted)`` for the beam's support condition."""
    raw = get(ctx, ("beam_case", "case", "load_case", "support_case"))
    defaulted = raw is None
    key = str(raw if raw is not None else DEFAULT_CASE).strip().lower()
    key = key.replace("-", "_").replace(" ", "_").replace("center", "centre")
    key = CASE_ALIASES.get(key, key)
    if key not in CASES:
        raise MissingParam(
            ["beam_case"],
            f"a known beam_case (got {raw!r}; known: {', '.join(sorted(CASES))})",
        )
    return key, CASES[key], defaulted


# --------------------------------------------------------------------------- #
# material
# --------------------------------------------------------------------------- #
def material_row(ctx: Any) -> tuple[str, dict[str, Any] | None]:
    name = str(get(ctx, ("material", "material_name"), "") or "").strip().lower()
    key = name.replace("-", "_").replace(" ", "_")
    return key, MATERIALS.get(key)


def modulus(ctx: Any) -> tuple[float, str]:
    """Young's modulus and where it came from."""
    explicit = get(ctx, ("modulus_mpa", "youngs_modulus_mpa", "e_mpa", "E_mpa"))
    if explicit is not None:
        return float(explicit), "modulus_mpa"
    key, row = material_row(ctx)
    if row is not None:
        return float(row["E"]), f"pack table {key}"
    raise MissingParam(
        ["modulus_mpa", "material"],
        "Young's modulus (give modulus_mpa, or a `material` this pack's table knows: "
        + ", ".join(sorted(MATERIALS)[:6]) + ", ...)",
    )


def yield_stress(ctx: Any) -> tuple[float, str]:
    """Yield (metals) or design stress (polymers, wood), and its source."""
    explicit = get(ctx, ("yield_mpa", "yield_strength_mpa", "sigma_y_mpa"))
    if explicit is not None:
        return float(explicit), "yield_mpa"
    key, row = material_row(ctx)
    if row is not None:
        return float(row["yield"]), f"pack table {key}"
    raise MissingParam(
        ["yield_mpa", "material"],
        "a yield / design stress (give yield_mpa, or a `material` this pack's table knows)",
    )


def poisson(ctx: Any) -> float:
    explicit = get(ctx, ("poisson", "poissons_ratio", "nu"))
    if explicit is not None:
        return float(explicit)
    _key, row = material_row(ctx)
    if row is not None:
        return float(row.get("nu", DEFAULT_POISSON))
    return DEFAULT_POISSON


def e_over_g(ctx: Any) -> tuple[float, str, bool]:
    """``(E/G, source, isotropy_assumed)`` for the shear-deflection estimate.

    Only the RATIO is needed, never E itself, which is what lets
    ``beam.model_validity`` run on a model that has not named a material yet.

    Order, most specific first: a stated ``e_over_g``; a stated
    ``shear_modulus_mpa`` divided by whatever modulus the model carries; the
    material table's measured ratio (present for wood, where isotropy is badly
    wrong); and only then the isotropic relation E/G = 2(1+nu).

    That last route is exact for an isotropic solid and gives 2.6-2.7 for every
    metal here. For wood it is wrong by four to six times IN THE OPTIMISTIC
    DIRECTION - softwood G_LR is about E_L/16 - so the third flag comes back True
    whenever the assumption is being made on something that is not a known metal,
    and the caller must say on its verdict line that its number is a LOWER BOUND.
    """
    explicit = get(ctx, ("e_over_g", "modulus_over_shear_modulus"))
    if explicit is not None:
        return positive(float(explicit), ["e_over_g"], "E/G ratio"), "e_over_g (given)", False
    g_stated = get(ctx, ("shear_modulus_mpa", "g_mpa"))
    if g_stated is not None:
        g = positive(float(g_stated), ["shear_modulus_mpa"], "shear modulus")
        try:
            E, e_src = modulus(ctx)
        except MissingParam:
            pass                       # no E to divide by; fall through to the table
        else:
            return E / g, f"E {E:.0f} [{e_src}] / G {g:.0f} MPa (given)", False
    key, row = material_row(ctx)
    if row is not None and row.get("e_over_g") is not None:
        return float(row["e_over_g"]), f"pack table {key}", False
    nu = poisson(ctx)
    isotropic = 2.0 * (1.0 + nu)
    assumed = not (row is not None and row.get("kind") == "metal")
    return isotropic, f"isotropic 2(1+nu), nu {nu:g}", assumed


def allowable_direct(ctx: Any, sf: float) -> tuple[float, str]:
    """Allowable normal stress, either given outright or derived as yield/SF."""
    direct = get(ctx, ("allowable_stress_mpa", "design_stress_mpa"))
    if direct is not None:
        return float(direct), "allowable_stress_mpa (given)"
    sy, src = yield_stress(ctx)
    return sy / sf, f"{sy:.0f} MPa yield [{src}] / SF {sf:g}"


def allowable_shear(ctx: Any, sf: float) -> tuple[float, str]:
    """Allowable shear stress, and an honest statement of how it was obtained.

    Order: a stated allowable, then a stated shear strength, then the material
    table's measured shear (present only for wood and printed polymer, where the
    von Mises estimate is badly wrong), and only then 0.577*yield. The last one
    is an ESTIMATE for ductile metals and the detail line says so, because
    applying it to plywood overstates the allowable by roughly five times.
    """
    direct = get(ctx, ("allowable_shear_mpa",))
    if direct is not None:
        return float(direct), "allowable_shear_mpa (given)"
    stated = get(ctx, ("shear_strength_mpa", "shear_yield_mpa"))
    if stated is not None:
        return float(stated) / sf, f"{float(stated):.0f} MPa shear strength / SF {sf:g}"
    key, row = material_row(ctx)
    if row is not None and row.get("shear_mpa") is not None:
        return float(row["shear_mpa"]) / sf, f"{row['shear_mpa']:.1f} MPa shear [pack table {key}] / SF {sf:g}"
    sy, src = yield_stress(ctx)
    return (SHEAR_YIELD_FRACTION * sy) / sf, (
        f"{SHEAR_YIELD_FRACTION:g}x{sy:.0f} MPa yield [{src}] / SF {sf:g}, von Mises ESTIMATE"
    )


# --------------------------------------------------------------------------- #
# section properties
# --------------------------------------------------------------------------- #
def section(ctx: Any) -> dict[str, Any]:
    """Section properties in mm, from whatever the model happens to carry.

    Four ways in, most explicit first:

    1. ``I_mm4`` + ``area_mm2`` (+ ``c_mm``/``height_mm``) — a section this pack
       has no formula for. ``first_moment_mm3`` and ``web_width_mm`` are optional
       and only the shear gate needs them; without them that one gate skips and
       says which key is missing, rather than the whole pack refusing the model.
    2. ``section: "rect"`` with ``width_mm`` x ``height_mm``.
    3. ``section: "circle"`` with ``dia_mm``.
    4. ``section: "tube"`` with ``dia_mm`` and ``wall_mm``.

    ``height_mm`` is the depth IN THE BENDING DIRECTION. Getting that backwards
    on a rectangle changes I by (b/h)^2 and is the single most common way a
    correct formula returns a wrong number — so the verdicts print b x h and the
    reviewer is expected to look at it.
    """
    shape = str(get(ctx, ("section", "section_shape", "profile"), "") or "").strip().lower()
    b = get(ctx, ("width_mm", "b_mm", "breadth_mm"))
    h = get(ctx, ("height_mm", "h_mm", "depth_mm", "section_depth_mm"))
    d = get(ctx, ("dia_mm", "diameter_mm", "od_mm", "outer_dia_mm"))
    wall = get(ctx, ("wall_mm", "wall_thickness_mm", "tube_wall_mm"))
    given_I = get(ctx, ("I_mm4", "i_mm4", "second_moment_mm4"))

    if given_I is not None:
        I = positive(float(given_I), ["I_mm4"], "second moment of area I_mm4")
        A = positive(num(ctx, ("area_mm2", "a_mm2"),
                         "section area (required alongside an explicit I_mm4)"),
                     ["area_mm2"], "section area")
        c = get(ctx, ("c_mm", "extreme_fibre_mm"))
        if c is None and h is not None:
            c = float(h) / 2.0
        if c is None:
            raise MissingParam(["c_mm", "height_mm"],
                               "the distance to the extreme fibre (c_mm) alongside an explicit I_mm4")
        c = positive(float(c), ["c_mm"], "extreme fibre distance")
        depth = float(h) if h is not None else 2.0 * c
        # I_min is NOT defaulted to the bending I. Falling back to it is the exact
        # error PACK.md warns about two sections earlier ("a rectangle bent the
        # strong way buckles the other way"), it is unconservative, and the
        # explicit route is precisely where I_min/I is most likely to be far from
        # 1 - an extrusion, a channel, a built-up member, a shape this pack has no
        # formula for. So it comes back None and beam.buckling SKIPS naming the
        # key, exactly as beam.shear_stress already does for Q and t_web. An
        # explicit section that really is symmetric states i_min_mm4 = I_mm4, and
        # that statement is a design decision worth one line in the model.
        I_min = get(ctx, ("i_min_mm4", "I_min_mm4"))
        Q = get(ctx, ("first_moment_mm3", "q_mm3", "Q_mm3"))
        web = get(ctx, ("web_width_mm", "t_web_mm"))
        # alpha is the shear shape factor, used only in the shear-deflection
        # estimate. 1.2 is the RECTANGLE's value and it is the wrong number for
        # the sections people reach this route for: a thin-webbed I or channel is
        # roughly A/A_web, commonly 3-6, so assuming 1.2 under-reports the omitted
        # shear deflection by that factor on exactly the sections where it matters
        # most. It is assumed rather than refused because the validity gate has to
        # keep working on half-specified models - but the assumption is flagged
        # and the caller discloses it.
        alpha_raw = get(ctx, ("alpha_shear", "shear_shape_factor"))
        shear_area = get(ctx, ("shear_area_mm2", "web_area_mm2"))
        if alpha_raw is not None:
            alpha, alpha_assumed = positive(float(alpha_raw), ["alpha_shear"],
                                            "shear shape factor"), False
        elif shear_area is not None:
            alpha, alpha_assumed = A / positive(float(shear_area), ["shear_area_mm2"],
                                                "shear area"), False
        else:
            alpha, alpha_assumed = 1.2, True
        return {
            "A": A, "I": I,
            "I_min": float(I_min) if I_min is not None else None,
            "I_min_source": "i_min_mm4" if I_min is not None else None,
            "c": c, "depth": depth,
            "Q": float(Q) if Q is not None else None,
            "t_web": float(web) if web is not None else None,
            "alpha": alpha, "alpha_assumed": alpha_assumed, "shape": "explicit",
            "desc": f"I={I:.0f} mm^4, A={A:.0f} mm^2, c={c:.2f} mm (given)",
        }

    circular = shape in ("circle", "round", "rod", "bar", "circ", "circular", "solid_round")
    tubular = shape in ("tube", "pipe", "hollow", "circ_tube", "round_tube")
    if not shape and d is not None:
        tubular, circular = (wall is not None), (wall is None)

    if tubular:
        D = positive(num(ctx, ("dia_mm", "diameter_mm", "od_mm"), "the tube outer diameter"),
                     ["dia_mm"], "outer diameter")
        t = positive(num(ctx, ("wall_mm", "wall_thickness_mm"), "the tube wall thickness"),
                     ["wall_mm"], "wall thickness")
        di = D - 2.0 * t
        if di <= 0.0:
            raise MissingParam(["wall_mm"],
                               f"a wall thinner than the radius (wall {t:g} mm in a {D:g} mm tube "
                               f"leaves no bore; use section=\"circle\" for solid stock)")
        A = math.pi * (D * D - di * di) / 4.0
        I = math.pi * (D ** 4 - di ** 4) / 64.0
        return {"A": A, "I": I, "I_min": I, "I_min_source": "axisymmetric: I_min = I",
                "c": D / 2.0, "depth": D,
                "Q": (D ** 3 - di ** 3) / 12.0, "t_web": 2.0 * t, "alpha": 2.0,
                "alpha_assumed": False, "shape": "tube",
                "desc": f"tube od {D:g} x wall {t:g} mm, I={I:.0f} mm^4"}

    if circular:
        D = positive(num(ctx, ("dia_mm", "diameter_mm"), "the round bar diameter"),
                     ["dia_mm"], "diameter")
        A = math.pi * D * D / 4.0
        I = math.pi * D ** 4 / 64.0
        return {"A": A, "I": I, "I_min": I, "I_min_source": "axisymmetric: I_min = I",
                "c": D / 2.0, "depth": D,
                "Q": D ** 3 / 12.0, "t_web": D, "alpha": 10.0 / 9.0,
                "alpha_assumed": False, "shape": "circle",
                "desc": f"round bar dia {D:g} mm, I={I:.0f} mm^4"}

    # default: rectangle. Named last because it is what you get by accident.
    bb = positive(num(ctx, ("width_mm", "b_mm", "breadth_mm"),
                      "the section width (or a `section` shape this pack knows: rect, circle, tube)"),
                  ["width_mm"], "section width")
    hh = positive(num(ctx, ("height_mm", "h_mm", "depth_mm"),
                      "the section depth in the bending direction"),
                  ["height_mm"], "section depth")
    I = bb * hh ** 3 / 12.0
    return {"A": bb * hh, "I": I, "I_min": min(I, hh * bb ** 3 / 12.0),
            "I_min_source": "weaker of b*h^3/12 and h*b^3/12",
            "c": hh / 2.0, "depth": hh,
            "Q": bb * hh * hh / 8.0, "t_web": bb, "alpha": 1.2,
            "alpha_assumed": False, "shape": "rect",
            "desc": f"rect {bb:g} x {hh:g} mm (b x h), I={I:.0f} mm^4"}


# --------------------------------------------------------------------------- #
# derived quantities
# --------------------------------------------------------------------------- #
def span(ctx: Any) -> float:
    return positive(num(ctx, ("span_mm", "length_mm", "beam_length_mm", "free_span_mm", "arm_length_mm"),
                        "the free span between supports"),
                    ["span_mm"], "span")


def load(ctx: Any) -> float:
    names, sense = LOAD_KEYS["load_n"]
    return unsigned_load(
        num(ctx, names, "the applied transverse load (total, in newtons)"),
        names, sense,
    )


def deflection_mm(k_d: float, P: float, L: float, E: float, I: float) -> float:
    return k_d * P * L ** 3 / (E * I)


def shear_fraction(k_s: float, k_d: float, alpha: float, eg: float,
                   I: float, A: float, L: float) -> float:
    """Estimated shear deflection as a fraction of the bending deflection.

    delta_s/delta_b = (k_s/k_d) * alpha * (E/G) * I / (A*L^2)

    E cancels — only the RATIO E/G survives — so this needs no material
    stiffness, which is what lets ``beam.model_validity`` police the other gates
    on a model that has not named a material yet.

    It does NOT cancel the material entirely, and an earlier version of this
    function pretended otherwise by hardcoding E/G = 2(1+nu). That relation is
    exact for an ISOTROPIC solid and this pack's table is half wood and printed
    polymer; on plywood it under-reported the omission by about 4.5x. The ratio
    now comes from ``e_over_g()``, which reads a real value where one exists and
    tells the caller when it had to assume.

    It is still an estimate: a real Timoshenko solve differs by some percent, and
    the number is only ever used to say how far the closed form is
    under-predicting.
    """
    return (k_s / k_d) * alpha * eg * I / (A * L * L)
