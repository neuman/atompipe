// SPDX-License-Identifier: Apache-2.0
// live.js: the page follows `nopekit site serve --watch` (architecture phase 5,
// SPEC 33).
//
// `site build` writes `data/build.json` last: the build time, an `id` over the
// tracked baked bytes, whether the build is live, and whether it worked. The
// page reads it once at load. While the last read says `live: true` and the
// page is visible, it reads it again every two seconds; when the `id` moves,
// the caller fetches the data again and draws it in place. A failed build keeps
// the last data and says so. A 404 or `live: false` stops the polling, so a
// published page needs only its static files and never polls a server that is
// not there.
//
// The clock lives in build.json alone (SPEC 32): the tracked files never change
// on a rebuild that judged nothing new, so nothing here can read a fresh `id`
// as fresh results. (What slipped through before build.json: every build
// stamped `state.json` with its time, and `git status` was never clean.)

/** The poll interval. Two seconds: the watcher debounces over two of its own
 *  one-second polls, so a faster page would only ask more often for the same
 *  file. *Rejected:* a server push (the page must work from static files). */
export const POLL_MS = 2000;

/** Read data/build.json; null when it is not there or does not parse. */
export async function readBuild() {
  try {
    const res = await fetch("data/build.json", { cache: "no-store" });
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    return null;
  }
}

/** Follow build.json. ``onBuild(build)`` runs on every read (and with null
 *  when there is none); ``onNewId(build)`` runs when the id moves on a build
 *  that worked. Returns ``{stop}``. */
export function watchBuild(onNewId, onBuild, first = undefined) {
  let last = null;
  let timer = 0;
  let stopped = false;

  async function tick() {
    timer = 0;
    if (stopped) return;
    const build = await readBuild();
    if (onBuild) onBuild(build);
    if (!build || build.live !== true) return;          // published, or gone: stop
    if (last && build.ok !== false && build.id && build.id !== last.id && onNewId) {
      await onNewId(build);
    }
    if (build.ok !== false) last = build;
    schedule();
  }

  function schedule() {
    if (stopped || timer) return;
    if (document.visibilityState === "hidden") return;  // resumes on visibilitychange
    timer = setTimeout(tick, POLL_MS);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && last && last.live) schedule();
  });

  if (first !== undefined) {
    last = first;
    if (first && first.live === true) schedule();
  } else {
    tick();
  }
  return { stop() { stopped = true; if (timer) clearTimeout(timer); } };
}
