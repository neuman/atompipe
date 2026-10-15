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


def run() -> int:
    """`cli.main(["round", "--hook"])`, which prints its one JSON object and
    returns 0; anything that escapes it, or stops nopekit importing, becomes
    one ``systemMessage`` line. Always 0: Claude Code reads exit 2 as "block"."""
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
