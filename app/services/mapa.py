"""Consultas de celdas y puntos industriales para el mapa."""

from typing import Any

import orjson

from app.db import Datos
from app.errores import ApiError, datos_no_disponibles
from app.schemas.armonizacion import Capa
from app.services.armonizacion import CONTEOS_SQL, cobertura_sql
from app.services.periodos import periodo_diario
from app.services.zonas import parsear_bbox

CELDAS_SQL = f"""
, zona AS (
    SELECT cell_id, provincia_id FROM dim_celdas
    WHERE lon_centro BETWEEN ? AND ? AND lat_centro BETWEEN ? AND ?
), meses AS (
    SELECT z.cell_id, z.provincia_id, month(c.fecha) AS mes,
           year(c.fecha) AS anio, {CONTEOS_SQL}
    FROM conteos_celda_dia c
    JOIN zona z ON z.cell_id = c.cell_id
    JOIN cobertura d ON d.fecha = c.fecha
    WHERE c.anio BETWEEN ? AND ? AND c.fecha BETWEEN ? AND ?
    GROUP BY 1, 2, 3, 4
), por_tipo AS (
    SELECT cell_id, provincia_id, mes, modis, obs, est_terra AS conteo, 'terra' AS tipo
    FROM meses
    UNION ALL
    SELECT cell_id, provincia_id, mes, 0, 0, est_modis, 'modis' FROM meses
), totales AS (
    SELECT t.cell_id, sum(t.modis) AS modis, sum(t.obs) AS obs,
           sum(t.conteo * coalesce(fp.factor, fr.factor, fn.factor)::DOUBLE) AS estimado,
           count(*) FILTER (WHERE t.conteo > 0 AND
               coalesce(fp.factor, fr.factor, fn.factor) IS NULL) AS factores_faltantes
    FROM por_tipo t
    JOIN dim_provincias p ON p.provincia_id = t.provincia_id
    LEFT JOIN factores_provincia_mes fp
        ON fp.provincia_id = t.provincia_id AND fp.mes = t.mes AND fp.tipo = t.tipo
    LEFT JOIN factores_region_mes fr
        ON fr.region = p.region AND fr.mes = t.mes AND fr.tipo = t.tipo
    LEFT JOIN factores_region_mes fn
        ON fn.region = 'Argentina' AND fn.mes = t.mes AND fn.tipo = t.tipo
    GROUP BY t.cell_id
), estado AS (
    SELECT count(*) FILTER (WHERE operativo) AS observados, count(*) AS dias FROM cobertura
), valores AS (
    SELECT z.cell_id, z.provincia_id, coalesce(t.modis, 0) AS modis,
           CASE WHEN e.observados > 0 THEN coalesce(t.obs, 0) END AS viirs,
           coalesce(t.obs, 0) + coalesce(t.estimado, 0) AS armonizado,
           CASE WHEN e.observados = 0 THEN 'estimado'
                WHEN e.observados = e.dias THEN 'observado' ELSE 'mixto' END AS estado,
           coalesce(t.factores_faltantes, 0) AS factores_faltantes
    FROM zona z CROSS JOIN estado e LEFT JOIN totales t ON t.cell_id = z.cell_id
), seleccion AS (
    SELECT *, CASE ? WHEN 'modis' THEN modis WHEN 'viirs' THEN viirs
                     ELSE armonizado END AS valor,
           max(factores_faltantes) OVER () AS faltantes
    FROM valores
), filtradas AS (
    SELECT * FROM seleccion WHERE valor >= ? OR faltantes > 0 ORDER BY cell_id LIMIT ?
)
SELECT f.cell_id, f.provincia_id, f.modis, f.viirs, f.estado, f.valor, f.faltantes, d.geom_geojson
FROM filtradas f JOIN dim_celdas d ON d.cell_id = f.cell_id ORDER BY f.cell_id
"""


def celdas(
    datos: Datos, bbox: str, desde: str, hasta: str, capa: Capa, min_focos: float, maximo: int
) -> dict[str, Any]:
    oeste, sur, este, norte = parsear_bbox(bbox)
    inicio, fin = periodo_diario(datos, desde, hasta, max_dias=366)
    assert datos.metadata is not None
    filas = datos.consultar(
        cobertura_sql(datos.metadata.referencia_viirs) + CELDAS_SQL,
        [
            inicio,
            fin,
            oeste,
            este,
            sur,
            norte,
            inicio.year,
            fin.year,
            inicio,
            fin,
            capa,
            min_focos,
            maximo + 1,
        ],
    )
    if filas and filas[0]["faltantes"]:
        raise datos_no_disponibles()
    if len(filas) > maximo:
        raise ApiError(413, "RESULTADO_DEMASIADO_GRANDE", "Acercá el mapa o acortá el período.")
    features = []
    for fila in filas:
        geometria = orjson.loads(fila.pop("geom_geojson"))
        fila.pop("faltantes")
        fila["valor"] = round(fila["valor"], 1)
        features.append({"type": "Feature", "geometry": geometria, "properties": fila})
    return {"type": "FeatureCollection", "features": features}


def industriales(datos: Datos, bbox: str | None) -> dict[str, Any]:
    sql = "SELECT lon, lat, motivo, n_focos, provincia_id FROM puntos_industriales"
    if bbox is None:
        filas = datos.consultar(sql + " ORDER BY punto_id")
    else:
        oeste, sur, este, norte = parsear_bbox(bbox)
        filas = datos.consultar(
            sql + " WHERE lon BETWEEN ? AND ? AND lat BETWEEN ? AND ? ORDER BY punto_id",
            [oeste, este, sur, norte],
        )
    features = []
    for fila in filas:
        coordenadas = [fila.pop("lon"), fila.pop("lat")]
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": coordenadas},
                "properties": fila,
            }
        )
    return {"type": "FeatureCollection", "features": features}
