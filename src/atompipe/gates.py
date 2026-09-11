# SPDX-License-Identifier: Apache-2.0
"""atompipe.gates — the registry that refuses to register a logger.

A GATE is an executable that settles a claim *and is able to fail*. Everything in
this module exists to keep that second half true, because the first half is easy
and the second half is where designs get shipped broken.

Three rules are mechanical here, not advisory:

1. **No negative control, no registration.** :meth:`Registry.register` raises
   ``AtompipeError`` when ``spec.negative_control is None``. A cable-routing
   validator once returned a pass flag nobody read — for a whole revision it
   reported success while the cable was geometrically inside a wall. The comment
   left behind afterwards is the shortest statement of this module's job:
   *a logger is not a gate*. A gate that cannot
   demonstrate failure on known-bad input has proven nothing, and the only
   moment we can force the issue is registration.

2. **A skipped gate is visible, never absent.** :func:`availability` decides
   whether the gate's tooling exists; a missing solver produces a ``Verdict``
   with ``skipped=True`` and a ``skip_reason``, and ``Verdict.ok`` is already
   False for those. The claim then resolves BLOCKED in the readiness report
   instead of the gate quietly vanishing from the sweep. Silently degrading is
   how a report starts lying.

3. **An error is not a failure.** A crashed gate settles nothing — it did not
   measure the design, it exploded. :func:`run_gate` catches ``Exception`` and
   returns a verdict with ``error`` set and a trimmed traceback in ``detail``,
   kept separate from ``passed=False`` all the way into the ledger. The two read
   differently downstream — a missing tool resolves its claim to BLOCKED, a crash
   to FAIL, because a crash is the louder problem — and the report must be able
   to say "this gate could not run" instead of "your design is wrong".

   ``SystemExit`` is caught alongside it even though it is not an ``Exception``.
   A gate body that reached ``sys.exit()`` used to unwind past the handler and
   out of `atompipe check`, which exited **0 having printed and recorded
   nothing** — a sweep that proved nothing, reporting success. ``KeyboardInterrupt``
   is the one thing still allowed through: Ctrl-C during a twenty-minute solver
   gate must stop the run, not be filed as a verdict.

The gate function itself stays an ordinary function: :func:`gate` registers it
and returns it **unchanged**, so it is directly callable and directly testable
without the registry in the way.

Time policy (contract rule 3): nothing here stamps a timestamp. Durations are
*measured*, which is not the same thing — a wall-clock duration cannot be passed
in by a caller who is waiting on the result, and ``RunMeta.when`` still arrives
from the CLI edge.
"""
from __future__ import annotations

import contextlib
import dataclasses
import fnmatch
import importlib
import importlib.util
import os
import shutil
import sys
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .models import GateSpec, Ledger, NegativeControl, Tier, Verdict
from .util import AtompipeError, ensure_dir, short_hash

__all__ = [
    "GateContext",
    "Registry",
    "REGISTRY",
    "active_registry",
    "use_registry",
    "gate",
    "availability",
    "run_gate",
    "run_all",
    "selftest",
    "load_fixture",
    "describe",
    "registry_summary",
]


#: A verdict is ONE LINE of context. A whole sweep should cost tens of lines,
#: because each check emits one dense line and puts the volume in files; a gate
#: that dumps its log into `detail` turns a 40-gate sweep into 4,000 lines of
#: context nobody reads. Detail is collapsed to a single line and capped here.
_DETAIL_MAX = 500

#: How much of a crashing gate's traceback survives into `detail`. The last
#: frames are the ones that name the actual failure; the first frames are always
#: this module calling the gate, which the reader already knows.
_TRACE_TAIL = 400


def _trace_tail(text: str, limit: int = _TRACE_TAIL) -> str:
    """The last ``limit``-ish characters of a traceback, cut at a line boundary.

    A raw ``text[-400:]`` opens mid-identifier ("nt call last):"), which reads as
    corruption and makes a reader distrust the rest of the line. Cutting forward
    to the next newline costs a few characters and keeps the first surviving
    frame intact.
    """
    if len(text) <= limit:
        return text
    tail = text[-limit:]
    newline = tail.find("\n")
    return tail[newline + 1:] if 0 <= newline < limit // 2 else tail


def _noop_log(_message: str) -> None:
    """Default ``GateContext.log``: swallow it.

    A gate must be runnable with no CLI attached — from a test, from a pack's
    own ``__main__``, from another gate. Defaulting to ``print`` would spray a
    JSON-mode CLI with prose and make ``--json`` unparseable.
    """


def _one_line(text: Any, limit: int = _DETAIL_MAX) -> str:
    """Collapse ``text`` to a single capped line, preserving the front of it.

    Newlines become ``' | '`` rather than spaces so a flattened traceback stays
    greppable and a reader can still see where one frame ended. Truncation marks
    itself; a silently cut string is a string somebody will quote in a bug
    report as if it were complete.
    """
    if text is None:
        return ""
    flat = " | ".join(part.strip() for part in str(text).splitlines() if part.strip())
    flat = " ".join(flat.split())
    if len(flat) > limit:
        return flat[: limit - 3].rstrip() + "..."
    return flat


# --------------------------------------------------------------------------- #
# the context a gate is handed
# --------------------------------------------------------------------------- #
@dataclass
class GateContext:
    """Everything a gate is allowed to see. One argument, by design.

    A gate signature of ``fn(ctx)`` rather than ``fn(model, params, out_dir,
    ...)`` is what lets the spine add a field without breaking every pack in
    existence. Packs are third-party code; their call signature is a contract.

    Fields:

    ``root``     project root (the directory containing ``.atompipe/``).
    ``ledger``   the whole project state: claims, params, prior verdicts.
    ``model``    the loaded model module/instance, or None when the gate is
                 checking something else (a file, a netlist, an input artifact).
    ``params``   the projection flattened to ``{name: value}`` — config AND
                 derived together. Gates read numbers from here, never by
                 re-deriving them, because a gate that recomputes a derived
                 value is checking its own arithmetic instead of the model's.
    ``out_dir``  scratch and evidence. Anything cited in ``Verdict.evidence``
                 goes here; see :meth:`out_path`.
    ``tier``     the tier of the sweep in progress. A gate may use it to pick a
                 cheaper path, but must not use it to lower its own standard.
    ``log``      one-line progress sink. Defaults to a no-op.
    ``extra``    free-form. The negative-control machinery merges a fixture's
                 dict in here, and a caller may put ``pack_dirs`` /``pack_dir``
                 here to say where a pack's fixtures live (see
                 :func:`_fixture_root`).

    Every field has a default so a test can build a context with the one thing
    it cares about. That is additive to the contract's declaration, not a change
    to it: field order is unchanged and positional construction still works.
    """

    root: str = ""
    ledger: Ledger = field(default_factory=Ledger)
    model: Any | None = None
    params: dict[str, Any] = field(default_factory=dict)
    out_dir: str = ""
    tier: int = 0
    log: Callable[[str], None] = _noop_log
    extra: dict[str, Any] = field(default_factory=dict)

    # -- parameter access -------------------------------------------------- #
    def param(self, name: str, default: Any = None) -> Any:
        """Read one projected parameter, or ``default``.

        Accepts a dotted spelling (``config.beam_mm``) as well as the flat one,
        because half the callers are looking at ``model.json`` — which is
        ``{"config": {...}, "derived": {...}}`` — while ``params`` here is
        flattened. Tolerating both spellings costs two lines and removes a
        class of "the gate read None and passed" bug.
        """
        if name in self.params:
            return self.params[name]
        tail = name.rsplit(".", 1)[-1]
        if tail in self.params:
            return self.params[tail]
        return default

    def require_param(self, name: str) -> Any:
        """Read a parameter that MUST exist, or raise ``AtompipeError``.

        A missing parameter is a user-side mismatch between the model and the
        pack — not a bug in either — and the gate must stop rather than compare
        against ``None``. ``None <= limit`` raises in Python, but ``bool(None)``
        does not, and a gate that quietly treats a missing value as falsy is the
        precise shape of the failure this whole module exists to prevent.
        """
        missing = object()
        value = self.param(name, missing)
        if value is missing:
            known = ", ".join(sorted(self.params)[:8]) or "(nothing)"
            raise AtompipeError(
                f"the model does not define {name!r}, which this gate needs. "
                f"Add it to the model's CONFIG (or derive it in build()) and "
                f"re-run `atompipe model --write`. Projection currently has: {known}"
            )
        return value

    # -- evidence ---------------------------------------------------------- #
    def out_path(self, *parts: str) -> str:
        """Path under ``out_dir`` for an evidence file, with the dir created.

        Gates cite files in ``Verdict.evidence``; those files are what makes a
        PROVEN row in the readiness report auditable two months later. Creating
        the directory lazily here (instead of eagerly in :func:`run_gate`) keeps
        a gate that writes nothing from leaving empty directories behind.
        """
        base = self.out_dir or os.path.join(self.root or os.curdir, ".atompipe", "out")
        target = os.path.join(base, *parts) if parts else base
        ensure_dir(os.path.dirname(target) if parts else target)
        return target

    def with_extra(self, extra: dict[str, Any] | None) -> "GateContext":
        """A copy of this context with ``extra`` merged over the existing one.

        Used by :func:`selftest` to hand a gate its known-bad fixture without
        mutating the caller's context — a selftest that left the bad geometry
        behind in ``ctx.extra`` would poison every gate that ran after it.
        """
        merged = dict(self.extra or {})
        merged.update(extra or {})
        return dataclasses.replace(self, extra=merged)


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def _own_copy(spec: GateSpec) -> GateSpec:
    """A private copy of ``spec``, deep enough that the caller cannot edit it later.

    Registration is a one-time audit (``negative_control`` present, fixture named,
    id usable) and storing the caller's object would make that audit a formality:
    the checks run against a record the caller still holds a handle to and can
    rewrite the instant they return. The attack is three lines and it is not
    hypothetical for third-party pack code —

        spec = GateSpec(id="x", negative_control=NegativeControl(fixture="bad.py"))
        registry.register(spec, fn)     # passes the audit
        spec.negative_control = None    # and it is a logger again, still registered

    — after which the sweep runs a gate nothing proves can fail, and
    `atompipe gate selftest` reports "declares no negative control" for a gate
    that registered with one. The mutable list fields are copied for the same
    reason: ``spec.claims.append("stiffness")`` after the fact silently widens
    what a verdict is allowed to settle, which is the ledger claiming coverage
    nobody registered.

    Shallow-per-field is enough because every field is a str, an int enum, a list
    of str, or the ``NegativeControl`` (itself all strings).
    """
    nc = spec.negative_control
    return dataclasses.replace(
        spec,
        claims=list(spec.claims or []),
        requires_tools=list(spec.requires_tools or []),
        requires_python=list(spec.requires_python or []),
        negative_control=dataclasses.replace(nc) if nc is not None else None,
    )


def _control_gap(spec: GateSpec) -> str:
    """Why this spec's negative control is not usable, or ``""`` if it is.

    :meth:`Registry.register` is the primary enforcement and says far more; this
    is the cheap re-assertion for the moment a gate is actually about to run.
    See :func:`run_all` for why running one is not enough.
    """
    nc = spec.negative_control
    if nc is None:
        return "its negative control is gone"
    if not isinstance(nc, NegativeControl):
        return f"its negative control is a {type(nc).__name__}, not a NegativeControl"
    if not (nc.fixture or "").strip():
        return "its negative control names no fixture"
    return ""


class Registry:
    """The gates known to this process, in declaration order.

    Order is part of the contract: a sweep runs gates in the order they
    registered, which is the order a pack's author wrote them, which is usually
    cheapest-and-most-fundamental first. Sorting alphabetically would put
    ``cad.wall_thickness`` before ``cad.watertight`` and report thin walls on a
    mesh that is not even closed.

    The registry holds ``(spec, fn)`` pairs. The spec is serialisable and the
    function is not, which is why ``GateSpec.entry`` exists — out-of-process
    discovery re-imports from the entry string rather than unpickling anything.
    """

    def __init__(self) -> None:
        self._gates: dict[str, tuple[GateSpec, Callable[[GateContext], Any]]] = {}

    # -- registration ------------------------------------------------------ #
    def register(
        self,
        spec: GateSpec,
        fn: Callable[[GateContext], Any],
        *,
        replace: bool = False,
    ) -> None:
        """Register one gate, or raise ``AtompipeError`` explaining what is missing.

        **This is rule 5 of the method made mechanical.** A gate with no declared
        negative control cannot be shown to fail on known-bad input, which means
        nobody — including its author — knows whether it measures anything. The
        failure has shipped exactly that way for a whole revision: a cable-routing
        validator that returned a pass flag nobody read, with the cable
        geometrically inside a wall. Registration is the last moment
        the system can ask for proof before a green tick starts meaning something
        to a human, so it asks here and refuses here.

        The other refusals are smaller but the same idea — a registry that
        accepts a nameless or duplicated gate produces a report that cannot be
        trusted to say which gate proved what:

        * empty ``spec.id`` — verdicts key on it, the ledger keys on it
        * a fixture-less ``NegativeControl`` — the declaration without the proof
        * a duplicate id from a different function — two packs claiming one name;
          the second silently winning is how a gate stops being the gate you read

        Re-registering the *same* function object under the same id is a no-op,
        because importing a pack's gate module twice in one process is routine
        and is not a conflict. ``replace=True`` is the deliberate override.

        What is stored is a **copy** (:func:`_own_copy`), never the caller's
        object. A check run against a record the caller can rewrite afterwards is
        not a check — see that function for the three-line withdrawal it closes.
        """
        if not isinstance(spec, GateSpec):          # a bug in the caller, not the user
            raise TypeError(f"register() needs a GateSpec, got {type(spec).__name__}")
        if not callable(fn):
            raise TypeError(f"gate {spec.id!r} is not callable ({type(fn).__name__})")

        gate_id = (spec.id or "").strip()
        if not gate_id or any(ch.isspace() for ch in gate_id):
            raise AtompipeError(
                f"gate id {spec.id!r} is empty or contains whitespace — ids are keys "
                f"in the ledger and on the command line. Use a dotted, pack-prefixed "
                f"id like 'fdm.overhang'."
            )

        nc = spec.negative_control
        if nc is None:
            raise AtompipeError(
                f"gate {gate_id!r} declares no negative_control, so nothing proves it can "
                f"fail — and a validator that cannot be shown to fail is a logger, not a "
                f"gate. One shipped that way for a whole revision: a cable-routing check "
                f"returned a pass flag nobody read while the cable sat inside a wall. "
                f"Declare the known-bad input it must reject:\n"
                f"    from atompipe.models import NegativeControl\n"
                f"    negative_control=NegativeControl(\n"
                f"        fixture=\"selftest/known_bad.py\",   # make(ctx) -> input broken in the\n"
                f"                                          # ONE way this gate claims to detect\n"
                f"        note=\"what is wrong with it, in one line\",\n"
                f"    )\n"
                f"then prove it: atompipe gate selftest {gate_id}"
            )
        if not isinstance(nc, NegativeControl):
            raise AtompipeError(
                f"gate {gate_id!r}: negative_control must be a NegativeControl, "
                f"got {type(nc).__name__}"
            )
        if not (nc.fixture or "").strip():
            raise AtompipeError(
                f"gate {gate_id!r} declares a negative_control with no fixture — the "
                f"declaration without the known-bad input proves exactly as much as no "
                f"declaration at all. Set fixture=\"selftest/<file>.py\" (a make(ctx) "
                f"function) or \"module:function\"."
            )

        existing = self._gates.get(gate_id)
        if existing is not None and not replace:
            old_spec, old_fn = existing
            if old_fn is fn:
                self._gates[gate_id] = (_own_copy(spec), fn)   # idempotent re-import
                return
            where_old = old_spec.entry or old_spec.pack or getattr(old_fn, "__module__", "?")
            where_new = spec.entry or spec.pack or getattr(fn, "__module__", "?")
            raise AtompipeError(
                f"gate id {gate_id!r} is already registered by {where_old} and "
                f"{where_new} wants it too. Two gates cannot share an id: verdicts, "
                f"claim coverage and `atompipe check --only` all key on it. Rename one "
                f"(ids are pack-prefixed for exactly this reason)."
            )

        self._gates[gate_id] = (_own_copy(spec), fn)

    def unregister(self, gate_id: str) -> bool:
        """Drop a gate. Returns whether it was there. Mostly for tests."""
        return self._gates.pop(gate_id, None) is not None

    def clear(self) -> None:
        """Empty the registry. Tests and `packs.validate` use a scratch registry."""
        self._gates.clear()

    # -- lookup ------------------------------------------------------------ #
    def get(self, gate_id: str) -> tuple[GateSpec, Callable[[GateContext], Any]] | None:
        """``(spec, fn)`` for one id, or None. Never raises on an unknown id —
        the caller usually has a better error message than this module does."""
        return self._gates.get(gate_id)

    def specs(self) -> list[GateSpec]:
        """Every spec, in registration order."""
        return [spec for spec, _ in self._gates.values()]

    def ids(self) -> list[str]:
        """Every gate id, in registration order."""
        return list(self._gates)

    def pairs(self) -> list[tuple[GateSpec, Callable[[GateContext], Any]]]:
        """Every ``(spec, fn)``, in registration order."""
        return list(self._gates.values())

    def for_claim(self, claim_id: str, tags: Iterable[str] = ()) -> list[GateSpec]:
        """Gates that cover a claim, by id OR by tag.

        ``GateSpec.claims`` deliberately mixes the two: a pack author who has
        never seen your project cannot name your claim ids, but can say "I settle
        anything tagged ``manufacturability``". That is what makes packs
        composable, and it is why this lookup is not a dict.

        Matching is case-insensitive and whitespace-stripped. A ``Manufacturability``
        tag failing to match a ``manufacturability`` gate would show up as an
        UNCLAIMED claim in the readiness report — a capability gap that does not
        exist — and send someone off to install a solver they already have.
        """
        wanted = {(claim_id or "").strip().lower()}
        wanted.update((t or "").strip().lower() for t in (tags or ()))
        wanted.discard("")
        if not wanted:
            return []
        out: list[GateSpec] = []
        for spec, _ in self._gates.values():
            declared = {(c or "").strip().lower() for c in (spec.claims or [])}
            if declared & wanted:
                out.append(spec)
        return out

    def by_tier(self, max_tier: int) -> list[GateSpec]:
        """Gates at or below ``max_tier``, in registration order.

        The inner loop is tier 0 and must stay in seconds (rule 10): ``--part
        NAME`` at ~5s versus ``--all`` at ~20min is the difference that makes
        iteration possible at all. This filter is what keeps that promise, so it
        is ``<=`` on the declared tier and nothing cleverer — a gate that
        mislabels its tier breaks everyone's loop and no filter can save it.
        """
        ceiling = int(max_tier)
        return [spec for spec, _ in self._gates.values() if int(spec.tier) <= ceiling]

    # -- dunders ----------------------------------------------------------- #
    def __len__(self) -> int:
        return len(self._gates)

    def __contains__(self, gate_id: object) -> bool:
        return gate_id in self._gates

    def __iter__(self):
        return iter(self._gates.values())

    def __repr__(self) -> str:          # pragma: no cover - diagnostics only
        return f"Registry({len(self._gates)} gates: {', '.join(list(self._gates)[:6])})"


#: The process-wide default registry. Pack gate modules decorate against this on
#: import; `packs.load_gates` may pass its own for isolated validation.
REGISTRY = Registry()

#: Stack of registries that `@gate` targets when a gate module does not name one.
#: Empty means REGISTRY. A stack rather than a single slot because validating one
#: pack while another is loading is a real sequence, and the inner load must not
#: leave the outer one decorating into the wrong registry on its way out.
_ACTIVE_REGISTRIES: list[Registry] = []


def active_registry() -> Registry:
    """The registry ``@gate`` decorates into right now.

    A gate module cannot name the registry it should land in — it is imported by
    ``packs.load_gates``, which chose one, and the module was written before that
    choice existed. So the choice is ambient for the duration of the import and
    this is where it is read.
    """
    return _ACTIVE_REGISTRIES[-1] if _ACTIVE_REGISTRIES else REGISTRY


@contextlib.contextmanager
def use_registry(registry: Registry):
    """Make ``registry`` the target of every ``@gate`` decorated inside the block.

    This is the seam a pack loader needs::

        with use_registry(my_registry):
            import_the_packs_gate_modules()     # @gate lands in my_registry

    Without it, a loader that hands a private registry to an import gets an empty
    registry back and its gates in the global one — and because ``load_gates``
    reports what it added by diffing the registry it was given, the symptom is an
    empty list rather than an error: a pack that looks like it ships no gates at
    all. Silent under-reporting is the worst available failure here, which is why
    the seam exists rather than being left to convention.

    Not thread-safe, and does not need to be: Python serialises module execution
    behind the import lock, and this is only ever held across an import.
    """
    _ACTIVE_REGISTRIES.append(registry)
    try:
        yield registry
    finally:
        # Pop OUR entry, not the top one, in case a gate module misbehaved and
        # left something on the stack; a leaked entry would silently redirect
        # every later registration in the process.
        try:
            _ACTIVE_REGISTRIES.remove(registry)
        except ValueError:                       # pragma: no cover - defensive
            pass


# --------------------------------------------------------------------------- #
# the decorator
# --------------------------------------------------------------------------- #
def gate(
    *,
    id: str,
    claims: Iterable[str] = (),
    tier: Tier | int = Tier.INSTANT,
    settles: str = "",
    requires_tools: Iterable[str] = (),
    requires_python: Iterable[str] = (),
    negative_control: NegativeControl | None = None,
    title: str = "",
    description: str = "",
    pack: str = "",
    entry: str = "",
    registry: Registry | None = None,
) -> Callable[[Callable[[GateContext], Any]], Callable[[GateContext], Any]]:
    """Declare a gate: build its :class:`~atompipe.models.GateSpec` and register it.

    Returns the function **unchanged** — no wrapper, no signature change. A gate
    is an ordinary function of one argument and stays directly callable:

        from pack.gates.printability import overhang
        v = overhang(ctx)          # no registry, no CLI, no fixture

    That matters more than it looks. A decorator that wrapped the function would
    make the gate's own unit test go through the registry's normalisation, and
    then the thing under test would no longer be the thing that ships.

    The spec is also attached as ``fn.gate_spec`` so a loader that walks a
    module's attributes can find it without consulting a registry.

    Two fields are *derived* rather than restated (rule 2 — derive, never
    duplicate):

    * ``pack`` falls back to the defining module's ``PACK`` global, which is what
      ``packs.load_gates`` sets. Typing the pack name into forty decorators is
      forty chances to typo it, and a mistyped pack name silently orphans a gate
      in the readiness report.
    * ``entry`` falls back to ``module:qualname``, the string an out-of-process
      run needs to re-import this gate.
    * ``title``/``description`` fall back to the docstring's first line / rest,
      because a gate whose docstring already says what it checks should not have
      to say it twice and let the two drift.

    ``registry=None`` (the default) means :func:`active_registry` — the registry a
    pack loader has made current with :func:`use_registry`, or the module-level
    ``REGISTRY`` when nobody has. A gate module is imported by machinery it has
    never heard of, so it must not have to name a registry; passing one
    explicitly is for tests and for a gate defined in application code.

    Registration failures raise ``AtompipeError`` at IMPORT time, which is the
    point: a pack with a control-less gate fails to load rather than loading with
    a gate nobody can trust.
    """
    if negative_control is not None and not isinstance(negative_control, NegativeControl):
        # Caught here rather than in register() so the traceback points at the
        # decorator in the pack's source, where the author can see it.
        raise AtompipeError(
            f"gate {id!r}: negative_control must be a NegativeControl instance, "
            f"got {type(negative_control).__name__}"
        )

    def decorate(fn: Callable[[GateContext], Any]) -> Callable[[GateContext], Any]:
        doc = (fn.__doc__ or "").strip()
        doc_title, _, doc_rest = doc.partition("\n")

        module = sys.modules.get(getattr(fn, "__module__", "") or "")
        module_pack = getattr(module, "PACK", "") if module is not None else ""

        spec = GateSpec(
            id=id,
            title=title or doc_title.strip(),
            claims=[str(c) for c in (claims or ())],
            tier=Tier(int(tier)),
            pack=pack or (str(module_pack) if module_pack else ""),
            requires_tools=[str(t) for t in (requires_tools or ())],
            requires_python=[str(m) for m in (requires_python or ())],
            negative_control=negative_control,
            description=description or doc_rest.strip(),
            settles=settles,
            entry=entry or f"{getattr(fn, '__module__', '?')}:{getattr(fn, '__qualname__', getattr(fn, '__name__', '?'))}",
        )
        # Resolved at DECORATION time, not when `gate()` was called: the
        # ambient registry is whatever loader is importing this module right now.
        target_registry = registry if registry is not None else active_registry()
        target_registry.register(spec, fn)
        fn.gate_spec = spec          # type: ignore[attr-defined]
        return fn

    return decorate


# --------------------------------------------------------------------------- #
# availability
# --------------------------------------------------------------------------- #
def availability(spec: GateSpec) -> tuple[bool, str]:
    """Can this gate run here? ``(ok, reason)`` — the reason is user-facing.

    Checks executables with ``shutil.which`` and importable modules with
    ``importlib.util.find_spec``. ``find_spec`` is used instead of ``import``
    because importing a heavy solver binding to find out whether it exists costs
    seconds, and the tier-0 loop's whole promise is that it does not.

    **Never silently skip.** The reason string produced here becomes
    ``Verdict.skip_reason``, which keeps an uninstalled solver visible in the
    readiness report as BLOCKED instead of letting the gate vanish from the
    sweep. A missing tool that produces no row is indistinguishable from a tool
    that passed, and that indistinguishability is how a report starts lying.

    All missing dependencies are reported, not just the first: a user who
    installs one tool and reruns only to be told about the next one is a user
    who gives up on the third.
    """
    missing_tools = [t for t in (spec.requires_tools or []) if t and shutil.which(t) is None]

    missing_modules: list[str] = []
    for module_name in (spec.requires_python or []):
        if not module_name:
            continue
        try:
            found = importlib.util.find_spec(module_name)
        except (ImportError, AttributeError, ValueError) as exc:
            # find_spec("a.b") imports "a"; a parent package that raises on
            # import is, for our purposes, exactly as unusable as one that is
            # absent — but say WHICH, because "not installed" would send the
            # user to pip for a package that is already there and broken.
            missing_modules.append(f"{module_name} ({type(exc).__name__})")
            continue
        except SystemExit as exc:                    # BaseException; see run_gate
            # find_spec imports the parent package, and a solver binding's
            # "driver not installed" guard is routinely a bare sys.exit() at
            # module scope. Uncaught, that ends `atompipe check` right here with
            # the binding's own exit code — no rows, no ledger, possibly 0. A
            # package that exits when imported is unusable, which is a SKIP, and
            # a skip is never a pass.
            missing_modules.append(f"{module_name} (exits on import: sys.exit({exc.code!r}))")
            continue
        except Exception as exc:                     # noqa: BLE001 - third-party import side effects
            missing_modules.append(f"{module_name} ({type(exc).__name__}: {exc})")
            continue
        if found is None:
            missing_modules.append(module_name)

    if not missing_tools and not missing_modules:
        return True, ""

    reasons: list[str] = []
    if missing_tools:
        reasons.append(f"requires {', '.join(missing_tools)} (not on PATH)")
    if missing_modules:
        reasons.append(f"requires python {', '.join(missing_modules)} (not importable)")
    return False, "; ".join(reasons)


# --------------------------------------------------------------------------- #
# running one gate
# --------------------------------------------------------------------------- #
def _stamp(verdict: Verdict, spec: GateSpec, duration: float) -> Verdict:
    """Overwrite the identity fields of a verdict from its spec.

    A gate cannot be trusted to report its own name, tier, pack, claims or
    runtime — not because pack authors lie, but because copy-pasted gate bodies
    keep the previous gate's id in the ``Verdict(gate=...)`` literal, and a
    verdict filed under the wrong gate is worse than a missing one: it overwrites
    a real result in ``Ledger.upsert_verdict`` and marks someone else's claim.
    The spec is the only authority on identity, so the spec wins, always.

    ``passed`` is forced False whenever the gate skipped or errored. ``Verdict.ok``
    already encodes that, but ``passed`` is what lands in the JSON a human reads,
    and "passed: true, error: ..." is a sentence nobody should have to interpret.
    """
    passed = bool(verdict.passed) and not verdict.skipped and not verdict.error
    return dataclasses.replace(
        verdict,
        gate=spec.id,
        tier=Tier(int(spec.tier)),
        pack=spec.pack,
        claims=list(spec.claims or []),
        duration_s=round(max(0.0, float(duration)), 6),
        passed=passed,
        detail=_one_line(verdict.detail),
        skip_reason=_one_line(verdict.skip_reason, 200),
        error=_one_line(verdict.error, 200),
    )


def _normalise(result: Any, spec: GateSpec) -> Verdict:
    """Turn whatever a gate returned into a ``Verdict``, or say it cannot.

    Accepted, in descending order of how much the gate told us:

    * ``Verdict``            — used as-is (identity still overwritten)
    * ``dict``              — ``passed`` / ``pass`` / ``ok``, plus any Verdict field.
      ``pass`` is accepted because it is the conventional key for a check emitting
      ``{"check":"geometry","pass":true,"detail":"..."}``, and a spine that cannot
      read the shape its own gates naturally produce is friction for no gain.
    * ``(bool, detail)``    — the common analytic gate
    * ``bool``              — a gate with nothing to say beyond yes/no

    Everything else is an ERROR verdict, not a failure and not a pass. ``None``
    especially: a gate that falls off the end of its function has measured
    nothing, and the one thing this module must never do is let that read as
    green.
    """
    if isinstance(result, Verdict):
        return result

    if isinstance(result, bool):
        return Verdict(gate=spec.id, passed=result)

    if isinstance(result, dict):
        data = dict(result)
        if "passed" not in data:
            for alias in ("pass", "ok"):
                if alias in data:
                    data["passed"] = data.pop(alias)
                    break
        if "detail" not in data and "message" in data:
            data["detail"] = data.pop("message")
        if "passed" not in data:
            return Verdict(
                gate=spec.id,
                error="gate returned a dict with no 'passed' key",
                detail=f"returned keys: {', '.join(sorted(map(str, data))) or '(none)'} — "
                       f"a gate that does not say whether it passed is a logger",
            )
        data["passed"] = bool(data["passed"])
        # `gate` is a required field on Verdict and check-style dicts spell it
        # `check` (or omit it), so seed it before from_dict; _stamp overwrites it
        # from the spec a moment later either way.
        data.setdefault("gate", spec.id)
        try:
            return Verdict.from_dict(data)
        except (TypeError, ValueError) as exc:
            return Verdict(
                gate=spec.id,
                error=f"gate returned an unusable dict ({type(exc).__name__})",
                detail=str(exc),
            )

    if isinstance(result, (tuple, list)) and 1 <= len(result) <= 2:
        passed = result[0]
        if not isinstance(passed, bool):
            return Verdict(
                gate=spec.id,
                error="gate returned a tuple whose first element is not a bool",
                detail=f"got {type(passed).__name__}; expected (bool, detail)",
            )
        detail = "" if len(result) == 1 else str(result[1])
        return Verdict(gate=spec.id, passed=passed, detail=detail)

    if result is None:
        return Verdict(
            gate=spec.id,
            error="gate returned None",
            detail="a gate must return a Verdict, a bool, (bool, detail) or a dict; "
                   "returning nothing settles nothing",
        )

    return Verdict(
        gate=spec.id,
        error=f"gate returned an unusable {type(result).__name__}",
        detail="expected a Verdict, a bool, (bool, detail) or a dict",
    )


def run_gate(spec: GateSpec, fn: Callable[[GateContext], Any], ctx: GateContext) -> Verdict:
    """Run one gate and return a verdict that is honest about what happened.

    Four outcomes, and keeping them four instead of two is the whole job:

    * **pass**    — it ran and the acceptance held
    * **fail**    — it ran and the acceptance did not hold  (fix the design)
    * **skip**    — its tooling is absent, so it did not run (install the tool)
    * **error**   — it ran and crashed                      (fix the gate)

    An error is NOT a failure. A crashed gate has proven nothing about the
    design, and collapsing the two would invite someone to "fix" a broken import
    by changing a wall thickness. The two stay distinguishable in the record
    (``error`` set, ``passed`` forced False, ``Verdict.ok`` False either way) so
    that a skip can resolve its claim to BLOCKED, a crash to FAIL, and neither
    can ever be mistaken for the gate having measured something.

    Availability is checked BEFORE the clock starts, so a skipped gate reports
    ~0s rather than the cost of discovering the tool is missing.

    ``Exception`` is caught; ``KeyboardInterrupt`` is not — a Ctrl-C during a
    twenty-minute solver gate must stop the sweep, not be filed as a verdict and
    marched on from.

    ``SystemExit`` and ``GeneratorExit`` ARE caught, even though they are
    ``BaseException`` and not ``Exception``. That exception to the exception is
    there because of what got through: a gate body that reached ``sys.exit()``
    — pack code calling ``argparse`` on its own arguments, or a dependency whose
    import guard exits when a tool is absent — unwound straight past this
    handler, out of ``run_all``, and out of `atompipe check`, which then exited
    **0 having printed and recorded nothing at all**. A sweep that proves nothing
    and reports success is the exact failure this module exists to make
    impossible, so a gate that exits the process is filed as an errored gate
    (fix the gate) and the remaining gates still run.
    """
    ok, reason = availability(spec)
    if not ok:
        return _stamp(
            Verdict(gate=spec.id, passed=False, skipped=True, skip_reason=reason),
            spec,
            0.0,
        )

    started = time.perf_counter()
    try:
        result = fn(ctx)
    except (SystemExit, GeneratorExit) as exc:       # BaseException: see docstring.
        # Ordered BEFORE the Exception clause on purpose — neither of these is an
        # Exception subclass, so the clause below would never see them and they
        # would leave the sweep silently. KeyboardInterrupt is deliberately NOT
        # in this tuple: Ctrl-C must still stop a long run.
        elapsed = time.perf_counter() - started
        trace = traceback.format_exc()
        if isinstance(exc, SystemExit):
            what = (
                f"gate called sys.exit({exc.code!r}); a gate must return a verdict, "
                f"not exit the process"
            )
        else:
            what = (
                "gate raised GeneratorExit; a gate must return a verdict, not unwind "
                "the process"
            )
        return _stamp(
            Verdict(gate=spec.id, passed=False, error=what, detail=_trace_tail(trace)),
            spec,
            elapsed,
        )
    except Exception as exc:                         # noqa: BLE001 - deliberate: see docstring
        elapsed = time.perf_counter() - started
        trace = traceback.format_exc()
        return _stamp(
            Verdict(
                gate=spec.id,
                passed=False,
                error=f"{type(exc).__name__}: {exc}",
                detail=_trace_tail(trace),
            ),
            spec,
            elapsed,
        )
    elapsed = time.perf_counter() - started
    return _stamp(_normalise(result, spec), spec, elapsed)


# --------------------------------------------------------------------------- #
# running a sweep
# --------------------------------------------------------------------------- #
def _selected(registry: Registry, max_tier: int, only: str | Iterable[str] | None) -> list[GateSpec]:
    """Resolve the tier + ``only`` filters to a concrete, ordered gate list.

    ``only`` accepts an exact id, a pack name, or an fnmatch pattern
    (``cad.*``), and matching a nothing raises. That last part is the important
    one: a typo'd ``--only cad.watertigt`` that quietly ran zero gates and
    printed nothing would be reported by the CLI as a clean sweep, which is the
    same lie as a validator that exits 0. An empty registry is allowed through
    (there is nothing to typo), and the tier filter alone may legitimately select
    nothing — a project whose gates are all tier 2 running a tier-0 loop.
    """
    within_tier = registry.by_tier(max_tier)
    if only is None:
        return within_tier

    patterns = [only] if isinstance(only, str) else [str(o) for o in only]
    patterns = [p.strip() for p in patterns if str(p).strip()]
    if not patterns:
        return within_tier

    all_specs = registry.specs()
    chosen: list[GateSpec] = []
    unmatched: list[str] = []
    for pattern in patterns:
        hits = [
            s for s in all_specs
            if s.id == pattern
            or (s.pack and s.pack == pattern)
            or fnmatch.fnmatchcase(s.id, pattern)
        ]
        if not hits:
            unmatched.append(pattern)
        chosen.extend(hits)

    if unmatched and all_specs:
        known = ", ".join(s.id for s in all_specs[:12])
        more = "" if len(all_specs) <= 12 else f" (+{len(all_specs) - 12} more)"
        raise AtompipeError(
            f"no gate matches {', '.join(repr(u) for u in unmatched)} — running zero gates "
            f"and calling it a clean sweep is the failure this tool exists to prevent. "
            f"Known gates: {known}{more}"
        )

    # An explicitly named gate is run even if it sits above the tier ceiling:
    # naming it IS the opt-in to its cost. Order stays registration order.
    seen: set[str] = set()
    ordered: list[GateSpec] = []
    for spec in all_specs:
        if spec.id in {c.id for c in chosen} and spec.id not in seen:
            seen.add(spec.id)
            ordered.append(spec)
    return ordered


def run_all(
    registry: Registry,
    ctx: GateContext,
    *,
    max_tier: int = 0,
    only: str | Iterable[str] | None = None,
    on_verdict: Callable[[Verdict], None] | None = None,
) -> list[Verdict]:
    """Run every selected gate in declaration order and return their verdicts.

    ``max_tier`` defaults to 0 because the default sweep is the inner loop, and
    the inner loop must stay in seconds (rule 10). A caller who wants the
    twenty-minute solver asks for it.

    ``on_verdict`` is called with each verdict the moment it lands, so the CLI
    can stream one line per gate instead of going silent for the length of the
    slowest tier-2 gate in the list. It is called for skips and errors too —
    especially for skips, which are the rows a user most needs to see scroll
    past, because they are the ones that will resolve to BLOCKED.

    A gate that raises does not stop the sweep (it becomes an error verdict);
    an ``on_verdict`` callback that raises DOES, because that is our bug and a
    half-reported sweep must not look like a whole one.

    ``ctx.tier`` is reconciled with ``max_tier`` here rather than trusted: a
    context that says tier 0 while the sweep runs tier 2 would let a gate pick
    its cheap path during an expensive run, and nothing downstream would ever
    show the discrepancy.

    Rule 5 is re-asserted per spec rather than assumed from registration. The
    registry stores its own copy of every spec, but ``get()`` hands that copy out
    and callers legitimately stamp it (``packs.load_gates`` fills in a blank
    ``pack``), so the field that registration exists to guarantee is still within
    reach of code that runs between registration and the sweep. Checking it again
    costs one attribute read per gate and closes the only remaining window in
    which a logger can be swept as a gate.
    """
    selected = _selected(registry, max_tier, only)
    if int(ctx.tier) != int(max_tier):
        ctx = dataclasses.replace(ctx, tier=int(max_tier))
    if ctx.out_dir:
        ensure_dir(ctx.out_dir)      # once, up front: gates cite files in it

    verdicts: list[Verdict] = []
    for spec in selected:
        entry = registry.get(spec.id)
        if entry is None:            # concurrent unregister; nothing else can do this
            raise AtompipeError(f"gate {spec.id!r} disappeared from the registry mid-sweep")
        live, fn = entry
        gap = _control_gap(live)
        if gap:
            verdict = _stamp(
                Verdict(
                    gate=live.id,
                    passed=False,
                    error=f"{live.id} was registered with a negative control and {gap}",
                    detail="a gate nothing proves can fail is a logger; refusing to "
                           "sweep it rather than file a verdict it cannot support — "
                           "restore the control and run `atompipe gate selftest`",
                ),
                live,
                0.0,
            )
        else:
            verdict = run_gate(live, fn, ctx)
        verdicts.append(verdict)
        if on_verdict is not None:
            on_verdict(verdict)
    return verdicts


# --------------------------------------------------------------------------- #
# negative controls
# --------------------------------------------------------------------------- #
def _looks_like_path(ref: str) -> bool:
    """Is this fixture reference a file path rather than ``module:function``?

    ``.py`` anywhere, or a path separator, means path. The ``module:function``
    form has neither. A Windows ``C:\\x\\bad.py`` hits the ``.py`` test first,
    which is why that test comes first.
    """
    return ref.endswith(".py") or "/" in ref or os.sep in ref


def _load_py_file(path: str) -> Any:
    """Import a standalone .py file as a private module and return it.

    The module name is salted with a hash of the absolute path so two packs can
    each ship ``selftest/known_bad.py`` without the second one silently getting
    the first one's already-cached module — a collision that would make a gate
    selftest itself against somebody else's fixture and still look green.
    """
    absolute = os.path.abspath(path)
    module_name = f"_atompipe_fixture_{short_hash(absolute, 10)}"
    cached = sys.modules.get(module_name)
    if cached is not None:
        return cached

    spec = importlib.util.spec_from_file_location(module_name, absolute)
    if spec is None or spec.loader is None:
        raise AtompipeError(f"cannot load fixture {path}: not an importable Python file")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module            # before exec: dataclasses need it
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        # Not an Exception, so the clause below cannot see it. A fixture module
        # that exits at import — a dependency's "tool not installed" guard, say —
        # would otherwise take the whole `gate selftest` run down with whatever
        # exit code it chose, including 0. "Every control passed" and "the process
        # died during the first control" must never render the same.
        sys.modules.pop(module_name, None)
        raise AtompipeError(
            f"fixture {path} called sys.exit({exc.code!r}) while importing — a fixture "
            f"builds known-bad input, it does not exit the process; the gate it guards "
            f"is unproven until it stops"
        ) from exc
    except Exception as exc:                     # noqa: BLE001 - user's fixture code
        sys.modules.pop(module_name, None)
        raise AtompipeError(
            f"fixture {path} failed to import ({type(exc).__name__}: {exc}) — the "
            f"known-bad input is broken, so the gate it guards is unproven"
        ) from exc
    return module


def load_fixture(ref: str, root: str) -> Any:
    """Resolve a negative-control reference to the callable that builds it.

    Two accepted spellings, both from ``NegativeControl.fixture``:

    * ``"selftest/holed_mesh.py"`` — a file with a ``make(ctx)`` function.
      Relative paths resolve against ``root`` (the project root, or the pack
      directory when the caller knows it — see :func:`selftest`).
    * ``"pack.mod:make_brick"`` — an importable module and a function in it.
      A file path may also carry an explicit function: ``"selftest/x.py:other"``.

    Returns the callable, NOT the fixture. The caller invokes it with the real
    ``GateContext`` so the fixture can build its known-bad input relative to the
    real one — a control that ignores the context ends up testing a constant.

    Every failure here is an ``AtompipeError``: a missing or broken fixture is a
    pack-authoring mistake the user can fix, and it must surface loudly rather
    than degrade into "control unavailable, assume the gate is fine". That
    assumption is the one this module exists to refuse.
    """
    ref = (ref or "").strip()
    if not ref:
        raise AtompipeError("negative control has an empty fixture reference")

    func_name = ""
    target = ref
    if ":" in ref:
        head, _, tail = ref.rpartition(":")
        # Guard the Windows drive letter: "C:\x.py" must not split into ("C", "\x.py").
        if head and tail.isidentifier() and len(head) > 1:
            target, func_name = head, tail

    if _looks_like_path(target):
        path = target if os.path.isabs(target) else os.path.join(root or os.curdir, target)
        if not os.path.isfile(path):
            raise AtompipeError(
                f"negative-control fixture {target!r} does not exist "
                f"(looked in {os.path.abspath(path)}). The gate cannot be proven able "
                f"to fail until it does."
            )
        module = _load_py_file(path)
        wanted = func_name or "make"
        source = target
    else:
        try:
            module = importlib.import_module(target)
        except ImportError as exc:
            raise AtompipeError(
                f"cannot import negative-control fixture module {target!r}: {exc}"
            ) from exc
        except SystemExit as exc:                # BaseException: see _load_py_file
            raise AtompipeError(
                f"negative-control fixture module {target!r} called sys.exit({exc.code!r}) "
                f"while importing — the control cannot be built, so the gate is unproven"
            ) from exc
        except Exception as exc:                 # noqa: BLE001 - user's fixture code
            raise AtompipeError(
                f"negative-control fixture module {target!r} failed to import "
                f"({type(exc).__name__}: {exc})"
            ) from exc
        wanted = func_name or "make"
        source = target

    fn = getattr(module, wanted, None)
    if fn is None:
        raise AtompipeError(
            f"negative-control fixture {source!r} has no {wanted}() function — a fixture "
            f"exposes `def make(ctx):` returning a GateContext or a dict merged into "
            f"ctx.extra"
        )
    if not callable(fn):
        raise AtompipeError(f"negative-control fixture {source}:{wanted} is not callable")
    return fn


def _fixture_root(spec: GateSpec, ctx: GateContext, fn: Callable[..., Any] | None = None) -> str:
    """Where a relative fixture path is resolved from, most specific first.

    A pack's fixture is written ``selftest/steep_cone.py`` and lives in the PACK
    directory, not the project root — ``packs.validate`` resolves it against
    ``pack_dir`` and this must agree, or a control that validates cleanly would
    go missing the moment someone ran it. Four sources, in order:

    1. ``ctx.extra["pack_dirs"][spec.pack]`` — an explicit map from a caller that
       loaded several packs.
    2. ``ctx.extra["pack_dir"]`` — a caller working inside one pack.
    3. ``PACK_DIR`` on the gate function's own module. ``packs.load_gates`` sets
       it before executing each gate module, so this works with no cooperation
       from the caller at all, which is the case that actually happens.
    4. ``ctx.root`` — a project's own gates, whose ``selftest/`` sits beside the
       model.

    A fixture that resolves to nothing produces "does not exist, looked in
    <path>" from :func:`load_fixture` — naming the path it tried, because the
    alternative (a silent skip) would leave a gate unproven and looking fine.
    """
    extra = ctx.extra if isinstance(ctx.extra, dict) else {}
    pack_dirs = extra.get("pack_dirs")
    if isinstance(pack_dirs, dict) and spec.pack and pack_dirs.get(spec.pack):
        return str(pack_dirs[spec.pack])
    single = extra.get("pack_dir")
    if isinstance(single, str) and single:
        return single
    if fn is not None:
        module = sys.modules.get(getattr(fn, "__module__", "") or "")
        pack_dir = getattr(module, "PACK_DIR", "") if module is not None else ""
        if isinstance(pack_dir, str) and pack_dir:
            return pack_dir
    return ctx.root or os.curdir


def selftest(spec: GateSpec, fn: Callable[[GateContext], Any], ctx: GateContext) -> Verdict:
    """Run the gate against its own known-bad input. The verdict is on the GATE.

    ``passed=True`` here means *the gate correctly failed on input that is known
    to be bad* — it is a measurement of the instrument, not of the design. The
    canonical example: a simulator that runs its full scenario sweep a second time
    with the protective element removed and demands that the failure appear. That
    control proves nothing about the design and everything about the simulator.

    The returned verdict is filed under ``<gate id>#selftest`` and carries NO
    claims. Both are deliberate. Sharing the gate's id would overwrite its real
    verdict in ``Ledger.upsert_verdict``; attributing the gate's claims to a
    selftest would let "the instrument works" resolve a claim to PASS, which is
    exactly the laundering of assumption into proof that rule 5 exists to stop.

    Outcomes:

    * gate failed on the fixture         -> selftest PASSES (the control works)
    * gate PASSED on the fixture         -> selftest FAILS, bluntly: the gate is
      not measuring what it claims to measure
    * gate crashed on the fixture        -> selftest FAILS: refusing by exploding
      is not the same as detecting, and an exception cannot be trusted to have
      come from the defect the fixture planted
    * gate's tooling is missing          -> selftest SKIPS (nothing was tested)
    * fixture itself is missing/broken   -> selftest ERRORS (the control is gone,
      so the gate is unproven — never a pass)
    """
    selftest_id = f"{spec.id}#selftest"
    tier = Tier(int(spec.tier))

    def verdict(**kw: Any) -> Verdict:
        base = {"gate": selftest_id, "tier": tier, "pack": spec.pack, "claims": []}
        base.update(kw)
        return Verdict(**base)       # type: ignore[arg-type]

    nc = spec.negative_control
    if nc is None or not (nc.fixture or "").strip():
        # Registration forbids this, so reaching it means a hand-built spec that
        # never went through Registry.register. Still not an error: the honest
        # report of "this gate cannot be falsified" is a FAILING selftest.
        return verdict(
            passed=False,
            detail=f"{spec.id} declares no negative control, so there is nothing to "
                   f"prove it can fail — it is a logger until one exists",
        )

    expect = (nc.expect or "fail").strip().lower()
    if expect not in ("fail", "error"):
        return verdict(
            passed=False,
            error=f"negative_control.expect={nc.expect!r} is not understood",
            detail="expect must be 'fail' (the gate must not pass on this input) "
                   "or 'error'",
        )

    available, reason = availability(spec)
    if not available:
        return verdict(
            passed=False, skipped=True,
            skip_reason=f"{reason} — the gate could not be exercised, so its control is unproven",
        )

    started = time.perf_counter()
    try:
        make = load_fixture(nc.fixture, _fixture_root(spec, ctx, fn))
        built = make(ctx)
    except AtompipeError as exc:
        return verdict(
            passed=False, error="negative control unusable",
            detail=str(exc), duration_s=round(time.perf_counter() - started, 6),
        )
    except (SystemExit, GeneratorExit) as exc:
        # Same hole as run_gate's: neither is an Exception, so the clause below
        # would miss them and a fixture that exits would abort `gate selftest`
        # mid-run with nothing printed and nothing recorded. The honest reading of
        # a control that exits the process is that the control is unusable.
        code = exc.code if isinstance(exc, SystemExit) else None
        return verdict(
            passed=False,
            error=f"fixture called sys.exit({code!r})" if isinstance(exc, SystemExit)
                  else "fixture raised GeneratorExit",
            detail=f"{nc.fixture} must build known-bad input and return it, not exit the "
                   f"process — the control is unusable, so {spec.id} is unproven",
            duration_s=round(time.perf_counter() - started, 6),
        )
    except Exception as exc:                     # noqa: BLE001 - user's fixture code
        return verdict(
            passed=False, error=f"fixture raised {type(exc).__name__}: {exc}",
            detail=_trace_tail(traceback.format_exc()),
            duration_s=round(time.perf_counter() - started, 6),
        )

    if isinstance(built, GateContext):
        bad_ctx = built
    elif isinstance(built, dict):
        bad_ctx = ctx.with_extra(built)
    elif built is None:
        return verdict(
            passed=False, error="fixture returned None",
            detail=f"{nc.fixture} must return a GateContext or a dict to merge into "
                   f"ctx.extra; returning nothing means the gate ran against the GOOD "
                   f"input and any result is meaningless",
            duration_s=round(time.perf_counter() - started, 6),
        )
    else:
        return verdict(
            passed=False, error=f"fixture returned {type(built).__name__}",
            detail=f"{nc.fixture} must return a GateContext or a dict for ctx.extra",
            duration_s=round(time.perf_counter() - started, 6),
        )

    inner = run_gate(spec, fn, bad_ctx)
    elapsed = round(time.perf_counter() - started, 6)
    shared = {
        "measured": inner.measured, "limit": inner.limit, "units": inner.units,
        "evidence": list(inner.evidence or []), "duration_s": elapsed,
    }
    where = f"{nc.fixture}" + (f" ({nc.note})" if nc.note else "")

    if inner.skipped:
        return verdict(
            passed=False, skipped=True,
            skip_reason=inner.skip_reason or "gate skipped itself on the control input",
            **shared,
        )

    if expect == "error":
        # A control that expects a crash is unusual but legitimate: some gates
        # guard a parser, and "refuses to read the malformed file" IS the check.
        if inner.error:
            return verdict(passed=True,
                           detail=f"correctly errored on {where}: {inner.error}", **shared)
        return verdict(
            passed=False,
            detail=f"{spec.id} did not error on {where} as its control declares "
                   f"(passed={inner.passed}) — the control and the gate disagree about "
                   f"what this gate does",
            **shared,
        )

    if inner.error:
        return verdict(
            passed=False,
            detail=f"{spec.id} CRASHED on {where} instead of failing ({inner.error}) — "
                   f"an exception is not a measurement, and nothing here shows the gate "
                   f"detected the planted defect rather than tripping over it",
            **shared,
        )

    if inner.passed:
        return verdict(
            passed=False,
            detail=f"{spec.id} PASSED its own known-bad fixture {where} — it is not "
                   f"measuring what it claims to measure. Either the fixture is not bad "
                   f"in the way this gate checks, or the gate is a logger. Do not trust "
                   f"a green verdict from it until this fails.",
            **shared,
        )

    return verdict(
        passed=True,
        detail=f"correctly failed on {where}"
               + (f": {inner.detail}" if inner.detail else ""),
        **shared,
    )


# --------------------------------------------------------------------------- #
# description and summary
# --------------------------------------------------------------------------- #
def describe(spec: GateSpec) -> str:
    """One dense line for `atompipe gate list`. Never more than one.

    Everything a reader needs to decide whether to care: what it is, what it
    costs, what it settles, whether it can run here, and what its control is. The
    control is included on purpose — it is the fact that makes the gate's green
    tick mean anything, so it belongs in the listing and not three commands away.
    """
    bits = [f"{spec.id}  [t{int(spec.tier)}"]
    if spec.pack:
        bits[0] += f" {spec.pack}"
    bits[0] += "]"
    if spec.title:
        bits.append(spec.title)
    if spec.settles:
        bits.append(f"settles {spec.settles}")
    if spec.claims:
        bits.append("claims " + ",".join(spec.claims))
    needs = list(spec.requires_tools or []) + list(spec.requires_python or [])
    if needs:
        ok, reason = availability(spec)
        bits.append(("needs " + ",".join(needs)) if ok else f"BLOCKED: {reason}")
    nc = spec.negative_control
    bits.append(f"control {nc.fixture}" if nc and nc.fixture else "NO CONTROL")
    return _one_line("  ".join(bits), 240)


def registry_summary(registry: Registry) -> dict[str, Any]:
    """A JSON-safe overview of what this process can check, and what it cannot.

    Written for `atompipe doctor` and `--json`. The fields that matter are the
    negative ones: ``unavailable`` names every gate that would SKIP here and
    why, and ``max_tier`` versus ``by_tier`` shows whether a project has any
    cheap gates at all. A pack that ships only tier-2 gates has not finished its
    job (rule 10), and this is where that shows up as a number instead of as a
    twenty-minute inner loop nobody mentions.
    """
    specs = registry.specs()
    by_tier: dict[str, int] = {}
    by_pack: dict[str, int] = {}
    claims: set[str] = set()
    tools: set[str] = set()
    modules: set[str] = set()
    unavailable: list[dict[str, str]] = []

    for spec in specs:
        key = str(int(spec.tier))
        by_tier[key] = by_tier.get(key, 0) + 1
        pack = spec.pack or "(project)"
        by_pack[pack] = by_pack.get(pack, 0) + 1
        claims.update(c for c in (spec.claims or []) if c)
        tools.update(t for t in (spec.requires_tools or []) if t)
        modules.update(m for m in (spec.requires_python or []) if m)
        ok, reason = availability(spec)
        if not ok:
            unavailable.append({"gate": spec.id, "reason": reason})

    return {
        "gates": len(specs),
        "ids": [s.id for s in specs],
        "by_tier": by_tier,
        "by_pack": by_pack,
        "max_tier": max((int(s.tier) for s in specs), default=0),
        "tier0": by_tier.get("0", 0),
        "claims": sorted(claims),
        "requires_tools": sorted(tools),
        "requires_python": sorted(modules),
        "available": len(specs) - len(unavailable),
        "unavailable": unavailable,
        "without_negative_control": [
            s.id for s in specs
            if not (s.negative_control and (s.negative_control.fixture or "").strip())
        ],
    }
