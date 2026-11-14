"""Configuración por entorno (docs/05 §2)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_defaults_y_cors_separado_por_comas(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com, http://localhost:5173")
    monkeypatch.setenv("RELOAD_TOKEN", "secreto")
    s = Settings(_env_file=None)
    assert s.cors_origins == ["https://a.example.com", "http://localhost:5173"]
    assert s.data_dir == Path("/var/data/current")
    assert s.duckdb_memory_limit == "500MB"
    assert s.duckdb_threads == 1
    assert s.query_timeout_s == 10
    assert s.max_celdas_mapa == 20_000
    assert s.max_filas_csv == 500_000
    assert s.reload_token.get_secret_value() == "secreto"
    assert "secreto" not in repr(s)


@pytest.mark.parametrize("falta", ["CORS_ORIGINS", "RELOAD_TOKEN"])
def test_variables_obligatorias(monkeypatch: pytest.MonkeyPatch, falta: str) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com")
    monkeypatch.setenv("RELOAD_TOKEN", "x")
    monkeypatch.delenv(falta)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_memory_limit_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com")
    monkeypatch.setenv("RELOAD_TOKEN", "x")
    monkeypatch.setenv("DUCKDB_MEMORY_LIMIT", "mucho")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
