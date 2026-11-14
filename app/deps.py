"""Dependencias comunes de los routers."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request

from app.db import Datos
from app.errores import datos_no_disponibles
from app.schemas.zonas import DESC_BBOX, DESC_PROVINCIA, PedidoZona


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


def zona_desde_query(
    provincia_id: Annotated[str | None, Query(description=DESC_PROVINCIA, examples=["74"])] = None,
    bbox: Annotated[
        str | None, Query(description=DESC_BBOX, examples=["-67.4,-36.0,-64.9,-31.8"])
    ] = None,
) -> PedidoZona:
    """Zona para los endpoints GET (el polígono solo se acepta por POST)."""
    return PedidoZona(provincia_id=provincia_id, bbox=bbox)


ZonaQueryDep = Annotated[PedidoZona, Depends(zona_desde_query)]
