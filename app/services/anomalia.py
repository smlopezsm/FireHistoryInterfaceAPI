"""Comparación de un mes con las observaciones históricas del mismo mes calendario."""

from bisect import bisect_right
from math import ceil
from statistics import median

from app.errores import ApiError
from app.schemas.anomalia import Anomalia, Categoria, Referencia
from app.services.armonizacion import Acumulado


def _cuantil(muestra: list[float], probabilidad: float) -> float:
    return muestra[ceil(len(muestra) * probabilidad) - 1]


def _categoria(valor: float, muestra: list[float]) -> Categoria:
    if valor < _cuantil(muestra, 0.1):
        return "muy_por_debajo"
    if valor < _cuantil(muestra, 0.25):
        return "por_debajo"
    if valor > _cuantil(muestra, 0.9):
        return "muy_por_encima"
    if valor > _cuantil(muestra, 0.75):
        return "por_encima"
    return "normal"


def _era(mes: Acumulado) -> Referencia:
    """`observada` si a lo sumo el 10 % de los días se estimó (mismo umbral que `alta`)."""
    return "observada" if mes.estimados <= 0.1 * mes.dias else "estimada"


def comparar(meses: dict[str, Acumulado], mes: str | None) -> Anomalia:
    if mes is None:
        mes = next((p for p in reversed(meses) if not meses[p].parcial), None)
    if mes is None or mes not in meses:
        raise ApiError(400, "PERIODO_INVALIDO", "Indicá un mes disponible en formato YYYY-MM.")

    actual = meses[mes]
    # H1: 2001–2011 (estimado desde MODIS) y 2012+ (observado) tienen niveles distintos;
    # cada mes se compara solo con años de su misma era.
    era = _era(actual)
    valor = round(actual.armonizado, 1)
    muestra = sorted(
        round(datos.armonizado, 1)
        for periodo, datos in meses.items()
        if periodo != mes and periodo[5:] == mes[5:] and not datos.parcial and _era(datos) == era
    )
    n = len(muestra)
    central = median(muestra) if n else None
    return Anomalia(
        mes=mes,
        valor=valor,
        referencia=era,
        mediana=central,
        p25=_cuantil(muestra, 0.25) if n else None,
        p75=_cuantil(muestra, 0.75) if n else None,
        razon=valor / central if central else None,
        percentil=100 * bisect_right(muestra, valor) / n if n else None,
        categoria=_categoria(valor, muestra) if n >= 10 and not actual.parcial else None,
        anios_usados=n,
    )
