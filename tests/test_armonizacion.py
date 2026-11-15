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


def test_calendario_y_serie_por_region(cliente):
    cal = cliente.get(
        "/api/v1/calendario",
        params={"region": "R1", "desde": "2006-08", "hasta": "2006-08"},
    )
    assert cal.status_code == 200, cal.text
    assert cal.json()["zona"]["tipo"] == "region"
    assert cal.json()["zona"]["id"] == "R1"
    assert cal.json()["meses"][0]["armonizado"] == 30

    serie = cliente.post(
        "/api/v1/serie",
        json={"region": "R2", "desde": "2011-05", "hasta": "2011-05"},
    )
    assert serie.status_code == 200, serie.text
    assert serie.json()["zona"]["tipo"] == "region"
    assert serie.json()["puntos"][0]["armonizado"] == 14


def _apagar_modis(destino, fechas, satelite="Terra"):
    """Deja `satelite` no operativo en `fechas` (texto YYYY-MM-DD) en una copia de los fixtures."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    ruta = destino / "satelite_operativo.parquet"
    tabla = pq.read_table(ruta)
    apagar = pc.and_(
        pc.equal(tabla["satelite"], satelite),
        pc.is_in(pc.cast(tabla["fecha"], pa.string()), value_set=pa.array(fechas)),
    )
    columna = tabla.schema.get_field_index("operativo")
    operativo = pc.if_else(apagar, False, tabla["operativo"])
    pq.write_table(tabla.set_column(columna, tabla.schema.field(columna), operativo), ruta)


def test_modis_caido_se_informa_y_ensancha_el_maximo(tmp_path, hacer_cliente):
    # H9: un día estimado sin Terra no puede sumar 0 en silencio.
    destino = tmp_path / "datos"
    shutil.copytree(FIXTURES, destino)
    _apagar_modis(destino, ["2006-08-10"])
    cliente = hacer_cliente(data_dir=destino)
    r = cliente.get(
        "/api/v1/calendario", params={"provincia_id": "P1", "desde": "2006-08", "hasta": "2006-08"}
    )
    assert r.status_code == 200, r.text
    (mes,) = r.json()["meses"]
    # U1 sin cambios en el valor (30,0) ni en el mínimo (16,5); el máximo (55,8) se
    # escala por los días con MODIS: 55,8 x 31 / 30.
    assert mes["dias_sin_modis"] == 1
    assert (mes["armonizado"], mes["minimo"]) == (30, 16.5)
    assert mes["maximo"] == pytest.approx(55.8 * 31 / 30, abs=0.1)
    assert mes["confianza"] == "baja"


def test_aqua_caido_cuenta_desde_2002(tmp_path, hacer_cliente):
    destino = tmp_path / "datos"
    shutil.copytree(FIXTURES, destino)
    _apagar_modis(destino, ["2006-08-10", "2006-08-11"], satelite="Aqua")
    cliente = hacer_cliente(data_dir=destino)
    r = cliente.get(
        "/api/v1/serie",
        params={
            "provincia_id": "P1",
            "desde": "2006-01",
            "hasta": "2006-12",
            "granularidad": "anio",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["puntos"][0]["dias_sin_modis"] == 2


def test_dias_observados_no_cuentan_como_sin_modis(tmp_path, hacer_cliente):
    # Si la referencia VIIRS operó, que falte MODIS no importa.
    destino = tmp_path / "datos"
    shutil.copytree(FIXTURES, destino)
    _apagar_modis(destino, ["2022-07-04"])
    cliente = hacer_cliente(data_dir=destino)
    r = cliente.get(
        "/api/v1/calendario", params={"provincia_id": "P1", "desde": "2022-07", "hasta": "2022-07"}
    )
    (mes,) = r.json()["meses"]
    assert (mes["dias_sin_modis"], mes["confianza"]) == (0, "alta")


def test_fixtures_sin_modis_caido(cliente):
    r = cliente.get("/api/v1/calendario", params={"provincia_id": "P1"})
    assert {m["dias_sin_modis"] for m in r.json()["meses"]} == {0}


def test_estimado_con_factor_no_provincial(cliente):
    # H13: U8 (P2, mayo) usa el factor de la región para todo su estimado.
    from app.schemas.armonizacion import PeriodoConsulta
    from app.schemas.zonas import PedidoZona
    from app.services.armonizacion import calcular_meses
    from app.services.zonas import resolver_zona

    datos = cliente.app.state.datos
    zona = resolver_zona(datos, PedidoZona(provincia_id="P2"))
    meses = calcular_meses(datos, zona, PeriodoConsulta(desde="2011-05", hasta="2011-05"))
    assert meses["2011-05"].est_no_provincial == pytest.approx(14.0)
    zona = resolver_zona(datos, PedidoZona(provincia_id="P1"))
    meses = calcular_meses(datos, zona, PeriodoConsulta(desde="2011-05", hasta="2011-05"))
    assert meses["2011-05"].est_no_provincial == 0
