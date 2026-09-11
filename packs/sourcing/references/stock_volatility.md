# Stock volatility, qualification cost, and reserving the riskiest line

Short note, one idea: **stock matters in proportion to what the alternate would cost
you**, and that cost is almost never the unit price.

## Two kinds of part

A **fungible** part — a common passive, a standard fastener, a generic connector —
can vanish from one warehouse and be replaced the same afternoon from another, or
by a different manufacturer's equivalent. Its stock figure is worth watching the
week you order and forgetting the rest of the time.

A **qualified** part is one whose replacement costs work: a calibrated sensing
element, a certified radio module, a specific display whose driver you wrote, a
motor whose curve your control loop was tuned against. Swapping it means a new
footprint, or new firmware constants, or a re-test, or a re-certification — weeks of
somebody's time, on a critical path, with a risk of finding a second problem.

The stock number looks identical for both. The consequence of it going to zero
differs by two orders of magnitude.

## Why the qualified part is the volatile one

It is usually the part with the smallest number of manufacturers, the longest
factory lead, the narrowest customer base and the least warehouse depth. One other
customer's production order can empty it. And its long factory lead — the number
that looks harmless while stock covers you — is exactly the number you inherit the
moment it does not.

That is the trap: a line reading *18,000 in stock, 26-week factory lead* is the
single most dangerous line in a BOM, and it reads as the safest, because the
effective lead time is zero right up until it is twenty-six weeks.

## The habit: reserve the riskiest line first

Before anything else in the build is committed — before tooling, before the boards,
before the enclosure — put the highest-qualification-cost line on order or on
backorder.

Reasons it is worth the awkwardness of spending money early:

- **A backorder holds queue position.** If the factory lead arrives anyway, you are
  at the front of it rather than joining behind the people who ordered when you
  were still deciding.
- **It converts an unknown into a date.** A confirmed ship date is a schedule input;
  a stock figure is a photograph.
- **It fails cheaply.** Finding out now that the part is on allocation costs a
  purchase order and a conversation. Finding out after tooling costs the tooling.
- **It is the only line where "buy spares" is obviously correct.** Spares of a
  fungible part are clutter; spares of a qualified part are schedule insurance, and
  the right quantity is "enough to finish the build plus the units you will break
  during bring-up".

## Recording it

In the BOM, the fields that carry this judgement are `stock`, `lead_time_weeks`,
`sources`, `alternate_qualified`, and — for anything sole-sourced —
`single_source_accepted` with an `acceptance_note` that states the re-qualification
cost **in weeks**. `bom.single_source` fails until that note exists, which is the
point: the gate is not asking you to find a second vendor, it is asking you to
decide, in writing, and to say what the decision would cost if it goes wrong.

Also record the **date** each stock and lead-time figure was captured. When the BOM
changes, the ledger marks the claims stale — which is the honest outcome, because a
stock figure from six weeks ago has not been checked, whatever it says.
