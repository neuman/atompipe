# SPDX-License-Identifier: Apache-2.0
"""The exported part, not the optimizer's density or compliance.

All reads enter through ctx; no cross-gate memo or project-specific geometry.
The solver runs afresh on two meshes. Its files are evidence, never a cache.
"""
import json
import math
import os


def case(ctx):
    p = ctx.param("simp_case")
    if not isinstance(p, dict):
        # ParamTrace is a Mapping, not necessarily a dict.
        from collections.abc import Mapping
        if not isinstance(p, Mapping):
            raise ValueError("simp_case must be an object")
    p = dict(p)
    expected = {"mesh", "young_mpa", "poisson", "mesh_mm", "support", "loads", "stress_region"}
    if set(p) != expected:
        raise ValueError(f"simp_case keys must be {sorted(expected)}")
    if not isinstance(p["mesh"], str) or not p["mesh"]:
        raise ValueError("mesh must name an exported STL")
    for key in ("young_mpa", "mesh_mm"):
        if not number(p[key]) or p[key] <= 0:
            raise ValueError(f"{key} must be finite and positive")
    if not number(p["poisson"]) or not -1 < p["poisson"] < 0.5:
        raise ValueError("poisson must lie strictly between -1 and 0.5")
    box(p["support"])
    box(p["stress_region"])
    if not p["loads"]:
        raise ValueError("at least one load patch is required")
    for load in p["loads"]:
        if set(load) != {"box", "force_n"}:
            raise ValueError("each load needs box and force_n")
        box(load["box"])
        v = load["force_n"]
        if len(v) != 3 or not all(number(x) for x in v) or not any(v):
            raise ValueError("force_n must be a finite nonzero 3-vector")
    return p


def number(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def box(b):
    if len(b) != 2 or any(len(v) != 3 for v in b):
        raise ValueError("box must be [[xmin,ymin,zmin],[xmax,ymax,zmax]]")
    if not all(number(x) for v in b for x in v) or any(a > z for a, z in zip(*b)):
        raise ValueError("box endpoints must be finite and ordered")


def mesh(ctx, p):
    import numpy as np
    import trimesh
    path = p["mesh"]
    if not os.path.isabs(path):
        path = os.path.join(ctx.root, path)
    part = ctx.load_file(path, loader=read_mesh)
    if not isinstance(part, trimesh.Trimesh) or not part.is_volume or not np.isfinite(part.vertices).all():
        raise ValueError("exported mesh must be a finite, watertight, consistently wound solid")
    if len(part.split(only_watertight=False)) != 1:
        raise ValueError("exported part must be connected; detached material is not a load path")
    return part


def read_mesh(path):
    import trimesh
    return trimesh.load(path, force="mesh", process=True)


def select(nodes, b):
    import numpy as np
    return np.flatnonzero(((nodes >= np.asarray(b[0])) & (nodes <= np.asarray(b[1]))).all(axis=1))


def solve(ctx, p, gate_id):
    import numpy as np
    from nopekit.modelio import load_path
    ccx = load_path(os.path.join(os.path.dirname(__file__), "_ccx.py"))
    part = mesh(ctx, p)
    folder = ctx.out_path("topology-simp", gate_id)
    os.makedirs(folder, exist_ok=True)
    surface = os.path.join(folder, "part.stl")
    part.export(surface)
    answers, evidence = [], [surface]
    for label, size in (("coarse", p["mesh_mm"]), ("fine", p["mesh_mm"] * 0.65)):
        nodes, tets = ccx.mesh_surface(surface, size)
        support = select(nodes, p["support"])
        if len(support) < 3 or np.linalg.matrix_rank(nodes[support] - nodes[support[0]]) < 2:
            raise ValueError("support must select at least three non-collinear mesh nodes")
        F = np.zeros_like(nodes)
        loads = []
        for load in p["loads"]:
            ids = select(nodes, load["box"])
            if not len(ids) or np.intersect1d(ids, support).size:
                raise ValueError("load patch is empty or overlaps a fixed support")
            f = np.asarray(load["force_n"], float)
            F[ids] += f / len(ids)
            loads.append((ids, f))
        region = select(nodes, p["stress_region"])
        if not len(region):
            raise ValueError("stress_region contains no mesh nodes")
        if np.intersect1d(region, np.concatenate([support, *[ids for ids, _ in loads]])).size:
            raise ValueError("stress_region must exclude supports and loaded nodes (singular stresses)")
        materials = {"PART": {"E": p["young_mpa"], "nu": p["poisson"], "density_g_cm3": 1.0}}
        names = np.full(len(tets), "PART")
        deck = os.path.join(folder, label + ".inp")
        ccx.write_deck(deck, nodes, tets, materials=materials, element_material=names,
                       fixed_nodes=support, steps=[{"kind": "static", "loads": loads}])
        stem = ccx.run(deck, threads=1, timeout=180)
        disp, stress = ccx.frd_blocks(stem, "DISP"), ccx.frd_blocks(stem, "STRESS")
        if len(disp) != 1 or len(stress) != 1:
            raise RuntimeError("expected exactly one displacement and stress result")
        U, S = disp[0], stress[0]
        if U.shape != (len(nodes), 3) or S.shape != (len(nodes), 6) or not np.isfinite(U).all() or not np.isfinite(S).all():
            raise RuntimeError("incomplete or non-finite CalculiX results")
        residual = ccx.residual(nodes, tets, materials, names, None, U, F, held=support)
        force = sum(np.linalg.norm(f) for _, f in loads)
        error = float(np.max(residual)) / force
        if error > 0.005:
            raise RuntimeError(f"static equilibrium residual {error:.2%} exceeds 0.5% of applied load")
        displacement = float(np.linalg.norm(U, axis=1).max())
        if displacement > 0.02 * float(np.linalg.norm(part.extents)):
            raise RuntimeError("displacement exceeds 2% of part diagonal: small-deformation model not justified")
        answers.append({"mesh_mm": size, "elements": len(tets), "equilibrium_relative": error,
                        "displacement_mm": displacement, "stress_mpa": float(ccx.von_mises(S[region]).max())})
        evidence.extend([deck, stem + ".log", stem + ".frd"])
    if answers[1]["elements"] <= answers[0]["elements"]:
        raise RuntimeError("the finer mesh did not add elements")
    for key in ("displacement_mm", "stress_mpa"):
        a, b = (r[key] for r in answers)
        if b <= 0 or abs(a - b) / b > 0.05:
            raise RuntimeError(f"{key} did not agree within 5% on mesh refinement: {a:g}, {b:g}")
    summary = os.path.join(folder, "summary.json")
    with open(summary, "w", encoding="utf-8") as f:
        json.dump({"meshes": answers, "object": "exported STL", "stress_region": list(p["stress_region"])}, f, indent=2)
    evidence.append(summary)
    return answers[1], evidence
