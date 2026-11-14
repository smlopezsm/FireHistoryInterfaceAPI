"""Modelo del formato único de error (docs/03 §Errores)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorDetalle(BaseModel):
    codigo: str = Field(description="Código estable del error, por ejemplo `ZONA_INVALIDA`.")
    mensaje: str = Field(description="Mensaje en español para mostrar al usuario.")
    detalle: Any = Field(None, description="Información adicional (o `null`).")


class ErrorRespuesta(BaseModel):
    error: ErrorDetalle
