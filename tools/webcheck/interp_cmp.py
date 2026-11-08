"""Validación cruzada del intérprete del asistente: navegador (TypeScript) frente a referencia (Python).

Uso: python tools/webcheck/interp_cmp.py BUNDLE_interp.mjs
(cd frontend && npx esbuild ../tools/webcheck/interp.ts --bundle --platform=node --format=esm --outfile=/tmp/interp.mjs)
Compara familia, valores, elementos no soportados y notas para cada frase.
"""
import json
import subprocess
import sys

from monxu.ai.interpreter import parse

texts = ["Mesa con ruedas de 1200x700x900, 120 kg, con peto trasero de 60 mm",
 "Carro de taller 1200x700x900 con dos asas, 150 kg", "Carro 1000x600x900 sin asa, 100 kg",
 "Mesa de laboratorio inoxidable 1500x750x900 con peto, 150 kg",
 "Puesto de trabajo 1600x750x900 con estante superior, tope trasero 40 mm, 200 kg",
 "Banco de trabajo movil 1500x700x850 con asa en cada extremo y 5 cm de peto",
 "Mesa 1800x800x900 sin peto, 300 kg, balda inferior 100 kg", "Carro con asa 900x500x850, 60 kg",
 "Mesa sin ruedas 1200x600x900, 100 kg", "Mesa 2400x900x900 de trabajo pesado, 800 kg distribuidos y carga puntual de 150 kg", "Mesa 1800x800x900, 300 kg, carga concentrada: 120 kg", "Mesa de soldadura 2000x1000x850 sistema 28, placa de 20 mm, 1000 kg", "Mesa para soldar 1200x800 con taladros de 16 y vuelo de 80 mm, 500 kg y 150 kg puntual", "Banco de soldadura 1500x1000x850 placa lisa de 15 mm de espesor con peto", "Puesto de trabajo 1200x700x850 con reposapiés a 220 mm, 100 kg", "Mesa 1500x750x900 sin reposapies, con apoyapies de 30 cm",
 "Carro de picking de 4 niveles 1200x600x1600, 40 kg por nivel, con asa en los dos extremos",
 "Estanteria con ruedas 1000x500x1500 de 5 baldas, 25 kg por balda, sin asa",
 "Carro de bandejas inoxidable 800x500x1500, 5 niveles",
 "Estanteria 1500x600x2000 de 5 niveles, 150 kg por nivel, anclada al suelo",
 "Necesito una estantería en batería de tres módulos de 1000 mm, 500 de fondo y 2 m de alto, 5 niveles con 100 kg por bandeja, anclada al suelo",
 "Estantería en batería de 4 m de largo con módulos de 1 m, 400 de profundidad, 2200 de altura y seis niveles",
 "Batería de estanterías de 3 módulos, 3600 mm de frente total, 600 de fondo, 2000 de alto",
 "estantería de 2 módulos 1200 x 600 x 2000 con 4 niveles de 150 kg por nivel",
 "estantería modular de 3 cuerpos de 900 mm con 50 niveles", "estantería de 600 de fondo y 2000 de alto",
 "estantería de 2 m de largo, 600 de fondo", "estantería con 1800 de frente y 5 niveles",
 "Necesito una tarima de 2000 x 1000 a 300 mm de altura para un operario, 2 kN/m2, anclada",
 "plataforma de trabajo baja de 1500 por 800, 250 de alto", "podio de 3000x1200x450 con 1000 kg y carga puntual de 250 kg",
 "tarima de 1200x800x200 de acero inoxidable con balda", "tarima de 2 x 1 m con 300 kg/m2", "mesa de 1800 x 800 con 300 kg",
 "carga de 2 x 150 kg en una mesa 1200x700x900", "estanteria de 1200 por 400 con 5 niveles de 80 kg por nivel", "Puesto de trabajo 1600x750x900 con estante superior y panel perforado, 200 kg"]
texts += [
    "carro plataforma de 1200x800 para 500 kg con asa a 950 mm", "plataforma con ruedas 1000x600, 300 kg, dos asas",
    "plataforma rodante sin asa de 1200 x 800, 400 kg", "plataforma de trabajo con ruedas para un operario 1500x800",
    "carro de taller 1000x600x900 con asa a 1000 mm de altura, 120 kg",
    "carro plataforma 1000 x 600 con asa a 900 mm de altura y peto de 50 mm, 250 kg",
    "carro de base plana inoxidable 800x500 de 120 kg", "carro de plataforma de 1,6 x 0,8 m con 600 kg y asa en cada extremo",
    "mesa 1800x800x900 400 kg en la encimera y 100 kg en la balda", "mesa 1800x800x950 400 kg",
    "mesa de 1.500 x 800 x 900 con 1 500 kg", "estanteria 2000 x 600 x 2.000, 5 niveles de 1.000 kg",
    "mesa 1500x800x900 con balda de 80 kg y 200 kg en la encimera", "mesa 1800x800x900, 400 kg, balda de 100 kg",
    "mesa de 2000x800x900 con balda vacia y 300 kg sobre la encimera", "estanteria 1500x600x2000 5 baldas de 80 kg cada una",
    "carro estanteria de 4 bandejas de 30 kg", "estanteria de 1500x600x2000 con 5 niveles de 100 kg anclada al suelo",
]
js = json.loads(subprocess.run(["node", sys.argv[1]], input=json.dumps(texts), capture_output=True, text=True,
                               check=True).stdout)
bad = 0
for t, j in zip(texts, js):
    p = parse(t)
    py = {"family": p.family, "values": p.values, "unsupported": p.unsupported, "notes": p.notes}
    if py != j:
        bad += 1
        print("DIFF", t, "\n py", py, "\n js", j)
print("FRASES", len(texts), "DIFERENCIAS", bad)
sys.exit(1 if bad else 0)
