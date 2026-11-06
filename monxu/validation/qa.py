"""Control de calidad previo a la exportación.

Niveles: ``bloqueante`` (impide exportar), ``advertencia``, ``ok`` y ``pendiente`` (validación que
corresponde a un técnico o a datos que faltan). Distingue un diseño geométricamente completo de
un diseño técnicamente verificado.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from .. import catalog
from ..core.model import ProfilePart, SheetPart

BLOCK, WARN, OK, PEND = "bloqueante", "advertencia", "ok", "pendiente"


class QA:
    def __init__(self):
        self.items: list[dict[str, Any]] = []

    def add(self, level, code, message, **data):
        self.items.append({"level": level, "code": code, "message": message, **data})

    def result(self) -> dict[str, Any]:
        lv = [i["level"] for i in self.items]
        blocking = lv.count(BLOCK)
        res = "bloqueante" if blocking else ("advertencia" if WARN in lv else "ok")
        return {"result": res, "blocking": blocking, "warnings": lv.count(WARN), "pending": lv.count(PEND),
                "ok": lv.count(OK), "items": self.items,
                "summary": f"{blocking} errores bloqueantes, {lv.count(WARN)} advertencias, {lv.count(PEND)} "
                           f"validaciones pendientes, {lv.count(OK)} comprobaciones satisfactorias."}


def model_checks(model, interf: dict, eng: dict, dfm: list, bom: dict) -> QA:
    q = QA()
    ps = model.params.values
    # geometría válida
    bad = [p.ref for p in model.parts.values() if not p.shape.isValid() or p.volume <= 0]
    q.add(BLOCK if bad else OK, "GEO-VALIDA", f"Sólidos no válidos: {bad}" if bad else
          f"{len(model.parts)} definiciones de pieza con sólido B-rep válido y volumen positivo.")
    # duplicados
    seen, dup = {}, []
    for i in model.instances:
        k = (i.part.key, tuple(np.round(i.T, 4).reshape(-1)))
        if k in seen:
            dup.append((seen[k], i.id))
        seen[k] = i.id
    q.add(BLOCK if dup else OK, "GEO-DUPLICADOS", f"Componentes duplicados en la misma posición: {dup}" if dup else
          "Sin componentes duplicados coincidentes.")
    # interferencias
    n = len(interf["interferences"])
    q.add(BLOCK if n else OK, "GEO-INTERFERENCIAS",
          f"{n} interferencias: " + "; ".join(f"{x['a']}↔{x['b']} {x['volume_mm3']} mm³" for x in interf["interferences"])
          if n else f"Sin interferencias ({interf['pairs_checked']} parejas evaluadas, tolerancia de contacto "
                    f"{interf['tolerance_mm3']} mm³).")
    # reglas de diseño
    for nte in model.design_notes:
        if nte["level"] == "error":
            q.add(BLOCK, nte["code"], nte["message"])
        elif nte["level"] == "advertencia":
            q.add(WARN, nte["code"], nte["message"])
    # dimensiones (envolvente declarada por la familia)
    env = model.dims.get("envelope")
    if env:
        insts = [model.instance(i) for i in env["ids"]] if env.get("ids") else \
            [i for i in model.instances if i.group in env.get("groups", ())]
        lo = np.min([i.bbox[0] for i in insts], axis=0)
        hi = np.max([i.bbox[1] for i in insts], axis=0)
        nx, ny = env.get("names", ("LONGITUD", "ANCHURA"))
        devs = {nx: hi[0] - lo[0] - env["dx"], ny: hi[1] - lo[1] - env["dy"], "ALTURA": hi[2] - env["zmax"]}
        bad = {k: round(v, 4) for k, v in devs.items() if abs(v) > 0.01}
        q.add(BLOCK if bad else OK, "GEO-DIMENSIONES", f"Desviación entre geometría y parámetros: {bad}" if bad else
              "Dimensiones generales de la geometría coinciden con los parámetros (±0,01 mm).")
        blo, bhi = model.bounding_box()
        over = max(lo[0] - blo[0], lo[1] - blo[1], bhi[0] - hi[0], bhi[1] - hi[1])
        if over > 0.5:
            q.add(WARN, "GEO-SALIENTE", f"Elementos sobresalen {over:.1f} mm del contorno del producto (apoyos: "
                                        "bases de pies o ruedas): considerar en implantación.")
    # holguras
    g = model.ctx.derived.get("HOLGURA_ENC")
    r = model.ctx.derived.get("RADIO_ENC")
    if g and r:
        q.add(OK if g.value >= r.value else BLOCK, "GEO-HOLGURAS",
              f"Holgura estructura–pestaña {g.value} mm ≥ radio de plegado {r.value} mm." if g.value >= r.value else
              "Holgura menor que el radio de plegado.")
    # materiales
    fin = catalog.finish(ps["ACABADO"])
    fams = {catalog.material(p.material).family for p in model.parts.values() if p.material}
    incompatible = [f for f in fams if f not in fin["compatible"]]
    q.add(WARN if incompatible else OK, "MAT-ACABADO", f"Acabado '{fin['name']}' no indicado para {incompatible}."
          if incompatible else f"Acabado compatible con los materiales ({', '.join(sorted(fams))}).")
    if {"acero_carbono", "acero_inoxidable"} <= fams or {"aluminio", "acero_carbono"} <= fams:
        q.add(WARN, "MAT-GALVANICO", "Contacto entre metales distintos: riesgo de corrosión galvánica; prever aislamiento.")
    for p in model.parts.values():
        if p.material and catalog.material(p.material).haz_reduction_required and any(
                j.kind == "soldadura" and any(model.instance(m).part is p for m in j.members) for j in model.joints):
            q.add(PEND, "MAT-HAZ", "Aluminio soldado: reducción de resistencia en ZAT (EN 1999-1-1 §6.1.6) no evaluada.")
            break
    if ps.get("ENTORNO") in ("exterior", "interior_humedo") and "acero_carbono" in fams and ps["ACABADO"] != "GALVANIZADO":
        q.add(WARN, "MAT-ENTORNO", "Entorno húmedo/exterior con acero al carbono pintado: valorar galvanizado o inoxidable.")
    if ps.get("ENTORNO") == "alimentario" and fams - {"acero_inoxidable"}:
        q.add(WARN, "MAT-ALIMENTARIO", "Uso alimentario: se recomienda acero inoxidable en superficies de contacto.")
    # espesores y fabricación
    for f in dfm:
        if f["level"] == "error":
            q.add(BLOCK, f["code"], f"{f['element']}: {f['message']} {f.get('proposal', '')}".strip())
    q.add(OK, "DFM", f"{sum(1 for f in dfm if f['level'] == 'error')} errores de fabricabilidad, "
                     f"{sum(1 for f in dfm if f['level'] == 'advertencia')} advertencias de fabricación.")
    # uniones / conectividad
    members = [i.id for i in model.instances if i.structural]
    welded = {m for j in model.joints if j.kind == "soldadura" for m in j.members}
    loose = [m for m in members if m not in welded]
    q.add(BLOCK if loose else OK, "UNI-CONECTIVIDAD", f"Barras sin unión: {loose}" if loose else
          f"Todas las barras estructurales ({len(members)}) están unidas; {len(model.joints)} uniones definidas.")
    # peso
    inst_mass = sum(i.part.mass for i in model.instances)
    q.add(OK if abs(inst_mass - bom["totals"]["total_mass"]) <= 0.0005 + 1e-6 * inst_mass else BLOCK, "BOM-PESO",
          f"Masa del BOM {bom['totals']['total_mass']:.3f} kg = suma de instancias {inst_mass:.3f} kg.")
    devs = []
    for r_ in bom["rows"]:
        if r_["nominal_mass"]:
            dv = abs(r_["unit_mass"] - r_["nominal_mass"]) / r_["nominal_mass"]
            if dv > 0.02:
                devs.append((r_["ref"], round(dv * 100, 2)))
    q.add(WARN if devs else OK, "BOM-PESO-NOMINAL", f"Diferencias > 2 % entre masa del sólido y masa nominal: {devs}"
          if devs else "Masas de los sólidos coherentes con las masas nominales (perfil kg/m, desarrollo×espesor) < 2 %.")
    # BOM
    qty = sum(r_["qty"] for r_ in bom["rows"])
    q.add(OK if qty == len(model.instances) else BLOCK, "BOM-CANTIDADES",
          f"Cantidades del BOM ({qty}) = instancias del modelo ({len(model.instances)}).")
    refs = [p.ref for p in model.parts.values()]
    q.add(OK if len(set(refs)) == len(refs) and all(refs) else BLOCK, "BOM-REFERENCIAS",
          "Referencias únicas asignadas a todas las piezas." if len(set(refs)) == len(refs) else "Referencias duplicadas.")
    # desarrollos
    from ..cad.sheetmetal import volume_consistency
    for p in model.parts.values():
        if isinstance(p, SheetPart):
            exp, dev = volume_consistency(p.spec, p.volume)
            q.add(OK if dev < 1e-6 else BLOCK, "CHAPA-DESARROLLO",
                  f"{p.ref}: desarrollo coherente con el sólido 3D (desviación de volumen {dev:.1e})." if dev < 1e-6
                  else f"{p.ref}: el desarrollo NO coincide con el sólido 3D (desviación de volumen {dev:.1e}); "
                       "suele deberse a taladros dentro de la zona de pliegue.")
    # verificación estructural
    st = eng["status"]
    if st == "NO_CUMPLE":
        fails = [c["description"] for c in eng["checks"] if c["status"] == "NO_CUMPLE"]
        q.add(WARN, "CALC-NO-CUMPLE", "Verificación estructural preliminar NO superada (no apto para fabricación "
                                      "hasta modificar el diseño): " + "; ".join(fails))
    elif st == "PENDIENTE":
        q.add(PEND, "CALC-PENDIENTE", "Verificación estructural incompleta: " + "; ".join(eng["pending"] or
                                                                                      ["datos pendientes"]))
    else:
        q.add(OK, "CALC", "Verificación estructural preliminar automatizada: CUMPLE.")
    q.add(PEND, "VALIDACION-TECNICA", "Validación definitiva por técnico competente pendiente de firma.")
    return q


def export_checks(q: QA, model, files: dict[str, Any], bom: dict) -> QA:
    """Integridad de archivos exportados y coherencia con el modelo."""
    st = files.get("step")
    if st:
        ok = st["solids"] == st.get("model_solids", len(model.instances)) and \
            abs(st["volume"] - st["model_volume"]) / st["model_volume"] < 1e-6
        q.add(OK if ok else BLOCK, "EXP-STEP", f"STEP reimportado: {st['solids']} sólidos, volumen {st['volume']:.0f} mm³ "
                                               f"(modelo {st['model_volume']:.0f} mm³).")
    for dx in files.get("dxf", []):
        ok = dx["errors"] == 0 and dx["closed_contours"] and dx["insunits"] == 4 and \
            abs(dx["width"] - dx["expected"][0]) < 0.01 and abs(dx["height"] - dx["expected"][1]) < 0.01
        q.add(OK if ok else BLOCK, "EXP-DXF", f"{dx['file']}: {dx['width']}×{dx['height']} mm (esperado "
                                              f"{dx['expected'][0]:.3f}×{dx['expected'][1]:.3f}), {dx['errors']} errores, "
                                              f"capas {', '.join(dx['layers'])}.")
    xl = files.get("excel")
    if xl:
        q.add(OK if xl["matches_bom"] and xl["formulas"] else BLOCK, "EXP-EXCEL",
              f"Excel: {xl['rows']} filas, {xl['qty']} uds, {xl['total_mass']} kg, fórmulas "
              f"{'presentes' if xl['formulas'] else 'ausentes'}.")
    dr = files.get("drawings")
    if dr:
        q.add(OK if dr["pages"] == dr["expected_pages"] else BLOCK, "EXP-PDF",
              f"Planos PDF: {dr['pages']} hojas (esperadas {dr['expected_pages']}).")
        mism = dr.get("mismatches", [])
        q.add(BLOCK if mism else OK, "PLANO-GEOMETRIA", f"Cotas de plano no coincidentes con la geometría: {mism}" if mism
              else f"{dr['checked_dims']} cotas de plano verificadas frente a la geometría y los parámetros.")
    return q


def drawing_consistency(model, drawings: dict) -> dict:
    """Compara las cotas registradas al dibujar con los parámetros y la geometría de las piezas."""
    env = model.dims.get("envelope", {})
    names = env.get("names", ("LONGITUD", "ANCHURA"))
    expected = {names[0]: env.get("dx"), names[1]: env.get("dy"), "ALTURA": env.get("zmax")}
    expected = {k: v for k, v in expected.items() if v is not None}
    for lv in model.dims.get("levels", []):
        name = lv[0]
        if model.dims.get(name) is not None:
            expected[name] = model.dims[name]
    expected.update(model.dims.get("drawing_expected", {}))
    for p in model.parts.values():
        if isinstance(p, SheetPart):
            fp = p.flat
            expected[f"{p.ref}_DESARROLLO_X"] = fp.width
            expected[f"{p.ref}_DESARROLLO_Y"] = fp.height
            expected[f"{p.ref}_LX"] = p.spec.Lx
            expected[f"{p.ref}_LY"] = p.spec.Ly
            expected[f"{p.ref}_ESPESOR"] = p.spec.t
        if isinstance(p, ProfilePart):
            expected[f"L_{p.ref}"] = p.length
    mism, checked = [], 0
    for sh in drawings["sheets"]:
        for dm in sh["dims"]:
            if dm["name"] in expected:
                checked += 1
                if abs(dm["value"] - expected[dm["name"]]) > 0.05:
                    mism.append({"sheet": sh["number"], "dim": dm["name"], "drawn": dm["value"],
                                 "expected": round(expected[dm["name"]], 3)})
    return {"checked_dims": checked, "mismatches": mism}
