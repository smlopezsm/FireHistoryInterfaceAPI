"""Genera el mini dataset de pruebas en ``tests/fixtures/`` (docs/06 §1).

Uso: ``python scripts/make_fixtures.py [carpeta_destino]``

Contenido (todo con los esquemas exactos de docs/02):

- 2 provincias ficticias: ``P1`` (región ``R1``) y ``P2`` (región ``R2``), 10 celdas cada una.
- ``conteos_celda_dia`` en 2001, 2006, 2011, 2012, 2022 y 2026 con casos elegidos a mano
  para las pruebas U1-U9 (ver ``CASOS`` abajo).
- Factores conocidos: ``P1`` modis = 3,0 y terra = 2,0 en todos los meses;
  ``P2`` modis = 4,0 (**sin el mes 5**, para la U8) y terra = 2,5.
  Respaldo regional: ``R2`` modis mes 5 = 3,5.
- Caída de S-NPP del 2022-08-10 al 2022-08-12 (3 días).
- Rangos: los valores iniciales de docs/02 §6.

Los valores esperados de cada prueba se documentan junto a cada caso.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import esquemas as esq
import grilla

RAIZ = Path(__file__).resolve().parent.parent
DESTINO_DEFAULT = RAIZ / "tests" / "fixtures"

FECHA_MIN = date(2000, 11, 1)
FECHA_MAX = date(2026, 11, 13)
FACTORES_VERSION = "test-1"

# Inicio y fin de cada misión en el archivo (docs/02 §7). None = sigue operativo.
MISIONES: dict[str, tuple[date, date | None]] = {
    "Terra": (FECHA_MIN, None),
    "Aqua": (date(2002, 7, 4), None),
    "SNPP": (date(2012, 1, 20), date(2026, 11, 2)),
    "N20": (date(2018, 4, 1), None),
    "N21": (date(2024, 1, 17), None),
}
CAIDA_SNPP = (date(2022, 8, 10), date(2022, 8, 12))

PROVINCIAS = {
    "P1": {"nombre": "Provincia Uno", "region": "R1", "lon": -66.40, "lat": -33.30},
    "P2": {"nombre": "Provincia Dos", "region": "R2", "lon": -66.10, "lat": -33.30},
}


def _celdas() -> dict[str, list[dict[str, Any]]]:
    """10 celdas por provincia (bloque de 5 columnas x 2 filas)."""
    salida: dict[str, list[dict[str, Any]]] = {}
    for pid, p in PROVINCIAS.items():
        _, fila0, col0 = grilla.celda_de(p["lon"], p["lat"])
        celdas = []
        for df in range(2):
            for dc in range(5):
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
        salida[pid] = celdas
    return salida


CELDAS = _celdas()
C1 = [c["cell_id"] for c in CELDAS["P1"]]
C2 = [c["cell_id"] for c in CELDAS["P2"]]

# (celda, fecha, n_terra, n_aqua, n_snpp, n_n20, n_n21)
CASOS: list[tuple[int, date, int, int, int, int, int]] = [
    # U5 · 2001-09, solo Terra en P1: n_terra = 5 → 5 x 2,0 (terra) = 10,0
    (C1[0], date(2001, 9, 5), 3, 0, 0, 0, 0),
    (C1[1], date(2001, 9, 20), 2, 0, 0, 0, 0),
    # U1 · 2006-08, P1: MODIS = 10 → 10 x 3,0 = 30,0 ; rango (6-20) = [16,5 ; 55,8]
    (C1[0], date(2006, 8, 3), 4, 2, 0, 0, 0),
    (C1[2], date(2006, 8, 15), 1, 3, 0, 0, 0),
    # U9 · 2006-03 sin ningún foco → minimo 0, maximo 10 (por provincia)
    # U8 · 2011-05, P2 sin factor del mes 5: MODIS = 4 → 4 x 3,5 (R2) = 14,0
    (C2[0], date(2011, 5, 10), 2, 2, 0, 0, 0),
    #      2011-05, P1: MODIS = 2 → 2 x 3,0 = 6,0
    (C1[3], date(2011, 5, 10), 1, 1, 0, 0, 0),
    # U7 · 2011-09, zona P1 + P2: 5 x 3,0 + 5 x 4,0 = 35,0
    (C1[4], date(2011, 9, 12), 3, 2, 0, 0, 0),
    (C2[1], date(2011, 9, 12), 2, 3, 0, 0, 0),
    # Mixto natural · 2012-01 (S-NPP desde el 20): est 3 x 3,0 = 9 + obs 6 = 15,0 ;
    # frac_estimada = 19/31
    (C1[0], date(2012, 1, 10), 2, 1, 0, 0, 0),
    (C1[0], date(2012, 1, 25), 1, 1, 6, 0, 0),
    # U2 + U6 · 2022-07, S-NPP operativo todo el mes: armonizado = 5 + 7 = 12 (N21 no suma)
    (C1[0], date(2022, 7, 4), 1, 2, 5, 5, 0),
    (C1[5], date(2022, 7, 20), 0, 0, 7, 6, 4),
    # U3 · 2022-08, S-NPP caído 10-12: obs 8 + 4 = 12 ; est (2 + 2) x 3,0 = 12 → 24,0 ;
    # frac_estimada = 3/31 ; el N20 del día 11 NO se usa (todavía no es referencia)
    (C1[0], date(2022, 8, 5), 2, 1, 8, 0, 0),
    (C1[1], date(2022, 8, 11), 2, 2, 0, 9, 0),
    (C1[2], date(2022, 8, 20), 0, 1, 4, 0, 0),
    # U4 · 2026-11: días 1-2 referencia S-NPP, desde el 3 referencia N20.
    # obs = 3 (S-NPP del 1) + 7 (N20 del 10) = 10 ; el S-NPP del 10 NO se usa
    (C1[0], date(2026, 11, 1), 0, 1, 3, 4, 0),
    (C1[0], date(2026, 11, 10), 1, 1, 5, 7, 2),
]


def _conteos() -> list[dict[str, Any]]:
    prov = {c["cell_id"]: c["provincia_id"] for cs in CELDAS.values() for c in cs}
    filas = []
    for cell, fecha, t, a, s, n20, n21 in CASOS:
        assert FECHA_MIN <= fecha <= FECHA_MAX
        assert max(t, a, s, n20, n21) > 0
        filas.append(
            {
                "cell_id": cell,
                "fecha": fecha,
                "provincia_id": prov[cell],
                "n_terra": t,
                "n_aqua": a,
                "n_snpp": s,
                "n_n20": n20,
                "n_n21": n21,
            }
        )
    return filas


def _focos(conteos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Un foco por cada conteo, cerca del centroide de su celda."""
    centro = {c["cell_id"]: c for cs in CELDAS.values() for c in cs}
    columnas = [
        ("n_terra", "Terra", "MODIS"),
        ("n_aqua", "Aqua", "MODIS"),
        ("n_snpp", "SNPP", "VIIRS"),
        ("n_n20", "N20", "VIIRS"),
        ("n_n21", "N21", "VIIRS"),
    ]
    filas = []
    secuencia: dict[date, int] = {}
    for fila in conteos:
        c = centro[fila["cell_id"]]
        for col, sat, sensor in columnas:
            for i in range(fila[col]):
                n = secuencia.get(fila["fecha"], 0) + 1
                secuencia[fila["fecha"]] = n
                filas.append(
                    {
                        "foco_id": int(fila["fecha"].strftime("%Y%m%d")) * 1_000_000 + n,
                        "fecha": fila["fecha"],
                        "hora_utc": f"{(13 + i) % 24:02d}{(7 * n) % 60:02d}",
                        "satelite": sat,
                        "sensor": sensor,
                        "lat": c["lat_centro"] + 0.003 * ((i % 3) - 1),
                        "lon": c["lon_centro"] + 0.003 * ((n % 3) - 1),
                        "confianza": "75" if sensor == "MODIS" else "n",
                        "frp_mw": 5.0 + i,
                        "dia_noche": "D",
                        "fuente": "NRT" if fila["fecha"] > date(2026, 8, 31) else "SP",
                        "cell_id": fila["cell_id"],
                        "provincia_id": fila["provincia_id"],
                    }
                )
    return filas


def _satelite_operativo(conteos: list[dict[str, Any]]) -> list[dict[str, Any]]:
    col = {"Terra": "n_terra", "Aqua": "n_aqua", "SNPP": "n_snpp", "N20": "n_n20", "N21": "n_n21"}
    filas = []
    for sat, (inicio, fin) in MISIONES.items():
        reales: dict[date, int] = {}
        for f in conteos:
            reales[f["fecha"]] = reales.get(f["fecha"], 0) + f[col[sat]]
        d = inicio
        while d <= FECHA_MAX:
            operativo = (fin is None or d <= fin) and not (
                sat == "SNPP" and CAIDA_SNPP[0] <= d <= CAIDA_SNPP[1]
            )
            # n_nacional sintético: los focos del fixture + un fondo fijo si operó.
            n = reales.get(d, 0) + (100 if operativo else 0)
            filas.append({"fecha": d, "satelite": sat, "operativo": operativo, "n_nacional": n})
            d += timedelta(days=1)
    return filas


def _factores() -> list[dict[str, Any]]:
    filas = []
    valores = {
        ("P1", "modis"): 3.0,
        ("P1", "terra"): 2.0,
        ("P2", "modis"): 4.0,
        ("P2", "terra"): 2.5,
    }
    for (pid, tipo), factor in valores.items():
        for mes in range(1, 13):
            if pid == "P2" and tipo == "modis" and mes == 5:
                continue  # U8: combinación faltante
            filas.append(
                {
                    "provincia_id": pid,
                    "mes": mes,
                    "tipo": tipo,
                    "factor": factor,
                    "nivel_origen": "provincia",
                    "n_modis_calib": 500,
                    "factores_version": FACTORES_VERSION,
                }
            )
    return filas


def _factores_region() -> list[dict[str, Any]]:
    valores = {
        ("R1", "modis"): 3.0,
        ("R1", "terra"): 2.0,
        ("R2", "modis"): 3.5,
        ("R2", "terra"): 2.5,
        ("Argentina", "modis"): 3.32,
        ("Argentina", "terra"): 2.2,
    }
    return [
        {
            "region": region,
            "mes": mes,
            "tipo": tipo,
            "factor": factor,
            "n_modis_calib": 1000,
            "factores_version": FACTORES_VERSION,
        }
        for (region, tipo), factor in valores.items()
        for mes in range(1, 13)
    ]


def _provincias() -> list[dict[str, Any]]:
    filas = []
    for pid, p in PROVINCIAS.items():
        lats = [c["lat_centro"] for c in CELDAS[pid]]
        lons = [c["lon_centro"] for c in CELDAS[pid]]
        oeste, sur = round(min(lons) - 0.03, 2), round(min(lats) - 0.03, 2)
        este, norte = round(max(lons) + 0.03, 2), round(max(lats) + 0.03, 2)
        filas.append(
            {
                "provincia_id": pid,
                "nombre": p["nombre"],
                "region": p["region"],
                "geom_geojson": grilla.rectangulo_geojson(oeste, sur, este, norte),
                "bbox": f"{oeste:.2f},{sur:.2f},{este:.2f},{norte:.2f}",
            }
        )
    return filas


def _industriales() -> list[dict[str, Any]]:
    puntos = [
        (C1[9], "nocturno todo el año", 210, 8, 12, 0.92, 640),
        (C2[9], "marcado industrial por FIRMS", 95, 5, 9, 0.40, 130),
    ]
    centro = {c["cell_id"]: c for cs in CELDAS.values() for c in cs}
    filas = []
    for cell, motivo, dias, anios, meses, frac, n in puntos:
        c = centro[cell]
        filas.append(
            {
                "punto_id": esq.punto_id(c["lat_centro"], c["lon_centro"]),
                "lat": c["lat_centro"],
                "lon": c["lon_centro"],
                "provincia_id": c["provincia_id"],
                "motivo": motivo,
                "dias": dias,
                "anios": anios,
                "meses": meses,
                "frac_nocturna": frac,
                "n_focos": n,
            }
        )
    return filas


def generar(destino: Path) -> None:
    esq.limpiar_particiones(destino)
    conteos = _conteos()
    esq.escribir_particionado(destino / "conteos_celda_dia", conteos, esq.CONTEOS_CELDA_DIA)
    esq.escribir_particionado(destino / "focos", _focos(conteos), esq.FOCOS)
    esq.escribir(destino / "dim_celdas.parquet", CELDAS["P1"] + CELDAS["P2"], esq.DIM_CELDAS)
    esq.escribir(destino / "dim_provincias.parquet", _provincias(), esq.DIM_PROVINCIAS)
    esq.escribir(
        destino / "factores_provincia_mes.parquet", _factores(), esq.FACTORES_PROVINCIA_MES
    )
    esq.escribir(
        destino / "factores_region_mes.parquet", _factores_region(), esq.FACTORES_REGION_MES
    )
    esq.escribir_rangos(destino / "rangos.parquet")
    esq.escribir(
        destino / "satelite_operativo.parquet",
        _satelite_operativo(conteos),
        esq.SATELITE_OPERATIVO,
    )
    esq.escribir(destino / "puntos_industriales.parquet", _industriales(), esq.PUNTOS_INDUSTRIALES)
    esq.escribir_metadata(
        destino / "metadata.json",
        {
            "schema_version": "1.0.0",
            "data_version": "2026-11-14T09:00:00-03:00",
            "factores_version": FACTORES_VERSION,
            "fecha_min": FECHA_MIN.isoformat(),
            "fecha_max": FECHA_MAX.isoformat(),
            "fecha_ultimo_sp": "2026-08-31",
            "referencia_viirs": [
                {"satelite": "SNPP", "desde": "2012-01-20", "hasta": "2026-11-02"},
                {"satelite": "N20", "desde": "2026-11-03", "hasta": None},
            ],
            "fuentes": ["FIXTURES DE PRUEBA (datos inventados)"],
            "pipeline_commit": "fixtures",
        },
    )


if __name__ == "__main__":
    destino = Path(sys.argv[1]) if len(sys.argv) > 1 else DESTINO_DEFAULT
    generar(destino)
    print(f"Fixtures generados en {destino}")
