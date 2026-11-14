"""Contrato de las capas del mapa."""

import pytest

PARAMS = {"bbox": "-68,-35,-62,-31", "desde": "2011-09-01", "hasta": "2011-09-30"}


@pytest.mark.parametrize(
    ("capa", "valores"),
    [
        ("armonizado", [15, 20]),
        ("modis", [5, 5]),
        ("viirs", []),
    ],
)
def test_celdas_por_capa(cliente, capa, valores):
    r = cliente.get("/api/v1/mapa/celdas", params={**PARAMS, "capa": capa})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["type"] == "FeatureCollection"
    assert sorted(f["properties"]["valor"] for f in cuerpo["features"]) == valores
    for feature in cuerpo["features"]:
        assert feature["geometry"]["type"] == "Polygon"
        assert feature["properties"]["viirs"] is None
        assert feature["properties"]["estado"] == "estimado"


def test_c4_limite_despues_del_filtro(hacer_cliente):
    cliente = hacer_cliente(max_celdas_mapa=1)
    r = cliente.get("/api/v1/mapa/celdas", params=PARAMS)
    assert r.status_code == 413, r.text
    assert r.json()["error"]["codigo"] == "RESULTADO_DEMASIADO_GRANDE"
    r = cliente.get("/api/v1/mapa/celdas", params={**PARAMS, "min_focos": 16})
    assert r.status_code == 200, r.text
    assert len(r.json()["features"]) == 1


def test_periodo_excede_366_dias(cliente):
    r = cliente.get("/api/v1/mapa/celdas", params={**PARAMS, "hasta": "2012-09-01"})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["codigo"] == "PERIODO_INVALIDO"


def test_puntos_industriales(cliente):
    r = cliente.get("/api/v1/mapa/industriales")
    assert r.status_code == 200, r.text
    assert r.json()["features"]
    punto = r.json()["features"][0]
    assert punto["geometry"]["type"] == "Point"
    assert set(punto["properties"]) == {"motivo", "n_focos", "provincia_id"}
    r = cliente.get("/api/v1/mapa/industriales", params={"bbox": "0,0,1,1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"type": "FeatureCollection", "features": []}


def test_celdas_mes_mixto_complementan_viirs_con_modis(cliente):
    r = cliente.get(
        "/api/v1/mapa/celdas",
        params={**PARAMS, "desde": "2022-08-01", "hasta": "2022-08-31"},
    )
    assert r.status_code == 200, r.text
    celdas = [f["properties"] for f in r.json()["features"]]
    assert sum(c["valor"] for c in celdas) == 24
    assert sum(c["viirs"] for c in celdas) == 12
    assert {c["estado"] for c in celdas} == {"mixto"}


def test_mapa_sin_celdas_en_bbox(cliente):
    r = cliente.get("/api/v1/mapa/celdas", params={**PARAMS, "bbox": "0,0,1,1"})
    assert r.status_code == 200, r.text
    assert r.json() == {"type": "FeatureCollection", "features": []}


def test_industriales_sin_provincia(tmp_path, hacer_cliente):
    # Con datos reales hay puntos fuera de los límites provinciales (provincia_id nulo).
    import shutil

    import pyarrow.parquet as pq

    from app.schemas.mapa import ColeccionIndustriales
    from tests.conftest import FIXTURES

    destino = tmp_path / "datos"
    shutil.copytree(FIXTURES, destino)
    ruta = destino / "puntos_industriales.parquet"
    tabla = pq.read_table(ruta)
    filas = tabla.to_pylist()
    filas[0]["provincia_id"] = None
    pq.write_table(type(tabla).from_pylist(filas, schema=tabla.schema), ruta)

    r = hacer_cliente(data_dir=destino).get("/api/v1/mapa/industriales")
    assert r.status_code == 200, r.text
    coleccion = ColeccionIndustriales.model_validate(r.json())
    assert [f.properties.provincia_id for f in coleccion.features].count(None) == 1
