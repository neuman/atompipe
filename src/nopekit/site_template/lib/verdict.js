// SPDX-License-Identifier: Apache-2.0
// verdict.js: the verdict as the two pages draw it (the engineering page's
// hero and the marketing page's), from `page.json`'s `verdict` alone.
//
// One module for both pages, so the marketing page can never draw a softer
// verdict than the engineering page: the same sentence, the same tally chips
// with the same glyph and word, the same limits line. Every word and every
// count is the bake's (`report`'s readiness sentence and `count_bits`); this
// file maps them to the DOM and decides none of them (invariants 12 and 14).
// What it closes: a page that leads with a render while a claim fails, with
// its verdict drawn by a copy of the engineering page's code that drifts.

import { el } from "./dom.js";
import { lookOf } from "./format.js";

/** The sentence's lead, up to its first full stop: what the engineering page
 *  sets in bold. The marketing page shows the bake's `headline`, and falls
 *  back to this cut only on data from a build before `headline` was baked. */
export function leadOf(sentence) {
  const text = String(sentence || "");
  const cut = text.search(/\.(\s|$)/);
  return cut >= 0 ? text.slice(0, cut + 1) : text;
}

/** The bake's tally as chips: glyph and word on each (`lookOf(t.key)`, the
 *  label as baked). The tally carries no marks: a mark is a claim's, and each
 *  claim's own chip carries it. */
export function tallyList(verdict, { cls = "tally" } = {}) {
  const tally = (verdict && verdict.tally) || [];
  if (!tally.length) return null;
  return el("ul", { class: cls }, ...tally.map((t) => {
    const tl = lookOf(t.key, { errored: t.errored > 0 });
    return el("li", { class: `nk-chip tone-${tl.tone}` },
      el("span", { class: "nk-glyph", "aria-hidden": "true", text: tl.glyph }),
      el("span", { class: "nk-word", text: t.label }));
  }));
}

/** The engineering page's verdict: the sentence, with its lead in bold up to
 *  the first full stop, then the count strip, the notice when a result is
 *  older than the design, and the limits line. */
export function verdictBlock(verdict, words) {
  const sentence = String(verdict.sentence || "");
  const lead = leadOf(sentence);
  const rest = sentence.slice(lead.length);
  const look = lookOf(verdict.token);
  return [
    el("p", { class: `verdict tone-${look.tone}` },
      el("span", { class: "verdict-glyph", "aria-hidden": "true", text: look.glyph }),
      el("b", { text: lead }), rest),
    tallyList(verdict),
    verdict.stale && verdict.notice
      ? el("p", { class: "nk-notice", role: "status" },
          el("span", { class: "nk-glyph", "aria-hidden": "true", text: "≈" }), verdict.notice)
      : null,
    verdict.limits ? el("p", { class: "limits small", text: verdict.limits }) : null,
  ];
}
