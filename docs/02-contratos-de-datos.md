# 02 · Contratos de datos

Este documento define **el formato exacto de cada archivo** que la API lee desde `/var/data/current/`. El pipeline (`ml_nasaspaceapp`) es el **productor** y la API es la **consumidora**. Cualquier cambio de formato implica subir `schema_version` en `metadata.json`.

## Convenciones generales

| Regla | Valor |
|---|---|
| Formato | Apache Parquet, compresión ZSTD |
| Fechas | `DATE` en **hora local de Argentina** (UTC−3; con el huso histórico de cada provincia cuando corresponda) |
| Coordenadas | WGS84 (EPSG:4326), grados decimales, `FLOAT` |
| Grilla | Albers custom Argentina, celdas de 5 × 5 km, `cell_id = fila · 460 + columna` |
| Particionado | Estilo Hive por año: `anio=YYYY/part-0.parquet` en los archivos grandes |
| Nulos | Solo donde la tabla lo indica como "Sí" |
| Satélites | Valores válidos: `Terra`, `Aqua`, `SNPP`, `N20`, `N21` |
| Dispersión | **No se guardan ceros**: si una celda-día no aparece, tuvo 0 focos (siempre que el satélite estuviera operativo, ver `satelite_operativo`) |

---

## 1. `focos/` — detecciones individuales (para la descarga CSV y el mapa de puntos)

Una fila = **un foco** que pasó los filtros de calidad y **no** está en un punto industrial.

| Columna | Tipo | Nulo | Descripción | Ejemplo |
|---|---|---|---|---|
| `foco_id` | `INT64` | No | Identificador único estable | `20240815000123` |
| `fecha` | `DATE` | No | Fecha local | `2024-08-15` |
| `hora_utc` | `VARCHAR(4)` | No | Hora de adquisición UTC, `HHMM` | `0425` |
| `satelite` | `VARCHAR` | No | `Terra`, `Aqua`, `SNPP`, `N20`, `N21` | `SNPP` |
| `sensor` | `VARCHAR` | No | `MODIS` o `VIIRS` | `VIIRS` |
| `lat` | `FLOAT` | No | Latitud del centro del píxel | `-33.3014` |
| `lon` | `FLOAT` | No | Longitud del centro del píxel | `-66.3321` |
| `confianza` | `VARCHAR` | No | MODIS: `0–100`; VIIRS: `n` / `h` | `n` |
| `frp_mw` | `FLOAT` | No | Potencia radiativa (MW); informativo | `5.2` |
| `dia_noche` | `VARCHAR(1)` | No | `D` / `N` | `D` |
| `fuente` | `VARCHAR` | No | `SP` (científico) / `NRT` (casi real) | `SP` |
| `cell_id` | `INT32` | No | Celda 5 × 5 km | `229643` |
| `provincia_id` | `VARCHAR(2)` | Sí | Código INDEC de la provincia; nulo si cae fuera | `74` |
| `anio` | `INT16` | No | Partición | `2024` |

**Volumen esperado:** ~4,1 M filas (2000 → hoy) · ~100–200 MB en Parquet *(estimación; se confirma al generarlo)*.

---

## 2. `conteos_celda_dia/` — conteos diarios por celda y satélite (base del calendario)

Una fila = **una celda en un día con al menos 1 foco** de algún satélite.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `cell_id` | `INT32` | No | Celda 5 × 5 km |
| `fecha` | `DATE` | No | Fecha local |
| `provincia_id` | `VARCHAR(2)` | No | Provincia a la que se asigna la celda (mayor fracción de área) |
| `n_terra` | `INT16` | No | Focos Terra |
| `n_aqua` | `INT16` | No | Focos Aqua |
| `n_snpp` | `INT16` | No | Focos S-NPP |
| `n_n20` | `INT16` | No | Focos NOAA-20 |
| `n_n21` | `INT16` | No | Focos NOAA-21 (informativo; **no** se usa como referencia) |
| `anio` | `INT16` | No | Partición |

**Reglas:**
- Los focos en **puntos industriales ya están excluidos**.
- Los conteos usan los mismos filtros que la calibración: confianza (MODIS ≥ 30; VIIRS `n`/`h`), `type = 0` cuando existe y FRP > 0.

---

## 3. `dim_celdas.parquet` — dimensión de celdas (máscara nacional)

Una fila = **una celda que toca el territorio continental argentino**.

| Columna | Tipo | Nulo | Descripción |
|---|---|---|---|
| `cell_id` | `INT32` | No | Clave |
| `grid_row` | `INT16` | No | Fila (0–779) |
| `grid_col` | `INT16` | No | Columna (0–459) |
| `provincia_id` | `VARCHAR(2)` | No | Provincia con mayor fracción de la celda |
| `region` | `VARCHAR` | No | `NOA`, `NEA`, `Pampeana`, `Cuyo`, `Patagonia` |
| `frac_dentro` | `FLOAT` | No | Fracción de la celda dentro de Argentina (0–1) |
| `lat_centro` | `FLOAT` | No | Centroide de la celda (EPSG:4326) |
| `lon_centro` | `FLOAT` | No | Centroide de la celda (EPSG:4326) |
| `geom_geojson` | `VARCHAR` | No | Polígono de la celda (4 vértices, EPSG:4326) en GeoJSON |

---

## 4. `dim_provincias.parquet`

| Columna | Tipo | Nulo | Descripción | Ejemplo |
|---|---|---|---|---|
| `provincia_id` | `VARCHAR(2)` | No | Código INDEC | `74` |
| `nombre` | `VARCHAR` | No | Nombre oficial corto | `San Luis` |
| `region` | `VARCHAR` | No | Región | `Cuyo` |
| `geom_geojson` | `VARCHAR` | No | Polígono simplificado (≈ 1 km) para el mapa | — |
| `bbox` | `VARCHAR` | No | `oeste,sur,este,norte` | `-67.38,-36.00,-64.88,-31.83` |

---

## 5. `factores_provincia_mes.parquet` — factores de armonización

Una fila = **provincia × mes calendario** (24 × 12 = 288 filas por tipo).

| Columna | Tipo | Nulo | Descripción | Ejemplo |
|---|---|---|---|---|
| `provincia_id` | `VARCHAR(2)` | No | Código INDEC | `74` |
| `mes` | `INT8` | No | 1–12 | `6` |
| `tipo` | `VARCHAR` | No | `modis` (Terra + Aqua) o `terra` (período solo Terra) | `modis` |
| `factor` | `FLOAT` | No | Focos VIIRS (S-NPP) por cada foco MODIS | `2.49` |
| `nivel_origen` | `VARCHAR` | No | De dónde sale principalmente: `provincia`, `region` o `pais` | `provincia` |
| `n_modis_calib` | `INT32` | No | Focos MODIS usados en la calibración (confianza) | `1840` |
| `factores_version` | `VARCHAR` | No | Versión de la tabla | `2026.11-b1` |

**Regla:** si falta una combinación (por ejemplo, CABA en un mes sin datos), la API usa el factor de la región para ese mes, tomado de `factores_region_mes.parquet` (§5.1); si tampoco existe, el nacional (`region = Argentina`). En ese caso la API informa `nivel_origen = region` o `pais`.

### 5.1 `factores_region_mes.parquet` — factores de respaldo por región y nacional

Una fila = **región × mes calendario**, más el nivel nacional (6 × 12 = 72 filas por tipo). La API **solo** los usa cuando falta una combinación en `factores_provincia_mes.parquet`.

| Columna | Tipo | Nulo | Descripción | Ejemplo |
|---|---|---|---|---|
| `region` | `VARCHAR` | No | `NOA`, `NEA`, `Pampeana`, `Cuyo`, `Patagonia` o `Argentina` (nivel nacional) | `Cuyo` |
| `mes` | `INT8` | No | 1–12 | `6` |
| `tipo` | `VARCHAR` | No | `modis` o `terra` (igual que en §5) | `modis` |
| `factor` | `FLOAT` | No | Focos VIIRS (S-NPP) por cada foco MODIS en la región | `3.10` |
| `n_modis_calib` | `INT32` | No | Focos MODIS usados en la calibración | `9120` |
| `factores_version` | `VARCHAR` | No | Igual que en §5 | `2026.11-b1` |

---

## 6. `rangos.parquet` — multiplicadores del intervalo del 80 %

| Columna | Tipo | Descripción |
|---|---|---|
| `modis_min` | `INT32` | Límite inferior del tramo de focos MODIS del mes (inclusive) |
| `modis_max` | `INT32` | Límite superior (inclusive; `2147483647` = sin tope) |
| `mult_bajo` | `FLOAT` | Multiplicador inferior (si `modis_min = 0`, es un **valor absoluto**) |
| `mult_alto` | `FLOAT` | Multiplicador superior (si `modis_min = 0`, es un **valor absoluto**) |

**Valores iniciales** (calibración 2012–2022, cobertura medida: 77,9 %):

| modis_min | modis_max | mult_bajo | mult_alto |
|---:|---:|---:|---:|
| 0 | 0 | 0 | 10 |
| 1 | 5 | 0.46 | 4.49 |
| 6 | 20 | 0.55 | 1.86 |
| 21 | 100 | 0.63 | 1.33 |
| 101 | 500 | 0.73 | 1.24 |
| 501 | 2147483647 | 0.82 | 1.18 |

---

## 7. `satelite_operativo.parquet` — días con satélite caído

Una fila = **día × satélite** desde el inicio de cada misión.

| Columna | Tipo | Descripción |
|---|---|---|
| `fecha` | `DATE` | Día |
| `satelite` | `VARCHAR` | `Terra`, `Aqua`, `SNPP`, `N20`, `N21` |
| `operativo` | `BOOLEAN` | `false` si el satélite no tiene **ninguna** detección en todo el país ese día (o si la fecha es anterior al inicio o posterior al fin de la misión) |
| `n_nacional` | `INT32` | Focos de ese satélite en todo el país ese día |

**Fechas clave:** S-NPP operativo del 2012-01-20 al 2026-11-02 · NOAA-20 desde 2018-04-01 en el archivo · Aqua desde 2002-07-04.

---

## 8. `puntos_industriales.parquet` — fuentes fijas excluidas

| Columna | Tipo | Descripción |
|---|---|---|
| `punto_id` | `INT64` | Identificador de la celda de ~1 km (lat × 100, lon × 100 redondeados) |
| `lat`, `lon` | `FLOAT` | Posición media |
| `provincia_id` | `VARCHAR(2)` | Provincia |
| `motivo` | `VARCHAR` | `nocturno todo el año` · `marcado industrial por FIRMS` · `nocturno estacional` |
| `dias`, `anios`, `meses` | `INT16` | Persistencia observada |
| `frac_nocturna` | `FLOAT` | Proporción de detecciones nocturnas |
| `n_focos` | `INT32` | Focos excluidos en ese punto |

Versión inicial: **488 puntos** (80.681 focos excluidos). La API lo expone como capa informativa del mapa.

---

## 9. `metadata.json`

```json
{
  "schema_version": "1.0.0",
  "data_version": "2026-11-14T09:00:00-03:00",
  "factores_version": "2026.11-b1",
  "fecha_min": "2000-11-01",
  "fecha_max": "2026-11-13",
  "fecha_ultimo_sp": "2026-08-31",
  "referencia_viirs": [
    {"satelite": "SNPP", "desde": "2012-01-20", "hasta": "2026-11-02"},
    {"satelite": "N20",  "desde": "2026-11-03", "hasta": null}
  ],
  "fuentes": ["NASA FIRMS MODIS C6.1", "NASA FIRMS VIIRS 375m", "IGN via API Georef"],
  "pipeline_commit": "abc1234"
}
```

---

## Validaciones obligatorias del pipeline (antes de publicar)

| Chequeo | Condición |
|---|---|
| Esquema | Columnas y tipos exactamente como en este documento |
| Fechas | `fecha_min ≤ fecha ≤ fecha_max`, sin fechas futuras |
| Conteos | Todos los `n_*` ≥ 0 y al menos uno > 0 por fila |
| Claves | `cell_id` presente en `dim_celdas`; `provincia_id` en `dim_provincias` |
| Factores | 24 × 12 filas por `tipo`; `0.5 < factor < 20` |
| Factores de respaldo | 6 × 12 filas por `tipo` (5 regiones + `Argentina`); `0.5 < factor < 20` |
| Volumen | Diferencia de filas con la versión anterior < 5 % en años cerrados |

## Fuentes y citas

- NASA FIRMS — MODIS C6.1 y VIIRS 375 m Active Fire (SP y NRT).
- Límites provinciales: Instituto Geográfico Nacional, vía API Georef (datos.gob.ar).
- Método de armonización: ver `propuesta_B_calendario_focos_armonizado_ES.md` (proyecto del equipo).
