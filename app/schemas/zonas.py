"""Modelos de la zona de consulta (docs/03 §Convenciones)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DESC_PROVINCIA = "Código INDEC de la provincia, por ejemplo `74` (San Luis)."
DESC_REGION = "Nombre de la región, por ejemplo `NOA`, `NEA`, `Pampeana`, `Cuyo` o `Patagonia`."
DESC_BBOX = "Rectángulo `oeste,sur,este,norte` en grados (EPSG:4326)."
DESC_GEOMETRIA = (
    "Polígono GeoJSON (`Polygon` o `MultiPolygon`, EPSG:4326) de hasta 2.000 vértices. "
    "Entran las celdas cuyo centroide cae dentro."
)


class PedidoZona(BaseModel):
    """Zona de consulta: **una sola** de `provincia_id`, `region`, `bbox` o `geometria`."""

    provincia_id: str | None = Field(None, description=DESC_PROVINCIA, examples=["74"])
    region: str | None = Field(None, description=DESC_REGION, examples=["Cuyo"])
    bbox: str | None = Field(None, description=DESC_BBOX, examples=["-67.4,-36.0,-64.9,-31.8"])
    geometria: dict[str, Any] | None = Field(None, description=DESC_GEOMETRIA)


class Zona(BaseModel):
    """Zona resuelta, tal como se devuelve en las respuestas."""

    tipo: Literal["provincia", "region", "bbox", "geometria"] = Field(
        description="Cómo se pidió la zona."
    )
    id: str | None = Field(
        description="Código de provincia o nombre de región (si `tipo` es `provincia` o `region`)."
    )
    bbox: list[float] | None = Field(
        description="`[oeste, sur, este, norte]` del bbox pedido o del polígono."
    )
    celdas: int = Field(description="Cantidad de celdas de 5 × 5 km de la zona.")
    area_km2: float = Field(description="Área de Argentina dentro de esas celdas, en km².")
