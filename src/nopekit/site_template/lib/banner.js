// SPDX-License-Identifier: Apache-2.0
// banner.js: what `data/build.json` says on both pages. A failed rebuild in a
// banner at the top, and the time of the build in the footer.
//
// A failed build keeps the last data on the page, so the banner is what says
// that the page is behind the records: a page that showed the old verdict with
// no word of the failure would show a pass the design no longer earns. The
// banner's words are the bake's (`words.notices.build_failed`), the failure's
// text is the build's last line, and the time is build.json's (the clock
// lives there alone, SPEC 32). It was page.js's own until the marketing page
// came, and a second copy is a second place for the banner to go quiet.

import { el, mount, $ } from "./dom.js";
import { stamp } from "./format.js";

/** Fill `#build-banner` and `#built` from ``build`` (or null). */
export function paintBuild(build, words) {
  const notices = (words && words.notices) || {};
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
