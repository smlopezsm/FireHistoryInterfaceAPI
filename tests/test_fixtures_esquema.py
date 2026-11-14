"""Los fixtures respetan exactamente los esquemas de docs/02."""

from __future__ import annotations

import pyarrow.parquet as pq
import pytest

from tests.conftest import FIXTURES

I16, I32, I64, F32 = "int16", "int32", "int64", "float"
STR, DATE, BOOL, I8 = "string", "date32[day]", "bool", "int8"

# (columna, tipo Arrow, admite nulos) — transcripción de docs/02.
ESPERADO: dict[str, list[tuple[str, str, bool]]] = {
    "focos": [
        ("foco_id", I64, False), ("fecha", DATE, False), ("hora_utc", STR, False),
        ("satelite", STR, False), ("sensor", STR, False), ("lat", F32, False),
        ("lon", F32, False), ("confianza", STR, False), ("frp_mw", F32, False),
        ("dia_noche", STR, False), ("fuente", STR, False), ("cell_id", I32, False),
        ("provincia_id", STR, True),
    ],
    "conteos_celda_dia": [
        ("cell_id", I32, False), ("fecha", DATE, False), ("provincia_id", STR, False),
        ("n_terra", I16, False), ("n_aqua", I16, False), ("n_snpp", I16, False),
        ("n_n20", I16, False), ("n_n21", I16, False),
    ],
    "dim_celdas.parquet": [
        ("cell_id", I32, False), ("grid_row", I16, False), ("grid_col", I16, False),
        ("provincia_id", STR, False), ("region", STR, False), ("frac_dentro", F32, False),
        ("lat_centro", F32, False), ("lon_centro", F32, False), ("geom_geojson", STR, False),
    ],
    "dim_provincias.parquet": [
        ("provincia_id", STR, False), ("nombre", STR, False), ("region", STR, False),
        ("geom_geojson", STR, False), ("bbox", STR, False),
    ],
    "factores_provincia_mes.parquet": [
        ("provincia_id", STR, False), ("mes", I8, False), ("tipo", STR, False),
        ("factor", F32, False), ("nivel_origen", STR, False), ("n_modis_calib", I32, False),
        ("factores_version", STR, False),
    ],
    "factores_region_mes.parquet": [
        ("region", STR, False), ("mes", I8, False), ("tipo", STR, False),
        ("factor", F32, False), ("n_modis_calib", I32, False), ("factores_version", STR, False),
    ],
    "rangos.parquet": [
        ("modis_min", I32, False), ("modis_max", I32, False),
        ("mult_bajo", F32, False), ("mult_alto", F32, False),
    ],
    "satelite_operativo.parquet": [
        ("fecha", DATE, False), ("satelite", STR, False),
        ("operativo", BOOL, False), ("n_nacional", I32, False),
    ],
    "puntos_industriales.parquet": [
        ("punto_id", I64, False), ("lat", F32, False), ("lon", F32, False),
        ("provincia_id", STR, False), ("motivo", STR, False), ("dias", I16, False),
        ("anios", I16, False), ("meses", I16, False), ("frac_nocturna", F32, False),
        ("n_focos", I32, False),
    ],
}  # fmt: skip


@pytest.mark.parametrize("nombre", sorted(ESPERADO))
def test_esquema_exacto(nombre: str) -> None:
    ruta = FIXTURES / nombre
    archivos = sorted(ruta.glob("anio=*/part-0.parquet")) if ruta.is_dir() else [ruta]
    assert archivos, f"no hay archivos para {nombre}"
    for archivo in archivos:
        esquema = pq.read_schema(archivo)
        real = [(c.name, str(c.type), c.nullable) for c in esquema]
        assert real == ESPERADO[nombre], archivo
        assert pq.ParquetFile(archivo).metadata.row_group(0).column(0).compression == "ZSTD"


def test_particiones_por_anio() -> None:
    anios = sorted(p.name for p in (FIXTURES / "conteos_celda_dia").glob("anio=*"))
    assert anios == [f"anio={a}" for a in (2001, 2006, 2011, 2012, 2022, 2026)]


def test_rangos_iniciales() -> None:
    filas = pq.read_table(FIXTURES / "rangos.parquet").to_pylist()
    assert [(f["modis_min"], f["modis_max"]) for f in filas] == [
        (0, 0),
        (1, 5),
        (6, 20),
        (21, 100),
        (101, 500),
        (501, 2147483647),
    ]
    assert filas[0]["mult_alto"] == 10


def test_conteos_no_tienen_filas_vacias() -> None:
    for archivo in (FIXTURES / "conteos_celda_dia").glob("anio=*/part-0.parquet"):
        for fila in pq.read_table(archivo).to_pylist():
            valores = [fila[c] for c in ("n_terra", "n_aqua", "n_snpp", "n_n20", "n_n21")]
            assert min(valores) >= 0 and max(valores) > 0
