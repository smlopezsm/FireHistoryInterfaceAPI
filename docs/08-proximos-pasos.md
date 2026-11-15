# 08 · Estado actual y próximos pasos

Documento de traspaso para retomar el backend. Estado al **2026-11-15**.

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
| Revisión F3–F7 | #12 | Correcciones de la revisión (ver §4) |
| Datos en la imagen | #14 | Versión del pipeline en `data/current/`, copiada dentro de la imagen |
| Veredicto · docs | #15 | Rangos publicados y validación científica en docs/02 y docs/04 §8 |
| Caché | #16 | `ETag` por ruta y query canonizados |
| Zona por región | #17 | Parámetro `region` en las zonas y en `/provincias` |
| `.gitignore` | #18 | Ignora `ModeloPredictivo/` |
| Health asincrónico | #19 | `/health` y `/metadata` sin pasar por el threadpool |
| Confianza H9/H13 | #20 | `dias_sin_modis` y factores no provinciales |
| Anomalía y confianza H1/H15 | #21 | Anomalía por era (`referencia`) y `media` por ancho del rango |

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

- **Datos reales:** `data/current/` tiene la versión `20261114T174945` del pipeline [`ML_NasaSpaceApp`](https://github.com/DenisPablo/ML_NasaSpaceApp) (`schema_version 1.1.0`, desde `2000-11-01`). Pendiente en el pipeline: los huecos de NRT de agosto y octubre de 2026 y las geometrías provinciales inválidas (14 de 24).
- **Rendimiento (R1–R6) y validación científica (S1–S4)** de [06](06-pruebas-y-aceptacion.md): solo se miden con datos reales en el VPS.
- **Veredicto científico de la armonización:** [informe y scripts](https://github.com/DenisPablo/ML_NasaSpaceApp/blob/main/analisis/veredicto-armonizacion/README.md) en el pipeline ("sólido con reservas"). Lo que le toca a la API está resumido en [04 §8](04-logica-de-armonizacion.md#8-validación-científica-y-limitaciones-conocidas). Lo que le toca al pipeline: rangos validados hacia adelante y por provincia, rangos para Terra sola, una definición relativa de "día operativo" y cerrar la ventana de calibración `modis` antes de la deriva orbital (2022+).
- **Despliegue** ([05](05-despliegue.md)): la imagen de GHCR es pública y la API responde en el VPS. Falta: en Dokploy, el dominio del backend con ruta `/api` (puerto 8000, sin quitar el prefijo); definir `CORS_ORIGINS` con el dominio del frontend; cerrar el puerto 9000 expuesto; y cargar el secreto `DOKPLOY_WEBHOOK_URL` (hoy el CI omite ese paso).
- **Integración con el frontend** [`FireHistoryInterface`](https://github.com/smlopezsm/FireHistoryInterface).

### Mejoras menores (opcionales)

- Los CSV se arman en un archivo temporal y después se transmiten: la memoria queda acotada, pero el primer byte llega cuando termina la consulta.
- Al recargar, la conexión DuckDB anterior la cierra el recolector de Python cuando termina la última petición que la usa (no hay cierre explícito).

### Advertencia sobre rutas síncronas y saturación del threadpool

- **Por qué las rutas con DuckDB son `def` (síncronas):** las consultas DuckDB, el semáforo `threading.BoundedSemaphore` (`max_consultas_concurrentes = 4`), el lock de recarga y la escritura de CSV temporales son bloqueantes. Definir esos endpoints como `def` hace que FastAPI/AnyIO los ejecute en el *worker threadpool* (40 hilos por defecto) sin bloquear el *event loop* de `asyncio`.
- **Riesgo de saturación para monitoreo y endpoints sin I/O:** si ráfagas de consultas lentas ocupan todos los hilos del pool (hasta `query_timeout_s = 10` s esperando el semáforo o ejecutando), cualquier ruta ligera declarada como `def` —o que dependa de `Depends()` síncronos— queda en cola detrás de ellas y puede hacer fallar el `HEALTHCHECK` de Docker (`--timeout=5s`, `timeout=4` s).
- **Regla de mantenimiento:** los endpoints que solo leen estado en memoria (`GET /api/v1/health`, `GET /api/v1/metadata`) y sus dependencias compartidas (`obtener_datos`, `datos_listos`) deben mantenerse como `async def` para responder directo en el *event loop*, preservando la fijación de versión por `ContextVar` en `CacheMiddleware`.

## 6. Entorno local

- Instalación, datos demo y cómo levantar la API: [README §Inicio rápido](../README.md#inicio-rápido-local).
- Los valores esperados de U1–U9 sobre los fixtures están anotados en `scripts/make_fixtures.py` (`CASOS`) y verificados en `tests/test_armonizacion.py`.
- La grilla de los scripts está rotada respecto de lon/lat (Albers): no asumir que las celdas de una fila tienen la misma longitud.
