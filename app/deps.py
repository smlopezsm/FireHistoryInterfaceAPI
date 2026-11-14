"""Dependencias comunes de los routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.db import Datos
from app.errores import datos_no_disponibles


def obtener_datos(request: Request) -> Datos:
    datos: Datos = request.app.state.datos
    return datos


def datos_listos(datos: Annotated[Datos, Depends(obtener_datos)]) -> Datos:
    """Exige datos abiertos; si no, responde 503 `DATOS_NO_DISPONIBLES`."""
    if not datos.listo:
        raise datos_no_disponibles()
    return datos


DatosDep = Annotated[Datos, Depends(obtener_datos)]
DatosListosDep = Annotated[Datos, Depends(datos_listos)]
