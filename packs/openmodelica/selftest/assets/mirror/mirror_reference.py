# SPDX-License-Identifier: Apache-2.0
"""The MIRROR: an independent implementation of ThermalTank's equations.

This file is the thing ``modelica.mirror_agrees`` compares the recorded Modelica
run against, and it is shipped so that a reader can see what "independent" means
here rather than taking the word for it.

The Modelica model states a relation:

    C*der(T) = Q - UA*(T - T_amb)

and hands it to a solver, which integrates it numerically. This file states the
CLOSED FORM of the same relation:

    T(t) = T_inf + (T_start - T_inf)*exp(-t/tau),
      T_inf = T_amb + Q/UA,   tau = C/UA

and evaluates it directly. Nothing is shared between the two paths but the
parameter values: no code, no solver, no integration. That is what makes the
comparison worth anything — two implementations that share a subroutine share its
bugs, and a mirror that imports the model is a mirror that agrees with it by
construction.

Run it to regenerate ``thermal_tank_mirror.csv``:

    python3 selftest/assets/mirror/mirror_reference.py

The numbers must not be edited by hand. If the model's parameters move, change
them here and re-run; a mirror that was hand-patched to agree is a mirror that
has stopped being evidence.
"""
from __future__ import annotations

import math
import os

#: The same parameter values ThermalTank.Tank declares. They are restated rather
#: than parsed out of the .mo on purpose: a mirror that reads the model's source
#: is no longer independent of it, and the ONE thing these two implementations
#: are allowed to share is the physical constants a human typed twice and can
#: check by eye.
C = 210000.0        # J/K    thermal capacitance of the contents
UA = 42.0           # W/K    loss conductance of the wall
Q = 2100.0          # W      electrical heat input
T_AMB = 293.15      # K      ambient air temperature
T_START = 293.15    # K      contents temperature at t = 0

#: Times to tabulate, seconds. Six points over 0..25000 s = 0..5 tau. A subset of
#: the result grid on purpose: the gate interpolates the Modelica result at each
#: mirror time, so the mirror is free to be sparser, denser, or on entirely
#: different times from the run it checks.
TIMES = (0.0, 5000.0, 10000.0, 15000.0, 20000.0, 25000.0)


def temperature(t: float) -> float:
    """Closed-form contents temperature at time ``t``, kelvin."""
    tau = C / UA
    t_inf = T_AMB + Q / UA
    return t_inf + (T_START - t_inf) * math.exp(-t / tau)


def wall_loss(t: float) -> float:
    """Closed-form heat leaving through the wall at time ``t``, watts."""
    return UA * (temperature(t) - T_AMB)


def main() -> None:
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "thermal_tank_mirror.csv")
    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write("time,tank.T,tank.qLoss\n")
        for t in TIMES:
            handle.write(f"{float(t)!r},{temperature(t)!r},{wall_loss(t)!r}\n")
    print(f"wrote {target}")
    print(f"tau = {C / UA:g} s   T_inf = {T_AMB + Q / UA:g} K   "
          f"T(25000) = {temperature(25000.0):.6f} K")


if __name__ == "__main__":
    main()
