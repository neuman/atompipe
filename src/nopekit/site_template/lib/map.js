// SPDX-License-Identifier: Apache-2.0
// map.js: the grounding map, drawn from data/map.json (architecture phase 5,
// SPEC 29).
//
// The author's transit pattern, in plain SVG: what was asked on the left edge,
// the zones of choices, the stations (values that several lines share), and the
// boards of claims on the right. Each claim is ONE LINE. It starts at what was
// asked, stops at the zones and stations its evaluators read, and ends on its
// row of its board. The line carries its status in three channels at once: its
// stroke (solid, heavy, dashed, dotted, from TOKEN_LOOK), its colour, and the
// glyph and baked word on its row.
//
// ORDER IS BAKED, GEOMETRY IS RENDERED. `map.json` holds every node's lane, its
// order, its row and its column (indexes, never pixels); this file turns them
// into positions with fixed arithmetic, so the same state draws the same map
// every time. It never runs a force layout and it never reorders by default.
// The one reordering, "worst first", is a viewer control: it sorts rows inside
// each board by the baked `severity` and redraws.
//
// TEXT IS MEASURED AFTER PLACEMENT. Every label sits where the structure puts
// it; `relayout` then measures it (getComputedTextLength) and shortens it to its
// room, or wraps it where a column has room for lines. Text never moves a
// capsule or a track. What slipped through in the reference map: its label
// widths came from character counts, and a font that loaded late overlapped
// them.
//
// THE MAP COMPUTES NO TRUTH. It reads `token`, `word`, `marks`, `tally`,
// `severity` and the order keys, and nothing here decides a status, a margin,
// readiness or a worst-of: a board's token is the baked worst of its claims, a
// line's is its claim's. (What slipped through in the reference: its board
// headers decided GO and NO-GO in the browser from a hand-kept claim list.)
//
// No d3, no dependency: the page has no build step, and the drawing a reader
// is asked to trust should be readable with view-source.

import { el, svg, mount } from "./dom.js";
import { lookOf, tokenChip } from "./format.js";

/** The map's native width. Every position below is in these units; the SVG
 *  scales to its box, and `--s` keeps small text at 12 px or more on screen
 *  when the box is narrower (the reference map's rule). */
const W = 1400;
/** The board lane: its left edge, its right edge, and where a row's text
 *  starts. 520 units hold a statement and its value on two lines at 13 px. */
const BX = 872, BR = 1392, SX = BX + 18;
/** Row geometry. A row is two lines of text: the statement, then the word and
 *  the value. The board header holds the title, its line and its tally. */
const TOP = 52, HDR_H = 46, ROW_H = 42, BOARD_GAP = 16, ROW_PAD = 6;
/** Left lanes: the first x, the last x a capsule may take (the lines need room
 *  to run into the boards), the requirement label's width and the gap between
 *  two lanes. */
const X0 = 14, XL = BX - 64, REQ_LABEL = 214, REQ_PITCH = 26, LANE_GAP = 26;
/** A capsule's half width and the room above and below its first and last
 *  track. */
const CAP_R = 7, CAP_PAD = 10;
/** Unvisited nodes (no line stops there) are listed under the map, in their
 *  lane. One row each. */
const LOOSE_H = 26;

const SEVERITY_SORT = (a, b) => a.severity - b.severity || a.row - b.row;

/** The row and header geometry at the drawn scale ``s``. map.css grows each
 *  font to max(its size, 12 px / s) in map units, so below 1400 px the text is
 *  taller than at 1400: the rows grow with it, and the title's baseline and
 *  the second line move down with it. What slipped through (review of phase
 *  5): the geometry stayed at its 1400 px numbers, and at 900 px each title
 *  sat on its status line and each id ran into its title. */
export function metricsFor(s) {
  const t14 = Math.max(14, 12 / s), t12 = Math.max(12, 12 / s), t11 = Math.max(11, 11 / s);
  const h125 = Math.max(12.5, 12 / s);
  const d14 = t14 - 14, d12 = t12 - 12, dh = h125 - 12.5;
  return {
    t14, t12, t11,
    rowH: Math.ceil(ROW_H + 1.05 * d14 + 1.25 * d12),
    trackY: 13 + 0.7 * d14,            // the track's y below the row's top
    title: 0.35 * t14,                 // the title's baseline below the track
    sub: 0.35 * t14 + t12 + 4,         // the second line's baseline below the track
    hdrH: Math.ceil(HDR_H + dh + 1.25 * d12),
    hdrTitle: 19 + 0.8 * dh,
    hdrLine: 36 + dh + d12,
  };
}

/** The drawn scale of a box ``width`` wide (the map is never drawn below 0.6). */
const scaleOf = (width) => Math.max(0.6, (width || W) / W);

/** Draw the map into ``host``. Returns ``{destroy, select, clear}``.
 *  ``onSelect(kind, key)`` opens the drawer; ``onBoard(key)`` scrolls to a
 *  board's section. */
export function renderMap(host, map, page, { onSelect, onBoard, onRescale, worstFirst = false } = {}) {
  const words = (page && page.words) || {};
  const claimRows = (page && page.claims) || {};
  const nodes = map.nodes || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lineOf = new Map((map.lines || []).map((l) => [l.claim, l]));
  const boards = nodes.filter((n) => n.kind === "board");
  const claimNode = new Map(nodes.filter((n) => n.kind === "claim").map((n) => [n.key, n]));
  const leftLanes = (map.lanes || []).filter((lane) => lane !== "boards");
  const restsOn = ((map.edges || {}).rests_on) || {};

  // ------------------------------------------------------------------ rows
  // The geometry at the scale the host draws at now; a resize to another
  // geometry asks the page to draw again (`onRescale`).
  const drawnS = scaleOf(host.getBoundingClientRect().width);
  const drawnAt = metricsFor(drawnS);
  let destroyed = false;
  const M = drawnAt;
  const rowY = new Map();          // claim key -> the y of its track
  const headerY = new Map();       // board key -> the top of its header
  let y = TOP;
  for (const board of boards) {
    headerY.set(board.key, y);
    y += M.hdrH + ROW_PAD;
    const rows = board.claims.map((key) => claimNode.get(key)).filter(Boolean);
    if (worstFirst) rows.sort(SEVERITY_SORT);
    for (const row of rows) {
      rowY.set(row.key, y + M.trackY);
      y += M.rowH;
    }
    y += BOARD_GAP;
  }
  const rowsBottom = y;

  // ------------------------------------------------------------------ columns
  const columns = map.columns || {};
  const laneX = {};                // lane -> [left, right]
  const pitch = {};                // lane -> column pitch
  let x = X0;
  if (leftLanes.includes("requirements")) {
    const n = Math.max(1, columns.requirements || 1);
    laneX.requirements = [x, x + REQ_LABEL + n * REQ_PITCH];
    pitch.requirements = REQ_PITCH;
    x = laneX.requirements[1] + LANE_GAP;
  }
  const flexLanes = leftLanes.filter((lane) => lane !== "requirements");
  const flexCols = flexLanes.reduce((n, lane) => n + Math.max(1, columns[lane] || 1), 0);
  const room = XL - x - LANE_GAP * Math.max(0, flexLanes.length - 1);
  const flexPitch = flexCols ? Math.max(64, Math.min(210, room / flexCols)) : 0;
  for (const lane of flexLanes) {
    const n = Math.max(1, columns[lane] || 1);
    laneX[lane] = [x, x + n * flexPitch];
    pitch[lane] = flexPitch;
    x = laneX[lane][1] + LANE_GAP;
  }

  const capsules = nodes.filter((n) => n.lane !== "boards");
  const capX = new Map();
  for (const node of capsules) {
    const [left] = laneX[node.lane] || [X0];
    const base = node.lane === "requirements" ? left + REQ_LABEL : left;
    capX.set(node.id, base + ((node.column || 0) + 0.5) * (pitch[node.lane] || REQ_PITCH));
  }
  const spanOf = (node) => {
    const ys = (node.claims || []).map((key) => rowY.get(key)).filter((v) => v !== undefined);
    return ys.length ? [Math.min(...ys), Math.max(...ys)] : null;
  };

  // Nodes no line stops at: a list under the rows, in their own lane.
  const loose = new Map();         // lane -> [node]
  for (const node of capsules) {
    if (spanOf(node)) continue;
    if (!loose.has(node.lane)) loose.set(node.lane, []);
    loose.get(node.lane).push(node);
  }
  const looseRows = Math.max(0, ...Array.from(loose.values(), (list) => list.length));
  const H = rowsBottom + (looseRows ? 34 + looseRows * LOOSE_H : 0) + 8;

  // ------------------------------------------------------------------ the svg
  const root = svg("svg", {
    class: "nk-map", viewBox: `0 0 ${W} ${H}`, role: "group",
    "aria-label": words.headings && words.headings.map ? words.headings.map : "map",
  });
  const viewport = svg("g", { class: "vp" });
  root.appendChild(viewport);
  const layer = {};
  for (const name of ["heads", "labels", "casing", "tracks", "hits", "caps", "bridges", "dots",
    "caplabels", "board"]) {
    layer[name] = svg("g", { class: `L-${name}` });
    viewport.appendChild(layer[name]);
  }
  const later = [];                // text to measure after placement

  // column heads
  const laneWord = (lane) => String(((words.lanes || {})[lane]) || lane).toUpperCase();
  for (const lane of leftLanes) {
    const [left, right] = laneX[lane];
    const mid = lane === "requirements" ? (left + right) / 2 : (left + right) / 2;
    layer.heads.appendChild(svg("text", { class: "colhead", x: mid, y: 24,
      "text-anchor": "middle", text: laneWord(lane) }));
  }
  layer.heads.appendChild(svg("text", { class: "colhead", x: (BX + BR) / 2, y: 24,
    "text-anchor": "middle", text: laneWord("boards") }));

  // ------------------------------------------------------------------ tracks
  const tracks = new Map();        // claim key -> {x0, x1, y, look}
  for (const line of map.lines || []) {
    const yy = rowY.get(line.claim);
    if (yy === undefined) continue;
    const firstStop = (line.stops || []).find((id) => capX.has(id));
    const x0 = firstStop ? capX.get(firstStop) : BX - 46;
    const x1 = SX - 12;
    const look = lookOf(line.token, { errored: line.errored });
    tracks.set(line.claim, { x0, x1, y: yy, look, line });
    const d = `M${x0},${yy} H${x1}`;
    const marks = line.marks || [];
    if (marks.includes("amber")) {
      layer.casing.appendChild(svg("path", { d, class: "casing amber", "data-c": line.claim }));
    }
    if (marks.includes("disagree")) {
      layer.casing.appendChild(svg("path", { d, class: "casing disagree", "data-c": line.claim }));
    }
    layer.tracks.appendChild(svg("path", {
      d, class: `track tk-${look.stroke} tone-${look.tone}`, "data-c": line.claim,
    }));
    const hit = svg("path", { d, class: "hit", "data-c": line.claim });
    bindLine(hit, line.claim);
    layer.hits.appendChild(hit);
  }

  // ------------------------------------------------------------------ capsules
  const capEls = [];
  const labelEls = [];             // capsule labels dim with their capsule
  for (const node of capsules) {
    const span = spanOf(node);
    if (!span) continue;
    const cx = capX.get(node.id);
    const y0 = span[0] - CAP_PAD, y1 = span[1] + CAP_PAD;
    const members = new Set(node.claims || []);
    const g = svg("g", {
      class: `capsule cap-${node.kind}${node.generated ? " generated" : ""}`,
      "data-node": node.id, tabindex: "0", role: "button",
      "aria-label": `${node.title || node.key}`,
    });
    g.dataset.claims = (node.claims || []).join(" ");
    if (node.kind === "requirement") {
      const look = lookOf(node.token, { errored: node.errored });
      g.appendChild(svg("rect", { class: `cap tone-${look.tone}`, x: cx - CAP_R, y: y0,
        width: CAP_R * 2, height: y1 - y0, rx: CAP_R }));
    } else {
      g.appendChild(svg("rect", { class: "cap", x: cx - CAP_R, y: y0, width: CAP_R * 2,
        height: y1 - y0, rx: CAP_R }));
    }
    g.appendChild(svg("rect", { class: "hit", x: cx - 14, y: y0 - 4, width: 28,
      height: y1 - y0 + 8 }));
    layer.caps.appendChild(g);
    bindNode(g, node);
    capEls.push(g);

    // A member line gets a dot inside the capsule; a line that only passes the
    // capsule's span is drawn OVER it on a bridge, so it does not read as a stop.
    for (const [key, track] of tracks) {
      if (track.y < y0 || track.y > y1 || track.x0 > cx || track.x1 < cx) continue;
      if (members.has(key)) {
        layer.dots.appendChild(svg("circle", { class: `dot tone-${track.look.tone}`,
          cx, cy: track.y, r: 3.2, "data-c": key }));
      } else {
        const d = `M${cx - CAP_R - 3},${track.y} H${cx + CAP_R + 3}`;
        layer.bridges.appendChild(svg("path", { d, class: "bridge-gap", "data-c": key }));
        layer.bridges.appendChild(svg("path", {
          d, class: `track tk-${track.look.stroke} tone-${track.look.tone}`, "data-c": key }));
      }
    }

    if ((node.marks || []).includes("disagree")) {
      g.appendChild(svg("text", { class: "mark-bang", x: cx, y: y0 - 4, "text-anchor": "middle",
        text: "!" }));
    }
    if (node.kind === "requirement") {
      later.push(requirementLabel(node, cx, span));
    } else {
      later.push(capsuleLabel(node, cx, y0));
    }
  }

  // nodes no line stops at, listed under the map in their lane
  if (looseRows) {
    for (const [lane, list] of loose) {
      const [left, right] = laneX[lane];
      const top = rowsBottom + 10;
      layer.labels.appendChild(svg("text", { class: "loose-head", x: left, y: top,
        text: "No line stops here yet." }));
      list.forEach((node, i) => {
        const yy = top + 14 + i * LOOSE_H;
        const g = svg("g", { class: `loose cap-${node.kind}`, "data-node": node.id,
          tabindex: "0", role: "button", "aria-label": node.title || node.key });
        g.dataset.claims = "";
        g.appendChild(svg("rect", { class: "loose-bg", x: left, y: yy, width: right - left,
          height: LOOSE_H - 6, rx: 9 }));
        const t = svg("text", { class: `loose-name${node.generated ? " mono" : ""}`,
          x: left + 10, y: yy + 14, text: node.title || node.key });
        g.appendChild(t);
        later.push({ fit: [t, right - left - 20] });
        layer.labels.appendChild(g);
        bindNode(g, node);
        capEls.push(g);
      });
    }
  }

  // ------------------------------------------------------------------ boards
  const rowEls = new Map();
  const headerEls = new Map();
  for (const board of boards) {
    const y0 = headerY.get(board.key);
    const look = lookOf(board.token, { errored: board.errored });
    const g = svg("g", { class: `hdr st-${board.token}${board.errored ? " st-errored" : ""}`,
      "data-board": board.key, tabindex: "0", role: "button",
      "aria-label": `${board.title}: ${board.word}` });
    g.dataset.claims = (board.claims || []).join(" ");
    g.appendChild(svg("rect", { class: "hbg", x: BX, y: y0, width: BR - BX, height: M.hdrH, rx: 9 }));
    const title = svg("text", { class: "ht", x: BX + 12, y: y0 + M.hdrTitle,
      text: String(board.title || board.key).toUpperCase() });
    const lineText = svg("text", { class: "hd", x: BX + 12, y: y0 + M.hdrLine, text: board.line || "" });
    const status = svg("text", { class: `hv tone-${look.tone}`, x: BR - 10, y: y0 + M.hdrTitle,
      "text-anchor": "end" });
    status.appendChild(svg("tspan", { class: "glyph", text: `${look.glyph} ` }));
    status.appendChild(svg("tspan", { text: String(board.word || board.token).toUpperCase() }));
    const tally = svg("text", { class: "htally", x: BR - 10, y: y0 + M.hdrLine, "text-anchor": "end",
      text: (board.tally || []).map((t) => `${lookOf(t.key).glyph} ${t.label}`).join("  ·  ") });
    g.append(title, lineText, status, tally);
    if ((board.marks || []).includes("disagree")) {
      g.appendChild(svg("text", { class: "mark-bang", x: BR - 10, y: y0 - 4,
        "text-anchor": "end", text: "!" }));
    }
    layer.board.appendChild(g);
    later.push({ fit: [title, BR - BX - 24], before: status });
    later.push({ fit: [lineText, BR - BX - 24], before: tally });
    headerEls.set(board.key, g);
    g.addEventListener("mouseenter", () => preview(new Set(board.claims || [])));
    g.addEventListener("mouseleave", restore);
    g.addEventListener("focus", () => preview(new Set(board.claims || [])));
    g.addEventListener("blur", restore);
    g.addEventListener("click", () => onBoard && onBoard(board.key));
    g.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onBoard && onBoard(board.key); }
    });

    for (const key of board.claims || []) {
      const node = claimNode.get(key);
      const yy = rowY.get(key);
      if (!node || yy === undefined) continue;
      const rlook = lookOf(node.token, { errored: node.errored });
      const rg = svg("g", { class: `row st-${node.token}${node.errored ? " st-errored" : ""}`,
        "data-c": key, tabindex: "0", role: "button",
        "aria-label": `${key}: ${node.title}. ${node.word}.` });
      const top = yy - M.trackY;
      rg.appendChild(svg("rect", { class: "bg", x: BX + 2, y: top - 2, width: BR - BX - 4,
        height: M.rowH - 4, rx: 7 }));
      rg.appendChild(svg("rect", { class: "failbar", x: BX + 2, y: top - 1, width: 3,
        height: M.rowH - 6, rx: 1.5 }));
      rg.appendChild(svg("text", { class: `rglyph tone-${rlook.tone}`, x: SX - 4, y: yy + M.title,
        "text-anchor": "middle", text: rlook.glyph }));
      const idt = svg("text", { class: "rid", x: SX + 10, y: yy + M.title - 0.5, text: key });
      const name = svg("text", { class: "rname", x: SX + 44, y: yy + M.title, text: node.title || key });
      const sub = svg("text", { class: "rsub", x: SX + 44, y: yy + M.sub });
      sub.appendChild(svg("tspan", { class: `rword tone-${rlook.tone}`, text: node.word || node.token }));
      const detail = node.value_text || ((claimRows[key] || {}).cause_text) || "";
      if (detail) sub.appendChild(svg("tspan", { class: "rdetail", text: `  ·  ${detail}` }));
      rg.append(idt, name, sub);
      let bang = null;
      if ((node.marks || []).includes("disagree")) {
        bang = svg("text", { class: "mark-bang", x: SX + 34, y: yy + M.title,
          "text-anchor": "middle", text: "!" });
        rg.appendChild(bang);
      }
      layer.board.appendChild(rg);
      // The title and the second line start after the id as drawn (measured
      // in relayout), then fit what is left of the row.
      later.push({ row: [idt, bang, name, sub] });
      rowEls.set(key, rg);
      bindLine(rg, key);
    }
  }

  mount(host, root);

  // ------------------------------------------------------------------ labels
  function capsuleLabel(node, cx, top) {
    const t = svg("text", { class: "caplabel", x: cx, y: top - 7, "text-anchor": "middle" });
    t.dataset.claims = (node.claims || []).join(" ");
    labelEls.push(t);
    t.appendChild(svg("tspan", { class: `name${node.generated ? " mono" : ""}`,
      text: node.title || node.key }));
    if (node.kind === "station" && node.value_text) {
      t.appendChild(svg("tspan", { class: "val", text: `  ${node.value_text}` }));
    }
    layer.caplabels.appendChild(t);
    let bar = null;
    if (node.kind === "zone" && node.ground) {
      bar = groundBar(node, cx, top - 4);
      bar.dataset.claims = t.dataset.claims;
      labelEls.push(bar);
      layer.caplabels.appendChild(bar);
    }
    // A label may take two columns of room: a label that still meets an
    // earlier one moves up a line (relayout), and only then is it shortened.
    return { fit: [t, 2 * (pitch[node.lane] || 120) - 16], nudge: true, bar };
  }

  /** The zone's ground bar (the reference map's): where its choices come from,
   *  chosen, from an input or from an assumption, with a diamond for each
   *  assumption that sources one. Counts are the bake's (`ground`). */
  function groundBar(node, cx, y0) {
    const g = svg("g", { class: "gground" });
    const ground = node.ground || {};
    const total = (ground.chosen || 0) + (ground.input || 0) + (ground.assumption || 0);
    if (!total) return g;
    const width = 30;
    let bx = cx - width / 2;
    for (const [kind, cls] of [["chosen", "g-chosen"], ["input", "g-input"], ["assumption", "g-guess"]]) {
      const n = ground[kind] || 0;
      if (!n) continue;
      const w = (n / total) * width;
      g.appendChild(svg("rect", { class: `gbar ${cls}`, x: bx, y: y0 - 1, width: Math.max(1.5, w - 1),
        height: 3, rx: 1 }));
      bx += w;
    }
    return g;
  }

  function requirementLabel(node, cx, span) {
    const t = svg("text", { class: "reqlabel", x: cx - 14, y: (span[0] + span[1]) / 2,
      "text-anchor": "end" });
    t.dataset.claims = (node.claims || []).join(" ");
    labelEls.push(t);
    layer.labels.appendChild(t);
    return { wrap: [t, REQ_LABEL - 20, node], span };
  }

  // ------------------------------------------------------------------ measure
  const tw = (t) => { try { return t.getComputedTextLength(); } catch (err) { return 0; } };

  /** Shorten a text element (its last tspan first) until it fits ``room``.
   *  The full text is kept on the element and shown as its tooltip when cut. */
  function fitText(t, room) {
    let spans = Array.from(t.childNodes).filter((n) => n.nodeName === "tspan");
    if (!spans.length) {
      const only = svg("tspan", { text: t.textContent });
      while (t.firstChild) t.removeChild(t.firstChild);
      t.appendChild(only);
      spans = [only];
    }
    if (!t.dataset.full) t.dataset.full = JSON.stringify(spans.map((s) => s.textContent));
    const parts = JSON.parse(t.dataset.full);
    spans.forEach((s, i) => { s.textContent = parts[i] !== undefined ? parts[i] : ""; });
    const old = t.querySelector("title");
    if (old) old.remove();
    if (tw(t) <= room) return;
    for (let i = spans.length - 1; i >= 0; i -= 1) {
      const s = spans[i];
      const full = s.textContent;
      let lo = 0, hi = full.length;
      while (lo < hi) {
        const mid = Math.ceil((lo + hi) / 2);
        s.textContent = full.slice(0, mid).trimEnd() + "…";
        if (tw(t) <= room) lo = mid; else hi = mid - 1;
      }
      s.textContent = lo ? full.slice(0, lo).trimEnd() + "…" : "";
      if (tw(t) <= room || i === 0) break;
    }
    t.appendChild(svg("title", { text: parts.join("") }));
  }

  /** A requirement's id and statement, wrapped into the lines its room holds:
   *  from the capsule above it to the capsule below it in its column. */
  function wrapRequirement(t, width, node, span, roomTop, roomBottom) {
    while (t.firstChild) t.removeChild(t.firstChild);
    // A line of the label is its text's height (f13, grown below 1400 px).
    const lineH = Math.max(15, 1.2 * Math.max(13, 12 / drawnS));
    const maxLines = Math.max(1, Math.min(5, Math.floor((roomBottom - roomTop) / lineH)));
    const wordsOf = String(node.title || "").split(/\s+/).filter(Boolean);
    const lines = [];
    let current = [`${node.key}`];
    const probe = svg("tspan", {});
    t.appendChild(probe);
    for (const word of wordsOf) {
      probe.textContent = [...current, word].join(" ");
      if (tw(t) > width && current.length) {
        lines.push(current.join(" "));
        current = [word];
      } else {
        current.push(word);
      }
    }
    lines.push(current.join(" "));
    t.removeChild(probe);
    let shown = lines.slice(0, maxLines);
    if (lines.length > maxLines) shown[maxLines - 1] = `${shown[maxLines - 1]} …`;
    const mid = (span[0] + span[1]) / 2;
    const first = mid - ((shown.length - 1) * lineH) / 2 + 4;
    shown.forEach((text, i) => {
      const s = svg("tspan", { x: Number(t.getAttribute("x")), y: first + i * lineH,
        class: i === 0 ? "req-first" : "" });
      if (i === 0 && text.startsWith(node.key)) {
        s.appendChild(svg("tspan", { class: "req-id", text: node.key }));
        s.appendChild(document.createTextNode(text.slice(node.key.length)));
      } else {
        s.textContent = text;
      }
      t.appendChild(s);
    });
    const title = svg("title", { text: `${node.key} ${node.title || ""}` });
    t.appendChild(title);
  }

  function relayout() {
    const placed = [];
    for (const item of later) {
      if (!item.row) continue;
      const [idt, bang, name, sub] = item.row;
      let nx = Math.max(SX + 44, SX + 10 + tw(idt) + 0.6 * M.t14);
      if (bang) {
        bang.setAttribute("x", nx);
        nx += 0.8 * M.t14;
      }
      name.setAttribute("x", nx);
      sub.setAttribute("x", nx);
      fitText(name, Math.max(24, BR - 10 - nx));
      fitText(sub, Math.max(24, BR - 10 - nx));
    }
    // requirement rooms: the gap between the capsules above and below in a column
    const reqs = later.filter((item) => item.wrap)
      .sort((a, b) => a.span[0] - b.span[0]);
    reqs.forEach((item, i) => {
      const above = i > 0 ? reqs[i - 1].span[1] + CAP_PAD : TOP - 8;
      const below = i < reqs.length - 1 ? reqs[i + 1].span[0] - CAP_PAD : rowsBottom;
      const mid = (item.span[0] + item.span[1]) / 2;
      const half = Math.min(mid - above, below - mid);
      wrapRequirement(item.wrap[0], item.wrap[1], item.wrap[2], item.span,
        mid - half + 4, mid + half - 4);
    });
    for (const item of later) {
      if (!item.fit) continue;
      const [t, room] = item.fit;
      let width = room;
      if (item.before) {
        const used = tw(item.before);
        width = Math.min(room, room - used - 16);
      }
      fitText(t, Math.max(24, width));
      if (item.bar) {
        // the ground bar sits under the label's left edge
        const w = tw(t);
        const left = Number(t.getAttribute("x")) - w / 2;
        let bx = left;
        for (const rect of item.bar.querySelectorAll("rect")) {
          rect.setAttribute("x", bx);
          bx += Number(rect.getAttribute("width")) + 1;
        }
      }
      if (item.nudge) {
        // move up one line, at most twice, to clear an earlier label
        t.setAttribute("y", t.dataset.y0 || t.getAttribute("y"));
        t.dataset.y0 = t.getAttribute("y");
        if (item.bar) item.bar.removeAttribute("transform");
        for (let k = 0; k < 2; k += 1) {
          const box = safeBox(t);
          if (!box || !placed.some((b) => overlaps(b, box))) break;
          t.setAttribute("y", Number(t.getAttribute("y")) - 15);
          if (item.bar) item.bar.setAttribute("transform", `translate(0,${-15 * (k + 1)})`);
        }
        const box = safeBox(t);
        if (box) placed.push(box);
      }
    }
  }
  const safeBox = (t) => { try { return t.getBBox(); } catch (err) { return null; } };
  const overlaps = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width
    && a.y < b.y + b.height && b.y < a.y + a.height;

  // ------------------------------------------------------------------ highlight
  let pinned = null;               // the selection the drawer shows

  function setHighlight(keys, secondary = new Set()) {
    root.classList.add("hlon");
    for (const node of root.querySelectorAll("[data-c]")) {
      const key = node.getAttribute("data-c");
      node.classList.toggle("hl", keys.has(key));
      node.classList.toggle("hl2", !keys.has(key) && secondary.has(key));
      node.classList.toggle("dim", !keys.has(key) && !secondary.has(key));
    }
    for (const g of [...capEls, ...headerEls.values()]) {
      const members = (g.dataset.claims || "").split(" ").filter(Boolean);
      const on = members.some((key) => keys.has(key));
      g.classList.toggle("hl", on);
      g.classList.toggle("dim", !on);
    }
    for (const t of labelEls) {
      const members = (t.dataset.claims || "").split(" ").filter(Boolean);
      t.classList.toggle("dim", !members.some((key) => keys.has(key)));
    }
  }

  function clearHighlight() {
    root.classList.remove("hlon");
    for (const node of root.querySelectorAll(".hl, .hl2, .dim")) {
      node.classList.remove("hl", "hl2", "dim");
    }
  }

  function lineSet(key) {
    const keys = new Set([key]);
    const rests = new Set((restsOn[`claim:${key}`] || []).map((id) => id.replace(/^claim:/, "")));
    return [keys, rests];
  }

  function preview(keys, secondary) { setHighlight(keys, secondary); }
  function restore() {
    if (pinned) setHighlight(pinned[0], pinned[1]);
    else clearHighlight();
  }

  function bindLine(target, key) {
    target.addEventListener("mouseenter", () => preview(...lineSet(key)));
    target.addEventListener("mouseleave", restore);
    target.addEventListener("focus", () => preview(...lineSet(key)));
    target.addEventListener("blur", restore);
    target.addEventListener("click", () => onSelect && onSelect("claim", key));
    target.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect && onSelect("claim", key); }
    });
  }

  function bindNode(g, node) {
    const keys = new Set(node.claims || []);
    g.addEventListener("mouseenter", () => preview(keys));
    g.addEventListener("mouseleave", restore);
    g.addEventListener("focus", () => preview(keys));
    g.addEventListener("blur", restore);
    g.addEventListener("click", () => onSelect && onSelect(node.kind, node.key));
    g.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onSelect && onSelect(node.kind, node.key); }
    });
  }

  // ------------------------------------------------------------------ pan and zoom
  const view = { k: 1, tx: 0, ty: 0 };
  const apply = () => viewport.setAttribute("transform",
    `translate(${view.tx.toFixed(2)},${view.ty.toFixed(2)}) scale(${view.k.toFixed(4)})`);
  const toMap = (clientX, clientY) => {
    const box = root.getBoundingClientRect();
    const unit = W / (box.width || W);
    return [(clientX - box.left) * unit, (clientY - box.top) * unit, unit];
  };
  function zoomAt(factor, mx, my) {
    const k = Math.max(0.6, Math.min(4, view.k * factor));
    const f = k / view.k;
    view.tx = mx - (mx - view.tx) * f;
    view.ty = my - (my - view.ty) * f;
    view.k = k;
    apply();
  }
  function reset() { view.k = 1; view.tx = 0; view.ty = 0; apply(); }

  root.addEventListener("wheel", (ev) => {
    if (!(ev.ctrlKey || ev.metaKey)) return;
    ev.preventDefault();
    const [mx, my] = toMap(ev.clientX, ev.clientY);
    zoomAt(Math.exp(-ev.deltaY * 0.0022), mx, my);
  }, { passive: false });

  const pointers = new Map();
  let drag = null, moved = false, pinch = null;
  root.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0 && ev.pointerType === "mouse") return;
    pointers.set(ev.pointerId, [ev.clientX, ev.clientY]);
    moved = false;
    if (pointers.size === 1) {
      drag = { x: ev.clientX, y: ev.clientY, tx: view.tx, ty: view.ty, id: ev.pointerId };
    } else if (pointers.size === 2) {
      const [[ax, ay], [bx, by]] = Array.from(pointers.values());
      pinch = { d: Math.hypot(ax - bx, ay - by), k: view.k };
      drag = null;
    }
  });
  root.addEventListener("pointermove", (ev) => {
    if (!pointers.has(ev.pointerId)) return;
    pointers.set(ev.pointerId, [ev.clientX, ev.clientY]);
    if (pinch && pointers.size === 2) {
      const [[ax, ay], [bx, by]] = Array.from(pointers.values());
      const [mx, my] = toMap((ax + bx) / 2, (ay + by) / 2);
      zoomAt((pinch.k * Math.hypot(ax - bx, ay - by) / (pinch.d || 1)) / view.k, mx, my);
      moved = true;
      return;
    }
    if (!drag) return;
    const [, , unit] = toMap(ev.clientX, ev.clientY);
    const dx = (ev.clientX - drag.x) * unit, dy = (ev.clientY - drag.y) * unit;
    if (!moved && Math.hypot(dx, dy) < 5 * unit) return;
    if (!moved) { moved = true; try { root.setPointerCapture(ev.pointerId); } catch (err) { /* gone */ } }
    view.tx = drag.tx + dx;
    view.ty = drag.ty + dy;
    apply();
  });
  const release = (ev) => {
    pointers.delete(ev.pointerId);
    if (pointers.size < 2) pinch = null;
    if (!pointers.size) drag = null;
  };
  root.addEventListener("pointerup", release);
  root.addEventListener("pointercancel", release);
  // a drag that moved is not a click on what it ended over
  root.addEventListener("click", (ev) => { if (moved) { ev.stopPropagation(); ev.preventDefault(); moved = false; } }, true);

  let over = false;
  root.addEventListener("mouseenter", () => { over = true; });
  root.addEventListener("mouseleave", () => { over = false; });
  const onKey = (ev) => {
    if (ev.key !== "0" || ev.metaKey || ev.ctrlKey || ev.altKey) return;
    const target = ev.target;
    if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA")) return;
    if (over || host.contains(document.activeElement)) { reset(); ev.preventDefault(); }
  };
  document.addEventListener("keydown", onKey);

  // ------------------------------------------------------------------ scale
  let lastS = null;
  function measureScale() {
    const w = root.getBoundingClientRect().width;
    if (!w) return;
    const s = scaleOf(w);
    if (lastS !== null && Math.abs(s - lastS) < 0.002) return;
    lastS = s;
    root.style.setProperty("--s", s.toFixed(4));
    const now = metricsFor(s);
    if (onRescale && Math.abs(s - drawnS) > 0.005
        && (now.rowH !== drawnAt.rowH || now.hdrH !== drawnAt.hdrH)) {
      // The rows were laid out for another text size: draw again at this one.
      requestAnimationFrame(() => { if (!destroyed) onRescale(); });
      return;
    }
    relayout();
  }
  const ro = window.ResizeObserver ? new ResizeObserver(() => requestAnimationFrame(measureScale)) : null;
  if (ro) ro.observe(root); else window.addEventListener("resize", measureScale);
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(() => { lastS = null; measureScale(); });
  measureScale();
  if (lastS === null) relayout();

  return {
    element: root,
    zoomIn() { zoomAt(1.25, W / 2, H / 2); },
    zoomOut() { zoomAt(1 / 1.25, W / 2, H / 2); },
    reset,
    get view() { return { ...view }; },
    set view(v) { if (v) { view.k = v.k; view.tx = v.tx; view.ty = v.ty; apply(); } },
    /** Keep one claim's line lit while the drawer shows it. */
    select(kind, key) {
      if (kind === "claim") pinned = lineSet(key);
      else {
        const node = byId.get(`${kind}:${key}`);
        pinned = node ? [new Set(node.claims || []), new Set()] : null;
      }
      restore();
    },
    /** Light every line whose token is one of ``tokens`` (the legend). */
    showTokens(tokens) {
      if (!tokens) { restore(); return; }
      const keys = new Set((map.lines || []).filter((l) => tokens.has(l.errored ? "errored" : l.token))
        .map((l) => l.claim));
      setHighlight(keys);
    },
    clear() { pinned = null; clearHighlight(); },
    destroy() {
      destroyed = true;
      document.removeEventListener("keydown", onKey);
      if (ro) ro.disconnect(); else window.removeEventListener("resize", measureScale);
      root.remove();
    },
  };
}

/** The map at phone width: a list, not a drawing (SPEC 29). What was asked as
 *  chips, then each board's header and its rows: the chip, the id, the
 *  statement, the value, and the choices each line reads. */
export function mapList(map, page, { onSelect, onBoard } = {}) {
  const words = (page && page.words) || {};
  const nodes = map.nodes || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lineOf = new Map((map.lines || []).map((l) => [l.claim, l]));
  const claimRows = (page && page.claims) || {};
  const claimNode = new Map(nodes.filter((n) => n.kind === "claim").map((n) => [n.key, n]));
  // The chip and, for a disagreeing claim, board or requirement, its "!" and
  // the notice under it (what slipped through in review: this list drew a
  // disagreeing claim as a plain chip, the desktop drawing alone marked it).
  const notices = words.notices || {};
  const chip = (node) => tokenChip(node.token, node.word,
    { errored: node.errored, small: true, marks: node.marks, notices });
  const markNote = (node) => ((node.marks || []).includes("disagree") && notices.disagree
    ? el("span", { class: "ml-mark", text: notices.disagree }) : null);
  const reqs = nodes.filter((n) => n.kind === "requirement");
  const out = el("div", { class: "nk-maplist" });
  if (reqs.length) {
    out.appendChild(el("p", { class: "ml-head", text: String((words.lanes || {}).requirements || "") }));
    out.appendChild(el("ul", { class: "ml-reqs" }, ...reqs.map((r) => el("li", {},
      el("button", { class: "ml-req", type: "button", onclick: () => onSelect && onSelect("requirement", r.key) },
        chip(r), el("b", { class: "mono", text: ` ${r.key} ` }), el("span", { text: r.title }),
        markNote(r))))));
  }
  for (const board of nodes.filter((n) => n.kind === "board")) {
    const look = lookOf(board.token, { errored: board.errored });
    out.appendChild(el("section", { class: `ml-board tone-${look.tone}` },
      el("button", { class: "ml-bhead", type: "button", onclick: () => onBoard && onBoard(board.key) },
        el("span", { class: "ml-btitle", text: board.title }), chip(board)),
      board.line ? el("p", { class: "ml-bline", text: board.line }) : null,
      markNote(board),
      el("ul", { class: "ml-rows" }, ...(board.claims || []).map((key) => {
        const node = claimNode.get(key);
        if (!node) return null;
        const line = lineOf.get(key) || {};
        const zones = (line.stops || []).map((id) => byId.get(id))
          .filter((n) => n && (n.kind === "zone" || n.kind === "station"))
          .map((n) => n.title || n.key);
        const detail = node.value_text || ((claimRows[key] || {}).cause_text) || "";
        return el("li", {},
          el("button", { class: "ml-row", type: "button", onclick: () => onSelect && onSelect("claim", key) },
            el("span", { class: "ml-top" }, chip(node), el("b", { class: "mono", text: ` ${key} ` })),
            el("span", { class: "ml-stmt", text: node.title }),
            detail ? el("span", { class: "ml-val", text: detail }) : null,
            markNote(node),
            zones.length ? el("span", { class: "ml-reads", text: `Reads: ${zones.join(", ")}` }) : null));
      }))));
  }
  return out;
}
