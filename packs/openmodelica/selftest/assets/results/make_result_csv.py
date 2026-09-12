# SPDX-License-Identifier: Apache-2.0
"""Regenerate ThermalTank.TankRun_res.csv. READ PROVENANCE.md FIRST.

This writes a file in OMC's result-CSV format. **It is not omc and it does not
pretend to be.** It integrates ThermalTank.Tank's one equation with fixed-step
RK4 so that the pack's tier-0 gates have a real numeric run to read on a machine
with no OpenModelica installed. See PROVENANCE.md for why that is the honest
option and what it costs.

    python3 selftest/assets/results/make_result_csv.py
"""
from __future__ import annotations

import os

#: The same parameters ThermalTank.Tank declares, typed again by a human.
C = 210000.0        # J/K
UA = 42.0           # W/K
Q = 2100.0          # W
T_AMB = 293.15      # K
T_START = 293.15    # K

#: The experiment annotation on ThermalTank.TankRun: 0..25000 s, 25 intervals.
START = 0.0
STOP = 25000.0
STEP = 1000.0

#: Fixed-step classical RK4. Chosen over the forward Euler an example would
#: normally reach for because Euler at h/tau = 0.2 is 10% wrong at the knee of
#: the exponential, and a "result" that wrong would make modelica.mirror_agrees
#: fail on the baseline for a reason that has nothing to do with the gate. RK4 at
#: the same step is ~3e-4 K from the closed form over the whole run, which is a
#: realistic amount of numerical disagreement for a mirror check to see and pass.
#: A variable-step stiff solver (which is what omc would actually use) was not
#: written: it would be a third of this file's length in solver code, and the
#: point of the file is to be readable, not to be a solver.


def derivative(temperature: float) -> float:
    return (Q - UA * (temperature - T_AMB)) / C


def main() -> None:
    target = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "ThermalTank.TankRun_res.csv")
    times = [START]
    values = [T_START]
    t, y = START, T_START
    while t < STOP - 1e-9:
        k1 = derivative(y)
        k2 = derivative(y + STEP / 2 * k1)
        k3 = derivative(y + STEP / 2 * k2)
        k4 = derivative(y + STEP * k3)
        y = y + STEP / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        t = t + STEP
        times.append(t)
        values.append(y)

    with open(target, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('"time","tank.T","tank.qLoss","der(tank.T)"\n')
        for t, y in zip(times, values):
            handle.write(f"{float(t)!r},{y!r},{UA * (y - T_AMB)!r},"
                         f"{derivative(y)!r}\n")
    print(f"wrote {target}: {len(times)} rows, final T = {values[-1]:.6f} K, "
          f"final der(T) = {derivative(values[-1]):.3e} K/s")


if __name__ == "__main__":
    main()
