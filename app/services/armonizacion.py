"""Armonización mensual de focos por provincia según docs/04."""

import re
from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median
from typing import Any

from app.db import Datos
from app.errores import ApiError, datos_no_disponibles
from app.schemas.armonizacion import Capa, Confianza, Estado, PeriodoConsulta, Punto, Resumen
from app.schemas.metadata import ReferenciaViirs
from app.services.zonas import ZonaResuelta

POCOS_DATOS = {"94", "78", "02"}


def cobertura_sql(referencias: list[ReferenciaViirs]) -> str:
    """CTE con la referencia VIIRS de cada día (de `metadata.referencia_viirs`) y si operó.

    `modis_operativo` indica si estuvo el MODIS con que se estima ese día: Terra antes
    de 2002-07-04 y Terra + Aqua desde entonces (docs/04 §5). Sin fila cuenta como caído.

    Los días operativos se cuentan independientemente de las filas de focos. Los valores
    vienen de un modelo validado (satélite `SNPP` o `N20` y fechas), así que es seguro
    escribirlos en el SQL.
    """
    casos = []
    for ref in referencias:
        hasta = f" AND dia <= DATE '{ref.hasta.isoformat()}'" if ref.hasta else ""
        casos.append(f"WHEN dia >= DATE '{ref.desde.isoformat()}'{hasta} THEN '{ref.satelite}'")
    referencia = f"CASE {' '.join(casos)} END" if casos else "NULL"
    return f"""
WITH dias AS (
    SELECT CAST(dia AS DATE) AS fecha, {referencia} AS referencia
    FROM generate_series(?::DATE, ?::DATE, INTERVAL 1 DAY) AS fechas(dia)
), cobertura AS (
    SELECT d.fecha, d.referencia, coalesce(s.operativo, false) AS operativo,
           coalesce(t.operativo, false)
               AND (d.fecha < DATE '2002-07-04' OR coalesce(a.operativo, false))
               AS modis_operativo
    FROM dias d
    LEFT JOIN satelite_operativo s ON s.fecha = d.fecha AND s.satelite = d.referencia
    LEFT JOIN satelite_operativo t ON t.fecha = d.fecha AND t.satelite = 'Terra'
    LEFT JOIN satelite_operativo a ON a.fecha = d.fecha AND a.satelite = 'Aqua'
)
"""


CONTEOS_SQL = """
           sum(c.n_terra + c.n_aqua) AS modis,
           sum(CASE WHEN d.operativo AND d.referencia = 'SNPP' THEN c.n_snpp
                    WHEN d.operativo AND d.referencia = 'N20' THEN c.n_n20
                    ELSE 0 END) AS obs,
           sum(CASE WHEN NOT d.operativo AND c.fecha < DATE '2002-07-04'
                    THEN c.n_terra ELSE 0 END) AS est_terra,
           sum(CASE WHEN NOT d.operativo AND c.fecha >= DATE '2002-07-04'
                    THEN c.n_terra + c.n_aqua ELSE 0 END) AS est_modis
"""

AGREGAR = """, meses AS (
    SELECT date_trunc('month', fecha)::DATE AS mes, count(*) AS dias,
           count(*) FILTER (WHERE NOT operativo) AS estimados,
           count(*) FILTER (WHERE NOT operativo AND NOT modis_operativo) AS sin_modis
    FROM cobertura GROUP BY 1
), focos_mes AS (
    SELECT date_trunc('month', c.fecha)::DATE AS mes, c.provincia_id,
           {conteos}
    FROM conteos_celda_dia c JOIN cobertura d ON c.fecha = d.fecha
    WHERE c.anio BETWEEN ? AND ?
      AND c.fecha BETWEEN ? AND ?
      AND c.cell_id IN (SELECT cell_id FROM zona_celdas)
    GROUP BY 1, 2
)
SELECT m.*, p.provincia_id, p.region, coalesce(f.modis, 0) AS modis,
       coalesce(f.obs, 0) AS obs, coalesce(f.est_terra, 0) AS est_terra,
       coalesce(f.est_modis, 0) AS est_modis
FROM meses m CROSS JOIN dim_provincias p
LEFT JOIN focos_mes f ON f.mes = m.mes AND f.provincia_id = p.provincia_id
WHERE p.provincia_id IN (SELECT unnest(?::VARCHAR[]))
ORDER BY m.mes, p.provincia_id
"""


@dataclass
class Acumulado:
    dias: int = 0
    estimados: int = 0
    obs: int = 0
    modis: int = 0
    est_terra: int = 0
    est_modis: int = 0
    sin_modis: int = 0
    armonizado: float = 0
    est_no_provincial: float = 0
    minimo: float = 0
    maximo: float = 0
    parcial: bool = False

    def punto(self, periodo: str, pocos_datos: bool) -> Punto:
        frac = self.estimados / self.dias
        estado: Estado = "estimado" if frac == 1 else "mixto" if frac else "observado"
        # docs/04 §5: lo observado (frac ≤ 0,1) es "alta" en cualquier zona; "pocos datos"
        # solo baja la confianza de lo estimado.
        # H9: si más del 10 % de los días estimados no tuvo MODIS, el estimado puede quedar
        # corto. H13: si más de la mitad de lo estimado usa factores de la región o del
        # país, baja un nivel. Ver docs/04 §5.
        estimado = self.armonizado - self.obs
        confianza: Confianza = "baja"
        if frac <= 0.1:
            confianza = "alta"
        elif (
            not pocos_datos
            and self.est_terra == 0
            and self.est_modis >= 21
            and self.sin_modis <= 0.1 * self.estimados
            and self.est_no_provincial <= estimado / 2
        ):
            confianza = "media"
        return Punto(
            periodo=periodo,
            modis=self.modis,
            viirs=self.obs if self.estimados < self.dias else None,
            armonizado=round(self.armonizado, 1),
            minimo=round(self.minimo, 1),
            maximo=round(self.maximo, 1),
            estado=estado,
            frac_estimada=frac,
            dias_sin_modis=self.sin_modis,
            confianza=confianza,
            parcial=self.parcial,
        )

    def sumar_mes(self, mes: "Acumulado") -> None:
        self.dias += mes.dias
        self.estimados += mes.estimados
        self.obs += mes.obs
        self.modis += mes.modis
        self.est_terra += mes.est_terra
        self.est_modis += mes.est_modis
        self.sin_modis += mes.sin_modis
        self.armonizado += mes.armonizado
        self.est_no_provincial += mes.est_no_provincial
        self.minimo += mes.minimo
        self.maximo += mes.maximo
        self.parcial |= mes.parcial


def _limites(consulta: PeriodoConsulta, inicio: date, fin: date) -> tuple[date, date]:
    def leer(texto: str | None, defecto: date) -> date:
        if texto is None:
            return defecto.replace(day=1)
        if not re.fullmatch(r"[0-9]{4}-[0-9]{2}", texto):
            raise ValueError
        return date.fromisoformat(texto + "-01")

    try:
        desde = leer(consulta.desde, inicio)
        hasta = leer(consulta.hasta, fin)
        if not inicio.replace(day=1) <= desde <= hasta <= fin.replace(day=1):
            raise ValueError
    except ValueError:
        raise ApiError(
            400, "PERIODO_INVALIDO", "Indicá un período válido en formato YYYY-MM."
        ) from None

    ultimo = hasta.replace(day=monthrange(hasta.year, hasta.month)[1])
    return max(inicio, desde), min(fin, ultimo)


class Factores:
    def __init__(self, datos: Datos) -> None:
        self.provincias = {
            (f["provincia_id"], f["mes"], f["tipo"]): (float(f["factor"]), f["nivel_origen"])
            for f in datos.consultar("SELECT * FROM factores_provincia_mes")
        }
        self.regiones = {
            (f["region"], f["mes"], f["tipo"]): float(f["factor"])
            for f in datos.consultar("SELECT * FROM factores_region_mes")
        }

    def obtener(self, provincia: str, region: str, mes: int, tipo: str) -> tuple[float, str]:
        factor = self.provincias.get((provincia, mes, tipo))
        if factor is not None:
            return factor
        regional = self.regiones.get((region, mes, tipo))
        if regional is not None and region != "Argentina":
            return regional, "region"
        nacional = self.regiones.get(("Argentina", mes, tipo))
        if nacional is None:
            raise datos_no_disponibles()
        return nacional, "pais"


def _sumar_provincia(
    mes: Acumulado, fila: dict[str, Any], factores: Factores, rangos: list[dict[str, Any]]
) -> None:
    terra, modis = fila["est_terra"], fila["est_modis"]
    total = terra + modis
    estimado = minimo = maximo = no_provincial = 0.0
    if mes.estimados and (total or mes.estimados == mes.dias):
        for tipo, conteo in (("terra", terra), ("modis", modis)):
            if conteo:
                factor, origen = factores.obtener(
                    fila["provincia_id"], fila["region"], fila["mes"].month, tipo
                )
                estimado += conteo * factor
                if origen != "provincia":
                    no_provincial += conteo * factor
        rango = next((r for r in rangos if r["modis_min"] <= total <= r["modis_max"]), None)
        if rango is None:
            raise datos_no_disponibles()
        minimo = estimado * rango["mult_bajo"]
        maximo = estimado * rango["mult_alto"] if total else rango["mult_alto"]
        # H9: los días sin MODIS no aportan focos; el máximo supone que fueron como el
        # promedio de los días estimados que sí tuvieron MODIS (docs/04 §4).
        con_modis = mes.estimados - mes.sin_modis
        if mes.sin_modis and con_modis:
            maximo *= mes.estimados / con_modis

    obs = fila["obs"]
    mes.obs += obs
    mes.modis += fila["modis"]
    mes.est_terra += terra
    mes.est_modis += modis
    mes.armonizado += obs + estimado
    mes.est_no_provincial += no_provincial
    mes.minimo += obs + minimo
    mes.maximo += obs + maximo


def calcular_meses(
    datos: Datos, zona: ZonaResuelta, consulta: PeriodoConsulta
) -> dict[str, Acumulado]:
    metadata = datos.metadata
    if metadata is None:
        raise datos_no_disponibles()
    inicio, fin = _limites(consulta, metadata.fecha_min, metadata.fecha_max)
    filas = datos.consultar(
        cobertura_sql(metadata.referencia_viirs) + AGREGAR.format(conteos=CONTEOS_SQL),
        [inicio, fin, inicio.year, fin.year, inicio, fin, list(zona.provincias)],
        celdas=zona.celdas_ids,
    )
    factores = Factores(datos)
    rangos = datos.consultar("SELECT * FROM rangos")
    meses: dict[str, Acumulado] = {}
    for fila in filas:
        fecha: date = fila["mes"]
        periodo = fecha.isoformat()[:7]
        mes = meses.setdefault(
            periodo,
            Acumulado(
                dias=fila["dias"],
                estimados=fila["estimados"],
                sin_modis=fila["sin_modis"],
                parcial=(
                    fecha == fin.replace(day=1) and fin.day < monthrange(fin.year, fin.month)[1]
                ),
            ),
        )
        _sumar_provincia(mes, fila, factores, rangos)
    return meses


def resumir(puntos: list[Punto], capa: Capa) -> Resumen:
    valores: dict[str, float] = {}
    anios: dict[int, float] = defaultdict(float)
    for punto in puntos:
        valor = (
            punto.modis if capa == "modis" else punto.viirs if capa == "viirs" else punto.armonizado
        )
        if valor is not None:
            valores[punto.periodo] = valor
            anios[int(punto.periodo[:4])] += valor
    return Resumen(
        max_mes=max(valores, key=valores.__getitem__) if valores else None,
        max_anio=max(anios, key=anios.__getitem__) if anios else None,
        total=round(sum(valores.values()), 1) if valores else None,
        mediana_mensual=round(median(valores.values()), 1) if valores else None,
    )


def pocos_datos(zona: ZonaResuelta) -> bool:
    area = sum(p.area_km2 for codigo, p in zona.provincias.items() if codigo in POCOS_DATOS)
    return area > zona.area_km2 / 2


def agrupar_anios(meses: dict[str, Acumulado]) -> dict[str, Acumulado]:
    anios: dict[str, Acumulado] = defaultdict(Acumulado)
    for periodo, mes in meses.items():
        anios[periodo[:4]].sumar_mes(mes)
    return anios
