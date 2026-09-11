# SPDX-License-Identifier: Apache-2.0
"""atompipe.cli — the command surface, and the only place that reads the clock.

Everything below is an edge. The spine's logic lives in the other modules and is
pure; this file resolves a project root, stamps a timestamp, takes a lock, calls
one or two functions, and renders the result. When a command here starts
computing something, that computation belongs in `claims`, `report` or `gates`
instead — a rule that has a cost and is worth it: a status line derived in the
CLI is a status line that cannot be tested and that will eventually disagree
with the report.

Four conventions hold across every command:

* **Terse and greppable by default.** One line per verdict, one line per claim,
  one line per gate. `[ok  ] beam.deflection : 0.700 mm at 15 N` is a line you
  can `grep FAIL` and a line an agent can hold fifty of. Anything longer is
  behind `--json` or in `docs/readiness.md`.
* **`--json` on every read command.** Not a pretty-printer switch: the JSON is
  the same data the human output renders, so an agent never has to parse
  columns. When `--json` is given, nothing but JSON goes to stdout.
* **`AtompipeError` -> `error: <msg>` on stderr, exit 2.** No traceback: a stack
  trace teaches a user nothing about a missing file. Anything else keeps its
  traceback, because by construction it is a bug in the spine.
* **The clock is read here and nowhere else** (contract rule 3). `utcnow_iso()`
  is called in this file and the string is passed down. Every function it calls
  takes `when`/`added` as a plain argument precisely so a run can be replayed.

Exit codes, which are the actual product for the two commands anyone puts in
CI:

    0   fine
    1   a gate-level verdict says stop  — `check` with a blocking critical claim,
        `gate selftest` with a control that did not fire, `doctor` with a
        hard failure. This is what makes `atompipe check` usable as a pre-spend
        gate: it exits non-zero *while anything critical is unproven*, not only
        when something failed.
    2   the user did something the tool cannot act on (AtompipeError, bad args)
    130 interrupted

One design note worth stating because it is load-bearing and not obvious: gates
reach a project from two places. Packs the ledger opted into (`meta.packs`) come
first, and then `<root>/gates/*.py` — the project's OWN gates, which is how the
reference project in `examples/bracket` ships six gates with no pack at all. The
spine contract describes pack loading only; project-local gates are implemented
here because a project that cannot write a gate without publishing a pack would
never write the first one.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
import textwrap
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from . import __version__
from . import artifacts, claims, decisions, gates, modelio, packs, report, store
from .models import (
    Acceptance,
    ArtifactKind,
    Claim,
    ClaimKind,
    ClaimStatus,
    Comparator,
    Extraction,
    Ledger,
    PhysicalResult,
    ProjectMeta,
    RunMeta,
    Verdict,
)
from .util import (
    AtompipeError,
    FileLock,
    human_bytes,
    human_duration,
    rel,
    short_hash,
    utcnow_iso,
)

__all__ = ["main", "build_parser"]

#: Project-local gates: `<root>/gates/*.py`, imported exactly like a pack's, but
#: with no manifest and no pack name. The reference project uses this and so does
#: every project before it has a pack worth extracting.
PROJECT_GATES_DIR = "gates"

#: The lock every write-side command takes, for the whole operation. Two
#: `atompipe check` runs in one project would otherwise interleave their
#: read-modify-write of the ledger and the second would silently drop the first's
#: verdicts.
LOCK_NAME = "build.lock"

#: Tier ceiling meaning "everything". Tier is an IntEnum topping out at 3
#: (EXTERNAL); this is deliberately past it so a pack that invents a higher
#: number is still swept rather than silently skipped.
ALL_TIERS = 99


# --------------------------------------------------------------------------- #
# output
# --------------------------------------------------------------------------- #
def _say(text: str = "") -> None:
    """Print one line to stdout, flushed.

    Flushed because `check` streams a line per gate and a tier-2 sweep can sit
    for minutes between them; a buffered stdout turns "watch the gates land" into
    "watch nothing, then get everything at once", which is the same experience as
    no streaming at all.
    """
    print(text, flush=True)


def _warn(text: str) -> None:
    """A caveat that must not pollute stdout.

    Warnings go to stderr so `atompipe gate list | ...` and `--json` stay clean.
    A warning printed into a JSON document is a parse error at the other end.
    """
    print(text, file=sys.stderr, flush=True)


def _dump(obj: Any) -> None:
    """Write one JSON document to stdout: sorted keys, indent 2.

    Sorted and indented for the same reason the ledger is — this output gets
    diffed and eyeballed as often as it gets parsed.
    """
    print(json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False, default=str),
          flush=True)


def _tag(kind: str) -> str:
    """`[ok  ]`-style tag, padded to the width `Verdict.render` uses.

    Same four-character field as a verdict tag so a `doctor` line and a `check`
    line align in the same terminal and the same grep.
    """
    return f"[{kind:<4}]"


def _split_csv(value: str | None) -> list[str]:
    """`"a, b ,c"` -> `["a", "b", "c"]`. Empty pieces dropped.

    Used for every comma-separated flag (`--grounds`, `--tags`, `--gates`).
    Repeating the flag works too; this is for the spelling people actually type.
    """
    return [piece.strip() for piece in (value or "").split(",") if piece.strip()]


def _collect(values: Iterable[str] | None) -> list[str]:
    """Flatten a repeatable flag whose values may themselves be comma-separated."""
    out: list[str] = []
    for value in values or ():
        out.extend(_split_csv(value))
    return out


def _age(when: str, *, now: float | None = None) -> str:
    """`"4m 12s ago"` for an ISO stamp, or `""` if it cannot be read.

    Ages are rendered here rather than stored because a stored age is wrong one
    second later. An unparseable stamp returns empty instead of raising: a
    hand-edited `when` is a cosmetic problem, and refusing to print `status` over
    it would be a wildly disproportionate response.
    """
    try:
        stamp = datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return ""
    reference = datetime.fromtimestamp(now, tz=timezone.utc) if now is not None \
        else datetime.now(timezone.utc)
    seconds = (reference - stamp).total_seconds()
    if seconds < 0:
        # A clock that moved, or a stamp from another machine. Saying "in the
        # future" is more useful than a negative duration nobody can act on.
        return "in the future"
    return f"{human_duration(seconds)} ago"


# --------------------------------------------------------------------------- #
# project plumbing
# --------------------------------------------------------------------------- #
def _root(args: argparse.Namespace) -> str:
    """The project root for this invocation, or an AtompipeError saying there is none.

    `-C/--dir` sets where the search STARTS, not where it ends: like git, the
    walk goes up until it finds `.atompipe/`, so running from `model/` or
    `inputs/cad/` hits the same project.
    """
    return store.require_root(getattr(args, "dir", None))


def _lock(root: str) -> FileLock:
    """The build lock for `root`, as a context manager.

    Held around every command that writes. The failure it prevents is concrete:
    two runs that both load the ledger, both add verdicts and both save will lose
    one set entirely, with nothing anywhere saying so.
    """
    return FileLock(os.path.join(store.atompipe_dir(root), LOCK_NAME))


def _load_project_gates(root: str, registry: gates.Registry) -> list[Any]:
    """Import `<root>/gates/*.py` into `registry`; return the specs they added.

    The project's own gates, loaded the same way a pack's are and for the same
    reasons — the pack directory equivalent is the project root, so a gate can
    `import selftest.bad_configs` or share a `_geom.py` helper with the model.

    Three details are copied deliberately from `packs.load_gates`, because the
    two must behave identically or a gate would work in a project and break the
    moment it was extracted into a pack:

    * the root goes on `sys.path[0]` and comes off in a `finally`; a leaked entry
      makes the *next* import resolve against this project
    * module names are salted with a hash of the file's absolute path, so two
      projects in one process cannot silently share a `gates/structural.py`
    * `PACK_DIR` is NOT set, so `gates._fixture_root` falls through to `ctx.root`
      and `selftest/bad_configs.py` resolves beside the model, where it lives

    Files starting with `_` are skipped (helpers, not gates). Any failure becomes
    an AtompipeError naming the file: a gate module that will not import is a
    user's Python problem, and a spine traceback would read as a spine bug.
    """
    directory = os.path.join(root, PROJECT_GATES_DIR)
    if not os.path.isdir(directory):
        return []

    try:
        names = sorted(os.listdir(directory))
    except OSError as exc:
        raise AtompipeError(f"cannot read {rel(directory, root)}: {exc}") from exc
    files = [os.path.join(directory, n) for n in names
             if n.endswith(".py") and not n.startswith("_")]
    if not files:
        return []

    before = {spec.id for spec in registry.specs()}
    sys.path.insert(0, root)
    try:
        with gates.use_registry(registry):
            for path in files:
                stem = os.path.splitext(os.path.basename(path))[0]
                module_name = f"atompipe_project_{stem}_{short_hash(os.path.abspath(path), 8)}"
                if module_name in sys.modules:
                    continue          # ordinary import semantics: already executed
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec is None or spec.loader is None:     # pragma: no cover
                    raise AtompipeError(
                        f"{rel(path, root)}: no import machinery accepted this file")
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                try:
                    spec.loader.exec_module(module)
                except AtompipeError as exc:
                    # A registry refusal (no negative control) is already phrased
                    # for a human. Keep the phrasing, add the location.
                    sys.modules.pop(module_name, None)
                    raise AtompipeError(f"{rel(path, root)}: {exc}") from exc
                except BaseException as exc:
                    sys.modules.pop(module_name, None)
                    raise AtompipeError(
                        f"{rel(path, root)} failed to import: "
                        f"{type(exc).__name__}: {exc}"
                    ) from exc
    finally:
        try:
            sys.path.remove(root)
        except ValueError:            # pragma: no cover - a gate mangled sys.path
            pass
    return [spec for spec in registry.specs() if spec.id not in before]


def _registry(root: str, ledger: Ledger, *,
              strict: bool = True) -> tuple[gates.Registry, list[str]]:
    """Load every gate this project can see. Returns `(registry, problems)`.

    Packs first (in `meta.packs` order, which is gate-id precedence), then the
    project's own `gates/`. The module-level `gates.REGISTRY` is the target
    because a CLI process serves exactly one project and a private registry would
    buy nothing but a layer.

    `strict=False` turns a broken pack into a *reported* problem instead of an
    exception, and only `status` and `doctor` use it. The distinction matters:
    `doctor` exists to tell you your pack is broken, so it must survive a broken
    pack; `check` must not, because a sweep that silently ran two packs out of
    three would publish an UNCLAIMED section that is an artefact of an import
    error rather than a statement about the design.
    """
    registry = gates.REGISTRY
    problems: list[str] = []
    for label, load in (
        ("packs", lambda: packs.load_all_gates(packs.installed(root, ledger=ledger),
                                               registry, root)),
        ("project gates", lambda: _load_project_gates(root, registry)),
    ):
        try:
            load()
        except AtompipeError as exc:
            if strict:
                raise
            problems.append(f"{label} did not load: {exc}")
    return registry, problems


def _projection(root: str, ledger: Ledger, *, entry: str | None = None) -> tuple[Any, dict | None]:
    """Load the model and build its projection, or `(None, None)` if there is none.

    A project with no `meta.model_entry` is a normal, early state — claims and
    evidence come before the model — so that case returns None rather than
    raising. A model entry that IS recorded and does not load is a different
    thing entirely and propagates: the model is the single source of truth, and a
    check run against a model that failed to import proves nothing about
    anything.
    """
    target = (entry or ledger.meta.model_entry or "").strip()
    if not target:
        return None, None
    model = modelio.load_model(root, target)
    return model, modelio.project(model)


def _projection_safe(root: str, ledger: Ledger) -> tuple[Any, dict | None, str]:
    """`_projection`, with the failure returned instead of raised.

    For `status` and `doctor`, which have to keep working on a project whose
    model is mid-edit — that is precisely when someone runs them.
    """
    try:
        model, projection = _projection(root, ledger)
    except AtompipeError as exc:
        return None, None, str(exc)
    return model, projection, ""


def _flat_params(projection: dict | None) -> tuple[dict[str, Any], list[str]]:
    """Flatten a projection to `{name: value}` for `GateContext.params`, with conflicts.

    Derived values first, then config over the top, so an INPUT always wins a
    name collision. `build()` returning a key that shares a config field's name
    is common and harmless when the values agree (the reference model echoes
    `material` straight back); when they do NOT agree, one of the two numbers a
    gate could read is not the model's input, and which one it got would depend
    on dict ordering. So the input wins, and the disagreement is returned to be
    reported rather than resolved silently — that is rule 6, cross-representation
    agreement, applied at the cheapest place it can be applied.
    """
    if not projection:
        return {}, []
    config = dict(projection.get("config") or {})
    derived = dict(projection.get("derived") or {})
    conflicts = [
        f"{name}: config {config[name]!r} vs build() {derived[name]!r}"
        for name in sorted(set(config) & set(derived))
        if config[name] != derived[name]
    ]
    flat = dict(derived)
    flat.update(config)
    return flat, conflicts


def _staleness(ledger: Ledger, projection: dict | None) -> tuple[bool, str]:
    """Have the model or the inputs moved since the last recorded sweep?

    This is the one comparison that stops a green report from being a lie about a
    design nobody has re-checked. It is computed here, at the edge, and passed
    into `claims`/`report` as a flag, because those modules must resolve the same
    ledger identically on two machines and a resolver that read the model could
    not (see `claims.resolve_status`).

    Judged against `RunMeta`, not against the verdicts, because a `Verdict` has
    nowhere to record which model it measured. The consequence is honest but
    coarse, and `check` compensates: a `--only` sweep deliberately does not
    advance `last_run`, so the verdicts it did not refresh keep reading stale.
    """
    run = ledger.last_run
    if not run.when:
        return False, "no sweep recorded yet"
    reasons: list[str] = []
    if projection is not None and run.model_hash:
        current = modelio.model_hash(projection)
        if current != run.model_hash:
            reasons.append(f"model {run.model_hash} -> {current}")
    current_inputs = artifacts.inputs_hash(ledger)
    if run.inputs_hash and current_inputs != run.inputs_hash:
        reasons.append(f"inputs {run.inputs_hash} -> {current_inputs}")
    return bool(reasons), "; ".join(reasons) or "unchanged since the last sweep"


#: Parameter sync lives in `modelio.sync_params` and NOWHERE ELSE.
#:
#: There used to be a second implementation right here, and `cmd_check` called
#: both of them twelve lines apart. This one rebuilt `ledger.params` from the
#: model and carried over only `grounded_by`, `gates`, `tags` and `changed_in`,
#: so every `atompipe check` silently deleted `Param.rejected` — the record of
#: what was TRIED AND LOST, which rule 3 calls the highest-value field in the
#: system — and `Param.source` along with it. A project could accumulate a year
#: of rejected alternatives in the ledger and have the inner-loop command wipe
#: them on the next run, with nothing printed and nothing to diff against.
#:
#: `modelio.sync_params` merges the other way round — it keeps the ledger's
#: whole record and replaces only value/units/rationale/derived_from, the four
#: fields the model actually owns — so it is the only one that survives. If a
#: merge is ever needed again, extend that function; do not write a second one
#: here, because two merges in one process will disagree and the destructive one
#: always runs last.


def _link_grounding(ledger: Ledger) -> list[str]:
    """Write the back-reference an extraction implies. Returns names that match nothing.

    `Extraction.grounds` points outward ("this photo grounds `hull_beam`"), and
    `artifacts.grounding` inverts that on demand — but `Param.grounded_by` and
    `Claim.grounded_by` are the *stored* form of the same edge, and
    `decisions.why` reads only the stored one. Without this, an agent that
    ingested a datasheet, extracted the figure and grounded a parameter on it
    would still be told by `atompipe why` that the parameter is "asserted, not
    evidenced" — the exact opposite of what happened.

    Idempotent (ids are added once) and additive only: an edge a human declared
    by hand is never removed here, because this function cannot tell a
    hand-declared edge from a stale one and guessing wrong deletes provenance.

    Names that match no parameter and no claim are returned rather than dropped.
    They are usually an ordering artefact — the extraction was recorded before
    the model declared the parameter — and they resolve themselves on the next
    `check`. A typo looks the same from here, so the caller says so out loud.
    """
    from_extractions = artifacts.grounding(ledger, include_declared=False)
    unmatched: list[str] = []
    for name, artifact_ids in from_extractions.items():
        param = ledger.param(name)
        claim = ledger.claim(name)
        target = param or claim
        if target is None:
            unmatched.append(name)
            continue
        current = list(target.grounded_by or [])
        for artifact_id in artifact_ids:
            if artifact_id not in current:
                current.append(artifact_id)
        target.grounded_by = current
    return sorted(unmatched)


def _refresh_coverage(ledger: Ledger, registry: gates.Registry) -> None:
    """Write live gate coverage into `claim.gates`. Only `check` may call this.

    `claim.gates` is a cache of a fact the registry owns, and `claims.py` says so
    in as many words. The cache still has to exist, because the things that read
    a ledger WITHOUT a registry — `decisions.why` above all — otherwise report
    "no gate can settle it" for a claim three gates are covering. An agent that
    trusts that sentence goes off to install a solver the project already has.

    Refreshed only in `check`, and refreshed by REPLACEMENT rather than union,
    because `check` is the one command that has loaded every pack the ledger
    declares (`_registry(strict=True)` refuses to proceed otherwise). So the
    coverage it computes is the project's complete gate set at that moment, and
    a stale id left over from a pack that was removed should disappear rather
    than keep a dead gate's name on a claim forever.
    """
    live = claims.coverage(ledger, registry)
    for claim in ledger.claims:
        claim.gates = live.get(claim.id, [])


class _ParamReads(dict):
    """`ctx.params`, but it remembers which keys a gate actually looked up.

    `Param.gates` — "which gate protects this number", the fourth item rule 3
    asks every constant to carry — was declared on the dataclass and then never
    assigned by anything. The visible consequence was that `atompipe why
    <param>` told every reader "GATES (0) — none: no gate would notice if this
    value went wrong" about parameters that three gates were reading on every
    sweep. That sentence is worse than no sentence: an agent that believes it
    goes off to write a gate the project already has, or edits the number
    thinking nothing measures it.

    The linkage is not stored anywhere, but it is observable: a gate reads its
    inputs out of `ctx.params`, so the keys it touches ARE the parameters it
    protects. This subclasses `dict` rather than wrapping it in a `Mapping` so
    that a gate doing anything else with the object — `.items()`, `len()`,
    `dict(ctx.params)`, a `**` splat — behaves exactly as before; only the three
    single-key accessors are intercepted.

    **One level of nesting is followed.** The projection is
    `{"config": {...}, "derived": {...}}` and `_flat_params` merges those two,
    so a gate reading a config field spells it either `ctx.params["thickness"]`
    or `ctx.params["config"]["thickness"]` — the reference project's gates use
    the second spelling for seven of their reads. Recording only the top level
    caught `config` and attributed nothing. Deeper than one level is NOT
    followed on purpose: a sourcing gate walking a BOM document would start
    attributing itself to every line-item key that happens to share a parameter
    name, which is a false positive in the generous direction.

    Bulk iteration is deliberately NOT recorded either. A gate that does `for
    name in ctx.params` has not shown interest in any particular parameter, and
    attributing all twelve to it would put a gate id on every param.

    Cost is one `set.add` per lookup and one wrapper per nested dict per sweep,
    which is what keeps it usable in the inner loop (rule 10).
    """

    def __init__(self, params: dict[str, Any], *,
                 seen: set[str] | None = None, nested: bool = False) -> None:
        super().__init__(params)
        #: Shared by reference with every nested wrapper, which is why `take()`
        #: clears this set in place instead of rebinding it. Rebinding left the
        #: children writing into a set nobody read again.
        self.seen: set[str] = set() if seen is None else seen
        self._nested = nested
        self._children: dict[Any, "_ParamReads"] = {}

    def _seen(self, key: Any) -> None:
        if isinstance(key, str):
            self.seen.add(key)

    def _wrap(self, key: Any, value: Any) -> Any:
        if self._nested or type(value) is not dict:
            return value
        child = self._children.get(key)
        if child is None:
            child = _ParamReads(value, seen=self.seen, nested=True)
            self._children[key] = child
        return child

    def __getitem__(self, key: Any) -> Any:
        self._seen(key)
        return self._wrap(key, super().__getitem__(key))

    def __contains__(self, key: Any) -> bool:
        # `GateContext.param` asks `name in self.params` before reading it, so a
        # membership test is a read as far as attribution is concerned.
        self._seen(key)
        return super().__contains__(key)

    def get(self, key: Any, default: Any = None) -> Any:
        self._seen(key)
        if not super().__contains__(key):
            return default
        return self._wrap(key, super().__getitem__(key))

    def take(self) -> set[str]:
        """Hand back the keys read since the last `take()`, and start fresh."""
        seen = set(self.seen)
        self.seen.clear()
        return seen


def _refresh_param_gates(ledger: Ledger, reads: dict[str, set[str]], *,
                         replace: bool) -> None:
    """Write "which gates read this parameter" into `Param.gates`.

    `reads` is `{gate id: names it looked up}`, collected by `_ParamReads` while
    the sweep ran. Names that are not ledger parameters are dropped: a gate
    asking for `span_mm` on a model that has no such field is telling us the
    gate wants it, not that the project has it, and inventing a Param row from a
    failed lookup would put phantom numbers in the ledger.

    A gate that SKIPPED still counts. It read the parameter, found it missing or
    found its tool absent, and would have measured it — which is exactly the
    question `atompipe why` is answering. What it must never do is imply the
    value was checked; that is `Verdict`'s job and a skip is never a pass.

    `replace=False` for a `--only` sweep, for the same reason such a sweep does
    not advance `last_run`: it saw a subset of the gates, so overwriting the
    full picture with the subset would quietly retire every gate it did not run.

    The honest limit, stated because the field will be read as stronger than it
    is: this records a DIRECT read. A gate that reads the derived `deflection`
    protects `arm_length` in physical fact, but nothing in the projection says
    which inputs that derived value came from, so `arm_length` still ends up
    with an empty list. An empty `Param.gates` therefore means "no gate reads
    this value by name", which is weaker than "nothing would notice if it
    changed" — and the fix for a parameter that deserves better is to name it in
    a gate, which is the right outcome anyway.
    """
    known = {param.name for param in ledger.params}
    by_param: dict[str, list[str]] = {}
    for gate_id in sorted(reads):
        for name in sorted(reads[gate_id]):
            if isinstance(name, str) and name in known:
                by_param.setdefault(name, []).append(gate_id)
    for param in ledger.params:
        found = by_param.get(param.name, [])
        if replace:
            param.gates = found
        else:
            merged = list(param.gates or [])
            merged.extend(gate_id for gate_id in found if gate_id not in merged)
            param.gates = merged


def _skip_digest(skipped: list[Verdict], *, width: int = 96) -> list[str]:
    """Collapse a wall of `[skip]` lines into one line per distinct REASON.

    `atompipe check` is the inner-loop command, and once a few packs are
    installed it was measured at 37 lines carrying seven informative verdicts:
    26 skip lines repeating five reasons verbatim, because every gate in a pack
    skips for the same missing field. An agent reading that scrolls past the one
    FAIL it ran the command for. The reason is the actionable half ("add
    `volume_mm3` to the model"), and it is identical across the group, so it is
    printed once with the gate ids behind it.

    Sorted by group size descending, then by reason, so the biggest single thing
    to fix is the first line you read. The reason text is NOT truncated: it names
    the field to add, and a digest that drops that is a digest that sends the
    reader back to the un-collapsed output.

    A reason with exactly one gate behind it renders as the ordinary verdict
    line. Grouping a group of one cost a second line to say "1 gate" and made
    the digest LONGER than the wall it replaced — measured at 43 lines against
    the original 37 before this branch existed.
    """
    groups: dict[str, list[str]] = {}
    for verdict in skipped:
        reason = (verdict.skip_reason or verdict.detail
                  or verdict.error or "no reason recorded").strip()
        groups.setdefault(reason, []).append(verdict.gate)

    lines: list[str] = []
    for reason, gate_ids in sorted(groups.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if len(gate_ids) == 1:
            lines.append(f"{_tag('skip')} {gate_ids[0]} : {reason}")
            continue
        lines.append(f"{_tag('skip')} {len(gate_ids)} gates — {reason}")
        lines.append(textwrap.fill(", ".join(gate_ids), width=width,
                                   initial_indent="       ", subsequent_indent="       ",
                                   break_long_words=False, break_on_hyphens=False))
    return lines


def _context(root: str, ledger: Ledger, model: Any, projection: dict | None,
             tier: int, *, quiet: bool = False) -> gates.GateContext:
    """Build the one argument every gate receives.

    `model` is the `modelio.LoadedModel`, not the bare module: it carries the
    module, the resolved config, the entry path and the params, and a gate that
    only wants the module reaches it as `ctx.model.module`. Handing over the
    richer object costs nothing and saves the gate from re-deriving what the
    loader already resolved.

    `log` goes to stderr so a gate's progress chatter never lands inside `--json`
    output, and is silenced entirely under `--json` because a caller parsing
    stdout is usually not reading stderr either.
    """
    params, conflicts = _flat_params(projection)
    for conflict in conflicts:
        _warn(f"warning: model and build() disagree on {conflict} — "
              f"gates read the config value")
    # A DEFENSIVE COPY, not the live ledger. Gate code is third-party: a pack is an
    # ordinary directory anyone can drop in, and `cmd_check` saves the ledger after
    # the sweep. Handing over the real object let a gate append its own Verdict —
    # for a gate that never ran — or clear a critical claim, and the save wrote it
    # straight to disk. The only writes that reach the ledger are the verdicts
    # `run_all` RETURNS, which `run_gate` has already stamped with the true gate id,
    # tier and claims, so a gate cannot forge a row for anything but itself.
    #
    # Gates legitimately need to READ the ledger (a sourcing gate reads the BOM
    # claims, a report gate reads the decisions), so it stays available — just not
    # as a writable handle on the thing about to be persisted.
    return gates.GateContext(
        root=root,
        ledger=Ledger.from_dict(ledger.to_dict()),
        model=model,
        params=params,
        out_dir=store.out_dir(root),
        tier=int(tier),
        log=(lambda message: None) if quiet else (lambda message: _warn(f"    {message}")),
        extra={},
    )


def _verdict_row(verdict: Verdict) -> dict[str, Any]:
    """One verdict as JSON. `ok` is included because `passed` alone is not the answer.

    `passed` is True on a verdict that was skipped or errored only if a gate set
    it that way, and consumers reach for the obvious field. `ok` is
    `passed and not skipped and not error` — the single field that answers "did
    this prove anything", spelled out so nobody downstream has to reimplement the
    three-way distinction and get it wrong in the generous direction.

    Optional fields that are empty are OMITTED. `atompipe check --json` on a
    project with five packs installed measured 20,207 characters, most of it
    `"detail": "", "error": "", "evidence": [], "skip_reason": "", "units": ""`
    repeated once per gate — thousands of tokens of an agent's context spent
    carrying the absence of information. An absent key and an empty string say
    the same thing to a reader and one of them is free.

    `measured` and `limit` are dropped only when they are None, never when they
    are falsy. A gate that measured exactly 0.0 measured something, and dropping
    that row would turn a real reading into "this gate reported no number" —
    the generous-direction misread this file spends most of its comments
    refusing.
    """
    row = verdict.to_dict()
    for key in ("detail", "error", "evidence", "skip_reason", "units"):
        if not row.get(key):
            row.pop(key, None)
    for key in ("measured", "limit"):
        if row.get(key) is None:
            row.pop(key, None)
    # 4dp is ~0.1 ms. A tier-0 gate reports `1.6689300537109375e-05` otherwise,
    # which is 22 characters saying "instant" in the least readable way available.
    row["duration_s"] = round(float(row.get("duration_s") or 0.0), 4)
    row["ok"] = verdict.ok
    return row


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #
def cmd_init(args: argparse.Namespace) -> int:
    """Create the project layout, the starter ledger, and the next three steps.

    The last part is not decoration. `init` that prints "initialised." leaves a
    new user staring at eight empty directories with no idea which one is theirs,
    and the most common outcome is a project whose model gets written before any
    evidence is gathered — which is how numbers arrive with no provenance and
    stay that way. The three steps are printed in the order that produces a
    project with grounds: ask for evidence, write the claims it supports, then
    the model.
    """
    root = os.path.abspath(getattr(args, "dir", None) or os.getcwd())
    name = (args.name or os.path.basename(root.rstrip(os.sep)) or "project").strip()
    meta = ProjectMeta(
        name=name,
        summary=(args.summary or "").strip(),
        created=utcnow_iso(),
        revision=(args.revision or "v0.1").strip(),
        model_entry=(args.model or "").strip(),
        packs=_collect(args.pack),
        spine_version=__version__,
    )
    ledger = store.init(root, meta)
    paths = store.project_paths(root)

    if args.json:
        _dump({
            "root": root,
            "ledger": rel(paths["ledger"], root),
            "meta": ledger.meta.to_dict(),
            "next": [
                "atompipe ask",
                "atompipe claim add --statement ... --quantity ... --cmp '<=' --limit ...",
                "atompipe model --set-entry model/<thing>.py",
            ],
        })
        return 0

    _say(f"initialised atompipe project {name!r} at {root}")
    _say(f"  {rel(paths['ledger'], root):<24} the whole project state — claims, evidence,"
         f" decisions")
    _say(f"  {'inputs/':<24} evidence you put in by hand ({len(store.INPUT_BUCKETS)} buckets)")
    _say(f"  {'model/':<24} the parametric model: the only source of truth")
    _say(f"  {'docs/':<24} generated readiness report and decision log")
    _say("")
    _say("next, in this order:")
    _say("  1. atompipe ask                 — what evidence to ask for, then")
    _say("     atompipe ingest <files> --kind sketch --desc '...'")
    _say("     atompipe extract <id> --what '...' --grounds <param>   (an artifact with")
    _say("     no extraction is decoration)")
    _say("  2. atompipe claim add --statement 'floats with the full payload at <=60% draft' \\")
    _say("       --quantity 'draft fraction' --cmp '<=' --limit 0.6 --units ''")
    _say("  3. write model/<thing>.py — a dataclass CONFIG plus build(config) -> dict —")
    _say("     then: atompipe model --set-entry model/<thing>.py && atompipe check")
    return 0


# --------------------------------------------------------------------------- #
# status
# --------------------------------------------------------------------------- #
def cmd_status(args: argparse.Namespace) -> int:
    """The one-screen answer to "where is this project".

    `report.render_terminal` does the claim/gap/gate half. Everything appended
    here is a fact that lives outside the readiness report and that someone
    reading it needs anyway: which packs are in play, whether the model still
    matches the last sweep, how old that sweep is, and the NAMES (not counts) of
    the artifacts nobody read and the parameters nobody defended. The report
    counts those; a count tells you there is work and not where it is.

    Never fails on a broken pack or an unloadable model — both are reported as
    lines. `status` is what you run when something is wrong.
    """
    root = _root(args)
    ledger = store.load(root)
    registry, problems = _registry(root, ledger, strict=False)
    model, projection, model_error = _projection_safe(root, ledger)
    stale, stale_why = _staleness(ledger, projection)

    installed = packs.installed(root, ledger=ledger)
    available = packs.available(root)
    unread = artifacts.unextracted(ledger)
    undefended = [p.name for p in ledger.params if not (p.rationale or "").strip()]
    summary = claims.summarise(ledger, registry, stale=stale)
    resolved = claims.statuses(ledger, stale=stale, registry=registry)

    if args.json:
        _dump({
            "root": root,
            "meta": ledger.meta.to_dict(),
            "summary": summary,
            "claims": {cid: str(status) for cid, status in resolved.items()},
            "gaps": [need.to_dict() for need in claims.find_gaps(ledger, registry)],
            "stale": stale,
            "stale_reason": stale_why,
            "model": {
                "entry": ledger.meta.model_entry,
                "loaded": projection is not None,
                "error": model_error,
                "hash": modelio.model_hash(projection) if projection else "",
                "undocumented_params": undefended,
            },
            "packs": {"installed": installed, "available": available},
            "inputs": {
                "total": len(ledger.inputs),
                "unextracted": [a.id for a in unread],
            },
            "last_run": ledger.last_run.to_dict(),
            "last_run_age": _age(ledger.last_run.when),
            "problems": problems,
        })
        return 0

    sys.stdout.write(report.render_terminal(ledger, registry, stale=stale))

    entry = ledger.meta.model_entry or "(none recorded)"
    if model_error:
        _say(f"model: {entry} — DOES NOT LOAD: {model_error.splitlines()[0]}")
    elif projection is not None:
        _say(f"model: {entry} — hash {modelio.model_hash(projection)} ({stale_why})")
    else:
        _say(f"model: {entry} — set one with `atompipe model --set-entry model/<thing>.py`")

    if installed:
        _say(f"packs: {', '.join(installed)} "
             f"({len(available)} available: {', '.join(available[:6]) or 'none'})")
    elif available:
        _say(f"packs: none installed; {len(available)} available "
             f"({', '.join(available[:6])}) — `atompipe packs add <name>`")

    if ledger.last_run.when:
        age = _age(ledger.last_run.when)
        _say(f"last sweep: {ledger.last_run.when} ({age}), tier {ledger.last_run.tier}, "
             f"{human_duration(ledger.last_run.duration_s)}")
    else:
        _say("last sweep: never — `atompipe check`")

    if unread:
        names = ", ".join(a.id for a in unread[:5])
        more = f", +{len(unread) - 5}" if len(unread) > 5 else ""
        _say(f"unread evidence: {names}{more} — `atompipe extract <id> --what ...`")
    if undefended:
        names = ", ".join(undefended[:5])
        more = f", +{len(undefended) - 5}" if len(undefended) > 5 else ""
        _say(f"undefended params: {names}{more} — no rationale recorded")
    for problem in problems:
        _say(f"{_tag('FAIL')} {problem}")
    return 0


# --------------------------------------------------------------------------- #
# check
# --------------------------------------------------------------------------- #
def cmd_check(args: argparse.Namespace) -> int:
    """Run the gates, record the run, and exit non-zero while anything critical blocks.

    The whole loop lives in this function: load the model, project it, load the
    gates, sweep them at the requested tier, stream one line each as they land,
    write the verdicts into the ledger, append the run to the history, then ask
    `claims.blocking` whether a spend would be reckless.

    Exit 1 on a blocking critical claim is the point of the command. It is not
    "exit 1 if a gate failed" — an UNCLAIMED, PENDING or BLOCKED critical claim
    blocks too, because none of them is evidence and all of them are routinely
    read as "no news is good news". That is what makes this usable as a pre-spend
    gate and in CI.

    `--only` deliberately does NOT advance `last_run`. A filtered sweep leaves
    most verdicts untouched, and advancing the recorded model hash would launder
    every one of those older verdicts into "current" — the exact staleness lie
    the hash exists to catch. So a filtered run records its history file, updates
    the verdicts it actually produced, and leaves the staleness clock where it
    was.
    """
    root = _root(args)
    tier = int(args.tier)
    only = list(args.only) if args.only else None

    with _lock(root):
        ledger = store.load(root)
        registry, _ = _registry(root, ledger, strict=True)
        model, projection = _projection(root, ledger)
        # Refresh the ledger's parameter records from the model before sweeping.
        # The model owns every value; the ledger owns the provenance accumulated
        # around it (rejected alternatives, grounding, which gates protect it).
        # Without this the ledger's params stay empty forever and `atompipe why`
        # — the whole point of recording provenance — can never find anything.
        # ONE call, to `modelio.sync_params`: see the note above `_link_grounding`
        # for the second implementation that used to run here and the field it ate.
        if model is not None:
            modelio.sync_params(ledger, model)
        # After the sync, not before: a parameter that only just appeared in the
        # ledger is exactly the one whose evidence has been waiting to attach.
        _link_grounding(ledger)
        _refresh_coverage(ledger, registry)
        ctx = _context(root, ledger, model, projection, tier, quiet=args.json)

        if projection is None and registry.specs():
            _warn("warning: no model entry recorded — gates that read ctx.params "
                  "will error. `atompipe model --set-entry model/<thing>.py`")

        # Record which parameters each gate reads, so `Param.gates` stops being a
        # field nothing ever assigned. `run_all` may `dataclasses.replace` the
        # context to reconcile its tier; that copies the field by reference, so
        # the same recorder survives the swap.
        reads = _ParamReads(ctx.params)
        ctx.params = reads
        param_reads: dict[str, set[str]] = {}

        def _landed(verdict: Verdict) -> None:
            # `run_all` calls this the instant a gate returns, before the next one
            # starts, which is the whole reason the attribution is per-gate and
            # not one undifferentiated pile of keys at the end of the sweep.
            param_reads[verdict.gate] = reads.take()
            # Only verdicts that RAN stream. Skips are collapsed by reason after
            # the sweep (see `_skip_digest`) — they are the rows that used to bury
            # the one FAIL the command was run for.
            if not args.json and not verdict.skipped:
                _say(verdict.render())

        started = time.perf_counter()
        verdicts = gates.run_all(registry, ctx, max_tier=tier, only=only,
                                 on_verdict=_landed)
        elapsed = time.perf_counter() - started

        swept = {verdict.gate for verdict in verdicts}
        for verdict in verdicts:
            ledger.upsert_verdict(verdict)
        _refresh_param_gates(ledger, param_reads, replace=only is None)

        run_meta = RunMeta(
            when=utcnow_iso(),
            tier=tier,
            model_hash=modelio.model_hash(projection) if projection else "",
            inputs_hash=artifacts.inputs_hash(ledger),
            spine_version=__version__,
            duration_s=round(elapsed, 4),
        )
        run_path = ""
        if not args.no_record:
            run_path = store.record_run(root, verdicts, run_meta)
            if only is None:
                ledger.last_run = run_meta
            store.save(root, ledger)

        stale, stale_why = _staleness(ledger, projection)
        blockers = claims.blocking(ledger, registry, stale=stale)
        summary = claims.summarise(ledger, registry, stale=stale)

    ran = [v for v in verdicts if v.ok]
    failed = [v for v in verdicts if not v.ok and not v.skipped and not v.error]
    skipped = [v for v in verdicts if v.skipped]
    errored = [v for v in verdicts if v.error]
    carried = [v for v in ledger.verdicts if v.gate not in swept]

    # A project with no claims has proven nothing, and this command's exit code is
    # the only part of it CI reads. It used to print "an empty ledger is not a
    # clean bill of health" and then return 0 — a message and a return code
    # disagreeing, with the machine believing the one that laundered. Zero
    # blocking claims out of zero claims is not readiness, so it is not a zero.
    ready = bool(ledger.claims) and not blockers

    if args.json:
        _dump({
            "tier": tier,
            "only": only,
            "verdicts": [_verdict_row(v) for v in verdicts],
            "counts": {"ran": len(ran), "failed": len(failed),
                       "skipped": len(skipped), "errored": len(errored)},
            "carried_over": [v.gate for v in carried],
            "summary": summary,
            "blocking": [{"claim": claim.id, "status": str(status),
                          "statement": claim.statement} for claim, status in blockers],
            "ready": ready,
            "claims_recorded": len(ledger.claims),
            "stale": stale,
            "stale_reason": stale_why,
            "run": rel(run_path, root) if run_path else "",
            "model_hash": run_meta.model_hash,
            "duration_s": run_meta.duration_s,
        })
        return 0 if ready else 1

    bits = [f"{len(verdicts)} gates", f"{len(ran)} ok"]
    if failed:
        bits.append(f"{len(failed)} FAIL")
    if skipped:
        bits.append(f"{len(skipped)} skipped")
    if errored:
        bits.append(f"{len(errored)} errored")
    _say(f"{', '.join(bits)} in {human_duration(elapsed)} — tier {tier}"
         + (f", model {run_meta.model_hash}" if run_meta.model_hash else ""))

    # The skips, one line per distinct reason instead of one per gate. They come
    # after the summary and before the blockers on purpose: the summary already
    # carries the count, and the thing you must act on has to stay at the bottom
    # of the screen where the eye lands.
    for line in _skip_digest(skipped):
        _say(line)

    if carried:
        shown = ", ".join(v.gate for v in carried[:4])
        more = f", +{len(carried) - 4}" if len(carried) > 4 else ""
        _say(f"note: {len(carried)} verdict(s) predate this sweep ({shown}{more}) — "
             f"they were not re-run")

    if not ledger.claims:
        # "ready" on a project that has never stated what must be true is the
        # laundering this whole tool exists to refuse: zero blocking claims
        # out of zero claims is not evidence of anything. Non-zero, so that the
        # exit code says the same thing this line says.
        _say("no claims recorded, so nothing was checked — an empty ledger is not a "
             "clean bill of health. `atompipe claim add --statement ...`")
        return 1

    if not blockers:
        _say("ready: no critical claim is blocking "
             "(physical and assumed claims are still listed in `atompipe report`)")
        return 0

    _say(f"BLOCKING — {len(blockers)} critical claim(s) must not be spent against:")
    for claim, status in blockers:
        reason = _blocking_reason(ledger, claim, status)
        _say(f"{_tag(str(status)[:4])} {claim.id} {claim.statement} — {reason}")
    return 1


def _blocking_reason(ledger: Ledger, claim: Claim, status: ClaimStatus) -> str:
    """The shortest true sentence about why one claim blocks.

    A failing gate's own detail beats any phrasing invented here: it carries the
    measured value and the limit, which is what the reader is about to go and
    change. Only when no verdict speaks does this fall back to naming the status.

    THE REASON MUST MATCH THE STATUS. Several gates can cover one claim, and the
    first non-passing one is not necessarily the one that set the status: a claim
    covered by a project gate that FAILED and a pack gate that SKIPPED for a
    missing parameter was reporting `[fail] C1 ... — pack.gate: the projection
    does not provide ...`, which sends the reader to look for a missing parameter
    when the real answer is that their part sags 0.7 mm. So a FAIL cites a gate
    that actually ran and failed, in preference to one that skipped or errored.
    """
    covering = list(claims.covering_verdicts(claim, ledger.verdicts))
    # Real measurements first: a gate that RAN and failed explains a FAIL. Then
    # errors (a crash is louder than a missing tool), then skips.
    ranked = (
        [v for v in covering if not v.ok and not v.skipped and not v.error]
        + [v for v in covering if v.error]
        + [v for v in covering if v.skipped]
    )
    for verdict in ranked:
        body = verdict.detail or verdict.error or verdict.skip_reason
        return f"{verdict.gate}: {body}" if body else f"{verdict.gate} did not pass"
    if status is ClaimStatus.UNCLAIMED:
        return "no gate covers it — `atompipe gap --propose`"
    if status is ClaimStatus.PENDING:
        return "its gates have never run"
    if status is ClaimStatus.BLOCKED:
        return "its gates could not run here (missing tooling)"
    if status is ClaimStatus.STALE:
        return "it passed against a model that has since moved"
    return str(status)


# --------------------------------------------------------------------------- #
# ask / ingest / inputs / extract
# --------------------------------------------------------------------------- #
def cmd_ask(args: argparse.Namespace) -> int:
    """Print what evidence to request from the human, as questions to paste.

    This is the command an agent runs before it starts guessing numbers. The
    ordering and the cap come from `artifacts.requests_by_kind` — kinds with
    nothing at all first, breadth before depth, six by default because that is
    what a person answers in one sitting.

    The output is deliberately plain prose with a number in front: these lines
    get said to a human, and a taxonomy prefix ("sketch: ...") makes them read
    like a form. The bucket each answer lands in is printed after the question,
    for the agent, not for the person being asked.
    """
    root = _root(args)
    ledger = store.load(root)
    if args.kind:
        pairs = [(args.kind, prompt) for prompt in artifacts.prompts_for(args.kind)]
    else:
        pairs = artifacts.requests_by_kind(
            ledger, project_kind=args.about or ledger.meta.summary, limit=args.limit)

    if args.json:
        _dump({
            "requests": [{"kind": kind, "prompt": prompt,
                          "bucket": artifacts.bucket_for(kind)} for kind, prompt in pairs],
            "have": sorted({str(a.kind) for a in ledger.inputs}),
        })
        return 0

    if not pairs:
        _say("nothing to ask for: every artifact kind has enough evidence. "
             "`atompipe inputs --unextracted` for what arrived and was never read.")
        return 0

    _say("ask for these, in this order:")
    for index, (kind, prompt) in enumerate(pairs, start=1):
        bucket = artifacts.bucket_for(kind)
        where = f"  -> inputs/{bucket}/" if bucket else ""
        _say(f" {index}. {prompt}{where}")
    _say("")
    _say("then: atompipe ingest <file> --kind <kind> --desc '<what it shows>'")
    _say("and:  atompipe extract <artifact-id> --what '<what it says>' --grounds <param>")
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    """Take one or more real files (or URLs) into the project as evidence.

    Every path is filed, hashed and registered; a `http(s)://` argument is
    registered as a link instead, with no fetch — the spine never touches the
    network.

    The reminder at the end is not filler. Ingesting is the half people do; the
    half they drop is `extract`, and an artifact with no extraction grounds
    nothing, proves nothing, and makes the project *look* evidenced in the file
    listing while not one parameter traces back to it.
    """
    root = _root(args)
    when = utcnow_iso()
    landed: list[Any] = []

    with _lock(root):
        ledger = store.load(root)
        for source in args.paths:
            if source.startswith(("http://", "https://")):
                artifact = artifacts.ingest_link(
                    root, ledger, source, description=args.desc,
                    kind=args.kind or ArtifactKind.LINK, when=when)
            else:
                artifact = artifacts.ingest(
                    root, ledger, source, kind=args.kind, description=args.desc,
                    when=when, copy=not args.no_copy, licence=args.licence,
                    note=args.note)
            landed.append(artifact)
        store.save(root, ledger)

    if args.json:
        _dump({"ingested": [a.to_dict() for a in landed],
               "inputs_hash": artifacts.inputs_hash(ledger)})
        return 0

    for artifact in landed:
        where = artifact.path or artifact.url
        size = f"  {human_bytes(artifact.bytes)}" if artifact.bytes else ""
        _say(f"{artifact.id:<20} {str(artifact.kind):<12} {where}{size}")
    _say(f"{len(landed)} artifact(s) registered. An artifact with no extraction is decoration:")
    for artifact in landed[:3]:
        _say(f"  atompipe extract {artifact.id} --what '<what it tells you>' "
             f"--grounds <param-or-claim>")
    return 0


def cmd_inputs(args: argparse.Namespace) -> int:
    """List ingested evidence; `--unextracted` lists only the decorations.

    The `[!]` marker on an unread artifact is the whole reason this listing
    exists as its own command rather than a line in `status`: a project with
    twelve files and two extractions looks grounded from the outside and is not.
    """
    root = _root(args)
    ledger = store.load(root)
    rows = artifacts.unextracted(ledger) if args.unextracted else list(ledger.inputs)
    if args.kind:
        rows = [a for a in rows if str(a.kind) == args.kind]

    if args.json:
        _dump({"inputs": [a.to_dict() for a in rows],
               "total": len(ledger.inputs),
               "unextracted": len(artifacts.unextracted(ledger)),
               "grounding": artifacts.grounding(ledger)})
        return 0

    if not rows:
        _say("no ingested artifacts match" if ledger.inputs
             else "no evidence ingested yet — `atompipe ask` for what to request")
        return 0

    for artifact in rows:
        mark = "   " if artifact.extractions else "[!]"
        where = artifact.path or artifact.url
        note = (f"{len(artifact.extractions)} extraction(s)" if artifact.extractions
                else "NEVER READ")
        _say(f"{mark} {artifact.id:<20} {str(artifact.kind):<12} {where:<40} {note}")
    unread = [a for a in rows if not a.extractions]
    if unread:
        _say(f"{len(unread)} artifact(s) nobody read anything out of. Evidence nobody "
             f"extracted from is decoration.")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    """Record what was actually read out of an artifact, and what that grounds.

    This is the step that converts a photograph into provenance: after it,
    `atompipe why <param>` can answer "what is this number standing on?" with a
    file, a sentence and a confidence, instead of silence.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        extraction = Extraction(
            what=args.what,
            grounds=_collect(args.grounds),
            confidence=args.confidence,
            note=args.note or "",
        )
        artifact = artifacts.add_extraction(ledger, args.artifact, extraction)
        unmatched = _link_grounding(ledger)
        store.save(root, ledger)

    if args.json:
        _dump(dict(artifact.to_dict(), unmatched_grounds=unmatched))
        return 0
    _say(f"{artifact.id}: {extraction.what}  [{extraction.confidence}]")
    if extraction.grounds:
        _say(f"  grounds: {', '.join(extraction.grounds)}")
        pending = [name for name in extraction.grounds if name in unmatched]
        if pending:
            _warn(f"warning: nothing in the ledger is named {', '.join(pending)} yet — "
                  f"if that is a model parameter it links on the next `atompipe check`; "
                  f"if it is a typo, nothing will ever stand on this evidence")
    else:
        _say("  grounds nothing yet — `--grounds <param-or-claim>` is what makes this "
             "traceable from the other end")
    return 0


# --------------------------------------------------------------------------- #
# claims
# --------------------------------------------------------------------------- #
def _acceptance_from(args: argparse.Namespace, existing: Acceptance | None = None) -> Acceptance:
    """Build (or patch) an `Acceptance` from the threshold flags.

    Patching rather than replacing so `claim edit --limit 0.4` does not silently
    wipe the quantity and units someone wrote last week.
    """
    base = existing or Acceptance()
    comparator = base.comparator
    if getattr(args, "cmp", None):
        comparator = Comparator(args.cmp)
    return Acceptance(
        quantity=args.quantity if args.quantity is not None else base.quantity,
        comparator=comparator,
        limit=args.limit if args.limit is not None else base.limit,
        limit_hi=args.limit_hi if args.limit_hi is not None else base.limit_hi,
        units=args.units if args.units is not None else base.units,
    )


def cmd_claim_add(args: argparse.Namespace) -> int:
    """Add one claim. Warns — loudly — when it has no machine-checkable threshold.

    The warning rather than a refusal is deliberate. "A claim without an
    acceptance is a wish" (models.Acceptance), and a wish must not be allowed to
    look settled — but claims are captured during intake, often before anyone
    knows the number, and a CLI that refuses the first half of the thought gets
    replaced by a text file. So it is recorded, and it nags every time it is
    printed.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        claim_id = (args.id or "").strip() or claims.next_claim_id(ledger, args.prefix)
        if ledger.claim(claim_id):
            raise AtompipeError(
                f"claim {claim_id!r} already exists — use `atompipe claim edit {claim_id}`")
        claim = Claim(
            id=claim_id,
            statement=args.statement.strip(),
            kind=ClaimKind(args.kind),
            acceptance=_acceptance_from(args),
            rationale=args.rationale or "",
            source=args.source or "",
            grounded_by=_collect(args.grounds),
            gates=_collect(args.gates),
            tags=_collect(args.tags),
            critical=not args.nice_to_have,
            note=args.note or "",
        )
        ledger.claims.append(claim)
        store.save(root, ledger)

    if args.json:
        _dump(claim.to_dict())
        return 0
    _say(f"{claim.id}  {claim.statement}  [{claim.kind}]"
         f"{'' if claim.critical else '  (nice-to-have)'}")
    rendered = claim.acceptance.render()
    if rendered:
        _say(f"  accepts: {rendered}")
    if claim.acceptance.limit is None and claim.kind is ClaimKind.MEASURABLE:
        _warn(f"warning: {claim.id} has no acceptance threshold — 'strong enough' is not "
              f"a claim. Add one: atompipe claim edit {claim.id} "
              f"--quantity '<what is measured>' --cmp '<=' --limit <number> --units mm")
    return 0


def cmd_claim_list(args: argparse.Namespace) -> int:
    """One line per claim: status, id, statement, acceptance.

    Sorted by ledger order, not by status: an agent reading this twenty minutes
    apart needs the same line in the same place, and a list that reorders itself
    as things pass is unreadable as a diff.
    """
    root = _root(args)
    ledger = store.load(root)
    registry, _ = _registry(root, ledger, strict=False)
    _model, projection, _err = _projection_safe(root, ledger)
    stale, _why = _staleness(ledger, projection)
    resolved = claims.statuses(ledger, stale=stale, registry=registry)
    cover = claims.coverage(ledger, registry)

    rows = list(ledger.claims)
    if args.status:
        rows = [c for c in rows if str(resolved.get(c.id)) == args.status]
    if args.kind:
        rows = [c for c in rows if str(c.kind) == args.kind]
    if args.tag:
        rows = [c for c in rows if args.tag in (c.tags or ())]

    if args.json:
        _dump({"claims": [dict(c.to_dict(), status=str(resolved.get(c.id)),
                               covered_by=cover.get(c.id, [])) for c in rows],
               "stale": stale})
        return 0

    if not rows:
        _say("no claims recorded" if not ledger.claims else "no claims match that filter")
        return 0
    for claim in rows:
        status = resolved.get(claim.id, ClaimStatus.UNCLAIMED)
        accepts = claim.acceptance.render() or "NO THRESHOLD"
        flag = "" if claim.critical else " (nice-to-have)"
        _say(f"{report.status_tag(status)} {claim.id:<6} {claim.statement}{flag}"
             f"  [{claim.kind}] {accepts}")
    return 0


def cmd_claim_show(args: argparse.Namespace) -> int:
    """One claim's whole provenance — the same view `atompipe why` gives.

    Routed through `decisions.why` rather than re-rendered here, because two
    renderings of one claim's history is two places to forget the rejected
    alternatives.
    """
    root = _root(args)
    ledger = store.load(root)
    claim = ledger.claim(args.id)
    if claim is None:
        raise AtompipeError(f"no claim {args.id!r} — `atompipe claim list` shows what exists")
    registry, _ = _registry(root, ledger, strict=False)
    _model, projection, _err = _projection_safe(root, ledger)
    stale, _why = _staleness(ledger, projection)
    status = claims.resolve_status(claim, ledger.verdicts, stale=stale)

    if args.json:
        _dump(dict(claim.to_dict(), status=str(status),
                   covered_by=claims.coverage(ledger, registry).get(claim.id, []),
                   verdicts=[_verdict_row(v)
                             for v in claims.covering_verdicts(claim, ledger.verdicts)],
                   why=decisions.why(ledger, claim.id)))
        return 0
    _say(f"{report.status_tag(status)} {claim.id}")
    sys.stdout.write(decisions.why(ledger, claim.id))
    return 0


def cmd_claim_edit(args: argparse.Namespace) -> int:
    """Change one claim in place. Only the flags you pass are touched.

    Every field is optional and `None` means "leave it": an edit command that
    reset unmentioned fields to defaults would quietly delete a rationale every
    time someone retagged a claim.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        claim = ledger.claim(args.id)
        if claim is None:
            raise AtompipeError(f"no claim {args.id!r}")
        if args.statement is not None:
            claim.statement = args.statement.strip()
        if args.kind is not None:
            claim.kind = ClaimKind(args.kind)
        if args.rationale is not None:
            claim.rationale = args.rationale
        if args.source is not None:
            claim.source = args.source
        if args.note is not None:
            claim.note = args.note
        if args.tags is not None:
            claim.tags = _collect(args.tags)
        if args.gates is not None:
            claim.gates = _collect(args.gates)
        if args.grounds is not None:
            claim.grounded_by = _collect(args.grounds)
        if args.critical:
            claim.critical = True
        if args.nice_to_have:
            claim.critical = False
        claim.acceptance = _acceptance_from(args, claim.acceptance)
        store.save(root, ledger)

    if args.json:
        _dump(claim.to_dict())
        return 0
    _say(f"{claim.id}  {claim.statement}  [{claim.kind}]  "
         f"{claim.acceptance.render() or 'NO THRESHOLD'}")
    return 0


def cmd_claim_physical(args: argparse.Namespace) -> int:
    """Record a real-world result against a PHYSICAL claim.

    The only way a physical claim ever leaves UNVERIFIED. No simulation launders
    one into green — "the printed seam is watertight" is settled by water — so
    this command exists to let the one thing that CAN settle it, a human with the
    object, say so on the record, with a date, a name and the evidence files.

    Refuses on a MEASURABLE claim on purpose: hand-recording a pass for something
    a gate is supposed to prove is exactly how a readiness report stops meaning
    anything.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        claim = ledger.claim(args.id)
        if claim is None:
            raise AtompipeError(f"no claim {args.id!r}")
        if claim.kind is not ClaimKind.PHYSICAL:
            raise AtompipeError(
                f"claim {claim.id!r} is {claim.kind}, not physical. A hand-recorded "
                f"result on a measurable claim is an unchecked assertion wearing a "
                f"gate's clothes — run the gate, or change the claim's kind on purpose "
                f"with `atompipe claim edit {claim.id} --kind physical`")
        # Two spellings because two exist in the wild: `--pass`/`--fail` is what
        # the generated readiness report tells the user to run, and a bare
        # `pass`/`fail` is what people type. Accepting only one of them would
        # make a command this project prints itself fail on paste.
        passed = args.passed
        if passed is None:
            if not args.result:
                raise AtompipeError(
                    f"say what happened: `atompipe claim physical {args.id} pass` "
                    f"or `--fail`, with --detail describing what was actually observed")
            passed = args.result == "pass"
        claim.physical_result = PhysicalResult(
            passed=passed,
            when=(args.when or utcnow_iso()),
            who=args.who or "",
            detail=args.detail or "",
            evidence=_collect(args.evidence),
        )
        store.save(root, ledger)

    status = ClaimStatus.VERIFIED if claim.physical_result.passed else ClaimStatus.REFUTED
    if args.json:
        _dump(dict(claim.to_dict(), status=str(status)))
        return 0
    _say(f"{report.status_tag(status)} {claim.id} {claim.statement} — "
         f"{claim.physical_result.detail or ('pass' if passed else 'fail')} "
         f"({claim.physical_result.who or 'unattributed'}, {claim.physical_result.when})")
    return 0


# --------------------------------------------------------------------------- #
# gaps
# --------------------------------------------------------------------------- #
def cmd_gap(args: argparse.Namespace) -> int:
    """Measurable claims no gate covers — and, with `--propose`, packs that might.

    A gap is a growth signal, not a failure: the system is admitting there is a
    physical quantity it cannot currently check. The Needs are PERSISTED so that
    the classification and the candidate costs an agent records against one
    survive to the next session — `find_gaps` matches existing Needs by claim id
    and keeps everything that was written on them.

    Needs that are no longer gaps are left in the ledger untouched rather than
    deleted. A closed gap is a fact about the project's history, and deciding it
    is `SATISFIED` is a judgement this command is not entitled to make.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        registry, _ = _registry(root, ledger, strict=False)
        gaps = claims.find_gaps(ledger, registry)
        by_id = {need.id: index for index, need in enumerate(ledger.needs)}
        for need in gaps:
            if need.id in by_id:
                ledger.needs[by_id[need.id]] = need
            else:
                ledger.needs.append(need)
        store.save(root, ledger)

    manifests = packs.discover(root) if args.propose else []
    proposals: dict[str, list[Any]] = {
        need.id: packs.match(need, manifests) for need in gaps} if args.propose else {}

    if args.json:
        _dump({
            "gaps": [dict(need.to_dict(),
                          candidates_from_packs=[m.to_dict() for m in proposals.get(need.id, [])])
                     for need in gaps],
            "n_gaps": len(gaps),
        })
        return 0

    if not gaps:
        _say("no gaps: every measurable claim has a registered gate covering it")
        return 0

    for need in gaps:
        cids = ", ".join(need.claim_ids)
        _say(f"{_tag('gap')} {need.id:<10} {need.quantity or '(unnamed quantity)'} "
             f"— claims {cids} ({need.status})")
        if need.claim_class:
            _say(f"            class: {need.claim_class}")
        for candidate in need.candidates:
            _say(f"            {candidate.kind or 'candidate':<9} {candidate.name} "
                 f"— {candidate.cost or 'cost unstated'}")
        if args.propose:
            matched = proposals.get(need.id, [])
            if matched:
                for manifest in matched[:3]:
                    _say(f"            pack      {manifest.name} — {manifest.description}")
            else:
                _say("            no installed pack settles this vocabulary — this is the "
                     "extension protocol's trigger (docs/EXTENSION_PROTOCOL.md)")
    _say(f"{len(gaps)} gap(s). Name the quantity, try the analytic answer first, and only "
         f"then propose a solver — with its real cost said out loud.")
    return 0


# --------------------------------------------------------------------------- #
# gates
# --------------------------------------------------------------------------- #
def _gate_row(spec: Any) -> dict[str, Any]:
    """One gate as JSON, without its prose. The default shape of `gate list --json`.

    Everything here answers a question a caller can act on: what it is, what it
    costs, where it came from, what it settles, what it needs installed, and —
    non-negotiably — the fixture of its negative control, because a gate with no
    demonstrable failure is a logger and the listing must not hide that. What is
    left out is `description` and the control's `note`, which are paragraphs of
    English. `--full` brings both back; `atompipe gate show <id>` prints them for
    the one gate you are actually reading.
    """
    control = getattr(spec, "negative_control", None)
    row: dict[str, Any] = {
        "id": spec.id,
        "title": spec.title,
        "tier": int(spec.tier),
        "pack": spec.pack,
        "settles": spec.settles,
        "claims": list(spec.claims or []),
        "negative_control": {"fixture": control.fixture,
                             "expect": control.expect} if control else None,
    }
    # Empty requirement lists are the common case and say nothing; a present one
    # is the reason a gate skips, so it is never dropped when it has content.
    if spec.requires_tools:
        row["requires_tools"] = list(spec.requires_tools)
    if spec.requires_python:
        row["requires_python"] = list(spec.requires_python)
    return row


def cmd_gate_list(args: argparse.Namespace) -> int:
    """Every registered gate, one dense line each, via `gates.describe`.

    The line includes the negative control, because the control is the fact that
    makes the gate's green tick mean anything and it belongs where the gate is
    listed rather than three commands away.

    `--json` emits a SUMMARY projection, not the whole spec. The full dump
    measured 61,721 characters — roughly 15k tokens — on a project with five
    packs installed, and almost all of it was `description`: every gate's
    multi-paragraph docstring, plus the prose note on its negative control. An
    agent runs this command to find out which gate settles which claim, and
    paying fifteen thousand tokens for the prose it did not ask for is the
    opposite of a cheap inner loop (rule 10). `--full` still emits everything,
    for the one caller in a hundred that wants it, and `atompipe gate show <id>`
    has always been the way to read one gate's prose.
    """
    root = _root(args)
    ledger = store.load(root)
    registry, problems = _registry(root, ledger, strict=False)
    specs = registry.by_tier(args.tier if args.tier is not None else ALL_TIERS)

    if args.json:
        _dump({"gates": [spec.to_dict() if args.full else _gate_row(spec)
                         for spec in specs],
               "full": bool(args.full),
               "summary": gates.registry_summary(registry),
               "problems": problems})
        return 0

    if not specs:
        _say("no gates registered. Install a pack (`atompipe packs`) or write "
             "gates/<name>.py in this project.")
        for problem in problems:
            _say(f"{_tag('FAIL')} {problem}")
        return 0
    for spec in specs:
        _say(gates.describe(spec))
    summary = gates.registry_summary(registry)
    _say(f"{summary['gates']} gates, {summary['tier0']} at tier 0, "
         f"{summary['available']} runnable here")
    for problem in problems:
        _say(f"{_tag('FAIL')} {problem}")
    return 0


def cmd_gate_show(args: argparse.Namespace) -> int:
    """Everything about one gate: what it settles, what it needs, how it last ran."""
    root = _root(args)
    ledger = store.load(root)
    registry, _ = _registry(root, ledger, strict=False)
    entry = registry.get(args.id)
    if entry is None:
        known = ", ".join(registry.ids()[:12]) or "(none registered)"
        raise AtompipeError(f"no gate {args.id!r}. Registered: {known}")
    spec, _fn = entry
    ok, reason = gates.availability(spec)
    verdict = ledger.verdict(spec.id)
    control = ledger.verdict(f"{spec.id}#selftest")

    if args.json:
        _dump({"gate": spec.to_dict(), "available": ok, "availability": reason,
               "last_verdict": _verdict_row(verdict) if verdict else None,
               "last_selftest": _verdict_row(control) if control else None})
        return 0

    _say(gates.describe(spec))
    if spec.description:
        _say(f"  {spec.description}")
    _say(f"  tier {int(spec.tier)}  pack {spec.pack or '(project)'}  entry {spec.entry}")
    _say(f"  claims: {', '.join(spec.claims) or '(none — this gate settles nothing)'}")
    _say(f"  runnable here: {'yes' if ok else 'NO — ' + reason}")
    if spec.negative_control:
        _say(f"  control: {spec.negative_control.fixture} "
             f"(must {spec.negative_control.expect})")
        if spec.negative_control.note:
            _say(f"           {spec.negative_control.note}")
    else:
        _say("  control: NONE — this gate cannot be shown to fail, so it is a logger")
    _say(f"  last verdict: {verdict.render() if verdict else '(never run)'}")
    _say(f"  last selftest: {control.render() if control else '(never run)'}")
    return 0


def cmd_gate_selftest(args: argparse.Namespace) -> int:
    """Run every gate against its own known-bad input, and fail if one does not fail.

    This is rule 5 with a return code. `passed` on one of these lines means *the
    gate correctly rejected input that is known to be bad* — it measures the
    instrument, not the design.

    Exit 1 covers three outcomes, not one: a gate that PASSED its known-bad
    fixture (it is not measuring what it claims), a gate that CRASHED on it
    (refusing by exploding is not detecting), and a fixture that is missing or
    broken (the control is gone, so the gate is unproven). A gate whose tooling
    is absent SKIPS and does not fail the command — nothing was tested, and that
    is already visible as BLOCKED in the readiness report.

    Every tier runs by default. Capping the default at tier 0 would leave the
    expensive gates — the ones nobody re-reads — permanently unproven, which is
    the exact shape of the failure this command exists to catch.

    The selftest verdicts are appended to the run history but NOT written into
    the ledger's verdict list: they are filed under `<gate>#selftest` and carry
    no claims, and proof that the instrument works must never resolve a claim.
    """
    root = _root(args)
    max_tier = ALL_TIERS if args.tier is None else int(args.tier)
    selection = list(args.gates or []) + list(args.only or [])

    with _lock(root):
        ledger = store.load(root)
        registry, _ = _registry(root, ledger, strict=True)
        model, projection = _projection(root, ledger)
        ctx = _context(root, ledger, model, projection, max_tier, quiet=args.json)
        # Private, on purpose: `--only` must mean exactly what it means for
        # `check`, and a second copy of the id/pack/glob matching rule would
        # eventually disagree with the first — always in the permissive
        # direction, which here would silently test fewer controls than asked.
        specs = gates._selected(registry, max_tier, selection or None)

        started = time.perf_counter()
        results: list[Verdict] = []
        for spec in specs:
            pair = registry.get(spec.id)
            if pair is None:                        # pragma: no cover - defensive
                continue
            verdict = gates.selftest(spec, pair[1], ctx)
            results.append(verdict)
            if not args.json:
                _say(verdict.render())
        elapsed = time.perf_counter() - started

        if results and not args.no_record:
            store.record_run(root, results, RunMeta(
                when=utcnow_iso(), tier=max_tier,
                model_hash=modelio.model_hash(projection) if projection else "",
                inputs_hash=artifacts.inputs_hash(ledger),
                spine_version=__version__, duration_s=round(elapsed, 4)))

    broken = [v for v in results if not v.ok and not v.skipped]
    skipped = [v for v in results if v.skipped]

    if args.json:
        _dump({"selftests": [_verdict_row(v) for v in results],
               "broken": [v.gate for v in broken],
               "skipped": [v.gate for v in skipped],
               "ok": not broken})
        return 1 if broken else 0

    if not results:
        _say("no gates registered, so no controls to run")
        return 0
    _say(f"{len(results)} control(s) in {human_duration(elapsed)}: "
         f"{len(results) - len(broken) - len(skipped)} fired, {len(broken)} BROKEN, "
         f"{len(skipped)} skipped")
    if broken:
        _say("these gates cannot be trusted — each one failed to reject its own "
             "known-bad input, or lost its control:")
        for verdict in broken:
            _say(f"{_tag('FAIL')} {verdict.gate} — "
                 f"{verdict.detail or verdict.error or 'no detail'}")
        return 1
    return 0


# --------------------------------------------------------------------------- #
# report / why / decide
# --------------------------------------------------------------------------- #
def cmd_report(args: argparse.Namespace) -> int:
    """The readiness report: what is proven, what is not, and why.

    Prints the markdown by default because the markdown IS the deliverable — the
    thing you hand someone before they spend money. `--write` puts it at
    `docs/readiness.md`; `atompipe status` is the compressed terminal view of the
    same ledger.

    `strict=False` here is deliberate — a report must render on a machine where
    the packs are not installed — but the *failures it swallows* were being
    thrown away with the underscore, and so was the model-load error. The result
    was the worst artefact this tool can produce: a green-looking deliverable
    generated from a registry that is missing a pack, where every claim that
    pack covered reads UNCLAIMED because of an import error rather than because
    nobody wrote the gate. That is a lie about coverage, in the one document
    whose entire value is refusing to claim what it has not proven (rule 9), so
    both failures are now named in a banner directly under the headline.
    """
    root = _root(args)
    ledger = store.load(root)
    registry, problems = _registry(root, ledger, strict=False)
    _model, projection, model_error = _projection_safe(root, ledger)
    stale, stale_why = _staleness(ledger, projection)
    banner = _load_failure_banner(problems, model_error)

    if args.json:
        resolved = claims.statuses(ledger, stale=stale, registry=registry)
        _dump({
            "summary": claims.summarise(ledger, registry, stale=stale),
            "claims": {cid: str(status) for cid, status in resolved.items()},
            "coverage": claims.coverage(ledger, registry),
            "gaps": [need.to_dict() for need in claims.find_gaps(ledger, registry)],
            "verdicts": [_verdict_row(v) for v in ledger.verdicts],
            "stale": stale,
            "stale_reason": stale_why,
            "problems": problems,
            "model_error": model_error,
            "coverage_understated": bool(banner),
        })
        return 0

    if args.write:
        with _lock(root):
            path = report.write_report(root, ledger, registry, stale=stale)
        _say(rel(path, root))
        # To stderr, because the one line on stdout is the path and scripts read
        # it. A caveat that breaks `report --write` as a shell substitution would
        # get silenced by whoever hit it, which is the opposite of the point.
        for line in banner:
            _warn(line)
        return 0
    sys.stdout.write(_with_banner(
        report.render_markdown(ledger, registry, stale=stale), banner))
    return 0


def _load_failure_banner(problems: list[str], model_error: str) -> list[str]:
    """The "this report understates coverage" banner, or `[]` when nothing failed.

    Counted rather than merely listed: "2 gate sources failed to load" is the
    sentence that makes a reader distrust the UNCLAIMED rows, and a reader who
    sees only a pack name at the bottom of a wall of markdown will not connect
    the two.
    """
    if not problems and not model_error:
        return []
    lines = ["> **This report is incomplete.** "
             f"{len(problems)} gate source(s) failed to load"
             + (" and the model did not load" if model_error else "")
             + ", so coverage below is UNDERSTATED: a claim may read UNCLAIMED "
               "because its gate never registered, not because no gate exists."]
    lines += [f"> - {problem}" for problem in problems]
    if model_error:
        lines.append(f"> - model: {model_error.splitlines()[0]}")
    return lines


def _with_banner(markdown: str, banner: list[str]) -> str:
    """Insert `banner` immediately after the report's `# ` headline.

    After rather than before, so the document still opens with its title and
    stays a valid readiness report; immediately after rather than at the end,
    because a caveat below the PROVEN table is a caveat nobody reads before
    quoting the PROVEN table.
    """
    if not banner:
        return markdown
    lines = markdown.splitlines()
    cut = next((i + 1 for i, line in enumerate(lines) if line.startswith("# ")), 0)
    merged = lines[:cut] + ["", *banner] + lines[cut:]
    return "\n".join(merged) + "\n"


def cmd_why(args: argparse.Namespace) -> int:
    """One parameter or claim's whole history, instead of the whole decision log.

    The context-window win: value, what it derives from, the rationale, every
    rejected alternative with the concrete reason it lost, the gates that protect
    it, the evidence that grounds it, and the decisions that moved it.
    """
    root = _root(args)
    ledger = store.load(root)
    text = decisions.why(ledger, args.name)
    if args.json:
        _dump({"name": args.name, "why": text})
        return 0
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    """Record a decision — including, above all, what LOST and why.

    `--rejected "0.5 mm|the router could not close that net through the congested
    corridor"` is the highest-value thing this whole system stores. Without it
    every fresh context window re-proposes every settled number. A rejection with
    no reason is refused by `decisions.add`, which is why the flag takes a pair.
    """
    root = _root(args)
    when = args.when or utcnow_iso()
    rejected: list[Any] = []
    for raw in args.rejected or ():
        parts = [piece.strip() for piece in raw.split("|")]
        # A single-piece value is passed through as a string so `decisions.add`
        # raises its own sentence about reasonless rejections, which says more
        # than anything this parser could.
        rejected.append(tuple(parts) if len(parts) >= 2 else raw)

    with _lock(root):
        ledger = store.load(root)
        decision = decisions.add(
            ledger,
            title=args.title,
            summary=args.summary,
            when=when,
            rejected=rejected,
            params_changed=_collect(args.param),
            claims_changed=_collect(args.claim),
            body=args.body or "",
            evidence=_collect(args.evidence),
        )
        store.save(root, ledger)
        log_path = decisions.write_log(root, ledger)

    if args.json:
        _dump(dict(decision.to_dict(), log=rel(log_path, root)))
        return 0
    _say(f"{decision.id}  {decision.title}  ({decision.when})")
    for item in decision.rejected:
        _say(f"  rejected {item.value}: {item.why}")
    _say(f"  log: {rel(log_path, root)}")
    return 0


# --------------------------------------------------------------------------- #
# packs
# --------------------------------------------------------------------------- #
def cmd_packs_list(args: argparse.Namespace) -> int:
    """Every discoverable pack, with where it came from and whether it is installed.

    Installed is a PROJECT fact (`meta.packs`), available is a filesystem fact.
    Keeping the two visibly apart answers the two questions people actually have:
    "why is this gate not running" (available, not installed) and "where did this
    gate come from" (installed, and shadowed by a copy earlier on the path).
    """
    root = _root(args)
    ledger = store.load(root)
    installed = packs.installed(root, ledger=ledger)
    found = packs.discover_dirs(root)

    if args.json:
        _dump({
            "installed": installed,
            "available": [{"name": manifest.name, "dir": directory,
                           "installed": manifest.name in installed,
                           **manifest.to_dict()}
                          for directory, manifest in found],
            "search_paths": packs.search_paths(root, existing_only=False),
        })
        return 0

    if not found:
        _say("no packs found. Searched:")
        for path in packs.search_paths(root, existing_only=False):
            _say(f"  {path}")
        return 0
    for directory, manifest in found:
        mark = "*" if manifest.name in installed else " "
        _say(f"{mark} {manifest.name:<18} {manifest.version:<8} "
             f"t{int(manifest.max_tier)}  {manifest.description}")
        if args.verbose:
            _say(f"    {directory}")
            _say(f"    settles: {', '.join(manifest.settles) or '(nothing declared)'}")
    missing = [name for name in installed if not packs.find(name, root)]
    _say(f"* = installed in this project ({len(installed)} of {len(found)} discoverable)")
    for name in missing:
        _say(f"{_tag('FAIL')} {name} is in meta.packs but was not found on any search path")
    return 0


def cmd_packs_show(args: argparse.Namespace) -> int:
    """Tier 2 (`PACK.md`) for one pack, or tier 3 with `--ref <name>`.

    Separate commands for separate tiers on purpose: reading every installed
    pack's prose would cost more context than the entire rest of the project
    state, which is what the three-tier split exists to prevent.
    """
    root = _root(args)
    if args.ref:
        text = packs.reference_doc(args.name, args.ref, root)
    else:
        text = packs.pack_doc(args.name, root)
    manifest = packs.read_manifest(packs.find(args.name, root) or "")

    if args.json:
        _dump({"manifest": manifest.to_dict(),
               "references": packs.references(args.name, root),
               "doc": text})
        return 0
    if not args.ref:
        _say(f"# {manifest.name} {manifest.version} — {manifest.description}")
        refs = packs.references(args.name, root)
        if refs:
            _say(f"references (tier 3): {', '.join(refs)}  "
                 f"— `atompipe packs show {args.name} --ref <name>`")
        _say("")
    sys.stdout.write(text if text.endswith("\n") else text + "\n")
    return 0


def cmd_packs_validate(args: argparse.Namespace) -> int:
    """Run the same checks CI runs on a pack. Exit 1 if anything is wrong.

    Accepts a pack name or a directory, so a pack being written in place can be
    validated before it is anywhere a search path will find it.
    """
    root = store.find_root(getattr(args, "dir", None))
    target = args.name
    pack_dir = target if os.path.isdir(target) else (packs.find(target, root) or "")
    if not pack_dir:
        raise AtompipeError(f"no pack {target!r} on any search path, and no such directory")
    problems = packs.validate(pack_dir)

    if args.json:
        _dump({"pack": pack_dir, "problems": problems, "ok": not problems})
        return 1 if problems else 0
    if not problems:
        _say(f"{_tag('ok')} {pack_dir}: publishable")
        return 0
    for problem in problems:
        _say(f"{_tag('FAIL')} {problem}")
    _say(f"{len(problems)} problem(s) in {pack_dir}")
    return 1


def cmd_packs_add(args: argparse.Namespace) -> int:
    """Opt this project into a pack: append it to `meta.packs`.

    Installed is a project decision, not a filesystem accident — a pack sitting
    in `~/.atompipe/packs` is available to every project on the machine and must
    not start contributing gates to this one until the ledger says so. The pack
    is loaded immediately so a broken one fails here, where the user is looking,
    rather than in the middle of the next `check`.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        added: list[str] = []
        for name in args.names:
            if not packs.find(name, root):
                looked = "\n  ".join(packs.search_paths(root, existing_only=False))
                raise AtompipeError(f"no pack {name!r} found. Searched:\n  {looked}")
            if name in (ledger.meta.packs or []):
                continue
            ledger.meta.packs = list(ledger.meta.packs or []) + [name]
            added.append(name)
        registry = gates.Registry()
        specs = packs.load_all_gates(ledger.meta.packs, registry, root)
        store.save(root, ledger)

    if args.json:
        _dump({"added": added, "packs": ledger.meta.packs,
               "gates": [spec.id for spec in specs]})
        return 0
    _say(f"packs: {', '.join(ledger.meta.packs) or '(none)'}")
    _say(f"{len(specs)} gate(s) now available: {', '.join(s.id for s in specs[:8])}")
    return 0


def cmd_packs_remove(args: argparse.Namespace) -> int:
    """Drop a pack from `meta.packs`. Its past verdicts stay in the ledger.

    Deliberately: a verdict is a record of something that was true when it ran,
    and deleting the evidence because the tooling was uninstalled would make the
    history lie. The claims those gates covered simply stop being covered, which
    `status` will report as UNCLAIMED — the honest answer.
    """
    root = _root(args)
    with _lock(root):
        ledger = store.load(root)
        before = list(ledger.meta.packs or [])
        ledger.meta.packs = [name for name in before if name not in set(args.names)]
        store.save(root, ledger)
    dropped = [name for name in before if name not in ledger.meta.packs]

    if args.json:
        _dump({"removed": dropped, "packs": ledger.meta.packs})
        return 0
    _say(f"removed {', '.join(dropped) or '(nothing)'}; "
         f"packs now: {', '.join(ledger.meta.packs) or '(none)'}")
    _say("past verdicts from those gates are kept — `atompipe status` will now show "
         "the claims they covered as uncovered")
    return 0


# --------------------------------------------------------------------------- #
# model
# --------------------------------------------------------------------------- #
def cmd_model(args: argparse.Namespace) -> int:
    """Load the model, project it, and say what that projection looks like.

    `--write` produces `.atompipe/model.json`, the diffable view: sorted keys,
    one value per line, so a parameter change reads as `deflection 0.70 -> 0.47`
    in `git diff` instead of as one enormous line. `--set-entry` records which
    file is the model — the loader deliberately never guesses, because "the only
    .py in model/" works right up until there are two.
    """
    root = _root(args)

    if args.set_entry:
        with _lock(root):
            ledger = store.load(root)
            candidate = os.path.join(root, args.set_entry)
            if not os.path.exists(candidate) and not os.path.isabs(args.set_entry):
                raise AtompipeError(
                    f"{args.set_entry} does not exist (looked at {candidate}) — "
                    f"create the model first, then record it")
            ledger.meta.model_entry = args.set_entry
            store.save(root, ledger)
    ledger = store.load(root)

    model, projection = _projection(root, ledger, entry=args.entry)
    if projection is None:
        raise AtompipeError(
            "no model entry recorded — `atompipe model --set-entry model/<thing>.py` "
            "(the model is a dataclass CONFIG plus build(config) -> dict)")

    digest = modelio.model_hash(projection)
    undocumented = modelio.undocumented_params(model)

    # Plain `atompipe model` is a READ. It used to take the build lock and save
    # the ledger unconditionally, three lines below the comment promising it did
    # not — so printing the projection while a sweep was in flight contended for
    # the lock, and a `model` in a loop rewrote the ledger's mtime forever. The
    # write now happens only for the two spellings that are already writes.
    #
    # `--set-entry` and `--write` both prime the ledger's parameter table from
    # the model, so `atompipe why <param>` answers straight after either one
    # rather than only after the first gate sweep.
    written = ""
    if args.set_entry or args.write:
        with _lock(root):
            fresh = store.load(root)
            modelio.sync_params(fresh, model)
            orphans = modelio.orphan_params(fresh, model)
            store.save(root, fresh)
            if args.write:
                written = modelio.write_projection(root, projection)
    else:
        # Lock-free: `orphan_params` only compares two in-memory lists, and the
        # ledger already in hand is the one we would have re-read anyway.
        orphans = modelio.orphan_params(ledger, model)

    if args.json:
        _dump({"entry": model.entry, "hash": digest, "projection": projection,
               "params": [param.to_dict() for param in model.params],
               "undocumented": undocumented,
               "written": rel(written, root) if written else ""})
        return 0

    config = projection.get("config") or {}
    derived = projection.get("derived") or {}
    _say(f"model: {model.entry}  hash {digest}")
    if orphans:
        _say(f"  {len(orphans)} ledger param(s) the model no longer defines: "
             f"{', '.join(orphans[:6])}"
             + ("..." if len(orphans) > 6 else "")
             + "  — renamed, or dropped without a decision entry?")
    _say(f"  {len(config)} config value(s), {len(derived)} derived value(s), "
         f"{len(model.params)} param record(s)")
    if undocumented:
        _say(f"  no rationale: {', '.join(undocumented)} — a number with no rationale "
             f"gets re-litigated by every fresh reader")
    if written:
        _say(f"  wrote {rel(written, root)}")
    return 0


# --------------------------------------------------------------------------- #
# doctor
# --------------------------------------------------------------------------- #
def _check(results: list[dict], name: str, status: str, detail: str) -> None:
    """Append one doctor row. `status` is one of ok / warn / FAIL."""
    results.append({"check": name, "status": status, "detail": detail})


def _ledger_problems(root: str, ledger: Ledger, registry: gates.Registry) -> list[str]:
    """Everything structurally wrong with this ledger, as sentences.

    Integrity here means "the records still refer to things that exist". Every
    one of these is a way the project can look fine and be wrong: a duplicate
    claim id means one of two claims is invisible to every lookup; a verdict for
    a gate nobody can find is a green tick with no instrument behind it; a
    missing artifact file is provenance that no longer resolves.
    """
    problems: list[str] = []

    def duplicates(values: Iterable[str], what: str) -> None:
        seen: set[str] = set()
        for value in values:
            if value in seen:
                problems.append(f"duplicate {what} {value!r} — one of them is unreachable")
            seen.add(value)

    duplicates([c.id for c in ledger.claims], "claim id")
    duplicates([p.name for p in ledger.params], "param name")
    duplicates([a.id for a in ledger.inputs], "artifact id")
    duplicates([n.id for n in ledger.needs], "need id")
    duplicates([d.id for d in ledger.decisions], "decision id")

    known_gates = set(registry.ids())
    orphaned = sorted({v.gate for v in ledger.verdicts
                       if not v.gate.endswith("#selftest") and v.gate not in known_gates})
    if orphaned and known_gates:
        # These verdicts still resolve their claims (`claims.covering_verdicts`
        # matches on the verdict, not on whether the gate still exists), so a
        # removed pack can leave passes standing that this machine cannot
        # reproduce. That is a readiness problem, not a tidiness one.
        problems.append(
            f"{len(orphaned)} verdict(s) from gates that are not registered here "
            f"({', '.join(orphaned[:4])}{'...' if len(orphaned) > 4 else ''}) — they still "
            f"resolve their claims but nothing here can re-run them; reinstall the pack "
            f"or drop the verdicts")
    for claim in ledger.claims:
        for gate_id in claim.gates or ():
            if known_gates and gate_id not in known_gates:
                problems.append(f"claim {claim.id} names gate {gate_id!r}, not registered here")
    for artifact in ledger.inputs:
        if artifact.path and not os.path.exists(os.path.join(root, artifact.path)):
            problems.append(f"artifact {artifact.id}: {artifact.path} is gone from disk")
    claim_ids = {c.id for c in ledger.claims}
    for need in ledger.needs:
        for cid in need.claim_ids or ():
            if cid not in claim_ids:
                problems.append(f"need {need.id} refers to claim {cid!r}, which does not exist")
    for record in store.load_runs(root, limit=50):
        if record.get("error"):
            problems.append(f"run {record.get('path')}: {record['error']}")
    return problems


def cmd_doctor(args: argparse.Namespace) -> int:
    """Everything that could be wrong with this environment, in one pass.

    This is the first thing anyone runs when confused, so it is diagnostic rather
    than decorative: every row names what was checked, what was found, and — when
    it is wrong — what to do. It survives every failure it reports (a broken
    pack, a model that will not import, a corrupt run file), because a doctor that
    dies on the first problem cannot tell you about the second.

    Exit 1 on any FAIL so it is usable in CI as an environment gate. Warnings do
    not fail: a solver that is not installed here is a real fact about the
    machine, and it is already visible as BLOCKED in the readiness report.
    """
    results: list[dict] = []

    version = ".".join(str(part) for part in sys.version_info[:3])
    _check(results, "python",
           "ok" if sys.version_info >= (3, 10) else "FAIL",
           f"{version} at {sys.executable} ({platform.system()}) — needs >= 3.10")
    _check(results, "spine", "ok",
           f"atompipe {__version__} from {os.path.dirname(os.path.abspath(__file__))}")

    root = store.find_root(getattr(args, "dir", None))
    if root is None:
        where = os.path.abspath(getattr(args, "dir", None) or os.getcwd())
        _check(results, "project", "FAIL",
               f"no .atompipe/ in {where} or any parent — run `atompipe init`")
        return _doctor_finish(args, results)
    _check(results, "project", "ok", root)

    try:
        ledger = store.load(root)
    except AtompipeError as exc:
        _check(results, "ledger", "FAIL", str(exc))
        return _doctor_finish(args, results)
    _check(results, "ledger", "ok",
           f"{len(ledger.claims)} claims, {len(ledger.params)} params, "
           f"{len(ledger.inputs)} artifacts, {len(ledger.needs)} needs, "
           f"{len(ledger.decisions)} decisions, {len(ledger.verdicts)} verdicts")

    paths = store.project_paths(root)
    missing = [key for key in ("runs", "out", "inputs", "docs", "model")
               if not os.path.isdir(paths[key])]
    _check(results, "layout", "warn" if missing else "ok",
           f"missing: {', '.join(missing)} (recreated on demand)" if missing
           else "all well-known directories present")

    registry, pack_problems = _registry(root, ledger, strict=False)
    for problem in pack_problems:
        _check(results, "gate-loading", "FAIL", problem)

    installed = packs.installed(root, ledger=ledger)
    available = packs.available(root)
    unfound = [name for name in installed if not packs.find(name, root)]
    _check(results, "packs", "FAIL" if unfound else "ok",
           f"{len(installed)} installed ({', '.join(installed) or 'none'}), "
           f"{len(available)} discoverable"
           + (f" — NOT FOUND: {', '.join(unfound)}" if unfound else ""))
    if not pack_problems and not available:
        _check(results, "pack-search", "warn",
               "no packs on any search path: "
               + ", ".join(packs.search_paths(root, existing_only=False)))

    summary = gates.registry_summary(registry)
    uncontrolled = summary["without_negative_control"]
    gate_status = "FAIL" if uncontrolled else ("warn" if not summary["gates"] else "ok")
    _check(results, "gates", gate_status,
           f"{summary['gates']} registered, {summary['tier0']} at tier 0, "
           f"{summary['available']} runnable here"
           + (f" — NO NEGATIVE CONTROL: {', '.join(uncontrolled)}" if uncontrolled
              else "" if summary["gates"] else " — nothing can be checked yet"))
    for row in summary["unavailable"]:
        _check(results, "gate-tool", "warn", f"{row['gate']}: {row['reason']}")
    for tool in summary["requires_tools"]:
        found = shutil.which(tool)
        _check(results, "tool", "ok" if found else "warn",
               f"{tool}: {found or 'not on PATH — gates needing it will SKIP, not fail'}")

    model = None
    projection = None
    if not (ledger.meta.model_entry or "").strip():
        _check(results, "model", "warn",
               "no model entry recorded — `atompipe model --set-entry model/<thing>.py`")
    else:
        try:
            model, projection = _projection(root, ledger)
        except AtompipeError as exc:
            _check(results, "model", "FAIL", str(exc).replace("\n", " "))
        else:
            _check(results, "model", "ok",
                   f"{model.entry} loads, hash {modelio.model_hash(projection)}, "
                   f"{len(model.params)} params")

    if model is not None:
        try:
            deterministic, detail = modelio.check_determinism(model, 2)
        except AtompipeError as exc:
            _check(results, "model-determinism", "FAIL", str(exc).replace("\n", " "))
        else:
            _check(results, "model-determinism", "ok" if deterministic else "FAIL", detail)
        undocumented = modelio.undocumented_params(model)
        _check(results, "model-provenance", "warn" if undocumented else "ok",
               f"{len(undocumented)} param(s) with no rationale: "
               f"{', '.join(undocumented[:6])}" if undocumented
               else "every param carries a rationale")
        # Checked against a COPY: doctor never writes, and a diagnostic that
        # silently repaired what it was diagnosing would hide the problem from
        # the next run.
        declared = {param.name for param in (model.params or [])}
        orphans = [param.name for param in ledger.params if param.name not in declared]
        _check(results, "model-params", "warn" if orphans else "ok",
               f"{len(orphans)} ledger param(s) the model no longer declares: "
               f"{', '.join(orphans[:6])} — renamed, or removed and still grounded"
               if orphans else f"{len(declared)} param(s), all still in the model")

    stale, why = _staleness(ledger, projection)
    _check(results, "staleness", "warn" if stale else "ok",
           why + (" — verdicts describe a model that no longer exists; `atompipe check`"
                  if stale else ""))

    problems = _ledger_problems(root, ledger, registry)
    _check(results, "ledger-integrity", "FAIL" if problems else "ok",
           "; ".join(problems[:4]) + (f" (+{len(problems) - 4} more)" if len(problems) > 4 else "")
           if problems else "records all resolve")

    lock = _lock(root)
    age = lock.age()
    if age is not None:
        holder = lock.holder()
        _check(results, "lock", "warn",
               f"{LOCK_NAME} held by pid {holder.get('pid', '?')} for "
               f"{human_duration(age)} — another run is in progress, or crashed")

    return _doctor_finish(args, results)


def _doctor_finish(args: argparse.Namespace, results: list[dict]) -> int:
    """Render the doctor rows and return the exit code."""
    failures = [row for row in results if row["status"] == "FAIL"]
    if args.json:
        _dump({"checks": results, "ok": not failures,
               "failures": [row["check"] for row in failures]})
        return 1 if failures else 0
    for row in results:
        _say(f"{_tag(row['status'])} {row['check']:<18} {row['detail']}")
    warnings = [row for row in results if row["status"] == "warn"]
    _say(f"{len(results)} checks — {len(failures)} failing, {len(warnings)} warning(s)")
    return 1 if failures else 0


# --------------------------------------------------------------------------- #
# argument parsing
# --------------------------------------------------------------------------- #
def _common() -> argparse.ArgumentParser:
    """Flags every subcommand carries: `--json` and a repeat of `-C/--dir`.

    `-C` is repeated on the subparsers so both `atompipe -C proj check` and
    `atompipe check -C proj` work — people type both. `default=SUPPRESS` is what
    makes that safe: without it the subparser would write its own `None` over the
    value the top-level parser already stored, and `atompipe -C proj check` would
    silently run against the current directory instead.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-C", "--dir", metavar="DIR", default=argparse.SUPPRESS,
                        help="run against this project directory instead of the cwd")
    common.add_argument("--json", action="store_true",
                        help="machine-readable output; nothing else goes to stdout")
    return common


def build_parser() -> argparse.ArgumentParser:
    """The whole command surface.

    Every help string is written for someone who has not read the docs, because
    `--help` is where most people meet this tool. Where a command's *point* is
    non-obvious — `ask`, `gap`, `gate selftest` — the help says what it is for
    rather than what it does.
    """
    common = _common()
    parser = argparse.ArgumentParser(
        prog="atompipe",
        description="Claims, gates, packs and an honest readiness report.",
        epilog="`atompipe doctor` is the first thing to run when something is confusing.",
    )
    parser.add_argument("--version", action="version", version=f"atompipe {__version__}")
    parser.add_argument("-C", "--dir", metavar="DIR", default=None,
                        help="run against this project directory instead of the cwd")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # -- init ------------------------------------------------------------- #
    p = sub.add_parser("init", parents=[common], help="create the project layout")
    p.add_argument("--name", default="", help="project name (default: directory name)")
    p.add_argument("--summary", default="", help="one line: what is being built")
    p.add_argument("--revision", default="v0.1")
    p.add_argument("--model", default="", help="model entry, e.g. model/bracket.py")
    p.add_argument("--pack", action="append", default=[], help="pack to install (repeatable)")
    p.set_defaults(func=cmd_init)

    # -- status ----------------------------------------------------------- #
    p = sub.add_parser("status", parents=[common],
                       help="where this project is, in one screen")
    p.set_defaults(func=cmd_status)

    # -- check ------------------------------------------------------------ #
    p = sub.add_parser("check", parents=[common],
                       help="run the gates; exits 1 while anything critical is unproven")
    p.add_argument("--tier", type=int, default=0,
                   help="cost ceiling: 0 instant (default), 1 build, 2 solve, 3 external")
    p.add_argument("--only", action="append", metavar="GATE",
                   help="gate id, pack name or glob (repeatable); runs it above its tier too")
    p.add_argument("--no-record", action="store_true",
                   help="do not write verdicts or run history (a dry sweep)")
    p.set_defaults(func=cmd_check)

    # -- ask -------------------------------------------------------------- #
    p = sub.add_parser("ask", parents=[common],
                       help="what evidence to request from the human, in priority order")
    p.add_argument("--kind", choices=[k.value for k in ArtifactKind],
                   help="all prompts for one artifact kind instead of the priority list")
    p.add_argument("--about", default="",
                   help="what the project is, to bias the ordering (default: meta.summary)")
    p.add_argument("--limit", type=int, default=6,
                   help="how many to ask for at once (default 6: what a person answers)")
    p.set_defaults(func=cmd_ask)

    # -- ingest / inputs / extract ---------------------------------------- #
    p = sub.add_parser("ingest", parents=[common],
                       help="take files (or URLs) into the project as evidence")
    p.add_argument("paths", nargs="+")
    p.add_argument("--kind", choices=[k.value for k in ArtifactKind],
                   help="override the guess made from extension and directory")
    p.add_argument("--desc", default="", help="what it shows — worth the sentence")
    p.add_argument("--licence", default="", help="provenance: ingested media gets redistributed")
    p.add_argument("--note", default="")
    p.add_argument("--no-copy", action="store_true",
                   help="register in place instead of copying into inputs/")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("inputs", parents=[common], help="list ingested evidence")
    p.add_argument("--unextracted", action="store_true",
                   help="only the artifacts nobody has read anything out of")
    p.add_argument("--kind", choices=[k.value for k in ArtifactKind])
    p.set_defaults(func=cmd_inputs)

    p = sub.add_parser("extract", parents=[common],
                       help="record what was read out of an artifact, and what it grounds")
    p.add_argument("artifact", help="artifact id from `atompipe inputs`")
    p.add_argument("--what", required=True, help='e.g. "hull beam at midship reads 148 mm"')
    p.add_argument("--grounds", action="append", default=[],
                   help="param names / claim ids this supports (comma-separated or repeated)")
    p.add_argument("--confidence", default="stated",
                   choices=["measured", "scaled", "stated", "inferred"])
    p.add_argument("--note", default="")
    p.set_defaults(func=cmd_extract)

    # -- claim ------------------------------------------------------------ #
    claim = sub.add_parser("claim", help="add, list, show, edit and settle claims")
    claim_sub = claim.add_subparsers(dest="claim_command", metavar="<sub>")
    claim.set_defaults(func=lambda args: _needs_subcommand(claim))

    p = claim_sub.add_parser("add", parents=[common], help="add a claim")
    p.add_argument("--statement", required=True, help="what must be true for this to work")
    p.add_argument("--kind", default=ClaimKind.MEASURABLE.value,
                   choices=[k.value for k in ClaimKind])
    p.add_argument("--id", default="", help="explicit id (default: next free C<n>)")
    p.add_argument("--prefix", default="C", help="id prefix when generating (default C)")
    p.add_argument("--quantity", default=None, help='what is measured, e.g. "tip deflection"')
    p.add_argument("--cmp", default=None, choices=[c.value for c in Comparator],
                   help="comparator for the threshold")
    p.add_argument("--limit", type=float, default=None)
    p.add_argument("--limit-hi", type=float, default=None, help="upper bound for `between`")
    p.add_argument("--units", default=None)
    p.add_argument("--rationale", default="", help="why this matters; what breaks if false")
    p.add_argument("--source", default="")
    p.add_argument("--tags", action="append", default=[],
                   help="tags packs bind gates to (comma-separated or repeated)")
    p.add_argument("--gates", action="append", default=[], help="gate ids that cover it")
    p.add_argument("--grounds", action="append", default=[], help="artifact ids behind it")
    p.add_argument("--note", default="")
    p.add_argument("--nice-to-have", action="store_true",
                   help="not critical: never blocks a spend")
    p.set_defaults(func=cmd_claim_add)

    p = claim_sub.add_parser("list", parents=[common], help="one line per claim")
    p.add_argument("--status", choices=[s.value for s in ClaimStatus])
    p.add_argument("--kind", choices=[k.value for k in ClaimKind])
    p.add_argument("--tag", default="")
    p.set_defaults(func=cmd_claim_list)

    p = claim_sub.add_parser("show", parents=[common], help="one claim's whole history")
    p.add_argument("id")
    p.set_defaults(func=cmd_claim_show)

    p = claim_sub.add_parser("edit", parents=[common],
                             help="change a claim; unmentioned fields are untouched")
    p.add_argument("id")
    p.add_argument("--statement", default=None)
    p.add_argument("--kind", default=None, choices=[k.value for k in ClaimKind])
    p.add_argument("--quantity", default=None)
    p.add_argument("--cmp", default=None, choices=[c.value for c in Comparator])
    p.add_argument("--limit", type=float, default=None)
    p.add_argument("--limit-hi", type=float, default=None)
    p.add_argument("--units", default=None)
    p.add_argument("--rationale", default=None)
    p.add_argument("--source", default=None)
    p.add_argument("--note", default=None)
    p.add_argument("--tags", action="append", default=None)
    p.add_argument("--gates", action="append", default=None)
    p.add_argument("--grounds", action="append", default=None)
    p.add_argument("--critical", action="store_true", help="mark critical (blocks a spend)")
    p.add_argument("--nice-to-have", action="store_true", help="mark non-critical")
    p.set_defaults(func=cmd_claim_edit)

    p = claim_sub.add_parser("physical", parents=[common],
                             help="record a real-world result on a physical claim")
    p.add_argument("id")
    p.add_argument("result", nargs="?", choices=["pass", "fail"],
                   help="what happened in the real world")
    outcome = p.add_mutually_exclusive_group()
    outcome.add_argument("--pass", dest="passed", action="store_const", const=True,
                         help="same as the positional `pass` (what the report prints)")
    outcome.add_argument("--fail", dest="passed", action="store_const", const=False,
                         help="same as the positional `fail`")
    p.set_defaults(passed=None)
    p.add_argument("--when", default="", help="ISO date (default: now)")
    p.add_argument("--who", default="")
    p.add_argument("--detail", default="", help="what was actually observed")
    p.add_argument("--evidence", action="append", default=[], help="photo / log paths")
    p.set_defaults(func=cmd_claim_physical)

    # -- gap -------------------------------------------------------------- #
    p = sub.add_parser("gap", parents=[common],
                       help="measurable claims no gate covers — how the system grows")
    p.add_argument("--propose", action="store_true",
                   help="also list installed packs whose vocabulary matches")
    p.set_defaults(func=cmd_gap)

    # -- gate ------------------------------------------------------------- #
    gate = sub.add_parser("gate", help="list, inspect and falsify the gates")
    gate_sub = gate.add_subparsers(dest="gate_command", metavar="<sub>")
    gate.set_defaults(func=lambda args: _needs_subcommand(gate))

    p = gate_sub.add_parser("list", parents=[common], help="every registered gate")
    p.add_argument("--tier", type=int, default=None, help="only gates at or below this tier")
    p.add_argument("--full", action="store_true",
                   help="--json: include every gate's description (~4x the output)")
    p.set_defaults(func=cmd_gate_list)

    p = gate_sub.add_parser("show", parents=[common], help="one gate in full")
    p.add_argument("id")
    p.set_defaults(func=cmd_gate_show)

    p = gate_sub.add_parser("selftest", parents=[common],
                            help="run every negative control; fails any gate that cannot fail")
    # The positional form exists because `gates.py` prints `atompipe gate
    # selftest <id>` when it refuses a control-less gate, and a command the tool
    # tells you to run has to work as printed.
    p.add_argument("gates", nargs="*", metavar="GATE",
                   help="gate ids, pack names or globs; default is every control")
    p.add_argument("--only", action="append", metavar="GATE",
                   help="same as the positional form (repeatable)")
    p.add_argument("--tier", type=int, default=None,
                   help="cap the cost; the default runs every tier's control")
    p.add_argument("--no-record", action="store_true", help="do not append to the run history")
    p.set_defaults(func=cmd_gate_selftest)

    # -- report / why / decide -------------------------------------------- #
    p = sub.add_parser("report", parents=[common], help="the readiness report")
    p.add_argument("--write", action="store_true", help="write docs/readiness.md")
    p.set_defaults(func=cmd_report)

    p = sub.add_parser("why", parents=[common],
                       help="one param or claim's full history, instead of the whole log")
    p.add_argument("name")
    p.set_defaults(func=cmd_why)

    p = sub.add_parser("decide", parents=[common],
                       help="record a decision, including what LOST and why")
    p.add_argument("--title", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--when", default="", help="ISO timestamp (default: now)")
    p.add_argument("--rejected", action="append", default=[], metavar="VALUE|WHY",
                   help='what lost and the concrete reason: "0.5 mm|the router could not close"')
    p.add_argument("--param", action="append", default=[], help="param names this moved")
    p.add_argument("--claim", action="append", default=[], help="claim ids this moved")
    p.add_argument("--evidence", action="append", default=[])
    p.add_argument("--body", default="", help="long-form markdown")
    p.set_defaults(func=cmd_decide)

    # -- packs ------------------------------------------------------------ #
    # `pack` is an alias because the extension protocol and `packs.py`'s own
    # messages say `atompipe pack validate`; a documented command must run.
    pack = sub.add_parser("packs", aliases=["pack"],
                          help="discover, read, validate and install packs")
    pack_sub = pack.add_subparsers(dest="packs_command", metavar="<sub>")
    pack.set_defaults(func=cmd_packs_list, json=False, verbose=False)

    p = pack_sub.add_parser("list", parents=[common], help="every discoverable pack")
    p.add_argument("-v", "--verbose", action="store_true", help="also show directory and settles")
    p.set_defaults(func=cmd_packs_list)

    p = pack_sub.add_parser("show", parents=[common], help="a pack's PACK.md (tier 2)")
    p.add_argument("name")
    p.add_argument("--ref", default="", help="a tier-3 reference instead of PACK.md")
    p.set_defaults(func=cmd_packs_show)

    p = pack_sub.add_parser("validate", parents=[common],
                            help="the checks CI runs; exit 1 on any problem")
    p.add_argument("name", help="pack name or directory")
    p.set_defaults(func=cmd_packs_validate)

    p = pack_sub.add_parser("add", parents=[common], help="opt this project into a pack")
    p.add_argument("names", nargs="+")
    p.set_defaults(func=cmd_packs_add)

    p = pack_sub.add_parser("remove", parents=[common], help="drop a pack from this project")
    p.add_argument("names", nargs="+")
    p.set_defaults(func=cmd_packs_remove)

    # -- model / doctor --------------------------------------------------- #
    p = sub.add_parser("model", parents=[common], help="the model, projected")
    p.add_argument("--write", action="store_true", help="write .atompipe/model.json")
    p.add_argument("--entry", default=None, help="project this file instead of the recorded one")
    p.add_argument("--set-entry", default="", metavar="PATH",
                   help="record this file as the project's model")
    p.set_defaults(func=cmd_model)

    p = sub.add_parser("doctor", parents=[common],
                       help="environment, model, packs, gates and ledger integrity")
    p.set_defaults(func=cmd_doctor)

    _tag_subparsers(parser)
    return parser


def _tag_subparsers(parser: argparse.ArgumentParser) -> None:
    """Give every subparser a `_parser` default pointing at itself.

    So that `main` can hand a bad flag back to the parser the user was actually
    using. `atompipe check --tierr 1` printed the two-line TOP-LEVEL usage —
    `usage: atompipe [-h] [--version] [-C DIR] <command> ...` — which lists the
    subcommands and not one of `check`'s own flags, so the reader learns nothing
    about the flag they got wrong and has to go and type `--help` separately.

    argparse fills defaults from the innermost parser last (each subparser parses
    into a fresh namespace that is then copied outward), so `args._parser` ends
    up as the deepest one that matched: `claim add`, not `claim`.

    `_actions` is private, but the alternative is repeating `set_defaults` on
    thirty subparsers, where the thirty-first would be added without it and
    nobody would notice until someone typoed a flag on exactly that command.
    Detection is by duck type — a `choices` that is a dict is a subparsers action
    — so it does not name a private argparse CLASS as well as a private field.
    """
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if not isinstance(choices, dict):
            continue
        for child in choices.values():
            child.set_defaults(_parser=child)
            _tag_subparsers(child)


def _needs_subcommand(parser: argparse.ArgumentParser) -> int:
    """`atompipe claim` with no subcommand: print its help, exit 2.

    Exit 2 rather than 0 because an incomplete command line is a user error, and
    a script that typoed its way here must not read the help text as success.
    """
    parser.print_help(sys.stderr)
    return 2


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    """Parse, dispatch, and turn exceptions into exit codes.

    `AtompipeError` is the user's problem and prints as one sentence with no
    traceback; everything else is the spine's problem and keeps its traceback,
    because a bug that prints like a user error gets reported as a user error and
    never gets fixed.

    `BrokenPipeError` is handled rather than raised: `atompipe gate list | head`
    is a normal thing to type, and Python's default behaviour there is a
    confusing "Exception ignored" block at interpreter shutdown. stdout is
    redirected to devnull so the flush at exit has somewhere harmless to go.
    """
    parser = build_parser()
    try:
        # `parse_known_args`, then complain via the subparser the user reached.
        # `parse_args` reports an unrecognized flag from the TOP-LEVEL parser, so
        # `atompipe check --tierr 1` printed the list of subcommands instead of
        # the list of `check`'s flags — the one thing the reader needed.
        args, unknown = parser.parse_known_args(
            list(sys.argv[1:] if argv is None else argv))
        if unknown:
            chosen = getattr(args, "_parser", None) or parser
            chosen.error(f"unrecognized arguments: {' '.join(unknown)}")
    except SystemExit as exc:                # --help, --version, or a bad flag
        return int(exc.code or 0)

    handler: Callable[[argparse.Namespace], int] | None = getattr(args, "func", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2

    try:
        return int(handler(args) or 0)
    except AtompipeError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        return 141
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":              # pragma: no cover - `python -m atompipe.cli`
    raise SystemExit(main())
