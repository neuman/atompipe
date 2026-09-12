# Adversarial lenses — equation-based modelling

Run these before the model is trusted, not after a number from it has been
quoted in a decision. Each heading is a different person attacking the same
model on its own terms (method rule 8). The uncomfortable questions are the
point.

---

## 1. Is the model well-posed?

- How many equations and how many unknowns? Not "it ran" — the number. Which
  command printed it, and when?
- Which variables are declared and never constrained? A variable added "for
  plotting" that nothing assigns is an unknown, and the system has no unique
  solution with it in there.
- Is any equation a restatement of another? Two equations that are the same
  relation written differently balance the count and leave the system singular.
- Where did the tool have to **reduce the index**? Every rigidly-coupled pair of
  inertias, every ideal transformer, every position constraint is a candidate.
  Did you look at the log, or did you assume it did not happen?
- Which algebraic loops got torn, and what are the tearing variables? A loop torn
  on a badly-scaled variable converges slowly, or to the wrong root.

## 2. Are the initial conditions real?

- Which states are `fixed = true` and which are guesses? A `start` value without
  `fixed` is a HINT to the initialisation solver, not an initial condition, and
  the run can begin somewhere else entirely.
- Did the initialisation system have more than one solution? Print the initial
  values and read them as physics: is any pressure negative, any temperature
  below absolute zero, any mass fraction outside 0..1, any flow going the wrong
  way through a check valve?
- Is the initial state *consistent* — does it satisfy the algebraic equations, or
  only the differential ones? An inconsistent start shows as a spike in the first
  few samples that everybody has learned to crop off the plot.
- If the claim is about steady state, why are you starting from a transient at
  all? `initialEquation der(x) = 0` asks the question directly and answers it in
  one solve instead of five time constants.

## 3. Is the solver tolerance tighter than the effect being claimed?

- What is the claim's margin, as a fraction? What is `tolerance`? If the first is
  within a few multiples of the second, the claim is measuring the solver.
- Re-run at 1e-8 and at 1e-4. Did the number move? By how much, compared with the
  margin? **If you have not done this, you do not know.**
- Did any event resolve differently between the two runs? A marginal threshold
  crossing that lands on the other side at a tighter tolerance is a design that
  is not robust, reported as a design that passed.
- Is the model badly scaled — states spanning many orders of magnitude in SI
  units? A relative tolerance means something different to a 1e-9 kg/s flow and a
  1e6 J energy in the same system.

## 4. Does the result depend on step size or output grid?

- `numberOfIntervals` is a RESOLUTION, not an accuracy. A `max` reducer over a
  coarse grid misses a peak between samples. What is the shortest feature in the
  response, and how many output points land on it?
- Did you use a fixed-step solver? Then the step size IS the accuracy, and you
  owe a convergence study: halve it, and report whether the answer moved.
- Is there a stiff subsystem forcing tiny steps? A run that takes an hour for a
  model of six equations is telling you about a time constant you did not think
  you had.

## 5. Events, discontinuities and chattering

- List every state event: every `if`, `when`, `noEvent`, `smooth`, every
  saturation, hysteresis, friction and check valve.
- How many events did the run actually fire? Is it thousands? Then the model
  chattered and the answer is an artefact of event handling, not physics.
- Is any threshold crossed exactly at a sample boundary, or at t = 0?
- Did somebody use `noEvent()` to make the chattering stop? That does not fix the
  model — it hides the discontinuity from the solver and lets it step straight
  over it.

## 6. Units and dimensional truth

- How many parameters are bare `Real` with no unit? That number is the size of
  the hole; nothing in the toolchain will object to any arithmetic among them.
- Kelvin or celsius? Absolute or gauge? Radians or degrees? Per second or per
  hour? Each of these has a plausible wrong answer exactly one constant away.
- Has `--unitChecking` ever been switched on? What did it say? (If the answer is
  "it produced hundreds of warnings so we turned it off", that is the finding.)
- Does a parameter's NAME carry its unit (`distance_km`) while its declaration
  says nothing? Then the unit lives in a comment the compiler cannot read.

## 7. The mirror nobody checked

- Is there a second implementation of these equations — a spreadsheet, a
  notebook, a script that produces "the numbers" for slides? There usually is,
  and it usually exists because the real model could not be run where the numbers
  were needed.
- When did anyone last compare the two, on the same inputs, variable by variable?
- Which one do decisions actually get made from? If it is the mirror, the
  Modelica model is documentation, and the thing being validated is not the thing
  being used.
- Do the two share code? Then they share bugs, and the comparison proves nothing.

## 8. What is not modelled at all

- Name three physical effects deliberately left out, and the magnitude of each.
  "Thermal mass of the piping", "sensor lag", "the controller's sample period".
- What is held constant that is not? Ambient conditions, a property evaluated at
  one temperature, an efficiency that is really a function of load.
- Where does the model stop being valid? Every correlation, material property and
  linearisation has a range. What are they, and does the claimed operating point
  sit inside all of them?
- What happens at the boundaries of the run — before `startTime`, after
  `stopTime`? A claim about "steady state" made from a run that stopped at 1 tau
  is a claim about a transient.

## 9. Provenance of the numbers in the model

- For each parameter: why this value, what was rejected, what measurement or
  datasheet it came from, which gate protects it (method rule 3).
- Which parameters were tuned to make the model match data? Those are fitted
  constants, not physical ones, and the model cannot then be used to predict the
  thing it was fitted to.
- Which solver settings were copied from a tutorial? Those are constants too.

## 10. The gap between the source and the result

- Is the committed result file the output of the committed source? What proves
  it — a hash, a timestamp, or a memory?
- If the source has moved since the run, every tier-0 verdict in this pack is
  STALE, and stale is not passed.
- Who can reproduce the run, on what machine, in how long? A result nobody can
  regenerate is a measurement, not a model.
