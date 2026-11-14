"""Endpoints de capas geográficas."""

from typing import Annotated

import orjson
from fastapi import APIRouter, Query, Request, Response

from app.deps import DatosListosDep
from app.schemas.armonizacion import Capa
from app.schemas.errores import ErrorRespuesta
from app.schemas.mapa import ColeccionCeldas, ColeccionIndustriales
from app.services import mapa

router = APIRouter(prefix="/mapa", tags=["mapa"])


@router.get(
    "/celdas",
    response_model=None,
    responses={
        200: {"model": ColeccionCeldas, "description": "Celdas como FeatureCollection."},
        413: {"model": ErrorRespuesta, "description": "Más de 20.000 celdas."},
    },
    summary="Celdas con focos en la vista del mapa",
    description=(
        "Celdas de 5 × 5 km de la vista (`bbox`) con focos en el período (hasta 366 días), como "
        "polígonos GeoJSON. Devuelve como máximo 20.000 celdas; si hay más, responde 413: acercá "
        "el mapa o acortá el período."
    ),
)
def celdas(
    request: Request,
    datos: DatosListosDep,
    bbox: Annotated[str, Query(description="Vista del mapa: oeste,sur,este,norte.")],
    desde: Annotated[str, Query(description="Primer día (YYYY-MM-DD).")],
    hasta: Annotated[str, Query(description="Último día (YYYY-MM-DD).")],
    capa: Annotated[Capa, Query(description="`armonizado`, `modis` o `viirs`.")] = "armonizado",
    min_focos: Annotated[
        float, Query(ge=0, allow_inf_nan=False, description="No devuelve celdas con menos focos.")
    ] = 1,
) -> Response:
    # GeoJSON grande: se serializa directo con orjson, sin validar 20.000 objetos.
    coleccion = mapa.celdas(
        datos, bbox, desde, hasta, capa, min_focos, request.app.state.settings.max_celdas_mapa
    )
    return Response(orjson.dumps(coleccion), media_type="application/json")


@router.get(
    "/industriales",
    response_model=None,
    responses={200: {"model": ColeccionIndustriales, "description": "Puntos industriales."}},
    summary="Puntos industriales",
    description=(
        "Fuentes fijas (industrias, quemas permanentes) excluidas de los conteos, como puntos "
        "GeoJSON. Es una capa informativa; `bbox` es opcional."
    ),
)
def industriales(
    datos: DatosListosDep,
    bbox: Annotated[str | None, Query(description="Vista del mapa: oeste,sur,este,norte.")] = None,
) -> Response:
    return Response(orjson.dumps(mapa.industriales(datos, bbox)), media_type="application/json")
