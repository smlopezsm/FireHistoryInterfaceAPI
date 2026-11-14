"""Resolución de zona: provincia, bbox y polígono → celdas por centroide (F2)."""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Annotated, Any

import pytest
from fastapi import Body, FastAPI
from fastapi.testclient import TestClient

from app.db import Datos
from app.deps import DatosListosDep, ZonaQueryDep
from app.errores import ApiError
from app.schemas.zonas import PedidoZona, Zona
from app.services.zonas import resolver_zona
from tests.conftest import crear_settings


@pytest.fixture(scope="module")
def datos() -> Iterator[Datos]:
    d = Datos(crear_settings())
    d.abrir()
    yield d
    d.cerrar()


def _extension(datos: Datos, provincia: str | None = None) -> tuple[float, float, float, float]:
    filtro = "WHERE provincia_id = ?" if provincia else ""
    f = datos.consultar(
        "SELECT min(lon_centro) o, min(lat_centro) s, max(lon_centro) e, max(lat_centro) n "
        f"FROM dim_celdas {filtro}",
        [provincia] if provincia else None,
    )[0]
    return f["o"], f["s"], f["e"], f["n"]


def _bbox(ext: tuple[float, float, float, float], margen: float = 0.01) -> str:
    o, s, e, n = ext
    return f"{o - margen},{s - margen},{e + margen},{n + margen}"


def _rectangulo(ext: tuple[float, float, float, float], margen: float = 0.01) -> list[list[float]]:
    o, s, e, n = ext
    o, s, e, n = o - margen, s - margen, e + margen, n + margen
    return [[o, s], [e, s], [e, n], [o, n], [o, s]]


def _error(datos: Datos, **pedido: Any) -> ApiError:
    with pytest.raises(ApiError) as exc:
        resolver_zona(datos, PedidoZona(**pedido))
    return exc.value


# --- una sola zona ------------------------------------------------------------------------


def test_sin_zona(datos: Datos) -> None:
    e = _error(datos)
    assert (e.status, e.codigo) == (400, "ZONA_INVALIDA")
    assert e.mensaje == "Indicá una sola zona: provincia_id, bbox o geometria."


def test_dos_zonas(datos: Datos) -> None:
    e = _error(datos, provincia_id="P1", bbox="-67,-34,-65,-32")
    assert (e.status, e.codigo) == (400, "ZONA_INVALIDA")


# --- provincia ----------------------------------------------------------------------------


def test_provincia(datos: Datos) -> None:
    z = resolver_zona(datos, PedidoZona(provincia_id="P1"))
    assert len(z.celdas_ids) == 10
    assert z.area_km2 == pytest.approx(250.0)
    assert set(z.provincias) == {"P1"}
    r = z.respuesta()
    assert (r.tipo, r.id, r.celdas, r.area_km2) == ("provincia", "P1", 10, 250.0)
    assert r.bbox is not None and len(r.bbox) == 4


def test_provincia_inexistente(datos: Datos) -> None:
    e = _error(datos, provincia_id="99")
    assert (e.status, e.codigo) == (404, "PROVINCIA_NO_ENCONTRADA")


# --- bbox ---------------------------------------------------------------------------------


def test_bbox_una_provincia(datos: Datos) -> None:
    z = resolver_zona(datos, PedidoZona(bbox=_bbox(_extension(datos, "P1"))))
    assert len(z.celdas_ids) == 10 and set(z.provincias) == {"P1"}
    assert z.respuesta().tipo == "bbox"


def test_bbox_cruza_provincias(datos: Datos) -> None:
    z = resolver_zona(datos, PedidoZona(bbox=_bbox(_extension(datos))))
    assert len(z.celdas_ids) == 20
    assert {p: r.celdas for p, r in z.provincias.items()} == {"P1": 10, "P2": 10}


def test_bbox_entra_por_centroide(datos: Datos) -> None:
    o, s, e, n = _extension(datos, "P1")
    # Un bbox que corta las celdas del borde oeste: solo entran las de centroide adentro.
    corte = o + 0.001
    z = resolver_zona(datos, PedidoZona(bbox=f"{corte},{s - 0.01},{e + 0.01},{n + 0.01}"))
    esperadas = datos.consultar(
        "SELECT list(cell_id ORDER BY cell_id) AS ids FROM dim_celdas "
        "WHERE provincia_id = 'P1' AND lon_centro >= ?",
        [corte],
    )[0]["ids"]
    assert 0 < len(esperadas) < 10
    assert z.celdas_ids == esperadas


def test_bbox_sin_celdas(datos: Datos) -> None:
    e = _error(datos, bbox="-60,-30,-59,-29")
    assert (e.status, e.codigo) == (400, "ZONA_INVALIDA")
    assert e.mensaje == "La zona no contiene celdas de Argentina."


@pytest.mark.parametrize(
    "bbox", ["-67,-34,-65", "a,b,c,d", "-65,-34,-67,-32", "-67,-32,-65,-34", "-200,-34,-65,-32"]
)
def test_bbox_mal_formado(datos: Datos, bbox: str) -> None:
    e = _error(datos, bbox=bbox)
    assert (e.status, e.codigo) == (422, "PARAMETRO_INVALIDO")


# --- polígono -----------------------------------------------------------------------------


def test_poligono(datos: Datos) -> None:
    geo = {"type": "Polygon", "coordinates": [_rectangulo(_extension(datos, "P2"))]}
    z = resolver_zona(datos, PedidoZona(geometria=geo))
    assert len(z.celdas_ids) == 10 and set(z.provincias) == {"P2"}
    assert z.respuesta().tipo == "geometria"


def test_multipoligono(datos: Datos) -> None:
    geo = {
        "type": "MultiPolygon",
        "coordinates": [
            [_rectangulo(_extension(datos, "P1"))],
            [_rectangulo(_extension(datos, "P2"))],
        ],
    }
    z = resolver_zona(datos, PedidoZona(geometria=geo))
    assert len(z.celdas_ids) == 20


def _circulo(lon: float, lat: float, radio: float, n: int) -> list[list[float]]:
    puntos = [
        [lon + radio * math.cos(2 * math.pi * i / n), lat + radio * math.sin(2 * math.pi * i / n)]
        for i in range(n)
    ]
    return [*puntos, puntos[0]]


def test_poligono_2000_vertices_ok(datos: Datos) -> None:
    o, s, e, n = _extension(datos)
    geo = {"type": "Polygon", "coordinates": [_circulo((o + e) / 2, (s + n) / 2, 1.0, 2000)]}
    assert len(resolver_zona(datos, PedidoZona(geometria=geo)).celdas_ids) == 20


def test_poligono_demasiados_vertices(datos: Datos) -> None:
    geo = {"type": "Polygon", "coordinates": [_circulo(-66.2, -33.3, 1.0, 2001)]}
    e = _error(datos, geometria=geo)
    assert (e.status, e.codigo) == (400, "GEOMETRIA_INVALIDA")
    assert e.detalle == {"vertices": 2001, "maximo": 2000}


def test_poligono_autointersecado(datos: Datos) -> None:
    moño = [[-66.5, -33.4], [-66.0, -33.2], [-66.0, -33.4], [-66.5, -33.2], [-66.5, -33.4]]
    e = _error(datos, geometria={"type": "Polygon", "coordinates": [moño]})
    assert (e.status, e.codigo) == (400, "GEOMETRIA_INVALIDA")
    assert "Self-intersection" in str(e.detalle)


@pytest.mark.parametrize(
    "geo",
    [
        {"type": "Point", "coordinates": [-66, -33]},
        {"type": "Polygon"},
        {"type": "Polygon", "coordinates": [[[-66, -33], [-65, -33]]]},
        {"type": "Polygon", "coordinates": "no"},
        {
            "type": "Polygon",
            "coordinates": [[[5000000, 1000], [5000100, 1000], [5000100, 1100], [5000000, 1000]]],
        },
        {"coordinates": [[[-66, -33], [-65, -33], [-65, -32], [-66, -33]]]},
    ],
)
def test_geojson_invalido(datos: Datos, geo: dict[str, Any]) -> None:
    e = _error(datos, geometria=geo)
    assert (e.status, e.codigo) == (400, "GEOMETRIA_INVALIDA")


# --- por HTTP: GET (query) y POST (body) ----------------------------------------------------


@pytest.fixture
def cliente_zona(cliente: TestClient) -> TestClient:
    app: FastAPI = cliente.app  # type: ignore[assignment]

    @app.get("/api/v1/_zona", response_model=Zona)
    def _get(datos: DatosListosDep, zona: ZonaQueryDep) -> Zona:
        return resolver_zona(datos, zona).respuesta()

    @app.post("/api/v1/_zona", response_model=Zona)
    def _post(datos: DatosListosDep, pedido: Annotated[PedidoZona, Body()]) -> Zona:
        return resolver_zona(datos, pedido).respuesta()

    return cliente


def test_http_get_provincia(cliente_zona: TestClient) -> None:
    r = cliente_zona.get("/api/v1/_zona", params={"provincia_id": "P1"})
    assert r.status_code == 200
    assert r.json()["celdas"] == 10


def test_http_get_sin_zona(cliente_zona: TestClient) -> None:
    r = cliente_zona.get("/api/v1/_zona")
    assert r.status_code == 400
    assert r.json()["error"]["codigo"] == "ZONA_INVALIDA"


def test_http_post_geometria(cliente_zona: TestClient, datos: Datos) -> None:
    geo = {"type": "Polygon", "coordinates": [_rectangulo(_extension(datos))]}
    r = cliente_zona.post("/api/v1/_zona", json={"geometria": geo})
    assert r.status_code == 200
    assert r.json()["celdas"] == 20
    assert r.json()["area_km2"] == 500.0


def test_http_post_body_demasiado_grande(cliente_zona: TestClient) -> None:
    relleno = "x" * (256 * 1024)
    r = cliente_zona.post("/api/v1/_zona", json={"provincia_id": "P1", "relleno": relleno})
    assert r.status_code == 413
    assert r.json()["error"]["codigo"] == "CUERPO_DEMASIADO_GRANDE"


def test_http_post_body_chico_pasa(cliente_zona: TestClient) -> None:
    r = cliente_zona.post("/api/v1/_zona", json={"provincia_id": "P2"})
    assert r.status_code == 200
