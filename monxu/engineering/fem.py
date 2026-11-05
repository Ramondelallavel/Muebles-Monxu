"""Análisis lineal elástico de pórticos espaciales por el método de rigidez (barras de Euler-Bernoulli).

Unidades: N, mm, MPa. Cada nodo tiene 6 grados de libertad (ux, uy, uz, rx, ry, rz).
Ejes locales de barra: x según la directriz, z según el canto de la sección (vector 'up'),
y = z × x. La inercia ``Iy`` (flexión en el plano x–z) corresponde al canto H de la sección.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Element:
    i: int
    j: int
    E: float
    G: float
    A: float
    Iy: float
    Iz: float
    J: float
    up: np.ndarray
    member: str = ""
    L: float = 0.0
    R: np.ndarray = field(default=None, repr=False)


class Frame3D:
    def __init__(self, merge_tol: float = 0.5):
        self.nodes: list[np.ndarray] = []
        self.elements: list[Element] = []
        self.fixed: dict[int, tuple[bool, ...]] = {}
        self.merge_tol = merge_tol
        self.loads: dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------ definición
    def node(self, p) -> int:
        p = np.asarray(p, float)
        for k, q in enumerate(self.nodes):
            if np.linalg.norm(p - q) <= self.merge_tol:
                return k
        self.nodes.append(p)
        return len(self.nodes) - 1

    def element(self, i, j, E, G, A, Iy, Iz, J, up, member="") -> int:
        e = Element(i, j, E, G, A, Iy, Iz, J, np.asarray(up, float), member)
        d = self.nodes[j] - self.nodes[i]
        e.L = float(np.linalg.norm(d))
        if e.L < 1e-6:
            raise ValueError("Elemento de longitud nula")
        x = d / e.L
        z = e.up - x * np.dot(e.up, x)
        if np.linalg.norm(z) < 1e-9:
            raise ValueError("Vector 'up' paralelo a la barra")
        z /= np.linalg.norm(z)
        y = np.cross(z, x)
        e.R = np.vstack([x, y, z])
        self.elements.append(e)
        return len(self.elements) - 1

    def support(self, n: int, dofs=(True, True, True, False, False, False)) -> None:
        self.fixed[n] = tuple(dofs)

    def ndof(self) -> int:
        return 6 * len(self.nodes)

    def load_vector(self, case: str) -> np.ndarray:
        if case not in self.loads:
            self.loads[case] = np.zeros(self.ndof())
        return self.loads[case]

    def add_nodal_load(self, case: str, n: int, F=(0, 0, 0), M=(0, 0, 0)) -> None:
        f = self.load_vector(case)
        f[6 * n:6 * n + 3] += F
        f[6 * n + 3:6 * n + 6] += M

    # ------------------------------------------------------------------ matrices
    @staticmethod
    def k_local(e: Element) -> np.ndarray:
        L, E, G = e.L, e.E, e.G
        k = np.zeros((12, 12))
        EA, GJ = E * e.A / L, G * e.J / L
        k[0, 0] = k[6, 6] = EA
        k[0, 6] = k[6, 0] = -EA
        k[3, 3] = k[9, 9] = GJ
        k[3, 9] = k[9, 3] = -GJ
        a, b, c, d = 12 * E * e.Iz / L ** 3, 6 * E * e.Iz / L ** 2, 4 * E * e.Iz / L, 2 * E * e.Iz / L
        for (r, s, v) in [(1, 1, a), (1, 5, b), (1, 7, -a), (1, 11, b), (5, 5, c), (5, 7, -b), (5, 11, d),
                          (7, 7, a), (7, 11, -b), (11, 11, c)]:
            k[r, s] = k[s, r] = v
        a, b, c, d = 12 * E * e.Iy / L ** 3, 6 * E * e.Iy / L ** 2, 4 * E * e.Iy / L, 2 * E * e.Iy / L
        for (r, s, v) in [(2, 2, a), (2, 4, -b), (2, 8, -a), (2, 10, -b), (4, 4, c), (4, 8, b), (4, 10, d),
                          (8, 8, a), (8, 10, b), (10, 10, c)]:
            k[r, s] = k[s, r] = v
        return k

    @staticmethod
    def T(e: Element) -> np.ndarray:
        T = np.zeros((12, 12))
        for b in range(4):
            T[3 * b:3 * b + 3, 3 * b:3 * b + 3] = e.R
        return T

    def stiffness(self) -> np.ndarray:
        K = np.zeros((self.ndof(), self.ndof()))
        for e in self.elements:
            T = self.T(e)
            kg = T.T @ self.k_local(e) @ T
            idx = np.r_[6 * e.i:6 * e.i + 6, 6 * e.j:6 * e.j + 6]
            K[np.ix_(idx, idx)] += kg
        return K

    # ------------------------------------------------------------------ resolución
    def solve(self, cases: list[str] | None = None) -> "Results":
        K = self.stiffness()
        fixed = np.zeros(self.ndof(), bool)
        for n, dofs in self.fixed.items():
            for k, f in enumerate(dofs):
                fixed[6 * n + k] = f
        free = ~fixed
        Kff = K[np.ix_(free, free)]
        cases = cases or list(self.loads)
        U = {}
        for c in cases:
            F = self.load_vector(c)
            u = np.zeros(self.ndof())
            u[free] = np.linalg.solve(Kff, F[free])
            U[c] = u
        return Results(self, K, U)


class Results:
    def __init__(self, frame: Frame3D, K: np.ndarray, U: dict[str, np.ndarray]):
        self.frame, self.K, self.U = frame, K, U

    def combine(self, factors: dict[str, float]) -> np.ndarray:
        u = np.zeros(self.frame.ndof())
        for c, f in factors.items():
            if c in self.U:
                u += f * self.U[c]
        return u

    def combine_loads(self, factors: dict[str, float]) -> np.ndarray:
        F = np.zeros(self.frame.ndof())
        for c, f in factors.items():
            if c in self.frame.loads:
                F += f * self.frame.loads[c]
        return F

    def element_forces(self, k: int, u: np.ndarray) -> np.ndarray:
        """Esfuerzos en extremos en ejes locales [N1,Vy1,Vz1,T1,My1,Mz1,N2,...] (acción sobre la barra)."""
        e = self.frame.elements[k]
        idx = np.r_[6 * e.i:6 * e.i + 6, 6 * e.j:6 * e.j + 6]
        return Frame3D.k_local(e) @ Frame3D.T(e) @ u[idx]

    def reactions(self, u: np.ndarray, F: np.ndarray) -> dict[int, np.ndarray]:
        r = self.K @ u - F
        return {n: r[6 * n:6 * n + 6] for n in self.frame.fixed}


def gauss_points(n: int = 6):
    return np.polynomial.legendre.leggauss(n)


def line_load_to_nodes(s_nodes: np.ndarray, p, s0: float, s1: float, n_gauss: int = 6) -> np.ndarray:
    """Cargas nodales equivalentes (funciones de forma lineales) de una densidad p(s) en [s0, s1].

    ``s_nodes`` ordenadas. La parte de [s0, s1] fuera del rango de nodos se asigna al nodo extremo.
    Devuelve la fuerza en cada nodo (misma unidad que ∫p ds)."""
    out = np.zeros(len(s_nodes))
    xg, wg = gauss_points(n_gauss)

    def integrate(a, b, f):
        if b <= a:
            return 0.0
        xm, xr = (a + b) / 2, (b - a) / 2
        return float(sum(w * f(xm + xr * x) for x, w in zip(xg, wg)) * xr)

    lo, hi = s_nodes[0], s_nodes[-1]
    out[0] += integrate(s0, min(s1, lo), p)
    out[-1] += integrate(max(s0, hi), s1, p)
    for k in range(len(s_nodes) - 1):
        a, b = s_nodes[k], s_nodes[k + 1]
        lo_, hi_ = max(a, s0), min(b, s1)
        if hi_ <= lo_:
            continue
        Lk = b - a
        out[k] += integrate(lo_, hi_, lambda s: p(s) * (b - s) / Lk)
        out[k + 1] += integrate(lo_, hi_, lambda s: p(s) * (s - a) / Lk)
    return out
