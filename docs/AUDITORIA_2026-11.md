# Auditoría integral del generador de mobiliario industrial (noviembre de 2026)

Proyecto de referencia: **P-2026-0039**, estantería en batería `EB3x1000-600-2000` (parámetros en
`tests/data/ref_P-2026-0039.json`). La auditoría se ha hecho sobre el código de los dos motores (servidor
Python con CadQuery y navegador TypeScript), que deben dar el mismo resultado.

Criterio seguido: no se ha cambiado ninguna dimensión, material, carga, perfil ni geometría para que un
control salga bien. Lo que el programa no puede certificar queda **PENDIENTE DE VALIDACIÓN** y bloquea la
liberación hasta que un técnico lo cierra con el documento que lo justifica.

## 1. Errores detectados, causa raíz y corrección

### Los 15 puntos del proyecto de referencia

| Nº | Error | Causa raíz | Corrección | Control que lo vigila |
|----|-------|-----------|------------|-----------------------|
| 1 | Las instrucciones citaban M6x12 y el BOM M6x10 | Textos de montaje escritos a mano en cada familia | Instrucciones generadas desde las uniones y componentes del modelo (`monxu/docs/assembly.py`), con las referencias `N-<código>` del BOM | `XDOC-TORNILLERIA-INSTR` |
| 2 | Tuerca remachable M6 con una norma que no le corresponde | Campo «norma» obligatorio en el catálogo, rellenado por analogía | Norma solo si existe; ficha de componente con fabricante, modelo, material, clase, par y estado de validación | `COMP-<código>`, `BOM-COMERCIALES` |
| 3 | Placa de 5 mm: 0,031 m² / 1,23 kg en compras y 0,942 kg en el presupuesto | Tres fórmulas distintas para la misma chapa (compras, presupuesto, anidado) | Chapa cortada a medida 250×130 mm (0,0325 m², 1,28 kg) y la misma cifra en anidado, DXF, compras y presupuesto | `XDOC-COMPRAS-OPT`, `XDOC-PRESUPUESTO-COMPRAS` |
| 4 | Cinco chapas de 2 mm compradas (245,3 kg) y 197,0 kg presupuestados | Presupuesto por peso neto con un aprovechamiento genérico del 80 % | Presupuesto por material comprado según el anidado real | `XDOC-PRESUPUESTO-COMPRAS` |
| 5 | Perfiles: 66 m comprados y 60,33 m + 8 % presupuestados | Merma genérica en lugar del plan de corte | Barras del plan de corte: 11 + 3 barras, 163,5 kg | `XDOC-PRESUPUESTO-COMPRAS`, `XDOC-BOM-CORTE` |
| 6 | Peso propio del cálculo 309,4 kg y BOM 307,46 kg | El cálculo pesaba las barras por su longitud de eje y kg/m nominal | Peso propio con la masa de cada pieza; las piezas no modeladas como barra se aplican en el nudo más próximo | `XDOC-PESO-CALC` (307,448 frente a 307,464 kg) |
| 7 | Plan de corte sin despuntes ni balance | El optimizador solo devolvía piezas y aprovechamiento | Cada barra cumple `L = despunte inicial + Σ piezas + sierra + despunte final + retal`; retal reutilizable o chatarra | `XDOC-BALANCE` |
| 8 | Aprovechamientos de chapa sobre el formato nominal | Se dividía por el formato aunque no se comprara entero | Aprovechamiento sobre lo comprado (64,2 % y 59,0 %) | `XDOC-COMPRAS-OPT` |
| 9 | Pies niveladores «cumplen» con una capacidad de catálogo genérico | La capacidad genérica se trataba como certificada | La comprobación queda PENDIENTE DE VALIDACIÓN (aprovechamiento 0,919) | `CALC-VAL-A.PIES`, `COMP-PIE_NIV_M10_D50` |
| 10 | Cabezas de tornillo 3,3 mm fuera del contorno, sin documentar | El control de envolvente no daba valores | Advertencia con valor esperado y obtenido | `GEO-SALIENTE` |
| 11 | Tres avisos de soldadura genéricos | Textos fijos, iguales para cualquier producto | Calculados desde la geometría: 60 uniones enrasadas y 60 dentro del radio de esquina (0,5 mm); gargantas menores de 3 mm exigen WPS | `SOL-ENRASE`, `SOL-RADIO-ESQUINA`, `SOL-WPS` |
| 12 | Cálculo sin imperfecciones ni segundo orden | Hipótesis simplificadas no declaradas | Imperfecciones globales equivalentes y α_cr (método de Horne) con amplificación; limitaciones declaradas | `S.IMPERF`, `S.ALFA-CR-X/Y` |
| 13 | Normas de inoxidable y aluminio en un producto de acero al carbono | Lista de normas por familia, sin filtrar | Normas por material, proceso y norma de producto | prueba 13 de `tests/test_auditoria.py` |
| 14 | Sello «CÁLCULO VERIFICADO — CUMPLE» con «Comprobado» y «Aprobado» vacíos | El sello salía del resultado del cálculo | Nueve estados de aprobación encadenados; el sello sale del estado y de las firmas registradas | `monxu/validation/approval.py` |
| 15 | Exportaciones sin comprobar frente al modelo | Solo se comprobaba que el archivo existiera | STEP releído, STL releído, DXF de pieza y de anidado medidos; el STEP facetado del navegador se declara como tal | `EXP-STEP`, `EXP-STEP-TIPO`, `EXP-STL`, `EXP-DXF`, `EXP-DXF-ANIDADO` |

### Errores adicionales encontrados durante la auditoría

| Error | Causa raíz | Corrección |
|-------|-----------|------------|
| Armario: peso propio del cálculo 127,6 kg frente a 93,1 kg del BOM | Piezas colgadas contadas dos veces al reconstruir la estructura | Corregido en los dos motores; lo detectó `XDOC-PESO-CALC` |
| Estantería cantilever: α_cr < 3 incluso con el mayor perfil | El modelo de apoyos isostático lleva toda la acción horizontal a un pie; no representa una estructura anclada | Con anclaje se calcula además con los apoyos coaccionados; el resultado queda PENDIENTE DE VALIDACIÓN (véase el apartado 6) |
| La corrección automática anunciaba «cumple todas las verificaciones» | El texto no distinguía «sin NO CUMPLE» de «verificado» | La propuesta lleva el veredicto y las validaciones que quedan |
| Hoja de despiece: peso unitario «0» en tornillos, «1» por 0,96 kg, «158» por 157,95 kg | Se usaba el formato de cotas, que redondea a entero | Cifras del BOM (hasta 4 decimales) y control del peso impreso |
| Hoja de perfiles (servidor): la posición de taladro «890» salía «89» | Texto cortado a 110 caracteres | Mecanizados completos en varias líneas, separados por «;» |
| Hoja de perfiles: a partir del undécimo perfil no se dibujaba ninguno; las barras que no cabían, tampoco | Bucle que terminaba al llenarse la hoja | Hojas de continuación y barras iguales agrupadas |
| Referencias cortadas («N-TORNILLO_ISO7380…») en despiece, explosionado y montaje | Columnas de ancho fijo | Columnas al ancho del contenido y texto partido en líneas |
| Servidor: panel perforado con 24 de sus 550 agujeros en la tabla | El servidor no acotaba la retícula como patrón | Retícula acotada como patrón (como en el navegador) |
| Servidor: notas del conjunto general sobre el cajetín en una cantilever | Posición fija de las notas | Se colocan en el primer hueco libre |
| CSV del servidor con punto decimal y del navegador con coma | Dos escritores distintos | Coma decimal y las mismas celdas en ambos |
| Hipótesis «2.0·L» en el servidor y «2·L» en el navegador | Formato numérico distinto | Mismo texto; la validación cruzada compara ya las hipótesis |
| Avisos con «encimera» en una estantería | Textos por defecto de mesa | Textos según el producto y control `XDOC-TEXTOS-PRODUCTO` |

## 2. Controles nuevos

Motor central de calidad (`monxu/validation/qa.py`, `frontend/src/engine/pipeline.ts`). Cada control lleva
código, severidad (CRÍTICO, BLOQUEANTE, ADVERTENCIA, INFORMATIVO), documento, valor esperado, valor obtenido,
diferencia, criterio y acción.

- **Entre documentos:** `XDOC-BOM-3D`, `XDOC-BOM-CORTE`, `XDOC-BOM-COMPRAS`, `XDOC-COMPRAS-OPT`, `XDOC-BALANCE`,
  `XDOC-PESO-CALC`, `XDOC-PESO-COMPRA`, `XDOC-PRESUPUESTO-COMPRAS`, `XDOC-TORNILLERIA-INSTR`,
  `XDOC-TEXTOS-PRODUCTO`, `XDOC-SOLDADURA-CALC`.
- **Componentes y soldadura:** `BOM-COMERCIALES`, `COMP-<código>`, `SOL-WPS`, `SOL-ENRASE`, `SOL-RADIO-ESQUINA`,
  `MON-ROSCA`, `MON-ROSCA-UTIL`, `MON-PROFUNDIDAD`.
- **Cálculo:** `CALC-VAL-<comprobación>` por cada resultado pendiente de validación.
- **Exportaciones:** `EXP-STEP-TIPO`, `EXP-STL`, `EXP-DXF-ANIDADO`.
- **Planos:** `PLANO-GEOMETRIA` ampliado (cantidades y pesos impresos, taladros de cada perfil, barras y
  piezas del plan de corte, textos cortados, hojas anunciadas) y `PLANO-MONTAJE`.

## 3. Estados de aprobación

Diseño generado → geometría validada → BOM validado → fabricabilidad revisada → cálculo estructural validado →
documentación generada → revisión técnica pendiente → aprobado técnicamente → liberado para fabricación.

Cada validación pendiente se cierra con la referencia del documento que la justifica; cada etapa, con su
firma. Liberar exige un expediente generado después de aprobar. Las revisiones anteriores a la auditoría no
pueden aprobarse sin emitir una nueva (migración de datos a la versión 2 del esquema).

## 4. Proyecto de referencia regenerado

| Concepto | Antes | Después |
|----------|-------|---------|
| Perfil RHS 40x20x2 presupuestado | 109,25 kg (60,33 m + 8 %) | 110,70 kg (11 barras de 6 m) |
| Perfil SHS 50x50x2 presupuestado | 49,88 kg | 52,80 kg (3 barras de 6 m) |
| Chapa de 2 mm presupuestada | 196,98 kg (neto / 0,8) | 245,31 kg (5 chapas 2500×1250) |
| Chapa de 5 mm presupuestada | 0,942 kg | 1,28 kg (250×130 mm a medida) |
| Material comprado | sin dato único | 410,089 kg = 305,184 neto + 95,582 desperdicio + 9,323 retales |
| Cortes de sierra | 98 | 112 (refrentado de cada barra y uno por pieza) |
| Coste directo / precio | 1 152,08 € / 1 589,86 € | 1 284,73 € / 1 772,92 € |
| Peso propio del cálculo / BOM | 309,4 / 307,46 kg | 307,448 / 307,464 kg |
| α_cr | no calculado | 85,4 (X) y 76,8 (Y) |
| Pies niveladores | CUMPLE 0,921 | PENDIENTE DE VALIDACIÓN 0,919 |
| Normas citadas | incluía EN 1993-1-4 y EN 1999-1-1 | solo las del acero al carbono y los procesos presentes |
| Sello de los documentos | CÁLCULO VERIFICADO — CUMPLE | GEOMETRÍA VALIDADA — SIN APROBACIÓN TÉCNICA · NO APTO PARA FABRICACIÓN |
| Bloqueos de liberación | 0 | 7 |

Los siete bloqueos son validaciones que corresponden a un técnico: capacidad de los pies (`CALC-VAL-A.PIES`,
`COMP-PIE_NIV_M10_D50`), tacos de anclaje (`CALC-VAL-E.ANCLAJE`, `COMP-ANCLAJE_M8`), anejo nacional
(`CALC-VAL-N.ANEJO-NACIONAL`), tuerca remachable (`COMP-TUERCA_REMACHABLE_M6`) y WPS (`SOL-WPS`).

Expediente del servidor: 39 archivos (STEP, STL, BREP y GLB del conjunto, STEP de 11 piezas, planos de 10
hojas, 8 DXF, Excel, 5 CSV, informes). Expediente del navegador: 45 archivos. Los CSV de compras,
presupuesto, plan de corte y balance son idénticos byte a byte en los dos.

## 5. Diferencias conocidas entre los dos motores

- **Masa de las piezas.** El servidor mide el sólido B-rep; el navegador usa la definición analítica. Difieren
  menos del 0,02 % (307,464 frente a 307,448 kg en el proyecto de referencia).
- **STEP.** El del servidor es B-rep exacto; el del navegador es facetado y así lo declara (`EXP-STEP-TIPO`).
- **Instrucciones de montaje.** El servidor genera una hoja; el navegador, una hoja por paso con su tabla de
  piezas. El texto de los pasos es el mismo.
- **Planos.** Mismos textos, cotas, cantidades y referencias; puede cambiar la escala elegida para una vista,
  y el PDF del navegador escribe «pi» y «<=» donde el del servidor escribe «π» y «≤».

## 6. Cuestiones de ingeniería pendientes

Requieren la decisión de un técnico. La aplicación las informa y no las da por buenas.

1. **Anejo nacional.** Se usan los valores recomendados de EN 1990 y EN 1993; falta fijar el del país de
   instalación.
2. **Capacidades certificadas** de pies niveladores, ruedas y tacos de anclaje: el catálogo es genérico y
   faltan fabricante, modelo y ficha.
3. **WPS cualificada** para los cordones con garganta menor de 3 mm.
4. **Estabilidad longitudinal de las cantilever ancladas.** Con el apoyo isostático α_cr,X vale entre 1,1 y
   2,3 en tres plantillas; con los apoyos anclados coaccionados, entre 9 y 40. Falta validar el cortante de
   los tacos y de los vástagos de los pies, o hacer un análisis de segundo orden. Sin anclar, la comprobación
   es NO CUMPLE y la corrección propuesta es anclar.
5. **Par de apriete en tuerca remachable** (8 N·m orientativo, limitado por la tuerca): confirmar con la ficha.
6. **Parámetros de taller:** despunte final de barra (0 mm por defecto), retal reutilizable mínimo (500 mm en
   barra, 300 mm en chapa) y umbral de corte a medida de chapa (10 %).
7. **Imputación del material en el presupuesto:** por compra (por defecto) o por consumo, descontando los
   retales reutilizables.

## 7. Resultados de las pruebas

Ejecución final sobre el código entregado (noviembre de 2026):

| Prueba | Resultado |
|--------|-----------|
| Batería completa de `pytest` (unitarias, aceptación, catálogo, familias, planos, motor del navegador, invariantes, auditoría) | **286 superadas, 0 fallos** |
| `tests/test_auditoria.py` (regresión de los 15 puntos, propagación de parámetros, pruebas negativas, planos, CSV, aprobación, migración) | 52 pruebas, todas superadas |
| Validación cruzada navegador ↔ servidor (`tools/webcheck/compare.py`): 71 plantillas, aleatorios y casos avanzados; parámetros, piezas, masas, comprobaciones, reacciones, corte, anidado, compras, presupuesto, soldadura, veredicto, hipótesis y corrección automática | 141 casos, **0 diferencias** |
| Planos de las 71 plantillas, motor del navegador: coherencia con el modelo, textos cortados, hojas anunciadas, solapes | 0 incidencias |
| Planos de las 71 plantillas, motor Python: coherencia con el modelo y hojas anunciadas | 0 incidencias. El barrido de solapes marca solo el símbolo «≤» del texto de las cantilever, un artefacto de la extracción de texto del PDF (la fuente Symbol no da anchura al carácter) |
| Interfaz (Playwright): flujo completo de aprobación con validaciones, firmas, nueva edición del expediente, liberación e inventario de retales; flujo general; familias nuevas; recorrido de las 71 plantillas | 36 + 14 + 13 comprobaciones superadas; 71 plantillas sin errores de consola |
| Expediente del navegador releído con herramientas del servidor (OpenCascade, pdfplumber, openpyxl, ezdxf) | 0 errores |

## 8. Archivos modificados

- **Catálogos:** `monxu/catalog/data/` (`components.json`, `profiles.json`, `sheets.json`, `costs.json`,
  `standards.json`, `criteria.json`).
- **Fabricación:** `monxu/manufacturing/` (`optimization.py`, `plan.py`, `costing.py`).
- **Documentos:** `monxu/docs/` (`assembly.py` y `dependencies.py` nuevos; `bom.py`, `plans.py`,
  `drawing_kit.py`, `dxf.py`, `excel.py`, `report.py`), `monxu/cad/export.py`, `monxu/pipeline.py`.
- **Cálculo:** `monxu/engineering/` (`analysis.py`, `autofix.py`), `monxu/core/model.py`.
- **Validación y aprobación:** `monxu/validation/` (`qa.py`; `approval.py` nuevo), `monxu/storage/db.py`,
  `monxu/api/main.py`.
- **Familias:** textos de montaje y piezas colgadas en `monxu/families/`.
- **Navegador:** `frontend/src/engine/` (los mismos módulos; `approval.ts` y `dependencies.ts` nuevos),
  `frontend/src/local/` (`localApi.ts`, `dossier.ts`), `frontend/src/App.tsx`, `panels.tsx`, `api.ts`,
  `styles.css`.
- **Pruebas y herramientas:** `tests/test_auditoria.py` y `tests/data/ref_P-2026-0039.json` nuevos; ajustes
  en otras seis pruebas; `tools/invariants.py`, `tools/webcheck/` (`compare.py`, `ref.py`, `run.ts`,
  `dossier.ts`, `drawings.ts`, `layout.ts`, `verify_dossier.py`).
