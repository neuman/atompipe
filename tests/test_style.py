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
a terminal. And after it (follow-up after phase 3b): the scan read the style,
never the words, so the page said "Pending build: 1 claim needs an article
(C5)" to a newcomer who had never met the paper's word. `TheSiteSaysABuiltPart`
fails on "article" in any site string, in what the build bakes (a recorded
result in the drawer included) and in the template.

Run:  PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_style.py'
"""
from __future__ import annotations

import json
import os
import re
import string
import tempfile
import unittest
from typing import Any, Iterable

import _env
import _projects
from nopekit import page, prose, report, store
from nopekit.models import Claim, ClaimKind, EntryStanding, PhysicalResult, Standing
from test_site_truth import _bracket, bake_project


class _Sample(dict):
    """Sample values for every placeholder a site string formats."""

    VALUES = {"rev": "v0.1", "n": "7", "claims": "claims", "groups": "1 failing (C1)",
              "is_": "are", "checked": "checked", "Checked": "Checked", "k": "2", "req": "4",
              "m": "print-v1", "id": "C1", "gate": "g.one", "authority": "Robin Okafor",
              "milestone": "print-v1", "measured": "0.7", "units": "mm", "limit": "0.5 mm",
              "pct": "40%", "delta": "0.2 mm", "article": "3f2a9c1e0b7d",
              "moves": "thickness 7 -> 8", "size": "3 MiB", "cap": "2 MiB",
              "evaluators": "evaluators", "tier_flag": "", "Pending": "Pending build",
              "need": "need", "who": "Robin Okafor", "path": "photos/fit.jpg"}

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
               "by", "basis", "outcome", "headings", "notices", "ready", "columns", "ground",
               # architecture phase 3b: maps keyed by a station or a claim id,
               # a choice's name, or a source category
               "stop_kind", "stop_kinds", "skipped", "sources"}

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


# --------------------------------------------------------------------------- #
# follow-up after phase 3b: a newcomer reads a built part, never an article
# --------------------------------------------------------------------------- #
#: GLOSSARY §1's word for one built physical object, as a word: the CLI,
#: REPORT.md and JUnit say it, and the site says "a built part" (SPEC 34).
ARTICLE = re.compile(r"\barticles?\b", re.I)

#: Seeded ledgers (`test_export.seeded`) whose pages reach every place the
#: site names a built part: 1 (Pending build, a part to build again, a recorded
#: pass that does not count), 3 (a claim checked on a built part, a counted
#: result) and 5 (a pass that does not count beside Pending build).
#: `test_the_bakes_reach_every_clause` holds them to it.
ARTICLE_SEEDS = (1, 3, 5)


def article_hits(texts: Iterable[tuple[str, str]]) -> list[str]:
    """``where: text`` for each of ``texts`` that says "article"."""
    return [f"{where}: {text}" for where, text in texts if ARTICLE.search(text)]


class TheSiteSaysABuiltPart(_env.EnvCase):
    """(SPEC 34; follow-up after phase 3b) A newcomer reads "a built part"
    where the CLI says "an article": no `HUMAN["site"]` string, no word the
    build bakes into `page.json` or `map.json` and no template string says
    "article" — the readiness sentence and its hardware clause, the hints and
    causes, next steps and the parts to build again, a recorded result in the
    drawer. What slipped through: the page read "Pending build: 1 claim needs
    an article (C5). No claim is checked on any article." — the CLI's clause,
    shared because it passed the style scan — and its drawer "a new article is
    needed, not a rerun", the CLI's words, exempt as a shared producer."""

    @classmethod
    def setUpClass(cls) -> None:
        import test_export
        from test_site_truth import _Res, bake
        cls.root = _bracket(cls)
        cls.baked = [("bracket", bake_project(cls.root))]
        for seed in ARTICLE_SEEDS:
            ledger, stale = test_export.seeded(seed)
            cls.baked.append((f"seed {seed}", bake(ledger, _Res(stale_gates=stale))))

    def baked_words(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for label, baked in self.baked:
            for name, doc in (("map.json", baked.map_doc), ("page.json", baked.page_doc)):
                out += [(f"{label} {where}", text)
                        for where, text in baked_word_strings(doc, name)[0]]
        return out

    def test_no_site_string_says_article(self):
        self.assertEqual(article_hits(human_site_strings()), [])

    def test_no_baked_word_says_article(self):
        words = self.baked_words()
        self.assertGreater(len(words), 200, "the scan reads the bakes' words")
        self.assertEqual(article_hits(words), [])
        self.assertEqual(style_problems(words), [], "a recorded result's words included")

    def test_no_template_string_says_article(self):
        self.assertEqual(article_hits(template_strings()), [])

    def test_the_bakes_reach_every_clause(self):
        """Not vacuous: the bakes say Pending build, a part to build again, a
        claim checked on a built part and none, a pass that does not count, and
        a recorded result counted and not, each in the site's words."""
        text = json.dumps([baked.page_doc for _label, baked in self.baked])
        for needle in ("needs a test on a built part (", "is from an earlier design.",
                       "Checked on a built part: ", "No claim is checked on any built part.",
                       "a pass that does not count", "Test on a built part"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        results = [row["physical"] for _label, baked in self.baked
                   for row in baked.page_doc["claims"].values() if row.get("physical")]
        self.assertTrue([r for r in results if r["counts"]])
        self.assertTrue([r for r in results if r["why"]])

    def test_every_reason_a_result_does_not_count(self):
        """Each branch of `result_facts` on the site: no "article", the style
        held, and `counts` the CLI register's own (one function, so the
        drawer's tone and the technical record's never disagree)."""
        result = PhysicalResult(passed=True, who="Dana <d@x>", channel="interactive",
                                article={"hash": "a" * 64})
        moved = ("config.thickness 7.0 -> 8.0",)
        whys = ("agent-session", "non-interactive", "legacy", "who", "measured",
                "evidence:photos/fit.jpg", "beside", "none", "authority", "export-missing",
                "article-moved", "claim-moved", "article-unjudged", "judgment-moved")
        found: list[str] = []
        for judgment in (False, True):
            for why in whys:
                for moves in (moved, ()):
                    entry = EntryStanding(0, True, False, why, "a" * 64, "moved", moves)
                    claim = Claim(id="C5", statement="s", physical_result=result,
                                  results=(result,),
                                  standing=Standing(f"not-counted:{why}", 0, "a" * 64, moves,
                                                    (entry,)),
                                  **({"kind": ClaimKind.ASSUMPTION, "rationale": "r",
                                      "terminal": "human", "authority": "Dana"} if judgment
                                     else {"kind": ClaimKind.PHYSICAL}))
                    site = report.result_facts(claim, result, register="site")
                    cli = report.result_facts(claim, result)
                    self.assertEqual((site["counts"], site["token"]),
                                     (cli["counts"], cli["token"]))
                    self.assertEqual(site["token"], "not-counted")
                    texts = [(f"{why} judgment={judgment} {key}", site[key])
                             for key in ("why", "recorded", "heading")]
                    self.assertTrue(site["why"], why)
                    found += article_hits(texts) + style_problems(texts)
        failed = PhysicalResult(passed=False, who="Dana <d@x>", channel="agent-session s1",
                                article={"hash": "b" * 64})
        claim = Claim(id="C5", statement="s", kind=ClaimKind.PHYSICAL, physical_result=result,
                      results=(failed, result),
                      standing=Standing("current", 1, "a" * 64, (), (
                          EntryStanding(0, False, False, "", "b" * 64, "current"),
                          EntryStanding(1, True, True, "", "a" * 64, "current")),
                          superseded=(0,)))
        site = report.result_facts(claim, failed, register="site")
        self.assertEqual((site["counts"], site["token"], site["recorded"]),
                         (False, "not-counted", "Recorded by Dana <d@x> from an agent session."))
        self.assertIn("A pass on part aaaaaaaaaaaa replaces this fail", site["why"])
        found += article_hits([("superseded", site["why"])])
        self.assertEqual(found, [])

    def test_a_planted_article_is_caught(self):
        table = dict(report.HUMAN["site"])
        table["rebuild"] = "Rebuild article {article} for {claims}."
        self.assertEqual(len(article_hits(human_site_strings(table))), 1)
        planted = json.loads(json.dumps(self.baked[0][1].page_doc))
        planted["verdict"]["sentence"] += " Pending build: 1 claim needs an article (C5)."
        self.assertEqual(len(article_hits(baked_word_strings(planted, "page.json")[0])), 1)
        self.assertEqual(article_hits([("hash", "Part 3f2a9c1e0b7d is from an earlier "
                                                "design."),
                                       ("heading", "Articles to rebuild")]),
                         ["heading: Articles to rebuild"])


#: The template's strings, read once per process: two classes scan them, and
#: the lexer over every template file is ~0.1 s (the fast tier's budget pays
#: for `TheSiteSaysABuiltPart` with it).
_TEMPLATE_STRINGS: list[tuple[str, str]] = []


#: The words a marketing-page script must never say itself (the two pages):
#: each status word, *ready*, *verified*, *not current*, *article* and the
#: limits sentence come from the bake.
_MARKETING_BANNED = re.compile(
    r"\b(?:ready|checked|open|gap|stale|verified|not current|article|does not mean true)\b",
    re.I)


def marketing_word_problems(sources: dict) -> list[str]:
    """``name: string`` for each string of ``sources`` that says *ready* (any
    string literal, a class name too), or that a reader sees and says a banned
    word (`_MARKETING_BANNED`)."""
    import _template
    out = []
    shown = re.compile(r"(?:\btext|\blabel|\btitle|aria-label|\balt|textContent)\W{0,3}"
                       r"\s*[:=,]\s*\(?\s*$")
    for name, text in sources.items():
        for piece in _template._lex(text):
            if piece[0] != "string":
                continue
            if re.search(r"\bready\b", piece[1], re.I) or (
                    shown.search(piece[2]) and _MARKETING_BANNED.search(piece[1])):
                out.append(f"{name}: {piece[1]!r}")
        for said in _template.prose_literals(text):
            if _MARKETING_BANNED.search(said):
                out.append(f"{name}: {said!r}")
    return out


def template_strings() -> list[tuple[str, str]]:
    """Every human-facing string the site template ships: HTML text and its
    `alt`/`title`/`aria-label`, and the JavaScript literals that read as words."""
    if not _TEMPLATE_STRINGS:
        import _template
        for name, text in _template.template_files(".html").items():
            _TEMPLATE_STRINGS.extend((name, piece) for piece in _template.html_texts(text))
        for name, text in _template.template_files(".js").items():
            _TEMPLATE_STRINGS.extend((name, piece) for piece in _template.prose_literals(text))
    return list(_TEMPLATE_STRINGS)


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
                     "lib/sections.js", "lib/panels.js", "app.js",
                     # The two pages: both shells and the marketing page's script.
                     "engineering/index.html", "marketing/index.html", "marketing.js"):
            self.assertIn(name, names)
        self.assertEqual(style_problems(found), [])

    def test_checked_does_not_mean_true_is_the_bakes_alone(self):
        """Each page says it once, from `verdict.limits`: the template never
        says it, in the root, either page's shell, their scripts or a module."""
        import _template
        scanned = []
        for name, text in {**_template.template_files(".html"),
                           **_template.template_files(".js")}.items():
            if name in ("index.html", "engineering/index.html", "marketing/index.html",
                        "page.js", "marketing.js") or name.startswith("lib/"):
                scanned.append(name)
                with self.subTest(name):
                    self.assertNotIn("does not mean true", text.lower())
        for name in ("engineering/index.html", "marketing/index.html", "marketing.js",
                     "lib/verdict.js"):
            self.assertIn(name, scanned)

    def test_the_marketing_page_says_no_status_word_of_its_own(self):
        """(the two pages) The marketing page's script and the modules the two
        pages share say no status word, no *ready* and no *article* in any
        string: each comes from a baked word (`verdict.headline`, a chip's
        `word`). A literal "ready" in any string at all, class names included;
        the other words in the strings a reader sees. A planted one is caught."""
        import _template
        files = _template.template_files(".js")
        names = ("marketing.js", "lib/verdict.js", "lib/theme.js", "lib/banner.js")
        self.assertEqual(marketing_word_problems({n: files[n] for n in names}), [])
        for planted in ('el("p", { text: "The bracket is ready to print." });',
                        'const cls = "mk-ready";',
                        'el("span", { text: "3 checked" });',
                        'el("p", { text: "Built on the article you printed." });',
                        'el("p", { text: "Checked does not mean true." });',
                        'el("p", { text: "Some results are stale." });'):
            with self.subTest(planted):
                source = {"marketing.js": files["marketing.js"] + "\n" + planted + "\n"}
                self.assertTrue(marketing_word_problems(source), planted)

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
