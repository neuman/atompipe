# SPDX-License-Identifier: Apache-2.0
"""Reading the site template's sources as a scanner sees them (architecture
phase 5, the template side): its JavaScript as code with every comment and
every string's text blanked (the `${...}` code of a template literal kept), its
string literals with the code just before each, and its HTML's human-facing
text (text nodes, `alt`, `title`, `aria-label`).

Two classes read them: `test_site_truth.TheBrowserComputesNoTruth` (the code,
invariant 14) and `test_style.TemplateWordsFollowTheStyle` (the words, SPEC 34,
35). One lexer for both, so a string the style scan reads is never code the
truth scan skips, or the other way round.

The lexer knows comments, the three quote kinds and `${...}` nesting. It does
not know regular-expression literals: a quote inside one would end the
scanner's string early. The template keeps quotes out of its regex literals
(`TheBrowserComputesNoTruth.test_the_lexer_reads_the_whole_template` holds the
count of what it reads, so a lexer thrown off course goes red).
"""
from __future__ import annotations

import glob
import html.parser
import os
import re

from nopekit import site

TEMPLATE = site.TEMPLATE_DIR


def template_files(suffix: str) -> dict[str, str]:
    """``{relative path: text}`` of every template file ending in ``suffix``."""
    out = {}
    for path in sorted(glob.glob(os.path.join(TEMPLATE, "**", f"*{suffix}"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            out[os.path.relpath(path, TEMPLATE).replace(os.sep, "/")] = fh.read()
    return out


def _lex(source: str):
    """Yield ``("code", text)`` and ``("string", text, before)`` pieces of a
    script, comments dropped; a template literal's `${...}` is yielded as code
    and as one blank in the string's text."""
    i, n = 0, len(source)
    start = 0
    while i < n:
        if source.startswith("//", i):
            yield ("code", source[start:i])
            end = source.find("\n", i)
            i = n if end < 0 else end
            start = i
        elif source.startswith("/*", i):
            yield ("code", source[start:i])
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
            start = i
        elif source[i] in "\"'`":
            yield ("code", source[start:i])
            before = source[max(0, i - 24):i]
            quote, j, buf = source[i], i + 1, []
            while j < n and source[j] != quote:
                if source[j] == "\\":
                    buf.append(source[j + 1:j + 2])
                    j += 2
                elif quote == "`" and source.startswith("${", j):
                    depth, k = 1, j + 2
                    while k < n and depth:
                        depth += {"{": 1, "}": -1}.get(source[k], 0)
                        k += 1
                    yield ("code", " " + source[j + 2:k - 1] + " ")
                    buf.append(" ")
                    j = k
                elif quote != "`" and source[j] == "\n":
                    break
                else:
                    buf.append(source[j])
                    j += 1
            yield ("string", "".join(buf), before)
            i = j + 1
            start = i
        else:
            i += 1
    yield ("code", source[start:n])


def js_code(source: str) -> str:
    """The script's code: comments gone, each string's text replaced by an
    empty string literal, a template literal's `${...}` code kept."""
    out = []
    for piece in _lex(source):
        out.append(piece[1] if piece[0] == "code" else '""')
    return "".join(out)


def js_literals(source: str) -> list[tuple[str, str]]:
    """Every string literal: ``(text, the code just before it)``."""
    return [(p[1], p[2]) for p in _lex(source) if p[0] == "string"]


#: Two plain words side by side: what every sentence has and a class list, a
#: selector, a path or an SVG path does not.
_WORD_PAIR = re.compile(r"(?<![\w$-])[A-Za-z][A-Za-z]+ [A-Za-z][A-Za-z]+(?![\w-])")
#: The code before a literal that makes it a name, never words: a class, a
#: selector, an attribute or event name, a media query, a storage key.
_NAME_SLOT = re.compile(
    r"(?:class:\s*|className\s*=\s*|querySelector(?:All)?\(\s*|closest\(\s*|matchMedia\(\s*"
    r"|setAttribute\(\s*|getAttribute\(\s*|addEventListener\(\s*|classList\.\w+\(\s*"
    r"|createElementNS?\(\s*|getPropertyValue\(\s*|localStorage\.\w+\(\s*|[!=]==?\s*)$")


def prose_literals(source: str) -> list[str]:
    """The literals a reader sees as words: two plain words side by side, not
    in a name slot, not a URL. The heuristic SPEC 34's scan reads (planted
    cases in `test_style.TemplateWordsFollowTheStyle`)."""
    out = []
    for text, before in js_literals(source):
        if _NAME_SLOT.search(before) or "://" in text:
            continue
        if _WORD_PAIR.search(text):
            out.append(text)
    return out


class _Text(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if name in ("alt", "title", "aria-label") and value:
                self.out.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.out.append(" ".join(data.split()))


def html_texts(source: str) -> list[str]:
    """An HTML file's human-facing text: text nodes (outside script and
    style) and the `alt`, `title` and `aria-label` attributes. Comments are
    skipped. Adjacent text runs inside one element stay apart, so a sentence
    split by an inline tag reads as two pieces."""
    parser = _Text()
    parser.feed(source)
    return parser.out
