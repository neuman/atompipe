# SPDX-License-Identifier: Apache-2.0
"""Grid convergence index (GCI): the Celik et al. (2008) procedure, stdlib only.

Used by ``cfd.mesh_independence`` and ``cfd.pressure_drop``. Its arithmetic is
held to the published worked examples in ``tests/test_cfd_openfoam.py`` (Celik
Table 1, columns 1 and 3; the NASA NPARC example): 32 of 33 printed numbers
reproduce at their printed precision, and the 33rd (column 2, e_ext 0.9%) cannot
be reproduced from the table's own values (0.8465%).

Source of every equation below (equation numbers are the paper's):
  I. B. Celik, U. Ghia, P. J. Roache, C. J. Freitas (+ H. Coleman, P. E. Raad in
  the published version), "Procedure for Estimation and Reporting of Uncertainty
  Due to Discretization in CFD Applications", ASME J. Fluids Eng. 130(7):078001,
  2008.  Text used: the manuscript ASME hosts at
  https://qa12.asme.org/wwwasmeorg/media/ResourceFiles/Shop/Journals/JFENumAccuracy.pdf
  (pages 3-7).  Two-grid and Fs=3 rules: Roache (1994) J. Fluids Eng.
  116:405-413, as restated by NASA NPARC "Examining Spatial (Grid) Convergence",
  https://www.grc.nasa.gov/www/wind/valid/tutorial/spatconv.html

Grid 1 is the FINEST: h1 < h2 < h3, r21 = h2/h1, r32 = h3/h2.

What this module refuses to do quietly (each is a way a GCI number lies):
  * Celik Eq. (3a) wraps the right side in |.|, so p is positive even when the
    three values DIVERGE.  `classify` decides convergence before p is trusted.
  * A difference that is zero, or inside the stated iterative noise, makes Eq.
    (3) meaningless (Celik p.4-5: "the above procedure does not work").
  * With p observed from the same three grids, the asymptotic-range ratio
    GCI32 / (r21^p GCI21) equals |phi1/phi2| identically (derivation in
    `asymptotic_ratio`), so it carries no information.  It is reported, and
    flagged, never used as evidence.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Celik Eq. (7) / Roache (1994): the factor of safety when p is observed from
# three or more grids.  Fs = 3.0 is Roache's value for two grids (or an assumed
# p); NASA NPARC page: "Fs=3.0 for comparisons of two grids and Fs=1.25 for
# comparisons over three or more grids".
FS_THREE_GRID = 1.25
FS_TWO_GRID = 3.0

# Celik Step 2: "It is desirable that the grid refinement factor ... be greater
# than 1.3.  This value of 1.3 is based on experience, and not on formal
# derivation."  NASA NPARC states a looser floor of r >= 1.1.
R_MIN_RECOMMENDED = 1.3

MONOTONE_CONVERGENCE = "monotone convergence"
OSCILLATORY_CONVERGENCE = "oscillatory convergence"
MONOTONE_DIVERGENCE = "monotone divergence"
OSCILLATORY_DIVERGENCE = "oscillatory divergence"
UNRESOLVED = "unresolved"  # a difference is zero or inside the noise


class GCIError(ValueError):
    """The inputs cannot give a GCI (bad sizes, order, or degenerate data)."""


def representative_h(n_cells: float, dim: int, total_measure: float = 1.0) -> float:
    """Celik Eq. (1)/(2): h = [ (1/N) sum dV_i ]^(1/D) = (V_total / N)^(1/D).

    `dim` is the dimension of the MESH (2 for a 2-D mesh, 3 for 3-D), "irrespective
    of the problem being solved" (Celik p.3).  An OpenFOAM 2-D case is a 3-D mesh
    one cell thick: count it as dim=2 with N = the cell count (one layer)."""
    if dim not in (1, 2, 3):
        raise GCIError("dim must be 1, 2 or 3, got %r" % (dim,))
    if n_cells <= 0 or total_measure <= 0:
        raise GCIError("cell count and total measure must be positive")
    return (total_measure / float(n_cells)) ** (1.0 / dim)


def ratios(h=None, cells=None, dim=None):
    """(r21, r32) from three sizes h (fine first) or three cell counts (fine first).

    From cell counts: r21 = (N1/N2)^(1/D) (NASA NPARC 'effective grid refinement
    ratio'; equivalent to Eq. (1)/(2) on the same domain)."""
    if (h is None) == (cells is None):
        raise GCIError("give exactly one of h or cells")
    if h is not None:
        h1, h2, h3 = (float(x) for x in h)
        if not (0 < h1 < h2 < h3):
            raise GCIError("need 0 < h1 < h2 < h3 (grid 1 finest), got %r" % (h,))
        return h2 / h1, h3 / h2
    if dim is None:
        raise GCIError("cell counts need dim (the mesh dimension, 2 or 3)")
    n1, n2, n3 = (float(x) for x in cells)
    if not (n1 > n2 > n3 > 0):
        raise GCIError("need N1 > N2 > N3 > 0 (grid 1 finest), got %r" % (cells,))
    return (n1 / n2) ** (1.0 / dim), (n2 / n3) ** (1.0 / dim)


def classify(eps21: float, eps32: float, r21: float, r32: float) -> str:
    """Convergence type from eps21 = phi2-phi1, eps32 = phi3-phi2.

    Constant r: R = eps21/eps32 in (0,1) monotone convergence, (-1,0) oscillatory
    convergence, >1 monotone divergence, <-1 oscillatory divergence (Roache, as
    quoted by Eca & Hoekstra, 3rd Lisbon Workshop 2008, p.3).

    Non-constant r (derived here, not in Celik): for phi = phi0 + a h^p with p > 0,
    eps32/eps21 = r21^p (r32^p - 1)/(r21^p - 1), which rises monotonically from
    ln(r32)/ln(r21) at p -> 0+ to infinity.  So monotone convergence with some
    p > 0 exists iff eps32/eps21 > ln(r32)/ln(r21); for r21 == r32 this is R < 1.
    Celik's |.| in Eq. (3a) would hand back a positive p in the divergent case.
    The oscillatory split uses |eps32| > |eps21|, the constant-r amplitude rule.
    """
    rho = eps32 / eps21
    if rho > 0:
        threshold = math.log(r32) / math.log(r21)
        return MONOTONE_CONVERGENCE if rho > threshold else MONOTONE_DIVERGENCE
    return OSCILLATORY_CONVERGENCE if abs(rho) > 1.0 else OSCILLATORY_DIVERGENCE


def apparent_order_fixed_point(eps21: float, eps32: float, r21: float, r32: float,
                               tol: float = 1e-12, maxiter: int = 1000):
    """Celik Eq. (3a)-(3c) by fixed-point iteration, initial guess = first term.

        p    = (1/ln r21) * | ln|eps32/eps21| + q(p) |          (3a)
        q(p) = ln( (r21^p - s) / (r32^p - s) )                    (3b)
        s    = 1 * sign(eps32/eps21)                              (3c)

    Returns (p, s, iterations, converged).  A fixed point that wanders, or q that
    leaves its domain, returns converged=False with the last iterate."""
    rho = eps32 / eps21
    s = 1.0 if rho > 0 else -1.0
    lr = math.log(abs(rho))
    ln21 = math.log(r21)
    p = abs(lr) / ln21
    ln_max = max(ln21, math.log(r32))
    for it in range(1, maxiter + 1):
        # p ln r > 700 overflows a float, and p > 50 is not an order of any
        # discretisation a gate would accept: stop and say it did not converge.
        if p > 50.0 or p * ln_max > 700.0:
            return p, s, it, False
        num = r21 ** p - s
        den = r32 ** p - s
        if num <= 0 or den <= 0:
            return p, s, it, False
        p_new = abs(lr + math.log(num / den)) / ln21
        if abs(p_new - p) <= tol * max(1.0, abs(p_new)):
            return p_new, s, it, True
        p = p_new
    return p, s, maxiter, False


def _residual(p, lr, r21, r32, s):
    """F(p) = p ln r21 - ( ln|eps32/eps21| + q(p) ), the SIGNED branch of (3a).

    Eq. (3a)'s |.| has a second, reflected branch, p ln r21 = -(ln|rho| + q(p)),
    whose root is not an order of the data: over exact power-law data it is the
    second root a bisection finds (57 of 57 fallback cases in the scan).  Data
    that obey phi = phi0 + a h^p satisfy ln|rho| + q(p) = p ln r21 > 0, so only
    the signed branch is solved here; classify() has already named divergence."""
    num, den = r21 ** p - s, r32 ** p - s
    if num <= 0 or den <= 0:
        return None
    return p * math.log(r21) - (lr + math.log(num / den))


def apparent_order_bracketed(eps21, eps32, r21, r32, p_max=50.0, samples=4000):
    """The same Eq. (3a) solved by bracketing and bisection instead of iteration.

    Why it exists: the fixed point map of Eq. (3a) is not a contraction when r21
    is small against r32.  Over exact power-law data (phi = 1 + 0.1 h^p) with
    r21, r32 in {1.1,1.2,1.3,1.5,2,3} and p in {0.3..5}, the iteration failed in
    57 of 252 cases (measured when this module was written).  Returns (p, roots) with every
    root found on a log grid of `samples` points in (1e-6, p_max]; p is None when
    there is none."""
    rho = eps32 / eps21
    s = 1.0 if rho > 0 else -1.0
    lr = math.log(abs(rho))
    lo_l, hi_l = math.log(1e-6), math.log(p_max)
    grid = [math.exp(lo_l + (hi_l - lo_l) * i / samples) for i in range(samples + 1)]
    roots = []
    prev_p, prev_f = None, None
    for p in grid:
        f = _residual(p, lr, r21, r32, s)
        if f is not None and prev_f is not None and (f == 0 or (prev_f < 0) != (f < 0)):
            a, b, fa = prev_p, p, prev_f
            for _ in range(200):
                m = 0.5 * (a + b)
                fm = _residual(m, lr, r21, r32, s)
                if fm is None:
                    break
                if (fa < 0) == (fm < 0):
                    a, fa = m, fm
                else:
                    b = m
            roots.append(0.5 * (a + b))
        prev_p, prev_f = p, f
    return (roots[0] if roots else None), roots, s


def apparent_order(eps21, eps32, r21, r32, tol=1e-12, maxiter=1000):
    """Celik's fixed-point iteration first; on failure, the bracketed solve.
    Returns (p, s, iterations, converged, method, n_roots)."""
    p, s, its, ok = apparent_order_fixed_point(eps21, eps32, r21, r32, tol, maxiter)
    if ok:
        return p, s, its, True, "fixed-point", None
    pb, roots, s = apparent_order_bracketed(eps21, eps32, r21, r32)
    if pb is None:
        return p, s, its, False, "none", 0
    return pb, s, its, len(roots) == 1, "bisection", len(roots)


@dataclass
class GCIResult:
    phi: tuple
    r21: float
    r32: float
    eps21: float
    eps32: float
    convergence: str
    p: float | None = None
    p_converged: bool = False
    p_iterations: int = 0
    p_method: str = ""
    s: float | None = None
    phi_ext21: float | None = None
    phi_ext32: float | None = None
    e_a21: float | None = None
    e_ext21: float | None = None
    gci_fine21: float | None = None
    gci_32: float | None = None
    asymptotic_ratio: float | None = None
    fs: float = FS_THREE_GRID
    warnings: list = field(default_factory=list)


def asymptotic_ratio(gci21: float, gci32: float, r21: float, p: float) -> float:
    """NASA NPARC check GCI23 = r^p GCI12, as the ratio GCI32 / (r21^p GCI21).

    Exact identity when p is observed from these same three grids: from Eq. (3)
    eps32/eps21 = r21^p (r32^p-1)/(r21^p-1), so GCI32/(r21^p GCI21) =
    (|eps32|/|phi2|/(r32^p-1)) / (r21^p |eps21|/|phi1|/(r21^p-1)) = |phi1/phi2|.
    It equals 1 to within the relative change between grids 1 and 2 whatever the
    data, so it is only informative with p from other grids or the formal p.
    NB the NPARC VERIFY program prints the reciprocal, r^p GCI12/GCI23."""
    return gci32 / (r21 ** p * gci21)


def gci(phi, h=None, cells=None, dim=None, fs: float = FS_THREE_GRID,
        noise: float = 0.0, scale: float | None = None) -> GCIResult:
    """Three-grid GCI (Celik Steps 3-5).  phi = (phi1, phi2, phi3), FINE FIRST.

    noise: the absolute iterative-convergence uncertainty of each phi (Celik App.
      A asks it to be at least ten times below the discretization error).  A
      difference |eps| <= noise is UNRESOLVED and no p is computed.
    scale: the normalising value for the relative errors and GCI; default |phi1|
      (Celik Eq. 5).  NPARC: when phi1 is near zero "another normalizing value
      should be used in place of f1".
    """
    phi1, phi2, phi3 = (float(x) for x in phi)
    r21, r32 = ratios(h=h, cells=cells, dim=dim)
    eps21, eps32 = phi2 - phi1, phi3 - phi2
    warnings = []
    if r21 < R_MIN_RECOMMENDED or r32 < R_MIN_RECOMMENDED:
        warnings.append("refinement ratio below 1.3 (Celik Step 2): r21=%.4g r32=%.4g"
                        % (r21, r32))
    floor = max(float(noise), 0.0)
    if abs(eps21) <= floor or abs(eps32) <= floor:
        warnings.append("a grid-to-grid difference is zero or inside the noise %.3g:"
                        " eps21=%.3g eps32=%.3g (Celik p.4-5)" % (floor, eps21, eps32))
        return GCIResult((phi1, phi2, phi3), r21, r32, eps21, eps32, UNRESOLVED,
                         fs=fs, warnings=warnings)
    kind = classify(eps21, eps32, r21, r32)
    p, s, its, ok, method, n_roots = apparent_order(eps21, eps32, r21, r32)
    res = GCIResult((phi1, phi2, phi3), r21, r32, eps21, eps32, kind, p=p,
                    p_converged=ok, p_iterations=its, p_method=method, s=s, fs=fs,
                    warnings=warnings)
    if method == "bisection":
        warnings.append("Celik's fixed-point iteration did not converge; p from"
                        " bisection on Eq. (3a) (%d root(s))" % n_roots)
    if not ok:
        warnings.append("no unique p solves Eq. (3a) (method %s, roots %s)"
                        % (method, n_roots))
        return res
    if kind in (MONOTONE_DIVERGENCE, OSCILLATORY_DIVERGENCE):
        warnings.append("%s: Eq. (3a)'s |.| gives p=%.4g anyway; not an order" % (kind, p))
    if kind == OSCILLATORY_CONVERGENCE:
        warnings.append("oscillatory convergence (eps32/eps21 < 0, Celik p.4)")
    a21, a32 = r21 ** p, r32 ** p
    res.phi_ext21 = (a21 * phi1 - phi2) / (a21 - 1.0)                       # (4)
    res.phi_ext32 = (a32 * phi2 - phi3) / (a32 - 1.0)
    norm1 = abs(phi1) if scale is None else abs(float(scale))
    norm2 = abs(phi2) if scale is None else abs(float(scale))
    if norm1 == 0.0 or norm2 == 0.0:
        warnings.append("normalising value is zero: give scale=")
        return res
    res.e_a21 = abs(eps21) / norm1                                          # (5)
    res.e_ext21 = (abs(res.phi_ext21 - phi1) / abs(res.phi_ext21)          # (6)
                   if res.phi_ext21 != 0 else None)
    res.gci_fine21 = fs * res.e_a21 / (a21 - 1.0)                           # (7)
    # Fine-grid GCI of the (2,3) pair, NPARC's "GCI23": Fs |eps32/phi2| / (r32^p-1).
    res.gci_32 = fs * (abs(eps32) / norm2) / (a32 - 1.0)
    res.asymptotic_ratio = asymptotic_ratio(res.gci_fine21, res.gci_32, r21, p)
    return res


def gci_two_grid(phi1: float, phi2: float, r21: float, p: float,
                 fs: float = FS_TWO_GRID, scale: float | None = None) -> float:
    """Roache's two-grid GCI with an ASSUMED (formal) order p: Fs |eps|/(r^p-1),
    eps = (phi2-phi1)/phi1, with Fs = 3 (NPARC page; Roache 1994)."""
    norm = abs(phi1) if scale is None else abs(float(scale))
    if r21 <= 1.0 or p <= 0 or norm == 0:
        raise GCIError("need r21 > 1, p > 0 and a nonzero normalising value")
    return fs * (abs(phi2 - phi1) / norm) / (r21 ** p - 1.0)


def gci_constant_r(phi, r: float, fs: float = FS_THREE_GRID):
    """NPARC's closed form for constant r: p = ln((f3-f2)/(f2-f1))/ln r (no |.|,
    so a divergent or oscillatory triple raises instead of returning p).
    Returns (p, f_h0, GCI12, GCI23, GCI23/(r^p GCI12))."""
    f1, f2, f3 = (float(x) for x in phi)
    ratio = (f3 - f2) / (f2 - f1)
    if ratio <= 0:
        raise GCIError("oscillatory: (f3-f2)/(f2-f1) = %.4g <= 0" % ratio)
    p = math.log(ratio) / math.log(r)
    if p <= 0:
        raise GCIError("divergent: observed p = %.4g <= 0" % p)
    rp = r ** p
    f0 = f1 + (f1 - f2) / (rp - 1.0)
    g12 = fs * abs((f2 - f1) / f1) / (rp - 1.0)
    g23 = fs * abs((f3 - f2) / f2) / (rp - 1.0)
    return p, f0, g12, g23, g23 / (rp * g12)
