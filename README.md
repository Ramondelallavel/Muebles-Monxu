# Muebles Monxu — Plataforma de ingeniería y diseño paramétrico de mobiliario industrial

Convierte una necesidad expresada en lenguaje natural en un producto industrial definido
geométrica, mecánica y constructivamente: modelo B-rep real, cálculo, planos, desarrollos,
BOM, optimización de corte y expediente de fabricación, todo derivado de una única fuente de
parámetros.

> **Estado:** núcleo funcional con cuatro familias completas (**mesa industrial**, **estantería
> industrial**, **puesto de trabajo** y **carro de taller**) y el caso de aceptación §23 superado por
> pruebas automáticas. Los armarios (puertas, cajones) están previstos en la arquitectura pero
> **no implementados**.

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
| 7. Nuevas familias | ◐ parcial | **Estantería industrial** (N niveles, montantes, bastidores y bandejas, anclaje), **puesto de trabajo** (montantes, travesaño alto, estante en voladizo, panel perforado) y **carro de taller** (ruedas de espiga con freno, asa). Armarios: sólo se identifican en el asistente |
| 8. Validación | ✔ | 64 pruebas: unidades frente a soluciones analíticas y tablas, las cuatro familias, QA, API, aceptación §23, validación cruzada navegador ↔ servidor, expediente del navegador y legibilidad de planos |

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

## Puesto de trabajo y carro de taller

Ambas familias derivan de la mesa (encimera y balda de chapa plegada sobre bastidores soldados) y
comparten su cálculo, dimensionado, DFM y documentación.

- **Puesto de trabajo** (`PT`): las patas traseras se prolongan como montantes hasta la altura de la
  superestructura y se unen arriba con un travesaño soldado. La encimera lleva escotaduras sólo en
  las esquinas traseras. Opcionalmente:
  - un estante superior en voladizo (bandeja plegada sobre larguero trasero, brazos y larguero
    delantero soldados a los montantes), dimensionado con su carga como placa;
  - un panel perforado portaherramientas (agujero 10×10 a paso 38) atornillado a los montantes. Su
    peso entra en el cálculo como masa colgada de los montantes.
- **Carro de taller** (`CT`): ruedas giratorias de espiga roscada en las tuercas soldadas de las
  placas base, con freno en el lado del asa. La rueda se elige por cálculo (la de menor capacidad
  que soporta la reacción de servicio). Las dos patas del lado del asa se prolongan y se unen con el
  asa soldada. El empuje horizontal es la **fuerza de maniobra** con las ruedas frenadas (100 N por
  defecto): un carro no se ancla y se comprueba siempre frente al vuelco.

Plantillas: 4 de puesto de trabajo (montaje, inspección, embalaje, taller pesado) y 3 de carro
(dos niveles, transporte, inoxidable alimentario).

## Planos sin solapes

Cada hoja registra todo lo que se dibuja: textos con su caja real en Helvetica, líneas de las
vistas (vistas y ocultas), cotas, globos, símbolos de soldadura, tablas y cajetín. La colocación
usa ese registro:

- **Cotas:** el texto se prueba centrado, desplazado, fuera de las líneas de referencia y en filas
  escalonadas. Las líneas de cota apiladas se separan solas. Los tramos iguales demasiado cortos se
  acotan como «n×paso».
- **Globos:** se colocan en el hueco libre más cercano a la pieza, sin pisar textos, cotas ni otros
  globos. Después se intercambian los pares cuyas líneas de referencia se cruzan.
- **Símbolos de soldadura:** misma búsqueda, con flechas a puntos distintos de la unión.
- **Rótulos y notas:** los rótulos de vista van bajo la vista y sus cotas; las notas, en el primer
  hueco libre.
- **Desarrollos perforados:** se acotan como patrón, sin una tabla de cientos de agujeros.

La auditoría (`frontend/src/engine/layout.ts`) busca textos que se pisan, líneas que atraviesan un
texto, globos que pisan algo, líneas de referencia cruzadas y textos fuera del marco o dentro del
cajetín. Su resultado entra en el control de calidad del expediente como `PLANO-LEGIBILIDAD`.

- **Plantillas:** las 19 plantillas (las 4 familias) salen con 0 conflictos en planos y montaje,
  salvo un cruce de líneas de referencia en el explosionado de PT-2000-TALLER.
- **Configuraciones aleatorias:** en 60 configuraciones (1.032 hojas) quedan 6 conflictos: 5 cruces
  de referencias y 1 línea que toca un texto. Antes de estos cambios, 40 configuraciones (626 hojas)
  daban 117 conflictos, entre ellos textos superpuestos.
- **Servidor:** las mejoras de colocación están en los planos del navegador. Los planos PDF del
  servidor (`monxu/docs/plans.py`) mantienen su maquetación anterior.

## Versión artefacto (motor en el navegador)

La misma interfaz funciona sin servidor: el motor completo está portado a TypeScript en
`frontend/src/engine/` (parámetros y dependencias, las cuatro familias, chapa plegada y
desarrollos, FEM 3D de barras con solver skyline LDLᵀ y renumeración Cuthill-McKee, placas de
Navier, comprobaciones EN 1993, dimensionado automático, plan de corte, anidado, DFM, BOM, control
de calidad e intérprete del asistente). `frontend/src/local/` contiene la API local (misma interfaz
que la del servidor) y el generador del expediente.

```bash
cd frontend && VITE_LOCAL=1 npx vite build --mode artifact && node ../tools/build_artifact.mjs dist-artifact monxu.html
```

- **Persistencia:** base de datos privada del artefacto por usuario (`data/users/<id>/<proyecto>`), con
  revisiones inmutables e historial; en memoria si no hay base de datos.
- **Geometría:** cada pieza es un sólido facetado cerrado con sus taladros. Los tubos se modelan como paredes y
  esquinas EN 10219; las chapas, como base, pliegues y alas. El volumen se desvía < 0,2 % del analítico. De estos
  sólidos salen el visor, el STEP, las aristas de los planos y la detección de interferencias (cruce de triángulos
  con penetración > 0,25 mm, más la prueba de pieza contenida).
- **Expediente (un único ZIP, carpetas 01–06):**
  - 01: STEP AP214 del conjunto, con estructura de producto y una ocurrencia por instancia, y de cada pieza; STL y JSON paramétrico.
  - 02: planos PDF A3 con cajetín ISO 7200 y vistas en primer diedro, con líneas ocultas. Hojas: conjunto, estructura
    soldada, perfiles y plan de corte, piezas de chapa con sección del pliegue, desarrollos, pletinas, soldaduras
    ISO 2553 con detalles, explosionado, montaje y despiece.
  - 03: DXF R12 1:1 por pieza y por hoja de anidado.
  - 04: BOM en Excel con fórmulas (con su valor calculado) y CSV.
  - 05: plan de corte y anidado.
  - 06: instrucciones de montaje en PDF (una hoja por paso), informe de cálculo HTML e historial.
  - Manifiesto SHA-256. Antes de empaquetar se verifica cada archivo: sólidos del STEP, hojas del PDF, cotas del plano
    frente a la geometría, Excel frente al BOM y medidas de los DXF.
- **Asistente:** intérprete de reglas; dentro de Claude puede completarse con Claude (capacidad
  `sample`), y las reglas prevalecen.
- **Diferencias con el servidor:** el STEP del navegador es facetado (caras planas), no B-rep con superficies
  exactas. Las interferencias se detectan sobre esos sólidos facetados, no por volumen común B-rep.

### Validación cruzada navegador ↔ servidor

`tools/webcheck/compare.py` ejecuta los mismos casos en los dos motores. Compara parámetros
resueltos y su origen, derivados, piezas y masas, nodos del modelo FEM, estado y aprovechamiento
de cada comprobación, reacciones, plan de corte, anidado, soldadura, pintura, DFM y totales del BOM.

```bash
cd frontend && npx esbuild ../tools/webcheck/run.ts --bundle --platform=node --format=esm --outfile=/tmp/webrun.mjs
cd .. && python tools/webcheck/compare.py /tmp/webrun.mjs 60 11
```

Con las 19 plantillas de las cuatro familias, la aceptación 2000→2400, los dos diseños por defecto y
14 casos aleatorios de todas las familias (37 casos) no hay ninguna diferencia. El aprovechamiento
coincide exactamente en todas las comprobaciones salvo el vuelco, donde el error relativo es
≤ 2,4·10⁻⁴ por el centro de gravedad calculado sobre los sólidos facetados.

`tools/webcheck/verify_dossier.py` relee el ZIP generado por el navegador con las herramientas del servidor:

- **STEP:** reimportación con OpenCascade. Mesa de 2000 mm: 99/99 sólidos válidos y volumen a −0,07 % del B-rep;
  estantería de 2888 mm: 311/311. Puesto de trabajo de 1500 mm: 137 ocurrencias, 139/139 sólidos válidos
  (−0,08 %). Carro de 1200 mm: 81 ocurrencias, 95/95 sólidos válidos (−0,22 %). Cada rueda se compone de varios
  cuerpos: horquilla, espiga, cabezal, rueda y pedal.
- **PDF:** pdfplumber (hojas A3 con cajetín).
- **Excel:** openpyxl (fórmulas, unidades y masa frente al BOM del servidor).
- **DXF:** ezdxf (0 errores, contornos cerrados y medidas iguales a los desarrollos del servidor).
- **Manifiesto:** comprobación de las sumas SHA-256.

`tools/webcheck/fuzz.ts` recorre parámetros aleatorios, incluidos los avanzados. En 800 casos (20 expedientes
completos): 0 excepciones, 0 valores no finitos y 0 sólidos abiertos. Otros 400 casos de las cuatro familias dieron
0 excepciones. Los 2 sólidos abiertos que aparecieron (escotadura de bandeja mayor que la mitad de su fondo) ya están
corregidos. Las 168 configuraciones con interferencias acompañan, todas, a un error de diseño ya señalado por las
reglas (por ejemplo, tuerca soldada mayor que el interior de la pata). `tools/webcheck/layout_fuzz.ts` hace lo
mismo con la auditoría de legibilidad de los planos.

La comparación destapó dos fallos del motor de referencia, ya corregidos en ambos motores:

- **Referencias duplicadas en estanterías:** en estanterías de 5–6 niveles, largueros geométricamente
  idénticos recibían referencias distintas por ruido de coma flotante en las cotas de los taladros.
  Ahora las cotas se redondean a 0,001 mm en la clave de pieza.
- **Interacción de pandeo activada por ruido numérico:** en barras con axil nulo, un residuo de
  −10⁻¹¹ N activaba la interacción de pandeo. Ahora se aplica un umbral de 1 mN.
- **Extremo de barra perdido en el modelo FEM:** los puntos de cada barra se redondean a 0,001 mm
  y, si el redondeo de la longitud la superaba, se descartaba el extremo final y la barra quedaba
  suelta (matriz singular). Aparecía con los brazos del estante del puesto de trabajo; ahora la
  tolerancia es coherente con el redondeo.

## Datos que quedan como hipótesis o pendientes

- **Empuje horizontal:** 300 N por defecto en el canto de la encimera. Con ese valor, una mesa vacía y ligera no supera el vuelco EQU, y el sistema lo informa así; el asistente pide el dato real.
- **Capacidad de los pies niveladores y de las ruedas:** catálogo genérico, a confirmar con el proveedor. Las ruedas
  se modelan con su envolvente simplificada (sin descentrado de giro).
- **Fuerza de maniobra del carro:** 100 N por defecto, aplicada en el plano de la encimera con las ruedas frenadas.
- **DC01:** la norma no garantiza fy mínimo, así que se marca como hipótesis.
- **Gargantas a < 3 mm:** quedan fuera de EN 1993-1-8 §4.5.2 y requieren una WPS cualificada.

## Referencia MT-1800

El repositorio no contenía los archivos del proyecto de referencia MT-1800 (PDF, Excel, DXF).
La presentación se ha basado en la práctica normalizada: cuadro de rotulación ISO 7200, líneas
ISO 128-2, acotación ISO 129-1, primer diedro, símbolos ISO 2553 y tolerancias ISO 2768-mK /
EN ISO 13920. Cuando se aporten, conviene ajustar cajetín, distribución de vistas y codificación
de referencias a ese patrón.

Más detalle técnico en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).
