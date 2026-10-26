---
as_of: b2c25115e0ce4c68
---

# The air around a motorcycle

This project finds the drag of a motorcycle with a rider. The body is the motorBike from the OpenFOAM tutorials. In the model, the air comes to the bike at 20 m/s. On the road, the bike moves through still air at that speed.

## What the person asked for

The bike and the rider must push through still air with a drag area of at most 0.35 m^2 (R1). The drag area is the drag force divided by the pressure of the moving air. It does not need a frontal area.

## How the drag is found

OpenFOAM makes a mesh around the body and calculates the flow with the k-omega SST model. Guards check each step: the speed of the air, the box, the quality of the mesh, the solver history and the wall model. OpenFOAM also calculates the pressure on the surface and the paths of the air. ParaView draws them.

## What the pictures show

The pictures show the flow on the base mesh, which has 358654 cells. The colours on the body show the pressure coefficient Cp. The lines show the paths of the air, and their colours show the speed of the air. The wake pictures show the slow air behind the bike and the rider. The chart of the drag area shows how the value changed during the last part of the solver run.

## What the check found

In the last check run, the guards passed. The flow was the stated flow, and the box was large enough. The base mesh had no face past the quality limits. The drag area settled on the base mesh. On 96.32% of the body, y+ was at most 300, and the limit is 90% (C6). The page shows these claims as stale, because nopekit cannot see all of the inputs of the solver. Only a new check run can show that these results are still current.

On the base mesh, the drag area is 0.299 m^2. One mesh does not give the drag area, because a finer mesh can give a different value.

The mesh check (C7) fails. The pack made two finer meshes, with 926215 and 2674337 cells, and solved each mesh for 500 iterations. At the end, the drag area on the finest mesh did not settle. Its iterative uncertainty is 1.98% of the drag area, and the limit is 1%. Because of this, the evaluator stopped before it compared the three meshes, and it did not calculate a mesh error band (GCI). The drag area goes down from the base mesh to the middle mesh, and up on the finest mesh. But this order is not certain, because the change between the two finest meshes is smaller than the iterative uncertainty of the finest mesh.

The drag area claim (C1) cannot be judged yet. Its evaluator runs only when C7 passes.

## What can change this

More iterations on the finest mesh can let its drag area settle. Then the evaluator can compare the three meshes. If the three values converge in one direction, the pack can calculate the mesh error band, and C1 can be judged. If they do not, the ladder must change, for example with different mesh sizes.

## What stays open

Two assumptions stay open. The wheels do not turn in the model (A1). A steady solution stands for the mean of a wake that is not steady (A2). A person must record each one.

The bike is not ready for the wind tunnel.
