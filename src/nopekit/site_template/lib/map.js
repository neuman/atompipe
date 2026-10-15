// SPDX-License-Identifier: Apache-2.0
// map.js: the grounding map, drawn from data/map.json (architecture phase 5,
// SPEC 29; the transit layout, architecture phase 3b).
//
// The author's transit pattern, in plain SVG. On the left, what was asked (a
// card per requirement) and every group of choices (a zone box: its count, a
// bar of where its numbers come from, a diamond for each unconfirmed
// assumption that sets one). In the middle, the shared values (stations), in
// columns by the order the trace observed. On the right, the boards of claims.
// Each claim is ONE LINE: it starts at its first station, rides the stations
// its evaluators read (a filled dot) and the ones the trace puts before them (a
// hollow dot), and ends on its row of its board. Thin curves (feeds) run from
// each zone to every station its choices move, and from a zone to the start of
// a line that reads one of its choices directly (a tap). The line carries its
// status in three channels at once: its stroke (solid, heavy, dashed, dotted,
// from TOKEN_LOOK), its colour, and the glyph and baked word on its row.
//
// LINES BUNDLE AND FAN, BY ONE FIXED RULE. A station's lines sit side by side
// at a fixed pitch, in the order of their rows, centred on the mean of those
// rows; between two stations a line bends once, just after it leaves the first,
// and after its last station it fans into its row late, near the boards. In a
// bend zone the lines that rise turn top-first and the lines that fall turn
// bottom-first, so lines that share a bundle never cross. What slipped through
// (the author's verdict on phase 5's map, "so simplistic looking"): every line
// ran level at its row, so nothing showed which lines shared what, and the
// reference's trunk was rejected as "per-project routing". It is not: the
// layers are baked, and the bundling rule is the same for every project.
//
// ORDER IS BAKED, GEOMETRY IS RENDERED. `map.json` holds every node's lane, its
// order, rank, row, layer and column (indexes, never pixels); this file turns
// them into positions with fixed arithmetic, so the same state draws the same
// map every time. It never runs a force layout and it never reorders by
// default. The one reordering, "worst first", is a viewer control: it sorts
// rows inside each board by the baked `severity` and redraws.
//
// TEXT IS MEASURED AFTER PLACEMENT. Every label sits where the structure puts
// it; `relayout` then measures it (getComputedTextLength) and shortens it to its
// room, or wraps it where a box has room for lines. Text never moves a capsule,
// a box or a track. What slipped through in the reference map: its label widths
// came from character counts, and a font that loaded late overlapped them.
//
// THE MAP COMPUTES NO TRUTH. It reads `token`, `word`, `marks`, `tally`,
// `severity`, a feed's `estimate`, a line's `amber` and the order keys, and
// nothing here decides a status, a margin, readiness or a worst-of: a board's
// token is the baked worst of its claims, a line's is its claim's, and amber is
// the bake's mark. (What slipped through in the reference: its board headers
// decided GO and NO-GO in the browser from a hand-kept claim list, and its
// amber bands came from a hand-kept list of claims "on faith".)
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
/** The first row's top, the gap between two boards and the pad under a
 *  header. */
const TOP = 52, BOARD_GAP = 16, ROW_PAD = 6;
/** The left column: its x, the width of a requirement card and of a zone box.
 *  A zone box holds its name and count on one line, and a 96-unit bar and up to
 *  three assumption chips on the next (the reference's box was 184 wide and held
 *  two diamonds without ids; three ids need 236). */
const LX = 12, CARD_W = 236, ZONE_W = 236, ZONE_R = LX + ZONE_W;
/** A requirement card: three lines of text at most, so its height never
 *  depends on a measured width (text never moves a box). */
const CARD_LINES = 3, CARD_LINE_H = 15, CARD_PAD = 9, CARD_GAP = 8;
/** A zone box: its height, the least room between two boxes, and the room
 *  between the zone heading and the first box. Rejected: the design's even
 *  pitch over the column (52-76 units), which put "Parts list" 900 units from
 *  anything it fed; a box sits at the mean height of what it feeds instead,
 *  pushed down in its baked rank when it meets the box above. */
const ZONE_H = 46, ZONE_GAP = 10, BAR_W = 96;
/** The station columns: the middle lane's edges. Every (layer, column) of
 *  `map.layers` gets an equal share; on PETGasus that is 8 columns of 64 units.
 *  Rejected: 300-840 (the design's), which left 33 units for the last fan-out,
 *  too few for ten lines. */
const MX0 = 286, MX1 = 800;
/** Lines: the pitch of two lines side by side in a bundle (the reference's
 *  6.5 drew 3.2-unit strokes touching once their halos were added), the least
 *  pitch a crowded bend zone may shrink to, the bend's 45-degree run and the
 *  corner radius (the reference's `rounded(pts, 9)`), how far left of its first
 *  station a line starts, and the last x a line's final bend may start at. */
const TSP = 7, TSP_MIN = 3, BEND = 9, CORNER = 10, START = 22, FR = BX - 18;
/** A capsule's half width, the room above and below its first and last line,
 *  and the least gap between two capsules in one column (it holds the lower
 *  capsule's title). */
const CAP_R = 7, CAP_PAD = 8, CAP_GAP = 34;
/** Feeds: the fan at a zone's right edge, and how far along the run the curve's
 *  handles reach (0.45 is the reference's `buildFeeds`). */
const FAN = 12, HANDLE = 0.45;
/** Unvisited stations (no line stops there) are listed under the map. */
const LOOSE_H = 26;

const SEVERITY_SORT = (a, b) => a.severity - b.severity || a.row - b.row;
const BY_RANK = (a, b) => (a.rank ?? a.order ?? 0) - (b.rank ?? b.order ?? 0) || (a.order ?? 0) - (b.order ?? 0);
// "unrecorded": no record says where the number comes from (review of phase
// 3b: such a number was drawn as a design choice).
const SOURCES = [["chosen", "g-chosen"], ["datasheet", "g-sheet"], ["estimate", "g-est"], ["assumption", "g-guess"],
  ["unrecorded", "g-none"]];

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
    rowH: Math.ceil(42 + 1.05 * d14 + 1.25 * d12),
    trackY: 13 + 0.7 * d14,            // the track's y below the row's top
    title: 0.35 * t14,                 // the title's baseline below the track
    sub: 0.35 * t14 + t12 + 4,         // the second line's baseline below the track
    hdrH: Math.ceil(46 + dh + 1.25 * d12),
    hdrTitle: 19 + 0.8 * dh,
    hdrLine: 36 + dh + d12,
    line13: Math.max(CARD_LINE_H, 1.2 * Math.max(13, 12 / s)),
    // a zone box: its height, its name's baseline, its bar's top and its
    // chips' baseline, grown with its text as a row is
    zoneH: Math.ceil(ZONE_H + 1.25 * (Math.max(13, 12 / s) - 13) + (t11 - 11)),
    zName: 17 + (Math.max(13, 12 / s) - 13),
    zBar: 28 + 1.1 * (Math.max(13, 12 / s) - 13),
    zId: 35 + 1.1 * (Math.max(13, 12 / s) - 13) + 0.4 * (t11 - 11),
  };
}

/** The drawn scale of a box ``width`` wide (the map is never drawn below 0.6). */
const scaleOf = (width) => Math.max(0.6, (width || W) / W);

/** A polyline with rounded corners (the reference's `rounded`). */
function rounded(pts, r = CORNER) {
  if (pts.length < 3) return "M" + pts.map((p) => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join("L");
  let d = `M${pts[0][0].toFixed(1)},${pts[0][1].toFixed(1)}`;
  for (let i = 1; i < pts.length - 1; i += 1) {
    const [x0, y0] = pts[i - 1], [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    const l1 = Math.hypot(x1 - x0, y1 - y0), l2 = Math.hypot(x2 - x1, y2 - y1);
    if (!l1 || !l2) continue;
    const rr = Math.min(r, l1 / 2, l2 / 2);
    const ax = x1 - ((x1 - x0) / l1) * rr, ay = y1 - ((y1 - y0) / l1) * rr;
    const bx = x1 + ((x2 - x1) / l2) * rr, by = y1 + ((y2 - y1) / l2) * rr;
    d += `L${ax.toFixed(1)},${ay.toFixed(1)}Q${x1.toFixed(1)},${y1.toFixed(1)} ${bx.toFixed(1)},${by.toFixed(1)}`;
  }
  const last = pts[pts.length - 1];
  return `${d}L${last[0].toFixed(1)},${last[1].toFixed(1)}`;
}

/** The part of a polyline left of ``x1``. */
function clipTo(pts, x1) {
  const out = [pts[0]];
  for (let i = 0; i < pts.length - 1; i += 1) {
    const [xa, ya] = pts[i], [xb, yb] = pts[i + 1];
    if (xb <= x1) { out.push([xb, yb]); continue; }
    if (xa < x1) out.push([x1, ya + ((yb - ya) * (x1 - xa)) / ((xb - xa) || 1)]);
    break;
  }
  return out;
}

/** The part of a polyline right of ``x0`` (the reference's `clipFrom`). */
function clipFrom(pts, x0) {
  const out = [];
  for (let i = 0; i < pts.length - 1; i += 1) {
    const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    if (x2 < x0) continue;
    if (x1 < x0) out.push([x0, y1 + ((y2 - y1) * (x0 - x1)) / ((x2 - x1) || 1)]);
    else out.push([x1, y1]);
  }
  out.push(pts[pts.length - 1]);
  return out;
}

/** The y of a polyline at ``x`` (its first segment over x), or null. */
function yAt(pts, x) {
  for (let i = 0; i < pts.length - 1; i += 1) {
    const [x1, y1] = pts[i], [x2, y2] = pts[i + 1];
    if (x >= Math.min(x1, x2) - 0.01 && x <= Math.max(x1, x2) + 0.01) {
      return x2 === x1 ? y1 : y1 + ((y2 - y1) * (x - x1)) / (x2 - x1);
    }
  }
  return null;
}

/** One bend from ``y0`` to ``y1`` starting at ``x``: level, a 45-degree run,
 *  the vertical, a 45-degree run, level (the reference's `trunkPath`). */
function bendPoints(x, y0, y1) {
  const r = Math.min(BEND, Math.abs(y1 - y0) / 2), sg = y1 < y0 ? -1 : 1;
  return [[x, y0], [x + r, y0 + sg * r], [x + r, y1 - sg * r], [x + 2 * r, y1]];
}

/** Draw the map into ``host``. Returns ``{destroy, select, clear}``.
 *  ``onSelect(kind, key)`` opens the drawer; ``onBoard(key)`` scrolls to a
 *  board's section. */
export function renderMap(host, map, page, { onSelect, onBoard, onRescale, worstFirst = false } = {}) {
  const words = (page && page.words) || {};
  const traceWords = words.trace || {};
  const claimRows = (page && page.claims) || {};
  const nodes = map.nodes || [];
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const lines = map.lines || [];
  const lineOf = new Map(lines.map((l) => [l.claim, l]));
  const boards = nodes.filter((n) => n.kind === "board");
  const claimNode = new Map(nodes.filter((n) => n.kind === "claim").map((n) => [n.key, n]));
  const requirements = nodes.filter((n) => n.kind === "requirement").sort(BY_RANK);
  const zones = nodes.filter((n) => n.kind === "zone").sort(BY_RANK);
  const stations = nodes.filter((n) => n.kind === "station");
  const feeds = map.feeds || [];
  const restsOn = ((map.edges || {}).rests_on) || {};
  // the claims each assumption holds up (rests_on, reversed): hovering an
  // assumption lights them. What slipped through (review of phase 3b): it
  // lit the assumption alone and dimmed every claim resting on it.
  const restedBy = new Map();
  for (const [src, targets] of Object.entries(restsOn)) {
    for (const t of targets || []) {
      const key = String(t).replace(/^claim:/, "");
      if (!restedBy.has(key)) restedBy.set(key, []);
      restedBy.get(key).push(String(src).replace(/^claim:/, ""));
    }
  }

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
  const byRow = (a, b) => (rowY.get(a) ?? 0) - (rowY.get(b) ?? 0);

  // ------------------------------------------------------------------ stations
  // x: an equal share of the middle lane for each (layer, column) of the bake.
  const layers = (map.layers && map.layers.length) ? map.layers
    : [Math.max(1, ...stations.map((s) => (s.layer || 0) + 1))];
  const layerStart = [];
  layers.reduce((sum, n, i) => { layerStart[i] = sum; return sum + Math.max(1, n); }, 0);
  const nCols = layers.reduce((sum, n) => sum + Math.max(1, n), 0) || 1;
  const pitchX = (MX1 - MX0) / nCols;
  const colOf = (s) => (layerStart[s.layer || 0] || 0) + (s.column || 0);
  const colX = (c) => MX0 + (c + 0.5) * pitchX;

  // Each station's bundle: its lines, side by side in the order of their rows,
  // centred on the mean of those rows.
  const through = new Map();       // station id -> [claim keys]
  for (const line of lines) {
    if (!rowY.has(line.claim)) continue;
    for (const stop of line.stops || []) {
      if (!byId.has(stop) || byId.get(stop).kind !== "station") continue;
      if (!through.has(stop)) through.set(stop, []);
      through.get(stop).push(line.claim);
    }
  }
  const place = new Map();         // station id -> {x, col, top, bottom, slot: Map}
  const columnsOf = new Map();     // column -> [station ids], by centre
  for (const s of stations) {
    const keys = (through.get(s.id) || []).slice().sort(byRow);
    if (!keys.length) continue;
    const centre = keys.reduce((sum, k) => sum + rowY.get(k), 0) / keys.length;
    const col = colOf(s);
    place.set(s.id, { x: colX(col), col, keys, centre });
    if (!columnsOf.has(col)) columnsOf.set(col, []);
    columnsOf.get(col).push(s.id);
  }
  // In one column, capsules meet: push each down below the one above it, in
  // the order of their centres (then their baked order).
  for (const ids of columnsOf.values()) {
    ids.sort((a, b) => place.get(a).centre - place.get(b).centre
      || (byId.get(a).order || 0) - (byId.get(b).order || 0));
    let floor = -Infinity;
    for (const id of ids) {
      const p = place.get(id);
      const half = ((p.keys.length - 1) * TSP) / 2;
      let first = p.centre - half;
      if (first - CAP_PAD < floor + CAP_GAP) first = floor + CAP_GAP + CAP_PAD;
      p.slot = new Map(p.keys.map((k, i) => [k, first + i * TSP]));
      p.top = first - CAP_PAD;
      p.bottom = first + (p.keys.length - 1) * TSP + CAP_PAD;
      floor = p.bottom;
    }
  }

  // ------------------------------------------------------------------ routes
  // Each line's stops on the drawing, and the bends between them. A bend zone
  // is the room just after a column (between two stations), or the final band
  // before the boards; in each, the lines that rise take x top-first and the
  // lines that fall bottom-first.
  const stopsOf = (line) => (line.stops || []).filter((id) => place.has(id));
  const bendZones = new Map();     // zone key -> {x0, x1, up: [], down: []}
  const zoneOf = (key, x0, x1) => {
    if (!bendZones.has(key)) bendZones.set(key, { x0, x1, up: [], down: [] });
    return bendZones.get(key);
  };
  const lastCol = Math.max(-1, ...Array.from(place.values(), (p) => p.col));
  const finalX0 = Math.max(MX1 - 8, colX(Math.max(0, lastCol)) + CAP_R + 8);
  const legs = new Map();          // claim -> [{from:[x,y], to:[x,y], zone, bend}]
  for (const line of lines) {
    const ry = rowY.get(line.claim);
    if (ry === undefined) continue;
    const stops = stopsOf(line);
    const list = [];
    for (let i = 0; i < stops.length; i += 1) {
      const p = place.get(stops[i]);
      const yy = p.slot.get(line.claim);
      const next = i + 1 < stops.length ? place.get(stops[i + 1]) : null;
      const ty = next ? next.slot.get(line.claim) : ry;
      const leg = { from: [p.x, yy], to: [next ? next.x : SX - 12, ty], bend: null };
      if (Math.abs(ty - yy) > 0.5) {
        const zone = next
          ? zoneOf(`c${p.col}`, p.x + CAP_R + 5, colX(p.col + 1) - CAP_R - 5)
          : zoneOf("final", finalX0, FR);
        leg.zone = zone;
        (ty < yy ? zone.up : zone.down).push({ claim: line.claim, y: yy, leg });
      }
      list.push(leg);
    }
    legs.set(line.claim, list);
  }
  for (const zone of bendZones.values()) {
    const room = Math.max(0, zone.x1 - zone.x0 - 2 * BEND);
    for (const [group, dir] of [[zone.up, 1], [zone.down, -1]]) {
      group.sort((a, b) => dir * (a.y - b.y) || byRow(a.claim, b.claim));
      const pitch = group.length > 1 ? Math.max(TSP_MIN, Math.min(TSP, room / (group.length - 1))) : 0;
      group.forEach((item, i) => { item.leg.bend = zone.x0 + i * pitch; });
    }
  }
  const routes = new Map();        // claim -> {pts, start:[x,y], halt: bool}
  for (const line of lines) {
    const ry = rowY.get(line.claim);
    if (ry === undefined) continue;
    const list = legs.get(line.claim) || [];
    const fed = (line.taps || []).length || (line.fed_by || []).length;
    if (!list.length) {
      // No station: a short stub on its row, or, when a zone feeds it
      // directly, a longer one with a halt where its taps land.
      const x0 = fed ? BX - 120 : BX - 46;
      routes.set(line.claim, { pts: [[x0, ry], [SX - 12, ry]], start: [x0, ry], halt: !!fed });
      continue;
    }
    const first = list[0].from;
    const pts = [[first[0] - START, first[1]], first];
    for (const leg of list) {
      if (leg.bend !== null && leg.bend !== undefined) {
        const x = Math.min(Math.max(leg.bend, leg.from[0] + CAP_R + 2), leg.to[0] - 2 * BEND - 2);
        pts.push(...bendPoints(x, leg.from[1], leg.to[1]));
      }
      pts.push(leg.to);
    }
    routes.set(line.claim, { pts, start: pts[0], halt: false, fed: !!fed });
  }

  // ------------------------------------------------------------------ left column
  // Requirement cards first, then the zone boxes at the mean height of what
  // each feeds, in their baked rank.
  const cardH = CARD_PAD * 2 + CARD_LINES * M.line13;
  const cardTop = TOP;
  const cards = requirements.map((r, i) => ({ node: r, y: cardTop + i * (cardH + CARD_GAP) }));
  const cardsBottom = cards.length ? cards[cards.length - 1].y + cardH : TOP - 30;
  const zoneHead = cards.length ? cardsBottom + 30 : 24;
  const zonesTop = cards.length ? zoneHead + 14 : TOP;
  const targetYs = new Map();      // zone id -> [y of what it feeds]
  for (const f of feeds) {
    const p = place.get(f.to);
    if (!p) continue;
    if (!targetYs.has(f.zone)) targetYs.set(f.zone, []);
    targetYs.get(f.zone).push((p.top + p.bottom) / 2);
  }
  const taps = [];                 // {zone, claim, choices}
  for (const line of lines) {
    const route = routes.get(line.claim);
    if (!route) continue;
    for (const tap of line.taps || []) {
      if (!byId.has(tap.zone)) continue;
      taps.push({ zone: tap.zone, claim: line.claim, choices: tap.choices || [] });
      if (!targetYs.has(tap.zone)) targetYs.set(tap.zone, []);
      targetYs.get(tap.zone).push(route.start[1]);
    }
  }
  const zoneY = new Map();         // zone id -> its box's top
  {
    let floor = zonesTop - ZONE_GAP;
    const fedZones = zones.filter((z) => (targetYs.get(z.id) || []).length);
    const idleZones = zones.filter((z) => !(targetYs.get(z.id) || []).length);
    for (const z of [...fedZones, ...idleZones]) {
      const ys = targetYs.get(z.id) || [];
      const want = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length - M.zoneH / 2 : floor + ZONE_GAP;
      const top = Math.max(want, floor + ZONE_GAP);
      zoneY.set(z.id, top);
      floor = top + M.zoneH;
    }
  }
  const zonesBottom = zones.length ? Math.max(...zoneY.values()) + M.zoneH : zonesTop;
  const keyTop = zonesBottom + 22;
  const keyLines = zones.length ? 10 : 0;
  const keyBottom = keyTop + keyLines * M.line13;

  // Stations no line stops at: a list under the map.
  const loose = stations.filter((s) => !place.has(s.id));
  const capsBottom = Math.max(0, ...Array.from(place.values(), (p) => p.bottom));
  const looseTop = Math.max(rowsBottom, capsBottom + 20);
  const H = Math.max(rowsBottom, keyBottom, capsBottom + 12, cardsBottom)
    + (loose.length ? 34 + loose.length * LOOSE_H : 0) + 8;

  // ------------------------------------------------------------------ the svg
  const root = svg("svg", {
    class: "nk-map", viewBox: `0 0 ${W} ${H}`, role: "group",
    "aria-label": words.headings && words.headings.map ? words.headings.map : "map",
  });
  const viewport = svg("g", { class: "vp" });
  root.appendChild(viewport);
  const layer = {};
  for (const name of ["heads", "feeds", "zones", "cards", "labels", "casing", "tracks", "hits", "caps",
    "bridges", "dots", "caplabels", "board"]) {
    layer[name] = svg("g", { class: `L-${name}` });
    viewport.appendChild(layer[name]);
  }
  const later = [];                // text to measure after placement

  // column heads
  const laneWord = (lane) => String(((words.lanes || {})[lane]) || lane).toUpperCase();
  const leftHead = cards.length ? "requirements" : "zones";
  layer.heads.appendChild(svg("text", { class: "colhead", x: LX + CARD_W / 2, y: 24,
    "text-anchor": "middle", text: laneWord(leftHead) }));
  if (cards.length && zones.length) {
    layer.heads.appendChild(svg("text", { class: "colhead", x: LX + ZONE_W / 2, y: zoneHead,
      "text-anchor": "middle", text: laneWord("zones") }));
  }
  if (place.size || stations.length) {
    layer.heads.appendChild(svg("text", { class: "colhead", x: (MX0 + MX1) / 2, y: 24,
      "text-anchor": "middle", text: laneWord("stations") }));
  }
  layer.heads.appendChild(svg("text", { class: "colhead", x: (BX + BR) / 2, y: 24,
    "text-anchor": "middle", text: laneWord("boards") }));

  // ------------------------------------------------------------------ tracks
  // One halo and one stroke per line, in row order, so where two lines cross
  // the later one reads over the earlier one.
  const looks = new Map();
  const ordered = lines.filter((l) => routes.has(l.claim)).map((l) => l.claim).sort(byRow);
  for (const key of ordered) {
    const line = lineOf.get(key);
    const route = routes.get(key);
    const look = lookOf(line.token, { errored: line.errored });
    looks.set(key, look);
    const d = rounded(route.pts);
    const marks = line.marks || [];
    layer.tracks.appendChild(svg("path", { d, class: `halo tk-${look.stroke}`, "data-c": key }));
    // the casings sit between the line's halo and its stroke, so a line's own
    // halo never cuts its amber band in two
    if (marks.includes("amber")) {
      const enters = line.amber && line.amber.enters && place.get(line.amber.enters);
      const pts = enters ? clipFrom(route.pts, enters.x - CAP_R - 4) : route.pts;
      layer.tracks.appendChild(svg("path", { d: rounded(pts), class: "casing amber", "data-c": key }));
    }
    if (marks.includes("disagree")) {
      layer.tracks.appendChild(svg("path", { d, class: "casing disagree", "data-c": key }));
    }
    layer.tracks.appendChild(svg("path", {
      d, class: `track tk-${look.stroke} tone-${look.tone}`, "data-c": key,
    }));
    const hit = svg("path", { d, class: "hit", "data-c": key });
    bindLine(hit, key);
    layer.hits.appendChild(hit);
    // where the line starts: a tap circle when a zone feeds it, a halt when it
    // rides no station
    if (route.halt || route.fed) {
      layer.dots.appendChild(svg("circle", { class: `tapdot${route.halt ? " halt" : ""} tone-${look.tone}`,
        cx: route.start[0], cy: route.start[1], r: route.halt ? 4 : 3.5, "data-c": key }));
    }
    // The part of a line before the first value its evaluators read rides
    // stations the trace only puts before them: faded, so an inferred order
    // never reads like a read (review of phase 3b).
    const firstRead = (line.stops || []).find((id) => place.has(id) && (line.stop_kind || {})[id] === "read");
    const firstStop = (line.stops || []).find((id) => place.has(id));
    if (firstStop && firstStop !== firstRead) {
      const until = firstRead ? place.get(firstRead).x - CAP_R - 3 : route.pts[route.pts.length - 1][0];
      const pts = clipTo(route.pts, until);
      if (pts.length > 1) {
        layer.tracks.appendChild(svg("path", { d: rounded(pts), class: "upfade", "data-c": key },
          traceWords.upstream_stop ? svg("title", { text: traceWords.upstream_stop }) : null));
      }
    }
    // a line whose every read the test did not see change says so where it starts
    if (line.unseen && traceWords.unseen_line) {
      layer.dots.appendChild(svg("circle", { class: `tapdot unseen tone-${look.tone}`, cx: route.start[0],
        cy: route.start[1], r: 4, "data-c": key }, svg("title", { text: traceWords.unseen_line })));
    }
  }

  // ------------------------------------------------------------------ springs
  // An assumption's row is joined to each station its choices move, and a
  // test on the real part to the stations of the assumptions it settles
  // (the bake's `sets`): a thin curve from the row's start back to the
  // station, as the reference's springs sit beside the station a guess
  // enters. What slipped through (review of phase 3b): these rows ended in a
  // stub that joined nothing.
  for (const line of lines) {
    const route = routes.get(line.claim);
    if (!route || !(line.sets || []).length) continue;
    const node = claimNode.get(line.claim) || {};
    const words = node.claim_kind === "physical" ? traceWords.settles : traceWords.sets;
    for (const sid of line.sets) {
      const p = place.get(sid);
      if (!p) continue;
      const x1 = p.x + CAP_R + 1, y1 = (p.top + p.bottom) / 2, [x2, y2] = route.start;
      const k = HANDLE * (x2 - x1);
      const d = `M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 + k).toFixed(1)},${y1.toFixed(1)} ${(x2 - k).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
      layer.feeds.appendChild(svg("path", { d, class: `spring ${node.claim_kind === "physical" ? "proof" : "guess"}`,
        "data-c": line.claim }, words ? svg("title", { text: words }) : null));
    }
  }

  // ------------------------------------------------------------------ capsules
  const capEls = [];
  const labelEls = [];             // capsule labels dim with their capsule
  const capOf = new Map();         // station id -> its group
  for (const s of stations) {
    const p = place.get(s.id);
    if (!p) continue;
    const g = svg("g", {
      class: `capsule cap-station${s.generated ? " generated" : ""}`,
      "data-node": s.id, tabindex: "0", role: "button",
      "aria-label": `${s.title || s.key}${s.value_text ? `: ${s.value_text}` : ""}`,
    });
    g.dataset.claims = p.keys.join(" ");
    g.appendChild(svg("rect", { class: "cap", x: p.x - CAP_R, y: p.top, width: CAP_R * 2,
      height: p.bottom - p.top, rx: CAP_R }));
    g.appendChild(svg("rect", { class: "hit", x: p.x - 14, y: p.top - 4, width: 28,
      height: p.bottom - p.top + 8 }));
    layer.caps.appendChild(g);
    bindStation(g, s);
    capEls.push(g);
    capOf.set(s.id, g);
    if ((s.marks || []).includes("disagree")) {
      g.appendChild(svg("text", { class: "mark-bang", x: p.x, y: p.top - 4, "text-anchor": "middle",
        text: "!" }));
    }
    // A stopping line gets a dot: filled where its evaluators read the value,
    // hollow where the trace puts the value before what they read.
    const kinds = s.stop_kinds || {};
    for (const key of p.keys) {
      const look = looks.get(key);
      if (!look) continue;
      const line = lineOf.get(key) || {};
      const kind = (line.stop_kind || {})[s.id] || kinds[key] || "read";
      layer.dots.appendChild(svg("circle", {
        class: `dot ${kind === "upstream" ? "up" : "read"} tone-${look.tone}`,
        cx: p.x, cy: p.slot.get(key), r: kind === "upstream" ? 2.9 : 3.2, "data-c": key,
      }, kind === "upstream" && traceWords.upstream_stop ? svg("title", { text: traceWords.upstream_stop }) : null));
    }
    // A line that only passes the capsule's span is drawn OVER it on a bridge,
    // so it never reads as a stop.
    for (const [key, route] of routes) {
      if (p.slot.has(key)) continue;
      const yy = yAt(route.pts, p.x);
      if (yy === null || yy < p.top - 1 || yy > p.bottom + 1) continue;
      const look = looks.get(key);
      const d = `M${(p.x - CAP_R - 3).toFixed(1)},${yy.toFixed(1)} H${(p.x + CAP_R + 3).toFixed(1)}`;
      layer.bridges.appendChild(svg("path", { d, class: "bridge-gap", "data-c": key }));
      layer.bridges.appendChild(svg("path", {
        d, class: `track tk-${look.stroke} tone-${look.tone}`, "data-c": key }));
    }
    later.push(capsuleLabel(s, p.x, p.top));
  }

  // requirement cards: what was asked, at the top of the left column
  for (const { node, y: top } of cards) {
    const look = lookOf(node.token, { errored: node.errored });
    const g = svg("g", { class: `card cap-requirement tone-${look.tone}`, "data-node": node.id,
      tabindex: "0", role: "button", "aria-label": `${node.key}: ${node.title || ""}. ${node.word || ""}.` });
    g.dataset.claims = (node.claims || []).join(" ");
    g.appendChild(svg("rect", { class: "cardbg", x: LX, y: top, width: CARD_W, height: cardH, rx: 9 }));
    g.appendChild(svg("rect", { class: `cardbar tone-${look.tone}`, x: LX, y: top + 4, width: 3.5,
      height: cardH - 8, rx: 1.5 }));
    const glyph = svg("text", { class: `cglyph tone-${look.tone}`, x: LX + 16, y: top + CARD_PAD + 11,
      "text-anchor": "middle", text: look.glyph });
    const body = svg("text", { class: "ctext", x: LX + 28, y: top + CARD_PAD + 11 });
    g.append(glyph, body);
    if ((node.marks || []).includes("disagree")) {
      g.appendChild(svg("text", { class: "mark-bang", x: LX + CARD_W - 10, y: top + CARD_PAD + 11,
        "text-anchor": "end", text: "!" }));
    }
    layer.cards.appendChild(g);
    later.push({ card: [body, node, CARD_W - 40, top + CARD_PAD + 11] });
    bindNode(g, node, new Set(node.claims || []));
    capEls.push(g);
  }

  // stations no line stops at, listed under the map
  if (loose.length) {
    const left = MX0, right = MX1;
    layer.labels.appendChild(svg("text", { class: "loose-head", x: left, y: looseTop + 10,
      text: "No line stops here yet." }));
    loose.forEach((node, i) => {
      const yy = looseTop + 24 + i * LOOSE_H;
      const g = svg("g", { class: "loose cap-station", "data-node": node.id,
        tabindex: "0", role: "button", "aria-label": node.title || node.key });
      g.dataset.claims = "";
      g.appendChild(svg("rect", { class: "loose-bg", x: left, y: yy, width: right - left,
        height: LOOSE_H - 6, rx: 9 }));
      const t = svg("text", { class: `loose-name${node.generated ? " mono" : ""}`,
        x: left + 10, y: yy + 14, text: node.title || node.key });
      g.appendChild(t);
      later.push({ fit: [t, right - left - 20] });
      layer.labels.appendChild(g);
      bindStation(g, node);
      capEls.push(g);
    });
  }

  // ------------------------------------------------------------------ zones
  // Every group of choices: a box with its name and count, a bar of where its
  // numbers come from (the bake's `sources`), and an amber diamond with its id
  // for each unconfirmed assumption that sets one of its choices.
  const zoneEls = new Map();
  const zoneMid = (id) => zoneY.get(id) + M.zoneH / 2;
  for (const z of zones) {
    const top = zoneY.get(z.id);
    const g = svg("g", { class: `zone${z.idle ? " idle" : ""}${z.generated ? " generated" : ""}`,
      "data-zone": z.id, tabindex: "0", role: "button",
      "aria-label": `${z.title || z.key}, ${z.count ?? (z.members || []).length}` });
    g.appendChild(svg("rect", { class: "zbg", x: LX, y: top, width: ZONE_W, height: M.zoneH, rx: 10 }));
    const name = svg("text", { class: `zname${z.generated ? " mono" : ""}`, x: LX + 10, y: top + M.zName,
      text: z.title || z.key });
    const count = svg("text", { class: "zcount", x: ZONE_R - 10, y: top + M.zName, "text-anchor": "end",
      text: String(z.count ?? (z.members || []).length) });
    g.append(name, count);
    if (z.idle && traceWords.zone_idle) g.appendChild(svg("title", { text: traceWords.zone_idle }));
    else if ((z.unmeasured || []).length && traceWords.zone_unmeasured) {
      g.appendChild(svg("title", { text: `${traceWords.zone_unmeasured} ${z.unmeasured.join(", ")}` }));
    }
    // the bar
    const src = z.sources || {};
    const total = SOURCES.reduce((n, [k]) => n + (src[k] || 0), 0)
      || ((z.ground || {}).chosen || 0) + ((z.ground || {}).input || 0) + ((z.ground || {}).assumption || 0);
    let bx = LX + 10;
    const parts = z.sources ? SOURCES : [["chosen", "g-chosen"], ["input", "g-sheet"], ["assumption", "g-guess"]];
    const bag = z.sources ? src : (z.ground || {});
    for (const [k, cls] of parts) {
      const n = bag[k] || 0;
      if (!n || !total) continue;
      const w = (n / total) * BAR_W;
      g.appendChild(svg("rect", { class: `gbar ${cls}`, x: bx, y: top + M.zBar, width: Math.max(1.5, w - 1.2),
        height: 6, rx: 1.5 }));
      bx += w;
    }
    // the assumptions that set a choice here, right-aligned (each placed in
    // relayout, after its id is measured)
    const chips = [];
    for (const id of (z.estimate || []).slice().reverse()) {
      const chip = svg("g", { class: "zest", "data-a": id, tabindex: "0", role: "button", "aria-label": id });
      const t = svg("text", { class: "zid", x: ZONE_R - 8, y: top + M.zId, "text-anchor": "end", text: id });
      chip.append(svg("path", { class: "zdia" }), t);
      g.appendChild(chip);
      chips.push([chip, t]);
      bindAssumption(chip, id);
    }
    if (chips.length) later.push({ chips: [chips, top] });
    layer.zones.appendChild(g);
    later.push({ fit: [name, ZONE_W - 20], before: count });
    zoneEls.set(z.id, g);
    bindZone(g, z);
  }
  // under the boxes: what the boxes and the bars say
  if (zones.length) {
    const nChoices = zones.reduce((n, z) => n + (z.count ?? (z.members || []).length), 0);
    const summary = String(traceWords.zones_summary || "")
      .replace("{n}", String(nChoices)).replace("{z}", String(zones.length));
    const t1 = svg("text", { class: "zkey", x: LX, y: keyTop, text: summary });
    layer.zones.appendChild(t1);
    const sourceWords = traceWords.sources || {};
    const key = svg("g", { class: "zkeyrow" });
    const items = [];
    // only the sources some bar draws (a key with an unused swatch says the
    // map holds a kind of number it does not)
    const used = new Set(zones.flatMap((z) => Object.entries(z.sources || {}).filter(([, n]) => n > 0).map(([k]) => k)));
    for (const [k, cls] of SOURCES) {
      if (!sourceWords[k] || !used.has(k)) continue;
      const it = svg("g", {});
      const sw = k === "assumption" ? svg("path", { class: "zdia" })
        : svg("rect", { class: `gbar ${cls}`, width: 12, height: 6, rx: 1.5 });
      const t = svg("text", { class: "zkey", x: 0, y: 0, text: sourceWords[k] });
      it.append(sw, t);
      key.appendChild(it);
      items.push({ sw, t, dia: k === "assumption" });
    }
    layer.zones.appendChild(key);
    let t3 = null;
    if (traceWords.feeds_key && feeds.length) {
      t3 = svg("text", { class: "zkey", x: LX, y: keyTop, text: traceWords.feeds_key });
      layer.zones.appendChild(t3);
    }
    // the three are stacked in relayout, each after the last as wrapped
    later.push({ zkey: [t1, items, t3] });
  }

  // ------------------------------------------------------------------ feeds
  // A thin curve from a zone's right edge to each station its choices move
  // (the bake's `feeds`, the trace's direct derivation), and to the start of
  // each line that reads one of its choices directly (`taps`). A feed is amber
  // and dashed when an unconfirmed assumption sets one of its choices.
  const feedEls = [];
  {
    const outs = new Map();        // zone id -> [{item, y}]
    const ins = new Map();         // station id -> [{item, y}]
    const items = [];
    for (const f of feeds) {
      const p = place.get(f.to);
      if (!p || !zoneY.has(f.zone)) continue;
      items.push({ kind: "feed", zone: f.zone, to: f.to, claim: "", f, tx: p.x - CAP_R, ty: (p.top + p.bottom) / 2 });
    }
    for (const t of taps) {
      if (!zoneY.has(t.zone)) continue;
      const r = routes.get(t.claim);
      items.push({ kind: "tap", zone: t.zone, to: `claim:${t.claim}`, claim: t.claim, f: t,
        tx: r.start[0] - (r.halt ? 4 : 3.5), ty: r.start[1] });
    }
    for (const it of items) {
      if (!outs.has(it.zone)) outs.set(it.zone, []);
      outs.get(it.zone).push(it);
      if (it.kind === "feed") {
        if (!ins.has(it.to)) ins.set(it.to, []);
        ins.get(it.to).push(it);
      }
    }
    for (const [zid, list] of outs) {
      list.sort((a, b) => a.ty - b.ty || a.tx - b.tx);
      const spread = list.length > 1 ? Math.min(FAN * 2, (M.zoneH - 12)) / (list.length - 1) : 0;
      list.forEach((it, i) => { it.sy = zoneMid(zid) - (spread * (list.length - 1)) / 2 + i * spread; });
    }
    for (const [sid, list] of ins) {
      const p = place.get(sid);
      list.sort((a, b) => a.sy - b.sy);
      const span = Math.max(0, p.bottom - p.top - 12);
      const step = list.length > 1 ? Math.min(6, span / (list.length - 1)) : 0;
      const mid = (p.top + p.bottom) / 2;
      list.forEach((it, i) => { it.ty = mid - (step * (list.length - 1)) / 2 + i * step; });
    }
    for (const it of items) {
      const x1 = ZONE_R, y1 = it.sy, x2 = it.tx, y2 = it.ty;
      const k = HANDLE * (x2 - x1);
      const d = `M${x1},${y1.toFixed(1)} C${(x1 + k).toFixed(1)},${y1.toFixed(1)} ${(x2 - k).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}`;
      const est = it.kind === "feed" ? (it.f.estimate || []) : [];
      const path = svg("path", { d, class: `feed${it.kind === "tap" ? " tap" : ""}${est.length ? " est" : ""}`,
        "data-zone": it.zone, "data-to": it.to });
      if (est.length) path.dataset.est = est.join(" ");
      if (it.claim) path.dataset.tap = it.claim;
      const choices = (it.f.choices || []).join(", ");
      if (choices) path.appendChild(svg("title", { text: choices }));
      layer.feeds.appendChild(path);
      feedEls.push(path);
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
    const lit = () => light(new Set(board.claims || []));
    g.addEventListener("mouseenter", lit);
    g.addEventListener("mouseleave", restore);
    g.addEventListener("focus", lit);
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
      const line = lineOf.get(key) || {};
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
      if ((node.marks || []).includes("amber") && line.amber && line.amber.word) {
        sub.appendChild(svg("tspan", { class: "ramber", text: "  ◆" }));
      }
      if ((line.serves || []).length) {
        sub.appendChild(svg("tspan", { class: "rreq", text: `  ·  ${line.serves.join(", ")}` }));
      }
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
    t.dataset.claims = (place.get(node.id) || { keys: [] }).keys.join(" ");
    t.dataset.node = node.id;
    labelEls.push(t);
    t.appendChild(svg("tspan", { class: `name${node.generated ? " mono" : ""}`,
      text: node.title || node.key }));
    if (node.value_text) t.appendChild(svg("tspan", { class: "val", text: `  ${node.value_text}` }));
    layer.caplabels.appendChild(t);
    // The label goes where it meets the fewest tracks and no other label or
    // capsule (relayout): above, below, then beside its capsule. What slipped
    // through (the first transit drawing): every label sat above its capsule,
    // so a line passing just above a bundle struck its title through.
    return { label: [t, place.get(node.id)] };
  }

  /** Where a station's label may go, in the order tried: [x, y, anchor]. */
  function labelSpots(p, lineH) {
    const mid = (p.top + p.bottom) / 2 + 4, below = p.bottom + lineH + 1;
    return [
      [p.x, p.top - 7, "middle"], [p.x + 8, p.top - 7, "end"], [p.x - 8, p.top - 7, "start"],
      [p.x, below, "middle"], [p.x + 8, below, "end"], [p.x - 8, below, "start"],
      [p.x - CAP_R - 6, mid, "end"], [p.x + CAP_R + 6, mid, "start"],
      [p.x, p.top - 7 - lineH, "middle"], [p.x + 8, p.top - 7 - lineH, "end"], [p.x - 8, p.top - 7 - lineH, "start"],
      [p.x, below + lineH, "middle"], [p.x + CAP_R + 4, below, "start"], [p.x, p.top - 7 - 2 * lineH, "middle"],
    ];
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

  /** Words of ``text`` in lines of ``width`` at most, ``maxLines`` at most
   *  (the last one ends "…" when cut). ``first`` is a lead the first line
   *  starts with. */
  function wrapWords(t, text, width, maxLines, first = "") {
    const probe = svg("tspan", {});
    t.appendChild(probe);
    const out = [];
    let current = first ? [first] : [];
    for (const word of String(text || "").split(/\s+/).filter(Boolean)) {
      probe.textContent = [...current, word].join(" ");
      if (tw(t) > width && current.length) {
        out.push(current.join(" "));
        current = [word];
      } else {
        current.push(word);
      }
    }
    if (current.length) out.push(current.join(" "));
    t.removeChild(probe);
    const shown = out.slice(0, maxLines);
    if (out.length > maxLines) shown[maxLines - 1] = `${shown[maxLines - 1]} …`;
    return { shown, cut: out.length > maxLines };
  }

  function wrapText(t, width, maxLines, lineH) {
    if (!t.dataset.full) t.dataset.full = t.textContent;
    const text = t.dataset.full;
    while (t.firstChild) t.removeChild(t.firstChild);
    const { shown, cut } = wrapWords(t, text, width, maxLines);
    const x = Number(t.getAttribute("x")), y0 = Number(t.getAttribute("y"));
    shown.forEach((line, i) => t.appendChild(svg("tspan", { x, y: y0 + i * lineH, text: line })));
    if (cut) t.appendChild(svg("title", { text }));
  }

  /** A requirement card's id and statement, in three lines at most. */
  function wrapCard(t, node, width, y0) {
    while (t.firstChild) t.removeChild(t.firstChild);
    const { shown, cut } = wrapWords(t, node.title, width, CARD_LINES, node.key);
    const x = Number(t.getAttribute("x"));
    shown.forEach((text, i) => {
      const s = svg("tspan", { x, y: y0 + i * M.line13 });
      if (i === 0 && text.startsWith(node.key)) {
        s.appendChild(svg("tspan", { class: "req-id", text: node.key }));
        s.appendChild(document.createTextNode(text.slice(node.key.length)));
      } else {
        s.textContent = text;
      }
      t.appendChild(s);
    });
    t.appendChild(svg("title", { text: `${node.key} ${node.title || ""}${cut ? "" : ""}` }));
  }

  function relayout() {
    const placed = [];
    for (const item of later) {
      if (item.row) {
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
      } else if (item.card) {
        const [t, node, width, y0] = item.card;
        wrapCard(t, node, width, y0);
      } else if (item.wrapText) {
        wrapText(...item.wrapText);
      } else if (item.chips) {
        // an assumption's diamond sits left of its id as drawn, right to left
        const [chips, top] = item.chips;
        let ax = ZONE_R - 8;
        const dy = top + M.zBar + 3;
        for (const [chip, t] of chips) {
          t.setAttribute("x", ax);
          const dx = ax - tw(t) - 9;
          chip.querySelector("path").setAttribute("d",
            `M${dx},${dy - 6} L${dx + 6},${dy} L${dx},${dy + 6} L${dx - 6},${dy} Z`);
          ax = dx - 12;
        }
      } else if (item.zkey) {
        // under the boxes: the summary, a swatch and its word for each source
        // (wrapped to the column), then what a thin line is
        const [t1, items, t3] = item.zkey;
        wrapText(t1, ZONE_W, 3, M.line13);
        let x = LX, yy = keyTop + t1.querySelectorAll("tspan").length * M.line13 + 4;
        for (const { sw, t, dia } of items) {
          const w = 17 + tw(t) + 12;
          if (x > LX && x + w > LX + ZONE_W) { x = LX; yy += M.line13 + 2; }
          if (dia) sw.setAttribute("d", `M${x + 5},${yy - 6} L${x + 11},${yy} L${x + 5},${yy + 6} L${x - 1},${yy} Z`);
          else { sw.setAttribute("x", x); sw.setAttribute("y", yy - 3); }
          t.setAttribute("x", x + 17);
          t.setAttribute("y", yy + 4);
          x += w;
        }
        if (t3) {
          t3.setAttribute("y", yy + M.line13 + 8);
          wrapText(t3, ZONE_W, 3, M.line13);
        }
      }
    }
    // station labels, each at the spot that crosses the fewest tracks
    const boxes = Array.from(place.values(), (p) => ({ x: p.x - CAP_R - 1, y: p.top - 1,
      width: 2 * CAP_R + 2, height: p.bottom - p.top + 2 }));
    const segs = [];
    for (const route of routes.values()) {
      for (let i = 0; i < route.pts.length - 1; i += 1) segs.push([...route.pts[i], ...route.pts[i + 1]]);
    }
    const lineH = Math.max(15, 1.15 * Math.max(13, 12 / drawnS));
    for (const item of later) {
      if (!item.label) continue;
      const [t, p] = item.label;
      fitText(t, Math.max(180, 3 * pitchX));
      let best = null;
      labelSpots(p, lineH).forEach(([x, yy, anchor], i) => {
        t.setAttribute("x", x); t.setAttribute("y", yy); t.setAttribute("text-anchor", anchor);
        const box = safeBox(t);
        if (!box) return;
        const pad = { x: box.x - 2, y: box.y - 1, width: box.width + 4, height: box.height + 2 };
        let score = i;
        score += 12 * segs.filter((sg) => segHits(sg, pad)).length;
        score += 1000 * [...boxes, ...placed].filter((b) => overlaps(b, pad)).length;
        if (pad.x < ZONE_R + 6 || pad.x + pad.width > BX - 4 || pad.y < 30) score += 1000;
        if (!best || score < best.score) best = { score, x, yy, anchor, box: pad };
      });
      if (best) {
        t.setAttribute("x", best.x); t.setAttribute("y", best.yy); t.setAttribute("text-anchor", best.anchor);
        placed.push(best.box);
      }
    }
    for (const item of later) {
      if (!item.fit) continue;
      const [t, room] = item.fit;
      let width = room;
      if (item.before) {
        const used = tw(item.before);
        width = Math.min(room, room - used - 16);
      }
      fitText(t, Math.max(24, width));
      if (item.nudge) {
        // move up one line, at most twice, to clear an earlier label
        t.setAttribute("y", t.dataset.y0 || t.getAttribute("y"));
        t.dataset.y0 = t.getAttribute("y");
        for (let k = 0; k < 2; k += 1) {
          const box = safeBox(t);
          if (!box || !placed.some((b) => overlaps(b, box))) break;
          t.setAttribute("y", Number(t.getAttribute("y")) - 15);
        }
        const box = safeBox(t);
        if (box) placed.push(box);
      }
    }
  }
  const safeBox = (t) => { try { return t.getBBox(); } catch (err) { return null; } };
  /** Whether the segment [x1, y1, x2, y2] meets the box (Liang-Barsky). */
  const segHits = ([x1, y1, x2, y2], b) => {
    let t0 = 0, t1 = 1;
    const dx = x2 - x1, dy = y2 - y1;
    for (const [pp, q] of [[-dx, x1 - b.x], [dx, b.x + b.width - x1], [-dy, y1 - b.y], [dy, b.y + b.height - y1]]) {
      if (pp === 0) { if (q < 0) return false; continue; }
      const r = q / pp;
      if (pp < 0) { if (r > t1) return false; if (r > t0) t0 = r; } else { if (r < t0) return false; if (r < t1) t1 = r; }
    }
    return true;
  };
  const overlaps = (a, b) => a.x < b.x + b.width && b.x < a.x + a.width
    && a.y < b.y + b.height && b.y < a.y + a.height;

  // ------------------------------------------------------------------ highlight
  // What a hover lights: lines (by claim), the lines they rest on (in their own
  // colour), feeds (by zone and target), zones. Everything else dims.
  let pinned = null;               // the selection the drawer shows

  function light(keys, secondary = new Set(), feedOn = null, zonesOn = null, stationsOn = null) {
    root.classList.add("hlon");
    for (const node of root.querySelectorAll("[data-c]")) {
      const key = node.getAttribute("data-c");
      node.classList.toggle("hl", keys.has(key));
      node.classList.toggle("hl2", !keys.has(key) && secondary.has(key));
      node.classList.toggle("dim", !keys.has(key) && !secondary.has(key));
    }
    for (const g of [...capEls, ...headerEls.values()]) {
      const members = (g.dataset.claims || "").split(" ").filter(Boolean);
      const on = members.some((key) => keys.has(key)) || !!(stationsOn && stationsOn.has(g.dataset.node));
      g.classList.toggle("hl", on);
      g.classList.toggle("dim", !on);
    }
    for (const t of labelEls) {
      const members = (t.dataset.claims || "").split(" ").filter(Boolean);
      t.classList.toggle("dim", !members.some((key) => keys.has(key))
        && !(stationsOn && stationsOn.has(t.dataset.node)));
    }
    const zonesLit = zonesOn || new Set([
      ...lines.filter((l) => keys.has(l.claim)).flatMap((l) => l.fed_by || []),
      ...zones.filter((z) => (z.estimate || []).some((id) => keys.has(id))).map((z) => z.id)]);
    for (const [zid, g] of zoneEls) {
      g.classList.toggle("hl", zonesLit.has(zid));
      g.classList.toggle("dim", !zonesLit.has(zid));
    }
    const on = feedOn || ((p) => (p.dataset.tap ? keys.has(p.dataset.tap)
      : (p.dataset.est || "").split(" ").some((id) => keys.has(id))
        || lines.some((l) => keys.has(l.claim) && (l.stops || []).includes(p.dataset.to)
          && (l.fed_by || []).includes(p.dataset.zone))));
    for (const p of feedEls) p.classList.toggle("on", !!on(p));
  }

  function clearHighlight() {
    root.classList.remove("hlon");
    for (const node of root.querySelectorAll(".hl, .hl2, .dim, .on")) {
      node.classList.remove("hl", "hl2", "dim", "on");
    }
  }

  function lineSet(key) {
    if (restedBy.has(key)) return assumptionSet(key);
    const keys = new Set([key]);
    const rests = new Set((restsOn[`claim:${key}`] || []).map((id) => id.replace(/^claim:/, "")));
    return [keys, rests];
  }
  function stationSet(node) {
    const p = place.get(node.id);
    return [new Set(p ? p.keys : (node.claims || [])), new Set(),
      (f) => !f.dataset.tap && f.dataset.to === node.id, new Set(node.fed_by || [])];
  }
  function zoneSet(z) {
    const keys = new Set(lines.filter((l) => (l.fed_by || []).includes(z.id)).map((l) => l.claim));
    return [keys, new Set(), (f) => f.dataset.zone === z.id, new Set([z.id])];
  }
  function assumptionSet(id) {
    // the assumption, every claim resting on it (their lines carry their own
    // amber band where it flips them), the feeds it sets and the stations
    // those feeds enter
    const ests = feedEls.filter((f) => (f.dataset.est || "").split(" ").includes(id));
    const zs = new Set(ests.map((f) => f.dataset.zone));
    const keys = new Set([id, ...(restedBy.get(id) || [])]);
    const stationsOn = new Set([...ests.map((f) => f.dataset.to), ...((lineOf.get(id) || {}).sets || [])]);
    return [keys, new Set(), (f) => ests.includes(f), zs, stationsOn];
  }

  function restore() {
    if (pinned) light(...pinned);
    else clearHighlight();
  }

  function bindTarget(target, set, open) {
    target.addEventListener("mouseenter", () => light(...set()));
    target.addEventListener("mouseleave", restore);
    target.addEventListener("focus", () => light(...set()));
    target.addEventListener("blur", restore);
    target.addEventListener("click", (ev) => { ev.stopPropagation(); open(); });
    target.addEventListener("keydown", (ev) => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); ev.stopPropagation(); open(); }
    });
  }
  function bindLine(target, key) {
    bindTarget(target, () => lineSet(key), () => onSelect && onSelect("claim", key));
  }
  function bindNode(g, node, keys) {
    bindTarget(g, () => [keys, new Set()], () => onSelect && onSelect(node.kind, node.key));
  }
  function bindStation(g, node) {
    bindTarget(g, () => stationSet(node), () => onSelect && onSelect("station", node.key));
  }
  function bindZone(g, z) {
    bindTarget(g, () => zoneSet(z), () => onSelect && onSelect("zone", z.key));
  }
  function bindAssumption(chip, id) {
    bindTarget(chip, () => assumptionSet(id),
      () => onSelect && (claimNode.has(id) ? onSelect("claim", id) : null));
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
    /** Keep one claim's line (or a node's lines) lit while the drawer shows it. */
    select(kind, key) {
      if (kind === "claim") pinned = lineSet(key);
      else if (kind === "station" && byId.has(`station:${key}`)) pinned = stationSet(byId.get(`station:${key}`));
      else if (kind === "zone" && byId.has(`zone:${key}`)) pinned = zoneSet(byId.get(`zone:${key}`));
      else {
        const node = byId.get(`${kind}:${key}`);
        pinned = node ? [new Set(node.claims || []), new Set()] : null;
      }
      restore();
    },
    /** Light every line whose token is one of ``tokens`` (the legend), or
     *  whose marks hold ``mark``. */
    showTokens(tokens, mark = "") {
      if (!tokens && !mark) { restore(); return; }
      const keys = new Set(lines.filter((l) => (tokens && tokens.has(l.errored ? "errored" : l.token))
        || (mark && (l.marks || []).includes(mark))).map((l) => l.claim));
      light(keys);
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
 *  statement, the value, the stations each line rides and the zones that feed
 *  it, and amber when the bake marks it. */
export function mapList(map, page, { onSelect, onBoard } = {}) {
  const words = (page && page.words) || {};
  const traceWords = words.trace || {};
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
  const amberNote = (node, line) => ((node.marks || []).includes("amber") && line.amber && line.amber.word
    ? el("span", { class: "ml-amber" }, el("span", { class: "ml-dia", "aria-hidden": "true", text: "◆" }),
        el("span", { text: ` ${line.amber.word}` }))
    : null);
  const titles = (ids) => (ids || []).map((id) => byId.get(id)).filter(Boolean).map((n) => n.title || n.key);
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
        // what its evaluators read, and, apart, what the test only puts
        // before them (review of phase 3b: the phone list named both as rides)
        const stationStops = (line.stops || []).filter((id) => (byId.get(id) || {}).kind === "station");
        const rides = titles(stationStops.filter((id) => (line.stop_kind || {})[id] !== "upstream"));
        const before = titles(stationStops.filter((id) => (line.stop_kind || {})[id] === "upstream"));
        const sets = titles(line.sets || []);
        const fed = titles(line.fed_by);
        const detail = node.value_text || ((claimRows[key] || {}).cause_text) || "";
        return el("li", {},
          el("button", { class: "ml-row", type: "button", onclick: () => onSelect && onSelect("claim", key) },
            el("span", { class: "ml-top" }, chip(node), el("b", { class: "mono", text: ` ${key} ` }),
              (line.serves || []).length ? el("span", { class: "ml-req-tag mono", text: line.serves.join(", ") }) : null),
            el("span", { class: "ml-stmt", text: node.title }),
            detail ? el("span", { class: "ml-val", text: detail }) : null,
            markNote(node),
            amberNote(node, line),
            rides.length ? el("span", { class: "ml-reads" },
              el("b", { text: `${traceWords.rides || "Rides"}: ` }), rides.join(" → ")) : null,
            before.length && traceWords.upstream_rides ? el("span", { class: "ml-reads ml-up" },
              el("b", { text: `${traceWords.upstream_rides}: ` }), before.join(" → ")) : null,
            sets.length ? el("span", { class: "ml-reads" },
              el("b", { text: "◆ " }), sets.join(", ")) : null,
            line.unseen && traceWords.unseen_line ? el("span", { class: "ml-reads", text: traceWords.unseen_line }) : null,
            fed.length ? el("span", { class: "ml-reads" },
              el("b", { text: `${traceWords.fed_by || "Fed by"}: ` }), fed.join(", ")) : null));
      }))));
  }
  return out;
}
