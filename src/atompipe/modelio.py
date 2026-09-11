# SPDX-License-Identifier: Apache-2.0
"""atompipe.modelio — the model contract: one parametric model, one truth.

Rule 1 of the method is that a single parametric model is the only source of
truth and everything else is generated from it. This module is where that rule
stops being a slogan and becomes an interface:

    model/<thing>.py
        CONFIG: <dataclass instance>        # every input, and nothing else
        def build(config) -> dict           # every derived quantity, pure
        PARAMS: list[Param] = [...]         # optional, the provenance

Nothing downstream — no gate, no report, no generator — is allowed to hold an
input of its own. It asks for the PROJECTION instead: a flat, JSON-safe,
diffable view of the config plus everything `build()` resolved, which is also
what staleness is judged against (`model_hash`).

Three things here exist because of specific failures, not because a loader is
traditional:

* **No silent coercion.** A projection value that is not JSON-safe raises
  `AtompipeError` naming the exact field. The tempting alternative — `default=
  str` on `json.dumps` — turns a `Vector3` into `"<Vector3 object at 0x7f...>"`,
  which hashes differently on every run and makes a model and its projection
  drift apart without a single error message. Drift between two representations
  of the same thing is exactly what a cross-representation check is written to
  catch, and catching it at this boundary is cheaper than catching it downstream.

* **The import error is the product.** A traceback from inside a user's model is
  the single most common thing anyone hits here — a typo, a missing third-party
  dependency, a divide by zero in `build()`. `load_model` and `project` catch it
  and re-raise as `AtompipeError` carrying the real exception text AND the line
  in the user's file, because "ZeroDivisionError" with no location is a worse
  message than the traceback it replaced.

* **Determinism is assertable.** `check_determinism` builds twice and diffs.
  Byte-identical output makes a sound acceptance gate for a large refactor:
  if the result is bit-for-bit the same, the refactor changed
  nothing, and that is a proof no amount of reading the diff can give you. A
  model that cannot pass this one has a clock, a `set`, or a `random` in it, and
  every hash-based staleness check downstream is already lying.

Time policy (contract rule 3): nothing here reads the clock. `build()` is
supposed to be pure, and a model that stamps its own timestamp fails
`check_determinism` on purpose.
"""
from __future__ import annotations

import ast
import inspect

import dataclasses
import importlib.machinery
import importlib.util
import json
import math
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any

from . import store
from .models import Param, _enc
from .util import AtompipeError, atomic_write_json, rel, short_hash

__all__ = [
    "LoadedModel",
    "load_model",
    "project",
    "model_hash",
    "write_projection",
    "params_from_model",
    "undocumented_params",
    "check_determinism",
]

#: Loaded model modules are registered in `sys.modules` under this prefix rather
#: than under their own stem. A project that names its model `model/types.py` or
#: `model/email.py` — and people do, because the directory is theirs — would
#: otherwise shadow a stdlib module for the rest of the process, and the failure
#: lands somewhere else entirely, minutes later, in code that never heard of the
#: model. The prefix costs nothing and makes that impossible.
_MODULE_PREFIX = "atompipe_model_"

#: This file, so user tracebacks can be trimmed of spine frames.
_THIS_FILE = os.path.abspath(__file__)


# --------------------------------------------------------------------------- #
# the loaded model
# --------------------------------------------------------------------------- #
@dataclass
class LoadedModel:
    """A model module that has been imported, with its config resolved.

    This type deliberately does NOT live in `models.py`: it holds a live module
    object and a live dataclass instance, neither of which can cross the JSON
    boundary. Everything that IS persisted about a model — the params, the
    projection, the hash — is a plain dict or a `models.Param` by the time it
    leaves this module.

    `entry` is stored repo-relative (`model/bracket.py`) to match
    `ProjectMeta.model_entry`, so a record written on one machine still resolves
    on another.
    """

    module: Any
    config: Any
    entry: str
    params: list[Param] = field(default_factory=list)

    @property
    def file(self) -> str:
        """Absolute path of the file that was executed.

        Derived from the module rather than stored a second time (rule 2): two
        fields that must agree about the same path are two fields that will
        eventually disagree.
        """
        return os.path.abspath(getattr(self.module, "__file__", "") or "")

    @property
    def directory(self) -> str:
        """Directory the model was loaded from — where its sibling files live."""
        path = self.file
        return os.path.dirname(path) if path else ""


# --------------------------------------------------------------------------- #
# error rendering:  the user's traceback, in one line
# --------------------------------------------------------------------------- #
def _user_location(exc: BaseException) -> str:
    """`  at model/bracket.py:87 in build` for the deepest frame OUTSIDE the spine.

    The deepest non-spine frame is where the user's code actually broke. Keeping
    just that line (plus the source text) is the whole difference between an
    error a user can fix and one they have to reproduce under a debugger; the
    twelve frames of importlib machinery above it teach nobody anything.
    """
    if isinstance(exc, SyntaxError) and exc.filename:
        # A SyntaxError never reaches a frame in the user's file — the module
        # body was never executed — so its location lives on the exception.
        where = f"\n  at {exc.filename}:{exc.lineno or 0}"
        return f"{where}\n    {exc.text.strip()}" if exc.text else where

    frames = traceback.extract_tb(exc.__traceback__)
    outside = [f for f in frames if os.path.abspath(f.filename or "") != _THIS_FILE]
    if not outside:
        return ""
    frame = outside[-1]
    where = f"\n  at {frame.filename}:{frame.lineno} in {frame.name}"
    return f"{where}\n    {frame.line.strip()}" if frame.line else where


def _explain(exc: BaseException) -> str:
    """`ZeroDivisionError: float division by zero` + where it happened.

    `ModuleNotFoundError` gets an extra sentence because it is both the most
    common failure and the one most often misread as an atompipe bug: the SPINE
    is standard-library only, a user's MODEL is not required to be, and the
    thing to do about it is `pip install`, not file an issue.
    """
    text = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, ModuleNotFoundError) and exc.name:
        text += (
            f"\n  the model imports {exc.name!r}, which is not installed in this "
            f"interpreter ({sys.executable}) — install it, or keep the model "
            f"standard-library only so the project runs on a fresh machine"
        )
    return text + _user_location(exc)


# --------------------------------------------------------------------------- #
# JSON safety:  the boundary where drift is caught
# --------------------------------------------------------------------------- #
def _json_problem(path: str, value: Any) -> str:
    """The message for one non-JSON-safe projection value. Names the field.

    Every branch here says what to do in `build()`, because the answer is always
    "return a different value", never "atompipe will handle it".
    """
    kind = type(value).__name__
    if isinstance(value, (set, frozenset)):
        # Worse than merely unserialisable: a set's iteration order depends on
        # string hash randomisation, so it differs between PROCESSES. Coercing
        # one to a list would give a projection that hashes differently on every
        # run and marks every gate result stale for no reason.
        return (
            f"{path} is a {kind}; JSON has no set, and a set's iteration order "
            f"changes between processes (PYTHONHASHSEED), so the model hash "
            f"would differ on every run — return sorted(...) from build()"
        )
    if callable(value):
        return (
            f"{path} is a {kind} (a callable); build() returns DATA, not "
            f"behaviour — call it and return the result"
        )
    return (
        f"{path} is a {kind}, which is not JSON-safe. Convert it in build() "
        f"(float(), str(), list(), or .to_dict()) — the spine will not coerce "
        f"it for you, because a coerced value and the model it came from drift "
        f"apart with no error to notice"
    )


def _check_json_safe(value: Any, path: str, seen: set[int] | None = None) -> None:
    """Walk `value`, raising AtompipeError at the first field JSON cannot hold.

    Runs AFTER `models._enc`, so dataclasses, enums and tuples are already
    primitives; anything still exotic at this point is something the model
    genuinely invented and genuinely has to fix.

    Three rejections here are stricter than `json.dumps` and each one is
    deliberate:

    * **NaN / Infinity.** `json.dumps` happily emits the bare tokens `NaN` and
      `Infinity`, which are not JSON (RFC 8259) and which every non-Python
      reader — jq, a browser, a fab house's importer — rejects. Worse, a NaN
      defeats `Acceptance.holds` silently: `nan <= limit` is False and
      `nan > limit` is also False, so a claim backed by a NaN can neither pass
      nor fail, it just quietly never proves anything. That is a logger, not a
      gate.
    * **Non-string dict keys.** `json.dumps({1: "a"})` returns `{"1": "a"}` with
      no complaint, so the value that comes back from disk is no longer the
      value that went in. That is the definition of drift.
    * **Cycles.** `models._enc` normally hits a self-referencing structure
      first and dies of recursion, which `_safe` translates; this guard is the
      backstop for anyone walking a structure `_enc` never touched.
    """
    if value is None or isinstance(value, (str, bool, int)):
        return                                    # bool is an int; both are fine
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise AtompipeError(
                f"{path} is {value!r}. NaN and Infinity are not JSON, and a NaN "
                f"silently defeats every claim comparator (nan <= x and nan > x "
                f"are both False), so a gate reading it can never fail or pass "
                f"— guard the division in build() and return None instead"
            )
        return

    if isinstance(value, (dict, list)):
        seen = set() if seen is None else seen
        if id(value) in seen:
            raise AtompipeError(
                f"{path} contains a reference back to a container that already "
                f"encloses it; a cyclic structure cannot be serialised"
            )
        seen = seen | {id(value)}
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise AtompipeError(
                        f"{path} has a non-string key {key!r} "
                        f"({type(key).__name__}); JSON object keys are strings "
                        f"and json.dumps would stringify it silently, so the "
                        f"projection would stop round-tripping — use str keys"
                    )
                _check_json_safe(item, f"{path}.{key}", seen)
        else:
            for index, item in enumerate(value):
                _check_json_safe(item, f"{path}[{index}]", seen)
        return

    raise AtompipeError(_json_problem(path, value))


def _safe(value: Any, path: str) -> Any:
    """`models._enc` then validate. The only way a value enters a projection.

    The RecursionError catch is not paranoia: `_enc` (and `dataclasses.asdict`
    underneath it) walks a structure blindly, so a dict that contains itself —
    or a parent/child pair of dataclasses pointing at each other, which is how
    most people's first assembly tree gets written — exhausts the stack *before*
    the validator ever sees a field. Left alone that surfaces as a thousand-line
    traceback through `_enc`, naming nothing the user can act on.
    """
    try:
        encoded = _enc(value)
        _check_json_safe(encoded, path)
    except RecursionError as exc:
        raise AtompipeError(
            f"{path} could not be encoded: it nests too deeply, or a value "
            f"refers back to a container that encloses it. build() returns a "
            f"tree, not a graph — replace the back-reference with a name or an id"
        ) from exc
    return encoded


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def _resolve_entry(root: str, entry: str | None) -> str:
    """Absolute path of the model file, from an explicit entry or the ledger.

    Deliberately does NOT guess. If the ledger has no `model_entry`, this lists
    what it can see under `model/` and asks the user to pick — a loader that
    guesses "the only .py file in model/" works right up until there are two,
    and then silently analyses the wrong one.
    """
    if not entry:
        meta = store.load(root).meta
        entry = (meta.model_entry or "").strip()
    if not entry:
        candidates = _model_candidates(root)
        hint = (
            f" — found {', '.join(candidates)}" if candidates
            else " — write one (a dataclass CONFIG plus build(config) -> dict)"
        )
        raise AtompipeError(
            f"no model entry recorded for this project: set "
            f"meta.model_entry in {rel(store.ledger_path(root), root)} to the "
            f"model file{hint}"
        )

    path = entry if os.path.isabs(entry) else os.path.join(root, entry)
    path = os.path.abspath(path)

    if os.path.isdir(path):
        # A model that grew into a package: `model/hull/` with an __init__.py.
        # A model routinely grows into a package of many modules; this must keep working.
        package_init = os.path.join(path, "__init__.py")
        if not os.path.isfile(package_init):
            raise AtompipeError(
                f"model entry {entry!r} is a directory with no __init__.py; "
                f"point meta.model_entry at a .py file, or add "
                f"{rel(package_init, root)}"
            )
        return package_init

    if not os.path.isfile(path):
        raise AtompipeError(
            f"model entry {entry!r} does not exist (looked in "
            f"{rel(path, root)}); fix meta.model_entry or create the file"
        )
    return path


def _model_candidates(root: str) -> list[str]:
    """Plausible model files under `model/`, for the "you have no entry" message."""
    directory = store.model_dir(root)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    return [
        rel(os.path.join(directory, n), root)
        for n in names
        if n.endswith(".py") and not n.startswith("_")
    ][:8]


class _FreshLoader(importlib.machinery.SourceFileLoader):
    """A source loader that never consults or writes `__pycache__`.

    This is not an optimisation, it is a correctness fix, and it was found by
    smoke-testing the obvious thing: load the model, edit `thickness: float =
    7.0` to `8.0`, load it again — and get the OLD value back, with no error and
    no warning.

    Python validates a cached `.pyc` against the source's mtime (whole seconds)
    and its size in bytes. `7.0` and `8.0` are the same size, and a tier-0 loop
    that promises to run in seconds means the re-run happens inside the same
    second. Both checks pass, the stale bytecode is executed, and `atompipe
    check` confidently reports yesterday's geometry as today's. That is the
    exact failure this whole module exists to prevent — the model changed and
    the projection did not — arriving through the back door.

    Overriding `get_code` to compile the source every time costs a millisecond
    on a file a human wrote and closes it. `source_to_code` still compiles with
    `dont_inherit=True`, so the spine's own `from __future__ import annotations`
    does not silently leak into a model that never asked for it.

    Residual, and worth knowing when a model is split across files: only the
    ENTRY module is loaded this way. Sibling modules go through the normal
    import machinery and can still be served from a `__pycache__` left behind by
    running the model by hand. By contract every INPUT lives in the entry file's
    `CONFIG` dataclass, so the constants people actually edit are covered.
    """

    def get_code(self, fullname: str) -> Any:
        return self.source_to_code(self.get_source(fullname), self.path)


def _import_file(path: str) -> Any:
    """Execute the model file as a module, with its own directory importable.

    The directory goes on `sys.path` so a model can split itself across several
    files (`import geometry` next to `bracket.py`) without becoming a package
    first. It is removed again afterwards, and that removal is not politeness:
    a `model/` directory containing `types.py` or `json.py` on `sys.path` will
    shadow the standard library for every later import in the process,
    including the spine's own. The window is kept as short as the import itself.

    The consequence, which is worth knowing when you split a model: import your
    sibling modules at MODULE level, not lazily inside `build()`. By the time
    `build()` runs, the path is back to normal — module-level imports are
    already cached in `sys.modules`, a first lazy import is not.

    Only paths this function actually ADDED are removed, so a model that
    legitimately extends `sys.path` for itself keeps its addition.
    """
    directory = os.path.dirname(path)
    is_package = os.path.basename(path) == "__init__.py"

    # For a package, the PARENT is what makes `import hull.parts` resolve; the
    # package directory itself is what makes flat sibling imports resolve. Both,
    # in that order, so the package name wins over a same-named submodule.
    additions = [directory]
    if is_package:
        additions.insert(0, os.path.dirname(directory))

    stem = os.path.basename(directory) if is_package else os.path.splitext(os.path.basename(path))[0]
    name = _MODULE_PREFIX + (stem or "model")

    spec = importlib.util.spec_from_file_location(
        name,
        path,
        loader=_FreshLoader(name, path),          # never a stale .pyc; see above
        submodule_search_locations=[directory] if is_package else None,
    )
    if spec is None or spec.loader is None:       # a .py we cannot make a spec for
        raise AtompipeError(
            f"cannot import {path}: python does not recognise it as a module "
            f"(is it a .py file?)"
        )

    module = importlib.util.module_from_spec(spec)
    added = [d for d in additions if d and d not in sys.path]
    for d in reversed(added):
        sys.path.insert(0, d)
    # Registered BEFORE execution: a module that imports itself, a dataclass
    # that resolves its own annotations, and pickling all look the module up by
    # name while the body is still running.
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException as exc:                  # noqa: BLE001 - re-raised below
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        raise AtompipeError(f"model {path} failed to import\n  {_explain(exc)}") from exc
    finally:
        for d in added:
            try:
                sys.path.remove(d)
            except ValueError:                    # the model removed it itself
                pass
    return module


def _resolve_config(module: Any, path: str) -> Any:
    """Find the config: `CONFIG` first, then `Config()`.

    Both spellings are accepted because both are honest. `CONFIG = Config()` is
    what a model writes once it has non-default values it wants to keep; a bare
    `Config` dataclass with defaults is what a model starts as. Refusing the
    second would make the first five minutes of a project feel like paperwork.

    What is NOT accepted is a plain dict or a namespace. `params_from_model`
    reads field order, defaults and types out of `dataclasses.fields`, and a
    dict has none of those — the provenance of a number would have nowhere to
    live.
    """
    config = getattr(module, "CONFIG", None)

    if config is None or isinstance(config, type):
        # `CONFIG = Config` (the class, not an instance) is a common slip and
        # means exactly what `Config` alone means, so treat them the same.
        factory = config if isinstance(config, type) else getattr(module, "Config", None)
        if isinstance(factory, type):
            try:
                config = factory()
            except Exception as exc:              # noqa: BLE001 - user's __init__
                raise AtompipeError(
                    f"{path} defines Config but Config() could not be "
                    f"constructed with no arguments; give every field a default "
                    f"or add `CONFIG = Config(...)`\n  {_explain(exc)}"
                ) from exc

    if config is None:
        raise AtompipeError(
            f"{path} exposes no model config: expected a module-level `CONFIG` "
            f"(a dataclass instance) or a `Config` dataclass constructible with "
            f"no arguments"
        )

    if not dataclasses.is_dataclass(config) or isinstance(config, type):
        raise AtompipeError(
            f"CONFIG in {path} is a {type(config).__name__}, not a dataclass "
            f"instance. The config carries the field order, defaults and types "
            f"that every parameter's provenance hangs off — use "
            f"`@dataclass class Config: ...` and `CONFIG = Config()`"
        )
    return config


def load_model(root: str, entry: str | None = None) -> LoadedModel:
    """Import the project's model and resolve its config and params.

    `entry` defaults to `ledger.meta.model_entry`; pass it explicitly to load a
    model that is not the project's own (a fixture, a candidate revision) with
    no ledger read at all — that saves the tier-0 loop a file read it does not
    need (rule 10).

    Everything a user can get wrong here — a missing file, a syntax error, an
    uninstalled import, a config that is a dict — raises `AtompipeError` with
    the real message and the line it came from. That is the whole job: this is
    the first spine function a new project touches, and it is the one that most
    often has something to say.
    """
    path = _resolve_entry(root, entry)
    module = _import_file(path)
    relative = rel(path, root)

    config = _resolve_config(module, relative)

    builder = getattr(module, "build", None)
    if not callable(builder):
        raise AtompipeError(
            f"{relative} has no `build(config) -> dict`. The model is the only "
            f"source of truth, and build() is how everything downstream — "
            f"gates, reports, generators — reads it; without it the model is a "
            f"pile of constants nobody can check"
        )

    model = LoadedModel(module=module, config=config, entry=relative)
    model.params = params_from_model(model)
    return model


# --------------------------------------------------------------------------- #
# projection
# --------------------------------------------------------------------------- #
def project(model: LoadedModel) -> dict[str, Any]:
    """Run `build()` and return `{"config": {...}, "derived": {...}}`, JSON-safe.

    This is the ONLY view of a model the rest of the spine gets. A gate is
    handed the projection, not the module, which is what stops a gate from
    recomputing a section modulus slightly differently from the model and
    "proving" a claim about a part that does not exist (rule 2).

    `config` is the dataclass fields verbatim: the inputs. `derived` is whatever
    `build()` returned: the consequences. The split is what lets a report say
    "you changed `thickness`" instead of "137 numbers changed".

    Every value passes through `models._enc` and is then VALIDATED. A value JSON
    cannot hold raises `AtompipeError` naming the field — see `_check_json_safe`
    for why each rejection is stricter than `json.dumps` is.
    """
    builder = getattr(model.module, "build", None)
    if not callable(builder):                     # re-checked: callers construct
        raise AtompipeError(f"{model.entry} has no callable build(config)")

    try:
        derived = builder(model.config)
    except AtompipeError:
        raise                                     # the model used our error type
    except Exception as exc:                      # noqa: BLE001 - user's build()
        raise AtompipeError(
            f"{model.entry}: build(config) raised\n  {_explain(exc)}"
        ) from exc

    if not isinstance(derived, dict):
        raise AtompipeError(
            f"{model.entry}: build(config) returned {type(derived).__name__}, "
            f"expected a dict of derived values. Every gate reads this dict by "
            f"key name; a tuple or an object gives them nothing to ask for"
        )

    return {
        "config": _safe(model.config, "config"),
        "derived": _safe(derived, "derived"),
    }


def _canonical(projection: dict[str, Any]) -> str:
    """The one byte-level representation of a projection.

    `sort_keys` because a dict's insertion order is not part of the model's
    meaning and must not change its hash. `allow_nan=False` so a NaN that
    somehow skipped validation fails loudly instead of hashing as the token
    `NaN`. Compact separators because nothing reads this string — the readable
    copy is what `write_projection` puts on disk.
    """
    try:
        return json.dumps(
            projection,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as exc:
        raise AtompipeError(
            f"projection is not JSON-serialisable ({exc}); build it with "
            f"modelio.project(), which validates every field and names the one "
            f"that is wrong"
        ) from exc


def model_hash(projection: dict[str, Any]) -> str:
    """Stable short hash of a projection. Drives staleness, and nothing else.

    Staleness is the quiet failure this exists to prevent: gates pass, someone
    edits `thickness`, and the report keeps showing yesterday's green. Recording
    this hash with a run (`RunMeta.model_hash`) makes "these verdicts describe a
    model that no longer exists" a computable fact instead of a habit.

    Stable means stable across PROCESSES, not just within one — which is why
    `project()` rejects sets (hash-randomised iteration order) and why this
    sorts keys. 12 hex chars: enough to distinguish revisions, short enough to
    sit in a run filename and be compared by eye.
    """
    return short_hash(_canonical(projection))


def write_projection(root: str, projection: dict[str, Any]) -> str:
    """Write `.atompipe/model.json` and return its path.

    This file is the diffable view of the model: sorted keys, indent 2, one
    value per line, so `git diff` after a parameter change reads as "deflection
    0.70 -> 0.47" rather than as one enormous line. It is generated output —
    deleting it loses nothing — but it is the artefact that makes a design
    change reviewable by someone who does not read Python.

    Written EXACTLY as given, with no hash or timestamp folded in: a file that
    contains its own hash cannot be checked against `model_hash(read_json(...))`
    by anyone, and a generated file with a timestamp in it changes on every
    build and teaches every reviewer to ignore its diff.
    """
    path = store.project_paths(root)["projection"]
    atomic_write_json(path, projection)
    return path


# --------------------------------------------------------------------------- #
# parameters and their provenance
# --------------------------------------------------------------------------- #
def _explicit_params(module: Any, entry: str) -> list[Param]:
    """Read the model's optional `PARAMS`, tolerantly but not silently.

    Dicts are accepted alongside `Param` instances because a model that
    generates its parameter table (from a CSV of stock sizes, say) naturally
    produces dicts, and `Param.from_dict` is the contract's own reader.
    """
    raw = getattr(module, "PARAMS", None)
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)) or not isinstance(raw, (list, tuple)):
        raise AtompipeError(
            f"{entry}: PARAMS must be a list of Param records, got "
            f"{type(raw).__name__}"
        )

    params: list[Param] = []
    seen: dict[str, int] = {}
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            # `value` is a required field on Param but a POINTLESS one to write
            # here: for anything that is also a config field the dataclass owns
            # the value and this one is overwritten below. Defaulting it to None
            # is what lets a model write the useful half — the units and the
            # rationale — without restating a number it would only get wrong.
            item = Param.from_dict({"value": None, **item})
        if not isinstance(item, Param):
            raise AtompipeError(
                f"{entry}: PARAMS[{index}] is a {type(item).__name__}; every "
                f"entry must be an atompipe Param (or a dict of one)"
            )
        name = (item.name or "").strip()
        if not name:
            raise AtompipeError(
                f"{entry}: PARAMS[{index}] has no name; a parameter's name is "
                f"how a claim, a gate and a decision all refer to the same number"
            )
        if name in seen:
            # Silently keeping the last one loses whichever rationale was
            # written first, and the loss is invisible in the report.
            raise AtompipeError(
                f"{entry}: PARAMS declares {name!r} twice (entries "
                f"{seen[name]} and {index}); merge them"
            )
        seen[name] = index
        params.append(item)
    return params


def _config_source(model: LoadedModel) -> str:
    """Absolute path of the file defining the model's config class.

    Falls back through the module's own `__file__` and finally the recorded entry,
    because every one of these can legitimately be missing (a class built by a
    decorator, a module loaded from a zip) and losing prose must never be fatal.
    """
    for getter in (lambda: inspect.getfile(type(model.config)),
                   lambda: getattr(model.module, "__file__", "") or "",
                   lambda: model.entry):
        try:
            path = getter()
        except (TypeError, OSError):
            continue
        if path and os.path.isfile(path):
            return path
    return model.entry


def field_docstrings(entry: str, class_name: str) -> dict[str, str]:
    """Attribute docstrings from the model's config dataclass, by AST.

    Python has no runtime access to the string literal that follows a field:

        @dataclass
        class Config:
            thickness: float = 7.0
            '''mm. 4.0 was tried and misses the deflection limit by ~5x.'''

    ...but that is exactly where a careful author writes the rationale, because it
    is the idiomatic place and it sits against the value it explains. Parsing it
    out means rule 3 (every constant carries its provenance) costs nothing beyond
    normal Python, and — more importantly — it avoids the trap of demanding a
    parallel `PARAMS` table that repeats every field name. That table would be a
    second source of truth for the field list, which is precisely what rule 2
    forbids, and it would drift the first time somebody added a field.

    So: `PARAMS` stays available for what a docstring cannot carry (rejected
    alternatives, units as data, gate bindings), and the docstring carries the
    prose. An explicit `PARAMS` rationale wins over a docstring when both exist.

    Returns {} on any parse failure — a model that cannot be parsed can still be
    imported and run, and losing prose is not a reason to refuse to load.
    """
    try:
        with open(entry, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=entry)
    except (OSError, SyntaxError):
        return {}

    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != class_name:
            continue
        body = node.body
        for i, stmt in enumerate(body):
            # A field is `name: type` or `name: type = default`; its docstring is
            # the bare string expression immediately after it.
            if not isinstance(stmt, ast.AnnAssign) or not isinstance(stmt.target, ast.Name):
                continue
            if i + 1 >= len(body):
                continue
            nxt = body[i + 1]
            if (isinstance(nxt, ast.Expr) and isinstance(nxt.value, ast.Constant)
                    and isinstance(nxt.value.value, str)):
                text = " ".join(nxt.value.value.split())
                if text:
                    out[stmt.target.id] = text
    return out


def params_from_model(model: LoadedModel) -> list[Param]:
    """Merge the model's `PARAMS` provenance with its dataclass fields.

    The split of duties is the point:

    * the **dataclass field** owns the VALUE — always, even when `PARAMS` states
      one. A literal repeated in `PARAMS` is a second source of truth, and the
      two WILL drift (that is rule 2, and it is not a hypothetical: a config
      says 7.0, a params table says 6.0, and the report defends a number the
      part was never built with). The field wins, silently and by design.
    * **`PARAMS`** owns everything a field cannot express: units, the rationale,
      the rejected alternatives, the source, which gates protect it.

    Order is the model's own field order, then any `PARAMS` entry that matches
    no field — those are kept, because a model legitimately documents constants
    that live outside the config (a material property, a fastener standard).

    Fields with no `PARAMS` entry still become `Param`s, with empty units and an
    empty rationale, and `undocumented_params` is how the report nags about
    them. A number with no rationale is a number nobody can defend.
    """
    declared = {p.name: p for p in _explicit_params(model.module, model.entry)}
    # Resolve from the CLASS, not from `model.entry`. `entry` is the relative path
    # the ledger stores, and a model that has grown into a package defines its
    # config in whichever module it likes — the docstrings live with the class, so
    # ask the class where it lives.
    docs = field_docstrings(_config_source(model), type(model.config).__name__)
    used: set[str] = set()
    merged: list[Param] = []

    for f in dataclasses.fields(model.config):
        value = _safe(getattr(model.config, f.name), f"config.{f.name}")
        param = declared.get(f.name)
        if param is None:
            merged.append(Param(name=f.name, value=value,
                                rationale=docs.get(f.name, "")))
            continue
        used.add(f.name)
        # An explicit PARAMS rationale wins; the docstring fills the gap when it
        # is silent, so the two can be used together without either being a
        # partial duplicate of the other.
        if not param.rationale and f.name in docs:
            param = dataclasses.replace(param, rationale=docs[f.name])
        # Copy, so repeated calls cannot mutate the model module's own PARAMS
        # list — a loader that edits the thing it loaded is a loader that gives
        # a different answer the second time it is called.
        merged.append(dataclasses.replace(param, value=value))

    for name, param in declared.items():
        if name not in used:
            merged.append(
                dataclasses.replace(param, value=_safe(param.value, f"PARAMS.{name}"))
            )
    return merged



def sync_params(ledger, model: LoadedModel) -> list[Param]:
    """Refresh `ledger.params` from the model, preserving ledger-only provenance.

    Two stores hold a parameter and neither is redundant:

    * the **model** owns the VALUE, the units and the rationale. It is the single
      source of truth (rule 1), and re-reading it on every sweep is what stops the
      ledger defending a number the design no longer has.
    * the **ledger** owns everything the model cannot express and a human or agent
      accumulated over time: rejected alternatives, which input artifacts ground
      it, which gates protect it, which decision last moved it.

    So this merges rather than replaces. A param the model still defines keeps its
    ledger provenance and takes the model's current value; a param the model has
    DROPPED is kept, flagged by `orphan_params`, because deleting it would silently
    destroy the record of why it once existed — and a parameter that disappears
    without explanation is exactly the kind of hole the decision log exists to
    prevent. Call it whenever the model is loaded.
    """
    from_model = {p.name: p for p in params_from_model(model)}
    existing = {p.name: p for p in ledger.params}
    merged: list[Param] = []

    for name, fresh in from_model.items():
        old = existing.get(name)
        if old is None:
            merged.append(fresh)
            continue
        # Model wins on value/units/derivation; ledger wins on accumulated provenance.
        merged.append(dataclasses.replace(
            old,
            value=fresh.value,
            units=fresh.units or old.units,
            rationale=fresh.rationale or old.rationale,
            derived_from=fresh.derived_from or old.derived_from,
        ))

    for name, old in existing.items():
        if name not in from_model:
            merged.append(old)          # orphan: kept, reported, never silently dropped

    ledger.params = merged
    return merged


def orphan_params(ledger, model: LoadedModel) -> list[str]:
    """Ledger params the model no longer defines.

    Either the model dropped a parameter and the record should be retired with a
    decision entry, or the parameter was renamed and its provenance is now
    stranded — pointing at nothing while every `grounded_by` still references it.
    Both are worth a line in the report rather than a silent deletion.
    """
    live = {p.name for p in params_from_model(model)}
    return [p.name for p in ledger.params if p.name not in live]

def undocumented_params(model: LoadedModel) -> list[str]:
    """Names of parameters carrying no rationale. The report's nag list.

    The test is the rationale, not the paperwork: a `Param` that exists in
    `PARAMS` with `rationale=""` is exactly as undefended as a field nobody
    mentioned. "It was 7 when it worked" is not a rationale, but at least it is
    a sentence someone can argue with; an empty string is a number that will be
    re-litigated by every fresh reader forever, which is the cost `Rejected`
    exists to eliminate.

    Returned in model field order, so the list reads like the config file.
    """
    return [p.name for p in (model.params or params_from_model(model))
            if not (p.rationale or "").strip()]


# --------------------------------------------------------------------------- #
# determinism
# --------------------------------------------------------------------------- #
def _first_difference(a: Any, b: Any, path: str) -> str | None:
    """First field where two projections disagree, or None. Depth-first, sorted.

    Reporting the FIELD rather than "the projections differ" is the difference
    between a five-minute fix (`mass_g` moved in the 14th decimal: a set got
    iterated) and an afternoon of bisecting a build function.
    """
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                return f"{path}.{key}: absent in the first run, present later"
            if key not in b:
                return f"{path}.{key}: present in the first run, absent later"
            found = _first_difference(a[key], b[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return f"{path}: length {len(a)} then {len(b)}"
        for index, (x, y) in enumerate(zip(a, b)):
            found = _first_difference(x, y, f"{path}[{index}]")
            if found:
                return found
        return None
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} {a!r} then {type(b).__name__} {b!r}"
    if a != b:
        return f"{path}: {a!r} then {b!r}"
    return None


def check_determinism(model: LoadedModel, runs: int = 2) -> tuple[bool, str]:
    """Build the model `runs` times and prove the projection does not move.

    Byte-identical output makes a sound acceptance gate for a
    4,250-line refactor: if every exported mesh hashes the same before and
    after, the refactor changed nothing, and no amount of reading the diff gives
    you that. The same property one level up is this function.

    It is also a precondition for everything hash-based downstream. If `build()`
    is not deterministic then `model_hash` is noise, every run looks stale, and
    "the model changed" stops meaning anything. The usual culprits, in the order
    they show up: a `set` in the output (hash-randomised between processes), a
    timestamp, a `random`, a dict keyed by object identity, and a `build()` that
    MUTATES the config it was handed — which this catches precisely because the
    same config instance is reused across runs rather than being deep-copied.

    Returns `(ok, detail)` where `detail` is one line naming the first field
    that moved, so a verdict can carry it. Never raises for a non-deterministic
    model: that is a finding, not a crash. It DOES raise `AtompipeError` if
    `build()` itself fails, because that is a different problem with a different
    fix.
    """
    if runs < 2:
        # A programming error, not a user error: one run cannot disagree with
        # itself, and silently returning True would be a gate that cannot fail.
        raise ValueError(f"check_determinism needs at least 2 runs, got {runs}")

    first = project(model)
    first_text = _canonical(first)
    digest = short_hash(first_text)

    for run in range(2, runs + 1):
        current = project(model)
        if _canonical(current) == first_text:
            continue
        where = _first_difference(first, current, "projection") or "(unlocatable)"
        return False, (
            f"build() is not deterministic: run {run} differs from run 1 at {where}"
        )

    return True, f"{runs} builds identical (model hash {digest})"
