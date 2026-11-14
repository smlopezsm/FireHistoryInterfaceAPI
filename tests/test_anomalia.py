"""Pruebas de anomalías históricas."""

import pytest
from fastapi.testclient import TestClient

from app.services.anomalia import comparar
from app.services.armonizacion import Acumulado


def test_compara_mismo_mes_y_excluye_evaluado(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2022-08"})
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["valor"] == 24
    assert cuerpo["anios_usados"] == 25
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
    resultado = comparar(meses, "2019-08")
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
    resultado = comparar(meses, "2022-08")
    assert resultado.categoria == categoria
    assert resultado.mediana == 6.5
    assert (resultado.p25, resultado.p75) == (3, 9)


def test_muestra_excluye_meses_parciales(cliente: TestClient) -> None:
    # 2026-11 está incompleto (datos hasta el 13): no puede entrar en el histórico de noviembre.
    r = cliente.get("/api/v1/anomalia", params={"provincia_id": "P1", "mes": "2025-11"})
    assert r.status_code == 200, r.text
    # Noviembres completos: 2000 a 2025 (26) menos el evaluado = 25.
    assert r.json()["anios_usados"] == 25


def test_muestra_excluye_parciales_unitario() -> None:
    meses = {f"{2010 + i}-11": Acumulado(armonizado=5) for i in range(12)}
    meses["2022-11"] = Acumulado(armonizado=1000, parcial=True)
    resultado = comparar(meses, "2021-11")
    assert resultado.anios_usados == 11
    assert resultado.mediana == 5
