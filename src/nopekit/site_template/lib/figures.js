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
    tag.onerror = () => reject(new Error(src));
    document.head.appendChild(tag);
  });
}

/** The page theme for the chart: the colours of page.css's tokens and the
 *  look of each `style` name the spec uses (`page.chart_spec`). Look only:
 *  what is drawn, and where, is the spec's. */
function chartTheme() {
  const css = getComputedStyle(document.documentElement);
  // The first of ``names`` the page's stylesheet sets: page.css's tokens on
  // the engineering page, style.css's on the technical record (P2.5: one
  // chart, two stylesheets), else the default.
  const v = (names, dflt) => {
    for (const name of [].concat(names)) {
      const found = (css.getPropertyValue(name) || "").trim();
      if (found) return found;
    }
    return dflt;
  };
  const ink = v("--ink", "#0b0b0b"), ink2 = v("--ink-2", "#52514e"), grid = v(["--grid", "--line-2"], "#e1e0d9");
  const fail = v(["--fail", "--bad"], "#d03b3b"), accent = v("--accent", "#2a78d6"), amber = v(["--amber-strong", "--warn"], "#b98000");
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
    // A chart's title is the judged point's words, beside points with words
    // of their own (`page.chart_spec`, review of issue #15's P3): the ring's
    // label, in its look. A style does not reach a title's colour.
    title: { color: ink, fontSize: 12, fontWeight: 600, anchor: "start" },
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
      "nk-band-end": { color: ink2, thickness: 2, size: 16, opacity: 1 },
      "nk-hollow": { strokeWidth: 2, opacity: 1 },
      "nk-point": { opacity: 1 },
      "nk-point-label": { color: ink2 },
      "nk-estimate": { color: ink2, size: 90, opacity: 1 },
      // A ring: the band and the point under it stay in view (review of P2).
      "nk-current": { color: ink, size: 300, strokeWidth: 2.5, opacity: 1 },
      "nk-current-rule": { color: ink, strokeDash: [1, 3], strokeWidth: 1.5 },
      "nk-current-label": { color: ink, fontWeight: 600 },
      // The verdicts' anchors on a chart view of the technical record
      // (`page.view_chart`): a located series drawn heavier, a located x as
      // a rule in its severity's colour.
      "nk-located": { strokeWidth: 4, opacity: 1 },
      "nk-loc-fail": { color: fail, strokeDash: [4, 4], strokeWidth: 1.5 },
      "nk-loc-warn": { color: amber, strokeDash: [4, 4], strokeWidth: 1.5 },
      "nk-loc-info": { color: accent, strokeDash: [4, 4], strokeWidth: 1.5 },
      "nk-loc-label": { color: ink2 },
    },
  };
}

/** The charts drawn on this page: ``{host, spec, view}`` each, so that a
 *  change of theme draws them again in the new theme's colours. */
const liveCharts = new Set();
let themeWatched = false;
let redrawQueued = false;

/** Draw ``spec`` into ``host`` in the theme the page has now, and keep it
 *  among the live charts. */
function embedChart(embed, item) {
  const config = chartTheme();
  // An axis title longer than the box ends in an ellipsis instead of running
  // past its edge. What slipped through (P2.5, the beam's deflection chart at
  // 390 px): "section depth h (in the bending direction) (mm)" lost its units
  // off the right edge. Layout only: the words are the spec's.
  const room = Math.max(120, (item.host.clientWidth || 0) - 60);
  config.axis = { ...config.axis, titleLimit: room };
  // And a legend in a narrow box is one entry a line: in a row, the CFD
  // settling chart's third mesh ran off a 390 px box (P2.5).
  if (room < 460) config.legend = { ...config.legend, direction: "vertical" };
  return embed(item.host, item.spec, { actions: false, renderer: "svg", mode: "vega-lite",
    config }).then((result) => {
    item.view = result && result.view;
    liveCharts.add(item);
  });
}

/** Draw every live chart again once the theme moves: the button
 *  (`lib/theme.js` sets ``data-theme``) or the system's dark or light. Vega
 *  writes the theme's colours into the SVG it draws, and nothing in page.css
 *  reaches them after. What slipped through (review of P1): after the theme
 *  button, the chart kept the old theme's colours, and the judged point and
 *  its label drew near-black on the dark card. A chart whose host left the
 *  page is let go. */
function watchTheme() {
  if (themeWatched) return;
  themeWatched = true;
  const redraw = () => {
    if (redrawQueued) return;
    redrawQueued = true;
    requestAnimationFrame(() => {
      redrawQueued = false;
      if (!window.vegaEmbed) return;
      for (const item of [...liveCharts]) {
        liveCharts.delete(item);
        if (item.view && item.view.finalize) item.view.finalize();
        if (!item.host.isConnected) continue;
        item.host.replaceChildren();
        embedChart(window.vegaEmbed, item).catch(() => { /* the drawing in place stays */ });
      }
    });
  };
  new MutationObserver(redraw).observe(document.documentElement,
    { attributes: true, attributeFilter: ["data-theme"] });
  const media = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)");
  if (media && media.addEventListener) media.addEventListener("change", redraw);
}

/** A bound chart: the baked spec handed to vegaEmbed whole, or, where the
 *  library does not load, the numbers it would draw as a table (never a
 *  drawing of our own). */
function chartBox(fig, words) {
  const chart = fig.chart || {};
  const host = el("div", { class: "fig-chart" });
  if (!chart.spec) {
    mount(host, el("p", { class: "muted small", text: fig.currency_word || "" }));
    return host;
  }
  return drawChart(host, chart, (words.figure || {}).table || "", fig.view);
}

/** Draw ``chart.spec`` (a spec the spine baked whole: `page.chart_spec`) into
 *  ``host`` with Vega-Lite, or, where the library does not load, its numbers
 *  as a table under ``notice``. The engineering page's cards and the
 *  technical record's chart views (`lib/stage.js`) both draw through here.
 *  What it replaced on the technical record (P2.5): `lib/chart.js`, a
 *  hand-drawn SVG whose text fell to about 5 px on a phone. */
export function drawChart(host, chart, notice, name) {
  const spec = chart && chart.spec;
  if (!spec) return host;
  watchTheme();
  loadVega()
    .then((embed) => embedChart(embed, { host, spec, view: null }))
    .catch((err) => {
      // The reason stays in the console: a sentence the page shows is baked
      // (`report.HUMAN`), so the style scans read it.
      console.warn("chart", name, err);
      mount(host, chartTable(chart, notice));
    });
  return host;
}

/** The labels of the baked limit (one, or a list), as they are. */
const limitLabels = (limit) => [].concat(limit || []).map((l) => (l && l.label) || "").filter(Boolean);
/** The baked margin words of the judged point (one, or a list), as they are. */
const marginTexts = (current) => [].concat(current || []).map((c) => (c && c.margin_text) || "").filter(Boolean);

/** The chart's numbers as the table the spine baked (`page.chart_table`):
 *  its head and rows as text, a long series cut to its ends with a row that
 *  counts the rest, its bands, rules and estimates, and the limit and the
 *  judged point's words under it. What slipped through (review of P2): this
 *  printed every row of the spec's data, 250 rows of 17 digits for the CFD
 *  settling chart, wider than its card, and left out the tolerance and the
 *  estimates, which are not in that data. */
function chartTable(chart, notice) {
  const table = chart.table || { head: [], rows: [] };
  return el("div", { class: "fig-table" },
    el("p", { class: "nk-notice", role: "note", text: notice || "" }),
    el("div", { class: "fig-table-scroll" },
      el("table", {},
        el("thead", {}, el("tr", {}, ...(table.head || []).map((h) => el("th", { text: h || "" })))),
        el("tbody", {}, ...(table.rows || []).map((r) => el("tr", {},
          ...r.map((cell) => el("td", { text: cell || "" }))))))),
    ...limitLabels(chart.limit).map((text) => el("p", { class: "small", text })),
    ...marginTexts(chart.current).map((text) => el("p", { class: "small", text })));
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
        ...(scale.ticks || []).map((t) => el("span", { class: `fig-tick${tickEnd(t.at)}`,
          style: { left: `${(Number(t.at) * 100).toFixed(2)}%` } },
          el("span", { class: "fig-tick-text", text: t.text || "" })))),
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

/** Where a tick's words sit on its mark: centred, or from the mark inward
 *  near an end of the ramp, so they stay inside the legend. Layout alone: the
 *  mark itself is always at the baked position (``.fig-tick::before`` at the
 *  tick's own left). What slipped through (review of P2): the first and last
 *  ticks' words were moved by `:first-child` and `:last-child` rules and the
 *  mark moved with them, up to 17 px off its value on the speed legend, and an
 *  interior first tick (the pressure's 0.0, at 0.165) too. */
function tickEnd(at) {
  const where = Number(at);
  return where < 0.1 ? " fig-tick--start" : where > 0.9 ? " fig-tick--end" : "";
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

/** A still: its marks' words in a row above the picture, each over its baked
 *  position with a short line down to the picture's edge, and the picture
 *  linked to its full file. Nothing is drawn over the picture: the lines in it
 *  are the tool's own. What slipped through (review of P2): the words sat on
 *  the picture, and on a phone a 10 to 1 strip 29 px high was mostly hidden
 *  by them; a white line drawn over each plane hid the black line ParaView
 *  drew there. Exported for the hero of both pages, with ``src`` the hero's
 *  own file. */
export function figureStill(fig, src) {
  const marks = fig.marks || [];
  return el("div", { class: "fig-still-box" },
    marks.length
      ? el("div", { class: "fig-marks", "aria-hidden": "true" },
          ...marks.map((m) => el("span", { class: `fig-mark${tickEnd(m.at)}`,
            style: { left: `${(Number(m.at) * 100).toFixed(2)}%` } },
            el("span", { class: "fig-mark-text", text: m.text || "" }))))
      : null,
    el("a", { class: "fig-still", href: src || fig.src, target: "_blank", rel: "noopener" },
      el("img", { src: src || fig.src, alt: fig.alt || fig.title || "", loading: "lazy" })));
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
function turnButton(fig, build, words) {
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
        onError: (err) => {
          console.warn("3D view", fig.id, err);
          mount(frame, el("p", { class: "nk-notice", role: "note",
            text: ((words && words.figure) || {}).turn_failed || "" }));
        } });
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
    : fig.kind === "image" && fig.src ? figureStill(fig) : null;
  return el("figure", { class: `fig fig-${fig.kind} currency-${fig.currency}`, id: `figure-${fig.id}` },
    el("figcaption", { class: "fig-head" },
      el("span", { class: "fig-title", text: fig.title || fig.view }),
      figureChips(fig, words)),
    drawn ? null : el("p", { class: `fig-none tone-${look.tone}` },
      el("span", { class: "nk-glyph", "aria-hidden": "true", text: look.glyph }), ` ${fig.currency_word || ""}`),
    body,
    // The legend and the caption under the picture they explain, then the 3D
    // view, which the same legend explains (review of P2: the button sat
    // between the still and its legend).
    fig.kind === "image" ? scaleLegend(fig.scale) : null,
    fig.caption ? el("p", { class: "fig-caption", text: fig.caption }) : null,
    turnButton(fig, build, words),
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
  // The claim's own value: the binding one, else the first the bake marks
  // compared with the claim's acceptance condition, the rule the technical
  // record's claimRow keeps (panels.js). None compared, none shown. What
  // slipped through (the walkthrough after P2.6): with no binding value the
  // card fell back to the first row, so a Stale CFD claim (an opaque gate
  // reads Stale outside its own check run) headlined its guard cfd.regime's
  // 0.008696 fraction of limit above the 0.5222 Pa the claim is about.
  const judging = values.find((v) => v.binding) || values.find((v) => v.compared) || null;
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
    // Why the claim reads what it reads, in the bake's sentence (review of
    // P2: a failing card said its value and margin and never why it failed).
    // Not beside Checked (the value says it) or Stale (the card's currency
    // sentence says it).
    row.cause_text && !["checked", "stale"].includes(row.token)
      ? el("p", { class: "fig-cause", text: row.cause_text }) : null,
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
