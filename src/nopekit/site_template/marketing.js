// SPDX-License-Identifier: Apache-2.0
// marketing.js: the marketing page (`marketing/index.html`).
//
// The outline, top to bottom: the design in a viewer a reader can turn,
// explode and colour, with the name, the summary and the verdict beside it;
// the story; what it must do; the choices behind it, and what lost to each;
// Made with nopekit. It is the page a person sends to someone who did not
// build the design. The engineering page (page.js) is one link away, with
// every claim and its evidence.
//
// It reads `data/page.json` (the bake), `data/state.json` for the views alone
// (a view resolves one way on both pages: from state.json's `views`, its
// `data_url` fetched when the build split it out), and `data/build.json` when
// it is there. Every status, word, count, order, label and heading on this
// page is in one of those files: this script maps them to the DOM and handles
// the viewer, its controls and the popovers. It computes no status, margin,
// readiness, order or plural (SPEC 32, invariant 14); a decision's order, its
// `shown` flag, its `lost_label` and the `decisions_more` label are baked.
//
// The verdict stays in the first screen at every width, with the same chips as
// the engineering page (lib/verdict.js): a page that leads with a render and
// hides a failing claim is what the doctrine forbids (SITE_CONTRACT, "What the
// page must show"). A `preferred_against` rejection reads the bake's
// `type_word`, which says "not recorded by <name>" until that person records it
// (invariant 13); this script never words a preference.
//
// The customizer is presentation alone. A colour, an exploded pose, a part
// shown alone or another baked view changes this page and nothing else: no
// design value, no fit, no strength, nothing a check reads. The parts popover
// says so in one line. (What it closes before it could slip through: a viewer
// whose colour picker reads as a configurator implies that the checks hold for
// the colour or the variant a reader chose.)

import { el, mount, $, svg } from "./lib/dom.js";
import { lookOf, tokenChip } from "./lib/format.js";
import { renderProse } from "./lib/sections.js";
import { readBuild, watchBuild } from "./lib/live.js";
import { createViewer } from "./lib/viewer3d.js";
import { renderImage, renderDiagram } from "./lib/stage.js";
import { figureTag, scaleLegend, figureStill } from "./lib/figures.js";
import { leadOf, tallyList } from "./lib/verdict.js";
import { themeButton, menuName } from "./lib/theme.js";
import { paintBuild } from "./lib/banner.js";

/** The presentation colours of the parts popover. Six plain finishes and no
 *  status hue: no red, green or amber (a status's colours on both pages), and
 *  no blue near the viewer's highlight (#2f7fd1), so a part a reader coloured
 *  never reads as a part a verdict lit. *Rejected:* a free colour picker (it
 *  offers the status hues); the page's status palette (a red part reads as a
 *  failing part); one colour per part kept in a record (a colour is not a
 *  design value, and a record would make it one). */
const SWATCHES = [
  { name: "Graphite", css: "#34373c" },
  { name: "White", css: "#f1f0eb" },
  { name: "Sand", css: "#cdb88f" },
  { name: "Plum", css: "#7b5c86" },
  { name: "Slate teal", css: "#5f8586" },
  { name: "Copper", css: "#a8673f" },
];

/** The storage key of a view's colours, one entry per view id: a reader's
 *  choice, kept in their browser only. *Rejected:* one key for every view (a
 *  part name in one view is another part, or none, in the next). */
const TINT_KEY = "nopekit-tints:";

/** The share of the width the model moves right on a wide screen, so the copy
 *  at the left does not cover it. 0.18: at 1440 px the copy column ends near
 *  560 px, and the model's centre then sits near 980 px. *Rejected:* 0.25 (on
 *  a 1000 px screen the model's right edge left the canvas); 0 with a solid
 *  panel behind the copy (it hid a third of the model). */
const FRAME_SHIFT = 0.18;

const WIDE = window.matchMedia ? window.matchMedia("(min-width: 980px)") : null;
const CALM = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;

const mk = {
  doc: null,          // page.json
  state: null,        // state.json (views only), or null
  build: null,        // build.json, or null
  viewer: null,       // the viewer's api, once loaded
  viewId: null,       // the view the stage shows now
  repView: null,      // the representation's key: its view, and its figure as baked
  repFigure: null,    // the representation's figure (issue #15), or null
  repControls: null,  // a figure hero's baked controls, or null
  popover: null,      // { panel, button } of the popover on screen
  observer: null,     // the IntersectionObserver that pauses the viewer
  visible: true,
};

themeButton();
boot();

async function boot() {
  try {
    mk.doc = await fetchJson("data/page.json");
  } catch (err) {
    noData(err);
    return;
  }
  mk.state = await readViews(mk.doc);
  mk.build = await readBuild();
  render();
  scrollToHash();
  watchBuild(refresh, showBuild, mk.build);
}

async function fetchJson(url) {
  const res = await fetch(url, { cache: "no-store" });
  if (!res.ok) throw new Error(`${url}: ${res.status} ${res.statusText}`);
  return res.json();
}

/** state.json, read only when the representation names a view. */
async function readViews(doc) {
  const rep = (doc && doc.representation) || {};
  if (!rep.view) return null;
  try { return await fetchJson("data/state.json"); } catch (err) { return null; }
}

/** New data from a rebuild (live mode): drawn in place, the scroll kept, and
 *  the viewer kept while the representation's view is the same. */
async function refresh(build) {
  let doc;
  try { doc = await fetchJson("data/page.json"); } catch (err) { return; }
  mk.doc = doc;
  mk.state = await readViews(doc);
  mk.build = build;
  const scroll = window.scrollY;
  render({ again: true });
  window.scrollTo(0, scroll);
}

// --------------------------------------------------------------------------- //
// the outline
// --------------------------------------------------------------------------- //
function render({ again = false } = {}) {
  const doc = mk.doc;
  const words = doc.words || {};
  const meta = doc.meta || {};
  if (meta.name) document.title = `${meta.name} · Marketing`;
  menuName(meta);

  mount($("#mk-eyebrow"), meta.revision || "");
  $("#mk-eyebrow").hidden = !meta.revision;
  mount($("#name"), meta.name || "");
  // The name's length sizes it to its room (marketing.css): presentation only.
  $("#name").style.setProperty("--mk-name-len", String(Math.max(8, String(meta.name || "").length)));
  mount($("#mk-tagline"), meta.summary || "");
  $("#mk-tagline").hidden = !meta.summary;
  mount($("#verdict"), ...verdictHead(doc.verdict || {}, words));
  mount($("#mk-copy-rest"), ...verdictRest(doc, words));

  const rep = doc.representation || {};
  if (!again || mk.repView !== repKeyOf(rep)) stage(rep);

  section($("#story"), storySection(doc, words));
  section($("#asked"), askedSection(doc, words));
  section($("#choices"), choicesSection(doc, words));
  showBuild(mk.build);
}

function section(host, children) {
  if (!host) return;
  const list = (children || []).filter(Boolean);
  host.hidden = !list.length;
  mount(host, ...list);
}

/** The headline, large, with the readiness glyph, then the tally chips, the
 *  stale notice in the page's register while `verdict.stale`, and the limits
 *  line. The headline is the bake's first sentence of the readiness sentence;
 *  a build from before `headline` falls back to the same cut the engineering
 *  page sets in bold.
 *
 *  All four are in #verdict, which stacks above the viewer below 980px, so a
 *  phone's first screen holds them all (SITE_CONTRACT, "What the page must
 *  show": the limits line is in the marketing page's floor). What slipped
 *  through (review of SPEC 40): the stale notice and the limits line were in
 *  #mk-copy-rest, which stacks under the viewer, so at 390x844 "Checked does
 *  not mean true" started at y=906 and the stale notice at y=863, both off
 *  the first screen, while the docs said above the fold at every width. */
function verdictHead(verdict, words) {
  const look = lookOf(verdict.token);
  const headline = verdict.headline || leadOf(verdict.sentence);
  const notices = (words && words.notices) || {};
  return [
    headline
      ? el("p", { class: `mk-headline tone-${look.tone}` },
          el("span", { class: "verdict-glyph", "aria-hidden": "true", text: look.glyph }),
          el("span", { text: headline }))
      : null,
    tallyList(verdict, { cls: "tally mk-tally" }),
    // The notice is baked (`verdict.notice_public`, issue #15 D1): "older than
    // the design" is false of a solver's result on an untouched design. A
    // page.json from before it falls back to the one sentence it had.
    verdict.stale && (verdict.notice_public || notices.stale_public)
      ? el("p", { class: "nk-notice mk-stale", role: "status" },
          el("span", { class: "nk-glyph", "aria-hidden": "true", text: "≈" }),
          verdict.notice_public || notices.stale_public)
      : null,
    verdict.limits ? el("p", { class: "limits mk-limits", text: verdict.limits }) : null,
  ];
}

/** The whole sentence in a block a reader unfolds, and the two buttons. */
function verdictRest(doc, words) {
  const verdict = doc.verdict || {};
  const headings = words.headings || {};
  const sentence = String(verdict.sentence || "");
  const headline = String(verdict.headline || leadOf(sentence));
  const story = doc.story || doc.intro;
  return [
    sentence && sentence !== headline && headings.unsettled
      ? el("details", { class: "mk-unsettled" },
          el("summary", { text: headings.unsettled }),
          el("p", { text: sentence }))
      : null,
    el("p", { class: "mk-cta" },
      story
        ? el("a", { class: "mk-btn mk-btn-primary", href: "marketing/#story", onclick: jumpTo("story"),
            text: "Read the story" })
        : null,
      el("a", { class: "mk-btn mk-btn-ghost", href: "engineering/",
        text: headings.evidence || "Engineering page" })),
  ];
}

/** A click on a same-page link: scroll there and keep the page's own path in
 *  the address (under the base element, a bare `#x` names the site's root). */
function jumpTo(id) {
  return (ev) => {
    const target = document.getElementById(id);
    if (!target) return;
    ev.preventDefault();
    target.scrollIntoView({ behavior: CALM && CALM.matches ? "auto" : "smooth", block: "start" });
    try { history.replaceState(null, "", `${location.pathname}#${id}`); } catch (err) { /* file: */ }
  };
}

/** The page renders after the browser's own jump to the fragment, which found
 *  an empty page: jump again once the sections are there. */
function scrollToHash() {
  const id = decodeURIComponent((location.hash || "").replace(/^#/, ""));
  const target = id ? document.getElementById(id) : null;
  if (target) target.scrollIntoView({ block: "start" });
}

const openClaim = (id) => location.assign(`engineering/#claim=${encodeURIComponent(id)}`);

// --------------------------------------------------------------------------- //
// the stage: the representation, and the customizer around a 3D view
// --------------------------------------------------------------------------- //
/** A hero's key: its view and, for a figure, the whole baked figure, so a
 *  live rebuild that moves a figure's chips or its sentence draws it again. */
const repKeyOf = (rep) => `${rep.view}|${JSON.stringify(rep.figure || null)}`;

/** The hero. A figure as the hero (issue #15) says which result it is under
 *  the picture, with the chips of the claims its gate covers, and as a 3D
 *  field it turns its committed GLB in field mode with the baked `controls`
 *  alone (spin): parts, colours, wireframe and explode act on a model's
 *  parts, and a solved field has none. */
function stage(rep) {
  const host = $("#mk-stage");
  const hero = $("#top");
  closePopover();
  disposeViewer();
  mk.repView = repKeyOf(rep);
  mk.repFigure = rep.figure || null;
  mk.repControls = Array.isArray(rep.controls) ? rep.controls : null;
  const view = findView(rep.view);
  const words = (mk.doc && mk.doc.words) || {};
  // No representation: a hero of text alone. No box, no controls and no
  // author's notice: the notice is for the person who builds the site, and
  // the build says it there.
  hero.classList.toggle("mk-hero--text", !view);
  hero.classList.remove("mk-hero--flat");
  if (!view) { mount(host); return; }
  if (rep.kind === "model3d" || rep.kind === "field") {
    mountViewer(rep.view, { first: true });
    return;
  }
  hero.classList.add("mk-hero--flat");
  const caption = rep.title ? el("figcaption", { class: "mk-caption", text: rep.title }) : null;
  withData(view).then(() => {
    if (mk.repView !== repKeyOf(rep)) return;       // a rebuild moved on meanwhile
    if (rep.kind === "image") {
      // A figure still is drawn as on its card, with its plane words and
      // caption (review of P2: two unnamed black lines on the hero).
      const fig = rep.figure;
      mount(host, el("figure", { class: fig ? "mk-flat mk-figure" : "mk-flat" },
        fig ? figureStill(fig, view.src) : renderImage(view, [], null), caption,
        fig ? figureTag(fig, words) : null, fig ? scaleLegend(fig.scale) : null,
        fig && fig.caption ? el("p", { class: "fig-caption", text: fig.caption }) : null));
      return;
    }
    const flat = el("div", { class: "mk-flat-svg" });
    const note = el("div", {});
    mount(host, el("figure", { class: "mk-flat" }, flat, note, caption));
    renderDiagram(view, flat, note);
  });
}

function findView(id) {
  if (!id) return null;
  const view = ((mk.state && mk.state.views) || []).find((v) => v.id === id) || null;
  const fig = mk.repFigure;
  // A figure hero as a 3D field: its committed GLB, never the still's PNG.
  if (view && fig && fig.view === id && fig.field_src) {
    return { ...view, kind: "field", src: fig.field_src };
  }
  return view;
}

async function withData(view) {
  if (view.data_url && !(view.data && Object.keys(view.data).length)) {
    try { view.data = await fetchJson(view.data_url); } catch (err) { /* drawn without it */ }
  }
  return view;
}

/** The baked views a reader may choose among: `representation.alternates`
 *  (the model views, the same file once, the representation's first), else
 *  the representation alone. */
function alternates() {
  const rep = (mk.doc && mk.doc.representation) || {};
  const listed = (rep.alternates || []).filter((a) => a && a.view && findView(a.view));
  if (listed.length) return listed;
  return rep.view ? [{ view: rep.view, title: rep.title || "", bytes: null }] : [];
}

function sizeText(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return "";
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1e3))} kB`;
}

function disposeViewer() {
  if (mk.observer) { mk.observer.disconnect(); mk.observer = null; }
  if (mk.viewer) { mk.viewer.dispose(); mk.viewer = null; }
}

/** The viewer for ``viewId``: the canvas, the loading state, then the control
 *  pill once the model is in. On a connection that asks to save data, a
 *  button loads it instead of the page. */
function mountViewer(viewId, { first = false } = {}) {
  const host = $("#mk-stage");
  closePopover();
  disposeViewer();
  mk.viewId = viewId;
  const view = findView(viewId);
  const choice = alternates().find((a) => a.view === viewId) || {};
  const size = sizeText(choice.bytes);
  const canvas = el("div", { class: "mk-canvas" });
  const box = el("div", { class: "viewer mk-viewer", id: "hero3d" }, canvas);
  mount(host, box);
  if (!view) {
    mount(canvas, problem("The 3D view did not load.", `No view ${viewId} in data/state.json.`));
    return;
  }
  const saving = first && navigator.connection && navigator.connection.saveData;
  if (saving) {
    box.appendChild(el("div", { class: "mk-loading" },
      el("button", { class: "mk-btn mk-btn-primary", type: "button",
        text: size ? `Show the 3D model (${size})` : "Show the 3D model",
        onclick: () => startViewer(view, box, canvas, size) })));
    return;
  }
  startViewer(view, box, canvas, size);
}

function startViewer(view, box, canvas, size) {
  const bar = el("span", { class: "mk-bar-fill" });
  const loading = el("div", { class: "mk-loading", role: "status" },
    el("div", { class: "mk-loading-card" },
      el("span", { class: "mk-spinner", "aria-hidden": "true" }),
      el("span", { class: "mk-loading-text", text: "Loading the model" }),
      size ? el("span", { class: "mk-loading-size", text: size }) : null,
      el("span", { class: "mk-bar", "aria-hidden": "true" }, bar)));
  const old = box.querySelector(".mk-loading");
  if (old) old.remove();
  box.appendChild(loading);
  const choice = alternates().find((a) => a.view === view.id) || {};
  const expected = Number(choice.bytes) || 0;
  const pressed = { spin: !(CALM && CALM.matches) };
  let spinButton = null;
  const fig = mk.repFigure && mk.repFigure.view === view.id ? mk.repFigure : null;
  if (fig) {
    const words = (mk.doc && mk.doc.words) || {};
    box.after(el("div", { class: "mk-figure-tag" }, figureTag(fig, words), scaleLegend(fig.scale)));
  }
  mk.viewer = createViewer({
    host: canvas, view, field: !!fig,
    onProgress: (loaded, total) => {
      const whole = total || expected;
      if (whole > 0) bar.style.width = `${Math.min(100, (loaded / whole) * 100).toFixed(1)}%`;
    },
    onReady: (api) => {
      loading.remove();
      mk.viewer = api;
      api.setFrameShift(WIDE && WIDE.matches ? FRAME_SHIFT : 0);
      restoreTints(view, api);
      api.setSpin(pressed.spin);
      spinButton = controls(view, api, box, pressed, fig ? mk.repControls : null);
      watchSight(api);
    },
    onSpinStop: () => { pressed.spin = false; if (spinButton) spinButton.setAttribute("aria-pressed", "false"); },
    onError: (err) => {
      mk.viewer = null;
      loading.remove();
      mount(canvas, problem("The 3D view did not load.", err && err.message ? err.message : String(err)));
    },
  });
}

function problem(title, detail) {
  return el("div", { class: "rep-empty" },
    el("p", { text: title }),
    detail ? el("p", { class: "small", text: detail }) : null);
}

/** Draw nothing while the stage is out of sight or the tab is hidden. */
function watchSight(api) {
  const apply = () => api.pause(!mk.visible || document.visibilityState === "hidden");
  if ("IntersectionObserver" in window) {
    mk.observer = new IntersectionObserver((entries) => {
      for (const entry of entries) mk.visible = entry.isIntersecting;
      apply();
    });
    mk.observer.observe($("#mk-stage"));
  }
  document.addEventListener("visibilitychange", apply);
}

if (WIDE && WIDE.addEventListener) {
  WIDE.addEventListener("change", () => {
    if (mk.viewer && mk.viewer.setFrameShift) mk.viewer.setFrameShift(WIDE.matches ? FRAME_SHIFT : 0);
  });
}

// --------------------------------------------------------------------------- //
// the control pill and its popovers
// --------------------------------------------------------------------------- //
const ICONS = {
  spin: "M12 5a7 7 0 1 1-6.3 4M5 4v5h5",
  parts: "M4 7l8-4 8 4-8 4-8-4zm0 5l8 4 8-4M4 17l8 4 8-4",
  views: "M3 7h18M3 12h18M3 17h18",
  wire: "M12 3l8 5v8l-8 5-8-5V8l8-5zm0 0v18M4 8l16 8M20 8L4 16",
  reset: "M4 12a8 8 0 1 0 2.3-5.7M4 4v4h4",
  full: "M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5",
};

function icon(name) {
  return svg("svg", { class: "mk-icon", viewBox: "0 0 24 24", width: "18", height: "18",
    "aria-hidden": "true", focusable: "false" },
    svg("path", { d: ICONS[name], fill: "none", stroke: "currentColor", "stroke-width": "1.8",
      "stroke-linecap": "round", "stroke-linejoin": "round" }));
}

function ctl(name, label, spec = {}) {
  return el("button", { class: "mk-ctl", type: "button", title: label, ...spec },
    icon(name), el("span", { class: "mk-ctl-label", text: label }));
}

/** The pill: explode (two or more movers), spin, parts, views (two or more
 *  baked model views), wireframe, reset and full screen (where the browser
 *  has it). Returns the spin button, which the viewer turns off when a hand
 *  stops the model. */
function controls(view, api, box, pressed, only = null) {
  const tools = [];
  let slider = null;
  // A figure hero's baked `controls` (spin): nothing else applies to a field.
  if (only) {
    const spinOnly = ctl("spin", "Spin", { "aria-pressed": String(pressed.spin) });
    spinOnly.addEventListener("click", () => {
      pressed.spin = spinOnly.getAttribute("aria-pressed") !== "true";
      spinOnly.setAttribute("aria-pressed", String(pressed.spin));
      api.setSpin(pressed.spin);
    });
    if (only.includes("spin")) tools.push(spinOnly);
    box.appendChild(el("div", { class: "mk-pill", role: "toolbar", "aria-label": "Viewer controls" }, ...tools));
    box.appendChild(el("p", { class: "mk-hint", text: "Drag to turn. Scroll to zoom." }));
    return spinOnly;
  }
  if (api.canExplode && api.movers.length >= 2) {
    slider = el("input", { class: "explode-slider mk-slider", type: "range", min: "0", max: "100",
      value: "0", "aria-label": "Explode the model",
      oninput: (ev) => api.setExplode(Number(ev.target.value) / 100) });
    tools.push(el("label", { class: "explode mk-explode" },
      el("span", { class: "explode-cap explode-cap--l", text: "Assembled" }), slider,
      el("span", { class: "explode-cap explode-cap--r", text: "Exploded" })));
  }
  const spin = ctl("spin", "Spin", { "aria-pressed": String(pressed.spin) });
  spin.addEventListener("click", () => {
    pressed.spin = spin.getAttribute("aria-pressed") !== "true";
    spin.setAttribute("aria-pressed", String(pressed.spin));
    api.setSpin(pressed.spin);
  });
  tools.push(spin);

  const rows = partRows(view, api);
  const isolated = { name: null };
  if (rows.length) {
    const partsBtn = ctl("parts", "Parts", { "aria-expanded": "false", "aria-haspopup": "dialog" });
    const panel = partsPanel(view, api, rows, isolated);
    partsBtn.addEventListener("click", () => togglePopover(panel, partsBtn));
    tools.push(el("div", { class: "mk-pop-anchor" }, partsBtn, panel));
  }
  const choices = alternates();
  if (choices.length > 1) {
    const viewsBtn = ctl("views", "Views", { "aria-expanded": "false", "aria-haspopup": "dialog" });
    const panel = viewsPanel(choices);
    viewsBtn.addEventListener("click", () => togglePopover(panel, viewsBtn));
    tools.push(el("div", { class: "mk-pop-anchor" }, viewsBtn, panel));
  }
  const wire = ctl("wire", "Wireframe", { "aria-pressed": "false" });
  wire.addEventListener("click", () => {
    const on = wire.getAttribute("aria-pressed") !== "true";
    wire.setAttribute("aria-pressed", String(on));
    api.setWireframe(on);
  });
  tools.push(wire);
  const reset = ctl("reset", "Reset");
  reset.addEventListener("click", () => {
    api.reset();
    api.home();
    forgetTints(view);
    if (slider) slider.value = "0";
    wire.setAttribute("aria-pressed", "false");
    isolated.name = null;
    closePopover();
    box.querySelectorAll(".mk-swatch").forEach((b) => b.setAttribute("aria-pressed", b.dataset.css ? "false" : "true"));
    box.querySelectorAll(".mk-only").forEach((b) => { b.setAttribute("aria-pressed", "false"); mount(b, "Show only"); });
  });
  tools.push(reset);
  if (document.fullscreenEnabled) {
    const full = ctl("full", "Full screen", { "aria-pressed": "false" });
    const hero = $("#top");
    full.addEventListener("click", () => {
      if (document.fullscreenElement) document.exitFullscreen();
      else if (hero.requestFullscreen) hero.requestFullscreen();
    });
    document.addEventListener("fullscreenchange", () => {
      full.setAttribute("aria-pressed", String(document.fullscreenElement === hero));
    });
    tools.push(full);
  }
  box.appendChild(el("div", { class: "mk-pill", role: "toolbar", "aria-label": "Viewer controls" }, ...tools));
  box.appendChild(el("p", { class: "mk-hint", text: "Drag to turn. Scroll to zoom." }));
  return spin;
}

/** The rows of the parts popover: the view's groups (each group's nodes the
 *  union of its parts' nodes), else its parts, else the movers of its explode
 *  manifest, in the order the view lists them. */
function partRows(view, api) {
  const meta = view.meta || {};
  const parts = meta.parts && typeof meta.parts === "object" && !Array.isArray(meta.parts) ? meta.parts : {};
  const groups = meta.groups && typeof meta.groups === "object" && !Array.isArray(meta.groups) ? meta.groups : {};
  const listOf = (value) => (Array.isArray(value) ? value : ((value && value.parts) || [])).map(String);
  const nodesOf = (part) => (Array.isArray(parts[part]) ? parts[part].map(String) : [part]);
  if (Object.keys(groups).length) {
    return Object.keys(groups).map((name) => ({
      name, nodes: Array.from(new Set(listOf(groups[name]).flatMap(nodesOf))),
    }));
  }
  if (Object.keys(parts).length) {
    return Object.keys(parts).map((name) => ({ name, nodes: nodesOf(name) }));
  }
  return (api.movers || []).map((name) => ({ name, nodes: [name] }));
}

const label = (name) => String(name).replace(/_/g, " ");

function partsPanel(view, api, rows, isolated) {
  const saved = readTints(view.id);
  const list = el("ul", { class: "mk-parts" }, ...rows.map((row) => {
    const only = el("button", { class: "mk-only", type: "button", "aria-pressed": "false",
      text: "Show only" });
    only.addEventListener("click", () => {
      const on = isolated.name !== row.name;
      isolated.name = on ? row.name : null;
      api.isolateNodes(on ? row.nodes : null);
      list.querySelectorAll(".mk-only").forEach((b) => { b.setAttribute("aria-pressed", "false"); mount(b, "Show only"); });
      if (on) { only.setAttribute("aria-pressed", "true"); mount(only, "Show all"); }
    });
    const current = saved[row.name] || "";
    const swatch = (entry) => {
      const css = entry ? entry.css : "";
      return el("button", { class: `mk-swatch${css ? "" : " mk-swatch-orig"}`, type: "button",
        title: entry ? entry.name : "Original", "aria-label": entry ? entry.name : "Original",
        "aria-pressed": String(css === current), dataset: { css },
        style: css ? { background: css } : null,
        onclick: (ev) => {
          api.tint(row.nodes, css || null);
          storeTint(view.id, row.name, css);
          ev.currentTarget.parentElement.querySelectorAll(".mk-swatch")
            .forEach((b) => b.setAttribute("aria-pressed", String(b === ev.currentTarget)));
        } });
    };
    return el("li", { class: "mk-part" },
      el("div", { class: "mk-part-top" }, el("span", { class: "mk-part-name", text: label(row.name) }), only),
      el("div", { class: "mk-swatches", role: "group", "aria-label": `Colour of ${label(row.name)}` },
        swatch(null), ...SWATCHES.map(swatch)));
  }));
  return popover("Parts", list,
    el("p", { class: "mk-note", text: "The colours show on this page only. The checks read the design in the records." }));
}

function viewsPanel(choices) {
  const list = el("ul", { class: "mk-views" }, ...choices.map((choice) => el("li", {},
    el("button", { class: "mk-view", type: "button", "aria-pressed": String(choice.view === mk.viewId),
      onclick: () => { closePopover(); mountViewer(choice.view); } },
      el("span", { text: choice.title || choice.view }),
      sizeText(choice.bytes) ? el("span", { class: "mk-view-size", text: sizeText(choice.bytes) }) : null))));
  return popover("Views", list, null);
}

function popover(title, body, foot) {
  // Close puts the focus back on the popover's button, as Esc does. What
  // slipped through (review of SPEC 40): it closed without the focus, the
  // focused × was hidden, and a keyboard's next Tab started again at the top
  // of the page.
  const close = el("button", { class: "mk-pop-close", type: "button", "aria-label": "Close", text: "×",
    onclick: () => closePopover({ focus: true }) });
  const panel = el("div", { class: "mk-pop", role: "dialog", "aria-label": title, tabindex: "-1", hidden: true },
    el("div", { class: "mk-pop-head" }, el("span", { class: "mk-pop-title", text: title }), close),
    el("div", { class: "mk-pop-body" }, body), foot);
  return panel;
}

/** One popover on screen at a time; Esc, a click outside and Close shut it,
 *  and the focus goes back to its button. */
function togglePopover(panel, button) {
  const same = mk.popover && mk.popover.panel === panel;
  closePopover();
  if (same) return;
  panel.hidden = false;
  button.setAttribute("aria-expanded", "true");
  mk.popover = { panel, button };
  panel.focus({ preventScroll: true });
}

function closePopover({ focus = false } = {}) {
  if (!mk.popover) return;
  const { panel, button } = mk.popover;
  panel.hidden = true;
  button.setAttribute("aria-expanded", "false");
  mk.popover = null;
  if (focus) button.focus();
}

document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && mk.popover) closePopover({ focus: true });
});
document.addEventListener("pointerdown", (ev) => {
  if (!mk.popover) return;
  const anchor = mk.popover.panel.parentElement;
  if (anchor && !anchor.contains(ev.target)) closePopover();
});

// --------------------------------------------------------------------------- //
// colours: a reader's, in their browser, one entry per view
// --------------------------------------------------------------------------- //
function readTints(viewId) {
  try {
    const raw = window.localStorage.getItem(TINT_KEY + viewId);
    const found = raw ? JSON.parse(raw) : {};
    return found && typeof found === "object" ? found : {};
  } catch (err) {
    return {};
  }
}

function storeTint(viewId, row, css) {
  const saved = readTints(viewId);
  if (css) saved[row] = css; else delete saved[row];
  try { window.localStorage.setItem(TINT_KEY + viewId, JSON.stringify(saved)); } catch (err) { /* private window */ }
}

function forgetTints(view) {
  try { window.localStorage.removeItem(TINT_KEY + view.id); } catch (err) { /* private window */ }
}

function restoreTints(view, api) {
  const saved = readTints(view.id);
  for (const row of partRows(view, api)) {
    if (saved[row.name]) api.tint(row.nodes, saved[row.name]);
  }
}

// --------------------------------------------------------------------------- //
// the story, what it must do, the choices behind it
// --------------------------------------------------------------------------- //
/** The story: `story.md`, else `intro.md`, each with its stamp's notice when
 *  it was written before the latest results. With neither, no section: the
 *  summary is in the hero, and a page that says it twice is padding. */
function storySection(doc, words) {
  const prose = doc.story || doc.intro;
  if (!prose) return [];
  const headings = words.headings || {};
  return [
    headings.story ? el("h2", { text: headings.story }) : null,
    renderProse(prose, doc, { onClaim: openClaim }),
  ];
}

/** One card for each requirement, in the map's order: the person's words, the
 *  status the bake gave it (with its marks), each mark's words under it, and
 *  one link to its evidence. The chip's "!" and "◆" carry their words as a
 *  label only; this page has no drawer to say them, so the card says them in
 *  full (review of SPEC 40: a requirement whose claim the trace flips read as
 *  a plain green chip here). */
function askedSection(doc, words) {
  const rows = doc.requirements || [];
  if (!rows.length) return [];
  const headings = words.headings || {};
  return [
    headings.asked ? el("h2", { text: headings.asked }) : null,
    el("ul", { class: "mk-asked" }, ...rows.map((row) => el("li", { class: "mk-card mk-req" },
      el("p", { class: "mk-req-text", text: row.statement || row.id }),
      el("div", { class: "mk-req-foot" },
        tokenChip(row.token, row.word, { errored: row.errored, marks: row.marks, notices: words.notices,
          trace: words.trace, group: true }),
        el("a", { class: "mk-more", href: `engineering/#requirement=${encodeURIComponent(row.id)}`,
          text: headings.evidence || row.id })),
      ...markNotes(row.marks, words, { group: true })))),
  ];
}

/** The words of a row's marks, in the bake's words: `disagree`'s notice and
 *  amber's word, the one the chip's "◆" carries (`trace.amber_group` for a
 *  row that stands for several claims, `trace.amber_flips` for one claim). */
function markNotes(marks, words, { group = false } = {}) {
  const list = marks || [];
  const notices = words.notices || {};
  const trace = words.trace || {};
  const amberWord = group ? trace.amber_group : trace.amber_flips;
  return [
    list.includes("disagree") && notices.disagree
      ? el("p", { class: "nk-notice tone-bad mk-mark-note", text: notices.disagree }) : null,
    list.includes("amber") && amberWord
      ? el("p", { class: "mk-amber-note" },
          el("span", { class: "nk-amber", "aria-hidden": "true", text: "◆" }), ` ${amberWord}`)
      : null,
  ];
}

/** The decisions, newest first as baked: the `shown` ones as cards, every
 *  other one inside one block a reader unfolds, then the values no decision
 *  holds and what lost to each. */
function choicesSection(doc, words) {
  const headings = words.headings || {};
  const decisions = doc.decisions || [];
  const shown = decisions.filter((d) => d.shown);
  const rest = decisions.filter((d) => !d.shown);
  const losers = doc.losers || [];
  if (!decisions.length && !losers.length) return [];
  return [
    headings.decisions ? el("h2", { text: headings.decisions }) : null,
    shown.length ? el("div", { class: "mk-decisions" }, ...shown.map((d) => decisionCard(d, words))) : null,
    rest.length
      ? el("details", { class: "mk-fold" },
          el("summary", { text: doc.decisions_more || "" }),
          el("div", { class: "mk-decisions" }, ...rest.map((d) => decisionCard(d, words))))
      : null,
    losers.length
      ? el("details", { class: "mk-fold" },
          el("summary", { text: headings.losers || "" }),
          el("ul", { class: "mk-values" }, ...losers.map(valueRow)))
      : null,
  ];
}

function day(when) {
  const date = new Date(String(when || ""));
  if (Number.isNaN(date.getTime())) return String(when || "");
  return date.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function decisionCard(d, words) {
  const headings = words.headings || {};
  const summary = String(d.summary || "");
  const clamp = summary ? el("p", { class: "mk-clamp", text: summary }) : null;
  const whole = summary && headings.whole_decision
    ? el("details", { class: "mk-whole" }, el("summary", { text: headings.whole_decision }),
        el("p", { text: summary }))
    : null;
  if (clamp && whole) {
    // Unfold only what the clamp hides: measured after layout. The text is
    // never cut in JavaScript (a cut can split "4.5 mm" from its unit).
    requestAnimationFrame(() => { if (clamp.scrollHeight <= clamp.clientHeight + 1) whole.hidden = true; });
  }
  const rejected = d.rejected || [];
  const values = d.values || [];
  return el("div", { class: "mk-card mk-decision", id: `decision-${d.id}` },
    el("p", { class: "mk-date" }, el("time", { datetime: String(d.when || ""), text: day(d.when) })),
    el("h3", { text: d.title || d.id }),
    (d.claims || []).length
      ? el("p", { class: "mk-chips" }, ...d.claims.map((c) => el("a", { class: "mk-claim",
          href: `engineering/#claim=${encodeURIComponent(c.claim)}` },
          el("span", { class: "mono mk-claim-id", text: c.claim }),
          tokenChip(c.token, c.word, { errored: c.errored, small: true, marks: c.marks,
            notices: words.notices, trace: words.trace }))))
      : null,
    clamp, whole,
    rejected.length && d.lost_label
      ? el("details", { class: "mk-lost" }, el("summary", { text: d.lost_label }),
          el("ul", { class: "mk-rejected" }, ...rejected.map(rejectedRow)))
      : null,
    values.length ? el("ul", { class: "mk-values" }, ...values.map(valueRow)) : null);
}

/** One option that lost: its value, the bake's word for its type (for a
 *  preference, who stated it and whether they recorded it), why, and its
 *  return condition in the bake's words with its text as written. */
function rejectedRow(r) {
  return el("li", { class: "mk-reject" },
    el("p", { class: "mk-reject-top" },
      el("b", { class: "mk-reject-value", text: r.value || "" }),
      r.type_word ? el("span", { class: `mk-mark mk-pref-${r.preference || "none"}`, text: r.type_word }) : null),
    r.reason ? el("p", { class: "mk-reason", text: r.reason }) : null,
    r.returns_word
      ? el("p", { class: "mk-returns" }, r.returns_word,
          r.returns_text ? el("code", { class: "mono", text: r.returns_text }) : null)
      : null);
}

/** A value, its rationale, and what lost to it with why. */
function valueRow(v) {
  return el("li", { class: "mk-value" },
    el("p", { class: "mk-value-top" },
      el("code", { class: "mono", text: v.name }),
      v.value_text ? el("b", { class: "mk-value-now", text: v.value_text }) : null),
    v.rationale ? el("p", { class: "mk-value-why", text: v.rationale }) : null,
    (v.lost || []).length
      ? el("ul", { class: "mk-value-lost" }, ...v.lost.map((l) => el("li", {},
          el("s", { class: "mk-lost-value", text: l.value_text || "" }),
          l.reason ? el("span", { class: "mk-lost-why", text: ` ${l.reason}` }) : null)))
      : null);
}

// --------------------------------------------------------------------------- //
// build.json, and a page with no data
// --------------------------------------------------------------------------- //
function showBuild(build) {
  paintBuild(build, (mk.doc && mk.doc.words) || {});
}

function noData(err) {
  const isFile = location.protocol === "file:";
  $("#top").classList.add("mk-hero--text");
  mount($("#verdict"),
    el("p", { class: "mk-headline" }, el("b", { text: "This page has no data yet." })),
    el("p", { class: "small mono", text: err && err.message ? err.message : String(err) }),
    isFile
      ? el("p", {}, "Serve the page through a web server. A browser does not let a page read its data files from the disk. Run ",
          el("code", { class: "mono", text: "nopekit site serve" }), ".")
      : el("p", {}, "Build the data from the project root with ",
          el("code", { class: "mono", text: "nopekit site build" }), "."));
}
