"""/health y /metadata (docs/03), incluida la parte de C7 de F1."""

from __future__ import annotations

import inspect
from collections.abc import Callable

import anyio
import anyio.to_thread
import httpx
import pytest
from fastapi.testclient import TestClient

from app.deps import datos_listos, obtener_datos
from app.routers.health import health
from app.routers.metadata import metadata
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
    assert r.headers["etag"] == f'"{VERSION}"'
    r2 = cliente.get("/api/v1/metadata", headers={"If-None-Match": r.headers["etag"]})
    assert r2.status_code == 304
    assert r2.content == b""


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


def test_health_y_metadata_son_async_sin_threadpool(
    cliente: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert inspect.iscoroutinefunction(health)
    assert inspect.iscoroutinefunction(metadata)
    assert inspect.iscoroutinefunction(obtener_datos)
    assert inspect.iscoroutinefunction(datos_listos)

    def _prohibido(*args: object, **kwargs: object) -> object:
        raise AssertionError("No debe usar el threadpool de AnyIO")

    monkeypatch.setattr(anyio.to_thread, "run_sync", _prohibido)

    async def _probar() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=cliente.app),
            base_url="http://test",
        ) as ac:
            r_health = await ac.get("/api/v1/health")
            r_meta = await ac.get("/api/v1/metadata")
            assert r_health.status_code == 200
            assert r_health.json()["estado"] == "ok"
            assert r_meta.status_code == 200
            assert r_meta.json()["data_version"] == VERSION

    anyio.run(_probar)
