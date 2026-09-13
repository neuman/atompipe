#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Behaviour matrix for ``cad.assembly_connected``: held, apart, and through.

    python3 packs/cad-solid/selftest/check_connectivity.py

The unittest harness can only require a gate to FAIL — that is what a negative
control is — so it runs ``bad_meshes.py:broken_chain`` and stops. For this gate the
other directions are where the value is, and they are the ones that are easy to get
wrong in a way nothing else notices:

1. **COVERAGE is the default question, and it needs no declaration.** Every part must
   be held by something. The gate builds the contact graph from the geometry and
   reports any part in no contact at all, and any group of parts joined to each other
   and not to the rest. The first version of this gate asked only about DECLARED
   pairs, so on the real 30-body assembly it was hardened against — the one whose
   rudder hung 42.9 mm below its bracket — it reported "the projection declares no
   required contacts" and skipped. ``orphaned_part`` is that input, and the gate must
   FAIL on it with nothing declared.
2. **A pair that INTERPENETRATES must come out CONNECTED**, with a gap of exactly
   zero. A screw in its insert, a stock in its bearing, a shaft in its tube: all of
   them overlap by design. This gate asks the opposite question from `cad.clash`
   about a different set of pairs, and a gate that reported an assembled press fit
   as a gap would be unusable on any real assembly.
3. **The measurement must sample the SURFACES, not the vertices.** This is the trap
   that has actually bitten, and the check below prints both numbers side by side: a
   6 mm shaft driven through a bearing boss reads **11.2 mm apart** measured at
   vertices and **0.00 mm** measured properly, because a tessellated cylinder has
   vertices only at its two end rings.
4. **A pair reported APART must carry a bound, not an impression.** The refinement
   lattice's covering radius is the error, it is one-signed, and ``measured - error
   > tolerance`` is what the gate calls "apart". Section 7 measures it.
5. **A declared member that is not in the assembly is a FAILURE, not a skip**, and a
   wildcard, a missing reason and an unrecognised role are all REFUSED — each failing
   the gate on the declaration rather than being honoured or dropped quietly.
6. **`measured`, `limit` and the pair named in `detail` all come from ONE row.** They
   used to come from three, so a PASS could print a measurement larger than the limit
   it was compared against. Section 8 is that check, on every fixture in the file.
7. **Every fixture is SEALED**: it behaves identically against the pack's baseline
   and against an empty projection. Section 9.

Exits non-zero and names every row that came out wrong. Standalone on purpose: it is
a check on the instrument, it needs no project, and it must be runnable on the
machine where the answer is bad.
"""
from __future__ import annotations

import dataclasses
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_PACK = os.path.dirname(_HERE)
_REPO = os.path.dirname(os.path.dirname(_PACK))
for _candidate in (os.path.join(_REPO, "src"), _PACK):
    if os.path.isdir(_candidate) and _candidate not in sys.path:
        sys.path.insert(0, _candidate)


def _load_gate_module():
    """Import the pack's gate module by path, so this runs from any directory."""
    import importlib.util

    path = os.path.join(_PACK, "gates", "solid.py")
    spec = importlib.util.spec_from_file_location("cad_solid_gates_solid", path)
    if spec is None or spec.loader is None:            # pragma: no cover - packaging
        raise SystemExit(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _baseline() -> dict:
    """The pack's OWN projection. Never a host project's — see bad_meshes._sealed."""
    with open(os.path.join(_HERE, "baseline.json"), encoding="utf-8") as handle:
        loaded = json.load(handle)
    return {k: v for k, v in loaded.items() if not k.startswith("_")}


def _ctx(gates, meshes=None, **overrides):
    """A sealed context: the pack's baseline, this geometry, these declarations."""
    params = _baseline()
    params.update(overrides)
    return gates.GateContext(
        root=_PACK, params=params, out_dir=os.path.join(_PACK, ".selftest-out"),
        tier=3, log=lambda _m: None, extra={"meshes": meshes} if meshes else {})


def _rows(verdict):
    """The per-pair table the gate just wrote, read back off disk.

    Read back rather than returned, for the same reason `check_clash_contact.py`
    does it: the evidence file is what a reader and the site actually see, and a row
    that cannot be serialised (a bare `NaN` is not JSON) breaks the page rather than
    one pair.
    """
    if not verdict.evidence:
        return []
    with open(verdict.evidence[0], encoding="utf-8") as handle:
        return json.load(handle).get("contacts", [])


def _headline(verdict):
    """The one row the verdict's number, limit and named pair must all come from."""
    if not verdict.evidence:
        return {}
    with open(verdict.evidence[0], encoding="utf-8") as handle:
        return json.load(handle).get("headline") or {}


def _row(rows, a, b):
    for row in rows:
        if {row["a"], row["b"]} == {a, b}:
            return row
    return {}


def _vertex_only_gaps(gates, mesh_a, mesh_b):
    """``(vertex-to-vertex, vertex-to-surface)`` — the two naive answers, in mm.

    Printed next to the real one, because the difference is the whole argument for
    sampling the faces and it is far more convincing as three numbers than as a
    paragraph. Both naive forms are implementations somebody reasonably writes:
    nearest vertex pair, and nearest vertex-to-surface (which is what a
    ``signed_distance`` over the other part's vertices gives, and what reported a
    stock passing clean through its bore as 5.5 mm apart on a real boat).
    """
    import numpy as np

    va = np.asarray(mesh_a.vertices, dtype=float)
    vb = np.asarray(mesh_b.vertices, dtype=float)
    pair = float(np.sqrt(((va[:, None, :] - vb[None, :, :]) ** 2).sum(axis=2)).min())
    surface = min(
        float(gates._point_triangle_min(va, np.asarray(mesh_b.triangles, float)).min()),
        float(gates._point_triangle_min(vb, np.asarray(mesh_a.triangles, float)).min()))
    return pair, surface


def main() -> int:                                     # noqa: C901 - a flat check list
    gates = _load_gate_module()
    import bad_meshes

    problems: list[str] = []

    def check(label, condition, detail=""):
        print(f"  [{'ok  ' if condition else 'BAD '}] {label}"
              + (f" — {detail}" if detail else ""))
        if not condition:
            problems.append(f"{label}: {detail}")

    base = gates.GateContext(root=_PACK, params=_baseline(),
                             out_dir=os.path.join(_PACK, ".selftest-out"), tier=3,
                             log=lambda _m: None, extra={})

    # -- 1. the known-good assembly ----------------------------------------- #
    print("1. the pack's own baseline (three declared contacts, all closed)")
    verdict = gates.assembly_connected(_ctx(gates))
    rows = _rows(verdict)
    check("gate passes", verdict.passed and not verdict.skipped,
          verdict.detail or verdict.skip_reason)
    named = ", ".join(sorted(f"{r['a']}/{r['b']}" for r in rows))
    check("all three declared contacts are measured", len(rows) == 3,
          f"{len(rows)} row(s): {named}")
    check("the clash_allow role is read as a required contact",
          any("clash_allow" in " ".join(r.get("sources", [])) for r in rows),
          "the cover/housing entry carries role=required and is not typed twice")
    check("the chain is expanded into consecutive pairs",
          sum(1 for r in rows if r.get("chains")) == 2,
          "clamp_path: cover -> housing -> carriage")

    # -- 2. a shaft through a boss: interpenetration IS connection ---------- #
    print("\n2. a 6 mm shaft through a bearing boss whose bore is not modelled")
    fixture = bad_meshes.shaft_in_bore(dataclasses.replace(base))
    verdict = gates.assembly_connected(fixture)
    row = _row(_rows(verdict), "bearing_boss", "shaft")
    meshes = fixture.extra["meshes"]
    naive, naive_surface = _vertex_only_gaps(gates, meshes["bearing_boss"], meshes["shaft"])
    check("gate passes", verdict.passed and not verdict.skipped,
          verdict.detail or verdict.skip_reason)
    check("the pair is reported as interpenetrating", row.get("interpenetrating") is True,
          f"interpenetrating={row.get('interpenetrating')!r}")
    check("its gap is exactly zero", row.get("gap_mm") == 0.0,
          f"gap_mm={row.get('gap_mm')!r}")
    tolerance = float(_baseline()["max_mating_gap_mm"])
    check("and BOTH vertex-only measurements would have called it OPEN",
          min(naive, naive_surface) > tolerance,
          f"nearest vertex pair {naive:.2f} mm, nearest vertex-to-surface "
          f"{naive_surface:.2f} mm, actual surface-to-surface {row.get('gap_mm')!r} mm "
          f"— the naive answers are {min(naive, naive_surface) / tolerance:.0f}x the "
          f"{tolerance:g} mm mating tolerance on a pair that is assembled")

    # -- 3. the shipped fixtures -------------------------------------------- #
    print("\n3. the shipped fixtures")
    for name, must_pass, note in (
        ("broken_chain", False, "the cover 3 mm off its rim (the declared control)"),
        ("orphaned_part", False, "the roller 12 mm off the floor, NOTHING declared"),
        ("free_standing_silencer", False, "a free-standing entry with no reason"),
        ("lifted_stop", False, "the guide roller 2 mm off the cavity floor"),
        ("missing_member", False, "a declared contact whose member is not modelled"),
        ("mating_wildcard", False, "'carriage' vs '*'"),
        ("mating_no_reason", False, "an entry with no stated reason"),
        ("mating_unknown_role", False, "role='requird' on a clash_allow entry"),
        ("shaft_in_bore", True, "a press fit, which is a contact"),
    ):
        fixture_ctx = getattr(bad_meshes, name)(dataclasses.replace(base))
        verdict = gates.assembly_connected(fixture_ctx)
        ok = (verdict.passed if must_pass else not verdict.passed) and not verdict.skipped
        check(f"{name} {'passes' if must_pass else 'fails'} ({note})", ok,
              verdict.detail or verdict.skip_reason)
    # -- 4. the refusals are about the DOCUMENT, not the geometry ----------- #
    print("\n4. a refused declaration fails on the entry, with nothing wrong in the mesh")
    for label, params in (
        ("a wildcard", {"mating_pairs": [{"pair": ["cover", "*"], "reason": "bolted"}]}),
        ("no reason", {"mating_pairs": [{"pair": ["cover", "carriage"], "reason": " "}]}),
        ("a part named twice", {"mating_pairs": [{"pair": ["cover", "cover"],
                                                  "reason": "itself"}]}),
        ("a one-member chain", {"assembly_chains": {"x": {"chain": ["cover"],
                                                          "reason": "a chain of one"}}}),
        ("a chain with no reason", {"assembly_chains": {"x": {"chain": ["cover", "housing"]}}}),
        ("a negative tolerance", {"mating_pairs": [{"pair": ["cover", "carriage"],
                                                    "reason": "bolted", "tol_mm": -1}]}),
    ):
        verdict = gates.assembly_connected(_ctx(gates, **params))
        check(f"refuses {label}",
              not verdict.passed and not verdict.skipped
              and verdict.units == "refused entries",
              verdict.detail or verdict.skip_reason)

    # -- 5. NOTHING DECLARED. Coverage still answers, and never skips -------- #
    #
    # This is the section the whole gate turns on. The first version SKIPPED here —
    # "the projection declares no required contacts" — which is an absence of
    # evidence rendered as an absence of problems, on the one input where the real
    # defect actually lived. Coverage asks the question that needs no foresight:
    # every part must be held by something.
    print("\n5. nothing declared at all")
    verdict = gates.assembly_connected(_ctx(gates, clash_allow=[], mating_pairs=[],
                                            assembly_chains={}))
    check("the intact assembly still PASSES on coverage alone",
          verdict.passed and not verdict.skipped, verdict.detail or verdict.skip_reason)
    check("and says so: nothing declared, so which part holds which is unproven",
          "nothing is declared" in (verdict.detail or ""), verdict.detail)
    check("the pass line states how much was examined, not how much was declared",
          "parts examined" in (verdict.detail or ""), verdict.detail)

    orphan = gates.assembly_connected(bad_meshes.orphaned_part(dataclasses.replace(base)))
    check("a part adrift FAILS with nothing declared",
          not orphan.passed and not orphan.skipped,
          orphan.detail or orphan.skip_reason)
    check("and the verdict NAMES the floating part",
          "guide_roller" in (orphan.detail or ""), orphan.detail)
    check("with a locator on it, so the viewer lights it up",
          any(loc.target.startswith("guide_roller") for loc in (orphan.locators or [])),
          ", ".join(loc.target for loc in (orphan.locators or [])) or "none")

    # A part declared free-standing ON PURPOSE, with a reason, is not a finding —
    # and the reason is the whole difference between a declaration and a silencer.
    declared = bad_meshes.orphaned_part(dataclasses.replace(base))
    declared.params["free_standing_parts"] = [
        {"part": "guide_roller",
         "reason": "shipped loose in the box; shown here for context only"}]
    verdict = gates.assembly_connected(declared)
    check("a part declared free-standing WITH a reason is not a finding",
          verdict.passed and not verdict.skipped, verdict.detail or verdict.skip_reason)
    check("and the pass line says the declaration was used",
          "free-standing" in (verdict.detail or ""), verdict.detail)

    # The only skip there is.
    verdict = gates.assembly_connected(
        _ctx(gates, meshes={"housing": bad_meshes._baseline_mesh("housing")}))
    check("ONE part skips — nothing to measure below two",
          verdict.skipped and not verdict.passed, verdict.skip_reason)
    check("and no other input skips: no tolerance is a FAILURE, not silence",
          not gates.assembly_connected(
              _ctx(gates, **{"max_mating_gap_mm": None,
                             "mating_tolerance_mm": None})).skipped,
          gates.assembly_connected(_ctx(gates, **{"max_mating_gap_mm": None,
                                                  "mating_tolerance_mm": None})).detail)
    bare = gates.assembly_connected(_ctx(gates, clash_allow=[], mating_pairs=[],
                                         assembly_chains={},
                                         **{"max_mating_gap_mm": None,
                                            "mating_tolerance_mm": None}))
    check("with nothing declared AND no tolerance, coverage runs at the "
          "tessellation floor", bare.passed and not bare.skipped,
          bare.detail or bare.skip_reason)
    # -- 6. the same pair declared twice is one contact --------------------- #
    #
    # The ordinary case, not a mistake: a clash_allow entry marked required and a
    # chain step naming the same two parts. Both say "these must touch", so the
    # tightest stated tolerance governs and the row records both sources.
    print("\n6. one pair, two declarations")
    verdict = gates.assembly_connected(_ctx(gates, **{
        "mating_pairs": [{"pair": ["cover", "housing"], "reason": "bolted rim",
                          "tol_mm": 0.05}]}))
    row = _row(_rows(verdict), "cover", "housing")
    check("the pair declared three ways is ONE row",
          len(_rows(verdict)) == 2 and row,
          f"{len(_rows(verdict))} rows: cover/housing (clash_allow role + chain step + "
          f"mating_pairs) and carriage/housing (chain step)")
    check("both sources are recorded", len(row.get("sources", [])) >= 2,
          f"sources={row.get('sources')!r}")
    check("the tightest tolerance governs", row.get("tolerance_mm") == 0.05,
          f"tolerance_mm={row.get('tolerance_mm')!r} (0.05 from the entry, "
          f"0.2 from max_mating_gap_mm)")

    # -- 7. the error bound, measured rather than asserted ------------------ #
    #
    # The place a sampled distance goes wrong is an isolated closest approach on a
    # CURVED surface — and the calibration case has to be one where the closest point
    # is not a vertex, or it proves nothing. Two crossed tessellated cylinders are
    # that case and it is the real one: a cylinder has vertices ONLY at its two end
    # rings, so the closest approach between two of them crossing at right angles
    # lands in the middle of a 200 mm facet with no vertex within 100 mm of it. A
    # sphere on a plate does NOT work — its closest point is always its lowest
    # vertex, so every budget reads the answer exactly and the check is vacuous.
    #
    # Three things have to hold, and the last is the one the old implementation could
    # not claim. The error is one-signed (a sampled distance is an upper bound, so a
    # thin budget cries wolf and cannot hide a contact). The default budget is NOT
    # good enough on its own here, which is why the refinement is not decoration. And
    # the refinement returns a BOUND: `measured - error` is what the gate compares
    # against the tolerance, so "apart" is a proof rather than an impression.
    print("\n7. the error bound (two crossed cylinders, truly 0.500 mm apart)")
    import numpy as np
    import trimesh

    def crossed():
        """Two 40 mm cylinders at right angles, 0.500 mm apart, freshly built.

        Rebuilt per call because `_Solid` caches its sample cloud for the life of a
        gate run, which is right inside the gate and wrong in a loop over budgets.
        """
        def barrel(axis):
            turn = trimesh.transformations.rotation_matrix(np.pi / 2.0, axis)
            return trimesh.creation.cylinder(radius=20.0, height=200.0, sections=32,
                                             transform=turn)
        lower, upper = barrel((0.0, 1.0, 0.0)), barrel((1.0, 0.0, 0.0))
        upper.apply_translation(
            (0.0, 0.0, lower.bounds[1][2] - upper.bounds[0][2] + 0.5))
        return gates._Solid("lower", lower), gates._Solid("upper", upper)

    true_gap = 0.5
    coarse = {}
    for budget in (50, 200, gates.CONTACT_SAMPLES, 10 * gates.CONTACT_SAMPLES):
        left, right = crossed()
        coarse[budget] = gates._coarse_gap(left, right, budget, float("inf"))
        print(f"        {budget:>6d} samples/part -> {coarse[budget]:.3f} mm "
              f"({coarse[budget] - true_gap:+.3f} mm) before refinement")
    check("every sampled answer is an OVER-estimate, never an under-estimate",
          all(value >= true_gap - 1e-9 for value in coarse.values()),
          f"{ {k: round(v, 3) for k, v in coarse.items()} } — a sampled distance is "
          f"an upper bound on the true one, so a thin budget cries wolf and cannot "
          f"hide a contact")
    check("the default budget is NOT enough on its own, which is why refining matters",
          coarse[gates.CONTACT_SAMPLES] > true_gap + 0.1,
          f"{coarse[gates.CONTACT_SAMPLES]:.3f} mm vs {true_gap} mm true — "
          f"{coarse[gates.CONTACT_SAMPLES] - true_gap:+.3f} mm, which at a tight "
          f"tolerance is a false alarm on a closed joint")

    left, right = crossed()
    result = gates._pair_contact(left, right, 0.55, gates.CONTACT_SAMPLES)
    print(f"        refined at a 0.55 mm tolerance -> {result['gap_mm']:.4f} mm "
          f"on {result['lattice_points']} lattice points")
    check("refinement rescues the pair the coarse pass would have failed",
          result["touching"] and abs(result["gap_mm"] - true_gap) < 0.01,
          f"gap_mm={result['gap_mm']!r} touching={result['touching']!r} — the coarse "
          f"pass said {coarse[gates.CONTACT_SAMPLES]:.3f} mm, over a 0.55 mm tolerance")
    check("and it never reports LESS than the truth",
          result["gap_mm"] >= true_gap - 1e-9, f"{result['gap_mm']!r} vs {true_gap}")

    left, right = crossed()
    apart = gates._pair_contact(left, right, 0.2, gates.CONTACT_SAMPLES)
    check("a pair that really is beyond the tolerance is PROVEN apart",
          not apart["touching"] and apart["decidable"], apart["why"])
    check("and says the figure is an upper bound when nothing measured it",
          apart["error_mm"] is None and "UPPER bound" in apart["why"],
          f"error_mm={apart['error_mm']!r}: {apart['why'][:110]}")

    # -- 8. the verdict's number, limit and named pair are ONE row ---------- #
    #
    # They used to be three: `measured` was the worst gap anywhere in the assembly,
    # `limit` was the tolerance of the worst OPEN pair, and `detail` named a third —
    # so a PASS could print a measurement larger than the limit beside it. The gate
    # now builds one headline row and reads everything from it; this is the check
    # that keeps it that way, run over every fixture in the file.
    print("\n8. measured, limit and the named pair come from ONE row")
    for name in ("baseline", "orphaned_part", "broken_chain", "lifted_stop",
                 "missing_member", "shaft_in_bore"):
        if name == "baseline":
            verdict = gates.assembly_connected(_ctx(gates))
        else:
            verdict = gates.assembly_connected(
                getattr(bad_meshes, name)(dataclasses.replace(base)))
        head = _headline(verdict)
        detail = verdict.detail or ""
        ok = bool(head) and verdict.measured == head.get("measured_mm") \
            and verdict.limit == head.get("limit_mm") \
            and (head.get("a", "") in detail) \
            and (not head.get("b") or head["b"] in detail)
        check(f"{name}: {verdict.measured!r} vs {verdict.limit!r} is "
              f"{head.get('a')}/{head.get('b')} ({head.get('kind')})", ok,
              "" if ok else f"headline={head!r} detail={detail[:120]!r}")
        if verdict.passed:
            check(f"{name}: a PASS never prints measured above limit",
                  verdict.measured is None or verdict.limit is None
                  or verdict.measured <= verdict.limit,
                  f"measured={verdict.measured!r} limit={verdict.limit!r}")

    # -- 9. every fixture is SEALED ----------------------------------------- #
    #
    # A fixture that layers its known-bad values over the host project's projection
    # is a control that fires in some repositories and not others, which is the same
    # as having none. The probe is the one tests/test_packs.py::ControlsAreSealed
    # uses, run here over the fixtures the unittest harness never reaches.
    print("\n9. every fixture behaves the same against an empty projection")
    empty = gates.GateContext(root=_PACK, params={},
                              out_dir=os.path.join(_PACK, ".selftest-out"), tier=3,
                              log=lambda _m: None, extra={})
    for name in ("broken_chain", "orphaned_part", "free_standing_silencer",
                 "lifted_stop", "missing_member", "mating_wildcard",
                 "mating_no_reason", "mating_unknown_role", "shaft_in_bore"):
        rich = gates.assembly_connected(getattr(bad_meshes, name)(
            dataclasses.replace(base)))
        bare = gates.assembly_connected(getattr(bad_meshes, name)(
            dataclasses.replace(empty)))
        same = (rich.passed == bare.passed and rich.skipped == bare.skipped
                and not bare.skipped)
        check(f"{name} is sealed", same,
              f"baseline -> {'pass' if rich.passed else 'FAIL'}"
              f"{' (skip)' if rich.skipped else ''}, empty projection -> "
              f"{'pass' if bare.passed else 'FAIL'}"
              f"{' (skip)' if bare.skipped else ''}: {bare.detail or bare.skip_reason}")

    print()
    if problems:
        print(f"FAILED — {len(problems)} wrong answer(s):")
        for line in problems:
            print(f"  * {line}")
        return 1
    print("OK — every part must be held by something with nothing declared, a gap is "
          "a finding, interpenetration is a contact, a missing member is a failure, "
          "a declaration this gate cannot trust fails the gate, and the number in the "
          "verdict belongs to the pair the verdict names")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
