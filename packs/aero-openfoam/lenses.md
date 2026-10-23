# Lenses: attacking a drag area before anyone builds from it

Each lens is a question a reviewer asks of THIS case, with the evidence it would
take to close it. A run that passes every guard answers some of them and not the
rest: it says the equations were solved well, never that they were the right
equations or the right body.

## The body that was meshed

- Is the surface file the design's? The pack pins it by sha256, so it runs the
  file you named. Who checked that the file is the current design, at the right
  scale (mm against m), with the rider in the right position?
- What was left out? Mirrors, cables, a number plate, the rider's helmet shape.
  A simplification is a claim; name it in the claim's statement.
- Did snappyHexMesh mesh what the file holds? Look at the body's patches in the
  mesh, not only at the count of faces in error. A gap smaller than the cells
  closes; a thin part (a mudguard) can lose its thickness.
- Are the wheels still in the model and turning in the world? A still wheel on a
  moving ground has another drag than a turning one.

## The stream that was stated

- Is `aero_u_inf_m_s` the speed of the claim? A drag area changes little with
  speed, but the Reynolds number and the wall layers do.
- Still air, or a head wind? A cross wind of a few m/s turns the flow by several
  degrees, and the drag of a body at yaw is not its drag head on.
- Is the ground moving with the air? A road under a vehicle moves; a wind-tunnel
  floor does not. The two give different drags near the ground.
- Is the inlet's turbulence (k and omega in 0/) the real stream's? The
  tutorial's values are a choice, not a measurement.

## A box too small for the wake

- Where does the wake end? An outlet in the wake forces its fixed pressure on a
  flow that has not recovered. `aero.domain` asks for 15 H; look at the wake's
  length in the pictures too.
- Is the blockage the body's? The pack uses the body's bounding box as its
  frontal area, an upper bound. A real tunnel test of the same body has its own
  blockage correction.

## A mesh the mesher gave up on

- Did snappyHexMesh extrude layers where the drag is made? Layer coverage is in
  the detail; a low number on the body's back half is where separation is
  decided.
- Is the cell cap the reason the mesh is coarse? `aero.mesh_quality` fails a cap
  that was reached. A cap not reached can still be the reason a level stops
  refining in a region.

## Convergence that is a limit cycle

- Does the drag area settle, or does it swing about a mean? A steady solver on a
  flow that sheds vortices swings for ever. The iterative uncertainty is half the
  swing; a mean taken over too short a window moves with the window.
- Does the mean drift between windows? A half-range can be small while the mean
  still moves (P0: +0.59% on the motorBike's L0 while U_I read 0.27%).

## A drag area for the wrong question

- Is the claim about drag area, or about a top speed, a fuel use or a range?
  Each needs more than CdA: rolling resistance, power, a drive cycle.
- Is CdA at one speed the claim, or CdA over a range of speeds? A run is one
  speed.

## Against something that is not this solver

- What does the same body give in another code, another model (k-epsilon,
  Spalart-Allmaras), or a wind tunnel? k-omega SST is one model; a second one
  that agrees is evidence, one that differs by 20% is a finding.
- For the motorBike tutorial, OpenFOAM's own run reads Cd 0.41 on its estimated
  0.75 m^2 (0.304 m^2 of CdA). That is the same code, not a check of it.
