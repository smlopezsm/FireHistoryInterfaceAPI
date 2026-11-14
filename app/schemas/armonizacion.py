"""Contratos de calendario y serie."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.zonas import PedidoZona, Zona

Capa = Literal["armonizado", "modis", "viirs"]
Granularidad = Literal["mes", "anio"]
Confianza = Literal["alta", "media", "baja"]
Estado = Literal["observado", "estimado", "mixto"]


class PeriodoConsulta(BaseModel):
    desde: str | None = Field(None, description="Primer mes (YYYY-MM).")
    hasta: str | None = Field(None, description="Último mes (YYYY-MM).")
    capa: Capa = Field("armonizado", description="Capa de conteos.")


class PedidoCalendario(PedidoZona, PeriodoConsulta):
    pass


class PedidoSerie(PedidoCalendario):
    granularidad: Granularidad = "mes"


class Punto(BaseModel):
    periodo: str
    modis: int
    viirs: int | None
    armonizado: float
    minimo: float
    maximo: float
    estado: Estado
    frac_estimada: float
    confianza: Confianza
    parcial: bool


class Resumen(BaseModel):
    max_mes: str | None
    max_anio: int | None
    total: float | None
    mediana_mensual: float | None


class Calendario(BaseModel):
    zona: Zona
    capa: Capa
    unidad: str
    meses: list[Punto]
    resumen: Resumen
    data_version: str


class Serie(BaseModel):
    zona: Zona
    granularidad: Granularidad
    puntos: list[Punto]
