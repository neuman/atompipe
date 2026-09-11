# Adversarial lenses — sourcing

Five questions, asked before anything is ordered, while changing the answer is
still free. Method rule 8: review moves the spec before it is built. A sourcing
review that happens after the purchase order is a post-mortem.

Attack the BOM, not the person who wrote it. The BOM is confident by construction:
every line has a number in it, and a number looks like knowledge.

---

## 1. What is the single point of failure?

Not "are there risky parts" — **which one line ends the project**, and say its name
out loud.

- Which line has exactly one supplier? Which has exactly one *manufacturer* behind
  several suppliers? Two distributors for one factory is one source wearing a
  disguise. `bom.single_source` counts manufacturers wherever a line records one —
  but on a line that records none it can only count suppliers, and it says how many
  lines are in that state. Record `manufacturer` and `mpn` or the count flatters you.
- Which line, if it vanished tomorrow, costs the most to replace — not in unit
  price, but in *work*: a new footprint, a new calibration, a re-test, a document
  revision, a re-certification?
- Which vendor holds more than one critical line? A shop with your enclosure and
  your gasket is one fire away from both.
- Is the single point of failure a part at all? A sole tooling set, one person who
  knows the programming fixture, one bank account that can pay a deposit.

## 2. What happens at 10x quantity?

The BOM is a snapshot at one quantity and it hides that fact well.

- Which prices were captured at qty 1 and used at qty 1,000? Which were quoted at
  1,000 and are being used to plan a run of 25?
- What breaks at 10x: an MOQ that was slack becomes tight, a stock figure that
  covered you does not, a hand-assembly step that was fine at 25 is now three
  weeks of somebody's life.
- Which vendor was quoting a prototype price to win the production business, and
  what is the real one?
- At 10x, does any line cross into a different process, a different line, a
  different plant, or a different country? Those are new lead times and a new
  first-article, not a discount.
- And the reverse, which is the one people forget: what happens at **0.1x**? Most
  minimums and every tooling charge are brutal on the way down, and the second
  build is usually smaller than the first.

## 3. What if the riskiest part is gone in six weeks?

Pick the worst line from lens 1 and play it out, concretely.

- Is there a drop-in alternate, or an alternate that needs work? Name the work.
- **Who qualifies it, and when are they free?** An alternate nobody has time to
  test is not an alternate.
- How many units of buffer do you hold today, and how many weeks of build is that?
- Could you have bought the buffer before this conversation? The stock that
  disappears is always the stock you were about to order.
- If the answer is "we redesign", how long is that loop — and does the redesign
  touch anything already committed to tooling?

## 4. What is excluded from the quote?

A quote is a number surrounded by things it does not include.

- Tooling, fixtures, stencils, programming, first-article, test, setup per order.
- Freight, insurance, duty, brokerage, and who is the importer of record.
- What quantity is the price good at, and for how many days?
- What is the payment term, and does a deposit gate the start of the lead time?
- What is the tolerance/finish/material the price assumes, and what happens to it
  when yours differs by 0.02 mm?
- What is the vendor's minimum per order, and does it apply per line or per PO?
- See `references/quote_checklist.md`; run it against every quote before it is
  compared to another one.

## 5. Who qualifies the alternate — and who decides?

Second-sourcing is an engineering task with a name and a date, or it is a feeling.

- For each critical line, who signs that the alternate is equivalent, against what
  test, and how long does that test take?
- Is the alternate qualified *now*, or qualified in a document from the last
  revision of the design?
- Who is allowed to accept a single-source risk, and did they? An accepted risk
  with a written reason is a decision. The same risk unwritten is a surprise with
  a date on it.
- When the alternate is a different manufacturer, what else changes with it —
  firmware, calibration constants, a mechanical envelope, a certification mark?

---

## Before the money moves

- The riskiest line is reserved or on order before anything else is committed.
- Every claim this pack covers is PASS, not SKIP. A blocked gate before a spend is
  a spend on faith.
- Somebody has read the quote's exclusions out loud to somebody else.
- The longest lead time in the BOM is the date on the schedule. Not the average,
  not the typical, not the one you were hoping for.
