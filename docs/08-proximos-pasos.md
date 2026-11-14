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
| `satelite_operativo` sin fila para un día | Ese día cuenta como **no operativo** | 04 (código) |

## 4. Revisión de F3–F7 (correcciones de este PR)

- **Anomalía:** el histórico incluía el mes en curso (incompleto); ahora se excluye.
- **Referencia VIIRS:** las fechas de S-NPP → NOAA-20 estaban fijas en el SQL; ahora salen de `metadata.json`.
- **Swagger:** las 13 operaciones de F3–F7 tenían solo `summary`; ahora tienen descripción, y los campos de respuesta también. `/mapa/*` declara su esquema GeoJSON.
- **CSV de focos:** `lat`/`lon` se redondean a 5 decimales y `frp_mw` a 2 (antes salía el ruido de los FLOAT de 32 bits).
- **Documentación:** errores `TOKEN_REQUERIDO` (401) y `TOKEN_INVALIDO` (403) en la tabla de 03.
- **Pruebas nuevas:** confianza (reglas y provincias "pocos datos"), C1 completo (respuestas y OpenAPI) y C7 en todos los endpoints de datos.

## 5. Pendientes

### Decisión del equipo

- **Confianza en provincias con pocos datos** (Tierra del Fuego `94`, Santa Cruz `78`, CABA `02`): hoy, si la zona tiene más del 50 % de su área en esas provincias, la confianza es `baja` **aunque el mes sea 100 % observado**. [04 §5](04-logica-de-armonizacion.md#5-confianza) no aclara qué pasa con los meses observados. Opciones: dejarlo así o que los meses con `frac_estimada ≤ 0,1` sean siempre `alta`.

### Fuera de este repo

- **Datos reales:** el pipeline [`ml_nasaspaceapp`](https://github.com/DenisPablo/ml_nasaspaceapp) tiene que publicar los Parquet con el formato de [02](02-contratos-de-datos.md), incluido `factores_region_mes.parquet` y `schema_version = "1.1.0"`.
- **Rendimiento (R1–R6) y validación científica (S1–S4)** de [06](06-pruebas-y-aceptacion.md): solo se miden con datos reales en el VPS.
- **Despliegue** ([05](05-despliegue.md)): preparar el VPS, configurar Dokploy, cargar el secreto `DOKPLOY_WEBHOOK_URL` (hoy el CI omite ese paso), definir `CORS_ORIGINS` y `RELOAD_TOKEN`, y decidir si la imagen de GHCR es pública.
- **Integración con el frontend** [`FireHistoryInterface`](https://github.com/smlopezsm/FireHistoryInterface).

### Mejoras menores (opcionales)

- Los CSV se arman en un archivo temporal y después se transmiten: la memoria queda acotada, pero el primer byte llega cuando termina la consulta.
- Al recargar, la conexión DuckDB anterior la cierra el recolector de Python cuando termina la última petición que la usa (no hay cierre explícito).

## 6. Entorno local

- Python 3.12 con `uv`: `uv venv --python 3.12 .venv && uv pip install -e ".[dev]"`.
- Datos demo: `.venv/bin/python scripts/make_demo_data.py` → `data/demo/` (sintéticos, fuera del repo).
- Levantar: `DATA_DIR=data/demo CORS_ORIGINS=http://localhost:5173 RELOAD_TOKEN=dev .venv/bin/uvicorn app.main:app --workers 2`.
- Los valores esperados de U1–U9 sobre los fixtures están anotados en `scripts/make_fixtures.py` (`CASOS`) y verificados en `tests/test_armonizacion.py`.
- La grilla de los scripts está rotada respecto de lon/lat (Albers): no asumir que las celdas de una fila tienen la misma longitud.
