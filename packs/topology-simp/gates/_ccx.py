# SPDX-License-Identifier: Apache-2.0
"""CalculiX through gmsh: mesh a closed surface into quadratic tetrahedra, write a
CalculiX deck, run `ccx`, read back displacements, stresses and frequencies.

Units throughout: mm, N, MPa, tonne/mm^3 (so 1 g/cm^3 = 1e-9), s, Hz.

Nothing here judges anything: a project's evaluators call it and compare its
answers with the claims' limits. What it can get wrong quietly, and how each is
guarded:
  * the mesh — `mesh_surface` refuses a mesh with sliver tets or tets far over
    the asked size (QUALITY_MIN, EDGE_MAX_X), retrying gmsh with tighter
    targets; evaluators should rerun on a finer surface and mesh and refuse
    a result that moves;
  * the solve — the equation solver runs on one thread (multithreaded, this
    build's SPOOLES returned solutions out of equilibrium), and `residual`
    measures any static solve's equilibrium against a stiffness built here;
  * units — densities are converted here, once, from g/cm^3;
  * the solve — `run` refuses a run whose .dat/.frd is missing or whose log
    reports an error, never returning partial numbers.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess

import numpy as np

# gmsh's 10-node tetrahedron numbers its edge nodes in a different order from
# CalculiX's C3D10 (gmsh: 0-1, 1-2, 2-0, 0-3, 2-3, 1-3; ccx: 0-1, 1-2, 2-0,
# 0-3, 1-3, 2-3): swap the last two.
_GMSH_TO_CCX_TET10 = [0, 1, 2, 3, 4, 5, 6, 7, 9, 8]


def find_ccx() -> str | None:
    """`ccx` on the PATH (the distribution's calculix-ccx installs it there)."""
    for name in ("ccx", "ccx_2.21", "ccx_2.22", "ccx_2.20"):
        path = shutil.which(name)
        if path:
            return path
    return None


def mesh_surface(stl_path: str, size: float, order: int = 2):
    """Quadratic tetrahedra of the exported surface. Each retry starts clean.

    Try the original facets, then remesh classified surfaces at 180 and 40
    degrees with progressively tighter size targets. Every candidate still
    meets the original edge and quality limits. No surface-changing fallback:
    a surface that cannot be meshed is an error, never a substituted part.
    Returns nodes (n,3), tets (m,10), zero-based in CalculiX order.
    """
    errors = []
    # Gmsh's size is a target, not a maximum edge: leave 20%, then 40%
    # headroom rather than relaxing the edge and quality checks after a failure.
    for attempt, factor in (("direct", 1.0), (180.0, 0.8), (40.0, 0.8), (40.0, 0.6)):
        try:
            nodes, tets = _mesh_once(stl_path, size * factor, order, attempt)
            _check_mesh(nodes, tets, size)
            return nodes, tets
        except Exception as exc:
            errors.append(f"{attempt} at {factor}x: {exc}")
    raise RuntimeError("no mesher could mesh the surface: " + "; ".join(errors))


#: A tet's quality, 6 sqrt(2) V / Lmax^3: 1 for a regular one, 0 for a flat one.
#: Below this a quadratic tet's stresses and the solve both go wrong: gmsh's
#: 'direct' mesh of the v0.2 frame held tets at 0.004-0.009, where a corrupted
#: solve put 124 N of error and the crash check read its 'peak'.
QUALITY_MIN = 0.02

#: Longest tet edge allowed, x the asked size. gmsh's 'direct' attempt fills the
#: surface's own triangles, and a simplified level set has 4 mm triangles on its
#: flat faces whatever `size` says, so its 'fine' mesh was no finer there.
EDGE_MAX_X = 2.0


def tet_quality(nodes, tets):
    """6 sqrt(2) V / Lmax^3 per tet (corner nodes)."""
    t4 = tets[:, :4]
    p = nodes[t4]
    edges = np.stack([p[:, j] - p[:, i] for i, j in ((0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3))], axis=1)
    lmax = np.linalg.norm(edges, axis=2).max(axis=1)
    return 6 * np.sqrt(2) * tet_volumes(nodes, t4) / lmax ** 3, lmax


def _check_mesh(nodes, tets, size):
    q, lmax = tet_quality(nodes, tets)
    if q.min() < QUALITY_MIN:
        raise RuntimeError(f"{int((q < QUALITY_MIN).sum())} sliver tets (quality down to {q.min():.4f}, "
                           f"floor {QUALITY_MIN})")
    if lmax.max() > EDGE_MAX_X * size:
        raise RuntimeError(f"tets up to {lmax.max():.2f} mm, over {EDGE_MAX_X} x the {size} mm asked")


def _mesh_once(stl_path, size, order, attempt):
    import gmsh
    gmsh.initialize(["-noenv"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.option.setNumber("General.NumThreads", 1)
        gmsh.merge(stl_path)
        if attempt != "direct":
            gmsh.model.mesh.classifySurfaces(np.radians(attempt), True, True, np.pi)
            gmsh.model.mesh.createGeometry()
        surfs = [s[1] for s in gmsh.model.getEntities(2)]
        loop = gmsh.model.geo.addSurfaceLoop(surfs)
        gmsh.model.geo.addVolume([loop])
        gmsh.model.geo.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size * 0.25)
        gmsh.option.setNumber("Mesh.Algorithm3D", 1)            # Delaunay
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)      # straight-sided: no inverted curved tets
        gmsh.model.mesh.generate(3)
        return _read_tets(gmsh)
    finally:
        gmsh.finalize()


def mesh_box(lx: float, ly: float, lz: float, size: float, order: int = 2):
    """A box from the origin to (lx, ly, lz), for smoke tests."""
    import gmsh
    gmsh.initialize(["-noenv"])
    try:
        gmsh.option.setNumber("General.Terminal", 0)
        gmsh.model.occ.addBox(0, 0, 0, lx, ly, lz)
        gmsh.model.occ.synchronize()
        gmsh.option.setNumber("Mesh.MeshSizeMax", size)
        gmsh.option.setNumber("Mesh.MeshSizeMin", size * 0.5)
        gmsh.option.setNumber("Mesh.ElementOrder", order)
        gmsh.option.setNumber("Mesh.SecondOrderLinear", 1)
        gmsh.model.mesh.generate(3)
        return _read_tets(gmsh)
    finally:
        gmsh.finalize()


def _read_tets(gmsh):
    tags, coords, _ = gmsh.model.mesh.getNodes()
    order = np.argsort(tags)
    tags = tags[order]
    xyz = coords.reshape(-1, 3)[order]
    index = {int(t): i for i, t in enumerate(tags)}
    etypes, _, enodes = gmsh.model.mesh.getElements(3)
    tets = None
    for et, en in zip(etypes, enodes):
        if et == 11:                                            # 10-node tetrahedron
            tets = np.array([index[int(t)] for t in en], dtype=np.int64).reshape(-1, 10)
    if tets is None or not len(tets):
        raise RuntimeError("gmsh produced no 10-node tetrahedra: the surface did not close into a volume")
    tets = tets[:, _GMSH_TO_CCX_TET10]
    used = np.unique(tets)
    remap = np.full(len(xyz), -1, np.int64)
    remap[used] = np.arange(used.size)
    return xyz[used], remap[tets]


def tet_volumes(nodes, tets):
    a, b, c, d = (nodes[tets[:, k]] for k in range(4))
    return np.einsum("ij,ij->i", np.cross(b - a, c - a), d - a) / 6.0


def write_deck(path, nodes, tets, *, materials, element_material, steps, fixed_nodes=(),
               point_masses=(), orientation=None, boundary=()):
    """A CalculiX input deck.

    materials: {name: dict(E, nu, density_g_cm3) | dict(E1, E2, E3, nu12, nu13, nu23,
               G12, G13, G23, density_g_cm3)} — the second form is transversely
               isotropic, its axis 3 along `orientation`'s local z.
    element_material: (m,) array of material names, one per tet.
    steps: list of dict(kind='static', loads=[(node_ids, (fx, fy, fz))...]) or
           dict(kind='frequency', n=10, lower_hz=-1.0).
    fixed_nodes: node ids (0-based) held in x, y and z.
    boundary: [(node_id, first_dof, last_dof)] held in some directions only (dof
              1 x, 2 y, 3 z): a statically determinate hold, for a free body
              whose loads balance (inertia relief).
    point_masses: [(node_ids, mass_g)]: the mass shared evenly over the nodes.
    Each static step's loads REPLACE the last step's (*CLOAD, OP=NEW): CalculiX's
    default keeps every earlier step's loads on, so a second load case carried
    the first one's too.
    orientation: (a, b) two 3-vectors: local x along a, local xy-plane holds b.
    """
    lines = ["*HEADING", "written by solid-fea _ccx.write_deck", "*NODE"]
    lines += [f"{i + 1},{x:.6f},{y:.6f},{z:.6f}" for i, (x, y, z) in enumerate(nodes)]
    names = sorted(set(element_material))
    eid = 1
    for name in names:
        sel = np.nonzero(np.asarray(element_material) == name)[0]
        lines.append(f"*ELEMENT,TYPE=C3D10,ELSET=E{name}")
        for e in sel:
            lines.append(f"{eid}," + ",".join(str(int(n) + 1) for n in tets[e]))
            eid += 1
    mass_lines = []
    for k, (nids, mass_g) in enumerate(point_masses):
        nids = np.asarray(nids, dtype=np.int64)
        if not len(nids):
            raise ValueError(f"point mass {k} has no nodes")
        lines.append(f"*ELEMENT,TYPE=MASS,ELSET=PM{k}")
        for n in nids:
            lines.append(f"{eid},{int(n) + 1}")
            eid += 1
        mass_lines += [f"*MASS,ELSET=PM{k}", f"{mass_g / 1e6 / len(nids):.6e}"]     # g -> tonne
    if len(fixed_nodes):
        lines.append("*NSET,NSET=NFIX")
        lines += _chunks([int(n) + 1 for n in fixed_nodes])
    if orientation is not None:
        a, b = orientation
        lines.append("*ORIENTATION,NAME=ORI,SYSTEM=RECTANGULAR")
        lines.append(",".join(f"{v:.6f}" for v in (*a, *b)))
    for name in names:
        m = materials[name]
        lines.append(f"*MATERIAL,NAME={name}")
        if "E1" in m:
            lines.append("*ELASTIC,TYPE=ENGINEERING CONSTANTS")
            lines.append(",".join(f"{m[k]:.6g}" for k in ("E1", "E2", "E3", "nu12", "nu13", "nu23", "G12", "G13")))
            lines.append(f"{m['G23']:.6g},293.")
        else:
            lines += ["*ELASTIC", f"{m['E']:.6g},{m['nu']:.6g}"]
        lines += ["*DENSITY", f"{m['density_g_cm3'] * 1e-9:.6e}"]
        ori = ",ORIENTATION=ORI" if (orientation is not None and "E1" in m) else ""
        lines.append(f"*SOLID SECTION,ELSET=E{name},MATERIAL={name}{ori}")
    lines += mass_lines
    if len(fixed_nodes):
        lines += ["*BOUNDARY", "NFIX,1,3"]
    if len(boundary):
        lines.append("*BOUNDARY")
        lines += [f"{int(n) + 1},{int(a)},{int(b)}" for n, a, b in boundary]
    for st in steps:
        if st["kind"] == "static":
            lines += ["*STEP", "*STATIC", "*CLOAD,OP=NEW"]
            for nids, (fx, fy, fz) in st["loads"]:
                nids = np.asarray(nids, dtype=np.int64)
                for n in nids:
                    for dof, f in ((1, fx), (2, fy), (3, fz)):
                        if f:
                            lines.append(f"{int(n) + 1},{dof},{f / len(nids):.6e}")
            lines += ["*NODE FILE", "U", "*EL FILE", "S", "*END STEP"]
        elif st["kind"] == "frequency":
            lines += ["*STEP", "*FREQUENCY", f"{st.get('n', 10)},{st.get('lower_hz', -1.0)}",
                      "*NODE FILE", "U", "*END STEP"]
        else:
            raise ValueError(st["kind"])
    with open(path, "w") as fh:
        fh.write("\n".join(lines) + "\n")


def _chunks(ids, per=16):
    return [",".join(str(i) for i in ids[k:k + per]) for k in range(0, len(ids), per)]


def run(deck_path, ccx=None, timeout=1800, threads=None):
    """Run ccx on `deck_path` (.inp). Returns the job stem. Raises with the log's
    tail on any failure: a partial result is never returned."""
    ccx = ccx or find_ccx()
    if not ccx:
        raise FileNotFoundError("ccx (CalculiX) not found on PATH")
    work, name = os.path.split(os.path.abspath(deck_path))
    stem = name[:-4] if name.endswith(".inp") else name
    # The solver's environment is stated, never copied from ours: a gate that
    # reads the environment has an input no cache key sees (nopekit doctor).
    n = str(threads or os.cpu_count() or 1)
    # The equation solver runs on ONE thread. Multithreaded, this build's SPOOLES
    # returned static solutions out of equilibrium by up to 124 N, for a 1 N load,
    # round sliver tets, with no warning (PLA and TPU frames, wall cases); the same
    # deck single-threaded: 0.01 N, in 25 s. Assembly and stresses stay threaded.
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "OMP_NUM_THREADS": n, "CCX_NPROC_EQUATION_SOLVER": "1",
           "CCX_NPROC_STIFFNESS": n, "CCX_NPROC_RESULTS": n}
    # A successful exit with no new output must not inherit yesterday's FRD.
    # These are this job's generated scratch files, never model inputs.
    for suffix in (".frd", ".dat", ".sta", ".cvg", ".log"):
        previous = os.path.join(work, stem + suffix)
        if os.path.exists(previous):
            os.unlink(previous)
    proc = subprocess.run([ccx, "-i", stem], cwd=work, capture_output=True, text=True, timeout=timeout,
                          env=env, stdin=subprocess.DEVNULL)
    log = (proc.stdout or "") + (proc.stderr or "")
    with open(os.path.join(work, stem + ".log"), "w") as fh:
        fh.write(log)
    bad = re.search(r"\*ERROR.*", log)
    if proc.returncode != 0 or bad or not os.path.exists(os.path.join(work, stem + ".frd")):
        tail = " / ".join(l for l in log.strip().splitlines()[-6:])
        raise RuntimeError(f"ccx failed (exit {proc.returncode}): {bad.group(0) if bad else tail}")
    return os.path.join(work, stem)


def residual(nodes, tets, materials, element_material, orientation, U, F, held=()):
    """|K u - f| per node (N) for a static step's displacements U (n, 3) and
    loads F (n, 3), with K built here from the deck's own materials (4-point
    C3D10 integration), independent of the solver. `held`: node ids whose
    reactions are not residual. A sound solve leaves a few mN (the .frd's five
    digits); a corrupted one, newtons. Checked to 1e-7 mm against CalculiX's own
    K on the v0.2 frame (scratch review, 2026-10-17)."""
    pairs = [(0, 1), (1, 2), (0, 2), (0, 3), (1, 3), (2, 3)]
    R = None
    if orientation is not None:
        a = np.asarray(orientation[0], float)
        b = np.asarray(orientation[1], float)
        n3 = np.cross(a, b)
        R = np.stack([a, np.cross(n3, a), n3])                      # rows: local x, y, z in global terms
        R /= np.linalg.norm(R, axis=1, keepdims=True)

    def stiffness(m):
        if "E1" not in m:
            E, nu = m["E"], m["nu"]
            m = dict(E1=E, E2=E, E3=E, nu12=nu, nu13=nu, nu23=nu, G12=E / (2 * (1 + nu)),
                     G13=E / (2 * (1 + nu)), G23=E / (2 * (1 + nu)))
        Sm = np.zeros((6, 6))
        Sm[0, 0], Sm[1, 1], Sm[2, 2] = 1 / m["E1"], 1 / m["E2"], 1 / m["E3"]
        Sm[0, 1] = Sm[1, 0] = -m["nu12"] / m["E1"]
        Sm[0, 2] = Sm[2, 0] = -m["nu13"] / m["E1"]
        Sm[1, 2] = Sm[2, 1] = -m["nu23"] / m["E2"]
        Sm[3, 3], Sm[4, 4], Sm[5, 5] = 1 / m["G12"], 1 / m["G13"], 1 / m["G23"]
        return np.linalg.inv(Sm)                                    # Voigt: xx yy zz xy xz yz
    C = {name: stiffness(m) for name, m in materials.items()}
    Ce = np.stack([C[e] for e in element_material])
    xa, xb = 0.5854101966249685, 0.1381966011250105

    def shape_grads(xi, eta, ze):
        L = np.array([1 - xi - eta - ze, xi, eta, ze])
        dL = np.array([[-1, -1, -1], [1, 0, 0], [0, 1, 0], [0, 0, 1]], float)
        g = np.zeros((10, 3))
        for i in range(4):
            g[i] = (4 * L[i] - 1) * dL[i]
        for k, (i, j) in enumerate(pairs):
            g[4 + k] = 4 * (L[i] * dL[j] + L[j] * dL[i])
        return g
    xe, ue = nodes[tets], np.nan_to_num(U[:len(nodes)])[tets]
    fint = np.zeros((len(tets), 10, 3))
    for g in (shape_grads(xb, xb, xb), shape_grads(xa, xb, xb), shape_grads(xb, xa, xb), shape_grads(xb, xb, xa)):
        J = np.einsum("ni,mnj->mij", g, xe)
        det = np.linalg.det(J)
        Gx = np.einsum("ni,mji->mnj", g, np.linalg.inv(J))
        H = np.einsum("mnj,mni->mij", Gx, ue)                       # du_i/dx_j
        eps = 0.5 * (H + H.transpose(0, 2, 1))
        if R is not None:
            eps = np.einsum("ai,mij,bj->mab", R, eps, R)
        v = np.stack([eps[:, 0, 0], eps[:, 1, 1], eps[:, 2, 2], 2 * eps[:, 0, 1], 2 * eps[:, 0, 2],
                      2 * eps[:, 1, 2]], 1)
        sv = np.einsum("mab,mb->ma", Ce, v)
        st = np.stack([np.stack([sv[:, 0], sv[:, 3], sv[:, 4]], -1), np.stack([sv[:, 3], sv[:, 1], sv[:, 5]], -1),
                       np.stack([sv[:, 4], sv[:, 5], sv[:, 2]], -1)], -2)
        if R is not None:
            st = np.einsum("ai,mab,bj->mij", R, st, R)
        fint += np.einsum("mnj,mij->mni", Gx, st) * (det / 24)[:, None, None]
    r = np.zeros((len(nodes), 3))
    np.add.at(r, tets.ravel(), fint.reshape(-1, 3))
    res = np.linalg.norm(r - F, axis=1)
    res[np.asarray(held, dtype=np.int64)] = 0.0
    return res


def read_frd(stem):
    """[{'name': 'DISP'|'STRESS', 'step': k, 'values': {node: array}}] in file order."""
    out = []
    cur = None
    with open(stem + ".frd") as fh:
        for line in fh:
            if line.startswith("    1PSTEP"):
                step = int(line.split()[2]) if len(line.split()) > 2 else len(out)
            if line.startswith(" -4"):
                cur = {"name": line.split()[1], "values": {}, "step": None}
                out.append(cur)
            elif line.startswith(" -1") and cur is not None:
                node = int(line[3:13])
                vals = [float(line[13 + 12 * k: 25 + 12 * k]) for k in range((len(line.rstrip()) - 13) // 12)]
                cur["values"][node] = np.array(vals)
            elif line.startswith(" -3"):
                cur = None
    return out


def frd_blocks(stem, name):
    """Every block of one kind (e.g. 'DISP', 'STRESS') as (n_nodes_total, k) arrays,
    0-based by node, in step order."""
    blocks = [b for b in read_frd(stem) if b["name"] == name]
    res = []
    for b in blocks:
        n = max(b["values"]) if b["values"] else 0
        k = len(next(iter(b["values"].values()))) if b["values"] else 0
        arr = np.full((n, k), np.nan)
        for node, v in b["values"].items():
            arr[node - 1] = v
        res.append(arr)
    return res


def read_frequencies(stem):
    """Eigenfrequencies (Hz) from the .dat file, in order."""
    freqs = []
    with open(stem + ".dat") as fh:
        text = fh.read()
    m = re.search(r"E I G E N V A L U E   O U T P U T(.*?)(?:\n\s*\n\s*\n|P A R T I C I P|$)", text, re.S)
    if not m:
        return freqs
    for line in m.group(1).splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[0].isdigit():
            freqs.append(float(parts[3]))            # MODE NO, EIGENVALUE, (RAD/TIME), (CYCLES/TIME)
    return freqs


def von_mises(S):
    """S: (n, 6) xx, yy, zz, xy, yz, zx."""
    sxx, syy, szz, sxy, syz, szx = S.T
    return np.sqrt(0.5 * ((sxx - syy) ** 2 + (syy - szz) ** 2 + (szz - sxx) ** 2) + 3 * (sxy ** 2 + syz ** 2 + szx ** 2))


def normal_stress(S, n):
    """Normal stress on planes with unit normal n: n^T sigma n, per node."""
    n = np.asarray(n, float) / np.linalg.norm(n)
    sxx, syy, szz, sxy, syz, szx = S.T
    return (n[0] ** 2 * sxx + n[1] ** 2 * syy + n[2] ** 2 * szz
            + 2 * (n[0] * n[1] * sxy + n[1] * n[2] * syz + n[2] * n[0] * szx))


def principal_max(S):
    sxx, syy, szz, sxy, syz, szx = S.T
    T = np.stack([np.stack([sxx, sxy, szx], -1), np.stack([sxy, syy, syz], -1), np.stack([szx, syz, szz], -1)], -2)
    return np.linalg.eigvalsh(T)[:, -1]
