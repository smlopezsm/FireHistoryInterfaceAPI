"""GET /metadata (docs/03 §metadata)."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import DatosListosDep
from app.schemas.errores import ErrorRespuesta
from app.schemas.metadata import Metadata

router = APIRouter(tags=["estado"])


@router.get(
    "/metadata",
    response_model=Metadata,
    summary="Versiones y rango de fechas de los datos",
    description=(
        "Devuelve el contenido de `metadata.json` (versión de datos y de factores, rango de "
        "fechas, satélite VIIRS de referencia por período y fuentes), más la cantidad total "
        "de celdas y de provincias."
    ),
    responses={503: {"model": ErrorRespuesta, "description": "Datos no disponibles."}},
)
def metadata(datos: DatosListosDep) -> Metadata:
    assert datos.metadata is not None
    return Metadata(
        **datos.metadata.model_dump(),
        celdas_total=datos.celdas_total,
        provincias_total=datos.provincias_total,
    )
