# SPDX-License-Identifier: Apache-2.0
"""nopekit.site — the ledger, rendered and addressable.

The site has two jobs and the second one is why it exists:

1. **Explain the thing** to someone who did not build it.
2. **Debug the thing** — spin it, pull it apart, and see the latest gate results
   *anchored to the geometry they are about*.

A readiness report says ``cad.clash: 1 interfering pair — back_left /
grip_lid_left, 0.41 mm^3``. That is a sentence somebody has to go and act on.
The same verdict carrying two :class:`~nopekit.models.Locator` records lights
both parts up in the viewer, and the reader is looking at the problem a second
later. Everything in this module exists to keep that link intact from the gate
that measured the overlap to the pixel that turns red.

Five rules are mechanical here, not advisory:

1. **The site never computes truth.** It renders the ledger. Nothing in this
   module runs a gate, re-derives a measurement, or decides whether a claim
   passes — :mod:`nopekit.claims` and :mod:`nopekit.report` do that, and
   :func:`state` calls *them* rather than reimplementing the judgement. A page
   that reached its own verdict would be a second opinion published next to the
   first, and a reader has no way to tell which one is the design's actual
   status. If a number on the page is wrong, the ledger is wrong (rule 1 of the
   method: generated files are outputs, not sources).

2. **:func:`build` does not run gates.** It renders what
   :func:`nopekit.verdicts.resolve` makes of the verdict cache — which never
   runs a gate either — and stamps each verdict with its own age. A build that
   helpfully re-ran the cheap gates and not the expensive ones would publish a
   mixed-age picture under one timestamp — the tier-0 numbers from ten seconds
   ago beside the tier-2 numbers from last Tuesday, with nothing on the page
   saying which is which. Age is per gate for the same reason, and so is
   staleness: each verdict is current or not by its OWN inputs.

   What slipped through (S-28): this module kept its own copy of the staleness
   rule and of ``_flat_params``, "byte-for-byte" the CLI's, synced by a
   comment, and judged the whole page by one hash of the projection against
   the last sweep's. A page handed no resolution now asks the resolver itself;
   there is no generous default that lists recorded entries as current, which
   would serve every cached PASS whether or not its control was ever
   demonstrated (invariant 7 by omission).

3. **A locator that cannot be drawn is REPORTED, never dropped.** A gate that
   thinks it is drawing and is not looks exactly like a gate that found nothing,
   and the failure mode is silent on both ends: the pack author sees a passing
   import and the reader sees an unannotated verdict. :func:`locator_problems`
   names every locator addressing a view that does not exist or a node the view
   does not declare, and the problem list rides in ``state.json`` as well as in
   the build summary, so it is visible to the page and to ``curl`` alike.

4. **It degrades all the way down.** A project with no geometry — a chemical
   process, a supply chain, a bracket with nothing exported yet — still gets
   claims, verdicts, evidence, provenance and the readiness sentence. 3D is one
   view kind among six, not the point. A viewgen with nothing to draw returns
   ``None`` and that is a normal outcome, not an error.

5. **Extensibility lives in the data, not in shipped code.** A pack emits views
   in kinds the renderer already knows. Nothing here loads pack JavaScript: the
   one artifact whose entire job is to be trusted when a gate says something is
   wrong must not depend on code nobody reviewed.

The structure deliberately mirrors :mod:`nopekit.gates` — :class:`ViewContext`
for :class:`~nopekit.gates.GateContext`, :class:`ViewRegistry` for
:class:`~nopekit.gates.Registry`, :func:`viewgen` for
:func:`~nopekit.gates.gate`, :func:`run_all_viewgens` for
:func:`~nopekit.gates.run_all`. A pack author who has written a gate should
have to learn nothing to write a viewgen. The one asymmetry is deliberate and
is called out at :meth:`ViewRegistry.register`: a viewgen declares no negative
control, because it settles nothing and there is no claim to falsify.

Time policy (contract rule 3): nothing here reads the clock. ``now`` arrives
from the CLI edge as an ISO string; a verdict's ``when`` is the resolver's — the
obs run that last hit or wrote its entry, else the entry's commit time — and an
*absent* ``now`` or ``when`` produces ``age_s: null`` rather than a zero. A zero
age renders as "just now", which is precisely the lie a staleness display exists
to prevent.

No build step, ever. ``site/`` is plain HTML, CSS and ES modules;
``nopekit site build`` writes JSON and ``nopekit site serve`` is
``python3 -m http.server``. A project site that needs npm is a project site that
rots, and the spine is standard-library only for exactly the same reason.
"""
from __future__ import annotations

import contextlib
import dataclasses
import fnmatch
import json
import os
import posixpath
import shutil
import sys
import tempfile
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping

from . import claims as claim_logic
from . import decisions as decision_logic
from . import graph as graph_logic
from . import modelio
from . import page as page_logic
from . import prose as prose_logic
from . import report as report_logic
from . import store
from . import vcs
from . import verdicts as verdict_logic
from .gates import availability as _gate_availability
from .models import Ledger, Locator, Verdict, View, ViewKind
from .util import (
    NopekitError,
    atomic_write_json,
    atomic_write_text,
    ensure_dir,
    sha256_text,
    write_json_if_changed,
)

__all__ = [
    "SITE_DIR",
    "DATA_DIR",
    "ASSETS_DIR",
    "VENDOR_DIR",
    "VIEWS_DIR",
    "STATE_NAME",
    "ViewContext",
    "ViewSpec",
    "ViewRegistry",
    "VIEW_REGISTRY",
    "viewgen",
    "active_view_registry",
    "use_view_registry",
    "availability",
    "run_viewgen",
    "run_all_viewgens",
    "derive_explode",
    "locator_problems",
    "scaffold",
    "build",
    "state",
    "resolution_digest",
    "resolution_moved",
    "clean_assets",
    "vendor_urls",
    # architecture phase 5: the front page, the clock file, the watcher
    "PAGE_NAME", "MAP_NAME", "BUILD_NAME", "CONTENT_DIR", "EVIDENCE_DIR", "SHELLS",
    "OUTLINE_MARKER", "OUTLINE_MARKER_RE", "AGED_SECONDS", "WATCH_DIRS",
    "scaffolded", "outline_of", "ensure_site_ignore", "prose_pool", "baked_pool", "ages",
    "write_build_json",
    "watch_snapshot", "refresh_renderer",
]


# --------------------------------------------------------------------------- #
# layout
# --------------------------------------------------------------------------- #
#: The site lives at ``<root>/site/``. Not hidden and not under ``.nopekit/``:
#: users edit ``index.html``, and a directory people are invited to hack on does
#: not belong in the tool's private state.
SITE_DIR = "site"

#: Generated JSON, relative to ``site/``. Hand-editing anything under here is
#: editing an output (method rule 1); ``build`` overwrites it without asking.
DATA_DIR = "data"

#: Generated binaries a viewgen wrote: GLB, PNG, SVG, CSV. Relative to ``site/``.
ASSETS_DIR = "assets"

#: Where ``nopekit site vendor`` puts three.js for offline use. Gitignored by
#: default — it is a third-party copy, it is large, and the site works without it.
VENDOR_DIR = "vendor"

#: Per-view payloads too big to inline, under ``site/data/views/<id>.json``.
VIEWS_DIR = posixpath.join(DATA_DIR, "views")

#: The technical record's document (`technical.html` reads it whole).
STATE_NAME = "state.json"

#: The front page's two documents (architecture phase 5, SPEC 28-30): the
#: outline around the map, and the map. Baked by `page`, tracked.
PAGE_NAME = "page.json"
MAP_NAME = "map.json"

#: The clock (SPEC 32): the build time, each verdict's age and the live flag.
#: Ignored by git through `site/.gitignore`, so a rebuild that judged nothing new
#: changes no tracked byte; the page works without it.
BUILD_NAME = "build.json"

#: The agent's prose and figures (SPEC 30), under ``site/``: tracked, stamped by
#: `nopekit site stamp`, and not a record.
CONTENT_DIR = "content"

#: Evidence the evaluators wrote, copied under ``site/`` so a published page can
#: link it (`page.evidence_plan`).
EVIDENCE_DIR = "assets/evidence"

#: The shells: the project's own files, written by `site init` (and
#: `technical.html` by `site build` when absent), never refreshed. PETGasus ships
#: its own `technical.html`, a renamed older shell with its own title: a refresh
#: would erase it. *Rejected:* refreshing `technical.html` as a renderer file.
SHELLS = ("index.html", "technical.html")

#: The outline marker the new shell carries (SPEC 28): `site build` warns when
#: `index.html` lacks it, or carries an older outline. A meta tag, so a page
#: written by hand can carry it too.
OUTLINE_MARKER = '<meta name="nopekit-outline" content="1">'
OUTLINE_MARKER_RE = r'<meta\s+name=["\']nopekit-outline["\']\s+content=["\'](\d+)["\']'

#: A verdict this old is *aged* on the page (`build.json`'s ``aged``), and an
#: oldest result past it beside one four times newer raises the mixed-age
#: banner. Moved from the template's format.js (SPEC 32: the browser computes no
#: status): a day, because a check run once a day is the slowest loop a designer
#: keeps up with, and a result older than that is from another working session.
#: *Rejected:* an hour (every lunch break would age the page); a week (a result
#: from last Tuesday would read as fresh as this morning's).
AGED_SECONDS = 24 * 3600

#: What `nopekit site serve --watch` polls (SPEC 33): the records, the project
#: file, the model and the project's evaluators, views and generators, the packs
#: copied in, the verdict cache, the trace, and the page's own text and
#: authored pins. `__pycache__` and `*.pyc` are left out.
WATCH_DIRS: tuple[str, ...] = (*store.RECORD_DIRS, ".nopekit/project.json", "model", "gates",
                               "selftest", "views", "generators", ".nopekit/packs",
                               ".nopekit/verdicts", ".nopekit/trace", "site/content",
                               "site/annotations.json", "site/explode.json")

#: The scaffold source, shipped inside the package (see pyproject package-data).
TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site_template")

#: A view payload larger than this is written to ``data/views/<id>.json`` instead
#: of being inlined in ``state.json``. The threshold exists because ``state.json``
#: is meant to be read whole — by the page in one fetch, and by an agent with
#: `curl` and no browser. One field-sample table of 40,000 rows inlined would
#: make the file that answers "what is the status of this project?" unreadable
#: for the 99% of readers who did not want the table.
VIEW_INLINE_MAX = 8192

#: Characters allowed in a view id. Ids become filenames (``data/views/<id>.json``)
#: and query fragments, and a locator addresses a view by this string, so a slash
#: or a space in one is a path escape and a broken anchor at the same time.
_ID_OK = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_."
)

#: The lines `ensure_site_ignore` appends to an older `site/.gitignore`
#: (architecture phase 5, SPEC 32): the clock file is an output that changes on
#: every build, so a tracked copy would dirty `git status` after every build.
_BUILD_IGNORE = (
    "# `site build` writes the build time and each result's age here. It changes on\n"
    "# every build, so git ignores it. The page works without it.\n"
    "data/build.json\n"
)

#: Written by :func:`scaffold` when the site has no ``.gitignore`` of its own.
#: ``data/`` and ``assets/`` are deliberately NOT ignored: they are the published
#: site, and a repo that ignores them publishes an empty page. ``vendor/`` is,
#: and from phase 5 ``data/build.json``.
_GITIGNORE = (
    "# `nopekit site vendor` writes three.js here. It is a third-party copy,\n"
    "# it is large, and the site loads the same version from a CDN without it —\n"
    "# so it is not ours to commit. Delete the vendor/ line (and only that line)\n"
    "# if you want an offline, self-contained archive of the project in git.\n"
    "vendor/\n"
    "\n" + _BUILD_IGNORE
)


def _noop_log(_message: str) -> None:
    """Default ``ViewContext.log``: swallow it.

    Same reasoning as ``gates._noop_log``: a viewgen must be runnable from a
    test or a pack's own ``__main__`` with no CLI attached, and defaulting to
    ``print`` would spray a ``--json`` CLI with prose.
    """


# --------------------------------------------------------------------------- #
# the context a viewgen is handed
# --------------------------------------------------------------------------- #
@dataclass
class ViewContext:
    """Everything a viewgen is allowed to see. One argument, mirroring GateContext.

    The field list is deliberately the same shape as
    :class:`~nopekit.gates.GateContext` — ``root``, ``ledger``, ``model``,
    ``params``, a place to write, ``log``, ``extra`` — because a pack author
    writing ``views/assembly.py`` has already written ``gates/clash.py`` and
    should not have to learn a second API to draw what the first one measured.
    Where gates get ``out_dir`` (evidence), viewgens get ``assets_dir``
    (published output); where gates get ``tier`` (how expensive a sweep this
    is), viewgens get nothing equivalent, because drawing is not tiered.

    Every field has a default so a test can build a context with the one thing
    it cares about.

    ``written`` is not part of the constructor: it is the record of what
    :meth:`write_asset` actually wrote, and :func:`build` reads it to decide
    what in ``site/assets/`` is still live. A viewgen cannot seed it, because a
    viewgen claiming to have written a file it did not write would make
    :func:`clean_assets` preserve a phantom.
    """

    root: str = ""
    ledger: Ledger = field(default_factory=Ledger)
    model: Any | None = None
    params: dict[str, Any] = field(default_factory=dict)
    assets_dir: str = ""
    log: Callable[[str], None] = _noop_log
    extra: dict[str, Any] = field(default_factory=dict)

    #: Site-relative paths this context has written, in order. Populated only by
    #: :meth:`write_asset`; see :func:`clean_assets` for why it must be complete.
    written: list[str] = field(default_factory=list, init=False)

    # -- parameter access -------------------------------------------------- #
    def param(self, name: str, default: Any = None) -> Any:
        """Read one projected parameter, or ``default``.

        Byte-for-byte the behaviour of ``GateContext.param``, dotted spelling
        included: half the callers are looking at ``model.json``, which is
        ``{"config": {...}, "derived": {...}}``, while ``params`` here is
        flattened. The two contexts must agree — a pack author who learned
        ``ctx.param("config.thickness")`` in a gate and got ``None`` in a
        viewgen would file it as a spine bug, and would be right.
        """
        if name in self.params:
            return self.params[name]
        tail = name.rsplit(".", 1)[-1]
        if tail in self.params:
            return self.params[tail]
        return default

    # -- assets ------------------------------------------------------------ #
    def _assets_root(self) -> str:
        """Absolute directory assets land in. Derived, so a test needs only ``root``."""
        if self.assets_dir:
            return self.assets_dir
        return os.path.join(self.root or os.curdir, SITE_DIR, ASSETS_DIR)

    def asset_path(self, name: str) -> str:
        """Filesystem path an asset called ``name`` would have. Creates nothing.

        For a viewgen that must hand a real path to an exporter which insists on
        opening the file itself (trimesh, matplotlib, a solver's writer). Pair it
        with :meth:`write_asset` for anything you can produce in memory, because
        only ``write_asset`` records the file — see there for why that matters.
        """
        return os.path.join(self._assets_root(), _safe_asset_name(name))

    def write_asset(self, name: str, data: bytes | str) -> str:
        """Write one asset and return its path **relative to ``site/``**.

        The return value is what goes in ``View.src``: ``"assets/assembly.glb"``.
        Relative because the page is served from ``site/`` and the whole
        directory is copied, published, zipped and moved around; an absolute
        path baked into ``state.json`` describes one machine's filesystem and
        breaks on every other one.

        **Never write into ``site/assets/`` by hand.** ``build`` must be able to
        delete stale assets — a renamed view otherwise leaves a 12 MB GLB behind
        that is indistinguishable from a current one — and it can only delete
        what it knows is no longer referenced, which means it can only trust a
        list of what *was* written. A viewgen that writes the file itself is
        invisible to that list: its output either survives forever or, worse,
        gets deleted the first time somebody makes the cleaner more aggressive.

        The write is atomic (temp file in the same directory, then
        ``os.replace``). A viewer handed a half-written GLB does not raise; it
        renders a broken box, which reads as a modelling problem rather than as
        a crashed export.
        """
        safe = _safe_asset_name(name)
        target = os.path.join(self._assets_root(), safe)
        ensure_dir(os.path.dirname(target))
        payload = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        # Written only when the bytes differ (architecture phase 5, SPEC 32): a
        # rebuild that drew the same picture changes no tracked byte and no
        # mtime. The path is recorded either way, or the cleaner would delete it.
        try:
            with open(target, "rb") as fh:
                same = fh.read() == payload
        except OSError:
            same = False
        if not same:
            _atomic_write_bytes(target, payload)

        site_relative = posixpath.join(ASSETS_DIR, safe)
        if site_relative not in self.written:
            self.written.append(site_relative)
        return site_relative


def _safe_asset_name(name: str) -> str:
    """Validate an asset name and return it normalised to a posix sub-path.

    Subdirectories are allowed (``"charts/sweep.csv"``); escaping ``assets/`` is
    not. Viewgens are third-party pack code — a pack is an ordinary directory
    anybody can drop in — so ``write_asset("../../.nopekit/ledger.json", ...)``
    is a real reach, and it is the ledger it would land on. The check is here
    rather than at the call site because both public entry points (
    :meth:`ViewContext.write_asset` and :meth:`ViewContext.asset_path`) need the
    same answer and a check that exists twice is a check that will exist once.
    """
    raw = str(name or "").strip().replace("\\", "/")
    if not raw:
        raise NopekitError(
            "write_asset() needs a name — an asset with no filename cannot be "
            "referenced by a view, cleaned, or published"
        )
    if raw.startswith("/") or os.path.isabs(raw) or (len(raw) > 1 and raw[1] == ":"):
        raise NopekitError(
            f"asset name {name!r} is an absolute path. Assets are written under "
            f"site/{ASSETS_DIR}/ and referenced relative to site/, so that the "
            f"whole directory can be copied and published somewhere else."
        )
    normalised = posixpath.normpath(raw)
    if normalised == ".." or normalised.startswith("../"):
        raise NopekitError(
            f"asset name {name!r} escapes site/{ASSETS_DIR}/. Everything a viewgen "
            f"writes has to live inside the assets directory: it is published as "
            f"part of the site, and `nopekit site build` deletes stale files in "
            f"there — which it can only do safely if nothing outside is reachable."
        )
    return normalised


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    """``util.atomic_write_text`` for bytes: temp file in the same dir, then replace.

    ``util`` has the text version only, and a GLB is not text — round-tripping
    binary through a str encoding to reuse it would corrupt the file quietly,
    which is the one failure mode worse than not being atomic at all. Same
    directory so ``os.replace`` stays on one filesystem and therefore stays
    atomic; ``/tmp`` is frequently a different mount and the rename would
    degrade to a copy.
    """
    directory = os.path.dirname(path) or os.curdir
    ensure_dir(directory)
    handle, temp = tempfile.mkstemp(dir=directory, prefix=".nopekit-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(temp)
        raise


# --------------------------------------------------------------------------- #
# the registration record
# --------------------------------------------------------------------------- #
@dataclass
class ViewSpec:
    """Registration record for one viewgen. The callable itself is not serialised.

    Mirrors :class:`~nopekit.models.GateSpec`, minus everything that only makes
    sense for something that can fail: no tier (drawing is not swept), no
    ``settles`` (a view settles nothing), no negative control (see
    :meth:`ViewRegistry.register`).

    ``gates`` is the list of gate ids whose locators are expected to address this
    view. It is a *declaration for the page* — "show me the gates that touch
    this view" without scanning every verdict — and not a constraint: a verdict
    from a gate that is not listed still draws, because a pack that grew a new
    gate must not silently stop rendering.
    """

    id: str
    kind: ViewKind = ViewKind.IMAGE
    title: str = ""
    description: str = ""
    requires_python: tuple = ()
    requires_tools: tuple = ()
    pack: str = ""
    order: int = 100
    gates: tuple = ()


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #
def _own_copy(spec: ViewSpec) -> ViewSpec:
    """A private copy the caller cannot edit afterwards.

    Same reasoning as ``gates._own_copy``: registration audits the record (id
    usable, kind known), and storing the caller's object would make that audit a
    formality — a pack could register ``id="assembly"`` and rewrite the id a line
    later, after which every locator aimed at the view it registered addresses
    nothing. The tuple fields are re-tupled for the same reason.
    """
    return dataclasses.replace(
        spec,
        kind=ViewKind(spec.kind),
        requires_python=tuple(spec.requires_python or ()),
        requires_tools=tuple(spec.requires_tools or ()),
        gates=tuple(spec.gates or ()),
    )


class ViewRegistry:
    """The viewgens known to this process, in declaration order.

    Order is preserved for the same reason :class:`~nopekit.gates.Registry`
    preserves it — it is the order the pack's author wrote them — but display
    order is ``ViewSpec.order`` and the page sorts on that. Registration order is
    the tie-break, so two views that both took the default 100 render in the
    order their pack declared rather than alphabetically.
    """

    def __init__(self) -> None:
        self._views: dict[str, tuple[ViewSpec, Callable[[ViewContext], Any]]] = {}

    # -- registration ------------------------------------------------------ #
    def register(
        self,
        spec: ViewSpec,
        fn: Callable[[ViewContext], Any],
        *,
        replace: bool = False,
    ) -> None:
        """Register one viewgen, or raise ``NopekitError`` saying what is wrong.

        **This registry deliberately does not demand a negative control**, and
        the asymmetry with :meth:`nopekit.gates.Registry.register` is worth
        stating because a reader who knows that code will look for it. A gate is
        refused without one because a validator nobody has watched fail is a
        logger, and a green tick from a logger launders assumption into proof. A
        viewgen proves nothing: it draws. There is no claim to falsify, no
        acceptance to invert, and a known-bad fixture for a picture would only
        demonstrate that the picture is different. The honesty machinery belongs
        on the thing that makes a claim, and putting a ceremonial version of it
        here would teach pack authors that the control is paperwork.

        What IS refused, and why each one produces a wrong page rather than an
        error:

        * an empty or unsafe id — the id is a filename (``data/views/<id>.json``),
          a URL fragment, and the string every ``Locator.view`` matches against
        * an unknown kind — the renderer knows six kinds and nothing else; a
          seventh renders as a blank panel with no message
        * a duplicate id from a different function — two views claiming one name
          means every locator aimed at that name lights up whichever one
          registered last, which is a confident highlight on the wrong geometry.
          That is worse than no highlight: it sends someone to inspect a part
          that is fine, and after the second time they stop trusting the overlay.

        Re-registering the *same* function under the same id is a no-op, because
        importing a pack's view module twice in one process is routine.
        """
        if not isinstance(spec, ViewSpec):       # a bug in the caller, not the user
            raise TypeError(f"register() needs a ViewSpec, got {type(spec).__name__}")
        if not callable(fn):
            raise TypeError(f"viewgen {spec.id!r} is not callable ({type(fn).__name__})")

        view_id = (spec.id or "").strip()
        _require_view_id(view_id)
        spec = dataclasses.replace(spec, id=view_id, kind=_coerce_kind(view_id, spec.kind))

        existing = self._views.get(view_id)
        if existing is not None and not replace:
            old_spec, old_fn = existing
            if old_fn is fn:
                self._views[view_id] = (_own_copy(spec), fn)      # idempotent re-import
                return
            where_old = old_spec.pack or getattr(old_fn, "__module__", "?")
            where_new = spec.pack or getattr(fn, "__module__", "?")
            raise NopekitError(
                f"view id {view_id!r} is already registered by {where_old} and "
                f"{where_new} wants it too. Two views cannot share an id: every "
                f"Locator addresses a view by this string, so the second one "
                f"silently steals the first one's highlights. Rename one."
            )

        self._views[view_id] = (_own_copy(spec), fn)

    def unregister(self, view_id: str) -> bool:
        """Drop a viewgen. Returns whether it was there. Mostly for tests."""
        return self._views.pop(view_id, None) is not None

    def clear(self) -> None:
        """Empty the registry. Tests and isolated pack validation use a scratch one."""
        self._views.clear()

    # -- lookup ------------------------------------------------------------ #
    def get(self, view_id: str) -> tuple[ViewSpec, Callable[[ViewContext], Any]] | None:
        """``(spec, fn)`` for one id, or None. Never raises on an unknown id."""
        return self._views.get(view_id)

    def specs(self) -> list[ViewSpec]:
        """Every spec, in registration order."""
        return [spec for spec, _ in self._views.values()]

    def ids(self) -> list[str]:
        """Every view id, in registration order."""
        return list(self._views)

    def pairs(self) -> list[tuple[ViewSpec, Callable[[ViewContext], Any]]]:
        """Every ``(spec, fn)``, in registration order."""
        return list(self._views.values())

    # -- dunders ----------------------------------------------------------- #
    def __len__(self) -> int:
        return len(self._views)

    def __contains__(self, view_id: object) -> bool:
        return view_id in self._views

    def __iter__(self):
        return iter(self._views.values())

    def __repr__(self) -> str:          # pragma: no cover - diagnostics only
        return f"ViewRegistry({len(self._views)} views: {', '.join(list(self._views)[:6])})"


def _coerce_kind(view_id: str, kind: Any) -> ViewKind:
    """``ViewKind`` or ``NopekitError`` naming the kinds the renderer knows.

    A bare ``ValueError: 'hologram' is not a valid ViewKind`` is a Python error
    about an enum; a pack author reading it learns nothing about what the site
    can draw. The refusal has to carry the vocabulary, because the whole point of
    the fixed kind list is that extensibility lives in the DATA — the answer is
    always "pick the kind that carries your payload", never "add a renderer".
    """
    try:
        return ViewKind(kind)
    except ValueError as exc:
        known = ", ".join(k.value for k in ViewKind)
        raise NopekitError(
            f"view {view_id!r} declares kind {kind!r}, which the site cannot render. "
            f"Known kinds: {known}. A pack gets visualisation for free by emitting "
            f"one of these; it does not get to ship its own renderer, because the "
            f"one artifact whose job is to be trusted cannot depend on code nobody "
            f"reviewed."
        ) from exc


def _require_view_id(view_id: str) -> None:
    """Refuse a view id that cannot be a filename, a fragment and a locator target.

    Checked at registration because every later use is somewhere it is too late
    to complain: ``data/views/../../x.json`` is a path escape at write time, and
    an id with a space in it is a locator that never matches at read time — and
    a locator that never matches is silent by construction.
    """
    if not view_id:
        raise NopekitError(
            "a view needs an id: it is the string every Locator addresses, the "
            "name of its payload file, and the anchor the page links to"
        )
    bad = sorted({ch for ch in view_id if ch not in _ID_OK})
    if bad:
        raise NopekitError(
            f"view id {view_id!r} contains {', '.join(repr(c) for c in bad)}. Use "
            f"letters, digits, '-', '_' and '.': the id becomes a filename under "
            f"site/{VIEWS_DIR}/ and a URL fragment, and a locator matches it as a "
            f"literal string."
        )


#: The process-wide default registry. Pack view modules decorate against this on
#: import; a loader may pass its own for isolated validation.
VIEW_REGISTRY = ViewRegistry()

#: Stack of registries that ``@viewgen`` targets when a module does not name one.
#: Empty means VIEW_REGISTRY. A stack, not a slot, for the same reason as in
#: ``gates``: validating one pack while another is loading is a real sequence.
_ACTIVE_VIEW_REGISTRIES: list[ViewRegistry] = []


def active_view_registry() -> ViewRegistry:
    """The registry ``@viewgen`` decorates into right now.

    A pack's view module cannot name the registry it belongs in — it is imported
    by a loader that chose one, and the module was written before that choice
    existed. So the choice is ambient for the duration of the import.
    """
    return _ACTIVE_VIEW_REGISTRIES[-1] if _ACTIVE_VIEW_REGISTRIES else VIEW_REGISTRY


@contextlib.contextmanager
def use_view_registry(registry: ViewRegistry):
    """Make ``registry`` the target of every ``@viewgen`` decorated inside the block.

    The same seam ``gates.use_registry`` provides, and it exists for the same
    measured failure: a loader that hands a private registry to an import and
    gets an empty one back, with the views in the global registry instead.
    Because a loader reports what it added by diffing the registry it was given,
    the symptom is an empty list rather than an error — a pack that looks like it
    ships no views at all. Silent under-reporting is the worst failure available
    here, so the seam exists rather than being left to convention.
    """
    _ACTIVE_VIEW_REGISTRIES.append(registry)
    try:
        yield registry
    finally:
        # Remove OUR entry, not the top one: a module that misbehaved and left
        # something on the stack would otherwise silently redirect every later
        # registration in the process.
        try:
            _ACTIVE_VIEW_REGISTRIES.remove(registry)
        except ValueError:                       # pragma: no cover - defensive
            pass


# --------------------------------------------------------------------------- #
# the decorator
# --------------------------------------------------------------------------- #
def viewgen(
    *,
    id: str,
    kind: ViewKind | str,
    title: str = "",
    description: str = "",
    requires_python: Iterable[str] = (),
    requires_tools: Iterable[str] = (),
    pack: str = "",
    order: int = 100,
    gates: Iterable[str] = (),
    registry: ViewRegistry | None = None,
) -> Callable[[Callable[[ViewContext], Any]], Callable[[ViewContext], Any]]:
    """Declare a viewgen: build its :class:`ViewSpec` and register it.

    Returns the function **unchanged** — no wrapper, no signature change —
    exactly as :func:`nopekit.gates.gate` does, so a viewgen stays an ordinary
    function of one argument and its own unit test exercises the thing that
    ships rather than the registry's normalisation of it::

        from pack.views.assembly import assembly
        view = assembly(ctx)        # no registry, no CLI

    The spec is attached as ``fn.view_spec`` so a loader walking a module's
    attributes can find it without consulting a registry.

    Three fields are derived rather than restated (method rule 2):

    * ``pack`` falls back to the defining module's ``PACK`` global, which is what
      a pack loader sets. Typing the pack name into twenty decorators is twenty
      chances to typo it, and a mistyped pack name orphans a view in the site's
      grouping with nothing reporting it.
    * ``title`` / ``description`` fall back to the docstring's first line / rest,
      so a viewgen whose docstring already says what it draws does not say it
      twice and let the two drift.

    ``requires_python`` / ``requires_tools`` are declared the way a gate declares
    them, and for the same reason: a viewgen whose exporter is not installed is
    reported as *unavailable*, with the missing module named, rather than
    vanishing. A view that is absent because trimesh is missing looks exactly
    like a view the project never had.

    Registration failures raise ``NopekitError`` at IMPORT time, which is the
    point — a pack with a duplicate view id fails to load rather than loading
    with one view quietly shadowing another.
    """

    def decorate(fn: Callable[[ViewContext], Any]) -> Callable[[ViewContext], Any]:
        doc = (fn.__doc__ or "").strip()
        doc_title, _, doc_rest = doc.partition("\n")

        module = sys.modules.get(getattr(fn, "__module__", "") or "")
        module_pack = getattr(module, "PACK", "") if module is not None else ""

        spec = ViewSpec(
            id=id,
            kind=_coerce_kind(id, kind),
            title=title or doc_title.strip(),
            description=description or doc_rest.strip(),
            requires_python=tuple(str(m) for m in (requires_python or ())),
            requires_tools=tuple(str(t) for t in (requires_tools or ())),
            pack=pack or (str(module_pack) if module_pack else ""),
            order=int(order),
            gates=tuple(str(g) for g in (gates or ())),
        )
        # Resolved at DECORATION time, not when `viewgen()` was called: the
        # ambient registry is whatever loader is importing this module right now.
        target = registry if registry is not None else active_view_registry()
        target.register(spec, fn)
        fn.view_spec = spec              # type: ignore[attr-defined]
        return fn

    return decorate


# --------------------------------------------------------------------------- #
# availability
# --------------------------------------------------------------------------- #
def availability(spec: ViewSpec) -> tuple[bool, str]:
    """Can this viewgen run here? ``(ok, reason)`` — the reason is user-facing.

    Delegates to :func:`nopekit.gates.availability`, which needs only
    ``requires_tools`` and ``requires_python`` and which :class:`ViewSpec`
    provides under the same names. That is deliberate rather than lazy: the
    question "is trimesh importable?" has exactly one right answer, and the
    gates implementation is the one that learned the hard cases — a parent
    package that raises on import (absent and broken are equally unusable, but
    the message must say which), and a solver binding whose "driver not
    installed" guard is a bare ``sys.exit()`` at module scope, which uncaught
    ends the whole command. A second copy here would be a second copy that has
    not learned any of that yet.
    """
    return _gate_availability(spec)      # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# running one viewgen
# --------------------------------------------------------------------------- #
#: Note prefixes :func:`run_viewgen` emits, so :func:`run_all_viewgens` can
#: classify an outcome without re-deriving it. The contract's return type is
#: ``(View | None, str)`` — a human-facing note — and three different reasons for
#: "no view" must stay distinguishable downstream: unavailable is a missing
#: dependency (install it), empty is nothing to draw (normal), error is a broken
#: viewgen (fix it). Classifying by sniffing free text at a distance is fragile,
#: so the prefixes are constants shared by the producer and the consumer.
_NOTE_UNAVAILABLE = "unavailable: "
_NOTE_ERROR = "error: "
_NOTE_EMPTY = "nothing to draw"


def _note_status(view: View | None, note: str) -> str:
    """``ok`` | ``empty`` | ``unavailable`` | ``error`` for one viewgen's outcome."""
    if view is not None:
        return "ok"
    if note.startswith(_NOTE_UNAVAILABLE):
        return "unavailable"
    if note.startswith(_NOTE_ERROR):
        return "error"
    return "empty"


def _stamp_view(view: View, spec: ViewSpec) -> tuple[View, str]:
    """Overwrite the identity fields of a view from its spec. Returns ``(view, note)``.

    Same rule as ``gates._stamp``, and it exists because of the same copy-paste:
    a viewgen written by duplicating the one next to it keeps the previous
    view's id in its ``View(id=...)`` literal. A view filed under the wrong id
    is worse than a missing one — it overwrites its neighbour in the id-keyed
    view list, and every locator aimed at either id now points at one arbitrary
    picture. The spec is the only authority on identity, so the spec wins.

    ``kind`` is forced too, and a disagreement is reported rather than
    reconciled: the registration is what the site's grouping and the pack's
    documentation were written against, and a viewgen that returns a different
    kind is a bug in one of the two places, not a preference.
    """
    note = ""
    if view.kind != spec.kind:
        note = (f"declared kind {spec.kind.value!r} but returned "
                f"{ViewKind(view.kind).value!r}; the declaration wins")
    return (
        dataclasses.replace(
            view,
            id=spec.id,
            kind=spec.kind,
            title=view.title or spec.title,
            description=view.description or spec.description,
            pack=view.pack or spec.pack,
            # The declaration wins unless the viewgen deliberately moved off
            # the default: display order is a property of where a pack wants its
            # view to sit, which is decided at registration, but a viewgen that
            # computes an order at run time (a sweep view that belongs next to
            # the gate it plots) has said something the spec could not know.
            order=view.order if view.order != 100 else int(spec.order),
            # Union, not replacement: the spec's declaration is what the pack
            # documented, the view's list is what the run actually found, and
            # dropping either makes "show me the gates that touch this view"
            # quietly incomplete.
            gates=sorted({*(view.gates or []), *(spec.gates or ())}),
        ),
        note,
    )


def run_viewgen(
    spec: ViewSpec,
    fn: Callable[[ViewContext], Any],
    ctx: ViewContext,
) -> tuple[View | None, str]:
    """Run one viewgen. Returns ``(view or None, note)``; never raises.

    Four outcomes, and keeping them four instead of two is the job:

    * **a view** — it ran and produced something to render (note usually empty)
    * **None, "nothing to draw"** — it ran and had nothing. A CAD viewgen in a
      project with no geometry is not a failure and must not be one: the site
      degrades all the way down to claims and verdicts, and a project that never
      exports a mesh is a normal project, not a broken one.
    * **None, "unavailable: ..."** — its exporter is not installed. Reported,
      never silent: a view missing because trimesh is absent looks identical to
      a view the project never had, and the second costs nobody an afternoon.
    * **None, "error: ..."** — it crashed. A crashed viewgen is a bug in the
      viewgen; it does not stop the build, because the other views and the whole
      claims/verdicts half of the page are still true and still worth publishing.

    ``SystemExit`` and ``GeneratorExit`` are caught alongside ``Exception`` for
    the reason ``gates.run_gate`` spells out at length: pack code that reaches
    ``sys.exit()`` — an exporter's import guard, a stray ``argparse`` call —
    unwinds past an ``except Exception`` handler and out of the command, which
    then exits having written nothing and reported nothing. ``KeyboardInterrupt``
    is deliberately still allowed through: Ctrl-C during a slow mesh export must
    stop the build.

    A viewgen returning something that is not a ``View`` and not ``None`` is an
    error, not a view. There is no coercion here (unlike ``gates._normalise``,
    which accepts four shapes) because there is no natural shorthand for a
    picture: a ``dict`` that looks like a view is a view someone forgot to
    construct, and guessing at it produces a panel that renders wrong rather
    than a message that says what to fix.
    """
    ok, reason = availability(spec)
    if not ok:
        return None, _NOTE_UNAVAILABLE + reason

    try:
        result = fn(ctx)
    except (SystemExit, GeneratorExit) as exc:    # BaseException: see docstring
        what = (f"viewgen called sys.exit({exc.code!r})"
                if isinstance(exc, SystemExit) else "viewgen raised GeneratorExit")
        return None, _NOTE_ERROR + f"{what} — a viewgen must return a View or None"
    except Exception as exc:                      # noqa: BLE001 - deliberate
        tail = traceback.format_exc().strip().splitlines()[-1]
        return None, _NOTE_ERROR + f"{type(exc).__name__}: {exc} ({tail})"

    if result is None:
        return None, _NOTE_EMPTY
    if not isinstance(result, View):
        return None, _NOTE_ERROR + (
            f"viewgen returned {type(result).__name__}; expected a View or None. "
            f"Returning None is the correct way to say there is nothing to draw."
        )

    view, note = _stamp_view(result, spec)
    return view, note


def _selected_views(registry: ViewRegistry, only: str | Iterable[str] | None) -> list[ViewSpec]:
    """Resolve ``only`` to a concrete, ordered spec list. Unmatched patterns raise.

    ``only`` accepts an exact id, a pack name, or an fnmatch pattern
    (``cad.*``) — the same vocabulary as ``nopekit check --only``, because a
    user who learned one should not have to learn the other. Matching nothing
    raises, exactly as it does there: a typo'd ``--only assmebly`` that quietly
    built zero views and reported a clean build is the same lie as a validator
    that exits 0. An empty registry is allowed through — there is nothing to
    typo against.
    """
    all_specs = registry.specs()
    if only is None:
        return all_specs

    patterns = [only] if isinstance(only, str) else [str(o) for o in only]
    patterns = [p.strip() for p in patterns if str(p).strip()]
    if not patterns:
        return all_specs

    chosen: set[str] = set()
    unmatched: list[str] = []
    for pattern in patterns:
        hits = [s for s in all_specs
                if s.id == pattern
                or (s.pack and s.pack == pattern)
                or fnmatch.fnmatchcase(s.id, pattern)]
        if not hits:
            unmatched.append(pattern)
        chosen.update(s.id for s in hits)

    if unmatched and all_specs:
        known = ", ".join(s.id for s in all_specs[:12])
        more = "" if len(all_specs) <= 12 else f" (+{len(all_specs) - 12} more)"
        raise NopekitError(
            f"no view matches {', '.join(repr(u) for u in unmatched)} — building zero "
            f"views and calling it a build is the failure this tool exists to prevent. "
            f"Known views: {known}{more}"
        )
    return [s for s in all_specs if s.id in chosen]


def run_all_viewgens(
    registry: ViewRegistry,
    ctx: ViewContext,
    *,
    only: str | Iterable[str] | None = None,
) -> tuple[list, list]:
    """Run every selected viewgen. Returns ``(views, notes)``.

    ``views`` are the ones that produced something, sorted by
    ``(spec.order, registration order)`` — display order, resolved once here so
    the page does not have to and so ``state.json`` reads top-to-bottom the way
    the site does.

    ``notes`` carries **one record per viewgen that ran**, including the ones
    that produced nothing::

        {"view": "assembly", "status": "unavailable", "pack": "cad",
         "note": "unavailable: requires python trimesh (not importable)"}

    Every viewgen gets a row, not just the failures, because "which views does
    this project have, and why is that one missing?" is a question the build
    summary has to be able to answer without the reader re-running anything.
    ``status`` is one of ``ok`` / ``empty`` / ``unavailable`` / ``error``.

    A viewgen that crashes does not stop the build: the rest of the site —
    every other view, and the entire claims-and-verdicts half of the page — is
    still true, and withholding a true report because one picture failed to draw
    helps nobody. The crash is in ``notes`` with its exception, and
    :func:`build` lifts it into the summary's warnings so it is not merely
    *available* but *said*.
    """
    selected = _selected_views(registry, only)
    order_index = {spec.id: i for i, spec in enumerate(registry.specs())}

    views: list[View] = []
    notes: list[dict[str, Any]] = []
    for spec in selected:
        entry = registry.get(spec.id)
        if entry is None:            # concurrent unregister; nothing else can do this
            raise NopekitError(f"view {spec.id!r} disappeared from the registry mid-build")
        live, fn = entry
        ctx.log(f"view {live.id}")
        view, note = run_viewgen(live, fn, ctx)
        notes.append({
            "view": live.id,
            "pack": live.pack,
            "kind": ViewKind(live.kind).value,
            "status": _note_status(view, note),
            "note": note,
        })
        if view is not None:
            views.append(view)

    views.sort(key=lambda v: (int(v.order), order_index.get(v.id, 0), v.id))
    return views, notes


# --------------------------------------------------------------------------- #
# explode, derived
# --------------------------------------------------------------------------- #
#: Clearance factor on the thickness extent. 1.15 rather than 1.0 so parts
#: actually separate instead of sitting face-to-face, where an exploded view
#: reads as an unexploded one with a suspicious seam.
_STEP_CLEARANCE = 1.15

#: Floor on the step, in the GLB's own units (mm for every CAD exporter the packs
#: use). A 0.8 mm sheet-metal stack derives a 0.92 mm step, which on screen is
#: indistinguishable from not exploding at all — the geometry is thin, but the
#: reader's eye is not.
_STEP_MIN = 14.0

#: Decimal places kept in the manifest. Offsets are display positions, not
#: measurements: six more digits would add nothing a viewer can show and would
#: churn the diff of a generated file on every rebuild.
_ROUND = 4

#: Separator between a mover name and a node's role within it. A double
#: underscore, not a single one, because single underscores are ordinary inside
#: part names — ``back_left`` is one part, ``grip_lid_left__screw_boss`` is a
#: feature of ``grip_lid_left`` — and a grouper that split on the first ``_``
#: would shatter every multi-word part into a mover of its own.
MOVER_SEPARATOR = "__"


def derive_explode(bounds: dict, *, overrides: dict | None = None) -> dict:
    """Derive an explode manifest from node bounding boxes in the GLB's own space.

    ``bounds`` is ``{node_name: (min_xyz, max_xyz)}``. Returns::

        {"axes": {"thick": 2, "height": 1, "width": 0},
         "extent": [...], "center": [...], "step": 18.4,
         "movers": {"lid": {"offset": [0, 0, 27.6], "nodes": [...], "rank": 2}}}

    Everything here is **derived, never asked for** (method rule 2), and the
    reason is specific rather than aesthetic:

    * **The thickness axis is the smallest global extent.** A stack is thin in
      the direction it stacks; that is what makes it a stack.
    * **Stack order is each mover's centroid along that axis, sorted.** A stack
      order is something the geometry already knows. Transcribing it into a
      hand-authored layer table is how it goes stale — the table is written once,
      a part moves to the other side of the board six revisions later, and the
      exploded view keeps showing the old order with total confidence. Nothing
      catches it, because nothing is comparing the table to the model.
    * **``step`` is ``max(thickness_extent × 1.15, 14)``** so parts clear each
      other at any scale, with a floor for geometry too thin to separate visibly.
    * **Movers left or right of centre fan outward on the widest axis**,
      proportionally to how far off centre they sit — a mover at the edge of the
      assembly fans a full step, one on the centreline does not move sideways at
      all. This is what makes a mirrored or two-handed assembly readable instead
      of collapsing both halves onto one column of parts. The magnitude is
      ``step`` again rather than a second tuned constant: the clearance that
      separates layers is the clearance that separates halves.

    Movers group by the node-name prefix before ``__`` (see
    :data:`MOVER_SEPARATOR`), so ``lid__boss_a`` and ``lid__boss_b`` travel with
    ``lid``. A node with no separator is its own mover. **Node names are an
    interface**: whatever a ``model3d`` viewgen names its nodes is what every
    gate in that domain must use in its locators, and that scheme belongs in the
    pack's ``PACK.md``.

    ``overrides`` merges **per mover**, so correcting one part does not mean
    transcribing the other twenty — which is the practical reason hand-authored
    manifests rot: the cost of fixing one offset is retyping the whole table, so
    nobody does it twice. Accepted in either shape::

        {"movers": {"lid": {"offset": [0, 0, 40]}}, "step": 22}
        {"lid": {"offset": [0, 0, 40]}}

    ``nodes`` cannot be overridden: node membership comes from the geometry, and
    an override that edits it is transcribing the thing this function exists to
    stop transcribing. An override naming a mover that does not exist is
    reported under ``stale_overrides`` rather than dropped — it means the part
    was renamed or deleted and a hand-edit outlived it.
    """
    boxes = {str(name): _box(name, box) for name, box in (bounds or {}).items()}

    if not boxes:
        # A model3d view with no nodes is a degenerate but legal input (an empty
        # assembly, a viewgen that exported only a ground plane). Returning a
        # manifest of zeros beats raising: the caller has already produced a GLB,
        # and refusing to describe it would turn an empty picture into a failed
        # build.
        manifest: dict[str, Any] = {
            "axes": {"thick": 2, "height": 1, "width": 0},
            "extent": [0.0, 0.0, 0.0],
            "center": [0.0, 0.0, 0.0],
            "step": _STEP_MIN,
            "movers": {},
        }
        return _apply_explode_overrides(manifest, overrides)

    lows = [min(box[0][i] for box in boxes.values()) for i in range(3)]
    highs = [max(box[1][i] for box in boxes.values()) for i in range(3)]
    extent = [highs[i] - lows[i] for i in range(3)]
    center = [(highs[i] + lows[i]) / 2.0 for i in range(3)]

    # Ascending extent, index as the tie-break so a perfect cube resolves the
    # same way on every machine. A manifest that depends on dict iteration order
    # is a manifest that differs between two runs of the same build, and the
    # diff of a generated file is the only thing telling a reviewer what moved.
    by_extent = sorted(range(3), key=lambda i: (extent[i], i))
    thick = by_extent[0]
    rest = by_extent[1:]
    width = max(rest, key=lambda i: (extent[i], -i))
    height = next(i for i in rest if i != width)

    groups: dict[str, list[str]] = {}
    for node in boxes:
        groups.setdefault(mover_name(node), []).append(node)

    centroids: dict[str, list[float]] = {}
    for mover, nodes in groups.items():
        # The centre of the mover's combined bounding box, not the mean of its
        # nodes' centres: a mover with one large body and nine tiny bosses would
        # otherwise be centroided onto the bosses, and it would sort into the
        # wrong layer. We have bounding boxes, not masses, so this is the
        # honest definition of "where this part is".
        lo = [min(boxes[n][0][i] for n in nodes) for i in range(3)]
        hi = [max(boxes[n][1][i] for n in nodes) for i in range(3)]
        centroids[mover] = [(hi[i] + lo[i]) / 2.0 for i in range(3)]

    step = max(extent[thick] * _STEP_CLEARANCE, _STEP_MIN)
    ordered = sorted(groups, key=lambda m: (centroids[m][thick], m))
    n = len(ordered)
    span = extent[width]

    movers: dict[str, Any] = {}
    for rank, mover in enumerate(ordered):
        offset = [0.0, 0.0, 0.0]
        # Centred on the assembly rather than counted up from the bottom, so an
        # exploded view stays inside the same camera frame as the assembled one.
        offset[thick] = (rank - (n - 1) / 2.0) * step
        if span > 0:
            fan = 2.0 * (centroids[mover][width] - center[width]) / span
            offset[width] += max(-1.0, min(1.0, fan)) * step
        movers[mover] = {
            "offset": [round(v, _ROUND) for v in offset],
            "nodes": sorted(groups[mover]),
            # Rank rides along so a viewer can stage the explode one layer at a
            # time without re-deriving the sort from the offsets it was given.
            "rank": rank,
        }

    manifest = {
        "axes": {"thick": thick, "height": height, "width": width},
        "extent": [round(v, _ROUND) for v in extent],
        "center": [round(v, _ROUND) for v in center],
        "step": round(step, _ROUND),
        "movers": movers,
    }
    return _apply_explode_overrides(manifest, overrides)


def mover_name(node: str) -> str:
    """The mover a node belongs to: its name before ``__``, or the whole name."""
    name = str(node)
    return name.split(MOVER_SEPARATOR, 1)[0] if MOVER_SEPARATOR in name else name


def _box(name: Any, box: Any) -> tuple[list[float], list[float]]:
    """Validate one ``(min_xyz, max_xyz)`` pair, naming the node when it is wrong."""
    try:
        low, high = box
        low = [float(v) for v in low]
        high = [float(v) for v in high]
    except (TypeError, ValueError) as exc:
        raise NopekitError(
            f"bounds for node {name!r} are not a (min_xyz, max_xyz) pair of three "
            f"numbers each: {box!r}"
        ) from exc
    if len(low) != 3 or len(high) != 3:
        raise NopekitError(
            f"bounds for node {name!r} need three coordinates per corner, got "
            f"{len(low)} and {len(high)}"
        )
    # Swapped corners are repaired rather than rejected: some exporters hand back
    # a box with a negative extent on a mirrored part, and a negative extent
    # would make that axis sort as the *smallest* one — quietly electing the
    # wrong thickness axis and exploding the whole assembly sideways.
    return ([min(a, b) for a, b in zip(low, high)],
            [max(a, b) for a, b in zip(low, high)])


def _apply_explode_overrides(manifest: dict, overrides: dict | None) -> dict:
    """Merge ``overrides`` into a derived manifest, per mover. See :func:`derive_explode`."""
    if not overrides:
        return manifest
    if not isinstance(overrides, dict):
        raise NopekitError(
            f"explode overrides must be a dict, got {type(overrides).__name__}"
        )

    # Either shape is accepted, and the rule is unambiguous: a "movers" key means
    # the manifest-shaped form, anything else is the movers map itself. Being
    # forgiving here costs three lines; being wrong costs a silently ignored
    # site/explode.json, which is the failure people debug for an hour.
    if "movers" in overrides:
        top = {k: v for k, v in overrides.items() if k != "movers"}
        per_mover = overrides.get("movers") or {}
    else:
        top = {}
        per_mover = overrides

    for key in ("step", "axes", "center", "extent"):
        if key in top:
            manifest[key] = top[key]

    stale: list[str] = []
    movers = manifest["movers"]
    for name, patch in (per_mover or {}).items():
        if name not in movers:
            stale.append(str(name))
            continue
        if not isinstance(patch, dict):
            raise NopekitError(
                f"explode override for mover {name!r} must be a dict of fields to "
                f"replace, got {type(patch).__name__}"
            )
        merged = dict(movers[name])
        for key, value in patch.items():
            if key == "nodes":
                # Node membership is geometry. An override that edits it is
                # transcribing exactly what this module derives, and it will be
                # the copy that goes stale.
                continue
            if key == "offset":
                value = _offset(name, value)
            merged[key] = value
        movers[name] = merged

    if stale:
        # Never silent: an override for a part that no longer exists means a
        # hand-edit has outlived its geometry, and the person who wrote it is
        # still looking at a viewer that ignores them.
        manifest["stale_overrides"] = sorted(stale)
    return manifest


def _offset(name: str, value: Any) -> list[float]:
    """Validate an overridden offset. A two-element offset breaks the viewer silently."""
    try:
        out = [float(v) for v in value]
    except (TypeError, ValueError) as exc:
        raise NopekitError(
            f"explode override for {name!r}: offset must be three numbers, got {value!r}"
        ) from exc
    if len(out) != 3:
        raise NopekitError(
            f"explode override for {name!r}: offset needs three components (x, y, z), "
            f"got {len(out)}"
        )
    return [round(v, _ROUND) for v in out]


# --------------------------------------------------------------------------- #
# locators: the debugging link, and its failure modes
# --------------------------------------------------------------------------- #
def _view_targets(view: View) -> tuple[set[str] | None, str]:
    """What this view declares as addressable, and what those things are called.

    ``None`` means the view publishes no namespace, so a target cannot be
    checked — an image with no hotspot list, a diagram whose element ids live
    inside its SVG. Unverifiable is NOT reported as a problem: a false "unknown
    node" on every locator would train readers to ignore the problem list, and
    then the real ones go past unread too.
    """
    kind = ViewKind(view.kind)
    meta = view.meta or {}
    data = view.data or {}

    if kind in (ViewKind.MODEL3D, ViewKind.FIELD):
        names = list(meta.get("nodes") or [])
        explode = meta.get("explode")
        if isinstance(explode, dict):
            # A locator may legitimately address a mover ("lid") as well as a
            # node ("lid__boss_a"): the mover is what the viewer isolates.
            for mover, record in (explode.get("movers") or {}).items():
                names.append(str(mover))
                names.extend(str(n) for n in (record or {}).get("nodes") or [])
        return (({str(n) for n in names}) or None), "node"

    if kind is ViewKind.IMAGE:
        spots = data.get("hotspots") or []
        ids = {str(h.get("id")) for h in spots if isinstance(h, dict) and h.get("id")}
        return (ids or None), "hotspot"

    if kind is ViewKind.CHART:
        series = data.get("series")
        if isinstance(series, dict):
            return ({str(k) for k in series} or None), "series"
        if isinstance(series, list):
            keys = {str(s.get("key") or s.get("name")) for s in series
                    if isinstance(s, dict) and (s.get("key") or s.get("name"))}
            return (keys or None), "series"
        return None, "series"

    if kind is ViewKind.TABLE:
        rows = data.get("rows") or []
        ids = {str(r.get("id")) for r in rows if isinstance(r, dict) and r.get("id")}
        return (ids or None), "row"

    elements = data.get("elements") or meta.get("elements") or []
    return ({str(e) for e in elements} or None), "element"


def locator_problems(views: Iterable[View], verdicts: Iterable[Verdict]) -> list[dict]:
    """Every locator that cannot be drawn, with the gate that emitted it.

    **A locator is never dropped for being unusable.** It stays in
    ``state.json`` and the problem is published beside it, because the two
    failure modes this catches are both invisible from the inside:

    * a locator naming a view that does not exist — the gate believes it is
      drawing, the page draws nothing, and *a gate that thinks it is drawing and
      is not looks exactly like a gate that found nothing*. The pack author sees
      a clean import; the reader sees an unannotated verdict.
    * a locator naming a node the view does not declare — usually the node
      naming scheme moved on one side of the interface. ``PACK.md`` publishes
      that scheme precisely because it is an interface between a viewgen and
      every gate in its domain, and interfaces drift.

    Returns one record per bad locator::

        {"gate": "cad.clash", "view": "assembly", "target": "back_left",
         "severity": "unknown-target",
         "problem": "view 'assembly' declares no node 'back_left'"}
    """
    by_id = {v.id: v for v in views}
    namespaces = {vid: _view_targets(view) for vid, view in by_id.items()}

    out: list[dict] = []
    for verdict in verdicts:
        for locator in (verdict.locators or []):
            if not isinstance(locator, Locator):
                locator = Locator.from_dict(locator)         # tolerate a raw dict
            view_id = (locator.view or "").strip()
            if not view_id:
                out.append({
                    "gate": verdict.gate, "view": "", "target": locator.target,
                    "severity": "missing-view",
                    "problem": "locator names no view, so nothing can be highlighted",
                })
                continue
            if view_id not in by_id:
                known = ", ".join(sorted(by_id)[:6]) or "(no views were built)"
                out.append({
                    "gate": verdict.gate, "view": view_id, "target": locator.target,
                    "severity": "missing-view",
                    "problem": f"names view {view_id!r}, which no view generates. "
                               f"Built views: {known}",
                })
                continue
            target = (locator.target or "").strip()
            if not target:
                continue            # the whole view; always addressable
            names, label = namespaces[view_id]
            if names is not None and target not in names:
                out.append({
                    "gate": verdict.gate, "view": view_id, "target": target,
                    "severity": "unknown-target",
                    "problem": f"view {view_id!r} declares no {label} {target!r}",
                })
    return out


# --------------------------------------------------------------------------- #
# the editor's launch entry
# --------------------------------------------------------------------------- #
#: Where an editor looks for "how do I run this project": VS Code's Run and Debug.
#: What slipped through: a groundspace built end to end had a site and no way to
#: open it short of knowing `nopekit site serve` existed; the person looking at it
#: in their editor found nothing to press. *Rejected:* `.claude/launch.json` (the
#: projects this was asked for keep theirs in `.vscode/`), and serving `site/` with
#: `python3 -m http.server` (it loses `site serve`'s no-store and `.js` MIME fixes,
#: which are the difference between a current page and a blank one).
LAUNCH_PATH = os.path.join(".vscode", "launch.json")

#: The line `nopekit site serve` prints once its socket is listening, and the
#: pattern the launch entry waits for. Kept beside each other so one cannot move
#: without the other: `tests/test_launch.py` runs the real server and matches its
#: first line with this pattern.
SERVE_READY_LINE = "serving {served} at {url}"
SERVE_READY_RE = r"serving \S+ at (https?://\S+)"


def launch_config(name: str, *, src_root: str | None = None) -> dict:
    """The `.vscode/launch.json` a groundspace ships: build the site, serve it on a
    free port, and let the editor open the browser when the server says it is up.

    Shaped after VS Code's `node-terminal` launch with a `serverReadyAction`, because
    that runs any shell command with no extension and opens the browser on the URL
    the server printed. Each choice, and what it is for:

    * `site build` first, `;` not `&&`: the page should show the ledger as it is
      now, and a model that does not build should still open on the last page that
      did (the page says how old its data is).
    * `-p 0`: another groundspace's site may already hold 8000; the bound port is
      what the server prints and what the pattern captures.
    * `--no-browser`: the editor opens it; two windows otherwise.
    * the command finds `nopekit` on PATH, else runs it as a module from
      `src_root` (the nopekit this file was written by), so the entry works for an
      installed nopekit and for one run from a checkout. The fallback path is
      machine-specific; `nopekit site init` rewrites nothing, so delete the file
      and run `nopekit site build` to regenerate it on another machine.
    """
    a = "$A"
    find = ('command -v nopekit >/dev/null 2>&1 && A=nopekit || A="python3 -m nopekit"; ')
    command = f"{find}{a} site build; {a} site serve -p 0 --no-browser"
    env = {"NO_COLOR": "1"}
    if src_root:
        env["PYTHONPATH"] = src_root

    def one(browser: str, action: str) -> dict:
        return {
            "name": f"{name} site — {browser}",
            "type": "node-terminal",
            "request": "launch",
            "command": command,
            "cwd": "${workspaceFolder}",
            "env": dict(env),
            "serverReadyAction": {
                "pattern": SERVE_READY_RE,
                "uriFormat": "%s",
                "action": action,
                "webRoot": "${workspaceFolder}/" + SITE_DIR,
                "killOnServerStop": True,
            },
        }

    return {"version": "0.2.0",
            "configurations": [one("Chrome", "debugWithChrome"), one("Edge", "debugWithEdge")]}


def ensure_launch(root: str, name: str) -> str | None:
    """Write `<root>/.vscode/launch.json` when there is none. Returns the path
    written (relative), or None when a file was already there.

    Never edits an existing one: it is the person's (often JSON with comments, which
    this cannot round-trip), and a launch entry silently rewritten is the editor's
    version of a hand-edited generated file.
    """
    path = os.path.join(root, LAUNCH_PATH)
    if os.path.exists(path):
        return None
    src_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ensure_dir(os.path.dirname(path))
    atomic_write_text(path, json.dumps(launch_config(name, src_root=src_root),
                                       indent=2, ensure_ascii=False) + "\n")
    return LAUNCH_PATH.replace(os.sep, "/")


# --------------------------------------------------------------------------- #
# scaffolding
# --------------------------------------------------------------------------- #
def scaffold(root: str, *, force: bool = False) -> list:
    """Copy the site template into ``<root>/site/``. Returns the paths written.

    **Refuses to overwrite an existing ``site/index.html`` unless ``force``.**
    That file is the shell, and the contract says it plainly: *hackable, yours,
    never regenerated after init*. Someone who has spent an afternoon on their
    project's page must not lose it to a command they ran to get the new
    renderer, and a scaffold that silently rewrote it would be the same class of
    mistake as hand-editing a generated file — in the opposite direction.

    Everything else in the template (``app.js``, ``style.css``, and anything a
    later template adds) IS refreshed. Those are the renderer: they are ours,
    they get fixes, and a project that could never receive one would be stuck
    with the bugs of the day it was created. ``force`` replaces the shell too.

    ``data/`` and ``assets/`` are created empty so a freshly scaffolded site
    serves without a build, and ``.gitignore`` is written only when absent —
    ignoring ``vendor/`` and deliberately not ignoring the generated JSON, which
    IS the published site.
    """
    site = os.path.join(root, SITE_DIR)
    index = os.path.join(site, "index.html")
    if os.path.exists(index) and not force:
        raise NopekitError(
            f"{posixpath.join(SITE_DIR, 'index.html')} already exists and it is "
            f"yours — the shell is meant to be edited and is never regenerated. "
            f"Re-run with --force to replace it (your edits are not recoverable "
            f"afterwards), or delete the file first. `nopekit site build` "
            f"refreshes the data without touching it."
        )
    if not os.path.isdir(TEMPLATE_DIR):             # pragma: no cover - packaging
        raise NopekitError(
            f"the site template is missing from the installed package "
            f"({TEMPLATE_DIR}). This is a packaging fault, not a project fault: "
            f"reinstall nopekit."
        )

    written: list[str] = []
    for source, relative in _template_files():
        target = os.path.join(site, relative)
        # `technical.html` is a shell too (architecture phase 5): written when
        # absent, or with `force`; a project's own copy is never replaced.
        if relative in SHELLS and relative != "index.html" and os.path.exists(target) \
                and not force:
            continue
        ensure_dir(os.path.dirname(target))
        shutil.copyfile(source, target)
        written.append(posixpath.join(SITE_DIR, relative))

    for directory in (DATA_DIR, VIEWS_DIR, ASSETS_DIR, CONTENT_DIR):
        ensure_dir(os.path.join(site, directory.replace("/", os.sep)))

    gitignore = os.path.join(site, ".gitignore")
    if not os.path.exists(gitignore):
        atomic_write_text(gitignore, _GITIGNORE)
        written.append(posixpath.join(SITE_DIR, ".gitignore"))
    elif ensure_site_ignore(root):
        written.append(posixpath.join(SITE_DIR, ".gitignore"))

    return sorted(written)


def scaffolded(root: str) -> bool:
    """Whether ``root`` has a site: ``site/index.html`` is a file. The one
    predicate `round`, `status`, `doctor`, `site build` and `site serve` ask
    (architecture phase 5): a project that tracks only ``site/content/`` (the
    bracket) has text for a page and no page, so it has no site."""
    return os.path.isfile(os.path.join(root, SITE_DIR, "index.html"))


def outline_of(root: str) -> int | None:
    """The outline ``site/index.html`` carries (`OUTLINE_MARKER`), or None when
    it carries none (a shell older than the outline, or the project's own)."""
    import re
    try:
        with open(os.path.join(root, SITE_DIR, "index.html"), "r", encoding="utf-8",
                  errors="replace") as fh:
            found = re.search(OUTLINE_MARKER_RE, fh.read())
    except OSError:
        return None
    return int(found.group(1)) if found else None


def ensure_site_ignore(root: str) -> bool:
    """Append the clock file's ignore lines to ``site/.gitignore`` when no line
    equals ``data/build.json`` or ``/data/build.json``, creating the file with
    only those lines when there is none; True when it wrote. Every other byte
    stays as it was. What slipped through (review of phase 5): a missing
    ``site/.gitignore`` (the scaffolded one said to delete it for an offline
    archive) was left missing, so ``build.json``, which changes on every
    build, dirtied ``git status`` after every rebuild."""
    path = os.path.join(root, SITE_DIR, ".gitignore")
    try:
        with open(path, "r", encoding="utf-8", newline="") as fh:
            text = fh.read()
    except FileNotFoundError:
        if not os.path.isdir(os.path.join(root, SITE_DIR)):
            return False
        atomic_write_text(path, _BUILD_IGNORE)
        return True
    if any(line.strip() in ("data/build.json", "/data/build.json")
           for line in text.splitlines()):
        return False
    body = text if not text or text.endswith("\n") else text + "\n"
    atomic_write_text(path, body + ("\n" if body.strip() else "") + _BUILD_IGNORE)
    return True


def _evidence_plan(root: str, view: Any, resolution: Any, registry: Any) -> list:
    """`page.evidence_plan` with git's ignore rules: a path in the project that
    git ignores and does not track is never published (`vcs.ignored`)."""
    asked: dict[str, bool] = {}

    def ignored(relpath: str) -> bool:
        if relpath not in asked:
            found = vcs.ignored(root, [relpath])
            asked[relpath] = bool(found) and relpath in found
        return asked[relpath]

    return page_logic.evidence_plan(root, view, resolution, registry, ignored=ignored)


def _kept_json(site: str, keep: Iterable[str]) -> list:
    """The JSON documents among ``keep`` (paths under ``site/assets/``, as
    `clean_assets` takes them), read; one that does not parse is left out."""
    docs: list[Any] = []
    seen: set[str] = set()
    for entry in keep:
        text = str(entry).replace("\\", "/").strip()
        if not text.endswith(".json"):
            continue
        if not text.startswith(ASSETS_DIR + "/"):
            text = posixpath.join(ASSETS_DIR, text)
        text = posixpath.normpath(text)
        if text in seen:
            continue
        seen.add(text)
        try:
            with open(os.path.join(site, *text.split("/")), "r", encoding="utf-8") as fh:
                docs.append(json.load(fh))
        except (OSError, ValueError):
            continue
    return docs


def prose_pool(docs: Iterable[Any], assets: Iterable[Any] = ()) -> Any:
    """The number pool prose is matched against (`prose.number_pool`): the
    baked documents (``state.json`` with its view files, ``map.json``,
    ``page.json`` without its prose) and the asset JSON the page keeps."""
    return prose_logic.number_pool([*docs, *assets])


def baked_pool(root: str, map_doc: Mapping[str, Any], page_doc: Mapping[str, Any]) -> Any:
    """`prose_pool` over a built site as it is on disk, for a reader that
    checks a baked page's number marks (`page.status_problems`): its
    ``state.json``, its view files, ``map.json``, ``page.json`` with every
    prose piece left out, and every JSON file under ``assets/`` (after a
    build, exactly the ones it kept)."""
    site = os.path.join(root, SITE_DIR)
    docs: list[Any] = []
    try:
        with open(os.path.join(site, DATA_DIR, STATE_NAME), "r", encoding="utf-8") as fh:
            docs.append(json.load(fh))
    except (OSError, ValueError):
        pass
    views_dir = os.path.join(site, VIEWS_DIR.replace("/", os.sep))
    if os.path.isdir(views_dir):
        for name in sorted(os.listdir(views_dir)):
            if name.endswith(".json"):
                try:
                    with open(os.path.join(views_dir, name), "r", encoding="utf-8") as fh:
                        docs.append(json.load(fh))
                except (OSError, ValueError):
                    continue
    bare = json.loads(json.dumps(page_doc))
    for section in bare.get("sections") or ():
        section["prose"] = None
    bare["intro"] = None
    if isinstance(bare.get("next"), dict):
        bare["next"]["prose"] = None
    assets: list[str] = []
    for directory, _dirs, names in os.walk(os.path.join(site, ASSETS_DIR)):
        for name in sorted(names):
            if name.endswith(".json"):
                assets.append(os.path.relpath(os.path.join(directory, name), site)
                              .replace(os.sep, "/"))
    return prose_pool([*docs, map_doc, bare], _kept_json(site, assets))


def ages(resolution: Any, now: str) -> dict:
    """``{gate: {when, age_s, aged}}`` over the resolution's rows: ``when`` the
    resolver's (the obs run that last hit or wrote the entry, else its commit
    time), ``age_s`` `_age_seconds` (null when unknown, never 0), ``aged`` at
    `AGED_SECONDS` or more. For `build.json` only: the clock never reaches a
    tracked file."""
    out: dict[str, dict] = {}
    for gid in sorted((getattr(resolution, "rows", None) or {}), key=store._natural):
        row = resolution.rows[gid]
        when = str(getattr(row, "when", "") or "")
        age = _age_seconds(now, when)
        out[gid] = {"when": when, "age_s": age,
                    "aged": bool(age is not None and age >= AGED_SECONDS)}
    return out


def _mixed_age(verdicts: Mapping[str, dict]) -> dict:
    """The mixed-age banner's decision, baked (SPEC 32): shown when at least two
    results have an age, the oldest is aged, and it is more than four times the
    newest — the template's `mixedAgeBanner` rule, moved here."""
    found = [(gid, row["age_s"]) for gid, row in verdicts.items()
             if isinstance(row.get("age_s"), (int, float))]
    if len(found) < 2:
        return {"shown": False, "oldest_s": None, "newest_s": None, "gates": []}
    oldest = max(age for _gid, age in found)
    newest = min(age for _gid, age in found)
    shown = oldest >= AGED_SECONDS and oldest > newest * 4
    return {"shown": bool(shown), "oldest_s": oldest, "newest_s": newest,
            "gates": [gid for gid, age in found if age >= AGED_SECONDS] if shown else []}


def write_build_json(root: str, *, now: str, id: str, ok: bool = True, error: str = "",
                     live: bool = False, verdicts: Mapping[str, dict] | None = None,
                     mixed_age: Mapping[str, Any] | None = None) -> str:
    """Write ``site/data/build.json`` (ignored, SPEC 32-33): the build time, the
    live flag the page polls by, an ``id`` over the tracked baked bytes (the
    page reloads its data when it moves), ok and error, and each verdict's age.
    Returns its site path."""
    verdicts = dict(verdicts or {})
    doc = {"schema": 1, "built": now, "live": bool(live), "id": id, "ok": bool(ok),
           "error": str(error or ""), "verdicts": verdicts,
           "mixed_age": dict(mixed_age) if mixed_age is not None else _mixed_age(verdicts)}
    path = os.path.join(root, SITE_DIR, DATA_DIR, BUILD_NAME)
    ensure_dir(os.path.dirname(path))
    atomic_write_json(path, doc)
    return posixpath.join(SITE_DIR, DATA_DIR, BUILD_NAME)


def _baked_id(site: str) -> str:
    """The seal over ``{relpath: sha256}`` of the tracked baked files: the
    three documents and every ``data/views/*.json``."""
    import hashlib
    files: dict[str, str] = {}
    data = os.path.join(site, DATA_DIR)
    names = [STATE_NAME, MAP_NAME, PAGE_NAME]
    views = os.path.join(site, VIEWS_DIR.replace("/", os.sep))
    if os.path.isdir(views):
        names += [posixpath.join("views", n) for n in sorted(os.listdir(views))
                  if n.endswith(".json")]
    for name in names:
        path = os.path.join(data, *name.split("/"))
        try:
            with open(path, "rb") as fh:
                files[name] = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            continue
    return hashlib.sha256(("nopekit-build-v1\n" + json.dumps(files, sort_keys=True))
                          .encode("utf-8")).hexdigest()[:16]


def watch_snapshot(root: str) -> dict:
    """``{relpath: (size, mtime_ns)}`` over `WATCH_DIRS` — what `site serve
    --watch` compares between polls. ``__pycache__`` and ``*.pyc`` are left
    out; a missing path is simply absent."""
    out: dict[str, tuple] = {}
    for rel in WATCH_DIRS:
        path = os.path.join(root, *rel.split("/"))
        if os.path.isfile(path):
            st = os.stat(path)
            out[rel] = (st.st_size, st.st_mtime_ns)
            continue
        if not os.path.isdir(path):
            continue
        for directory, dirnames, filenames in os.walk(path):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for name in filenames:
                if name.endswith(".pyc"):
                    continue
                full = os.path.join(directory, name)
                try:
                    st = os.stat(full)
                except OSError:
                    continue
                out[os.path.relpath(full, root).replace(os.sep, "/")] = (st.st_size,
                                                                        st.st_mtime_ns)
    return out


def refresh_renderer(root: str) -> list:
    """Bring every renderer file under ``<root>/site/`` up to the installed
    template — everything but ``index.html``, the shell that is yours — and
    return the site paths it rewrote (``[]`` when each already matched).

    ``scaffold``'s docstring always said the renderer "IS refreshed"; nothing
    did it after ``site init``, which refuses while ``index.html`` exists. What
    slipped through (review of the P2.1 design): a page scaffolded before P2.1
    kept a ``format.js`` that read ``blocked`` as "its tooling is missing" in a
    missing tool's tone and took READY from ``readiness.ready`` — so once P2.1
    filed a crash under ``blocked``, that page read a crash exactly like a
    missing tool, and a project waiting for an article READY. ``site build`` is
    the command every such project runs, so it refreshes the renderer, byte for
    byte, before it writes the data the renderer reads. *Rejected:* a
    ``--refresh`` flag on ``site init`` (a step nobody knows to take); refusing
    the build when the renderer differs (the fix is mechanical, and the shell
    stays untouched either way)."""
    site = os.path.join(root, SITE_DIR)
    out: list[str] = []
    for source, relative in _template_files():
        if relative in SHELLS:
            continue
        target = os.path.join(site, *relative.split("/"))
        with open(source, "rb") as fh:
            want = fh.read()
        try:
            with open(target, "rb") as fh:
                if fh.read() == want:
                    continue
        except OSError:
            pass
        ensure_dir(os.path.dirname(target))
        _atomic_write_bytes(target, want)
        out.append(posixpath.join(SITE_DIR, relative))
    return sorted(out)


def _template_files() -> list[tuple[str, str]]:
    """``(absolute source, site-relative destination)`` for every template file.

    Walked rather than enumerated. A hardcoded list of three filenames is how a
    template's new file silently fails to ship — the same way a pack-root helper
    module once failed to make it into the wheel and every gate in that pack died
    on import. Dotfiles and ``__pycache__`` are skipped: the template is data,
    and Python never executes it from here.
    """
    out: list[tuple[str, str]] = []
    for directory, dirnames, filenames in os.walk(TEMPLATE_DIR):
        dirnames[:] = sorted(d for d in dirnames
                             if not d.startswith(".") and d != "__pycache__")
        for name in sorted(filenames):
            if name.startswith(".") or name.endswith(".pyc"):
                continue
            source = os.path.join(directory, name)
            relative = os.path.relpath(source, TEMPLATE_DIR).replace(os.sep, "/")
            out.append((source, relative))
    return out


# --------------------------------------------------------------------------- #
# building
# --------------------------------------------------------------------------- #
def build(
    root: str,
    ledger: Ledger,
    registry: Any,
    view_registry: ViewRegistry,
    *,
    model: Any | None = None,
    projection: dict | None = None,
    now: str = "",
    resolution: Any = None,
    params: Any = None,
    graph: Any = None,
    live: bool = False,
) -> dict:
    """Run the viewgens, write ``site/data/`` and ``site/assets/``, return a summary.

    **This function does not run gates**, and the omission is the point. It
    renders ``resolution`` — the caller's ``verdicts.resolve`` of the verdict
    cache. A build that re-ran the cheap gates on the way past would publish a
    page whose tier-0 numbers are ten seconds old and whose tier-2 numbers are
    a week old, and the reader has no way to tell them apart. If the results
    are stale, the fix is to run ``nopekit check``, and the page's job is to
    make the staleness impossible to miss, not to paper over it.

    Handed no ``resolution``, it resolves for itself (:func:`state`), against
    the projection it builds the views from: ``projection``, or — when the
    caller passed neither it nor ``model`` — the live model, loaded here. A
    model that does not load is not an error for the page; the resolver reads
    every verdict that read it as not current (S-21), and the build warns.
    ``params`` as for :func:`state`; handed none, they are the view of the model
    the build already holds. ``graph`` is the caller's `graph.build` over the
    same resolution (`round` hands its own, so the map and the round record
    share one graph); with none, `graph.of` builds it. ``live`` marks
    ``data/build.json`` live, so a page served by `site serve --watch` polls it.

    What it writes (architecture phase 5, SPEC 28-33), in this order: the
    renderer (`refresh_renderer`, never a shell), ``technical.html`` when absent,
    the clock's ignore line; the views and ``state.json`` (the technical
    record, clock-free); ``map.json`` and ``page.json`` (`page`), refused
    whole when `page.status_problems` finds a token the resolution does not
    say (invariant 14); the evidence copies; ``build.json`` last. Every tracked
    file is written only when its bytes differ, so a rebuild that judged
    nothing new changes no tracked byte and no mtime.

    ``registry`` is the *gate* registry; ``view_registry`` holds the viewgens.
    Both are parameters so a build can run against a scratch registry in a test.

    Returns a summary dict: what was written, what was removed, every viewgen's
    outcome, and — never merely available but actually said — ``warnings``,
    which is the list a CLI must print. The ledger is NOT written back: the site
    is an output and the records are the source (method rule 1).
    """
    site = os.path.join(root, SITE_DIR)
    if not scaffolded(root):
        raise NopekitError(
            f"no {SITE_DIR}/index.html at {os.path.abspath(root)}: run `nopekit site init` "
            f"first ({SITE_DIR}/{CONTENT_DIR}/ holds the page's text, not the page)")
    data_dir = os.path.join(site, DATA_DIR)
    views_dir = os.path.join(site, VIEWS_DIR.replace("/", os.sep))
    assets_dir = os.path.join(site, ASSETS_DIR)
    for directory in (data_dir, views_dir, assets_dir):
        ensure_dir(directory)
    refreshed = refresh_renderer(root)
    for source, relative in _template_files():
        if relative in SHELLS and relative != "index.html" \
                and not os.path.exists(os.path.join(site, relative)):
            shutil.copyfile(source, os.path.join(site, relative))
            refreshed.append(posixpath.join(SITE_DIR, relative))
    ignore_written = ensure_site_ignore(root)

    warnings: list[str] = []
    model_error = ""
    if projection is None and model is None:
        model, projection, model_error = _live_projection(root, ledger)
    if model_error:
        warnings.append(f"the model does not load, so no verdict that reads it is "
                        f"current: {model_error}")
    flat, conflicts = modelio.flat_params(projection)
    for conflict in conflicts:
        warnings.append(f"model and build() disagree on {conflict} — views read the "
                        f"config value")

    ctx = ViewContext(
        root=root,
        # A DEFENSIVE COPY, exactly as `cli._context` hands gates one. Viewgens
        # are third-party code, and handing over the live object would let a
        # viewgen append a Verdict or clear a claim, which `state()` would then
        # publish as the project's status a few lines later.
        ledger=Ledger.from_dict(ledger.to_dict()),
        model=model,
        params=flat,
        assets_dir=assets_dir,
        log=_noop_log,
        extra={},
    )

    generated, notes = run_all_viewgens(view_registry, ctx)
    for note in notes:
        if note["status"] in ("error", "unavailable"):
            warnings.append(f"view {note['view']}: {note['note']}")

    merged, conflicts_views = _merge_views(ledger.views, generated)
    warnings.extend(conflicts_views)

    # `state` reads views off the ledger, so the generated ones are grafted onto
    # an in-memory copy. A `replace`, not a dict round trip: a claim's results
    # and attributions live in memory only (P2.5a, `FORBIDDEN_KEYS`).
    for_state = dataclasses.replace(ledger, views=list(merged))
    if resolution is None:
        # Resolved against the LEDGER the caller handed in, not `for_state`:
        # the generated views are page furniture, never a gate input.
        resolution = _resolve(root, ledger, registry, projection=projection, model=model,
                              model_error=model_error, now=now)
    if params is None:
        params = _param_views(ledger, model, model_error, resolution, registry)
    view = verdict_logic.view(for_state, resolution)
    composed = _composed(view, registry, resolution)
    payload = state(root, for_state, registry, resolution=resolution, params=params,
                    judged=(view, composed))
    stale = bool(payload["meta"]["stale"])
    stale_reason = str(payload["meta"]["stale_reason"])

    # -- the front page (page.py): the map, the outline, the floor ---------- #
    tokens = graph_logic.tokens(view, resolution, registry, composed=composed)
    built = graph if graph is not None else graph_logic.of(
        root, view, resolution, registry, projection=projection, model=model, views=params,
        bases={})
    lay = page_logic.layout(view, built, projection=projection, params=params,
                            registry=registry, resolution=resolution)
    warnings.extend(lay.warnings)
    records = str(payload["meta"].get("records_digest") or "")
    judged = str(payload["meta"].get("resolution_digest") or "")
    plan = _evidence_plan(root, view, resolution, registry)
    for item in plan:
        if item.reason:
            warnings.append(f"evidence {item.path} of {item.gate} is not on the page: "
                            f"{item.reason}")
    map_doc = page_logic.bake_map(view, lay, built, tokens, composed, projection=projection,
                                  params=params, registry=registry, payload=payload,
                                  name=str(view.meta.name or ""), records_digest=records,
                                  resolution_digest=judged)
    page_doc = page_logic.bake_page(root, view, lay, built, tokens, composed,
                                    registry=registry, payload=payload, plan=plan,
                                    records_digest=records, resolution_digest=judged)
    problems_found = page_logic.status_problems(map_doc, page_doc, view, composed, tokens)
    if problems_found:
        raise NopekitError(
            f"the page would say more than the resolution, so nothing under "
            f"{SITE_DIR}/{DATA_DIR}/ was written: {problems_found[0]}. This is a defect in "
            f"nopekit; report it.")

    written: list[str] = []
    # Evidence first: a copy the page links must be on disk before the page is.
    copied = kept = 0
    keep_evidence: list[str] = []
    for item in plan:
        if item.action == "copy" and item.source and item.dest:
            target = os.path.join(site, *item.dest.split("/"))
            with open(item.source, "rb") as fh:
                payload_bytes = fh.read()
            try:
                with open(target, "rb") as fh:
                    same = fh.read() == payload_bytes
            except OSError:
                same = False
            if not same:
                _atomic_write_bytes(target, payload_bytes)
                written.append(posixpath.join(SITE_DIR, item.dest))
            copied += 1
            keep_evidence.append(item.dest)
        elif item.action == "keep" and item.dest:
            kept += 1
            keep_evidence.append(item.dest)
    not_shown = sum(1 for item in plan if item.action == "none")

    # Split the payloads too big to inline BEFORE writing state.json, so the file
    # the page fetches stays the size of a project summary rather than the size
    # of its largest table.
    kept_view_files: list[str] = []
    inline_views: list[Any] = []
    for row in payload["views"]:
        view_id = str(row.get("id") or "")
        inline = row.get("data") or {}
        if not inline:
            continue
        try:
            _require_view_id(view_id)
        except NopekitError as exc:
            warnings.append(f"view {view_id!r} kept inline: {exc}")
            continue
        if _rough_size(inline) <= VIEW_INLINE_MAX:
            continue
        relative = posixpath.join(VIEWS_DIR, f"{view_id}.json")
        if write_json_if_changed(os.path.join(site, relative.replace("/", os.sep)), inline):
            written.append(posixpath.join(SITE_DIR, relative))
        inline_views.append(inline)
        row["data"] = {}
        row["data_url"] = relative
        kept_view_files.append(f"{view_id}.json")

    # Keep every asset a view still points at, not merely the ones written this
    # run: a viewgen that skipped because its exporter is missing did not rewrite
    # its GLB, and deleting the previous one would turn a missing dependency into
    # a missing picture with no explanation. And every evidence copy the plan
    # links.
    keep = list(ctx.written) + keep_evidence
    for row in payload["views"]:
        src = str(row.get("src") or "")
        if src.startswith(ASSETS_DIR + "/"):
            keep.append(src)

    # The prose last among the bakes: its numbers are matched against every
    # number the other documents hold (SPEC 30), never against itself, and
    # only against assets this build keeps: a file the cleaner removes below
    # never vouches for a number. What slipped through (review of phase 5): the
    # pool read every JSON under assets/ before the cleaner ran, so an old
    # evidence copy matched a number once, and the next build, with nothing
    # new judged, marked it and rewrote page.json.
    pool = prose_pool([payload, *inline_views, map_doc, page_doc],
                      _kept_json(site, keep))
    prose_rows = page_logic.bake_prose(root, page_doc, lay, tokens, pool)
    for row in prose_rows:
        where = row["file"]
        if row["subject"] is None:
            warnings.extend(row["problems"])
            continue
        if row["stamp"] == "stale":
            warnings.append(f"{where}: written before the latest results; read it again, then "
                            f"`nopekit site stamp {row['subject']}`")
        elif row["stamp"] == "unstamped":
            warnings.append(f"{where}: not stamped; read it again, then "
                            f"`nopekit site stamp {row['subject']}`")
        for number in row["unmatched"][:8]:
            warnings.append(f"{where}: {number} matches no number the site bakes; the page "
                            f"marks it")
        if len(row["unmatched"]) > 8:
            warnings.append(f"{where}: and {len(row['unmatched']) - 8} more")
        for problem in row["register"] + row["problems"]:
            warnings.append(f"{where}: {problem}")

    map_doc["self"] = page_logic.seal(map_doc)
    page_doc["self"] = page_logic.seal(page_doc)
    for name, doc in ((STATE_NAME, payload), (MAP_NAME, map_doc), (PAGE_NAME, page_doc)):
        relative = posixpath.join(DATA_DIR, name)
        if write_json_if_changed(os.path.join(data_dir, name), doc):
            written.append(posixpath.join(SITE_DIR, relative))

    removed = [posixpath.join(SITE_DIR, p) for p in
               clean_assets(root, keep) + _clean_view_files(views_dir, kept_view_files)]

    problems = payload.get("locator_problems") or []
    for problem in problems:
        warnings.append(f"locator {problem['gate']} -> {problem['view']}"
                        f"{'/' + problem['target'] if problem['target'] else ''}: "
                        f"{problem['problem']}")

    marker = outline_of(root)
    if marker is None or marker < page_logic.OUTLINE:
        warnings.append(
            f"{SITE_DIR}/index.html predates the page outline (no nopekit-outline marker): "
            f"data/{PAGE_NAME} and data/{MAP_NAME} are written, and no page shows them. Keep "
            f"a copy of your index.html, then run `nopekit site init --force`; "
            f"technical.html keeps today's panels.")

    verdict_ages = ages(resolution, now)
    build_json = write_build_json(root, now=now, id=_baked_id(site), ok=True, live=live,
                                  verdicts=verdict_ages)
    stamps = [r["stamp"] for r in prose_rows if r["subject"] is not None]
    return {
        "root": root,
        "site": SITE_DIR,
        "state": posixpath.join(SITE_DIR, DATA_DIR, STATE_NAME),
        "page": posixpath.join(SITE_DIR, DATA_DIR, PAGE_NAME),
        "map_file": posixpath.join(SITE_DIR, DATA_DIR, MAP_NAME),
        "build_json": build_json,
        "built": now,
        "stale": stale,
        "stale_reason": stale_reason,
        "views": [{"id": v["id"], "kind": v["kind"], "src": v.get("src", ""),
                   "pack": v.get("pack", ""), "data_url": v.get("data_url", "")}
                  for v in payload["views"]],
        "viewgens": notes,
        "wrote": sorted(set(written + refreshed
                            + ([posixpath.join(SITE_DIR, ".gitignore")] if ignore_written
                               else [])
                            + [posixpath.join(SITE_DIR, p) for p in ctx.written])),
        "refreshed": refreshed,
        "removed": sorted(removed),
        "locator_problems": problems,
        "counts": {
            "views": len(payload["views"]),
            "claims": len(payload["claims"]),
            "verdicts": len(payload["verdicts"]),
            "locator_problems": len(problems),
            "assets": len(ctx.written),
        },
        "map": {"lines": len(lay.lines), "boards": len(lay.boards), "zones": len(lay.zones),
                "stations": len(lay.stations), "traced": built.trace is not None},
        "prose": [{"file": r["file"], "subject": r["subject"], "stamp": r["stamp"],
                   "unmatched": r["unmatched"], "register": r["register"],
                   "problems": r["problems"]} for r in prose_rows],
        "prose_counts": {"current": stamps.count("current"), "stale": stamps.count("stale"),
                         "unstamped": stamps.count("unstamped"),
                         "unmatched": sum(len(r["unmatched"]) for r in prose_rows)},
        "outline": {"marker": marker, "current": page_logic.OUTLINE},
        "evidence": {"copied": copied, "kept": kept, "missing": not_shown},
        "warnings": warnings,
    }


def _merge_views(declared: Iterable[View], generated: Iterable[View]) -> tuple[list, list]:
    """Ledger-declared views plus generated ones. Returns ``(views, warnings)``.

    A project can declare a view by hand in the ledger (a photograph of the
    prototype, a diagram somebody drew) as well as generate one. On an id
    collision the **generated** view wins, because it was produced from the model
    in this build and the declared one is a record of a previous opinion — but
    the collision is reported, since the losing view silently disappearing from
    the page is exactly the kind of absence nobody investigates.
    """
    by_id: dict[str, View] = {}
    warnings: list[str] = []
    # `run_all_viewgens` already resolved display order among the generated
    # views, registration order included; re-sorting on (order, id) here would
    # throw that tie-break away and re-alphabetise a pack's panels. So the
    # generated sequence is preserved as its own key and the declared views
    # follow it.
    rank: dict[str, int] = {}
    for view in generated or []:
        rank.setdefault(view.id, len(rank))
    for view in declared or []:
        by_id[view.id] = view
        rank.setdefault(view.id, len(rank) + 1000)
    for view in generated or []:
        if view.id in by_id:
            warnings.append(
                f"view {view.id!r} is declared in the ledger and generated by a "
                f"viewgen; the generated one is published"
            )
        by_id[view.id] = view
    ordered = sorted(by_id.values(), key=lambda v: (int(v.order), rank[v.id], v.id))
    return ordered, warnings


def _rough_size(payload: Any) -> int:
    """Cheap byte estimate for an inline view payload, for the split decision.

    ``repr`` rather than ``json.dumps``: this only has to be right to within a
    factor of two to decide which side of an 8 KB threshold something is on, and
    serialising every table twice to find out is a real cost on a project with
    forty of them.
    """
    return len(repr(payload))


def _clean_view_files(views_dir: str, keep: Iterable[str]) -> list[str]:
    """Delete ``data/views/*.json`` that no longer belongs to a view. Returns removals.

    Same reasoning as :func:`clean_assets`: a renamed view otherwise leaves its
    old payload on disk, where it is indistinguishable from a current one to
    anything that finds it by URL.
    """
    keeping = set(keep)
    removed: list[str] = []
    if not os.path.isdir(views_dir):
        return removed
    for name in sorted(os.listdir(views_dir)):
        path = os.path.join(views_dir, name)
        if not name.endswith(".json") or not os.path.isfile(path):
            continue
        if name in keeping:
            continue
        os.unlink(path)
        removed.append(posixpath.join(VIEWS_DIR, name))
    return removed


def clean_assets(root: str, keep: Iterable[str]) -> list:
    """Delete files under ``site/assets/`` that nothing references. Returns removals.

    ``keep`` is site-relative (``"assets/assembly.glb"``) or assets-relative
    (``"assembly.glb"``); both spellings are accepted because the first is what
    :meth:`ViewContext.write_asset` returns and the second is what a caller
    holding a bare filename has.

    Stale assets are not harmless. A renamed view leaves a 12 MB GLB behind that
    no page links to but every deploy copies, and — the part that actually costs
    something — a reader who reaches the old URL cannot tell the abandoned
    geometry from the current geometry. It renders perfectly. This is why
    ``write_asset`` exists at all: the cleaner can only be trusted to delete what
    it can prove is unreferenced, which means every asset has to arrive through a
    path that records it.

    Symlinks are removed as links and never followed, and directories are left
    alone except for pruning the empty ones. Nothing outside ``site/assets/`` is
    reachable from here by construction.
    """
    assets = os.path.join(root, SITE_DIR, ASSETS_DIR)
    if not os.path.isdir(assets):
        return []

    keeping: set[str] = set()
    for entry in keep or []:
        text = str(entry).replace("\\", "/").strip()
        if not text:
            continue
        if text.startswith(ASSETS_DIR + "/"):
            text = text[len(ASSETS_DIR) + 1:]
        keeping.add(posixpath.normpath(text))

    removed: list[str] = []
    # Bottom-up so a directory is visited after its children and can be pruned
    # in the same pass once it is empty.
    for directory, _dirnames, filenames in os.walk(assets, topdown=False):
        for name in sorted(filenames):
            path = os.path.join(directory, name)
            relative = os.path.relpath(path, assets).replace(os.sep, "/")
            if relative in keeping:
                continue
            os.unlink(path)
            removed.append(posixpath.join(ASSETS_DIR, relative))
        if directory != assets and not os.listdir(directory):
            os.rmdir(directory)
    return sorted(removed)


# --------------------------------------------------------------------------- #
# the state the page reads
# --------------------------------------------------------------------------- #
def state(
    root: str,
    ledger: Ledger,
    registry: Any,
    *,
    now: str = "",
    stale: bool | None = None,
    resolution: Any = None,
    params: Any = None,
    judged: tuple | None = None,
) -> dict:
    """Everything the page shows, in one inspectable JSON-safe dict.

    One file, read once, with nothing behind a second request: claims with
    resolved status, verdicts with their locators and ages, views, parameters
    with their rationale **and their rejected alternatives**, inputs with what
    was extracted from them, capability gaps, decisions, and the readiness
    sentence. That completeness is a feature for humans and a requirement for
    agents — ``curl .../data/state.json`` has to be enough to answer "what is the
    status of this project?" without a browser, and an agent that has to render
    HTML to read a verdict will not read the verdict.

    The judgements are **borrowed, not recomputed**. Which verdict each gate
    has, and whether it is current, is ``resolution``'s — the one resolver's
    (:func:`nopekit.verdicts.resolve`, R-5); claim statuses come from
    :mod:`nopekit.claims` given the resolver's ``stale_gates``, the headline
    sentence, the words and the coverage logic from :mod:`nopekit.report`. Those
    are private helpers in ``report`` and reaching for them is deliberate: a
    second implementation would give the page and the readiness document two
    opinions about the same ledger, and the page is the one more people will
    read. One of the two would eventually be wrong and nothing would be
    comparing them.

    ``resolution`` — the caller's, laid over ``ledger`` as its verdicts. With
    none, this resolves for itself, against the live model (loaded here when
    the ledger names one). *Rejected:* a default that lists the recorded entries
    with nothing stale — a caller that forgot the keyword would serve every
    cached PASS as current and never ask whether its control was demonstrated,
    and nothing on the page would say so (judges 2 and 3, SF PD-07).

    ``stale=True`` is the all-stale override: every claim that would pass reads
    STALE, every row not current. ``None`` and ``False`` are no override at all
    — a caller cannot declare the cache current; only the resolver says what is.

    ``now`` is kept for callers and ignored (architecture phase 5, SPEC 32): the
    document is clock-free, and the build time and each verdict's age go to
    ``data/build.json`` (`ages`, `write_build_json`). ``judged`` is the
    caller's ``(view, composed)``, so a build composes once.

    ``params`` — the caller's :func:`nopekit.modelio.param_view` (the CLI's,
    which also names what a broken model's text states). With none, the view of
    the live model, loaded here as for ``resolution``. Never ``ledger.params``:
    what slipped through (review, checkpoint 1.3) — this read the records, which
    from 1.3 hold only what the model cannot (a source, a grounding), so the
    migrated bracket's page showed no parameter at all, and a record holding
    only ``"source"`` was shown at value ``null`` and flagged undefended while
    ``doctor`` said every parameter carried a rationale.
    """
    if resolution is None or params is None:
        model, projection, model_error = _live_projection(root, ledger)
        if resolution is None:
            resolution = _resolve(root, ledger, registry, projection=projection,
                                  model=model, model_error=model_error, now=now)
        if params is None:
            params = _param_views(ledger, model, model_error, resolution, registry)
    everything = stale is True
    stale_gates = frozenset(resolution.stale_gates)
    # The page's ledger IS the resolution laid over the records: every judgement
    # below — statuses, coverage, PARTIAL, the headline, locator problems — reads
    # these verdicts, so none of them can disagree with the verdict rows.
    if judged is not None:
        view, composed = judged
    else:
        view = verdict_logic.view(ledger, resolution)
        composed = _composed(view, registry, resolution, everything)
    assets = page_logic.evidence_assets(_evidence_plan(root, view, resolution, registry))
    board_of = {cid: board.id for board in page_logic.boards_of(view)
                for cid in board.members}
    resolved = {cid: c.status for cid, c in composed.items()}
    summary = claim_logic.summarise(view, registry, stale=everything,
                                    stale_gates=stale_gates)
    cover = report_logic._coverage(view, registry)
    stale_reasons = {gid: (resolution.rows[gid].stale_reason if gid in resolution.rows
                           else "") for gid in stale_gates}

    from . import packs as pack_logic             # a reader's module: not at import
    found_proposers = (pack_logic.proposers(root)
                       if any(a.proposer for a in view.inputs) else {})
    input_bases = {a.id: pack_logic.proposer_basis(found_proposers, a.proposer)
                   for a in view.inputs if a.proposer}
    verdict_rows: list[dict] = []
    bases = report_logic._bases(registry)
    for verdict in view.verdicts:
        how = resolution.rows.get(verdict.gate)
        row = verdict.to_dict()
        # SPEC 38: where the evaluator's verdict logic comes from — the
        # registry's token, `undeclared` with no spec; shown, never a status.
        row["basis"] = bases.get(verdict.gate, "undeclared")
        if how is not None and how.cached and how.entry is not None:
            # A cached row shows its entry as recorded: the tier and pack the
            # gate RAN under. The resolver re-stamps a stale verdict with the
            # gate's current spec so coverage is judged against the claims the
            # gate covers now, and tier and pack come along with the claims. For
            # a Fresh entry the two always agree — both are in its code digest
            # (SPEC_FIELDS_IN_RHO) — so this moves nothing that counts; for a
            # stale one the page shows what was measured, beside why it is not
            # current. The claims stay the resolver's: the claim rows are judged
            # from them, and a verdict row naming other claims would be a second
            # opinion about coverage.
            recorded = how.entry.to_verdict()
            row["tier"], row["pack"] = int(recorded.tier), recorded.pack
        # How the resolver reached this verdict, said on the row it describes:
        # `cached` — it is a cache entry's, as recorded; `fresh` — and it is
        # current and counts; `stale_reason` — why it is not current (the
        # resolver's words: "config.bed_xy 220.0 -> 250.0", "control not
        # demonstrated at this version — run nopekit check"). A row the page
        # showed without them would look exactly as current as one that is.
        row["cached"] = bool(how is not None and how.cached)
        row["fresh"] = bool(how is not None and how.fresh) and not everything
        reason = how.stale_reason if how is not None else ""
        row["stale_reason"] = reason or (_MARKED_STALE if everything else "")
        # No clock here (architecture phase 5, SPEC 32): a verdict's `when` and
        # age go to `data/build.json` (`ages`), which git ignores, so a rebuild
        # that judged nothing new changes no tracked byte. What slipped through
        # before: every build rewrote `state.json` with new ages, so a check that
        # moved nothing still dirtied `git status` with the published page.
        # `ok` is the only predicate that means "it ran, it did not crash, and it
        # said yes". The page must never key a green tick off `passed`: a skipped
        # gate carries passed=False today, but a pack that sets passed=True next
        # to skipped=True would walk straight into the proof column.
        row["ok"] = verdict.ok
        # From `Verdict.outcome`, the one definition (R-5) — never the flags.
        # What slipped through (P2.1 design): this read `passed`, so a junk
        # truthy pass flag (`"yes"`) rendered `pass` on a row whose `ok` was
        # False, and a skipped-and-errored verdict rendered by its first flag.
        # An unqualified evaluator's row reads `unqualified` (P2.3-D17), never
        # `errored`: its verdict says `error` only so that it is never ok (R-2),
        # and the page painted a crash's word on something that crashed nothing.
        # A pass outside its operating context reads `outside-context` (P2.4-D22:
        # never counted `unqualified` — outside its context the evaluator is
        # still qualified; what does not hold is this pass's inputs). What
        # slipped through (review of P2.4): the CLI split it out and the page
        # painted `? UNQUALIFIED` beside the row text "outside operating context".
        row["status"] = ("outside-context" if claim_logic.outside_context(verdict) else
                         "unqualified" if getattr(verdict, "unqualified", "") else
                         {"error": "errored", "skipped": "skipped", "pass": "pass",
                          "fail": "fail"}[verdict.outcome])
        if getattr(verdict, "unqualified", ""):
            # The reason in the table's words (`report.HUMAN`), the token kept
            # for a machine reader; the page owns neither.
            # `text` is the row's sentence, lead and all (`report.unqualified_text`):
            # the page rendered `error`, R-2's fallback, which carries the token
            # (review of P2.3: `unqualified: qualification:not-yet|0` on every
            # bracket row of a clone without its cache).
            row["qualification"] = {
                "token": verdict.unqualified,
                "reason": report_logic.qualification_reason(verdict.unqualified),
                "text": report_logic.unqualified_text(verdict.unqualified)}
        # The margin (D-17, P2.4-D8): `claims.margin`, the one function, or
        # why there is none — on every row, never computed by the page (the
        # site renders the ledger; it never computes truth). `margin` null and
        # `margin_why` "" are the two that do not apply to each other.
        found = claim_logic.margin(verdict)
        row["margin"] = (None if found.fraction is None
                         else float(f"{found.fraction:.6g}"))
        row["margin_why"] = found.why
        row["views"] = sorted({(loc.view or "") for loc in (verdict.locators or [])
                               if (loc.view or "")})
        if not verdict.locators and not verdict.ok:
            # Said out loud rather than left as an empty list: an unlocatable
            # failure is a normal, honest outcome (a gate attaches a locator only
            # when it genuinely knows the position, because a confident highlight
            # on the wrong part is worse than none) and the page has to be able
            # to say so instead of looking like the overlay is broken.
            row["unanchored"] = True
        # The evidence as the page links it (`page.evidence_plan`): the published
        # copy's href, aligned with `evidence`, or "" where it is not on the page.
        row["evidence_assets"] = list(assets.get(verdict.gate) or
                                      ["" for _ in verdict.evidence or ()])
        verdict_rows.append(row)
    # Reading order, baked (SPEC 32): errored, fail, unqualified, outside its
    # context, skipped, pass, then the natural gate id — what the template's
    # VERDICT_ORDER and anchored-verdict ranking computed in the browser.
    for i, row in enumerate(sorted(verdict_rows, key=lambda r: (
            _ROW_RANK.get(str(r.get("status")), len(_ROW_RANK)),
            store._natural(str(r.get("gate")))))):
        row["order"] = i

    claim_rows: list[dict] = []
    needs = {spec.id: list(getattr(spec, "needs", None) or ())
             for spec in report_logic._specs(registry)}
    # In severity order (P2.1-D16): what slipped through (P2.0 F-5), the page
    # listed claims in record order, a skip above the crash it should sit under.
    for claim in report_logic.in_severity(view, composed):
        found = composed[claim.id]
        status = found.status
        unproven = report_logic._unproven_for(claim.id, cover, view)
        # The claim as every JSON channel shows it (`report.claim_json`, P2.5a-D20):
        # its record fields, its terminal and authority, and `physical_result`
        # carrying the judge's `counts` and `why` — the page keys its ok tone on
        # those, never on `passed` (critique 3 of the P2.5a design).
        row = report_logic.claim_json(claim, composed=found, exports=view.exports)
        row["status"] = str(status)
        # A recorded result's outcome as a word key (architecture phase 5,
        # template side): the page shows "pass" or "fail" from `outcome` and its
        # tone from `counts`, and reads no `passed` flag (SPEC 32: the template
        # scan refuses a `.passed` read, which a verdict row's flag and a
        # result's field share).
        if isinstance(row.get("physical_result"), dict):
            row["physical_result"]["outcome"] = (
                "pass" if row["physical_result"].get("passed") is True else "fail")
        # The words beside the kept enum (P2.1-D12): `key`, `word`, `cause`,
        # `reason`, `errored` — all `report.HUMAN`'s, so the page owns none.
        row.update(report_logic.status_view(found, view, claim,
                                            stale_reasons=stale_reasons))
        row["acceptance_render"] = claim.acceptance.render()
        row["gates"] = list(cover.get(claim.id) or claim.gates or [])
        row["verdicts"] = [v.gate for v in report_logic._claim_verdicts(view, claim)]
        row["evidence"] = sorted({e for v in report_logic._claim_verdicts(view, claim)
                                  for e in (v.evidence or [])})
        # Each covering gate that produced no pass that counts, with its reason
        # led by the fact (`unrun`, `errored: …`, `skipped: …`, `unqualified:
        # …`). PARTIAL went with P2.1 (GLOSSARY §3: under the composition no
        # Checked claim has one); `disagree` is what is left of it — a claim the
        # resolver calls `pass` while one of these exists — and the page paints
        # it loud, never as a lesser success (D18; review of the P2.1 design:
        # with `partial` gone and nothing in its place, a resolver regression
        # would have reached the page as a clean Checked chip).
        row["unproven"] = [{"gate": gid, "why": why} for gid, why in unproven]
        row["disagree"] = bool(report_logic._disagreement(view, claim, found, cover))
        # Which values are the claim's (P2.4, critique 10 of its design): the
        # evaluators whose value is compared with its acceptance condition, and
        # the passes whose value is not (another quantity or units) — computed
        # here by `claims`, so the page reads which value to show and never
        # chooses one. What slipped through: the page headlined the first
        # passing verdict, a guard's `8.57 L/h` on failing C1.
        row["compared"] = claim_logic.compared_gates(claim, view.verdicts)
        row["not_compared"] = [gid for gid, _why in claim_logic.not_compared(
            claim, view.verdicts, needs)]
        # The CLAIM's limit, which the page shows beside the claim's value — never
        # the verdict's: a compared pair is the one kind whose two limits can
        # part. What slipped through (review of P2.4): the summary drew the
        # headline verdict's own limit, so Failing C3 read `0.195 MPa / 15 MPa`
        # against a claim of `<= 0.1 MPa` — S-35's slip, on the page.
        row["limit_text"] = report_logic.limit_words(claim.acceptance)
        # The board the claim sits on (SPEC 17): the record's, or `other`.
        row["board"] = board_of.get(claim.id, page_logic.OTHER)
        claim_rows.append(row)

    # The one producer's statuses, with D18's disagreeing claims named
    # (`report.requirement_statuses`): the same `cover` as `row["disagree"]`.
    served = report_logic.requirement_statuses(view, composed, cover)
    views = [_chart_margins(v.to_dict()) for v in view.views]
    problems = locator_problems(view.views, view.verdicts)

    payload = {
        "meta": {
            **view.meta.to_dict(),
            "stale": everything or bool(stale_gates),
            "stale_reason": (_MARKED_STALE if everything
                             else _stale_reason(resolution, stale_gates)),
            # Which records this page was built from: `store.records_digest`,
            # over the record files' paths and bytes and `project.json`. The
            # page's own staleness (`cli._site_state`) compares it with the
            # records now. What it replaced compared mtimes with `ledger.json`,
            # which from 1.3 is a generated index every command rewrites — a page
            # of unchanged records read stale after any `status` (cli:H16). The
            # records are half of what the page renders; `resolution_digest`, set
            # below, is the other half.
            "records_digest": store.records_digest(root),
            # Stated on the artifact itself, because someone will find this file
            # on its own and wonder whether editing it does anything.
            "generated": "nopekit site build — an output of the ledger and its verdict "
                         "cache, not a source. If a number here is wrong, the ledger is "
                         "wrong.",
        },
        "readiness": {
            # markdown=False: the page styles its own emphasis, and `**not
            # ready**` rendered literally into HTML reads as a typo in the one
            # sentence that has to be believed.
            "verdict": report_logic._verdict_sentence(
                view, composed, registry, stale=everything, markdown=False),
            # Kept as they were (P2.1-D12): `counts` by enum value, `ready` —
            # nothing stops `check` — and `n_gaps`, gap records. What the page
            # reads from P2.1: `all_required_checked` for its READY headline
            # (GLOSSARY §4), and `tally` for its count strip, in HUMAN's words
            # with a crash counted apart (`N skipped (k errored)`).
            "counts": summary["by_status"],
            "by_key": summary["counts"],
            "errored": summary["errored"],
            "tally": _tally(composed),
            "kinds": summary["by_kind"],
            "ready": summary["ready"],
            "all_required_checked": summary["all_required_checked"],
            "unresolved": summary["unresolved_ids"],
            "blocking": summary["blocking_ids"],
            "n_claims": summary["n_claims"],
            "n_critical": summary["n_critical"],
            "n_gates": summary["n_gates"],
            "n_gaps": summary["n_gaps"],
            # P2.5b (S-60's field half): *ready* per milestone, the one
            # predicate's (`claims.unresolved` through `summarise`), as last
            # evaluated — the boundary's is `export <m> --dry-run`'s. The page
            # renders it in P5; until then it is here for an agent to read.
            "milestones": summary.get("milestones") or {},
        },
        # Every status's words, keyed by the enum value a claim row's `status`
        # holds: the page's chip labels and hints, so the site never owns a word
        # (D-16). An `errored` entry for a crash's Skipped.
        "words": report_logic.words_table(),
        # Each verdict row's outcome word, the same way: `HUMAN`'s.
        "outcome_words": report_logic.outcome_words(),
        # The rest of what the page says that is the ledger's word, not the
        # page's: `invalidated`, each gap record's state and each verdict chip's
        # title (`report.page_phrases`).
        "phrases": report_logic.page_phrases(),
        "claims": claim_rows,
        # SPEC decision 12: each requirement, its status from the one producer
        # over the compositions above, worded by `report.requirement_json`. The
        # page draws none until the map (phase 5); `resolution_digest` covers
        # them, so a moved requirement status marks the page behind.
        "requirements": [report_logic.requirement_json(r, served[r.id])
                         for r in view.requirements],
        "verdicts": verdict_rows,
        "views": views,
        "locator_problems": problems,
        "params": [_param_row(param, view) for param in params],
        # SPEC 38: an input's basis is its proposer's, looked up (`""` with no
        # proposer, `undeclared` when no discoverable pack declares it).
        "inputs": [{**artifact.to_dict(), "extracted": artifact.extracted,
                    "basis": input_bases.get(artifact.id, "")}
                   for artifact in view.inputs],
        "gaps": [need.to_dict() for need in report_logic._needs(view, registry)],
        "decisions": [decision.to_dict() for decision in view.decisions],
        # SPEC 14: every rejected alternative as tokens — its type, its return
        # condition's state now, its preference's standing — `summarise`'s.
        "rejections": summary["rejections"],
        # The rebuild prediction (P2.5a-D16): `claims.rebuild`, the one producer.
        "rebuild": [found.to_dict() for found in claim_logic.rebuild(view)],
    }
    # What this page judged, so `cli._site_state` can ask whether a rebuild now
    # would judge the same (`resolution_digest`). Set last, over the finished
    # document, and by this function, so the build's digest and the reader's are
    # one computation over one producer's output and cannot drift apart.
    payload["meta"]["resolution_digest"] = resolution_digest(payload)
    return payload


#: The rank `state` orders verdict rows by (SPEC 32): a crash first, louder
#: than a fail (invariant 2), then a fail, an unqualified evaluator, a pass
#: outside its context, a skip, a pass.
_ROW_RANK = {"errored": 0, "fail": 1, "unqualified": 2, "outside-context": 3, "skipped": 4,
             "pass": 5}


def _composed(view: Any, registry: Any, resolution: Any, everything: bool = False) -> dict:
    """The compositions `state` and the front page share — one
    `claims.compositions` call per build."""
    return claim_logic.compositions(view, registry=registry, stale=everything,
                                    stale_gates=frozenset(resolution.stale_gates))


def _chart_margins(row: dict) -> dict:
    """A chart view's current points with ``margin_text`` (SPEC 32): the
    distance from each to the view's own limit, in the site's words — what the
    template's ``marginText`` subtracted in the browser. Other views as they
    are."""
    if str(row.get("kind") or "") != "chart":
        return row
    data = row.get("data")
    if not isinstance(data, dict):
        return row
    meta = row.get("meta") or {}
    raw_limits = data.get("limit", data.get("limits", meta.get("limit")))
    limits = raw_limits if isinstance(raw_limits, list) else (
        [] if raw_limits is None else [raw_limits])
    limit = None
    for item in limits:
        if isinstance(item, dict):
            value, axis = item.get("value", item.get("limit")), item.get("axis")
            comparator = str(item.get("comparator") or "<=")
        else:
            value, axis, comparator = item, "y", "<="
        if axis != "x" and _finite(value):
            limit = (float(value), comparator)
            break
    key = next((k for k in ("current", "marker", "now") if k in data), None)
    if limit is None or key is None:
        return row
    y_axis = data.get("y") if isinstance(data.get("y"), dict) else {}
    units = str(y_axis.get("units") or meta.get("y_units") or "")
    said = report_logic.HUMAN["site"]["chart_margin"]

    def one(item: Any) -> Any:
        point = dict(item) if isinstance(item, dict) else {"value": item}
        y = point.get("y", point.get("value"))
        if not _finite(y):
            return item
        delta = float(y) - limit[0]
        inside = delta < 0 if limit[1].startswith("<") else delta > 0
        text = f"{page_logic._num(abs(delta))}{' ' + units if units else ''}"
        point["margin_text"] = said["inside" if inside else "past"].format(delta=text)
        return point

    current = data[key]
    data = dict(data)
    data[key] = [one(c) for c in current] if isinstance(current, list) else one(current)
    return {**row, "data": data}


def _finite(value: Any) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and value not in (float("inf"), float("-inf")))


# --------------------------------------------------------------------------- #
# what a page judged
# --------------------------------------------------------------------------- #
#: What ``resolution_digest`` leaves out of a ``state`` document: the two
#: digests, each verdict row's ``evidence_assets``, and the views with their
#: ``locator_problems``. (Until phase 5 it also left out the clock — the
#: build's ``built`` stamp and each row's ``when`` and ``age_s`` — which the
#: document no longer holds: they are in ``data/build.json``. Phase 3a's
#: ``judgement_digest`` is this function, renamed: "judgement" now names
#: nothing on the page, and the glossary's *judgment* is an expert's.) Everything else is judged, including keys a
#: later ``state`` adds: a new clock-like key makes pages read stale after every
#: check, which someone sees the same day; an unwatched judgement is the defect
#: this digest exists for (review, ``repro_site``). *Rejected:* an allow-list of
#: judged keys, which fails silent in exactly that direction; judging ``when``,
#: which a check that changed nothing moves (a cache hit is an obs run), so every
#: sweep would send the reader to rebuild a page whose every verdict still
#: stands (cli:H16's complaint, in a new place). The views are page furniture,
#: drawn by viewgens that a reader asking "is the page current?" never runs: a
#: model edit that moves no verdict leaves the judgement current and the drawing
#: old, and ``site build`` redraws it. Not a claim — no verdict rests on a view.
_UNJUDGED_META = frozenset({"records_digest", "resolution_digest"})
#: `evidence_assets` says where a copy is on the page, which moves with what is
#: on disk, never with the judgement.
_UNJUDGED_ROW = frozenset({"evidence_assets"})
_UNJUDGED_KEYS = frozenset({"views", "locator_problems"})


def _tally(composed: Any) -> list[dict]:
    """The page's count strip: `report.count_bits`, one item per status word
    present, Checked first then severity order, each `{key, status, n, errored,
    label}` — `label` the terminal count line's own bit (`7 skipped (6
    errored)`), so the strip and the line are one producer. What slipped through
    (review of the P2.1 design): the strip printed literal labels per enum
    value, so a crash counted under the skip with no `(k errored)`, and "with no
    gate" and "capability gap" stayed on the page after every other channel
    moved."""
    return report_logic.count_bits(composed)


def resolution_digest(payload: Any) -> str:
    """sha256 over what a ``state`` document judged: its claim statuses and
    PARTIAL markers, the readiness sentence and counts, every verdict row with
    how the resolver reached it (``cached``, ``fresh``, ``stale_reason``), the
    parameters with the gates that read them, the gaps and the records it shows
    — everything but ``_UNJUDGED_*``.

    Why it exists: a page renders the records AND the resolver's judgement of
    the verdict cache against the live model, and ``meta.records_digest`` sees
    only the first. A ``check`` that FAILed C1 moved no record, so ``site
    status``, ``status`` and ``doctor`` read a page showing C1 PASS as "current
    with the records" (review, ``repro_site``). Before checkpoint 1.3 the check
    rewrote ``ledger.json`` and the mtime rule caught it. *Rejected:* a
    fingerprint of the files the resolution read (``verdicts.watched_paths``) —
    a second opinion about whether the resolution moved, blind to what is not a
    watched file (``controls.json`` admitting a control, a remembered crash, a
    solver installed or removed); this asks the one resolver (R-5) and compares
    its answer. Never a judgement itself: the page computes nothing from it.
    """
    meta = {key: value for key, value in (payload.get("meta") or {}).items()
            if key not in _UNJUDGED_META}
    rows = [{key: value for key, value in dict(row).items() if key not in _UNJUDGED_ROW}
            for row in payload.get("verdicts") or ()]
    judged = {key: value for key, value in payload.items()
              if key not in _UNJUDGED_KEYS and key not in ("meta", "verdicts")}
    judged["meta"], judged["verdicts"] = meta, rows
    # allow_nan: a digest is not a file, and `atomic_write_json` already refuses
    # the page a NaN names (S-47); refusing here too would turn "is the page
    # current?" into a crash of `status`, the command run when something is wrong.
    text = json.dumps(judged, sort_keys=True, ensure_ascii=False, allow_nan=True,
                      separators=(",", ":"))
    return sha256_text("nopekit-resolution-v1\n" + text)


def resolution_moved(shown: Any, now: Any) -> list[str]:
    """What a page shows that a rebuild would not, as short facts: each claim
    whose status moved (``C1 pass -> fail``, ``C9 (none) -> pending`` for one
    the page lacks), else each verdict row whose outcome or measurement moved
    (``g.one pass 0.41 mm -> pass 0.29 mm``; ``… (stale)`` on a row that does
    not count), else each parameter whose value moved (``thickness 7 mm -> 8
    mm``) or, its value standing, the first other field that did (``thickness
    rationale``), in the documents' order. ``[]`` when none moved — the
    readiness, a stale reason's words: the caller then says only THAT it moved.
    ``shown`` is the page's ``state.json``, ``now`` a ``state`` document built
    now; both are read, never judged again.

    The parameter tier arrived with the parameter view (review, checkpoint
    1.3): the page's ``params`` are the model's values and rationales now, so a
    docstring edit moves what the page shows and no verdict, and a reason that
    named nothing sent the reader looking for a verdict that had not moved."""
    def claims_of(doc: Any) -> dict[str, str]:
        return {str(row.get("id")): str(row.get("status") or "")
                for row in (doc.get("claims") or ())}

    def row_of(row: Any) -> str:
        said = [str(row.get("status") or "")]
        measured = row.get("measured")
        if isinstance(measured, (int, float)) and not isinstance(measured, bool):
            said.append(f"{measured:g}" + (f" {row['units']}" if row.get("units") else ""))
        if row.get("stale_reason"):
            said.append("(stale)")
        return " ".join(said)

    def gates_of(doc: Any) -> dict[str, str]:
        return {str(row.get("gate")): row_of(row) for row in (doc.get("verdicts") or ())}

    moved: list[str] = []
    for before, after in ((claims_of(shown), claims_of(now)), (gates_of(shown), gates_of(now))):
        for key in [*after, *(k for k in before if k not in after)]:
            if before.get(key) != after.get(key):
                moved.append(f"{key} {before.get(key) or '(none)'} -> "
                             f"{after.get(key) or '(none)'}")
        if moved:
            return moved

    def params_of(doc: Any) -> dict[str, dict]:
        return {str(row.get("name")): dict(row) for row in (doc.get("params") or ())}

    def value_of(row: dict | None) -> str:
        if row is None:
            return "(none)"
        value = row.get("value")
        said = "(no value)" if value is None else f"{value:g}" if (
            isinstance(value, (int, float)) and not isinstance(value, bool)) else str(value)
        return said + (f" {row['units']}" if row.get("units") and value is not None else "")

    before, after = params_of(shown), params_of(now)
    for key in [*after, *(k for k in before if k not in after)]:
        old, new = before.get(key), after.get(key)
        if old == new:
            continue
        if old is None or new is None or old.get("value") != new.get("value"):
            moved.append(f"{key} {value_of(old)} -> {value_of(new)}")
        else:
            # In the row's own key order (``ParamView.to_dict``'s, then the
            # flags), so an emptied rationale reads as ``rationale``, not as the
            # ``defended`` flag it also moved.
            field = next(name for name in [*new, *(k for k in old if k not in new)]
                         if old.get(name) != new.get(name))
            moved.append(f"{key} {field}")
    return moved


def _param_views(ledger: Ledger, model: Any, model_error: str, resolution: Any,
                 registry: Any) -> list:
    """``modelio.param_view`` of ``model``, each view's ``gates`` read off the
    resolution's read sets for the gates ``registry`` registers (all of them
    with no registry) — what the page shows when its caller handed none."""
    registered = ({spec.id for spec in report_logic._specs(registry)}
                  if registry is not None else None)
    reads = {gate: paths for gate, paths in (getattr(resolution, "read_sets", None)
                                              or {}).items()
             if registered is None or gate in registered}
    return modelio.param_view(ledger, model, model_error=model_error, read_sets=reads)


def _param_row(param: Any, ledger: Ledger) -> dict:
    """One parameter as ``modelio.ParamView.to_dict`` spells it — the model's
    value where it lives, its rationale and losers from both homes, the gates
    that read it — and a flag for the provenance it lacks.

    ``defended`` is ``modelio.undefended_params``'s answer, the one ``doctor``,
    ``status`` and the report print: false for a number the model holds that no
    home defends, which the next agent will change; ``None`` where the model
    holds no number (``model_error`` says why, or the record outlived its field)
    — there is nothing to defend, and "undefended" would be a claim about text
    nobody read. The page shows the flag next to the number rather than in a
    list somewhere else.

    ``changed_in`` is derived from the decisions (``decisions.changed_in``, as
    ``why`` derives it) — the page's "last moved in". The record row it
    replaced carried the key, and the strict reader keeps it out of records.
    """
    row = param.to_dict()
    row["changed_in"] = decision_logic.changed_in(ledger, param.name)
    row["defended"] = (None if not param.home
                       else not modelio.undefended_params([param]))
    row["derived"] = bool(param.derived_from)
    return row


# --------------------------------------------------------------------------- #
# the resolution, and ages
# --------------------------------------------------------------------------- #
#: A row's (and ``meta``'s) stale reason under the caller's ``stale=True``.
#: Said as what it is — the caller's word, not the resolver's finding — so a
#: reader does not go looking for an input that moved. *Rejected:* the old
#: "supplied by the caller", which named who and not what; and an empty reason,
#: which leaves a not-current row looking exactly like a current one.
_MARKED_STALE = "marked stale by the caller"


def _live_projection(root: str, ledger: Ledger) -> tuple[Any, dict | None, str]:
    """``(model, projection, model_error)`` for the model the ledger names —
    ``(None, None, "")`` when it names none, which is a normal early state.

    Loaded here only when the caller handed the page neither a resolution nor a
    projection. *Rejected:* the projection recorded in ``.nopekit/model.json``,
    which this module used to fall back on — it is the model as the last
    command saw it, so a model edited since would resolve every entry against
    the old values and read current. A model that does not load returns its
    error instead, and the resolver reads every verdict that read it as not
    current (S-21): never raising here, because a page that cannot be built for
    a broken model hides the one fact the reader most needs.
    """
    entry = (ledger.meta.model_entry or "").strip()
    if not entry:
        return None, None, ""
    try:
        model = modelio.load_model(root, entry)
        return model, modelio.project(model), ""
    except NopekitError as exc:
        return None, None, str(exc)


def _resolve(root: str, ledger: Ledger, registry: Any, *, projection: dict | None = None,
             model: Any = None, model_error: str = "", now: str = "") -> Any:
    """What the page renders when its caller did not say: the ONE resolver's
    answer (R-5). ``projection``/``model`` as :func:`build` built them; with
    neither, the live model is loaded (:func:`_live_projection`)."""
    if projection is None and model is None and not model_error:
        model, projection, model_error = _live_projection(root, ledger)
    return verdict_logic.resolve(root, registry, projection, ledger,
                                 model_error=model_error, now=now, model=model)


def _stale_reason(resolution: Any, stale_gates: frozenset) -> str:
    """``meta.stale_reason``: the stale gates by name, each with the resolver's
    reason, in the resolution's order — at most ``verdicts.MAX_STALE_REASONS``,
    then ``(+n more)``, the cap ``status`` puts on one gate's reasons, so the
    banner stays a line. ``""`` when nothing is stale.

    What it replaced: ``model 3211… -> 9a0c…; inputs e3b0… -> 5f1d…`` — one pair
    of hashes for the whole project, which said THAT something moved and never
    which result it touched, and was the same sentence for a comment edit and a
    changed load case.
    """
    named = [(gid, resolution.rows[gid].stale_reason)
             for gid in resolution.rows if gid in stale_gates]
    named += [(gid, "") for gid in sorted(stale_gates - {gid for gid, _ in named})]
    shown = [f"{gid}: {why}" if why else gid
             for gid, why in named[:verdict_logic.MAX_STALE_REASONS]]
    more = len(named) - len(shown)
    return "; ".join(shown) + (f" (+{more} more)" if more > 0 else "")


def _parse_iso(text: str) -> datetime | None:
    """Parse an nopekit timestamp, or None. Never raises, never guesses.

    Tolerant of the ``Z`` suffix `utcnow_iso` writes and of the offset forms a
    human might paste in. An unparseable timestamp yields None, which becomes a
    null age — a wrong age is worse than an absent one, because the page renders
    it with the same confidence as a right one.
    """
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _age_seconds(now: str, when: str) -> float | None:
    """Seconds between ``when`` and ``now``, or None when either is unknown.

    Clamped at zero: a clock skew that produced a negative age would render as a
    result from the future, which reads as a bug in the page rather than a bug in
    the clock and sends the reader to the wrong place.
    """
    start, end = _parse_iso(when), _parse_iso(now)
    if start is None or end is None:
        return None
    if start.tzinfo is None or end.tzinfo is None:      # mixed naive/aware
        start, end = start.replace(tzinfo=None), end.replace(tzinfo=None)
    return round(max(0.0, (end - start).total_seconds()), 3)


# --------------------------------------------------------------------------- #
# vendoring
# --------------------------------------------------------------------------- #
#: Pinned exactly, never a range and never "latest". An unpinned CDN URL is a
#: build step somebody else controls: the page that rendered a verdict correctly
#: this morning can render it wrong this afternoon, with no commit in between and
#: nothing to bisect. The site is the artifact whose job is to be trusted when a
#: gate says something is wrong.
THREE_VERSION = "0.169.0"

#: jsdelivr's npm mirror, which serves the published package tree unmodified —
#: so the vendored copy and the CDN copy are the same files at the same relative
#: paths, and `nopekit site vendor` changes where the modules come from without
#: changing what they are.
_THREE_BASE = f"https://cdn.jsdelivr.net/npm/three@{THREE_VERSION}"


def vendor_urls() -> dict:
    """``{site-relative path: URL}`` for ``nopekit site vendor``. Offline three.js.

    The layout under ``vendor/`` **mirrors the package's own**, and that is not
    tidiness: ``jsm/loaders/GLTFLoader.js`` contains
    ``import { toTrianglesDrawMode } from '../utils/BufferGeometryUtils.js'``,
    so flattening the three files into one directory produces a vendored site
    that 404s on a relative import the CDN copy resolves fine. The breakage
    appears only offline, which is the one situation vendoring exists for and the
    one nobody tests before archiving a project.

    ``BufferGeometryUtils.js`` is in the list for the same reason — it is not
    imported by the page, it is imported by the loader, and a vendor step that
    copies only what the page names leaves a dangling dependency.

    The import map in ``index.html`` is what chooses between these files and the
    CDN; this function only says what to fetch and where to put it. The mapping
    the template declares is::

        "three"      -> vendor/three.module.js       (or the CDN build)
        "three/addons/" -> vendor/jsm/               (or the CDN examples/jsm/)

    so the bare specifier inside every addon resolves either way without
    rewriting a single file.
    """
    return {
        posixpath.join(VENDOR_DIR, "three.module.js"):
            f"{_THREE_BASE}/build/three.module.js",
        posixpath.join(VENDOR_DIR, "jsm/loaders/GLTFLoader.js"):
            f"{_THREE_BASE}/examples/jsm/loaders/GLTFLoader.js",
        posixpath.join(VENDOR_DIR, "jsm/controls/OrbitControls.js"):
            f"{_THREE_BASE}/examples/jsm/controls/OrbitControls.js",
        posixpath.join(VENDOR_DIR, "jsm/utils/BufferGeometryUtils.js"):
            f"{_THREE_BASE}/examples/jsm/utils/BufferGeometryUtils.js",
    }
