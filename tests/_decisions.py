# SPDX-License-Identifier: Apache-2.0
"""Fixtures for architecture phase 2 (SPEC 14, 22, 25, 38): decisions that keep
their losers, the person's channel for a preference, and proposers.

* :func:`bracket` — a migrated bracket copy: it holds ``decisions/print-in-petg.json``
  as ``nopekit decide`` wrote it, whose third rejection is preferred against by the
  invented Robin Okafor, recorded by no one.
* :func:`sealed` — an entry sealed and chained by THIS file's own copy of the
  preference seal form: a fixture sealed by the code under test changes shape with it.
* :func:`person` — the in-process stand-in for a person's own shell: stdin a
  terminal that types ``answer``, no agent marker, git's identity ``who``. Each
  half can be turned off, so the same context is the agent's shell or a pipe.
* :func:`main` — ``cli.main`` in process, its exit code and what it printed.
* :func:`fixture_pack` — a pack in a temp directory with one evaluator and one
  proposer, for ``NOPEKIT_PACK_PATH``.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from typing import Any, Iterator
from unittest import mock

import _projects

from nopekit import cli, util

#: The invented person the bracket's preferred_against rejection names.
PERSON = "Robin Okafor"
PERSON_WHO = "Robin Okafor <robin@example.invalid>"
#: Someone else, whose shell is not Robin's.
PAT_WHO = "Pat Other <pat@example.invalid>"
DECISION = "print-in-petg"
ALU = "a machined 6061 aluminium bracket"


def bracket(dest: str) -> str:
    """The committed bracket, migrated, at ``dest``."""
    return _projects.bracket_copy(dest, migrated=True)


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


def decision_path(root: str, did: str = DECISION) -> str:
    return os.path.join(root, "decisions", f"{did}.json")


def edit_decision(root: str, did: str = DECISION, **changes: Any) -> dict:
    """Edit ``decisions/<did>.json`` as a hand or an agent would; returns it."""
    data = read_json(decision_path(root, did))
    data.update(changes)
    write_json(decision_path(root, did), data)
    return data


def edit_rejection(root: str, index: int, did: str = DECISION, **changes: Any) -> dict:
    """Edit one rejection of ``decisions/<did>.json``; ``None`` deletes a key."""
    data = read_json(decision_path(root, did))
    item = data["rejected"][index]
    for key, value in changes.items():
        if value is None:
            item.pop(key, None)
        else:
            item[key] = value
    write_json(decision_path(root, did), data)
    return data


def sealed(entry: dict, stem: str, prev: str) -> dict:
    """``entry`` sealed and chained as one of ``preferences/<stem>.json``'s entries:
    the seal over the entry with the seal's schema, the record KIND, the file and
    the list (SPEC 14; the exports form with its own kind)."""
    body = {k: v for k, v in entry.items() if k not in ("prev", "digest")}
    body["prev"] = prev
    form = {"schema": 1, "kind": "preferences", "file": stem, "list": "preferences", **body}
    return {**body, "digest": util.seal(form)}


def chain(entries: list[dict], stem: str) -> list[dict]:
    """Each of ``entries`` sealed and linked to the one before."""
    out: list[dict] = []
    for entry in entries:
        out.append(sealed(entry, stem, out[-1]["digest"] if out else ""))
    return out


def write_preferences(root: str, stem: str, entries: list[dict]) -> str:
    path = os.path.join(root, "preferences", f"{stem}.json")
    write_json(path, {"preferences": entries})
    return path


def entry_for(root: str, *, did: str = DECISION, index: int = 2, who: str = PERSON_WHO,
              name: str = PERSON, channel: str = "interactive",
              when: str = "2026-10-14T16:00:00Z") -> dict:
    """The entry ``prefer`` would record for rejection ``index`` as the decision
    reads now — its digest from the spine's own binding (`claims.rejection_digest`)."""
    from nopekit import claims, store
    ledger = store.load(root)
    decision = next(d for d in ledger.decisions if d.id == did)
    item = decision.rejected[index]
    return {"decision": did, "value": item.value, "name": name,
            "rejection_digest": claims.rejection_digest(decision, item),
            "who": who, "when": when, "channel": channel}


class _Terminal(io.StringIO):
    def isatty(self) -> bool:            # noqa: D401 - the one thing it says
        return True


class _Pipe(io.StringIO):
    def isatty(self) -> bool:
        return False


@contextlib.contextmanager
def person(answer: str | None = DECISION, *, who: str | None = PERSON_WHO, tty: bool = True,
           marker: str | None = None) -> Iterator[None]:
    """A person's own shell, in process: stdin a terminal (``tty``) holding
    ``answer``, no agent marker unless ``marker`` names one, and git's identity
    ``who`` (None: no identity)."""
    env = {k: v for k, v in os.environ.items() if k not in cli.AGENT_MARKERS}
    if marker:
        env[marker] = "1"
    text = "" if answer is None else answer + "\n"
    stdin = _Terminal(text) if tty else _Pipe(text)
    with mock.patch.dict(os.environ, env, clear=True), \
            mock.patch.object(cli.sys, "stdin", stdin), \
            mock.patch.object(cli.vcs, "ident", lambda _root: who):
        yield


def main(root: str, *argv: str) -> tuple[int, str, str]:
    """``nopekit <argv>`` in process against ``root``: (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(["-C", root, *argv])
    return code, out.getvalue(), err.getvalue()


def tree(root: str) -> dict[str, bytes]:
    """Every file under ``root`` but the ignored index and scratch, as bytes."""
    out: dict[str, bytes] = {}
    for here, dirs, names in os.walk(root):
        rel = os.path.relpath(here, root).replace(os.sep, "/")
        if rel.startswith(".nopekit/cache") or rel.startswith(".nopekit/obs") \
                or rel.startswith(".nopekit/out") or "__pycache__" in rel:
            continue
        for name in names:
            path = os.path.join(here, name)
            key = os.path.relpath(path, root).replace(os.sep, "/")
            if key in (".nopekit/ledger.json",):
                continue
            with open(path, "rb") as fh:
                out[key] = fh.read()
    return out


# --------------------------------------------------------------------------- #
# a pack with a proposer (SPEC 22, 25)
# --------------------------------------------------------------------------- #
PROPOSER_ID = "fixture.parts"
GATE_ID = "fixture.width"

_PACK_JSON = {
    "name": "fixture-pack", "version": "0.1.0",
    "description": "A test pack: one evaluator, one proposer",
    "settles": ["width"], "claim_classes": ["fixture"],
    "provides_gates": [GATE_ID], "max_tier": 0, "origin": "written for the tests",
    "basis": "sourced",
    "provides_proposers": [{"id": PROPOSER_ID, "basis": "sourced",
                            "description": "lists two parts from a fixed catalogue",
                            "run": "proposers/parts.py"}],
}

_GATE = '''
from nopekit.gates import gate
from nopekit.models import NegativeControl, Tier, Verdict


@gate(id="fixture.width", claims=["fixture-width"], tier=Tier.INSTANT, settles="width",
      negative_control=NegativeControl(fixture="selftest/bad.py:narrow", note="too narrow"))
def width(ctx):
    """Width is at least 1."""
    w = float(ctx.params.get("width", 0))
    return Verdict(gate="fixture.width", passed=w >= 1.0, measured=w, limit=1.0, units="mm",
                   comparator=">=")
'''

#: The proposer: writes two files into its directory, one with fixed bytes (the
#: dedupe row), and records that it RAN — never that it was imported — in a file
#: only a run writes. ``FIXTURE_PROPOSER_MODE`` chooses a failure to plant.
_PROPOSER = '''
import os, sys, time
out = os.environ["NOPEKIT_PROPOSAL_DIR"]
mode = os.environ.get("FIXTURE_PROPOSER_MODE", "")
if mode == "fail":
    print("the catalogue is unreachable", file=sys.stderr)
    sys.exit(3)
if mode == "sleep":
    time.sleep(30)
if mode == "touch-records":
    with open(os.path.join(os.environ["NOPEKIT_PROJECT"], "claims", "C99.json"), "w") as fh:
        fh.write('{"statement": "planted by a proposer"}\\n')
if mode == "touch-model":
    with open(os.path.join(os.environ["NOPEKIT_PROJECT"], "model", "bracket.py"), "a") as fh:
        fh.write("# edited by a proposer\\n")
if mode == "touch-verdicts":
    here = os.path.join(os.environ["NOPEKIT_PROJECT"], ".nopekit", "verdicts", "bracket.bed_fit")
    with open(os.path.join(here, "planted.json"), "w") as fh:
        fh.write("{}\\n")
if mode == "scratch":
    for rel in (".nopekit/cache/x.json", "model/__pycache__/m.cpython-311.pyc"):
        path = os.path.join(os.environ["NOPEKIT_PROJECT"], *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write("scratch\\n")
if mode == "nothing":
    sys.exit(0)
with open(os.path.join(out, "parts-fixed.txt"), "w") as fh:
    fh.write("M5 wall anchor, catalogue line 12\\n")
with open(os.path.join(out, "parts-args.txt"), "w") as fh:
    fh.write("asked: " + " ".join(sys.argv[1:]) + "\\n")
'''


_PACKS_MADE: list[str] = []


def fixture_pack(base: str) -> tuple[str, str]:
    """``(base, name)``: ``<base>/<name>`` holds one evaluator and one proposer;
    ``base`` is the directory to put on ``NOPEKIT_PACK_PATH``. Each call names its
    pack afresh (``fixture-pack-<n>``): a pack's gate modules are keyed on its
    name in ``sys.modules``, and a second directory under one name is refused as
    a shadow."""
    name = f"fixture-pack-{len(_PACKS_MADE) + 1}"
    _PACKS_MADE.append(name)
    pack = os.path.join(base, name)
    write_json(os.path.join(pack, "pack.json"), dict(_PACK_JSON, name=name))
    for rel, text in (("gates/width.py", _GATE), ("proposers/parts.py", _PROPOSER),
                      ("selftest/bad.py", "import dataclasses\n\n\ndef narrow(ctx):\n"
                                          "    return dataclasses.replace(ctx, params="
                                          "{'width': 0.2})\n"),
                      ("PACK.md", "# fixture\n\nIt cannot settle anything real.\n" * 30),
                      ("lenses.md", "# lenses\n")):
        path = os.path.join(pack, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    write_json(os.path.join(pack, "selftest", "baseline.json"),
               {"width": 2.0, "_notes": {"width": "the part's width, mm"}})
    return base, name
