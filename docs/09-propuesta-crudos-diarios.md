# 09 · Propuesta: endpoint dedicado diario para MODIS y VIIRS

> **Estado: propuesta, no implementada.** Ningún endpoint de este documento existe en la API. Si se aprueba, el contrato se agrega primero en [03](03-contratos-api.md).

Propuesta técnica e implementación planificada para incorporar una segunda vista de **frecuencia diaria con datos crudos observados** (`modis` y `viirs`) para comparación rápida, manteniendo intactas las vistas **mensuales y anuales armonizadas** (`/api/v1/serie` y `/api/v1/calendario`).

## Motivación y restricción estadística

La tabla base `conteos_celda_dia` y `satelite_operativo` ([`app/db.py`](../app/db.py)) ya tienen granularidad diaria. Sin embargo, los factores de armonización (`factores_provincia_mes`, `factores_region_mes`) y la tabla de incertidumbre (`rangos.parquet`) están calibrados sobre **totales mensuales por provincia** ([`04-logica-de-armonizacion.md`](04-logica-de-armonizacion.md)).

Aplicar el factor mensual sobre un día suelto con 0–2 focos introduce ruido por horarios de pasada y nubosidad, deja el rango del 80 % más ancho que el propio valor (así que la confianza nunca podría ser `media`, ver [04 §5](04-logica-de-armonizacion.md#5-confianza)) y vuelve binaria la fracción estimada. Por eso se separan las dos vistas:

| Vista | Granularidad | Contenido | Endpoint |
|---|---|---|---|
| **Histórica comparable** | Mensual / Anual | `modis`, `viirs`, `armonizado`, `minimo`, `maximo`, `estado`, `confianza` | `/api/v1/serie`, `/api/v1/calendario` |
| **Detalle diario crudo** | Diaria (tope 366 días) | `modis` y `viirs` observados (`null` si no hubo referencia operativa) | `/api/v1/crudos/diario` *(propuesto)* |

## Decisión de diseño

Crear un router y esquema propios para datos crudos diarios en lugar de mezclarlo con `/api/v1/serie`:

- **Endpoint:** `GET /api/v1/crudos/diario` y `POST /api/v1/crudos/diario` (registrado en `app/main.py` bajo `/api/v1`).
- **Por qué separado:** En [`app/schemas/armonizacion.py`](../app/schemas/armonizacion.py), `Punto` exige `armonizado`, `minimo`, `maximo`, `estado` y `confianza` como campos no nulos. Separar el contrato evita debilitar el esquema actual y deja explícita la frontera entre datos crudos y datos armonizados.
- **Límite de rango:** Tope de `366` días por consulta (configurable en `Settings`) para acotar el tamaño de respuesta y proteger a DuckDB.

## Plan de implementación

### 1. Configuración (`app/config.py`)
- Agregar `max_dias_crudos_diario: int = 366` en `Settings` para controlar el rango máximo permitido en consultas diarias.

### 2. Esquemas (`app/schemas/crudos.py`)
- Definir `PeriodoDiarioConsulta` con `desde: str | None` y `hasta: str | None` en formato `YYYY-MM-DD`.
- Definir `PedidoCrudosDiario(PedidoZona, PeriodoDiarioConsulta)` para `POST`.
- Definir `PuntoCrudoDiario`:
  - `fecha: date` (`YYYY-MM-DD`)
  - `modis: int` (`n_terra + n_aqua`)
  - `viirs: int | None` (conteo del satélite de referencia si `operativo = true`; `null` si no hubo referencia operativa ese día, respetando `null` ≠ `0`)
  - `referencia_viirs: Literal["SNPP", "N20"] | None` (trazabilidad del sensor VIIRS observado ese día)
- Definir `CrudosDiario`: `zona: Zona`, `desde: date`, `hasta: date`, `puntos: list[PuntoCrudoDiario]` y `data_version: str`.

### 3. Servicio de datos (`app/services/crudos.py`)
- Agregar `_limites_diarios(consulta, inicio, fin, max_dias)`:
  - Validar formato `YYYY-MM-DD` (responder `400 PERIODO_INVALIDO` si es inválido o `desde > hasta`).
  - Si no se envían fechas, tomar la ventana `[max(inicio, fin - (max_dias - 1)), fin]`.
  - Si `(hasta - desde).days + 1 > max_dias`, devolver `400` con mensaje claro indicando el límite.
- Agregar `calcular_crudos_diarios(datos, zona, inicio, fin)`:
  - Reutilizar `cobertura_sql(metadata.referencia_viirs)` de [`app/services/armonizacion.py`](../app/services/armonizacion.py) para generar todos los días del rango con su estado `operativo` y `referencia`.
  - Hacer `LEFT JOIN` contra `conteos_celda_dia` filtrado por `anio BETWEEN ...`, `fecha BETWEEN ...` y `cell_id IN (SELECT cell_id FROM zona_celdas)`.
  - Devolver por cada fecha `sum(n_terra + n_aqua)` como `modis` y `sum(n_snpp | n_n20)` si `operativo` (o `None` si `NOT operativo`) como `viirs`.

### 4. Router y registro (`app/routers/crudos.py` y `app/main.py`)
- Exponer `GET /crudos/diario` (zona por `provincia_id` o `bbox` vía `ZonaQueryDep` + `PeriodoDiarioConsulta` por query).
- Exponer `POST /crudos/diario` (zona incluyendo `geometria` vía `PedidoCrudosDiario`).
- Registrar `crudos.router` en `app/main.py` bajo `PREFIJO` (`/api/v1`).
- Aclarar en OpenAPI que devuelve **conteos crudos diarios de MODIS y VIIRS** (sin armonización) y que para series históricas comparables se debe usar `/api/v1/serie` o `/api/v1/calendario`.

### 5. Documentación (`docs/03-contratos-api.md`)
- Documentar `/api/v1/crudos/diario` (`GET` y `POST`), sus parámetros, el límite de días y el criterio de `viirs = null`.

### 6. Pruebas (`tests/test_crudos.py` y `tests/test_contrato.py`)
- **Casos en `tests/test_crudos.py`:**
  - Días con VIIRS operativo devuelven `modis` y `viirs` enteros (incluyendo días sin focos como `0`, no omitidos).
  - Días sin VIIRS operativo (antes de `2012-01-20` o satélite caído) devuelven `viirs = null` y `modis` entero.
  - Consulta por `provincia_id`, `bbox` y `geometria` (`POST`).
  - Rango inválido (`desde > hasta`, formato erróneo) y rango que supera `max_dias_crudos_diario`.
- **Casos en `tests/test_contrato.py`:**
  - Verificar que `/openapi.json` expone `/api/v1/crudos/diario` (`GET` y `POST`) y que no se modificó el contrato de `/api/v1/serie` ni `/api/v1/calendario`.

## Verificación final

```bash
ruff check . && ruff format --check . && mypy app && pytest -q
```
