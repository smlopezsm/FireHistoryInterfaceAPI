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


@router.get("/calendario", summary="Calendario mensual de focos")
def calendario_get(
    datos: DatosListosDep, zona: ZonaQueryDep, consulta: Annotated[PeriodoConsulta, Query()]
) -> Calendario:
    return _calendario(datos, zona, consulta)


@router.post("/calendario", summary="Calendario mensual de focos para una geometría")
def calendario_post(datos: DatosListosDep, pedido: PedidoCalendario) -> Calendario:
    return _calendario(datos, pedido, pedido)


@router.get("/serie", summary="Serie mensual o anual de focos")
def serie_get(
    datos: DatosListosDep,
    zona: ZonaQueryDep,
    consulta: Annotated[PeriodoConsulta, Query()],
    granularidad: Granularidad = "mes",
) -> Serie:
    return _serie(datos, zona, consulta, granularidad)


@router.post("/serie", summary="Serie mensual o anual de focos para una geometría")
def serie_post(datos: DatosListosDep, pedido: PedidoSerie) -> Serie:
    return _serie(datos, pedido, pedido, pedido.granularidad)
