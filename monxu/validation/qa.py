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
from ..core.model import PlatePart, ProfilePart, SheetPart

BLOCK, WARN, OK, PEND = "bloqueante", "advertencia", "ok", "pendiente"


SEVERITIES = ("CRÍTICO", "BLOQUEANTE", "ADVERTENCIA", "INFORMATIVO")
#: códigos cuyo fallo invalida la coherencia entre documentos o la seguridad: severidad CRÍTICO
CRITICAL_PREFIXES = ("XDOC-", "GEO-VALIDA", "GEO-INTERFERENCIAS", "GEO-DIMENSIONES", "BOM-", "EXP-", "PLANO-", "CALC-NO")
DOCUMENTS = (("XDOC-", "Documentación cruzada"), ("GEO-", "Modelo 3D"), ("UNI-", "Modelo 3D"), ("BOM-", "BOM"),
             ("CHAPA-", "Desarrollos y DXF"), ("MAT-", "Materiales"), ("CALC", "Cálculo estructural"),
             ("COMP-", "Componentes comerciales"), ("SOL-", "Soldadura"), ("EXP-STEP", "STEP"), ("EXP-STL", "STL"),
             ("EXP-DXF", "DXF"), ("EXP-EXCEL", "Excel BOM"), ("EXP-PDF", "Planos"), ("PLANO-", "Planos"),
             ("DFM", "Fabricación (DFM)"), ("LAS-", "Fabricación (DFM)"), ("PLG-", "Fabricación (DFM)"),
             ("PRF-", "Fabricación (DFM)"), ("MON-", "Montaje y tornillería"), ("GAL-", "Fabricación (DFM)"))
RESULTS = {BLOCK: "NO CUMPLE", WARN: "ADVERTENCIA", PEND: "PENDIENTE DE VALIDACIÓN", OK: "CUMPLE"}


def _document(code: str) -> str:
    return next((d for p, d in DOCUMENTS if code.startswith(p)), "Modelo")


class QA:
    """Motor central de validaciones. Cada comprobación lleva código único, descripción, resultado, severidad,
    documento afectado, valor esperado, valor obtenido, diferencia, criterio de aceptación y acción correctora.
    ``level`` (bloqueante / advertencia / pendiente / ok) se conserva por compatibilidad: bloqueante impide exportar;
    bloqueante, pendiente y lo marcado con ``release_block`` impiden liberar para fabricación."""

    def __init__(self):
        self.items: list[dict[str, Any]] = []

    def add(self, level, code, message, **data):
        sev = data.pop("severity", None) or (
            ("CRÍTICO" if code.startswith(CRITICAL_PREFIXES) else "BLOQUEANTE") if level == BLOCK else
            "BLOQUEANTE" if level == PEND else "ADVERTENCIA" if level == WARN else "INFORMATIVO")
        item = {"level": level, "code": code, "message": message, "severity": sev,
                "result": data.pop("result", None) or RESULTS[level], "description": data.pop("description", None) or message,
                "document": data.pop("document", None) or _document(code), "expected": data.pop("expected", None),
                "obtained": data.pop("obtained", None), "difference": data.pop("difference", None),
                "criterion": data.pop("criterion", None), "action": data.pop("action", None),
                "release_block": data.pop("release_block", level in (BLOCK, PEND)), **data}
        self.items.append(item)

    def result(self) -> dict[str, Any]:
        lv = [i["level"] for i in self.items]
        blocking = lv.count(BLOCK)
        res = "bloqueante" if blocking else ("advertencia" if WARN in lv else "ok")
        sev = {s: sum(1 for i in self.items if i["severity"] == s and i["level"] != OK) for s in SEVERITIES}
        rb = [i["code"] for i in self.items if i["release_block"]]
        return {"result": res, "blocking": blocking, "warnings": lv.count(WARN), "pending": lv.count(PEND),
                "ok": lv.count(OK), "items": self.items, "by_severity": sev, "release_blockers": rb,
                "summary": f"{blocking} errores bloqueantes, {lv.count(WARN)} advertencias, {lv.count(PEND)} "
                           f"validaciones pendientes, {lv.count(OK)} comprobaciones satisfactorias."}


def model_checks(model, interf: dict, eng: dict, dfm: list, bom: dict, plan: dict | None = None,
                 cost: dict | None = None) -> QA:
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
        if over > 0.5:      # qué sobresale (pies, ruedas, manetas...), no siempre los apoyos
            names: list[str] = []
            for i in model.instances:
                b0, b1 = i.bbox
                if max(lo[0] - b0[0], lo[1] - b0[1], b1[0] - hi[0], b1[1] - hi[1]) > 0.5 and i.part.name not in names:
                    names.append(i.part.name)
            q.add(WARN, "GEO-SALIENTE", f"Elementos sobresalen {over:.1f} mm del contorno del producto "
                                        f"({'; '.join(names[:3])}{'…' if len(names) > 3 else ''}): considerar en "
                                        "implantación.",
                  expected=f"contorno {hi[0] - lo[0]:.1f} × {hi[1] - lo[1]:.1f} mm",
                  obtained=f"envolvente máxima {bhi[0] - blo[0]:.1f} × {bhi[1] - blo[1]:.1f} × {bhi[2] - blo[2]:.1f} mm",
                  difference=round(over, 2), criterion="Las cotas generales son las del contorno declarado; la envolvente "
                  "máxima (cabezas de tornillo, pies, manetas) figura en el plano de conjunto",
                  action="Considerar la envolvente máxima en la implantación y el embalaje")
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
    # sólido B-rep frente a la definición analítica de perfiles y pletinas: detecta booleanas fallidas (taladros no
    # restados, sólidos degenerados); misma comprobación que el motor del navegador
    vol_dev = []
    for p in model.parts.values():
        if isinstance(p, ProfilePart):
            exp = p.profile.props.A * p.length - sum(math.pi * h[3] ** 2 / 4 * p.profile.t for h in p.holes)
        elif isinstance(p, PlatePart):
            exp = (p.w * p.h - (4 - math.pi) * p.corner_r ** 2 - sum(math.pi * d ** 2 / 4 for _, _, d in p.holes)) * p.t
        else:
            continue
        dev = abs(p.volume - exp) / exp
        if dev > 5e-3:
            vol_dev.append(f"{p.ref} {dev * 100:.2f} %")
    q.add(BLOCK if vol_dev else OK, "GEO-VOLUMEN", f"Volumen del sólido distinto del analítico: {'; '.join(vol_dev)}"
          if vol_dev else "Volumen de cada sólido (perfiles con taladros y pletinas) coherente con su definición analítica "
                          "(< 0,5 %).")
    # verificación estructural
    st = eng["status"]
    if st == "NO_CUMPLE":
        fails = [c["description"] for c in eng["checks"] if c["status"] == "NO_CUMPLE"]
        q.add(WARN, "CALC-NO-CUMPLE", "Verificación estructural NO superada (no apto para fabricación "
                                      "hasta modificar el diseño): " + "; ".join(fails), release_block=True,
              severity="CRÍTICO", result="NO CUMPLE", action="Modificar el diseño (perfiles, espesores o cargas)")
    elif st == "PENDIENTE":
        q.add(PEND, "CALC-PENDIENTE", "Verificación estructural incompleta: " + "; ".join(eng["pending"] or
                                                                                      ["datos pendientes"]))
    else:
        q.add(OK, "CALC", "Comprobaciones estructurales calculadas: CUMPLEN." if eng.get("validation_pending") else
              "Verificación estructural automatizada completa: CUMPLE.")
    for v in eng.get("validation_pending", []):
        q.add(PEND, f"CALC-VAL-{v['id']}", f"Cálculo pendiente de validación — {v['description']}: {v['reason']}.",
              document="Cálculo estructural", criterion="Dato certificado (ficha técnica, ETA, certificado 3.1 o anejo "
              "nacional) que sustituya la hipótesis", action="Validar con el documento correspondiente y registrar su "
              "referencia en la validación técnica")
    if plan is not None:
        cross_checks(q, model, eng, dfm, bom, plan, cost)
    return q


def cross_checks(q: QA, model, eng: dict, dfm: list, bom: dict, plan: dict, cost: dict | None) -> None:
    """Controles cruzados entre documentos generados desde el modelo maestro (= pipeline.ts, crossChecks)."""
    from collections import Counter
    from ..docs import assembly
    lot = plan.get("lot", 1)
    inst = Counter(i.part.key for i in model.instances)
    # BOM ↔ instancias 3D, referencia a referencia
    bad = [f"{r['ref']}: BOM {r['qty']} / 3D {inst[p.key]}" for p in model.parts.values()
           for r in bom["rows"] if r["ref"] == p.ref and r["qty"] != inst[p.key]]
    q.add(BLOCK if bad else OK, "XDOC-BOM-3D", "BOM frente a instancias del modelo 3D: " +
          ("; ".join(bad) if bad else f"{len(bom['rows'])} referencias, {sum(inst.values())} instancias coincidentes."),
          expected=sum(inst.values()), obtained=sum(r["qty"] for r in bom["rows"]),
          difference=sum(r["qty"] for r in bom["rows"]) - sum(inst.values()),
          criterion="Cantidad de cada referencia del BOM = instancias del 3D", action="Regenerar el BOM desde el modelo")
    by_ref = {p.ref: inst[p.key] * lot for p in model.parts.values()}
    # BOM ↔ plan de corte y anidado (lote)
    cut = Counter(x["ref"] for c in plan["cutting"] for b in c["bars"] for x in b["cuts"])
    nest = Counter(pl["ref"] for n in plan["nesting"] if n.get("feasible") for sh in n["sheets"] for pl in sh["placements"])
    bad = [f"{ref}: plan {cut[ref]} / BOM {by_ref[ref]}" for p in model.parts.values() if p.kind == "perfil"
           for ref in [p.ref] if cut[ref] != by_ref[ref]]
    bad += [f"{ref}: anidado {nest[ref]} / BOM {by_ref[ref]}" for p in model.parts.values() if p.kind in ("chapa", "pletina")
            for ref in [p.ref] if nest[ref] != by_ref[ref] and all(n.get("feasible") for n in plan["nesting"])]
    q.add(BLOCK if bad else OK, "XDOC-BOM-CORTE", "Piezas del plan de corte y del anidado frente al BOM: " +
          ("; ".join(bad) if bad else f"{sum(cut.values())} piezas de perfil y {sum(nest.values())} de chapa (lote de {lot})."),
          expected="cantidad BOM × lote", obtained="piezas cortadas y anidadas",
          criterion="Cada pieza del BOM aparece en el plan de corte o en el anidado tantas veces como unidades × lote",
          action="Regenerar el plan de fabricación")
    # BOM ↔ compras (componentes comerciales)
    std = Counter(i.part.code for i in model.instances if i.part.kind == "normalizado")
    pur = {p["code"]: p["qty"] for p in plan["purchases"]["items"] if p["type"] == "Comercial"}
    bad = [f"N-{c}: compras {pur.get(c)} / BOM {n * lot}" for c, n in sorted(std.items()) if pur.get(c) != n * lot]
    bad += [f"N-{c} sobrante en compras" for c in pur if c not in std]
    q.add(BLOCK if bad else OK, "XDOC-BOM-COMPRAS", "Componentes comerciales de la lista de compras frente al BOM: " +
          ("; ".join(bad) if bad else f"{len(std)} referencias coincidentes (lote de {lot})."),
          criterion="Unidades compradas = unidades del BOM × lote", action="Regenerar la lista de compras")
    # componentes comerciales del BOM: referencia N-<código> del catálogo y masa de catálogo positiva
    bad = [r["ref"] for r in bom["rows"] if r["kind"] == "normalizado" and
           (not r["code"] or r["ref"] != f"N-{r['code']}" or not (r["unit_mass"] and r["unit_mass"] > 0))]
    q.add(BLOCK if bad else OK, "BOM-COMERCIALES", "Componentes comerciales del BOM: " +
          ("sin referencia de catálogo o sin masa: " + ", ".join(bad) if bad else
           f"{len(std)} referencias N-<código> con masa de catálogo."),
          criterion="Cada componente comercial tiene referencia de catálogo y masa positiva",
          action="Completar el componente en la base de componentes comerciales")
    # compras ↔ optimización
    bars = {p["group"]: p["qty"] for p in plan["purchases"]["items"] if p["type"] == "Perfil"}
    bad = []
    for c in plan["cutting"]:
        grp = f"{c['profile']} {c['material']}"
        if bars.get(grp, 0) != c["n_bars"]:
            bad.append(f"{grp}: compras {bars.get(grp, 0)} / plan {c['n_bars']}")
    for n in plan["nesting"]:
        if not n.get("feasible"):
            continue
        g = f"{n['material']} e={n['thickness']:g} mm"
        full = sum(p["qty"] for p in plan["purchases"]["items"] if p.get("group") == g and p["type"] == "Chapa")
        cust = sum(p["qty"] for p in plan["purchases"]["items"] if p.get("group") == g and p["type"] == "Chapa (corte a medida)")
        if full != n["purchase"]["n_full"] or cust != n["purchase"]["n_custom"]:
            bad.append(f"{g}: compras {full}+{cust} / anidado {n['purchase']['n_full']}+{n['purchase']['n_custom']}")
    q.add(BLOCK if bad else OK, "XDOC-COMPRAS-OPT", "Lista de compras frente al plan de corte y al anidado: " +
          ("; ".join(bad) if bad else "barras y chapas compradas = las del plan de corte y del anidado."),
          criterion="Barras y chapas de la lista de compras = las de la optimización", action="Regenerar la lista de compras")
    # balance de material (barra a barra y por grupo)
    bad = [f"{c['profile']} barra {b['bar']}: {b['balance_mm']:g} mm" for c in plan["cutting"] for b in c["bars"]
           if abs(b["balance_mm"]) > 1e-6]
    bad += [f"{r['group']}: {r['balance']}" for r in plan["balance"]["rows"] if r["balance"] is not None and abs(r["balance"]) > 1e-6]
    q.add(BLOCK if bad else OK, "XDOC-BALANCE", "Balance de material: " + ("; ".join(bad) if bad else
          "cada barra cumple L = despunte inicial + piezas + sierra + despunte final + retal, y lo comprado = neto + "
          "desperdicio + retales en cada grupo."), expected=0.0, obtained=max([0.0] + [abs(b["balance_mm"]) for c in
          plan["cutting"] for b in c["bars"]]), criterion="Balance nulo (±1e-6)", action="Revisar el optimizador")
    # peso: BOM ↔ geometría ↔ cálculo
    t = bom["totals"]
    sw = eng.get("self_weight")
    if sw:
        d = sw["total_kg"] - t["mass_product_kg"]
        ok = abs(d) <= 0.002 * t["mass_product_kg"] + 0.01
        q.add(OK if ok else BLOCK, "XDOC-PESO-CALC", f"Peso propio del cálculo {sw['total_kg']:.3f} kg (aplicado "
              f"{sw['applied_kg']:.3f} kg + {sw['below_supports_kg']:.3f} kg bajo los apoyos) frente a la masa del producto "
              f"del BOM {t['mass_product_kg']:.3f} kg.", expected=t["mass_product_kg"], obtained=sw["total_kg"],
              difference=round(d, 3), criterion="|diferencia| ≤ 0,2 % + 0,01 kg (definición analítica frente a sólido)",
              action="Revisar las masas que no se aplican al modelo de cálculo")
    q.add(OK, "XDOC-PESO-COMPRA", f"Masas separadas: producto {t['mass_product_kg']:.2f} kg/ud (fabricadas "
          f"{t['mass_manufactured_kg']:.2f} + comerciales {t['mass_commercial_kg']:.2f}); material comprado "
          f"{t['mass_purchased_kg']:.2f} kg, desperdicio {t['mass_waste_kg']:.2f} kg y retales {t['mass_reusable_kg']:.2f} kg "
          f"para el lote de {lot}: no se suman entre sí.", severity="INFORMATIVO")
    # presupuesto ↔ compras
    if cost:
        raw = sum(p["mass_kg"] for p in plan["purchases"]["items"] if p["type"].startswith(("Perfil", "Chapa"))
                  and p.get("purchase", True) and p["mass_kg"] is not None)
        if cost["material_basis"] == "compra" and cost["lot"] == lot:
            mkg = cost["material_kg_per_unit"] * lot
            ok = abs(mkg - raw) <= 0.01 * max(1, len(plan["purchases"]["items"]))
            q.add(OK if ok else BLOCK, "XDOC-PRESUPUESTO-COMPRAS", f"Material del presupuesto {mkg:.3f} kg frente al "
                  f"material comprado {raw:.3f} kg (lote de {lot}).", expected=round(raw, 3), obtained=round(mkg, 3),
                  difference=round(mkg - raw, 3), criterion="Material presupuestado = barras y chapas compradas",
                  action="Recalcular el presupuesto con el plan de fabricación")
    # instrucciones de montaje ↔ BOM (referencias y designaciones de tornillería)
    texts = list(assembly.step_texts(model).values())
    bad = assembly.designation_issues(model, texts)
    q.add(BLOCK if bad else OK, "XDOC-TORNILLERIA-INSTR", "Referencias de las instrucciones de montaje frente al BOM: " +
          (", ".join(bad) + " no están en el BOM" if bad else "todas las referencias y designaciones citadas están en "
                                                               "el BOM y en el 3D."),
          expected="referencias del BOM", obtained=", ".join(bad) or "coincidentes",
          criterion="Las instrucciones usan exactamente las referencias del BOM y del 3D",
          action="Corregir el texto de montaje de la familia")
    # textos generados ↔ producto: nada de vocabulario de otra familia (p. ej. «encimera» en una estantería)
    texts += assembly.notes(model, assembly.default_notes(model)) + [f["message"] for f in dfm] + \
        list(eng.get("hypotheses", [])) + list(eng.get("limitations", [])) + [c["label"] for c in eng.get("load_cases", [])]
    bad = assembly.foreign_words(model, texts)
    q.add(BLOCK if bad else OK, "XDOC-TEXTOS-PRODUCTO", "Textos de montaje, fabricación y cálculo frente al producto: " +
          ("mencionan una encimera que el producto no tiene: " + " | ".join(bad) if bad else
           "sin vocabulario de otro tipo de producto."), expected="textos propios del producto",
          obtained=f"{len(bad)} textos ajenos" if bad else "coherentes",
          criterion="Los textos generados solo nombran elementos que existen en el modelo",
          action="Corregir el texto por defecto o el de la familia")
    # soldadura ↔ cálculo (garganta)
    joints = {j.id: j for j in model.joints}
    bad = []
    for c in eng["checks"]:
        if c["id"].startswith("W.") and c["id"][2:] in joints:
            a = (c.get("details") or {}).get("a_mm")
            if a is not None and abs(a - joints[c["id"][2:]].weld["a"]) > 1e-9:
                bad.append(c["id"])
    q.add(BLOCK if bad else OK, "XDOC-SOLDADURA-CALC", "Gargantas del cálculo frente a las de las uniones del modelo: " +
          (", ".join(bad) if bad else "coincidentes."), criterion="El cálculo usa la garganta de cada unión del modelo",
          action="Regenerar el cálculo")
    # componentes comerciales sin validar
    for code in sorted(std):
        c = catalog.component(code)
        v = c.get("validation") or {}
        if v.get("status") != "definido_por_norma":
            q.add(PEND, f"COMP-{code}", f"N-{code} ({c['name']}): pendiente de validación — faltan "
                  f"{', '.join(v.get('missing', ['datos técnicos']))}.", document="Componentes comerciales",
                  criterion="Fabricante, modelo, ficha técnica y capacidades certificadas",
                  action="Seleccionar el modelo comercial y registrar su ficha en la validación")
    # WPS cualificada
    thin = [j for j in model.joints if j.kind == "soldadura" and j.weld["a"] < 3]
    if thin:
        q.add(PEND, "SOL-WPS", f"{len(thin)} cordones con garganta < 3 mm en pared delgada: requieren WPS cualificada "
              "(EN ISO 15614-1) y control de penetración antes de fabricar.", document="Soldadura",
              criterion="WPS cualificada y soldadores cualificados (EN ISO 9606-1) para el espesor y la posición",
              action="Cualificar la WPS y registrar su referencia en la validación técnica")


def export_checks(q: QA, model, files: dict[str, Any], bom: dict) -> QA:
    """Integridad de archivos exportados y coherencia con el modelo."""
    st = files.get("step")
    if st:
        ok = st["solids"] == st.get("model_solids", len(model.instances)) and \
            abs(st["volume"] - st["model_volume"]) / st["model_volume"] < 1e-6
        q.add(OK if ok else BLOCK, "EXP-STEP", f"STEP reimportado: {st['solids']} sólidos, volumen {st['volume']:.0f} mm³ "
                                               f"(modelo {st['model_volume']:.0f} mm³).")
    q.add(OK, "EXP-STEP-TIPO", "STEP del servidor: B-rep analítico de OpenCascade (caras planas, cilíndricas y tóricas "
          "exactas), no facetado.", severity="INFORMATIVO", document="STEP")
    sl = files.get("stl")
    if sl:
        mb = sl["model_bbox"]
        d_box = max(max(abs(sl["bbox"][0][j] - mb[0][j]), abs(sl["bbox"][1][j] - mb[1][j])) for j in range(3))
        d_vol = abs(sl["volume"] - sl["model_volume"]) / sl["model_volume"]
        ok = sl["bytes_ok"] and sl["triangles"] > 0 and d_vol < 0.01 and d_box < 0.2
        q.add(OK if ok else BLOCK, "EXP-STL", f"STL releído: {sl['triangles']} triángulos, volumen {sl['volume'] / 1e6:.4f} dm³ "
              f"(sólidos {sl['model_volume'] / 1e6:.4f} dm³, teselado a 0,1 mm), envolvente con desviación máxima "
              f"{d_box:.3f} mm; unidades mm, ejes del modelo.", expected=round(sl["model_volume"], 1),
              obtained=round(sl["volume"], 1), difference=round(d_vol, 6),
              criterion="Volumen ±1 % (teselado) y envolvente ±0,2 mm respecto a los sólidos B-rep", action="Regenerar el STL")
    for nd in files.get("nesting_dxf", []):
        ok = nd["errors"] == 0 and nd["cut_contours"] == nd["expected_parts"] and nd["format"] is not None and \
            abs(nd["format"][0] - nd["expected_format"][0]) < 0.01 and abs(nd["format"][1] - nd["expected_format"][1]) < 0.01
        q.add(OK if ok else BLOCK, "EXP-DXF-ANIDADO", f"{nd['file']}: {nd['cut_contours']} contornos exteriores (anidado "
              f"{nd['expected_parts']}), chapa {nd['format'][0]:.1f}×{nd['format'][1]:.1f} mm (anidado "
              f"{nd['expected_format'][0]:g}×{nd['expected_format'][1]:g})." if nd["format"] else f"{nd['file']}: sin contorno de chapa.",
              expected=nd["expected_parts"], obtained=nd["cut_contours"],
              criterion="El DXF del anidado tiene las mismas piezas y la misma chapa que el anidado del plan",
              action="Regenerar el anidado")
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
        q.add(BLOCK if mism else OK, "PLANO-GEOMETRIA", f"Planos no coincidentes con el modelo (cotas, cantidades, pesos, "
              f"taladros, barras del plan de corte o textos cortados): {mism}" if mism
              else f"{dr['checked_dims']} cotas y registros de plano verificados frente a la geometría, los parámetros, "
                   "el despiece y el plan de corte; ninguno ausente ni truncado.")
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
        # cantidades impresas en el despiece frente a las instancias del 3D, y peso unitario impreso (en gramos)
        # frente al de la pieza con el redondeo del BOM
        expected[f"CANT_{p.ref}"] = sum(1 for i in model.instances if i.part.key == p.key)
        expected[f"PESO_G_{p.ref}"] = round(p.mass, 4) * 1000
    expected.update(drawings.get("expected") or {})
    mism, checked, drawn = [], 0, set()
    for sh in drawings["sheets"]:
        for dm in sh["dims"]:
            if dm["name"] in expected:
                checked += 1
                drawn.add(dm["name"])
                if abs(dm["value"] - expected[dm["name"]]) > 0.05:
                    mism.append({"sheet": sh["number"], "dim": dm["name"], "drawn": dm["value"],
                                 "expected": round(expected[dm["name"]], 3)})
    # lo que debe figurar y no figura: un perfil sin su longitud o sus taladros, una pieza sin fila en el despiece,
    # barras o piezas del plan de corte sin representar (una hoja llena no puede omitir nada sin aviso)
    for name in sorted(n for n in expected if n.startswith(REQUIRED_IN_DRAWINGS) and n not in drawn):
        mism.append({"sheet": "—", "dim": name, "drawn": None, "expected": round(expected[name], 3)})
    for sh in drawings["sheets"]:                   # un texto de tabla cortado («N-TORNILLO_ISO7380…») no identifica nada
        for txt in sh.get("truncated", []):
            mism.append({"sheet": sh["number"], "dim": "TEXTO_TRUNCADO", "drawn": None, "expected": txt})
    if drawings.get("announced") is not None and drawings["announced"] != len(drawings["sheets"]):
        mism.append({"sheet": "—", "dim": "HOJAS", "drawn": len(drawings["sheets"]), "expected": drawings["announced"]})
    return {"checked_dims": checked, "mismatches": mism}


#: registros que deben figurar siempre en los planos (longitud y taladros de cada perfil, cantidad y peso de cada
#: pieza del despiece, barras y piezas de cada grupo del plan de corte)
REQUIRED_IN_DRAWINGS = ("L_", "CANT_", "PESO_G_", "TAL_", "BARRAS_", "PIEZAS_CORTE_")
