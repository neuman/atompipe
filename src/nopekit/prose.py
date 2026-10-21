# SPDX-License-Identifier: Apache-2.0
"""prose.py — the agent's text on the site, and the scans that hold it
(architecture phase 5, SPEC decisions 30, 34 and 35).

The site persuades in one place: the prose an agent writes in
``site/content/<board>.md``, ``intro.md`` and ``next.md``. Everything else on
the page is baked from the resolution. This module is what keeps that one place
honest, mechanically, with three guards and no judgement of its own:

* **the stamp** (`stamp_digest`, `stamp_text`): a piece of prose carries
  ``as_of`` in its front matter, the digest of the status tokens of the claims
  it is about at the moment it was written. When the resolution of those claims
  moves, the digest moves and the page says the text was written before the
  latest results. A stamp guards age, never correctness.
* **the number scan** (`number_pool`, `scan_numbers`, `matches`): every number
  in the prose must match a number the build bakes, at the prose's precision.
  A number nothing baked holds is marked on the page and named by the build.
* **the style scans** (`register_problems`, `long_sentences`): the banned
  register of SPEC 35 and the sentence length of ASD-STE100 rule 4.1, over the
  template, the words the build bakes and the prose. Two rules of SPEC 35 have
  no pattern without false positives (lists of three for rhythm, a closing line
  that restates the paragraph): they are review-only, and SITE_CONTRACT says so.

What slipped through before it: nothing kept prose from saying a claim passes
after it failed. The reference page's text was hand-written beside a map that
moved, and nothing compared the two.

Pure functions over strings and JSON values: no clock, no git, no file reads
(``exists`` is the caller's), so `site stamp`, `site build` and the style tests
all import it without the page machinery. The markdown is parsed here, at build
time, into typed blocks and runs; the browser never receives HTML from prose.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import re
from typing import Any, Callable, Iterable, NamedTuple

#: ASD-STE100 rule 4.1: a sentence in descriptive writing has at most 25 words.
#: *Rejected:* rule 5.1's 20 (that rule is for procedures, and the site has no
#: procedures; the imperative next steps are one-line commands).
SENTENCE_MAX_WORDS = 25

#: Words that, after a number and one space, are read as its unit (``15 N``).
#: Letters JOINED to a number are always read as its unit (``12mm``, ``12L/h``,
#: ``40Nm``) unless they are an identifier suffix (`IDENTIFIER_SUFFIXES`); a
#: word after a space that is not here stands alone (``2 bolts``), and so does
#: the number. A unit with a slash counts when its first part is here
#: (``USD/unit``). *Rejected:* any word after a space as a unit (``2 bolts``
#: would read as the unit ``bolts`` and never match a count); letters joined to
#: a number read as an identifier unless listed here, the first cut, which left
#: ``12L/h`` and ``40Nm`` unscanned and unmarked (review of phase 5).
UNIT_WORDS = frozenset({"mm", "cm", "m", "km", "um", "µm", "nm", "in", "ft", "g", "kg", "mg",
                        "lb", "lbf", "N", "kN", "Nm", "Pa", "kPa", "MPa", "GPa", "bar", "mbar",
                        "psi", "s", "ms", "min", "h", "Hz", "kHz", "rpm", "V", "mV", "A", "mA",
                        "W", "kW", "Wh", "kWh", "mAh", "Ah", "J", "kJ", "K", "x", "°", "°C",
                        "°F", "deg", "rad", "dB", "L", "mL", "USD", "EUR"})

#: Letters joined to a number that make it an identifier, never a value: an
#: ordinal (``1st``, ``2nd``) or a dimension (``3D``). A letter before the
#: digits (``M3``, ``C1``, ``v0.1``) already keeps a number from being read.
IDENTIFIER_SUFFIXES = frozenset({"st", "nd", "rd", "th", "D"})

#: SPEC 35's banned words, as the register scan names them.
BANNED_WORDS = ("delve", "robust", "seamless", "crucial", "honest")

#: Keys whose numbers are structure, never a value a reader is shown: an order
#: index, a row, a column, a tier or a list index is not a result, so prose that
#: says "1" must not match it. What slipped through (review of phase 5): `row`,
#: `index` and `tier` were pooled, so every small integer in prose matched one.
#: `bytes` (the two pages: a model file's size, the marketing viewer's loading
#: bar) is a file's size, never a result: "6,481,920" in a story is no value of
#: the design. A bound figure's ``scale``, ``marks`` and ``binding`` (issue #15,
#: B.4.3, in ``state.json``'s view rows): a colour range is a pack constant
#: times a result, a mark's ``at`` a place on the picture, and neither is a
#: result a sentence may quote (a colour bound of 0.02 m/s would vouch for
#: "0.02 m/s" in prose about anything). And ``page.json``'s ``figures``, the
#: representation's ``figure`` and a figure's ``chart`` (P1.4): a figure's
#: numbers are a picture's (its scale, its marks, its file's size), and a
#: chart's limit and point are the floor's, which the floor rows already pool.
POOL_EXCLUDED_KEYS = frozenset({"schema", "outline", "order", "column", "columns", "severity",
                                "rank", "row", "index", "tier", "bytes", "scale", "marks",
                                "binding", "figures", "figure", "chart"})

#: Keys whose numbers (and every number under them) are counts: how many claims,
#: gaps or evaluators. A count matches only a number written with no unit, so
#: "3 claims" matches a tally of 3 and "3 mm" never does. *Rejected:* leaving
#: counts out of the pool (a true "3 of 7 claims are checked" would be marked);
#: pooling them as values, the first cut, which let "the tip sags 3 mm" match a
#: tally (review of phase 5).
POOL_COUNT_KEYS = frozenset({"n", "errored", "counts", "by_key", "ground", "tally", "legend",
                             "n_claims", "n_critical", "n_gaps", "n_gates"})

#: Keys whose numbers are fractions (a margin of -0.3994): they match a
#: percentage (``40%``) or a bare number, never a number with another unit.
POOL_FRACTION_KEYS = frozenset({"margin", "fraction"})

#: The pool's tags beside a unit: a count, a fraction, and a value whose units
#: no baked key states (which matches a number in any unit).
COUNT = "#count"
FRACTION = "#fraction"
UNSTATED = ""

_FENCE = "---"


# --------------------------------------------------------------------------- #
# front matter and the stamp
# --------------------------------------------------------------------------- #
class FrontMatter(NamedTuple):
    """A prose file read: ``as_of`` (or None), every ``key: value`` it held,
    the ``body`` after it, and the ``problems`` (an unknown key, an unclosed
    block)."""

    as_of: str | None
    keys: dict
    body: str
    problems: tuple


def _lines(text: str) -> list[str]:
    return text.splitlines(keepends=True)


def _bare(line: str) -> str:
    return line.rstrip("\r\n")


def parse_front_matter(text: str) -> FrontMatter:
    """The front matter of a prose file: optional, exactly a first line ``---``,
    ``key: value`` lines, and a closing ``---``. Only ``as_of`` is read; an
    unknown key is a problem and is kept. With no closing ``---`` the text reads
    as having no front matter, and that is a problem too."""
    lines = _lines(text)
    if not lines or _bare(lines[0]).strip() != _FENCE:
        return FrontMatter(None, {}, text, ())
    keys: dict[str, str] = {}
    problems: list[str] = []
    for i, line in enumerate(lines[1:], start=1):
        bare = _bare(line)
        if bare.strip() == _FENCE:
            for key in keys:
                if key != "as_of":
                    problems.append(f"front matter key {key!r} is not read (only as_of)")
            as_of = keys.get("as_of", "").strip() or None
            return FrontMatter(as_of, keys, "".join(lines[i + 1:]), tuple(problems))
        if not bare.strip():
            continue
        key, sep, value = bare.partition(":")
        if not sep or not key.strip():
            problems.append(f"front matter line {i + 1} is not 'key: value'")
            continue
        keys[key.strip()] = value.strip()
    return FrontMatter(None, {}, text, ("the front matter has no closing --- line, so it is "
                                        "read as text",))


def stamp_text(text: str, as_of: str) -> str:
    """``text`` with its ``as_of`` set to ``as_of``, every other byte kept (CRLF
    included): the value on an existing ``as_of:`` line is replaced; else
    ``as_of`` becomes the first line of existing front matter; else a front
    matter block is put before the text."""
    newline = "\r\n" if "\r\n" in text else "\n"
    lines = _lines(text)
    found = parse_front_matter(text)
    closed = bool(lines) and _bare(lines[0]).strip() == _FENCE and not any(
        "closing" in p for p in found.problems)
    if closed:
        for i, line in enumerate(lines[1:], start=1):
            bare = _bare(line)
            if bare.strip() == _FENCE:
                break
            key, sep, _value = bare.partition(":")
            if sep and key.strip() == "as_of":
                ending = line[len(bare):]
                lines[i] = f"{key}: {as_of}{ending}"
                return "".join(lines)
        ending = lines[0][len(_bare(lines[0])):] or newline
        lines.insert(1, f"as_of: {as_of}{ending}")
        return "".join(lines)
    return f"{_FENCE}{newline}as_of: {as_of}{newline}{_FENCE}{newline}{newline}{text}"


def stamp_digest(subject: str, tokens: dict) -> str:
    """The stamp: the first 16 hex of sha256 over ``subject`` and its claims'
    tokens (``{claim id: token[:marks]}``, plus ``_readiness`` and ``_m:<id>``
    for intro and next). Membership is in the keys, so a regroup moves it."""
    text = json.dumps(tokens, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(f"nopekit-stamp-v1\n{subject}\n{text}".encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# the markdown subset
# --------------------------------------------------------------------------- #
#: A claim-shaped word: capitals then digits. Linked only when that claim exists.
_CLAIM_WORD = re.compile(r"(?<![\w.-])([A-Z]+[0-9]+)(?![\w-])")

_INLINE = re.compile(
    r"`(?P<code>[^`]+)`"
    r"|\*\*(?P<bold>.+?)\*\*"
    r"|\*(?P<ital>[^*\s](?:[^*]*[^*\s])?)\*"
    r"|\[(?P<ltext>[^\]]+)\]\((?P<href>[^)\s]+)(?:\s+\"[^\"]*\")?\)")

_FIGURE = re.compile(r'^!\[(?P<alt>[^\]]*)\]\((?P<src>[^)\s"]+)(?:\s+"(?P<cap>[^"]*)")?\)\s*$')
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_BULLET = re.compile(r"^\s{0,3}[-*]\s+(.*)$")
_NUMBERED = re.compile(r"^\s{0,3}\d+[.)]\s+(.*)$")
_QUOTE = re.compile(r"^\s{0,3}>\s?(.*)$")
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
_SUBSET = "not in the page's markdown subset"


def _href_ok(href: str) -> bool:
    if href.startswith(("https://", "http://")) or href.startswith("#"):
        return True
    if _SCHEME.match(href) or href.startswith(("/", "\\")):
        return False
    return ".." not in href.replace("\\", "/").split("/")


def _site_path_ok(path: str) -> bool:
    if not path or _SCHEME.match(path) or path.startswith(("/", "\\")):
        return False
    return ".." not in path.replace("\\", "/").split("/")


def _claim_runs(text: str, attrs: dict, claims: frozenset) -> list[dict]:
    out: list[dict] = []
    at = 0
    for found in _CLAIM_WORD.finditer(text):
        if found.group(1) not in claims:
            continue
        if found.start() > at:
            out.append({"t": text[at:found.start()], **attrs})
        out.append({"t": found.group(1), "claim": found.group(1), **attrs})
        at = found.end()
    if at < len(text):
        out.append({"t": text[at:], **attrs})
    return out


def _inline(text: str, claims: frozenset, problems: list[str]) -> list[dict]:
    """``text`` as runs: code, bold, italic, links, claim ids, plain text."""
    runs: list[dict] = []
    at = 0
    for found in _INLINE.finditer(text):
        if found.start() > at:
            runs += _claim_runs(text[at:found.start()], {}, claims)
        if found.group("code") is not None:
            runs.append({"t": found.group("code"), "code": True})
        elif found.group("bold") is not None:
            runs += _claim_runs(found.group("bold"), {"b": True}, claims)
        elif found.group("ital") is not None:
            runs += _claim_runs(found.group("ital"), {"i": True}, claims)
        else:
            href = found.group("href")
            if _href_ok(href):
                runs.append({"t": found.group("ltext"), "href": href})
            else:
                problems.append(f"link {href!r} is not https, http, a site path or an #anchor: "
                                f"it is shown as text")
                runs += _claim_runs(found.group("ltext"), {}, claims)
        at = found.end()
    if at < len(text):
        runs += _claim_runs(text[at:], {}, claims)
    return [run for run in runs if run.get("t")]


def parse_markdown(body: str, *, exists: Callable[[str], bool] = lambda _p: True,
                   claims: Iterable[str] = (),
                   misplaced: Callable[[str], str] = lambda _p: ""
                   ) -> tuple[list[dict], list[str]]:
    """``body`` as typed blocks (``h3``, ``h4``, ``p``, ``quote``, ``ul``,
    ``ol``, ``figure``) of runs, and the problems found. Never HTML: the page
    builds DOM from the runs. ``exists(path)`` says whether a figure's file is
    under ``site/``; ``claims`` are the claim ids a word may link to.
    ``misplaced(path)`` is why a figure's path is no place for a figure, or
    ``""``: such a figure reads missing whether its file exists or not, and the
    reason is its problem (issue #15: a figure under ``site/assets/``, which
    the build cleans).

    The subset: ``#`` and ``##`` are ``h3`` (the section's ``h2`` is the
    board's title), ``###`` and deeper ``h4``; paragraphs split on blank lines;
    ``- `` and ``* `` items, ``1. `` items, one level deep; ``> `` quotes; a
    paragraph that is only an image is a figure; inline code, bold, italic and
    links (``https:``, ``http:``, a site path, ``#anchor``). Raw HTML, tables
    and fenced code stay literal text, each with a problem."""
    claim_set = frozenset(claims)
    problems: list[str] = []
    blocks: list[dict] = []
    para: list[str] = []
    items: list[str] = []
    item_kind = ""
    quote: list[str] = []
    fenced = False

    def flush_para() -> None:
        if not para:
            return
        text = " ".join(line.strip() for line in para)
        para.clear()
        figure = _FIGURE.match(text)
        if figure:
            src = figure.group("src")
            if not _site_path_ok(src):
                problems.append(f"figure {src!r} is not a path under site/: it is shown as text")
                blocks.append({"type": "p", "runs": [{"t": text}]})
                return
            why = misplaced(src)
            missing = bool(why) or not exists(src)
            if why:
                problems.append(f"figure {src} {why}")
            elif missing:
                problems.append(f"figure {src} is not under site/")
            blocks.append({"type": "figure", "src": src, "alt": figure.group("alt"),
                           "caption": _inline(figure.group("cap") or "", claim_set, problems),
                           "missing": missing})
            return
        if text.lstrip().startswith("<"):
            problems.append(f"raw HTML is {_SUBSET}: it is shown as text")
            blocks.append({"type": "p", "runs": [{"t": text}]})
            return
        if text.lstrip().startswith("|"):
            problems.append(f"a table is {_SUBSET}: it is shown as text")
            blocks.append({"type": "p", "runs": [{"t": text}]})
            return
        blocks.append({"type": "p", "runs": _inline(text, claim_set, problems)})

    def flush_items() -> None:
        nonlocal item_kind
        if items:
            blocks.append({"type": item_kind,
                           "items": [_inline(item, claim_set, problems) for item in items]})
        items.clear()
        item_kind = ""

    def flush_quote() -> None:
        if quote:
            blocks.append({"type": "quote",
                           "runs": _inline(" ".join(q.strip() for q in quote), claim_set,
                                           problems)})
        quote.clear()

    def flush_all() -> None:
        flush_para()
        flush_items()
        flush_quote()

    for raw in body.splitlines():
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            if not fenced:
                flush_all()
                problems.append(f"a fenced code block is {_SUBSET}: it is shown as text")
            fenced = not fenced
            continue
        if fenced:
            blocks.append({"type": "p", "runs": [{"t": line, "code": True}]} if line.strip()
                          else {"type": "p", "runs": []})
            continue
        if not line.strip():
            flush_all()
            continue
        heading = _HEADING.match(line)
        if heading:
            flush_all()
            level = len(heading.group(1))
            blocks.append({"type": "h3" if level <= 2 else "h4",
                           "runs": _inline(heading.group(2), claim_set, problems)})
            continue
        bullet, numbered = _BULLET.match(line), _NUMBERED.match(line)
        if bullet or numbered:
            kind = "ul" if bullet else "ol"
            flush_para()
            flush_quote()
            if item_kind and item_kind != kind:
                flush_items()
            item_kind = kind
            items.append((bullet or numbered).group(1))
            continue
        quoted = _QUOTE.match(line)
        if quoted:
            flush_para()
            flush_items()
            quote.append(quoted.group(1))
            continue
        if items and raw[:1] in (" ", "\t"):
            items[-1] += " " + line.strip()
            continue
        flush_items()
        flush_quote()
        para.append(line)
    flush_all()
    return [b for b in blocks if b.get("runs") != [] or b["type"] != "p"], problems


# --------------------------------------------------------------------------- #
# the number scan
# --------------------------------------------------------------------------- #
class Pool(NamedTuple):
    """The absolute values of every number the build bakes, sorted
    (``values``), and the same values by tag (``tagged``): a unit as baked
    (``mm``), `COUNT`, `FRACTION` or `UNSTATED`."""

    values: tuple
    tagged: Any = None

    def near(self, x: float, tolerance: float, tag: str | None = None) -> bool:
        values = self.values if tag is None else (self.tagged or {}).get(tag, ())
        i = bisect.bisect_left(values, x - tolerance)
        return i < len(values) and values[i] <= x + tolerance


def unit_key(unit: Any) -> str:
    """A unit as the pool compares it: stripped, micro written ``u``."""
    return str(unit or "").strip().replace("µ", "u").replace("μ", "u")


def number_pool(docs: Iterable[Any]) -> Pool:
    """Every finite int or float leaf of ``docs`` (bools excluded), as its
    absolute value, except under `POOL_EXCLUDED_KEYS`, each tagged: a count
    under `POOL_COUNT_KEYS`, a fraction under `POOL_FRACTION_KEYS`, else the
    ``units`` (or ``unit``) string of the object that holds it, `UNSTATED` when
    it states none. Numbers inside strings are not collected: a baked sentence
    is formatted from leaves already here, and an authored string is the
    claim's words, not a result."""
    found: dict[str, set[float]] = {}

    def walk(node: Any, tag: str) -> None:
        if isinstance(node, dict):
            stated = node.get("units", node.get("unit"))
            if isinstance(stated, str):
                own = unit_key(stated)
            else:
                own = tag if tag in (COUNT, FRACTION) else UNSTATED
            for key, value in node.items():
                if key in POOL_EXCLUDED_KEYS:
                    continue
                walk(value, COUNT if key in POOL_COUNT_KEYS or own == COUNT
                     else FRACTION if key in POOL_FRACTION_KEYS else own)
        elif isinstance(node, (list, tuple)):
            for value in node:
                walk(value, tag)
        elif isinstance(node, bool):
            return
        elif isinstance(node, (int, float)) and math.isfinite(node):
            found.setdefault(tag, set()).add(abs(float(node)))

    for doc in docs:
        walk(doc, UNSTATED)
    every = sorted({x for values in found.values() for x in values})
    return Pool(tuple(every), {tag: tuple(sorted(values)) for tag, values in found.items()})


#: A number in prose: an optional sign, digits (with thousands separators) and
#: an optional fraction, or a fraction alone (``.9``), an optional exponent
#: (``1e3``), then a percent sign, or letters joined to it (its unit, or an
#: identifier), or a word after one space (its unit, or the next word). What
#: slipped through (review of phase 5): ``.9 mm`` and ``1e3`` were never read.
_UNIT_CHARS = r"[A-Za-z°µμ]+(?:/[A-Za-z°µμ]+)*"
_NUMBER = re.compile(
    r"(?<![A-Za-z0-9_.])(?P<sign>[−-])?"
    r"(?:(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?|\.(?P<lead>\d+))"
    r"(?:[eE](?P<exp>[+-]?\d+)(?![A-Za-z0-9]))?"
    rf"(?:(?P<pct>\s?%)|(?P<joined>{_UNIT_CHARS})|(?P<space>\s)(?P<word>{_UNIT_CHARS}))?")


def _precision(number: str) -> int:
    """The decimals ``number`` is written to (``0.70`` 2, ``1e3`` -3)."""
    mantissa, _e, exponent = number.replace("E", "e").partition("e")
    decimals = len(mantissa.split(".", 1)[1]) if "." in mantissa else 0
    try:
        return decimals - int(exponent or 0)
    except ValueError:
        return decimals


def matches(text: str, decimals: int, percent: bool, pool: Pool, unit: str = "") -> bool:
    """Whether ``text`` (a number as written: ``1,200``, ``−0.40``, ``1e3``)
    matches a pooled value at its precision: within half a unit of its last
    written decimal, sign-insensitive (prose says "40% past the limit" over a
    margin of −0.3994). A number with no unit matches any value; one with a
    unit only a value in that unit or in units no key states, never a count or
    a fraction; a percentage a fraction times 100, an unstated value as written
    or times 100, or a value in ``%``. What slipped through (review of phase 5):
    units were never compared, so "3 mm" matched a count of 3 claims and "40%"
    a limit of 40 N."""
    try:
        x = abs(float(text.replace(",", "").replace("−", "-")))
    except ValueError:
        return False
    tolerance = 0.5 * 10.0 ** (-int(decimals))
    slack = 1e-12 * max(1.0, x)
    tol = tolerance + slack
    if percent:
        return (pool.near(x / 100.0, tol / 100.0, FRACTION)
                or pool.near(x / 100.0, tol / 100.0, UNSTATED)
                or pool.near(x, tol, UNSTATED) or pool.near(x, tol, "%"))
    key = unit_key(unit)
    if not key:
        return pool.near(x, tol)
    return pool.near(x, tol, key) or pool.near(x, tol, UNSTATED)


def _is_unit_word(word: str) -> bool:
    return word in UNIT_WORDS or word.split("/", 1)[0] in UNIT_WORDS


def _numbers_in(text: str) -> list[tuple[int, int, str, str, int, bool, str]]:
    """``(start, end, number, unit, decimals, percent, written)`` for each
    number ``text`` holds that the scan reads."""
    out = []
    for found in _NUMBER.finditer(text):
        joined, word = found.group("joined"), found.group("word")
        if joined is not None and joined in IDENTIFIER_SUFFIXES:
            continue                                    # an identifier: 3D, 1st
        if found.group("lead") is not None:
            mantissa = "." + found.group("lead")
        else:
            mantissa = found.group("int") + (
                "." + found.group("frac") if found.group("frac") else "")
        number = (found.group("sign") or "") + mantissa + (
            "e" + found.group("exp") if found.group("exp") else "")
        decimals = _precision(number.replace(",", ""))
        if found.group("pct"):
            unit, end = "%", found.end()
        elif joined is not None:
            unit, end = joined, found.end()
        elif word is not None and _is_unit_word(word):
            unit, end = word, found.end()
        else:
            unit = ""
            end = found.start("space") if word is not None else found.end()
        out.append((found.start(), end, number, unit, decimals, unit == "%",
                    text[found.start():end]))
    return out


_SCANNED_BLOCKS = ("h3", "h4", "p", "quote")


def all_runs(blocks: Iterable[dict]) -> list[dict]:
    """Every run of ``blocks``: a block's runs, each list item's, a figure's
    caption."""
    out: list[dict] = []
    for block in blocks or ():
        if block.get("type") in ("ul", "ol"):
            for item in block.get("items") or ():
                out += list(item or ())
        elif block.get("type") == "figure":
            out += list(block.get("caption") or ())
        else:
            out += list(block.get("runs") or ())
    return out


def number_runs(blocks: Iterable[dict]) -> list[dict]:
    """The number runs of ``blocks`` (`scan_numbers`' ``{"num", "unit",
    "match", "t"}``), in text order."""
    return [run for run in all_runs(blocks) if "num" in run]


def run_matches(run: dict, pool: Pool) -> bool:
    """Whether a baked number run matches ``pool``, by the rule the scan used:
    what a reader of a baked page checks its ``match`` flags with."""
    number = str(run.get("num", ""))
    unit = str(run.get("unit", "") or "")
    return matches(number, _precision(number.replace(",", "")), unit == "%", pool,
                   "" if unit == "%" else unit)


def scan_numbers(blocks: list[dict], pool: Pool) -> tuple[list[dict], list[str]]:
    """``blocks`` with each text run split into text and number runs
    (``{"num", "unit", "match", "t"}``), and the numbers no pooled value
    matches, in text order (``"0.71 mm"``). Scanned: headings, paragraphs,
    quotes, list items and captions. Never scanned: code, claim ids, link
    targets, figure paths, the front matter (`parse_front_matter` has removed
    it)."""
    unmatched: list[str] = []

    def split(runs: list[dict]) -> list[dict]:
        out: list[dict] = []
        for run in runs:
            if run.get("code") or "claim" in run or "num" in run:
                out.append(run)
                continue
            text = run.get("t", "")
            attrs = {k: v for k, v in run.items() if k != "t"}
            at = 0
            for start, end, number, unit, decimals, percent, written in _numbers_in(text):
                if start > at:
                    out.append({"t": text[at:start], **attrs})
                ok = matches(number, decimals, percent, pool, "" if percent else unit)
                out.append({"num": number, "unit": unit, "match": ok, "t": written, **attrs})
                if not ok:
                    unmatched.append(number + (("" if unit == "%" else " ") + unit if unit else ""))
                at = end
            if at < len(text):
                out.append({"t": text[at:], **attrs})
        return out

    result: list[dict] = []
    for block in blocks:
        block = dict(block)
        if block.get("type") in _SCANNED_BLOCKS:
            block["runs"] = split(block.get("runs") or [])
        elif block.get("type") in ("ul", "ol"):
            block["items"] = [split(item) for item in block.get("items") or []]
        elif block.get("type") == "figure":
            block["caption"] = split(block.get("caption") or [])
        result.append(block)
    return result, unmatched


def runs_text(runs: Iterable[dict], *, code: bool = False) -> str:
    """The text of ``runs`` as a reader reads it, code spans left out unless
    ``code``."""
    return "".join(str(run.get("t", run.get("num", ""))) for run in runs
                   if code or not run.get("code"))


def blocks_text(blocks: Iterable[dict]) -> list[str]:
    """Each block's text (each list item on its own), code left out — what the
    style scans read."""
    out: list[str] = []
    for block in blocks:
        if block.get("type") in ("ul", "ol"):
            out += [runs_text(item) for item in block.get("items") or []]
        elif block.get("type") == "figure":
            out += [block.get("alt") or "", runs_text(block.get("caption") or [])]
        else:
            out.append(runs_text(block.get("runs") or []))
    return [text for text in out if text.strip()]


# --------------------------------------------------------------------------- #
# the style scans (SPEC 34, 35)
# --------------------------------------------------------------------------- #
_REGISTER: tuple[tuple[str, re.Pattern], ...] = (
    ("em-dash", re.compile(r"—|\s–\s|\s--\s")),
    ("not X but Y", re.compile(r"\bnot\b[^.!?;:]{1,60}?\bbut\b", re.I)),
    ("question", re.compile(r"\?(?=\s|$)")),
    ("banned word", re.compile(r"\b(delve[sd]?|delving|robust(?:ly|ness)?|seamless(?:ly)?|"
                               r"crucial(?:ly)?|honest(?:ly|y)?)\b", re.I)),
    ("contraction", re.compile(r"\b\w+n['’]t\b|\b\w+['’](?:re|ve|ll|d|m)\b|"
                               r"\b(?:it|that|there|what|here|let|who|where|he|she)['’]s\b",
                               re.I)),
)


def register_problems(text: str) -> list[str]:
    """Every banned-register hit in ``text`` (SPEC 35), each ``"<label>:
    <the words around it>"``: an em-dash aside, "not X but Y", a question, a
    banned word, a contraction (a possessive ``'s`` on a noun is allowed)."""
    out: list[str] = []
    for label, pattern in _REGISTER:
        for found in pattern.finditer(text):
            start, end = max(0, found.start() - 24), min(len(text), found.end() + 24)
            out.append(f"{label}: {' '.join(text[start:end].split())}")
    return out


_SENTENCE_END = re.compile(r"(?<=[.!?:;])\s+")
_ID_WORD = re.compile(r"^[A-Z]+\d+[,;.:)]?$")


def _word_count(sentence: str) -> int:
    count = 0
    depth = 0
    in_code = False
    for token in sentence.split():
        opens, closes = token.count("("), token.count(")")
        ticks = token.count("`")
        skip = depth > 0 or opens > 0 or in_code or ticks > 0
        depth = max(0, depth + opens - closes)
        if ticks % 2 == 1:
            in_code = not in_code
        if skip:
            continue
        if "://" in token or token.startswith("www.") or _ID_WORD.match(token):
            continue
        if any(ch.isalpha() for ch in token):
            count += 1
    return count


def long_sentences(text: str, limit: int = SENTENCE_MAX_WORDS) -> list[str]:
    """The sentences of ``text`` over ``limit`` words (ASD-STE100 rule 4.1),
    each ``"<n> words: <its start>"``. Words are whitespace tokens with a letter;
    tokens in parentheses, code spans and URLs, and ids (``C1``), are not
    counted."""
    out: list[str] = []
    for sentence in _SENTENCE_END.split(" ".join(text.split())):
        n = _word_count(sentence)
        if n > limit:
            out.append(f"{n} words: {sentence[:60]}{'...' if len(sentence) > 60 else ''}")
    return out


__all__ = [
    "SENTENCE_MAX_WORDS", "UNIT_WORDS", "IDENTIFIER_SUFFIXES", "BANNED_WORDS",
    "POOL_EXCLUDED_KEYS", "POOL_COUNT_KEYS", "POOL_FRACTION_KEYS", "COUNT", "FRACTION",
    "UNSTATED", "FrontMatter", "Pool",
    "parse_front_matter", "stamp_text", "stamp_digest", "parse_markdown",
    "number_pool", "scan_numbers", "matches", "unit_key", "all_runs", "number_runs",
    "run_matches", "runs_text", "blocks_text",
    "register_problems", "long_sentences",
]
