"""Modelos de /metadata (docs/02 §9 y docs/03 §metadata)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class ReferenciaViirs(BaseModel):
    satelite: str = Field(description="Satélite VIIRS de referencia (`SNPP` o `N20`).")
    desde: date = Field(description="Primer día en que es la referencia.")
    hasta: date | None = Field(description="Último día; `null` si sigue vigente.")


class MetadataArchivo(BaseModel):
    """Contenido de `metadata.json`, tal como lo publica el pipeline."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field(description="Versión del formato de los archivos.")
    data_version: str = Field(description="Versión de los datos activos.")
    factores_version: str = Field(description="Versión de la tabla de factores.")
    fecha_min: date = Field(description="Primer día con datos.")
    fecha_max: date = Field(description="Último día con datos.")
    fecha_ultimo_sp: date = Field(
        description="Último día con datos científicos (SP); después hay NRT."
    )
    referencia_viirs: list[ReferenciaViirs] = Field(
        description="Satélite VIIRS usado como referencia en cada período."
    )
    fuentes: list[str] = Field(description="Fuentes de los datos.")
    pipeline_commit: str = Field(description="Commit del pipeline que generó los datos.")


class Metadata(MetadataArchivo):
    """Respuesta de `/metadata`."""

    celdas_total: int = Field(description="Cantidad de celdas de 5 × 5 km de la máscara.")
    provincias_total: int = Field(description="Cantidad de provincias.")
