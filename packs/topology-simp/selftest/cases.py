# SPDX-License-Identifier: Apache-2.0
"""Sealed controls: the pack's own part, loads and limits, never the host's."""
import dataclasses
import json
import os
from nopekit.models import Ledger

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def baseline(ctx):
    with open(os.path.join(ROOT, "selftest", "baseline.json"), encoding="utf-8") as f:
        p = json.load(f)
    return dataclasses.replace(ctx, root=ROOT, params=p, ledger=Ledger(), model=None, extra={})


def invalid_material(ctx):
    c = baseline(ctx)
    c.params["simp_case"]["young_mpa"] = -1000.0
    return c


def too_much_material(ctx):
    c = baseline(ctx)
    c.params["simp_case"]["mesh"] = "selftest/assets/wide.stl"
    return c


def too_soft(ctx):
    c = baseline(ctx)
    c.params["simp_case"]["young_mpa"] = 500.0
    return c


def overloaded(ctx):
    c = baseline(ctx)
    c.params["simp_case"]["loads"][0]["force_n"][2] = -10.0
    return c
