# Arquitectura técnica

## Flujo de datos (fuente única)

```
Lenguaje natural ──► Asistente IA ──► Parámetros (tabla central, con origen de cada valor)
                                            │
                     Dimensionado (reglas + cálculo) resuelve los valores "auto"
                                            │
                                            ▼
                     Familia de producto (reglas constructivas, árbol de operaciones)
                                            │
                                            ▼
                     Modelo de producto: piezas B-rep (OpenCascade) + instancias + uniones
            ┌───────────────┬───────────────┼───────────────┬────────────────┐
            ▼               ▼               ▼               ▼                ▼
      Cálculo (FEM,   Fabricación     BOM / pesos     Planos (HLR)     Exportación
      placas, EN 1993) (DFM, corte,   (desde sólidos)  cotas medidas    STEP/STL/BREP/
                       anidado)                        en la geometría  DXF/Excel/PDF
            └───────────────┴───────────────┴───────────────┴────────────────┘
                                            │
                          Control de calidad previo (bloqueante / advertencia /
                          pendiente / correcto) + reverificación de archivos
                                            │
                          Expediente atómico 01…06 + manifiesto SHA-256 + ZIP
```

Nada se calcula dos veces por caminos distintos: los planos miden la geometría, el DXF sale del
mismo desarrollo que el sólido 3D, el BOM pesa los sólidos y el modelo de cálculo usa los ejes y
las uniones de las instancias del CAD.

## Módulos

| Paquete | Responsabilidad |
|---|---|
| `monxu/catalog` | Catálogos JSON versionados: materiales, perfiles EN 10219, chapa y reglas de taller, componentes, normas, criterios de cálculo. Propiedades de sección calculadas desde la geometría de la sección. |
| `monxu/core` | `ParamSpec`/`ParameterSet` (validación, unidades, origen del valor), `ParamContext` (derivados y árbol de operaciones con dependencias registradas automáticamente), modelo de producto (piezas, instancias, subconjuntos, uniones). |
| `monxu/cad` | Sólidos B-rep (tubos con radios EN 10219, chapa plegada por operaciones con radio y factor K, pletinas, normalizados), interferencias por volumen común, exportación STEP/STL/BREP/GLB y malla para el visor. |
| `monxu/families` | Interfaz `ProductFamily` y registro. Implementada: `mesa_industrial`. Previstas (no implementadas): puestos de trabajo, estanterías, armarios. |
| `monxu/engineering` | FEM 3D de barras (12 GDL), placas por serie de Navier, comprobaciones EN 1993-1-1/1-8 simplificadas, vuelco EQU, dimensionado iterativo. |
| `monxu/manufacturing` | Corte de barras (BFD + ramificación y poda hasta la cota inferior), anidado MaxRects, soldadura, pintura, reglas DFM. |
| `monxu/docs` | BOM, Excel con fórmulas, DXF por capas, planos A3 (HLR, cajetín ISO 7200, primer diedro, ISO 129, ISO 2553), informes PDF. |
| `monxu/validation` | Control de calidad previo a exportación y coherencia plano ↔ geometría. |
| `monxu/pipeline.py` | Regeneración sincronizada y expediente atómico. |
| `monxu/storage` | SQLite/SQLAlchemy: proyectos, revisiones inmutables, registro de cambios, documentos, plantillas. |
| `monxu/ai` | Intérprete determinista en español + adaptador opcional a Claude con salida estructurada. |
| `monxu/api` | API REST FastAPI; sirve la interfaz compilada. |
| `frontend/` | React + TypeScript + Three.js. |

## ADR-001: motor geométrico

**Decisión:** CadQuery 2.8 sobre OCP (OpenCascade 7.9) como kernel B-rep.

**Contexto:** se requiere geometría sólida real, operaciones booleanas, propiedades másicas,
proyección con líneas ocultas para planos y exportación STEP/STL.

**Alternativas evaluadas:**

- *FreeCAD (API Python):* usa el mismo kernel OpenCascade y aporta módulos de chapa y TechDraw,
  pero no se distribuye como paquete pip (requiere conda/AppImage), arrastra la aplicación
  completa y su API de documentos con recomputación global complica el uso como servicio.
- *CadQuery/OCP:* instalable con pip, API Python directa sobre OpenCascade, licencias
  Apache-2.0 (CadQuery) y LGPL-2.1 (OCCT) compatibles con uso comercial, exportación STEP con
  ensamblajes y nombres, HLR exacto disponible en OCP.

**Consecuencias:**

- La chapa plegada se modela por operaciones propias (cara base + pestañas con radio y factor K).
  Sólido y desarrollo salen de la misma definición, y su coherencia se comprueba exactamente.
- Los planos se generan con HLR de OpenCascade y reportlab (no TechDraw).
- El "formato editable nativo" del expediente es el JSON paramétrico de la plataforma, que
  regenera la geometría, más el BREP nativo de OpenCascade. No se genera `.FCStd`; para
  intercambiar con FreeCAD o con otros CAD se usa el STEP del conjunto y de cada pieza.

## Limitaciones conocidas

- Sólo la familia mesa industrial tiene generador paramétrico. Las demás familias se interpretan
  en el asistente, pero se declaran como no implementadas.
- Accesorios no implementados: cajones, panel trasero perforado, ruedas, puertas, iluminación,
  tomas eléctricas, soportes de monitor y regulación de altura. El asistente los detecta y los
  declara como no incluidos.
- El cálculo es elástico lineal de primer orden con métodos simplificados conservadores. No hay
  FEA de placa ni de detalle de unión, P-Δ, fatiga ni análisis dinámico. La validación
  definitiva corresponde a un técnico competente, y la aplicación lo exige antes de pasar el
  proyecto a "preparado para fabricación".
- El anidado es por envolvente rectangular, no de forma libre.
- Las capacidades de pies niveladores proceden de un catálogo genérico y deben confirmarse con
  el proveedor.
