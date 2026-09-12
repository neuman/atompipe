package ThermalTank
  "A stirred tank with a constant heat input and a convective loss to ambient.

   The smallest model that is still a real Modelica model: one continuous state,
   one algebraic variable, an acausal balance written as an equation rather than
   as an assignment, and a closed-form answer to check the solver against.

   T(t) = T_inf + (T_start - T_inf) * exp(-t/tau),
     T_inf = T_amb + Q/UA,  tau = C/UA.

   The closed form is what selftest/assets/mirror/ holds, so this package and its
   mirror are two independent implementations of one set of equations and
   modelica.mirror_agrees can compare them.

   Units are declared on local Real subtypes rather than pulled from
   Modelica.Units.SI so the package loads into a bare omc with no Modelica
   Standard Library present. That is a deliberate choice for a test asset; a real
   project should use the MSL types."

  type Temperature = Real(unit = "K", min = 0)
    "Absolute thermodynamic temperature";
  type HeatFlowRate = Real(unit = "W")
    "Heat flow rate, positive in the direction named by the variable";
  type HeatCapacity = Real(unit = "J/K")
    "Lumped thermal capacitance of a body held at one temperature";
  type ThermalConductance = Real(unit = "W/K")
    "Overall heat transfer coefficient multiplied by the area it acts over";

  model Tank
    "Lumped-capacitance tank: C*der(T) = Q - UA*(T - T_amb)"
    parameter HeatCapacity C = 210000
      "Thermal capacitance of the contents: 50 kg of water at 4200 J/(kg.K)";
    parameter ThermalConductance UA = 42
      "Loss conductance of the whole wetted wall, insulation and outer film together";
    parameter HeatFlowRate Q = 2100
      "Electrical heat delivered by the immersed element while it is on";
    parameter Temperature T_amb = 293.15
      "Ambient air temperature outside the tank, held constant over the run";
    parameter Temperature T_start = 293.15
      "Contents temperature at t = 0, equal to ambient: the tank starts cold";
    parameter Real heaterDutyFraction(unit = "1") = 1.0
      "Fraction of the run for which the element is energised, 0 to 1";

    Temperature T(start = T_start, fixed = true)
      "Bulk temperature of the contents; the one state of this model";
    HeatFlowRate qLoss
      "Heat leaving through the wall, positive outward";
  equation
    qLoss = UA * (T - T_amb);
    C * der(T) = heaterDutyFraction * Q - qLoss;
  end Tank;

  model TankRun
    "The tank as a runnable experiment: one Tank, default parameters, 25000 s"
    Tank tank
      "The tank under test; its variables appear in the result as tank.T, tank.qLoss";
    annotation(experiment(StartTime = 0, StopTime = 25000, Interval = 1000,
                          Tolerance = 1e-6));
  end TankRun;
end ThermalTank;
