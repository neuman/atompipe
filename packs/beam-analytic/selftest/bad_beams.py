# SPDX-License-Identifier: Apache-2.0
"""Known-bad fixtures for the beam-analytic gates.

Each function returns a GateContext carrying the BASELINE beam below, moved into
the failure the gate under test claims to detect. That constraint is the whole
point: a fixture that is bad in some other way — a corrupt file, a missing key, a
nonsense unit — proves the gate handles garbage, not that it measures what it
claims to measure.

**Why the fixtures carry their own beam instead of mutating the host project's.**
A pack's gates run against projects the pack author has never seen. If a fixture
simply overrode ``height_mm`` on whatever was in ``ctx.params``, then on a project
whose section is a tube the override would be ignored, the gate would pass, and
the selftest would report the gate broken when the fixture was. A control that can
fail for a reason other than the one it is testing is not a control. So the
baseline is fixed, stated in ``selftest/baseline.json``, and known to pass every
gate in this pack — ``BASELINE`` below is literally that file, which is the same
projection CI feeds the gates to prove they pass a good design.

**Why the bad value is DERIVED and not written down.** Every fixture here reads
the threshold it has to beat out of the baseline and computes the value that
lands ``_MARGIN`` past it. A literal would be a second copy of the threshold with
a different date on it: change ``deflection_limit_mm`` in the baseline and a
hardcoded 2.5 mm section depth either stops failing or starts failing for the
wrong reason, silently, and the selftest still reads green either way.

The context itself is still inherited: root, out_dir and ledger come from the
caller, so evidence still lands where the caller wanted it.
"""
from __future__ import annotations

import dataclasses
import json
import math
import os
import sys
from typing import Any

# The fixtures invert the pack's own formulae to place themselves, so they read
# the pack's arithmetic rather than restating it (method rule 2). The gates
# directory is not a package, so it goes on the path the same way beam.py does.
_GATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "gates")
if _GATES not in sys.path:
    sys.path.insert(0, _GATES)

import _beam_analytic_lib as B  # noqa: E402

#: How far past its limit a control is placed: 15%.
#:
#: WHY SO LITTLE. A control is a test of the INSTRUMENT, and the instrument has
#: two parts — the arithmetic and the threshold. A fixture sixty times past the
#: limit only exercises the first: it would still fire if the threshold were
#: wrong by a factor of ten, or read from the wrong key, or compared with the
#: wrong sign. A fixture 15% past fires only if the limit is where the pack says
#: it is. These gates are deterministic closed form with no measurement noise, so
#: 15% is not a marginal call, it is an exact one.
#:
#: The second reason is collateral. The baseline is a competent bracket with
#: several utilisations near 0.7, so a control pushed hard past one limit drags
#: three other gates over theirs and stops discriminating. The smallest margin
#: that still fails is the one that fires the fewest other gates.
#:
#: REJECTED: a per-fixture margin chosen for narrative effect ("64x floppier").
#: It reads well and proves less.
_MARGIN = 1.15

_BASELINE_JSON = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baseline.json")


def _load_baseline() -> dict[str, Any]:
    with open(_BASELINE_JSON, "r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return {k: v for k, v in raw.items() if not k.startswith("_")}


#: The known-good beam: a 12 x 10 mm aluminium cantilever, 60 mm free span, 300 N
#: at the tip, bolted through a 6 mm ear with one M4, lightly loaded in
#: compression. It passes all eight gates.
#:
#: Documentation keys (``_description``, ``_notes``) are stripped: they are for a
#: reader learning the pack's vocabulary, and a gate must never see them.
BASELINE: dict[str, Any] = _load_baseline()


def _variant(ctx, **overrides: Any):
    """The baseline beam with ``overrides`` applied, on the caller's context."""
    params = dict(BASELINE)
    params.update(overrides)
    return dataclasses.replace(ctx, params=params)


def _sf(probe) -> float:
    value, _defaulted = B.opt(probe, ("safety_factor", "sf", "fos"),
                              B.DEFAULT_SAFETY_FACTOR)
    return value


def baseline(ctx):
    """The known-GOOD beam. Not a negative control — a reference point.

    Useful to a reader checking that the fixtures below really do move one thing,
    and to anyone sanity-checking the pack after editing a coefficient.
    """
    return _variant(ctx)


# --------------------------------------------------------------------------- #
def shallow_section(ctx):
    """beam.deflection — section depth reduced until the sag is 15% past the limit.

    delta goes as 1/h^3, so the depth that lands exactly ``_MARGIN`` past the
    baseline's own ``deflection_limit_mm`` is h_base * (delta_base/delta_target)^(1/3)
    — about 8.17 mm against the baseline's 10 mm, for 0.575 mm of sag against a
    0.5 mm limit. Load, span, material and width are untouched, so a gate that is
    really computing k_d*P*L^3/(E*I) cannot miss it and a gate echoing a constant
    will.

    **Why not a quarter of the depth.** That was the previous version of this
    fixture and it deflected 20.06 mm on a 60 mm span — 33% of the span, more
    than three times outside the small-deflection limit PACK.md states, so the
    number in its own docstring was not a physical deflection at all. The sibling
    fixture ``long_span`` articulates exactly why that is not allowed. At 0.575 mm
    this beam is 0.96% of its span and comfortably inside the theory.

    ``beam.deflection_ratio`` fails here too, and cannot be prevented from doing
    so: the baseline's 0.5 mm limit on a 60 mm span is already L/120, tighter than
    the L/180 serviceability limit, so at this baseline ANY absolute-deflection
    failure is also a ratio failure. Everything else still passes — bending at
    util 0.98, validity at L/h 7.3, buckling, bearing and shear untouched in
    substance.
    """
    probe = _variant(ctx)
    sec = B.section(probe)
    E, _src = B.modulus(probe)
    _case, (k_d, _km, _kv, _ks, _n), _d = B.case_of(probe)
    limit = B.num(probe, ("deflection_limit_mm", "max_deflection_mm",
                          "deflection_allow_mm"), "the deflection limit")
    d_base = B.deflection_mm(k_d, B.load(probe), B.span(probe), E, sec["I"])
    h_base = sec["depth"]
    h_bad = h_base * (d_base / (_MARGIN * limit)) ** (1.0 / 3.0)
    return _variant(ctx, height_mm=round(h_bad, 3))


def long_span(ctx):
    """beam.deflection_ratio — the span that puts L/delta 15% past the L/N limit.

    The span fraction goes as 1/L^2, so L_bad = L_base * sqrt(ratio_base/ratio_target)
    with ratio_target = the baseline's own ``deflection_ratio_limit`` / ``_MARGIN``:
    about 66.4 mm against the baseline's 60, taking L/191 to L/157 against an
    L/180 limit. The section, the load and the material are not touched.

    **This is a span-fraction failure and nothing else, and that is checked.**
    The previous version of this fixture used a 150 mm span and said the same
    sentence, but it was false — it also failed ``beam.deflection`` (4.898 mm
    against a 0.5 mm limit) and ``beam.bending_stress`` (util 1.63), so it fired
    three gates and demonstrated nothing about discrimination. At 66.4 mm the sag
    is 0.424 mm inside the 0.5 mm limit, bending is util 0.72, L/h is 6.6 and
    every other gate passes.

    The window that allows this is narrow — the absolute deflection limit puts a
    ceiling on the span at 70.1 mm and the ratio limit puts a floor at 61.9 mm —
    which is exactly why the span is computed instead of chosen. If a future
    baseline closes that window the assertion below fails loudly and the selftest
    reports the control as unusable, rather than quietly becoming a compound
    failure again.

    The beam is also still deflecting 0.6% of its span, well inside
    small-deflection theory. A control that had to leave the theory's validity
    behind to produce a failure would be proving something about the theory
    instead of about the gate.
    """
    probe = _variant(ctx)
    sec = B.section(probe)
    E, _src = B.modulus(probe)
    P = B.load(probe)
    L_base = B.span(probe)
    _case, (k_d, _km, _kv, _ks, _n), _d = B.case_of(probe)
    denom, _defaulted = B.opt(probe, ("deflection_ratio_limit",
                                      "span_over_deflection_limit", "l_over_d_limit"),
                              B.DEFAULT_RATIO_LIMIT)
    ratio_base = L_base / B.deflection_mm(k_d, P, L_base, E, sec["I"])
    L_bad = L_base * math.sqrt(ratio_base / (denom / _MARGIN))
    abs_limit = B.num(probe, ("deflection_limit_mm", "max_deflection_mm",
                              "deflection_allow_mm"), "the deflection limit")
    d_bad = B.deflection_mm(k_d, P, L_bad, E, sec["I"])
    if d_bad > abs_limit:
        raise ValueError(
            f"long_span can no longer isolate beam.deflection_ratio: the span that "
            f"puts the ratio {_MARGIN:g}x past L/{denom:g} ({L_bad:.1f} mm) sags "
            f"{d_bad:.3f} mm, past the baseline's own {abs_limit:g} mm absolute limit, "
            f"so beam.deflection would fail too. Loosen deflection_limit_mm in "
            f"selftest/baseline.json or build this control on a different beam")
    return _variant(ctx, span_mm=round(L_bad, 2))


def overloaded(ctx):
    """beam.bending_stress — the load that puts extreme-fibre stress 15% past allowable.

    Bending stress is linear in load, so P_bad = P_base * (sigma_target/sigma_base)
    with sigma_target = _MARGIN * the allowable the gate itself computes: about
    529 N against the baseline's 300, taking 90 MPa to 158.7 MPa against a 138 MPa
    allowable (276 MPa yield / SF 2). Geometry, material and support case are
    unchanged: the only thing wrong with this beam is how hard it is pushed.

    ``beam.deflection`` and ``beam.deflection_ratio`` fail here too and that
    cannot be avoided at this baseline. The baseline is deliberately a competent
    bracket, which means stiffness and strength are near-simultaneously governing
    — deflection reaches its limit at 479 N and bending at 460 N — so there is no
    load that trips one without the other. Isolating them would need a second
    change, and a control that moves two numbers to look tidy is worse than one
    that moves one and says what happened.
    """
    probe = _variant(ctx)
    sec = B.section(probe)
    P_base = B.load(probe)
    L = B.span(probe)
    _case, (_kd, k_m, _kv, _ks, _n), _d = B.case_of(probe)
    allow, _src = B.allowable_direct(probe, _sf(probe))
    sigma_base = k_m * P_base * L * sec["c"] / sec["I"]
    P_bad = P_base * (_MARGIN * allow) / sigma_base
    return _variant(ctx, load_n=round(P_bad, 1))


def shear_governed(ctx):
    """beam.shear_stress — the regime where transverse shear genuinely governs.

    The same 12 x 10 mm section on the same 60 mm span, in **birch plywood** under
    a **distributed load**, carrying the load that puts tau 15% past the shear
    allowable: about 322 N, for tau 2.01 MPa against a 1.75 MPa allowable
    (3.5 MPa table shear / SF 2). Bending sits at util 0.81, deflection at 0.11 mm,
    buckling at 0.27 and bearing at 0.83 — all passing — so the discrimination
    this control has to prove is proved.

    **Why it takes three keys and not one, and why this is the honest version.**
    The previous fixture moved five (case, span, width, height, load) to reach a
    30 mm span, 6 x 25 mm member at L/h 1.2 carrying 20 kN, and claimed only shear
    tripped. It was outside the gate's own stated assumption (the load sat 0.6 of
    a section depth from a support, where the shear is carried in direct
    compression and VQ/It over-predicts), and it was outside the pack's own
    declared validity. The reason it had to go there is structural: for a solid
    metal section the normal and shear allowables are in the ratio 1/0.577 = 1.73,
    and with sigma/tau = 4*(k_m/k_v)*(L/h) shear cannot govern above L/h = 2.6 in
    ANY case in the table. There is no one-number version of this control in
    aluminium, and that fact is itself the finding — see ``beam.shear_stress``.

    In plywood the ratio is 30/3.5 = 8.6 because shear strength along the grain is
    roughly a tenth of bending strength, and under a distributed load on simple
    supports (k_m/k_v = 1/4) shear governs below L/h = 8.6. The baseline's own
    L/h of 6 sits inside that, so the material and the support case are the two
    keys that move the member into the regime, and the load is then derived from
    the threshold. That is one physical idea — *put the member where shear
    governs* — expressed in the fewest keys that can express it.

    ``beam.model_validity`` also fails here, at util 3.2, and this is not
    contamination: it is a theorem. The omitted shear deflection is
    (k_s/k_d)*alpha*(E/G)*I/(A*L^2), and the same two things that make shear
    stress govern — a low shear strength and a stiff support case — make shear
    deflection large. Worked across every material and case in this pack, the
    region where shear stress governs lies entirely inside the region where shear
    deflection exceeds 10%. Wherever this gate binds, the deflection numbers are
    already untrustworthy, and both gates saying so at once is correct.
    """
    material, case = "plywood_birch", "simply_supported_udl"
    probe = _variant(ctx, material=material, beam_case=case)
    sec = B.section(probe)
    _case, (_kd, _km, k_v, _ks, _n), _d = B.case_of(probe)
    allow, _src = B.allowable_shear(probe, _sf(probe))
    # tau = V*Q/(I*t) with V = k_v*P, linear in P
    P_bad = _MARGIN * allow * sec["I"] * sec["t_web"] / (sec["Q"] * k_v)
    return _variant(ctx, material=material, beam_case=case, load_n=round(P_bad, 1))


def slender_strut(ctx):
    """beam.buckling — the unbraced length at which the factored load is 15% past P_cr.

    Inverting Euler, L = sqrt(pi^2*E*I_min / P_cr_target) / K with
    P_cr_target = axial * SF / _MARGIN: about 471 mm against the baseline's 60,
    for P_cr 696 N against an 800 N factored demand. Section, material, end
    fixity and axial load are all untouched; only the length the strut has to hold
    that load over has changed, which is the single variable this gate exists to
    be sensitive to. Nothing else in the pack reads ``column_length_mm``, so this
    control fires exactly one gate.

    It also crosses the Johnson/Euler transition — lambda 342 against a transition
    of 70 — so the gate has to be on the elastic branch here to get the right
    answer, and the inversion above is only valid because it is.
    """
    probe = _variant(ctx)
    sec = B.section(probe)
    E, _src = B.modulus(probe)
    sf = _sf(probe)
    names, sense = B.LOAD_KEYS["axial_load_n"]
    axial = B.unsigned_load(B.num(probe, names, "the axial load"), names, sense)
    cond = str(B.get(probe, ("column_end_condition", "end_condition", "column_ends"), "")
               or "").strip().lower().replace("-", "_").replace(" ", "_")
    k_raw = B.get(probe, ("column_k", "buckling_k", "k_factor", "effective_length_factor"))
    K = float(k_raw) if k_raw is not None else B.END_CONDITION_K[cond]
    p_cr_target = axial * sf / _MARGIN
    L_bad = math.sqrt(math.pi ** 2 * E * sec["I_min"] / p_cr_target) / K
    return _variant(ctx, column_length_mm=round(L_bad, 1))


def thin_flange(ctx):
    """beam.bearing — the bearing thickness that puts hole-wall stress 15% past allowable.

    Bearing stress goes as 1/t, so t_bad = P / (n * d * _MARGIN * allowable):
    about 0.47 mm against the baseline's 6 mm ear, taking 12.5 MPa to 158.7 MPa
    against a 138 MPa allowable. This is the sheet-metal ear that gets added late
    in a design. Nothing else in the pack reads ``plate_thickness_mm``, so no
    other gate moves — the beam itself is untouched, which is the whole point of
    this gate existing in a structural pack rather than a fastener one.
    """
    probe = _variant(ctx)
    d = B.num(probe, ("bolt_dia_mm", "fastener_dia_mm", "bolt_diameter_mm"),
              "the bolt diameter")
    n, _defaulted = B.opt(probe, ("n_bolts", "bolt_count", "fastener_count"), 1.0)
    names, sense = B.LOAD_KEYS["bearing_load_n"]
    raw = B.get(probe, names)
    P = B.unsigned_load(float(raw), names, sense) if raw is not None else B.load(probe)
    allow, _src = B.allowable_direct(probe, _sf(probe))
    t_bad = P / (n * d * _MARGIN * allow)
    return _variant(ctx, plate_thickness_mm=round(t_bad, 4))


def stubby(ctx):
    """beam.model_validity — the span that puts L/h 15% below the slenderness floor.

    L_bad = h * limit / _MARGIN: about 43.5 mm against the baseline's 60, on the
    same 10 mm section depth, for L/h 4.35 against a floor of 5. The part is not
    weak — it is
    stiffer and stronger than the baseline in every other gate, all of which pass.
    What has failed is the MODEL, and a validity gate that could not tell those
    two apart would be worthless.

    The margin is deliberately small so that this control proves the floor is at
    5 and not merely that the arithmetic responds. A fixture at L/h 1.2 (the
    previous version) would fire just as happily if the floor had been mistyped as
    3 or read from the wrong key.

    This control exercises the SLENDERNESS criterion. The gate's second criterion
    — the omitted shear deflection exceeding 10% — is what fails on
    ``shear_governed``, where a plywood beam at a perfectly respectable L/h of 6
    is missing 32% of its deflection.
    """
    probe = _variant(ctx)
    sec = B.section(probe)
    limit, _defaulted = B.opt(probe, ("min_slenderness", "slenderness_limit"),
                              B.MIN_SLENDERNESS)
    return _variant(ctx, span_mm=round(sec["depth"] * limit / _MARGIN, 3))


def negated_load(ctx):
    """beam.input_sanity — the same beam with its transverse load carrying a sign.

    One change: the model adopts a downward-negative convention, so every load key
    it carries flips sign. That is not a corrupt input — it is an ordinary
    convention, and the load family is the one input a model is most likely to
    carry a sign on. It is expressed in three keys because a convention applies to
    all of them or to none; a fixture that negated only ``load_n`` would leave the
    guards on ``axial_load_n`` and ``bearing_load_n`` unexercised.

    Before the sign guards existed this beam returned seven PASSes — `util -0.65`
    on bending, `tau -3.75 MPa` on shear, `util -0.03` on buckling, `util -0.09`
    on bearing, and `L/inf` with ``measured=None`` out of the deflection-ratio
    gate's "infinitely stiff is a pass" branch. Seven green ticks and zero
    refusals on a member that had not been analysed at all. All six analysis gates
    now SKIP on it, resolving their claims BLOCKED; this gate FAILs, which is what
    keeps the report from showing six quiet blanks and no red line at all.
    (``beam.model_validity`` still passes, correctly: it reads geometry and
    material, not loads.)

    The magnitudes are untouched — they have to be, because the fault being tested
    is the sign and nothing else. There is no threshold here to derive a magnitude
    from: the limit is zero faults.
    """
    flipped = {key: -float(BASELINE[key]) for key in B.LOAD_KEYS if key in BASELINE}
    return _variant(ctx, **flipped)


def si_units(ctx):
    """beam.input_sanity — the SAME baseline restated in metres and pascals.

    Not a declared negative control (a gate gets one, and the sign fault above is
    the blocker this pack was shipped with), but a runnable demonstration of the
    other half of what ``beam.input_sanity`` catches, and the fixture to reach for
    if that half ever needs a control of its own.

    Before the unit bands existed this projection produced seven PASSes reading
    `E 68900000000 MPa`, `I=0 mm^4`, `90000000.0 MPa vs 138000000.0 MPa allowable`
    and `bearing 12500000.0 MPa on 0.0 mm^2`. The absurd numbers were printed, so
    a human reading the detail lines would catch it — but utilisation, L/delta and
    L/h are all scale-invariant and read completely normal, so an agent scanning
    verdict status learned nothing at all.
    """
    lengths = ("span_mm", "width_mm", "height_mm", "column_length_mm",
               "bolt_dia_mm", "plate_thickness_mm", "deflection_limit_mm")
    params = dict(BASELINE)
    for key in lengths:
        if key in params:
            params[key] = float(params[key]) / 1000.0
    row = B.MATERIALS[str(params["material"])]
    params.pop("material")
    params["modulus_mpa"] = row["E"] * 1.0e6          # MPa -> Pa
    params["yield_mpa"] = row["yield"] * 1.0e6
    return dataclasses.replace(ctx, params=params)
