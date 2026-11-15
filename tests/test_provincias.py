"""GET /provincias (docs/03 §provincias)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_provincias_sin_geometria(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/provincias")
    assert r.status_code == 200
    cuerpo = r.json()
    assert [p["provincia_id"] for p in cuerpo] == ["P1", "P2"]
    p1 = cuerpo[0]
    assert set(p1) == {"provincia_id", "nombre", "region", "bbox", "geometria"}
    assert (p1["nombre"], p1["region"], p1["geometria"]) == ("Provincia Uno", "R1", None)
    assert len(p1["bbox"]) == 4 and all(isinstance(v, float) for v in p1["bbox"])
    oeste, sur, este, norte = p1["bbox"]
    assert oeste < este and sur < norte
    assert r.headers["etag"]


def test_provincias_con_geometria(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/provincias", params={"geometria": "true"})
    geom = r.json()[0]["geometria"]
    assert geom["type"] == "Polygon"
    assert len(geom["coordinates"][0]) == 5


def test_provincias_parametro_invalido(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/provincias", params={"geometria": "quizas"})
    assert r.status_code == 422
    assert r.json()["error"]["codigo"] == "PARAMETRO_INVALIDO"


def test_provincias_sin_datos(cliente_sin_datos: TestClient) -> None:
    r = cliente_sin_datos.get("/api/v1/provincias")
    assert r.status_code == 503


def test_provincias_filtro_region(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/provincias", params={"region": "R2"})
    assert r.status_code == 200
    assert [p["provincia_id"] for p in r.json()] == ["P2"]

    vacia = cliente.get("/api/v1/provincias", params={"region": "NO_EXISTE"})
    assert vacia.status_code == 200
    assert vacia.json() == []
