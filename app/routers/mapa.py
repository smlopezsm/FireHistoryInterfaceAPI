"""Endpoints de capas geográficas."""

from typing import Annotated, Any

from fastapi import APIRouter, Query, Request

from app.deps import DatosListosDep
from app.schemas.armonizacion import Capa
from app.services import mapa

router = APIRouter(prefix="/mapa", tags=["mapa"])


@router.get("/celdas", summary="Celdas con focos en la vista del mapa")
def celdas(
    request: Request,
    datos: DatosListosDep,
    bbox: Annotated[str, Query(description="Vista del mapa: oeste,sur,este,norte.")],
    desde: Annotated[str, Query(description="Primer día (YYYY-MM-DD).")],
    hasta: Annotated[str, Query(description="Último día (YYYY-MM-DD).")],
    capa: Capa = "armonizado",
    min_focos: Annotated[float, Query(ge=0, allow_inf_nan=False)] = 1,
) -> dict[str, Any]:
    return mapa.celdas(
        datos, bbox, desde, hasta, capa, min_focos, request.app.state.settings.max_celdas_mapa
    )


@router.get("/industriales", summary="Puntos industriales")
def industriales(
    datos: DatosListosDep,
    bbox: Annotated[str | None, Query(description="Vista del mapa: oeste,sur,este,norte.")] = None,
) -> dict[str, Any]:
    return mapa.industriales(datos, bbox)
