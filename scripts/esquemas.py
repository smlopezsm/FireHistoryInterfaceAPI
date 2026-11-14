"""Esquemas Arrow de los archivos de datos, exactamente como en docs/02.

Los usan ``make_fixtures.py`` y ``make_demo_data.py``. En los archivos particionados
(``focos/`` y ``conteos_celda_dia/``) la columna ``anio`` va en la ruta
(``anio=YYYY/part-0.parquet``, estilo Hive) y no dentro del archivo.
"""

from __future__ import annotations

import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq


def _esquema(columnas: list[tuple[Any, ...]]) -> pa.Schema:
    """Columnas ``(nombre, tipo)`` no nulas; ``(nombre, tipo, True)`` admite nulos (docs/02)."""
    return pa.schema([pa.field(c[0], c[1], nullable=len(c) > 2 and bool(c[2])) for c in columnas])


FOCOS = _esquema(
    [
        ("foco_id", pa.int64()),
        ("fecha", pa.date32()),
        ("hora_utc", pa.string()),
        ("satelite", pa.string()),
        ("sensor", pa.string()),
        ("lat", pa.float32()),
        ("lon", pa.float32()),
        ("confianza", pa.string()),
        ("frp_mw", pa.float32()),
        ("dia_noche", pa.string()),
        ("fuente", pa.string()),
        ("cell_id", pa.int32()),
        ("provincia_id", pa.string(), True),
    ]
)

CONTEOS_CELDA_DIA = _esquema(
    [
        ("cell_id", pa.int32()),
        ("fecha", pa.date32()),
        ("provincia_id", pa.string()),
        ("n_terra", pa.int16()),
        ("n_aqua", pa.int16()),
        ("n_snpp", pa.int16()),
        ("n_n20", pa.int16()),
        ("n_n21", pa.int16()),
    ]
)

DIM_CELDAS = _esquema(
    [
        ("cell_id", pa.int32()),
        ("grid_row", pa.int16()),
        ("grid_col", pa.int16()),
        ("provincia_id", pa.string()),
        ("region", pa.string()),
        ("frac_dentro", pa.float32()),
        ("lat_centro", pa.float32()),
        ("lon_centro", pa.float32()),
        ("geom_geojson", pa.string()),
    ]
)

DIM_PROVINCIAS = _esquema(
    [
        ("provincia_id", pa.string()),
        ("nombre", pa.string()),
        ("region", pa.string()),
        ("geom_geojson", pa.string()),
        ("bbox", pa.string()),
    ]
)

FACTORES_PROVINCIA_MES = _esquema(
    [
        ("provincia_id", pa.string()),
        ("mes", pa.int8()),
        ("tipo", pa.string()),
        ("factor", pa.float32()),
        ("nivel_origen", pa.string()),
        ("n_modis_calib", pa.int32()),
        ("factores_version", pa.string()),
    ]
)

# Propuesto (opción b, aprobada): factores de respaldo por región y nacional
# (region = "Argentina"). Pendiente de documentar en docs/02.
FACTORES_REGION_MES = _esquema(
    [
        ("region", pa.string()),
        ("mes", pa.int8()),
        ("tipo", pa.string()),
        ("factor", pa.float32()),
        ("n_modis_calib", pa.int32()),
        ("factores_version", pa.string()),
    ]
)

RANGOS = _esquema(
    [
        ("modis_min", pa.int32()),
        ("modis_max", pa.int32()),
        ("mult_bajo", pa.float32()),
        ("mult_alto", pa.float32()),
    ]
)

SATELITE_OPERATIVO = _esquema(
    [
        ("fecha", pa.date32()),
        ("satelite", pa.string()),
        ("operativo", pa.bool_()),
        ("n_nacional", pa.int32()),
    ]
)

PUNTOS_INDUSTRIALES = _esquema(
    [
        ("punto_id", pa.int64()),
        ("lat", pa.float32()),
        ("lon", pa.float32()),
        ("provincia_id", pa.string(), True),
        ("motivo", pa.string()),
        ("dias", pa.int16()),
        ("anios", pa.int16()),
        ("meses", pa.int16()),
        ("frac_nocturna", pa.float32()),
        ("n_focos", pa.int32()),
    ]
)

RANGOS_INICIALES = [
    (0, 0, 0.0, 10.0),
    (1, 5, 0.46, 4.49),
    (6, 20, 0.55, 1.86),
    (21, 100, 0.63, 1.33),
    (101, 500, 0.73, 1.24),
    (501, 2147483647, 0.82, 1.18),
]


def escribir(ruta: Path, filas: list[dict[str, Any]], esquema: pa.Schema) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tabla = pa.Table.from_pylist(filas, schema=esquema)
    pq.write_table(tabla, ruta, compression="zstd")


def escribir_particionado(carpeta: Path, filas: list[dict[str, Any]], esquema: pa.Schema) -> None:
    """Escribe ``carpeta/anio=YYYY/part-0.parquet`` agrupando por el año de ``fecha``."""
    por_anio: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for fila in filas:
        por_anio[fila["fecha"].year].append(fila)
    for anio, grupo in sorted(por_anio.items()):
        grupo.sort(key=lambda f: (f["fecha"], f["cell_id"]))
        escribir(carpeta / f"anio={anio}" / "part-0.parquet", grupo, esquema)


def limpiar_particiones(destino: Path) -> None:
    """Borra solo las carpetas ``anio=YYYY`` de los archivos particionados."""
    for carpeta in ("focos", "conteos_celda_dia"):
        for particion in (destino / carpeta).glob("anio=*"):
            shutil.rmtree(particion)


def escribir_rangos(ruta: Path) -> None:
    filas = [
        {"modis_min": a, "modis_max": b, "mult_bajo": lo, "mult_alto": hi}
        for a, b, lo, hi in RANGOS_INICIALES
    ]
    escribir(ruta, filas, RANGOS)


def escribir_metadata(ruta: Path, datos: dict[str, Any]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(datos, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def punto_id(lat: float, lon: float) -> int:
    """Celda de ~1 km: lat x 100 y lon x 100 redondeados, combinados en un entero."""
    return (round(lat * 100) + 9000) * 100_000 + (round(lon * 100) + 18_000)
