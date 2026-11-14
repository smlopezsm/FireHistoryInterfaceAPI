"""Configuración común de las pruebas."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIXTURES = Path(__file__).parent / "fixtures"
ORIGEN_FRONT = "http://localhost:5173"


def crear_settings(**cambios: Any) -> Settings:
    base: dict[str, Any] = {
        "data_dir": FIXTURES,
        "cors_origins": ORIGEN_FRONT,
        "reload_token": "token-de-prueba",
    }
    base.update(cambios)
    return Settings(_env_file=None, **base)


@pytest.fixture
def hacer_cliente() -> Iterator[Callable[..., TestClient]]:
    abiertos: list[TestClient] = []

    def _hacer(**cambios: Any) -> TestClient:
        cliente = TestClient(create_app(crear_settings(**cambios)))
        cliente.__enter__()  # ejecuta el lifespan (abre DuckDB)
        abiertos.append(cliente)
        return cliente

    yield _hacer
    for cliente in abiertos:
        cliente.__exit__(None, None, None)


@pytest.fixture
def cliente(hacer_cliente: Callable[..., TestClient]) -> TestClient:
    return hacer_cliente()


@pytest.fixture
def cliente_sin_datos(hacer_cliente: Callable[..., TestClient], tmp_path: Path) -> TestClient:
    return hacer_cliente(data_dir=tmp_path / "no-existe")
