"""Modelo de /health (docs/03 §health)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class Health(BaseModel):
    estado: Literal["ok", "degradado"] = Field(
        description="`ok` si los datos están listos; `degradado` si no se pudieron abrir."
    )
    datos_listos: bool = Field(description="DuckDB abrió los Parquet correctamente.")
    data_version: str | None = Field(description="Versión de datos activa (`null` sin datos).")
    fecha_max: date | None = Field(description="Último día con datos (`null` sin datos).")
