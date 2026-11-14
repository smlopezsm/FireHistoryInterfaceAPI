"""Contrato de anomalías mensuales."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.zonas import PedidoZona

Categoria = Literal["muy_por_debajo", "por_debajo", "normal", "por_encima", "muy_por_encima"]


class PedidoAnomalia(PedidoZona):
    mes: str | None = Field(None, description="Mes a evaluar (YYYY-MM).")


class Anomalia(BaseModel):
    mes: str
    valor: float
    mediana: float | None
    p25: float | None
    p75: float | None
    razon: float | None
    percentil: float | None
    categoria: Categoria | None
    anios_usados: int
