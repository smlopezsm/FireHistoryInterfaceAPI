"""Aplicación FastAPI de FireHistoryInterfaceAPI."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.cache import CacheMiddleware
from app.config import Settings, get_settings
from app.db import Datos
from app.errores import registrar_manejadores
from app.limites import LimiteBodyMiddleware
from app.routers import admin, anomalia, armonizacion, descargas, health, mapa, metadata, provincias

PREFIJO = "/api/v1"

DESCRIPCION = """
API del **calendario armonizado de focos de calor MODIS × VIIRS para Argentina**
(NASA Space Apps Challenge 2026).

Devuelve conteos de focos **a escala VIIRS S-NPP** por zona y período. Cuando no hubo
VIIRS de referencia, el valor se **estima** con MODIS × un factor provincia × mes, y
siempre se informa `estado`, `minimo`, `maximo` y `confianza`.

- `null` significa **sin dato**, nunca cero.
- Fuentes: NASA FIRMS (MODIS C6.1 y VIIRS 375 m). Límites: IGN vía API Georef.
"""

ETIQUETAS = [
    {"name": "estado", "description": "Salud del servicio y versión de los datos."},
    {
        "name": "zonas",
        "description": (
            "Provincias y zonas de consulta. Toda consulta usa **una sola** zona: "
            "`provincia_id`, `bbox` o un polígono GeoJSON (solo por POST). Entran las celdas "
            "de 5 × 5 km cuyo centroide cae dentro de la zona."
        ),
    },
]


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    logging.basicConfig(
        level=config.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Uvicorn ejecuta el lifespan en cada worker: una conexión DuckDB por worker.
        datos = Datos(config)
        datos.abrir()
        app.state.datos = datos

        async def revisar_version() -> None:
            while True:
                await asyncio.sleep(5)
                await asyncio.to_thread(datos.abrir, solo_si_cambio=True)

        monitor = asyncio.create_task(revisar_version())
        try:
            yield
        finally:
            monitor.cancel()
            with suppress(asyncio.CancelledError):
                await monitor
            await asyncio.to_thread(datos.cerrar)

    app = FastAPI(
        title="FireHistoryInterfaceAPI",
        summary="Focos de calor armonizados MODIS × VIIRS para Argentina",
        description=DESCRIPCION,
        version="0.1.0",
        openapi_tags=ETIQUETAS,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.state.settings = config

    app.add_middleware(CacheMiddleware)
    app.add_middleware(LimiteBodyMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "If-None-Match"],
        expose_headers=["ETag", "Content-Disposition"],
        max_age=3600,
    )
    registrar_manejadores(app)

    app.include_router(health.router, prefix=PREFIJO)
    app.include_router(metadata.router, prefix=PREFIJO)
    app.include_router(provincias.router, prefix=PREFIJO)
    app.include_router(armonizacion.router, prefix=PREFIJO)
    app.include_router(anomalia.router, prefix=PREFIJO)
    app.include_router(mapa.router, prefix=PREFIJO)
    app.include_router(descargas.router, prefix=PREFIJO)
    app.include_router(admin.router, prefix=PREFIJO)
    return app


def __getattr__(nombre: str) -> FastAPI:
    # `uvicorn app.main:app` crea la app recién al importarla, con la configuración del entorno.
    if nombre == "app":
        aplicacion = create_app()
        globals()["app"] = aplicacion
        return aplicacion
    raise AttributeError(nombre)
