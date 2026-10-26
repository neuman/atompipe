# The selftest on the real tools

`nopekit gate selftest --pack aero-openfoam --junit <file>.xml` on ESI OpenFOAM
v2606 and Open MPI 4.1.6, the baseline spheroid on 4 ranks
(`selftest/baseline.json`). Every gate's known-good control must pass and its
known-bad control must fail, each for its own reason. The JUnit file of this
run is the pack's admission evidence.

## The run (P6, 2026-10-23)

```
aero-openfoam (bundled) : 9 qualified
aero.case_readable : known-good pass · known-bad fail → qualified
aero.reference : known-good pass · known-bad fail → qualified
aero.regime : known-good pass · known-bad fail → qualified
aero.domain : known-good pass · known-bad fail → qualified
aero.mesh_quality : known-good pass · known-bad fail → qualified
aero.converged : known-good pass · known-bad fail → qualified
aero.wall_treatment : known-good pass · known-bad fail → qualified
aero.mesh_independence : known-good pass · known-bad fail → qualified
aero.drag_area : known-good pass · known-bad fail → qualified
9 evaluators in 20m 13s: 9 qualified, 0 unqualified, 0 skipped
```

The JUnit file: two suites, `controls` and `baselines`, 9 cases each, 0
failures, 0 errors, 0 skipped (`exit_code` 0, 2026-10-24T04:59:49Z).

Wall time 1175 s (19 min 35 s, `/usr/bin/time`) on a 7-core machine that
nothing else was loading. Four ladders are most of it (next section).

## Where each control lands

| Gate | Known-bad | Its value | The limit | Why it fails |
|---|---|---|---|---|
| `aero.case_readable` | `coded_inlet` | no value | none | the inlet is a `codedFixedValue`: C++ the case would compile |
| `aero.reference` | `wrong_speed` | no value | none | the inlet at 23 m/s, `aero_u_inf_m_s` 20 |
| `aero.regime` | `thick_air` | Re 4.35e5 | >= 5e5 | the air 15% too viscous for turbulent wall layers |
| `aero.domain` | `short_wake` | 13.0 H downstream | >= 15 H | the outlet moved upstream |
| `aero.mesh_quality` | `cell_cap` | 27 332 cells | < 20 000 cap | snappyHexMesh stopped refining at the cap and still said it finished |
| `aero.converged` | `cut_short` | U_I 11.1% | <= 1% | endTime 110: the window closes in the start-up |
| `aero.wall_treatment` | `no_layers` | 35.58% of the area | >= 90% | no layers: y+ above 300 on 64.4% of the body (mean 360) |
| `aero.mesh_independence` | `narrow_ladder` | no value | none | ratio 1.3: effective ratios 1.237 and 1.308 from 41 574, 78 726 and 176 196 cells, under 1.3, judged before any solve |
| `aero.drag_area` | `bigger_body` | 0.00529625 m^2 | <= 0.0044 m^2 | every radius 1.125 times: 1.204 times past B1's limit |

`no_layers`, `bigger_body` and the drag gate's guards: `aero.wall_treatment`
passes `bigger_body` (100%), and `aero.mesh_independence` passes it (GCI
18.28% against the baseline's 20%), so the edges from `aero.drag_area` are
isolated (`tests/test_packs.ControlsAreIsolated`).

## The baseline

| Gate | Value | Limit |
|---|---|---|
| `aero.wall_treatment` | y+ <= 300 on 100% of 0.631382 m^2 (2 396 faces); mean y+ 121.15, OpenFOAM's 121.15 | >= 90% |
| `aero.mesh_independence` | GCI 15.67% (cells 41 574, 132 094, 386 302; CdA 0.00443257, 0.00384200, 0.00364309 m^2; observed p 2.712, so p = 2 with Fs 3) | <= 20% (the baseline's own) |
| `aero.drag_area` | 0.00364309 x 1.15674 + 8.2e-9 = 0.00421412 m^2 | <= 0.0044 m^2 (B1) |

B1's limit, 0.0044 m^2, sits 4.4% over the baseline's top and 16.9% under
the `bigger_body` control's (the control's is 20.4% over it) (`references/convergence.md` has the ladders).

## What it costs

- One spheroid ladder (three meshes and three solves of 300 iterations on 4
  ranks): about 3 min; the 1.125 times larger body's about 3 min 10 s.
- Four ladders a selftest: `aero.mesh_independence`'s known-good control;
  `aero.drag_area`'s known-good control (its own out directory, so its own
  solve); its four goalpost runs (one shared directory: the first solves, the
  next three read its record, `gates/aero.py`, `_Record`); and its known-bad
  control, the larger body. *Measured and rejected:* sharing records across out
  directories through a module dict halved this (574 s) and is a memo the
  spine cannot empty (`nopekit doctor`'s `memos` row).
- `narrow_ladder` meshes three levels and solves none (about 20 s).
- `no_layers` is one base-mesh solve (about 10 s).
- **No run store here.** `gate selftest` never reads `.nopekit/cache/runs/`
  (only a `check` that is not forced does, issue #15's P9), so this run, the
  pack's admission evidence, solves every control each time. In a project, the
  controls that `check` re-runs on the spheroid are served from the store from
  the second check on, and each one is named in a `note:` line (*its known-bad
  control reused: ...*). A control's stored run is keyed on its own staged
  copy: `cut_short`'s endTime 110 is another key than the baseline's 300
  (`tests/test_run_store.TheRunStoreKeyIsWhatTheSolverRead`).
