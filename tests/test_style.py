# SPDX-License-Identifier: Apache-2.0
"""The site's words follow ASD-STE100 and carry no LLM register (architecture
phase 5, SPEC 34, 35).

Scanned, with `prose.register_problems` (an em-dash aside, "not X but Y", a
rhetorical question, a banned word, a contraction) and `prose.long_sentences`
(over 25 words, rule 4.1): every `HUMAN["site"]` string formatted with sample
values; the word keys of the bracket's built `page.json` and `map.json`
(`page.WORD_KEYS`, and every string key is classified); the README block
nopekit writes; the bracket's `site/content/`. Record text is exempt (a claim's
statement, a group's title and line, an evaluator's detail), and so are the
CLI's shared producers and `state.json`'s words, in the glossary's register.
The template's strings are scanned in `TemplateWordsFollowTheStyle` (the
template side of phase 5): every HTML text node and `alt`, `title` and
`aria-label`, and every JavaScript literal that reads as words (two plain words
side by side, outside a class, selector, attribute or comparison slot:
`_template.prose_literals`); comments are exempt.

What slipped through before it: the template held about a hundred em-dashes,
and the words reached the page from the CLI's table, in a register written for
a terminal.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_style.py'
"""
from __future__ import annotations

import json
import os
import string
import tempfile
import unittest
from typing import Any, Iterable

import _env
import _projects
from nopekit import page, prose, report, store
from test_site_truth import _bracket, bake_project


class _Sample(dict):
    """Sample values for every placeholder a site string formats."""

    VALUES = {"rev": "v0.1", "n": "7", "claims": "claims", "groups": "1 failing (C1)",
              "is_": "are", "checked": "checked", "Checked": "Checked", "k": "2", "req": "4",
              "m": "print-v1", "id": "C1", "gate": "g.one", "authority": "Robin Okafor",
              "milestone": "print-v1", "measured": "0.7", "units": "mm", "limit": "0.5 mm",
              "pct": "40%", "delta": "0.2 mm", "article": "3f2a9c1e0b7d",
              "moves": "thickness 7 -> 8", "size": "3 MiB", "cap": "2 MiB",
              "evaluators": "evaluators", "tier_flag": ""}

    def __missing__(self, key: str) -> str:
        return self.VALUES.get(key, "x")


def style_problems(texts: Iterable[tuple[str, str]]) -> list[str]:
    """Each banned-register hit and long sentence in ``texts`` (``(where,
    text)`` pairs)."""
    out: list[str] = []
    for where, text in texts:
        for found in prose.register_problems(text) + prose.long_sentences(text):
            out.append(f"{where}: {found}")
    return out


def human_site_strings(table: Any = None) -> list[tuple[str, str]]:
    """Every `HUMAN["site"]` string, formatted with sample values."""
    out: list[tuple[str, str]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, str):
            out.append((path, string.Formatter().vformat(value, (), _Sample())))
        elif hasattr(value, "items"):
            for key, item in value.items():
                walk(item, f"{path}.{key}")

    walk(report.HUMAN["site"] if table is None else table, "HUMAN.site")
    return out


def baked_word_strings(doc: Any, name: str) -> tuple[list[tuple[str, str]], list[str]]:
    """``(word strings, unclassified keys)`` of a baked document: every string
    at a `page.WORD_KEYS` key (or under `words`), and every string-valued key
    in neither `WORD_KEYS` nor `RECORD_KEYS`. A string's key is the nearest
    one that is not a name in a map of names; prose blocks are the prose's."""
    words: list[tuple[str, str]] = []
    loose: list[str] = []
    id_maps = {"values", "evaluators", "edges", "via", "claims", "tokens", "lanes", "kinds",
               "by", "basis", "outcome", "headings", "notices", "ready", "columns", "ground"}

    def walk(node: Any, key: str, path: str, under_words: bool, in_ids: bool) -> None:
        if isinstance(node, dict):
            for child, value in node.items():
                child_key = key if in_ids else child
                # `edges` is two maps of names deep: {type: {source: [targets]}}.
                nested = in_ids and key == "edges" and isinstance(value, dict)
                walk(value, child_key, f"{path}.{child}", under_words or child == "words",
                     nested or (child in id_maps and isinstance(value, dict) and not in_ids))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                walk(value, key, f"{path}[{i}]", under_words, False)
        elif isinstance(node, str):
            if key == "blocks" or "blocks" in path.split("."):
                return
            if under_words or key in page.WORD_KEYS:
                words.append((f"{name}{path}", node))
            elif key not in page.RECORD_KEYS:
                loose.append(f"{name}{path} ({key})")

    walk(doc, "", "", False, False)
    return words, loose


class SiteWordsFollowTheStyle(_env.EnvCase):
    """(SPEC 34, 35) What nopekit says on the site, held to the style."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _bracket(cls)
        cls.baked = bake_project(cls.root)

    def test_every_site_string(self):
        found = human_site_strings()
        self.assertGreater(len(found), 100, "the table is not where the test looks")
        self.assertEqual(style_problems(found), [])

    def test_the_words_the_build_bakes(self):
        for name, doc in (("map.json", self.baked.map_doc), ("page.json", self.baked.page_doc)):
            with self.subTest(name):
                words, _loose = baked_word_strings(doc, name)
                self.assertTrue(words)
                self.assertEqual(style_problems(words), [])

    def test_checked_does_not_mean_true_once(self):
        text = json.dumps([self.baked.map_doc, self.baked.page_doc])
        self.assertEqual(text.count("does not mean true"), 1)
        self.assertIn("does not mean true", self.baked.page_doc["verdict"]["limits"])

    def test_the_readme_block_and_the_brackets_text(self):
        texts = [("README block", store.README_BADGE_BLOCK)]
        content = os.path.join(_projects.BRACKET, "site", "content")
        for name in sorted(os.listdir(content)):
            if name.endswith(".md"):
                with open(os.path.join(content, name), encoding="utf-8") as fh:
                    found = prose.parse_front_matter(fh.read())
                blocks, problems = prose.parse_markdown(found.body)
                self.assertEqual(problems, [], name)
                texts += [(name, text) for text in prose.blocks_text(blocks)]
        self.assertGreater(len(texts), 10)
        self.assertEqual(style_problems(texts), [])


class ThePlantedRegisterIsCaught(unittest.TestCase):
    """(SPEC 35) One planted violator of each rule is caught, and the words the
    rules allow are not."""

    def test_each_rule(self):
        planted = {
            "em-dash": "The arm holds — most of the time.",
            "not X but Y": "It is not the arm but the bolt that fails.",
            "question": "Does the arm hold? It does.",
            "banned word": "A robust arm holds the pump.",
            "contraction": "The arm doesn't sag.",
        }
        for label, text in planted.items():
            with self.subTest(label):
                found = prose.register_problems(text)
                self.assertTrue(any(f.startswith(label + ":") for f in found), found)
        long = " ".join(["word"] * 26) + "."
        self.assertEqual(len(prose.long_sentences(long)), 1)
        self.assertEqual(prose.long_sentences(" ".join(["word"] * 25) + "."), [])
        self.assertEqual(prose.long_sentences(
            " ".join(["word"] * 20) + " (" + " ".join(["aside"] * 10) + ") C1, C2 and C3."),
            [], "parentheses and ids are not counted")
        for allowed in ("The arm's tip sags 0.70 mm.", "It is not ready. The bolt holds.",
                        "Set 1 - 2 mm: the range."):
            with self.subTest(allowed):
                self.assertEqual(prose.register_problems(allowed), [])

    def test_a_planted_site_string_is_caught(self):
        table = dict(report.HUMAN["site"])
        table["generated"] = "nopekit wrote this — honestly."
        self.assertEqual(len(style_problems(human_site_strings(table))), 2)


class EveryBakedKeyIsClassified(_env.EnvCase):
    """(SPEC 34) Every string-valued key of `page.json` and `map.json` is a word
    the scan reads or a record key it exempts, never neither; the two sets are
    disjoint; a planted key is caught."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.root = _bracket(cls)
        cls.baked = bake_project(cls.root)

    def test_every_key(self):
        self.assertEqual(page.WORD_KEYS & page.RECORD_KEYS, frozenset())
        for name, doc in (("map.json", self.baked.map_doc), ("page.json", self.baked.page_doc)):
            with self.subTest(name):
                self.assertEqual(baked_word_strings(doc, name)[1], [])

    def test_a_planted_key_is_caught(self):
        doc = json.loads(json.dumps(self.baked.page_doc))
        doc["verdict"]["planted_u05"] = "a sentence"
        self.assertEqual(baked_word_strings(doc, "page.json")[1],
                         ["page.json.verdict.planted_u05 (planted_u05)"])


def template_strings() -> list[tuple[str, str]]:
    """Every human-facing string the site template ships: HTML text and its
    `alt`/`title`/`aria-label`, and the JavaScript literals that read as words."""
    import _template
    out: list[tuple[str, str]] = []
    for name, text in _template.template_files(".html").items():
        out += [(name, piece) for piece in _template.html_texts(text)]
    for name, text in _template.template_files(".js").items():
        out += [(name, piece) for piece in _template.prose_literals(text)]
    return out


class TemplateWordsFollowTheStyle(unittest.TestCase):
    """(SPEC 34, 35) Every string the template shows a reader follows the
    style: no banned register and no sentence over 25 words. What slipped
    through before phase 5: the template held about a hundred em-dashes, most
    of them in strings a reader saw."""

    def test_every_template_string(self):
        found = template_strings()
        self.assertGreater(len(found), 150, "the scan reads the template's words")
        names = {name for name, _ in found}
        for name in ("index.html", "technical.html", "page.js", "lib/map.js", "lib/drawer.js",
                     "lib/sections.js", "lib/panels.js", "app.js"):
            self.assertIn(name, names)
        self.assertEqual(style_problems(found), [])

    def test_checked_does_not_mean_true_is_the_bakes_alone(self):
        """The front page says it once, from `verdict.limits`: the template
        never says it."""
        import _template
        for name, text in {**_template.template_files(".html"),
                           **_template.template_files(".js")}.items():
            if name in ("index.html", "page.js") or name.startswith("lib/"):
                with self.subTest(name):
                    self.assertNotIn("does not mean true", text.lower())

    def test_the_heuristic_reads_words_and_skips_names(self):
        import _template
        source = (
            'el("p", { class: "small muted", text: "The arm holds — most of the time." });\n'
            'root.querySelectorAll(".hl, .hl2, .dim");\n'
            'if (row.status === "not ready") go();\n'
            'const url = "https://github.com/neuman/nopekit and more";\n'
            '// "a comment — never scanned"\n'
            'const t = `${n} lines doesn\'t fit`;\n')
        said = _template.prose_literals(source)
        self.assertEqual(said, ["The arm holds — most of the time.", "  lines doesn\'t fit"])
        problems = style_problems([("planted", piece) for piece in said])
        self.assertEqual(len(problems), 2, problems)

    def test_a_planted_html_string_is_caught(self):
        import _template
        page = ('<p>This page isn\'t ready.</p><img alt="A robust bracket">'
                '<script>const x = "ignored — here";</script><!-- a comment — skipped -->'
                '<p>' + " ".join(["word"] * 26) + '.</p>')
        found = style_problems([("planted", t) for t in _template.html_texts(page)])
        self.assertEqual(len(found), 3, found)


if __name__ == "__main__":
    unittest.main()
