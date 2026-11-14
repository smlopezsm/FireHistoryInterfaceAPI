"""Capa de datos: DuckDB por worker, errores 422 y corte por tiempo."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app.db import Datos
from app.errores import ApiError
from tests.conftest import crear_settings


def test_vistas_y_particion_anio() -> None:
    datos = Datos(crear_settings())
    datos.abrir()
    try:
        assert datos.listo
        filas = datos.consultar(
            "SELECT anio, sum(n_terra + n_aqua) AS modis FROM conteos_celda_dia "
            "WHERE fecha BETWEEN ? AND ? GROUP BY anio",
            ["2006-08-01", "2006-08-31"],
        )
        assert filas == [{"anio": 2006, "modis": 10}]
        tipos = datos.consultar("SELECT typeof(anio) AS t FROM focos LIMIT 1")
        assert tipos == [{"t": "SMALLINT"}]
    finally:
        datos.cerrar()


def test_solo_lectura() -> None:
    datos = Datos(crear_settings())
    datos.abrir()
    try:
        with pytest.raises(Exception, match=r"(?i)view|catalog|not supported|cannot"):
            datos.consultar("INSERT INTO dim_celdas SELECT * FROM dim_celdas")
        with pytest.raises(Exception, match=r"(?i)lock"):
            datos.consultar("SET memory_limit = '10GB'")
    finally:
        datos.cerrar()


def test_corte_por_tiempo() -> None:
    datos = Datos(crear_settings(query_timeout_s=0.2, duckdb_threads=1))
    datos.abrir()
    try:
        with pytest.raises(ApiError) as exc:
            datos.consultar("SELECT count(*) FROM range(100000000000) a")
        assert exc.value.status == 504
        assert exc.value.codigo == "TIEMPO_EXCEDIDO"
        # la conexión sigue sana después del corte
        assert datos.consultar("SELECT 1 AS uno") == [{"uno": 1}]
    finally:
        datos.cerrar()


def test_sin_datos_consulta_503(tmp_path) -> None:
    datos = Datos(crear_settings(data_dir=tmp_path))
    datos.abrir()
    assert not datos.listo
    with pytest.raises(ApiError) as exc:
        datos.consultar("SELECT 1")
    assert exc.value.status == 503


def test_error_de_validacion_422(cliente: TestClient) -> None:
    app: FastAPI = cliente.app  # type: ignore[assignment]

    @app.get("/api/v1/_prueba")
    def _prueba(n: int = Query(...)) -> dict[str, int]:
        return {"n": n}

    r = cliente.get("/api/v1/_prueba", params={"n": "abc"})
    assert r.status_code == 422
    error = r.json()["error"]
    assert error["codigo"] == "PARAMETRO_INVALIDO"
    assert error["detalle"][0]["campo"] == "query.n"


def test_celdas_de_zona_grande_viajan_como_tabla() -> None:
    # Argentina tiene ~112.000 celdas: pasarlas como lista parametrizada tardaba ~8 s.
    datos = Datos(crear_settings())
    datos.abrir()
    try:
        reales = [f["cell_id"] for f in datos.consultar("SELECT cell_id FROM dim_celdas")]
        celdas = list(range(1, 120_000)) + reales
        inicio = time.perf_counter()
        filas = datos.consultar(
            "SELECT count(*) AS n FROM conteos_celda_dia "
            "WHERE cell_id IN (SELECT cell_id FROM zona_celdas)",
            celdas=celdas,
        )
        assert time.perf_counter() - inicio < 2
        total = datos.consultar("SELECT count(*) AS n FROM conteos_celda_dia")
        assert filas == total
    finally:
        datos.cerrar()


def test_codigo_no_pasa_listas_de_celdas_como_parametro() -> None:
    for archivo in Path("app").rglob("*.py"):
        assert "unnest(?::INTEGER[])" not in archivo.read_text(), archivo
