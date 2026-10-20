// SPDX-License-Identifier: Apache-2.0
// theme.js: the page chrome both pages share. The theme button (a reader's
// choice of dark or light, kept under one storage key for every page of the
// site) and the project's name in the page menu.
//
// It was page.js's own until the marketing page came: two copies of a
// fifteen-line function drift, and a theme chosen on one page then did not
// hold on the other. The key stays `nopekit-theme`, so a choice made before
// the two pages still holds.

import { $, mount } from "./dom.js";

/** The storage key of the reader's theme. *Rejected:* one key for each page
 *  (a reader who chose dark on one page got light on the next). */
export const THEME_KEY = "nopekit-theme";

/** Apply the saved theme and wire the button, wherever it sits: in the page
 *  menu, or fixed at the top right on a front page from before the two pages.
 *  A private window that refuses storage gets the system theme. */
export function themeButton() {
  const button = $("#themebtn");
  let saved = null;
  try { saved = window.localStorage.getItem(THEME_KEY); } catch (err) { saved = null; }
  if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  if (!button) return;
  button.addEventListener("click", () => {
    const dark = document.documentElement.dataset.theme
      ? document.documentElement.dataset.theme === "dark"
      : window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = dark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { window.localStorage.setItem(THEME_KEY, next); } catch (err) { /* private window */ }
  });
}

/** The project's name in the page menu (`#viewnav-name`), from `meta.name`.
 *  A shell with no menu (a front page from before the two pages) is left as
 *  it is. */
export function menuName(meta) {
  const host = $("#viewnav-name");
  if (host && meta && meta.name) mount(host, meta.name);
}
