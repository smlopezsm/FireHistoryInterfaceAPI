"""Pruebas de anomalías históricas."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.services.anomalia import comparar, primer_mes_observado
from app.services.armonizacion import Acumulado

INICIO_VIIRS = "2012-02"  # primer mes completo con S-NPP (desde 2012-01-20)
TODO_OBSERVADO = "2000-01"


def test_compara_mismo_mes_y_excluye_evaluado(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2022-08"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["valor"] == 24
    # 2022-08 es observado (frac 3/31): se compara con los agostos observados 2012–2026.
    assert cuerpo["referencia"] == "observada"
    assert cuerpo["anios_usados"] == 14
    assert cuerpo["mediana"] == 0
    assert cuerpo["razon"] is None


def test_ultimo_mes_completo(cliente: TestClient) -> None:
    r = cliente.post("/api/v1/anomalia", json={"provincia_id": "P1"})
    assert r.status_code == 200, r.text
    assert r.json()["mes"] == "2026-10"


def test_mes_parcial_sin_categoria(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2026-11"})
    assert r.status_code == 200, r.text
    assert r.json()["categoria"] is None


def test_mes_invalido(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2022-8"})
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "PERIODO_INVALIDO"


def test_u10_menos_de_diez_anios() -> None:
    meses = {f"{anio}-08": Acumulado(armonizado=10) for anio in range(2010, 2020)}
    resultado = comparar(meses, "2019-08", inicio_observado=TODO_OBSERVADO)
    assert resultado.anios_usados == 9
    assert resultado.categoria is None


@pytest.mark.parametrize(
    ("valor", "categoria"),
    [
        (0, "muy_por_debajo"),
        (2, "por_debajo"),
        (6, "normal"),
        (10, "por_encima"),
        (12, "muy_por_encima"),
    ],
)
def test_categorias_con_historial_suficiente(valor: float, categoria: str) -> None:
    meses = {f"{2010 + i}-08": Acumulado(armonizado=i + 1) for i in range(12)}
    meses["2022-08"] = Acumulado(armonizado=valor)
    resultado = comparar(meses, "2022-08", inicio_observado=TODO_OBSERVADO)
    assert resultado.categoria == categoria
    assert resultado.mediana == 6.5
    assert (resultado.p25, resultado.p75) == (3, 9)


def test_muestra_excluye_meses_parciales(cliente: TestClient) -> None:
    # 2026-11 está incompleto (datos hasta el 13): no puede entrar en el histórico de noviembre.
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2025-11"})
    assert r.status_code == 200, r.text
    # Noviembres observados completos: 2012 a 2025 (14) menos el evaluado = 13.
    assert r.json()["anios_usados"] == 13


def test_muestra_excluye_parciales_unitario() -> None:
    meses = {f"{2010 + i}-11": Acumulado(armonizado=5) for i in range(12)}
    meses["2022-11"] = Acumulado(armonizado=1000, parcial=True)
    resultado = comparar(meses, "2021-11", inicio_observado=TODO_OBSERVADO)
    assert resultado.anios_usados == 11
    assert resultado.mediana == 5


def _eras() -> dict[str, Acumulado]:
    # 2001–2011 estimados (nivel 100) y 2012–2025 observados (nivel 10).
    meses = {
        f"{anio}-08": Acumulado(dias=31, estimados=31, armonizado=100) for anio in range(2001, 2012)
    }
    meses.update(
        {f"{anio}-08": Acumulado(dias=31, estimados=0, armonizado=10) for anio in range(2012, 2026)}
    )
    return meses


def test_anomalia_compara_con_la_misma_era_observada() -> None:
    resultado = comparar(_eras(), "2020-08", inicio_observado=INICIO_VIIRS)
    assert (resultado.referencia, resultado.anios_usados) == ("observada", 13)
    assert (resultado.mediana, resultado.categoria) == (10, "normal")


def test_anomalia_compara_con_la_misma_era_estimada() -> None:
    resultado = comparar(_eras(), "2005-08", inicio_observado=INICIO_VIIRS)
    assert (resultado.referencia, resultado.anios_usados) == ("estimada", 10)
    assert (resultado.mediana, resultado.categoria) == (100, "normal")


def test_era_por_fecha_y_no_por_frac_estimada() -> None:
    # Un mes de la época VIIRS con la referencia caída muchos días (2022-08 tuvo 10 de 31)
    # sigue en la era observada: se compara con 2012+ y no con 2001–2011.
    meses = _eras()
    meses["2022-08"] = Acumulado(dias=31, estimados=10, armonizado=9)
    resultado = comparar(meses, "2022-08", inicio_observado=INICIO_VIIRS)
    assert (resultado.referencia, resultado.anios_usados) == ("observada", 13)
    assert (resultado.mediana, resultado.categoria) == (10, "muy_por_debajo")
    # Y tampoco sale de la muestra de los demás años observados.
    assert comparar(meses, "2020-08", inicio_observado=INICIO_VIIRS).anios_usados == 13


def test_mes_de_inicio_de_viirs_es_estimado() -> None:
    # 2012-01 tiene S-NPP desde el 20: es mayormente estimado y va con 2001–2011.
    meses = {f"{anio}-01": Acumulado(armonizado=100) for anio in range(2001, 2013)}
    resultado = comparar(meses, "2012-01", inicio_observado=INICIO_VIIRS)
    assert (resultado.referencia, resultado.anios_usados) == ("estimada", 11)


@pytest.mark.parametrize(
    ("desde", "primer_mes"), [(date(2012, 1, 20), "2012-02"), (date(2026, 11, 1), "2026-11")]
)
def test_primer_mes_observado(desde: date, primer_mes: str) -> None:
    assert primer_mes_observado(desde) == primer_mes


def test_anomalia_era_por_fecha_con_fixtures(cliente: TestClient) -> None:
    for mes, era in [("2012-01", "estimada"), ("2012-02", "observada"), ("2011-12", "estimada")]:
        r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": mes})
        assert r.status_code == 200, r.text
        assert r.json()["referencia"] == era, mes


def test_anomalia_informa_referencia(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2006-08"})
    assert r.status_code == 200, r.text
    assert r.json()["referencia"] == "estimada"
