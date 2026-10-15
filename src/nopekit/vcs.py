# SPDX-License-Identifier: Apache-2.0
"""nopekit.vcs — the only git edge.

Every question the spine asks git goes through this module, and nothing else in
``src/`` starts a git process (``test_meta.NoGitOutsideVcs`` refuses one). Phase 1
asks four things: which files a pack's ``selftest/`` holds (the control entry's
static walk), when an entry file was committed (a verdict's age on the page), the
commit a report was made at, and — from P2.5 on — who is signing. P3 adds
candidate worktrees here too, so the rules below are written once.

What each rule is for:

* **Argv form, ``-C root``.** No shell, so a path with a space or a quote is one
  argument, and every call names the repository it is asking about instead of
  inheriting the process's working directory.
* **A clean environment.** A git hook exports ``GIT_DIR``, ``GIT_INDEX_FILE`` and
  ``GIT_WORK_TREE`` pointing at the OUTER repository; an nopekit command run from
  a pre-commit hook would otherwise answer every question about the project with
  the hook's repository — its HEAD, its index, its files (the same trap
  ``tests/_env.py`` closes for the suite's own children). ``_STRIPPED`` lists the
  variables that pick a repository, an index, an object store or a config
  injection; everything else a user set on purpose (``GIT_CONFIG_GLOBAL``,
  ``GIT_AUTHOR_NAME``, ``GIT_SSH_COMMAND``) is theirs and stays.
* **A timeout** (``VCS_TIMEOUT_S``), because a hung ``core.fsmonitor`` daemon or a
  credential prompt would otherwise hang ``check`` with no output at all.
* **Never raising.** Every function answers ``None`` (or ``{}``, or ``False``)
  on any failure: no git on PATH, not a repository, a shallow or broken clone, a
  timeout, output it cannot parse. What slipped through while mapping Phase 1
  (tests:H11): ``verify.sh --dir`` checks a COPY of the bracket that has no
  ``.git``, and ``test_site`` runs ``doctor`` in-process in a bare temp
  directory — a git edge that raised there would have made "not a repository"
  a crash instead of a fact. Callers degrade: the selftest walk falls back to a
  filesystem walk, an age to ``null``, a commit to "not a git repository".

Only paths and hashes come back, never git's prose: ``LC_ALL=C`` keeps the
output parseable on a localized machine, and ``-z`` keeps a file name with a
newline or a non-ASCII character one exact name instead of a C-quoted string.

It imports nothing from nopekit (spec §3.1 allows ``util`` and no other), so
anything in the spine may ask git without an import cycle. It never reads the
wall clock (spec §0.6): a commit time is git's record, converted, not a reading
of now.

The writing half (architecture phase 6)
---------------------------------------
``round --commit`` (and the Stop hook's ``round --hook``) commits a round, and
``init`` starts a repository when the project sits in none; both go through
the functions below, so this module stays the only git edge. They keep every
rule above — argv form, ``-C root``, the same clean environment — and add a
contract of their own, because a write is not a question:

* **Explicit literal paths, always.** ``add`` and ``commit`` take a list of
  paths relative to ``root``, handed over on stdin (``--pathspec-from-file=-
  --pathspec-file-nul``: no argv limit, and a name with a newline stays one
  name) under ``--literal-pathspecs``. Never ``-A`` over the repository, never
  a directory pathspec: a hook that ran ``git add -A`` would commit a person's
  unrelated work as "round N" (designed against in phase 6). ``commit`` uses
  ``--only``, so what the person staged outside the list stays staged and
  uncommitted.
* **Never pushes.** ``push``, ``merge`` and ``tag`` come with candidates and
  merge (phase 4), under this same section.
* **Never writes config.** The only ``-c`` is ``user.useConfigOnly=true`` on
  the commit, so git never invents an identity from the host name — the rule
  ``ident`` keeps.
* **Never bypasses a hook.** No ``--no-verify``, no ``core.hooksPath``: a
  refusing hook is an answer, quoted back. ``GIT_EDITOR=:`` so no hook ever
  opens an editor no one can see.
* **A timeout of its own** (``VCS_WRITE_TIMEOUT_S``), ending in SIGTERM before
  SIGKILL: git removes its ``index.lock`` on SIGTERM, and a lock left behind
  would fail the person's next commit.
* **Never raises.** Each returns a ``Wrote``; ``why`` is the one place git's
  prose comes back — its first stderr line — and it is shown to a person,
  never parsed.

Three reads serve the writes (``changed_paths``, ``staged_paths``,
``operation``); they follow the read half's rules.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from typing import Iterable, NamedTuple, Sequence

__all__ = [
    "VCS_TIMEOUT_S",
    "is_repo",
    "git_head",
    "ls_files",
    "ignored",
    "ident",
    "committer_ident",
    "show",
    "history",
    "model_dirty",
    "commit_times",
    # the writing half (architecture phase 6)
    "VCS_WRITE_TIMEOUT_S",
    "Wrote",
    "in_repository",
    "init_repo",
    "changed_paths",
    "staged_paths",
    "operation",
    "add",
    "commit",
]


#: Seconds before a git call is abandoned and answered ``None``. Why 10: far above
#: an honest answer — measured 2026-09-27, ``ls-files --cached --others`` and a
#: whole-history ``log --name-only`` over this repository take 0.01-0.02 s warm,
#: and ``git ls-files`` on a cold, large repository (an index the page cache has
#: never seen) takes seconds — so only a hang reaches it. Rejected: unbounded (a
#: hung fsmonitor hook or credential helper hangs ``check`` with no output, and
#: the user cannot tell nopekit from git); 1-2 s (a network filesystem or a cold
#: cache legitimately takes that long, and a timeout is not a crash — it is read
#: as "not a repository", which quietly swaps the selftest walk for the
#: filesystem walk).
VCS_TIMEOUT_S = 10

#: Removed from the environment of every git call. Two sources, unioned:
#: the spec's list (§4 U13), and git's own ``git rev-parse --local-env-vars``
#: (git 2.43) — the variables git itself clears when it runs a sub-git in ANOTHER
#: repository (a submodule), which is exactly this module's situation. The union
#: is what ``VcsIsTheOnlyGitEdge`` checks against the installed git's list, so a
#: git that grows a new repository-local variable turns a test red instead of
#: leaking. Why each group:
#:
#: * which repository: GIT_DIR, GIT_WORK_TREE, GIT_IMPLICIT_WORK_TREE,
#:   GIT_COMMON_DIR, GIT_PREFIX, GIT_NAMESPACE, GIT_CEILING_DIRECTORIES (a
#:   foreign ceiling can stop discovery short of the project's ``.git``);
#: * which index and objects: GIT_INDEX_FILE, GIT_OBJECT_DIRECTORY,
#:   GIT_ALTERNATE_OBJECT_DIRECTORIES, GIT_GRAFT_FILE, GIT_SHALLOW_FILE,
#:   GIT_NO_REPLACE_OBJECTS, GIT_REPLACE_REF_BASE, GIT_QUARANTINE_PATH (a
#:   pre-receive hook sets it with the object directories);
#: * injected config: GIT_CONFIG_PARAMETERS (how ``git -c`` reaches a hook's
#:   children), GIT_CONFIG_COUNT (its newer spelling — with the count gone, git
#:   reads no GIT_CONFIG_KEY_n/VALUE_n), GIT_CONFIG (a legacy single-file
#:   override).
#:
#: Rejected: stripping every ``GIT_*`` as ``tests/_env.py`` does. The suite wants a
#: machine-free child; the spine wants the USER's git — their ``GIT_CONFIG_GLOBAL``,
#: their ``GIT_AUTHOR_NAME`` (``ident`` must agree with the commit ``git commit``
#: would make), their ``GIT_SSH_COMMAND`` once P3 fetches. Also rejected: asking
#: the installed git for its list at runtime (a second process on every call, to
#: learn a list git changes a few times a decade and that a test already pins).
_STRIPPED = frozenset({
    "GIT_DIR", "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_COMMON_DIR",
    "GIT_PREFIX", "GIT_NAMESPACE", "GIT_CEILING_DIRECTORIES",
    "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_GRAFT_FILE", "GIT_SHALLOW_FILE", "GIT_NO_REPLACE_OBJECTS",
    "GIT_REPLACE_REF_BASE", "GIT_QUARANTINE_PATH",
    "GIT_CONFIG_PARAMETERS", "GIT_CONFIG_COUNT", "GIT_CONFIG",
})

#: Set on every git call. ``GIT_OPTIONAL_LOCKS=0``: a read-only question must
#: never take ``.git/index.lock`` — ``git status`` refreshes the index
#: opportunistically, and a lock held by nopekit fails the user's concurrent
#: ``git commit`` with "index.lock exists". ``GIT_TERMINAL_PROMPT=0``: git never
#: asks (stdin is closed as well, so a question fails instead of hanging).
#: ``LC_ALL=C``: the output this module parses is git's, not a translation of it.
_SET = {"GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}

_HEX_OID = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")

#: A commit header in ``commit_times``'s log: \x01<committer epoch>\x02<decorations>.
#: Neither control byte occurs in a decimal time or a ref name. A file name that
#: BEGINS with \x01 is legal and absurd; it reads as a header that does not parse,
#: and the whole answer becomes unknown (``{}``) rather than a wrong time.
_LOG_FORMAT = "%x01%ct%x02%D"


def _environment() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in _STRIPPED}
    env.update(_SET)
    return env


def _ask(root: str | os.PathLike[str], args: Sequence[str], *,
         literal_pathspecs: bool = False) -> tuple[int | None, bytes, bytes]:
    """``git -C root <args>``: ``(returncode, stdout, stderr)``; ``(None, b"",
    b"timeout")`` when it did not finish and ``(None, b"", b"")`` when it did
    not start. The one place a read-only git process starts.

    ``--literal-pathspecs`` for calls that take paths: a file literally named
    ``*.stl`` or ``:(top)x`` is a path, not a pattern that quietly matches
    something else.
    """
    try:
        argv = ["git", "-C", os.fspath(root)]
        if literal_pathspecs:
            argv.append("--literal-pathspecs")
        argv.extend(os.fspath(a) for a in args)
        proc = subprocess.run(
            argv, env=_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=VCS_TIMEOUT_S, check=False)
    except subprocess.TimeoutExpired:
        return None, b"", b"timeout"
    except Exception:  # noqa: BLE001 — never raises: see the module docstring
        # FileNotFoundError (no git), PermissionError (a noexec PATH entry),
        # ValueError (a NUL byte in a path), TypeError (a path that is not
        # one). Each means "git did not answer", which is the answer.
        return None, b"", b""
    return proc.returncode, proc.stdout, proc.stderr


def _git(root: str | os.PathLike[str], args: Sequence[str], *,
         literal_pathspecs: bool = False) -> bytes | None:
    """``git -C root <args>``'s stdout, or ``None`` for any failure at all."""
    code, out, _err = _ask(root, args, literal_pathspecs=literal_pathspecs)
    return out if code == 0 else None


def _text(out: bytes | None) -> str | None:
    if out is None:
        return None
    try:
        return out.decode("utf-8").strip()
    except UnicodeDecodeError:
        return None


def is_repo(path: str | os.PathLike[str]) -> bool:
    """``path`` is inside a git work tree. ``False`` for anything else, including
    no git at all: the caller's question is "can I ask git about this?"."""
    return _text(_git(path, ["rev-parse", "--is-inside-work-tree"])) == "true"


def git_head(root: str | os.PathLike[str]) -> str | None:
    """The full object id of ``HEAD`` for the repository holding ``root``;
    ``None`` outside a repository, before the first commit, or on any failure."""
    oid = _text(_git(root, ["rev-parse", "--verify", "--quiet", "HEAD^{commit}"]))
    return oid if oid and _HEX_OID.match(oid) else None


def ls_files(root: str | os.PathLike[str], relpaths: Iterable[str], *,
             others: bool = True) -> list[str] | None:
    """The files git knows under ``relpaths`` (all of ``root`` when empty), as
    POSIX paths relative to ``root``, sorted and unique; ``None`` on failure.

    With ``others`` (the default): tracked files plus untracked files that no
    ignore rule excludes (``--cached --others --exclude-standard``) — the files
    the author would commit, which is what the control entry's selftest walk
    digests. A pack's ``selftest/`` file created but not yet added
    still counts: a control input the author is editing is an input.

    What git reports is passed through, not re-checked against the disk: a
    tracked file deleted from the working tree is still listed (its digest reads
    missing, which is a change), and an untracked nested repository appears once
    as ``name/``. Duplicates — one path per stage while a merge is unresolved —
    are collapsed.
    """
    paths = _paths(relpaths)
    if paths is None:
        return None
    args = ["ls-files", "-z"]
    if others:
        args += ["--cached", "--others", "--exclude-standard"]
    args += ["--", *paths]
    out = _git(root, args, literal_pathspecs=True)
    if out is None:
        return None
    return sorted({os.fsdecode(name) for name in out.split(b"\0") if name})


def ignored(root: str | os.PathLike[str], relpaths: Iterable[str]) -> list[str] | None:
    """The files under ``relpaths`` that git ignores and does not track, as
    POSIX paths relative to ``root``, sorted; ``None`` on failure or outside a
    repository. A tracked file is never in it, whatever an ignore rule says
    (it is already public), and a path with no file is never in it either.
    `site build` asks it before it publishes evidence a verdict names by a
    path in the project (architecture phase 5: a git-ignored ``.env`` named as
    evidence was published)."""
    paths = _paths(relpaths)
    if not paths:
        return None if paths is None else []
    out = _git(root, ["ls-files", "-z", "--others", "--ignored", "--exclude-standard", "--",
                      *paths], literal_pathspecs=True)
    if out is None:
        return None
    return sorted({os.fsdecode(name) for name in out.split(b"\0") if name})


def _ident(root: str | os.PathLike[str], var: str) -> str | None:
    line = _text(_git(root, ["-c", "user.useConfigOnly=true", "var", var]))
    if not line:
        return None
    # "Name <email> 1790560187 -0700": the identity ends at the last '>'. What
    # follows is git's clock, and a clock does not belong in an identity.
    end = line.rfind(">")
    who = line[:end + 1].strip() if end >= 0 else ""
    return who if "<" in who else None


def ident(root: str | os.PathLike[str]) -> str | None:
    """``Name <email>`` — the author identity a commit in ``root`` would carry,
    timestamp dropped; ``None`` when none is configured.

    ``user.useConfigOnly=true`` is the point: without it git invents
    ``user@host.domain`` from the machine, and a signature that names a hostname
    nobody chose is a signature nobody made (D-12; P2.5's signer and P3's
    preference records refuse on ``None``).
    """
    return _ident(root, "GIT_AUTHOR_IDENT")


def committer_ident(root: str | os.PathLike[str]) -> str | None:
    """``Name <email>`` — the COMMITTER a commit in ``root`` would carry
    (``committer.name``/``committer.email`` config or ``GIT_COMMITTER_*`` over
    ``user.*``), timestamp dropped; ``None`` when none is configured.

    For the round's identity gate (review of architecture phase 6): the gate
    read the author alone, and a CI runner or wrapper that exported
    ``GIT_COMMITTER_*`` put a committer on a round's commit that the project's
    ``people`` never named, with the paragraph naming only the author."""
    return _ident(root, "GIT_COMMITTER_IDENT")


def show(root: str | os.PathLike[str], relpath: str, rev: str = "HEAD") -> bytes | None:
    """The bytes commit ``rev`` (``HEAD``, or a full object id from
    :func:`history`) holds at ``relpath`` (``git show <rev>:<path>``), or
    ``None`` — outside a repository, before a first commit, or a path the
    commit does not hold. Read-only.

    For the strict results reader's refusal (P2.5a, critique 6 of its design):
    "git checkout -- results/C1.json" discards whatever the commit does not
    hold, and a fail recorded since is exactly that — so the refusal compares
    the two and names each fail the restore would drop. A path with a ``:`` or
    a leading ``-``, or a ``rev`` that is neither ``HEAD`` nor an object id, is
    refused as no answer rather than handed to git as syntax."""
    rel = _normal(os.fspath(relpath))
    if not rel or rel.startswith("-") or ":" in rel:
        return None
    if rev != "HEAD" and not _HEX_OID.match(str(rev)):
        return None
    return _git(root, ["show", f"{rev}:./{rel}"])


def history(root: str | os.PathLike[str], relpath: str, limit: int) -> list[str]:
    """The full object ids of the commits that changed ``relpath``, newest
    first, at most ``limit`` — ``[]`` outside a repository, for a path no commit
    holds, or on any failure. Read-only.

    For the results reader's refusal (review of P2.5a): a hand edit that was
    COMMITTED leaves ``HEAD`` holding the same broken bytes, so "git checkout
    -- results/C2.json" changed nothing and every command refused again; the
    refusal walks these back to the newest version that verifies. Pinned
    against the user's log config as ``commit_times`` is (``log.follow`` would
    walk a rename into another claim's file)."""
    rel = _normal(os.fspath(relpath))
    if not rel or rel.startswith("-") or limit < 1:
        return []
    out = _text(_git(root, ["-c", "log.follow=false", "-c", "log.showSignature=false",
                            "log", f"-n{int(limit)}", "--no-renames", "--format=%H", "--",
                            rel], literal_pathspecs=True))
    if not out:
        return []
    return [line for line in out.splitlines() if _HEX_OID.match(line)]


def model_dirty(root: str | os.PathLike[str], relpaths: Iterable[str]) -> bool | None:
    """Whether any of ``relpaths`` (the model's files) differs from the last
    commit — staged, unstaged or untracked — or ``None`` outside a repository.
    Read-only (``git status --porcelain``). For ``claim physical``'s prompt
    (P2.5a, R4 of its design): the moment a person attests that the object in
    hand was built from this design is the moment to see that the design moved
    since the last commit."""
    paths = _paths(relpaths)
    if not paths:
        return None if paths is None else False
    out = _git(root, ["status", "--porcelain", "-z", "--untracked-files=all", "--", *paths],
               literal_pathspecs=True)
    if out is None:
        return None
    return bool(out.strip(b"\0"))


def _iso(epoch: int) -> str:
    # The shape util.utcnow_iso stamps, so an age computed from an obs `when`
    # and one computed from a commit time read the same.
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _paths(relpaths: Iterable[str] | str | os.PathLike[str]) -> list[str] | None:
    """``relpaths`` as a list of strings; a lone path is one path, never its
    characters (``ls_files(root, "selftest")`` would otherwise ask about ``s``,
    ``e``, ``l``...). ``None`` when it is not paths at all."""
    if isinstance(relpaths, (str, bytes, os.PathLike)):
        relpaths = [relpaths]
    try:
        return [os.fsdecode(p) for p in relpaths]
    except TypeError:
        return None


def _normal(relpath: str) -> str:
    path = relpath.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    path = path.rstrip("/")
    return "" if path == "." else path


def commit_times(root: str | os.PathLike[str], relpaths: Iterable[str]) -> dict[str, str]:
    """``{relpath: "2026-09-27T14:02:11Z"}`` — when the newest commit touching
    each path (a file, or anything under a directory) was committed.

    A path appears only when git knows its time: untracked, outside ``root``, or
    any failure → absent, and the caller renders the age as unknown, never 0.

    One ``git log`` walk for all paths, newest first. Committer time, not author
    time: a rebased entry reached this history when it was committed here.

    **Shallow clones.** CI checks out one commit, whose diff against nothing
    "adds" every file. Attributing a file to that boundary commit would date an
    entry committed a year ago to the clone's tip — younger than it is, the
    flattering direction on a page where age fades a verdict. So a path whose
    newest touching commit is a shallow boundary (git decorates it ``grafted``)
    has no time.
    """
    paths = _paths(relpaths)
    if not paths:
        return {}
    wanted = {p: _normal(p) for p in paths}
    # Pinned against the user's log config, each of which changes what this
    # parses: log.follow (renames under one path), log.showSignature (gpg lines
    # in the output), log.showRoot (the root commit's files) — `--root` restores
    # it. "" is not a pathspec git accepts; "." is the same question.
    args = ["-c", "log.follow=false", "-c", "log.showSignature=false",
            "log", "-z", "--root", "--no-renames", "--relative", "--name-only",
            "--decorate-refs-exclude=*", f"--format={_LOG_FORMAT}",
            "--", *sorted({path or "." for path in wanted.values()})]
    out = _git(root, args, literal_pathspecs=True)
    if out is None:
        return {}

    # file -> (newest real commit time, newest boundary commit time)
    newest: dict[str, list[int]] = {}
    when, grafted, after_header = 0, False, False
    for token in out.split(b"\0"):
        if token.startswith(b"\x01"):
            head, _, decorations = token[1:].partition(b"\x02")
            try:
                when = int(head)
            except ValueError:
                return {}
            grafted = b"grafted" in decorations.split(b", ")
            after_header = True
            continue
        if after_header and token.startswith(b"\n"):
            token = token[1:]          # git separates a header from its names with "\n"
        after_header = False
        if not token:
            continue
        slot = newest.setdefault(os.fsdecode(token), [-1, -1])
        index = 1 if grafted else 0
        slot[index] = max(slot[index], when)

    result: dict[str, str] = {}
    for original, path in wanted.items():
        real, boundary = -1, -1
        for name, (r, b) in newest.items():
            if not path or name == path or name.startswith(path + "/"):
                real, boundary = max(real, r), max(boundary, b)
        if real >= 0 and real >= boundary:
            result[original] = _iso(real)
    return result



# --------------------------------------------------------------------------- #
# the writing half (architecture phase 6)
# --------------------------------------------------------------------------- #
#: Seconds before a writing git call is abandoned. Why 120: the Stop hook's
#: budget is 300 s (``hooks/hooks.json``); a round's check and site build usually
#: take well under 60 s, and a commit hook that runs a linter or a test file takes
#: tens of seconds. Rejected: 10 s, the read timeout (an ordinary pre-commit hook
#: exceeds it, and the round would read "did not finish" on every turn); 290 s (a
#: hung gpg pinentry would spend the hook's whole budget, and Claude Code would
#: kill the hook mid-commit, leaving ``index.lock`` and printing no message).
VCS_WRITE_TIMEOUT_S = 120

#: Seconds between SIGTERM and SIGKILL when a writing call times out: git's
#: sigchain handler removes ``index.lock`` on SIGTERM, which takes milliseconds.
_TERM_GRACE_S = 5


class Wrote(NamedTuple):
    """What a writing call did. ``ok``; ``oid``, the new commit's full id
    (``commit`` only); ``why`` — ``""``, ``"no-git"`` (git could not be
    started), ``"timeout"``, ``"inside a repository"`` (``init_repo``) or
    ``"refused: <git's first stderr line>"``."""

    ok: bool
    oid: str | None
    why: str


def _git_write(root: str | os.PathLike[str], args: Sequence[str], *,
               stdin_bytes: bytes | None = None,
               timeout: float | None = None) -> tuple[int | None, bytes, str]:
    """``git -C root <args>``: ``(returncode, stdout, first stderr line)`` —
    ``(None, b"", "no-git")`` when git did not start and ``(None, b"",
    "timeout")`` when it did not finish. The one place a writing git process
    starts: the read half's environment plus ``GIT_EDITOR=:``. Never raises."""
    limit = VCS_WRITE_TIMEOUT_S if timeout is None else timeout
    env = _environment()
    env["GIT_EDITOR"] = ":"
    try:
        argv = ["git", "-C", os.fspath(root), *(os.fspath(a) for a in args)]
        proc = subprocess.Popen(
            argv, env=env,
            stdin=subprocess.PIPE if stdin_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:  # noqa: BLE001 — never raises: see the module docstring
        return None, b"", "no-git"
    try:
        out, err = proc.communicate(stdin_bytes, timeout=limit)
    except subprocess.TimeoutExpired:
        proc.terminate()
        try:
            proc.communicate(timeout=_TERM_GRACE_S)
        except Exception:  # noqa: BLE001
            proc.kill()
            try:
                proc.communicate(timeout=_TERM_GRACE_S)
            except Exception:  # noqa: BLE001
                pass
        return None, b"", "timeout"
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        return None, b"", "no-git"
    lines = [line.strip() for line in err.decode("utf-8", "replace").splitlines()
             if line.strip()]
    # git's own "fatal:"/"error:" line is the useful one; a hook's output comes
    # first and is what a refusing hook says, so the first line is kept.
    return proc.returncode, out, (lines[0] if lines else "")


def _refused(code: int | None, first: str) -> str:
    if code is None:
        return first
    return "refused: " + (first or f"git exited {code}")


def _pathspec_stdin(relpaths: Iterable[str]) -> bytes | None:
    paths = _paths(relpaths)
    if not paths:
        return None
    try:
        return b"".join(os.fsencode(p) + b"\0" for p in paths)
    except (TypeError, ValueError):
        return None


#: git's own words, under ``LC_ALL=C``, for "no repository holds this
#: directory" — the one refusal of ``rev-parse`` that is an answer rather than
#: a failure to answer. ``... (or any of the parent directories)`` and ``...
#: (or any parent up to mount point /x)`` both begin so.
_NOT_A_REPOSITORY = "not a git repository"
_NO_GIT = "git is not on PATH"


def in_repository(path: str | os.PathLike[str]) -> tuple[bool | None, str]:
    """Whether ``path`` sits in a git repository: ``(True, "")``, ``(False,
    "")`` — a POSITIVE "no": git said "not a git repository" and no ``.git``
    entry stands in ``path`` or above it — or ``(None, why)`` when git did not
    answer (not on PATH, a timeout, a refusal such as "dubious ownership", or a
    ``.git`` git would not read). Read-only.

    For ``init`` and `init_repo` (review of architecture phase 6): both asked
    `is_repo`, which answers ``False`` on ANY failure, so under the
    ``safe.directory`` refusal common on WSL ``/mnt/c``, shared drives and
    container volumes (``GIT_TEST_ASSUME_DIFFERENT_OWNER=1`` simulates it), or a
    10 s timeout on a cold large repository, ``init`` in a subdirectory of an
    existing repository started a nested one: the project was hidden from the
    repository it sat in, and every round committed into the nested one. A
    repository is started only on this function's ``False``. The ``.git``
    walk is the second witness: a ceiling or a filesystem boundary that stops
    git's discovery short of a repository is not "no repository"."""
    code, out_bytes, err_bytes = _ask(path, ["rev-parse", "--is-inside-work-tree"])
    if code is None:
        return None, (f"git did not answer in {VCS_TIMEOUT_S} s" if err_bytes == b"timeout"
                      else _NO_GIT)
    out = _text(out_bytes)
    if code == 0 and out in ("true", "false"):
        # "false": inside a .git directory or a bare repository — a repository
        # holds it all the same.
        return True, ""
    err = err_bytes.decode("utf-8", "replace")
    first = next((line.strip() for line in err.splitlines() if line.strip()), "")
    if code == 0 or _NOT_A_REPOSITORY not in err:
        return None, first or f"git exited {code}"
    here = os.path.abspath(os.fspath(path))
    while True:
        if os.path.lexists(os.path.join(here, ".git")):
            return None, f"git does not read the repository at {here}"
        parent = os.path.dirname(here)
        if parent == here:
            return False, ""
        here = parent


def init_repo(root: str | os.PathLike[str]) -> Wrote:
    """``git init -q`` in ``root``. Refused (``ok`` False) unless
    `in_repository` says positively that no repository holds ``root``:
    ``why`` ``"inside a repository"``, or ``"git did not answer: <why>"``.
    `init` changes nothing about git inside a repository, and a nested
    ``.git`` would hide the project from the repository it sits in."""
    inside, why = in_repository(root)
    if inside:
        return Wrote(False, None, "inside a repository")
    if inside is None:
        return Wrote(False, None, "no-git" if why == _NO_GIT else f"git did not answer: {why}")
    code, _out, first = _git_write(root, ["init", "-q"])
    if code == 0:
        return Wrote(True, None, "")
    return Wrote(False, None, _refused(code, first))


def _nul_list(out: bytes | None) -> list[str] | None:
    if out is None:
        return None
    return [os.fsdecode(name) for name in out.split(b"\0") if name]


def changed_paths(root: str | os.PathLike[str]) -> list[str] | None:
    """Every path under ``root`` that differs from ``HEAD`` — modified or
    deleted in the work tree, staged, or untracked and not ignored — relative
    to ``root``, POSIX, sorted and unique (an untracked nested repository
    keeps git's trailing ``/``); ``None`` outside a repository or on any
    failure. Read-only. Asked only about ``.``: a change elsewhere in the
    repository is never listed, so a project inside a larger repository (the
    bracket, a monorepo) sees its own subtree.

    Three questions, unioned: ``diff`` (the work tree against the index — it
    compares content, so a file whose mtime alone moved is not listed, where
    ``ls-files --modified`` would name it), ``diff --cached`` (the index against
    ``HEAD``; an unborn branch compares against nothing) and ``ls-files
    --others --exclude-standard``. Rejected: ``status --porcelain``, which
    prints paths relative to the repository's top level whatever ``-C`` says."""
    found: set[str] = set()
    for args in (["diff", "--name-only", "-z", "--no-renames", "--relative", "--", "."],
                 ["diff", "--cached", "--name-only", "-z", "--no-renames", "--relative",
                  "--", "."],
                 ["ls-files", "-z", "--others", "--exclude-standard", "--", "."]):
        names = _nul_list(_git(root, ["-c", "core.quotepath=false", *args]))
        if names is None:
            return None
        # An untracked nested repository is listed as ``name/``, and that slash
        # is kept: `rounds.in_round_paths` refuses a name ending in ``/``. What
        # slipped through (review of architecture phase 6): `_normal` stripped
        # it, so ``generators/cadlib/`` read as a file, was staged, and a round
        # committed a 160000 gitlink — a submodule pointer nobody chose.
        found.update(_normal(name) + ("/" if name.endswith("/") and _normal(name) else "")
                     for name in names)
    found.discard("")
    return sorted(found)


def staged_paths(root: str | os.PathLike[str]) -> list[str] | None:
    """The paths under ``root`` whose index entry differs from ``HEAD``,
    relative to ``root``, sorted; ``None`` on failure. Read-only."""
    names = _nul_list(_git(root, ["diff", "--cached", "--name-only", "-z", "--no-renames",
                                  "--relative", "--", "."]))
    if names is None:
        return None
    return sorted({_normal(name) for name in names} - {""})


#: The in-progress operations a round never commits through, by the file git
#: keeps while each runs (``git rev-parse --git-path <name>``).
_OPERATIONS = (("MERGE_HEAD", "merge"), ("rebase-merge", "rebase"), ("rebase-apply", "rebase"),
               ("CHERRY_PICK_HEAD", "cherry-pick"), ("REVERT_HEAD", "revert"),
               ("BISECT_LOG", "bisect"))


def operation(root: str | os.PathLike[str]) -> str | None:
    """What the repository holding ``root`` is in the middle of: ``""`` (none),
    ``"merge"``, ``"rebase"``, ``"cherry-pick"``, ``"revert"``, ``"bisect"``,
    or ``"detached"`` (HEAD names no branch); ``None`` outside a repository.
    Read-only. A commit made through any of them would land inside the
    person's operation — a merge commit nobody wrote, a rebase step that is a
    round. An unborn branch still has a symbolic HEAD, so a new repository
    reads ``""``."""
    if not is_repo(root):
        return None
    for name, word in _OPERATIONS:
        where = _text(_git(root, ["rev-parse", "--git-path", name]))
        if where and os.path.exists(os.path.join(os.fspath(root), where)):
            return word
    if _git(root, ["symbolic-ref", "-q", "HEAD"]) is None:
        return "detached"
    return ""


def add(root: str | os.PathLike[str], relpaths: Iterable[str]) -> Wrote:
    """Stage exactly ``relpaths`` (relative to ``root``): new, modified and
    deleted alike (``add --all`` limited to the list). Literal pathspecs on
    stdin, never a directory, never the repository."""
    data = _pathspec_stdin(relpaths)
    if data is None:
        return Wrote(False, None, "refused: no paths to stage")
    code, _out, first = _git_write(root, ["--literal-pathspecs", "add", "--all",
                                          "--pathspec-from-file=-", "--pathspec-file-nul"],
                                   stdin_bytes=data)
    if code == 0:
        return Wrote(True, None, "")
    return Wrote(False, None, _refused(code, first))


def commit(root: str | os.PathLike[str], relpaths: Iterable[str], subject: str,
           body: str) -> Wrote:
    """Commit exactly ``relpaths`` as they are in the work tree (``--only``),
    with ``subject`` and ``body`` as two paragraphs, under git's configured
    identity (``user.useConfigOnly=true``: none configured is a refusal, never
    an invented one). The commit hooks run; a refusing one is ``why``. ``oid``
    is ``HEAD`` after the commit."""
    data = _pathspec_stdin(relpaths)
    if data is None:
        return Wrote(False, None, "refused: no paths to commit")
    args = ["-c", "user.useConfigOnly=true", "--literal-pathspecs", "commit", "--quiet",
            "--cleanup=whitespace", "--only", "--pathspec-from-file=-",
            "--pathspec-file-nul", "-m", subject]
    if body:
        args += ["-m", body]
    code, _out, first = _git_write(root, args, stdin_bytes=data)
    if code == 0:
        return Wrote(True, git_head(root), "")
    return Wrote(False, None, _refused(code, first))
