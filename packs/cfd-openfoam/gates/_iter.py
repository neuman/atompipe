# SPDX-License-Identifier: Apache-2.0
"""How much a converging quantity may still move: Eca & Hoekstra's iterative-error
estimate, read at its most pessimistic over a ladder of fit windows, held against
a model-free reading of the same history. Standard library only.

Used by ``cfd.converged`` (is the pressure drop settled?) and by
``cfd.mesh_independence`` (the iterative error the GCI is compared with). The
entry point is ``remaining(series)``. ``envelope(changes, end)`` is the same
estimate on a history of changes, the form the authors' own examples are stored
in.

Source: L. Eca, M. Hoekstra, "Evaluation of numerical error estimation based on
grid refinement studies with the method of the manufactured solutions", Computers
& Fluids 38 (2009) 1580-1591, Sec. 2.1, Eqs. (1)-(10); "C&F 2009" below. Their
estimate is Eq. (9), e = L(n_o) / (1 - 10^q): the sum of the geometric progression
the changes follow from the last one on, with the slope q of the least-squares fit
of log10 of the change against the iteration number (Eq. (7)), the level L(n_o)
read from the fit (Eq. (8)), the fit's standard deviation D_f (Eq. (10)) and the
safety factor 1.25 (Sec. 2.1.1). What is ours, each with a negative control in
tests/test_cfd_openfoam.py (``TheIterativeErrorEstimate``): the slope read at its
upper confidence bound; the window ladder; the running maximum; the rate-change
refusal, in both directions; the round-off floor and the test that a flat tail is
round-off; the model-free reading.

The direction that matters: the estimate may sit above the true remaining change
(a run that had settled reads unsettled: a false fail, which costs a tighter
residual target), never so far below that a run reads settled more than
STABLE_TOL from the value it converges to. Where a choice has two readings, the
larger estimate is taken.

Chosen in issue #15, Phase 0: three designs (below) and a judge, on one harness
that judged every cut point of 3 held-out turbulent pitzDaily-family histories, 2
dev pitzDaily, 9 laminar pitzDaily runs no design saw, about 100 laminar channel
histories and residual stops, the pack's 12 selftest histories, 60 synthetic
histories with a known limit and 63 MARIN-derived ones. Every number quoted in
this module comes from that harness, on real ESI OpenFOAM v2606 where it says so.

What slipped through the estimator this replaces (``cfd._remaining`` until P0.1),
in order. Its first draft took the change over 10 iterations as the error: U
relaxed to 0.03 passed a run 9.7% from converged. The next compared only each
window's two ends, and a 2-iteration oscillation read as still. The next took
the rate from the windows' spreads: an earlier oscillation filling the window
before made a run that had just moved 0.17% pass, 0.22% from converged, and its
round-off floor, applied before the rate, let a creep relaxed to U 1e-4 pass with
0.2% to come. The last took the rate from the two end points of 10-iteration
windows (C&F 2009 p. 1582: "It is not safe ... to obtain q ... using the results
of only two subsequent iterations, because there is no guarantee that the
convergence is smooth"), and a history that was not monotone over its last 20
iterations fell to a branch that returned only the last 10 iterations' swing. On real v2606 simpleFoam histories that one
read settled at cut points up to 1.04% (pitzDaily) and 2.46% (pitzDailyExptInlet)
from the final value, up to 9.85% and 7.37% on two held-out pitzDaily runs, and,
on a laminar pitzDaily (nu 1e-3, the case a laminar gate decides alone, its
residuals meeting a target), up to 0.46% converged and 23.4% under slow
relaxation. This one reads no cut point of any of them settled more than 0.1%
from converged.

Precondition: the history is written finely enough that a change of ROUNDOFF of
the value is resolved. OpenFOAM's default (writePrecision 6) prints 7 significant
digits; on such a history a flat stretch is a print quantum, not round-off, and is
refused (``STAIRS``): a converged run printed to 7 digits then never reads
settled (a false fail). The gate writes ``writePrecision 12;`` into the two
function objects it owns.

Designs that lost:
- eh-faithful (C&F 2009 with transient removal by the criterion reached, a halving
  window ladder, a power-law tail when it fits better, ROUNDOFF 1e-9). 0 false
  settles on real data, but a slow mode under a fast one read settled 152 times
  (up to 1.00%) on six two-mode histories: its windows have no rate-change test.
  It also read inf at random on converged runs (the 1e-5 baseline ladder's level
  1, 7.7e-9 from converged), and it settled 91 cuts of a converged laminar
  pitzDaily where this one settles 1702. Of the 50 real residual stops within
  0.1% of converged it read 46 settled (this one 43): its loss is the two-mode
  miss, not the real data.
- eh-plus-drift (Eq. (9) on the last half and quarter, a two-sided rate test, a
  model-free reading with the farthest value over a quarter or half, floors 1e-7
  and 1e-6). The fewest misses on decaying synthetic histories, but it read 23
  of the 50 real residual stops within 0.1% of converged not settled (this one
  7), and a harmonic creep settled 1671 times, a creep under its 1e-7 floor 23
  times at 0.20%. Its mean-drift reading added |last - mean| to the
  extrapolation from the mean, about 3x the true remaining change on a geometric
  decay.
- eh-envelope (this one's base). Its one-sided slowing test let an overshoot,
  1 + 0.05 x 0.8^n - 0.003 x 0.997^n, read settled at 16 cuts up to 0.27%; its
  round-off rule read a creep printed to 7 digits settled at 767 cuts at 0.20%;
  an oscillating fast mode over a slow one at 27 cuts up to 0.44%.

The P0 review changed two readings on purpose, each measured on the judge's
harness: the acceleration test refuses deeper (SPEED_FLOOR 1e-7, was 1e-5) and
waits for a difference of DIVE_SLACK of the rate, and a history with too few
changes before a flat tail that is not round-off reads inf (it was None). The
parity below was run again after them, against the judged estimator with the
same two changes made: the same largest difference, 4.3e-13, and no cut point
that changes sides. On the harness no real history reads settled more than 0.1%
from converged, before or after; 183 of the 40,192 real cuts that read settled
now read not settled, no real residual stop changes, and the synthetic misses
went from 75 cuts in 9 histories to 61.

The arithmetic is the standard library's (``statistics.linear_regression``,
``statistics.fmean``, ``math.fsum``) where the judged estimator summed by hand.
P0.1's parity run held the two together at every cut point the judge's harness
takes on 248 histories, every cut up to 40 too, and MARIN's Table 1 windows
(307,220 readings): the largest relative difference is 4.3e-13, and no cut point
reads settled in one and not in the other. On Python 3.10 this module gives the
judged numbers bit for bit, and the judged sums themselves moved at 7906 of the
harness's 302,910 cut points (up to inf against a finite value on a ramp, never
across the settled line): the built-in sum() is compensated only from Python
3.12.
"""
from __future__ import annotations

import math
from itertools import accumulate
from statistics import fmean, linear_regression

#: Eca & Hoekstra's safety factor on the extrapolated iterative error: U_i =
#: 1.25 e_i (C&F 2009, Sec. 2.1.1, p. 1582). With it their estimate bounded the
#: true iterative error at more than 95% of the nodes in almost every case (pp.
#: 1585-86; conclusions, p. 1590). Rejected: 1 (measured on the judge's harness
#: in the P0 review: the synthetic misses go from 61 cuts in 9 histories to 67 in
#: 10, the worst from 1.51% to 1.53%, MARIN's df_iter histories from 14 cuts in 3
#: to 28 in 6, and the reading on the manual's Table 1 falls from 0.71 to 0.57 of
#: the authors' own tool at its lowest); 3 (the GCI's two-grid factor: no
#: iterative study carries it over).
SAFETY = 1.25

#: The fewest changes a window is fitted on: 8, so the slope's standard error has
#: 6 degrees of freedom and CONFIDENCE is a one-sided 95% bound there. Ours: C&F
#: 2009 only forbid a rate from two iterations, and MARIN's tool refuses 2 or fewer
#: points. A history needs 2 x WINDOW_MIN changes (17 values) before it is judged,
#: so the rate-change test has two windows. Rejected: 4 (2 degrees of freedom, t95
#: = 2.92: no longer a 95% bound); 16 (the test stand-in's converged run, 48
#: decaying iterations and 11 still, no longer settles, and 8 real residual stops
#: flip); 10 (the old STABLE_WINDOW, no reason of its own; eh-faithful's MIN_FIT,
#: whose 21-value minimum the gate's message said until P0.1).
WINDOW_MIN = 8

#: Standard errors: the pessimistic slope sits CONFIDENCE above the fitted one,
#: and the shortest window's rate must differ from the next one's by more than
#: CONFIDENCE combined standard errors to read as still changing. C&F 2009 judge
#: their estimator by the share of nodes it bounds and aim at 95% (pp. 1585-86);
#: one-sided t95 at 6 degrees of freedom is 1.94, rounded up. Rejected: 0 (q_f
#: bare: misses up to 1.93%, 0.66 of MARIN's tool on its Table 1, and the
#: estimate rests on the fitted rate alone, which C&F 2009 Sec. 4.5 saw fail); 3
#: (no coverage target asks for it, and it blunts the rate test).
CONFIDENCE = 2.0

#: A change at or below ROUNDOFF of the value is round-off: the fitted history ends
#: at the last change above it (MARIN's iterative_error ends it at the last change
#: above its tolerance, user manual Sec. 2.1), and a smaller change inside a
#: window is raised to it (raising a change only flattens the decay: the estimate
#: only grows). Ours, measured: the baseline writes 10 digits and ends on changes
#: of 3e-10 to 7e-10 of itself that no longer shrink; 1e-8 sits 1.5 decades
#: above. What it lets through: a drift under 1e-8 of the value per iteration
#: (1e5 iterations, 50 budgets of 2000, to move STABLE_TOL): the ramp 5e-9 per
#: iteration reads settled at its first 787 cuts (the model-free reading catches
#: it from then on). Rejected: 1e-9 (eh-faithful's: the 1e-5 baseline ladder's
#: level 0, 1.4e-8 from converged at its stop, read inf, and the pack's known-good
#: ``thicker_fluid`` level 1 read inf at its stop); 1e-7 (eh-plus-drift's floor:
#: a drift of 2e-8 per iteration gets through at 187 cuts, a harmonic creep at
#: 1994); 0 (the round-off tail of a converged run never shrinks: 19 of 29
#: channel runs taken to 1e-11 read unsettled in their last 31 iterations).
ROUNDOFF = 1e-8

#: A stretch of WINDOW_MIN or more changes under ROUNDOFF ends a history that has
#: reached round-off only if none of the STAIRS changes before it is exactly zero.
#: A solver that is still moving does not repeat a value to the last printed
#: digit; a history that did is printed in steps of one quantum, and its flat
#: stretches say nothing about its rate. It goes to the fit like any other
#: history, where steps of one size do not shrink: inf. What slipped through
#: without it: 1 + 0.002 x 0.99995^n printed to 7 significant digits (OpenFOAM's
#: default writePrecision 6) moves one quantum, 1e-6 of itself, about every ten
#: iterations; each flat run of 8 read as round-off, and it read settled at 767
#: cuts while 0.20% from its limit (eh-envelope), at 36 with the model-free
#: reading. What it costs: a converged run printed to 7 digits reads settled at
#: few of its cuts (the judge's laminar pitzDaily, nu 1e-3: 18 cuts, against 1702
#: printed to 12 digits), a false fail that writing 12 digits removes.
#: Rejected: any change under the floor before the stretch (the baseline's level 1
#: decays through troughs of 8e-9 of its value, then read inf, and the real
#: TheRealOpenFOAM test of the pack failed); a bound on the last change above the
#: floor, 10 x ROUNDOFF (the test stand-in's converged run, a decay that jumps to
#: an exact constant 12 iterations before its end, its last change 1.8e-6 of the
#: value, never settled, and 11 of the pack's tests failed).
#: The length, 16 changes, is not a measured choice. In the P0 review a look-back
#: of 8, of 32 and of the whole history read every cut of the judge's harness the
#: same as 16, and the pack's tests passed with each. 16 is the judged value, two
#: shortest windows; no history at hand tells the lengths apart.
STAIRS = 2 * WINDOW_MIN

#: An acceleration (the shortest window's rate faster than the next one's, by more
#: than CONFIDENCE combined standard errors and by more than DIVE_SLACK of the
#: next one's rate) is refused only while the last change above round-off is
#: above SPEED_FLOOR of the value: a decay that speeds up into round-off is how a
#: run near its fixed point ends, and one that dives far above it may be two modes
#: cancelling ahead of a turning point. Ours, measured; 10 x ROUNDOFF. Without the
#: refusal (eh-envelope's one-sided test) the overshoot 1 + 0.05 x 0.8^n - 0.003 x
#: 0.997^n read settled at 16 cuts up to 0.27% (with it, 2), and three overshoots
#: at 39 cuts (with it, 5).
#: What slipped through the judged 1e-5 (P0 review): two slow modes of opposite
#: sign change by less than 1e-5 of the value per iteration long before
#: round-off, so the refusal never fired and the value read settled near its
#: extremum. 1 + 0.05 x 0.995^n - 0.06 x 0.998^n read settled at cuts 233-248,
#: 2.21% from its limit; on 84 two-mode overshoots (rates 0.7 to 0.9995 per
#: iteration, every cut to 1200) 1810 cuts read settled more than 0.1% out, 187
#: at 1e-7 (what is left: ``remaining``).
#: Rejected: 1e-5 (above); 1e-6 (998 of those cuts, and three overshoots of the
#: judge's set at 8); 1e-8, ROUNDOFF itself, and 0 (the pack's own known-bad for
#: cfd.mesh_independence, the channel on 10 x 2 cells, ends its 29 iterations
#: accelerating, its last change above round-off 2.3e-8 of its value: it read inf
#: and failed the prerequisite cfd.converged, so the selftest called
#: cfd.mesh_independence unqualified, "control not isolated"); 1e-4 (more gets
#: through than at 1e-5: three overshoots at 37 cuts); a rate difference of 5% or
#: more before refusing either way (RATE_SLACK: the tiny standard error of a
#: smooth decay is what catches a power-law creep; six two-mode histories came
#: back at up to 1.03%, 1 + 0.05/sqrt(n) at 2071 cuts).
SPEED_FLOOR = 1e-7

#: The share of the next window's rate by which an acceleration must also be
#: faster before it is refused. Ours, measured (P0 review), on the side of an
#: acceleration only: on the side of a slowing rate a slack lets a slow mode
#: through (RATE_SLACK, above). A real 1e-6 stop at U 0.3, 1.8e-5 from converged,
#: decays so evenly that its standard errors are 1.5e-6 and 1.0e-6 decade per
#: iteration. Its last 8 changes run faster than its last 16 by 8.5e-6 decade per
#: iteration, 2e-4 of its rate, and its last change is 1.8e-6 of its value: with
#: no slack it read inf under any SPEED_FLOOR below that (the judge's reason to
#: reject 1e-6 and 1e-7). 1e-3 sits 5 x above it; the slow overshoots above dive
#: by 3% of their rate or more. Rejected: 0 (the U 0.3 stop and its ladder level
#: read inf); 1e-2 (512 cuts of the 84 overshoots against 187, for 32 more settled
#: real cuts and no real stop that changes).
DIVE_SLACK = 1e-3

#: The model-free reading ignores a net drift under DRIFT_FLOOR of the value per
#: window. Under it, a drift that never slows needs 1000 windows to move
#: STABLE_TOL. eh-plus-drift's value, which it took from the old SETTLED_FLOOR,
#: but the window is not the same: that one was 10 iterations, this one is a sixth
#: or a quarter of the run, so the floor per iteration falls as the run grows
#: (5e-7 of the value at 17 values, 2e-9, under ROUNDOFF, at 3000). Measured in
#: the P0 review on the judge's harness: the drift it lets through is the ramp
#: under ROUNDOFF that the module already accepts, and a smaller floor buys back
#: only that ramp's cuts for real cuts that read not settled. Rejected: 1e-7 (the
#: ramp of 5e-9 per iteration at 67 cuts, not 787, for 74 real cuts that no longer
#: read settled); 1e-9 (the ramp at none, for 138; the old floor rejected 1e-9 for
#: the baseline's round-off read as never settling, and no real residual stop
#: changes here); 1e-5 (the reading no longer catches the ramp: it reads settled at
#: all 2984 of its cuts). The ramp moves 0.1% in 2e5 iterations, 100 budgets.
DRIFT_FLOOR = 1e-6


def remaining(series):
    """How far the last value of ``series`` (one value per iteration, in order) may
    still be from the value it converges to, in its own units: None with fewer than
    2 x WINDOW_MIN + 1 values; math.inf when the history shows no decay to
    extrapolate (the changes do not shrink, the rate is still changing, or a value
    is not finite); else the larger of ``envelope`` (C&F 2009 Eq. (9), pessimistic)
    and ``drift`` (model-free), for the gate to compare with STABLE_TOL x |last|.

    The changes are |phi_n - phi_(n-1)|, the scalar form of the paper's L-infinity
    norm (Eq. (1)): sign-blind, so an oscillation whose swing decays is fitted like
    a monotone decay, and one whose swing does not decay reads not converging (Eq.
    (4): q < 0 or nothing). When the last WINDOW_MIN or more changes are all under
    round-off and no value repeated exactly before them (STAIRS), the history has
    reached round-off, and the reading is what it still swings by there.

    The relative line the gate draws needs a value away from zero: a quantity
    converging to zero, or crossing it at the cut, never reads settled. A last
    value that is not finite reads inf here, and inf <= STABLE_TOL x inf is True:
    the gate refuses a non-finite value before it compares.

    What it still cannot see, measured on the judge's harness and in the P0
    review, each class with every history measured in it:
    - An overshoot read at or near its turning point. The value stands still at
      its extremum, and nothing in the history tells an extremum from a limit:
      the error is the extremum's distance from the limit. The judge's three: 1 +
      0.05 x 0.8^n - 0.003 x 0.997^n at 2 cuts up to 0.27%, 1 + 0.2 x 0.9^n -
      0.01 x 0.995^n at 1 at 0.70%, 1 + 0.02 x 0.7^n - 0.002 x 0.999^n at 2 up to
      0.20%. The review's 84 (rates 0.7 to 0.9995): 37 of them at 187 cuts, from
      62 iterations before the extremum to 4 after it, up to 29% (1 + 0.25 x
      0.7^n - 0.3 x 0.999^n at cut 19).
    - A slow mode while a fast one carries every change of the last 2 x
      WINDOW_MIN iterations and the fast one oscillates: 1 + 0.005 x 0.998^n +
      0.05 x 0.9^n (-1)^n at 1 cut at 0.43%; 1 + 0.5 x 0.8^n cos(0.9 n) + 0.003 x
      0.995^n at 12 up to 0.25%; 1 + 0.5 x 0.8^n cos(0.9 n) + 0.002 x 0.999^n at
      23 (n = 40-70) up to 0.20%; 1 + 0.005 x 0.998^n + 0.01 x 0.99^n sin(0.7 n)
      at 2 up to 0.10%.
    - A rate that turned slower in the last few iterations: 0.85 to 0.995 at n =
      40, 5 cuts up to 1.51%; 0.7 to 0.998 at n = 30, 13 cuts up to 0.39%.
    - A drift under ROUNDOFF per iteration (the ramp 5e-9 per iteration, its
      first 787 cuts).
    - Anything after the last iteration (a step, a decay that later reverses:
      MARIN's df_iter1537, 14 cuts up to 1.36%).
    - A converged value that differs with the under-relaxation (Rhie-Chow: a
      fixed point, not an iterative error)."""
    n = len(series)
    if n < 2 * WINDOW_MIN + 1:
        return None
    if not all(math.isfinite(v) for v in series):
        return math.inf
    changes = [abs(b - a) for a, b in zip(series, series[1:])]
    cut = ROUNDOFF * abs(series[-1])
    end = max((i for i, c in enumerate(changes) if c > cut), default=-1)
    if (len(changes) - 1 - end >= WINDOW_MIN
            and 0.0 not in changes[max(0, end - STAIRS):max(0, end)]):
        est = max(abs(v - series[-1]) for v in series[end + 1:])
    else:
        est = envelope([max(c, cut) for c in changes], end,
                       speed_floor=SPEED_FLOOR * abs(series[-1]))
    if est is None or est == math.inf:
        # None: fewer than WINDOW_MIN changes before a flat tail that is not
        # round-off. What slipped through until the P0 review: it came back as None,
        # and the gate said "fewer than the 17 needed" of a 31-value history.
        return math.inf
    return max(est, drift(series))


def envelope(changes, end, speed_floor=0.0):
    """C&F 2009 Eq. (9) x SAFETY, read pessimistically, on changes[0..end]
    (magnitudes of the change per iteration, the last one that counts at ``end``):
    the largest estimate over the windows ending at ``end`` of WINDOW_MIN, 2 x
    WINDOW_MIN, 4 x WINDOW_MIN, ... changes and of the whole of [0, end];
    infinite when the shortest window's rate is slower than the next one's by more
    than CONFIDENCE combined standard errors, or faster by as much and by more
    than DIVE_SLACK of the next one's rate while the last change is above
    ``speed_floor`` (absolute; 0 refuses an acceleration at any depth); None when
    fewer than WINDOW_MIN changes lie in [0, end].

    Each window: the least-squares line of log10 change on iteration (Eqs. (7),
    (10)), its slope raised to the upper bound q_f + CONFIDENCE x SE, pivoted at the
    window's centroid, read at ``end`` (Eq. (8)) and raised by one D_f. C&F 2009
    (p. 1582) say D_f "may be used to obtain a more conservative estimate" and
    print the correction only in their 2006 SNH paper ([10]), which was not read
    for this pack: one D_f up is the plainest reading. D_f on m - 2 degrees of
    freedom (the printed denominator does not survive the PDF's text; m - 2 is the
    unbiased one and the larger). 1 - 10^q as -expm1: written plainly it rounds to 0.0 for a
    bound within 1e-17 of zero, and the division fails.

    Why a ladder of windows. One window cannot see a rate that slowed in its last
    iterations (C&F 2009 Sec. 4.5, their coarsest grid: "a strange decrease of the
    convergence rate in the last iterations"), and a long one dilutes it with the
    faster decay before; a short one sees the latest rate but is noisy, which the
    slope's bound pays for. The largest estimate stands. A long window that takes
    in the start-up transient fits a steeper decay, so a smaller estimate: it never
    wins, and no transient is cut off first (C&F 2009 Sec. 4.6 cut it by hand, and
    MARIN's tool asks for an it_0 "you probably have to play around with").

    Why the running maximum. A window fits, at each iteration, the largest change
    from there to ``end``: a window that starts in an oscillation's trough is not
    read as growing. Under a geometric decay it is the change itself. What it was
    for: the baseline's last mode oscillates with a period of 6-10 iterations, and
    levels 0 and 1 read never converging without it. Undone alone, measured: 0.1 x
    0.995^n cos(2n) never settles in 3000 iterations, MARIN's Table 1 item 2 reads
    inf, and the judge's unseen laminar pitzDaily (nu 1e-3 and 2e-3) first settle
    at iterations 2171 and 1535 instead of 1701 and 905; it buys 35 synthetic
    false settles back (up to 0.25%), the cost below.
    What it costs: it follows a fast oscillation's peaks over the troughs where a
    slow mode shows (the first miss in ``remaining``). Rejected: also fitting a
    running minimum (eh-envelope: halved those misses, but the period-3 decay then
    never settled, and the baseline's first settled cut moved from 25 to 38).

    Why the rate test, both ways. A slow mode under a fast one shows only as a
    bend: the latest rate is slower than the one before, and every window's line
    runs under the slow tail (without it, eh-envelope's 0.5 x 0.7^n + 0.003 x
    0.995^n read settled 0.30% out, and eh-faithful, which has none, read six
    two-mode histories settled 152 times up to 1.00%). A turning point shows the
    other way: two modes of opposite sign cancel, the changes dive faster than
    either mode, and the dive extrapolates to nothing (one-sided, 1 + 0.05 x 0.8^n
    - 0.003 x 0.997^n read settled at 16 cuts up to 0.27%, and 1 + 0.2 x 0.9^n -
    0.01 x 0.995^n at 12 up to 0.70%; two-sided above SPEED_FLOOR, at 2 and 1;
    eh-plus-drift's RATE_Z is the source of the second side). The rate the tail
    will keep is not known until the two agree. Undone both ways: six two-mode
    histories read settled 199 times up to 1.03%, and power-law creeps 2266 times
    up to 0.24%. Rejected: comparing the last WINDOW_MIN with the WINDOW_MIN before
    (disjoint windows: more real stops read inf, for few fewer synthetic
    misses)."""
    avail = end + 1
    if avail < WINDOW_MIN:
        return None
    peaks = list(accumulate(reversed(changes[:end + 1]), max))[::-1]
    logs = [math.log10(t) if t > 0 else 0.0 for t in peaks]
    lengths = []
    m = WINDOW_MIN
    while m < avail:
        lengths.append(m)
        m *= 2
    lengths.append(avail)
    fits = [_window(logs[avail - m:]) for m in lengths]
    if len(fits) >= 2:
        (q1, se1, _), (q2, se2, _) = fits[0], fits[1]
        bend = CONFIDENCE * math.hypot(se1, se2)
        if q1 > q2 + bend:
            return math.inf                           # still slowing
        if q1 < q2 - max(bend, DIVE_SLACK * abs(q2)) and changes[end] > speed_floor:
            return math.inf                           # diving: a turning point may come
    return SAFETY * max(e for _, _, e in fits)


def _window(ys):
    """One window's (q_f, SE, Eq. (9) read pessimistically, before SAFETY) on the
    log10 changes ``ys``, the last at ``end``: C&F 2009 Eqs. (7), (8), (10) with
    the iteration counted from the window's centroid, D_f on m - 2 degrees of
    freedom. Infinite when the slope's upper bound is not a decay (Eq. (4):
    convergence needs q < 0; MARIN's error_iterative calls it "Divergence")."""
    m = len(ys)
    ns = [i - (m - 1) / 2.0 for i in range(m)]
    q, yb = linear_regression(ns, ys)
    d_f = math.sqrt(math.fsum((y - yb - q * n) ** 2 for n, y in zip(ns, ys)) / (m - 2))
    se = d_f / math.sqrt(math.fsum(n * n for n in ns))
    q_hi = q + CONFIDENCE * se
    if not q_hi < 0:
        return q, se, math.inf
    level = yb + q_hi * ns[-1] + d_f
    try:
        return q, se, 10.0 ** level / -math.expm1(q_hi * math.log(10.0))
    except OverflowError:
        return q, se, math.inf


def drift(series):
    """A model-free reading of what is still to come, which assumes no law for the
    single steps: the larger of two extrapolations of the history's net drift over
    fractions of the run. The block means of its last three sixths extrapolate to
    a limit (the ratio r of the two successive drifts carried on geometrically),
    and the reading is the last value's distance from it; the least-squares slopes
    of its last two quarters, the same way. Infinite when the drift does not
    shrink (r >= 1); the last block's own movement when it is under DRIFT_FLOOR or
    the drifts change sign.

    Why. Over fractions of the run, a creep reads as drift however its single steps
    are hidden under a faster oscillation, which is where the running maximum is
    blind: without it, 1 + 0.005 x 0.998^n + 0.05 x 0.9^n (-1)^n read settled at
    27 cuts up to 0.44%, 1 + 0.005 x 0.998^n + 0.01 x 0.99^n sin(0.7n) at 35 up to
    0.12%, and a ramp of 5e-9 per iteration under ROUNDOFF at all 2984 cuts (at
    787 with it). From eh-plus-drift, with one change: its mean drift added the
    last value's distance from the last block's mean to the extrapolation from that
    mean, about 3x the true remaining change on a geometric decay (a real 1e-6 stop
    at U 0.02, 0.042% from converged, then read not settled); taken as the distance
    from the last value to the extrapolated limit, it moves no real stop's
    reading. Its farthest-value term is left out (it catches a few more synthetic
    misses and read 6 real 1e-6 stops at slow relaxation not settled). It carries
    no SAFETY factor: it is a cross-reading, never the extrapolation the paper
    calibrated, and on the real stops it reads about the true remaining change,
    under the Eq. (9) reading it is held against."""
    n = len(series)
    return max(_mean_drift(series, n // 6), _slope_drift(series, n // 4))


def _carry(last_move, ratio):
    """The geometric sum r / (1 - r) of a drift whose successive windows move by
    ``ratio``: infinite when it does not shrink."""
    return math.inf if ratio >= 1 else last_move * ratio / (1.0 - ratio)


def _mean_drift(s, b):
    """The last value's distance from the limit the means of the last three blocks
    of b values extrapolate to."""
    last = s[-1]
    n = len(s)
    m = [fmean(s[n - k * b:n - (k - 1) * b]) for k in (3, 2, 1)]
    d1, d2 = m[1] - m[0], m[2] - m[1]
    if abs(d2) <= DRIFT_FLOOR * abs(last) or d1 * d2 <= 0:
        return abs(last - m[2]) + abs(d2)
    return abs(last - (m[2] + math.copysign(_carry(abs(d2), d2 / d1), d2)))


def _slope_drift(s, w):
    """The drift still to come by the least-squares slopes of the last two windows
    of w values: the last window's movement carried on at the ratio of the two."""
    last = s[-1]
    b1 = linear_regression(range(w), s[-2 * w:-w]).slope
    b2 = linear_regression(range(w), s[-w:]).slope
    if abs(b2) * w <= DRIFT_FLOOR * abs(last) or b1 * b2 <= 0:
        return abs(b2) * w
    return _carry(abs(b2) * w, b2 / b1)
