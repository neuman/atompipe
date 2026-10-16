// SPDX-License-Identifier: Apache-2.0
// drawer.js: the panel that opens beside the map (architecture phase 5,
// SPEC 29, 30).
//
// Two clicks from a red line to the evidence: a click on the line opens this
// drawer with the claim's status, the one-line cause, the measured value against
// the claim's own limit, each evaluator with its basis and outcome, and the
// evidence links; the second click opens the evidence. The same blocks make each
// claim's entry in a board's floor (`claimBlocks`), so the drawer and the floor
// cannot say two things about one claim.
//
// Everything here is a baked string or a baked token from `page.json` and
// `map.json`. The drawer puts them in order; it judges nothing. (What slipped
// through in the reference map: its drawer computed a margin and a "could
// flip" percentage in the browser.)

import { el, mount } from "./dom.js";
import { outcomeLook, tokenChip } from "./format.js";

/** The blocks that explain one claim, in the order a reader asks for them:
 *  what it reads now and why, the value against the limit, how it is settled,
 *  each evaluator, a recorded test on a built part, what it rests on, and
 *  what settles it next. ``row`` is `page.json`'s `claims[id]`. */
export function claimBlocks(row, page, { onClaim } = {}) {
  const words = (page && page.words) || {};
  const notices = words.notices || {};
  const link = (id) => el("button", { class: "linkish mono", type: "button", text: id,
    onclick: () => onClaim && onClaim(id) });
  const values = row.values || [];
  const mech = row.mechanism || {};
  return [
    el("div", { class: "cb-status" },
      tokenChip(row.token, row.word, { errored: row.errored, marks: row.marks, notices }),
      row.kind_word ? el("span", { class: "cb-kind", text: row.kind_word }) : null,
      row.critical === false ? el("span", { class: "cb-kind", text: "Not required" }) : null),
    row.cause_text ? el("p", { class: "cb-cause", text: row.cause_text }) : null,
    (row.marks || []).includes("disagree") && notices.disagree
      ? el("p", { class: "nk-notice tone-bad", text: notices.disagree }) : null,
    values.length
      ? el("div", { class: "cb-block" },
          el("h4", { text: "Measured against the limit" }),
          el("ul", { class: "cb-values" }, ...values.map((v) => el("li",
            { class: v.binding ? "binding" : "" },
            el("span", { class: "cb-value", text: v.value_text || "" }),
            v.gate ? el("span", { class: "cb-gate mono", text: v.gate }) : null))))
      : null,
    row.acceptance
      ? el("p", { class: "cb-accept" }, el("span", { class: "muted", text: "Acceptance: " }),
          el("code", { class: "mono", text: row.acceptance }))
      : null,
    (mech.by_word || mech.how)
      ? el("div", { class: "cb-block" },
          el("h4", { text: "How it is settled" }),
          mech.by_word ? el("p", { class: "cb-by", text: mech.by_word }) : null,
          mech.how ? el("p", { class: "cb-how", text: mech.how }) : null)
      : null,
    (row.evaluators || []).length
      ? el("div", { class: "cb-block" },
          el("h4", { text: "Evaluators" }),
          el("ul", { class: "cb-evals" }, ...row.evaluators.map((ev) => evaluatorItem(ev, words))))
      : null,
    row.amber ? amberBlock(row.amber) : null,
    row.physical ? physicalBlock(row.physical) : null,
    (row.rests_on || []).length
      ? el("p", { class: "cb-rel" }, el("span", { class: "muted", text: "Rests on: " }),
          ...joinWith(row.rests_on.map(link), " "))
      : null,
    (row.resolves || []).length
      ? el("p", { class: "cb-rel" }, el("span", { class: "muted", text: "Replaces the assumption: " }),
          ...joinWith(row.resolves.map(link), " "))
      : null,
    (row.resolved_by || []).length
      ? el("p", { class: "cb-rel" }, el("span", { class: "muted", text: "A test that replaces it: " }),
          ...joinWith(row.resolved_by.map(link), " "))
      : null,
    row.settle && (row.settle.text || (row.settle.commands || []).length)
      ? el("div", { class: "cb-block cb-settle" },
          el("h4", { text: "To settle it" }),
          row.settle.text ? el("p", { text: row.settle.text }) : null,
          (row.settle.commands || []).length
            ? el("p", { class: "cb-cmds" }, ...row.settle.commands.map((c) => el("code", { class: "mono", text: c })))
            : null)
      : null,
  ];
}

function evaluatorItem(ev, words) {
  const look = outcomeLook(ev.outcome);
  return el("li", { class: `cb-eval tone-${look.tone}` },
    el("div", { class: "cb-eval-head" },
      el("span", { class: `nk-chip nk-chip-sm tone-${look.tone}` },
        el("span", { class: "nk-glyph", "aria-hidden": "true", text: look.glyph }),
        el("span", { class: "nk-word", text: ev.outcome_word || ev.outcome })),
      el("code", { class: "mono cb-eval-id", text: ev.id })),
    ev.detail ? el("p", { class: "cb-detail", text: ev.detail }) : null,
    ev.basis_word ? el("p", { class: "cb-basis muted", text: ev.basis_word }) : null,
    ev.stale_reason ? el("p", { class: "cb-stale", text: ev.stale_reason }) : null,
    (ev.evidence || []).length
      ? el("ul", { class: "cb-evidence" }, ...ev.evidence.map((item) => el("li", {},
          item.href
            ? el("a", { class: "mono", href: item.href, target: "_blank", rel: "noopener", text: item.name })
            : el("span", { class: "mono", text: item.name }),
          item.missing ? el("span", { class: "muted", text: ` ${item.missing}` }) : null)))
      : null);
}

/** Amber (architecture phase 3b): the bake's word for what a ±10% move of
 *  an unconfirmed assumption's choice did to this pass, and each run that
 *  flipped it. Shown beside the status; it changes none. */
function amberBlock(amber) {
  const flips = amber.state === "flips";
  return el("div", { class: `cb-block cb-amber${flips ? " flips" : ""}` },
    el("h4", { text: "If an assumption is wrong" }),
    amber.word ? el("p", { text: amber.word }) : null,
    (amber.items || []).length
      ? el("ul", { class: "cb-values" }, ...amber.items.map((item) => el("li", {},
          el("span", { class: "cb-value", text: item.text || "" }))))
      : null);
}

/** A recorded test on a built part, or an expert judgment: its glyph, tone and
 *  word from the bake's `token` and `word` (`report.result_facts`), through the
 *  outcome table, the one place a result's tone is said. What slipped through
 *  (follow-up after phase 3b): the block took its tone from `counts` alone, so
 *  a counted fail read green beside its Failing chip. */
function physicalBlock(found) {
  const look = outcomeLook(found.token);
  return el("div", { class: `cb-block cb-physical tone-${look.tone}` },
    found.heading ? el("h4", { text: found.heading }) : null,
    el("div", { class: "cb-eval-head" },
      el("span", { class: `nk-chip nk-chip-sm tone-${look.tone}` },
        el("span", { class: "nk-glyph", "aria-hidden": "true", text: look.glyph }),
        el("span", { class: "nk-word", text: found.word || found.token || "" }))),
    found.why ? el("p", { text: found.why }) : null,
    found.recorded ? el("p", { class: "muted small", text: found.recorded }) : null);
}

function joinWith(items, sep) {
  const out = [];
  items.forEach((item, i) => { if (i) out.push(sep); out.push(item); });
  return out;
}

/** The drawer: one panel at the right edge (full width on a phone). ``open``
 *  shows a claim, a requirement, a zone, a station or a board; Esc and the
 *  close button shut it. ``onChange(kind, key)`` tells the map what to keep
 *  lit (``null`` when it shuts). */
export function createDrawer(page, map, { onChange } = {}) {
  const words = (page && page.words) || {};
  let mapDoc = map, pageDoc = page;
  const body = el("div", { class: "drawer-body" });
  const crumb = el("div", { class: "crumbs" });
  const back = el("button", { class: "iconbtn", type: "button", "aria-label": "Back", text: "‹",
    hidden: true, onclick: () => goBack() });
  const close = el("button", { class: "iconbtn", type: "button", "aria-label": "Close", text: "×",
    onclick: () => shut() });
  const element = el("aside", { id: "nk-drawer", "aria-hidden": "true", tabindex: "-1" },
    el("div", { class: "drawer-head" }, back, crumb, close), body);
  const trail = [];
  let current = null;

  document.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && element.classList.contains("is-open")) shut();
  });

  const nodeOf = (kind, key) => (mapDoc.nodes || []).find((n) => n.id === `${kind}:${key}`);
  const kindWord = (kind) => ({
    claim: "Claim", requirement: "What was asked", zone: "Choices",
    station: "Shared value", board: "Board",
  })[kind] || kind;

  function open(kind, key, { push = true } = {}) {
    if (push && current && !(current[0] === kind && current[1] === key)) trail.push(current);
    current = [kind, key];
    back.hidden = !trail.length;
    mount(crumb, el("span", { text: kindWord(kind) }), el("b", { class: "mono", text: ` ${key}` }));
    mount(body, ...content(kind, key));
    element.classList.add("is-open");
    element.setAttribute("aria-hidden", "false");
    document.body.classList.add("drawer-open");
    body.scrollTop = 0;
    onChange && onChange(kind, key);
  }

  function goBack() {
    const last = trail.pop();
    if (last) open(last[0], last[1], { push: false });
  }

  function shut() {
    element.classList.remove("is-open");
    element.setAttribute("aria-hidden", "true");
    document.body.classList.remove("drawer-open");
    trail.length = 0;
    current = null;
    onChange && onChange(null, null);
  }

  function claimList(keys) {
    return el("ul", { class: "dr-claims" }, ...(keys || []).map((key) => {
      const node = nodeOf("claim", key);
      if (!node) return el("li", {}, el("span", { class: "mono", text: key }));
      return el("li", {}, el("button", { class: "dr-claim", type: "button",
        onclick: () => open("claim", key) },
        tokenChip(node.token, node.word, { errored: node.errored, small: true, marks: node.marks,
          notices: words.notices }),
        el("b", { class: "mono", text: ` ${key} ` }),
        el("span", { text: node.title })));
    }));
  }

  function readersOf(name) {
    const reads = ((mapDoc.edges || {}).reads) || {};
    return Object.keys(reads).filter((src) => (reads[src] || []).includes(`value:${name}`))
      .map((src) => src.replace(/^evaluator:/, ""));
  }

  function valueList(names) {
    const values = mapDoc.values || {};
    return el("ul", { class: "dr-values" }, ...(names || []).map((name) => {
      const v = values[name] || {};
      const readers = readersOf(name);
      return el("li", {},
        el("code", { class: "mono", text: name }),
        v.value_text ? el("span", { class: "dr-val", text: ` ${v.value_text}` }) : null,
        v.ground && v.ground !== "chosen" ? el("span", { class: "dr-ground", text: ` (${v.ground})` }) : null,
        readers.length
          ? el("p", { class: "muted small" }, "Read by: ",
              ...joinWith(readers.map((r) => el("code", { class: "mono", text: r })), ", "))
          : el("p", { class: "muted small", text: "No evaluator reads this value." }));
    }));
  }

  function content(kind, key) {
    if (kind === "claim") {
      const row = (pageDoc.claims || {})[key];
      if (!row) return [el("p", { text: `No claim ${key} on this page.` })];
      const line = (mapDoc.lines || []).find((l) => l.claim === key) || {};
      return [
        el("h3", { class: "dr-title", text: row.statement || key }),
        ...claimBlocks(row, pageDoc, { onClaim: (id) => open("claim", id) }),
        line.reads_all && (words.notices || {}).reads_all
          ? el("p", { class: "muted small", text: words.notices.reads_all }) : null,
        el("p", { class: "dr-tech" }, el("a", { href: `technical.html#claim=${encodeURIComponent(key)}`,
          text: "Show in the technical record" })),
      ];
    }
    const node = nodeOf(kind, key);
    if (!node) return [el("p", { text: `Nothing named ${key} on this map.` })];
    const head = [el("h3", { class: "dr-title", text: node.title || key })];
    if (node.line) head.push(el("p", { class: "dr-line", text: node.line }));
    if (node.token) head.push(el("div", { class: "cb-status" },
      tokenChip(node.token, node.word, { errored: node.errored, marks: node.marks,
        notices: words.notices })));
    if ((node.marks || []).includes("disagree") && (words.notices || {}).disagree) {
      head.push(el("p", { class: "nk-notice tone-bad", text: words.notices.disagree }));
    }
    if (kind === "requirement" || kind === "board") {
      return [...head,
        (node.tally || []).length
          ? el("p", { class: "muted small", text: node.tally.map((t) => t.label).join(" · ") }) : null,
        el("h4", { text: "Claims" }), claimList(node.claims)];
    }
    if (kind === "zone") {
      const out = (mapDoc.feeds || []).filter((f) => f.zone === node.id);
      const taps = (mapDoc.lines || []).flatMap((l) => (l.taps || [])
        .filter((t) => t.zone === node.id).map((t) => ({ claim: l.claim, choices: t.choices || [] })));
      return [...head,
        out.length || taps.length ? el("h4", { text: "Feeds" }) : null,
        out.length || taps.length
          ? el("ul", { class: "dr-feeds" },
              ...out.map((f) => {
                const to = (mapDoc.nodes || []).find((n) => n.id === f.to) || {};
                return el("li", {},
                  el("button", { class: "linkish", type: "button", text: to.title || to.key || f.to,
                    onclick: () => open("station", to.key) }),
                  el("span", { class: "muted small", text: ` ← ${(f.choices || []).join(", ")}` }),
                  (f.estimate || []).length
                    ? el("span", { class: "dr-est small", text: ` ◆ ${f.estimate.join(", ")}` }) : null);
              }),
              ...taps.map((t) => el("li", {},
                el("button", { class: "linkish mono", type: "button", text: t.claim,
                  onclick: () => open("claim", t.claim) }),
                el("span", { class: "muted small", text: ` reads ${t.choices.join(", ")}` }))))
          : null,
        node.idle && (words.trace || {}).zone_idle ? el("p", { class: "muted small", text: words.trace.zone_idle }) : null,
        !node.idle && (node.unmeasured || []).length && (words.trace || {}).zone_unmeasured
          ? el("p", { class: "muted small", text: `${words.trace.zone_unmeasured} ${node.unmeasured.join(", ")}` }) : null,
        el("h4", { text: "Choices" }), valueList(node.members),
        (node.assumptions || []).length
          ? el("div", {}, el("h4", { text: "Assumptions that set a choice here" }), claimList(node.assumptions))
          : null,
        (node.claims || []).length ? el("h4", { text: "Claims fed from here" }) : null,
        (node.claims || []).length ? claimList(node.claims) : null];
    }
    if (kind === "station") {
      const into = (mapDoc.feeds || []).filter((f) => f.to === node.id);
      const upstream = Object.keys(node.stop_kinds || {}).filter((c) => node.stop_kinds[c] === "upstream");
      return [...head,
        el("h4", { text: "Values" }), valueList(node.members),
        into.length ? el("h4", { text: "Moved by" }) : null,
        into.length
          ? el("ul", { class: "dr-feeds" }, ...into.map((f) => {
              const zone = (mapDoc.nodes || []).find((n) => n.id === f.zone) || {};
              return el("li", {},
                el("button", { class: "linkish", type: "button", text: zone.title || zone.key || f.zone,
                  onclick: () => open("zone", zone.key) }),
                el("span", { class: "muted small", text: `: ${(f.choices || []).join(", ")}` }),
                (f.estimate || []).length
                  ? el("span", { class: "dr-est small", text: ` ◆ ${f.estimate.join(", ")}` }) : null);
            }))
          : null,
        (node.claims || []).length ? el("h4", { text: "Claims whose line stops here" }) : null,
        (node.claims || []).length ? claimList(node.claims) : null,
        upstream.length && (words.trace || {}).upstream_stop
          ? el("p", { class: "muted small" }, `${upstream.join(", ")}: ${words.trace.upstream_stop}`)
          : null];
    }
    return head;
  }

  return {
    element,
    open,
    close: shut,
    get current() { return current; },
    /** New data from a rebuild: the open item is shown again from it. */
    update(nextPage, nextMap) {
      pageDoc = nextPage; mapDoc = nextMap;
      if (current) open(current[0], current[1], { push: false });
    },
  };
}
