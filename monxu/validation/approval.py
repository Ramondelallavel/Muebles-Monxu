"""Estados de aprobación de una revisión (= frontend/src/engine/approval.ts).

Un diseño avanza por nueve estados; cada uno exige el anterior:

1. Diseño generado — la revisión existe y su diseño se ha regenerado desde el modelo maestro.
2. Geometría validada — sin errores bloqueantes de geometría (sólidos, duplicados, interferencias, dimensiones,
   desarrollos, conectividad).
3. BOM validado — sin errores del BOM ni de los controles cruzados entre documentos, y cada componente comercial
   pendiente con su validación registrada (fabricante, modelo y ficha técnica).
4. Fabricabilidad revisada — sin errores de fabricación (DFM), la WPS validada cuando se requiere y la firma de
   quien revisa la fabricabilidad.
5. Cálculo estructural validado — el cálculo CUMPLE, cada comprobación pendiente de validación tiene su registro
   (ficha, ETA, certificado 3.1, anejo nacional) y firma el técnico que valida el cálculo.
6. Documentación generada — expediente de la revisión sin errores bloqueantes en sus archivos.
7. Revisión técnica pendiente — todo lo anterior cumplido; a la espera de aprobación.
8. Aprobado técnicamente — firma de aprobación sin ninguna validación abierta ni bloqueo de liberación.
9. Liberado para fabricación — firma de liberación tras la aprobación y con un expediente generado después de
   aprobar (los documentos llevan el sello de aprobación).

Ningún sello afirma «verificado» o «aprobado» mientras los campos de revisión y aprobación estén vacíos.
"""
from __future__ import annotations

from typing import Any

STATES = ["diseno_generado", "geometria_validada", "bom_validado", "fabricabilidad_revisada", "calculo_validado",
          "documentacion_generada", "revision_tecnica_pendiente", "aprobado_tecnicamente", "liberado_fabricacion"]
LABELS = {"diseno_generado": "Diseño generado", "geometria_validada": "Geometría validada",
          "bom_validado": "BOM validado", "fabricabilidad_revisada": "Fabricabilidad revisada",
          "calculo_validado": "Cálculo estructural validado", "documentacion_generada": "Documentación generada",
          "revision_tecnica_pendiente": "Revisión técnica pendiente", "aprobado_tecnicamente": "Aprobado técnicamente",
          "liberado_fabricacion": "Liberado para fabricación"}
SIGNOFFS = {"fabricabilidad": "fabricabilidad_revisada", "calculo": "calculo_validado",
            "aprobacion": "aprobado_tecnicamente", "liberacion": "liberado_fabricacion"}
GEO = ("GEO-", "UNI-", "CHAPA-")
BOM = ("BOM-", "XDOC-", "COMP-")
DFM = ("LAS-", "PLG-", "PRF-", "MON-", "DFM-", "SOL-", "GAL-", "ERG-")
CALC = ("CALC",)


def _items(qa: dict[str, Any] | None) -> list[dict[str, Any]]:
    return list((qa or {}).get("items", []))


def _blocking(items, prefixes) -> list[str]:
    return [i["code"] for i in items if i["level"] == "bloqueante" and i["code"].startswith(prefixes)]


def _open(items, prefixes, validations) -> list[str]:
    """Validaciones pendientes del ámbito sin registro."""
    return [i["code"] for i in items if i["level"] == "pendiente" and i["code"].startswith(prefixes)
            and i["code"] not in validations]


def evaluate(design_qa: dict[str, Any] | None, structural: str, dossier: dict[str, Any] | None,
             record: dict[str, Any] | None) -> dict[str, Any]:
    """Estado de aprobación de una revisión.

    design_qa: QA del diseño (items con code, level); structural: estado del cálculo (CUMPLE / NO_CUMPLE /
    PENDIENTE); dossier: {"qa": QA del expediente, "state": estado de aprobación con que se generó} o None;
    record: {"validations": {código: {...}}, "signoffs": {etapa: {"by", "date", ...}}}."""
    record = record or {}
    val = record.get("validations") or {}
    sig = record.get("signoffs") or {}
    items = _items(design_qa)
    d_items = _items((dossier or {}).get("qa")) or items
    gates: list[dict[str, Any]] = []

    def gate(state, ok, reasons, signer=None):
        gates.append({"id": state, "label": LABELS[state], "ok": bool(ok), "reasons": [r for r in reasons if r],
                      "signoff": signer})

    gate("diseno_generado", True, [])
    b = _blocking(items, GEO)
    gate("geometria_validada", not b, [f"errores de geometría: {', '.join(b)}" if b else ""])
    b, o = _blocking(items, BOM), _open(items, BOM, val)
    gate("bom_validado", not b and not o, [f"errores: {', '.join(b)}" if b else "",
                                           f"validaciones sin registrar: {', '.join(o)}" if o else ""])
    b, o, s = _blocking(items, DFM), _open(items, DFM, val), sig.get("fabricabilidad")
    gate("fabricabilidad_revisada", not b and not o and s, [f"errores de fabricación: {', '.join(b)}" if b else "",
                                                            f"validaciones sin registrar: {', '.join(o)}" if o else "",
                                                            "falta la firma de revisión de fabricabilidad" if not s else ""], s)
    o, s = _open(items, CALC, val), sig.get("calculo")
    gate("calculo_validado", structural == "CUMPLE" and not o and s,
         [f"cálculo {structural}" if structural != "CUMPLE" else "",
          f"validaciones sin registrar: {', '.join(o)}" if o else "",
          "falta la firma del técnico que valida el cálculo" if not s else ""], s)
    dq = (dossier or {}).get("qa") or {}
    gate("documentacion_generada", bool(dossier) and not dq.get("blocking"),
         ["expediente no generado" if not dossier else "",
          f"{dq.get('blocking')} errores bloqueantes en el expediente" if dossier and dq.get("blocking") else ""])
    gate("revision_tecnica_pendiente", True, [])
    blockers = [i["code"] for i in d_items if i.get("release_block") and not (i["level"] == "pendiente" and i["code"] in val)]
    blockers += [c for c in (i["code"] for i in items if i.get("release_block")
                             and not (i["level"] == "pendiente" and i["code"] in val)) if c not in blockers]
    s = sig.get("aprobacion")
    gate("aprobado_tecnicamente", s and not blockers, ["falta la firma de aprobación técnica" if not s else "",
                                                     f"bloqueos de liberación abiertos: {', '.join(blockers)}"
                                                     if blockers else ""], s)
    s = sig.get("liberacion")
    after = (dossier or {}).get("state") in ("aprobado_tecnicamente", "liberado_fabricacion")
    gate("liberado_fabricacion", s and after and not blockers,
         ["falta la firma de liberación para fabricación" if not s else "",
          "el expediente debe regenerarse después de la aprobación" if not after else ""], s)
    state = "diseno_generado"
    for g in gates:
        if not g["ok"]:
            break
        state = g["id"]
    open_all = sorted({i["code"] for i in items + d_items if i["level"] == "pendiente" and i["code"] not in val})
    return {"state": state, "label": LABELS[state], "index": STATES.index(state), "gates": gates,
            "open_validations": open_all, "release_blockers": blockers, "stamp": stamp(state, structural, sig)}


def stamp(state: str, structural: str, sig: dict[str, Any]) -> dict[str, str]:
    """Sello de los documentos según el estado de aprobación (nunca «verificado» sin firmas)."""
    def who(k):
        s = sig.get(k) or {}
        return f"{s.get('by', '')} ({s.get('date', '')})".strip()
    if structural == "NO_CUMPLE":
        return {"text": "NO APTO PARA FABRICACIÓN — verificación estructural no superada", "level": "error"}
    if state == "liberado_fabricacion":
        return {"text": f"LIBERADO PARA FABRICACIÓN — {who('liberacion')}", "level": "info"}
    if state == "aprobado_tecnicamente":
        return {"text": f"APROBADO TÉCNICAMENTE — {who('aprobacion')} · NO LIBERADO PARA FABRICACIÓN", "level": "info"}
    if structural == "PENDIENTE":
        return {"text": "PRELIMINAR — verificación estructural pendiente de datos · NO APTO PARA FABRICACIÓN",
                "level": "warn"}
    return {"text": f"{LABELS[state].upper()} — PENDIENTE DE REVISIÓN Y APROBACIÓN TÉCNICA · NO APTO PARA "
                    "FABRICACIÓN", "level": "warn"}


def can_sign(evaluation: dict[str, Any], stage: str) -> tuple[bool, str]:
    """Una firma solo puede registrarse si los estados anteriores al suyo se cumplen."""
    target = SIGNOFFS[stage]
    k = STATES.index(target)
    for g in evaluation["gates"][:k]:
        if not g["ok"]:
            return False, f"{g['label']}: {'; '.join(g['reasons']) or 'no cumplido'}"
    own = evaluation["gates"][k]
    other = [r for r in own["reasons"] if not r.startswith("falta la firma")]
    if other:
        return False, f"{own['label']}: {'; '.join(other)}"
    return True, ""
