"""/health y /metadata (docs/03), incluida la parte de C7 de F1."""

from __future__ import annotations

from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.conftest import ORIGEN_FRONT

VERSION = "2026-11-14T09:00:00-03:00"


def test_health_con_datos(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "estado": "ok",
        "datos_listos": True,
        "data_version": VERSION,
        "fecha_max": "2026-11-13",
    }
    assert "etag" not in r.headers  # /health no se cachea


def test_c7_health_sin_datos_degradado(cliente_sin_datos: TestClient) -> None:
    r = cliente_sin_datos.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {
        "estado": "degradado",
        "datos_listos": False,
        "data_version": None,
        "fecha_max": None,
    }


def test_c7_endpoint_de_datos_sin_datos_503(cliente_sin_datos: TestClient) -> None:
    r = cliente_sin_datos.get("/api/v1/metadata")
    assert r.status_code == 503
    assert r.json()["error"]["codigo"] == "DATOS_NO_DISPONIBLES"


def test_metadata_incompleta_queda_degradado(
    hacer_cliente: Callable[..., TestClient], tmp_path
) -> None:
    (tmp_path / "metadata.json").write_text('{"schema_version": "1.0.0"}')
    c = hacer_cliente(data_dir=tmp_path)
    assert c.get("/api/v1/health").json()["estado"] == "degradado"


def test_metadata(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/metadata")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["schema_version"] == "1.0.0"
    assert cuerpo["data_version"] == VERSION
    assert cuerpo["fecha_min"] == "2000-11-01"
    assert cuerpo["fecha_max"] == "2026-11-13"
    assert cuerpo["referencia_viirs"] == [
        {"satelite": "SNPP", "desde": "2012-01-20", "hasta": "2026-11-02"},
        {"satelite": "N20", "desde": "2026-11-03", "hasta": None},
    ]
    assert cuerpo["celdas_total"] == 20
    assert cuerpo["provincias_total"] == 2


def test_cache_etag_y_304(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/metadata")
    assert r.headers["cache-control"] == "public, max-age=3600"
    assert r.headers["etag"].startswith(f'"{VERSION}-')
    assert r.headers["etag"].endswith('"')
    r2 = cliente.get("/api/v1/metadata", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    assert r2.content == b""


def test_cache_etag_distingue_rutas_query_y_errores(cliente: TestClient) -> None:
    meta = cliente.get("/api/v1/metadata")
    prov = cliente.get("/api/v1/provincias", headers={"If-None-Match": meta.headers["etag"]})
    assert prov.status_code == 200
    assert prov.headers["etag"] != meta.headers["etag"]

    cal_a = cliente.get("/api/v1/calendario?provincia_id=P1&desde=2006-01")
    cal_b = cliente.get("/api/v1/calendario?desde=2006-01&provincia_id=P1")
    assert cal_a.status_code == 200
    assert cal_a.headers["etag"] == cal_b.headers["etag"]

    cal_p2 = cliente.get(
        "/api/v1/calendario?provincia_id=P2&desde=2006-01",
        headers={"If-None-Match": cal_a.headers["etag"]},
    )
    assert cal_p2.status_code == 200
    assert cal_p2.headers["etag"] != cal_a.headers["etag"]

    invalida = cliente.get(
        "/api/v1/calendario?provincia_id=NO_EXISTE",
        headers={"If-None-Match": meta.headers["etag"]},
    )
    assert invalida.status_code == 404


def test_cors_solo_frontend(cliente: TestClient) -> None:
    ok = cliente.get("/api/v1/health", headers={"Origin": ORIGEN_FRONT})
    assert ok.headers["access-control-allow-origin"] == ORIGEN_FRONT
    otro = cliente.get("/api/v1/health", headers={"Origin": "https://malicioso.example"})
    assert "access-control-allow-origin" not in otro.headers


def test_ruta_inexistente_con_formato_de_error(cliente: TestClient) -> None:
    r = cliente.get("/api/v1/no-existe")
    assert r.status_code == 404
    assert r.json() == {
        "error": {
            "codigo": "RUTA_NO_ENCONTRADA",
            "mensaje": "La ruta pedida no existe.",
            "detalle": None,
        }
    }


def test_openapi_en_espanol(cliente: TestClient) -> None:
    esquema = cliente.get("/openapi.json").json()
    assert "/api/v1/health" in esquema["paths"]
    assert "/api/v1/metadata" in esquema["paths"]
    assert esquema["paths"]["/api/v1/health"]["get"]["summary"] == "Estado del servicio"
    assert cliente.get("/docs").status_code == 200
