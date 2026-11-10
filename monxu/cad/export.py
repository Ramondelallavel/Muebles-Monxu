"""Exportación de geometría real: STEP (conjunto y piezas), STL, BREP nativo de OpenCascade y malla para el visor."""
from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np

from .. import catalog
from . import geometry as G


def _color(model, inst) -> tuple[float, float, float]:
    p = inst.part
    if p.finish:
        return tuple(catalog.finish(p.finish)["color"])
    if p.material:
        return catalog.material(p.material).render_color
    return (0.62, 0.64, 0.66) if p.kind == "normalizado" else (0.5, 0.5, 0.5)


def build_assembly(model) -> cq.Assembly:
    root = cq.Assembly(name=model.product_code)
    subs: dict[str, cq.Assembly] = {}
    for sid, sa in model.subassemblies.items():
        subs[sid] = cq.Assembly(name=f"{sid} {sa.name}")
    for inst in model.instances:
        c = _color(model, inst)
        subs[inst.group].add(inst.part.shape, name=f"{inst.id} [{inst.part.ref}]", loc=G.to_location(inst.T),
                             color=cq.Color(*c))
    for sid, a in subs.items():
        root.add(a, name=a.name)
    return root


def export_step_assembly(model, path: Path) -> Path:
    build_assembly(model).export(str(path), "STEP")
    return path


def export_step_part(part, path: Path) -> Path:
    cq.exporters.export(cq.Workplane().add(part.shape), str(path), exportType="STEP")
    return path


def export_stl(model, path: Path, tolerance: float = 0.1) -> Path:
    cq.exporters.export(cq.Workplane().add(model.compound()), str(path), exportType="STL", tolerance=tolerance,
                        angularTolerance=0.2)
    return path


def verify_stl(path: Path) -> dict:
    """Relee el STL (binario o ASCII): triángulos, volumen por el teorema de la divergencia y envolvente."""
    import struct
    import numpy as np
    raw = Path(path).read_bytes()
    tris = []
    if raw[:5] == b"solid" and b"facet" in raw[:400]:
        v = [list(map(float, ln.split()[1:4])) for ln in raw.decode("ascii", "ignore").splitlines()
             if ln.strip().startswith("vertex")]
        tris = np.array(v, float).reshape(-1, 3, 3)
        ok = True
    else:
        n = struct.unpack_from("<I", raw, 80)[0]
        ok = len(raw) == 84 + 50 * n
        dt = np.dtype([("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
        tris = np.frombuffer(raw, dtype=dt, count=n, offset=84)["v"].astype(float)
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    vol = float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)
    pts = tris.reshape(-1, 3)
    return {"triangles": len(tris), "bytes_ok": ok, "volume": vol, "bbox": [pts.min(0).tolist(), pts.max(0).tolist()]}


def export_brep(model, path: Path) -> Path:
    model.compound().exportBrep(str(path))
    return path


def export_glb(model, path: Path) -> Path:
    build_assembly(model).export(str(path), "GLTF")
    return path


def _b64(a: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(a).tobytes()).decode("ascii")


def viewer_payload(model, tolerance: float = 0.25, angular: float = 0.3) -> dict[str, Any]:
    """Malla por definición de pieza + instancias con matriz (instanciado en el visor)."""
    parts = {}
    for key, p in model.parts.items():
        verts, tris = p.shape.tessellate(tolerance, angular)
        pos = np.array([(v.x, v.y, v.z) for v in verts], np.float32).reshape(-1)
        idx = np.array(tris, np.uint32).reshape(-1)
        parts[key] = {"positions": _b64(pos), "indices": _b64(idx), "ref": p.ref, "kind": p.kind, "name": p.name,
                      "material": p.material, "mass": round(p.mass, 3), "dims": p.bom_dims()}
    insts = []
    for i in model.instances:
        sa = model.subassemblies[i.group]
        ex = np.array(sa.explode) + np.array(i.tags.get("explode_extra", (0, 0, 0)))
        lo, hi = i.bbox
        insts.append({"id": i.id, "name": i.name, "part": i.part.key, "ref": i.part.ref, "group": i.group,
                      "kind": i.part.kind, "matrix": [float(v) for v in i.T.T.reshape(-1)],   # column-major (three.js)
                      "color": list(_color(model, i)), "explode": ex.tolist(),
                      "bbox": [lo.tolist(), hi.tolist()], "feature": i.feature})
    lo, hi = model.bounding_box()
    return {"product_code": model.product_code, "parts": parts, "instances": insts,
            "bbox": [lo.tolist(), hi.tolist()],
            "subassemblies": [{"id": k, "name": v.name, "explode": list(v.explode)} for k, v in model.subassemblies.items()],
            "tree": model.component_tree()}


def write_viewer_payload(model, path: Path) -> Path:
    path.write_text(json.dumps(viewer_payload(model)), encoding="utf-8")
    return path
