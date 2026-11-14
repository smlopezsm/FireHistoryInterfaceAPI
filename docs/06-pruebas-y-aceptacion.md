# 06 · Pruebas y criterios de aceptación

## 1. Datos de prueba (fixtures)

En `tests/fixtures/` se incluye un **mini dataset** (menos de 1 MB) con el mismo formato que [02](02-contratos-de-datos.md):

| Archivo | Contenido |
|---|---|
| `dim_provincias.parquet` | 2 provincias ficticias (`P1` en región `R1`, `P2` en `R2`) |
| `dim_celdas.parquet` | 20 celdas (10 por provincia) |
| `conteos_celda_dia/` | 2001, 2006, 2011, 2012, 2022, 2026, con casos elegidos a mano |
| `factores_provincia_mes.parquet` | Factores fijos y conocidos (por ejemplo `P1` = 3,0 en todos los meses); falta `(P2, mes 5)` para la U8 |
| `factores_region_mes.parquet` | Factores de respaldo de `R1`, `R2` y `Argentina` (`R2` mes 5 conocido, para la U8) |
| `satelite_operativo.parquet` | Incluye una caída de S-NPP de 3 días en 2022 |
| `rangos.parquet` | Los valores de la tabla inicial |

## 2. Pruebas unitarias (lógica)

| ID | Caso | Resultado esperado |
|---|---|---|
| U1 | Mes de 2006 con 10 focos MODIS en `P1` (factor 3,0) | `armonizado = 30`, `estado = estimado`, `viirs = null` |
| U2 | Mes de 2022 con S-NPP operativo todos los días | `armonizado = Σ n_snpp`, `estado = observado`, `minimo = maximo = armonizado` |
| U3 | Mes de 2022 con 3 días de S-NPP caído | `estado = mixto`, `frac_estimada = 3/31`, esos días se estiman con MODIS |
| U4 | Fecha 2026-11-10 | La referencia es `n_n20`, no `n_snpp` |
| U5 | 2001 (solo Terra) | Se usa `n_terra` y `tipo = terra` |
| U6 | `n_n21 > 0` | **No** cambia `armonizado` |
| U7 | Zona que cruza `P1` y `P2` | Suma por provincia con su propio factor |
| U8 | Factor faltante `(P2, mes 5)` | Usa el de la región; `nivel_origen = region` |
| U9 | `modis_est = 0` en un mes 100 % estimado | `minimo = 0`, `maximo = 10` |
| U10 | Anomalía con menos de 10 años | `categoria = null` |

## 3. Pruebas de contrato (API)

| ID | Endpoint | Verifica |
|---|---|---|
| C1 | Todos | Las respuestas validan contra los modelos Pydantic y el `openapi.json` |
| C2 | `/calendario` | `viirs` es `null` (no `0`) antes de 2012-01-20 |
| C3 | `/calendario` sin zona o con dos zonas | 400 `ZONA_INVALIDA` |
| C4 | `/mapa/celdas` con más de 20.000 celdas | 413 |
| C5 | `/descargas/focos.csv` | `Content-Type` y `Content-Disposition` correctos; columnas en el orden documentado |
| C6 | `/admin/reload` sin token | 401 |
| C7 | `/health` sin datos | 503 en endpoints de datos; `/health` devuelve `degradado` |

## 4. Pruebas de rendimiento (en el VPS, con datos reales)

| ID | Escenario | Objetivo |
|---|---|---|
| R1 | `/calendario` de una provincia, 2000 → hoy | p95 < 800 ms |
| R2 | `/calendario` de Argentina completa | p95 < 2,5 s |
| R3 | `/calendario` con un polígono de 500 vértices | p95 < 1,5 s |
| R4 | `/mapa/celdas`, vista nacional, 1 mes | p95 < 1,5 s |
| R5 | 20 usuarios concurrentes (calendario + mapa) | 0 errores 5xx; RAM del contenedor < 1,5 GB |
| R6 | Memoria en reposo (API) | < 400 MB |

## 5. Validación científica (regresión)

Se recalcula sobre los datos reales y se compara con los resultados de la Propuesta B:

| ID | Chequeo | Tolerancia |
|---|---|---|
| S1 | Total anual nacional armonizado 2013–2025 vs. S-NPP observado (capa `armonizado` forzada a estimar) | Diferencia anual ≤ 12 % en todos los años |
| S2 | Factor nacional implícito | 3,32 ± 0,05 |
| S3 | Cobertura del rango del 80 % en 2023–2025 | 72–88 % |
| S4 | Sin escalón en 2012: razón estimado/observado 2012–2015 | Entre 0,90 y 1,12 |

## 6. Criterios de aceptación del MVP

- [ ] Los 11 endpoints responden según este contrato.
- [ ] Las pruebas U1–U10 y C1–C7 pasan en CI.
- [ ] R1, R2 y R5 cumplen en el VPS.
- [ ] S1–S4 cumplen con los datos de producción.
- [ ] La imagen Docker pesa menos de 250 MB y se despliega por webhook en menos de 1 minuto.
- [ ] `/docs` (Swagger) accesible y con descripciones en español.
