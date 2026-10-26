# Open work (stopped 2026-10-26)

Work on this pack stopped here by the author's decision. This file lists what is
not done and what is known to be wrong or slow, so the next person starts from
facts, not from memory. Each item says where to start.

## The motorbike demo (`examples/motorbike`)

- **C7 fails, and the reason is not settled.** On 2026-10-25 the ladder gave a
  drag area of 0.29925, 0.29625 and 0.30206 m^2 on 358654, 926215 and 2674337
  cells. The finest level did not settle in 500 iterations: U_I 1.98% of its
  drag area, past the 1% limit. The change between the two finest meshes
  (0.00581 m^2) is smaller than that U_I (0.00598 m^2), so the gate stopped
  before it compared the three meshes. The down-then-up order is therefore not
  shown to be real.
  - Start here: give the finer levels more iterations (an iteration budget per
    level, or `endTime` scaled with the level), then run the ladder again
    (about 1 h on 6 ranks). If the order stays down-then-up, try another ratio
    or a fourth level.
- **C1 is skipped** until C7 passes. All three meshes give about 0.30 m^2,
  under the 0.35 m^2 limit, but no gate has judged it with its error band.
- **A1 and A2 are gaps** until their owner records them in their own shell
  (`nopekit claim physical A1 assume`, `nopekit claim physical A2 assume
  --authority "<name>"`).
- **Five guard claims read Stale right after a full check.** The cause is
  `unseen` (the gates read inputs nopekit cannot see, invariant 12). This is
  correct, but a reader of the page sees "5 stale" beside a run that just
  passed. A clearer word on the page would help.
- **A fresh clone has no live 3D file.** The page's "Turn it in 3D" needs a
  local `nopekit site build`, which needs the check's out directory. The
  evidence logs and the figures are committed; the glTF is not.
- **The mesh fix is one setting:** `addLayersControls minThickness 0.2` (was
  0.1) in `case/system/snappyHexMeshDict`. With 0.1 the finest level had 5 faces
  in error from layer addition. The trials are in commit 6f6b411's message.

## The run store (design phase P9): not merged

- Work in progress is on the local branch `aero-run-store-wip`, one commit on
  top of `aero`. It is not reviewed, and its test run was stopped before it
  ended. Do not merge it as it is.
- It edits the spine (`src/nopekit/verdicts.py`, `src/nopekit/gates.py`), so a
  merge must regenerate the bracket's cache and run `nopekit round` in
  `examples/bracket` (tests/test_bracket_cache.py names the commands).
- The same branch holds a partial docs pass (design phase P10): SPINE_CONTRACT,
  SPEC, PACK_FORMAT, the skills, the README and a gallery image. It is not
  reviewed.
- Without the run store, every `check --tier 2` of the demo solves again: about
  63 min on 6 ranks (the ladder about 54 min of it).

## Tests that are slow where OpenFOAM is installed

- `tests.fast` takes about 25 min, not its 90 s budget, because test_packs runs
  this pack's baseline on the real tools. A stand-in for the fast tier would
  bring it back under budget.
- `test_mutation.TheWalkFindsNoConclusivePassOnBundledGates` walks the four
  SOLVE-tier gates over a few named parameters only (`SLOW_WALK`). It takes
  about 1 h 50 min. The full walk took 9.7 h; it passed once, on 2026-10-24.
- A full suite with the tools present takes many hours. Run the slow modules one
  at a time; run in parallel, they fail on timing.
