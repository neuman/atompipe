package AssertFires
  "The baseline tank with a ceiling the contents genuinely cross. Known-bad, on purpose.

   Negative control for modelica.simulates. Everything here compiles, checks
   balanced, and initialises. The single change from ThermalTank.Tank is T_max,
   set to 300 K when the tank's own steady state is T_amb + Q/UA = 343.15 K: the
   assert must fire, and it fires at t = tau*ln(50/43.15) = 738 s of a 25000 s run.

   That is the failure this control exists for. The simulation exits non-zero
   having written a result file that stops at 738 s, and a pipeline that reads a
   final value off that file gets a number for a run that never happened. Do not
   repair this file."

  model Tank
    "Lumped-capacitance tank with an assert the run violates"
    parameter Real C(unit = "J/K") = 210000
      "Thermal capacitance of the contents";
    parameter Real UA(unit = "W/K") = 42
      "Loss conductance of the wall";
    parameter Real Q(unit = "W") = 2100
      "Electrical heat input";
    parameter Real T_amb(unit = "K") = 293.15
      "Ambient air temperature";
    parameter Real T_max(unit = "K") = 300
      "THE PLANTED DEFECT: a ceiling 43 K below the tank's own steady state";

    Real T(unit = "K", start = 293.15, fixed = true)
      "Bulk temperature of the contents";
    Real qLoss(unit = "W")
      "Heat leaving through the wall";
  equation
    qLoss = UA * (T - T_amb);
    C * der(T) = Q - qLoss;
    assert(T < T_max, "tank contents crossed T_max: the run is not valid past this point");
  end Tank;

  model Run
    "The asserting tank as a runnable experiment"
    Tank tank
      "The tank under test";
    annotation(experiment(StartTime = 0, StopTime = 25000, Interval = 1000));
  end Run;
end AssertFires;
