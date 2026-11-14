"""Configuración por variables de entorno (docs/05 §2)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", frozen=True)

    data_dir: Path = Path("/var/data/current")
    duckdb_memory_limit: str = Field("500MB", pattern=r"^\d+(\.\d+)?\s*[KMGT]i?B$")
    duckdb_threads: int = Field(1, ge=1)
    query_timeout_s: float = Field(10, gt=0)
    max_consultas_concurrentes: int = Field(4, ge=1)
    cors_origins: Annotated[list[str], NoDecode]
    reload_token: SecretStr
    max_celdas_mapa: int = Field(20_000, ge=1)
    max_filas_csv: int = Field(500_000, ge=1)
    log_level: Literal["debug", "info", "warning"] = "info"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _separar_origenes(cls, valor: object) -> object:
        if isinstance(valor, str):
            return [o.strip() for o in valor.split(",") if o.strip()]
        return valor

    @field_validator("log_level", mode="before")
    @classmethod
    def _minusculas(cls, valor: object) -> object:
        return valor.lower() if isinstance(valor, str) else valor


@lru_cache
def get_settings() -> Settings:
    return Settings()  # los obligatorios vienen del entorno
