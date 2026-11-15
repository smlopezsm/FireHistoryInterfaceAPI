"""Cabeceras de caché (docs/03 §Convenciones): `Cache-Control` y `ETag` por ruta y versión."""

from __future__ import annotations

from hashlib import sha256
from urllib.parse import urlencode

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CACHE_CONTROL = "public, max-age=3600"
# Rutas que nunca se cachean (estado en vivo y administración).
SIN_CACHE = ("/api/v1/health", "/api/v1/admin/")


class CacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        datos = getattr(request.app.state, "datos", None)
        if datos is None:
            return await call_next(request)
        with datos.fijar_version():
            return await self._con_version(request, call_next, datos.data_version)

    async def _con_version(
        self, request: Request, call_next: RequestResponseEndpoint, version: str | None
    ) -> Response:
        if (
            request.method not in ("GET", "HEAD")
            or not request.url.path.startswith("/api/v1/")
            or request.url.path.startswith(SIN_CACHE)
            or version is None
        ):
            return await call_next(request)

        etag = _etag(version, request)
        if etag in _etags(request.headers.get("if-none-match")):
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})
        respuesta = await call_next(request)
        if respuesta.status_code == 200:
            respuesta.headers["ETag"] = etag
            respuesta.headers["Cache-Control"] = CACHE_CONTROL
        return respuesta


def _etag(version: str, request: Request) -> str:
    """Genera un ETag fuerte ligado a `data_version`, ruta y query params canonizados."""
    consulta = urlencode(sorted(request.query_params.multi_items()))
    clave = f"{request.url.path}?{consulta}" if consulta else request.url.path
    resumen = sha256(clave.encode("utf-8")).hexdigest()[:12]
    return f'"{version}-{resumen}"'


def _etags(cabecera: str | None) -> set[str]:
    if not cabecera:
        return set()
    return {e.strip().removeprefix("W/") for e in cabecera.split(",")}
