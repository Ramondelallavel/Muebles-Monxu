# Muebles Monxu — Plataforma de ingeniería y diseño paramétrico de mobiliario industrial

Convierte una necesidad expresada en lenguaje natural en un producto industrial definido
geométrica, mecánica y constructivamente: modelo B-rep real, cálculo, planos, desarrollos,
BOM, optimización de corte y expediente de fabricación, todo derivado de una única fuente de
parámetros.

> **Estado:** núcleo funcional con diez familias completas (**mesa industrial**, **mesa de soldadura**,
> **estantería industrial**, **estantería en batería**, **puesto de trabajo**, **carro de taller**, **carro estantería**,
> **carro plataforma**, **tarima / plataforma de trabajo** y **armario industrial**) y el caso de aceptación §23 superado
> por pruebas automáticas. Los cajones y las cajoneras **no están implementados**.

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
| 7. Nuevas familias | ◐ parcial | **Estantería industrial** (N niveles, montantes, bastidores y bandejas, anclaje), **puesto de trabajo** (montantes, travesaño alto, estante en voladizo, panel perforado) **carro de taller** (ruedas de espiga con freno; asa en uno, dos o ningún extremo) **carro estantería** (N niveles sobre ruedas, asa opcional), **mesa de soldadura** (placa perforada de 10–20 mm), **estantería en batería** (N módulos con montantes compartidos), **tarima** (plataforma baja con cargas de EN ISO 14122-2), **carro plataforma** (plataforma baja sobre ruedas con asa de empuje) y **armario industrial** (estructura tubular con laterales, fondo y puertas de chapa). Peto trasero opcional en mesa, puesto y carro. Cajoneras: sólo se identifican en el asistente |
| 8. Validación | ✔ | 125 pruebas: unidades frente a soluciones analíticas y tablas, las ocho familias, QA, API, aceptación §23, validación cruzada navegador ↔ servidor, expediente del navegador y legibilidad de planos |

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
  placas base, con freno en el extremo izquierdo. La rueda se elige por cálculo (la de menor capacidad
  que soporta la reacción de servicio). `ASA_EMPUJE` elige el asa:
  - `un_extremo` (por defecto): las dos patas del extremo izquierdo se prolongan y se unen con el asa soldada;
  - `dos_extremos`: asa en ambos extremos (carro de pasillo), con escotaduras en las cuatro esquinas;
  - `ninguna`: **mesa móvil**, con todas las patas a la altura de la encimera y sin escotaduras.

  El empuje horizontal es la **fuerza de maniobra** con las ruedas frenadas (100 N por defecto):
  un carro no se ancla y se comprueba siempre frente al vuelco.

### Peto trasero (mesa, puesto y carro)

`PETO_TRASERO` (mm sobre la encimera, 0 = sin peto) pliega hacia arriba el borde trasero de la
encimera como tope de piezas y herramientas. Ese borde queda sin fijaciones, así que el larguero
trasero del bastidor superior pasa a ser una pieza propia sin taladros. La pestaña del peto se
comprueba como cualquier otra en el DFM de plegado (ala mínima según la matriz). Los planos acotan
la altura de trabajo y la del peto por separado. El plano de la chapa también separa la pestaña y
el peto, e indica qué bordes se pliegan hacia arriba.

### Reposapiés (mesa, puesto y carro)

`REPOSAPIES` añade una barra soldada entre las patas delanteras, a `ALTURA_REPOSAPIES`, para
trabajar sentado o en taburete. Su perfil (`PERFIL_REPOSAPIES`) se dimensiona por cálculo, porque el
apoyo del pie entra en el modelo como una hipótesis de carga propia: 1 kN vertical en el centro
(combinaciones ELU-F y ELS-F). Así quedan verificadas la barra, sus soldaduras, las patas y la
flecha. Si coincide con la balda inferior o no deja 100 mm para el pie bajo ella, se informa
`GEO-REPOSAPIES-BALDA`.

El asistente reconoce «con peto (de N mm)», «sin peto», «tope trasero», «dos asas», «sin asa»,
«reposapiés (a N mm)» y «apoyapiés». Convierte «mesa con ruedas» o «mesa móvil» en un carro sin asa.

Plantillas: 4 de puesto de trabajo (montaje, inspección con reposapiés, embalaje con peto, taller pesado), 5 de
carro (dos niveles, transporte, dos asas, mesa móvil con peto, inoxidable alimentario) y la mesa de
laboratorio inoxidable con peto de 100 mm.

## Carro estantería

`carro_estanteria` (`CE`) es la estantería industrial montada sobre ruedas: carro de picking, de
bandejas o de transporte interno, con 2 a 6 niveles. Tiene montantes, bastidores por nivel y bandejas
de chapa plegada, como la estantería. Las cuatro ruedas giratorias de espiga roscada van en las
tuercas soldadas de las placas base, con freno en el extremo izquierdo, y se eligen por cálculo.

- **Asa de empuje** (`ASA_EMPUJE`: un extremo, dos o ninguna): tubo soldado entre los montantes de un
  extremo, a `ALTURA_ASA`. Debe dejar 40 mm de holgura para la mano respecto a las bandejas y
  bastidores de cada nivel; si no, se informa `GEO-ASA-NIVEL` y aparecen las interferencias reales.
- **Vuelco:** un carro no se ancla. La fuerza de maniobra se aplica a la altura de empuje (la del
  asa o, sin asa, `ALTURA_ASA` como altura de la mano), nunca por encima de la altura total. El
  desplome y las barras se siguen comprobando con la fuerza en el nivel superior.
- El asistente reconoce «carro estantería», «carro de picking / de bandejas / de baldas», «carro de
  N niveles» y «estantería con ruedas / móvil».

Plantillas: tres niveles de 1.000 mm, picking de cuatro niveles de 1.200 mm con asa en los dos
extremos, y bandejas inoxidable de cinco niveles de 800 mm.

## Mesa de soldadura

`mesa_soldadura` (`MS`) monta sobre la estructura de la mesa industrial una **placa de acero de 10 a
20 mm sin pintar**, perforada para el sistema de amarre:

- `SISTEMA_TALADROS`: Ø16 a paso 50 mm, Ø28 a paso 100 mm o placa lisa, en retícula centrada.
- `VUELO`: la estructura se retranquea respecto a los cantos de la placa para dejar sitio a mordazas
  y sargentos.
- Soldadura: la placa se suelda al bastidor superior con cordones discontinuos de 50 mm cada 250 mm.
  No lleva fijaciones atornilladas.

**Cálculo de la placa:** Navier sobre cada panel entre travesaños, para la carga uniforme y para la
carga puntual de pieza pesada. La rigidez y la resistencia se reducen por la eficiencia de ligamento
(p − d)/p: 0,68 en el sistema 16 y 0,72 en el 28.

**Espesor:** el dimensionado elige el menor espesor que verifica, con dos límites:
- un mínimo constructivo por planitud y deformación al soldar sobre la placa: 12 mm en el sistema 16
  y 15 mm en el 28;
- el máximo que permite el corte láser de los taladros (diámetro ≥ espesor).

La separación de travesaños y los perfiles salen también del cálculo.

**Planos y fabricación:** la placa tiene un plano propio. La retícula se acota como patrón
(«19×100 = 1900» y primer taladro a los cantos) en lugar de rotular cientos de taladros. En el
servidor, el sólido se construye como una cara con los taladros de contorno interior: 600 taladros en
0,2 s, con volumen exacto. Presupuesto con láser hasta 20 mm.

El asistente reconoce «mesa de soldadura / para soldar / de calderería», «sistema 16 / 28»,
«taladros de 16», «placa lisa», «placa de N mm» y «vuelo de N mm».

Plantillas: 1.200 × 800 sistema 16, 2.000 × 1.000 sistema 28 con 1.000 kg y 1.500 × 1.000 de
calderería con balda inferior.

## Estantería en batería

`estanteria_bateria` (`EB`) une de 2 a 8 módulos de estantería contiguos que **comparten los montantes
intermedios**: con N módulos hay 2·(N + 1) montantes en lugar de 4·N. `ANCHURA` es la de cada módulo
entre ejes de montantes, y la anchura total es `ANCHURA_TOTAL` = N · módulo + un montante.

- **Bastidores por módulo y nivel:** los largueros van entre caras de montante. En el montante común,
  cada módulo suelda su travesaño lateral a un lado del eje, dentro de la sección del tubo. Regla
  constructiva: junta/2 + retranqueo + ancho del travesaño ≤ medio montante. El dimensionado sube
  `PERFIL_MONTANTE` hasta cumplirla. Si el montante es fijo y no cabe, el error `DFM-BATERIA-MONTANTE`
  es bloqueante.
- **Bandejas iguales en todos los módulos** (una sola referencia), de eje a eje con 1 mm de junta.
  Llevan escotaduras de medio montante en X y de montante completo en Y. Las pestañas laterales de dos
  bandejas contiguas quedan enfrentadas a 1 mm, sin sitio para la cabeza de un tornillo. Por eso cada
  bandeja se atornilla solo por las pestañas delantera y trasera, y las laterales solo posicionan. El
  primer diseño atornillaba las cuatro pestañas y la detección de interferencias lo rechazó.
- **Cálculo:** cada bandeja es una superficie con su carga (`CARGA_POR_NIVEL` es la de cada bandeja). El
  FEM es el de la batería completa, con todos los montantes y pies, así que el montante común recibe
  las reacciones de los dos módulos.
- **Planos:** las cotas de niveles y travesaños se dan en el primer módulo, porque los demás son
  iguales. Una estructura soldada de más de 3 m genera la advertencia `ERG-TRANSPORTE`.
- **Asistente:** reconoce «estantería en batería», «batería de estanterías», «estantería de N módulos /
  cuerpos / vanos» y «estantería modular». Entiende tanto «módulos de 1.000 mm» como un frente total
  («4 m de largo», «3.600 de frente total»), que reparte entre los módulos o del que deduce cuántos hay.

Plantillas: 3 × 1.000 mm con cinco niveles, pesada de 4 × 1.200 mm y archivo de 2 × 900 mm con seis
niveles.

## Tarima / plataforma de trabajo

`tarima` (`TA`) es una plataforma baja para elevar al operario frente a una máquina o una línea, o
para pasar sobre conducciones. Es una chapa de acero de 3 a 10 mm soldada con cordones
discontinuos sobre un bastidor de tubo, con patas cortas, placas base y pies niveladores.

- **Cargas de EN ISO 14122-2:** carga repartida no menor que 2 kN/m² y 1,5 kN (153 kg)
  concentrada sobre 200 × 200 mm. La huella de la carga concentrada es propia de la superficie (en
  las mesas sigue siendo de 100 × 100 mm). La flecha admisible es L/200. Si la carga indicada es
  menor que la de la norma, se advierte con el valor mínimo en kg.
- **Límites:** altura de la superficie hasta 500 mm, porque por encima EN ISO 14122-3 exige
  barandilla (no incluida). El fondo llega a 1800 mm, para que la chapa entera quepa en el formato
  de 4000 × 2000 con los márgenes de corte. La estructura es de acero al carbono porque la chapa va
  soldada. Si los pies y el bastidor no caben en la altura pedida, el error da la altura mínima.
- **Lo que no se modela:** la superficie antideslizante (chapa lagrimada o recubrimiento). Queda
  como advertencia en todos los diseños. Por encima de 250 mm se sugiere valorar un peldaño de
  acceso, que tampoco se incluye.
- **Asistente:** reconoce «tarima», «plataforma de trabajo / baja / para el operario» y «podio».
  Convierte cargas en kN/m² o kg/m² a carga total y propone la carga mínima de la norma.

Plantillas: tarima de operario de 1.200 × 800 × 200 mm, plataforma frente a máquina de 2.000 × 1.000
× 300 mm y podio de taller de 3.000 × 1.200 × 450 mm.

## Carro plataforma

`carro_plataforma` (`CP`) es una plataforma baja de chapa plegada sobre un bastidor soldado y cuatro
ruedas giratorias de espiga roscada, para el transporte interno de cargas de hasta 1.000 kg. Es el
carro de taller sin balda ni reposapiés, con la superficie a 200–500 mm. El asa de empuje puede ir en
un extremo, en los dos o no existir (plataforma rodante). Las ruedas con freno van en el lado del asa.

- **Altura de la plataforma:** la cara superior debe dejar sitio al bastidor sobre las placas base de
  las ruedas, que se eligen por cálculo. Con la altura por defecto (300 mm), si la rueda que exige la
  carga no cabe, la plataforma se eleva (regla de diseño `REGLA-ALTURA`). Por ejemplo, 1.000 kg en
  1.200 × 800 piden ruedas Ø200 M20 y la plataforma sube a 335 mm. Un valor del usuario no se cambia:
  se informa `GEO-PLATAFORMA-BAJA` con la altura mínima.
- **Fuerza de maniobra en el asa:** se aplica donde se empuja, en el asa (la del extremo izquierdo si
  hay dos), tanto en el modelo de barras como en el vuelco del carro vacío. El desplome se limita a la
  altura del asa. Sin asa se aplica en el plano de la plataforma. Por defecto son 50 N. Un carro vacío es
  ligero: el de 1.000 × 600 mm (31 kg) admite 52 N de cálculo en el asa a 950 mm antes de volcar de
  lado, y el resultado lo dice (`empuje_admisible_N` en el detalle de la comprobación).
- **Ruedas nuevas en el catálogo:** Ø160 y Ø200 con espiga M20 (200 y 300 kg), con y sin freno.
- **Asistente:** reconoce «carro plataforma», «plataforma con ruedas», «plataforma rodante / móvil / de
  transporte» y «carro de base plana». Lee la altura del asa («asa a 950 mm») sin confundirla con la
  altura de la plataforma. Una «plataforma de trabajo con ruedas para un operario» sigue siendo una
  tarima, y las ruedas se marcan como no soportadas.

Plantillas: 1.000 × 600 mm (250 kg), 1.200 × 800 mm (500 kg), 1.600 × 800 mm con dos asas (600 kg),
plataforma rodante sin asa de 1.200 × 800 mm (400 kg) y carro inoxidable de 800 × 500 mm.

## Armario industrial

`armario` (`AR`) es una estantería de cuatro montantes cerrada: las bandejas de chapa plegada son el
suelo, las baldas y el techo del armario, y se añaden laterales, fondo y puertas.

- **Laterales y fondo:** chapa lisa cortada por láser, atornillada con tornillos ISO 7380 a tuercas
  remachables en la cara exterior de los montantes. Los montantes de cada esquina llevan sus propios
  taladros. Los paneles tienen taladros de alojamiento donde asoman las cabezas de los tornillos de las
  bandejas, y el fondo cubre los cantos traseros de los laterales.
- **Puertas:** chapa plegada con pestañas de 20 mm, superpuestas al frente y separadas 5 mm de los
  montantes. Por defecto ('auto') hay una puerta hasta 600 mm de anchura y dos por encima; también puede
  no haber puertas. Llevan bisagras exteriores de pernio (2, 3 o 4 según la altura) y maneta con
  cerradura en el canto libre; los herrajes son de inoxidable si la estructura lo es. Su desarrollo se
  orienta con la altura a lo largo de la chapa: el pulido del inoxidable satinado queda vertical y una
  puerta de 2 m cabe en el formato de 4.000 × 2.000.
- **Material:** chapa DC01 por defecto, la habitual en armarios pintados. Los espesores de paneles y
  puertas en 'auto' son la chapa más fina de 1 mm o más disponible en el material (en S235JR, 1,5 mm).
- **Cálculo:** la estructura resiste como una estantería. Paneles, puertas y herrajes son masas colgadas
  de los montantes (las puertas, del montante de las bisagras), sin función resistente. Por defecto se
  ancla al suelo, con un empuje de 150 N en la parte superior.
- **Asistente:** reconoce «armario» y el número de puertas («una puerta», «dos puertas», «puerta doble»,
  «sin puertas»). «4 baldas» son baldas intermedias: con el suelo y el techo, 6 niveles de bandeja.
  «Mesa con armario inferior» sigue siendo una mesa, con el armario como accesorio no soportado.

Plantillas: armario de taller de dos puertas de 1.000 × 500 × 1.950 mm, de una puerta de 600 mm, de
herramientas de 1.200 × 600 × 2.000 mm con 100 kg por balda, bajo de 1.000 mm sin anclar e inoxidable de
800 × 400 × 1.800 mm.

En el armario aparecieron tres fallos generales, corregidos en los dos motores:

- La comprobación de tornillería suponía que la pieza atornillada era una chapa plegada; con una placa
  lisa fallaba. Ahora usa el taladro de paso registrado por la familia.
- El aviso `GEO-SALIENTE` decía siempre «bases de pies o ruedas». Ahora nombra las piezas que sobresalen
  (por ejemplo, la maneta).
- Las hipótesis del cálculo se repetían (la del DC01, una vez por bandeja).
- En los desarrollos, los rótulos de plegado se colocaban antes que las cotas y podían caer encima de ellas
  en piezas estrechas.
- Con travesaños intermedios elegidos a mano (muchos o muy anchos), los travesaños se solapaban entre sí o con
  las patas y montantes sin ningún aviso. La regla `DFM-TRAVESANOS` lo señala y da el número máximo que cabe
  (mesas, puestos, carros, estanterías y armarios). La encontró el barrido aleatorio del motor del navegador
  (`FAMS=armario,carro_plataforma node fuzz.mjs`).
- Una plataforma más baja que la placa base de su rueda daba una pata de longitud negativa (sólido abierto).
  Ahora se rechaza con la altura mínima. Lo mismo con un estante de puesto de trabajo demasiado corto para su
  bastidor: los brazos salían de longitud negativa; ahora se rechaza con el fondo mínimo.
- La fijación de las bandejas podía quedar justo en la tangente del radio de esquina del perfil (a 0,05 mm):
  el cuerpo de la remachable rozaba la esquina interior del tubo. Ahora se exige 1 mm de margen; si no cabe,
  se pide una pestaña mayor. Ninguna plantilla cambia.
- El asistente avisa si se piden más de dos puertas en un armario.
- Nueva advertencia `GAL-VENTEO`: con galvanizado en caliente (EN ISO 1461), los tubos cerrados por soldadura
  necesitan taladros de venteo y drenaje (EN ISO 14713-2). No se modelan; el aviso da un criterio orientativo
  y recuerda repasar las roscas de las tuercas soldadas.

## Depuración de lógica: invariantes

`tools/invariants.py` comprueba sobre las plantillas y casos realistas aleatorios que el motor de
referencia es coherente consigo mismo:

- ningún parámetro queda en 'auto' y ningún valor del usuario se cambia;
- en cada combinación, las reacciones suman las cargas aplicadas, y cada superficie recibe exactamente su
  carga;
- un diseño simétrico tiene reacciones verticales simétricas;
- BOM = suma de piezas = masa del modelo;
- el plan de corte usa cada pieza tantas veces como su cantidad y la longitud de cada barra cuadra;
- el anidado coloca todas las piezas, dentro del formato útil y sin solapes;
- la soldadura total es la suma de las uniones;
- precio ≥ coste ≥ directo y el precio unitario no crece con el lote.

```bash
python tools/invariants.py 250 81
```

Resultado: 284 casos (plantillas y 250 aleatorios), 0 incidencias. `tests/test_invariants.py` lo
ejecuta sobre una plantilla de cada familia. Fallos encontrados y corregidos en los dos motores:

- **Carga perdida en la regla de 45°:** la integración de Gauss cruzaba los quiebros del reparto y
  perdía hasta un 0,1 % de la carga, del lado inseguro (1961,1 N en lugar de 1962,0 N). Ahora se integra
  por tramos.
- **Apoyos horizontales hiperestáticos:** los cuatro apoyos impedían el desplazamiento horizontal.
  Aparecían reacciones horizontales espurias y reacciones verticales asimétricas en diseños simétricos
  (321,7 frente a 361,1 N). Ahora un pie es fijo, otro desliza en X e impide el giro en planta, y el
  resto solo apoya en vertical.
- **Capacidad de pies y ruedas:** se comprobaba solo con la combinación ELS-1. Ahora se usa la peor
  combinación de servicio con peso propio (con carga puntual gobierna ELS-2).
- **Balance de barras:** cuando la última pieza apura la barra, no hay corte final, pero se contaba el
  ancho de sierra (balance de 6001 mm en barras de 6000). La cota inferior ya tiene en cuenta ese corte
  ahorrado.
- **Texto del vuelco:** decía «Vuelco de la carro vacía» y «de la puesto vacía». Ahora concuerda
  («del carro vacío»).

Además, el motor de referencia resolvía cada caso de carga con un sistema denso completo. Ahora
factoriza una sola vez la matriz dispersa (SuperLU) para todos los casos. La comprobación completa de
la mesa de 1.200 mm (dimensionado, cálculo y fabricación) baja de unos 8 s a 2 s.

### Asistente: datos que se perdían o se leían mal

Corregido en los dos intérpretes (`tools/webcheck/interp_cmp.py` compara 55 frases: 0 diferencias):

- **Datos interpretados descartados:** el asa en los dos extremos, el peto o el reposapiés se
  interpretaban, pero no pasaban a los parámetros (solo pasaba una lista fija). Ahora pasa todo lo que
  existe en la familia.
- **Cota unida a la carga:** en «1800x800x900 400 kg», el espacio se tomaba como separador de miles. La
  altura y la carga salían de 900.400. Ahora el espacio solo agrupa miles tras una o dos cifras
  («1 500 kg»), y un número nunca empieza en mitad de otro.
- **Coma tras la planta:** «1000x600, 300 kg» perdía las dos cotas.
- **Carga por nivel:** «5 niveles de 100 kg» se repartía como 100 kg en total (20 kg por nivel).
  «5 baldas de 80 kg cada una» no se leía, y «4 bandejas» no contaba como niveles.
- **Carga de balda y de encimera:** «400 kg, balda de 100 kg» asignaba los 400 kg a la balda, y «balda
  de 80 kg y 200 kg en la encimera» también.
- **Esquema del modelo de lenguaje:** no admitía `tarima` ni `carro_plataforma`.

## Borrar proyectos

En la lista de proyectos, cada fila tiene un botón **Borrar**. Pide confirmación dentro de la propia
página y avisa si el proyecto está validado o tiene expedientes.

- **En el servidor:** `DELETE /api/projects/{código}` elimina revisiones, documentos, historial y la
  carpeta `expedientes/<código>`. No se permite mientras se genera un expediente de ese proyecto.
- **En el navegador:** borra el proyecto de la base de datos privada del artefacto. Los ZIP ya
  descargados no se tocan.
- **Códigos:** no se reutilizan. Antes el siguiente código era «número de proyectos + 1» y, tras
  borrar uno, el proyecto nuevo repetía un código existente. Ahora hay un contador persistente y se
  usa siempre un número mayor que cualquiera emitido.

## Presupuesto estimado

Cada diseño lleva un presupuesto unitario calculado desde el modelo y el plan de fabricación con
las tarifas orientativas de `monxu/catalog/data/costs.json`, editables:

- material (con merma de perfil y aprovechamiento de chapa, o barras y chapas completas por lote);
- normalizados;
- consumibles de soldadura;
- operaciones:
  - corte y taladrado de perfiles;
  - láser por metro y por perforación, según espesor y material;
  - plegado por pliegue;
  - soldadura por horas de arco y factor de marcha;
- acabado por m² o por kg;
- montaje por elemento;
- preparación de máquinas y útil repartida entre las unidades del lote;
- gastos generales y margen.

Se incluye una tabla de coste unitario para lotes de 1, 5, 10, 25 y 50 unidades.

Aparece en la pestaña «Presupuesto», en la hoja «Presupuesto» del Excel (con fórmulas) y en
`04_LISTA_MATERIALES/presupuesto_estimado.csv/.json` del expediente. Los dos motores dan el mismo
importe (validación cruzada). Son tarifas de referencia: no incluyen transporte, embalaje especial,
diseño ni impuestos.

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

- **Plantillas:** las 25 plantillas (las 5 familias) salen con 0 conflictos en planos y montaje,
  salvo un cruce de líneas de referencia en el explosionado de PT-2000-TALLER. Una pasada final
  recoloca cualquier globo cuya referencia cruce otra; en ese caso no existe una posición libre
  de cruces y la hoja sigue siendo legible.
- **Configuraciones aleatorias:** en 60 configuraciones (1.032 hojas) quedan 6 conflictos: 5 cruces
  de referencias y 1 línea que toca un texto. Antes de estos cambios, 40 configuraciones (626 hojas)
  daban 117 conflictos, entre ellos textos superpuestos.
- **Servidor:** las mejoras de colocación están en los planos del navegador. Los planos PDF del
  servidor (`monxu/docs/plans.py`) mantienen su maquetación anterior.

## Versión artefacto (motor en el navegador)

La misma interfaz funciona sin servidor: el motor completo está portado a TypeScript en
`frontend/src/engine/` (parámetros y dependencias, las cinco familias, chapa plegada y
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

Con las 25 plantillas de las cinco familias, la aceptación 2000→2400, los dos diseños por defecto y
30 casos aleatorios de todas las familias (59 casos) no hay ninguna diferencia, ni en el presupuesto.
Los casos aleatorios incluyen peto, asas y carro estantería. Una segunda tanda de 66 casos (40
aleatorios) tampoco tuvo diferencias. La mesa de soldadura sumó 72 casos sin diferencias. La
estantería en batería, con sus 3 plantillas y 29 casos aleatorios (2 a 5 módulos, con y sin carga,
anclada o no, travesaño fijo o 'auto'), tampoco tiene ninguna. El aprovechamiento coincide exactamente en todas las
comprobaciones salvo el vuelco, donde el error relativo es ≤ 2,4·10⁻⁴ por el centro de gravedad
calculado sobre los sólidos facetados.

`tools/webcheck/verify_dossier.py` relee el ZIP generado por el navegador con las herramientas del servidor:

- **STEP:** reimportación con OpenCascade. Mesa de 2000 mm: 99/99 sólidos válidos y volumen a −0,07 % del B-rep;
  estantería de 2888 mm: 311/311. Puesto de trabajo de 1500 mm: 137 ocurrencias, 139/139 sólidos válidos
  (−0,08 %). Carro de 1200 mm: 81 ocurrencias, 95/95 sólidos válidos (−0,22 %). Carro estantería de picking
  de 1200 mm: 126 ocurrencias, 140/140 sólidos válidos (−0,15 %). Estantería en batería de 3 × 1.000 mm:
  317/317 sólidos válidos (−0,08 %), BOM con 317 unidades como el servidor. Cada rueda se compone de varios
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

Tras añadir el peto, las asas y el carro estantería, otros 300 casos de las cinco familias (con 2
expedientes completos) dieron 0 excepciones, 0 valores no finitos, 0 sólidos abiertos y 0 expedientes
fallidos. Las 132 configuraciones con interferencias van, todas, acompañadas de otro error de diseño
que las explica (`tools/webcheck/interf_why.ts`: 0 sospechosas).

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

## Correcciones de dimensionado

- **Chapas:** el dimensionado de encimeras, baldas y bandejas usaba el peso propio de la superficie
  plana. La verificación final usa la chapa real, con pestañas. Con flechas al límite, la
  verificación podía no cumplir (balda de la mesa inoxidable de 1500 mm: 100,4 %). Ahora los dos
  pasos usan la misma carga.
- **Carga puntual:** el espesor de encimera también se elige para que cumpla la carga puntual
  (`CARGA_PUNTUAL`). La mesa pesada de 2400 mm con 150 kg pasa de 146 % a 93 % con 4 mm de chapa.
- **Plantillas de mesa:** las de uso general y trabajo pesado se proponen ancladas al suelo. Con el
  empuje de 300 N, una mesa vacía de 45 kg vuelca de verdad. Quedan pendientes solo de verificar el
  taco. Ninguna plantilla del catálogo sale NO_CUMPLE.

### Barrido realista: fallos de creación corregidos

`tools/webcheck/realistic.py` genera casos con solo los datos que daría un cliente (medidas, cargas,
niveles, material, opciones) y deja el resto por defecto o en `auto`. En esos casos, un error
bloqueante es un fallo del generador. Se corrigió en los dos motores:

- **Carga puntual sin carga repartida:** la encimera no se dimensionaba y no cumplía.
- **Regla de diseño para valores por defecto incompatibles.** Si un valor que el usuario no ha
  fijado choca con otro, se corrige, se vuelve a dimensionar y se anota (`REGLA-*`). Un valor del
  usuario nunca se toca: se informa del error con el valor que funcionaría. Se aplica a:
  - la balda frente al reposapiés (con los valores por defecto chocaban siempre);
  - la balda o el primer nivel frente a la placa base y los apoyos;
  - el asa del carro estantería frente a los niveles.
- **Desplome:** solo se aumentaba la pata. Con travesaños débiles, una mesa de aluminio agotaba la
  serie hasta SHS 120x120x5 sin cumplir. Ahora se aumenta el elemento más flexible del pórtico en la
  dirección que falla (pata, EI/h, o viga, EI/L). La misma mesa cumple con SHS 50x50x2 y
  travesaños RHS 60x30x2.
- **Bastidor retranqueado:** tenía que caber en la pata contando el retranqueo para la pestaña de la
  chapa, no solo su ancho (`DFM-BASTIDOR-INF`, `DFM-BASTIDOR`).
- **Series de candidatos ampliadas:** SHS 100x100x5, 120x120x4 y 120x120x5; reposapiés RHS 80x40 y
  100x40.
- **Tuercas de soldar:** la DIN 929 de acero se soldaba a placas base de aluminio, que no es
  soldable, y de inoxidable, que crea un punto de corrosión. Ahora es del mismo material que la
  estructura. Una regla de fabricación nueva detecta uniones soldadas entre aluminio y acero
  (error) o entre acero e inoxidable (advertencia).
- **Presupuesto:** fallaba con piezas que no caben en ningún formato de chapa.
- **Asistente:** no entendía medidas de planta sueltas («2000 x 1000», «1500 por 800»).
- **Mensajes:** ahora dicen qué carga no se verifica y qué comprobación agota los perfiles.

Lo que sigue saliendo NO_CUMPLE o bloqueante en el barrido es física o un valor imposible fijado
por el usuario: vuelco de muebles sin anclar con el empuje por defecto, chapa DC01 (máximo 3 mm)
con cargas puntuales, taladro de Ø16 en placa de 20 mm, o un asa fijada contra un nivel.

## Servidor: errores corregidos

- `/api/projects` devolvía 500 en cuanto había algún proyecto, porque las revisiones se leían fuera
  de la sesión de base de datos. El interfaz mostraba la lista vacía.
- Con la base de datos vacía, dos peticiones simultáneas creaban las tablas a la vez («table
  already exists», 500).
- Un proyecto, revisión o plantilla inexistente devuelve 404 con el motivo, no 500.

## Errores encontrados por los barridos y corregidos

- **Pestaña más baja que el pliegue:** si la pestaña no llegaba a radio más espesor (radio de plegado
  grande con pestaña corta), OpenCascade no podía crear la arista y el diseño fallaba entero
  (`StdFail_NotDone`). Ahora se modela solo la zona curva, como en el navegador, y el DFM lo señala
  (`PLG-ALA-MIN`, `CHAPA-DESARROLLO`). En ese caso no fabricable la masa de esa chapa difiere entre
  motores: el navegador la calcula desde el desarrollo y el servidor desde el sólido. El veredicto y los
  errores sí coinciden.
- **Plantillas desactualizadas en el servidor:** las plantillas integradas solo se insertaban si
  faltaban, así que en una base de datos existente las modificadas conservaban sus valores antiguos.
  Ahora se actualizan al arrancar; las plantillas guardadas por el usuario no se tocan.
- **Control de calidad distinto según el motor:** el servidor no comprobaba el volumen de perfiles y
  pletinas frente a su definición analítica (`GEO-VOLUMEN`), que detecta booleanas fallidas. Ahora lo
  hace, y una prueba compara la lista completa de control de calidad de los dos motores.
- **Planos del navegador:** el diámetro de taladro de las pletinas se colocaba antes que sus cotas y
  podía quedar atravesado. En los símbolos de soldadura, una garganta de texto ancho («a1,5») invadía
  el círculo de soldadura perimetral. El barrido de 120 configuraciones (1920 hojas) baja de 18
  conflictos a 1.
- **Planos del servidor:** no tenían auditoría de legibilidad. `tests/test_server_drawings.py`
  comprueba ahora que ningún texto pise a otro. Se han corregido:
  - el número de unión montado sobre el proceso de soldadura;
  - el título de la sección A-A sobre la cota de espesor;
  - el rótulo de la perspectiva sobre el sello de estado;
  - los rótulos del plan de corte dentro del cajetín;
  - los símbolos de soldadura fuera del marco o dentro de los detalles;
  - las filas de globos fuera del marco (ahora se compactan o se reparten en filas intercaladas).

  Las 31 plantillas salen sin solapes de texto, en los planos del servidor y en los del navegador. En el
  navegador queda un único aviso de maquetación: dos líneas de referencia que se cruzan en la vista
  explosionada de PT-2000-TALLER.

- **Alertas repetidas en el interfaz:** el panel de alertas juntaba las notas de diseño con el control de
  calidad, que ya incluye las notas de error y advertencia, así que cada una aparecía dos veces.
- **Asistente: fondo tomado como anchura.** En «estantería de 600 de fondo y 2000 de alto», el fondo se
  asignaba también a la anchura de frente. Ahora la anchura queda por definir y se pregunta. Además se
  reconoce «frente» («1800 de frente», «frente total de 3600»).

## Verificación completa automática

Ninguna plantilla ni diseño por defecto queda «PENDIENTE»: las 63 plantillas y el diseño por defecto de las diez
familias salen CUMPLE. Lo que antes dejaba la verificación incompleta se calcula o se decide solo, en los dos motores
(Python y navegador, misma salida):

- **Cargas de uso por defecto (`por_uso`)**: si no se indica una carga, se adopta la del uso previsto y queda anotada
  (`CARGA-USO`). Mesa y puesto: 100–300 kg/m² según el uso (montaje 150), con la balda a la mitad. Estantería: 150 kg/m²
  de bandeja; carro estantería y armario: 100 kg/m². Mesa de soldadura: 500 kg/m², balda al 30 %. Carro plataforma:
  250 kg/m². Tarima: 2 kN/m² de EN ISO 14122-2, redondeados hacia arriba. Estante del puesto: 100 kg/m². La carga se
  recalcula si cambian las medidas, porque no se guarda como dato del proyecto.
- **Anclaje automático**: con «sin anclaje» por defecto, si el conjunto vacío volcara con el empuje, la regla de diseño
  lo ancla al suelo (`REGLA-ANCLAJE`). Un «sin anclaje» elegido por el usuario se respeta.
- **Tacos de anclaje (`TACO_ANCLAJE`, M8–M16)**: el de menor capacidad que resiste la tracción de cálculo por taco
  (vuelco EQU en las cuatro direcciones). `E.ANCLAJE` es una comprobación real contra la capacidad de catálogo. Los tacos
  se dibujan bajo cada pie, salen en la BOM y en el presupuesto y añaden el taladro al paso de montaje. No cuentan como
  peso estabilizador.
- **Carros**: la maniobra actúa completa en la dirección de la marcha y al 50 % en la lateral (giros y empujes
  ocasionales). Sin asa, completa en todas las direcciones.
- **Secciones clase 4**: sección eficaz según EN 1993-1-5 §4.4 (ρ de la pared más esbelta aplicada a toda la sección, del
  lado de la seguridad). Antes quedaban pendientes.
- **Carga 0 indicada**: la superficie se verifica con su peso propio. Antes quedaba pendiente.
- **Corrección automática comprobada**: si un diseño NO CUMPLE por valores fijados (perfil, espesor, chapa DC01,
  «sin anclaje», taco), se calcula la corrección mínima. Puede ser devolver esos valores a «auto», anclar al suelo, pasar
  la chapa a S235JR o, en un carro, limitar la fuerza de maniobra a la admisible (iterada porque el redimensionado cambia
  el peso). Sólo se ofrece si, regenerado y verificado, el diseño CUMPLE. En el barrido aleatorio había 11 casos que no
  cumplían por valores impuestos y los 11 tienen corrección comprobada. Se aplica con un botón (`correccion`).
  También se corrigen las geometrías imposibles por un valor fijado, con el valor válido más próximo que calcula la
  familia: asa contra un nivel, primer nivel o tarima demasiado bajos. La corrección geométrica se combina con la de
  cálculo si hace falta. Las dos implementaciones dan la misma corrección.
- **Rendimiento**: búsqueda de nodos en rejilla y matriz de rigidez dispersa en el cálculo de barras (antes cuadrática y
  densa). La estantería en batería por defecto pasa de 30 s a 8 s.

## Asistente automático y proyecto guardado

- **El asistente adopta y calcula lo que falta** en vez de preguntarlo: medidas propuestas, cargas de uso calculadas por
  el motor, material y uso habituales y anclaje decidido por el cálculo. Lo expone como supuestos que se cambian con los
  botones o escribiendo el dato. Cada respuesta se aplica sola al proyecto y el diseño se regenera y verifica.
- Sólo se aplica lo que cambia en cada turno (`to_apply`): lo editado en el formulario no se deshace, y lo que ya tiene el
  proyecto cuenta como conocido.
- Si la descripción es de otra familia y el proyecto aún no tiene revisiones, el proyecto cambia de familia.
- `«con balda y 400 kg»` asigna los 400 kg a la encimera. Sólo «balda de 100 kg» o «balda inferior: 100 kg» son
  carga de la balda.
- **Persistencia**:
  - la conversación se guarda con el proyecto (`assistant_state.chat`, últimos 40 mensajes) y no se pierde al cambiar de
    apartado ni al salir;
  - el borrador del formulario se guarda solo, 0,8 s después del último cambio;
  - al abrir un proyecto el diseño se regenera solo con sus parámetros guardados.
- Paridad: `tools/webcheck/interp_cmp.py` compara 66 frases y 15 conversaciones completas entre los dos motores
  (respuesta, supuestos, preguntas y datos aplicados en cada turno), sin diferencias.

### Validación de esta ronda

| Prueba | Resultado |
| --- | --- |
| Validación cruzada Python ↔ navegador | 107 casos, 0 diferencias. Ningún PENDIENTE (plantillas y defectos CUMPLE). |
| Invariantes de lógica | 183 casos, 0 incidencias. |
| Barrido realista (300 casos aleatorios) | Todo «NO CUMPLE» por valores impuestos tiene corrección comprobada. Quedan 2 bloqueos de geometría sin un valor único: taladro Ø16 en placa de 20 mm y tarima sin perfil posible. |
| Auditoría de planos y montaje | 73 casos (63 plantillas y los 10 diseños por defecto, con tacos), 0 solapes. |
| Pruebas Python | 125 rápidas y 18 lentas superadas. |
| Expediente del navegador con tacos | Verificado con las herramientas del servidor (STEP, DXF, STL), 0 errores. |
| Flujos de interfaz | Diseño recuperado al abrir, asistente que aplica y regenera, conversación y borrador conservados, corrección aplicada con un botón: 14/14 sin errores de consola. |
| Recorrido de las 63 plantillas en la interfaz | Sin errores de consola y 0 bloqueantes. |

## Datos que quedan como hipótesis o pendientes

- **Empuje horizontal:** 300 N por defecto en el canto de la encimera. Si con ese valor la mesa vacía volcara, se ancla al
  suelo por regla de diseño, salvo que el usuario haya elegido «sin anclaje».
- **Tacos de anclaje:** capacidad de tracción de catálogo genérico en hormigón C20/25 no fisurado, a confirmar con la ETA
  del fabricante y el soporte real.
- **Capacidad de los pies niveladores y de las ruedas:** catálogo genérico, a confirmar con el proveedor. Las ruedas
  se modelan con su envolvente simplificada (sin descentrado de giro).
- **Fuerza de maniobra del carro:** 100 N por defecto, aplicada en el plano de la encimera con las ruedas frenadas.
  En el carro plataforma, 50 N en el asa. El vuelco se comprueba con el carro vacío en la dirección más
  desfavorable, que en carros estrechos es la lateral.
- **DC01:** la norma no garantiza fy mínimo, así que se marca como hipótesis.
- **Armario:** paneles y puertas no se cuentan como diafragma (del lado de la seguridad). No se comprueba el
  vuelco con las puertas abiertas ni una carga sobre una puerta abierta. Las bisagras y la maneta se modelan
  con su envolvente; sus remaches y taladros no se modelan.
- **Gargantas a < 3 mm:** quedan fuera de EN 1993-1-8 §4.5.2 y requieren una WPS cualificada.

## Referencia MT-1800

El repositorio no contenía los archivos del proyecto de referencia MT-1800 (PDF, Excel, DXF).
La presentación se ha basado en la práctica normalizada: cuadro de rotulación ISO 7200, líneas
ISO 128-2, acotación ISO 129-1, primer diedro, símbolos ISO 2553 y tolerancias ISO 2768-mK /
EN ISO 13920. Cuando se aporten, conviene ajustar cajetín, distribución de vistas y codificación
de referencias a ese patrón.

Más detalle técnico en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).
