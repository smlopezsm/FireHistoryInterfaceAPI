# 03 · Contratos de la API

**Base:** `/api/v1` · **Formato:** JSON (UTF-8), salvo las descargas CSV · **Documentación interactiva:** `/docs` (Swagger) y `/openapi.json`

## Convenciones

| Tema | Regla |
|---|---|
| Fechas | `YYYY-MM-DD` (día) o `YYYY-MM` (mes), en hora local de Argentina |
| Zona de consulta | **Una sola** de: `provincia_id`, `bbox` o un polígono GeoJSON (solo en `POST`) |
| `bbox` | `oeste,sur,este,norte` en EPSG:4326, por ejemplo `-67.4,-36.0,-64.9,-31.8` |
| Polígono | GeoJSON `Polygon` o `MultiPolygon` en EPSG:4326, hasta 2.000 vértices |
| Celdas de una zona | Con `bbox` o polígono, entran las celdas cuyo **centroide** cae dentro de la zona. Con `provincia_id`, las celdas que `dim_celdas` asigna a esa provincia (mayor fracción de área), igual que en `conteos_celda_dia` |
| Números | Conteos como enteros; armonizados con 1 decimal |
| Nulos | `null` significa "**no hay dato**" (por ejemplo VIIRS antes de 2012), **nunca** cero |
| Caché | `Cache-Control: public, max-age=3600` y `ETag = "<data_version>-<hash>"` (incluye ruta y query canonizados) |
| CORS | Solo el dominio del frontend (variable `CORS_ORIGINS`) |
| Idioma | Claves de los campos en español, sin tildes |

## Resumen de endpoints

| Método | Ruta | Para qué | Usado por |
|---|---|---|---|
| GET | `/health` | Estado del servicio y de los datos | Dokploy, monitoreo |
| GET | `/metadata` | Versiones, rango de fechas y referencias | Frontend (pie de página, avisos) |
| GET | `/provincias` | Lista de provincias (y geometría opcional) | Selector de zona |
| GET / POST | `/calendario` | **Matriz mes × año** de focos armonizados | Pantalla principal |
| GET / POST | `/serie` | Serie mensual o anual de una zona | Gráfico de líneas |
| GET / POST | `/anomalia` | Un mes contra su mediana histórica | Tarjeta "este mes vs. lo normal" |
| GET | `/mapa/celdas` | Celdas con actividad en un período (GeoJSON) | Mapa |
| GET | `/mapa/industriales` | Fuentes industriales excluidas (GeoJSON) | Capa informativa |
| GET / POST | `/descargas/focos.csv` | Focos individuales de la zona y el período | Botón "Descargar focos" |
| GET / POST | `/descargas/calendario.csv` | Calendario en CSV | Botón "Descargar calendario" |
| POST | `/admin/reload` | Recargar los datos después de una actualización | Pipeline (con token) |

---

## `GET /health`

**Respuesta 200**

| Campo | Tipo | Descripción |
|---|---|---|
| `estado` | string | `ok` o `degradado` |
| `datos_listos` | boolean | DuckDB abrió los Parquet correctamente |
| `data_version` | string | Versión de datos activa |
| `fecha_max` | date | Último día con datos |

```json
{"estado": "ok", "datos_listos": true, "data_version": "2026-11-14T09:00:00-03:00", "fecha_max": "2026-11-13"}
```

## `GET /metadata`

Devuelve el contenido de `metadata.json` (ver [02](02-contratos-de-datos.md#9-metadatajson)) más `celdas_total` y `provincias_total`.

## `GET /provincias`

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `geometria` | boolean | `false` | Incluir el polígono simplificado |

**Respuesta 200:** lista de objetos.

| Campo | Tipo | Ejemplo |
|---|---|---|
| `provincia_id` | string | `"74"` |
| `nombre` | string | `"San Luis"` |
| `region` | string | `"Cuyo"` |
| `bbox` | number[4] | `[-67.38, -36.0, -64.88, -31.83]` |
| `geometria` | GeoJSON \| null | Solo si `geometria=true` |

---

## `GET /calendario` · `POST /calendario`

Matriz **mes × año** para la zona elegida. Es el endpoint central.

**Parámetros (query en GET, body JSON en POST)**

| Parámetro | Tipo | Obligatorio | Default | Descripción |
|---|---|---|---|---|
| `provincia_id` | string | Uno de los tres | — | Código INDEC |
| `bbox` | string | Uno de los tres | — | `oeste,sur,este,norte` |
| `geometria` | GeoJSON | Uno de los tres (solo POST) | — | Polígono dibujado por el usuario |
| `desde` | `YYYY-MM` | No | `2000-11` | Primer mes |
| `hasta` | `YYYY-MM` | No | último mes con datos | Último mes |
| `capa` | enum | No | `armonizado` | `armonizado`, `modis`, `viirs`. Cada mes trae **siempre** todos los campos; la capa solo cambia `unidad` y el cálculo de `resumen` (en `viirs`, los meses con `viirs = null` no cuentan) |

**Respuesta 200**

| Campo | Tipo | Descripción |
|---|---|---|
| `zona` | object | `{tipo, id o bbox, celdas, area_km2}` |
| `capa` | string | Capa pedida |
| `unidad` | string | `"focos (escala VIIRS S-NPP)"` o `"focos MODIS"` |
| `meses` | array | Una entrada por mes (ver tabla siguiente) |
| `resumen` | object | `{max_mes, max_anio, total, mediana_mensual}` |
| `data_version` | string | Para caché y trazabilidad |

**Cada elemento de `meses`**

| Campo | Tipo | Nulo | Descripción |
|---|---|---|---|
| `periodo` | `YYYY-MM` | No | Mes |
| `modis` | integer | No | Focos MODIS crudos (Terra + Aqua) |
| `viirs` | integer | **Sí** | Focos VIIRS observados del satélite de referencia; `null` si no había VIIRS |
| `armonizado` | number | No | Valor a mostrar en el calendario (escala VIIRS) |
| `minimo` | number | No | Límite inferior del rango del 80 % (igual a `armonizado` si es 100 % observado) |
| `maximo` | number | No | Límite superior del rango del 80 % |
| `estado` | enum | No | `observado`, `estimado` o `mixto` |
| `frac_estimada` | number | No | Fracción de días del mes que se estimaron (0–1) |
| `confianza` | enum | No | `alta`, `media` o `baja` (ver [04](04-logica-de-armonizacion.md#5-confianza)) |
| `parcial` | boolean | No | `true` si es el mes en curso (todavía incompleto) |

```json
{
  "zona": {"tipo": "provincia", "id": "74", "celdas": 3175, "area_km2": 75554},
  "capa": "armonizado",
  "unidad": "focos (escala VIIRS S-NPP)",
  "meses": [
    {"periodo": "2006-08", "modis": 120, "viirs": null, "armonizado": 358.8, "minimo": 262.0, "maximo": 445.0,
     "estado": "estimado", "frac_estimada": 1.0, "confianza": "media"},
    {"periodo": "2020-08", "modis": 410, "viirs": 1290, "armonizado": 1290.0, "minimo": 1290.0, "maximo": 1290.0,
     "estado": "observado", "frac_estimada": 0.0, "confianza": "alta"}
  ],
  "resumen": {"max_mes": "2020-08", "max_anio": 2020, "total": 41234.5, "mediana_mensual": 96.0},
  "data_version": "2026-11-14T09:00:00-03:00"
}
```

*(Valores del ejemplo ilustrativos.)*

## `GET /serie` · `POST /serie`

Mismos parámetros de zona y período que `/calendario`, más:

| Parámetro | Tipo | Default | Descripción |
|---|---|---|---|
| `granularidad` | enum | `mes` | `mes` o `anio` |

**Respuesta:** `{zona, granularidad, puntos: [...]}`; cada punto tiene los mismos campos que los `meses` de `/calendario` (con `periodo` = `YYYY` si es anual).

Para la granularidad anual se suman los conteos y los límites de los meses incluidos.
La fracción estimada se calcula sobre todos los días cubiertos por la consulta durante ese año.
`parcial` se activa si la serie incluye el mes incompleto al final de la cobertura.

## `GET /anomalia` · `POST /anomalia`

Compara un mes con el **mismo mes de todos los años** de la serie armonizada.

| Parámetro | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| zona | (igual que `/calendario`) | Sí | — |
| `mes` | `YYYY-MM` | No (default: último mes completo) | Mes a evaluar |

**Respuesta 200**

| Campo | Tipo | Descripción |
|---|---|---|
| `mes` | `YYYY-MM` | Mes evaluado |
| `valor` | number | Focos armonizados del mes |
| `mediana` | number | Mediana del mismo mes en todos los años disponibles |
| `p25`, `p75` | number | Cuartiles históricos |
| `razon` | number | `valor / mediana` (null si la mediana es 0) |
| `percentil` | number | Posición del mes en la historia (0–100) |
| `categoria` | enum | `muy_por_debajo` (< p10), `por_debajo` (< p25), `normal`, `por_encima` (> p75), `muy_por_encima` (> p90) |
| `anios_usados` | integer | Cantidad de años en la comparación |

El histórico excluye el mes evaluado y los meses incompletos (el mes en curso). Los percentiles de corte usan el rango más próximo
hacia arriba en la muestra ordenada. `percentil` indica el porcentaje de valores históricos
menores o iguales al valor evaluado. Con menos de 10 años o si el mes evaluado está incompleto,
`categoria` es nula. Si no hay años comparables, también son nulos la mediana, los cuartiles
y el percentil.

## `GET /mapa/celdas`

| Parámetro | Tipo | Obligatorio | Default | Descripción |
|---|---|---|---|---|
| `bbox` | string | Sí | — | Vista actual del mapa |
| `desde`, `hasta` | `YYYY-MM-DD` | Sí | — | Período (máximo 366 días) |
| `capa` | enum | No | `armonizado` | `armonizado`, `modis`, `viirs` |
| `min_focos` | number | No | `1` | No devuelve celdas debajo de este valor |

**Respuesta:** `FeatureCollection` con **polígonos** de celda.

| Propiedad | Tipo | Descripción |
|---|---|---|
| `cell_id` | integer | Celda |
| `provincia_id` | string | Provincia |
| `valor` | number | Focos de la capa pedida en el período |
| `modis`, `viirs` | integer \| null | Crudos |
| `estado` | enum | `observado`, `estimado`, `mixto` |

**Límite:** como máximo 20.000 celdas por respuesta; si se supera → **413** con el mensaje "acercá el mapa o acortá el período".

## `GET /mapa/industriales`

`FeatureCollection` de **puntos**, con las propiedades `motivo`, `n_focos` y `provincia_id` (`null` si el punto está fuera de las provincias). Tiene `bbox` opcional.

## `GET|POST /descargas/focos.csv`

| Parámetro | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| zona | (igual que `/calendario`) | Sí | — |
| `desde`, `hasta` | `YYYY-MM-DD` | Sí | Período |
| `sensor` | enum | No | `todos` (default), `MODIS`, `VIIRS` |

**Columnas del CSV:** `fecha, hora_utc, satelite, sensor, lat, lon, confianza, frp_mw, dia_noche, fuente, provincia_id, cell_id`

**Límite:** 500.000 filas; si se supera → **413**.

**Cabeceras:** `Content-Type: text/csv; charset=utf-8` y `Content-Disposition: attachment; filename="focos_<zona>_<desde>_<hasta>.csv"`. La primera línea del CSV es un comentario con la cita a NASA FIRMS.

## `GET|POST /descargas/calendario.csv`

**Columnas:** `periodo, modis, viirs, armonizado, minimo, maximo, estado, frac_estimada, confianza`.

## `POST /admin/reload`

- **Cabecera:** `Authorization: Bearer <RELOAD_TOKEN>`.
- **Qué hace:** reabre la conexión DuckDB **del worker que recibe la llamada** sobre `/var/data/current`. Como Uvicorn corre con 2 workers, además cada worker revisa cada pocos segundos a qué versión apunta el symlink `current` y, si cambió, reabre su conexión por su cuenta. Las consultas en curso terminan sobre la versión anterior.
- **Respuestas:** `204` si se cargó la versión, `401` sin credencial Bearer, `403` si el token es incorrecto y `503` si no se pudo abrir el paquete. Si falla la apertura, el worker conserva la última versión válida.

---

## Errores

Formato único:

```json
{"error": {"codigo": "ZONA_INVALIDA", "mensaje": "Indicá una sola zona: provincia_id, bbox o geometria.", "detalle": null}}
```

| HTTP | `codigo` | Cuándo |
|---|---|---|
| 400 | `ZONA_INVALIDA` | Falta la zona o hay más de una |
| 400 | `GEOMETRIA_INVALIDA` | GeoJSON mal formado, autointersecado o con más de 2.000 vértices |
| 400 | `PERIODO_INVALIDO` | `desde > hasta` o fuera de `[fecha_min, fecha_max]` |
| 401 | `TOKEN_REQUERIDO` | `POST /admin/reload` sin credencial Bearer |
| 403 | `TOKEN_INVALIDO` | `POST /admin/reload` con un token incorrecto |
| 404 | `PROVINCIA_NO_ENCONTRADA` | `provincia_id` inexistente |
| 413 | `RESULTADO_DEMASIADO_GRANDE` | Se superan los límites de celdas o de filas |
| 413 | `CUERPO_DEMASIADO_GRANDE` | El body de un `POST` supera los 256 KB |
| 422 | `PARAMETRO_INVALIDO` | Error de validación (FastAPI), incluido un `bbox` mal formado |
| 503 | `DATOS_NO_DISPONIBLES` | Datos recargándose o ausentes |
| 504 | `TIEMPO_EXCEDIDO` | Consulta de más de 10 s |

## Límites de uso

| Límite | Valor |
|---|---|
| Tiempo máximo por consulta | 10 s |
| Consultas concurrentes por worker | 4 (el resto espera) |
| Tamaño máximo del body (POST) | 256 KB |
| Rate limit sugerido (en Traefik) | 60 solicitudes / minuto por IP |
