"""Errores de la API con el formato único de docs/03 §Errores."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Error con código y mensaje en español."""

    def __init__(self, status: int, codigo: str, mensaje: str, detalle: Any = None) -> None:
        super().__init__(mensaje)
        self.status = status
        self.codigo = codigo
        self.mensaje = mensaje
        self.detalle = detalle


def datos_no_disponibles() -> ApiError:
    return ApiError(
        503,
        "DATOS_NO_DISPONIBLES",
        "Los datos no están disponibles en este momento. Probá de nuevo en unos minutos.",
    )


def tiempo_excedido(segundos: float) -> ApiError:
    return ApiError(
        504,
        "TIEMPO_EXCEDIDO",
        f"La consulta tardó más de {segundos:g} s. Achicá la zona o el período.",
    )


# Errores de ruteo de Starlette (no figuran en docs/03, pero se devuelven con el mismo formato).
_HTTP_GENERICOS = {
    404: ("RUTA_NO_ENCONTRADA", "La ruta pedida no existe."),
    405: ("METODO_NO_PERMITIDO", "El método HTTP no está permitido en esta ruta."),
}


def respuesta_error(status: int, codigo: str, mensaje: str, detalle: Any = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"codigo": codigo, "mensaje": mensaje, "detalle": detalle}},
    )


def registrar_manejadores(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return respuesta_error(exc.status, exc.codigo, exc.mensaje, exc.detalle)

    @app.exception_handler(RequestValidationError)
    async def _validacion(_: Request, exc: RequestValidationError) -> JSONResponse:
        detalle = [
            {"campo": ".".join(str(p) for p in e.get("loc", ())), "mensaje": e.get("msg", "")}
            for e in exc.errors()
        ]
        return respuesta_error(
            422, "PARAMETRO_INVALIDO", "Hay parámetros inválidos en la consulta.", detalle
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codigo, mensaje = _HTTP_GENERICOS.get(
            exc.status_code, (f"HTTP_{exc.status_code}", str(exc.detail))
        )
        respuesta = respuesta_error(exc.status_code, codigo, mensaje)
        if exc.headers:
            respuesta.headers.update(exc.headers)
        return respuesta
