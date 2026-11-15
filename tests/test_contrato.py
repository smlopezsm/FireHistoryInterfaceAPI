"""Pruebas de contrato C1 (respuestas y OpenAPI), C7 (sin datos) y confianza (docs/04 §5)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, TypeAdapter

from app.schemas.anomalia import Anomalia
from app.schemas.armonizacion import Calendario, Serie
from app.schemas.health import Health
from app.schemas.mapa import ColeccionCeldas, ColeccionIndustriales
from app.schemas.metadata import Metadata
from app.schemas.provincias import Provincia
from app.services.armonizacion import Acumulado, pocos_datos
from app.services.zonas import ResumenProvincia, ZonaResuelta

P1 = {"provincia_id": "P1"}
MAPA = {"bbox": "-68,-35,-62,-31", "desde": "2011-09-01", "hasta": "2011-09-30"}
FOCOS = {**P1, "desde": "2022-08-01", "hasta": "2022-08-31"}

# (método, ruta, parámetros o body, modelo de la respuesta)
JSON: list[tuple[str, str, dict[str, Any], Any]] = [
    ("GET", "/health", {}, Health),
    ("GET", "/metadata", {}, Metadata),
    ("GET", "/provincias", {"geometria": "true"}, list[Provincia]),
    ("GET", "/calendario", P1, Calendario),
    ("POST", "/calendario", P1, Calendario),
    ("GET", "/serie", {**P1, "granularidad": "anio"}, Serie),
    ("POST", "/serie", P1, Serie),
    ("GET", "/anomalia", P1, Anomalia),
    ("POST", "/anomalia", P1, Anomalia),
    ("GET", "/mapa/celdas", MAPA, ColeccionCeldas),
    ("GET", "/mapa/industriales", {}, ColeccionIndustriales),
]
CSV = [
    ("GET", "/descargas/focos.csv", FOCOS),
    ("POST", "/descargas/focos.csv", FOCOS),
    ("GET", "/descargas/calendario.csv", P1),
    ("POST", "/descargas/calendario.csv", P1),
]


def _pedir(cliente: TestClient, metodo: str, ruta: str, datos: dict[str, Any]) -> Any:
    url = "/api/v1" + ruta
    if metodo == "GET":
        return cliente.get(url, params=datos)
    return cliente.post(url, json=datos)


@pytest.mark.parametrize(("metodo", "ruta", "datos", "modelo"), JSON)
def test_c1_respuestas_validan_contra_su_modelo(
    cliente: TestClient, metodo: str, ruta: str, datos: dict[str, Any], modelo: Any
) -> None:
    r = _pedir(cliente, metodo, ruta, datos)
    assert r.status_code == 200, r.text
    TypeAdapter(modelo).validate_python(r.json(), strict=False)


@pytest.mark.parametrize(("metodo", "ruta", "datos"), CSV)
def test_c1_descargas_csv(
    cliente: TestClient, metodo: str, ruta: str, datos: dict[str, Any]
) -> None:
    r = _pedir(cliente, metodo, ruta, datos)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"].startswith('attachment; filename="')


def test_c1_openapi_documenta_todo(cliente: TestClient) -> None:
    esquema = cliente.get("/openapi.json").json()
    rutas = {(m.upper(), p) for p, ops in esquema["paths"].items() for m in ops}
    esperadas = {(m, "/api/v1" + r) for m, r, *_ in JSON} | {(m, "/api/v1" + r) for m, r, _ in CSV}
    esperadas.add(("POST", "/api/v1/admin/reload"))
    assert rutas == esperadas
    assert len(esquema["paths"]) == 11  # los 11 endpoints de docs/03
    for ruta, operaciones in esquema["paths"].items():
        for metodo, op in operaciones.items():
            assert op.get("summary") and op.get("description"), (metodo, ruta)
            if ruta.endswith(".csv") or ruta.endswith("/reload"):
                continue
            contenido = op["responses"]["200"]["content"]["application/json"]
            assert contenido.get("schema"), (metodo, ruta)


DATOS_SIN_DATOS = [(m, r, d) for m, r, d, _ in JSON if r != "/health"] + CSV


@pytest.mark.parametrize(("metodo", "ruta", "datos"), DATOS_SIN_DATOS)
def test_c7_sin_datos_todos_los_endpoints_responden_503(
    cliente_sin_datos: TestClient, metodo: str, ruta: str, datos: dict[str, Any]
) -> None:
    r = _pedir(cliente_sin_datos, metodo, ruta, datos)
    assert r.status_code == 503, (ruta, r.text)
    assert r.json()["error"]["codigo"] == "DATOS_NO_DISPONIBLES"


# --- confianza (docs/04 §5) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("periodo", "confianza"),
    [("2022-07", "alta"), ("2022-08", "alta"), ("2012-01", "baja"), ("2006-08", "baja")],
)
def test_confianza_con_fixtures(cliente: TestClient, periodo: str, confianza: str) -> None:
    r = cliente.get("/api/v1/calendario", params={**P1, "desde": periodo, "hasta": periodo})
    assert r.json()["meses"][0]["confianza"] == confianza


def _estimado(valor: float = 150, ancho: float = 100, **cambios: Any) -> Acumulado:
    """Mes 100 % estimado con `valor` focos y un rango de `ancho` (Terra + Aqua)."""
    base: dict[str, Any] = {
        "dias": 31,
        "estimados": 31,
        "est_modis": 50,
        "armonizado": valor,
        "minimo": valor * 0.7,
        "maximo": valor * 0.7 + ancho,
    }
    base.update(cambios)
    return Acumulado(**base)


@pytest.mark.parametrize(
    ("acumulado", "confianza"),
    [
        (Acumulado(dias=31, estimados=3, est_modis=2), "alta"),  # frac ≤ 0,1
        # H15: media si el rango no es más ancho que lo estimado
        (_estimado(ancho=100), "media"),
        (_estimado(ancho=150), "media"),  # en el límite
        (_estimado(ancho=151), "baja"),
        (_estimado(valor=0, ancho=9, est_modis=0), "baja"),  # estimado 0
        # mixto: el ancho se compara con lo estimado (150), no con el total (250)
        (_estimado(valor=250, ancho=130, estimados=10, obs=100), "media"),
        (_estimado(valor=250, ancho=160, estimados=10, obs=100), "baja"),
        # mixto sin focos MODIS en los días estimados: no hay base para "media"
        (_estimado(valor=100, ancho=0, estimados=10, obs=100, est_modis=0), "baja"),
        (_estimado(est_modis=0, est_terra=50), "baja"),  # período solo Terra
        # H9: más del 10 % de los días estimados sin MODIS → baja
        (_estimado(sin_modis=4), "baja"),
        (_estimado(sin_modis=3), "media"),
        (Acumulado(dias=31, estimados=3, est_modis=50, sin_modis=1), "alta"),  # frac ≤ 0,1
        # H13: más de la mitad del estimado con factor regional o nacional → baja
        (_estimado(est_no_provincial=76), "baja"),
        (_estimado(est_no_provincial=75), "media"),
        (_estimado(valor=250, estimados=10, obs=100, est_no_provincial=100), "baja"),
    ],
)
def test_reglas_de_confianza(acumulado: Acumulado, confianza: str) -> None:
    assert acumulado.punto("2010-08", pocos_datos=False).confianza == confianza


def test_region_con_provincias_chicas_no_es_media() -> None:
    # H15: 121 focos MODIS en total, pero repartidos: el rango sumado supera al valor.
    region = Acumulado(dias=31, estimados=31, est_modis=121)
    for _ in range(5):
        region.sumar_mes(_estimado(valor=80, ancho=105, est_modis=24, dias=0, estimados=0))
    assert region.est_modis == 241
    assert region.punto("2002-12", pocos_datos=False).confianza == "baja"


def _zona(areas: dict[str, float]) -> ZonaResuelta:
    return ZonaResuelta(
        tipo="bbox",
        id=None,
        bbox=None,
        celdas_ids=[1],
        area_km2=sum(areas.values()),
        provincias={p: ResumenProvincia(celdas=1, area_km2=a) for p, a in areas.items()},
    )


def test_pocos_datos_por_area() -> None:
    assert pocos_datos(_zona({"94": 60, "74": 40}))  # Tierra del Fuego > 50 %
    assert not pocos_datos(_zona({"78": 50, "74": 50}))  # exactamente 50 % no alcanza
    assert pocos_datos(_zona({"02": 10, "78": 45, "14": 45}))  # CABA + Santa Cruz


def test_modelos_tienen_descripciones() -> None:
    for modelo in (Calendario, Serie, Anomalia, ColeccionCeldas):
        assert isinstance(modelo, type) and issubclass(modelo, BaseModel)
    from app.schemas.armonizacion import Punto

    assert all(c.description for c in Punto.model_fields.values())
    assert all(c.description for c in Anomalia.model_fields.values())


@pytest.mark.parametrize(
    ("acumulado", "confianza"),
    [
        (Acumulado(dias=31, estimados=0), "alta"),  # 100 % observado
        (Acumulado(dias=31, estimados=3, est_modis=2), "alta"),  # frac ≤ 0,1
        (Acumulado(dias=31, estimados=31, est_modis=50), "baja"),  # estimado
        (Acumulado(dias=31, estimados=10, est_modis=50), "baja"),  # mixto con frac > 0,1
    ],
)
def test_pocos_datos_no_baja_los_meses_observados(acumulado: Acumulado, confianza: str) -> None:
    # Decisión del equipo (2026-11-14): "pocos datos" solo afecta a lo estimado.
    assert acumulado.punto("2023-08", pocos_datos=True).confianza == confianza
