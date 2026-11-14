"""Endpoints de anomalía mensual."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.db import Datos
from app.deps import DatosListosDep, ZonaQueryDep
from app.schemas.anomalia import Anomalia, PedidoAnomalia
from app.schemas.armonizacion import PeriodoConsulta
from app.schemas.zonas import PedidoZona
from app.services.anomalia import comparar
from app.services.armonizacion import calcular_meses
from app.services.zonas import resolver_zona

router = APIRouter(tags=["focos"])


def _anomalia(datos: Datos, pedido: PedidoZona, mes: str | None) -> Anomalia:
    zona = resolver_zona(datos, pedido)
    return comparar(calcular_meses(datos, zona, PeriodoConsulta()), mes)


@router.get("/anomalia", summary="Anomalía mensual respecto del histórico")
def anomalia_get(
    datos: DatosListosDep,
    zona: ZonaQueryDep,
    mes: Annotated[str | None, Query(description="Mes a evaluar (YYYY-MM).")] = None,
) -> Anomalia:
    return _anomalia(datos, zona, mes)


@router.post("/anomalia", summary="Anomalía mensual para una geometría")
def anomalia_post(datos: DatosListosDep, pedido: PedidoAnomalia) -> Anomalia:
    return _anomalia(datos, pedido, pedido.mes)
