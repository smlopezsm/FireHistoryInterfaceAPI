"""Endpoints de anomalía mensual."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.db import Datos
from app.deps import DatosListosDep, ZonaQueryDep
from app.schemas.anomalia import Anomalia, PedidoAnomalia
from app.schemas.armonizacion import PeriodoConsulta
from app.schemas.zonas import PedidoZona
from app.services.anomalia import comparar, primer_mes_observado
from app.services.armonizacion import calcular_meses
from app.services.zonas import resolver_zona

router = APIRouter(tags=["focos"])


def _anomalia(datos: Datos, pedido: PedidoZona, mes: str | None) -> Anomalia:
    zona = resolver_zona(datos, pedido)
    meses = calcular_meses(datos, zona, PeriodoConsulta())
    assert datos.metadata is not None  # calcular_meses ya lo exige
    # Era observada desde el primer mes completo con referencia VIIRS (docs/04 §6).
    inicios = [r.desde for r in datos.metadata.referencia_viirs]
    inicio = primer_mes_observado(min(inicios)) if inicios else "9999-12"
    return comparar(meses, mes, inicio_observado=inicio)


@router.get(
    "/anomalia",
    summary="Anomalía mensual respecto del histórico",
    description=(
        "Compara un mes con el mismo mes calendario de los demás años completos (mediana, "
        "cuartiles, percentil y categoría). La categoría es `null` con menos de 10 años o si el "
        "mes está incompleto. Sin `mes`, evalúa el último mes completo. La zona es **una sola** "
        "de `provincia_id` o `bbox` (por query); la versión POST acepta además un polígono "
        "GeoJSON en `geometria`."
    ),
)
def anomalia_get(
    datos: DatosListosDep,
    zona: ZonaQueryDep,
    mes: Annotated[str | None, Query(description="Mes a evaluar (YYYY-MM).")] = None,
) -> Anomalia:
    return _anomalia(datos, zona, mes)


@router.post(
    "/anomalia",
    summary="Anomalía mensual para una geometría",
    description=(
        "Igual que `GET /anomalia`, con los parámetros en el cuerpo JSON y polígono opcional en "
        "`geometria`."
    ),
)
def anomalia_post(datos: DatosListosDep, pedido: PedidoAnomalia) -> Anomalia:
    return _anomalia(datos, pedido, pedido.mes)
