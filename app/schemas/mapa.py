"""Modelos GeoJSON de las capas del mapa (docs/03 §mapa)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.armonizacion import Estado


class GeometriaPoligono(BaseModel):
    type: Literal["Polygon"]
    coordinates: list[list[list[float]]] = Field(description="Anillo de la celda (lon, lat).")


class PropiedadesCelda(BaseModel):
    cell_id: int = Field(description="Celda de 5 × 5 km.")
    provincia_id: str = Field(description="Provincia a la que pertenece la celda.")
    valor: float = Field(description="Focos de la capa pedida en el período (1 decimal).")
    modis: int = Field(description="Focos MODIS crudos (Terra + Aqua).")
    viirs: int | None = Field(
        description="Focos VIIRS observados del satélite de referencia; `null` si no hubo."
    )
    estado: Estado = Field(description="`observado`, `estimado` o `mixto` en el período.")


class FeatureCelda(BaseModel):
    type: Literal["Feature"]
    geometry: GeometriaPoligono
    properties: PropiedadesCelda


class ColeccionCeldas(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[FeatureCelda]


class GeometriaPunto(BaseModel):
    type: Literal["Point"]
    coordinates: list[float] = Field(description="`[lon, lat]`.", min_length=2, max_length=2)


class PropiedadesIndustrial(BaseModel):
    motivo: str = Field(description="Por qué se excluye el punto.")
    n_focos: int = Field(description="Focos excluidos en ese punto.")
    provincia_id: str = Field(description="Provincia.")


class FeatureIndustrial(BaseModel):
    type: Literal["Feature"]
    geometry: GeometriaPunto
    properties: PropiedadesIndustrial


class ColeccionIndustriales(BaseModel):
    type: Literal["FeatureCollection"]
    features: list[FeatureIndustrial]
