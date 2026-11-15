"""Validación de períodos diarios (`YYYY-MM-DD`) contra el rango de los datos."""

from __future__ import annotations

from datetime import date

from app.db import Datos
from app.errores import ApiError, datos_no_disponibles


def periodo_diario(
    datos: Datos, desde: str, hasta: str, *, max_dias: int | None = None
) -> tuple[date, date]:
    """Devuelve `(inicio, fin)` si las fechas son ISO exactas, están ordenadas, caen dentro de
    `[fecha_min, fecha_max]` y, con `max_dias`, abarcan como máximo esa cantidad de días."""
    metadata = datos.metadata
    if metadata is None:
        raise datos_no_disponibles()
    try:
        inicio, fin = date.fromisoformat(desde), date.fromisoformat(hasta)
        if (
            desde != inicio.isoformat()
            or hasta != fin.isoformat()
            or not metadata.fecha_min <= inicio <= fin <= metadata.fecha_max
            or (max_dias is not None and (fin - inicio).days >= max_dias)
        ):
            raise ValueError
    except ValueError:
        mensaje = (
            f"Indicá un período disponible de hasta {max_dias} días (YYYY-MM-DD)."
            if max_dias is not None
            else "Indicá un período válido (YYYY-MM-DD)."
        )
        raise ApiError(400, "PERIODO_INVALIDO", mensaje) from None
    return inicio, fin
