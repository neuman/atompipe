# nopekit

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/nopey.png">
  <img src="docs/img/nopey-transparent.png" width="300" alt="Nopey the honey badger, nopekit's mascot">
</picture>
</p>

**Have an idea for a real thing? Let's find out what holds up.**

Nopekit is a plugin for Claude Code, Codex and Cursor for exploring and engineering physical designs with an AI agent. Tell it what you want to make. It helps you work out what the design needs to do, explore possible approaches, build and run checks, and keep track of what the evidence actually says as the design changes.

It's based on the [Grounding by Falsification](https://github.com/neuman/nopekit/blob/main/grounding_by_falsification.pdf) approach. AI has gotten very good at making believable proposals for all sorts of things both digital and physical but it is especially good at coding. The problem is that it's still not great at figuring out which proposals are actually good on its own. Grounding by falsification is the idea that we need to wrap AI with something outside itself that can check its work and say "nope" using trusted reasoning/math/physics/etc. Nopekit turns that approach into an extensible framework with room for plugins that can falsify proposals across any domain but especially physical design work.  

You don't need to learn a new engineering framework before you start. Install the plugin, open a conversation, and bring your idea. The agent will work through the process with you.

## See it in action

<p align="center">
<img src="docs/img/site-example.png" width="900" alt="Nopekit project site showing a 3D-printed drone design and the grounding map that connects design choices to claims and checks">
</p>

*The project site connects the design, its requirements, the current candidate, and the checks and evidence behind it.*

[PETGasus live site](https://neuman.github.io/PETGasusDrone/) · [PETGasus repository](https://github.com/neuman/petgasusdrone)

## Get started

### 1. Install Nopekit

Nopekit is one plugin for three agents: the repository root holds a manifest for each
(`.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`), and they share the same skills
and the same end-of-turn hook, which records each round.

**Claude Code.** Ask it:

> Install the Nopekit plugin from `https://github.com/neuman/nopekit` and help me get it ready to use.

Or install it directly with Claude Code's plugin commands:

```text
/plugin marketplace add neuman/nopekit
/plugin install nopekit
```

**Codex.** Codex reads the same marketplace:

```bash
codex plugin marketplace add neuman/nopekit
codex plugin add nopekit@nopekit
```

Codex runs a plugin's hook only after you review and trust it, and asks again after
every update of the plugin. Until you do, rounds are not recorded at the end of a turn;
`nopekit round --commit` records one by hand.

**Cursor.** Clone the plugin into Cursor's local plugins, then restart Cursor:

```bash
git clone --depth 1 https://github.com/neuman/nopekit ~/.cursor/plugins/local/nopekit
```

To update, `git -C ~/.cursor/plugins/local/nopekit pull` and restart. Cursor can also
import the Claude Code plugin; install it one way, not both, or each turn ends with two
rounds.

You'll need Python 3.10 or newer available as `python3`. Nopekit's core has no third-party Python dependencies. Some checks need optional tools or packages; the agent should tell you when one is needed. For mesh checks used in 3D printing and solid-part work, install:

```sh
pip install trimesh numpy
```

### 2. Start a project

Open your agent (Claude Code, Codex or Cursor) in an empty directory and start with a prompt like this:

```text
I want to use Nopekit to design something new. Interview me about the idea, one question at a time. Help me turn what I want into requirements, explore possible designs, set up the project and its checks, and launch the project site so I can understand the design and follow its progress.
```

Then have a conversation. You can bring a rough idea, a half-finished project, a sketch, or a folder of existing files. You don't need to arrive with a complete specification.

### 3. Follow the work in the project site

As the project takes shape, Nopekit starts a local site for the project. Open the URL the agent gives you. The site is the human-readable surface of the project's **grounded design state**: it helps you see what you're trying to build, what alternatives are in play, which candidate is current, and why that candidate is or isn't ready.

Keep talking with the agent, question its conclusions, change your mind, and try alternatives. The design and its evidence evolve together.

---

## Proposers and falsifiers

**Something proposes a candidate. Independent checks try to reject it.**

Every Nopekit project has two kinds of work in it, and Nopekit keeps them apart.

- A **proposer** makes or changes a candidate design. Most of the time the proposer is the agent itself, editing the project's model. It can also be a tool, such as an autorouter, an optimizer or a parts search. A proposal settles nothing: its output is an input that the checks then judge.
- A **falsifier** tries to reject that candidate against something outside the proposer: a physical law, a textbook formula, a fabricator's limit, or an established tool's own verdict. Nopekit calls a falsifier a **gate**. A gate must first fail a known-bad input before its passes count.

Nothing that draws a candidate is allowed to judge it. The relationship is many-to-many. One proposer's output usually meets falsifiers from several domains at once, and one falsifier judges every candidate that reaches it, however that candidate was made.

```mermaid
flowchart LR
    subgraph P["Proposers: make a candidate"]
        agent["The agent edits the model<br/>(every project)"]
        topo["Topology optimizer<br/>(PETGasus's own pack)"]
        route["pcb.autoroute<br/>(built in: pcb-kicad)"]
        parts["Parts search<br/>(illustrative, not shipped)"]
    end
    subgraph C["Candidates"]
        part["Printed part"]
        board["Routed board"]
        bom["Assembly and its<br/>bill of materials"]
        heat["Heat and flow system"]
    end
    subgraph F["Falsifiers: try to reject it (built in)"]
        fdm["fdm-print"]
        cad["cad-solid"]
        beam["beam-analytic"]
        pcb["pcb-kicad"]
        src["sourcing"]
        thermo["thermal-analytic, fluids-analytic,<br/>cfd-openfoam, openmodelica"]
    end
    agent --> part & board & bom & heat
    topo --> part
    route --> board
    parts -.-> bom
    part --> fdm & cad & beam
    board --> pcb
    bom --> src & cad
    heat --> thermo
```

*Solid arrows are things that exist today. The dashed arrow is an illustration. `pcb.autoroute` is the only proposer a built-in pack ships. The topology optimizer lives in the PETGasus repository, not in Nopekit.*

| Proposer | What it does | Where it comes from |
|---|---|---|
| The agent, editing the model | The default proposer in every project. Each change it keeps is recorded as a decision, with the options that lost and why they lost. | Nopekit: the plugin's skill and `nopekit decide` |
| `pcb.autoroute` | Routes a KiCad board with Freerouting and proposes the routed copy. | Built in: the `pcb-kicad` pack |
| `fea.topopt3d` | A 3D topology optimizer (SIMP) that proposes where a frame's material goes. | A project's own pack (`solid-fea`, in the [PETGasus repository](https://github.com/neuman/petgasusdrone)). Not part of Nopekit. |
| A parts search, a thermal sizer, a hull fairer | Illustrations of proposers that a pack could add. | Not shipped. The [pack format](docs/PACK_FORMAT.md#proposers) says how to add one. |

Run a proposer with `nopekit propose <id>`. Each file it writes becomes an input record marked with the proposer that made it. Adopting that input as the design is a decision.

### A worked example: a topology-optimized frame that has to print

[PETGasus](https://neuman.github.io/PETGasusDrone/) is a small quadcopter whose frame is printed in one piece. A topology optimizer proposes where the plastic goes. The model draws that field as a printable surface. Then falsifiers from two built-in packs, and from the project's own gates, try to reject the drawn frame.

<p align="center">
<img src="docs/img/combos/topology-field-proposal.png" width="700" alt="The topology optimizer's density field for the PETGasus frame, seen from above and from the side; darker cells hold more plastic">
</p>

*The proposal: the optimizer's density field, from above and from the side. Darker means more plastic. By itself it settles nothing.*

<p align="center">
<img src="docs/img/packs/fdm-print-printed-frame.png" width="900" alt="The PETGasus frame as drawn from the density field: a 17 g PETG frame shown from above, below, the top and the side">
</p>

*The candidate that the falsifiers judge: the frame as the model draws it from that field, 17 g of PETG.*

| Falsifier | What it tries to catch | Basis | From |
|---|---|---|---|
| `fdm.min_wall` | A section thinner than three printed lines | model-only | `fdm-print` |
| `fdm.bridge_span`, `fdm.overhang` | Spans and steep faces that the printer cannot make without support | model-only | `fdm-print` |
| `fdm.bed_fit`, `fdm.print_time_est` | A frame too big for the bed, or too slow to print in one sitting | model-only | `fdm-print` |
| `cad.is_volume`, `cad.watertight`, `cad.degenerate_faces` | A mesh that is not a closed solid, so that no other number about it means anything | 1 established (trimesh), 2 model-only | `cad-solid` |
| `cad.wall_thickness` | The thinnest wall, found by casting rays inward | model-only | `cad-solid` |
| `petgasus.frame_mode`, `petgasus.crash_drop`, `petgasus.crash_wall` | A frame that resonates near the motors' speed, or breaks in a 1 m drop or a 3 m/s wall hit. CalculiX judges the drawn shape, never the optimizer's own score. | established, sourced | the project's own gates |
| `petgasus.topology_current` | A frame drawn from a field that was solved for a different problem | model-only | the project's own gate |

**What the falsifiers rejected.** The project's decision records keep each rejected option with its reason, from 2026-10-07 to 2026-10-18:

- **Print the optimizer's field directly.** Its spokes were 0.75 mm blades. The 1.6 mm minimum-member clean-up deleted them and cut the motor seats loose. The first vibration mode fell to 7 Hz, against a 200 Hz limit.
- **Cut the field at its midpoint.** The frame fell into 9 separate pieces, against the claim that it prints as one connected piece.
- **Draw the field with a 0.7 mm blur.** It erased thin limbs. CalculiX found the drawn motor seat at 1.25 N/mm, where the optimizer's own model said 15.3. The optimizer's number was not evidence for the part.
- **Open the surface at 0.6 mm.** It left walls of 1.14 to 1.25 mm, under the 1.26 mm minimum of three 0.42 mm lines.
- **Let thin walls grow freely over the propellers.** The frame's shadow on a propeller went from 14.8 % to 15.06 %, over its 15 % limit.

One rejection shows what a pass does not establish. One field filled the layer over each guard hoop, and the drawn hoops stood 4.8 mm tall against a 4 mm limit. The guard-height gate passed that frame, because it read the height from the parameters instead of the printed shape. The gate now measures the bands as printed. A pass establishes only what its gate actually measures.

<p align="center">
<img src="docs/img/combos/site-board-printability.png" width="500" alt="One board of the PETGasus project site: the printability claim C6 reads failing, the mesh claim C7 and the topology-field claim C17 read checked, and the support-removal claim P6 reads pending build">
</p>

*How the results appear on the PETGasus site, as built on 2026-10-18. The printability claim (C6) reads Failing, because `fdm.bridge_span` found a 1.8 mm ceiling with nothing to bridge from. The mesh claim (C7) and the topology-field claim (C17) read Checked. Whether the supports come off by hand (P6) waits on a real print.*

Nopekit does not ship a topology optimizer or a finite-element solver. The optimizer and the CalculiX gates are in PETGasus's own `solid-fea` pack. The built-in falsifiers in this example are `fdm-print` and `cad-solid`. `beam-analytic` is not used here: it reads a span, a section and a load, not a mesh, and its pack says it cannot judge non-prismatic members.

### Combinations the built-in packs support

Each combination below uses only gates that ship with Nopekit. Each proposer is marked **built in**, **project** or **illustrative**. An illustrative proposer is not shipped by any built-in pack: today the agent does that job by editing the model, or a project adds its own.

#### A printed part that carries load

**Proposer:** the agent's parametric model (built in), or an optimizer as above (project).

`IMAGE TBD: beam-analytic — a beam-like printed member, such as a bracket arm, with its load, span and deflection marked`

| Falsifier | What it tries to catch | Basis |
|---|---|---|
| `fdm.min_wall`, `fdm.overhang`, `fdm.bridge_span`, `fdm.bed_fit` | Geometry that the printer cannot make | model-only |
| `fdm.layer_alignment` | A main load carried across the layer bonds, the weak direction of a print | model-only |
| `cad.is_volume`, `cad.watertight` | A mesh that is not a closed solid | established, model-only |
| `cad.clash`, `cad.assembly_connected` | A part that shares material with a neighbour, or that nothing holds | model-only |
| `beam.model_validity` | A shape for which beam theory does not hold: too short for its depth, or with too much shear deflection left out | sourced |
| `beam.bending_stress`, `beam.deflection`, `beam.buckling` | A beam-like member that bends, sags or buckles past its limit | sourced |

`fdm-print` judges the mesh in print orientation. `beam-analytic` judges numbers from the model. Neither says anything about dimensional accuracy, warp or fatigue: each pack's `PACK.md` lists what it cannot settle.

#### A circuit board that must fit its case

**Proposer:** `pcb.autoroute` (built in). The router's board is an input. Adopting it is a decision, and then the same gates judge it as they judge a board routed by hand.

<p align="center">
<img src="docs/img/packs/pcb-kicad-routed-board.png" width="360" alt="KiCad render of a routed keyboard PCB: dome-switch contact pads and their copper traces">
<img src="docs/img/packs/cad-solid-exploded-assembly.png" width="420" alt="Exploded CAD assembly of a two-grip phone keyboard: shells, PCBs, rubber key pads, springs and lids stacked above the base">
</p>

*A routed board, and the assembly that it must fit inside.*

| Falsifier | What it tries to catch | Basis |
|---|---|---|
| `pcb.drc` | Copper that breaks the board's design rules, at every severity | established (KiCad) |
| `pcb.unconnected` | A connection that the router left open | established (KiCad) |
| `pcb.parity` | A board that no longer matches its schematic | established (KiCad) |
| `pcb.erc` | Schematic wiring faults: an open pin, an undriven power input | established (KiCad) |
| `pcb.net_width` | A track too narrow for its current (IPC-2221 heating) | sourced |
| `pcb.fab_rules` | A feature under the fabricator's published limits | sourced |
| `pcb.enclosure_fit` | A populated board that collides with its enclosure, or a part without its clearance | established (KiCad, CadQuery) |

A clean DRC does not say the circuit is right. A wrong pin map or a missing pull-up is legal copper, and the `pcb-kicad` pack lists those limits.

#### A heat system with flow in it

**Proposer:** illustrative. Today the agent sizes the collector, the insulation or the pipe run in the model, or writes an OpenModelica system model as the candidate.

<p align="center">
<img src="docs/img/packs/thermal-analytic-solar-charging.png" width="560" alt="Two weeks of clear-sky solar irradiance and the cumulative salt it charges in a solar thermochemical heat-storage model">
<img src="docs/img/packs/openmodelica-simulation-result.png" width="560" alt="OpenModelica simulation of a solar Stirling system over 24 hours: heat flows, and the vessel-to-cylinder temperature difference against its 10 °C minimum">
</p>

<p align="center">
<img src="docs/img/packs/cfd-openfoam.png" width="900" alt="Oil flow in a channel 10 mm high, as OpenFOAM solved it, in two coloured strips. The speed is low at the walls and high at the middle. The static pressure decreases from the inlet to the outlet. Two lines across each strip are the planes between which the pressure drop is measured">
</p>

*The pictures that `cfd-openfoam` puts on the site beside a pressure-drop claim, here from the pack's baseline: the speed and the static pressure that OpenFOAM solved on the finest mesh, drawn by ParaView. Each cell shows its own value. Magenta shows a value above the scale: at the corners of the inlet, the pressure is above the top of the scale.*

| Falsifier | What it tries to catch | Basis |
|---|---|---|
| `thermal.conduction`, `thermal.convection`, `thermal.steady_state_temp` | A part that runs hotter than its limit | sourced |
| `thermal.time_constant` | A lumped-capacitance answer where lumped capacitance does not hold | sourced |
| `solar.irradiance`, `solar.collector_output`, `solar.stagnation` | A collector that delivers too little heat, or overheats when the flow stops | sourced |
| `fluid.flow_regime`, `fluid.pipe_pressure_drop` | A loop whose pressure drop is more than the head available, or a correlation used outside its range | sourced |
| `cfd.regime`, `cfd.converged`, `cfd.mesh_independence`, `cfd.pressure_drop` | The same pressure drop from an OpenFOAM run, which counts only when the run is laminar, converged and mesh-independent | sourced, established (ESI OpenFOAM v2606) |
| `modelica.simulates`, `modelica.mirror_agrees` | A system model that does not run, or that disagrees with an independent implementation | established, model-only |

Two methods can judge one quantity: the analytic pipe pressure drop and the OpenFOAM one. Each has limits. `thermal-analytic` cannot see the flow field, and `cfd-openfoam` runs only laminar flow at one temperature, so neither one judges heated flow in a duct.

#### A hull that floats and prints

**Proposer:** illustrative. Today the agent models the hull and splits it into printable segments.

<p align="center">
<img src="docs/img/packs/fluids-analytic-boat-hull.png" width="600" alt="CAD render of a 3D-printed RC boat hull in three segments, each with its own cross-wall">
</p>

| Falsifier | What it tries to catch | Basis |
|---|---|---|
| `fluid.buoyancy`, `fluid.freeboard` | A hull that sinks, or sits too low when loaded | sourced |
| `fluid.metacentric`, `fluid.righting_arm` | A hull that rolls over instead of righting itself | sourced |
| `fluid.drag` | Drag at speed above the thrust available | sourced |
| `fdm.bed_fit` | A segment too big for the printer's bed | model-only |
| `cad.watertight`, `cad.is_volume` | A segment that is not a closed solid | model-only, established |

Every `fluids-analytic` gate is hydrostatic. Planing, waves and the free surface of water inside the hull are outside it.

#### An assembly you can buy

**Proposer:** illustrative. Today the agent chooses the parts. The pack format uses a parts search as its example of a proposer, but no built-in pack ships one.

<p align="center">
<img src="docs/img/combos/site-cost-against-budget.png" width="800" alt="The cost section of the PETGasus site: the parts as a stacked bar against a 150 dollar budget line, necessary parts 156 dollars, all parts 167 dollars">
</p>

*The PETGasus site, as built on 2026-10-18. `bom.cost` read 167.15 USD against the 150 USD budget, so the budget claim reads Failing.*

| Falsifier | What it tries to catch | Basis |
|---|---|---|
| `cad.clash`, `cad.assembly_connected` | Parts that overlap, or a part that nothing holds | model-only |
| `bom.complete`, `bom.availability` | A line that cannot be ordered, or that has no ship date | model-only |
| `bom.cost`, `bom.currency` | A build over budget, or a total that adds two currencies with no rate | model-only |
| `bom.moq`, `bom.single_source` | Minimum orders that buy a second build, or a part that only one vendor sells | model-only |
| `bom.process_rules` | A design outside the vendor's stated capabilities | sourced |

`sourcing` checks the arithmetic on the bill of materials you give it. It cannot see whether a price is real, or whether a part is the right part.

### How much a check is worth

Every falsifier above names its **basis**: `established` (an existing tool's own answer), `sourced` (a cited formula, standard or datasheet) or `model-only` (logic the AI wrote, with no outside source). A gate that fails its known-bad input has shown that it *can* fail. That does not show that its logic is correct or complete. A pass establishes what that gate measures, on the candidate it measured, and no more. [Packs and how far to trust them](#packs-and-how-far-to-trust-them) has the details, with every gate.

### The nine built-in packs

| Pack | The question it asks |
|---|---|
| `beam-analytic` | Can this beam carry the load? |
| `cad-solid` | Is it a real solid? Do the parts fit together? |
| `cfd-openfoam` | Is the pressure drop under its limit, and was the run sound enough to say so? |
| `fdm-print` | Can I print this part as designed? |
| `fluids-analytic` | Will it float, stay stable, and move as intended? |
| `openmodelica` | Does the model compile, balance, and produce the expected results? |
| `pcb-kicad` | Does the board agree with the schematic, and can it be manufactured? |
| `sourcing` | Can you actually buy the parts within budget? |
| `thermal-analytic` | Will it get too hot? How much heat can it move? |

---

## What Nopekit is for

AI can generate design ideas quickly. The hard part is finding out which ones survive contact with reality—and keeping track of what you learned when the design changes.

Nopekit helps you explore a **space of possible designs**, not just produce one plausible-looking answer. It records the requirements, the choices and parameters that shape the design, the claims that need to hold, the checks used to evaluate those claims, and the evidence those checks produce. When an input changes, choices and results that depended on it can become stale so the agent knows to reexamine them.

The [worked example above](#a-worked-example-a-topology-optimized-frame-that-has-to-print) shows this on a real design. The point is not a model that looks right. A design has to fit its requirements. Its parts and parameters affect one another. Checks can reveal that a candidate fails, that an assumption needs attention, or that more evidence is needed. As the design changes, the reasons for the current choices should stay understandable.

That is the goal of Nopekit: to help the human and agent work through design, evaluation, and evidence together, rather than treating a generated artifact as the end of the job.

## How the pieces fit together

A Nopekit project connects what you want to make with the evidence needed to judge whether a candidate is ready.

```mermaid
flowchart LR
    A[Your idea and requirements] --> B[Claims: what must be true]
    B --> C[Design choices and parameters]
    C --> D[Gates: checks that can fail]
    D --> E[Evidence and current verdicts]
    E --> F[Grounded design state]
    F --> G[Project site: a human-readable view]
    G -. questions, decisions, new ideas .-> A
    G -. changes to try .-> C
```

The real project is interconnected: one choice can affect several values, claims, and checks, and one claim can depend on several choices. The diagram above is just a simplified way to orient yourself.

- **Requirements** capture what you asked for, in your own terms.
- **Claims** describe things that must be true for the design to meet those requirements.
- **Parameters and decisions** describe the choices that shape the candidate, including why a value was chosen and what alternatives were rejected.
- **Gates** are executable checks that evaluate claims. A gate must show that it can fail on a known-bad input before its result can count as qualified evidence.
- **Evidence and verdicts** record what happened when a gate ran, what inputs it used, and whether that result still applies to the current design.
- **The grounded design state** is the connected record of the design, its alternatives, dependencies, checks, and evidence.
- **The project site** is where that state becomes understandable to a person. It presents the project's intent, tradespace, current candidate, and the reasons it is or isn't ready. It doesn't replace the underlying evidence or decide that a design is true; it renders the project's recorded state so you and the agent can reason about it.

## Using Nopekit, step by step

You don't have to manually run every step. Claude Code and Nopekit work through the cycle with you; this section explains what you're likely to see and how to make sense of it.

### 1. Start with the thing you want to make

Describe the goal in everyday language. It helps to say what the thing is for, where it will be used, what it needs to fit, what it must survive, and what matters most to you. You can add details later.

The agent may ask for supporting material: sketches, photos, measurements, existing parts, links, datasheets, or examples of something similar. Share what you have; gaps can be made explicit rather than filled with invented certainty.

### 2. Turn the idea into requirements and claims

The agent helps turn your answers into requirements, then identifies claims that need to hold for a design to work. Review the requirements when it asks. Correct misunderstandings early: the goal is to preserve your intent, not to make the project fit the first interpretation the model came up with.

Some claims can be checked analytically. Others need a simulation, an external tool, a human judgment, or a physical build. Nopekit should keep those differences visible.

### 3. Explore candidates and record decisions

The agent works with you to develop the model and explore alternatives. The project should preserve not just the current choice, but useful context about why it was chosen and what was rejected. That helps a future iteration avoid repeating the same dead ends—and makes it easier to revisit an old option when its assumptions change.

You can still change your mind. The goal isn't to lock you into an early decision; it's to make the consequences of a change easier to see.

### 4. Run checks and read the results

A check, or **gate**, evaluates a specific claim against the current inputs. Results are recorded with their provenance. A result may be useful without being a pass: it can reveal a failure, expose a missing capability, or show that an earlier result is now stale.

Here are the important distinctions:

| Status | What it means |
|---|---|
| **Checked** | A qualified gate passed on the inputs that apply to the current candidate. This is evidence for the claim the gate tests—not a guarantee that the whole product works. |
| **Failing** | A gate found a problem with the current candidate. Use the detail to decide what to change or investigate. |
| **Gap** | No suitable qualified gate currently settles the claim. The claim remains unresolved. |
| **Open** | A gate exists, but hasn't produced a current result for the inputs. |
| **Stale** | A gate passed earlier, but something it depended on has changed. The old result doesn't establish the claim for the current candidate. |
| **Skipped** | The gate was skipped, often because a required tool or dependency is missing. Nothing was established by that run. |
| **Skipped (errored)** | The gate crashed. Treat the result as unresolved, not as a pass. |
| **Pending build / physical** | The claim needs evidence from building or testing the real thing. Software checks cannot substitute for that evidence. |
| **Assumed** | The project is relying on something that has not yet been established by a qualifying check. |

The key habit is to ask: **What exactly does this result establish, and what does it leave open?** A clean CAD check isn't proof that a physical part will behave as intended. A simulation result isn't a real-world measurement. A claim with no check isn't checked just because the design looks plausible.

### 5. Use the site to reason about the design

The site isn't just a progress dashboard or a picture of the model. It's a way to inspect the relationships inside the grounded design state.

Depending on the project and the views it provides, use it to:

- understand the project's intent and requirements;
- explore the available design choices and how they connect;
- inspect the current candidate and its representation;
- trace a claim through the values and choices it depends on to the gate that evaluates it;
- see why the candidate is ready, not ready, or ready only in a limited sense;
- spot failures, missing checks, stale results, and assumptions that need attention.

The site renders the recorded state; it doesn't independently verify the design. If a number or claim looks wrong, follow it back to the underlying record or evidence and work with the agent to correct it.

### 6. Iterate

The process loops. A failed check may change a parameter. A new requirement may bring an old alternative back into consideration. A physical test may contradict a simulation. A new tool may make a previously unresolved claim testable.

After a meaningful change, the agent can re-run the checks affected by that change and update the project's recorded state and site. Keep asking questions and redirecting the work: the point is to make the engineering reasoning visible enough that you can participate in it.

## Useful commands

Most people can begin through conversation with Claude Code. If you want to inspect or operate the project directly, these commands are a useful starting point.

| Command | What it does |
|---|---|
| `nopekit status` | Summarizes the current claims and their statuses. |
| `nopekit check` | Runs the available gates against the current project. |
| `nopekit report` | Shows the readiness report. Use `--write` to write `REPORT.md`. |
| `nopekit why <name>` | Shows the history for a parameter, claim, or requirement, including recorded alternatives. |
| `nopekit gap --propose` | Lists claims whose mechanism—the gate, test, or judgment that settles them—has yet to run, and proposes packs that might run it. |
| `nopekit gate selftest` | Runs the gates' negative controls to check that they can fail on known-bad inputs. |
| `nopekit doctor` | Helps diagnose a confusing or broken setup. |
| `nopekit round` | Ends a round of work with a quick check, an updated site, and a round record. |
| `nopekit site build` | Builds the project's site from the recorded state and verdicts. It does not run gates. |
| `nopekit site serve --watch --detach` | Serves the local site and watches for project changes. |
| `nopekit site serve --stop` | Stops the detached site server. |

To see the complete command list and options, run:

```sh
nopekit --help
```

### Try the included example

The repository includes a small bracket project you can inspect without starting from scratch. From the Nopekit repository:

```sh
cd examples/bracket
nopekit status
nopekit check
nopekit gate selftest
nopekit why thickness
```

The example includes a deliberately failing check. That's intentional: a useful example should show you what a failure looks like, not just produce a reassuring green screen.

## Packs and how far to trust them

A **pack** adds checks for one domain. Nopekit ships nine. A pack can hold two kinds of tool:

- **Gates** (falsifiers) evaluate a claim and can say "nope". Every bundled gate is **qualified**: it passes a known-good input and fails a known-bad one, and CI re-runs both controls on every change, so a gate that cannot fail does not ship. A gate from anywhere else, such as one the agent writes for your project, must also fail each time one of its inputs is pushed past its limit.
- **Proposers** suggest options or evidence, such as a parts search or a slicer's estimate. A proposal settles nothing; it becomes an input that a gate can then check. `pcb-kicad` ships one, `pcb.autoroute` (Freerouting); its routed board is checked by the same DRC gates as any other. The [pack format](docs/PACK_FORMAT.md#proposers) describes how to add one.

Qualified means a gate *can* fail. It does not say how far to trust its logic. For that, each gate declares its **basis**: where its logic comes from.

| Basis | Where the logic comes from | How far to trust it |
|---|---|---|
| `established` | An existing, non-AI tool's own answer, such as trimesh's volume check or OpenModelica's `checkModel`. | As far as you trust that tool. |
| `sourced` | A cited outside source: a textbook formula, a standard or a datasheet. Each pack's `references/` names it. | As far as you trust the source, and inside the range the gate says the source applies to. |
| `model-only` | Written by the AI with no outside source, even when it calls a tool's functions. | Least. Its controls show it can fail, not that its arithmetic is right. Read it before you rely on it. |

The basis is shown by `nopekit gate list`, `nopekit gate show <id>`, the report and the site. It never changes a claim's status: a Checked claim is Checked whatever the basis of its gate, so look at the basis when you decide how much a pass is worth. A gate that needs a tool you have not installed is Skipped, never passed.

| Pack | What it covers | Gates | Basis | Needs |
|---|---|---|---|---|
| `beam-analytic` | Closed-form beam checks with zero dependencies: deflection, bending and shear stress, buckling, bearing, a slenderness guard on the theory itself, and a unit/sign guard on the projection. | 8 | 7 sourced, 1 model-only | nothing |
| `cad-solid` | Validates that exported solids are real solids, that placed parts do not interfere, and that every part is held by something: watertightness, validity, clash, contact coverage, envelope, wall. | 7 | 1 established, 6 model-only | trimesh, numpy |
| `cfd-openfoam` | Runs a laminar OpenFOAM case (ESI v2606) behind guards: case readable, laminar regime, checkMesh, convergence, mesh independence by GCI, then the pressure drop. | 6 | 3 established, 2 sourced, 1 model-only | ESI OpenFOAM v2606 (`openfoam2606`) for four gates; ParaView 6.2.0 (`pvbatch62`) for the pictures on the site only |
| `fdm-print` | Validates that a part is printable on a filament machine: bed fit with brim, wall thickness, overhang, bridge span, layer-direction loading and print time. | 7 | 7 model-only | trimesh, numpy (mesh gates) |
| `fluids-analytic` | Closed-form hydrostatics, stability, drag and pipe flow: the analytic answer for boats, floats, ducts and piping, before anyone installs a CFD solver. | 7 | 7 sourced | nothing |
| `openmodelica` | Validates a Modelica model and the runs recorded from it: parameter units, claim/variable drift, result validity, extracted values, mirror agreement, and equation balance under omc. | 8 | 4 established, 4 model-only | OpenModelica (`omc`) for its three solver gates |
| `pcb-kicad` | Checks a KiCad board and its schematic: DRC, ERC, schematic parity, connectivity, pin names, IPC-2221 trace heating, a fab's limits, ngspice measurements, and fit in its enclosure. | 10 | 6 established, 3 sourced, 1 model-only | KiCad 9 (`kicad-cli`) for six gates, ngspice for one, CadQuery for the fit |
| `sourcing` | Checks a project's BOM offline: every line orderable and priced in one convertible currency, rolled-up cost vs budget, lead times, MOQ overbuy, vendor process rules, single-source risk. | 7 | 1 sourced, 6 model-only | nothing |
| `thermal-analytic` | Closed-form heat transfer and solar: conduction networks, convection correlations, radiation, fins, steady-state and lumped transient temperature, flat-plate collectors, clear-sky irradiance. | 10 | 9 sourced, 1 model-only | nothing |

<details>
<summary><code>beam-analytic</code>: 8 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `beam.bearing` | Fastener hole bearing stress within the design allowable | sourced |
| `beam.bending_stress` | Extreme-fibre bending stress within the design allowable | sourced |
| `beam.buckling` | Axial compression against the critical buckling load | sourced |
| `beam.deflection` | Deflection under load, against an absolute limit | sourced |
| `beam.deflection_ratio` | Deflection as a span fraction (L/180, L/360 style serviceability) | sourced |
| `beam.input_sanity` | The projection is in this pack's units and sign convention | model-only |
| `beam.model_validity` | Euler-Bernoulli beam theory is applicable to this geometry | sourced |
| `beam.shear_stress` | Transverse shear stress within the design allowable | sourced |

</details>

<details>
<summary><code>cad-solid</code>: 7 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `cad.assembly_connected` | Every part is held by something, and every declared contact still closed (needs trimesh, numpy) | model-only |
| `cad.bounding` | Bounding box, volume and centre of mass within their stated limits | model-only |
| `cad.clash` | No unintended interference between placed solids (needs trimesh, numpy) | model-only |
| `cad.degenerate_faces` | No duplicate vertices and no zero-area triangles (needs trimesh, numpy) | model-only |
| `cad.is_volume` | Every solid is a volume: closed, consistently wound, positive volume (needs trimesh, numpy) | established |
| `cad.wall_thickness` | Thinnest wall found by inward ray casting, against the minimum (needs trimesh, numpy) | model-only |
| `cad.watertight` | Every solid is closed: no open edges, no non-manifold edges (needs trimesh, numpy) | model-only |

</details>

<details>
<summary><code>cfd-openfoam</code>: 6 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `cfd.case_readable` | The OpenFOAM case is one this pack can run and vouch for | model-only |
| `cfd.converged` | simpleFoam met the pack's residual targets, and the pressure drop settled (needs OpenFOAM) | established |
| `cfd.mesh_independence` | Three meshes agree: the grid convergence index (Celik et al. 2008) is inside its limit (needs OpenFOAM) | sourced |
| `cfd.mesh_quality` | checkMesh finds the case's mesh sound, inside stated limits (needs OpenFOAM) | established |
| `cfd.pressure_drop` | The static pressure drop between two planes, with its GCI band, is under the limit (needs OpenFOAM) | established |
| `cfd.regime` | The flow is laminar and incompressible: Reynolds and Mach numbers | sourced |

</details>

<details>
<summary><code>fdm-print</code>: 7 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `fdm.bed_fit` | Part fits the build volume once the brim is on it | model-only |
| `fdm.bridge_span` | Unsupported horizontal spans within the bridgeable maximum (needs trimesh, numpy) | model-only |
| `fdm.layer_alignment` | Primary load is not carried across the layer bonds | model-only |
| `fdm.min_wall` | Thinnest section carries at least three perimeters | model-only |
| `fdm.overhang` | Unsupported faces within the printable overhang angle (needs trimesh, numpy) | model-only |
| `fdm.print_time_est` | Estimated print time within the project's ceiling | model-only |
| `fdm.process_model_valid` | The process model this pack assumes actually applies | model-only |

</details>

<details>
<summary><code>fluids-analytic</code>: 7 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `fluid.buoyancy` | Displaced mass exceeds total mass, with reserve buoyancy left over | sourced |
| `fluid.drag` | Drag force at speed, against the available thrust budget | sourced |
| `fluid.flow_regime` | Every correlation in this pack is being used inside its Reynolds range | sourced |
| `fluid.freeboard` | Freeboard remaining at the loaded waterline | sourced |
| `fluid.metacentric` | Initial metacentric height GM is positive with a usable margin | sourced |
| `fluid.pipe_pressure_drop` | Pressure drop along the line, major plus minor, against the head available | sourced |
| `fluid.righting_arm` | Righting arm GZ at the stated heel meets the demand on it | sourced |

</details>

<details>
<summary><code>openmodelica</code>: 8 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `modelica.checks` | checkModel reports a balanced system: equations == unknowns (needs omc) | established |
| `modelica.claims_addressable` | Every Modelica variable a claim names still exists in the model or the result | model-only |
| `modelica.compiles` | buildModel produces an executable with no errors (needs omc) | established |
| `modelica.mirror_agrees` | The Modelica result and an independent implementation still agree | model-only |
| `modelica.result_claim` | A variable reduced out of the result meets its claim's acceptance | established |
| `modelica.simulates` | simulate() runs to stopTime, fires no assert, and writes a result (needs omc) | established |
| `modelica.solution_valid` | The recorded run finished, stayed finite, and produced the variables claimed | model-only |
| `modelica.source_hygiene` | Every parameter declaration carries a description, and a physical one a unit | model-only |

</details>

<details>
<summary><code>pcb-kicad</code>: 10 gates, 1 proposer</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `pcb.board_readable` | The board is a KiCad file this pack's reader knows | model-only |
| `pcb.drc` | KiCad's design rule check finds nothing, at every severity (needs kicad-cli) | established |
| `pcb.enclosure_fit` | The populated board fits its enclosure: nothing collides, every part keeps its clearance (needs kicad-cli, cadquery) | established |
| `pcb.erc` | KiCad's electrical rules check finds nothing in the schematic, at every severity (needs kicad-cli) | established |
| `pcb.fab_rules` | The board stays inside its fab's published limits (needs kicad-cli) | sourced |
| `pcb.net_width` | Every track of each current-carrying net stays inside its heating limit | sourced |
| `pcb.parity` | The board and its schematic agree: every part, value, footprint and net (needs kicad-cli) | established |
| `pcb.pin_names` | Pins the library gives one name carry one net | sourced |
| `pcb.spice` | A measurement ngspice makes on the project's circuit deck stays inside its limits (needs ngspice) | established |
| `pcb.unconnected` | Every connection the netlist asks for is made in copper (needs kicad-cli) | established |
| `pcb.autoroute` (proposer) | Routes the board with Freerouting and proposes the routed copy; settles nothing (needs pcbnew, Java, the Freerouting jar) | established |

</details>

<details>
<summary><code>sourcing</code>: 7 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `bom.availability` | Every line has a known ship date, and nothing is dead | model-only |
| `bom.complete` | Every BOM line can actually be ordered | model-only |
| `bom.cost` | Rolled-up build cost within budget | model-only |
| `bom.currency` | Every price is in a currency the roll-up can convert | model-only |
| `bom.moq` | Minimum order quantities not buying a second build | model-only |
| `bom.process_rules` | Design inside the vendor's stated capability set | sourced |
| `bom.single_source` | Single-source risk counted, not felt | model-only |

</details>

<details>
<summary><code>thermal-analytic</code>: 10 gates</summary>

| Gate | What it checks | Basis |
|---|---|---|
| `solar.collector_output` | Hottel-Whillier useful heat from a flat-plate collector | sourced |
| `solar.irradiance` | Clear-sky plane-of-array irradiance from site, date, hour and orientation | sourced |
| `solar.stagnation` | Absorber temperature with no flow and full sun, against what the loop survives | sourced |
| `thermal.conduction` | Wall-stack U-value from a series/parallel resistance network | sourced |
| `thermal.convection` | Convective coefficient from a Nusselt correlation, with its regime | sourced |
| `thermal.fin_efficiency` | Fin effectiveness, including the case where the fin makes it worse | sourced |
| `thermal.h_agreement` | The h handed to the lumped gates is the h this pack's correlation computes | model-only |
| `thermal.radiation` | Net radiant exchange with emissivity and a view factor | sourced |
| `thermal.steady_state_temp` | Component temperature from power and the resistance network | sourced |
| `thermal.time_constant` | Lumped time constant, and whether lumped capacitance is legitimate at all | sourced |

</details>

## More detail

- [The method](METHOD.md) — the principles Nopekit encodes.
- [Site contract](docs/SITE_CONTRACT.md) — how the project site represents the recorded state.
- [Origins](docs/ORIGINS.md) — the real project that informed the method.
- [Pack format](docs/PACK_FORMAT.md) — how domain-specific gates and capabilities are packaged.
- [Extension protocol](docs/EXTENSION_PROTOCOL.md) — how the system can grow new capabilities.
- [Grounding by Falsification paper](https://github.com/neuman/nopekit/blob/main/grounding_by_falsification.pdf) — optional background on the underlying idea.

## Status and license

Nopekit is an early project. The core engine and bundled packs work, but interfaces may change and the range of supported checks is still growing. Use it, inspect it, fork it, and tell us what breaks.

Licensed under the [Apache License 2.0](LICENSE).
