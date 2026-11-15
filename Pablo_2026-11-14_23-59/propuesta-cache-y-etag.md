# Propuesta de cambio mínimo: caché de tablas estáticas y `ETag`

Propuesta técnica para resolver los puntos 2 y 3 del análisis de deuda técnica en la rama `Fix/Cache-DenisPablo`, minimizando la superficie de cambio y manteniendo intactos los contratos de dominio y la arquitectura de solo lectura.

## Resumen ejecutivo

| Ítem | Problema actual | Cambio propuesto | Archivos afectados | Impacto |
|---|---|---|---|---|
| **Punto 2** · Caché de `factores` y `rangos` | Cada llamada a `calcular_meses()` adquiere el semáforo `_cupos` 3 veces extra para leer tablas inmutables (`app/services/armonizacion.py:214-215`). | Precargar ambas tablas en `VersionDatos` al abrir DuckDB (`Datos._conectar()`). | `app/db.py`, `app/services/armonizacion.py`, tests | Reduce de **4 a 1** las adquisiciones de `_cupos` por petición en `/calendario`, `/serie`, `/anomalia` y `/descargas/calendario.csv`. |
| **Punto 3** · `ETag` con clave de ruta y query | `CacheMiddleware` emite `ETag = "{data_version}"` global para todos los `GET` (`app/cache.py:34-37`). | Incluir ruta y query string canonizados en el `ETag` (con opción alternativa sin cambio de contrato). | `app/cache.py`, `docs/03-contratos-api.md`, `tests/test_health_metadata.py` | Evita `304` falsos entre endpoints/filtros distintos y evita enmascarar respuestas `4xx` manteniendo el cortocircuito previo a DuckDB. |

### Fuera de alcance (explícito)

- **Punto 1 (`async def` en `/health` y `/metadata`)**: excluido por definición del alcance solicitado.
- **Punto 4 (streaming CSV sin archivo temporal)**, **Punto 6 (cierre explícito de DuckDB al recargar)** y **detección *in-place* en `revisar_version`**: fuera de esta rama.
- **`app/services/mapa.py`**: `CELDAS_SQL` (`app/services/mapa.py:38-42`) une `factores_provincia_mes` y `factores_region_mes` dentro de una única consulta SQL en DuckDB; no realiza lecturas separadas, por lo que no se modifica.

---

## Ruta rápida de implementación

1. Precargar `factores_provincias`, `factores_regiones` y `rangos` como estructuras inmutables dentro de `VersionDatos` en `app/db.py`.
2. Adaptar `Factores` y `calcular_meses()` en `app/services/armonizacion.py` para leer desde `datos.version` (o fallback si fuera necesario en pruebas unitarias).
3. Actualizar `CacheMiddleware` en `app/cache.py` para incluir ruta + query en el `ETag` (o mover la validación de `If-None-Match` si se opta por no tocar el formato del header).
4. Actualizar/agregar pruebas y verificar con `ruff check . && ruff format --check . && mypy app && pytest -q`.

---

## Diseño técnico

### 1. Caché en memoria de `Factores` y `rangos` en `VersionDatos`

#### Situación actual
En `app/services/armonizacion.py:202-231`, cada ejecución de `calcular_meses()` realiza 4 llamadas a `datos.consultar()`:
1. La consulta agregada sobre `conteos_celda_dia` (`armonizacion.py:209-213`).
2. `SELECT * FROM factores_provincia_mes` dentro de `Factores.__init__` (`armonizacion.py:153`).
3. `SELECT * FROM factores_region_mes` dentro de `Factores.__init__` (`armonizacion.py:157`).
4. `SELECT * FROM rangos` (`armonizacion.py:215`).

Cada llamada entra por `Datos._ejecutar()` (`app/db.py:233-263`), adquiriendo `self._cupos` (`BoundedSemaphore(4)`), creando un cursor DuckDB, iniciando un `threading.Timer` y reconstruyendo los diccionarios en Python. Sin embargo, esas tres tablas pertenecen al mismo paquete de datos que `VersionDatos` y nunca cambian hasta una recarga.

#### Cambio mínimo propuesto

1. **En `app/db.py`**:
   - Agregar un tipo inmutable ligero (o tuplas/diccionarios de solo lectura) a `VersionDatos` (`app/db.py:52-59`), por ejemplo `factores_provincia`, `factores_region` y `rangos` (como `tuple` de filas o mapas ya indexados).
   - Poblarlos una sola vez dentro de `Datos._conectar()` (`app/db.py:138-174`), reutilizando la conexión `con` recién abierta antes de `SET lock_configuration = true` (sin consumir `_cupos` ni crear cursores en tiempo de petición).
   - Exponer propiedades en `Datos` (ej. `factores_provincia`, `factores_region`, `rangos` o un objeto de solo lectura) leyendo siempre desde `self._version`, de modo que la fijación por `ContextVar` (`fijar_version()` en `app/db.py:75-81`) garantice consistencia de snapshot ante una eventual recarga.

2. **En `app/services/armonizacion.py`**:
   - Permitir que `Factores` se inicialice desde los diccionarios ya cargados (o mediante un constructor `@classmethod def desde_tablas(...)`), evitando las dos consultas SQL de `Factores.__init__`.
   - En `calcular_meses()` (`armonizacion.py:214-215`), leer `factores` y `rangos` directamente desde `datos` sin invocar `datos.consultar()`. Si `datos` no tiene versión cargada, lanzar `datos_no_disponibles()` (comportamiento ya existente en la línea 207).
   - **No modificar** `_sumar_provincia()`, `Factores.obtener()`, `Acumulado` ni el esquema de salida.

#### Riesgos y verificación
- **Aislamiento de versiones**: al vivir dentro de `VersionDatos`, cualquier petición en curso que haya entrado por `CacheMiddleware` sigue viendo los factores correspondientes a su `data_version`.
- **Memoria**: `factores_provincia_mes` (~24 provincias × 12 meses × 2 tipos ≈ 576 filas), `factores_region_mes` y `rangos` ocupan pocos kilobytes en RAM.

---

### 2. Corrección de `ETag` en `CacheMiddleware`

#### Hallazgo relevante en contratos y pruebas
Antes de modificar `app/cache.py:34-37`, debe considerarse que el contrato actual define explícitamente `ETag = data_version`:
- `docs/03-contratos-api.md:16`: ``Caché | `Cache-Control: public, max-age=3600` y `ETag = data_version` ``
- `tests/test_health_metadata.py:70`: `assert r.headers["etag"] == f'"{VERSION}"'`
- `tests/test_recarga.py:35-60`: valida que `ETag` cambie tras una recarga de `data_version` y responda `200` al enviar el `ETag` viejo en `If-None-Match`.

Por ello se presentan dos opciones mínimas con su respectivo tradeoff:

| Opción | Implementación | Ventaja | Tradeoff / Impacto |
|---|---|---|---|
| **Opción A (Recomendada)** · `ETag` con clave de ruta + query | Calcular `clave = sha256(f"{request.url.path}?{urlencode(sorted(request.query_params.multi_items()))}".encode()).hexdigest()[:12]` y emitir `etag = f'"{version}-{clave}"'`. | Elimina colisiones entre rutas/filtros distintos, evita `304` sobre `4xx` (porque solo las respuestas `200` emiten ese `ETag`) y **conserva el cortocircuito antes de DuckDB**. | Requiere actualizar 1 aserción en `tests/test_health_metadata.py:70` y 1 línea en `docs/03-contratos-api.md:16`. |
| **Opción B** · Mantener `ETag = "{data_version}"` | Conservar `etag = f'"{version}"'`, pero evaluar `If-None-Match` **después** de `await call_next(request)` y solo cuando `respuesta.status_code == 200`. | Cero cambios en `docs/03-contratos-api.md:16` ni en `tests/test_health_metadata.py:70`. Evita devolver `304` en respuestas `4xx`. | **No evita** ejecutar la consulta en DuckDB en peticiones `304`, y mantiene el mismo `ETag` entre rutas distintas. |

#### Recomendación
Adoptar la **Opción A**: con ~6 líneas en `app/cache.py`, mantiene el ahorro de DuckDB en revalidaciones HTTP, impide que un `If-None-Match` obtenido en `/metadata` produzca `304` en otro endpoint o en una consulta inválida (`400`/`404`/`422`), y conserva la propiedad deseada de invalidación automática al cambiar `data_version`.

> **Nota de ordenamiento de query params**: ordenar `request.query_params.multi_items()` garantiza que `?provincia_id=06&desde=2020-01` y `?desde=2020-01&provincia_id=06` compartan el mismo `ETag`.

---

## Plan de pruebas y criterios de aceptación

- [ ] **Caché de factores y rangos**:
  - Todos los casos existentes de `tests/test_armonizacion.py` (U1–U9), `tests/test_anomalia.py` y `tests/test_descargas.py` pasan sin cambios en los valores calculados.
  - Nueva prueba unitaria en `tests/test_db.py` (o `tests/test_armonizacion.py`) verificando que `calcular_meses()` realiza exactamente **1** llamada a `datos.consultar()` (o usa los datos cacheados en `VersionDatos` sin abrir cursores extra).
- [ ] **ETag (Opción A)**:
  - `GET /api/v1/metadata` con su propio `ETag` en `If-None-Match` sigue devolviendo `304` y cuerpo vacío.
  - Enviar el `ETag` de `/api/v1/metadata` hacia otro endpoint (ej. `GET /api/v1/provincias` o `GET /api/v1/calendario?provincia_id=P1`) devuelve `200`, no `304`.
  - Enviar un `ETag` válido hacia una ruta con error `400`/`404`/`422` devuelve el error correspondiente, no `304`.
  - `tests/test_recarga.py` sigue pasando al cambiar `data_version`.
- [ ] **Calidad y tipado**:
  - `ruff check .`
  - `ruff format --check .`
  - `mypy app`
  - `pytest -q`

## Siguiente paso

Confirmar si se adopta la **Opción A** (actualizando `docs/03-contratos-api.md:16` y `tests/test_health_metadata.py:70`) o la **Opción B** para `ETag`, y proceder con la implementación en esta misma rama `Fix/Cache-DenisPablo`.
