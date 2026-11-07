"""Detección de interferencias entre sólidos del conjunto (volumen común B-rep)."""
from __future__ import annotations

from itertools import combinations

from . import geometry as G

#: volumen común por debajo del cual se considera contacto (mm3)
CONTACT_TOLERANCE_MM3 = 0.5


def _overlap(b1, b2, eps=0.01) -> bool:
    (a0, a1), (c0, c1) = b1, b2
    return all(a0[i] < c1[i] - eps and c0[i] < a1[i] - eps for i in range(3))


def check_interferences(model, tol: float = CONTACT_TOLERANCE_MM3) -> dict:
    inst = model.instances
    pairs = [(a, b) for a, b in combinations(inst, 2) if _overlap(a.bbox, b.bbox)]
    found = []
    for a, b in pairs:
        v = G.common_volume(a.shape, b.shape)
        if v != v or v > tol:   # NaN => booleana fallida, se informa como interferencia no verificable
            found.append({"a": a.id, "b": b.id, "volume_mm3": None if v != v else round(v, 3),
                          "a_name": a.name, "b_name": b.name})
    return {"pairs_checked": len(pairs), "instances": len(inst), "interferences": found,
            "tolerance_mm3": tol}
