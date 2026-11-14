"""Casos de armonización del traspaso F3."""

import json
import shutil

import pytest

from tests.conftest import FIXTURES


@pytest.mark.parametrize(
    ("periodo", "armonizado", "viirs", "estado"),
    [
        ("2001-09", 10, None, "estimado"),
        ("2006-03", 0, None, "estimado"),
        ("2006-08", 30, None, "estimado"),
        ("2012-01", 15, 6, "mixto"),
        ("2022-07", 12, 12, "observado"),
        ("2022-08", 24, 12, "mixto"),
        ("2026-11", 10, 10, "observado"),
    ],
)
def test_meses(cliente, periodo, armonizado, viirs, estado):
    r = cliente.get(
        "/api/v1/calendario",
        params={"provincia_id": "P1", "desde": periodo, "hasta": periodo},
    )
    assert r.status_code == 200, r.text
    (mes,) = r.json()["meses"]
    assert (mes["armonizado"], mes["viirs"], mes["estado"]) == (armonizado, viirs, estado)


def test_respaldo_regional(cliente):
    r = cliente.post(
        "/api/v1/serie",
        json={"provincia_id": "P2", "desde": "2011-05", "hasta": "2011-05"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["puntos"][0]["armonizado"] == 14


@pytest.mark.parametrize(
    ("params", "codigo"),
    [
        ({"provincia_id": "P1", "desde": "2022-8"}, "PERIODO_INVALIDO"),
        ({}, "ZONA_INVALIDA"),
    ],
)
def test_consulta_invalida(cliente, params, codigo):
    r = cliente.get("/api/v1/calendario", params=params)
    assert r.status_code == 400, r.text
    assert codigo in r.text


def test_serie_anual_ponderada_por_dias(cliente):
    r = cliente.get(
        "/api/v1/serie",
        params={
            "provincia_id": "P1",
            "desde": "2022-07",
            "hasta": "2022-08",
            "granularidad": "anio",
        },
    )
    assert r.status_code == 200, r.text
    (punto,) = r.json()["puntos"]
    assert punto["periodo"] == "2022"
    assert punto["armonizado"] == 36
    assert punto["viirs"] == 24
    assert punto["frac_estimada"] == pytest.approx(3 / 62)
    assert punto["estado"] == "mixto"


def test_calendario_capa_viirs_omite_meses_sin_referencia(cliente):
    r = cliente.post(
        "/api/v1/calendario",
        json={"provincia_id": "P1", "desde": "2011-12", "hasta": "2012-01", "capa": "viirs"},
    )
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert [m["viirs"] for m in cuerpo["meses"]] == [None, 6]
    assert cuerpo["resumen"] == {
        "max_mes": "2012-01",
        "max_anio": 2012,
        "total": 6,
        "mediana_mensual": 6,
    }


def test_rangos_por_provincia_y_mes(cliente):
    r = cliente.get("/api/v1/calendario", params={"provincia_id": "P1"})
    assert r.status_code == 200, r.text
    meses = {m["periodo"]: m for m in r.json()["meses"]}
    assert (meses["2006-03"]["minimo"], meses["2006-03"]["maximo"]) == (0, 10)
    assert (meses["2006-08"]["minimo"], meses["2006-08"]["maximo"]) == (16.5, 55.8)
    assert (meses["2022-08"]["minimo"], meses["2022-08"]["maximo"]) == (17.5, 65.9)
    assert meses["2022-08"]["frac_estimada"] == pytest.approx(3 / 31)
    assert meses["2026-11"]["parcial"] is True


def test_zona_de_dos_provincias(cliente):
    r = cliente.get(
        "/api/v1/calendario",
        params={"bbox": "-68,-35,-62,-31", "desde": "2011-09", "hasta": "2011-09"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["meses"][0]["armonizado"] == 35


def test_referencia_viirs_sale_de_metadata(tmp_path, hacer_cliente):
    # Si el pipeline adelanta el cambio a NOAA-20, la API lo sigue sin tocar código.
    destino = tmp_path / "datos"
    shutil.copytree(FIXTURES, destino)
    meta = json.loads((destino / "metadata.json").read_text())
    meta["referencia_viirs"] = [
        {"satelite": "SNPP", "desde": "2012-01-20", "hasta": "2022-07-31"},
        {"satelite": "N20", "desde": "2022-08-01", "hasta": None},
    ]
    (destino / "metadata.json").write_text(json.dumps(meta))
    cliente = hacer_cliente(data_dir=destino)
    r = cliente.get(
        "/api/v1/calendario", params={"provincia_id": "P1", "desde": "2022-08", "hasta": "2022-08"}
    )
    assert r.status_code == 200, r.text
    (mes,) = r.json()["meses"]
    # Con N20 de referencia, agosto es 100 % observado: solo el N20 del día 11 (9 focos).
    assert (mes["armonizado"], mes["viirs"], mes["estado"]) == (9, 9, "observado")


def test_referencia_viirs_invalida_deja_degradado(tmp_path, hacer_cliente):
    destino = tmp_path / "datos"
    shutil.copytree(FIXTURES, destino)
    meta = json.loads((destino / "metadata.json").read_text())
    meta["referencia_viirs"][1]["satelite"] = "N21"  # NOAA-21 nunca es referencia
    (destino / "metadata.json").write_text(json.dumps(meta))
    cliente = hacer_cliente(data_dir=destino)
    assert cliente.get("/api/v1/health").json()["estado"] == "degradado"
