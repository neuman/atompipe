# SPDX-License-Identifier: Apache-2.0
"""Current exported geometry, with one stable node: part. No solver colours."""
import os
from nopekit.models import View, ViewKind
from nopekit.site import ViewContext, viewgen


@viewgen(id="simp.part", kind=ViewKind.MODEL3D, title="Exported structural part",
         requires_python=["trimesh"], order=10)
def part(ctx: ViewContext):
    p = ctx.param("simp_case")
    if not p or not p.get("mesh"):
        return None
    import trimesh
    path = p["mesh"]
    if not os.path.isabs(path):
        path = os.path.join(ctx.root, path)
    mesh = trimesh.load(path, force="mesh")
    scene = trimesh.Scene()
    scene.add_geometry(mesh, node_name="part", geom_name="part")
    src = ctx.write_asset("simp-part.glb", scene.export(file_type="glb"))
    return View(id="simp.part", kind=ViewKind.MODEL3D, title="Exported structural part",
                src=src, meta={"nodes": ["part"]})
