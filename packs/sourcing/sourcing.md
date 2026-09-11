# Real-world constraints that are not physics

The knowledge that makes a design orderable rather than merely correct. Almost none
of it is in a datasheet, and all of it is discovered late by default.

## Minimums are a shape, not a number

There are at least four, and a BOM that records only one of them will surprise you:
the **minimum order quantity** on the line, the **order multiple** (reel, sheet,
tray, bag) that rounds you up again, the **minimum order value** for the vendor,
and the **minimum billing quantity** a shop applies to a machine setup. A 250-piece
need against a 1,000-piece reel with a $75 vendor minimum is three separate
adjustments in the same direction.

## Non-recurring charges are the second price list

Tooling, work-holding fixtures, stencils, programming, first-article inspection,
test fixtures, setup per order. Each is small next to the run and enormous next to
the first twenty-five units, and none of them appears in a unit price. Ask which
are one-time-ever, which recur per order, and — for tooling — **who keeps it**. A
fixture you paid for and the shop keeps is a switching cost you bought yourself.

## A price has a quantity, a date and an expiry

Every quoted price assumes a quantity; most assume a validity window measured in
days or weeks; some assume a payment term. A price captured from a listing at qty 1
and pasted into a BOM for a run of 1,000 is not a cheaper part, it is a wrong
number in the pessimistic direction — and the optimistic version of the same error
(a 10,000-piece price on a 250-piece run) is the one that gets a project approved.

## Lifecycle is a countdown, not a label

`active` means nothing about next year. **NRND** (not recommended for new designs)
means the manufacturer has already decided; you are buying time. **Last-time-buy**
is a deadline with a quantity attached, and it is usually announced with less notice
than a redesign takes. **Allocation** means the factory is rationing, and your order
is behind bigger customers who signed earlier. **EOL** means re-source now, whatever
the stock page says.

## Stock is somebody else's, until it is yours

A stock figure is a photograph of a warehouse. Two things move it: other people's
orders, and the manufacturer's lead time refilling it. For a part with a long
*qualification* cost — a calibrated sensor, a certified module, anything whose
alternate needs re-testing — the stock number is the only thing standing between
the schedule and a three-week re-qualification. Reserve or backorder that line
before anything else in the build is committed. See
`references/stock_volatility.md`.

## Process capability is per-vendor, per-line, and dated

Two shops with the same machine list do not hold the same tolerances, and one shop
does not hold the same tolerance on every line in its building. A finish that a
given contact type requires, a tolerance that needs a secondary operation, a pitch
that moves the board to a different assembly line with its own queue and its own
first-article — these are quoted facts, not industry constants. Get them in writing
with the quote and record them as `process_rules` so the design is checked against
them on every edit instead of at the next RFQ.

## Region decides more than shipping

Material availability, certification marks, mains voltage and plug types, import
duty and its paperwork, the customs broker, and who is the importer of record. A
material that is a stock item on one continent can be a 14-week import on another
with identical drawings. Record the region the BOM assumes.

## Single source is a decision or a surprise

Plenty of good products ship with sole-sourced parts. The difference between a
robust project and a fragile one is not the count — it is whether somebody wrote
down that they know, what the alternate would cost to qualify, and who would do it.
Write the acceptance next to the line, with the number of weeks in it.

## Two distributors is not two sources

Second-sourcing means a second *manufacturer* whose part you have qualified. Two
distributors shipping the same factory's part is one source with better logistics —
useful against a warehouse fire, useless against an EOL notice, a price move or an
allocation. Record the manufacturer and the MPN, not only the vendor and the vendor
part number: `bom.single_source` counts factories where you wrote one down and is
reduced to counting boxes where you did not.

## The order minimum is a name, and names are typed by hand

A minimum order value is attached to a vendor by *spelling*. "Rowe Polymer",
"rowe polymer" and "Rowe Polymer Ltd" are one company and three keys, and the
failure is silent and cheap: the minimum lands on nobody, the roll-up is under by
that amount, and the total still looks like a total. Match on a normalised name,
and treat a minimum that lands on no line as a finding rather than a no-op — it is
either a typo or a vendor somebody forgot to buy from, and both need a human.

## The ship date is the longest lead time

Not the average, not the typical. The build ships when the last part arrives, and
that part is usually not the expensive one — it is the one nobody worried about,
because it cost forty cents.
