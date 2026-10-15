// SPDX-License-Identifier: Apache-2.0
// page.js: the front page (architecture phase 5, SPEC 28).
//
// The outline, in order: the name; the representation; the verdict sentence
// and its count strip; the description; the grounding map; one section per
// board; the next steps; Made with nopekit. A reader who did not build the
// design learns what it is and what holds, and a designer gets from a red line
// to its evidence in two clicks.
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
import { lookOf, stamp } from "./lib/format.js";
import { renderMap, mapList } from "./lib/map.js";
import { createDrawer } from "./lib/drawer.js";
import { renderSections, renderNext, renderProse } from "./lib/sections.js";
import { readBuild, watchBuild } from "./lib/live.js";
import { createViewer } from "./lib/viewer3d.js";
import { renderImage, renderDiagram } from "./lib/stage.js";

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
  document.title = meta.name || document.title;

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

  // 2. the representation (kept across a live rebuild when its view is the same)
  const rep = doc.representation || {};
  if (!again || page.repView !== rep.view) representation(rep);

  // 3. the verdict, right under the representation
  mount($("#verdict"), ...verdictBlock(doc.verdict || {}, words));

  // 4. the description
  mount($("#description"), ...description(doc, openClaim));

  // 5. the map
  mount($("#map-title"), headings.map || "");
  mount($("#map-legend"), ...legend(page.map, words));
  drawMap();

  // 6. one section per board
  mount($("#boards"), ...renderSections(doc, { onClaim: openClaim }));

  // 7. next steps
  mount($("#next-title"), headings.next || "");
  mount($("#next-body"), ...renderNext(doc, { onClaim: openClaim }));

  // 9. the footer: the technical record, and when this was built
  mount($("#technical-link"), headings.technical || "technical.html");
  showBuild(page.build);
  if (!again) applyHash();
}

/** The sentence, with its lead in bold up to the first full stop, then the
 *  count strip (the bake's tally, glyph and word on each chip), the limits line,
 *  and the notice when a result is older than the design. */
function verdictBlock(verdict, words) {
  const sentence = String(verdict.sentence || "");
  const cut = sentence.search(/\.(\s|$)/);
  const lead = cut >= 0 ? sentence.slice(0, cut + 1) : sentence;
  const rest = cut >= 0 ? sentence.slice(cut + 1) : "";
  const look = lookOf(verdict.token);
  return [
    el("p", { class: `verdict tone-${look.tone}` },
      el("span", { class: "verdict-glyph", "aria-hidden": "true", text: look.glyph }),
      el("b", { text: lead }), rest),
    (verdict.tally || []).length
      ? el("ul", { class: "tally" }, ...verdict.tally.map((t) => {
          const tl = lookOf(t.key, { errored: t.errored > 0 });
          return el("li", { class: `nk-chip tone-${tl.tone}` },
            el("span", { class: "nk-glyph", "aria-hidden": "true", text: tl.glyph }),
            el("span", { class: "nk-word", text: t.label }));
        }))
      : null,
    verdict.stale && verdict.notice
      ? el("p", { class: "nk-notice", role: "status" },
          el("span", { class: "nk-glyph", "aria-hidden": "true", text: "≈" }), verdict.notice)
      : null,
    verdict.limits ? el("p", { class: "limits small", text: verdict.limits }) : null,
  ];
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
async function representation(rep) {
  const host = $("#representation");
  if (page.viewer) { page.viewer.dispose(); page.viewer = null; }
  page.repView = rep.view;
  const view = rep.view ? ((page.state && page.state.views) || []).find((v) => v.id === rep.view) : null;
  if (!view) {
    mount(host, el("div", { class: "rep-empty" }, el("p", { text: rep.notice || "" })));
    return;
  }
  if (view.data_url && !(view.data && Object.keys(view.data).length)) {
    try { view.data = await fetchJson(view.data_url); } catch (err) { /* drawn without it */ }
  }
  const caption = rep.title ? el("p", { class: "rep-caption small", text: rep.title }) : null;
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
    mount(host, box, caption);
    page.viewer = createViewer({
      host: frame, view,
      onReady: (api) => { pill.hidden = !api.canExplode; },
      onError: (err) => {
        page.viewer = null;
        mount(frame, el("div", { class: "rep-empty" },
          el("p", { text: "The 3D view did not load." }),
          el("p", { class: "small", text: err && err.message ? err.message : String(err) })));
      },
    });
    return;
  }
  if (rep.kind === "image") {
    mount(host, el("div", { class: "rep-flat" }, renderImage(view, [], null)), caption);
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
  return (map.legend || []).map((item) => {
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
  const notices = words.notices || {};
  const banner = $("#build-banner");
  if (banner) {
    if (build && build.ok === false) {
      const message = String(build.error || "");     // the failed build's last line
      mount(banner, el("span", { class: "nk-glyph", "aria-hidden": "true", text: "!" }),
        el("span", { text: notices.build_failed || "" }),
        message ? el("code", { class: "mono", text: message }) : null);
      banner.hidden = false;
    } else {
      banner.hidden = true;
    }
  }
  const built = $("#built");
  if (built) {
    mount(built, build && build.built
      ? `Built ${stamp(build.built)}${build.live ? ". This page follows the build." : "."}` : "");
  }
}

// --------------------------------------------------------------------------- //
// chrome
// --------------------------------------------------------------------------- //
function themeButton() {
  const button = $("#themebtn");
  let saved = null;
  try { saved = window.localStorage.getItem("nopekit-theme"); } catch (err) { saved = null; }
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  if (!button) return;
  button.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { window.localStorage.setItem("nopekit-theme", next); } catch (err) { /* private window */ }
  });
}

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
