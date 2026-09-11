# Lead time, for real

The quoted lead time is the vendor's best case for a customer who does everything
right. It is not a schedule, and it is not a promise. This note is about turning it
into a date you can defend.

## What a lead time is measured from

Almost never from when you asked. Usually from **receipt of a clean order**, which
in practice means after: the specification is frozen, the drawing revision is
agreed, the deposit has cleared, the first-article has been approved, and any
customer-supplied material has arrived. Each of those is a queue of its own and
each one is usually yours to clear.

Ask, in these words: *"What has to be true before the clock starts?"*

## Queue plus work

Most shops quote the sum of their backlog and your job. When a shop is four weeks
deep, a two-week job is six weeks away, and next month it is a different number
with the same drawing. This is why two quotes from the same shop, two months apart,
disagree while both are honest.

The consequence: lead time is the *least* stable number in a BOM. Re-record it
before you schedule against it, not when you first found the part.

## The stack that makes a real date

```
   your approvals + deposit            days to weeks, and it is yours to lose
 + vendor queue                        moves weekly, ask for it separately
 + manufacturing                       the number most people think is "the lead time"
 + inspection / first article          days, plus your own review time
 + freight and customs                 days to weeks; customs is not predictable
 + receiving, incoming inspection      a day you will forget to budget
 = the date you can actually build on
```

Then take the **longest** such stack across the whole BOM. The build ships when the
last part arrives. Averaging lead times produces a comforting number that describes
nothing.

## Stock does not mean instant

A part covered by distributor stock has an effective lead time of zero *while the
stock exists and is yours*. Until you place the order, it is somebody else's. For
anything with a long factory lead behind a healthy stock figure, the stock is the
only thing between you and that factory lead — see `stock_volatility.md`.

## What actually moves a lead time

- **Queue position.** The cheapest acceleration there is: ask when the next slot is
  and whether committing today takes it.
- **Approvals you are holding.** Frequently the largest single term and always the
  one under your control.
- **Expedite fees.** Real, sometimes worth it, and they buy queue position rather
  than physics. A two-week cure or a plating cycle does not expedite.
- **Splitting the order.** A partial shipment that unblocks a pilot build while the
  balance follows is often free to ask for and rarely offered.
- **Relaxing a spec.** A tolerance that forces a secondary operation, or a finish
  that goes to an outside plater, can be the entire difference between four weeks
  and eleven.

## Scheduling habits that survive contact

- **Schedule against the longest line, and name it.** Everyone on the project
  should be able to say which part sets the date.
- **Order the long-lead items first, before the design is finished around them.**
  This is uncomfortable and it is usually right: the parts with 20-week leads are
  rarely the ones still moving.
- **Re-check the top three lines weekly** while a design is open. Nothing else.
- **Record the date each lead time was captured.** A lead time without a date on it
  is a rumour, and it will be quoted back to you in a meeting six weeks later.
- **Do not average, do not round down, do not use "typical".** Quote the number the
  vendor said, in weeks, and attribute it.
- **Assume a re-quote if you change anything**, including quantity. Especially
  quantity.
