# SPDX-License-Identifier: Apache-2.0
"""Known-bad BOMs for the sourcing gates. One commercial defect each.

Every fixture builds its known-bad input from THIS PACK'S OWN
``selftest/baseline.json`` — the projection CI asserts every gate passes — copies
the BOM inside it, changes exactly ONE commercially meaningful thing in the
direction the gate under test cares about, and returns a context carrying that
document and nothing of the host project's.

**Sealed, deliberately** (see the SEALED FIXTURES section of
``docs/PACK_FORMAT.md``). A control is a test of the INSTRUMENT: proof the gate
can detect the failure mode it claims to rule out. That proof has to be the same
proof in every repository this pack is installed in. A fixture that mutated the
host project's BOM would have its severity decided by that project's numbers —
its thresholds, its quantities, its prices — so the identical control would fire
in one repo and pass in another, which is the same as having none and worse,
because it looks like having one.

ONE THING, and far enough. A defect sized to just clear a threshold stops
clearing it the moment somebody moves that threshold, and the selftest then
reports a working gate as unproven. So no fixture hardcodes a magnitude: each
reads the limit it has to beat out of the baseline the gate reads it from, and
beats it with room to spare — ten budgets rather than one, twenty times the
idle-money limit rather than one, and, where the limit is a COUNT of lines,
enough lines rather than exactly one.

That constraint is the whole point. A fixture that truncated the file or deleted
the ``lines`` array would prove the gates handle garbage, not that they measure
anything. Each of these is a BOM somebody could plausibly have committed: a price
cell left blank, a re-quote, a quote that came back on a foreign price list, an
end-of-life notice, a vendor minimum, a finish the quoted line does not offer, a
second source that quietly went away.
"""
from __future__ import annotations

import copy
import dataclasses
import json
import math
import os
import sys

_PACK_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PACK_DIR not in sys.path:
    sys.path.insert(0, _PACK_DIR)

import bomlib  # noqa: E402

#: The pack's own passing projection. Every fixture starts here and nowhere else.
BASELINE = os.path.join(_PACK_DIR, "selftest", "baseline.json")


# --------------------------------------------------------------------------- #
def _base(ctx):
    """``(sealed context, the BOM document inside it)``. Mutate the doc, then _note().

    The returned context carries the baseline projection in ``params``, so every
    threshold the fixture and the gate look up — ``build_quantity``,
    ``budget_per_unit``, ``moq_ratio_limit``, ``single_source_limit`` — resolves
    out of the pack, not out of whatever project this pack was installed into.
    Only ``root``/``out_dir``/``ledger`` survive from the host, and no gate here
    reads a number from any of them.
    """
    with open(BASELINE, encoding="utf-8") as fh:
        params = {k: v for k, v in json.load(fh).items() if not k.startswith("_")}
    doc = params.get("bom")
    if not isinstance(doc, dict) or not isinstance(doc.get("lines"), list):
        raise AssertionError(
            f"{BASELINE} carries no 'bom' document with a 'lines' array — the controls "
            f"in this pack are sealed to it and cannot be built without it")
    sealed = dataclasses.replace(ctx, params=copy.deepcopy(params), extra={})
    return sealed, sealed.params["bom"]


def _note(sealed, doc, text):
    """Hand the mutated document to the gate, with a record of what was done to it."""
    doc["_control"] = text
    return dataclasses.replace(sealed, extra={"bom": doc})


def _priced(doc):
    """Lines that carry a usable price, richest first. The defect goes where it bites."""
    out = []
    for i, line in enumerate(bomlib.lines(doc)):
        price, _ = bomlib.unit_price(line, doc)
        if price is not None and price > 0:
            out.append((price, i, line))
    return sorted(out, key=lambda t: (-t[0], t[1]))


# --------------------------------------------------------------------------- #
def unpriced_line(ctx):
    """bom.complete — one line's price cell left blank.

    The commonest real BOM defect there is, and the one a spreadsheet hides best:
    the row is still there, the part number is still right, and the total is now
    smaller than the truth. Nothing else about the part moves.
    """
    sealed, doc = _base(ctx)
    _, idx, line = _priced(doc)[0]
    line["unit_price"] = None
    return _note(sealed, doc, f"{bomlib.ref(line, idx)} left unpriced")


def price_shock(ctx):
    """bom.cost — one line re-quoted so it alone costs ten budgets.

    The email that arrives the week you were going to order. One number moves;
    quantities, vendors, minimums and tooling charges are untouched, so a failure
    here can only have come from the roll-up seeing the price.
    """
    sealed, doc = _base(ctx)
    qty = int(bomlib.setting(doc, sealed, "build_quantity"))
    budget_unit = bomlib.setting(doc, sealed, "budget_per_unit")
    budget_total = bomlib.setting(doc, sealed, "budget_total")
    per_unit_budget = (float(budget_unit) if budget_unit is not None
                       else float(budget_total) / qty)
    _, idx, line = _priced(doc)[0]
    per = max(float(line.get("qty_per_unit") or 1.0), 1e-6)
    # This part alone now costs ten times the entire per-unit budget. Taken from
    # the budget rather than as a fixed multiple so the control still lands when
    # somebody raises the budget.
    line["unit_price"] = round(10.0 * per_unit_budget / per, 4)
    return _note(sealed, doc,
                 f"{bomlib.ref(line, idx)} re-quoted to {line['unit_price']}, ten times "
                 f"the whole {per_unit_budget:g}/unit budget in one part")


def foreign_quote(ctx):
    """bom.currency — one line re-quoted on a price list the document cannot read.

    The second quote comes back from the vendor's own regional price list. The
    part, the vendor, the quantity and the number itself are all exactly as they
    were; the only change is the currency code beside the number, and there is no
    rate in the document to reach the base currency with. This is the change a
    roll-up cannot see: adding that number in produces a total that is wrong by
    whatever the exchange rate happens to be, and nothing else in the document
    disagrees with it.
    """
    sealed, doc = _base(ctx)
    base = str(doc.get("currency") or "").strip().upper()
    have = {str(code).strip().upper() for code in (doc.get("fx_rates") or {})}
    have.add(base)
    # A currency the document has no rate for, chosen from real ones rather than
    # invented, and READ OFF the document's own table so the control still lands
    # on a project that adds rates.
    code = next((c for c in ("JPY", "CHF", "SEK", "INR", "BRL", "NOK", "PLN")
                 if c not in have), "XXX")
    _, idx, line = _priced(doc)[0]
    line["price_currency"] = code
    return _note(sealed, doc,
                 f"{bomlib.ref(line, idx)} re-quoted in {code}, for which the document "
                 f"holds no fx_rates entry")


def end_of_life(ctx):
    """bom.availability — one line marked end-of-life.

    The notice that arrives by email and gets filed. Price, quantity, vendor and
    stock are exactly as they were; only the part's future changed, which is the
    one thing a BOM spreadsheet never recomputes.
    """
    sealed, doc = _base(ctx)
    for i, line in enumerate(bomlib.lines(doc)):
        if str(line.get("lifecycle") or "").strip().lower() not in bomlib.DEAD:
            line["lifecycle"] = "eol"
            return _note(sealed, doc, f"{bomlib.ref(line, i)} marked end-of-life")
    raise AssertionError("no line left to mark end-of-life")


def brutal_moq(ctx):
    """bom.moq — one vendor's minimum raised far past what the build needs.

    Applied to the most expensive line, because that is where a minimum stops
    being an annoyance and becomes money. The part, its price, its order multiple
    and the design are unchanged — only the smallest quantity the vendor will
    sell.

    The raise is computed from BOTH limits the gate applies, each read out of the
    baseline the gate reads it from: past the ratio filter, twenty times the
    per-line money limit, and twenty times the BOM-wide idle-capital limit. A
    control that only just trips is a control that stops tripping the next time
    somebody moves a threshold.
    """
    sealed, doc = _base(ctx)
    qty = int(bomlib.setting(doc, sealed, "build_quantity"))
    ratio_limit = float(bomlib.setting(doc, sealed, "moq_ratio_limit",
                                       bomlib.DEFAULT_MOQ_RATIO_LIMIT))
    excess_limit = float(bomlib.setting(doc, sealed, "moq_excess_limit",
                                        bomlib.DEFAULT_MOQ_EXCESS_LIMIT))
    price, idx, line = _priced(doc)[0]
    parts_total = sum(bomlib.purchase_qty(ln, qty) * (bomlib.unit_price(ln, doc)[0] or 0.0)
                      for ln in bomlib.lines(doc))
    idle_limit, _from = bomlib.idle_capital_limit(doc, sealed, parts_total)
    need = max(bomlib.needed_qty(line, qty), 1.0)
    line["moq"] = int(math.ceil(max(need * (ratio_limit + 1.0),
                                    need + 20.0 * excess_limit / price,
                                    need + 20.0 * idle_limit / price)))
    return _note(sealed, doc,
                 f"{bomlib.ref(line, idx)} MOQ raised to {line['moq']} against a need of "
                 f"{need:g} at {price:g} each")


def outside_capability(ctx):
    """bom.process_rules — one declared attribute moved outside the vendor's set.

    A finish the quoted line does not offer, or a tolerance ten times tighter than
    the process holds: whichever the project's own rules are written about. It is
    a design somebody could plausibly have specified, which is what makes it a
    test of the gate rather than a test of the JSON parser.

    ONE physical decision, applied EVERYWHERE THE DOCUMENT RECORDS IT. A board
    finish is one fact that lives in the design block and again on the line that
    buys the board, so a fixture that moved only one of them would be planting an
    inconsistent document instead of a changed one — and it would leave the
    line-scoped half of ``bomlib.evaluate_rules`` unexercised by any control, which
    is the half that expands a rule across lines and matches each line's own
    attributes. Both halves fail here, from the same single change.
    """
    sealed, doc = _base(ctx)
    if not (doc.get("process_rules") or []):
        raise AssertionError("the baseline supplies no process_rules to violate")

    for rule in bomlib.applicable_design_rules(doc):
        for attr, spec in (rule.get("require") or {}).items():
            design = doc.setdefault("design", {})
            value = bomlib.value_outside(spec, design.get(attr))
            design[attr] = value
            also = []
            for i, line in enumerate(bomlib.lines(doc)):
                if attr in bomlib.attrs_for_line(line):
                    line.setdefault("attributes", {})[attr] = value
                    also.append(bomlib.ref(line, i))
            where = f"design.{attr}" + (f" and {', '.join(also)}.{attr}" if also else "")
            return _note(sealed, doc,
                         f"{where} set to {value!r}, outside rule {rule.get('id')!r} "
                         f"— one decision, everywhere the document records it")

    for rule in (doc.get("process_rules") or []):
        if str(rule.get("scope") or "design").lower() != "line":
            continue
        for i, line in enumerate(bomlib.lines(doc)):
            attrs = bomlib.attrs_for_line(line)
            if not bomlib.rule_applies(rule, attrs):
                continue
            for attr, spec in (rule.get("require") or {}).items():
                line.setdefault("attributes", {})[attr] = bomlib.value_outside(spec, attrs.get(attr))
                return _note(sealed, doc,
                             f"{bomlib.ref(line, i)}.{attr} set to "
                             f"{line['attributes'][attr]!r}, outside rule {rule.get('id')!r}")
    raise AssertionError("no applicable process rule to violate")


def lost_second_source(ctx):
    """bom.single_source — the second source goes away, with nothing written down.

    One commercial event, expressed on each line in the terms that line records.
    A line that says who MAKES the part keeps BOTH of its distributors and loses
    only the qualified alternate: what is left is two companies shipping one
    factory's output, which is one source with better logistics and is exactly the
    case a distributor count cannot see. A line that names no manufacturer at all
    drops to one supplier. Prices, quantities and vendors are untouched; the parts
    are still buy-able, from one factory each, and nobody recorded that they know.

    Manufacturer-recorded lines are taken first and on this pack's baseline they
    are the only ones taken, which is the point: every planted line still lists two
    distributors, so the gate can only fail this fixture by counting factories.
    That makes the control discriminating rather than merely loud — if the count
    silently went back to counting boxes, the lines would read as dual-sourced, the
    gate would pass its own known-bad input, and the selftest would say so. The
    supplier spelling is used as filler only where a project records too few
    manufacturers to reach its own limit.

    The number of lines is taken from the baseline's ``single_source_limit`` rather
    than fixed at one, for the same reason ``brutal_moq`` overshoots its money
    limit: a project that has already accepted N sole-source lines in writing needs
    MORE than N new ones before this gate can move.
    """
    sealed, doc = _base(ctx)
    limit = float(bomlib.setting(doc, sealed, "single_source_limit",
                                 bomlib.DEFAULT_SINGLE_SOURCE_LIMIT))
    # Clear the limit, do not graze it: one line of headroom so the control still
    # trips the next time somebody raises the threshold by one.
    wanted = int(math.floor(limit)) + 2

    by_basis: dict[str, list[tuple[int, dict]]] = {"manufacturer": [], "supplier": []}
    for i, line in enumerate(bomlib.lines(doc)):
        count, basis, _names = bomlib.source_breadth(line)
        if count > 1 or line.get("alternate_qualified"):
            by_basis[basis].append((i, line))

    # Manufacturer-recorded lines FIRST, and on this pack's baseline that is all of
    # them: those lines keep both distributors, so the only thing that can make the
    # gate fail is counting factories rather than boxes. A control that also
    # stripped a supplier list would still fire if manufacturer counting silently
    # regressed to distributor counting, which is the defect this fixture exists to
    # keep out. Supplier-only lines are used as filler when a project does not
    # record enough manufacturers to reach the limit.
    picked = (by_basis["manufacturer"] + by_basis["supplier"])[:wanted]
    if len(picked) < wanted:
        raise AssertionError(
            f"single_source_limit is {limit:g}, so {wanted} line(s) must lose their "
            f"second source before bom.single_source can move, and only {len(picked)} "
            f"line(s) in the baseline have one to lose")

    refs = []
    for i, line in picked:
        count, basis, names = bomlib.source_breadth(line)
        if basis == "manufacturer":
            if count > 1:                       # a line qualified against two factories
                line["manufacturer"] = names[0]
                line.pop("manufacturers", None)
            refs.append(f"{bomlib.ref(line, i)} (one factory, "
                        f"{len(bomlib.sources_of(line))} distributors left in place)")
        else:
            vendor = str(line.get("vendor") or "").strip() or names[0]
            line["vendor"] = vendor
            line["sources"] = [vendor]
            refs.append(f"{bomlib.ref(line, i)} (down to one supplier)")
        line["alternate_qualified"] = False
        line.pop("single_source_accepted", None)
        line.pop("acceptance_note", None)
    return _note(sealed, doc,
                 f"{'; '.join(refs)} — second source gone, nothing written down")
