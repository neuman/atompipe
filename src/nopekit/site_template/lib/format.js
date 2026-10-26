// SPDX-License-Identifier: Apache-2.0
// format.js — how the ledger's vocabulary is spoken on the page.
//
// Nothing here decides anything. Every status on this page arrives already
// resolved in state.json (nopekit.claims resolves claims, nopekit.report
// writes the readiness sentence); this module only chooses the word, the glyph
// and the class name for a status the ledger already reached. The moment a
// function in here starts inferring a status from a measurement, the page has a
// second opinion about the project and the reader has no way to tell which of
// the two is the real one.
//
// EVERY STATUS CARRIES A GLYPH AND A WORD, never a colour alone. Colour is the
// third channel, not the first: a reader with a colour vision deficiency, a
// greyscale print of the readiness page, and a photograph of a laptop screen in
// a workshop all have to survive the distinction between "failing" and "proven",
// and two shades of a traffic light do not survive any of them.

import { el } from "./dom.js";

/** Claim statuses, as ClaimStatus in nopekit.models: the glyph and the tone
 *  of each enum value, and NOTHING it says. The word and its hint arrive in
 *  state.json's `words` (nopekit.report.HUMAN, GLOSSARY §3) through
 *  `useWords`, because a status word is truth and the site never owns one
 *  (PLAN D-16). What slipped through before P2.1: this table held its own
 *  labels — PROVEN, NO GATE, BLOCKED, NOT RUN, UNVERIFIED — a third
 *  vocabulary beside the terminal's tags and the report's headings, and the
 *  words a reader quoted from the page were none of the paper's.
 *
 *  A claim Skipped by a crash takes Failing's tone (`errored`, invariant 2): a
 *  crash reads louder than a missing tool on the page as on the terminal.
 *  Unknown values fall back to a neutral chip that prints the raw string — a
 *  newer spine inventing a status must not blank out a claim row on an older
 *  page. */
const CLAIM_STATUS = {
  pass:       { glyph: "✓", tone: "ok" },
  fail:       { glyph: "✕", tone: "bad" },
  stale:      { glyph: "≈", tone: "warn" },
  unclaimed:  { glyph: "?", tone: "warn" },
  blocked:    { glyph: "⊘", tone: "warn" },
  pending:    { glyph: "◌", tone: "warn" },
  unverified: { glyph: "◻", tone: "phys" },
  verified:   { glyph: "✓", tone: "ok" },
  refuted:    { glyph: "✕", tone: "bad" },
  asserted:   { glyph: "≡", tone: "assum" },
};

/** The words state.json carries, keyed by enum value (and `errored`). Set once
 *  by app.js from `state.words`; empty until then, when a chip prints the raw
 *  value rather than a word the page invented. */
let WORDS = {};

/** The ledger's other words the page prints — `invalidated`, each gap
 *  record's state, each verdict chip's title — from state.json's `phrases`
 *  (nopekit.report.page_phrases). What slipped through P2.1: the page held
 *  them itself, `≈ STALE` on the top bar over a project where no claim read
 *  Stale, its own "identified", and its own outcome hints. */
let PHRASES = {};

export function useWords(words, outcomes, phrases) {
  WORDS = words || {};
  OUTCOME_WORDS = outcomes || {};
  PHRASES = phrases || {};
}

/** `invalidated`, from state.json; the raw key until a state that has it. */
export function phrase(key) {
  const said = PHRASES[key];
  return typeof said === "string" && said ? said : String(key);
}

/** A gap record's state in its word (`identified` for `open`, and for a record
 *  that names none), from state.json; the raw state until a state that has it. */
export function needWord(status) {
  const need = PHRASES.need || {};
  return need[status] || (status ? String(status) : need.open || "");
}

/** Verdict statuses, as written by site.state(): pass | fail | skipped | errored
 *  | unqualified | outside-context. `skipped` and `errored` are deliberately NOT
 *  neutral greys — a gate whose solver is missing proved nothing, and an errored
 *  gate reads louder still, because a crash is a defect in the check itself.
 *  `unqualified` takes Gap's glyph and tone (P2.3): its claim reads Gap, and it
 *  crashed nothing. `outside-context` too (P2.4): a pass outside the inputs its
 *  evaluator was qualified on — its claim reads Gap, its evaluator is still
 *  qualified, and the word is state.json's, never UNQUALIFIED (review of P2.4).
 *
 *  A recorded result's `token` (`report.RESULT_TOKENS`) reads here too, on both
 *  pages: `pass` a pass that counts, `fail` a fail that counts (Failing's tone),
 *  `not-counted` muted, never a pass's look. This is the one place a recorded
 *  result's tone is said. What slipped through (follow-up after phase 3b): the
 *  drawer coloured the block on `counts` alone, so a counted fail read green
 *  beside its Failing chip, and the technical record kept a rule of its own. */
const VERDICT_STATUS = {
  pass:    { glyph: "✓", tone: "ok" },
  fail:    { glyph: "✕", tone: "bad" },
  skipped: { glyph: "⊘", tone: "warn" },
  errored: { glyph: "!", tone: "bad" },
  unqualified: { glyph: "?", tone: "warn" },
  "outside-context": { glyph: "?", tone: "warn" },
  "not-counted": { glyph: "◌", tone: "muted" },
};

/** Each verdict row's outcome word, from state.json's `outcome_words`
 *  (nopekit.report.HUMAN, GLOSSARY §1) — set with the status words. */
let OUTCOME_WORDS = {};

// GLOSSARY §9's group words. What slipped through: "the only kind a machine
// proves" and "taken on faith", a Never-say each, on the page alone after every
// other channel had moved.
const CLAIM_KIND = {
  measurable: {
    title: "Automated",
    blurb: "An automated evaluator settles these claims from the model.",
  },
  physical: {
    title: "Physical",
    blurb: "Only a test on a built part settles these claims. They stay on this " +
           "list until a person records a result.",
  },
  // No status word in a blurb: each row's chip and reason say what it reads
  // (review of P2.1: "An assumption nobody owns is a gap." — a status word the
  // page owned, and a scan of `label:`/`text:` values could not see a blurb).
  assumption: {
    title: "Assumptions",
    blurb: "A person accepts each of these for now, with a reason. " +
           "Each row says whether its owner has recorded it.",
  },
};

/** An outcome's word (`pass`, `fail`, …) from state.json's `outcome_words`;
 *  the raw key until a state that has it. */
export function outcomeWord(key) {
  return String(OUTCOME_WORDS[key] || key);
}

/** A claim row's chip: the glyph and tone for its enum value (Failing's tone
 *  when `errored`), the word and hint from state.json's `words`. */
export function claimStatus(key, { errored = false } = {}) {
  const look = CLAIM_STATUS[key];
  const said = (errored && WORDS.errored) || WORDS[key] || {};
  if (!look) {
    return { label: String(key || "unknown").toUpperCase(), glyph: "·", tone: "muted", hint: "" };
  }
  return {
    label: String(said.term || key).toUpperCase(),
    glyph: look.glyph,
    tone: errored ? "bad" : look.tone,
    hint: said.hint || "",
  };
}

/** A verdict row's chip: the glyph and tone for its outcome; the word from
 *  state.json's `outcome_words` and the hint from its `phrases.outcome_hint`
 *  (review of P2.1: the hints were the page's own words). */
export function verdictStatus(key) {
  const look = VERDICT_STATUS[key];
  if (!look) return { label: String(key || "unknown").toUpperCase(), glyph: "·", tone: "muted", hint: "" };
  return { ...look, label: String(OUTCOME_WORDS[key] || key).toUpperCase(),
           hint: String((PHRASES.outcome_hint || {})[key] || "") };
}

/** A baked outcome's look (`pass`, `fail`, `errored`, `skipped`,
 *  `unqualified`, `outside-context`, and `unrun` for an evaluator with no
 *  result; a recorded result's `token`): the verdict table's glyph and tone.
 *  The word is always the baked one (`outcome_word`, a result's `word`). */
export function outcomeLook(key) {
  return VERDICT_STATUS[key] || { glyph: "◌", tone: "dim" };
}

/** A bound figure's currency (issue #15, `page.FIGURE_CURRENCIES`): its glyph,
 *  its tone and whether its card says it at the top, keyed by the bake's word.
 *  The spine decides which word a figure carries; this table only says how
 *  each word looks, as TOKEN_LOOK does for a claim's token. A picture of
 *  another result, or of a result that is not current, takes Stale's glyph
 *  and a dashed frame (page.css), so it never looks like the result beside it.
 *  An unknown word gets the neutral look and its notice, never the current
 *  look. */
const CURRENCY_LOOK = {
  current: { glyph: "✓", tone: "ok",    notice: false },
  stale:   { glyph: "≈", tone: "dim",   notice: true },
  unseen:  { glyph: "≈", tone: "dim",   notice: true },
  older:   { glyph: "≈", tone: "warn",  notice: true },
  none:    { glyph: "◌", tone: "muted", notice: false },
};

export function currencyLook(key) {
  return CURRENCY_LOOK[key] || { glyph: "◌", tone: "dim", notice: true };
}

export function claimKind(key) {
  return CLAIM_KIND[key] || { title: String(key || "other"), blurb: "" };
}

/** The status chip. Glyph, then word, then colour — in that order of importance. */
export function chip(status, { small = false, title = "" } = {}) {
  return el("span", { class: `chip tone-${status.tone}${small ? " chip-sm" : ""}`, title: title || status.hint },
    el("span", { class: "chip-glyph", "aria-hidden": "true", text: status.glyph }),
    el("span", { class: "chip-label", text: status.label }));
}

// --------------------------------------------------------------------------- //
// the front page's tokens (architecture phase 5)
// --------------------------------------------------------------------------- //

/** How each claim status TOKEN looks on the front page and the map: its glyph,
 *  its tone and the stroke of its line. One table for the chip, the legend, the
 *  board header and the line, so a token cannot read one way on the map and
 *  another in its section. The tokens are `claims.STATUS_KEY`'s (and `errored`),
 *  exactly as `map.json` and `page.json` bake them; the WORD beside each glyph is
 *  always the baked `word`, never a string from this file (D-16).
 *
 *  Strokes, after the author's map (SPEC 29): a pass is a solid line, a fail a
 *  heavier solid red one, a crash a heavy dashed red one (louder than a missing
 *  tool, invariant 2), a result older than the design a dashed one, and every
 *  status that nothing has settled yet a dotted one. Amber is a MARK beside the
 *  token (`marks`), drawn as a casing under the line; it is never a token here.
 *
 *  An unknown token, from a newer spine, gets a neutral dot and prints the raw
 *  token as its word. It never borrows a pass's look. What slipped through in
 *  the reference map: its own vocabulary (GO, NO-GO, WAITING) beside the
 *  paper's, and no look at all for a crash or a skipped evaluator. */
export const TOKEN_LOOK = {
  checked:       { glyph: "✓", tone: "ok",    stroke: "solid" },
  failing:       { glyph: "✕", tone: "bad",   stroke: "heavy" },
  errored:       { glyph: "!", tone: "bad",   stroke: "crash" },
  stale:         { glyph: "≈", tone: "dim",   stroke: "dashed" },
  skipped:       { glyph: "⊘", tone: "warn",  stroke: "dotted" },
  gap:           { glyph: "?", tone: "warn",  stroke: "dotted" },
  open:          { glyph: "◌", tone: "warn",  stroke: "dotted" },
  pending_build: { glyph: "◻", tone: "phys",  stroke: "dotted" },
  assumed:       { glyph: "≡", tone: "assum", stroke: "dotted" },
};

/** The readiness tokens (`verdict.token`, a step group's `token`): ready reads
 *  as a pass, every other value as not ready. */
const READY_LOOK = {
  "ready":     { glyph: "✓", tone: "ok" },
  "not-ready": { glyph: "✕", tone: "bad" },
};

const UNKNOWN_LOOK = { glyph: "·", tone: "muted", stroke: "dotted", unknown: true };

/** The look of a baked token. `errored` wins: a crash takes its own look
 *  whatever word the status carries. */
export function lookOf(token, { errored = false } = {}) {
  if (errored) return TOKEN_LOOK.errored;
  return TOKEN_LOOK[token] || READY_LOOK[token] || UNKNOWN_LOOK;
}

/** A baked token's chip: glyph, then the baked word, then the colour. The word
 *  is the raw token when the bake gave none, so a newer token never blanks.
 *  ``marks`` are the bake's marks beside the token (`disagree`): each shows as
 *  a "!" in the chip, with ``notices.disagree`` as its label, so a claim whose
 *  status and evidence disagree never reads as a plain chip. Every caller that
 *  draws a token passes its marks (`test_site_truth` reads the calls). What
 *  slipped through (review of phase 5): the phone list and a board's heading
 *  drew a disagreeing claim as a plain green chip.
 *
 *  ``amber`` (a Checked pass that a ±10% move of an unconfirmed assumption's
 *  choice flips) shows as a "◆" in the chip, the map's amber diamond, with
 *  ``trace.amber_flips`` (the bake's `words.trace`, the word the map's own
 *  amber note reads, `amber_word("flips")`) as its label. It sits beside the
 *  status and never replaces it: the word and the tone stay the token's
 *  (invariant 12). Every caller passes ``trace`` beside ``notices``. What
 *  slipped through (review of SPEC 40): this chip drew `disagree` alone, so on
 *  the marketing page, which has no map and no drawer, a requirement or a
 *  decision's claim whose pass the trace flips read as a plain green chip, the
 *  same as a pass at 80% margin: phase 3b's slip again, on the page that
 *  persuades. A row that stands for several claims (a requirement, a board)
 *  passes ``group``: its amber is one of its claims' (`page._group_marks`), so
 *  its label is ``trace.amber_group``, never the claim's "This pass…" beside a
 *  group that fails (review of SPEC 40). */
export function tokenChip(token, word, { errored = false, small = false, title = "", marks = [], notices = {},
  trace = {}, group = false } = {}) {
  const look = lookOf(token, { errored });
  const disagree = (marks || []).includes("disagree");
  const amber = (marks || []).includes("amber");
  const label = (notices && notices.disagree) || "";
  const amberLabel = (trace && (group ? trace.amber_group : trace.amber_flips)) || "";
  return el("span", {
    class: `nk-chip tone-${look.tone}${small ? " nk-chip-sm" : ""}${disagree ? " has-mark" : ""}` +
      `${amber ? " has-amber" : ""}`,
    title: title || [disagree ? label : "", amber ? amberLabel : ""].filter(Boolean).join(" ") || null,
  },
    el("span", { class: "nk-glyph", "aria-hidden": "true", text: look.glyph }),
    el("span", { class: "nk-word", text: String(word || token || "") }),
    disagree ? el("span", { class: "nk-mark", role: "img", "aria-label": label || null, text: "!" }) : null,
    amber ? el("span", { class: "nk-amber", role: "img", "aria-label": amberLabel || null, text: "◆" }) : null);
}

/** A plain labelled tag with no status semantics (tier, pack, kind, count). */
export function tag(text, { tone = "muted", title = "" } = {}) {
  return el("span", { class: `tag tone-${tone}`, title, text });
}

// --------------------------------------------------------------------------- //
// numbers and time
// --------------------------------------------------------------------------- //

/** Four significant figures, trailing zeros stripped, never exponent soup for
 *  ordinary engineering magnitudes. A deflection of 0.7000000000000001 mm is the
 *  same measurement as 0.7 mm and one of the two spellings makes a reader
 *  distrust the page. */
export function num(value, { digits = 4 } = {}) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  if (n === 0) return "0";
  const magnitude = Math.abs(n);
  if (magnitude >= 1e6 || magnitude < 1e-4) return n.toExponential(2).replace("e", "e");
  return String(Number(n.toPrecision(digits)));
}

export function quantity(value, units) {
  const text = num(value);
  if (!text) return "";
  return units ? `${text} ${units}` : text;
}

/** Human age from seconds. `null` is NOT zero — site.state() dates a verdict
 *  from the run that last wrote or hit its entry, else the commit that brought
 *  it, and writes a null age when it knows neither; a zero renders as "just
 *  now", which is the exact lie a staleness display exists to prevent. */
export function age(seconds) {
  if (seconds === null || seconds === undefined) return "age unknown";
  const s = Math.max(0, Number(seconds) || 0);
  if (s < 90) return `${Math.round(s)}s ago`;
  const m = s / 60;
  if (m < 90) return `${Math.round(m)}m ago`;
  const h = m / 60;
  if (h < 36) return `${Math.round(h)}h ago`;
  const d = h / 24;
  if (d < 14) return `${Math.round(d)}d ago`;
  const w = d / 7;
  if (w < 9) return `${Math.round(w)}w ago`;
  return `${Math.round(d / 30)} months ago`;
}

/** ISO timestamp -> a local, readable stamp with the raw value on hover.
 *  Unparseable input is printed verbatim rather than swallowed: a malformed
 *  timestamp in the ledger is a thing to see, not to hide. */
export function stamp(iso) {
  const raw = String(iso || "").trim();
  if (!raw) return "";
  const date = new Date(raw.replace(" ", "T"));
  if (Number.isNaN(date.getTime())) return raw;
  return date.toLocaleString(undefined, {
    year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
  });
}

export function plural(n, one, many) {
  return `${n} ${n === 1 ? one : (many || one + "s")}`;
}

/** A gate id, a node name, a parameter: rendered monospace so an identifier is
 *  never mistaken for prose, and copyable as one word. */
export function code(text, extra = "") {
  return el("code", { class: `mono ${extra}`.trim(), text: String(text) });
}
