---
as_of: 22d0e7db7c486678
---

# The air around a motorcycle

This project finds the drag of a motorcycle with a rider. The body is the motorBike from the OpenFOAM tutorials. In the model, the air comes to the bike at 20 m/s. On the road, the bike moves through still air at that speed.

## What the person asked for

The bike and the rider must push through still air with a drag area of at most 0.35 m^2 (R1). The drag area is the drag force divided by the pressure of the moving air. It does not need a frontal area.

## How the drag is found

OpenFOAM makes a mesh around the body and calculates the flow with the k-omega SST model. A guard checks each step: the speed of the air, the size of the box around the bike, the quality of the mesh, and the history of the solver. OpenFOAM also calculates the pressure on the surface and the paths of the air. ParaView draws them.

## Where the design is now

The pictures show the flow on the base mesh. One mesh does not give the drag area: a finer mesh can give a different value. The ladder of three meshes is not in the pack yet, so no evaluator settles the drag area claim (C1).

Two assumptions stay open. The wheels do not turn in the model (A1). A steady solution stands for the mean of a wake that is not steady (A2). A person must record each one.

The bike is not ready for the wind tunnel.
