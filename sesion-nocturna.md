# Registro de cambios de la sesión nocturna (2026-11-14 / 2026-11-15)

Resumen técnico de todas las modificaciones realizadas sobre `fireHistoryInterfaceAPI`, agrupadas por rama e intención, junto con su justificación y alcance de verificación.

---

## 1. Corrección de colisiones de caché HTTP (`ETag`)

- **Rama:** `Fix/Cache-DenisPablo`
- **Commit:** `1ab816d` (`fix(cache): scope ETag by route and sorted query params`)
- **Alcance:** 3 archivos (`+47 / -11` líneas)

### Cambios realizados
- [`app/cache.py`](app/cache.py):
  - Se reemplazó el `ETag` único `"{data_version}"` por la función `_etag(version, request)`, que calcula `"{version}-{sha256[:12]}"` sobre `request.url.path` y `urlencode(sorted(request.query_params.multi_items()))`.
  - Se simplificó el retorno anticipado en `_con_version` para rutas excluidas (`SIN_CACHE`, métodos distintos de `GET`/`HEAD` o sin versión).
- [`docs/03-contratos-api.md`](docs/03-contratos-api.md):
  - Se actualizó la regla de caché en la tabla de convenciones para reflejar que el `ETag` combina versión, ruta y parámetros de consulta.
- [`tests/test_health_metadata.py`](tests/test_health_metadata.py):
  - Se incorporaron pruebas unitarias/HTTP que validan `ETag` distintos para rutas diferentes y query parameters en distinto orden (`?a=1&b=2` vs `?b=2&a=1` produciendo el mismo hash).

### Justificación técnica
Antes del cambio, todas las respuestas cacheables devolvían el mismo `ETag = data_version`. Si un cliente o caché intermedio revalidaba con `If-None-Match` entre rutas distintas o distintos filtros dentro de la misma versión de datos, el servidor podía devolver `304 Not Modified` para un recurso distinto al solicitado. Incluir la ruta y los parámetros de consulta canonizados (ordenados de forma determinista) dentro del hash mantiene la invalidación automática por `data_version` sin recalcular consultas DuckDB ni serializar el cuerpo antes de responder `304`.

---

## 2. Soporte nativo de filtro por región (`region`)

- **Rama:** `feat/filtro-region-denis-pablo`
- **Commit:** `3626d85` (`feat(zonas): add region filter across zone-based endpoints`)
- **Alcance:** 10 archivos (`+156 / -35` líneas)

### Cambios realizados
- [`app/schemas/zonas.py`](app/schemas/zonas.py):
  - Se añadió `DESC_REGION`, el campo opcional `region` en `PedidoZona` y el literal `"region"` en `Zona.tipo` (actualizando la descripción de `Zona.id`).
- [`app/deps.py`](app/deps.py):
  - Se expuso el parámetro de consulta `region` en `zona_desde_query`.
- [`app/services/zonas.py`](app/services/zonas.py):
  - Se extrajo el helper compartido `_por_grupo` para unificar la resolución de `provincia_id` (`_por_provincia`) y `region` (`_por_region`), calculando el `bbox` envolvente a partir de las provincias pertenecientes en `dim_provincias` y obteniendo las celdas asignadas desde `dim_celdas`.
  - Se incorporó el error `404 REGION_NO_ENCONTRADA` y se actualizó el mensaje por defecto de `400 ZONA_INVALIDA`.
  - Se actualizó `resolver_zona` para exigir exactamente una zona entre `provincia_id`, `region`, `bbox` o `geometria`.
- [`app/routers/provincias.py`](app/routers/provincias.py):
  - Se agregó el filtro opcional `?region=` en `GET /api/v1/provincias` usando consulta parametrizada.
- [`app/routers/descargas.py`](app/routers/descargas.py):
  - Se extendió `_nombre()` para sanear el identificador de archivo descargable cuando `zona.tipo in ("provincia", "region")`.
- [`app/main.py`](app/main.py):
  - Se actualizó la descripción del tag OpenAPI `zonas`.
- [`docs/03-contratos-api.md`](docs/03-contratos-api.md):
  - Se documentaron `region`, `REGION_NO_ENCONTRADA` y los mensajes de `ZONA_INVALIDA`.
- [`tests/test_zonas.py`](tests/test_zonas.py), [`tests/test_provincias.py`](tests/test_provincias.py) y [`tests/test_armonizacion.py`](tests/test_armonizacion.py):
  - Se añadieron pruebas unitarias e integración HTTP para el filtrado por región, errores `400`/`404`, filtrado en `/provincias` y nombres de descarga.

### Justificación técnica
Los Parquet (`dim_provincias` y `dim_celdas`) ya contenían la columna `region` (`NOA`, `NEA`, `Pampeana`, `Cuyo`, `Patagonia`). Delegar la selección de regiones al frontend enviando geometrías combinadas hubiera estado limitado por el tope de 2.000 vértices, habría cambiado el criterio de inclusión a centroide en lugar de asignación oficial por fracción de área, y no habría funcionado en endpoints `GET`. Centralizar `region` en `PedidoZona` y `resolver_zona` hace que todos los endpoints de zona (`/calendario`, `/serie`, `/anomalia`, `/descargas/focos.csv`, `/descargas/calendario.csv`) hereden el filtro sin duplicar lógica y aplicando los factores provinciales correctos antes de agregar.

---

## 3. Desacoplamiento asíncrono de monitoreo y documentación de concurrencia

- **Rama:** `Fix/async-health-metadata-denis-pablo`
- **Commit:** `dde4697` (`fix(api): make health and metadata endpoints async to avoid threadpool starvation`)
- **Alcance:** 5 archivos (`+46 / -4` líneas)

### Cambios realizados
- [`app/deps.py`](app/deps.py):
  - Se convirtieron `obtener_datos` y `datos_listos` a `async def`.
- [`app/routers/health.py`](app/routers/health.py) y [`app/routers/metadata.py`](app/routers/metadata.py):
  - Se convirtieron los handlers `health` y `metadata` de `def` a `async def`.
- [`docs/08-proximos-pasos.md`](docs/08-proximos-pasos.md):
  - Se agregó la sección *Advertencia sobre rutas síncronas y saturación del threadpool*.
- [`tests/test_health_metadata.py`](tests/test_health_metadata.py):
  - Se agregó `test_health_y_metadata_son_async_sin_threadpool`, que verifica `inspect.iscoroutinefunction` sobre los handlers y dependencias, y comprueba en runtime que `GET /api/v1/health` y `GET /api/v1/metadata` responden sin invocar `anyio.to_thread.run_sync`.

### Justificación técnica
- **Por qué las rutas de DuckDB permanecen síncronas (`def`):** las consultas sobre DuckDB, la adquisición del semáforo `threading.BoundedSemaphore` (`max_consultas_concurrentes = 4`), los locks de recarga y la escritura de CSV temporales son bloqueantes. Mantenerlas como `def` hace que FastAPI/AnyIO las ejecute en el *worker threadpool* (40 hilos por defecto) sin bloquear el *event loop* de `asyncio`.
- **Por qué `/health` y `/metadata` debían ser `async def`:** estos endpoints y sus dependencias `obtener_datos`/`datos_listos` solo leen referencias en memoria (fijadas por `ContextVar` desde `CacheMiddleware`). Mientras usaban `def`, FastAPI las enviaba al mismo *threadpool*; bajo ráfagas de consultas lentas (`query_timeout_s = 10` s), el agotamiento de hilos podía hacer vencer el `HEALTHCHECK` de Docker (`--timeout=5s`, `timeout=4` s). Al pasar tanto las rutas como sus dependencias a `async def`, ejecutan directamente en el *event loop* sin afectar la compatibilidad con los routers síncronos.

---

## 4. Exclusión en `.gitignore` y limpieza de `ModeloPredictivo/`

- **Rama:** `chore/gitignore-modelo-denis-pablo`
- **Commit:** `178ae61` (`chore: ignore local ModeloPredictivo directory`)
- **Alcance:** 1 archivo (`.gitignore`, `+3` líneas)

### Cambios realizados
- [`.gitignore`](.gitignore):
  - Se añadió la regla `ModeloPredictivo/` para impedir que la carpeta local del proyecto de predicción se incluya en commits de `fireHistoryInterfaceAPI`.
- **Limpieza local en `ModeloPredictivo/`:**
  - Se eliminaron ~394 MB de artefactos ignorados por su propio `.gitignore` y sin uso vigente:
    - `.venv/` (~393,5 MB): entorno virtual de Python 3.15 creado originalmente en otra ruta (`C:\Users\Denis\Documents\codigo\ModeloPredictivo\.venv`), regenerable desde `requirements.txt`.
    - `data/weather/openmeteo_argentina.parquet`: archivo legado de Open-Meteo descartado tras migrar a NASA POWER MERRA-2.
    - `.pytest_cache/`, `__pycache__/` (incluido el bytecode huérfano `ingest_openmeteo.cpython-315.pyc`) y `tests/__pycache__/`.
  - Se conservaron intactos todos los archivos trackeados por el repositorio Git interno de `ModeloPredictivo/`.

### Justificación técnica
La API productiva en este repositorio no carga librerías ni pesos de *machine learning* (contenedor acotado a 1,5 GB de RAM en Dokploy). Mantener `ModeloPredictivo/` excluido en `.gitignore` y limpio de cachés y entornos virtuales rotos evita contaminar los PRs del backend y reduce el espacio ocupado en disco sin perder código ni datos reproducibles.

---

## 5. Documentos de análisis y propuestas (sin commitear en ramas)

Archivos generados en el espacio de trabajo fuera de las ramas de PR:
- [`Pablo_2026-11-14_23-59/propuesta-cache-y-etag.md`](Pablo_2026-11-14_23-59/propuesta-cache-y-etag.md): análisis comparativo de opciones de `ETag` (Opción A elegida vs variante débil o cambio de contrato).
- [`docs/09-propuesta-crudos-diarios.md`](docs/09-propuesta-crudos-diarios.md): evaluación sobre el consumo actual de datos MODIS/VIIRS por separado frente a eventuales nuevos endpoints de serie diaria o focos paginados en JSON.

---

## 6. Estado de verificación

- **Entorno local configurado:** Python `3.12.10` en `.venv/` con dependencias de `.[dev]` instaladas.
- **`Fix/Cache-DenisPablo` (`1ab816d`):** `ruff check .`, `ruff format --check .` (62 archivos) y `mypy app/cache.py` sin errores; `pytest -q` obtuvo `163 passed, 2 failed` (los 2 fallos corresponden exclusivamente a `tests/test_recarga.py` en Windows por permisos de `os.symlink`, `WinError 1314`).
- **`feat/filtro-region-denis-pablo` (`3626d85`):** `ruff check app tests scripts`, `ruff format --check app tests scripts` (50 archivos) y `mypy` sobre los módulos modificados (`app/schemas/zonas.py`, `app/deps.py`, `app/services/zonas.py`, `app/routers/provincias.py`, `app/main.py`) sin errores; `pytest -q tests --ignore=tests/test_recarga.py` obtuvo `167 passed`.
- **`Fix/async-health-metadata-denis-pablo` (`dde4697`):** `ruff check app tests scripts`, `ruff format --check app tests scripts` (50 archivos) y `mypy app/routers/health.py app/routers/metadata.py app/deps.py` sin errores; `pytest -q tests --ignore=tests/test_recarga.py` obtuvo `162 passed`.
- **`chore/gitignore-modelo-denis-pablo` (`178ae61`):** validado con `git status -s` confirmando que `ModeloPredictivo/` dejó de figurar como carpeta sin seguimiento.
