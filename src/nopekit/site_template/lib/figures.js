// SPDX-License-Identifier: Apache-2.0
// figures.js: a board's claim cards, the pictures of a result beside the claims
// it covers (issue #15, B.4.1).
//
// One open card for each claim on a board that has figures, before the agent's
// prose: the claim and its chip; the value the judging evaluator measured, in
// large type; the other evaluators' values; which result the pictures are from
// (the spine's sentence, at the top when it is not the result on this page);
// the charts; the stills with their colour legend and plane labels; a 3D view
// a reader turns; and the line that names the result.
//
// Everything here is baked (`page.json`, `page.figure_row`): the currency, its
// sentence, the chips of every claim the gate covers, the chart's whole
// Vega-Lite spec, the scale's stops and ticks, the marks' positions. This file
// puts them in the DOM and decides none of them: no status, margin, limit,
// currency or order is computed here (invariant 14,
// `test_site_truth.TheBrowserComputesNoTruth`). What slipped through before
// the figures were bound: a picture sat on the page with nothing that said
// which result it was, so a design that went A, B, A showed B's picture under
// A's chip.

import { el, mount } from "./dom.js";
import { lookOf, tokenChip, currencyLook } from "./format.js";
import { createViewer } from "./viewer3d.js";

// --------------------------------------------------------------------------- //
// the chart library (rule 0.1 of the issue's design)
// --------------------------------------------------------------------------- //
/** Vega, Vega-Lite and vega-embed, pinned (`site.VEGA_VERSIONS`, which a test
 *  holds equal to this list): the vendored copy under `vendor/vega/` when
 *  `nopekit site vendor` put it there, else the CDN. The UMD builds, loaded in
 *  order as classic scripts: each is one self-contained file, where the ESM
 *  builds import some thirty bare package names an import map would have to
 *  list. A page shell is the project's own and never regenerated, so the
 *  loader lives here, in `lib/`, which every build refreshes. */
export const VEGA_FILES = [
  ["vendor/vega/vega.min.js", "https://cdn.jsdelivr.net/npm/vega@6.2.0/build/vega.min.js"],
  ["vendor/vega/vega-lite.min.js", "https://cdn.jsdelivr.net/npm/vega-lite@6.4.1/build/vega-lite.min.js"],
  ["vendor/vega/vega-embed.min.js", "https://cdn.jsdelivr.net/npm/vega-embed@7.1.0/build/vega-embed.min.js"],
];

let vegaLoad = null;

/** ``vegaEmbed``, once; rejects when the library does not load (offline and
 *  not vendored), and the card then shows the chart's numbers as a table. */
export function loadVega() {
  if (window.vegaEmbed) return Promise.resolve(window.vegaEmbed);
  if (!vegaLoad) {
    vegaLoad = (async () => {
      let vendored = false;
      try {
        const res = await fetch(VEGA_FILES[0][0], { method: "HEAD", cache: "no-store" });
        vendored = res.ok;
      } catch (err) {
        vendored = false;
      }
      for (const [local, cdn] of VEGA_FILES) await script(vendored ? local : cdn);
      if (!window.vegaEmbed) throw new Error("vega-embed loaded and defined nothing");
      return window.vegaEmbed;
    })().catch((err) => { vegaLoad = null; throw err; });
  }
  return vegaLoad;
}

function script(src) {
  return new Promise((resolve, reject) => {
    const tag = document.createElement("script");
    tag.src = src;
    tag.async = false;
    tag.onload = () => resolve();
    tag.onerror = () => reject(new Error(`${src} did not load`));
    document.head.appendChild(tag);
  });
}

/** The page theme for the chart: the colours of page.css's tokens and the
 *  look of each `style` name the spec uses (`page.chart_spec`). Look only:
 *  what is drawn, and where, is the spec's. */
function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  const v = (name, dflt) => (css.getPropertyValue(name) || "").trim() || dflt;
  const ink = v("--ink", "#0b0b0b"), ink2 = v("--ink-2", "#52514e"), grid = v("--grid", "#e1e0d9");
  const fail = v("--fail", "#d03b3b"), accent = v("--accent", "#2a78d6"), amber = v("--amber-strong", "#b98000");
  const font = v("--sans", "system-ui, sans-serif");
  return {
    background: null,
    font,
    view: { stroke: null },
    axis: { labelColor: ink2, titleColor: ink2, gridColor: grid, domainColor: grid, tickColor: grid,
      labelFontSize: 12, titleFontSize: 12, titleFontWeight: 600 },
    legend: { orient: "bottom", labelColor: ink2, labelFontSize: 12, title: null },
    range: { category: [accent, "#7a5aa8", "#2e7d4f", "#b98000", "#52514e", "#0f8b8d"] },
    line: { strokeWidth: 2 },
    point: { size: 60, strokeWidth: 2 },
    text: { fontSize: 12, color: ink },
    // Each style's colour is `color`, never `stroke` or `fill`: Vega-Lite
    // writes a mark's default colour into the mark itself, over a style's
    // stroke or fill, and reads a style's `color` first (seen on the figure
    // project's page, P1.5: the limit drew black). Where a label sits is the
    // spec's (`page.chart_spec`), never this theme's.
    style: {
      "nk-past": { color: fail, opacity: 0.07 },
      "nk-limit": { color: fail, strokeDash: [6, 4], strokeWidth: 2 },
      "nk-limit-label": { color: fail, fontWeight: 600 },
      "nk-rule": { color: amber, strokeDash: [2, 3], strokeWidth: 1.5 },
      "nk-rule-label": { color: amber },
      "nk-band": { color: ink2, strokeWidth: 2 },
      "nk-hollow": { strokeWidth: 2, opacity: 1 },
      "nk-point": { opacity: 1 },
      "nk-point-label": { color: ink2 },
      "nk-estimate": { color: ink2, size: 90, opacity: 1 },
      "nk-current": { color: ink, size: 150, opacity: 1 },
      "nk-current-rule": { color: ink, strokeDash: [1, 3], strokeWidth: 1.5 },
      "nk-current-label": { color: ink, fontWeight: 600 },
    },
  };
}

/** A bound chart: the baked spec handed to vegaEmbed whole, or, where the
 *  library does not load, the numbers it would draw as a table (never a
 *  drawing of our own). */
function chartBox(fig, words) {
  const chart = fig.chart || {};
  const host = el("div", { class: "fig-chart" });
  const spec = chart.spec;
  if (!spec) {
    mount(host, el("p", { class: "muted small", text: fig.currency_word || "" }));
    return host;
  }
  loadVega()
    .then((embed) => embed(host, spec, { actions: false, renderer: "svg", mode: "vega-lite",
      config: chartTheme() }))
    .catch((err) => mount(host, chartTable(fig, words, err)));
  return host;
}

function chartTable(fig, words, err) {
  const chart = fig.chart || {};
  const rows = (((chart.spec || {}).data || {}).values) || [];
  const said = (words.figure || {});
  return el("div", { class: "fig-table" },
    el("p", { class: "nk-notice", role: "note", text: said.table || "" }),
    el("table", {},
      el("thead", {}, el("tr", {}, el("th", { text: "" }), el("th", { text: "x" }), el("th", { text: "y" }))),
      el("tbody", {}, ...rows.map((r) => el("tr", {},
        el("td", { text: r.label || r.series || "" }), el("td", { text: String(r.x) }),
        el("td", { text: String(r.y) }))))),
    chart.limit && chart.limit.label ? el("p", { class: "small", text: chart.limit.label }) : null,
    chart.current && chart.current.margin_text
      ? el("p", { class: "small", text: chart.current.margin_text }) : null,
    err && err.message ? el("p", { class: "small muted", text: err.message }) : null);
}

// --------------------------------------------------------------------------- //
// the legend and the stills
// --------------------------------------------------------------------------- //
/** The colour legend of a still or a 3D view, from the baked scale alone: a
 *  gradient of its stops, a tick at each baked position with its baked text,
 *  the under and over swatches with their words, and where the range comes
 *  from. The same object coloured the pixels (C7: one legend, never a second
 *  one drawn into the picture). */
export function scaleLegend(scale) {
  if (!scale || !(scale.stops || []).length) return null;
  const stops = scale.stops.map((s) => `${s.colour} ${(Number(s.at) * 100).toFixed(2)}%`).join(", ");
  const title = [scale.quantity, scale.units ? `(${scale.units})` : ""].filter(Boolean).join(" ");
  return el("div", { class: "fig-legend" },
    title ? el("p", { class: "fig-legend-title", text: title }) : null,
    el("div", { class: "fig-legend-bar" },
      scale.under ? el("span", { class: "fig-swatch", style: { background: scale.under }, "aria-hidden": "true" }) : null,
      el("div", { class: "fig-ramp", style: { background: `linear-gradient(to right, ${stops})` } },
        ...(scale.ticks || []).map((t) => el("span", { class: "fig-tick",
          style: { left: `${(Number(t.at) * 100).toFixed(2)}%` }, text: t.text || "" }))),
      scale.over ? el("span", { class: "fig-swatch", style: { background: scale.over }, "aria-hidden": "true" }) : null),
    scale.under_word || scale.over_word
      ? el("p", { class: "fig-legend-words small" },
          scale.under ? el("span", { class: "fig-swatch-sm", style: { background: scale.under }, "aria-hidden": "true" }) : null,
          scale.under_word ? ` ${scale.under_word} ` : "",
          scale.over ? el("span", { class: "fig-swatch-sm", style: { background: scale.over }, "aria-hidden": "true" }) : null,
          scale.over_word ? ` ${scale.over_word}` : "")
      : null,
    scale.source_text ? el("p", { class: "small muted", text: scale.source_text }) : null);
}

/** The chips of every claim the figure's gate covers, as baked. */
function figureChips(fig, words) {
  const chips = fig.claims || [];
  if (!chips.length) return null;
  return el("div", { class: "fig-chips" }, ...chips.map((c) => el("span", { class: "fig-chip" },
    el("span", { class: "mono", text: c.id }), " ",
    tokenChip(c.token, c.word, { errored: c.errored, small: true, marks: c.marks,
      notices: words.notices, trace: words.trace }))));
}

/** A still: the picture linked to its full file, its marks as HTML labels at
 *  the baked positions, its legend and its caption. */
function still(fig) {
  return el("div", { class: "fig-still-box" },
    el("a", { class: "fig-still", href: fig.src, target: "_blank", rel: "noopener" },
      el("img", { src: fig.src, alt: fig.alt || fig.title || "", loading: "lazy" }),
      ...(fig.marks || []).map((m) => el("span", { class: "fig-mark",
        style: { left: `${(Number(m.at) * 100).toFixed(2)}%` } },
        el("span", { class: "fig-mark-text", text: m.text || "" })))));
}

const viewers = new Set();

/** Release every 3D view a card opened (a rebuild draws the cards again). */
export function disposeFigureViewers() {
  for (const v of viewers) v.dispose();
  viewers.clear();
}

/** "Turn it in 3D": shown only when there is a 3D file to turn, the committed
 *  one the bake names (`field_src`, or a 3D view's `src`) or the one this
 *  computer drew (`build.json`'s `live_figures`, keyed by the figure's id).
 *  The viewer mounts only when a reader asks: a field can be a megabyte. */
function turnButton(fig, build) {
  const turn = fig.turn || {};
  const live = ((build && build.live_figures) || {})[fig.id] || "";
  const src = fig.field_src || (fig.kind === "field" || fig.kind === "model3d" ? fig.src : "") || live;
  if (!src || !turn.word) return null;
  const box = el("div", { class: "fig-3d" });
  const button = el("button", { class: "fig-turn", type: "button", text: turn.word,
    onclick: () => {
      button.remove();
      const frame = el("div", { class: "viewer fig-viewer" });
      mount(box, frame, src === live && turn.live_word
        ? el("p", { class: "small muted", text: turn.live_word }) : null);
      const api = createViewer({ host: frame, view: { id: fig.id, kind: "field", src, meta: {} },
        field: true,
        onReady: (ready) => ready.setSpin(false),
        onError: (err) => mount(frame, el("p", { class: "nk-notice",
          text: err && err.message ? err.message : String(err) })) });
      viewers.add(api);
    } });
  mount(box, button);
  return box;
}

/** One figure: its title, the chips of the claims its gate covers, the
 *  picture (or the chart), the 3D button, the legend and the caption. A
 *  figure with no file shows its currency sentence alone. */
function figureBlock(fig, words, build) {
  const look = currencyLook(fig.currency);
  const drawn = fig.src || fig.data_src || fig.field_src;
  const body = fig.kind === "chart" && fig.data_src ? chartBox(fig, words)
    : fig.kind === "image" && fig.src ? still(fig) : null;
  return el("figure", { class: `fig fig-${fig.kind} currency-${fig.currency}`, id: `figure-${fig.id}` },
    el("figcaption", { class: "fig-head" },
      el("span", { class: "fig-title", text: fig.title || fig.view }),
      figureChips(fig, words)),
    drawn ? null : el("p", { class: `fig-none tone-${look.tone}` },
      el("span", { class: "nk-glyph", "aria-hidden": "true", text: look.glyph }), ` ${fig.currency_word || ""}`),
    body,
    turnButton(fig, build),
    fig.kind === "image" ? scaleLegend(fig.scale) : null,
    fig.caption ? el("p", { class: "fig-caption", text: fig.caption }) : null,
    fig.tool_word ? el("p", { class: "nk-notice", role: "note", text: fig.tool_word }) : null);
}

/** The figure's chips and its currency sentence on one line: what the hero
 *  shows under a figure, on both pages. */
export function figureTag(fig, words) {
  if (!fig) return null;
  const look = currencyLook(fig.currency);
  return el("div", { class: `fig-tag currency-${fig.currency}` },
    el("p", { class: `fig-currency tone-${look.tone}` },
      el("span", { class: "nk-glyph", "aria-hidden": "true", text: look.glyph }),
      ` ${fig.currency_word || ""}`, fig.drawn_text ? ` ${fig.drawn_text}` : ""),
    figureChips(fig, words || {}));
}

// --------------------------------------------------------------------------- //
// the card
// --------------------------------------------------------------------------- //
/** The cards of one board: one for each of its claims that has figures, in
 *  the board's baked order. */
export function figureCards(sec, page, { build = null } = {}) {
  const rows = (page && page.claims) || {};
  const words = (page && page.words) || {};
  return (sec.claims || []).map((key) => rows[key]).filter((row) => row && (row.figures || []).length)
    .map((row) => claimCard(row, words, build));
}

function claimCard(row, words, build) {
  const said = words.figure || {};
  const figs = row.figures || [];
  const values = row.values || [];
  const judging = values.find((v) => v.binding) || values[0] || null;
  const others = values.filter((v) => v !== judging);
  const sentences = Array.from(new Set(figs.filter((f) => currencyLook(f.currency).notice)
    .map((f) => [f.currency, `${f.currency_word || ""}${f.drawn_text ? " " + f.drawn_text : ""}`])
    .map(JSON.stringify))).map(JSON.parse);
  const charts = figs.filter((f) => f.kind === "chart");
  const stills = figs.filter((f) => f.kind !== "chart");
  const provenance = Array.from(new Set(figs.map((f) => f.provenance).filter(Boolean)));
  return el("article", {
    class: `card fig-card${sentences.length ? " fig-card--other" : ""} ${Array.from(new Set(figs.map((f) => `has-${f.currency}`))).join(" ")}`,
    id: `fig-${row.id}` },
    el("header", { class: "fig-card-head" },
      el("h3", {}, el("span", { class: "mono floor-id", text: row.id }), " ", row.statement || ""),
      tokenChip(row.token, row.word, { errored: row.errored, marks: row.marks, notices: words.notices,
        trace: words.trace })),
    judging
      ? el("div", { class: "fig-verdict" },
          el("p", { class: `fig-value tone-${lookOf(row.token, { errored: row.errored }).tone}`, text: judging.value_text || "" }),
          judging.gate && said.judged
            ? el("p", { class: "small muted", text: said.judged.replace("{gate}", judging.gate) }) : null)
      : null,
    others.length
      ? el("div", { class: "fig-tiles", "aria-label": said.others || "" },
          ...others.map((v) => el("div", { class: "fig-tile" },
            el("p", { class: "fig-tile-value", text: v.value_text || "" }),
            v.gate ? el("p", { class: "small muted mono", text: v.gate }) : null)))
      : null,
    ...sentences.map(([currency, text]) => el("p", { class: `nk-notice fig-notice tone-${currencyLook(currency).tone}`, role: "note" },
      el("span", { class: "nk-glyph", "aria-hidden": "true", text: currencyLook(currency).glyph }), ` ${text}`)),
    charts.length ? el("div", { class: "fig-charts" }, ...charts.map((f) => figureBlock(f, words, build))) : null,
    stills.length ? el("div", { class: "fig-stills" }, ...stills.map((f) => figureBlock(f, words, build))) : null,
    row.binding_text || provenance.length
      ? el("p", { class: "fig-binding small" }, [row.binding_text, ...provenance].filter(Boolean).join(" "))
      : null);
}
