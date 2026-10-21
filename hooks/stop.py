# SPDX-License-Identifier: Apache-2.0
"""The plugin's Stop hook: ``nopekit round --hook`` with the session's working
directory kept off the import path.

``hooks.json`` runs this file as a script. What slipped through (review of
architecture phase 6): the hook ran ``python3 -m nopekit round --hook``, and
``-m`` puts the current directory FIRST on ``sys.path``, ahead of PYTHONPATH and
the standard library. The hook fires at the end of every turn in every
repository the plugin is installed for, so a ``difflib.py`` in the session's
cwd ran as code — and one that raised ``SystemExit(2)`` blocked the turn, before
the hook's catch-all could run; an innocent ``types.py``, ``queue.py`` or
``select.py``, or a ``nopekit/`` directory, crashed the hook with a traceback
and no message, or ran the wrong nopekit.

Run as a script, Python puts this file's directory first, never the cwd. The
lines below then drop any empty or relative entry an environment left (each
means "the cwd"), put the plugin's own ``src`` first, and turn a failure to
import nopekit into the one-line ``systemMessage`` the hook promises, exit 0.

*Rejected:* ``PYTHONSAFEPATH=1`` / ``python3 -P`` (Python 3.11+; nopekit
supports 3.10); ``python3 -I`` (it drops user site-packages, so a mesh pack's
``trimesh`` installed with ``pip --user`` would read SKIPPED in the hook and
checked in the shell, flipping every round); the same lines as a ``-c``
one-liner inside ``hooks.json`` (untestable, and unreadable in a JSON string).

Nothing but builtins and modules already loaded at startup is imported before
``sys.path`` is set.

One script for the plugin's three hosts. Claude Code and Codex run it from
``hooks.json`` with no argument: Codex reads Claude Code's hook format, sets
``CLAUDE_PLUGIN_ROOT`` for a plugin's hook, and takes the same one JSON object
(it refuses any key outside Claude Code's set). Cursor runs it from
``cursor-hooks.json`` with ``--cursor``: Cursor's stop hook has no message key —
its one key, ``followup_message``, is submitted as the next prompt, so a round
said there would start another turn, and another round, up to its loop limit.
Under ``--cursor`` the paragraph goes to stderr (Cursor's hook log) and stdout
is ``{}``. *Rejected:* ``followup_message`` (the loop above); one hooks file for
all three (Cursor's format is ``{"version": 1, "hooks": {"stop": [...]}}``,
Claude Code's and Codex's a nested ``Stop`` matcher list).
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
sys.path[:] = [_SRC] + [entry for entry in sys.path
                        if entry and os.path.isabs(entry) and entry not in (_HERE, _SRC)]


def _say(message: dict) -> None:
    import json
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run(argv: list | None = None) -> int:
    """`cli.main(["round", "--hook"])`, which prints its one JSON object and
    returns 0; anything that escapes it, or stops nopekit importing, becomes
    one ``systemMessage`` line. Always 0: Claude Code and Codex read exit 2 as
    "block". With ``--cursor``, that object's message goes to stderr instead."""
    argv = sys.argv[1:] if argv is None else argv
    if "--cursor" not in argv:
        return _round()
    import io
    real, caught = sys.stdout, io.StringIO()
    sys.stdout = caught
    try:
        _round()
    finally:
        sys.stdout = real
    import json
    for line in caught.getvalue().splitlines():
        try:
            said = json.loads(line).get("systemMessage")
        except (ValueError, AttributeError):
            said = line
        if said:
            sys.stderr.write(str(said) + "\n")
    _say({})
    return 0


def _round() -> int:
    """The hook's body, saying its one JSON object on ``sys.stdout``."""
    try:
        from nopekit.cli import main
    except BaseException as exc:  # noqa: BLE001 — the hook never fails the turn
        line = (str(exc).strip().splitlines() or ["no message"])[0]
        _say({"systemMessage": f"nopekit round could not start ({type(exc).__name__}: "
                               f"{line}); nothing was committed."})
        return 0
    try:
        main(["round", "--hook"])
    except BaseException as exc:  # noqa: BLE001
        line = (str(exc).strip().splitlines() or ["no message"])[0]
        _say({"systemMessage": f"nopekit round crashed ({type(exc).__name__}: {line}); "
                               f"the round may be incomplete."})
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
