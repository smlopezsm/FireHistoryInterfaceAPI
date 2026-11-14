"""Recarga manual de datos del worker."""

from secrets import compare_digest
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.deps import DatosDep
from app.errores import ApiError, datos_no_disponibles

router = APIRouter(prefix="/admin", tags=["administracion"])


@router.post(
    "/reload",
    status_code=204,
    summary="Recargar los datos del worker",
    description=(
        "Reabre DuckDB sobre `/var/data/current` en el worker que recibe la llamada (el otro "
        "detecta el cambio del enlace `current` en pocos segundos). Requiere `Authorization: "
        "Bearer <RELOAD_TOKEN>`. Si el paquete nuevo no abre, se conserva la versión anterior y "
        "responde 503."
    ),
    responses={401: {"description": "Falta el token"}, 403: {"description": "Token inválido"}},
)
def recargar(
    request: Request,
    datos: DatosDep,
    credencial: Annotated[
        HTTPAuthorizationCredentials | None, Depends(HTTPBearer(auto_error=False))
    ],
) -> Response:
    if credencial is None:
        raise ApiError(401, "TOKEN_REQUERIDO", "Enviá un token Bearer.")
    esperado = request.app.state.settings.reload_token.get_secret_value()
    if not esperado or not compare_digest(credencial.credentials.encode(), esperado.encode()):
        raise ApiError(403, "TOKEN_INVALIDO", "El token de recarga es inválido.")
    if not datos.abrir():
        raise datos_no_disponibles()
    return Response(status_code=204)
