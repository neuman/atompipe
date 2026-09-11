# When to stop trusting closed form

Closed form is not a cheap approximation of FEA. On the problems it describes it
is **exact** — and it is exact in microseconds, on every edit, with no install,
no mesh and no convergence study. The question is never "is this accurate
enough"; it is "is this the problem these formulae describe".

## The decision rule

Run the tier-0 sweep first. Always. Then read the result:

| what came back | what to do |
|---|---|
| utilisation below ~0.3 on every gate, `beam.model_validity` passing | **Done.** Record it, move on. A solver will tell you the same thing three hours later. |
| utilisation above ~1.0 | **Done.** It fails. Change the design, not the tool. A refined analysis of a part that is 40% over is a way of arguing with arithmetic. |
| utilisation between ~0.3 and ~1.0 | Genuinely uncertain. Decide whether the *decision* changes with the answer. If a cheap change buys margin, make the change; if not, escalate. |
| `beam.model_validity` FAILED | The other numbers are not trustworthy. Escalate, or change the geometry until it is a beam again. |
| a gate SKIPPED | Nothing was proven. Find the missing number first; it is far cheaper than a solver. |

The trap in the middle row is worth naming: the reason to escalate is that the
**decision** depends on the answer, not that the number is interesting. If both
answers lead to the same part, the analysis is entertainment.

## Escalate before the solver: five cheaper moves

Most "we need FEA" is not.

1. **Superposition.** Multiple loads add exactly. Two table lookups and a plus
   sign covers a surprising share of real load cases.
2. **Bound it.** Run the case both ways — fully fixed and fully pinned ends,
   load at the worst station, the minimum material condition. If the pessimistic
   bound passes, you are finished and you never needed the exact answer.
3. **Apply a stress-concentration factor by hand.** `K_t` for a hole, a fillet or
   a step comes from published charts. Multiply the nominal stress by it. This is
   the single highest-value hand correction available and it takes a minute.
4. **Change the geometry so it *is* a beam.** Add depth, add a rib, move a hole
   off the peak-moment station, add a gusset at the root. A design that fits the
   closed form is a design you can iterate on in seconds for the rest of the
   project — which is worth more than one accurate number.
5. **Break one.** For anything printed, cast, glued, or made of a material whose
   properties you are guessing, a physical test with a scale and a lever settles
   more in an afternoon than a solver settles in a week — because the solver is
   fed the same guessed properties.

## When FEA is genuinely the right answer

Escalate when the geometry or the physics is outside what any closed form
describes:

- **Genuinely 2D or 3D stress fields**: plates, shells, brackets that are neither
  a beam nor a column, anything where load spreads in two directions at once.
- **Complex or organic geometry**: topology-optimised parts, castings with
  varying wall, anything where "the section" is not a meaningful phrase.
- **Contact**: press fits, snap fits, bolted joints where you need the actual
  pressure distribution, anything where parts touch and the touching is the
  problem.
- **Stress concentrations you cannot look up**: an intersection of three features
  where no chart applies.
- **Nonlinearity**: plastic deformation, large deflection, hyperelastic materials,
  buckling past the critical point.
- **Dynamics**: modal frequencies, vibration response, impact, drop.
- **Thermal-structural coupling**: differential expansion producing real stress.
- **Assemblies** whose members share load in a way you cannot resolve by hand.

## If you do escalate, escalate properly

FEA is a tier-2 gate and it obeys the extension protocol like any other. In
particular:

- **Name the unvalidated quantity first.** Not "check the bracket" — "peak
  principal stress at the root fillet under the 300 N rated load".
- **Validate the solver against this pack.** Run the FEA on a simple beam whose
  closed-form answer you already have from here. If it does not reproduce
  `P*L^3/(3*E*I)` to a few percent, the mesh, the units or the boundary
  conditions are wrong — and you have just found that out on a problem where you
  know the answer instead of on the one where you do not. Do this every time.
- **Give it a negative control.** An FEA gate that cannot tell a beam from a
  wire is not a gate. Run the same model with the section quartered, or the
  support released, and require the gate to fail.
- **Record every solver setting as a constant with provenance** — element type,
  mesh density, convergence criterion, contact formulation. A mesh that was
  chosen because it ran fast is a design decision and must be logged as one.
- **Do a mesh convergence study**, or state that you did not. A single run at one
  mesh density is one number, not a result.
- **Wait until the design has stopped moving.** Running a twenty-minute solve on
  geometry you are still redrawing is a way of feeling productive. Keep the
  closed-form loop until the shape settles, then escalate once.

## The thing to keep saying out loud

A converged solve is not a validated design, exactly as a clean compile is not a
working product. FEA answers the question you meshed, with the properties you
typed, under the boundary conditions you chose — and the boundary conditions are
the same thing this pack asks you to be honest about in `lenses.md`. A beautiful
contour plot with the wrong end fixity is a confident picture of a different part.
