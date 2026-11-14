"""Verificación del contrato CSV y del límite de filas."""

import csv

PARAMS = {"provincia_id": "P1", "desde": "2022-08-01", "hasta": "2022-08-31"}
FOCOS = "/api/v1/descargas/focos.csv"
CALENDARIO = "/api/v1/descargas/calendario.csv"


def test_focos_filtra_sensor_y_adjunta_csv(cliente):
    r = cliente.get(FOCOS, params={**PARAMS, "sensor": "VIIRS"})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == (
        'attachment; filename="focos_provincia-P1_2022-08-01_2022-08-31.csv"'
    )
    cita, cabecera, *datos = r.text.splitlines()
    assert cita.startswith("# Fuente: NASA FIRMS")
    assert cabecera == (
        "fecha,hora_utc,satelite,sensor,lat,lon,confianza,frp_mw,"
        "dia_noche,fuente,provincia_id,cell_id"
    )
    assert datos
    assert {fila["sensor"] for fila in csv.DictReader([cabecera, *datos])} == {"VIIRS"}


def test_c5_limite_de_filas(hacer_cliente):
    cliente = hacer_cliente(max_filas_csv=1)
    r = cliente.post(FOCOS, json={**PARAMS, "bbox": None})
    assert r.status_code == 413, r.text
    assert r.json()["error"]["codigo"] == "RESULTADO_DEMASIADO_GRANDE"
    assert "content-disposition" not in r.headers


def test_calendario_get_y_post_preservan_viirs_nulo(cliente):
    pedido = {"provincia_id": "P1", "desde": "2006-08", "hasta": "2006-08"}
    get = cliente.get(CALENDARIO, params=pedido)
    post = cliente.post(CALENDARIO, json=pedido)
    assert get.status_code == post.status_code == 200, (get.text, post.text)
    assert get.text == post.text
    (fila,) = csv.DictReader(get.text.splitlines())
    assert fila["viirs"] == ""
    assert fila["armonizado"] == "30.0"
    assert "parcial" not in fila


def test_focos_periodo_invalido(cliente):
    r = cliente.get(FOCOS, params={**PARAMS, "desde": "20220801"})
    assert r.status_code == 400, r.text
    assert r.json()["error"]["codigo"] == "PERIODO_INVALIDO"
