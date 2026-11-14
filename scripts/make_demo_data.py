"""Genera un dataset SINTÉTICO de demostración para levantar la API localmente.

Uso: ``python scripts/make_demo_data.py [carpeta_destino]`` (default ``data/demo``).

**No son datos reales.** Los focos se simulan con un modelo estacional simple:

- 3 provincias reales (San Luis ``74``, Córdoba ``14``, Neuquén ``58``) con un bloque
  de 8 x 8 celdas de 5 km cada una;
- fechas 2000-11-01 → 2026-11-13;
- caída de S-NPP del 2022-08-01 al 2022-08-10;
- factores MODIS → VIIRS por provincia y mes entre 2,5 y 4,5.

Requiere ``numpy`` (dependencia de desarrollo).
"""

from __future__ import annotations

import math
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import esquemas as esq
import grilla

RAIZ = Path(__file__).resolve().parent.parent
DESTINO_DEFAULT = RAIZ / "data" / "demo"

FECHA_MIN = date(2000, 11, 1)
FECHA_MAX = date(2026, 11, 13)
ULTIMO_SP = date(2026, 8, 31)
FACTORES_VERSION = "demo-1"
SEMILLA = 20261114
LADO = 8  # celdas por lado del bloque de cada provincia

MISIONES: dict[str, tuple[date, date | None]] = {
    "Terra": (FECHA_MIN, None),
    "Aqua": (date(2002, 7, 4), None),
    "SNPP": (date(2012, 1, 20), date(2026, 11, 2)),
    "N20": (date(2018, 4, 1), None),
    "N21": (date(2024, 1, 17), None),
}
CAIDA_SNPP = (date(2022, 8, 1), date(2022, 8, 10))

# bbox aproximado (oeste, sur, este, norte), centro del bloque de celdas y
# mes pico de la temporada de fuego.
PROVINCIAS: dict[str, dict[str, Any]] = {
    "74": {
        "nombre": "San Luis",
        "region": "Cuyo",
        "bbox": (-67.42, -35.99, -64.87, -31.85),
        "centro": (-66.0, -33.6),
        "pico": 9,
        "intensidad": 0.05,
    },
    "14": {
        "nombre": "Córdoba",
        "region": "Pampeana",
        "bbox": (-65.78, -35.00, -61.78, -29.50),
        "centro": (-64.6, -31.4),
        "pico": 8,
        "intensidad": 0.07,
    },
    "58": {
        "nombre": "Neuquén",
        "region": "Patagonia",
        "bbox": (-71.95, -41.10, -68.00, -36.00),
        "centro": (-70.6, -39.2),
        "pico": 1,
        "intensidad": 0.03,
    },
}
SATELITES = ["Terra", "Aqua", "SNPP", "N20", "N21"]
COLUMNA = {"Terra": "n_terra", "Aqua": "n_aqua", "SNPP": "n_snpp", "N20": "n_n20", "N21": "n_n21"}


def factor_modis(pid: str, mes: int) -> float:
    """Entre 2,5 y 4,5: más alto fuera de temporada (fuegos chicos que MODIS no ve)."""
    pico = PROVINCIAS[pid]["pico"]
    return round(3.5 - math.cos(2 * math.pi * (mes - pico) / 12), 2)


def factor_terra(pid: str, mes: int) -> float:
    return round(factor_modis(pid, mes) * 1.8, 2)


def _celdas() -> list[dict[str, Any]]:
    celdas = []
    for pid, p in PROVINCIAS.items():
        _, fila0, col0 = grilla.celda_de(*p["centro"])
        for df in range(-LADO // 2, LADO // 2):
            for dc in range(-LADO // 2, LADO // 2):
                fila, col = fila0 + df, col0 + dc
                lon, lat = grilla.centroide(fila, col)
                celdas.append(
                    {
                        "cell_id": fila * grilla.COLUMNAS + col,
                        "grid_row": fila,
                        "grid_col": col,
                        "provincia_id": pid,
                        "region": p["region"],
                        "frac_dentro": 1.0,
                        "lat_centro": lat,
                        "lon_centro": lon,
                        "geom_geojson": grilla.poligono_geojson(fila, col),
                    }
                )
    return celdas


def _operativo(sat: str, d: date) -> bool:
    inicio, fin = MISIONES[sat]
    if d < inicio or (fin is not None and d > fin):
        return False
    return not (sat == "SNPP" and CAIDA_SNPP[0] <= d <= CAIDA_SNPP[1])


def _simular(celdas: list[dict[str, Any]], rng: np.random.Generator) -> list[dict[str, Any]]:
    dias = [FECHA_MIN + timedelta(days=i) for i in range((FECHA_MAX - FECHA_MIN).days + 1)]
    n_dias = len(dias)
    meses = np.array([d.month for d in dias])
    anios = np.array([d.year for d in dias])
    filas: list[dict[str, Any]] = []
    for pid, p in PROVINCIAS.items():
        ids = [c["cell_id"] for c in celdas if c["provincia_id"] == pid]
        estacion = 0.15 + (1 + np.cos(2 * np.pi * (meses - p["pico"]) / 12)) ** 2
        mult_anio = {a: rng.lognormal(0.0, 0.5) for a in range(2000, 2027)}
        intensidad_dia = p["intensidad"] * estacion * np.array([mult_anio[a] for a in anios])
        f_modis = np.array([factor_modis(pid, m) for m in range(1, 13)])[meses - 1]
        f_terra = np.array([factor_terra(pid, m) for m in range(1, 13)])[meses - 1]
        operativo = {s: np.array([_operativo(s, d) for d in dias]) for s in SATELITES}
        hay_aqua = operativo["Aqua"]
        for cell in ids:
            # Fuego latente (sobredispersado) en escala VIIRS; cada satélite lo muestrea.
            latente = intensidad_dia * rng.gamma(0.3, 1 / 0.3, n_dias)
            modis = np.where(hay_aqua, latente / f_modis, latente / f_terra)
            n = {
                "Terra": rng.poisson(np.where(hay_aqua, modis / 2, modis)),
                "Aqua": rng.poisson(modis / 2) * hay_aqua,
                "SNPP": rng.poisson(latente) * operativo["SNPP"],
                "N20": rng.poisson(latente * 0.99) * operativo["N20"],
                "N21": rng.poisson(latente * 0.97) * operativo["N21"],
            }
            total = sum(n.values())
            for i in np.nonzero(total)[0]:
                filas.append(
                    {
                        "cell_id": cell,
                        "fecha": dias[i],
                        "provincia_id": pid,
                        **{COLUMNA[s]: min(int(n[s][i]), 32767) for s in SATELITES},
                    }
                )
    return filas


def _focos(
    conteos: list[dict[str, Any]], celdas: list[dict[str, Any]], rng: np.random.Generator
) -> list[dict[str, Any]]:
    centro = {c["cell_id"]: c for c in celdas}
    sensor = {"Terra": "MODIS", "Aqua": "MODIS", "SNPP": "VIIRS", "N20": "VIIRS", "N21": "VIIRS"}
    hora = {"Terra": 14, "Aqua": 18, "SNPP": 17, "N20": 17, "N21": 16}
    filas = []
    secuencia: dict[date, int] = {}
    for fila in conteos:
        c = centro[fila["cell_id"]]
        for sat in SATELITES:
            for _ in range(fila[COLUMNA[sat]]):
                k = secuencia.get(fila["fecha"], 0) + 1
                secuencia[fila["fecha"]] = k
                noche = rng.random() < 0.3
                h = (hora[sat] + (12 if noche else 0)) % 24
                filas.append(
                    {
                        "foco_id": int(fila["fecha"].strftime("%Y%m%d")) * 1_000_000 + k,
                        "fecha": fila["fecha"],
                        "hora_utc": f"{h:02d}{int(rng.integers(0, 60)):02d}",
                        "satelite": sat,
                        "sensor": sensor[sat],
                        "lat": c["lat_centro"] + float(rng.uniform(-0.022, 0.022)),
                        "lon": c["lon_centro"] + float(rng.uniform(-0.027, 0.027)),
                        "confianza": (
                            str(int(rng.integers(30, 101)))
                            if sensor[sat] == "MODIS"
                            else ("h" if rng.random() < 0.2 else "n")
                        ),
                        "frp_mw": float(rng.lognormal(2.0, 1.0)),
                        "dia_noche": "N" if noche else "D",
                        "fuente": "NRT" if fila["fecha"] > ULTIMO_SP else "SP",
                        "cell_id": fila["cell_id"],
                        "provincia_id": fila["provincia_id"],
                    }
                )
    return filas


def _satelite_operativo(conteos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    totales: dict[tuple[date, str], int] = {}
    for f in conteos:
        for s in SATELITES:
            clave = (f["fecha"], s)
            totales[clave] = totales.get(clave, 0) + f[COLUMNA[s]]
    filas = []
    for sat, (inicio, _) in MISIONES.items():
        d = inicio
        while d <= FECHA_MAX:
            op = _operativo(sat, d)
            # Fondo nacional sintético: el resto del país casi siempre tiene algún foco.
            n = totales.get((d, sat), 0) + (250 if op else 0)
            filas.append({"fecha": d, "satelite": sat, "operativo": op, "n_nacional": n})
            d += timedelta(days=1)
    return filas


def _factores() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prov = []
    for pid in PROVINCIAS:
        for mes in range(1, 13):
            for tipo, f in (("modis", factor_modis(pid, mes)), ("terra", factor_terra(pid, mes))):
                prov.append(
                    {
                        "provincia_id": pid,
                        "mes": mes,
                        "tipo": tipo,
                        "factor": f,
                        "nivel_origen": "provincia",
                        "n_modis_calib": 1500,
                        "factores_version": FACTORES_VERSION,
                    }
                )
    region = []
    grupos = {p["region"]: [pid] for pid, p in PROVINCIAS.items()}
    grupos["Argentina"] = list(PROVINCIAS)
    for nombre, pids in grupos.items():
        for mes in range(1, 13):
            for tipo, fn in (("modis", factor_modis), ("terra", factor_terra)):
                region.append(
                    {
                        "region": nombre,
                        "mes": mes,
                        "tipo": tipo,
                        "factor": round(sum(fn(p, mes) for p in pids) / len(pids), 2),
                        "n_modis_calib": 1500 * len(pids),
                        "factores_version": FACTORES_VERSION,
                    }
                )
    return prov, region


def _provincias() -> list[dict[str, Any]]:
    return [
        {
            "provincia_id": pid,
            "nombre": p["nombre"],
            "region": p["region"],
            "geom_geojson": grilla.rectangulo_geojson(*p["bbox"]),
            "bbox": ",".join(f"{v:.2f}" for v in p["bbox"]),
        }
        for pid, p in PROVINCIAS.items()
    ]


def _industriales(celdas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    elegidas = [c for c in celdas if c["cell_id"] % 23 == 0][:6]
    motivos = ["nocturno todo el año", "marcado industrial por FIRMS", "nocturno estacional"]
    filas = []
    for i, c in enumerate(elegidas):
        filas.append(
            {
                "punto_id": esq.punto_id(c["lat_centro"], c["lon_centro"]),
                "lat": c["lat_centro"],
                "lon": c["lon_centro"],
                "provincia_id": c["provincia_id"],
                "motivo": motivos[i % 3],
                "dias": 120 + 40 * i,
                "anios": 5 + i,
                "meses": 12 if i % 3 == 0 else 6,
                "frac_nocturna": 0.9 if i % 3 != 1 else 0.5,
                "n_focos": 300 + 75 * i,
            }
        )
    return filas


def generar(destino: Path) -> None:
    rng = np.random.default_rng(SEMILLA)
    esq.limpiar_particiones(destino)
    celdas = _celdas()
    conteos = _simular(celdas, rng)
    esq.escribir_particionado(destino / "conteos_celda_dia", conteos, esq.CONTEOS_CELDA_DIA)
    esq.escribir_particionado(destino / "focos", _focos(conteos, celdas, rng), esq.FOCOS)
    esq.escribir(destino / "dim_celdas.parquet", celdas, esq.DIM_CELDAS)
    esq.escribir(destino / "dim_provincias.parquet", _provincias(), esq.DIM_PROVINCIAS)
    prov, region = _factores()
    esq.escribir(destino / "factores_provincia_mes.parquet", prov, esq.FACTORES_PROVINCIA_MES)
    esq.escribir(destino / "factores_region_mes.parquet", region, esq.FACTORES_REGION_MES)
    esq.escribir_rangos(destino / "rangos.parquet")
    esq.escribir(
        destino / "satelite_operativo.parquet", _satelite_operativo(conteos), esq.SATELITE_OPERATIVO
    )
    esq.escribir(
        destino / "puntos_industriales.parquet", _industriales(celdas), esq.PUNTOS_INDUSTRIALES
    )
    esq.escribir_metadata(
        destino / "metadata.json",
        {
            "schema_version": "1.0.0",
            "data_version": "demo-2026-11-14",
            "factores_version": FACTORES_VERSION,
            "fecha_min": FECHA_MIN.isoformat(),
            "fecha_max": FECHA_MAX.isoformat(),
            "fecha_ultimo_sp": ULTIMO_SP.isoformat(),
            "referencia_viirs": [
                {"satelite": "SNPP", "desde": "2012-01-20", "hasta": "2026-11-02"},
                {"satelite": "N20", "desde": "2026-11-03", "hasta": None},
            ],
            "fuentes": ["DATOS SINTÉTICOS DE DEMOSTRACIÓN (no usar para análisis)"],
            "pipeline_commit": "demo",
        },
    )
    print(f"{len(celdas)} celdas, {len(conteos)} filas de conteos")


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else DESTINO_DEFAULT
    generar(destino)
    print(f"Datos de demostración generados en {destino}")
