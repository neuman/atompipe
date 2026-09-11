# SPDX-License-Identifier: Apache-2.0
"""Known-bad projections for the tier-0 envelope gate.

No mesh library is involved: ``cad.bounding`` reads numbers, so its control changes
a number. One number, in the direction the gate cares about, leaving every other
value in the projection exactly as it was — that is what makes a failing selftest
evidence that the gate measures height rather than evidence that it dislikes this
dict.
"""
from __future__ import annotations

import json as _json
import os as _os

import dataclasses


# ---------------------------------------------------------------------------
# SEALED FIXTURES
#
# A control must fire in EVERY project, not just a friendly one. Layering the
# known-bad values over the host project's projection looks safe — the override
# wins on every key it states — but gates resolve synonym families and derived
# quantities, so a key the fixture never mentions can still arrive from the
# project and neutralise the control.
#
# It was observed live in a sibling pack: a fixture raised a hull's centre of
# gravity to make it unstable, the host project happened to state a waterplane
# inertia (an honest thing to state, better than the pack's own fallback), and
# the gate PASSED ITS OWN KNOWN-BAD FIXTURE. A control whose severity depends on
# the host project's numbers passes in some repositories and fails in others,
# which is the same as having none.
#
# So the base here is the pack's OWN baseline.json, and nothing is inherited.
# `tests/test_packs.py::ControlsAreSealed` runs every control against an empty
# projection to keep it that way.
# ---------------------------------------------------------------------------
_BASELINE_PATH = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                               "baseline.json")


def _baseline() -> dict:
    """The pack's own plausible-good projection, documentation keys stripped."""
    try:
        with open(_BASELINE_PATH, "r", encoding="utf-8") as handle:
            loaded = _json.load(handle)
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in loaded.items() if not k.startswith("_")}


def _with_params(ctx, **overrides):
    """A copy of the context whose projection carries the overrides."""
    params = _baseline()
    params.update(overrides)
    return dataclasses.replace(ctx, params=params)


def tall_part(ctx):
    """cad.bounding — the part grows past its Z envelope and nothing else changes.

    The height is taken from the context's own limit so the fixture stays bad
    whatever envelope the project declares: 1.15x the stated Z limit is comfortably
    over and still a plausible part rather than an absurd one. A fixture that
    hard-coded 500 mm would also fail, and would prove only that the gate rejects
    nonsense.
    """
    base = _baseline()
    limit = base.get("bbox_limit_mm")
    z_limit = float(limit[2]) if isinstance(limit, (list, tuple)) else float(limit or 0.0)
    bbox = list(base.get("bbox_mm") or [0.0, 0.0, 0.0])
    bbox[2] = round(z_limit * 1.15, 3)
    return _with_params(ctx, bbox_mm=bbox)
