# Reading a vendor quote

A quote is a number surrounded by the things it does not include. The number is the
part everyone reads and the part that changes least. Work this list against every
quote *before* comparing it to another one — two quotes are only comparable once
you know what each has left out.

## The price itself

- [ ] **At what quantity?** A unit price with no quantity attached is not a price.
      Ask for a price break table: 1 / 25 / 100 / 1,000, or whatever brackets your
      real run sits between.
- [ ] **Valid until when?** Days or weeks, usually. Past it, you are re-quoting.
- [ ] **In what currency, and who carries the movement** between quote and invoice?
- [ ] **What revision of the drawing / netlist / spec** is it quoted against? A
      quote against last month's files is a quote for last month's part.
- [ ] **What material, finish and tolerance** does the price assume? A quote is
      priced on a specific set of those, and yours may differ by a hair.

## The charges that are not in the unit price

- [ ] **Tooling** — moulds, dies, work-holding, jigs. One time? Per revision? And
      **who keeps it**, physically, when the job is done.
- [ ] **Setup / NRE per order** — stencils, line setup, machine setup, programming.
      Recurring charges disguised as one-time ones are the commonest surprise here.
- [ ] **First-article inspection** and the report that comes with it, and how many
      working days it adds before the run starts.
- [ ] **Test** — fixtures, functional test time, and what a failure costs you.
- [ ] **Minimum order value** for the vendor, separate from any line's MOQ.
- [ ] **Scrap / attrition allowance** on the assembly: who pays for the parts the
      machine eats, and at what percentage.
- [ ] **Packaging** — reels, trays, bags, ESD, kitting, labelling. Often quoted as
      free and delivered as loose parts in one bag.

## Getting it to your door

- [ ] **Incoterm.** Who arranges freight and who owns the goods when. Ex-works is
      a cheaper number and a longer to-do list.
- [ ] **Freight and insurance**, at the real weight and dimensions, not a guess.
- [ ] **Duty, tariff code, and brokerage.** Who is the importer of record?
- [ ] **Where does it actually ship from?** A domestic vendor with an overseas
      plant has an overseas lead time.

## Time

- [ ] **Lead time from what event?** Almost always from receipt of a *clean* order
      — meaning after approvals, after the deposit clears, after first-article
      sign-off. Ask which of those starts the clock.
- [ ] **Is the quoted lead time the queue or the work?** If the shop is four weeks
      deep, your two-week job takes six.
- [ ] **What holidays or shutdowns** fall inside the window.
- [ ] **What happens if you are late** returning an approval — does the slot go to
      someone else, and how far back does that put you?

## Terms

- [ ] **Payment terms**, and whether a deposit gates the start of the lead time.
- [ ] **Cancellation and change**: at what point does the order become
      non-cancellable, non-returnable? Custom parts usually go NCNR early.
- [ ] **Tolerance on quantity delivered** — some processes ship +/-10% and bill what
      they ship.
- [ ] **Who owns the data** you handed over, and what they may do with it.

## Two habits worth more than the list

**Read the exclusions out loud to another person.** Exclusions are written to be
skimmed, and they are always in the same place: a small paragraph under the price.

**Re-add every excluded item as a line or a charge in the BOM.** A quote you have
fully decoded produces a landed per-unit cost, and that number — not the quoted
unit price — is the one `bom.cost` should be checking against your budget. If a
number is genuinely unknown, leave the field null so the gate reports it as
unknown. Never enter a zero you are not sure of; a zero is a claim.
