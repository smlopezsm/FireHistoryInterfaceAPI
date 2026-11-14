"""GET /provincias (docs/03 §provincias)."""

from __future__ import annotations

from typing import Annotated

import orjson
from fastapi import APIRouter, Query

from app.deps import DatosListosDep
from app.schemas.errores import ErrorRespuesta
from app.schemas.provincias import Provincia

router = APIRouter(tags=["zonas"])


@router.get(
    "/provincias",
    response_model=list[Provincia],
    summary="Lista de provincias",
    description=(
        "Devuelve las provincias con su código INDEC, nombre, región y rectángulo envolvente. "
        "Con `geometria=true` incluye además el polígono simplificado (≈ 1 km) para el mapa."
    ),
    responses={503: {"model": ErrorRespuesta, "description": "Datos no disponibles."}},
)
def listar_provincias(
    datos: DatosListosDep,
    geometria: Annotated[
        bool, Query(description="Incluir el polígono simplificado de cada provincia.")
    ] = False,
) -> list[Provincia]:
    columna_geom = "geom_geojson" if geometria else "NULL AS geom_geojson"
    filas = datos.consultar(
        f"SELECT provincia_id, nombre, region, bbox, {columna_geom} "
        "FROM dim_provincias ORDER BY provincia_id"
    )
    return [
        Provincia(
            provincia_id=f["provincia_id"],
            nombre=f["nombre"],
            region=f["region"],
            bbox=[float(v) for v in f["bbox"].split(",")],
            geometria=orjson.loads(f["geom_geojson"]) if f["geom_geojson"] else None,
        )
        for f in filas
    ]
