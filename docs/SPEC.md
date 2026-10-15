# nopekit: the architecture

Decided 2026-10-14, from an interview between the author and the agent, then
corrected the same day against the code (nine readers mapped every decision onto
`src/`, and the author answered what the mapping raised). This is the only plan. It
replaces `docs/PLAN.md`, `docs/PLAN-v0.14.md` and `docs/plan/`, retired at commit
`a00d0e5`; ids like `D-14`, `S-60`, `R-14` and `P2.5b` in code comments and contract
documents refer to that plan and resolve against git history at that commit.

Read it top to bottom once. Every decision has its reason beside it; a decision
without its reason should not survive a fresh context window. Section 8 lists the
details the agent decided during implementation, so the author can overturn any of
them in one place.

## 0. Settled by the author (2026-10-14)

1. **"Lenses" keeps its meaning.** The pack field `lenses` names the adversarial
   review prompts the agent uses to find claims it missed. The author's earlier
   "lenses" (a parts finder, a prior-art search, a generator) are **proposers**
   (decision 25). No rename.
2. **Return conditions are structured, with a text fallback.**
   `{"claim": "C1", "quantity": "margin" | "value" | "limit", "comparator": ">",
   "value": 0.02}` is evaluated by `check`. `{"text": "..."}` is shown and never
   evaluated, and reads as not machine-checkable.
3. **Round commits use an allow list.** The project's metadata lists its people.
   `nopekit round` commits only when git's configured identity is one of them;
   otherwise it warns and leaves the round uncommitted.
4. **Every proposer and evaluator declares its basis**: `established`, `sourced` or
   `model-only` (decision 38). The basis is shown; it changes no status and no
   qualification.
5. **The round record is written by `round` and `merge`, never by `check`**
   (decision 18). `check` keeps invariant 8 exactly as written. The live map still
   updates after every check, because `site serve --watch` rebuilds from the live
   resolution.
6. **Derivation is observed by perturbation** (decision 39): rebuild the model with
   each choice nudged, record what moved. Cached by the instructions' digest, run in
   the background at round end. It also gives amber: a pass that a ±10% error in an
   unconfirmed input would flip.
7. **Layout: the semantic work first.** Records move under `design/` (and
   `.nopekit/project.json` to `nopekit.json`) last, if budget remains. Project
   evaluators stay in `gates/` and `selftest/`, qualified against the project's own
   model; promoting one to a pack means writing a sealed baseline, not a move.
8. **METHOD.md may change in three places**: rule 9 (the representation comes first;
   the verdict sits in the map section right under it), section 0's chain
   (requirements come first; packs hold proposers and evaluators), and rule 1 (one
   set of instructions, whatever its layers, in place of one parametric model).
9. **People see the word "evaluator"** for anything that can settle a claim, on
   every human channel (CLI, report, site). "Proposer" and "falsifier" name the two
   kinds of pack contents in docs only; "gate" stays a code word (`GateSpec`,
   `gates/`).

Still open, not blocking: an electrical pack does not exist and the plugin
description promises PCBs; pack pins (decision 26) are deferred; records edited on
both sides of a candidate branch merge the ordinary git way.

## 1. What nopekit is

A system of record for a design's claims, the evaluators that have tested them, and
the history of both; plus packs that supply proposers and evaluators per domain;
plus renderers over the record. Five intentions, which are five interfaces to one
object:

1. Teach an agent the grounding-by-falsification method.
2. Give it a library of proposers and evaluators, extensible from other
   repositories, preferring established tools over LLM-built ones.
3. Interview the person, then iterate with them.
4. Keep the grounded design state in a form that reconstructs the same analysis and
   the same visualisation every time.
5. Build and keep a site that explains the state to the designer and to a newcomer.

The object is the grounded design state (paper §8): S = (T, F, L), the tradespace,
the falsification graph and the claim ledger. Everything else reads it or writes one
part of it.

## 2. Terms

| Term | Meaning |
|---|---|
| **choices** | the values a person or the agent picked: `spoke_count`, `arm_w`. In python, the model's `Config` fields. A value outside `Config` (a module table, a part number) is part of the instructions |
| **instructions** | how choices become the thing: the python, a parametric CAD file, a prompt, a Modelica model. Derived values (`duct_r_in = prop_r + tip_gap`) come from here |
| **outputs** | what the instructions produce: the mesh, the BOM, the build guide |
| **the design** | choices and instructions together. nopekit observes both; it owns neither |
| **record** | one fact in one file, read strictly, written by the agent or by a command |
| **verdict** | one evaluator's outcome on one set of inputs, keyed by the hash of what it read (ρ). Immutable |
| **resolution** | what the verdicts justify saying now: every claim's status, composed by the resolver. Computed live by every reader |
| **round record** | `.nopekit/round.json`: the resolution frozen at the end of a round, with the typed graph. Tracked. Written by `round` and `merge` only |
| **trace** | the observed derivation: which derived values move when each choice moves, and by how much. `.nopekit/trace/`, keyed by the instructions' digest |
| **grounded design state** | the checkout: records, the design, the verdict cache, the trace, the round record |
| **groundspace** | the sequence of states: the git history |
| **candidate** | a design that differs from HEAD by a set of choice overrides, with a disposition |
| **requirement** | what the person asked for, in their words. Ids `R1`, `R2`, ... |
| **claim** | a statement a mechanism can settle, derived from a requirement, with an acceptance condition |
| **mechanism** | what would settle a claim: how its evidence bottoms out, what would do it in words, and the evaluators the claim expects. Every claim names one |
| **evaluator** | anything that can settle a claim and has shown it can fail. The human-facing word (§0.9) |
| **proposer** | a tool the agent uses to produce options or evidence (a parts search, a layout optimiser). Its output is an input; it settles nothing |
| **basis** | where a proposer's or evaluator's answers come from: `established`, `sourced`, `model-only` |
| **round** | one unit of the agent's work: it ends when the agent's turn ends, with a commit |
| **pack** | one domain's proposers and evaluators, with skills, views and site partials |
| **board** | a named group of claims (any kind) the map draws as one board and the site explains as one section |
| **zone** | a named group of choices drawn as one band on the map's left |
| **station** | a derived value that several claim lines share on the map |
| **map** | the deterministic drawing of the resolution: the PETGasus transit pattern |
| **poster** | a board's section of the site: a generated floor plus the agent's chosen figures and prose |

## 3. What stays

1. **The invariants** in `CLAUDE.md` (numbered 1 to 13 and 15; 14 is reserved, see
   section 8) and the tests that hold them. Nothing below weakens one.
2. **Git is the groundspace.** A checkout is one state; commits are the history. No
   second history store, no snapshot per check. Reason: git already has parent
   pointers, authorship, signing and merges; a copy of that inside the tree is the
   duplication this design exists to avoid, and agents already speak git.
3. **One record per file, read strictly.** `results/` and `exports/` stay sealed and
   chained.
4. **The verdict cache** is the evidence ledger and the execution record. Nothing
   replaces it.
5. **Qualification**: controls, mutation testing for non-bundled evaluators,
   operating context, the human channel for results and ownership.
6. **Stdlib-only spine, no server, no database, no build step for the site.** A
   database does not diff in a pull request; `ledger.json` already is the query
   index.
7. **The site never computes truth.** Static, deployable as committed.
8. **Three-tier pack disclosure** and the pack admission bar.
9. **The model owns values and rationale** (METHOD rule 1). Records observe it
   (decision 10).

## 4. Decisions

### The state

10. **Records observe the design; they do not own its values.** The model owns every
    choice's value, units and rationale, and what lost to it (`PARAMS`).
    `params/<name>.json` keeps its role: the provenance the model cannot hold
    (`source`, `grounded_by`, `tags`). The observed view (value, units, rationale,
    what lost, choice or derived, derived from which choices, read by which
    evaluators) is computed from the model and the trace, shown live, and frozen in
    the round record. *Rejected:* values in records, the model reading them like
    Android string resources. Choices and instructions are not separable in practice
    (`plate_layout = "topopt"` is a choice that selects an instruction path), so
    records would hold the easy third of the state and claim to be its source, and a
    model reading files blinds the tracer. Each instruction layer needs an adapter
    that exposes its choices and provenance; python's `Config` docstrings and
    `PARAMS` are the first.
11. **Instructions are nodes.** Each file in the model's code closure carries its
    digest and a place on the map between choices and derived values; the trace
    gives the edges through it. A geometry edit reads as "this instruction changed,
    these stations moved." The granularity is a file.
12. **Requirements are records.** `requirements/<id>.json`: the person's words
    (`statement`) and where they came from (`source`: the interview, or an input
    id). Claims point at the requirements they serve with `requirements: [ids]`; a
    claim may serve several. A requirement's status is the worst status of its
    claims, in the composition's own order; a requirement no claim serves reads Gap.
    Readiness stays claims-only: milestones require claims. The map's left edge is
    this column.
13. **Every claim names its mechanism.**
    `"mechanism": {"by": "...", "how": "...", "evaluators": ["..."]}`.
    `by` is how the evidence bottoms out (today's `terminal` enum, validated against
    the kind, derived from the kind when absent); `how` says in words what would
    settle the claim (for a physical claim, the written test, today's `note`);
    `evaluators` names the evaluators the claim expects. That list is a cross-check,
    never coverage: coverage stays the registry's, because a claim file that held
    coverage was rewritten by `check` on every run (S-37). `check` and `doctor` warn
    when a named evaluator is not registered or does not cover the claim; no status
    moves. The sealed claim digest keeps its form (`terminal` is `by`, `note` is
    `how`), so every recorded physical pass stays bound. The old keys `terminal` and
    `note` are read as their mechanism equivalents. `gap` lists every claim whose
    mechanism has not run, physical and assumption claims included, and
    `gap --propose` searches with the `how` text. Reason: every claim is settleable;
    some are expensive. "Looks cool" is settled by a reddit post and a sentiment
    pass, latency one week. The status says the mechanism has not run, never that
    nothing can check it.
14. **Decisions get typed rejections and return conditions** (paper §7.4). Each
    `rejected` entry gains `type` (`infeasible`, `dominated`, `preferred_against`,
    `unevaluated`), `returns_if` (§0.2), and `input` when an input id is its source.
    `PARAMS` rejections in the model stay text. A `preferred_against` rejection is a
    person's preference: it counts only when that person records it with
    `nopekit prefer`, typed in their own shell (sealed, like an owner); until then it
    reads "preferred against, not recorded by <name>".
15. **Candidates are records.** `candidates/<id>.json`: `overrides` (choice values,
    or `"code"` when the candidate differs in instructions), `compared_against` (the
    round record digest at the merge), `disposition` (a rejection type, or
    `selected`), `why`, `returns_if`, and the tag `cand/<id>` by convention. The tree
    never holds a sha. `check` evaluates every return condition against the current
    resolution and prints a candidate that may return; it never changes the exit
    code. A condition on a claim that is not Checked and current reads "cannot be
    evaluated: C1 is <status>". `doctor` warns when a candidate's tag is missing,
    locally or on the remote. *Rejected:* a branch alone (says what, not why; cannot
    be acted on; one `git branch -D` from gone); a sha in the record (self-reference
    across the boundary, unstable under rebase).
16. **The state holds one candidate.** Several at once are branches. A sweep over
    fifty values is an evaluator's work and produces evidence on one claim, not fifty
    candidates. Heavy for set-based exploration of hundreds; fine for one agent and
    one person.
17. **Boards, zones and stations are records.** `groups/<id>.json`:
    `{"kind": "board" | "zone" | "station", "title", "line", "members": [...]}`. A
    board's members are claim ids of any kind; a zone's are choice names; a
    station's are derived-value names. A claim sits on at most one board; claims on
    none go to a board called "Other". Shared derived values without a station
    record become stations under their own names. Reason: the author's reference map
    groups claims, including assumptions and physical tests, onto boards.
18. **The round record is tracked.** `.nopekit/round.json`. Renamed from "the
    judgement", because the glossary's "judgment" is an expert's judgment. Written
    only by `nopekit round` and `nopekit merge`, never by `check`. It holds tokens,
    not words (status keys, ids, numbers, the typed graph), the digests of the
    records and the verdict cache it was computed from, and a digest of itself.
    Readers verify the self-digest and say "edited by hand" or "behind the records"
    when it fails. Never hand-merged: `merge` regenerates it. Not in the spine
    digest. Reason: a pull request that flips C1 from pass to fail shows as a
    one-line diff, and a rare history walk reads it with `git show` without
    re-judging under a newer nopekit.
19. **Edges are typed.** `reads` (evaluator to value, from verdict read sets),
    `settles` (evaluator to claim, registry coverage), `requires` (milestone to
    claim), `derives` (choice to derived value, from the trace), `sources` (input to
    choice, `params/<name>.json` `grounded_by`), `rests_on` (claim to assumption
    claim: its evaluators read a value derived from a choice an assumption sources),
    `resolves` (physical claim to the assumption it replaces: a `resolves: [ids]`
    field on the physical claim), `contradicts` (a physical fail to the evaluator
    that passed the claim) and `needs` (evaluator to prerequisite evaluator). The
    renderer never infers meaning from line style.

### The loop

20. **Only the agent edits records.** The human channel is the short list of actions
    that need a person: a physical result, ownership of an assumption, an expert
    judgment, a preference between candidates, going ahead over an unresolved claim.
    Records need to be readable by a person, not comfortable to edit.
21. **Interview first.** Product-manager style: extract requirements the person can
    state without technical vocabulary, ask for sketches, reference images, links,
    measurements, datasheets. Show the requirements for a yes; the person can always
    say skip. Then first light; claims appear beside the first verdicts, because most
    cannot be stated precisely before a model exists.
22. **Proposals are evidence.** A proposer's output goes through `ingest` and
    `extract`; the input records which proposer produced it. The options it found are
    kept or dropped in a decision record. No proposal record.
23. **`nopekit merge <branch>`.** Merges the branch through the writing half of
    `vcs.py`, tags each losing branch named with `--over` as `cand/<id>`, writes its
    candidate record (overrides from the two choice views, type and `returns_if`
    from the flags), regenerates the round record, commits, and pushes the tags when
    a remote exists (a failed push warns; the local merge stands). It refuses when
    `results/` or `exports/` changed on both sides: a sealed chain cannot be merged
    without re-sealing a person's entries. A `preferred_against` type is refused
    from an agent session; the person records it with `nopekit prefer`. A merge made
    without the command leaves the losers undisposed, not decided.
24. **Rounds are layered.** The map rebuilds after every `check` (through
    `site serve --watch`). The poster prose, the round record and the commit happen
    when the agent's turn ends: the plugin's Stop hook runs `nopekit round`, which
    runs a tier-0 check, starts the trace in the background when the instructions
    changed, builds the site when `site/` exists, writes the round record, stages the
    project's own paths (inside the project's directory only), and commits when the
    identity is allowed (§0.3), with the message `round N: <what changed>` and no
    attribution trailer. It prints its summary as the hook's `systemMessage` and
    exits 0: it never blocks the turn. The commit is history, not a quality gate: a
    round with failing claims still commits. *Rejected:* every write (half-states), a
    command the agent must remember, a state event (hours pass without one).

### Packs

25. **A pack holds proposers and evaluators** for one domain, plus skills, views and
    site partials. Project evaluators stay in the project's `gates/` and `selftest/`,
    qualified against the project's own model; a pack copied into a project stays in
    `.nopekit/packs/`; `NOPEKIT_PACK_PATH` keeps its place in the search order.
    Promoting a project evaluator to a pack means writing a sealed baseline.
26. **Extension repositories** add a pack or extend one (`"extends": "sourcing"` in
    `pack.json`). An extension's evaluator ids use its own namespace; it may `need`
    its base's evaluators; it is demonstrated with its base loaded; an id that is
    already registered is refused (the registry does this today). An extension is
    qualified at the non-bundled bar. A registry file at this repository's root
    (`registry.json`) indexes known pack repositories by what they settle;
    `gap --propose` shows them as "not installed". Pins by source and version are
    deferred.
27. **Track records stay derived** from `results/` on every read: never a file of
    their own, so deleting the verdict cache cannot erase them.
    `nopekit gate track --export` writes the portable, project-free form on demand,
    for a pull request to a pack's repository. Upstream flow beyond that is
    deferred. Reason: the paper (§7.3) says a track record attaches to its operating
    context and transfer cannot be assumed.
38. **Proposers and evaluators declare a basis**, in a fixed order of preference.
    `established`: wraps an existing non-AI tool with its own track record (KiCad's
    layout optimizer or DRC, OpenModelica, trimesh). `sourced`: built by an LLM, and
    its answers come from an outside source it reads (a parts search over a
    catalogue, a datasheet lookup, a cited textbook formula). `model-only`: built by
    an LLM with no basis outside the model. Declared per evaluator (`GateSpec`),
    defaulting to the pack's `basis` in `pack.json`; a bundled pack must declare it
    (`pack validate`); an undeclared basis shows as "undeclared". An input records
    the proposer that produced it; its basis is looked up from that proposer, never
    stated by the input (a self-stated trust property would launder itself, the
    reason `independence` is a forbidden key). The agent uses the highest basis
    available and says why when it goes lower. The basis appears in `gate list`, the
    map and the report; it changes no status and no qualification. Reason: the
    author's rule is "existing trusted systems first, then LLM-built systems that
    source themselves, then LLM-built systems with no outside basis", for both
    phases.
39. **The trace observes derivation by perturbation.** `nopekit model trace`
    rebuilds the model in a temporary copy of the project with each choice nudged by
    -10% and +10% (a boolean or a string is skipped and says so), and records which
    derived values moved and by how much (a scalar by relative change, a structure
    by its digest). Keyed by the instructions' digest and the choices' values,
    tracked under `.nopekit/trace/`, never rewritten. `round` starts it in the
    background when the instructions changed; the map shows each derivation edge as
    traced at a named round. Amber: for a Checked claim that rests on an assumption
    no one has confirmed, the trace re-runs that claim's evaluators on the nudged
    projection (writing nothing, as a mutation pass does); a pass that a ±10% move of
    an assumption-sourced choice flips is amber, "passes if the estimates hold".
    Amber is shown beside Checked; it changes no status. Cost: one model build per
    nudge (PETGasus: about an hour per instruction change).

### The site

28. **Fixed outline:** name, representation, description, map (with the verdict
    sentence right under the representation), one section per board, next steps,
    made with nopekit. Today's panels (every claim, every verdict with its locators,
    parameters with what lost, evidence, gaps, decisions) move to `technical.html`.
    `index.html` stays the project's own; `site build` warns when it predates the
    outline.
29. **The map follows the author's transit pattern** (`PETGasus Grounding Map.html`):
    zones of choices on the left, claim lines riding shared stations, ending on
    boards; green for a pass, red for a fail, amber for a pass the trace can flip,
    dashed for stale, dotted for not yet checked. **Order is baked, geometry is
    rendered:** the map data holds nodes with kind, lane, board, status token and a
    stable order index, and typed edges; no x or y. The renderer is plain SVG (no
    d3), uses a layered layout, never a force layout, never reorders by default (a
    "failing first" sort as a viewer control is fine), and measures text after
    placement, never to decide topology. *Rejected:* baked pixel positions (wrong on
    a phone, presentation in data); the reference's hand-placed layout and its
    in-browser what-if (both compute in the browser).
30. **Per-board sections are a poster.** A generated floor (measured against limit
    for every numeric verdict, the evidence the evaluator wrote, copied into
    `site/assets/`), collapsed by default; then the agent's chosen figures and prose
    in `site/content/<board>.md`, stamped `as_of` by `nopekit site stamp <board>`
    and flagged when the resolution of that board's claims has moved since. A
    missing `as_of` reads stale. Every number in prose must match a baked number at
    the prose's precision; a scan enforces it. The agent judges what is compelling,
    as for a conference poster; a figure made in the figuring-out is best, a figure
    made to explain is allowed when cheap. This is the one place the site persuades,
    so the stamp matters most here.
31. **History is rare and outside the daily build.** `site build` reads the
    checkout. A history walk (stills, frames, a video beside the representation) is
    one on-demand tool that reads each commit's round record with `git show`. It is
    the lowest priority, and anything it needs beyond the standard library stays out
    of `src/nopekit/`.
32. **Baked versus rendered.** Baked: written by `site build` under `site/data/` and
    `site/assets/`. Rendered: what the browser does with a baked file. Every number,
    status, word and order on the page exists in a baked file; the browser maps data
    to DOM and handles hover, selection, filters and theme. Never in the browser: a
    status, a margin, readiness, a sensitivity. The build time and each verdict's age
    go to `site/data/build.json`, which git ignores, so a rebuild that judged nothing
    new changes no tracked byte.
33. **Live versus published.** Local: `nopekit site serve --watch` watches the
    records, the model, the verdict cache, the trace and `site/content/`, rebuilds,
    and the page polls `data/build.json`. Published: Pages serves `site/` as
    committed, or CI builds it. Same baked files either way.

### Style

34. **Human-facing text on the site follows ASD-STE100** (Simplified Technical
    English): the site template, the words the build bakes, `site/content/` prose,
    the README block nopekit writes, and every skill's example output. Short
    sentences (about 20 words), one approved word for one thing, present tense,
    imperative for instructions, no contractions, no synonyms for variety. CLI output
    and `REPORT.md` keep the glossary and `test_vocabulary` as their rule. Record
    text (a claim's statement, a requirement's words, an evaluator's detail) is
    exempt. The PETGasus front page (commit `08c6783` in that repository) is the
    reference rewrite.
35. **No LLM register on the site.** Banned: em-dash asides, "not X but Y", lists of
    three for rhythm, rhetorical questions, "delve", "robust", "seamless",
    "crucial", "honest" as self-description, a closing line that restates the
    paragraph. "Checked does not mean true" appears once per page. A scan over the
    template and the generated content holds the list.
36. **The badge.** Every project nopekit creates shows the Made-with-nopekit badge,
    linked to `github.com/neuman/nopekit`: the last section of the site (the badge
    ships in the template) and a marked block at the bottom of the README, which
    `init` writes. The mascot (`docs/img/nopey.png`, Nopey the honey badger) belongs
    on this repository's README only.

### The plugin

37. **The skill shrinks** to the method plus a command table. A pack's skills are
    read, not installed: `nopekit packs skills` prints the skill files of the live
    packs that can run here, and the main skill tells the agent to read them. Paths
    use `${CLAUDE_PLUGIN_ROOT}` (braced; the unbraced form is not substituted, and
    the variable is not in the Bash tool's environment). The Stop hook lives in
    `hooks/hooks.json`. No `bin/`: hosts other than the CLI refuse a plugin that has
    one.

## 5. Layout

Now, through phase 7:

```
my-project/
  .nopekit/project.json     name, model entry, nopekit version, packs, people
  model/                    the instructions: owns every choice's value and rationale
  gates/  selftest/         the project's own evaluators and their controls
  views/  generators/       viewgens and the builders milestones name
  requirements/ claims/ decisions/ candidates/ inputs/ results/
  params/ needs/ milestones/ exports/ groups/ views/*.json     one record per file
  out/                      the outputs export builds; ignored
  .nopekit/
    verdicts/               tracked: every verdict by ρ, every control run
    trace/                  tracked: observed derivation, by instructions digest
    round.json              tracked: the round record
    packs/                  packs copied into this project
    ledger.json cache/ obs/ out/     ignored, rebuilt
  site/
    index.html              the project's own, never regenerated
    content/<board>.md      agent prose per board, stamped as_of
    annotations.json        authored pins on the representation
    img/made-with-nopekit.png
    data/  assets/          baked by `site build`; data/build.json ignored
```

Last (phase 8, if budget remains): every record directory moves under `design/`
(`exports/`, `needs/` and the `views/*.json` records with them), and
`.nopekit/project.json` becomes `nopekit.json` at the root, through a second one-time
migration under invariant 8's carve-out. Evidence bytes in `inputs/<bucket>/` move
with them only if the migration can keep every verdict and article bound.

## 6. Known risks

Named here so the first person to hit one knows it was seen.

- **Overrides drift from their base.** A candidate was judged against HEAD as it
  stood then. The record carries what it was compared against; the return condition
  applies to that comparison.
- **Return conditions reference claims that get edited.** A condition on a claim that
  is not Checked and current says so; it never silently fails to fire.
- **Claim ids collide across branches.** Two candidates each add the next id; `merge`
  refuses and names both.
- **The round record will be read for truth.** It carries its self-digest and a
  header saying what it is; nothing in the spine reads it as input.
- **The round runs mid-thought.** It commits what is there; the next round commits
  the rest.
- **The agent can run `git merge` without the command.** The candidate record is what
  carries the decision; an unrecorded merge leaves candidates undisposed.
- **Stamped prose ages within minutes.** The stale flag fires on a change to that
  board's claims, not on any change.
- **The floor is a wall of identical bars.** Collapsed by default.
- **A compelling figure can be wrong.** The stamp guards age, not correctness; the
  number scan is the only guard.
- **A slow model makes the trace slow.** It runs in the background and the map labels
  each derivation edge with the round that traced it.
- **A choice outside `Config` is invisible to the trace.** It shows as part of the
  instructions until the adapter exposes it.
- **The documents and tests are the real cost.** The glossary, the spine contract and
  the site contract describe the old shape, and about 1,700 tests hold it. Each
  decision is a document rewrite and a test rewrite before it is code.

## 7. Sequence

Each phase runs on branch `architecture`: understand, design (a judge panel),
implement in a worktree, review (three refuters per finding), fix, all four CI checks
green, commit. Smallest and safest first.

1. **Claims say how they settle** (done: e138fc8). The plugin paths (37, part), the
   mechanism (13), requirements (12), `gap` over every unsettled claim, the vocabulary
   (§0.9), METHOD.md's three edits (§0.8).
2. **Decisions keep their losers** (done: 7a1338c). Typed rejections and return
   conditions (14), `nopekit prefer` (a sealed preference, invariant 13), basis on
   evaluators, proposers and inputs (38), proposers in packs (22, 25).
3. **The graph and the round record** (3a). The typed graph (19), the round record
   (18), `nopekit round` without its hook and commit.
4. **The site** (5). Boards, zones, stations (17); the map data and the transit
   renderer (29); the outline and `technical.html` (28); the poster and `site stamp`
   (30); `build.json` and `serve --watch` (32, 33); the STE and register scans (34,
   35); the README badge (36).
5. **Rounds and the plugin** (6). The Stop hook and the round's commit (24), the
   people allow list (§0.3), the skill rewrite and pack skills (37).
6. **The trace** (3b). Derivation by perturbation, derives edges, amber (39).
7. **Candidates and merge** (4). Candidate records (15, 16), return conditions in
   `check`, the writing half of `vcs.py`, `nopekit merge` (23).
8. **Packs in the world** (7). `extends`, the registry file (26), the track export (27).
9. **The design/ move** (section 5) and **a replay** (a sandboxed agent with no shared
   priors runs the PETGasus requests through the new nopekit), if budget remains.

The order changed after phase 2 (2026-10-15): the author capped this refactor at 40%
of a week's usage, and two phases cost about ten points, so the work that shows (the
graph, the site, the live round) comes before the work that refines it (the trace,
candidates, packs in the world). Phase labels in parentheses are the ones commits
and section 8 use.

`examples/bracket` stays the reference project at every phase, its committed cache
regenerated whenever the spine moves.

## 8. Decided during implementation

The author did not answer these directly; the agent decided them within the
decisions above. Overturn any of them here.

- **Mechanism shape** (13): `by`, `how`, `evaluators`, beside the claim's `kind`; the
  sealed digest keeps its form so no person must re-test.
- **The evaluator list on a claim is a cross-check, never coverage** (13). An earlier
  reading made it add coverage; the code's lesson S-37 (a claim file holding coverage
  was rewritten by `check`) and the resolver's purity overruled it.
- **Requirement status and readiness** (12): worst of its claims; readiness stays
  claims-only; requirements get a report section and a map column, not a JUnit suite.
- **Amber changes no status** (39), as basis changes none (§0.4).
- **"Judgement" becomes "round record"** (18), to keep one word for one thing beside
  the glossary's "judgment".
- **Boards group claims, not evaluators** (17), as the reference map does.
- **A preference is recorded with `nopekit prefer`** (14, 23) and sealed like an
  owner, because a person's choice written into an agent-edited record is a nominee,
  not an attribution (invariant 11).
- **Track records stay derived** (27); the tracked `.nopekit/track/` of the first
  draft would have been a second home for the same facts.
- **Pins are deferred** (26): nothing reads a pack's version today, and the verdict
  cache already keys on each evaluator's code.
- **Style scope** (34, 35): the site and what nopekit writes into a README, not CLI
  output or `REPORT.md`.
- **The README badge** (36) is a marked block `init` appends at the bottom of
  `README.md`, with an absolute image URL, so it works before `site init`.
- **Invariant numbers**: 13 is "a preference counts only through the person's
  channel" (landed in phase 2) and 14 is reserved for "the site never says more than the
  resolution, and stamped prose is flagged when behind" (phase 5). Each lands with
  its tests, its `INVARIANT_CLASSES` row and its `CLAUDE.md` row.
- **The fast tier** keeps its 90-second rule: a phase that adds time pays it back.

**Phase 1** (claims say how they settle), decided while building it:

- **The claim stays flat in memory.** `Claim.terminal` is `by`, `Claim.note` is `how`,
  `Claim.evaluators` is new; only the file spells one `"mechanism"` object
  (`models.CLAIM_MECHANISM`). A nested `Mechanism` dataclass was rejected: every reader
  and about 105 test constructions rewritten for nothing phase 3 needs.
- **One home per member.** `terminal` beside `mechanism.by`, or `note` beside
  `mechanism.how`, is refused even when equal; different members in different
  spellings read; a top-level `evaluators` is refused; `"mechanism": {}` reads as absent.
- **The writer folds** the mechanism at `note`'s slot, members in `by`/`how`/`evaluators`
  order, and writes `requirements` last; index rows show that form, `to_dict` stays flat.
- **Not sealed:** `evaluators` and `requirements` are out of `claims.claim_digest`, and
  out of a gate's read of a claim while empty. `requirements` is read whole and traced.
  `how` stays sealed (it is `note`): editing it moves a judged or tested claim to Gap or
  Stale, as editing `note` did.
- **Requirement ids** are `R` and a number from 1 (`store.REQUIREMENT_ID`), on the file
  stem and every pointer. Fields: `statement` (required) and `source`. `status` and
  `claims` are forbidden keys naming their homes.
- **A pointer to a missing requirement is read**, an index problem and a doctor FAIL
  (the milestone precedent), as is a requirement id equal to a claim id; a requirement
  no claim serves is a doctor warning.
- **Requirement status** is `RequirementStatus(id, status, errored, claims, worst)`: the
  worst claim by `claims.severity`, a crash above a plain skip, ties in record order;
  Gap with no new cause when no claim serves it. A crash rolled up reads `skipped,
  errored` (`report.status_word`), since a rolled-up line prints no tag.
- **Status prints one untagged line**, `requirements N — R1 failing (C1) · …`, after the
  claim rows, only when requirements exist, capped at eight.
- **The report's `## Requirements`** comes after Failing and before Reproduce, only when
  requirements exist; no JUnit suite.
- **JSON:** `summarise()["requirements"]` (tokens); `status --json`, `report --json` and
  `state.json` gain `requirements` rows (`report.requirement_json`); `claim_json` gains
  `mechanism` and drops the flat `evaluators`.
- **"Yet to run"** means Gap, Pending build or Assumed (`claims.MECHANISM_YET_TO_RUN`);
  `gap` resolves the cache exactly as `status` does.
- **`gap`'s output:** status-tagged rows in severity order, each with its mechanism
  line, mechanism warnings and its gap record; a footer counting them; `--json` adds
  `yet_to_run`. `--propose` weighs the `how` words at half the quantity's, searches a
  claim with no Need through a transient Need never written, and says a pack checks
  only a modelled part of a physical, judged or assumed claim.
- **Mechanism warnings** are `unregistered` and `uncovered`, on `check`'s stdout after
  the limit warnings and in `check --json`; `doctor` has a `mechanisms` row that never
  FAILs; `why` shows none.
- **`reason()` is unchanged:** the `how` text is not appended to Gap reasons; it shows in
  `gap`, `why`, the report's gap section and the page's "Mechanism" field.
- **`why`** resolves requirement ids after exact params and claims, takes the caller's
  compositions, and a claim's `why` gains `serves:` and a MECHANISM section.
- **The bracket's requirements** are R1 to R4 in invented interview words; C1–C4 and C7
  declare `by: closed_form`, C5 and C6 leave `by` to their kind; every claim gets a `how`;
  C1–C4 name their tag-covering evaluators.
- **Legacy bracket copies** in the tests exclude `requirements/`
  (`tests/_projects._ADDED_AFTER_MIGRATION`).
- **The chain** `requirements -> claims -> gates -> packs -> readiness report` is also in
  README, CLAUDE.md and the skill; README's rule 1 follows METHOD's.
- **CLAUDE.md** invariants 4, 7, 11 and 12 each gained a clause, invariant 8's record list
  `requirements/`; the new classes map to rows 4, 7, 8, 11 and 12.
- **GLOSSARY:** requirement, mechanism, proposer and basis in §1; round record and board
  in §4 with italic Never-says; *candidate* is an alternative design with a disposition,
  and the current design is never one.
- **Human strings:** Failing's hint and a live-design control say "the current design";
  the three `"note"` strings name `mechanism.how`; the tool-option fallback word is
  "option"; the page's "Note" label is "Mechanism".
- **The plugin test** checks braces under `skills/`, `.claude-plugin/` and `hooks/`, that
  every METHOD.md or docs path a skill names is `${CLAUDE_PLUGIN_ROOT}`-rooted and
  exists, and that there is no `bin/`.
- **The fast tier's pay-back:** `test_status_table.UnqualifiedReadsGap` and one
  `check` run in `test_renderers` moved to the full suite.

**Phase 2** (decisions keep their losers), decided while building it:

- **Typed rejections live on `Rejection(Rejected)`**, used only by `Decision.rejected`.
  PARAMS and `params/` keep text `Rejected`; typed keys there are refused, naming
  `decide`.
- **`by` sits on each preferred_against rejection**, not on the decision: one decision
  can hold one person's preference beside an evaluator's infeasible, as each phase 4
  candidate will. preferred_against without `by`, and `by` on any other type, are
  refused.
- **Return conditions** compare with `<`, `<=`, `>` or `>=`. `"returns_if": {}` reads as
  absent. There are no units. A dangling claim or input is an index problem and a
  doctor warning; `decide` refuses both at write time. `write_record` holds a decision
  to the reader's rules before it writes.
- **The value the composition reports** for a Checked claim is the compared covering
  pass with the least margin (`claims.claim_value`). The margin is that verdict's own
  (`claims.margin`, now over a shared `_margin_of`). A Checked physical claim gives its
  counted result's measured value, in the acceptance units only. A judged claim has no
  value. `limit` on a band cannot be evaluated.
- **A preference binds** to the decision's id and title and the rejection's value, why
  and return condition (`claims.rejection_digest`, schema 1). Its file is
  `preferences/<decision id>.json`, a new sealed kind whose seal names the kind and the
  file, written through the exports branch of `append_sealed`, extracted unchanged. Its
  in-memory home is `Decision.preferences`, hidden from every gate.
- **`prefer` records one alternative per run** (`--value` when several name you). It
  is refused outright from an agent session or a pipe. A repeat writes nothing. It
  prints the rejection read back on the view `status` judges.
- **Basis** reaches a pack's gates through a `PACK_BASIS` module global. It is shown as
  a `basis <word>` segment after `gate list`'s bracket (the line collapses its spacing
  as before, so the shape is single-spaced), in `gate show`'s tier line, in the
  report's Evaluator cell and Reproduce comment, and on `state.json` verdict rows; not
  in JUnit. `pack validate` requires it only of bundled packs.
- **Bundled bases** are §5.4 of the phase design's table, unchanged after reading each
  gate: beam-analytic, fluids-analytic and thermal-analytic `sourced`
  (`beam.input_sanity` and `thermal.h_agreement` `model-only`); cad-solid, fdm-print,
  openmodelica and sourcing `model-only` (`cad.is_volume`, `modelica.checks`,
  `compiles`, `simulates` and `result_claim` `established`; `bom.process_rules`
  `sourced`); the bracket's four structural gates `sourced`, `bed_fit` and `min_wall`
  `model-only`.
- **Proposers** are scripts declared in `provides_proposers` (`id`, `basis`,
  `description`, `run`), found in any discoverable pack, and run as a subprocess with
  `NOPEKIT_PROPOSAL_DIR` (and `NOPEKIT_PROJECT`). A write anywhere in the project
  outside that directory (its ignored scratch aside), a non-zero exit or a timeout
  refuses the ingest. Human sentences say "proposed by". No bundled proposer ships.
- **`check` prints only "may return"**, after the mechanism warnings; its JSON gains
  `may_return`. `status` adds no line. `doctor` gains warn-only `decisions` and `basis`
  rows.
- **`state.json`'s rejection rows are a top-level `rejections` key**, beside
  `decisions`: the document has no `summary` key to carry them.
- **The bracket** gains `decisions/print-in-petg.json`, written by `decide` (title
  "Print in PETG", so the slug is the id), with three types and an unrecorded
  preference by an invented person, Robin Okafor (the phase design named another, a persona the private bench scores — `test_priors` refuses it in shipped text). Each sentence follows the model: PLA is
  infeasible on the model's own creep sentence; ABS is *unevaluated*, not dominated —
  the model holds no ABS properties, so "no stiffer than PETG" could not be said from
  it. No preference file is committed.
- **The status packs line** names up to eight available packs, then "and N more".
- **Invariant 13** lands in `tests/test_preferences.py`. Return-condition honesty maps
  to 12; basis maps to 4, 7 and 9; proposers map to 3 and 8.
- **The basis words, sharpened** (38): *established* when the verdict or proposal is
  an existing non-AI tool's own answer, *sourced* when its logic follows a cited
  outside source, *model-only* when the model wrote the logic, even when it calls a
  tool's primitives. Decision 38's "wraps an existing non-AI tool" would have made
  `cad.watertight` (its own edge count over a trimesh mesh) established; the
  glossary, PACK_FORMAT and the skills say the sharper rule.

**Review of phase 2**, decided while fixing what it found:

- **A physical claim's value is the counted pass's** (`Standing.counted`), never the
  newest entry: a later pass from an agent session is recorded, counts for nothing,
  and must not make a return condition hold.
- **A gate's copy of `decisions` holds no `preferences`** (`verdicts._HIDDEN_FROM_THE_COPY`):
  out of the digest was not enough. The claim's in-memory fields stay on the copy, as
  since P2.1.
- **`propose` watches the whole project**, by size and mtime (`cli._project_files`),
  not the records digest, and names every moved path; the limit is in SPINE_CONTRACT.
- **`propose`'s script arguments are `nargs="*"`**, and `main` hands everything after
  the first `--` to the script: nopekit's own flags stay nopekit's after the id, and
  a flag of the script's goes after `--` (an unrecognised argument before it is said
  aloud). `--json` prints JSON on a run that wrote no file.
- **A basis word is said beside "basis"**: `proposed by <id> (basis <word>)`, and
  `propose`'s listing row `<id>  basis <word>  <description>`.

**Phase 3a** (the graph and the round record), decided while building it:

- **The graph is structure; the statuses sit beside it.** `graph.build` returns nodes
  and typed edges with no status, `graph.tokens` the status tokens by id, and the round
  record holds both; the site joins them by id. Statuses inside the nodes were rejected:
  two homes in one file, and a flip of C1 diffing as a nested change instead of
  `"C1": "failing"`.
- **Node ids are `<kind>:<key>`;** an instruction's key is the article's portable code
  path with `<root>/` stripped (`model/bracket.py`). Nodes sort by kind, then
  naturally; edges by type, then source, then target. `to_dict` writes nodes as `{id:
  attrs}` and edges as `{type: {source: [targets]}}`, every type present, no edge
  attributes (`Graph.via` recomputes a `rests_on` edge's evaluator and values for `why`).
- **Each kind's attrs are always present:** a claim `{claim_kind, by, critical,
  removed}`, an evaluator `{pack, basis, tier, registered}`, a value `{role, digest}`
  and `value` only for a finite int, float or bool, an instruction `{digest}`, an input
  `{proposer, basis}`; a requirement, a milestone and a decision none.
- **Value nodes** are every choice and every other name an edge or a parameter view
  names; a derived value nothing reads, sources, decides or derives is no node (it
  keeps a 27 KB field out of the record). Roles are choice, derived or absent; a choice
  and a derived key of one name are one node, the choice.
- **An edge needs two nodes.** A pointer to a missing or wrong-kind record makes no
  edge (the index and doctor name it); an unregistered evaluator a `needs` or a
  `contradicts` names is a `registered: false` node.
- **`reads` come from the registered gates' served `Row.entry`**, never `obs/` or
  `Resolution.read_sets`, through one path rule (`graph.value_names`: `["config", k]`
  reads `k`, `["config"]` every choice, `[k]` `k`, `[]` every value — review of 3a).
  `settles` is `claims.effective_gates`; `sources` is the one grounding map, moved from
  `cli._grounding` to `artifacts.value_grounding`.
- **`rests_on`** is computed for claims of every kind, never to itself, and closes the
  read values upward over `derives` edges, so phase 3b's trace adds edges and no code
  (a stub trace in `test_graph` proves it). With no trace the graph says `trace:
  null`, `derives: {}`, and doctor "derivation not traced yet".
- **`Claim.resolves`** is declared after `requirements`, written only when non-empty,
  refused on a non-physical claim, on the claim itself, on a non-id and on a repeat; a
  dangling or non-assumption target is an index problem and a doctor `graph` FAIL. Not
  in the claim digest, absent-when-empty for a gate's read, and it moves no status.
- **An assumption's id in a param's `grounded_by`** says the value IS that assumption.
  An id that is both an input and a claim reads as the input and is an index problem; a
  non-assumption claim there is one too; `PARAMS` grounding gets the same check in
  doctor's `graph` row. `Claim.grounded_by` keeps meaning inputs only.
- **`FORBIDDEN_KEYS`** gains `Claim.rests_on`, `Param.read_by` and
  `Param.sourced_from`, each naming where the fact is derived.
- **The observed view** (`ParamView.read_by`, `sourced_from`, filled by
  `graph.observe`; `gates` kept as it was, so the two can differ) reaches
  `last_check.json`, `state.json` and `why`; `status` and the report carry the view for
  the undefended rule only and print neither field. `graph.observe` takes
  the model's choice names (`choices=`), the one thing a read of the whole `config`
  needs that a parameter view does not carry — a keyword the design did not list.
- **`why`** prints `read by:` and `sourced from:` for a parameter, `rests on:`,
  `resolves:` and `resolved by:` for a claim (each only when handed the graph, which
  the CLI always passes), an assumption in GROUNDED BY as `[assumption]`, and a short
  block for a derived value an evaluator read; `inputs --json` leaves claim ids out of
  its grounding map.
- **The round record is computed from three digests:** the records
  (`store.records_digest`), the verdict cache (every file's bytes under
  `.nopekit/verdicts/`) and the design (the seal of `verdicts.design_of`, the current
  article's `built_from`, extracted from `article_of` with every article hash
  unchanged). No spine or version digest: an upgrade is not "behind the records".
- **The file:** keys in a fixed order, indent 2, `ensure_ascii=False`, NaN refused, one
  newline; `self` is the seal of the rest; the one sentence is `HEADER`; a crash reads
  `errored`; `disagree` lists claims and requirements whose status and evidence
  disagree, so a contradiction never sits there as a silent `checked`.
- **Reader states:** absent, unreadable (strict JSON: duplicate keys and NaN refused;
  a merge conflict lands here), newer (schema above 1, never rewritten), edited (the
  seal does not match), current or behind (naming the records, the verdict cache or the
  design).
- **The write rule:** nothing when the record reads `ok` and holds the same on every
  key but its own four; otherwise the previous round + 1 (an edited record's
  included), else 1; never over a newer schema; bytes only when they differ.
  `rounds.sealed` is public, so invariant 8's test computes the record of the state
  after a run exactly as `write` does.
- **`round` resolves once, after its check,** with no sweep overlay (what `status`
  shows), and the site and the record share that resolution.
- **`round` never exits 2:** every `NopekitError` is said in one line with exit 0; a
  model that does not load refuses the check and the record is still written; a pack
  that does not import writes no record (`_check_run` takes the strict registry
  `round` loaded first, to tell that refusal from the model's — a keyword the design
  did not list); only a traceback exits 1.
- **`round`** migrates a legacy project as `check` does (invariant 8's carve-out
  names it), is not in `_INDEX_UNTOUCHED`, and prints one paragraph: flips capped at
  eight, new verdicts at four ids, status words from `report.status_token_word`,
  *ready* as last evaluated.
- **`status`** prints a `round record:` line after `last check run:` and `status
  --json` a `round` object (its state, never its statuses); `doctor` gains a warn-only
  `round` row and a `graph` row that FAILs on a pointer problem.
- **`graph.py` and `rounds.py` are not spine modules** and join `CLOCKLESS_MODULES`;
  only `cli` imports `rounds`, and the literal file name is a value only in `rounds.py`
  (a docstring may say where the record lives). Their invariant classes map to rows 7,
  8 and 12; no invariant number is new (14 stays reserved).
- **The bracket** gains `params/load_n.json` (`{"grounded_by": ["C6"]}`), so C1 rests
  on C6, and a committed `.nopekit/round.json` (round 1). No claim and no `resolves`
  were added, so the transcript's counts hold; the cache's regeneration ends with
  `nopekit round`.
- **Invariant 8's property test** explains a write of the round record only when its
  bytes moved and equal the record recomputed in process from the state after the run,
  never as a path allowance.
- **The louder project's after-edit round** runs after the files it reads are read:
  its tier-0 check re-runs what the edit invalidated and rebuilds the site, which every
  reader before it must see Stale.
- **The fast tier's pay-back:** `test_vocabulary.QualificationWordsComeFromOneTable`,
  `test_freshness`, `test_readers` and `test_trace` moved to the full suite, none an
  invariant class; the phase added ~3.8 s in process (its invariant rows and
  `round`'s watched run in the records sweep), and two interleaved pairs then measured
  flat against c26fcd5 (92.0 and 92.6 s wall against 92.5 and 92.3 s).
- **New public names:** `verdicts.design_of`, `store.pointer_problems` and
  `grounded_by_problem`, `artifacts.value_grounding` (`cli._grounding` deleted),
  `claims.outcome_key`, `report.status_token_word` (the private name kept),
  `report.round_paragraph` and `round_moved`. `site.judgement_digest` is not renamed
  until the site phase; no graph key goes into `state.json`, and no graph command is
  added.

**Review of phase 3a**, decided while fixing what it found:

- **A read of the whole `ctx.params` reads every value.** `.copy()`, `.items()` or
  `json.dumps(ctx.params)` record one bare path, `[]`; `graph.value_names` reads it as
  every choice and every derived key (`graph.derived_names`: the projection's, less an
  echoed `config`), so the evaluator draws its `reads` edges, its claim its `rests_on`,
  and `why` its `read by:`. `observe` and `_shown_params` take the projection's derived
  names for it.
- **`contradicts` starts at the claim**, not at a physical-result node (decision 19
  says "a physical fail"): `Resolution.track` names the claim whose sealed fail
  contradicts the evaluator, and a result is an entry of that claim's sealed file, not a
  record of its own. A result node would be a node per sealed entry, joined to nothing
  else; the claim is what the map draws.
- **The seal comes before the schema.** The self-digest rule is the record's format at
  every schema; a record whose seal fails reads `edited`, whatever its `schema`, and
  `round` writes it again. Only a sealed record with a greater schema reads `newer`.
- **Behind names the resolution** when none of the three digests moved and the record
  still differs from the body `round` would write now (`rounds.RESOLUTION`): an
  evaluator's code, its controls, a pack or a tool. `status` and `doctor` compute that
  body (`cli._round_state`). Digesting each evaluator's code and controls into
  `computed_from` was rejected: a second copy of the cache's own keying, blind to a pack
  installed or a tool gone. A forgery resealed by hand therefore reads behind.
- **A model that does not load builds no site in `round`**, as `site build` refuses it;
  the paragraph says "Site not built: <the model's error>".
- **Instructions are compared only when both records hold the model's code.** A model
  that stops loading says "instructions not recorded (the model does not load)" (and
  `--json`'s `instructions_unrecorded`), never every file moved.
- **`why <claim>`, untraced, says only direct reads were followed** for every claim an
  evaluator settles, with or without a `rests on:` line.
- **GLOSSARY §4** gains round, choice, derived value, instructions and read by; the
  decision row's italic *choice* now says the value a decision picked is a choice.
- **The fast tier's pay-back:** the review added ~1.3 s of invariant rows and moved
  `doctor`'s round row to the gate and the graph's and the round record's bytes on
  another path to the full suite; measured flat on wall against 6440bad, +0.6 s user.

## 9. Retired

`docs/PLAN.md`, `docs/PLAN-v0.14.md`, `docs/plan/phase-1.md` to `phase-5.md`,
`docs/plan/slipped.md`, and the two test classes that read the plan's gap-map rows
(`ClosedRowsResolve`, `ClosedRowsStayClosed` in `tests/test_contracts.py`). All at
commit `a00d0e5`. Phase 1's canonical `claims/C1.json` moved into
`tests/test_records.py`.
