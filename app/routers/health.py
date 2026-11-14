"""GET /health (docs/03 §health)."""

from __future__ import annotations

from fastapi import APIRouter

from app.deps import DatosDep
from app.schemas.health import Health

router = APIRouter(tags=["estado"])


@router.get(
    "/health",
    response_model=Health,
    summary="Estado del servicio",
    description=(
        "Indica si la API está levantada y si los datos están listos. Responde siempre 200: "
        "con `estado = degradado` cuando los Parquet no se pudieron abrir. "
        "Lo usan Dokploy y el monitoreo."
    ),
)
def health(datos: DatosDep) -> Health:
    meta = datos.metadata if datos.listo else None
    return Health(
        estado="ok" if meta else "degradado",
        datos_listos=meta is not None,
        data_version=meta.data_version if meta else None,
        fecha_max=meta.fecha_max if meta else None,
    )
