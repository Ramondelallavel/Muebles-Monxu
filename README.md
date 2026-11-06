# Muebles Monxu — Plataforma de ingeniería y diseño paramétrico de mobiliario industrial

Convierte una necesidad expresada en lenguaje natural en un producto industrial definido
geométrica, mecánica y constructivamente: modelo B-rep real, cálculo, planos, desarrollos,
BOM, optimización de corte y expediente de fabricación, todo derivado de una única fuente de
parámetros.

> **Estado:** núcleo funcional con dos familias completas, **mesa industrial** y **estantería
> industrial**, y el caso de aceptación §23 superado por pruebas automáticas. Puestos de trabajo,
> armarios y varios accesorios están previstos en la arquitectura pero **no implementados**.

## Puesta en marcha

Requisitos: Python ≥ 3.11 y Node 22 (sólo para compilar la interfaz).

```bash
python3 -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
```

```bash
cd frontend && npm install && npm run build && cd ..
```

```bash
MONXU_DATA=var uvicorn monxu.api.main:app --host 127.0.0.1 --port 8000
```

Abra `http://127.0.0.1:8000`. Los datos (SQLite y expedientes) se guardan en `var/`.

Para el asistente con Claude (opcional; sin él se usa el intérprete local determinista), defina
`MONXU_LLM=1` y `ANTHROPIC_API_KEY`.

Pruebas, incluido el caso de aceptación completo (unos 80 s):

```bash
python -m pytest -q
```

## Qué está implementado y verificado

| Fase | Estado | Evidencia |
|---|---|---|
| 1. Fundamentos | ✔ | Catálogos versionados, tabla de parámetros con origen del valor (usuario, IA, regla, cálculo), BD de proyectos y revisiones, interfaz |
| 2. Motor CAD | ✔ | B-rep OpenCascade, árbol de operaciones con dependencias, ensamblaje con IDs únicos, interferencias por volumen común |
| 3. Mesa industrial | ✔ | Patas, bastidores superior e inferior, travesaños por cálculo, encimera y balda plegadas, placas base, pies, fijación atornillada |
| 4. Documentación | ✔ | 12 hojas de planos (conjunto, estructura, perfiles, chapa, desarrollos, pletinas, soldaduras con detalles, explosionado, montaje, despiece), STEP de conjunto y de cada pieza, STL, BREP, GLB, DXF, Excel con fórmulas, informe PDF |
| 5. Fabricación | ✔ | Desarrollos con BA = π/2·(Ri+K·t), DFM (láser, plegadora, perfiles, soldadura, montaje), corte de barras hasta la cota inferior, anidado de chapa |
| 6. Asistente IA | ✔ | Interpretación en español con evidencia, preguntas de datos faltantes, propuesta preliminar diferenciada de lo verificado |
| 7. Nuevas familias | ◐ parcial | **Estantería industrial** implementada (N niveles, montantes, bastidores y bandejas, anclaje). Puestos de trabajo, armarios y carros: sólo se identifican en el asistente |
| 8. Validación | ✔ | 33 pruebas: unidades frente a soluciones analíticas y tablas, mesa, estantería, QA, API y aceptación §23 |

### Verificaciones de la cadena (no simuladas)

- **Sólido ↔ desarrollo:** la diferencia de volumen se predice exactamente (desviación < 1e-9).
- **STEP:** se reimporta y se comprueban el número de sólidos y el volumen total frente al modelo.
- **DXF:** se releen, se auditan con ezdxf y se comprueban las cotas del desarrollo (1:1, mm, contornos cerrados, capas `CORTE_*`, `PLEGADO_*`, `GRABADO`, `INFO`).
- **Planos:** cada cota se mide sobre la geometría y se registra; el QA la contrasta con los parámetros.
- **Excel:** se relee y se comprueban cantidades, masa y fórmulas.
- **Expediente:** se genera en una carpeta temporal y sólo se publica si no hay errores bloqueantes. Una revisión anterior nunca se sobrescribe.

### Motor de cálculo validado

- **FEM:** viga biapoyada (M = qL²/8 exacto, flecha −0,2 %) y voladizo (exacto).
- **Placas (Navier):** coeficientes de Timoshenko/Roark α = 0,00406, β = 0,0479 y β(a/b = 2) = 0,6102.
- **Secciones:** coinciden con las tablas EN 10219-2 (< 1 %).

Cada comprobación indica norma, hipótesis, combinación, valor, límite, aprovechamiento y estado.
Sin datos de carga el resultado es **PENDIENTE**: nunca se asigna una capacidad sin cálculo.

## Caso de aceptación §23 (`tests/test_acceptance.py`)

1. El usuario escribe la solicitud de la mesa 2.000 × 800 × 900 mm con 400 kg.
2. El asistente identifica la familia y los datos, y pregunta por la carga de la balda, el material, el uso, los empujes horizontales y el entorno.
3. Con las respuestas, propone perfiles «auto». El dimensionado elige chapa de 2 mm con 6 travesaños, tras evaluar las alternativas de 2,5, 3 y 4 mm.
4. Se genera el modelo CAD: 0 interferencias, verificación preliminar CUMPLE, BOM, corte y anidado.
5. Se emite la revisión A y su expediente 01…06 (37 archivos), con todas las exportaciones reverificadas.
6. La longitud cambia a 2.400 mm. Se regenera con 7 travesaños (cambio topológico, no escalado), largueros +400 mm y la misma longitud de patas.
7. Se emite la revisión B con su expediente nuevo. La revisión A se conserva intacta.
8. El paso a «preparado para fabricación» se bloquea hasta la validación de un técnico competente con nombre.

## Estantería industrial

Montantes de tubo cuadrado en las esquinas y, en cada nivel, un bastidor soldado con bandeja de
chapa plegada con escotaduras alrededor de los montantes, atornillada con tuercas remachables.
Con la carga por nivel, el cálculo dimensiona montantes, largueros, travesaños, espesor de chapa y
número de travesaños. Sin anclaje se comprueba el vuelco. Con anclaje al suelo se calcula la
tracción por anclaje; la capacidad del taco y del soporte queda **pendiente** de verificar.

Ejemplo de la especificación (1.500 × 600 × 2.000 mm, 5 niveles, 150 kg/nivel):

- **Dimensionado:** SHS 40×40×2 y RHS 40×20×2, con bandejas de 2 mm y 3 travesaños por nivel.
- **Sin anclaje:** no supera el vuelco con el empuje de 300 N.
- **Con anclaje:** 486 N de tracción por anclaje.
- **Expediente:** 31 archivos sin errores bloqueantes.

## Versión artefacto (motor en el navegador)

La misma interfaz funciona sin servidor: el motor completo está portado a TypeScript en
`frontend/src/engine/` (parámetros y dependencias, familias mesa y estantería, chapa plegada y
desarrollos, FEM 3D de barras con solver skyline LDLᵀ y renumeración Cuthill-McKee, placas de
Navier, comprobaciones EN 1993, dimensionado automático, plan de corte, anidado, DFM, BOM, control
de calidad e intérprete del asistente). `frontend/src/local/` contiene la API local (misma interfaz
que la del servidor) y el generador del expediente.

```bash
cd frontend && VITE_LOCAL=1 npx vite build --mode artifact && node ../tools/build_artifact.mjs dist-artifact monxu.html
```

- **Persistencia:** base de datos privada del artefacto por usuario (`data/users/<id>/<proyecto>`), con
  revisiones inmutables e historial; en memoria si no hay base de datos.
- **Expediente:** ZIP con las carpetas 01–06: JSON paramétrico nativo, malla STL, desarrollos SVG
  acotados, DXF R12 1:1 en mm por pieza y por hoja de anidado, BOM/compras/pesos en CSV, plan de
  corte, informe de cálculo HTML y manifiesto SHA-256.
- **Asistente:** intérprete de reglas; dentro de Claude puede completarse con Claude (capacidad
  `sample`), y las reglas prevalecen.
- **Sólo en el servidor:** STEP B-rep, interferencias por volumen común, planos PDF con líneas
  ocultas y Excel con fórmulas. El JSON paramétrico del expediente los regenera.

### Validación cruzada navegador ↔ servidor

`tools/webcheck/compare.py` ejecuta los mismos casos en los dos motores. Compara parámetros
resueltos y su origen, derivados, piezas y masas, nodos del modelo FEM, estado y aprovechamiento
de cada comprobación, reacciones, plan de corte, anidado, soldadura, pintura, DFM y totales del BOM.

```bash
cd frontend && npx esbuild ../tools/webcheck/run.ts --bundle --platform=node --format=esm --outfile=/tmp/webrun.mjs
cd .. && python tools/webcheck/compare.py /tmp/webrun.mjs 60 11
```

Con las 12 plantillas, la aceptación 2000→2400, los dos diseños por defecto y 60 casos aleatorios
(76 casos) no hay ninguna diferencia. El aprovechamiento coincide exactamente en todas las
comprobaciones salvo el vuelco, donde el error relativo es ≤ 1,4·10⁻⁴ por el centro de gravedad
calculado sobre la malla. `tools/webcheck/verify_dossier.py` relee con ezdxf los DXF del expediente
del navegador: 0 errores, contornos cerrados, unidades mm y medidas iguales a los desarrollos del
servidor. También comprueba las sumas SHA-256 del manifiesto.

La comparación destapó dos fallos del motor de referencia, ya corregidos en ambos motores:

- **Referencias duplicadas en estanterías:** en estanterías de 5–6 niveles, largueros geométricamente
  idénticos recibían referencias distintas por ruido de coma flotante en las cotas de los taladros.
  Ahora las cotas se redondean a 0,001 mm en la clave de pieza.
- **Interacción de pandeo activada por ruido numérico:** en barras con axil nulo, un residuo de
  −10⁻¹¹ N activaba la interacción de pandeo. Ahora se aplica un umbral de 1 mN.

## Datos que quedan como hipótesis o pendientes

- **Empuje horizontal:** 300 N por defecto en el canto de la encimera. Con ese valor, una mesa vacía y ligera no supera el vuelco EQU, y el sistema lo informa así; el asistente pide el dato real.
- **Capacidad de los pies niveladores:** catálogo genérico, a confirmar con el proveedor.
- **DC01:** la norma no garantiza fy mínimo, así que se marca como hipótesis.
- **Gargantas a < 3 mm:** quedan fuera de EN 1993-1-8 §4.5.2 y requieren una WPS cualificada.

## Referencia MT-1800

El repositorio no contenía los archivos del proyecto de referencia MT-1800 (PDF, Excel, DXF).
La presentación se ha basado en la práctica normalizada: cuadro de rotulación ISO 7200, líneas
ISO 128-2, acotación ISO 129-1, primer diedro, símbolos ISO 2553 y tolerancias ISO 2768-mK /
EN ISO 13920. Cuando se aporten, conviene ajustar cajetín, distribución de vistas y codificación
de referencias a ese patrón.

Más detalle técnico en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).
