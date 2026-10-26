# Attack the structural model

- Which loads did the optimizer never see? Try a lateral force, torsion and another mounting condition.
- Compare the exported geometry with the density field: did thresholding cut a load path or smoothing erase a seat?
- Does the clamp represent the real joint, or does it make a flexible connection infinitely stiff?
- Check the selected load nodes on both meshes. Does the same force land on the same physical patch?
- Which stress concentrations lie outside the region being asserted? Who checks the joint itself?
- Refine the exported surface as well as the volume mesh. Two meshes of the same wrong surface agree.
- Does the part remain in linear elasticity, particularly if it is printed across the layers?
- Challenge the ghost stiffness in nearly empty SIMP cells. The exported part has no such material.
- A converged objective can be a local optimum or a bad trade between load cases. Try another start and budget.
