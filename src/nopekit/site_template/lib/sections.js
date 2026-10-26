// SPDX-License-Identifier: Apache-2.0
// sections.js: one section per board, and the next steps (architecture phase 5,
// SPEC 28, 30).
//
// A board's section is a poster. A claim whose evaluator left pictures comes
// first, as an open card (lib/figures.js, issue #15): the claim's chip, its
// value, which result the pictures are from, the charts and the stills. Then
// the agent's prose (the one place the site persuades), then the generated
// floor, collapsed: every claim on the board with its status, its value
// against its limit, its evaluators and its evidence. The cards come before
// the prose because they answer the first questions (does it hold, and what
// does it look like), and the prose can point at them. *Rejected:* the cards
// between the prose and the floor (a reader reads persuasion before the
// result it is about). The prose arrives from `page.json` already parsed into blocks and
// runs, never as HTML, and with its stamp state: text written before the latest
// results shows the bake's notice above it, and a number that no baked file
// holds is marked where it stands. This file builds DOM from those runs and
// decides none of it. (What slipped through before the stamp: nothing kept prose
// from saying a claim passes after it failed.)

import { el } from "./dom.js";
import { lookOf, tokenChip } from "./format.js";
import { claimBlocks } from "./drawer.js";
import { figureCards, disposeFigureViewers } from "./figures.js";

/** A piece of prose: its notice when it is not current, then its blocks. */
export function renderProse(prose, page, { onClaim } = {}) {
  if (!prose) return null;
  const words = (page && page.words) || {};
  const notices = words.notices || {};
  return el("div", { class: `nk-prose stamp-${prose.stamp}` },
    prose.stamp !== "current" && prose.notice
      ? el("p", { class: "nk-notice", role: "note" },
          el("span", { class: "nk-glyph", "aria-hidden": "true", text: "≈" }), prose.notice)
      : null,
    ...(prose.blocks || []).map((block) => renderBlock(block, notices, onClaim)),
    (prose.unmatched || []).length && notices.unmatched_note
      ? el("p", { class: "nk-notice nk-unmatched-note", role: "note" }, ` ${notices.unmatched_note}`)
      : null);
}

function renderBlock(block, notices, onClaim) {
  const runs = (list) => (list || []).map((run) => renderRun(run, notices, onClaim));
  switch (block.type) {
    case "h3": return el("h3", {}, ...runs(block.runs));
    case "h4": return el("h4", {}, ...runs(block.runs));
    case "quote": return el("blockquote", {}, ...runs(block.runs));
    case "ul": return el("ul", {}, ...(block.items || []).map((item) => el("li", {}, ...runs(item))));
    case "ol": return el("ol", {}, ...(block.items || []).map((item) => el("li", {}, ...runs(item))));
    case "figure":
      return el("figure", { class: "nk-figure" },
        block.missing
          ? el("p", { class: "nk-notice", text: `${block.src}: this file is not in the site.` })
          : el("img", { src: block.src, alt: block.alt || "", loading: "lazy" }),
        (block.caption || []).length ? el("figcaption", {}, ...runs(block.caption)) : null);
    default: return el("p", {}, ...runs(block.runs));
  }
}

function renderRun(run, notices, onClaim) {
  if (run.num !== undefined) {
    const text = run.t || (run.unit ? `${run.num} ${run.unit}` : String(run.num));
    if (run.match === false) {
      return el("mark", { class: "nk-unmatched", title: notices.unmatched || "" }, text);
    }
    return el("span", { class: "nk-num", text });
  }
  if (run.claim) {
    return el("button", { class: "linkish mono", type: "button", text: run.t || run.claim,
      onclick: () => onClaim && onClaim(run.claim) });
  }
  let node = document.createTextNode(String(run.t || ""));
  if (run.code) node = el("code", { class: "mono" }, node);
  if (run.b) node = el("b", {}, node);
  if (run.i) node = el("i", {}, node);
  if (run.href) node = el("a", { href: pageHref(run.href) }, node);
  return node;
}

/** A prose link as the page must write it. Both pages sit one folder down
 *  under `<base href="../">`, so a bare `#board-x` would resolve against the
 *  site's root and leave the page (the root is a redirect, or a front page
 *  from before the two pages). A same-page anchor keeps the page's own path;
 *  every other link is left as the text wrote it. */
function pageHref(href) {
  const text = String(href);
  return text.startsWith("#") ? `${location.pathname}${text}` : text;
}

/** One section per board, in the baked order. ``build`` is `build.json` (or
 *  null): a figure's 3D file on this computer only is listed there. */
export function renderSections(page, { onClaim, build = null } = {}) {
  disposeFigureViewers();
  const words = (page && page.words) || {};
  const headings = words.headings || {};
  const rows = (page && page.claims) || {};
  return (page.sections || []).map((sec) => {
    const floor = el("details", { class: "floor" },
      el("summary", {}, headings.floor || "", el("span", { class: "muted", text: ` (${(sec.claims || []).length})` })),
      el("div", { class: "floor-body" }, ...(sec.claims || []).map((key) => {
        const row = rows[key];
        if (!row) return null;
        return el("article", { class: `floor-claim tone-${lookOf(row.token, { errored: row.errored }).tone}`,
          id: `floor-${key}` },
          el("h3", {}, el("span", { class: "mono floor-id", text: key }), " ", row.statement || ""),
          ...claimBlocks(row, page, { onClaim }));
      })));
    return el("section", { class: "nk-sec board-sec", id: `board-${sec.board}` },
      el("header", { class: "sec-head" },
        el("h2", { text: sec.title || sec.board }),
        el("div", { class: "sec-status" },
          tokenChip(sec.token, sec.word, { errored: sec.errored, marks: sec.marks,
            notices: words.notices, trace: words.trace, group: true }),
          (sec.tally || []).length
            ? el("span", { class: "sec-tally" }, ...sec.tally.map((t) => el("span", {
                class: `tally-item tone-${lookOf(t.key, { errored: t.errored > 0 }).tone}` },
                el("span", { class: "nk-glyph", "aria-hidden": "true", text: lookOf(t.key, { errored: t.errored > 0 }).glyph }),
                ` ${t.label}`)))
            : null)),
      sec.line ? el("p", { class: "lede", text: sec.line }) : null,
      (sec.marks || []).includes("disagree") && (words.notices || {}).disagree
        ? el("p", { class: "nk-notice tone-bad", role: "note", text: words.notices.disagree }) : null,
      ...figureCards(sec, page, { build }),
      renderProse(sec.prose, page, { onClaim }),
      floor);
  });
}

/** Next steps: one card for each milestone (what it still needs, and the
 *  command that settles each), the revision's own group when there is no
 *  milestone, the claims no milestone requires, the parts to build again, and
 *  the agent's text. `next: true` and `ready` are the bake's. */
export function renderNext(page, { onClaim } = {}) {
  const next = (page && page.next) || {};
  const headings = ((page && page.words) || {}).headings || {};
  const out = [];
  const notices = ((page && page.words) || {}).notices || {};
  const trace = ((page && page.words) || {}).trace || {};
  for (const group of next.milestones || []) out.push(stepGroup(group, onClaim, "", notices, trace));
  if (next.project) out.push(stepGroup(next.project, onClaim, headings.project, notices, trace));
  if ((next.open || []).length) {
    out.push(el("div", { class: "card step-card" },
      el("h3", { text: headings.open || "" }),
      el("ol", { class: "steps" }, ...next.open.map((step) => stepRow(step, onClaim, notices, trace)))));
  }
  if ((next.rebuild || []).length) {
    out.push(el("div", { class: "card step-card" },
      el("h3", { text: headings.rebuild || "" }),
      el("ul", { class: "steps" }, ...next.rebuild.map((item) => el("li", { class: "step" },
        el("span", { class: "mono", text: item.article }), " ", item.text || "")))));
  }
  const prose = renderProse(next.prose, page, { onClaim });
  if (prose) out.push(prose);
  return out;
}

function stepGroup(group, onClaim, title, notices, trace) {
  const look = lookOf(group.token);
  return el("div", { class: `card step-card${group.next ? " is-next" : ""}` },
    el("div", { class: "step-head" },
      el("span", { class: `step-dot tone-${look.tone}`, "aria-hidden": "true", text: look.glyph }),
      el("h3", {}, el("span", { class: "mono", text: group.id || title || "" }),
        group.word ? el("span", { class: `step-word tone-${look.tone}`, text: ` ${group.word}` }) : null),
      group.next ? el("span", { class: "next-tag", text: "Next" }) : null),
    group.description ? el("p", { class: "muted", text: group.description }) : null,
    group.sentence ? el("p", { class: "step-sentence", text: group.sentence }) : null,
    (group.steps || []).length
      ? el("ol", { class: "steps" }, ...group.steps.map((step) => stepRow(step, onClaim, notices, trace)))
      : null,
    (group.missing || []).length
      ? el("ul", { class: "steps" }, ...group.missing.map((m) => el("li", { class: "step tone-bad" },
          el("b", { class: "mono", text: m.claim }), " ", m.text || "")))
      : null);
}

function stepRow(step, onClaim, notices, trace) {
  return el("li", { class: "step" },
    el("div", { class: "step-top" },
      tokenChip(step.token, step.word, { errored: step.errored, small: true, marks: step.marks,
        notices, trace }),
      el("button", { class: "linkish mono", type: "button", text: step.claim,
        onclick: () => onClaim && onClaim(step.claim) }),
      el("span", { class: "step-stmt", text: step.statement || "" })),
    step.text ? el("p", { class: "step-text", text: step.text }) : null,
    (step.commands || []).length
      ? el("p", { class: "step-cmds" }, ...step.commands.map((c) => el("code", { class: "mono", text: c })))
      : null);
}

