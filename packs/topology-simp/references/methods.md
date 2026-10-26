# Methods and their sources

- SIMP, density filter, optimality criteria: Andreassen, Clausen, Schevenels,
  Lazarov, Sigmund, "Efficient topology optimization in MATLAB using 88 lines of
  code", Struct. Multidisc. Optim. 43 (2011) 1-16.
- In 3D: Liu, Tovar, "An efficient 3D topology optimization code written in
  Matlab", Struct. Multidisc. Optim. 50 (2014) 1175-1196.
- Heaviside projection with continuation: Wang, Lazarov, Sigmund, "On projection
  methods, convergence and robust formulations in topology optimization",
  Struct. Multidisc. Optim. 43 (2011) 767-784.
- Direct sparse solves: Schenk, Gärtner, "Solving unsymmetric sparse systems of
  linear equations with PARDISO", Future Gener. Comput. Syst. 20 (2004)
  475-487 (MKL's PARDISO, through pypardiso); Li, "An overview of SuperLU:
  algorithms, implementation, and user interface", ACM Trans. Math. Softw. 31
  (2005) 302-325 (scipy's splu).
- Smoothed aggregation, the preconditioner beyond the direct solvers' reach:
  Vanek, Mandel, Brezina, "Algebraic multigrid by smoothed aggregation for
  second and fourth order elliptic problems", Computing 56 (1996) 179-196;
  pyamg: Bell, Olson, Schroder, JOSS 7 (2022) 4142.
- Geometric multigrid-preconditioned CG for topology optimisation, tried first
  and rejected here (_fe3d.Solver says why): Amir, Aage, Lazarov, "On
  multigrid-CG for efficient topology optimization", Struct. Multidisc. Optim.
  49 (2014) 815-829.
- Meshing: Geuzaine, Remacle, "Gmsh: a 3-D finite element mesh generator with
  built-in pre- and post-processing facilities", Int. J. Numer. Meth. Engng 79
  (2009) 1309-1331; Hu, Schneider, Wang, Zorin, Panozzo, "Fast tetrahedral
  meshing in the wild", ACM Trans. Graph. 39 (2020) 117 (fTetWild).
- CalculiX: Dhondt, "The Finite Element Method for Three-Dimensional
  Thermomechanical Applications", Wiley 2004; ccx 2.21 user's manual.
- Elastic energy method for impact (falling weight on an elastic structure):
  Young, Budynas, "Roark's Formulas for Stress and Strain", 7th ed., ch. 16.
- Effective mass of an eccentric impact on a free rigid body: Goldsmith,
  "Impact", Arnold 1960, ch. 2.
- Stress averaged over a critical distance rather than read at one node:
  Taylor, "The Theory of Critical Distances: A New Perspective in Fracture
  Mechanics", Elsevier 2007.
