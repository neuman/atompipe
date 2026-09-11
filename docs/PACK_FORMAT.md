# Pack format

A **pack** teaches an agent one physical or manufacturing domain: how to generate
artifacts for it, how to validate claims in it, what the real-world constraints are,
and how to attack a design from its point of view.

Packs are the plugin layer. They are ordinary directories — no build step, no
registration, no central authority. Drop one in and it is found.

## Layout

```
packs/<name>/
  pack.json          # tier 1 — the manifest. ~20 words. Always affordable to read.
  PACK.md            # tier 2 — ~150 lines. Loaded when the domain is relevant.
  references/*.md    # tier 3 — loaded only for the specific task at hand.
  gates/*.py         # validators. Each declares a negative control.
  generators/*.py    # model -> domain artifact (optional)
  lenses.md          # adversarial review dimensions for this domain
  sourcing.md        # real-world procurement and process constraints (optional)
  scaffold/          # starter model + claims for a new project in this domain (optional)
  selftest/          # baseline.json + the known-bad fixtures gates must fail on
```

## Three-tier progressive disclosure

This is the central design constraint, and everything else follows from it. **An
agent must be able to know about forty packs while loading two.**

| Tier | File | Size | When it enters context |
|---|---|---|---|
| 1 | `pack.json` | ~20 words | always — this is how packs are discovered and matched to gaps |
| 2 | `PACK.md` | ~150 lines | when the agent is working in this domain |
| 3 | `references/*.md` | whatever it takes | only for the specific task at hand |

`atompipe packs list` reads **only** tier 1 and never imports Python. If your
manifest's `description` needs three sentences, the pack is doing too much — split
it.

Tier 3 is where the depth goes. A CFD pack's `references/meshing.md` can be nine
hundred lines; it costs nothing until an agent is actually meshing.

## `pack.json`

```json
{
  "name": "fdm-print",
  "version": "0.1.0",
  "description": "Validates that a solid is printable on a filament machine: bed fit, wall thickness, overhang, bridging.",
  "settles": ["bed fit", "wall thickness", "overhang angle", "bridge span", "print time"],
  "claim_classes": ["manufacturability", "fdm", "additive"],
  "provides_gates": ["fdm.bed_fit", "fdm.wall_thickness", "fdm.overhang", "fdm.bridges"],
  "provides_generators": [],
  "requires_tools": [],
  "requires_python": ["trimesh", "numpy"],
  "max_tier": 1,
  "lenses": ["printability", "part orientation", "assembly order", "material"],
  "licence": "Apache-2.0",
  "origin": "extracted from a production FDM project"
}
```

`settles` is the **matching vocabulary**. When `atompipe gap` finds a claim with no
gate, it scores every manifest's `settles` and `claim_classes` against the claim's
quantity to suggest candidates. Write the phrases a person would actually use for
the quantity, not your internal gate names.

`origin` matters. Say where the pack came from — extracted from a real project,
built by the extension protocol, ported from a paper. It tells the next reader how
much to trust it.

## `PACK.md`

Tier 2. Roughly 150 lines. Cover, in this order:

1. **What this pack settles** — the claims it can close, in plain language.
2. **What it cannot settle** — the adjacent things people will assume it covers and
   it does not. This section prevents more damage than the first one.
3. **Gates**, each with its tier, what it measures, its threshold source, and the
   known-bad fixture it fails on.
4. **Units and frames.** State them explicitly. Unit confusion is the most common
   cross-pack defect and it is entirely preventable.
5. **The physics in one paragraph** — enough that an agent can tell whether a result
   is absurd.
6. **Common failure modes** in this domain, and what they look like in a verdict.
7. **Where to look next** — which `references/` file covers what.

Write it for an agent that is competent but has never used this domain's tooling.

## Gates

```python
from atompipe.gates import gate, GateContext
from atompipe.models import Verdict, Tier, NegativeControl

@gate(
    id="fdm.overhang",
    title="Unsupported overhangs within the printable angle",
    claims=["manufacturability", "fdm"],       # claim ids OR claim TAGS
    tier=Tier.BUILD,
    settles="overhang angle",
    requires_python=["trimesh", "numpy"],
    negative_control=NegativeControl(
        fixture="selftest/steep_cone.py",
        note="a 70-degree cone: every face past the 50-degree limit, nothing else wrong",
    ),
)
def overhang(ctx: GateContext) -> Verdict:
    ...
    return Verdict(gate="fdm.overhang", passed=worst <= limit,
                   measured=worst, limit=limit, units="deg",
                   detail=f"worst face {worst:.1f}deg vs {limit}deg limit ({n} faces past)",
                   evidence=[report_path])
```

Rules, all enforced:

- **`negative_control` is mandatory.** The registry raises without it. A gate that
  cannot demonstrate failure is a logger — see rule 5 in `METHOD.md`.
- **Declare `requires_*` honestly.** A gate whose tool is missing reports SKIPPED and
  its claim goes BLOCKED, visibly. Silently degrading is how a report starts lying.
- **Declare the real tier.** A fifteen-minute gate is tier 2, however much you wish
  otherwise. Miscategorising it breaks everyone's inner loop.
- **One dense line in `detail`.** Bulk output goes to `ctx.out_dir` and is cited in
  `evidence`. A verdict is one line of context; a sweep of forty gates must stay
  readable.
- **Tag bindings are a two-sided contract, and the CLAIM side is where it goes
  wrong.** A gate's `claims` list is the set of vocabularies its result is relevant
  *evidence* for, so `beam.deflection` listing `["structural", "stiffness",
  "deflection"]` is correct: a sagging beam genuinely bears on a claim about
  structural adequacy. The mistake is on the claim side — tagging a narrow
  assertion with a broad vocabulary. A claim that says "root stress stays under
  half of yield" tagged `structural` gets covered by every structural gate in
  every installed pack, so a deflection failure makes a *stress* claim read FAIL
  and the reader goes hunting in the wrong place.

  So: **gates list everything they bear on; claims carry the narrowest vocabulary
  that describes what they actually assert.** Say so in `PACK.md` and give the
  vocabulary explicitly, because a pack that publishes its tag names is a pack
  whose claims can be written correctly by someone who has never read its code.

  The one gate that *should* bind broadly and narrowly at once is a **validity
  guard** — a slenderness check protecting beam theory, a Biot check protecting
  lumped capacitance, a Reynolds check protecting a correlation. When one of those
  trips, every other number in the domain really is untrustworthy, so dragging the
  whole domain down is the correct behaviour. Ship one; it is usually the most
  valuable gate in the pack.
- **Ship at least one tier-0 gate.** A pack of only expensive gates has not finished
  its job.

## Negative controls

The fixture must be bad **in the specific way the gate claims to detect**. Change one
physically meaningful thing, in the direction the gate cares about — a mesh with one
face deleted, a part scaled past the bed, a beam at a quarter of its section depth,
a matrix with the diodes removed.

A fixture that is bad in some *other* way (corrupt file, empty mesh) proves the gate
handles garbage, not that it measures what it claims.

Fixtures live in `selftest/` and expose `make(ctx)` returning either a new
`GateContext` or a dict merged into `ctx.extra`. Reference them as
`selftest/<file>.py` or `module:function`.

### Fixtures must be SEALED

A fixture states **everything its gate reads**. It never layers its known-bad
values over the host project's projection.

This looks like an over-precaution and is not. The overriding form —
`{**ctx.params, **known_bad}` — wins on every key it names, so it reads as safe.
But gates resolve synonym families and derived quantities, so a key the fixture
never mentions can still arrive from the project and neutralise the control.

It was observed live while building these packs. A hull fixture raised the centre
of gravity to make a boat unstable. The host project happened to state a
waterplane inertia — a perfectly honest thing to state, and better than the pack's
own rectangular fallback. That one key replaced the inertia the fixture's severity
had been computed against, the metacentric height came out at **+4.33 m**, and the
gate **passed its own known-bad fixture**. Six more controls in the same pack had
the identical hole, each defusable by a different innocuous project value.

> **A control whose severity depends on the host project's numbers is a control
> that passes in some repositories and fails in others. That is the same as having
> none — and worse, because it looks like having one.**

So:

```python
def top_heavy(ctx):
    """fluid.metacentric — the same hull with its mass raised above the metacentre."""
    return dataclasses.replace(ctx, params={**_baseline(), "kg_m": 0.62})
    #                                       ^^^^^^^^^^^ the PACK's baseline,
    #                                       never ctx.params
```

Mesh fixtures need the same discipline: returning a bare `{"meshes": ...}` merges
only into `ctx.extra` and leaves the gate reading its *threshold* from the host
project. A wall gate handed a quarter-thickness plate and no minimum-wall figure
does not fail — it **skips**, and a skip is not a control.

`tests/test_packs.py::ControlsAreSealed` enforces this by running every control
against an empty projection as well as the baseline: a sealed fixture behaves
identically, an inheriting one skips or flips.

Project-local fixtures are exempt. A fixture in your own repo deriving from your
own model is correct — it keeps the control one change away from *this* design.
The rule is for packs, which ship to strangers.

### `selftest/baseline.json` — required

A single JSON object: a plausible, physically coherent projection for this domain,
carrying **every key any gate in the pack reads**, describing a design that **every
gate passes**.

It exists because a gate with no parameters to read SKIPS, and a skipped control
never fires — so the gate ships unproven while the suite reads green. That is the
precise failure this project exists to prevent, and it has already happened here
once: a gate declared a negative-control fixture that was never written, and nobody
noticed because the gate was skipping for a missing dependency.

The baseline is also the pack's teaching example. Include a `_description` naming
the object and a `_notes` map of key → one line on what it is and its unit; an agent
that reads the baseline should be able to write a model this pack can gate, without
reading any of its code.

CI asserts three things: every gate passes the baseline, every control fires against
it, and nothing skips.

`atompipe gate selftest` runs every control and **fails any gate that passes its own
known-bad input**.

## `lenses.md`

The adversarial review dimensions for this domain — the angles a reviewer should
attack from before anything gets built. One heading each, a few pointed questions
under it. Rule 8 of the method lives here.

Good lenses are specific and uncomfortable: *"the part is loaded at its tip and its
root is a cantilever — what is the free span, really, and did you measure it from
the weld or from the wish?"*

## `sourcing.md`

The real-world constraints that are not physics: vendor process rules, minimum order
quantities, lead times, finishes that are mandatory for a given contact type, stock
volatility, tiers that force a different assembly line, materials that are quietly
unavailable in your region.

This is the knowledge that makes a design orderable rather than merely correct, and
it is almost never in a datasheet.

## Validation

```
atompipe pack validate <name>
```

checks that the manifest parses and matches its directory, `PACK.md` exists and is
substantive, every declared gate actually registers, every gate has a negative
control, `max_tier` matches the gates, the description is one line, and every
file-based fixture exists.

CI runs this plus `atompipe gate selftest` over every pack. **A pack whose gates have
never demonstrated failure does not get merged.**

## Contributing back

```
atompipe pack new <name>        # scaffold
atompipe pack validate <name>   # what CI will run
atompipe pack export <name>     # PR-ready, with selftest evidence attached
```

A pack built inside a user's project is exportable as a standalone directory with no
edits. That is the contribution loop: someone builds an RC boat, the agent follows
the extension protocol to grow a CFD gate, and the pack comes back for the next
person who needs one.
