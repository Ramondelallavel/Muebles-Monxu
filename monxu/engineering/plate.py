"""Placa rectangular delgada simplemente apoyada en sus cuatro bordes (solución de Navier).

Teoría de Kirchhoff, pequeñas deformaciones. Carga uniforme y/o carga repartida en una huella
rectangular u×v centrada en (ξ, η). Validada frente a los coeficientes de Timoshenko/Roark.
"""
from __future__ import annotations

import math

import numpy as np


def navier(a: float, b: float, t: float, E: float, nu: float, q: float = 0.0,
           patch: tuple[float, float, float, float, float] | None = None, at: tuple[float, float] | None = None,
           terms: int = 79) -> dict:
    """Flecha y momentos en el punto ``at`` (por defecto el centro de la huella o de la placa).

    a: luz en x, b: luz en y [mm]; q: presión uniforme [MPa = N/mm2];
    patch: (P [N], u, v, ξ, η) carga P repartida en u×v centrada en (ξ, η).
    Devuelve w [mm], Mx, My [N·mm/mm] y tensión máxima de flexión σ = 6·M/t² [MPa].
    """
    D = E * t ** 3 / (12 * (1 - nu ** 2))
    m = np.arange(1, terms + 1)[:, None].astype(float)
    n = np.arange(1, terms + 1)[None, :].astype(float)
    qmn = np.zeros((terms, terms))
    if q:
        odd = (m % 2 == 1) & (n % 2 == 1)
        qmn = qmn + np.where(odd, 16 * q / (math.pi ** 2 * m * n), 0.0)
    if patch:
        P, u, v, xi, eta = patch
        q0 = P / (u * v)
        qmn = qmn + (16 * q0 / (math.pi ** 2 * m * n) * np.sin(m * math.pi * xi / a) * np.sin(n * math.pi * eta / b)
                     * np.sin(m * math.pi * u / (2 * a)) * np.sin(n * math.pi * v / (2 * b)))
    if at is None:
        at = (patch[3], patch[4]) if patch else (a / 2, b / 2)
    x, y = at
    am, bn = m / a, n / b
    Wmn = qmn / (D * math.pi ** 4 * (am ** 2 + bn ** 2) ** 2)
    S = np.sin(m * math.pi * x / a) * np.sin(n * math.pi * y / b)
    w = float((Wmn * S).sum())
    Mx = float((D * math.pi ** 2 * Wmn * (am ** 2 + nu * bn ** 2) * S).sum())
    My = float((D * math.pi ** 2 * Wmn * (nu * am ** 2 + bn ** 2) * S).sum())
    M = max(abs(Mx), abs(My))
    return {"w": w, "Mx": Mx, "My": My, "sigma": 6 * M / t ** 2, "D": D, "at": at}


def uniform_panel(a: float, b: float, t: float, E: float, nu: float, q: float) -> dict:
    return navier(a, b, t, E, nu, q=q)


def patch_panel(a: float, b: float, t: float, E: float, nu: float, P: float, size: float) -> dict:
    u = min(size, a)
    v = min(size, b)
    return navier(a, b, t, E, nu, patch=(P, u, v, a / 2, b / 2), terms=121)
