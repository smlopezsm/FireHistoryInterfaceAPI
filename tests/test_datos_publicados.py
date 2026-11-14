"""La versión de datos de `data/current/` (la que va en la imagen) cumple el contrato."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq
import pytest

from app.db import Datos
from tests.conftest import crear_settings
from tests.test_fixtures_esquema import ESPERADO

ACTUAL = Path(__file__).resolve().parent.parent / "data" / "current"

pytestmark = pytest.mark.skipif(
    not (ACTUAL / "metadata.json").exists(), reason="no hay datos en data/current"
)


@pytest.mark.parametrize("nombre", sorted(ESPERADO))
def test_esquema_exacto(nombre: str) -> None:
    ruta = ACTUAL / nombre
    archivos = sorted(ruta.glob("anio=*/part-0.parquet")) if ruta.is_dir() else [ruta]
    assert archivos and archivos[0].exists(), f"falta {nombre}"
    esperado = [(c, t) for c, t, _ in ESPERADO[nombre]]
    for archivo in archivos:
        assert [(c.name, str(c.type)) for c in pq.read_schema(archivo)] == esperado, archivo


def test_la_api_abre_los_datos() -> None:
    datos = Datos(crear_settings(data_dir=ACTUAL))
    assert datos.abrir(), datos.error
    try:
        meta = datos.metadata
        assert meta is not None
        assert meta.fecha_min.isoformat() == "2000-11-01"
        assert meta.schema_version == "1.1.0"
        assert datos.provincias_total == 24
        fechas = datos.consultar(
            "SELECT min(fecha) AS desde, max(fecha) AS hasta FROM conteos_celda_dia"
        )[0]
        assert meta.fecha_min <= fechas["desde"] and fechas["hasta"] <= meta.fecha_max
        fuera = datos.consultar(
            "SELECT count(*) AS n FROM conteos_celda_dia "
            "WHERE cell_id NOT IN (SELECT cell_id FROM dim_celdas)"
        )[0]["n"]
        assert fuera == 0
    finally:
        datos.cerrar()
