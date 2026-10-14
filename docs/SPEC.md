# nopekit: the architecture

Decided 2026-10-14, from an interview between the author and the agent. This is the
only plan. It replaces `docs/PLAN.md`, `docs/PLAN-v0.14.md` and `docs/plan/`, retired
at commit `a00d0e5`; ids like `D-14`, `S-60`, `R-14` and `P2.5b` in code comments and
contract documents refer to that plan and resolve against git history at that commit.

Read it top to bottom once. Strike what you disagree with; everything below has one
reason beside it, and a decision without its reason should not survive a fresh context
window.

## 0. Settled before code (2026-10-14)

The author answered these before the refactor began.

1. **"Lenses" keeps its meaning.** The pack field `lenses` stays: it names the
   adversarial review prompts the agent uses to find claims it missed. The author's
   earlier "lenses" (a parts finder, a prior-art search, a generator) are
   **proposers** (decision 25). No rename.
2. **Return conditions are structured, with a text fallback.**
   `{"claim": "C1", "quantity": "margin" | "value" | "limit", "comparator": ">",
   "value": 0.02}` is evaluated by `check`. `{"text": "..."}` is shown and never
   evaluated, and reads as not machine-checkable.
3. **Round commits use an allow list.** `nopekit.json` lists the project's people.
   The Stop hook commits a round only when git's configured identity is one of them;
   otherwise it warns and leaves the round uncommitted.
4. **Every proposer and falsifier declares its basis** (decision 38): `established`,
   `grounded` or `model-only`. The basis is shown; it does not change a claim's
   status.

Still open, not blocking: an electrical pack does not exist and the plugin
description promises PCBs; merge semantics for records edited on both sides of a
candidate branch stay ordinary git.

## 1. What nopekit is

A system of record for a design's claims, the falsifiers that have tested them, and
the history of both; plus packs that supply proposers and falsifiers per domain; plus
renderers over the record. Five intentions, which are five interfaces to one object:

1. Teach an agent the grounding-by-falsification method.
2. Give it a library of proposers and falsifiers, extensible from other repositories.
3. Interview the person, then iterate with them.
4. Keep the grounded design state in a form that reconstructs the same analysis and
   the same visualisation every time.
5. Build and keep a site that explains the state to the designer and to a newcomer.

The object is the grounded design state (paper §8): S = (T, F, L), the tradespace, the
falsification graph and the claim ledger. Everything else reads it or writes one part
of it.

## 2. Terms

| Term | Meaning |
|---|---|
| **choices** | the values a person or the agent picked: `spoke_count`, `arm_w`, a motor part number |
| **instructions** | how choices become the thing: the python, a parametric CAD file, a prompt, a Modelica model. Derivations (`duct_r_in = prop_r + tip_gap`) live here |
| **outputs** | what the instructions produce: the mesh, the BOM, the build guide |
| **the design** | choices and instructions together. nopekit observes both; it owns neither |
| **record** | one fact in one file under `design/`, read strictly, written by the agent or by a command |
| **verdict** | one gate's outcome on one set of inputs, keyed by the hash of what it read (ρ). Immutable |
| **judgement** | what the verdicts justify saying now: every claim's status, composed by the resolver. Derived, tracked, clock-free |
| **grounded design state** | the checkout: records, the design, the verdict cache, the judgement |
| **groundspace** | the sequence of states: the git history |
| **candidate** | a design that differs from HEAD by a set of choice overrides, with a disposition |
| **requirement** | what the person asked for, in their words |
| **claim** | a statement a mechanism can settle, derived from a requirement, with an acceptance condition |
| **mechanism** | what would settle a claim: a gate, a person, a kid with an afternoon, a reddit post and a sentiment pass. Every claim names one |
| **round** | one unit of the agent's work: ends when its turn ends, with a commit |
| **pack** | one domain's proposers and falsifiers, with skills, views and site partials |
| **group** | a named set of gates the map draws as one lane and the site explains as one section |
| **map** | the deterministic drawing of the judgement: the PETGasus transit pattern |
| **poster** | the per-group section of the site: a generated floor plus the agent's chosen figures and prose |

## 3. What stays

1. **The fifteen invariants** in `CLAUDE.md` and the tests that hold them. Nothing
   below weakens one.
2. **Git is the groundspace.** A checkout is one state; commits are the history. No
   second history store, no snapshot per round. Reason: git already has parent
   pointers, authorship, signing and merges; a copy of that inside the tree is the
   duplication this design exists to avoid, and agents already speak git.
3. **One record per file, read strictly.** `results/` and `exports/` stay sealed and
   chained.
4. **The verdict cache** is the evidence ledger and the execution record. Nothing
   replaces it.
5. **Qualification**: controls, mutation testing for non-bundled gates, operating
   context, the human channel for results and ownership.
6. **Stdlib-only spine, no server, no database, no build step for the site.** A
   database does not diff in a pull request; `ledger.json` already is the query index.
7. **The site never computes truth.** Static, deployable as committed.
8. **Three-tier pack disclosure** and the pack admission bar.
9. **The model owns values and rationale** (METHOD rule 1). See decision 10 for the
   reversal that put this back.

## 4. Decisions

### The state

10. **Records observe the design; they do not own its values.** `design/params/` is
    what the tracer saw when the instructions ran: every value read, which were
    choices and which were derived from what, with the rationale the adapter read out
    of the instruction layer. *Rejected:* values in records, the model reading them
    like Android string resources. Choices and instructions are not separable in
    practice (`plate_layout = "topopt"` is a choice that selects an instruction
    path), so records would hold the easy third of the state and claim to be its
    source, and a model reading files blinds the tracer.
    Each instruction layer needs an adapter that exposes its choices and provenance;
    python's docstring and `PARAMS` convention is the first. A layer with no adapter
    shows its choices with no rationale, visibly.
11. **Instructions are nodes.** `geometry.py`, a CAD file, a prompt each carry a
    content hash and a place on the map between inputs and derived values. A geometry
    edit reads as "this instruction changed, these stations moved."
12. **Requirements are records**, in the person's words, from the interview. Claims
    point at the requirement they derive from. The map's left edge is this column.
13. **Every claim names its mechanism**, plus the gate pointer when one exists.
    Replaces `terminal` and `note`. A claim with no gate reads Gap with its mechanism
    shown; that text is the query for `gap --propose` and for anything that builds
    new falsifiers. Reason: every claim is settleable; some are expensive. "Looks
    cool" is settled by a reddit post and a sentiment pass, latency one week. The
    status says the mechanism has not run, never that nothing can check it.
14. **Decisions get typed rejections and return conditions** (paper §7.4):
    infeasible, dominated, preferred against, unevaluated; each with a condition a
    machine can evaluate and a pointer to the input it came from. Preferred-against
    names who, why and when to reconsider.
15. **Candidates are records.** `design/candidates/<id>.json` holds the choice
    overrides that define it, what it was compared against, its disposition, who, why
    and the return condition. The tree never holds a sha. Explored on a branch, tagged
    `cand/<id>` by convention when rejected; `doctor` warns when the tag is missing.
    `check` evaluates return conditions and reports a candidate that may return.
    *Rejected:* a branch alone (says what, not why; cannot be acted on; one
    `git branch -D` from gone); a sha in the record (self-reference across the
    boundary, unstable under rebase). A candidate that differs in instructions, not
    choices, says `overrides: code` and the tag matters more.
16. **The state holds one candidate.** Several at once are branches. A sweep over
    fifty values is an evaluator's work and produces evidence on one claim, not fifty
    candidates. Heavy for set-based exploration of hundreds; fine for one agent and
    one person.
17. **Groupings are records.** `design/groups/` names gate groups, input zones and
    plain labels. The map's lanes and the site's sections share it.
18. **The judgement is tracked.** `.nopekit/judgement.json`: statuses, counts, the
    graph with typed edges, clock-free, written by `check`, regenerated after a merge,
    never hand-merged. Replaces the record half of `last_check.json` and of the site's
    `state.json`. Reason: a pull request that flips C1 from pass to fail shows as a
    one-line diff; a rare history walk reads it from `git show` without re-judging
    under a newer nopekit. `check` refuses to trust a judgement whose digest it did
    not compute.
19. **Edges are typed.** `reads`, `settles`, `requires` (paper §4), plus `rests_on`
    (a pass that depends on an assumption: the amber case), `resolves` (a physical
    test that replaces an assumption) and `contradicts` (the evaluator track record).
    Propagation rules differ per type; the renderer never infers meaning from line
    style.

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
    `extract`; the options it found are kept or dropped in a decision record. No
    proposal record.
23. **`nopekit merge <branch>`.** Does the git merge, writes the loser records, tags
    them, regenerates the judgement, commits, pushes the tags. One command, the
    shape of `claim physical`: its only job is to make three facts hold in one step.
    Preferred-against is refused from an agent session. A merge without a record
    leaves the losers undisposed, not decided.
24. **Rounds are layered.** The map rebuilds on every `check`; it is generated,
    stamp-free and self-consistent at every check. The poster prose and the commit
    happen when the agent's turn ends, enforced by the Stop hook: commit what checks
    clean, warn about what does not, never block. A round without a commit is lost;
    the hook is what prevents that. *Rejected:* every write (half-states), a
    `nopekit round` the agent must remember, a state event (hours pass without one).

### Packs

25. **A pack holds proposers and falsifiers** for one domain, plus skills, views and
    site partials. Project-local packs live in `packs/<name>/` with a reserved
    prefix, replacing root `gates/`, `selftest/`, `views/`, `generators/`. Promoting
    one to a repository is a move.
26. **Extension repositories** add a pack or extend one (`extends: sourcing`). An
    extension gate is qualified at the non-bundled bar regardless of namespace, may
    only add ids and never shadow one. Pinned by source and version in `nopekit.json`;
    a registry file in this repository indexes what each settles.
27. **Track records are portable.** `.nopekit/track/` entries carry gate, version,
    operating context and outcome in a project-free schema. Upstream flow is
    deferred: pull requests to pack repositories when anyone wants to send one, a
    service only if aggregation across projects becomes a question. Reason: the paper
    (§7.3) says a track record attaches to its operating context and transfer cannot
    be assumed, so cross-project scores are research, not infrastructure.

38. **Proposers and falsifiers declare a basis**, in a fixed order of preference.
    `established`: wraps an existing non-AI tool with its own track record (KiCad's
    layout optimizer or DRC, OpenModelica, trimesh). `grounded`: built by an LLM,
    and its answers come from an outside source it reads (a parts search over a
    catalogue, a datasheet lookup, a cited textbook formula). `model-only`: built by
    an LLM with no basis outside the model. The agent uses the highest basis
    available and says why when it goes lower. An input a proposer produced carries
    that proposer's basis, so a parameter grounded by a model-only input shows as
    weakly grounded. The basis appears in `gate list`, the map and the report; it
    does not change a claim's status, and qualification is unchanged. Reason: the
    author's rule is "existing trusted systems first, then LLM-built systems that
    ground themselves, then LLM-built systems with no outside basis", for both
    phases.

### The site

28. **Fixed outline:** name, representation, description, map, one section per gate
    group, next steps, made with nopekit.
29. **The map follows the PETGasus transit pattern** (the author's
    `PETGasus Grounding Map.html`): inputs on the left, claim lines riding shared
    stations, ending at checks on milestone boards; amber for a pass that rests on a
    guess, dashed for stale, dotted for unchecked. Rendered from `judgement.json`
    plus `groups/`. **Order is baked, geometry is rendered:** `map.json` holds nodes
    with lane, group, status word and a stable order index, and edges; no x or y.
    The renderer uses a layered layout, no force layout, no reordering by default
    (a "failing first" sort as a viewer control is fine), and measures text after
    placement, never to decide topology. *Rejected:* baked pixel positions (wrong on
    a phone, presentation in data).
30. **Per-group sections are a poster.** A generated floor (measured-versus-limit per
    numeric gate, the evidence files the gate wrote), collapsed by default, then the
    agent's chosen figures and prose in `site/content/<group>.md`, stamped `as_of` a
    judgement digest and flagged when the judgement that touches that group has
    moved. The agent judges what is compelling, as for a conference poster; a figure
    made in the figuring-out is best, a figure made to explain is allowed when cheap.
    Every number in prose must appear in a baked file; a scan enforces it. This is the
    one place the site persuades, so the stamp matters most here.
31. **`site build` reads HEAD only.** History, stills and video are one rare on-demand
    tool (`nopekit site history <from>..<to>`) that walks git in worktrees, renders
    each judgement headless and captures frames; ffmpeg makes the video. Outside the
    spine.
32. **Baked versus rendered.** Baked: written by `site build` under `site/data/` and
    `site/assets/` from the state. Rendered: what the browser does with a baked file.
    Every number, status, word and order on the page exists in a baked file; the
    browser maps data to DOM and handles hover, selection, filters and theme. Never in
    the browser: a status, a margin, readiness, a sensitivity.
33. **Live versus published.** Local: `nopekit serve --watch` runs the tier-0 check
    and `site build` on change; the page polls `data/build.json`. Published: Pages
    serves `site/` as committed, or CI builds it. Same baked files either way.

### Style

34. **Human-facing text follows ASD-STE100** (Simplified Technical English) in every
    generated site, every README nopekit writes, and every skill's example output:
    short sentences (about 20 words), one approved word for one thing throughout,
    present tense, imperative for instructions, no contractions, no synonyms for
    variety. The PETGasus front page (commit `08c6783` in that repository) is the
    reference rewrite.
35. **No LLM register.** Text must not read as model-written. Banned: em-dash asides,
    "not X but Y", lists of three for rhythm, rhetorical questions, "delve",
    "robust", "seamless", "crucial", "honest" as self-description, a closing line
    that restates the paragraph. A scan over the template and the generated
    content holds the banned list.
36. **The badge.** Every repository nopekit creates shows
    `img/made-with-nopekit.png` linked to `github.com/neuman/nopekit`: the last
    section of the site and the bottom of the README. The badge ships in the site
    template. The mascot (`docs/img/nopey.png`, Nopey the honey badger) belongs on
    this repository's README only.

### The plugin

37. **The skill shrinks** to the method plus a command table; pack skills load by
    precedence (project `packs/`, then `~/.nopekit/packs`, then bundled), gated by
    what can run here. Paths use `${CLAUDE_PLUGIN_ROOT}` (braced; the unbraced form
    is not substituted and the variable is not in the Bash tool's environment). No
    `bin/`: hosts other than the CLI refuse a plugin that has one.

## 5. Layout

```
my-project/
  nopekit.json              name, model entry, nopekit version, packs pinned by source and version
  model/                    the instructions: owns every choice's value and rationale
  packs/<name>/             project-local packs: gates, selftest, views, proposers, skills, site partials
  design/                   the state at HEAD, one record per file
    requirements/ claims/ decisions/ candidates/ inputs/ results/ milestones/
    params/                 observed: every value read, choice or derived, with provenance
    groups/                 gate groups, input zones, plain labels
  out/                      the outputs; tracked where the person says so
  .nopekit/
    verdicts/               tracked: every verdict by ρ, every control run
    track/                  tracked: portable track records
    judgement.json          tracked, clock-free: statuses, counts, the typed graph
    cache/ obs/ index/      ignored, rebuilt
  site/
    index.html              yours, never regenerated
    content/<group>.md      agent prose per group, stamped as_of a judgement digest
    annotations.json        authored pins on the representation
    img/made-with-nopekit.png
    data/  assets/          baked by `site build`
```

## 6. Known risks

Named here so the first person to hit one knows it was seen.

- **Overrides drift from their base.** A candidate was judged against HEAD as it
  stood then. The record carries what it was compared against; the return condition
  applies to that comparison.
- **Return conditions reference claims that get edited.** A condition goes stale the
  way a verdict does, and a stale condition reads as such; it never silently fails to
  fire.
- **Claim ids collide across branches.** Two candidates each add the next id. Ids
  become non-sequential, or `merge` renumbers.
- **The judgement dirties the tree on every check that moves it.** That is the
  signal; CI must not assume a clean tree after a check.
- **The judgement will be read for truth.** It carries a header saying what it is;
  nothing in the spine reads it as input.
- **The Stop hook fires mid-thought.** It commits what checks clean and warns about
  the rest.
- **The agent can run `git merge` without the command.** The record is what carries
  the decision; an unrecorded merge leaves candidates undisposed.
- **Stamped prose ages within minutes.** The stale flag fires on a judgement change
  that touches the group, not on any change.
- **The floor is a wall of identical bars.** Collapsed by default.
- **A compelling figure can be wrong.** The stamp guards age, not correctness; the
  number scan is the only guard.
- **A parameter no gate reads is invisible.** True today; the map shows what the
  tracer saw.
- **The documents and tests are the real cost.** The glossary, the spine contract and
  the site contract describe the old shape, and several hundred tests hold it. Each
  decision above is a document rewrite and a test rewrite before it is code.

## 7. Sequence

Smallest and safest first; each step green before the next.

1. `${CLAUDE_PLUGIN_ROOT}` in the skill, so the plugin runs from an install.
2. Mechanism on the claim, replacing `terminal` and `note` (decision 13). Exercises
   the document-then-test path on something low-stakes.
3. Settle §0's three questions.
4. Requirements records and the interview (12, 21).
5. Typed rejections and return conditions on decisions (14).
6. `judgement.json` and typed edges (18, 19); `params/` as observation (10, 11).
7. Candidates and `nopekit merge` (15, 16, 23).
8. Groups, the map renderer, the site outline and the poster (17, 28 to 33).
9. Packs: project-local packs, `extends`, the registry, the rename (25 to 27, §0.1).
10. The Stop hook and rounds (24).
11. The rare history tool (31).

Migrate `examples/bracket` and PETGasus at step 6; both are the test projects.

## 8. Retired

`docs/PLAN.md`, `docs/PLAN-v0.14.md`, `docs/plan/phase-1.md` to `phase-5.md`,
`docs/plan/slipped.md`, and the two test classes that read the plan's gap-map rows
(`ClosedRowsResolve`, `ClosedRowsStayClosed` in `tests/test_contracts.py`). All at
commit `a00d0e5`.
