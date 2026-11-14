"""Descargas CSV del calendario y de focos individuales."""

import csv
from collections.abc import Iterator
from datetime import date
from tempfile import TemporaryFile
from typing import Annotated, Literal, TextIO

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from app.db import Datos
from app.deps import DatosListosDep, ZonaQueryDep
from app.errores import ApiError, datos_no_disponibles
from app.schemas.armonizacion import PedidoCalendario, PeriodoConsulta
from app.schemas.zonas import PedidoZona
from app.services.armonizacion import calcular_meses, pocos_datos
from app.services.zonas import ZonaResuelta, resolver_zona

router = APIRouter(prefix="/descargas", tags=["descargas"])
Sensor = Literal["todos", "MODIS", "VIIRS"]

FOCOS = (
    "fecha",
    "hora_utc",
    "satelite",
    "sensor",
    "lat",
    "lon",
    "confianza",
    "frp_mw",
    "dia_noche",
    "fuente",
    "provincia_id",
    "cell_id",
)
CALENDARIO = (
    "periodo",
    "modis",
    "viirs",
    "armonizado",
    "minimo",
    "maximo",
    "estado",
    "frac_estimada",
    "confianza",
)


class PedidoFocos(PedidoZona):
    desde: str
    hasta: str
    sensor: Sensor = "todos"


def _nombre(zona: ZonaResuelta) -> str:
    if zona.tipo == "provincia":
        codigo = zona.id or ""
        seguro = "".join(c for c in codigo if c.isascii() and c.isalnum())
        return f"provincia-{seguro}"
    return zona.tipo


def _respuesta(archivo: TextIO, nombre: str) -> StreamingResponse:
    archivo.seek(0)

    def emitir() -> Iterator[str]:
        with archivo:
            while bloque := archivo.read(65536):
                yield bloque

    return StreamingResponse(
        emitir(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre}.csv"'},
        background=BackgroundTask(archivo.close),
    )


def _focos(
    datos: Datos, pedido: PedidoZona, desde: str, hasta: str, sensor: Sensor, maximo: int
) -> StreamingResponse:
    zona = resolver_zona(datos, pedido)
    metadata = datos.metadata
    if metadata is None:
        raise datos_no_disponibles()
    try:
        inicio, fin = date.fromisoformat(desde), date.fromisoformat(hasta)
        if (
            inicio.isoformat() != desde
            or fin.isoformat() != hasta
            or not metadata.fecha_min <= inicio <= fin <= metadata.fecha_max
        ):
            raise ValueError
    except ValueError:
        raise ApiError(400, "PERIODO_INVALIDO", "Indicá un período válido (YYYY-MM-DD).") from None

    filtro = """
        FROM focos WHERE anio BETWEEN ? AND ? AND fecha BETWEEN ? AND ?
        AND cell_id IN (SELECT unnest(?::INTEGER[]))
        AND (? = 'todos' OR sensor = ?)
    """
    parametros = [inicio.year, fin.year, inicio, fin, zona.celdas_ids, sensor, sensor]
    archivo = TemporaryFile(  # noqa: SIM115 - la respuesta adquiere el archivo
        mode="w+t", encoding="utf-8", newline=""
    )
    try:
        archivo.write("# Fuente: NASA FIRMS (MODIS C6.1 y VIIRS 375 m)\r\n")
        escritor = csv.writer(archivo)
        escritor.writerow(FOCOS)
        datos.exportar_filas(filtro, ", ".join(FOCOS), parametros, maximo, escritor.writerows)
        return _respuesta(archivo, f"focos_{_nombre(zona)}_{desde}_{hasta}")
    except BaseException:
        archivo.close()
        raise


def _calendario(datos: Datos, pedido: PedidoZona, consulta: PeriodoConsulta) -> StreamingResponse:
    zona = resolver_zona(datos, pedido)
    meses = calcular_meses(datos, zona, consulta)
    archivo = TemporaryFile(  # noqa: SIM115 - la respuesta adquiere el archivo
        mode="w+t", encoding="utf-8", newline=""
    )
    try:
        escritor = csv.DictWriter(archivo, CALENDARIO, extrasaction="ignore")
        escritor.writeheader()
        confianza_baja = pocos_datos(zona)
        for periodo, mes in meses.items():
            escritor.writerow(mes.punto(periodo, confianza_baja).model_dump())
        return _respuesta(archivo, f"calendario_{_nombre(zona)}")
    except BaseException:
        archivo.close()
        raise


@router.get(
    "/focos.csv", summary="Descargar focos individuales en CSV", response_class=StreamingResponse
)
def focos_get(
    request: Request,
    datos: DatosListosDep,
    zona: ZonaQueryDep,
    desde: str,
    hasta: str,
    sensor: Sensor = "todos",
) -> StreamingResponse:
    return _focos(datos, zona, desde, hasta, sensor, request.app.state.settings.max_filas_csv)


@router.post(
    "/focos.csv", summary="Descargar focos por geometría en CSV", response_class=StreamingResponse
)
def focos_post(request: Request, datos: DatosListosDep, pedido: PedidoFocos) -> StreamingResponse:
    return _focos(
        datos,
        pedido,
        pedido.desde,
        pedido.hasta,
        pedido.sensor,
        request.app.state.settings.max_filas_csv,
    )


@router.get(
    "/calendario.csv", summary="Descargar el calendario en CSV", response_class=StreamingResponse
)
def calendario_get(
    datos: DatosListosDep,
    zona: ZonaQueryDep,
    consulta: Annotated[PeriodoConsulta, Query()],
) -> StreamingResponse:
    return _calendario(datos, zona, consulta)


@router.post(
    "/calendario.csv",
    summary="Descargar el calendario por geometría en CSV",
    response_class=StreamingResponse,
)
def calendario_post(datos: DatosListosDep, pedido: PedidoCalendario) -> StreamingResponse:
    return _calendario(datos, pedido, pedido)
