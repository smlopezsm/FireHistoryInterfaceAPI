"""Resolución de la zona de consulta a un conjunto de celdas (docs/03 §Convenciones).

- `provincia_id` y `region`: las celdas asignadas en `dim_celdas` (mayor fracción de área),
  igual que en `conteos_celda_dia`.
- `bbox` y `geometria`: las celdas cuyo **centroide** cae dentro de la zona.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

import shapely
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import explain_validity

from app.db import Datos
from app.errores import ApiError
from app.schemas.zonas import PedidoZona, Zona

MAX_VERTICES = 2_000
AREA_CELDA_KM2 = 25.0


@dataclass(frozen=True)
class ResumenProvincia:
    celdas: int
    area_km2: float


@dataclass(frozen=True)
class ZonaResuelta:
    tipo: str
    id: str | None
    bbox: tuple[float, float, float, float] | None
    celdas_ids: list[int]
    area_km2: float
    provincias: dict[str, ResumenProvincia] = field(default_factory=dict)

    def respuesta(self) -> Zona:
        return Zona.model_validate(
            {
                "tipo": self.tipo,
                "id": self.id,
                "bbox": list(self.bbox) if self.bbox else None,
                "celdas": len(self.celdas_ids),
                "area_km2": round(self.area_km2, 1),
            }
        )


def zona_invalida(
    mensaje: str = "Indicá una sola zona: provincia_id, region, bbox o geometria.",
) -> ApiError:
    return ApiError(400, "ZONA_INVALIDA", mensaje)


def geometria_invalida(mensaje: str, detalle: Any = None) -> ApiError:
    return ApiError(400, "GEOMETRIA_INVALIDA", mensaje, detalle)


def resolver_zona(datos: Datos, pedido: PedidoZona) -> ZonaResuelta:
    indicadas = [
        v
        for v in (pedido.provincia_id, pedido.region, pedido.bbox, pedido.geometria)
        if v not in (None, "")
    ]
    if len(indicadas) != 1:
        raise zona_invalida()
    if pedido.provincia_id:
        return _por_provincia(datos, pedido.provincia_id)
    if pedido.region:
        return _por_region(datos, pedido.region)
    if pedido.bbox:
        return _por_bbox(datos, parsear_bbox(pedido.bbox))
    assert pedido.geometria is not None
    return _por_geometria(datos, validar_geometria(pedido.geometria))


def parsear_bbox(texto: str) -> tuple[float, float, float, float]:
    partes = texto.split(",")
    try:
        valores = [float(p) for p in partes]
    except ValueError:
        valores = []
    if len(valores) != 4 or not all(math.isfinite(v) for v in valores):
        raise _bbox_invalido("debe tener 4 números: oeste,sur,este,norte.")
    oeste, sur, este, norte = valores
    if not (
        -180 <= oeste <= 180 and -180 <= este <= 180 and -90 <= sur <= 90 and -90 <= norte <= 90
    ):
        raise _bbox_invalido("las coordenadas están fuera de rango.")
    if oeste >= este or sur >= norte:
        raise _bbox_invalido("oeste debe ser menor que este y sur menor que norte.")
    return oeste, sur, este, norte


def _bbox_invalido(motivo: str) -> ApiError:
    return ApiError(
        422,
        "PARAMETRO_INVALIDO",
        f"El bbox es inválido: {motivo}",
        [{"campo": "bbox", "mensaje": motivo}],
    )


def validar_geometria(geojson: dict[str, Any]) -> Polygon | MultiPolygon:
    tipo = geojson.get("type")
    if tipo not in ("Polygon", "MultiPolygon"):
        raise geometria_invalida("La geometría debe ser un GeoJSON Polygon o MultiPolygon.")
    try:
        geom = shape(geojson)
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise geometria_invalida("El GeoJSON está mal formado.", str(exc)) from exc
    if geom.is_empty or not isinstance(geom, Polygon | MultiPolygon):
        raise geometria_invalida("El GeoJSON está mal formado.")
    vertices = _contar_vertices(geom)
    if vertices > MAX_VERTICES:
        raise geometria_invalida(
            f"La geometría tiene {vertices} vértices; el máximo es {MAX_VERTICES}.",
            {"vertices": vertices, "maximo": MAX_VERTICES},
        )
    oeste, sur, este, norte = geom.bounds
    if not (oeste >= -180 and este <= 180 and sur >= -90 and norte <= 90):
        raise geometria_invalida("Las coordenadas deben ser lon/lat en grados (EPSG:4326).")
    if not geom.is_valid:
        raise geometria_invalida(
            "La geometría no es válida (por ejemplo, se cruza consigo misma).",
            explain_validity(geom),
        )
    return geom


def _contar_vertices(geom: Polygon | MultiPolygon) -> int:
    poligonos = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    total = 0
    for p in poligonos:
        for anillo in [p.exterior, *p.interiors]:
            total += len(anillo.coords) - 1  # el último repite el primero
    return total


def _por_grupo(
    datos: Datos,
    tipo: Literal["provincia", "region"],
    columna: Literal["provincia_id", "region"],
    valor: str,
    codigo_error: str,
    mensaje_error: str,
) -> ZonaResuelta:
    """Resuelve celdas y bbox envolvente a partir de una columna de agrupación."""
    filas = datos.consultar(f"SELECT bbox FROM dim_provincias WHERE {columna} = ?", [valor])
    if not filas:
        raise ApiError(404, codigo_error, mensaje_error)
    cajas = [[float(v) for v in str(f["bbox"]).split(",")] for f in filas]
    bbox = (
        min(c[0] for c in cajas),
        min(c[1] for c in cajas),
        max(c[2] for c in cajas),
        max(c[3] for c in cajas),
    )
    columnas = datos.consultar_columnas(
        f"SELECT cell_id, provincia_id, frac_dentro FROM dim_celdas "
        f"WHERE {columna} = ? ORDER BY cell_id",
        [valor],
    )
    return _armar(tipo, valor, bbox, columnas)


def _por_provincia(datos: Datos, provincia_id: str) -> ZonaResuelta:
    return _por_grupo(
        datos,
        "provincia",
        "provincia_id",
        provincia_id,
        "PROVINCIA_NO_ENCONTRADA",
        f"No existe la provincia {provincia_id!r}.",
    )


def _por_region(datos: Datos, region: str) -> ZonaResuelta:
    return _por_grupo(
        datos,
        "region",
        "region",
        region,
        "REGION_NO_ENCONTRADA",
        f"No existe la región {region!r}.",
    )


def _por_bbox(datos: Datos, bbox: tuple[float, float, float, float]) -> ZonaResuelta:
    columnas = datos.consultar_columnas(
        "SELECT cell_id, provincia_id, frac_dentro FROM dim_celdas "
        "WHERE lon_centro BETWEEN ? AND ? AND lat_centro BETWEEN ? AND ? ORDER BY cell_id",
        [bbox[0], bbox[2], bbox[1], bbox[3]],
    )
    return _armar("bbox", None, bbox, columnas)


def _por_geometria(datos: Datos, geom: Polygon | MultiPolygon) -> ZonaResuelta:
    oeste, sur, este, norte = geom.bounds
    candidatas = datos.consultar_columnas(
        "SELECT cell_id, provincia_id, frac_dentro, lon_centro, lat_centro FROM dim_celdas "
        "WHERE lon_centro BETWEEN ? AND ? AND lat_centro BETWEEN ? AND ? ORDER BY cell_id",
        [oeste, este, sur, norte],
    )
    shapely.prepare(geom)
    dentro = shapely.intersects_xy(geom, candidatas["lon_centro"], candidatas["lat_centro"])
    columnas = {k: candidatas[k][dentro] for k in ("cell_id", "provincia_id", "frac_dentro")}
    return _armar("geometria", None, (oeste, sur, este, norte), columnas)


def _armar(
    tipo: str,
    id_: str | None,
    bbox: tuple[float, float, float, float] | None,
    columnas: dict[str, Any],
) -> ZonaResuelta:
    ids = [int(c) for c in columnas["cell_id"]]
    if not ids:
        raise zona_invalida("La zona no contiene celdas de Argentina.")
    celdas: dict[str, int] = defaultdict(int)
    areas: dict[str, float] = defaultdict(float)
    for pid, frac in zip(columnas["provincia_id"], columnas["frac_dentro"], strict=True):
        celdas[str(pid)] += 1
        areas[str(pid)] += float(frac) * AREA_CELDA_KM2
    provincias = {
        pid: ResumenProvincia(celdas=celdas[pid], area_km2=areas[pid]) for pid in sorted(celdas)
    }
    return ZonaResuelta(
        tipo=tipo,
        id=id_,
        bbox=bbox,
        celdas_ids=ids,
        area_km2=sum(areas.values()),
        provincias=provincias,
    )
