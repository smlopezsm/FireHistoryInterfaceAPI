"""Contrato de anomalías mensuales."""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.zonas import PedidoZona

Referencia = Literal["observada", "estimada"]
Categoria = Literal["muy_por_debajo", "por_debajo", "normal", "por_encima", "muy_por_encima"]


class PedidoAnomalia(PedidoZona):
    mes: str | None = Field(None, description="Mes a evaluar (YYYY-MM).")


class Anomalia(BaseModel):
    mes: str = Field(description="Mes evaluado (`YYYY-MM`).")
    valor: float = Field(description="Focos armonizados del mes.")
    referencia: Referencia = Field(
        description=(
            "Era con la que se compara, según la fecha: `observada` desde el primer mes "
            "completo con referencia VIIRS (`2012-02`) o `estimada` antes (desde MODIS). El "
            "mes evaluado se compara solo con años de su misma era (docs/04 §6)."
        )
    )
    mediana: float | None = Field(
        description="Mediana del mismo mes en los demás años completos de la misma era."
    )
    p25: float | None = Field(description="Cuartil inferior histórico.")
    p75: float | None = Field(description="Cuartil superior histórico.")
    razon: float | None = Field(description="`valor / mediana`; `null` si la mediana es 0.")
    percentil: float | None = Field(
        description="Porcentaje de años con un valor menor o igual (0–100)."
    )
    categoria: Categoria | None = Field(
        description="Categoría; `null` con menos de 10 años o si el mes está incompleto."
    )
    anios_usados: int = Field(description="Cantidad de años en la comparación.")
