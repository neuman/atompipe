# SPDX-License-Identifier: Apache-2.0
"""Write a small, reproducible SIMP problem; optionally draw a proposed field.

The example is a clamped 40x16x12 mm block with a distributed downward end
load, 35% of its designable volume available, and solid end pads. The grid is
2 mm: deliberately coarse enough to explore on a laptop. This is a proposal
example, not an assertion that its thresholded geometry is ready to build.
"""
import argparse
import hashlib
from pathlib import Path
import numpy as np


def problem(nx=20, ny=8, nz=6, h=2.0):
    region = np.zeros((nz, ny, nx), np.uint8)
    region[:, :, 0] = region[:, :, -1] = 1  # Keep support and loaded end pads.
    nodes = np.arange((nx + 1) * (ny + 1) * (nz + 1))
    end = nodes[nodes % (nx + 1) == nx]
    p = dict(nx=nx, ny=ny, nz=nz, h=h, origin=np.zeros(3), nu=0.3,
             region=region, erel=np.ones_like(region, dtype=float), cost=np.ones_like(region, dtype=float),
             fixed_nodes=nodes[nodes % (nx + 1) == 0], load_0_dofs=3 * end + 2,
             load_0_vals=np.full(len(end), -1.0 / len(end)), load_names=np.array(["end-load"]),
             load_weights=np.array([1.0]), budget_mm3=float((region == 0).sum() * h**3 * .35),
             rmin_mm=1.5*h, rmin_z_mm=1.5*h, symmetry="none")
    digest = hashlib.sha256()
    for key in sorted(p):
        a = np.asarray(p[key])
        digest.update(key.encode()); digest.update(str(a.shape).encode()); digest.update(str(a.dtype).encode()); digest.update(a.tobytes())
    p["problem_hash"] = digest.hexdigest()
    return p


def draw(field, destination, threshold=0.5):
    """Draw exactly the kept voxels, without hidden smoothing or island removal.

    This keeps voxel corners and exposes only faces bordering empty space.
    CAD/FEA checks may reject the result; changing its shape is another decision.
    """
    import trimesh
    with np.load(field, allow_pickle=False) as z:
        rho = z["rho"]
        kept = rho >= threshold
        h, origin = float(z["h"]), z["origin"]
    # Outward-wound corners, in (x,y,z); array indices below are (z,y,x).
    sides = [((-1,0,0),[(0,0,0),(0,0,1),(0,1,1),(0,1,0)]),
             ((1,0,0),[(1,0,0),(1,1,0),(1,1,1),(1,0,1)]),
             ((0,-1,0),[(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
             ((0,1,0),[(0,1,0),(0,1,1),(1,1,1),(1,1,0)]),
             ((0,0,-1),[(0,0,0),(0,1,0),(1,1,0),(1,0,0)]),
             ((0,0,1),[(0,0,1),(1,0,1),(1,1,1),(0,1,1)])]
    vertices, faces = [], []
    nz, ny, nx = kept.shape
    for z, y, x in np.argwhere(kept):
        for (dx,dy,dz), corners in sides:
            xx, yy, zz = x+dx, y+dy, z+dz
            if 0 <= xx < nx and 0 <= yy < ny and 0 <= zz < nz and kept[zz,yy,xx]:
                continue
            i = len(vertices)
            vertices.extend((origin + h*(np.array([x,y,z])+c)).tolist() for c in corners)
            faces.extend([(i,i+1,i+2),(i,i+2,i+3)])
    if not faces:
        raise ValueError("threshold removed every cell")
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
    mesh.export(destination)
    return mesh


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="directory for problem.npz or part.stl")
    ap.add_argument("--field", help="draw this proposed NPZ instead of writing a problem")
    ap.add_argument("--threshold", type=float, default=.5)
    args = ap.parse_args()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    if args.field:
        if not 0 < args.threshold <= 1:
            ap.error("threshold must be in (0,1]")
        draw(args.field, out / "part.stl", args.threshold)
    else:
        np.savez_compressed(out / "problem.npz", **problem())
