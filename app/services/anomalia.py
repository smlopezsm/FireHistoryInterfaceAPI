"""Comparación de un mes con las observaciones históricas del mismo mes calendario."""

from bisect import bisect_right
from datetime import date
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


def primer_mes_observado(inicio_viirs: date) -> str:
    """Primer mes (`YYYY-MM`) completo con referencia VIIRS: el de `inicio_viirs` si empieza
    el día 1, si no el siguiente. Con S-NPP desde 2012-01-20 es `2012-02`."""
    if inicio_viirs.day == 1:
        return inicio_viirs.isoformat()[:7]
    anio, mes = inicio_viirs.year + inicio_viirs.month // 12, inicio_viirs.month % 12 + 1
    return f"{anio:04d}-{mes:02d}"


def _era(periodo: str, inicio_observado: str) -> Referencia:
    """La era sale de la fecha, no de `frac_estimada`: un mes de la época VIIRS con la
    referencia caída varios días sigue comparándose con los años observados."""
    return "observada" if periodo >= inicio_observado else "estimada"


def comparar(meses: dict[str, Acumulado], mes: str | None, *, inicio_observado: str) -> Anomalia:
    if mes is None:
        mes = next((p for p in reversed(meses) if not meses[p].parcial), None)
    if mes is None or mes not in meses:
        raise ApiError(400, "PERIODO_INVALIDO", "Indicá un mes disponible en formato YYYY-MM.")

    actual = meses[mes]
    # H1: 2001–2011 (estimado desde MODIS) y 2012+ (observado) tienen niveles distintos;
    # cada mes se compara solo con años de su misma era.
    era = _era(mes, inicio_observado)
    valor = round(actual.armonizado, 1)
    muestra = sorted(
        round(datos.armonizado, 1)
        for periodo, datos in meses.items()
        if periodo != mes
        and periodo[5:] == mes[5:]
        and not datos.parcial
        and _era(periodo, inicio_observado) == era
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
