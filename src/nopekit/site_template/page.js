// SPDX-License-Identifier: Apache-2.0
// page.js: the front page (architecture phase 5, SPEC 28).
//
// The outline, in order: the name; the representation; the verdict sentence
// and its count strip; the description; the grounding map; one section per
// board; the next steps; Made with nopekit. A reader who did not build the
// design learns what it is and what holds, and a designer gets from a red line
// to its evidence in two clicks.
//
// It is the engineering page (`engineering/index.html`, whose `<base href="../">`
// makes every address below resolve against the site's root), and it still
// draws a front page from before the two pages at the root. It needs no page
// menu: `#viewnav-name` is filled when the shell has one. The marketing page is
// marketing.js; the verdict, the theme and the build banner are in lib/, one
// copy for both pages.
//
// It reads `data/page.json` and `data/map.json` (the bake), `data/state.json`
// for the views alone (the representation), and `data/build.json` when it is
// there (the build time, and live mode). Every number, status, word and order
// on this page is in one of those files: this script maps them to the DOM and
// handles hover, selection, the "worst first" control, pan and zoom, the
// drawer, the theme and the 3D view. It computes no status, margin, readiness
// or sensitivity (SPEC 32, invariant 14). What slipped through before it: the
// reference page decided its go/no-go in the browser, from a claim list in its
// own script, so a claim added to a board never reached the board.
//
// The technical record (every claim, every verdict with its locators, the
// parameters with what lost, the evidence, the gaps, the decisions) is
// technical.html, drawn by app.js from state.json.

import { el, mount, $ } from "./lib/dom.js";
import { lookOf } from "./lib/format.js";
import { renderMap, mapList } from "./lib/map.js";
import { createDrawer } from "./lib/drawer.js";
import { renderSections, renderNext, renderProse } from "./lib/sections.js";
import { readBuild, watchBuild } from "./lib/live.js";
import { verdictBlock } from "./lib/verdict.js";
import { themeButton, menuName } from "./lib/theme.js";
import { paintBuild } from "./lib/banner.js";
import { createViewer } from "./lib/viewer3d.js";
import { renderImage, renderDiagram } from "./lib/stage.js";
import { figureTag, figureLegends, figureStill, flatToggle } from "./lib/figures.js";

const PHONE = window.matchMedia ? window.matchMedia("(max-width: 759px)") : null;

const page = {
  doc: null,          // page.json
  map: null,          // map.json
  state: null,        // state.json (views only)
  build: null,        // build.json, or null
  drawer: null,
  mapApi: null,
  worstFirst: false,
  repView: null,      // the view the representation shows, and its viewer
  viewer: null,
};

themeButton();
boot();

async function boot() {
  let docs;
  try {
    docs = await Promise.all(["data/page.json", "data/map.json", "data/state.json"].map(fetchJson));
  } catch (err) {
    noData(err);
    return;
  }
  [page.doc, page.map, page.state] = docs;
  page.build = await readBuild();
  render();
  watchBuild(refresh, showBuild, page.build);
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
  return res.json();
}

/** New data from a rebuild (live mode). The scroll, the open drawer, the zoom
 *  and the selection stay where they are. */
async function refresh(build) {
  let docs;
  try {
    docs = await Promise.all(["data/page.json", "data/map.json", "data/state.json"].map(fetchJson));
  } catch (err) {
    return;                                    // the next poll tries again
  }
  [page.doc, page.map, page.state] = docs;
  page.build = build;
  const scroll = window.scrollY;
  render({ again: true });
  window.scrollTo(0, scroll);
}

// --------------------------------------------------------------------------- //
// the outline
// --------------------------------------------------------------------------- //
function render({ again = false } = {}) {
  const doc = page.doc;
  const words = doc.words || {};
  const headings = words.headings || {};
  const meta = doc.meta || {};
  // The tab says which page it is when the shell has the page menu; a front
  // page from before the two pages keeps the name alone.
  if (meta.name) document.title = $(".viewnav") ? `${meta.name} · Engineering` : meta.name;
  menuName(meta);

  if (!page.drawer) {
    page.drawer = createDrawer(doc, page.map, { onChange: (kind, key) => {
      if (!page.mapApi || !page.mapApi.select) return;
      if (kind) page.mapApi.select(kind, key); else page.mapApi.clear();
    } });
    document.body.appendChild(page.drawer.element);
  } else {
    page.drawer.update(doc, page.map);
  }
  const openClaim = (id) => page.drawer.open("claim", id);

  // 1. the name
  mount($("#name"), meta.name || "", meta.revision ? el("span", { class: "rev", text: meta.revision }) : null);

  // 2. the representation (kept across a live rebuild when its view is the same
  // and, for a figure, the whole baked figure: its chips and its sentence too)
  const rep = doc.representation || {};
  if (!again || page.repView !== repKeyOf(rep)) representation(rep, words);

  // 3. the verdict, right under the representation
  mount($("#verdict"), ...verdictBlock(doc.verdict || {}, words));

  // 4. the description
  mount($("#description"), ...description(doc, openClaim));

  // 5. the map
  mount($("#map-title"), headings.map || "");
  mount($("#map-legend"), ...legend(page.map, words));
  mapCaption(page.map, words);
  drawMap();

  // 6. one section per board
  mount($("#boards"), ...renderSections(doc, { onClaim: openClaim, build: page.build }));

  // 7. next steps
  mount($("#next-title"), headings.next || "");
  mount($("#next-body"), ...renderNext(doc, { onClaim: openClaim }));

  // 9. the footer: the technical record, and when this was built
  mount($("#technical-link"), headings.technical || "technical.html");
  showBuild(page.build);
  if (!again) applyHash();
}

function description(doc, openClaim) {
  const prose = renderProse(doc.intro, doc, { onClaim: openClaim });
  if (prose) return [prose];
  const desc = doc.description || {};
  return [
    desc.summary ? el("p", { class: "lede", text: desc.summary }) : null,
    desc.notice ? el("p", { class: "nk-notice", text: desc.notice }) : null,
  ];
}

// --------------------------------------------------------------------------- //
// the representation
// --------------------------------------------------------------------------- //
const repKeyOf = (rep) => `${rep.view}|${JSON.stringify(rep.figure || null)}`;

/** The hero. A figure as the hero (issue #15) shows which result it is, with
 *  the chips of the claims its gate covers, under the picture; as a 3D field
 *  it turns its committed GLB in field mode (the colours as the file holds
 *  them, `lib/viewer3d.js`), with the scale's legend, and offers only the
 *  baked `controls`. */
async function representation(rep, words) {
  const host = $("#representation");
  if (page.viewer) { page.viewer.dispose(); page.viewer = null; }
  page.repView = repKeyOf(rep);
  let view = rep.view ? ((page.state && page.state.views) || []).find((v) => v.id === rep.view) : null;
  const fig = rep.figure || null;
  if (view && fig && rep.kind === "field") view = { ...view, kind: "field", src: fig.field_src || view.src };
  const tag = fig ? figureTag(fig, words) : null;
  if (!view) {
    mount(host, el("div", { class: "rep-empty" }, el("p", { text: rep.notice || "" })));
    return;
  }
  if (view.data_url && !(view.data && Object.keys(view.data).length)) {
    try { view.data = await fetchJson(view.data_url); } catch (err) { /* drawn without it */ }
  }
  const caption = rep.title ? el("p", { class: "rep-caption small", text: rep.title }) : null;
  const explodes = !fig || (rep.controls || []).includes("explode");
  if (rep.kind === "model3d" || rep.kind === "field") {
    const frame = el("div", { class: "viewer-host" });
    const slider = el("input", { class: "explode-slider", type: "range", min: "0", max: "100",
      value: "0", "aria-label": "Explode the assembly",
      oninput: (ev) => page.viewer && page.viewer.setExplode(Number(ev.target.value) / 100) });
    const pill = el("div", { class: "control-bar", role: "toolbar", "aria-label": "Viewer controls" },
      el("label", { class: "explode" },
        el("span", { class: "explode-cap explode-cap--l", text: "Assembled" }), slider,
        el("span", { class: "explode-cap explode-cap--r", text: "Exploded" })));
    pill.hidden = true;
    const box = el("div", { class: "viewer", id: "hero3d" }, frame,
      el("div", { class: "hint", text: "Drag to turn. Scroll to zoom." }), pill);
    mount(host, box, caption, tag, fig ? figureLegends(fig) : null);
    page.viewer = createViewer({
      host: frame, view, field: !!fig, light: fig ? (fig.light || "") : undefined,
      onReady: (api) => {
        pill.hidden = !(explodes && api.canExplode);
        // A lit figure's flat colours (design P2), as on its card.
        const flat = flatToggle(api, fig && (fig.turn || {}).flat_word);
        if (flat) box.after(flat);
      },
      onError: (err) => {
        page.viewer = null;
        mount(frame, el("div", { class: "rep-empty" },
          el("p", { text: "The 3D view did not load." }),
          el("p", { class: "small", text: err && err.message ? err.message : String(err) })));
      },
    });
    return;
  }
  // A figure still as the hero is drawn as on its card: its plane words over
  // their lines, and its caption, the one text that says what the lines are.
  // What slipped through (review of P2): the hero drew the bare picture, two
  // black lines across it and nothing on the page that named them.
  if (rep.kind === "image") {
    mount(host, el("div", { class: fig ? "rep-flat rep-figure" : "rep-flat" },
      fig ? figureStill(fig, view.src) : renderImage(view, [], null)), caption, tag,
      fig ? figureLegends(fig) : null,
      fig && fig.caption ? el("p", { class: "fig-caption", text: fig.caption }) : null);
    return;
  }
  const flat = el("div", { class: "rep-flat" });
  const note = el("div", {});
  mount(host, flat, note, caption);
  renderDiagram(view, flat, note);
}

// --------------------------------------------------------------------------- //
// the map
// --------------------------------------------------------------------------- //
function legend(map, words) {
  const tokens = (words.tokens || {});
  const on = new Set();
  const chips = (map.legend || []).map((item) => {
    const look = lookOf(item.token);
    const said = tokens[item.token] || {};
    const button = el("button", { class: "lgf", type: "button", "aria-pressed": "false",
      title: said.hint || "",
      onclick: () => {
        if (on.has(item.token)) on.delete(item.token); else on.add(item.token);
        button.setAttribute("aria-pressed", String(on.has(item.token)));
        if (page.mapApi && page.mapApi.showTokens) page.mapApi.showTokens(on.size ? on : null);
      } },
      lineSample(look),
      el("span", { class: `nk-glyph tone-${look.tone}`, "aria-hidden": "true", text: look.glyph }),
      el("span", { text: said.word || item.token }),
      el("span", { class: "lg-n", text: String(item.n) }));
    return button;
  });
  return [...chips, amberChip(map, words)].filter(Boolean);
}

/** The caption over the drawing and the trace's note under it: what the
 *  lines are, then whether the links from the choices were measured, which
 *  choices the test did not move, and whether a trace runs now. Every word is
 *  baked (`words.trace`, `map.trace`); `index.html` is the project's own and
 *  never regenerated, so the caption is written here. */
function mapCaption(map, words) {
  const trace = (map && map.trace) || {};
  const said = (words && words.trace) || {};
  const desk = $(".maptools .cap-desk");
  if (desk && said.caption) {
    mount(desk, `${said.caption} Point at a line, a station or a group to show its links. Click one to see its evidence.`);
  }
  let note = $(".maptools .trace-note");
  if (!note && desk) {
    note = el("p", { class: "cap trace-note" });
    desk.after(note);
  }
  if (!note) return;
  const running = page.build && page.build.tracing && said.running ? said.running : "";
  mount(note, [trace.notice, trace.text, running].filter(Boolean).join(" "));
}

/** The amber chip of the legend: shown only when some line carries the
 *  bake's `amber` mark, and it lights those lines. */
function amberChip(map, words) {
  const marked = (map.lines || []).filter((l) => (l.marks || []).includes("amber")).length;
  const said = ((words.trace || {}).amber_legend) || "";
  if (!marked || !said) return null;
  const button = el("button", { class: "lgf lg-amber", type: "button", "aria-pressed": "false",
    onclick: () => {
      const on = button.getAttribute("aria-pressed") !== "true";
      button.setAttribute("aria-pressed", String(on));
      if (page.mapApi && page.mapApi.showTokens) page.mapApi.showTokens(null, on ? "amber" : "");
    } },
    el("span", { class: "lg-amber-band", "aria-hidden": "true" }),
    el("span", { text: said }),
    el("span", { class: "lg-n", text: String(marked) }));
  return button;
}

function lineSample(look) {
  const ns = "http://www.w3.org/2000/svg";
  const s = document.createElementNS(ns, "svg");
  s.setAttribute("width", "26"); s.setAttribute("height", "10"); s.setAttribute("aria-hidden", "true");
  s.setAttribute("class", "lg-line");
  const p = document.createElementNS(ns, "path");
  p.setAttribute("d", "M2,5 H24");
  p.setAttribute("class", `track tk-${look.stroke || "dotted"} tone-${look.tone}`);
  s.appendChild(p);
  return s;
}

function drawMap() {
  const host = $("#map-host");
  const keep = page.mapApi && page.mapApi.view;
  if (page.mapApi && page.mapApi.destroy) page.mapApi.destroy();
  page.mapApi = null;
  const onSelect = (kind, key) => page.drawer.open(kind, key);
  const onBoard = (key) => {
    const target = document.getElementById(`board-${key}`);
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  const phone = PHONE && PHONE.matches;
  document.body.classList.toggle("map-phone", !!phone);
  if (phone) {
    mount(host, mapList(page.map, page.doc, { onSelect, onBoard }));
    return;
  }
  page.mapApi = renderMap(host, page.map, page.doc, { onSelect, onBoard, worstFirst: page.worstFirst,
    onRescale: () => drawMap() });
  if (keep) page.mapApi.view = keep;
  const current = page.drawer && page.drawer.current;
  if (current) page.mapApi.select(current[0], current[1]);
}

if (PHONE && PHONE.addEventListener) PHONE.addEventListener("change", () => { if (page.map) drawMap(); });

$("#map-worst") && $("#map-worst").addEventListener("click", (ev) => {
  page.worstFirst = !page.worstFirst;
  ev.currentTarget.setAttribute("aria-pressed", String(page.worstFirst));
  if (page.map) drawMap();
});
$("#map-in") && $("#map-in").addEventListener("click", () => page.mapApi && page.mapApi.zoomIn());
$("#map-out") && $("#map-out").addEventListener("click", () => page.mapApi && page.mapApi.zoomOut());
$("#map-fit") && $("#map-fit").addEventListener("click", () => page.mapApi && page.mapApi.reset());

// --------------------------------------------------------------------------- //
// build.json: the build time, and a failed rebuild
// --------------------------------------------------------------------------- //
function showBuild(build) {
  const words = (page.doc && page.doc.words) || {};
  paintBuild(build, words);
  if (page.map && page.doc) mapCaption(page.map, words);
}

// --------------------------------------------------------------------------- //
// chrome
// --------------------------------------------------------------------------- //
/** `#claim=C1` (or `#C1`) opens that claim's drawer; `#board-<id>` scrolls. */
function applyHash() {
  const raw = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  if (!raw) return;
  const m = raw.match(/^(claim|requirement|zone|station|board)=(.+)$/);
  if (m) { page.drawer.open(m[1], m[2]); return; }
  const target = document.getElementById(raw);
  if (target) target.scrollIntoView({ block: "start" });
}

/** The page with no data: what to run, never a blank page. */
function noData(err) {
  const isFile = location.protocol === "file:";
  mount($("#verdict"),
    el("p", { class: "verdict" }, el("b", { text: "This page has no data yet." })),
    el("p", { class: "small mono", text: err && err.message ? err.message : String(err) }),
    isFile
      ? el("p", {}, "Serve the page through a web server. A browser does not let a page read its data files from the disk. Run ",
          el("code", { class: "mono", text: "nopekit site serve" }), ".")
      : el("p", {}, "Build the data from the project root with ",
          el("code", { class: "mono", text: "nopekit site build" }),
          ". An older build has no front-page data. Build again to make it."));
}
