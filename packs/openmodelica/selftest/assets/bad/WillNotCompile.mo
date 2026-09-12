package WillNotCompile
  "The baseline tank calling a function that does not exist. Known-bad, on purpose.

   Negative control for modelica.compiles. The file parses: the syntax is legal
   Modelica and a text editor sees nothing wrong. The equation count is right, the
   physics is right, and the only change from ThermalTank.Tank is that the wall
   loss is routed through wallLoss(), which is defined nowhere in this package and
   nowhere in any library. omc's frontend fails to instantiate the class and
   buildModel returns no executable.

   This is the shape of the real failure it stands for: a helper function renamed
   or moved out of the package while one caller was left behind. Do not repair
   this file."

  model Tank
    "Lumped-capacitance tank whose loss term calls an undefined function"
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
  equation
    qLoss = wallLoss(UA, T, T_amb);
    C * der(T) = Q - qLoss;
  end Tank;

  model Run
    "The uncompilable tank as a runnable experiment"
    Tank tank
      "The tank under test";
    annotation(experiment(StartTime = 0, StopTime = 25000, Interval = 1000));
  end Run;
end WillNotCompile;
