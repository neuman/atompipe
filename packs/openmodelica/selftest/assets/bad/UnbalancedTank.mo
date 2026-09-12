package UnbalancedTank
  "The baseline tank with ONE UNKNOWN TOO MANY. Known-bad, on purpose.

   Negative control for modelica.checks. Every equation of ThermalTank.Tank is
   still here and still correct; the single change is the extra variable qWall,
   declared and never given an equation. That is the classic structural error in
   an acausal language: nothing is syntactically wrong, nothing is physically
   absurd, and the system simply has no unique solution.

   omc's checkModel reports it as
     Class UnbalancedTank.Run has 2 equation(s) and 3 variable(s).
   and modelica.checks FAILS on the inequality. Do not repair this file."

  model Tank
    "Lumped-capacitance tank with an unmatched unknown"
    parameter Real C(unit = "J/K") = 210000
      "Thermal capacitance of the contents";
    parameter Real UA(unit = "W/K") = 42
      "Loss conductance of the wall";
    parameter Real Q(unit = "W") = 2100
      "Electrical heat input";
    parameter Real T_amb(unit = "K") = 293.15
      "Ambient air temperature";

    Real T(unit = "K", start = 293.15, fixed = true)
      "Bulk temperature of the contents";
    Real qLoss(unit = "W")
      "Heat leaving through the wall";
    Real qWall(unit = "W")
      "THE PLANTED DEFECT: heat crossing the wall metal, declared and never
       given an equation. One unknown, zero equations.";
  equation
    qLoss = UA * (T - T_amb);
    C * der(T) = Q - qLoss;
  end Tank;

  model Run
    "The unbalanced tank as a runnable experiment"
    Tank tank
      "The tank under test";
    annotation(experiment(StartTime = 0, StopTime = 25000, Interval = 1000));
  end Run;
end UnbalancedTank;
