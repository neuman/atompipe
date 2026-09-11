# atompipe

Take a sketch or a discussion to a physical thing you can actually build — with an
honest account of what has been verified and what has not.

atompipe is a Claude Code plugin and a small Python spine. It generalises a pipeline
that was proven on a real device before it was extracted — a physical product taken
from a napkin sketch to manufacturable outputs, working firmware and a published
readiness report, across dozens of revisions ([origins](docs/ORIGINS.md)).

It is domain-agnostic on purpose. The same spine drives an RC boat, a solar thermal
collector, a chemical process or a printed bracket, because the hard part is never
the domain. The hard part is knowing which parts of your design have actually been
checked.

```
claims  ->  gates  ->  packs  ->  readiness report
```

A **claim** is something that must be true for the design to work. A **gate** is an
executable that settles a claim *and is capable of failing*. A **pack** supplies gates
for one physical domain. The **readiness report** is the ledger rendered: what is
proven, what is not, and why.

## Install

**In Claude Code** — the repo is a plugin marketplace:

```
/plugin marketplace add neuman/atompipe
/plugin install atompipe
```

**Anywhere else** — the spine is **standard library only**, so there is nothing to
build and nothing to resolve:

```sh
pip install git+https://github.com/neuman/atompipe
# or just:
git clone https://github.com/neuman/atompipe && cd atompipe
PYTHONPATH=src python3 -m atompipe --help
```

Try it immediately on the reference project, which has zero dependencies:

```sh
cd examples/bracket
atompipe status         # 7 claims: 3 proven, 1 failing, 1 gap, 1 physical, 1 assumed
atompipe check          # 6 gates; one fails on purpose — fix `thickness` 7.0 -> 8.0
atompipe gate selftest  # every gate proves it can fail on known-bad input
atompipe why thickness  # one parameter's full history, including what was rejected
```

It ships with its claims and its ledger, because the ledger *is* a source of truth —
not a build artifact.

Nothing heavy installs until a claim needs it and you have said yes. The two packs
that want `trimesh` report their claims as **BLOCKED** — visibly — when it is absent,
rather than quietly skipping.

## What using it looks like

You describe a thing. atompipe asks for the evidence a design conversation never
produces on its own — sketches, a photo of the closest product you'd buy instead,
calipers on whatever it has to fit, datasheets for parts you have already chosen.
Then it extracts the claims:

```
C1  Floats with the full payload at <=60% draft          [measurable]
C2  Directionally stable at cruise (~4 m/s)              [measurable]
C3  Hull prints on a 220x220 bed without supports        [measurable]
C4  Runtime >=20 min at cruise on one pack               [measurable]
C5  Watertight at the hatch seam                         [physical only]
```

C5 cannot be validated by any tool. It stays UNVERIFIED, visibly, until you build one
and record a result. Everything else gets gated:

```
$ atompipe check
[ok  ] displacement  : 1.94 kg at 60% draft vs 1.2 kg payload
[ok  ] bed-fit       : 580 x 148 x 121 mm, splits into 2 parts
[FAIL] print-overhang: 14 faces past 52 deg on the bow flare
[skip] stability     : no gate installed for C2
```

That last line is the interesting one. A claim with no gate is a **capability gap**,
and it is how the system grows: the agent names the unvalidated quantity, tries the
analytic answer first, and only then proposes a solver — with the real cost said out
loud.

```
$ atompipe gap --propose
C2  directional stability at cruise        no gate

  (a) analytic  metacentric height from the waterplane. Runs now.
                Catches gross instability; misses planing and yaw at speed.
  (b) solver    OpenFOAM ~2 GB, ~20 min install, ~15 min/run.
```

When you take the solver, the agent installs it pinned, smoke-tests it, wraps it as a
gate, **proves the gate fails on a hull it should reject**, and offers to export the
whole thing as a pack so nobody has to do it again.

## Why you should believe the output

Because of what it refuses to claim. Every row in the PROVEN table cites the gate that
proved it and the evidence file it wrote. Everything else is listed as physical,
blocked, stale or assumed, with the reason.

Three statuses never blur into "pass":

- **skipped** — the gate did not run. Its tool is missing. Nothing was proven.
- **errored** — the gate crashed. Nothing was proven.
- **stale** — it passed, but inputs have changed since. Nothing is proven *now*.

And every gate must declare a **negative control**: known-bad input it has been shown
to fail on. The registry refuses to register a gate without one. This is not
bureaucracy — an agent that writes plausible code will write plausible validators,
and plausible validators are worse than none, because they launder assumption into
apparent proof.

## The method

Ten rules, in [`METHOD.md`](METHOD.md). The short version:

1. One parametric model is the only source of truth; everything else is generated.
2. Derive, never duplicate.
3. Every constant carries its provenance — especially the alternatives that lost.
4. Validators are gates, not loggers. *A logger is not a gate.*
5. Every gate needs a falsification control.
6. Check agreement across representations.
7. Wrap external solvers in converging loops.
8. Adversarial review moves the spec before anything is built.
9. Separate what is proven from what is assumed, in public.
10. Cheap inner loops, or there is no loop.

## Packs

| Pack | Gates | Needs | Settles |
|---|---|---|---|
| `beam-analytic` | 8 (8 tier-0) | none | tip deflection, mid-span deflection, deflection ratio, span over deflection limit, stiffness |
| `cad-solid` | 6 (1 tier-0) | trimesh, numpy | watertightness, solid validity, degenerate faces, duplicate vertices, part interference |
| `fdm-print` | 7 (5 tier-0) | trimesh, numpy | bed fit, bridge span, build volume, cantilever overhang, filament mass |
| `fluids-analytic` | 7 (7 tier-0) | none | buoyancy, displaced volume fraction, freeboard at load, reserve buoyancy, metacentric height |
| `sourcing` | 7 (7 tier-0) | none | bill of materials completeness, unpriced line, build cost per unit, rolled-up cost, budget |
| `thermal-analytic` | 10 (10 tier-0) | none | u-value, wall heat loss, insulation thickness, convective heat transfer coefficient, natural convection |

Packs are ordinary directories. No build step, no registration, no central authority
— drop one in and it is found. Three-tier disclosure keeps them cheap: a ~20-word
manifest is always in context, `PACK.md` loads when the domain is relevant, and
`references/` loads only for the task at hand.

See [`docs/PACK_FORMAT.md`](docs/PACK_FORMAT.md) to write one, and
[`docs/EXTENSION_PROTOCOL.md`](docs/EXTENSION_PROTOCOL.md) for how an agent grows a
capability that nobody prebaked.

## Commands

```
atompipe init                  atompipe status
atompipe ask                   what evidence to request from the human
atompipe ingest <files>        sketches, photos, CAD, datasheets, measurements
atompipe extract <artifact>    what was read out of it, and what that grounds
atompipe check [--tier N]      run gates; exits non-zero while anything critical blocks
atompipe gap [--propose]       claims with no gate, and packs that might cover them
atompipe why <param|claim>     one thing's full history, instead of the whole log
atompipe gate selftest         every negative control; fails any gate that can't fail
atompipe report [--write]      the readiness report
atompipe doctor                run this first when something is confusing
```

## Status

Early. The spine and the first extracted packs work; the interfaces will move. It is
Apache 2.0 — use it, fork it, or take the ten rules and ignore the code.

## Licence

Apache License 2.0. See [LICENSE](LICENSE).
