# SPDX-License-Identifier: Apache-2.0
"""derivation.py — the trace: derivation observed by perturbation (SPEC 39).

`nopekit model trace` rebuilds the model in temporary copies of the project,
each numeric choice (a ``Config`` field) moved by -10% and +10% in turn, and
records which derived values moved and by how much. The result is the trace,
``.nopekit/trace/<k16>.json``: keyed by the digests of the instructions and of
every choice's value, tracked, written once and only whole, never rewritten.
From it the graph gains its ``derives`` edges (choice -> derived value) and an
order between derived values (``after``, inferred), and the map gains its
middle: which zones feed which stations, and in what order a claim's line rides
them (architecture phase 3b).

Beside it sits **amber**: each automated claim's evaluators re-run, by the
check run's own rules, on the designs rebuilt with an assumption-sourced choice
moved. A Checked pass that a ±10% move of an unconfirmed assumption flips is
shown amber beside Checked. Amber is a display token: it moves no status, no
exit code, no readiness (invariant 12; `claims.py` never imports this module).

**What the trace says, and no more** (invariant 16). A choice it did not move
(a yes/no, a word, a structure, a zero, a field not settable) and a value no
move changed are said as not moved or not seen to move — never as independent:
the trace is one point of a nonlinear model, and a ``max()`` hides a
dependence there. An order between values is said as inferred. A trace is
written only when every numeric choice was moved both ways; a build that timed
out, died, wrote into the project or raised differently when run alone leaves
no tracked file.

**Every build happens in a copy** (invariant 15). One snapshot of the project
per run, a fresh copy of it per build, each build in a subprocess that imports
the model from its copy, with an audit hook that names any write into the
project. PETGasus's ``build()`` writes its print meshes beside its model:
they land in the copy.

What slipped through before this module: the map drew each claim line from the
values its evaluators read directly, so 94 of PETGasus's 110 choices reached no
claim and drew as if nothing depended on them; and a pass 0.8% inside its limit
on three unconfirmed assumptions read as green as one 80% inside.

Not a spine module: no verdict is keyed on it, and it imports `cli` only inside
the worker's amber evaluation (`_evaluate`), so the check run's own rules judge
amber. Clock-free: durations come from ``time.perf_counter`` and go to the log
and the CLI only, never into a tracked byte.
"""
from __future__ import annotations

import concurrent.futures
import contextlib
import dataclasses
import difflib
import enum
import hashlib
import json
import math
import numbers
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Iterable, Mapping, NamedTuple

from . import claims as claim_logic
from . import gates
from . import graph as graph_logic
from . import modelio
from . import store
from . import util
from . import verdicts
from .models import ClaimKind
from .store import _natural
from .util import NopekitError, seal

#: The trace file's schema, and the amber file's.
SCHEMA = 1

#: The observation method's version: in the key, so a change to how a move is
#: made or compared re-traces every design instead of serving an old reading.
#: 2 (review of phase 3b): an integer moves by its factor's sign, a float field
#: holding an int moves as a real, two equal zeros are no move, a file a value
#: names and a mesh compare by their bytes, and the key holds the data
#: ``build()`` read.
HARNESS = 2

#: The relative move (SPEC 39). Provenance: PETGasus rounds its outputs to 1-3
#: decimals, so a 1% move of most choices changes no output it prints.
#: *Rejected:* ±1% (invisible after the model's own rounding); ±50% (leaves the
#: model's valid range: duct radii pass the prop, and ``build()`` raises).
STEP = 0.1

#: A scalar counts as moved only past this relative change. Provenance: a
#: reassociated sum moves the last bit (~1e-15). *Rejected:* exact inequality
#: (a reordered sum reads as a dependence).
MOVE_FLOOR = 1e-9

#: Significant figures of a stored relative change. Provenance: libm differs in
#: the last bits between machines; four figures say what a person reads.
#: *Rejected:* ``repr`` (the last bit drifts, and the file's bytes with it).
SIGNIFICANT = 4

#: The fewest choices that must move a value before the trace orders it after
#: anything. Provenance: measured on PETGasus (architecture phase 3b's
#: prototype), the floor of two reproduces 19 of the reference map's 20 feeds
#: and C1's line layout -> frame -> mass -> thrust. *Rejected:* 1 (a value one
#: choice moves sits before everything that choice moves, and C1 rode the
#: screw stack and the assembly).
AFTER_FLOOR = 2

#: A move smaller than this relative change does not count toward the order
#: (`after_order`); it still draws its ``derives`` edge. Provenance: on
#: PETGasus seven assembly clearances move the total weight by 0.022% (a sliver
#: of frame volume) and leave the hover power, which the model rounds to 0.01 W
#: at 15 W (0.067%), unmoved: with every move counted, Total weight could never
#: sit before Hover power and C3's line ran backwards (review of phase 3b).
#: *Rejected:* every move counted (that review's defect); a number of
#: exceptions allowed (it counts choices, not sizes, and admits a real mover
#: missed); 1% (PETGasus's own 0.5-1% moves of a printed wall are real).
FAINT = 1e-3

#: Seconds a build may take before it is stopped, at the least. Provenance:
#: PETGasus builds in 28 s alone, 51-106 s under 8-way contention, and about 6
#: min when its topology cache is cold. *Rejected:* 120 s (a cold cache times
#: out); no timeout (a hung build holds the trace lock forever).
BUILD_TIMEOUT_FLOOR = 900.0

#: The timeout is ``max(BUILD_TIMEOUT_FLOOR, TIMEOUT_FACTOR * the base
#: build's seconds)``. Provenance: contention measured at up to 4x; ten leaves
#: room. *Rejected:* a fixed multiple alone (a 0.1 s model would time out on a
#: loaded machine's first page fault).
TIMEOUT_FACTOR = 10.0

#: The largest project a trace copies. Provenance: one copy per build in
#: flight, eight at once; PETGasus is 7 MiB without its git history and site.
#: *Rejected:* no cap (a checked-in dataset copied eight times fills /tmp).
SNAPSHOT_MAX_BYTES = 1 << 30

#: Each build runs with one BLAS/OpenMP thread. Provenance: 8 workers times 14
#: BLAS threads oversubscribed the machine, and with one thread the
#: floating-point order is fixed, so the two base builds agree. *Rejected:*
#: ``python -I`` (it drops ``PYTHONPATH`` and the user site, where trimesh and
#: numpy live for PETGasus).
THREAD_ENV: Mapping[str, str] = {"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                                 "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                                 "VECLIB_MAXIMUM_THREADS": "1"}

#: ``"0"`` turns off `round`'s background start (`tests/_env.run` sets it).
BACKGROUND_ENV = "NOPEKIT_TRACE_BACKGROUND"

TRACE_DIR = "trace"
SCRATCH_REL = ".nopekit/cache/trace"
LOCK_REL = ".nopekit/trace.lock"
LOG_REL = ".nopekit/out/trace.log"

#: Why a choice was not moved, in the order the table in SPEC section 8 names
#: them; each has a word in ``report.HUMAN["trace"]["skip"]``.
SKIP = ("yes-no", "word", "none", "structure", "zero", "not-finite", "fixed")

#: A run whose nudged token is one of these flips the pass: it fails, or it
#: no longer counts (a gap: outside the operating context, for one).
FLIP_TOKENS = ("failing", "gap")

HEADER = ("generated by `nopekit model trace`: which derived values moved when each choice "
          "was rebuilt at -10% and +10%. An observation, never a proof of independence: a "
          "value not seen to move may still depend on a choice. Do not edit it; nothing "
          "rewrites it.")
AMBER_HEADER = ("generated by `nopekit model trace`: each automated claim's evaluators re-run "
                "on designs rebuilt with one assumption-sourced choice moved -10% and +10%. "
                "Display only: it changes no status. Do not edit it; nothing rewrites it.")

#: The trace file's keys, in file order; the amber file's.
TRACE_KEYS = ("generated", "schema", "key", "keyed_on", "round", "entry", "skipped",
              "observed", "unmoved", "unsteady", "self")
AMBER_KEYS = ("generated", "schema", "trace", "round", "step", "choices", "claims", "self")

#: What a snapshot leaves out: the history, the outputs the project rebuilds,
#: the trace's own files, bytecode and environments. Ignored files are kept
#: (PETGasus's topology cache under ``build/topopt/`` saves minutes per
#: build), and so is the verdict cache (amber is judged against it).
#: *Rejected:* skipping what git ignores (it loses that cache); copying the
#: live tree per job (an edit during a 30-minute trace would mix two designs).
_SNAPSHOT_SKIP_TOP = frozenset({".git", "out", "site"})
_SNAPSHOT_SKIP_NOPEKIT = frozenset({"out", "obs", "cache", "trace"})
_SNAPSHOT_SKIP_ANY = frozenset({"__pycache__", "node_modules"})


def default_workers() -> int:
    """``min(8, cpus - 1)``, at least 1. Provenance: 8 workers measured 8.4 s
    per PETGasus build, effective; more saturates memory bandwidth (its FE
    solve), and every core would leave the person's machine unusable for half
    an hour. *Rejected:* ``os.cpu_count()``."""
    return max(1, min(8, (os.cpu_count() or 2) - 1))


# --------------------------------------------------------------------------- #
# nudges
# --------------------------------------------------------------------------- #
class Nudge(NamedTuple):
    """One choice's plan: ``steps`` ``(lo, hi)``, or ``()`` with ``skipped``
    one of `SKIP`."""

    name: str
    value: Any
    steps: tuple
    skipped: str

    @property
    def change(self) -> tuple:
        """Each step's relative change as a factor less one (``-0.1``,
        ``0.1`` for a real; ``-0.5``, ``0.5`` for the integer 2), to four
        figures; ``()`` when skipped."""
        if not self.steps:
            return ()
        base = float(self.value)
        return tuple(_sig(float(step) / base - 1.0) for step in self.steps)


def nudges(name: str, value: Any, *, settable: bool = True, real: bool = False) -> Nudge:
    """The two moves of choice ``name``: a real number times 0.9 and 1.1; an
    integer moved toward zero and away from it by ``max(1, round(0.1 *
    |v|))``, still an integer — so direction 0 is the factor below one for
    both, as it is for a real (``-20`` moves to ``-18`` and ``-22``). ``real``:
    the field is declared a real number, so an integer it holds moves as one
    (``wall: float = 2`` moves to 1.8 and 2.2). Skipped, with its reason: a
    field not settable (``init=False``), a yes/no, a word, ``None``, zero (no
    relative move exists), a number that is not finite, and anything else (a
    structure: a list, a dict, a dataclass, an enum). An integer's move may be
    larger than 10% (2 moves by 50%): `change` holds its size, and every label
    says it (review of phase 3b: they said ±10% for both). *Rejected:*
    ``round(v * 0.9)`` forced off ``v`` for integers (13.5 rounds to 14 and the
    two moves are not symmetric); the runtime type alone (a float field
    holding ``2`` moved to the integers 1 and 3)."""
    if not settable:
        return Nudge(name, value, (), "fixed")
    if isinstance(value, bool):
        return Nudge(name, value, (), "yes-no")
    if isinstance(value, str):
        return Nudge(name, value, (), "word")
    if value is None:
        return Nudge(name, value, (), "none")
    if isinstance(value, enum.Enum):
        return Nudge(name, value, (), "structure")
    if isinstance(value, numbers.Integral) and not real:
        whole = int(value)
        if whole == 0:
            return Nudge(name, value, (), "zero")
        step = max(1, int(round(STEP * abs(whole))))
        toward = step if whole > 0 else -step
        return Nudge(name, value, (whole - toward, whole + toward), "")
    if isinstance(value, numbers.Real):
        number = float(value)
        if not math.isfinite(number):
            return Nudge(name, value, (), "not-finite")
        if number == 0.0:
            return Nudge(name, value, (), "zero")
        return Nudge(name, value, (number * (1.0 - STEP), number * (1.0 + STEP)), "")
    return Nudge(name, value, (), "structure")


def _declared_real(annotation: Any) -> bool:
    """Whether a field's annotation names a real number and no integer:
    ``float``, ``"float"``, ``"float | None"``, ``"Optional[float]"``."""
    if annotation is float:
        return True
    if not isinstance(annotation, str):
        return False
    words = set(annotation.replace("[", " ").replace("]", " ").replace("|", " ")
                .replace(",", " ").replace(".", " ").replace("'", " ").replace('"', " ")
                .split())
    return "float" in words and "int" not in words


def plan_of(config: Any) -> list[Nudge]:
    """Every ``Config`` field's `Nudge`, in field order; a field declared a
    real number moves as one whatever its value's type (`nudges`)."""
    out: list[Nudge] = []
    for f in dataclasses.fields(config):
        out.append(nudges(f.name, getattr(config, f.name, None), settable=f.init,
                          real=_declared_real(f.type)))
    return out


def step_word(direction: int, change: Any = None, *, minus: str = "-") -> str:
    """How a move is said: ``-10%`` or ``+10%`` for a real, the actual size for
    an integer whose move is not 10% (``-50%``) — ``change`` the pair a trace
    file holds for the choice (`Nudge.change`), or None for ±10%."""
    size = None
    if isinstance(change, (list, tuple)) and len(change) == 2:
        found = change[direction]
        if isinstance(found, (int, float)) and not isinstance(found, bool):
            size = float(found)
    if size is None:
        size = -STEP if direction == 0 else STEP
    pct = abs(size) * 100.0
    text = f"{pct:.0f}" if abs(pct - round(pct)) < 0.05 else f"{pct:.2g}"
    return f"{minus if size < 0 else '+'}{text}%"


def apply(model: Any, name: str, step: Any) -> Any:
    """``model`` with choice ``name`` set to ``step``: a new
    `modelio.LoadedModel` over ``dataclasses.replace`` of its config (a
    ``__post_init__`` that refuses the value raises here, and that raise is
    an observation), and ``module.CONFIG`` rebound to it when the module holds
    the config instance as ``CONFIG``."""
    config = dataclasses.replace(model.config, **{name: step})
    module = model.module
    if getattr(module, "CONFIG", None) is model.config:
        try:
            module.CONFIG = config
        except Exception:                                   # noqa: BLE001 - read-only module
            pass
    return modelio.LoadedModel(module=module, config=config, entry=model.entry,
                               params=list(model.params))


# --------------------------------------------------------------------------- #
# the key
# --------------------------------------------------------------------------- #
def _py_files(directory: str, root: str | None = None) -> list[str]:
    """Every ``*.py`` under ``directory`` that a snapshot of ``root`` copies
    (`_ignore_for`'s rules: no ``node_modules``, no venv, no top-level
    ``out/``, ``site/`` or ``.git``), dot-directories left out. What slipped
    through (review of phase 3b): this walk kept what the snapshot drops, so a
    ``model/node_modules/helper.py`` put the reader's key and the worker's
    apart, the trace was never served, and every `round` started another."""
    ignore = _ignore_for(root if root is not None else directory)
    out: list[str] = []
    for here, dirnames, filenames in os.walk(directory):
        skip = ignore(here, list(dirnames) + list(filenames))
        dirnames[:] = sorted(d for d in dirnames if d != "__pycache__" and not d.startswith(".")
                             and d not in skip)
        for name in sorted(filenames):
            if name.endswith(".py") and not name.startswith("."):
                out.append(os.path.join(here, name))
    return out


def instructions_of(root: str, model: Any, anchors: Any) -> dict[str, str] | None:
    """``{portable path: digest}`` of the instructions: the model's code
    closure as an article reads it (`verdicts._model_code`), plus every
    ``*.py`` under the model entry's directory the closure does not hold, by
    canonical AST (a comment or a docstring moves nothing). ``None`` when the
    code was not recorded.

    What slipped through before the directory was added: PETGasus imports its
    FE code (``model/topopt.py``) lazily inside ``build()``, through no global,
    so the closure never held it and an edit to the frame's stiffness would
    have served the old trace. *Rejected:* a public alias of ``_model_code`` in
    `verdicts` (a spine edit only to rename, which re-keys every verdict)."""
    code = verdicts._model_code(model, anchors)
    if code is None:
        return None
    out = dict(code)
    entry_file = getattr(model, "file", "") or ""
    if entry_file:
        for path in _py_files(os.path.dirname(entry_file), root):
            # `verdicts._spell`'s rule: a file under the root is named bare.
            spelled = anchors.portable_path(path) if anchors is not None else None
            if spelled is not None and spelled.startswith("<root>/"):
                spelled = spelled[len("<root>/"):]
            spelled = spelled or os.path.abspath(path).replace(os.sep, "/")
            if spelled in out:
                continue
            try:
                with open(path, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            out[spelled] = verdicts.canonical_ast_digest(data) or (
                "sha256:" + hashlib.sha256(data).hexdigest())
    return dict(sorted(out.items()))


def choice_digests(config: Any, anchors: Any) -> dict[str, str]:
    """``{field: digest}`` for EVERY ``Config`` field — a skipped one too: a
    changed ``material`` word is another design."""
    return {f.name: verdicts.digest_value(getattr(config, f.name, None), anchors)
            for f in dataclasses.fields(config)}


def keyed_on(instructions: Mapping[str, str], choices: Mapping[str, str],
             data: Mapping[str, str] | None = None) -> dict:
    return {"harness": HARNESS, "step": STEP, "instructions": dict(instructions),
            "choices": dict(choices), "data": dict(data or {})}


def key_of(keyed: Mapping[str, Any]) -> str:
    """The trace key: the seal of ``{harness, step, instructions, choices,
    data}`` — ``data`` the files the base build read while it loaded and built
    (`_data_read`), ``{}`` when it read none."""
    return seal({"harness": keyed.get("harness"), "step": keyed.get("step"),
                 "instructions": keyed.get("instructions"), "choices": keyed.get("choices"),
                 "data": dict(keyed.get("data") or {})})


def current_keyed(root: str, model: Any, anchors: Any) -> dict | None:
    """`keyed_on` for ``model`` as loaded and built here, with no data (a
    reader cannot know what ``build()`` read: `trace_for` checks each trace's
    own ``data`` against the files on disk), or ``None`` when its code was not
    recorded. Computed AFTER a build, wherever it is computed: a sibling a
    global binds lazily is then in the closure both here and in the worker."""
    if model is None or getattr(model, "config", None) is None:
        return None
    try:
        instructions = instructions_of(root, model, anchors)
    except Exception:                                       # noqa: BLE001 - no key, said
        return None
    if instructions is None:
        return None
    try:
        return keyed_on(instructions, choice_digests(model.config, anchors))
    except TypeError:
        return None


def current_key(root: str, model: Any, projection: Any, anchors: Any) -> str | None:
    """The current design's trace key as a reader can name it — its
    instructions and choices with no build-time data (the key of a model whose
    ``build()`` reads no file) — or ``None`` with no projection (the model did
    not build) or unrecorded instructions. The scratch of a run is kept under
    it; `trace_for` names the trace that is current."""
    if projection is None:
        return None
    keyed = current_keyed(root, model, anchors)
    return key_of(keyed) if keyed is not None else None


def _sha_file(path: str) -> str | None:
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
    except OSError:
        return None
    return "sha256:" + digest.hexdigest()


def data_current(root: str, data: Mapping[str, str]) -> bool:
    """Whether every file a trace's base build read (``keyed_on.data``,
    root-relative) holds the same bytes under ``root`` now."""
    base = os.path.abspath(root)
    for rel, digest in data.items():
        if _sha_file(os.path.join(base, *str(rel).split("/"))) != digest:
            return False
    return True


def _same_inputs(keyed: Mapping[str, Any], inputs: Mapping[str, Any]) -> bool:
    return all(keyed.get(k) == inputs.get(k)
               for k in ("harness", "step", "instructions", "choices"))


def anchors_for(root: str, resolution: Any = None) -> Any:
    """The anchors a trace key is spelled against: the resolution's, else the
    root's alone."""
    found = getattr(resolution, "anchors", None) if resolution is not None else None
    return found or verdicts.Anchors(root=os.path.abspath(root))


# --------------------------------------------------------------------------- #
# moves
# --------------------------------------------------------------------------- #
def _sig(x: float) -> float:
    return float(f"{x:.{SIGNIFICANT}g}")


def _scalar(value: Any) -> float | int | None:
    """A finite real number (never a bool), as a plain int or float, else None."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    if isinstance(value, numbers.Integral):
        return int(value)
    number = float(value)
    return number if math.isfinite(number) else None


#: How deep `_content` looks into a derived value for a file, a mesh or an
#: array. Provenance: PETGasus nests its meshes two deep (``assembly_parts``
#: -> part -> ``path``). *Rejected:* no limit (a self-containing structure).
_CONTENT_DEPTH = 8


def _content(value: Any, root: str, seen: dict, depth: int = 0) -> Any:
    """``value`` with what its bytes are put in place of what only names
    them, for comparison: a path that names a file (absolute, or relative
    with a separator, under ``root``) becomes ``{"$path", "$bytes"}``; a mesh
    (``vertices`` and ``faces``) ``{"$mesh"}`` and an array (``tobytes``,
    ``shape``, ``dtype``) ``{"$array", "shape"}``, each a sha256 of its
    bytes; containers are walked. Everything else is left for
    `verdicts.digest_value`. What slipped through (review of phase 3b): a path
    digested as its string and a mesh by its type, so a nudge that reshaped
    the frame's mesh or changed the parts list moved nothing the trace could
    see, and the claims reading them drew as if no choice reached them."""
    if depth > _CONTENT_DEPTH:
        return value
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, (str, os.PathLike)):
        text = os.fspath(value)
        if not isinstance(text, str) or not text or len(text) > 4096:
            return value
        if os.path.isabs(text):
            full = text
        elif root and ("/" in text or os.sep in text):
            full = os.path.join(root, *text.split("/"))
        else:
            return value
        if full not in seen:
            seen[full] = _sha_file(full) if os.path.isfile(full) else None
        found = seen[full]
        return value if found is None else {"$path": text, "$bytes": found}
    if isinstance(value, Mapping):
        return {k: _content(v, root, seen, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_content(v, root, seen, depth + 1) for v in value]
    try:
        vertices, faces = getattr(value, "vertices", None), getattr(value, "faces", None)
        if vertices is not None and faces is not None and hasattr(vertices, "tobytes") \
                and hasattr(faces, "tobytes"):
            digest = hashlib.sha256()
            for part in (vertices, faces):
                digest.update(repr((tuple(getattr(part, "shape", ())),
                                    str(getattr(part, "dtype", "")))).encode("utf-8"))
                digest.update(part.tobytes())
            return {"$mesh": digest.hexdigest()}
        if hasattr(value, "tobytes") and hasattr(value, "shape") and hasattr(value, "dtype") \
                and tuple(getattr(value, "shape", ())):
            return {"$array": hashlib.sha256(value.tobytes()).hexdigest(),
                    "shape": list(value.shape), "dtype": str(value.dtype)}
    except Exception:                                       # noqa: BLE001 - left as it is
        return value
    return value


def observe_values(projection: Any, anchors: Any) -> dict[str, list]:
    """``{derived name: [digest, scalar or None]}`` over `graph.derived_names`
    — the values a trace compares, each digested with the bytes of the files,
    meshes and arrays it holds (`_content`)."""
    derived = (projection or {}).get("derived") or {}
    root = str(getattr(anchors, "root", "") or "") if anchors is not None else ""
    seen: dict = {}
    return {name: [verdicts.digest_value(_content(derived[name], root, seen), anchors),
                   _scalar(derived[name])]
            for name in graph_logic.derived_names(projection)}


def move_of(base: list | None, new: list | None) -> Any:
    """How one value moved from ``base`` to ``new`` (each ``[digest,
    scalar]``), or ``None`` when it did not: a relative change to four
    figures for a nonzero scalar base (``None`` under `MOVE_FLOOR`), ``{"abs":
    d}`` for a zero base, ``"#" + 16 hex`` of the new digest for anything else
    (a structure, a word, a type change), ``"gone"`` or ``"new"``. Two equal
    numbers are no move whatever their digests (``0`` and ``0.0``, ``0.0``
    and ``-0.0``: review of phase 3b, where each read as a structure's move)."""
    if base is None and new is None:
        return None
    if new is None:
        return "gone"
    if base is None:
        return "new"
    if base[0] == new[0]:
        return None
    b, n = base[1], new[1]
    if b is not None and n is not None:
        if b == n:
            return None
        if b != 0:
            rel = (n - b) / abs(b)
            if abs(rel) < MOVE_FLOOR:
                return None
            return _sig(rel)
        return {"abs": _sig(n - b)}
    return "#" + str(new[0])[:16]


def moves_between(base: Mapping[str, list], new: Mapping[str, list]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in sorted(set(base) | set(new), key=_natural):
        found = move_of(base.get(name), new.get(name))
        if found is not None:
            out[name] = found
    return out


def magnitude(move: Any) -> float:
    """How large a stored move reads, for ordering `why`'s list: a relative
    change's size; a structure's or an absolute change's, 1."""
    if isinstance(move, (int, float)) and not isinstance(move, bool):
        return abs(float(move))
    return 1.0


# --------------------------------------------------------------------------- #
# bytes
# --------------------------------------------------------------------------- #
def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _write(value: Any, level: int) -> str:
    pad = " " * (level + 1)
    end = " " * level
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [f"{pad}{json.dumps(str(k), ensure_ascii=False)}: {_write(v, level + 1)}"
                 for k, v in value.items()]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(value, (list, tuple)):
        if all(_is_scalar(v) for v in value):
            return json.dumps(list(value), ensure_ascii=False, allow_nan=False,
                              separators=(", ", ": "))
        items = [f"{pad}{_write(v, level + 1)}" for v in value]
        return "[\n" + ",\n".join(items) + "\n" + end + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def render(doc: Mapping[str, Any]) -> bytes:
    """A trace or amber file's bytes: indent 1, every list of scalars on one
    line, UTF-8 as itself, NaN refused, one newline. *Rejected:* ``indent=2``
    (about 25,000 lines for PETGasus)."""
    return (_write(dict(doc), 0) + "\n").encode("utf-8")


def self_digest(doc: Mapping[str, Any]) -> str:
    return seal({k: v for k, v in doc.items() if k != "self"})


def _sealed(doc: Mapping[str, Any], keys: tuple) -> dict:
    out = {k: doc[k] for k in keys if k != "self"}
    out["self"] = self_digest(out)
    return {k: out[k] for k in keys}


# --------------------------------------------------------------------------- #
# the order of derived values (observation only)
# --------------------------------------------------------------------------- #
class Order(NamedTuple):
    """`after_order`'s answer: ``after`` ``(earlier, later)`` pairs, Hasse
    reduced; ``ties`` the groups of values moved by the same choices (two or
    more members: the trace cannot order them); ``singles`` the values one
    choice alone moves (never ordered)."""

    after: tuple
    ties: tuple
    singles: tuple


def after_order(movers: Mapping[str, Iterable[str]],
                strong: Mapping[str, Iterable[str]] | None = None) -> Order:
    """The order the trace infers between derived values, from ``movers``
    (``{value: the choices that moved it}``) and ``strong`` (the choices that
    moved it by `FAINT` or more; ``movers`` when None): Y comes before X when at
    least `AFTER_FLOOR` choices move Y strongly, every one of them moves X, and
    X is moved by more — more strong movers, or more movers of any size.
    Computed on classes of values with the same strong and the same full mover
    sets (two or more values in one class are a tie: nothing orders them); an
    edge inside a cycle is dropped (the trace cannot decide that order), and
    the rest is reduced to its covering edges (Y -> X is dropped when Y reaches
    X through another value), then expanded member by member and sorted. A
    value one choice alone moves (of every size) is a single. Never stored in
    the trace file: a rule change needs no re-trace.

    Both "more" readings are needed (review of phase 3b, on PETGasus): a
    rounded value downstream drops a faint mover (Total weight before Hover
    power: more strong movers), and a large value downstream dilutes a strong
    move into a faint one (frame mass before total weight: more movers).

    *Rejected:* an elasticity-ratio or sign check (it rejects true edges
    wherever X depends on a choice by more than one path, e.g. mass -> thrust to
    weight under ``prop_d``); reading the model's source (the plausible
    validator this project exists to refuse). Named limit: two values that share
    their inputs without one feeding the other (the bracket's slenderness and
    its bounding box, both moved by the arm and the thickness) are ordered by
    this rule too — the order is said as inferred, and the map draws a stop it
    puts before a claim's reads faded (review of phase 3b)."""
    full = {n: frozenset(v) for n, v in movers.items() if frozenset(v)}
    source = movers if strong is None else strong
    strong_of = {n: frozenset(source.get(n, ())) & full[n] for n in full}
    classes: dict[tuple, list[str]] = {}
    for name in full:
        classes.setdefault((strong_of[name], full[name]), []).append(name)
    keys = sorted(classes, key=lambda k: (len(k[1]), len(k[0]), sorted(k[1], key=_natural),
                                          sorted(k[0], key=_natural)))

    def before(a: tuple, b: tuple) -> bool:
        (sa, fa), (sb, fb) = a, b
        return len(sa) >= AFTER_FLOOR and sa <= fb and (sa < sb or fa < fb)

    out_of: dict[tuple, set] = {k: {b for b in keys if b != k and before(k, b)} for k in keys}

    def reach(start: tuple) -> set:
        seen: set = set()
        todo = list(out_of[start])
        while todo:
            here = todo.pop()
            if here not in seen:
                seen.add(here)
                todo.extend(out_of[here])
        return seen

    reached = {k: reach(k) for k in keys}
    acyclic = {k: {b for b in out_of[k] if k not in reached[b]} for k in keys}

    def reach_dag(start: tuple, memo: dict) -> set:
        if start not in memo:
            memo[start] = set()
            found: set = set()
            for b in acyclic[start]:
                found.add(b)
                found |= reach_dag(b, memo)
            memo[start] = found
        return memo[start]

    memo: dict = {}
    reduced = [(a, b) for a in keys for b in acyclic[a]
               if not any(b in reach_dag(c, memo) for c in acyclic[a] if c != b)]
    after = sorted({(y, x) for a, b in reduced for y in classes[a] for x in classes[b]},
                   key=lambda p: (_natural(p[0]), _natural(p[1])))
    ties = sorted((tuple(sorted(names, key=_natural)) for names in classes.values()
                   if len(names) >= 2), key=lambda t: _natural(t[0]))
    singles = tuple(sorted((n for n, found in full.items() if len(found) == 1), key=_natural))
    return Order(tuple(after), tuple(ties), singles)


# --------------------------------------------------------------------------- #
# reading the files
# --------------------------------------------------------------------------- #
def trace_dir(root: str) -> str:
    return os.path.join(store.nopekit_dir(root), TRACE_DIR)


def trace_path(root: str, key: str) -> str:
    return os.path.join(trace_dir(root), f"{key[:16]}.json")


def _strict(pairs: list) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not JSON")


def _load_strict(path: str) -> tuple[str, Any, str]:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return "absent", None, ""
    except OSError as exc:
        return "unreadable", None, " ".join(str(exc).split())
    try:
        doc = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict,
                         parse_constant=_no_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        return "unreadable", None, (" ".join(str(exc).splitlines()[0].split()) if str(exc)
                                    else "not JSON")
    if not isinstance(doc, dict):
        return "unreadable", None, f"expected a JSON object, found {type(doc).__name__}"
    return "ok", doc, ""


def _unknown(doc: Mapping[str, Any], keys: tuple) -> str:
    for key in doc:
        if key not in keys:
            near = difflib.get_close_matches(str(key), keys, n=1)
            hint = f" (did you mean {near[0]!r}?)" if near else ""
            return f"unknown key {key!r}{hint}"
    missing = [k for k in keys if k not in doc]
    if missing:
        return f"missing key {missing[0]!r}"
    return ""


class TraceFile:
    """One trace file that reads ``ok``: its keys, and what follows from them —
    ``movers(name)``, ``derives`` (``(choice, derived)`` for every steady value a
    choice moved), the inferred ``after``, ``ties`` and ``singles``
    (`after_order`), and ``raised`` (``{(choice, direction): exception type}``).
    Implements `graph.Trace`."""

    def __init__(self, doc: Mapping[str, Any], path: str) -> None:
        self.path = path
        self.key = str(doc["key"])
        number = doc.get("round")
        self.round = number if isinstance(number, int) and not isinstance(number, bool) \
            else None
        self.entry = str(doc.get("entry") or "")
        self.keyed_on = dict(doc.get("keyed_on") or {})
        self.skipped = dict(doc.get("skipped") or {})
        self.observed = dict(doc.get("observed") or {})
        self.unmoved = tuple(doc.get("unmoved") or ())
        self.unsteady = tuple(doc.get("unsteady") or ())
        unsteady = set(self.unsteady)
        movers: dict[str, set[str]] = {}
        strong: dict[str, set[str]] = {}
        raised: dict[tuple[str, int], str] = {}
        for choice, row in self.observed.items():
            for name, pair in (row.get("moves") or {}).items():
                if name in unsteady or name == choice:
                    continue
                found = [p for p in (pair or ()) if p is not None]
                if found:
                    movers.setdefault(name, set()).add(choice)
                    if max(magnitude(p) for p in found) >= FAINT:
                        strong.setdefault(name, set()).add(choice)
            for direction, kind in enumerate(row.get("raised") or ()):
                if kind:
                    raised[(choice, direction)] = str(kind)
        self._movers = {k: frozenset(v) for k, v in movers.items()}
        self.raised = raised
        self.derives = tuple(sorted(((c, v) for v, cs in self._movers.items() for c in cs),
                                    key=lambda p: (_natural(p[0]), _natural(p[1]))))
        order = after_order(self._movers, {k: frozenset(v) for k, v in strong.items()})
        self.after = order.after
        self.ties = order.ties
        self.singles = order.singles

    def movers(self, name: str) -> frozenset:
        return self._movers.get(name, frozenset())

    @property
    def moved(self) -> tuple:
        """Every derived value some choice moved, natural order."""
        return tuple(sorted(self._movers, key=_natural))

    def moves(self, choice: str) -> dict:
        return dict((self.observed.get(choice) or {}).get("moves") or {})


def read_trace(path: str) -> tuple[str, TraceFile | None, str]:
    """``(state, file, line)``: ``absent``; ``unreadable`` (not strict JSON —
    duplicate keys and NaN refused — or not an object, or an unknown key, with
    a suggestion); ``edited`` (its seal does not match: checked BEFORE the
    schema, as the round record's is); ``newer`` (sealed, schema above 1);
    ``mismatch`` (sealed, and its name is not its key's first 16 hex, or its
    key is not the seal of what it says it is keyed on); ``ok``. Only an ``ok``
    file is ever used."""
    state, doc, line = _load_strict(path)
    if state != "ok":
        return state, None, line
    if not isinstance(doc.get("self"), str) or self_digest(doc) != doc["self"]:
        return "edited", None, "its digest does not match what it holds"
    schema = doc.get("schema")
    if isinstance(schema, int) and not isinstance(schema, bool) and schema > SCHEMA:
        return "newer", None, f"schema {schema}"
    problem = _unknown(doc, TRACE_KEYS)
    if problem:
        return "unreadable", None, problem
    key = doc.get("key")
    keyed = doc.get("keyed_on")
    name = os.path.basename(path)
    if not isinstance(key, str) or not isinstance(keyed, dict) or name != f"{key[:16]}.json" \
            or key_of(keyed) != key:
        return "mismatch", None, "its name or its key does not match what it is keyed on"
    try:
        return "ok", TraceFile(doc, path), ""
    except (AttributeError, TypeError, ValueError, KeyError) as exc:
        return "unreadable", None, f"malformed: {exc}"


class AmberFile(NamedTuple):
    path: str
    trace: str
    round: int | None
    choices: dict
    claims: dict


def amber_paths(root: str, key: str) -> list[str]:
    """Every amber file for trace key ``key``, by name."""
    folder = trace_dir(root)
    prefix = f"{key[:16]}.amber."
    try:
        names = sorted(n for n in os.listdir(folder)
                       if n.startswith(prefix) and n.endswith(".json"))
    except OSError:
        return []
    return [os.path.join(folder, n) for n in names]


def read_amber(path: str) -> tuple[str, AmberFile | None, str]:
    """The amber file's reader, by `read_trace`'s rules; a name whose seal
    part is not the first 16 hex of its own ``self`` reads ``mismatch``."""
    state, doc, line = _load_strict(path)
    if state != "ok":
        return state, None, line
    if not isinstance(doc.get("self"), str) or self_digest(doc) != doc["self"]:
        return "edited", None, "its digest does not match what it holds"
    schema = doc.get("schema")
    if isinstance(schema, int) and not isinstance(schema, bool) and schema > SCHEMA:
        return "newer", None, f"schema {schema}"
    problem = _unknown(doc, AMBER_KEYS)
    if problem:
        return "unreadable", None, problem
    trace = doc.get("trace")
    name = os.path.basename(path)
    if not isinstance(trace, str) or name != f"{trace[:16]}.amber.{doc['self'][:16]}.json":
        return "mismatch", None, "its name does not match its trace and its seal"
    if not isinstance(doc.get("choices"), dict) or not isinstance(doc.get("claims"), dict):
        return "unreadable", None, "malformed: choices and claims are objects"
    number = doc.get("round")
    number = number if isinstance(number, int) and not isinstance(number, bool) else None
    return "ok", AmberFile(path, trace, number, dict(doc["choices"]), dict(doc["claims"])), ""


class TraceRead(NamedTuple):
    """What a reader finds for the current design: ``state`` — ``current``
    (an ``ok`` trace for the current key), ``none`` (no usable trace for it),
    ``unrecorded`` (no key: the model's code was not recorded) or ``no-model``;
    ``key`` the current key; ``trace`` the `TraceFile`; ``problems``
    ``(path, state, line)`` for the key's files that do not read ``ok``;
    ``ambers`` the key's ``ok`` amber files."""

    state: str
    key: str | None
    trace: TraceFile | None
    problems: tuple
    ambers: tuple


def _trace_names(root: str) -> list[str]:
    """Every ``<16 hex>.json`` under ``.nopekit/trace/``, by name."""
    try:
        names = os.listdir(trace_dir(root))
    except OSError:
        return []
    return sorted(n for n in names if n.endswith(".json") and ".amber." not in n
                  and len(n) == 21)


def _claims_inputs(path: str, inputs: Mapping[str, Any]) -> bool:
    """Whether a file that does not read ``ok`` says it is keyed on these
    instructions and choices (its bytes, loosely: it is not trusted)."""
    try:
        with open(path, "rb") as fh:
            doc = json.loads(fh.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    keyed = doc.get("keyed_on") if isinstance(doc, dict) else None
    return isinstance(keyed, dict) and _same_inputs(keyed, inputs)


def trace_for(root: str, model: Any, projection: Any, anchors: Any) -> TraceRead:
    """The trace served for the current design, and only for it: a trace
    whose instructions and choices are the current ones and whose base build's
    data (``keyed_on.data``, the files ``build()`` read) holds the same bytes on
    disk now; a trace keyed on anything else is never drawn (invariant 7).
    ``key`` is that trace's key; with none, `current_key` (where the run's
    scratch lives). A file that does not read ``ok`` is a problem when it sits
    at `current_key`'s path or says it is keyed on these instructions and
    choices. What slipped through (review of phase 3b): the key held the code
    and the choices only, so a model whose ``build()`` reads ``model/e.json``
    kept its old trace, edges and amber current after ``e.json`` changed.
    *Rejected:* the nearest trace of the same instructions, labelled "for other
    choice values" (a derivation observed at another design read as this
    one's); the base build's derived values in the key (the worker builds with
    one BLAS thread, a reader with many, and a last-bit difference would leave
    every trace unserved)."""
    if projection is None or model is None:
        return TraceRead("no-model", None, None, (), ())
    inputs = current_keyed(root, model, anchors)
    if inputs is None:
        return TraceRead("unrecorded", None, None, (), ())
    key = key_of(inputs)
    first = trace_path(root, key)
    problems: list[tuple] = []
    found: TraceFile | None = None
    for name in [os.path.basename(first)] + [n for n in _trace_names(root)
                                             if n != os.path.basename(first)]:
        path = os.path.join(trace_dir(root), name)
        state, candidate, line = read_trace(path)
        if state == "absent":
            continue
        if state != "ok" or candidate is None:
            if path == first or _claims_inputs(path, inputs):
                problems.append((_rel(root, path), state, line))
            continue
        if _same_inputs(candidate.keyed_on, inputs) and data_current(
                root, candidate.keyed_on.get("data") or {}):
            found = candidate
            break
    if found is not None:
        key = found.key
    ambers: list[AmberFile] = []
    for amber_path in amber_paths(root, key):
        a_state, amber, a_line = read_amber(amber_path)
        if a_state == "ok" and amber is not None and amber.trace == key:
            ambers.append(amber)
        elif a_state != "ok":
            problems.append((_rel(root, amber_path), a_state, a_line))
    if found is not None:
        return TraceRead("current", key, found, tuple(problems), tuple(ambers))
    return TraceRead("none", key, None, tuple(problems), tuple(ambers))


def _rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


def trace_digest(root: str, key: str | None) -> str:
    """The round record's ``computed_from.trace``: sha256 over a prefix, the
    current key's trace file's bytes, and each of its amber files (name and
    bytes, sorted) — ``""`` with none."""
    if not key:
        return ""
    paths = []
    main = trace_path(root, key)
    if os.path.isfile(main):
        paths.append(main)
    paths += amber_paths(root, key)
    if not paths:
        return ""
    digest = hashlib.sha256(b"nopekit-trace-v1\x00")
    for path in paths:
        try:
            with open(path, "rb") as fh:
                data = fh.read()
        except OSError:
            continue
        digest.update(os.path.basename(path).encode("utf-8") + b"\x00"
                      + hashlib.sha256(data).hexdigest().encode("ascii") + b"\n")
    return digest.hexdigest()


def other_designs(root: str, key: str | None) -> tuple[int, int]:
    """``(files, bytes)`` of trace files under ``.nopekit/trace/`` for designs
    other than ``key`` — for `doctor`'s warning."""
    folder = trace_dir(root)
    count = size = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0, 0
    for name in names:
        if not name.endswith(".json") or (key and name.startswith(key[:16])):
            continue
        count += 1
        try:
            size += os.path.getsize(os.path.join(folder, name))
        except OSError:
            pass
    return count, size


# --------------------------------------------------------------------------- #
# the audit: a build that writes into the project is named
# --------------------------------------------------------------------------- #
_LOCAL = threading.local()
#: The watch a worker process installs for every thread (`_Watching`'s
#: ``process_wide``): a subprocess worker runs one job, so a write from a thread
#: pool ``build()`` starts is the job's too. What slipped through (review of
#: phase 3b): the watch lived on the worker's main thread alone, and a model
#: writing its meshes through a thread pool into the project wrote unnamed.
_PROCESS_WATCH: list = [None]
_HOOKED = False
_HOOK_GUARD = threading.Lock()
_WRITE_FLAGS = (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC)
_ONE_PATH = frozenset({"os.remove", "os.mkdir", "os.rmdir", "shutil.rmtree", "os.truncate",
                       "os.chmod", "os.utime"})
_TWO_PATHS = frozenset({"os.rename", "os.replace"})
_DEST_PATH = frozenset({"os.symlink", "os.link"})


def _inside(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder + os.sep)


def _audit(event: str, args: tuple) -> None:
    """The audit hook every worker installs: while this thread watches (or
    the process does, in a subprocess worker), a write-like event on a path
    inside the original project and outside the build's copy is recorded; and,
    while ``reading`` is on, a file opened to read inside the copy, and a
    write inside it, so the base build's data can be keyed (`_data_read`).
    One hook per process; the in-process launcher watches per thread, so a
    parent writing its own scratch while an in-process job runs is never
    blamed on the job."""
    watch = getattr(_LOCAL, "watch", None) or _PROCESS_WATCH[0]
    if watch is None:
        return
    paths: tuple = ()
    reads: tuple = ()
    try:
        if event == "open":
            path, mode, flags = (tuple(args) + (None, None, None))[:3]
            if isinstance(mode, str):
                writing = any(ch in mode for ch in "wax+")
            else:
                writing = isinstance(flags, int) and bool(flags & _WRITE_FLAGS)
            paths = (path,) if writing else ()
            reads = () if writing else (path,)
        elif event in _ONE_PATH:
            paths = tuple(args[:1])
        elif event in _TWO_PATHS:
            paths = tuple(args[:2])
        elif event in _DEST_PATH:
            paths = tuple(args[1:2])
    except Exception:                                       # noqa: BLE001 - never break a build
        return
    for path in paths + reads:
        if isinstance(path, int) or path is None:
            continue
        try:
            full = os.path.realpath(os.path.abspath(os.fsdecode(path)))
        except Exception:                                   # noqa: BLE001 - an odd argument
            continue
        if path in paths:
            if _inside(full, watch["root"]) and not _inside(full, watch["copy"]):
                watch["wrote"].append(os.path.relpath(full, watch["root"]).replace(os.sep, "/"))
            elif watch.get("reading") and _inside(full, watch["copy"]):
                watch["wrote_copy"].add(full)
        elif watch.get("reading") and _inside(full, watch["copy"]):
            watch["read"].add(full)


def _install_hook() -> None:
    global _HOOKED
    with _HOOK_GUARD:
        if not _HOOKED:
            sys.addaudithook(_audit)
            _HOOKED = True


class _Watching:
    """While inside, this thread's write-like events into ``root`` outside
    ``copy`` are recorded in ``wrote`` — every thread's with
    ``process_wide`` (a subprocess worker). Writes from a process ``build()``
    spawns are outside any audit hook: a limit, named in SPINE_CONTRACT."""

    def __init__(self, root: str, copy: str, *, process_wide: bool = False) -> None:
        self.state = {"root": os.path.realpath(root), "copy": os.path.realpath(copy),
                      "wrote": [], "reading": False, "read": set(), "wrote_copy": set()}
        self.process_wide = process_wide

    def __enter__(self) -> list:
        _install_hook()
        _LOCAL.watch = self.state
        if self.process_wide:
            _PROCESS_WATCH[0] = self.state
        return self.state["wrote"]

    def __exit__(self, *exc: Any) -> None:
        _LOCAL.watch = None
        if self.process_wide:
            _PROCESS_WATCH[0] = None


def _data_read(state: Mapping[str, Any], instructions: Mapping[str, str]) -> dict[str, str]:
    """``{root-relative path: sha256}`` of the files the base build opened to
    read inside its copy while it loaded and built — not ``.nopekit/``, not
    Python source or bytecode (the instructions hold the code, by AST), not a
    file the build also wrote (its own output or cache), not one the
    instructions already hold. The data ``build()`` reads (a material table in
    ``model/e.json``) is part of the design the trace observed."""
    copy = state["copy"]
    out: dict[str, str] = {}
    for full in sorted(set(state["read"]) - set(state["wrote_copy"])):
        if not os.path.isfile(full):
            continue
        rel = os.path.relpath(full, copy).replace(os.sep, "/")
        if rel.startswith(("../", ".nopekit/")) or rel.endswith((".py", ".pyc", ".pyo")) \
                or "/__pycache__/" in f"/{rel}" or rel in instructions:
            continue
        digest = _sha_file(full)
        if digest is not None:
            out[rel] = digest
    return dict(sorted(out.items()))


# --------------------------------------------------------------------------- #
# the worker: one build in one copy
# --------------------------------------------------------------------------- #
def _cause_type(exc: BaseException) -> str:
    """The type a raise is stored as: a `NopekitError`'s cause when it wraps one
    (`modelio.project` wraps the model's own exception), else its own. Only
    the type: a message can hold an address or an absolute path, and the file
    must be byte-stable."""
    cause = exc.__cause__ if isinstance(exc, NopekitError) and exc.__cause__ is not None \
        else exc
    return type(cause).__name__


def _first(exc: BaseException) -> str:
    text = str(exc.__cause__ if isinstance(exc, NopekitError) and exc.__cause__ else exc)
    return (text.strip().splitlines() or [""])[0][:300]


def _work(job: Mapping[str, Any], *, process_wide: bool = False) -> dict:
    """One job's work, in this process, on the job's copy: load the model from
    the copy, apply the nudge, build, and report the compared values — for a
    base job also its trace key (with the data its load and build read,
    `_data_read`) and, when asked, the amber subjects; for an amber job also
    each automated claim's composition (`_evaluate`). Every write into the
    original project is recorded (`_Watching`; every thread's with
    ``process_wide``, as `worker_main` runs it)."""
    copy, root, entry = str(job["copy"]), str(job["root"]), str(job["entry"])
    out: dict[str, Any] = {"ok": True, "values": None, "raised": None, "raised_line": "",
                           "wrote_project": [], "model_file": ""}
    watching = _Watching(root, copy, process_wide=process_wide)
    with watching as wrote:
        try:
            anchors = verdicts.Anchors(root=copy)
            watching.state["reading"] = True
            try:
                model = modelio.load_model(copy, entry)
                out["model_file"] = model.file
                if job.get("kind") == "nudge":
                    model = apply(model, str(job["choice"]), job["step"])
                projection = modelio.project(model)
            finally:
                watching.state["reading"] = False
        except Exception as exc:                            # noqa: BLE001 - an observation
            out["raised"] = _cause_type(exc)
            out["raised_line"] = _first(exc)
        else:
            out["values"] = observe_values(projection, anchors)
            if job.get("kind") == "base":
                keyed = current_keyed(copy, model, anchors)
                if keyed is not None:
                    keyed["data"] = _data_read(watching.state, keyed["instructions"])
                out["keyed_on"] = keyed
                out["key"] = key_of(keyed) if keyed is not None else None
                if job.get("subjects"):
                    out["subjects"] = _subjects_in(copy)
            if job.get("amber"):
                out["amber"] = _evaluate(copy, model, projection, str(job.get("now") or ""))
    out["wrote_project"] = sorted(set(wrote))
    return out


def _subjects_in(copy: str) -> dict:
    from . import cli                                    # the check run's own loaders
    ledger = cli._load(copy)
    registry, _ = cli._registry(copy, ledger, strict=True)
    return amber_subjects(copy, ledger, registry)


def _eligible(ledger: Any, registry: Any) -> list[tuple[Any, list[str]]]:
    """Every automated (measurable) claim with at least one covering
    registered evaluator, with those evaluators — whatever its status today, so
    an amber file depends on nothing that moves between commands."""
    cover = claim_logic.effective_gates(ledger, registry)
    out: list[tuple[Any, list[str]]] = []
    for claim in sorted(getattr(ledger, "claims", None) or (), key=lambda c: _natural(c.id)):
        if claim.kind != ClaimKind.MEASURABLE:
            continue
        ids = [g for g in cover.get(claim.id) or () if registry is not None
               and registry.get(g) is not None]
        if ids:
            out.append((claim, sorted(set(ids), key=_natural)))
    return out


def amber_subjects(root: str, ledger: Any, registry: Any) -> dict[str, dict]:
    """``{claim id: {"acceptance", "evaluators": {id: code digest}}}`` for
    every claim amber evaluates (`_eligible`): the digest of its acceptance
    condition (`verdicts.acceptance_of`) and the code digest of each covering
    evaluator and each prerequisite it needs (`gates.plan`). Amber is current
    for a claim only while these equal what its file holds."""
    anchors = verdicts.anchors_for(root, registry, out_dir=store.out_dir(root))
    claims_held = list(getattr(ledger, "claims", None) or ())
    out: dict[str, dict] = {}
    for claim, ids in _eligible(ledger, registry):
        evaluators: dict[str, str] = {}
        for spec in gates.plan(registry, ids):
            found = registry.get(spec.id)
            if found is None:
                continue
            evaluators[spec.id] = verdicts.code_digest(found[0], found[1],
                                                       anchors=anchors).digest
        out[claim.id] = {"acceptance": verdicts.acceptance_of(claims_held, claim.id).digest,
                         "evaluators": dict(sorted(evaluators.items(),
                                                   key=lambda kv: _natural(kv[0])))}
    return out


def _num(value: Any) -> Any:
    found = _scalar(value)
    if found is None:
        return None
    return found if isinstance(found, int) else _sig(found)


def _evaluate(copy: str, model: Any, projection: Any, now: str) -> dict:
    """Each automated claim's composition on this (nudged) design, by the
    check run's own rules: the covering evaluators and their prerequisites
    swept with ``record=False`` in the copy (an entry whose read set the
    nudge did not move is served from the copied cache; a non-bundled
    evaluator gets no model), then `cli._resolved` and
    `claims.compositions` — the one composition, never reinterpreted here.
    Returns ``{claim id: {"token", "by": [[evaluator, outcome, measured,
    limit, units], ...], "accept": [comparator, limit, limit_hi, units]}}``
    — ``accept`` the claim's acceptance condition, when it has a limit."""
    from . import cli                                    # the check run's own rules
    ledger = cli._load(copy)
    registry, _ = cli._registry(copy, ledger, strict=True)
    eligible = _eligible(ledger, registry)
    ids = sorted({g for _claim, found in eligible for g in found}, key=_natural)
    if not ids:
        return {}
    planned = gates.plan(registry, ids)
    tier = max(int(spec.tier) for spec in planned)
    ctx = cli._context(copy, ledger, model, projection, tier, quiet=True)
    result = verdicts.sweep(copy, registry, ctx, projection=projection, ledger=ledger,
                            max_tier=tier, only=ids, force=False, record=False, now=now)
    view, resolution = cli._resolved(copy, ledger, registry, projection, "", now=now,
                                     model=model, sweep=result)
    composed = claim_logic.compositions(view, registry=registry,
                                        stale_gates=resolution.stale_gates)
    by_id = {c.id: c for c in view.claims}
    out: dict[str, dict] = {}
    for claim, found in eligible:
        shown = by_id.get(claim.id, claim)
        composition = composed.get(claim.id)
        token = graph_logic._token(composition.status, composition.errored) \
            if composition is not None else "gap"
        rows = []
        for verdict in claim_logic.covering_verdicts(shown, view.verdicts):
            if verdict.gate not in found:
                continue
            rows.append([verdict.gate, verdict.outcome, _num(verdict.measured),
                         _num(verdict.limit), str(verdict.units or "")])
        rows.sort(key=lambda r: _natural(r[0]))
        out[claim.id] = {"token": token, "by": rows}
        acc = getattr(shown, "acceptance", None)
        if acc is not None and getattr(acc, "limit", None) is not None:
            # The claim's own limit, as the composition judged it (S-35): a
            # pass its evaluator gave against its own limit can still fail
            # here, and the flip is then said against this one.
            out[claim.id]["accept"] = [
                str(getattr(acc.comparator, "value", acc.comparator)), _num(acc.limit),
                _num(acc.limit_hi) if acc.limit_hi is not None else None, str(acc.units or "")]
    return out


def worker_main(argv: list[str]) -> int:
    """``python -m nopekit.derivation <job.json>``: run `_work` on the job and
    write its result beside the job, outside the copy. Exit 0 with a result;
    1 with ``{"ok": false, "error"}`` when the worker itself broke."""
    if len(argv) != 1:
        sys.stderr.write("usage: python -m nopekit.derivation <job.json>\n")
        return 2
    with open(argv[0], "r", encoding="utf-8") as fh:
        job = json.load(fh)
    os.chdir(job["copy"])
    try:
        result = _work(job, process_wide=True)
        code = 0
    except Exception as exc:                                # noqa: BLE001 - said to the parent
        result = {"ok": False, "error": f"{type(exc).__name__}: {_first(exc)}"}
        code = 1
    with open(job["out"] + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(result, fh, allow_nan=False, default=str)
    os.replace(job["out"] + ".tmp", job["out"])
    return code


# --------------------------------------------------------------------------- #
# launching a job
# --------------------------------------------------------------------------- #
class Launched(NamedTuple):
    """How one job ended: ``code`` the exit code (None when it timed out),
    ``timed_out``, ``tail`` the last lines of its stderr."""

    code: int | None
    timed_out: bool
    tail: str


def _package_parent() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def worker_env(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """The environment a worker (and a background trace) runs in: this one,
    with nopekit's package on ``PYTHONPATH`` first, no bytecode written, and
    one BLAS thread (`THREAD_ENV`)."""
    env = dict(os.environ if environ is None else environ)
    parent = _package_parent()
    old = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = parent + (os.pathsep + old if old else "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(THREAD_ENV)
    return env


def subprocess_launch(job: Mapping[str, Any], job_path: str, timeout: float) -> Launched:
    """The real launcher: ``python -m nopekit.derivation <job>``, in its own
    session, stopped (its whole process group) at ``timeout``. It starts in
    nopekit's own directory and moves into the copy itself (`worker_main`),
    so its build still runs there; started in the copy, ``-m`` put the copy's
    root first on ``sys.path``, and a ``difflib.py`` the project held there
    was imported by every build of every trace (found beside the background
    start's own, the follow-up after phase 3b)."""
    err_path = job_path + ".err"
    posix = os.name == "posix"
    with open(err_path, "wb") as err:
        kwargs: dict[str, Any] = {"cwd": _package_parent(), "env": worker_env(),
                                  "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
                                  "stderr": err}
        if posix:
            kwargs["start_new_session"] = True
        else:                                                    # pragma: no cover - windows
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        proc = subprocess.Popen([sys.executable, "-m", "nopekit.derivation", job_path],
                                **kwargs)
        try:
            code = proc.wait(timeout=timeout)
            timed_out = False
        except subprocess.TimeoutExpired:
            timed_out, code = True, None
            try:
                if posix:
                    os.killpg(proc.pid, 9)
                else:                                            # pragma: no cover - windows
                    proc.kill()
            except OSError:
                pass
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:                    # pragma: no cover
                pass
    try:
        with open(err_path, "r", encoding="utf-8", errors="replace") as fh:
            tail = " | ".join(fh.read().strip().splitlines()[-3:])
    except OSError:
        tail = ""
    return Launched(code, timed_out, tail[-400:])


#: One in-process job at a time, and no file opened by the run's other threads
#: while one runs: `modelio`'s import recording is process-global, so a file the
#: parent opened (a copy, a scratch row) while an in-process job loaded its model
#: landed in that job's recording, and a dict it iterated changed size under it
#: (a flaky ``RuntimeError`` in the review of phase 3b's tests). Re-entrant: the
#: run takes it around its own file work (`_run_locked`), and a test launcher
#: around its own. A subprocess worker records in its own process.
_IN_PROCESS = threading.RLock()


def in_process(job: Mapping[str, Any], job_path: str, timeout: float) -> Launched:
    """The same worker logic, in this process, on the job's copy — one job at a
    time (a model load swaps ``sys.modules`` and ``sys.path``). What every
    in-process test row passes as ``launch``."""
    with _IN_PROCESS:
        try:
            result = _work(job)
            code = 0
        except Exception as exc:                            # noqa: BLE001 - said to the parent
            result = {"ok": False, "error": f"{type(exc).__name__}: {_first(exc)}"}
            code = 1
        with open(job["out"], "w", encoding="utf-8") as fh:
            json.dump(result, fh, allow_nan=False, default=str)
    return Launched(code, False, "")


# --------------------------------------------------------------------------- #
# the run
# --------------------------------------------------------------------------- #
class Ran(NamedTuple):
    """What `run` did. ``state``: ``written`` (a tracked file was written),
    ``current`` (nothing to observe), ``partial`` (``--choices`` traced some of
    the plan; the scratch keeps them), ``incomplete`` (a build did not finish:
    nothing tracked was written for it), ``running`` (another trace holds the
    lock; only with ``quiet_if_running``)."""

    state: str
    key: str | None
    round: int | None
    written: tuple
    observed: int
    total: int
    skipped: dict
    unmoved: tuple
    unsteady: tuple
    raised: tuple
    incomplete: tuple
    amber: dict
    builds: dict
    problems: tuple
    order: dict
    timeout: float


def _words() -> Mapping[str, Any]:
    from . import report                                  # a reader's module: not at import
    return report.HUMAN["trace"]


def lock_path(root: str) -> str:
    return os.path.join(root, *LOCK_REL.split("/"))


def live_holder(root: str) -> int | None:
    """The pid of a live process on this host holding the trace lock, else
    None (a dead holder's file is left for the next acquire to reap)."""
    holder = util.FileLock(lock_path(root)).holder()
    pid = holder.get("pid")
    if isinstance(pid, int) and pid > 0 and holder.get("host") == util._HOST \
            and pid != os.getpid() and util._pid_alive(pid):
        return pid
    return None


def scratch_dir(root: str, key: str) -> str:
    return os.path.join(root, *SCRATCH_REL.split("/"), key[:16])


def scratch_state(root: str, key: str | None) -> dict:
    """The scratch's ``state.json`` for ``key`` (``{}`` when there is none)."""
    if not key:
        return {}
    try:
        with open(os.path.join(scratch_dir(root, key), "state.json"), "r",
                  encoding="utf-8") as fh:
            found = json.load(fh)
    except (OSError, ValueError):
        return {}
    return found if isinstance(found, dict) else {}


def _ignore_for(root: str) -> Callable[[str, list], set]:
    base = os.path.abspath(root)
    nopekit = os.path.join(base, store.NOPEKIT_DIR)

    def ignore(directory: str, names: list) -> set:
        here = os.path.abspath(directory)
        out = {n for n in names if n in _SNAPSHOT_SKIP_ANY}
        if here == base:
            out |= {n for n in names if n in _SNAPSHOT_SKIP_TOP}
        if here == nopekit:
            out |= {n for n in names if n in _SNAPSHOT_SKIP_NOPEKIT or n.endswith(".lock")}
        for n in names:
            if os.path.isfile(os.path.join(here, n, "pyvenv.cfg")):
                out.add(n)
        return out
    return ignore


def snapshot_size(root: str) -> tuple[int, list[tuple[int, str]]]:
    """``(bytes, [(bytes, top directory), ...])`` of what a snapshot copies."""
    ignore = _ignore_for(root)
    total = 0
    tops: dict[str, int] = {}
    base = os.path.abspath(root)
    for here, dirnames, filenames in os.walk(base):
        skip = ignore(here, list(dirnames) + list(filenames))
        dirnames[:] = [d for d in dirnames if d not in skip
                       and not os.path.islink(os.path.join(here, d))]
        for name in filenames:
            if name in skip:
                continue
            try:
                size = os.lstat(os.path.join(here, name)).st_size
            except OSError:
                continue
            total += size
            rel = os.path.relpath(here, base)
            top = rel.split(os.sep)[0] if rel != "." else "."
            tops[top] = tops.get(top, 0) + size
    return total, sorted(((v, k) for k, v in tops.items()), reverse=True)


def _sign(direction: int) -> str:
    return "-" if direction == 0 else "+"


def _step_of(by_name: Mapping[str, Nudge], choice: Any, direction: Any) -> str:
    """`step_word` for one of this run's moves."""
    nudge = by_name.get(choice) if choice is not None else None
    return step_word(int(direction or 0), nudge.change if nudge is not None else None)


def _plan_numeric(plan: Iterable[Nudge]) -> list[Nudge]:
    return [n for n in plan if n.steps]


def _write_once(path: str, data: bytes) -> bool:
    """Write ``data`` at ``path`` atomically, only when ``path`` is absent;
    True when written."""
    if os.path.exists(path):
        return False
    util.ensure_dir(os.path.dirname(path))
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    if os.path.exists(path):
        os.unlink(tmp)
        return False
    os.replace(tmp, path)
    return True


def _write_scratch(path: str, doc: Mapping[str, Any]) -> None:
    util.ensure_dir(os.path.dirname(path))
    util.atomic_write_text(path, json.dumps(doc, sort_keys=True, allow_nan=False))


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def amber_current(ambers: Iterable[AmberFile], subjects: Mapping[str, Mapping[str, Any]],
                  amber_choices: Iterable[str]) -> bool:
    """Whether some amber file holds every subject claim at its current
    digests over every amber choice."""
    wanted = set(amber_choices)
    if not wanted or not subjects:
        return True
    for amber in sorted(ambers, key=lambda a: os.path.basename(a.path)):
        if not wanted <= set(amber.choices):
            continue
        if all(_same_subject(amber.claims.get(cid), now) for cid, now in subjects.items()):
            return True
    return False


def _same_subject(held: Any, now: Mapping[str, Any]) -> bool:
    return isinstance(held, Mapping) and held.get("acceptance") == now.get("acceptance") \
        and dict(held.get("evaluators") or {}) == dict(now.get("evaluators") or {})


def run(root: str, *, plan: list[Nudge], entry: str, amber_choices: Mapping[str, list] = {},
        choices: Iterable[str] | None = None, workers: int | None = None,
        timeout: float | None = None, round_: int | None = None, now: str = "",
        quiet_if_running: bool = False, background: bool = False,
        on_line: Callable[[str], None] | None = None,
        launch: Callable[..., Launched] | None = None,
        project_lock: Callable[[], Any] | None = None,
        pack_dirs: Iterable[str] = ()) -> Ran:
    """Trace the design: one snapshot under the project lock, base-1 built
    alone (its key is the authoritative one, computed after its build), then
    base-2 and every move not already in the scratch, ``workers`` at a time,
    each in a fresh copy; a raised move run once more alone; then, under the
    project lock and only when the path is absent, the trace file when every
    numeric choice of ``plan`` was moved both ways, and the amber file when
    every amber move was evaluated. Holds `LOCK_REL` throughout, never the
    project lock but to snapshot and to write. Writes nothing tracked when
    anything did not finish. ``plan`` is `plan_of` the model's config;
    ``amber_choices`` ``{choice: [assumption ids]}`` (`graph.value_sources`);
    ``launch`` the launcher (`subprocess_launch`; tests pass `in_process`)."""
    said = _words()
    say = on_line or (lambda text: None)
    launch = launch or subprocess_launch
    workers = int(workers if workers is not None else default_workers())
    if workers < 1:
        raise NopekitError(said["refuse"]["workers"])
    root = os.path.abspath(root)
    if project_lock is None:
        project_lock = lambda: util.FileLock(os.path.join(store.nopekit_dir(root),  # noqa: E731
                                                          "build.lock"))
    numeric = _plan_numeric(plan)
    by_name = {n.name: n for n in plan}
    wanted = None if choices is None else [c for c in choices]
    amber_set = {c: list(v) for c, v in amber_choices.items()
                 if c in by_name and by_name[c].steps}
    skipped = {n.name: n.skipped for n in sorted(plan, key=lambda n: _natural(n.name))
               if not n.steps}

    pid = live_holder(root)
    if pid is not None:
        if quiet_if_running:
            return _ran("running", None, round_, skipped=skipped)
        raise NopekitError(said["refuse"]["running"].format(pid=pid, log=LOG_REL))
    trace_lock = util.FileLock(lock_path(root), stale_after=7 * 24 * 3600.0)
    with trace_lock:
        tmp = tempfile.mkdtemp(prefix="nopekit-trace-")
        try:
            return _run_locked(root, tmp, plan=plan, numeric=numeric, by_name=by_name,
                               entry=entry, amber_set=amber_set, wanted=wanted,
                               workers=workers, timeout=timeout, round_=round_, now=now,
                               background=background, say=say, launch=launch,
                               project_lock=project_lock, pack_dirs=pack_dirs,
                               skipped=skipped)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def _ran(state: str, key: str | None, round_: int | None, **kw: Any) -> Ran:
    base = dict(written=(), observed=0, total=0, skipped={}, unmoved=(), unsteady=(),
                raised=(), incomplete=(), amber={}, builds={}, problems=(), order={},
                timeout=0.0)
    base.update(kw)
    return Ran(state, key, round_, **base)


def _run_locked(root: str, tmp: str, *, plan, numeric, by_name, entry, amber_set, wanted,
                workers, timeout, round_, now, background, say, launch, project_lock,
                pack_dirs, skipped) -> Ran:
    said = _words()
    real_tmp = os.path.realpath(tmp)
    for clash in [root] + [os.path.abspath(p) for p in pack_dirs]:
        if _inside(real_tmp, os.path.realpath(clash)):
            raise NopekitError(said["refuse"]["inside"].format(base=tmp, clash=clash))
    size, tops = snapshot_size(root)
    if size > SNAPSHOT_MAX_BYTES:
        raise NopekitError(said["refuse"]["big"].format(
            size=util.human_bytes(size),
            dirs=", ".join(f"{name} ({util.human_bytes(n)})" for n, name in tops[:3])))
    snap = os.path.join(tmp, "snap")
    with project_lock():
        shutil.copytree(root, snap, symlinks=True, ignore=_ignore_for(root))
    counter = {"n": 0}
    count_guard = threading.Lock()
    # Only an in-process launch shares the import recording (`_IN_PROCESS`);
    # subprocess workers copy and read in parallel.
    io = _IN_PROCESS if launch is not subprocess_launch else contextlib.nullcontext()

    def one(kind: str, choice: str | None = None, direction: int | None = None,
            step: Any = None, amber: bool = False, subjects: bool = False,
            limit: float = BUILD_TIMEOUT_FLOOR) -> dict:
        with count_guard:
            counter["n"] += 1
            n = counter["n"]
        copy = os.path.join(tmp, f"job-{n}")
        job_path = os.path.join(tmp, f"job-{n}.json")
        out_path = os.path.join(tmp, f"job-{n}.out.json")
        job = {"harness": HARNESS, "root": root, "copy": copy, "entry": entry, "kind": kind,
               "choice": choice, "dir": direction, "step": step, "amber": amber,
               "subjects": subjects, "now": now, "out": out_path}
        try:
            with io:
                shutil.copytree(snap, copy, symlinks=True)
                with open(job_path, "w", encoding="utf-8") as fh:
                    json.dump(job, fh, allow_nan=False)
            started = time.perf_counter()
            ended = launch(job, job_path, limit)
            seconds = time.perf_counter() - started
            with io:
                result = _read_json(out_path) if not ended.timed_out else None
            if ended.timed_out:
                return {"job": job, "fail": "timeout", "seconds": seconds, "limit": limit}
            if not isinstance(result, dict) or not result.get("ok"):
                why = (result or {}).get("error") if isinstance(result, dict) else ""
                return {"job": job, "fail": "dead", "code": ended.code,
                        "why": why or ended.tail, "seconds": seconds}
            return {"job": job, "result": result, "seconds": seconds}
        finally:
            with io:
                shutil.rmtree(copy, ignore_errors=True)

    # -- base-1, alone: the key, computed after its build -------------------- #
    base_limit = float(timeout) if timeout else BUILD_TIMEOUT_FLOOR
    # With amber choices, base-1 also evaluates the unmoved design, so the
    # summary names as flipping only a claim that is Checked there.
    first = one("base", subjects=bool(amber_set), amber=bool(amber_set), limit=base_limit)
    if "fail" in first:
        why = (said["base_timed_out"].format(s=first["seconds"])
               if first["fail"] == "timeout"
               else said["base_dead"].format(code=first.get("code"),
                                             why=first.get("why") or ""))
        raise NopekitError(said["refuse"]["base_raised"].format(line=why))
    base = first["result"]
    if base.get("wrote_project"):
        # Refused whole, as any build's write is (the write is not undone):
        # no tracked file, exit 1.
        return _ran("incomplete", base.get("key"), round_, skipped=skipped,
                    total=len(numeric), problems=(said["refuse"]["wrote_base"].format(
                        paths=", ".join(base["wrote_project"][:6])),),
                    builds={"total": 1, "run": 1, "reused": 0, "raised": 0,
                            "incomplete": 0})
    if base.get("raised"):
        raise NopekitError(said["refuse"]["base_raised"].format(
            line=f"{base['raised']}: {base.get('raised_line') or ''}".strip()))
    key = base.get("key")
    if not key:
        raise NopekitError(said["refuse"]["unrecorded"])
    limit = float(timeout) if timeout else max(BUILD_TIMEOUT_FLOOR,
                                               TIMEOUT_FACTOR * float(first["seconds"]))
    path = trace_path(root, key)
    state, found, line = read_trace(path)
    if state not in ("ok", "absent"):
        raise NopekitError(said["refuse"]["edited"].format(path=_rel(root, path), state=state,
                                                           line=line))
    trace_ok = state == "ok"
    subjects = base.get("subjects") or {}
    ambers = [a for a in (read_amber(p)[1] for p in amber_paths(root, key)) if a is not None]
    if trace_ok and amber_current(ambers, subjects, amber_set):
        say(said["current"].format(path=_rel(root, path)))
        return _ran("current", key, round_, skipped=skipped, total=len(numeric),
                    observed=len(found.observed) if found is not None else 0,
                    builds={"total": 1, "run": 1, "reused": 0, "raised": 0, "incomplete": 0},
                    timeout=limit)
    amber_needed = bool(amber_set) and bool(subjects) and not amber_current(
        ambers, subjects, amber_set)

    # The scratch lives under the key a reader can name (no data: `trace_for`
    # and `start_background` find its state.json); each row says the full key
    # it was observed under, and amber the subjects it ran against, so a row
    # from other data or another acceptance condition is never reused.
    scratch = scratch_dir(root, key_of(dict(base["keyed_on"], data={})))
    amber_for = seal(subjects) if subjects else ""
    held: dict[str, dict] = {}
    for nudge in numeric:
        found_scratch = _read_json(os.path.join(scratch, f"{nudge.name}.json"))
        if _usable(found_scratch, key):
            held[nudge.name] = found_scratch

    # -- the jobs ------------------------------------------------------------ #
    if trace_ok:
        targets = [n for n in numeric if n.name in amber_set]
    else:
        targets = [n for n in numeric if wanted is None or n.name in wanted]
    jobs: list[tuple] = []
    reused = 0
    for nudge in targets:
        need_amber = amber_needed and nudge.name in amber_set
        have = held.get(nudge.name)
        if have is not None and (not need_amber or _amber_usable(have, amber_for)) \
                and (trace_ok or isinstance(have.get("moves"), dict)):
            reused += 2
            continue
        for direction, step in enumerate(nudge.steps):
            jobs.append(("nudge", nudge.name, direction, step, need_amber))
    if not trace_ok:
        jobs.insert(0, ("base", None, None, None, False))
    total_jobs = len(jobs)
    total_moves = sum(1 for spec in jobs if spec[0] == "nudge")
    say(said["head"].format(entry=entry, key12=key[:12], n=len(targets),
                            builds=total_jobs + 1, workers=workers))
    if skipped:
        items = [f"{name} ({said['skip'][token]})" for name, token in skipped.items()]
        shown = ", ".join(items[:4]) + (said["and_more"].format(n=len(items) - 4)
                                        if len(items) > 4 else "")
        say(said["not_nudged"].format(items=shown))

    results: dict[tuple, dict] = {}
    done = {"n": 0}

    def submit(spec: tuple) -> dict:
        kind, choice, direction, step, amber = spec
        return one(kind, choice, direction, step, amber=amber, limit=limit)

    def report_one(spec: tuple, outcome: dict) -> None:
        kind, choice, direction, _step, _amber = spec
        if kind == "base":
            return
        done["n"] += 1
        sign = _step_of(by_name, choice, direction)
        if "fail" in outcome:
            text = (said["timed_out"].format(choice=choice, step=sign, s=outcome["seconds"])
                    if outcome["fail"] == "timeout"
                    else said["dead"].format(choice=choice, step=sign, code=outcome.get("code"),
                                             why=outcome.get("why") or ""))
        elif outcome["result"].get("raised"):
            text = said["progress_raised"].format(
                done=done["n"], total=total_moves, choice=choice, step=sign,
                type=outcome["result"]["raised"], line=outcome["result"].get("raised_line", ""))
        else:
            moved = len(moves_between(base["values"] or {}, outcome["result"]["values"] or {}))
            text = said["progress"].format(done=done["n"], total=total_moves, choice=choice,
                                           step=sign, n=moved)
        say(text)

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(submit, spec): spec for spec in jobs}
        for future in concurrent.futures.as_completed(futures):
            spec = futures[future]
            outcome = future.result()
            results[spec] = outcome
            report_one(spec, outcome)
            with io:
                _maybe_scratch(scratch, spec, results, base, by_name, amber_set, amber_needed,
                               key=key, amber_for=amber_for)

    # -- a raise is run once more, alone ------------------------------------ #
    # A raise is kept only once it raised the same way alone (``confirmed``);
    # until then, and for a build that wrote into the project, no scratch row
    # is written, so the next run builds the choice again. What slipped
    # through (review of phase 3b): a row was scratched the moment both
    # directions were back, the refusal left it, and the next run wrote a
    # transient MemoryError, or a build that wrote into the project, into the
    # tracked trace that is never rewritten.
    incomplete: list[list] = []
    confirmed: set = set()
    retry_wrote: list[tuple] = []
    for spec, outcome in sorted(results.items(), key=lambda kv: str(kv[0])):
        result = outcome.get("result")
        if spec[0] == "base" or not result or not result.get("raised"):
            continue
        again = submit(spec)
        second = again.get("result")
        if second and second.get("wrote_project"):
            retry_wrote.append((spec, list(second["wrote_project"])))
        if not second or second.get("raised") != result.get("raised"):
            other = (second or {}).get("raised") or (again.get("fail") or "a result")
            incomplete.append([spec[1], spec[2], said["environmental"].format(
                choice=spec[1], step=_step_of(by_name, spec[1], spec[2]), a=result.get("raised"),
                b=other)])
            results[spec] = {"job": outcome["job"], "fail": "environmental"}
        else:
            confirmed.add(spec)
    for spec, outcome in results.items():
        if "fail" in outcome and outcome["fail"] != "environmental":
            step = _step_of(by_name, spec[1], spec[2]) if spec[2] is not None else "build"
            why = (said["timed_out"].format(choice=spec[1] or "base", step=step,
                                            s=outcome["seconds"])
                   if outcome["fail"] == "timeout"
                   else said["dead"].format(choice=spec[1] or "base", step=step,
                                            code=outcome.get("code"),
                                            why=outcome.get("why") or ""))
            incomplete.append([spec[1] or "base", spec[2], why])
    wrote = sorted({p for outcome in results.values()
                    for p in ((outcome.get("result") or {}).get("wrote_project") or ())}
                   | {p for _spec, paths in retry_wrote for p in paths})
    problems: list[str] = []
    if wrote:
        culprit = next((spec for spec, outcome in sorted(results.items(), key=lambda kv: str(kv[0]))
                        if (outcome.get("result") or {}).get("wrote_project")),
                       retry_wrote[0][0] if retry_wrote else None)
        problems.append(said["refuse"]["wrote"].format(
            choice=(culprit[1] if culprit else None) or "base",
            step=(_step_of(by_name, culprit[1], culprit[2])
                  if culprit and culprit[2] is not None else "build"),
            paths=", ".join(wrote[:6])))
    for spec in results:
        _maybe_scratch(scratch, spec, results, base, by_name, amber_set, amber_needed,
                       force=True, confirmed=confirmed, key=key, amber_for=amber_for)
    if incomplete or problems:
        _write_scratch(os.path.join(scratch, "state.json"),
                       {"incomplete": sorted(incomplete, key=lambda r: (str(r[0]), str(r[1]))),
                        "background": bool(background), "wrote_project": wrote,
                        "timeout": limit})
        return _ran("incomplete", key, round_, skipped=skipped, total=len(numeric),
                    incomplete=tuple(tuple(r) for r in incomplete), problems=tuple(problems),
                    builds={"total": total_jobs + 1, "run": len(results) + 1,
                            "reused": reused, "raised": 0, "incomplete": len(incomplete)},
                    timeout=limit)

    # -- assembly ------------------------------------------------------------ #
    rows: dict[str, dict] = {}
    for nudge in numeric:
        found_scratch = _read_json(os.path.join(scratch, f"{nudge.name}.json"))
        if _usable(found_scratch, key):
            rows[nudge.name] = found_scratch
    second_base = next((o.get("result") for s, o in results.items() if s[0] == "base"), None)
    unsteady: list[str] = []
    if second_base is not None:
        b1, b2 = base.get("values") or {}, second_base.get("values") or {}
        unsteady = sorted((n for n in set(b1) | set(b2)
                           if (b1.get(n) or [None])[0] != (b2.get(n) or [None])[0]),
                          key=_natural)
    written: list[str] = []
    complete = all(isinstance((rows.get(n.name) or {}).get("moves"), dict) for n in numeric)
    trace_doc = None
    raised_rows: list[tuple] = []
    if not trace_ok and complete and second_base is not None:
        trace_doc = _trace_doc(key, base, rows, numeric, skipped, unsteady, round_, entry)
        with project_lock():
            if _write_once(path, render(trace_doc)):
                written.append(_rel(root, path))
    for n in numeric:
        for direction, kind in enumerate((rows.get(n.name) or {}).get("raised") or ()):
            if kind:
                raised_rows.append((n.name, direction, kind))
    amber_info: dict[str, Any] = {}
    if amber_needed and all(_amber_usable(rows.get(c) or {}, amber_for) for c in amber_set):
        amber_doc = _amber_doc(key, round_, amber_set, rows, subjects)
        amber_path = os.path.join(trace_dir(root),
                                  f"{key[:16]}.amber.{amber_doc['self'][:16]}.json")
        with project_lock():
            if _write_once(amber_path, render(amber_doc)):
                written.append(_rel(root, amber_path))
        amber_info = _amber_summary(amber_doc, base.get("amber") or {})
    elif amber_set and subjects and not amber_needed:
        amber_info = {"choices": sorted(amber_set, key=_natural), "flips": [], "current": True}
    try:
        os.unlink(os.path.join(scratch, "state.json"))
    except OSError:
        pass
    if trace_doc is None and not trace_ok:
        state = "partial"
    elif written:
        state = "written"
    else:
        state = "current"
    traced = (TraceFile(trace_doc, path) if trace_doc is not None
              else (found if trace_ok else None))
    order = {}
    if traced is not None:
        order = {"derives": len(traced.derives), "after": len(traced.after),
                 "ties": len(traced.ties), "singles": len(traced.singles),
                 "moved": len(traced.moved), "unmoved": list(traced.unmoved)}
    return _ran(state, key, round_, written=tuple(written),
                observed=sum(1 for n in numeric if isinstance((rows.get(n.name) or {})
                                                               .get("moves"), dict)),
                total=len(numeric), skipped=skipped,
                unmoved=tuple(traced.unmoved) if traced is not None else (),
                unsteady=tuple(unsteady), raised=tuple(raised_rows), amber=amber_info,
                builds={"total": total_jobs + 1, "run": len(results) + 1, "reused": reused,
                        "raised": len(raised_rows), "incomplete": 0},
                order=order, timeout=limit)


def _usable(row: Any, key: str) -> bool:
    """A scratch row this run may use: this harness, observed under ``key``
    (the full key: the same data too), with its moves."""
    return isinstance(row, dict) and row.get("harness") == HARNESS and row.get("key") == key \
        and isinstance(row.get("moves"), dict)


def _amber_usable(row: Mapping[str, Any], amber_for: str) -> bool:
    """A row's amber runs, usable only when they ran against these subjects
    (the acceptance conditions and the evaluators' code, sealed). What
    slipped through (review of phase 3b): rows were reused whatever they ran
    against, and an amber file sealed with a 100 MPa limit said C3 flipped
    on runs made at 0.2 MPa."""
    return isinstance(row.get("amber"), list) and bool(amber_for) \
        and row.get("amber_for") == amber_for


def _maybe_scratch(scratch: str, spec: tuple, results: Mapping[tuple, dict], base: dict,
                   by_name: Mapping[str, Nudge], amber_set: Mapping[str, list],
                   amber_needed: bool, *, force: bool = False, confirmed: Iterable = (),
                   key: str = "", amber_for: str = "") -> None:
    """When both directions of a choice are back and neither failed, wrote
    into the project, or raised without the raise being ``confirmed`` (run
    again alone, the same), write its scratch row: ``{"harness", "key",
    "moves", "raised", "amber"?, "amber_for"?}``."""
    kind, choice = spec[0], spec[1]
    if kind != "nudge":
        return
    specs = [("nudge", choice, d, by_name[choice].steps[d], spec[4]) for d in (0, 1)]
    pair = [results.get(s) for s in specs]
    if any(p is None or "fail" in p for p in pair):
        return
    held = set(confirmed)
    for s, p in zip(specs, pair):
        result = p["result"]
        if result.get("wrote_project") or (result.get("raised") and s not in held):
            return
    path = os.path.join(scratch, f"{choice}.json")
    existing = _read_json(path)
    row: dict[str, Any] = dict(existing) if _usable(existing, key) \
        else {"harness": HARNESS, "key": key}
    base_values = base.get("values") or {}
    moves: dict[str, list] = {}
    raised = []
    for direction, outcome in enumerate(pair):
        result = outcome["result"]
        raised.append(result.get("raised"))
        if result.get("raised"):
            continue
        for name, move in moves_between(base_values, result.get("values") or {}).items():
            moves.setdefault(name, [None, None])[direction] = move
    if not isinstance(row.get("moves"), dict) or force:
        row["moves"] = {k: moves[k] for k in sorted(moves, key=_natural)}
        row["raised"] = raised
    if spec[4] and amber_needed and choice in amber_set:
        row["amber"] = [(o["result"].get("amber") if not o["result"].get("raised")
                         else {"__raised__": o["result"].get("raised")}) for o in pair]
        row["amber_for"] = amber_for
    _write_scratch(path, row)


def _trace_doc(key: str, base: Mapping[str, Any], rows: Mapping[str, dict],
               numeric: list[Nudge], skipped: Mapping[str, str], unsteady: list[str],
               round_: int | None, entry: str) -> dict:
    unsteady_set = set(unsteady)
    observed: dict[str, dict] = {}
    moved_any: set[str] = set()
    for nudge in sorted(numeric, key=lambda n: _natural(n.name)):
        row = rows[nudge.name]
        moves = {k: v for k, v in (row.get("moves") or {}).items() if k not in unsteady_set}
        moved_any.update(moves)
        item: dict[str, Any] = {}
        small, display = verdicts.small_value(nudge.value)
        if small:
            item["value"] = display
        item["steps"] = list(nudge.steps)
        if any(abs(c - d) > 1e-9 for c, d in zip(nudge.change, (-STEP, STEP))):
            # an integer's move is not 10%: its size, said by every label
            item["change"] = list(nudge.change)
        item["moves"] = {k: moves[k] for k in sorted(moves, key=_natural)}
        item["raised"] = list(row.get("raised") or [None, None])
        observed[nudge.name] = item
    compared = [n for n in (base.get("values") or {}) if n not in unsteady_set]
    unmoved = sorted((n for n in compared if n not in moved_any), key=_natural)
    doc = {"generated": HEADER, "schema": SCHEMA, "key": key,
           "keyed_on": dict(base["keyed_on"]), "round": round_, "entry": entry,
           "skipped": dict(skipped), "observed": observed, "unmoved": unmoved,
           "unsteady": list(unsteady)}
    return _sealed(doc, TRACE_KEYS)


def _amber_doc(key: str, round_: int | None, amber_set: Mapping[str, list],
               rows: Mapping[str, dict], subjects: Mapping[str, Mapping[str, Any]]) -> dict:
    claims_out: dict[str, dict] = {}
    for cid in sorted(subjects, key=_natural):
        runs: dict[str, list] = {}
        for choice in sorted(amber_set, key=_natural):
            pair = rows[choice].get("amber") or [None, None]
            shown = []
            for found in pair:
                if not isinstance(found, dict) or "__raised__" in found:
                    shown.append({"token": "raised", "by": []})
                    continue
                run_ = found.get(cid)
                if not isinstance(run_, dict):
                    shown.append({"token": "absent", "by": []})
                    continue
                item = {"token": str(run_.get("token")), "by": list(run_.get("by") or [])}
                if isinstance(run_.get("accept"), list):
                    item["accept"] = list(run_["accept"])
                shown.append(item)
            runs[choice] = shown
        claims_out[cid] = {"acceptance": subjects[cid].get("acceptance"),
                           "evaluators": dict(subjects[cid].get("evaluators") or {}),
                           "runs": runs}
    doc = {"generated": AMBER_HEADER, "schema": SCHEMA, "trace": key, "round": round_,
           "step": STEP,
           "choices": {c: sorted(amber_set[c], key=_natural)
                       for c in sorted(amber_set, key=_natural)},
           "claims": claims_out}
    return _sealed(doc, AMBER_KEYS)


def _amber_summary(doc: Mapping[str, Any], base: Mapping[str, Any]) -> dict:
    """The CLI's amber line: the claims evaluated, and those Checked on the
    unmoved design (``base``, base-1's evaluation) that some move flips."""
    flips = []
    for cid, row in (doc.get("claims") or {}).items():
        if ((base.get(cid) or {}).get("token")) != "checked":
            continue
        for choice, pair in (row.get("runs") or {}).items():
            if any(isinstance(r, dict) and r.get("token") in FLIP_TOKENS for r in pair):
                flips.append(cid)
                break
    return {"choices": sorted(doc.get("choices") or {}, key=_natural),
            "claims": len(doc.get("claims") or {}), "flips": sorted(set(flips), key=_natural),
            "current": False}


# --------------------------------------------------------------------------- #
# reading amber
# --------------------------------------------------------------------------- #
#: Amber's states, in precedence order.
AMBER_STATES = ("untraced", "not-current", "flips", "unclear", "holds")


class Amber(NamedTuple):
    """One Checked claim's amber now. ``state`` (`AMBER_STATES`); ``flips``
    ``(assumption, choice, direction, evaluator, measured, limit, units)`` for
    each flipping run; ``unclear`` ``(token, choice, direction)``; ``via``
    ``(assumption, choice)`` — the unconfirmed assumptions and the choices they
    source that this claim rests on; ``why`` for ``untraced`` and
    ``not-current``; ``rerun`` — whether a trace run would answer it (never
    for a choice the trace does not move). A flip's ``limit`` and ``units`` are
    the evaluator's when the evaluator itself failed, else the claim's
    acceptance condition, which the composition judged against (review of phase
    3b: a flip the cross-check decided was said against the evaluator's own
    15 MPa, a comfortable pass)."""

    state: str
    flips: tuple
    unclear: tuple
    via: tuple
    why: str
    rerun: bool = False
    changes: tuple = ()

    def step(self, choice: str, direction: int, *, minus: str = "-") -> str:
        """How the move of ``choice`` in ``direction`` is said: ``-10%``, or
        an integer's actual size (`step_word`; ``changes`` holds the trace's
        ``(choice, [lo, hi])`` for every choice that moves by other than
        10%)."""
        found = dict(self.changes).get(choice)
        return step_word(direction, found, minus=minus)


def unconfirmed(built: Any, tokens: Mapping[str, str], aid: str) -> bool:
    """An assumption no person has confirmed: its token is not ``assumed``
    (owned), and no physical claim that `resolves` it reads ``checked``."""
    if tokens.get(aid) == "assumed":
        return False
    for source in built.into(graph_logic.node_id("claim", aid), "resolves"):
        if tokens.get(source.partition(":")[2]) == "checked":
            return False
    return True


def amber_states(read: TraceRead, *, built: Any, tokens: Mapping[str, str],
                 subjects: Mapping[str, Mapping[str, Any]]) -> dict[str, Amber]:
    """Amber for every claim whose token is ``checked`` now and that rests on
    an unconfirmed assumption through a choice it sources (``built.via``):
    ``untraced`` (no trace for the current design, no amber file holding the
    claim, or a choice the trace does not move), ``not-current`` (the file's
    acceptance digest, evaluator set or an evaluator's code digest differs
    from ``subjects``, `amber_subjects` now), else ``flips``, ``unclear`` or
    ``holds`` from its runs. ``tokens`` are the claims' status tokens
    (`graph.tokens`). Display only: nothing here moves a status."""
    said = _words()
    out: dict[str, Amber] = {}
    trace = read.trace
    for cid, token in sorted(tokens.items(), key=lambda kv: _natural(kv[0])):
        if token != "checked":
            continue
        via: list[tuple[str, str]] = []
        for aid in built.rests_on(cid):
            if not unconfirmed(built, tokens, aid):
                continue
            for _ev, _read, sourced in built.via(cid, aid):
                node = built.node(graph_logic.node_id("value", sourced))
                if node is not None and node.attrs.get("role") == "choice" \
                        and (aid, sourced) not in via:
                    via.append((aid, sourced))
        if not via:
            continue
        via.sort(key=lambda p: (_natural(p[0]), _natural(p[1])))
        if read.state != "current" or trace is None:
            out[cid] = Amber("untraced", (), (), tuple(via), said["amber_why"]["no_trace"],
                             read.state == "none")
            continue
        skipped = [(c, trace.skipped[c]) for _a, c in via if c in trace.skipped]
        if skipped:
            name, token_ = skipped[0]
            out[cid] = Amber("untraced", (), (), tuple(via), said["amber_why"]["skipped"].format(
                name=name, word=said["skip"].get(token_, token_)), False)
            continue
        holding = [a for a in sorted(read.ambers, key=lambda a: os.path.basename(a.path))
                   if cid in a.claims]
        now = subjects.get(cid)
        changes = tuple((c, list((trace.observed.get(c) or {}).get("change")))
                        for _a, c in via
                        if isinstance((trace.observed.get(c) or {}).get("change"), list))
        matching = [a for a in holding
                    if now is not None and _same_subject(a.claims.get(cid), now)
                    and all(c in a.choices for _a, c in via)]
        if not matching:
            if not holding:
                out[cid] = Amber("untraced", (), (), tuple(via), said["amber_why"]["no_file"],
                                 True, changes)
                continue
            # The reason is read off the closest file: one at the current
            # acceptance condition first, then one with the current evaluator
            # set, then by name. What slipped through (review of phase 3b):
            # the first file by name was asked, and a committed file run at
            # another limit said "the acceptance condition changed" when only
            # the evaluator's code had.
            def closeness(amber: AmberFile) -> tuple:
                held_ = amber.claims.get(cid) or {}
                return (now is None or held_.get("acceptance") != now.get("acceptance"),
                        now is None or set(held_.get("evaluators") or {})
                        != set(now.get("evaluators") or {}),
                        not all(c in amber.choices for _a, c in via))
            closest = min(holding, key=closeness)
            held = closest.claims.get(cid) or {}
            if now is None or set((held.get("evaluators") or {})) != set(
                    now.get("evaluators") or {}):
                why = said["amber_why"]["evaluators"]
            elif held.get("acceptance") != now.get("acceptance"):
                why = said["amber_why"]["acceptance"]
            else:
                changed = [g for g, d in sorted((now.get("evaluators") or {}).items(),
                                                key=lambda kv: _natural(kv[0]))
                           if (held.get("evaluators") or {}).get(g) != d]
                if changed:
                    why = said["amber_why"]["gate"].format(gate=changed[0])
                else:
                    missing = [c for _a, c in via if c not in closest.choices]
                    out[cid] = Amber("untraced", (), (), tuple(via),
                                     said["amber_why"]["not_run"].format(
                                         name=missing[0] if missing else "?"), True, changes)
                    continue
            out[cid] = Amber("not-current", (), (), tuple(via), why, True, changes)
            continue
        runs_of = matching[0].claims[cid].get("runs") or {}
        flips: list[tuple] = []
        unclear: list[tuple] = []
        for aid, choice in via:
            for direction, run_ in enumerate(runs_of.get(choice) or ()):
                found = str((run_ or {}).get("token") or "")
                if found in FLIP_TOKENS:
                    flips.append((aid, choice, direction) + _flip_row(run_ or {}))
                elif found != "checked":
                    unclear.append((found or "absent", choice, direction))
        state = "flips" if flips else "unclear" if unclear else "holds"
        out[cid] = Amber(state, tuple(flips), tuple(unclear), tuple(via), "", False, changes)
    return out


def _flip_row(run_: Mapping[str, Any]) -> tuple:
    """``(evaluator, measured, limit, units)`` for one flipping run: the
    first evaluator that did not pass, against its own limit; when every one
    passed (the claim's acceptance condition failed the value), the first
    one's value against the claim's limit — the bound it is past."""
    rows = [r for r in (run_.get("by") or ()) if isinstance(r, (list, tuple)) and len(r) >= 5]
    failed = next((r for r in rows if r[1] != "pass"), None)
    if failed is not None:
        return (failed[0], failed[2], failed[3], failed[4])
    if not rows:
        return ("", None, None, "")
    row = rows[0]
    accept = run_.get("accept")
    if isinstance(accept, list) and len(accept) == 4 and accept[1] is not None \
            and (not accept[3] or not row[4] or accept[3] == row[4]):
        comparator, low, high, units = accept
        limit = low
        if high is not None and isinstance(row[2], (int, float)) \
                and not isinstance(row[2], bool) and row[2] > high:
            limit = high
        return (row[0], row[2], limit, units or row[4])
    return (row[0], row[2], row[3], row[4])


def amber_now(root: str, view: Any, registry: Any, built: Any, tokens: Mapping[str, str],
              read: TraceRead) -> dict[str, Amber]:
    """`amber_states` with the current digests read here (`amber_subjects`),
    only when there is a trace to compare them with."""
    subjects: dict = {}
    if read.state == "current" and registry is not None:
        try:
            subjects = amber_subjects(root, view, registry)
        except (NopekitError, OSError, ValueError):
            subjects = {}
    return amber_states(read, built=built, tokens=tokens, subjects=subjects)


def state_payload(read: TraceRead, built: Any, amber: Mapping[str, Amber]) -> dict:
    """``state.json``'s ``trace`` and ``amber`` keys (architecture phase 3b):
    ``{"trace": {"key": 12 hex or None, "round", "state": "traced" |
    "untraced"}, "amber": {claim id: state}}`` — tokens, inside the page's
    resolution digest, so an amber change makes the page stale."""
    traced = read.trace is not None and getattr(built, "trace", None) is not None
    return {"trace": {"key": read.key[:12] if traced and read.key else None,
                      "round": read.trace.round if traced else None,
                      "state": "traced" if traced else "untraced"},
            "amber": {cid: found.state for cid, found in sorted(
                amber.items(), key=lambda kv: _natural(kv[0]))}}


def needed(read: TraceRead, states: Mapping[str, Amber]) -> str:
    """What `round` asks of a background trace: ``"trace"`` when the current
    design has no trace, ``"amber"`` when it has one and some claim's amber is
    not current or was never run for a choice the trace moves, ``""``
    otherwise — a choice the trace does not move never asks, so `round` cannot
    loop on it."""
    if read.state == "none":
        return "trace"
    if read.state != "current":
        return ""
    if any(a.rerun for a in states.values()):
        return "amber"
    return ""


def amber_words(amber: Amber) -> str:
    """One CLI item for `status`'s ``amber:`` line."""
    said = _words()
    if amber.state == "flips" and amber.flips:
        aid, choice, direction, *_rest = amber.flips[0]
        return said["status_flips"].format(aid=aid, choice=choice,
                                           step=amber.step(choice, direction))
    if amber.state == "not-current":
        return said["status_not_current"].format(why=amber.why)
    if amber.state == "unclear" and amber.unclear:
        token, choice, direction = amber.unclear[0]
        return said["status_unclear"].format(token=token, choice=choice,
                                             step=amber.step(choice, direction))
    if amber.state == "untraced":
        return said["status_untraced"]
    return amber.state


# --------------------------------------------------------------------------- #
# the background start
# --------------------------------------------------------------------------- #
def start_background(root: str, *, round_: int | None, key: str | None,
                     popen: Callable[..., Any] | None = None) -> tuple[str, str]:
    """Start ``nopekit model trace --from-round N`` detached, its output
    appended to `LOG_REL`. ``(state, detail)``: ``off`` (`BACKGROUND_ENV` is
    ``"0"``), ``running`` (a live process holds the trace lock), ``incomplete``
    (the last background run for this key stopped before it finished: it is
    never started again by itself — a person runs it in the foreground),
    ``started``, or ``failed`` with the one-line reason. Never raises.

    It runs in nopekit's own directory (`_package_parent`, already first on
    its ``PYTHONPATH``), with the project named by ``-C``, absolute. What
    slipped through (the merge of phase 3b into phase 6, closed after it):
    it ran with the project as its cwd, and ``-m`` puts the cwd first on
    ``sys.path``, so a ``difflib.py`` in the project's root was imported in
    place of the library's at every round that started a trace — what the
    Stop hook's own launcher (``hooks/stop.py``) exists to stop. *Rejected:*
    ``python -I`` and ``-P`` (``hooks/stop.py`` gives the reasons: user
    site-packages, Python 3.11); a temporary directory (anyone may write a
    module there)."""
    if os.environ.get(BACKGROUND_ENV) == "0":
        return "off", ""
    pid = live_holder(root)
    if pid is not None:
        return "running", str(pid)
    found = scratch_state(root, key)
    if found.get("background") and (found.get("incomplete") or found.get("wrote_project")):
        return "incomplete", ""
    log = os.path.join(root, *LOG_REL.split("/"))
    try:
        util.ensure_dir(os.path.dirname(log))
        argv = [sys.executable, "-m", "nopekit", "model", "trace", "-C", os.path.abspath(root)]
        if round_ is not None:
            argv += ["--from-round", str(int(round_))]
        else:
            argv += ["--from-round", "0"]
        kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "close_fds": True,
                                  "env": worker_env(), "cwd": _package_parent()}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        else:                                                    # pragma: no cover - windows
            kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0)
                                       | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
        with open(log, "ab") as out:
            kwargs["stdout"] = out
            kwargs["stderr"] = out
            (popen or subprocess.Popen)(argv, **kwargs)
    except (OSError, ValueError) as exc:
        return "failed", " ".join(str(exc).split())
    return "started", LOG_REL


__all__ = [
    "SCHEMA", "HARNESS", "STEP", "MOVE_FLOOR", "SIGNIFICANT", "AFTER_FLOOR",
    "BUILD_TIMEOUT_FLOOR", "TIMEOUT_FACTOR", "SNAPSHOT_MAX_BYTES", "THREAD_ENV",
    "BACKGROUND_ENV", "TRACE_DIR", "SCRATCH_REL", "LOCK_REL", "LOG_REL", "SKIP",
    "FLIP_TOKENS", "HEADER", "AMBER_HEADER", "TRACE_KEYS", "AMBER_KEYS", "AMBER_STATES",
    "Nudge", "Order", "TraceFile", "AmberFile", "TraceRead", "Launched", "Ran", "Amber",
    "default_workers", "nudges", "plan_of", "apply", "instructions_of", "choice_digests",
    "keyed_on", "key_of", "current_keyed", "current_key", "anchors_for", "observe_values",
    "move_of", "moves_between", "magnitude", "render", "self_digest", "after_order",
    "trace_dir", "trace_path", "read_trace", "amber_paths", "read_amber", "trace_for",
    "trace_digest", "other_designs", "worker_main", "worker_env", "subprocess_launch",
    "in_process", "lock_path", "live_holder", "scratch_dir", "scratch_state",
    "snapshot_size", "amber_current", "amber_subjects", "run", "unconfirmed",
    "amber_states", "amber_now", "state_payload", "needed", "amber_words",
    "start_background",
]


if __name__ == "__main__":                                       # the worker's entry
    from nopekit import derivation as _canonical                 # one module object
    sys.exit(_canonical.worker_main(sys.argv[1:]))
