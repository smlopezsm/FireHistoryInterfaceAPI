"""Modelo de /provincias (docs/03 §provincias)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Provincia(BaseModel):
    provincia_id: str = Field(description="Código INDEC.", examples=["74"])
    nombre: str = Field(description="Nombre oficial corto.", examples=["San Luis"])
    region: str = Field(description="Región: NOA, NEA, Pampeana, Cuyo o Patagonia.")
    bbox: list[float] = Field(
        description="`[oeste, sur, este, norte]` en grados.",
        examples=[[-67.38, -36.0, -64.88, -31.83]],
        min_length=4,
        max_length=4,
    )
    geometria: dict[str, Any] | None = Field(
        description="Polígono simplificado (GeoJSON); solo si se pidió `geometria=true`."
    )
