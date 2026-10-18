# Lenses: attacking a CFD result before anyone builds from it

Each lens is a question a reviewer asks of THIS case, with the evidence it would
take to close it. A converged, mesh-independent run answers some of them and not
the rest: it says the equations were solved well, never that they were the right
equations.

## The model nobody chose

- Is the flow laminar, and who said so? A Reynolds number on the wrong length (a
  duct's width where its hydraulic diameter belongs, a body's length where its
  frontal width belongs) moves it by a factor of several. Check `cfd_length_m`
  against the geometry, and say which length it is.
- Is the flow incompressible? Below Mach 0.3 the density changes by under about 5%;
  a fan's tip, a nozzle or a leak may not be below it even when the mean flow is.
- Is the flow steady? A steady solver on a flow that sheds vortices (a cylinder
  past Reynolds number about 47) converges to an answer no instant of the real flow
  has, or never converges at all. A residual that settles into a cycle is the flow
  telling you.
- Is gravity, buoyancy or heat in the physics that matters? An isothermal solver
  has none of them.

## The geometry that was meshed

- Is the case's geometry the design's? A blockMeshDict typed by hand, an STL exported
  at the wrong scale (mm against m), an old export: each solves a different
  object well. At the same velocity, a length 1000 times too large gives a
  Reynolds number 1000 times too large.
- What was left out? Fillets, a grille, a gasket lip, a cable bundle in the duct. A
  simplification is a claim; name it in the claim's statement.
- Is the case 2D? A 2D case has no end effects and no secondary flow. A 2D channel
  is an infinitely wide one.

## Boundaries that decide the answer

- Is the inlet profile the real one? A uniform inlet into a short duct adds an
  entrance pressure drop a developed inlet does not have.
- Is the outlet far enough downstream? An outlet in a recirculation zone forces the
  flow back in through it, and the solver accepts that.
- Does a fixed pressure or velocity on a boundary hide what the claim is about? A
  fan's flow fixed at the inlet means the case cannot tell you that the fan cannot
  deliver it against this resistance.

## Convergence that is not

- Did the run stop because it met its residual targets, or because it ran out of
  iterations? `cfd.converged` reads which; a run that hit `endTime` is not converged,
  whatever its residuals look like.
- Did the quantity the claim is about stop changing? Residuals measure the equations'
  imbalance, not the drag or the pressure drop. `cfd.converged` holds both.
- Were the residual targets tight enough to mean anything? A target of 1e-2 is met by
  a solution still moving.

## The mesh that decides the number

- Would a finer mesh give a different answer? `cfd.mesh_independence` refines the
  project's mesh twice and estimates the error by Richardson extrapolation (Celik et
  al. 2008). An answer that still moves past the tolerance is the mesh's, not the
  flow's.
- Is the mesh fine where the gradients are? A wall boundary layer, a shear layer
  behind a step, the gap between a fin and a wall. A refinement of a mesh that misses
  a feature refines the miss.
- Did checkMesh say OK only because the thresholds are loose? `cfd.mesh_quality`
  states which limits it held, and a skewness under checkMesh's 4 can still be poor.

## A number for the wrong question

- Is the pressure the static one or the total one, kinematic (m^2/s^2) or in Pa?
  An incompressible solver's `p` is kinematic: multiply by density for Pa.
- Is the drag coefficient referred to the area the claim means (frontal, plan,
  wetted)? A coefficient is meaningless without its reference area and velocity.
- Is the result a mean over a face or the worst point on it? A peak temperature and
  a mean temperature can differ by tens of degrees.

## Against something that is not this solver

- Has the case been checked against an answer from somewhere else: a closed form
  (`fluids-analytic`), a published benchmark, a measurement? A CFD result agreeing
  with itself on a finer mesh shows the mesh is fine, not that the model is right.
- Has the same setup reproduced a known case? This pack's tests run a laminar
  channel against its exact answer where OpenFOAM is installed; a project's own
  validation case is the stronger evidence.
