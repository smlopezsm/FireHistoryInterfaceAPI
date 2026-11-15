# 08 · Estado actual y próximos pasos

Documento de traspaso para retomar el backend. Estado al **2026-11-14**.

## 1. Qué está hecho (en `main`)

| Feature | PR | Qué quedó |
|---|---|---|
| F1 · Esqueleto | #2 | FastAPI, configuración por entorno, DuckDB de solo lectura por worker, `/health`, `/metadata`, errores, CORS, ETag, Dockerfile (141 MB), CI |
| Docs · factores de respaldo | #3 | `factores_region_mes.parquet` en [02 §5.1](02-contratos-de-datos.md) |
| F2 · Zonas | #4 → #5 | `/provincias`, resolución de zona (provincia, bbox, polígono), límite de 256 KB en los POST |
| Docs · traspaso | #6 | Decisiones de F3–F7, este documento y `CLAUDE.md` |
| F3 · Calendario y serie | #7 | `/calendario` y `/serie` con el algoritmo de [04](04-logica-de-armonizacion.md) |
| F4 · Anomalía | #8 | `/anomalia` |
| F5 · Mapa | #9 | `/mapa/celdas` y `/mapa/industriales` |
| F6 · Descargas | #10 | `focos.csv` y `calendario.csv` |
| F7 · Recarga | #11 | `POST /admin/reload` y detección automática del cambio de `current` |
| Revisión F3–F7 | este PR | Correcciones de la revisión (ver §4) |

**Los 11 endpoints de [03](03-contratos-api.md) existen.** U1–U10 y C1–C7 tienen pruebas y pasan en CI.

## 2. Reglas de trabajo

- **Una feature por vez.** Cada rama sale de `main` actualizado y **cada PR va contra `main`**. No apilar PR.
- Antes de cada PR: `ruff check . && ruff format --check . && mypy app && pytest -q`. El build de Docker lo valida el CI.
- Nada de dependencias de ML. `null` nunca es 0. Mensajes, claves y descripciones de Swagger en español.
- Si algo no está en `docs/`, preguntar antes de inventar.

## 3. Decisiones tomadas

| Tema | Decisión | Dónde |
|---|---|---|
| `capa` (`modis`, `viirs`) | Cada mes trae siempre todos los campos; la capa solo cambia `unidad` y `resumen` | 03 |
| Mes en curso | `frac_estimada` sobre los días con datos (hasta `fecha_max`); no entra en el histórico de anomalía | 03, 04 |
| Meses con dos factores (julio de 2002) | Cada suma de MODIS con su factor (`terra` o `modis`) | 04 |
| Referencia VIIRS | Fechas leídas de `metadata.referencia_viirs` (solo `SNPP` o `N20`) | 04 |
| Recarga con 2 workers | `POST /admin/reload` reabre el worker que lo recibe; cada worker revisa `current` cada 5 s | 01, 03 |
| Zona por provincia | Celdas de `dim_celdas` con ese `provincia_id` | 03 |
| Body > 256 KB | 413 `CUERPO_DEMASIADO_GRANDE` | 03 |
| Confianza en provincias con "pocos datos" | Los meses con `frac_estimada ≤ 0,1` son `alta` en cualquier zona; "pocos datos" solo baja lo estimado | 04 §5 |
| Datos de producción | Versión del pipeline copiada en `data/current/` y empaquetada en la imagen (sin volumen en el VPS) | 05 |
| `satelite_operativo` sin fila para un día | Ese día cuenta como **no operativo** | 04 (código) |

## 4. Revisión de F3–F7 (correcciones de este PR)

- **Anomalía:** el histórico incluía el mes en curso (incompleto); ahora se excluye.
- **Referencia VIIRS:** las fechas de S-NPP → NOAA-20 estaban fijas en el SQL; ahora salen de `metadata.json`.
- **Swagger:** las 13 operaciones de F3–F7 tenían solo `summary`; ahora tienen descripción, y los campos de respuesta también. `/mapa/*` declara su esquema GeoJSON.
- **CSV de focos:** `lat`/`lon` se redondean a 5 decimales y `frp_mw` a 2 (antes salía el ruido de los FLOAT de 32 bits).
- **Documentación:** errores `TOKEN_REQUERIDO` (401) y `TOKEN_INVALIDO` (403) en la tabla de 03.
- **Confianza:** los meses observados ya no quedan en `baja` por estar en provincias con "pocos datos".
- **Rendimiento:** las celdas de la zona viajan a DuckDB como tabla Arrow registrada en el cursor (`zona_celdas`) y no como lista parametrizada. Con los datos reales del pipeline (versión `20261114T171326`, medido en una Mac): calendario de Argentina de 8,0 s a 0,3 s; de una provincia, de 285 a 97 ms; `focos.csv` de un año, de 540 a 76 ms.
- **Pruebas nuevas:** confianza (reglas y provincias "pocos datos"), C1 completo (respuestas y OpenAPI) y C7 en todos los endpoints de datos.

## 5. Pendientes

### Fuera de este repo

- **Datos reales:** el pipeline [`ML_NasaSpaceApp`](https://github.com/DenisPablo/ML_NasaSpaceApp) ya publica la versión `20261114T171326`, que cumple el contrato (esquemas, conteos, factor nacional 3,33). Falta una versión nueva con `fecha_min = 2000-11-01` y `schema_version = 1.1.0` (corrección en la rama `fix/fecha-min-y-schema-version` del pipeline). El contrato ya acepta factores `terra` de hasta 40 y `provincia_id` nulo en `puntos_industriales`.
- **Rendimiento (R1–R6) y validación científica (S1–S4)** de [06](06-pruebas-y-aceptacion.md): solo se miden con datos reales en el VPS.
- **Despliegue** ([05](05-despliegue.md)): preparar el VPS, configurar Dokploy, cargar el secreto `DOKPLOY_WEBHOOK_URL` (hoy el CI omite ese paso), definir `CORS_ORIGINS` y `RELOAD_TOKEN`, y decidir si la imagen de GHCR es pública.
- **Integración con el frontend** [`FireHistoryInterface`](https://github.com/smlopezsm/FireHistoryInterface).

### Mejoras menores (opcionales)

- Los CSV se arman en un archivo temporal y después se transmiten: la memoria queda acotada, pero el primer byte llega cuando termina la consulta.
- Al recargar, la conexión DuckDB anterior la cierra el recolector de Python cuando termina la última petición que la usa (no hay cierre explícito).

### Advertencia sobre rutas síncronas y saturación del threadpool

- **Por qué las rutas con DuckDB son `def` (síncronas):** las consultas DuckDB, el semáforo `threading.BoundedSemaphore` (`max_consultas_concurrentes = 4`), el lock de recarga y la escritura de CSV temporales son bloqueantes. Definir esos endpoints como `def` hace que FastAPI/AnyIO los ejecute en el *worker threadpool* (40 hilos por defecto) sin bloquear el *event loop* de `asyncio`.
- **Riesgo de saturación para monitoreo y endpoints sin I/O:** si ráfagas de consultas lentas ocupan todos los hilos del pool (hasta `query_timeout_s = 10` s esperando el semáforo o ejecutando), cualquier ruta ligera declarada como `def` —o que dependa de `Depends()` síncronos— queda en cola detrás de ellas y puede hacer fallar el `HEALTHCHECK` de Docker (`--timeout=5s`, `timeout=4` s).
- **Regla de mantenimiento:** los endpoints que solo leen estado en memoria (`GET /api/v1/health`, `GET /api/v1/metadata`) y sus dependencias compartidas (`obtener_datos`, `datos_listos`) deben mantenerse como `async def` para responder directo en el *event loop*, preservando la fijación de versión por `ContextVar` en `CacheMiddleware`.

## 6. Entorno local

- Python 3.12 con `uv`: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]"`.
- Datos demo: `.venv/bin/python scripts/make_demo_data.py` → `data/demo/` (sintéticos, fuera del repo).
- Levantar: `DATA_DIR=data/demo CORS_ORIGINS=http://localhost:5173 RELOAD_TOKEN=dev .venv/bin/uvicorn app.main:app --workers 2`.
- Los valores esperados de U1–U9 sobre los fixtures están anotados en `scripts/make_fixtures.py` (`CASOS`) y verificados en `tests/test_armonizacion.py`.
- La grilla de los scripts está rotada respecto de lon/lat (Albers): no asumir que las celdas de una fila tienen la misma longitud.
