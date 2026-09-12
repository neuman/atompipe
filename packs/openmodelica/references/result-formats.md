# OpenModelica result formats

## `outputFormat="csv"` — what this pack reads

```
"time","tank.T","tank.qLoss","der(tank.T)"
0,293.15,0,0.01
1000,302.2133333333333,380.65999999999997,0.008187333333333335
...
25000,342.8130761054808,2085.8491964301934,6.7384778903841e-05
```

The rules, all of which the parser in `gates/_modelica.py` depends on:

- **The header row is quoted; the data rows are not.** Python's `csv` module
  handles both without being told, which is why this pack parses with `csv` and
  not with `str.split(",")`.
- **The first column is `time`.** A file whose first column is something else is
  not an OMC result table, and `modelica.solution_valid` says so rather than
  guessing.
- **One column per recorded variable**, in the order omc chose (roughly:
  states, then their derivatives, then algebraics, then parameters if they were
  not filtered out) — not the order they appear in the source. Never index a
  result file by column number.
- **Variables inside a component are dotted**: `tank.T` is `T` inside the
  component `tank`. Arrays are subscripted: `pipe.T[3]`. The dots and brackets
  are part of the name, not a path syntax.
- **Derivatives are spelled `der(x)`** — parentheses inside a column name. This
  breaks naive tooling that treats `(` as a delimiter, and it is why
  `modelica.solution_valid` looks for `der(` as a prefix when it needs to find
  every state derivative.
- **Numbers are repr-grade floats** — up to 17 significant digits, with `e`
  notation. A CSV round trip is not bit-exact, which is why the stopTime check
  has a tolerance rather than testing equality.
- **Parameters appear as constant columns.** A parameter that never changes is
  still a column with the same value in every row, which is convenient and also
  means the file is much wider than the dynamics require.

### Duplicate time points at events — the one that surprises people

A model with a state event writes **the same time value twice**, once with the
pre-event values and once with the post-event values:

```
"time","valve.open","tank.level"
3600,0,2.4
3600.000036010021,0,2.4000001
3600.000036010021,1,2.4000001
7200,1,2.1
```

That is correct and expected: an event is a discontinuity, and the only honest
way to record a discontinuous variable is a sample either side of it. The
consequences for anything reading the file:

- **The time column is non-DEcreasing, not strictly increasing.**
  `modelica.solution_valid` checks for non-decreasing on purpose; a gate
  demanding strict monotonicity fails every model with a switch in it.
- **Interpolating at a time that coincides with an event is ambiguous.** The
  reader in this pack takes the LAST sample at or before the requested time,
  which is the post-event value — the one somebody asking "what is it at t" means.
- **A chattering model produces thousands of these.** A result file that is
  mostly duplicate timestamps is a finding, not a formatting quirk: see
  `lenses.md` §5.

### Non-finite values

A diverged run writes `nan`, `inf` or `-inf` (spelling varies with the C runtime;
Windows builds have historically emitted `1.#INF` and `-1.#IND`). The parser
recognises all of these and `modelica.solution_valid` refuses the file. It does
NOT drop them silently — a reader that skipped NaNs would let a claim be
extracted from a diverged run with nothing in the verdict to say so.

## `outputFormat="mat"` — the default, and why this pack does not read it

omc's default is a MATLAB v4 `.mat` file. It is much smaller than CSV (the
constant columns are stored once, not once per row) and it is what OMEdit plots.
Reading it needs either `scipy.io.loadmat` or a hand-written v4 reader, and the
variable table is stored transposed with a separate name matrix and a data-block
index — enough machinery that a tier-0 gate reading it would need a third-party
dependency, which the pack's hard rule forbids.

So: **record runs with `outputFormat="csv"`** for anything this pack gates.
`modelica.simulates` passes it explicitly. If you have a `.mat` from elsewhere,
convert it once:

```bash
omc <<'EOF'
convertMoFiles();                       // no-op; just to show the script form
EOF
# or, more usefully, re-run the simulation with outputFormat="csv"
```

There is no supported CLI converter; re-running with the CSV option is the
reliable route, and it also re-proves that the model still simulates.

Other formats you may meet: `outputFormat="plt"` (a legacy text format, one
block per variable, not a table) and `"empty"` (writes nothing at all — useful
for a compile-only check, and a trap if something downstream expects a file).

## Recording a run for this pack

```modelica
loadModel(Modelica);
loadFile("/abs/path/MyPackage/package.mo");
simulate(MyPackage.Experiments.NominalRun,
         startTime = 0, stopTime = 3600,
         numberOfIntervals = 3600,          // resolution, not accuracy
         tolerance = 1e-6,                  // accuracy
         outputFormat = "csv",
         variableFilter = ".*");            // or a regex, but then see below
getErrorString();
```

Then commit the CSV next to the model and point `modelica_result_csv` at it.

Four decisions to record as constants (method rule 3), because each of them can
silently change a claim:

- **`numberOfIntervals`** is a RESOLUTION choice. The solver steps where it needs
  to and interpolates onto this grid. A `max` reducer over a coarse grid misses a
  peak between samples, so raise it when a claim is about an extremum.
- **`tolerance`** is the accuracy choice, and the one that makes a result
  tolerance-dependent if a claim's margin is near it.
- **`variableFilter`** silently excludes everything it does not match. Use `.*`
  unless the file size is genuinely a problem, and list what you need in
  `modelica_required_variables` either way.
- **`method`** defaults to `dassl` (variable-step, stiff, error-controlled).
  `euler` and `rungekutta` are fixed-step and make the step size the accuracy,
  which then owes a convergence study.

## Staleness

A result file is a **recorded measurement of a source that has since moved**. The
tier-0 gates in this pack all read it, and none of them can tell you whether it
still corresponds to today's `.mo` files. That is the ledger's job: hash the
sources into the projection so a changed model marks the verdicts STALE, and
remember that stale is not passed (method rule 9).

The cheapest discipline that works: regenerate the result in the same commit that
changes the model, and never hand-edit a result file. It is a generated artifact,
and rule 1's corollary applies — generated files are outputs, not sources.
