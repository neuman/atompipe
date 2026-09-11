# Kernel tolerance healing

Tier 3. Read this when a boolean "just worked" after failing, when a model has been
through many revisions, or when a part passes every check in this pack and still
does not fit.

---

## The mechanism

A solid modelling kernel does not store exact geometry. It stores surfaces, curves
and vertices, each carrying a **tolerance** — the distance within which two entities
are considered coincident. Modelling operations are performed within that budget.

When a boolean is asked to join two faces that do not quite meet — they miss by a
micron because of an accumulated transform, a trimmed surface, an imported body, or
forty revisions of edits — the kernel has two options. It can fail, or it can widen
the tolerance of the vertices and edges involved until the entities touch, and then
proceed.

Almost every kernel takes the second option, because the first one produces support
tickets. The result is a body that is:

- **valid** — it passes the kernel's own check;
- **watertight** — it exports a closed mesh;
- **geometrically wrong** — a face is up to the healed tolerance away from where the
  design says it is, and the error is invisible in every view.

The heal is recorded, usually in a check-geometry report or an entity property that
nobody opens.

## Why this matters more than it sounds

The healed distance is small. The problem is not its size — it is what it *hides*.

A face that had to be pulled 0.02 mm to meet its neighbour was 0.02 mm from where
it should have been, and something upstream put it there: a wrong offset, a
mis-parented sketch, a transform applied twice, a stale imported body. The heal
converts a **design error** into a **valid body**, and the validation pipeline then
certifies the body. The upstream error survives into the next revision, where it
gets another heal, slightly larger.

Two symptoms of a design that has been healing quietly for a while:

1. Booleans that fail intermittently, then succeed after an unrelated edit. The
   model is operating at the edge of its tolerance budget; small changes push it
   either side.
2. A part that measures correctly in CAD and does not fit the part it was designed
   against. The two were healed in opposite directions.

## Gate the budget, not the outcome

The rule is simple and it is the reason this file exists:

> **A healthy part sits orders of magnitude below the kernel's tolerance limit. A
> part that needs the limit has an error healed into it.**

So do not check "did the operation succeed". Check the tolerance the entities
actually carry, and compare it to the kernel's default — not to its maximum.

A workable acceptance, in the shape this system wants:

- **Quantity:** maximum entity tolerance in the body.
- **Limit:** the kernel's *default* tolerance (typically around 1e-6 of the model
  scale), with perhaps one order of magnitude of headroom.
- **Fail:** anything approaching the kernel's *maximum* (often 1e-2 of model scale)
  — that is not a tolerance, it is a repair.
- **Evidence:** the list of healed entities and their tolerances, so the next reader
  can go and find what put each one there.

Record the numbers with provenance, like any other constant: which kernel, which
version, which default, and what the part measured. "It passed" is not a record.

## What to do with a healed body

1. **Find the upstream cause.** The heal is a symptom. Something is in the wrong
   place by roughly the healed distance, and that distance is a clue to which
   operation put it there.
2. **Do not export from a healed body and call it validated.** The mesh will be
   watertight and every gate in this pack will pass it. This pack cannot see a heal;
   the mesh has no memory of one.
3. **Rebuild rather than repair** where the feature tree allows it. A repaired body
   carries its healed tolerances forward into every subsequent operation.
4. **Re-run the whole sweep after any rebuild.** A tolerance change moves every
   measurement downstream of it, which is exactly what STALE means.

## Relationship to the mesh gates

`cad-solid` works on tessellated output. It sits *downstream* of everything on this
page, and it inherits the kernel's answer without being able to question it.

That is the honest boundary of this pack: it proves the mesh is a solid and that the
solids do not share material. It cannot prove the solids are in the right places, and
a healed body is precisely a body whose geometry is wrong in a way that leaves no
trace in the mesh. If the model has been through many revisions or imports foreign
bodies, that check has to happen in the CAD system, and it has to happen before
anyone trusts a green sweep here.
