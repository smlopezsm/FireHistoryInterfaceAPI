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
    periodo: str = Field(description="Mes `YYYY-MM` (o año `YYYY` en la serie anual).")
    modis: int = Field(description="Focos MODIS crudos (Terra + Aqua).")
    viirs: int | None = Field(
        description="Focos VIIRS observados del satélite de referencia; `null` si no hubo."
    )
    armonizado: float = Field(description="Valor a mostrar, en escala VIIRS S-NPP (1 decimal).")
    minimo: float = Field(description="Límite inferior del rango del 80 %.")
    maximo: float = Field(description="Límite superior del rango del 80 %.")
    estado: Estado = Field(description="`observado`, `estimado` o `mixto`.")
    frac_estimada: float = Field(
        description="Fracción de días estimados (0–1), sobre los días con datos."
    )
    confianza: Confianza = Field(description="`alta`, `media` o `baja` (docs/04 §5).")
    parcial: bool = Field(description="`true` si incluye el mes en curso, todavía incompleto.")


class Resumen(BaseModel):
    max_mes: str | None = Field(description="Mes con el valor más alto de la capa pedida.")
    max_anio: int | None = Field(description="Año con el total más alto de la capa pedida.")
    total: float | None = Field(description="Suma de la capa pedida en el período.")
    mediana_mensual: float | None = Field(description="Mediana mensual de la capa pedida.")


class Calendario(BaseModel):
    zona: Zona = Field(description="Zona resuelta.")
    capa: Capa = Field(description="Capa pedida.")
    unidad: str = Field(description="Unidad de los valores de la capa.")
    meses: list[Punto] = Field(description="Un elemento por mes del período.")
    resumen: Resumen = Field(description="Resumen de la capa pedida.")
    data_version: str = Field(description="Versión de los datos (para caché y trazabilidad).")


class Serie(BaseModel):
    zona: Zona = Field(description="Zona resuelta.")
    granularidad: Granularidad = Field(description="`mes` o `anio`.")
    puntos: list[Punto] = Field(description="Un elemento por mes o por año.")
