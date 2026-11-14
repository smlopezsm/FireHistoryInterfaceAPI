# 08 · Estado actual y próximos pasos (F3–F7)

Documento de traspaso para retomar el backend. Estado al **2026-11-14**.

## 1. Qué está hecho (en `main`)

| Feature | PR | Qué quedó |
|---|---|---|
| F1 · Esqueleto | #2 | FastAPI, configuración por entorno, DuckDB de solo lectura por worker, `/health`, `/metadata`, errores, CORS, ETag, Dockerfile (imagen de 141 MB), CI |
| Docs · factores de respaldo | #3 | `factores_region_mes.parquet` en [02 §5.1](02-contratos-de-datos.md) |
| F2 · Zonas | #4 → #5 | `/provincias`, resolución de zona (provincia, bbox, polígono), límite de 256 KB en los POST |

**Pruebas:** 63 en verde; ruff y mypy (estricto) sin errores.

## 2. Reglas de trabajo

- **Una feature por vez.** Cada rama sale de `main` actualizado y **cada PR va contra `main`**. No apilar PR: el #4 se mergeó en la rama de F1 y hubo que reabrirlo.
- Pruebas **primero** para la lógica de armonización (F3 y F4).
- Antes de cada PR: `ruff check . && ruff format --check . && mypy app && pytest -q`. El build de Docker lo valida el CI.
- Nada de dependencias de ML. `null` nunca es 0. Mensajes y descripciones de Swagger en español.
- Si algo no está en `docs/`, preguntar antes de inventar.

## 3. Decisiones ya tomadas (y documentadas en 01, 03 y 04)

| Tema | Decisión |
|---|---|
| `capa` (`modis`, `viirs`) | Cada mes trae siempre todos los campos; la capa solo cambia `unidad` y `resumen` |
| Mes en curso | `frac_estimada` se divide por los días con datos (hasta `fecha_max`) |
| Meses con dos factores (julio de 2002) | MODIS de días solo Terra × factor `terra` + MODIS de días Terra + Aqua × factor `modis` |
| Recarga con 2 workers | `POST /admin/reload` reabre el worker que lo recibe; cada worker revisa el symlink `current` cada pocos segundos |
| Zona por provincia | Celdas de `dim_celdas` con ese `provincia_id` (no centroide en el polígono provincial) |
| Body > 256 KB | 413 `CUERPO_DEMASIADO_GRANDE` |
| `satelite_operativo` sin fila para un día | Ese día el satélite cuenta como **no operativo** |

## 4. Piezas existentes para reutilizar

| Pieza | Dónde | Uso |
|---|---|---|
| `Datos.consultar(sql, params)` | `app/db.py` | Filas como `dict`; aplica cupo de 4 consultas y corte a los 10 s (504) |
| `Datos.consultar_columnas(sql, params)` | `app/db.py` | Columnas como arreglos NumPy (resultados grandes) |
| Vistas DuckDB | `app/db.py` (`ARCHIVOS`) | `focos`, `conteos_celda_dia` (con `anio` SMALLINT), `dim_celdas`, `dim_provincias`, `factores_provincia_mes`, `factores_region_mes`, `rangos`, `satelite_operativo`, `puntos_industriales` |
| `resolver_zona(datos, PedidoZona)` | `app/services/zonas.py` | Devuelve `ZonaResuelta`: `celdas_ids`, `provincias` (celdas y km² por provincia), `.respuesta()` → modelo `Zona` |
| `ZonaQueryDep` / `PedidoZona` | `app/deps.py`, `app/schemas/zonas.py` | Zona en GET (query) y base de los bodies POST |
| `DatosListosDep` | `app/deps.py` | 503 `DATOS_NO_DISPONIBLES` si no hay datos |
| `ApiError(status, codigo, mensaje, detalle)` | `app/errores.py` | Formato único de error |
| Caché | `app/cache.py` | `ETag` y `Cache-Control` automáticos en GET con 200 |

Para filtrar por celdas en DuckDB: `WHERE cell_id IN (SELECT unnest(?::INTEGER[]))` pasando `zona.celdas_ids`.

## 5. Plan por feature

### F3 · `/calendario` y `/serie` (`feat/f3-calendario`)

1. **Pruebas primero** (`tests/test_armonizacion.py`) con los valores esperados de la §6.
2. `app/services/armonizacion.py`:
   - Una consulta DuckDB: conteos de la zona en el período, unidos día a día con `satelite_operativo` de la referencia (S-NPP hasta 2026-11-02, N20 desde 2026-11-03), agrupados por **provincia × mes** con: `obs` (Σ n_ref en días operativos), `modis_est_modis` y `modis_est_terra` (MODIS de días no operativos, según el período), `modis` crudo, días estimados y días con datos.
   - Generar **todos** los meses del período aunque no tengan focos.
   - En Python: factor con respaldo provincia → región (`dim_provincias.region`) → `Argentina`; rango por tramo de `rangos.parquet` (con `modis_est = 0` → 0 a `mult_alto` solo si el mes es 100 % estimado; en mixtos, 0); sumar provincias; `estado`, `frac_estimada`, `confianza` (provincias "pocos datos": `94`, `78`, `02`, por fracción de área de la zona), `parcial`.
   - `viirs = null` solo si en el mes no hubo ningún día con referencia operativa.
   - Redondeo: armonizados con 1 decimal; conteos enteros.
3. Routers GET y POST de `/calendario` y `/serie` (`granularidad = mes | anio`). Validar `desde`/`hasta` (`YYYY-MM`) → 400 `PERIODO_INVALIDO`. `resumen`: `max_mes`, `max_anio`, `total`, `mediana_mensual`.
4. Pruebas de contrato C2 (`viirs` null antes de 2012-01-20) y C3 (zona inválida).
5. Verificación manual: `/calendario?provincia_id=P1` sobre los fixtures mostrando 2006-08 (estimado), 2022-07 (observado) y 2022-08 (mixto).

### F4 · `/anomalia` (`feat/f4-anomalia`)

- Reutiliza la serie armonizada de F3. Mismo mes calendario de todos los años, **excluyendo** el evaluado. Mediana, p10, p25, p75, p90 empíricos; `razon` null si la mediana es 0; `categoria` null con menos de 10 años o si el mes es parcial. Default: último mes completo.
- Prueba U10 (los fixtures tienen pocos años → `categoria = null`). Para probar categorías, armar un dataset temporal en `tmp_path` con 12+ años.

### F5 · Mapa (`feat/f5-mapa`) — mostrar plan antes de codear

- `/mapa/celdas`: `bbox` obligatorio, período de hasta 366 días (`YYYY-MM-DD`), misma lógica de F3 agrupada por **celda** (factor por provincia × mes de cada celda), filtro `min_focos`. Más de `MAX_CELDAS_MAPA` → 413 `RESULTADO_DEMASIADO_GRANDE` "acercá el mapa o acortá el período". GeoJSON armado con `orjson` desde `geom_geojson`.
- `/mapa/industriales`: puntos con `motivo`, `n_focos`, `provincia_id`; `bbox` opcional.
- Prueba C4: bajar `max_celdas_mapa` en la configuración de la prueba para forzar el 413.

### F6 · Descargas (`feat/f6-descargas`)

- `focos.csv`: contar primero (más de `MAX_FILAS_CSV` → 413), después `StreamingResponse` leyendo de DuckDB por lotes. Primera línea: comentario con la cita a NASA FIRMS. Columnas en el orden de `docs/03`. Filtro `sensor`.
- `calendario.csv`: reutiliza F3.
- `Content-Disposition: attachment; filename="focos_<zona>_<desde>_<hasta>.csv"` con zona `provincia-74`, `bbox` o `geometria`.
- Prueba C5.

### F7 · Recarga (`feat/f7-recarga`)

- `POST /admin/reload` con `Authorization: Bearer <RELOAD_TOKEN>`: sin token → 401, token incorrecto → 403 (comparar con `secrets.compare_digest`), OK → 204.
- Chequeo periódico del destino de `DATA_DIR` (`Path.resolve()`) en cada worker; si cambió, `Datos.abrir()` (ya cambia la conexión de forma atómica). Excluir `/admin/` de la caché (ya está en `app/cache.py`).
- Prueba C6 y cierre de C1 (todas las respuestas validan contra `/openapi.json`) y C7.

### Cierre

Revisar los criterios de [06 §6](06-pruebas-y-aceptacion.md#6-criterios-de-aceptación-del-mvp): 11 endpoints, U1–U10 y C1–C7 en CI, imagen < 250 MB, README.

## 6. Valores esperados con los fixtures (`provincia_id = P1` salvo indicación)

Factores: `P1` modis 3,0 / terra 2,0; `P2` modis 4,0 (falta el mes 5) / terra 2,5; `R2` modis mes 5 = 3,5.

| Prueba | Mes | Esperado |
|---|---|---|
| U5 | 2001-09 | MODIS 5 (solo Terra) × 2,0 = **10,0**; rango 1–5 → [4,6 ; 44,9]; estimado, confianza baja |
| U1 | 2006-08 | MODIS 10 × 3,0 = **30,0**; rango 6–20 → [16,5 ; 55,8]; estimado; `viirs = null` |
| U9 | 2006-03 | Sin focos: armonizado 0, mínimo 0, máximo **10** |
| U8 | 2011-05 (`P2`) | MODIS 4 × 3,5 (región `R2`) = **14,0**; `nivel_origen = region` |
| U7 | 2011-09 (bbox `P1` + `P2`) | 5 × 3,0 + 5 × 4,0 = **35,0** |
| Mixto | 2012-01 | Obs 6 + est 3 × 3,0 = **15,0**; `frac_estimada` = 19/31; rango [10,14 ; 46,41]; confianza baja |
| U2 + U6 | 2022-07 | **12** observado (5 + 7); N21 = 4 no suma; mínimo = máximo = 12 |
| U3 | 2022-08 | Obs 8 + 4 = 12; est (2 + 2) × 3,0 = 12 → **24,0**; `frac_estimada` = 3/31; mixto; rango [17,52 ; 65,88]; confianza alta; el N20 del día 11 no se usa |
| U4 | 2026-11 | Obs 3 (S-NPP del 1) + 7 (N20 del 10) = **10**; el S-NPP del 10 no se usa; `parcial = true`; observado |

Los casos están anotados en `scripts/make_fixtures.py` (`CASOS`).

## 7. Entorno local

- Python 3.12 con `uv`: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]"`.
- Datos demo: `.venv/bin/python scripts/make_demo_data.py` → `data/demo/` (sintéticos, fuera del repo).
- Levantar: `DATA_DIR=data/demo CORS_ORIGINS=http://localhost:5173 RELOAD_TOKEN=dev .venv/bin/uvicorn app.main:app --workers 2`.
- La grilla de los scripts está rotada respecto de lon/lat (Albers): no asumir que las celdas de una fila tienen la misma longitud.
