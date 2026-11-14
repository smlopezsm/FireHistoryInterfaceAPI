"""Endpoints de calendario y serie de focos."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.db import Datos
from app.deps import DatosListosDep, ZonaQueryDep
from app.errores import datos_no_disponibles
from app.schemas.armonizacion import (
    Calendario,
    Granularidad,
    PedidoCalendario,
    PedidoSerie,
    PeriodoConsulta,
    Serie,
)
from app.schemas.zonas import PedidoZona
from app.services.armonizacion import agrupar_anios, calcular_meses, pocos_datos, resumir
from app.services.zonas import resolver_zona

router = APIRouter(tags=["focos"])


def _calendario(datos: Datos, zona_pedida: PedidoZona, consulta: PeriodoConsulta) -> Calendario:
    zona = resolver_zona(datos, zona_pedida)
    data_version = datos.data_version
    if data_version is None:
        raise datos_no_disponibles()
    meses = calcular_meses(datos, zona, consulta)
    confianza_baja = pocos_datos(zona)
    puntos = [mes.punto(periodo, confianza_baja) for periodo, mes in meses.items()]
    return Calendario(
        zona=zona.respuesta(),
        capa=consulta.capa,
        unidad="focos MODIS" if consulta.capa == "modis" else "focos (escala VIIRS S-NPP)",
        meses=puntos,
        resumen=resumir(puntos, consulta.capa),
        data_version=data_version,
    )


def _serie(
    datos: Datos, zona_pedida: PedidoZona, consulta: PeriodoConsulta, granularidad: Granularidad
) -> Serie:
    zona = resolver_zona(datos, zona_pedida)
    meses = calcular_meses(datos, zona, consulta)
    periodos = agrupar_anios(meses) if granularidad == "anio" else meses
    confianza_baja = pocos_datos(zona)
    return Serie(
        zona=zona.respuesta(),
        granularidad=granularidad,
        puntos=[valor.punto(periodo, confianza_baja) for periodo, valor in periodos.items()],
    )


@router.get(
    "/calendario",
    summary="Calendario mensual de focos",
    description=(
        "Matriz mes × año de focos de la zona, a escala VIIRS S-NPP. Cada mes indica si el valor "
        "es observado, estimado (MODIS × factor provincia × mes) o mixto, con su rango del 80 % y"
        " su confianza. `capa` solo cambia `unidad` y `resumen`. La zona es **una sola** de "
        "`provincia_id` o `bbox` (por query); la versión POST acepta además un polígono GeoJSON "
        "en `geometria`."
    ),
)
def calendario_get(
    datos: DatosListosDep, zona: ZonaQueryDep, consulta: Annotated[PeriodoConsulta, Query()]
) -> Calendario:
    return _calendario(datos, zona, consulta)


@router.post(
    "/calendario",
    summary="Calendario mensual de focos para una geometría",
    description=(
        "Igual que `GET /calendario`, con los parámetros en el cuerpo JSON. Permite enviar un "
        "polígono GeoJSON en `geometria` (hasta 2.000 vértices)."
    ),
)
def calendario_post(datos: DatosListosDep, pedido: PedidoCalendario) -> Calendario:
    return _calendario(datos, pedido, pedido)


@router.get(
    "/serie",
    summary="Serie mensual o anual de focos",
    description=(
        "Serie de la zona por mes (`granularidad=mes`) o por año (`anio`). Cada punto tiene los "
        "mismos campos que los meses de `/calendario`; en la serie anual se suman los meses y la "
        "fracción estimada se calcula sobre los días del año. La zona es **una sola** de "
        "`provincia_id` o `bbox` (por query); la versión POST acepta además un polígono GeoJSON "
        "en `geometria`."
    ),
)
def serie_get(
    datos: DatosListosDep,
    zona: ZonaQueryDep,
    consulta: Annotated[PeriodoConsulta, Query()],
    granularidad: Granularidad = "mes",
) -> Serie:
    return _serie(datos, zona, consulta, granularidad)


@router.post(
    "/serie",
    summary="Serie mensual o anual de focos para una geometría",
    description=(
        "Igual que `GET /serie`, con los parámetros en el cuerpo JSON y polígono opcional en "
        "`geometria`."
    ),
)
def serie_post(datos: DatosListosDep, pedido: PedidoSerie) -> Serie:
    return _serie(datos, pedido, pedido, pedido.granularidad)
