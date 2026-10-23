# SPDX-License-Identifier: Apache-2.0
"""cfd-openfoam's reader and writer for OpenFOAM's dictionary files.

Standard library only, so the tier-0 gate runs where OpenFOAM is not installed
(CI among them) and every case file it decides on is opened by Python, where the
trace sees it. OpenFOAM reads its own files in a subprocess the trace cannot see
into, which is why the gates that run it are opaque and re-run on every check.

**The format** (OpenFOAM user guide, "Basic input/output file format"): a
dictionary is a list of entries, ``keyword value...;`` or ``keyword { ... }``;
a list is ``( ... )``, optionally with a count before it (``3(1 2 3)``);
``[0 2 -1 0 0 0 0]`` is a dimension set; ``//`` and ``/* */`` are comments; a
keyword may carry parentheses (``div(phi,U)``) and a quoted keyword is a regular
expression (``"(U|k|epsilon)"``); ``#include``, ``#includeEtc``,
``#includeFunc``, ``#remove``, ``#eval`` and ``#calc`` are directives; ``$name``
substitutes another entry. :func:`parse` keeps every entry in file order with
the span its value occupies, so :func:`set_entry` can change one value and leave
every other byte as it was: the known-bad fixtures are the baseline case with
one entry changed.

**What it does not do.** It does not evaluate ``#eval`` or ``#calc``, run
``#codeStream``, or expand a macro inside a list. A gate that needs a value the
reader cannot resolve says so and errors; it never reads a default in its place.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field


class FoamFormatError(ValueError):
    """The bytes are not an OpenFOAM dictionary this reader understands."""


# --------------------------------------------------------------------------- #
# tokens
# --------------------------------------------------------------------------- #
_PUNCT = frozenset("{}()[];")
_SPACE = frozenset(" \t\r\n\f\v")
_NUMBER_START = frozenset("0123456789+-.")
_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")


@dataclass(frozen=True)
class Tok:
    """One token: ``kind`` is ``punct``, ``word``, ``string``, ``number`` or
    ``verbatim`` (a ``#{ ... #}`` block); ``start``/``end`` are offsets."""

    kind: str
    text: str
    start: int
    end: int


def tokens(text: str) -> list[Tok]:
    """Every token of ``text``. Raises :class:`FoamFormatError` on an
    unterminated string, comment or verbatim block: a gate that judged part of a
    file would judge a different case."""
    out: list[Tok] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _SPACE:
            i += 1
            continue
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            if j < 0:
                raise FoamFormatError(f"unterminated /* comment at offset {i}")
            i = j + 2
            continue
        if text.startswith("#{", i):
            j = text.find("#}", i + 2)
            if j < 0:
                raise FoamFormatError(f"unterminated #{{ block at offset {i}")
            out.append(Tok("verbatim", text[i + 2:j], i, j + 2))
            i = j + 2
            continue
        if c in _PUNCT:
            out.append(Tok("punct", c, i, i + 1))
            i += 1
            continue
        if c == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            if j >= n:
                raise FoamFormatError(f"unterminated string at offset {i}")
            out.append(Tok("string", text[i + 1:j], i, j + 1))
            i = j + 1
            continue
        if text.startswith("${{", i):
            j = text.find("}}", i + 3)
            if j < 0:
                raise FoamFormatError(f"unterminated ${{{{ expression at offset {i}")
            out.append(Tok("expr", text[i:j + 2], i, j + 2))
            i = j + 2
            continue
        if text.startswith("${", i):
            # ``${../../master/patchFields}``: a macro with a scoped name, one word.
            j = text.find("}", i + 2)
            if j < 0:
                raise FoamFormatError(f"unterminated ${{ macro at offset {i}")
            out.append(Tok("word", text[i:j + 1], i, j + 1))
            i = j + 1
            continue
        if c in _NUMBER_START:
            m = _NUMBER.match(text, i)
            if m and (m.end() >= n or text[m.end()] in _SPACE or text[m.end()] in _PUNCT):
                out.append(Tok("number", m.group(0), i, m.end()))
                i = m.end()
                continue
        # A word: runs to whitespace, ';', '{', '}' or an unbalanced ')' — and may
        # hold balanced parentheses, as ``div(phi,U)`` does.
        j, depth = i, 0
        while j < n:
            d = text[j]
            if d in _SPACE or d in ";{}[]\"":
                break
            if d == "(":
                if j == i:
                    break
                depth += 1
            elif d == ")":
                if depth == 0:
                    break
                depth -= 1
            j += 1
        if j == i:
            raise FoamFormatError(f"unexpected character {c!r} at offset {i}")
        w = text[i:j]
        if w in ("#eval", "#calc"):
            # ``#eval{ 0.5 * $x }``: one expression token, braces balanced, so a
            # list holding one is still a list. The reader never evaluates it.
            k = j
            while k < n and text[k] in _SPACE:
                k += 1
            if k < n and text[k] == "{":
                depth, m = 0, k
                while m < n:
                    if text[m] == "{":
                        depth += 1
                    elif text[m] == "}":
                        depth -= 1
                        if depth == 0:
                            break
                    m += 1
                if m >= n:
                    raise FoamFormatError(f"unterminated {w} block at offset {i}")
                out.append(Tok("expr", text[i:m + 1], i, m + 1))
                i = m + 1
                continue
        out.append(Tok("word", w, i, j))
        i = j
    return out


# --------------------------------------------------------------------------- #
# the tree
# --------------------------------------------------------------------------- #
@dataclass
class FoamList:
    """A ``( ... )`` list (or a ``[ ... ]`` dimension set, ``square=True``)."""

    items: list
    start: int = 0
    end: int = 0
    square: bool = False

    def __iter__(self):
        return iter(self.items)

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


@dataclass
class Entry:
    """``key value...;`` (``value`` a list of items: :class:`Tok`,
    :class:`FoamList`, :class:`FoamDict`), ``key { ... }`` (``value`` a
    :class:`FoamDict`), or a directive (``key`` starts with ``#``). ``start``
    and ``end`` span the value, for :func:`set_entry`."""

    key: str
    value: object
    start: int
    end: int
    quoted: bool = False
    kstart: int = -1      # where the keyword starts, for remove_entries
    stop: int = -1        # just past the entry's ';' (or its '}'), for remove_entries

    @property
    def is_dict(self) -> bool:
        return isinstance(self.value, FoamDict)

    @property
    def directive(self) -> bool:
        return self.key.startswith("#") and not self.quoted


@dataclass
class FoamDict:
    entries: list[Entry] = field(default_factory=list)
    start: int = 0
    end: int = 0
    parent: "FoamDict | None" = field(default=None, repr=False)

    def keys(self) -> list[str]:
        return [e.key for e in self.entries if not e.directive]

    def directives(self) -> list[Entry]:
        return [e for e in self.entries if e.directive]

    def entry(self, key: str) -> Entry | None:
        """The entry ``key`` names, as OpenFOAM finds it: the last literal
        keyword of that name, else the last quoted (regular-expression) keyword
        that matches the whole of it."""
        found = None
        for e in self.entries:
            if not e.quoted and not e.directive and e.key == key:
                found = e
        if found is not None:
            return found
        for e in reversed(self.entries):
            if e.quoted:
                try:
                    if re.fullmatch(e.key, key):
                        return e
                except re.error:
                    continue
        return None

    def get(self, key: str, default=None):
        e = self.entry(key)
        return default if e is None else e.value

    def sub(self, path: str) -> "FoamDict | None":
        """The sub-dictionary at ``a/b/c``, or None."""
        node: FoamDict | None = self
        for part in [p for p in path.split("/") if p]:
            e = node.entry(part) if node is not None else None
            if e is None or not e.is_dict:
                return None
            node = e.value
        return node

    def lookup(self, path: str) -> Entry | None:
        """The entry at ``a/b/key``, or None."""
        head, _, key = path.rpartition("/")
        node = self.sub(head) if head else self
        return None if node is None else node.entry(key)


def _parse_list(toks: list[Tok], i: int, close: str, parent: FoamDict | None):
    items: list = []
    start = toks[i].start
    i += 1
    while i < len(toks):
        t = toks[i]
        if t.kind == "punct" and t.text == close:
            return FoamList(items, start, t.end, square=close == "]"), i + 1
        if t.kind == "punct" and t.text in "([":
            sub, i = _parse_list(toks, i, ")" if t.text == "(" else "]", parent)
            items.append(sub)
            continue
        if t.kind == "punct" and t.text == "{":
            sub, i = _parse_dict(toks, i + 1, t.start, parent)
            items.append(sub)
            continue
        if t.kind == "punct" and t.text in ")]};":
            if t.text == ";":
                items.append(t)
                i += 1
                continue
            raise FoamFormatError(f"unexpected {t.text!r} at offset {t.start}")
        items.append(t)
        i += 1
    raise FoamFormatError(f"unclosed {'(' if close == ')' else '['} at offset {start}")


def _parse_value(toks: list[Tok], i: int, parent: FoamDict):
    """Items up to the ``;`` that ends the entry: ``(items, i after ';', end)``."""
    items: list = []
    while i < len(toks):
        t = toks[i]
        if t.kind == "punct" and t.text == ";":
            return items, i + 1, t.start
        if t.kind == "punct" and t.text in "([":
            sub, i = _parse_list(toks, i, ")" if t.text == "(" else "]", parent)
            items.append(sub)
            continue
        if t.kind == "punct" and t.text == "{":
            sub, i = _parse_dict(toks, i + 1, t.start, parent)
            items.append(sub)
            continue
        if t.kind == "punct" and t.text in ")]}":
            raise FoamFormatError(f"unexpected {t.text!r} at offset {t.start} "
                                  f"(an entry not ended by ';'?)")
        items.append(t)
        i += 1
    raise FoamFormatError("an entry runs to the end of the file without ';'")


#: Directives that take one argument and no ';'.
_ONE_ARG = {"#include", "#sinclude", "#includeIfPresent", "#includeEtc", "#includeFunc",
            "#includeFuncIfPresent", "#inputMode", "#remove", "#default", "#overwrite",
            "#warn", "#error", "#merge", "#word", "#message"}


def _parse_dict(toks: list[Tok], i: int, start: int, parent: FoamDict | None):
    d = FoamDict(start=start, parent=parent)
    while i < len(toks):
        t = toks[i]
        if t.kind == "punct" and t.text == "}":
            if parent is None:
                raise FoamFormatError(f"unexpected '}}' at offset {t.start}")
            d.end = t.end
            return d, i + 1
        if t.kind == "punct" and t.text == ";":
            i += 1
            continue
        if parent is None and (t.kind == "punct" and t.text == "(" or (
                t.kind == "number" and i + 1 < len(toks) and toks[i + 1].text == "(")):
            # A file whose body is a list (polyMesh/boundary, a field of values):
            # one entry with no keyword, its count dropped.
            j = i + 1 if t.kind == "number" else i
            val, k = _parse_list(toks, j, ")", d)
            d.entries.append(Entry("", [val], val.start, val.end))
            i = k
            continue
        if t.kind not in ("word", "string") and not (t.kind == "number"):
            raise FoamFormatError(f"expected a keyword at offset {t.start}, found {t.text!r}")
        key, quoted = t.text, t.kind == "string"
        i += 1
        if key.startswith("#") and not quoted:
            # A directive: one argument (a word, a string or a list), or a block.
            if i < len(toks) and toks[i].kind == "punct" and toks[i].text in "{([":
                if toks[i].text == "{":
                    val, j = _parse_dict(toks, i + 1, toks[i].start, d)
                else:
                    val, j = _parse_list(toks, i, ")" if toks[i].text == "(" else "]", d)
                d.entries.append(Entry(key, val, toks[i].start, toks[j - 1].end,
                                       kstart=t.start, stop=toks[j - 1].end))
                i = j
            elif key in _ONE_ARG or key in ("#eval", "#calc", "#codeStream"):
                if i >= len(toks):
                    raise FoamFormatError(f"{key} with nothing after it")
                d.entries.append(Entry(key, [toks[i]], toks[i].start, toks[i].end,
                                       kstart=t.start, stop=toks[i].end))
                i += 1
            else:
                d.entries.append(Entry(key, [], t.end, t.end))
            continue
        if key.startswith("$") and i < len(toks) and toks[i].kind == "punct" and toks[i].text in ";}":
            # ``$name;`` — or ``$name`` closing its dictionary, which OpenFOAM takes.
            d.entries.append(Entry(key, [], t.end, t.end))
            i += 1 if toks[i].text == ";" else 0
            continue
        if i < len(toks) and toks[i].kind == "punct" and toks[i].text == "{":
            sub, j = _parse_dict(toks, i + 1, toks[i].start, d)
            d.entries.append(Entry(key, sub, toks[i].start, sub.end, quoted=quoted,
                                   kstart=t.start, stop=sub.end))
            i = j
            continue
        vstart = toks[i].start if i < len(toks) else t.end
        items, i, vend = _parse_value(toks, i, d)
        d.entries.append(Entry(key, items, vstart, vend, quoted=quoted,
                               kstart=t.start, stop=vend + 1))
    if parent is not None:
        raise FoamFormatError(f"unclosed {{ at offset {start}")
    d.end = toks[-1].end if toks else 0
    return d, i


def parse(text: str) -> FoamDict:
    """The whole of ``text`` as a :class:`FoamDict`. Raises
    :class:`FoamFormatError` rather than return part of a file."""
    toks = tokens(text)
    d, i = _parse_dict(toks, 0, 0, None)
    if i != len(toks):
        raise FoamFormatError(f"unexpected {toks[i].text!r} at offset {toks[i].start}")
    return d


def read(path: str) -> FoamDict:
    with open(path, encoding="utf-8") as fh:
        return parse(fh.read())


# --------------------------------------------------------------------------- #
# values
# --------------------------------------------------------------------------- #
def words(value) -> list[str]:
    """The plain tokens of an entry's value (lists and dictionaries dropped)."""
    if isinstance(value, Entry):
        value = value.value
    if not isinstance(value, list):
        return []
    return [t.text for t in value if isinstance(t, Tok)]


def word(d: FoamDict | None, key: str) -> str | None:
    """The single word ``key`` holds, or None (absent, a dictionary, or more
    than one token)."""
    if d is None:
        return None
    e = d.entry(key)
    if e is None or e.is_dict:
        return None
    w = [t for t in e.value if isinstance(t, Tok)]
    if len(w) != 1 or len(w) != len(e.value):
        return None
    return w[0].text


class Unresolved(ValueError):
    """A value the reader will not guess: a macro it cannot find, an ``#eval``,
    a dimensioned value with no number."""


def _resolve_macro(d: FoamDict, name: str, seen: set[str]):
    if name in seen:
        raise Unresolved(f"${name} refers to itself")
    seen = seen | {name}
    scope: FoamDict | None = d
    if name.startswith(":"):
        while scope.parent is not None:
            scope = scope.parent
        e = scope.lookup(name[1:].replace(".", "/"))
        if e is None:
            raise Unresolved(f"${name} names no entry")
        return e
    path = name.replace(".", "/")
    while scope is not None:
        e = scope.lookup(path)
        if e is not None:
            return e
        scope = scope.parent
    raise Unresolved(f"${name} names no entry")


def scalar(d: FoamDict | None, key: str, *, _seen: frozenset = frozenset()) -> float | None:
    """The number ``key`` holds, or None when absent. Takes the forms
    OpenFOAM writes: ``nu 1e-05;``, ``nu [0 2 -1 0 0 0 0] 1e-05;`` and the old
    ``nu nu [0 2 -1 0 0 0 0] 1e-05;``, and follows ``$name`` to another entry.
    Raises :class:`Unresolved` on anything else (an ``#eval``, a list)."""
    if d is None:
        return None
    e = d.entry(key)
    if e is None:
        return None
    if e.is_dict:
        raise Unresolved(f"{key} is a dictionary, not a number")
    items = [x for x in e.value if not (isinstance(x, FoamList) and x.square)]
    toks = [x for x in items if isinstance(x, Tok)]
    if len(toks) != len(items) or not toks:
        raise Unresolved(f"{key} is not a single number")
    last = toks[-1]
    if last.kind == "number":
        return float(last.text)
    if last.kind == "word" and last.text.startswith("$"):
        target = _resolve_macro(d, last.text[1:], set(_seen))
        holder = FoamDict(entries=[Entry(key, target.value, 0, 0)], parent=d)
        return scalar(holder, key, _seen=_seen | {last.text})
    if last.kind == "word" and last.text.startswith("#"):
        raise Unresolved(f"{key} is computed ({last.text}); this reader does not evaluate it")
    raise Unresolved(f"{key} holds {last.text!r}, not a number")


def vector(items) -> tuple[float, ...] | None:
    """``(1 0 0)`` as floats, or None."""
    if isinstance(items, FoamList) and items.items and all(
            isinstance(t, Tok) and t.kind == "number" for t in items.items):
        return tuple(float(t.text) for t in items.items)
    return None


# --------------------------------------------------------------------------- #
# writing
# --------------------------------------------------------------------------- #
def set_entry(text: str, path: str, new_value: str) -> str:
    """``text`` with the value of the entry at ``a/b/key`` replaced by
    ``new_value`` (written as given, without the ``;``), every other byte kept.
    Raises KeyError when there is no such entry: a fixture that edits nothing
    is not a control."""
    d = parse(text)
    e = d.lookup(path)
    if e is None or e.directive:
        raise KeyError(path)
    if e.is_dict:
        return text[:e.start] + "{ " + new_value + " }" + text[e.end:]
    return text[:e.start] + new_value + text[e.end:]


def remove_entries(text: str, path: str) -> str:
    """``text`` without any literal entry at ``a/b/key`` (every one of that name
    in that dictionary: OpenFOAM merges a repeated dictionary keyword, so
    replacing the last would leave the first in force)."""
    head, _, key = path.rpartition("/")
    d = parse(text)
    node = d.sub(head) if head else d
    if node is None:
        return text
    spans = [(e.kstart, e.stop) for e in node.entries
             if e.key == key and not e.quoted and not e.directive and e.kstart >= 0]
    for a, b in sorted(spans, reverse=True):
        text = text[:a] + text[b:]
    return text


def put_entry(text: str, path: str, entry_text: str) -> str:
    """``text`` with every literal ``a/b/key`` removed and ``entry_text`` (a
    whole entry, keyword and ``;`` or braces included) added at the end of the
    dictionary ``a/b``. Raises KeyError when ``a/b`` is not a dictionary."""
    head, _, _key = path.rpartition("/")
    text = remove_entries(text, path)
    if not head:
        return text.rstrip("\n") + "\n\n" + entry_text.rstrip() + "\n"
    node = parse(text).sub(head)
    if node is None:
        raise KeyError(head)
    close = node.end - 1
    return text[:close] + "    " + entry_text.rstrip() + "\n" + text[close:]


HEADER = """/*--------------------------------*- C++ -*----------------------------------*\\
  =========                 |
  \\\\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\\\    /   O peration     |
    \\\\  /    A nd           | written by nopekit's cfd-openfoam pack
     \\\\/     M anipulation  |
\\*---------------------------------------------------------------------------*/
"""


def foam_file(cls: str, obj: str, body: str, *, location: str | None = None) -> str:
    """A whole dictionary file: the banner, the ``FoamFile`` header and ``body``."""
    loc = f'    location    "{location}";\n' if location else ""
    return (f"{HEADER}FoamFile\n{{\n    version     2.0;\n    format      ascii;\n"
            f"    class       {cls};\n{loc}    object      {obj};\n}}\n"
            f"// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //\n\n"
            f"{body.rstrip()}\n\n"
            f"// ************************************************************************* //\n")


def case_file(case: str, rel: str) -> str:
    return os.path.join(case, *rel.split("/"))
