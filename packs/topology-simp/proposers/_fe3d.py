# SPDX-License-Identifier: Apache-2.0
"""3D linear elasticity on a structured grid of cubic hex8 elements. Solved
directly where memory allows (PARDISO through the optional `pypardiso` up to
PARDISO_MAX_DOFS unknowns, SuperLU up to 150k without it), and beyond that by
conjugate gradients preconditioned with smoothed-aggregation algebraic
multigrid (pyamg), which raises if it does not converge. See `Solver`.

Grid: nx * ny * nz elements of side h; element e = i + nx * (j + ny * k), node
n = i + (nx+1) * (j + (ny+1) * k), dof = 3 * n + component.

Smoke-tested against Timoshenko beam theory and a sparse direct solve, on both
the direct and the multigrid-CG path (see `selfcheck`). Elements whose modulus
is exactly 0 (passive void) are left out and every node only they touch is
dropped, so empty space costs nothing.
"""
from __future__ import annotations

import math

import numba as nb
import numpy as np
import scipy.sparse as sp
import scipy.sparse.linalg as spla

#: local node offsets of a hex8 (i, j, k)
OFF = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)], dtype=np.int64)


def hex8_ke(nu: float) -> np.ndarray:
    """24x24 stiffness of a unit cube with E = 1, by 2x2x2 Gauss quadrature.
    For a cube of side h, K = E * h * hex8_ke(nu)."""
    lam = nu / ((1 + nu) * (1 - 2 * nu))
    mu = 1 / (2 * (1 + nu))
    D = np.zeros((6, 6))
    D[:3, :3] = lam
    D[:3, :3] += 2 * mu * np.eye(3)
    D[3:, 3:] = mu * np.eye(3)
    g = np.array([0.5 - 0.5 / math.sqrt(3), 0.5 + 0.5 / math.sqrt(3)])
    KE = np.zeros((24, 24))
    for x in g:
        for y in g:
            for z in g:
                B = strain_matrix(x, y, z)
                KE += B.T @ D @ B / 8.0
    return KE


def strain_matrix(x: float, y: float, z: float) -> np.ndarray:
    """6x24 B of a unit cube at local point (x, y, z), Voigt order
    xx, yy, zz, xy, yz, zx (engineering shear)."""
    dN = np.zeros((8, 3))
    for a, (i, j, k) in enumerate(OFF):
        fx, fy, fz = (x if i else 1 - x), (y if j else 1 - y), (z if k else 1 - z)
        sx, sy, sz = (1 if i else -1), (1 if j else -1), (1 if k else -1)
        dN[a] = (sx * fy * fz, fx * sy * fz, fx * fy * sz)
    B = np.zeros((6, 24))
    for a in range(8):
        B[0, 3 * a] = dN[a, 0]
        B[1, 3 * a + 1] = dN[a, 1]
        B[2, 3 * a + 2] = dN[a, 2]
        B[3, 3 * a] = dN[a, 1]
        B[3, 3 * a + 1] = dN[a, 0]
        B[4, 3 * a + 1] = dN[a, 2]
        B[4, 3 * a + 2] = dN[a, 1]
        B[5, 3 * a] = dN[a, 2]
        B[5, 3 * a + 2] = dN[a, 0]
    return B


def element_dofs(nx: int, ny: int, nz: int) -> np.ndarray:
    """(n_el, 24) global dofs, elements ordered i fastest."""
    e = np.arange(nx * ny * nz)
    i, j, k = e % nx, (e // nx) % ny, e // (nx * ny)
    nodes = np.empty((e.size, 8), dtype=np.int64)
    for a, (di, dj, dk) in enumerate(OFF):
        nodes[:, a] = (i + di) + (nx + 1) * ((j + dj) + (ny + 1) * (k + dk))
    return (3 * nodes[:, :, None] + np.arange(3)[None, None, :]).reshape(-1, 24)


@nb.njit(parallel=True, fastmath=True, cache=False)
def element_energy(u, edofs, KE, out):
    """out[e] = u_e^T KE u_e (KE already scaled by h)."""
    for e in nb.prange(edofs.shape[0]):
        d = edofs[e]
        ue = np.empty(24)
        for p in range(24):
            ue[p] = u[d[p]]
        acc = 0.0
        for p in range(24):
            r = 0.0
            for q in range(24):
                r += KE[p, q] * ue[q]
            acc += ue[p] * r
        out[e] = acc


@nb.njit(parallel=True, fastmath=True, cache=False)
def _fill_bsr(data, indptr, indices, enodes, Ee, KE, rnode, colour_start, colour_idx):
    """data[block] += Ee[e] * KE[3a:3a+3, 3b:3b+3] for every live element e and
    node pair (a, b) whose nodes are both active; elements of one colour share no
    node, so each colour runs in parallel without races."""
    for c in range(8):
        for t in nb.prange(colour_start[c], colour_start[c + 1]):
            e = colour_idx[t]
            s = Ee[e]
            if s == 0.0:
                continue
            for a in range(8):
                ra = rnode[enodes[e, a]]
                if ra < 0:
                    continue
                lo, hi = indptr[ra], indptr[ra + 1]
                for b in range(8):
                    rb = rnode[enodes[e, b]]
                    if rb < 0:
                        continue
                    # binary search for column rb in row ra
                    l, r = lo, hi - 1
                    while l < r:
                        m = (l + r) // 2
                        if indices[m] < rb:
                            l = m + 1
                        else:
                            r = m
                    for i in range(3):
                        for j in range(3):
                            data[l, i, j] += s * KE[3 * a + i, 3 * b + j]


#: unknowns up to which a direct solve is used when PARDISO is available; larger
#: problems fall back to AMG-CG. A direct solver's factors on a 3D grid grow about
#: as n^(4/3). The PETGasus frame at 1.33 mm (364,596 unknowns) ran in about
#: 7 GB; at 1 mm (~840k, 3x that by the same scaling) PARDISO ran a 21 GB machine
#: out of memory, where the old limit (2M) sent it. 600k needs ~14 GB.
PARDISO_MAX_DOFS = 600_000


def _pardiso():
    """A PARDISO solver (real, nonsymmetric LU: mtype 11), or None without pypardiso."""
    try:
        import pypardiso
    except ImportError:
        return None
    try:
        return pypardiso.PyPardisoSolver(mtype=11)
    except ImportError:                     # pypardiso present, MKL's runtime not found
        return None


class Solver:
    """K(E) u = f on the grid, for many right-hand sides and many E fields.

    K is assembled straight into 3x3-block (BSR) form over the ACTIVE nodes only
    (a node every live element misses, or one the caller fixes, is dropped).

    Up to `direct_max_dofs` unknowns it is factorised (SuperLU, minimum-degree
    ordering on A+A^T): ~33 s at 81k unknowns, whatever the contrast, then each
    load case costs ~0.4 s. AMG-CG at that size took 95 s for seven cases once
    the members thinned (~150 iterations each), and the cure for that, a stiffer
    empty cell, let empty space carry load (topopt3d.EMIN). The default limit
    is 150k unknowns with SuperLU.

    With `pypardiso` importable (MKL's multithreaded PARDISO; optional, ~800 MB
    of MKL) the direct path uses it instead, and up to PARDISO_MAX_DOFS: at
    111k unknowns it factorised in 4.3 s where SuperLU took 64 s, to the same
    residual (3e-13). Its symmetric positive-definite mode (mtype 2) lost: a
    6e-4 residual. Same answers either way; only the time and memory differ.
    With PARDISO, a 2 mm PETGasus run (~112k unknowns, 13 load cases) took
    5.5 s an iteration, and a 1.33 mm one (~365k) 34 s and about 7 GB.

    Beyond the direct limit it is solved by CG preconditioned with pyamg's
    smoothed-aggregation multigrid, given the six rigid-body modes as its
    near-null space. `solve` raises if CG stops short of its tolerance (at
    `maxit`, or on a breakdown): an unconverged displacement gives wrong
    compliances and sensitivities, and the optimiser would act on them
    silently. The hierarchy is rebuilt every `reuse` set_E calls, by default
    every one: reusing it for 6 (a design that moved a little, the thinking
    went, is still preconditioned well by the last one) took CG from ~20 to
    ~180 iterations by the fourth optimisation step, 98 s against 15 s, while
    the setup costs ~2 s.

    *Rejected:* geometric multigrid, matrix-free, with rediscretised and then
    Galerkin coarse grids (the first version of this file). Both were fast per
    cycle and both failed on the real frame: guard hoops one cell thick, ringed
    by keep-outs, have no smooth coarse representation, and CG made no progress
    in 150 iterations where this converges in ~60 (2 mm grid, 125k dofs, 7 s).
    """

    def __init__(self, nx, ny, nz, h, nu, active_elements, fixed_nodes, reuse=1, direct_max_dofs=None):
        self.nx, self.ny, self.nz, self.h = nx, ny, nz, h
        self.n = 3 * (nx + 1) * (ny + 1) * (nz + 1)
        self.KE = np.ascontiguousarray(hex8_ke(nu) * h)
        self.edofs = element_dofs(nx, ny, nz)
        enodes = self.edofs[:, 0::3] // 3
        self.enodes = np.ascontiguousarray(enodes)
        nn = self.n // 3
        live = np.asarray(active_elements, bool)
        used = np.zeros(nn, bool)
        used[enodes[live].ravel()] = True
        used[np.asarray(fixed_nodes, np.int64)] = False
        self.rnode = np.full(nn, -1, np.int64)
        self.rnode[used] = np.arange(used.sum())
        self.active_nodes = np.nonzero(used)[0]
        self.nr = int(used.sum())
        # block sparsity: node pairs that share a live element, both active
        en = self.rnode[enodes[live]]
        rows = np.repeat(en, 8, axis=1).ravel()
        cols = np.tile(en, (1, 8)).ravel()
        ok = (rows >= 0) & (cols >= 0)
        pat = sp.csr_matrix((np.ones(ok.sum(), np.int8), (rows[ok], cols[ok])), shape=(self.nr, self.nr))
        pat.sum_duplicates()
        pat.sort_indices()
        self.indptr, self.indices = pat.indptr.astype(np.int64), pat.indices.astype(np.int64)
        e = np.arange(nx * ny * nz)
        colour = (e % nx % 2) + 2 * ((e // nx) % ny % 2) + 4 * (e // (nx * ny) % 2)
        order = np.argsort(colour, kind="stable")
        self.colour_idx = order.astype(np.int64)
        self.colour_start = np.searchsorted(colour[order], np.arange(9)).astype(np.int64)
        # rigid-body modes of the active nodes, for the aggregation
        X = (self.active_nodes % (nx + 1)) * h
        Y = ((self.active_nodes // (nx + 1)) % (ny + 1)) * h
        Z = (self.active_nodes // ((nx + 1) * (ny + 1))) * h
        B = np.zeros((self.nr, 3, 6))
        B[:, 0, 0] = B[:, 1, 1] = B[:, 2, 2] = 1
        B[:, 0, 3], B[:, 1, 3] = -Y, X
        B[:, 1, 4], B[:, 2, 4] = -Z, Y
        B[:, 0, 5], B[:, 2, 5] = Z, -X
        self.B = B.reshape(-1, 6)
        self.reuse, self._calls, self._M, self._lu = reuse, 0, None, None
        self._pardiso = _pardiso()
        if direct_max_dofs is None:
            direct_max_dofs = PARDISO_MAX_DOFS if self._pardiso is not None else 150_000
        self.direct_max_dofs = direct_max_dofs
        self.dof_index = (3 * self.active_nodes[:, None] + np.arange(3)[None, :]).ravel()

    def set_E(self, Ee):
        data = np.zeros((self.indices.size, 3, 3))
        _fill_bsr(data, self.indptr, self.indices, self.enodes, np.ascontiguousarray(Ee, np.float64),
                  self.KE, self.rnode, self.colour_start, self.colour_idx)
        self.A = sp.bsr_matrix((data, self.indices, self.indptr), shape=(3 * self.nr, 3 * self.nr))
        if 3 * self.nr <= self.direct_max_dofs and self._pardiso is not None:
            self._Acsr = self.A.tocsr()
            self._pardiso.factorize(self._Acsr)
            self._lu = self._pardiso
            return
        if 3 * self.nr <= self.direct_max_dofs:
            # K is symmetric positive definite: pivot on the diagonal only. Partial
            # pivoting (SuperLU's default) wandered off it on a high-contrast
            # design, 150M against 116M fill and 70 s against 30 s to factorise.
            self._lu = spla.splu(self.A.tocsc(), permc_spec="MMD_AT_PLUS_A",
                                 options=dict(SymmetricMode=True, DiagPivotThresh=0.0))
            return
        if self._M is None or self._calls % self.reuse == 0:
            import pyamg
            self._ml = pyamg.smoothed_aggregation_solver(self.A, B=self.B, max_coarse=500)
            self._M = self._ml.aspreconditioner(cycle="V")
        self._calls += 1

    def solve(self, f, x0=None, tol=1e-6, maxit=400):
        """f, x0 and the returned u are full-length (self.n); fixed dofs are 0.
        Returns (u, iterations, relative residual); iterations 0 for a direct solve.
        Raises RuntimeError when CG does not reach `tol` in `maxit` iterations."""
        b = f[self.dof_index]
        if self._lu is not None:
            y = self._lu.solve(self._Acsr, b) if self._lu is self._pardiso else self._lu.solve(b)
            u = np.zeros(self.n)
            u[self.dof_index] = y
            bn = np.linalg.norm(b)
            residual = float(np.linalg.norm(self.A @ y - b) / bn) if bn else 0.0
            if not np.isfinite(y).all() or not np.isfinite(residual) or residual > max(tol, 1e-8):
                raise RuntimeError(f"direct solve did not balance loads: relative residual {residual}")
            return u, 0, residual
        x = None if x0 is None else x0[self.dof_index]
        n = [0]
        y, info = spla.cg(self.A, b, x0=x, rtol=tol, maxiter=maxit, M=self._M,
                          callback=lambda _xk: n.__setitem__(0, n[0] + 1))
        u = np.zeros(self.n)
        u[self.dof_index] = y
        bn = np.linalg.norm(b)
        res = float(np.linalg.norm(self.A @ y - b) / bn) if bn else 0.0
        if info != 0:
            why = f"stopped at {maxit} iterations" if info > 0 else f"broke down (scipy info {info})"
            cure = ("use a coarser grid" if self._pardiso is not None or 3 * self.nr > PARDISO_MAX_DOFS else
                    f"install pypardiso to solve up to {PARDISO_MAX_DOFS} unknowns directly, or use a coarser grid")
            raise RuntimeError(f"AMG-CG {why} on {3 * self.nr} unknowns, relative residual {res:.2e} against "
                               f"{tol:g}: the answer is not a solution; {cure}")
        return u, n[0], res


def selfcheck() -> dict:
    """A clamped cantilever against Timoshenko beam theory and a direct solve.
    Returns the ratios; the caller decides what is close enough.

    tip_over_timoshenko and default_vs_direct: the path a problem this size
    takes (~11k unknowns: SuperLU, or PARDISO when installed).
    iterative_vs_direct and iterations: the same beam forced onto the AMG-CG
    path (direct_max_dofs=0), the one a problem over the direct limit takes."""
    nx, ny, nz, h = 40, 8, 8, 1.0
    E0, nu, F = 1000.0, 0.3, 1.0
    nodes = np.arange((nx + 1) * (ny + 1) * (nz + 1))
    ii = nodes % (nx + 1)
    live, fixed = np.ones(nx * ny * nz, bool), nodes[ii == 0]
    s = Solver(nx, ny, nz, h, nu, live, fixed)
    s.set_E(np.full(nx * ny * nz, E0))
    f = np.zeros(s.n)
    tip = nodes[ii == nx]
    f[3 * tip + 2] = -F / tip.size
    u, _its, _res = s.solve(f, tol=1e-10)
    w = -u[3 * tip + 2].mean()
    I = ny * nz ** 3 / 12
    G = E0 / (2 * (1 + nu))
    w_beam = F * nx ** 3 / (3 * E0 * I) + F * nx / (5 / 6 * G * ny * nz)
    ud = spla.spsolve(s.A.tocsc(), f[s.dof_index])
    s_cg = Solver(nx, ny, nz, h, nu, live, fixed, direct_max_dofs=0)
    s_cg.set_E(np.full(nx * ny * nz, E0))
    u_cg, its, _res = s_cg.solve(f, tol=1e-10)

    def rel(v):
        return float(np.abs(ud - v[s.dof_index]).max() / np.abs(ud).max())
    return {"tip_over_timoshenko": float(w / w_beam), "default_vs_direct": rel(u),
            "iterative_vs_direct": rel(u_cg), "iterations": its}
