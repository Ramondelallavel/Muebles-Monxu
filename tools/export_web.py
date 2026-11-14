"""Exporta las definiciones de familia (parámetros, plantillas, reglas de dimensionado) para el motor web."""
import json
import sys
from pathlib import Path

from monxu import catalog
from monxu.families import REGISTRY, library

out = {"catalog_versions": catalog.catalog_versions(), "library": library(), "families": {}}
for fid, f in REGISTRY.items():
    d = f.describe()
    d.update(templates=f.templates(), candidates=f.candidates, constructive_defaults=f.constructive_defaults,
             leg_param=f.leg_param, frame_params=list(f.frame_params), auto_in_construct=list(f.auto_in_construct))
    out["families"][fid] = d
dest = Path(sys.argv[1] if len(sys.argv) > 1 else "frontend/src/engine/data/families.json")
dest.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print("exportado", dest, {k: len(v["params"]) for k, v in out["families"].items()})
