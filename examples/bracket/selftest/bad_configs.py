# SPDX-License-Identifier: Apache-2.0
"""Known-bad fixtures for the bracket's gates.

Each function returns a GateContext whose params come from the model rebuilt with
ONE physically meaningful change, in the direction the gate under test cares about.

That constraint is the whole point. A fixture that is bad in some *other* way — a
corrupt file, a missing field, an empty mesh — proves the gate handles garbage, not
that it measures what it claims. `atompipe gate selftest` requires each gate to FAIL
on its own fixture; a gate that passes here is reported as broken.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_MODEL_DIR = str(Path(__file__).resolve().parent.parent / "model")
if _MODEL_DIR not in sys.path:
    sys.path.insert(0, _MODEL_DIR)

import bracket  # noqa: E402


def _with(ctx, **overrides):
    """Rebuild the model with overridden config and return a context carrying it."""
    base = ctx.params.get("config", {}) if getattr(ctx, "params", None) else {}
    fields = {f.name for f in dataclasses.fields(bracket.Config)}
    kw = {k: v for k, v in base.items() if k in fields}
    kw.update(overrides)
    return dataclasses.replace(ctx, params=bracket.build(bracket.Config(**kw)))


def quarter_thickness(ctx):
    """bracket.deflection — deflection goes as 1/t^3, so this is ~64x worse."""
    return _with(ctx, thickness=1.75)


def overloaded(ctx):
    """bracket.bending_stress — 20x load, geometry untouched."""
    return _with(ctx, load_n=300.0)


def thin_bearing(ctx):
    """bracket.bearing — one bolt in a thin plate with a large hole.

    Thickness moves here too, which also trips the deflection gate; that is fine and
    expected. What matters is that the bearing gate trips, and that the reason it
    trips is a collapsed bearing area rather than an unrelated defect.
    """
    return _with(ctx, n_bolts=1, hole_d=10.0, thickness=1.5, load_n=400.0)


def stubby(ctx):
    """bracket.model_validity — L/h of about 2.5, well inside where shear matters."""
    return _with(ctx, arm_length=20.0, thickness=8.0)


def oversized(ctx):
    """bracket.bed_fit — a 400 mm arm. Nothing wrong but the footprint."""
    return _with(ctx, arm_length=400.0)


def fat_nozzle(ctx):
    """bracket.min_wall — a 1.2 mm nozzle needs 3.6 mm of wall; the part has 7 mm...

    ...so push the section under it too. The change is still one idea: this part is
    being made by a process that cannot resolve it.
    """
    return _with(ctx, nozzle_d=1.2, thickness=3.0)
