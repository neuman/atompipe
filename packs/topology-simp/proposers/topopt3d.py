# SPDX-License-Identifier: Apache-2.0
"""fea.topopt3d — propose where a printed part's material should go, in 3D.

A proposer (PACK_FORMAT "Proposers"): it settles nothing. It reads a voxel
PROBLEM the project's model wrote (which cells must be solid, which must stay
empty, what each designable cell costs, the supports, the load cases), and
writes the density field that minimises the weighted compliance of those load
cases at the problem's material budget. The model turns the field into
geometry; the pack's evaluators then judge THAT geometry with a different
solver (CalculiX) and a different mesh — never this field.

Method: SIMP (penalty p = 3) with a density filter and a Heaviside projection,
updated by optimality criteria — Andreassen et al., "Efficient topology
optimization in MATLAB using 88 lines of code" (2011), in 3D as Liu & Tovar,
"An efficient 3D topology optimization code written in Matlab" (2014).
  * The filter is a cone of radius `rmin_mm` across and `rmin_z_mm` up and
    down (an ellipsoid; the same radius both ways when the problem omits
    `rmin_z_mm`). A larger `rmin_z_mm` lets members be thin across and deep.
  * The volume budget shrinks from 30 % of the designable volume to the
    target over the first 20 iterations. After that, the projection's
    sharpness beta doubles from 1 to 16: after 20 iterations at one beta, or
    after 10 once no design variable moves by 0.01.
  * The move limit tightens as beta grows (0.1, then 0.05 from beta 8, 0.025
    at 16). It halves when the objective zig-zags and grows back by 1.25x on
    every iteration that does not.
  * Symmetry: `D2` averages the field and its sensitivities over the mirror
    planes x = 0 and y = 0, so load cases placed at one corner design all four;
    `D4` also mirrors them across the diagonals (nx == ny). PETGasus uses D2.

The linear solves (_fe3d.Solver) are direct where memory allows: PARDISO
(optional, `pypardiso`) up to _fe3d.PARDISO_MAX_DOFS unknowns, SuperLU up to
150k without it. Larger problems use CG preconditioned by pyamg's
smoothed-aggregation multigrid, which raises rather than return an unconverged
answer. Matrix-free geometric multigrid (as in Amir, Aage & Lazarov, "On
multigrid-CG for efficient topology optimization", 2014) was tried first and
rejected: see _fe3d.Solver.

Usage (with the project as cwd, through `nopekit propose fea.topopt3d -- ...`):

    --problem build/topopt3d/problem.npz   the model's problem file (required)
    --variant NAME                         a label carried into the file names
    --iters N                              iteration cap (default 120)
    --warm FILE                            start from an earlier run's field (a proposal or a checkpoint)
    --c0-from FILE                         normalise the load cases by that run's starting compliances
    --checkpoint FILE                      the field every 10 iterations, within proposal output when hosted

A warm start takes the earlier run's beta. On the same problem (the same
problem hash: a checkpoint of this run, say) it resumes from that run's design
variables x and its c0. On another problem it starts from that run's projected
density rho, interpolated onto this grid, and first finds the design variables
whose field, under this problem's filter, reproduces it (optimise's rho0).
That run's x stands for a design only under the filter it was optimised with:
the 1.33 mm PETGasus refine, warm-started from the x of a 2 mm run filtered at
5.0 mm, began 63 % over its budget. This run's c0 then comes from its own
first iteration, unless --c0-from names a run (a proposal or a checkpoint)
whose c0 keeps that run's trade between the load cases.

Writes into $NOPEKIT_PROPOSAL_DIR (or --out): topopt3d-<variant>-<hash>.npz
(the field, its problem hash, the settings including c0 and the load case
names, the history), a .png preview and a .json summary. A checkpoint holds
rho, x, the grid, the problem hash and its info (beta, iteration, c0, load
case names).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

import numpy as np
from scipy import ndimage

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _fe3d as fe  # noqa: E402

EMIN = 1e-6
"""Modulus of an empty designable cell, relative to solid. 1e-3 lost (it cut
AMG-CG's iterations ~3x): a 14 mm deep region of empty cells at 1e-3 bends like
1.4 mm of solid plastic, and the PETGasus run left its motor seats floating in
that ghost plate rather than pay for real limbs under the props. At 1e-6 the
same region is worth 0.14 mm."""


def load_problem(path):
    z = np.load(path, allow_pickle=False)
    p = {k: z[k] for k in z.files}
    for k in ("nx", "ny", "nz"):
        if np.asarray(p[k]).shape != () or not np.isfinite(p[k]) or float(p[k]) != int(p[k]):
            raise ValueError(f"{k} must be an integer")
        p[k] = int(p[k])
    for k in ("h", "nu", "budget_mm3", "rmin_mm"):
        p[k] = float(p[k])
    p["rmin_z_mm"] = float(p["rmin_z_mm"]) if "rmin_z_mm" in p else p["rmin_mm"]
    p["symmetry"] = str(p["symmetry"])
    p["problem_hash"] = str(p["problem_hash"])
    p["load_names"] = [str(s) for s in p["load_names"]]
    validate_problem(p)
    return p


def validate_problem(p):
    """Reject malformed or inconsistent boundary data before allocating a solver.

    Loads on omitted or fixed nodes otherwise disappear from the reduced system.
    Symmetrising a design with asymmetric keep-outs silently overwrites its intent.
    """
    for k in ("nx", "ny", "nz"):
        if p[k] <= 0:
            raise ValueError(f"{k} must be positive")
    shape = (p["nz"], p["ny"], p["nx"])
    count = int(np.prod(shape))
    for k in ("h", "rmin_mm", "rmin_z_mm", "budget_mm3"):
        if not np.isfinite(p[k]) or p[k] <= 0:
            raise ValueError(f"{k} must be finite and positive")
    if not np.isfinite(p["nu"]) or not -1 < p["nu"] < .5:
        raise ValueError("nu must lie strictly between -1 and 0.5")
    if np.asarray(p["origin"]).shape != (3,) or not np.isfinite(p["origin"]).all():
        raise ValueError("origin must be a finite 3-vector")
    for k in ("region", "erel", "cost"):
        if p[k].size != count or not np.isfinite(p[k]).all():
            raise ValueError(f"{k} must have one finite entry per cell")
    region = p["region"].reshape(shape)
    if not np.isin(region, [0, 1, 2]).all() or not (region == 0).any():
        raise ValueError("region must use 0/1/2 and include designable cells")
    if (p["erel"].ravel()[region.ravel() != 2] <= 0).any() or (p["cost"].ravel()[region.ravel() == 0] <= 0).any():
        raise ValueError("active moduli and designable costs must be positive")
    available = float(p["cost"].ravel()[region.ravel() == 0].sum() * p["h"] ** 3)
    if p["budget_mm3"] > available:
        raise ValueError("budget exceeds the cost-weighted designable volume")
    if p["symmetry"] not in ("none", "D2", "D4") or (p["symmetry"] == "D4" and p["nx"] != p["ny"]):
        raise ValueError("symmetry must be none, D2, or D4 on a square XY grid")
    if p["symmetry"] != "none":
        sym = d2 if p["symmetry"] == "D2" else d4
        for k in ("region", "erel", "cost"):
            a = p[k].reshape(shape)
            if not np.allclose(a, sym(a), rtol=0, atol=1e-12):
                raise ValueError(f"{k} conflicts with requested symmetry")
    nn = (p["nx"] + 1) * (p["ny"] + 1) * (p["nz"] + 1)
    fixed = np.asarray(p["fixed_nodes"])
    if fixed.ndim != 1 or fixed.dtype.kind not in "iu" or fixed.size < 3 or (fixed < 0).any() or (fixed >= nn).any():
        raise ValueError("fixed_nodes needs at least three valid integer node ids")
    live = np.unique(fe.element_dofs(p["nx"], p["ny"], p["nz"])[region.ravel() != 2] // 3)
    if not np.isin(fixed, live).all():
        raise ValueError("fixed node is outside active material")
    xyz = np.array([fixed % (p["nx"] + 1), (fixed // (p["nx"] + 1)) % (p["ny"] + 1), fixed // ((p["nx"] + 1) * (p["ny"] + 1))]).T
    if np.linalg.matrix_rank(xyz - xyz[0]) < 2:
        raise ValueError("fixed nodes must restrain rigid rotation")
    weights = np.asarray(p["load_weights"])
    if not p["load_names"] or weights.shape != (len(p["load_names"]),) or not np.isfinite(weights).all() or (weights <= 0).any():
        raise ValueError("each load case needs a positive finite weight")
    for i, _ in enumerate(p["load_names"]):
        dofs, vals = p[f"load_{i}_dofs"], p[f"load_{i}_vals"]
        if dofs.ndim != 1 or dofs.dtype.kind not in "iu" or vals.shape != dofs.shape or not dofs.size or not np.isfinite(vals).all() or not np.any(vals):
            raise ValueError("load DOFs and finite nonzero forces must match")
        if (dofs < 0).any() or (dofs >= 3 * nn).any() or not np.isin(dofs // 3, live).all() or np.isin(dofs // 3, fixed).any():
            raise ValueError("load falls outside active free nodes")
        aggregated = np.zeros(3 * nn)
        np.add.at(aggregated, dofs, vals)
        if not np.any(aggregated):
            raise ValueError("load case cancels to zero")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", p["problem_hash"]):
        raise ValueError("problem_hash must be a filename-safe identifier")


def d2(a):
    """Average a (nz, ny, nx) field over the two mirror planes x = 0 and y = 0."""
    return (a + a[:, ::-1, :] + a[:, :, ::-1] + a[:, ::-1, ::-1]) / 4.0


def d4(a):
    """Average a (nz, ny, nx) field over the 8 symmetries of the square (nx == ny)."""
    t = np.swapaxes(a, 1, 2)
    return (a + a[:, ::-1, :] + a[:, :, ::-1] + a[:, ::-1, ::-1]
            + t + t[:, ::-1, :] + t[:, :, ::-1] + t[:, ::-1, ::-1]) / 8.0


def cone_kernel(r_cells, rz_cells=None):
    """The density filter's weights: a cone of radius r_cells across and rz_cells
    up and down (an ellipsoid; the same radius both ways by default). A larger
    rz lets members be thin across and still deep: blades."""
    rz_cells = r_cells if rz_cells is None else rz_cells

    def half(r):
        return int(np.ceil(r)) - 1 if float(r).is_integer() else int(np.floor(r))
    n, nz = half(r_cells), half(rz_cells)
    Z, Y, X = np.meshgrid(np.arange(-nz, nz + 1), np.arange(-n, n + 1), np.arange(-n, n + 1), indexing="ij")
    return np.maximum(0.0, 1.0 - np.sqrt((X / r_cells) ** 2 + (Y / r_cells) ** 2 + (Z / rz_cells) ** 2))


def project(x, beta, eta=0.5):
    if beta <= 0:
        return x, np.ones_like(x)
    a, b = np.tanh(beta * eta), np.tanh(beta * (1 - eta))
    t = np.tanh(beta * (x - eta))
    return (a + t) / (a + b), beta * (1 - t ** 2) / (a + b)


def preview_png(path, rho, p, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    top = rho.max(axis=0)
    side = rho.max(axis=1)
    h = p["h"]
    fig, ax = plt.subplots(1, 2, figsize=(11, 5.2), gridspec_kw={"width_ratios": [1, 1]})
    ext = [p["origin"][0], p["origin"][0] + p["nx"] * h, p["origin"][1], p["origin"][1] + p["ny"] * h]
    ax[0].imshow(top, origin="lower", extent=ext, cmap="Greys", vmin=0, vmax=1)
    ax[0].set_title("top (max over z)")
    ext2 = [p["origin"][0], p["origin"][0] + p["nx"] * h, p["origin"][2], p["origin"][2] + p["nz"] * h]
    ax[1].imshow(side, origin="lower", extent=ext2, cmap="Greys", vmin=0, vmax=1, aspect="auto")
    ax[1].set_title("side (max over y)")
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def optimise(p, iters=120, penal=3.0, move=0.1, log=print, x0=None, beta0=1.0, vol_start=0.3, vol_iters=20,
             every10=None, c0=None, rho0=None):
    """The run. Returns (rho, x, history, info).

    It starts cold (x0 and rho0 None), from design variables `x0` (this
    problem's own: a resume), or from a physical design `rho0` (another
    problem's field, on this grid), whose design variables it finds first.
    `every10(it, x, rho, beta, c0)` is called every 10 iterations (a
    checkpoint). `c0`, one compliance per load case, normalises the objective
    (None: this run's first iteration's)."""
    validate_problem(p)
    if iters < 1:
        raise ValueError("iters must be positive")
    if c0 is not None and (not np.isfinite(c0).all() or np.any(np.asarray(c0) <= 0)):
        raise ValueError("starting compliances must be finite and positive")
    if c0 is not None and len(c0) != len(p["load_names"]):
        raise ValueError(f"c0 has {len(c0)} entries for {len(p['load_names'])} load cases: it is from another problem")
    nx, ny, nz, h = p["nx"], p["ny"], p["nz"], p["h"]
    shape = (nz, ny, nx)
    region = p["region"].reshape(shape)
    design, solid, void = region == 0, region == 1, region == 2
    erel = p["erel"].reshape(shape).astype(float)
    cost = p["cost"].reshape(shape).astype(float)
    v_el = h ** 3

    solver = fe.Solver(nx, ny, nz, h, p["nu"], (~void).ravel(), p["fixed_nodes"].astype(np.int64))
    loads = []
    for k, name in enumerate(p["load_names"]):
        f = np.zeros(solver.n)
        np.add.at(f, p[f"load_{k}_dofs"].astype(np.int64), p[f"load_{k}_vals"])
        loads.append(f)
    weights = p["load_weights"].astype(float)

    kern = cone_kernel(p["rmin_mm"] / h, p["rmin_z_mm"] / h)
    Hs = ndimage.correlate(np.ones(shape), kern, mode="constant", cval=0.0)

    def filt(a):
        return ndimage.correlate(a, kern, mode="constant", cval=0.0) / Hs

    def filt_t(g):
        return ndimage.correlate(g / Hs, kern, mode="constant", cval=0.0)

    sym = {"D4": d4, "D2": d2}.get(p["symmetry"])
    budget = p["budget_mm3"]
    dvol = (cost * v_el)[design].sum()
    x = np.zeros(shape)
    x[solid] = 1.0
    # volume continuation: start well above the budget and shrink to it over
    # vol_iters iterations. Started AT a 2 % budget, every cell is nearly empty,
    # the stiffness matrix nearly singular, and CG made no progress in 400
    # iterations (63 s) where a 30 % start needs 21 (3.7 s). A warm start is
    # already a design: it starts at the budget.
    warm = x0 is not None or rho0 is not None
    start = max(budget, vol_start * dvol) if not warm else budget
    x[design] = min(0.9, start / dvol) if not warm else (x0 if x0 is not None else np.clip(rho0, 0.0, 1.0))[design]

    def budget_at(it):
        if it >= vol_iters or start <= budget:
            return budget
        return start * (budget / start) ** (it / vol_iters)

    def physical(xx, beta):
        xt = filt(xx)
        xb, dproj = project(xt, beta)
        xb = np.where(solid, 1.0, np.where(void, 0.0, xb))
        return xb, dproj

    def used(xb):
        return float((cost * v_el * xb)[design].sum())

    if rho0 is not None:
        # The design variables whose field, under THIS filter at the starting
        # beta, reproduces rho0: a damped fixed point, x <- x + 0.2 (rho0 - H(x)).
        # Taken as x itself, rho0 is eroded by the filter and the projection: the
        # 1.33 mm PETGasus refine (rmin 3.5 mm, beta 16), started from the 2 mm
        # run's rho, cost 2,558 cost-weighted mm^3 against its 9,375 budget, where
        # 60 steps of this give 9,025, correlating 0.96 with the 2 mm design
        # (rho0 as x: 0.64; the 2 mm run's own x, as before: 15,305 and 0.89).
        # 0.6 s at 1.33 mm.
        target = np.where(solid, 1.0, np.where(void, 0.0, np.clip(rho0, 0.0, 1.0)))
        for _ in range(60):
            x[design] = np.clip(x + 0.2 * (target - physical(x, beta0)[0]), 0.0, 1.0)[design]
        if sym:
            x = sym(x)

    beta, beta_max = beta0, 16.0
    move_k = move
    since_beta = 0
    us = [None] * len(loads)
    # c0, each case's compliance at the start of the run, normalises the objective;
    # a continuation reuses its parent's, or it would quietly re-weight the cases
    c0 = list(c0) if c0 is not None else None
    hist = []
    t_start = time.time()
    for it in range(iters):
        t0 = time.time()
        xb, dproj = physical(x, beta)
        E = np.where(void, 0.0, np.where(solid, erel, EMIN + xb ** penal * (1 - EMIN)))
        solver.set_E(E.ravel())
        cs, dc = [], np.zeros(shape)
        cg_its = []
        for k, f in enumerate(loads):
            u, n_it, res = solver.solve(f, x0=us[k], tol=1e-5 if beta >= 8 else (1e-4 if it >= vol_iters else 1e-3))
            us[k] = u
            cg_its.append(n_it)
            ck = float(f @ u)
            cs.append(ck)
            ce = np.empty(nx * ny * nz)
            fe.element_energy(u, solver.edofs, solver.KE, ce)
            ce = ce.reshape(shape)
            dc_k = -penal * xb ** (penal - 1) * (1 - EMIN) * ce
            dc += weights[k] * dc_k / (c0[k] if c0 else ck)
        if c0 is None:
            c0 = list(cs)
        obj = float(sum(w * c / c_ for w, c, c_ in zip(weights, cs, c0)))
        dc = np.where(design, dc, 0.0)
        dv = np.where(design, cost * v_el, 0.0)
        dcx = filt_t(dc * dproj)
        dvx = filt_t(dv * dproj)
        if sym:
            dcx, dvx = sym(dcx), sym(dvx)
        dcx = np.minimum(dcx, -1e-30)
        dvx = np.maximum(dvx, 1e-30)

        # move limit: smaller as the projection sharpens, halved when the objective
        # zig-zags, and grown back by 1.25x on every iteration that does not. A
        # fixed 0.1 at beta 16 flipped the same cells on and off every iteration
        # (objective 41.5, 51.1, 41.5, ...) and the run stopped on whichever half
        # it reached last. Halving alone never recovered: the objective also rises
        # while the budget shrinks and after every beta step, and the 2 mm run
        # 'petg-mid' reached beta 16 at move 0.0063, a quarter of its cap, still
        # falling ~4 % an iteration when the iteration cap stopped it.
        cap = move if beta < 8 else (move / 2 if beta < 16 else move / 4)
        if len(hist) >= 2 and obj > hist[-1]["obj"] and hist[-1]["obj"] < hist[-2]["obj"]:
            move_k = max(0.005, move_k * 0.5)
        else:
            move_k *= 1.25
        move_k = min(move_k, cap)
        lo, hi = 1e-20, 1e20
        xd = x[design]
        ratio = (-dcx / dvx)[design]
        for _ in range(60):
            lam = np.sqrt(lo * hi)
            xn = np.clip(xd * np.sqrt(ratio / lam), np.maximum(0, xd - move_k), np.minimum(1, xd + move_k))
            trial = x.copy()
            trial[design] = xn
            if sym:
                trial = sym(trial)
            if used(physical(trial, beta)[0]) > budget_at(it):
                lo = lam
            else:
                hi = lam
            if hi / lo < 1 + 1e-4:
                break
        change = float(np.abs(trial[design] - xd).max())
        x = trial
        since_beta += 1
        rec = {"it": it, "obj": round(obj, 5), "c": [round(c / c_, 4) for c, c_ in zip(cs, c0)], "move": round(move_k, 4),
               "used_mm3": round(used(physical(x, beta)[0]), 1), "beta": beta, "change": round(change, 4),
               "cg": cg_its, "s": round(time.time() - t0, 1)}
        hist.append(rec)
        log(json.dumps(rec))
        if every10 and it % 10 == 9:
            every10(it, x, physical(x, beta)[0], beta, c0)
        if it >= vol_iters and beta < beta_max and (since_beta >= 20 or (change < 0.01 and since_beta >= 10)):
            beta *= 2
            since_beta = 0
        elif beta >= beta_max and change < 0.005 and since_beta >= 10 and it >= vol_iters:
            break
    xb, _ = physical(x, beta)
    return xb.astype(np.float32), x.astype(np.float32), hist, {"c0": c0, "seconds": round(time.time() - t_start, 1),
                                                               "beta": beta, "penal": penal, "move": move,
                                                               "emin": EMIN}


def warm_field(path, p):
    """A previous run's field (a proposal or a checkpoint), on this problem's
    grid, to start from. Returns (field, beta, c0, which): the run's beta, its
    c0 when it solved this same problem (else None), and which field it is.

    The same problem (hash): its design variables x ("x", optimise's x0), so a
    checkpoint resumes from the same design (x as float16), beta and c0; the
    move limit, iteration count and history restart. Another problem (a finer grid, another filter
    radius, other cases): its projected density rho ("rho", optimise's rho0),
    interpolated and clipped to [0, 1]. The design is H(filt(x)), so x stands
    for it only under the filter it was optimised with: the 1.33 mm PETGasus
    refine (rmin 3.5 mm), started from the x of a 2 mm run filtered at 5.0 mm,
    began at 15,305 cost-weighted mm^3 against a 9,375 budget."""
    from scipy.ndimage import map_coordinates
    z = np.load(path, allow_pickle=False)
    info = json.loads(str(z["info"]))
    same = str(z["problem_hash"]) == p["problem_hash"]
    which = "x" if same else "rho"
    src = z[which].astype(float).reshape(int(z["nz"]), int(z["ny"]), int(z["nx"]))
    so, sh = z["origin"].astype(float), float(z["h"])
    nx, ny, nz, h = p["nx"], p["ny"], p["nz"], p["h"]
    k, j, i = np.meshgrid(np.arange(nz), np.arange(ny), np.arange(nx), indexing="ij")
    cx = (p["origin"][0] + (i + 0.5) * h - so[0]) / sh - 0.5
    cy = (p["origin"][1] + (j + 0.5) * h - so[1]) / sh - 0.5
    cz = (p["origin"][2] + (k + 0.5) * h - so[2]) / sh - 0.5
    x0 = np.clip(map_coordinates(src, [cz, cy, cx], order=1, mode="nearest"), 0.0, 1.0)
    return x0, info["beta"], (info.get("c0") if same else None), which


def read_c0(path, p):
    """The c0 a proposal or a checkpoint saved (each load case's compliance at its
    run's start), checked against this problem's load cases: by name where the
    file records them, by count where it predates that."""
    info = json.loads(str(np.load(path, allow_pickle=False)["info"]))
    c0 = info.get("c0")
    if not c0:
        raise SystemExit(f"--c0-from {path}: it holds no c0 (a checkpoint written before checkpoints kept it)")
    if len(c0) != len(p["load_names"]):
        raise SystemExit(f"--c0-from {path}: {len(c0)} load cases, where this problem has {len(p['load_names'])}")
    names = info.get("load_names")
    if names is not None and list(names) != p["load_names"]:
        raise SystemExit(f"--c0-from {path}: its load cases {names} are not this problem's {p['load_names']}")
    return [float(c) for c in c0]


def _checkpoint(path, x, xb, p, it, beta, c0):
    tmp = path + ".tmp.npz"
    info = {"beta": beta, "iteration": it, "variant": "checkpoint", "c0": c0, "load_names": p["load_names"]}
    np.savez_compressed(tmp, rho=xb.astype(np.float16), x=x.astype(np.float16), region=p["region"],
                        problem_hash=p["problem_hash"], nx=p["nx"], ny=p["ny"], nz=p["nz"], h=p["h"],
                        origin=p["origin"], info=json.dumps(info))
    os.replace(tmp, path)


def main(argv=None):
    ap = argparse.ArgumentParser(description="3D SIMP topology proposer")
    ap.add_argument("--problem", required=True)
    ap.add_argument("--variant", default="base")
    ap.add_argument("--iters", type=int, default=120)
    ap.add_argument("--warm", help="a previous run's .npz to start from (a proposal or a checkpoint; e.g. a "
                                   "coarser grid's): its x on the same problem, its rho on another")
    ap.add_argument("--checkpoint", help="write the current field every 10 iterations; hosted runs require a path inside proposal output")
    ap.add_argument("--c0-from", help="a run (a proposal or a checkpoint) whose starting compliances normalise this "
                                      "one's objective: a finer grid warm-started from a coarse run keeps the coarse "
                                      "run's trade between load cases, instead of re-weighting them by how well the "
                                      "coarse design already serves each")
    ap.add_argument("--out", default=os.environ.get("NOPEKIT_PROPOSAL_DIR"))
    a = ap.parse_args(argv)
    if not a.out:
        ap.error("no output directory: run through `nopekit propose`, or pass --out")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", a.variant):
        ap.error("variant must contain only letters, digits, underscores and hyphens")
    hosted = os.environ.get("NOPEKIT_PROPOSAL_DIR")
    if hosted and os.path.realpath(a.out) != os.path.realpath(hosted):
        ap.error("--out must be NOPEKIT_PROPOSAL_DIR when run by Nopekit")
    if hosted and a.checkpoint and os.path.commonpath([os.path.realpath(a.checkpoint), os.path.realpath(hosted)]) != os.path.realpath(hosted):
        ap.error("a hosted checkpoint must stay inside NOPEKIT_PROPOSAL_DIR")
    os.makedirs(a.out, exist_ok=True)
    p = load_problem(a.problem)
    field, beta0, c0, which = (None, 1.0, None, None) if not a.warm else warm_field(a.warm, p)
    x0, rho0 = (field, None) if which == "x" else (None, field)
    if a.c0_from:
        c0 = read_c0(a.c0_from, p)
    elif a.warm and c0 is None:
        print(f"warm start from {os.path.basename(a.warm)} ({which}) without its c0: the load cases are normalised "
              f"by this run's first iteration; --c0-from keeps the earlier run's trade between them",
              file=sys.stderr, flush=True)
    cb = (lambda it, x, xb, beta, c0_: _checkpoint(a.checkpoint, x, xb, p, it, beta, c0_)) if a.checkpoint else None
    rho, x, hist, info = optimise(p, iters=a.iters, log=lambda s: print(s, flush=True), x0=x0, beta0=beta0,
                                  every10=cb, c0=c0, rho0=rho0)
    info["warm"] = os.path.basename(a.warm) if a.warm else None
    info["warm_field"] = which
    info["c0_from"] = os.path.basename(a.c0_from) if a.c0_from else None
    info["load_names"] = p["load_names"]
    stem = os.path.join(a.out, f"topopt3d-{a.variant}-{p['problem_hash'][:10]}")
    np.savez_compressed(stem + ".npz", rho=rho.astype(np.float16), x=x.astype(np.float16), region=p["region"],
                        problem_hash=p["problem_hash"],
                        variant=a.variant, history=json.dumps(hist), info=json.dumps(info),
                        nx=p["nx"], ny=p["ny"], nz=p["nz"], h=p["h"], origin=p["origin"])
    preview_png(stem + ".png", rho, p, f"topopt3d {a.variant}: {len(hist)} iterations, objective {hist[-1]['obj']}")
    with open(stem + ".json", "w") as fh:
        json.dump({"variant": a.variant, "problem_hash": p["problem_hash"], "iterations": len(hist),
                   "final": hist[-1], **info}, fh, indent=1, sort_keys=True)
    print(f"wrote {stem}.npz")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
