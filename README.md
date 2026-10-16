# nopekit

<p align="center">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/img/nopey.png">
  <img src="docs/img/nopey-transparent.png" width="300" alt="Nopey the honey badger, nopekit's mascot">
</picture>
</p>

**Have an idea for a real thing? Let's find out what holds up.**

Nopekit is a Claude Code plugin for exploring and engineering physical designs with an AI agent. Tell it what you want to make. It helps you work out what the design needs to do, explore possible approaches, build and run checks, and keep track of what the evidence actually says as the design changes.

It's based on the [Grounding by Falsification](grounding_by_falsification.pdf) approach. AI has gotten very good at making believable proposals for all sorts of things both digital and physical but it is especially good at coding. The problem is that it's still not great at figuring out which proposals are actually good on its own. Grounding by falsification is the idea that we need to wrap AI with something outside itself that can check its work and say "nope" using trusted reasoning/math/physics/etc. Nopekit turns that approach into an extensible framework with room for plugins that can falsify proposals across any domain but especially physical design work.

You don't need to learn a new engineering framework before you start. Install the plugin, open a conversation, and bring your idea. The agent will work through the process with you.

<p align="center">
<img src="docs/img/site-example.png" width="900" alt="Nopekit project site showing a 3D-printed drone design and the grounding map that connects design choices to claims and checks">
</p>

*An example project site. It shows the design, the current candidate, the claims that matter, and how those claims connect to the choices and checks behind them.*

> **Early preview:** Nopekit is currently most useful for small physical-design projects: 3D printing, simple mechanics, beams, heat, fluids, and parts lists. Windows is untested. The plugin and its interfaces are still evolving.

## Get started

### 1. Install Nopekit in Claude Code

If you're already using Claude Code, start by asking it:

> Install the Nopekit plugin from `https://github.com/neuman/nopekit` and help me get it ready to use.

Or install it directly with Claude Code's plugin commands:

```text
/plugin marketplace add neuman/nopekit
/plugin install nopekit
```

You'll need Python 3.10 or newer available as `python3`. Nopekit's core has no third-party Python dependencies. Some checks need optional tools or packages; the agent should tell you when one is needed. For mesh checks used in 3D printing and solid-part work, install:

```sh
pip install trimesh numpy
```

### 2. Start a project

Open Claude Code in an empty directory and start with a prompt like this:

```text
I want to use Nopekit to design something new. Interview me about the idea, one question at a time. Help me turn what I want into requirements, explore possible designs, set up the project and its checks, and launch the project site so I can understand the design and follow its progress.
```

Then have a conversation. You can bring a rough idea, a half-finished project, a sketch, or a folder of existing files. You don't need to arrive with a complete specification.

### 3. Follow the work in the project site

As the project takes shape, Nopekit starts a local site for the project. Open the URL Claude Code gives you. The site is the human-readable surface of the project's **grounded design state**: it helps you see what you're trying to build, what alternatives are in play, which candidate is current, and why that candidate is or isn't ready.

Keep talking with the agent, question its conclusions, change your mind, and try alternatives. The design and its evidence evolve together.

---

## What Nopekit is for

AI can generate design ideas quickly. The hard part is finding out which ones survive contact with reality—and keeping track of what you learned when the design changes.

Nopekit helps you explore a **space of possible designs**, not just produce one plausible-looking answer. It records the requirements, the choices and parameters that shape the design, the claims that need to hold, the checks used to evaluate those claims, and the evidence those checks produce. When an input changes, choices and results that depended on it can become stale so the agent knows to reexamine them.

## A concrete example: PETGasus

[PETGasus](https://neuman.github.io/PETGasusDrone/) is a useful example of the kind of iterative design process Nopekit is meant to support. Its [project repository](https://github.com/neuman/petgasusdrone) shows the work behind a 3D-printed drone design.

The point isn't just to get a model that looks right. A design has to fit its requirements; its parts and parameters affect one another; and checks can reveal that a candidate fails, that an assumption needs attention, or that more evidence is needed. As the design changes, the reasons for the current choices should remain understandable.

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
| `nopekit gap --propose` | Lists unresolved claims and proposes available ways to evaluate them. |
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

## If something isn't working

- **The agent can't find Nopekit or its instructions:** check that the plugin is installed in Claude Code and start a new session if needed.
- **A check is skipped:** read the reason. It may need an optional Python package or external tool; install it only if you want to run that check.
- **A result is stale:** a dependency changed after the check ran. Re-run the relevant checks rather than treating the old result as current.
- **The design looks ready, but the report says otherwise:** follow the unresolved claims. A gap, assumption, or physical-only claim is information—not a bug to hide.
- **You're not sure where to start:** run `nopekit doctor`, or ask Claude Code to explain the current readiness report in plain language.

## More detail

- [The method](METHOD.md) — the principles Nopekit encodes.
- [Site contract](docs/SITE_CONTRACT.md) — how the project site represents the recorded state.
- [Origins](docs/ORIGINS.md) — the real project that informed the method.
- [Pack format](docs/PACK_FORMAT.md) — how domain-specific gates and capabilities are packaged.
- [Extension protocol](docs/EXTENSION_PROTOCOL.md) — how the system can grow new capabilities.
- [Grounding by falsification paper](grounding_by_falsification.pdf) — optional background on the underlying idea.

## Status and license

Nopekit is an early project. The core engine and bundled packs work, but interfaces may change and the range of supported checks is still growing. Use it, inspect it, fork it, and tell us what breaks.

Licensed under the [Apache License 2.0](LICENSE).
