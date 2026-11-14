"""Cabeceras de caché (docs/03 §Convenciones): `Cache-Control` y `ETag = data_version`."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

CACHE_CONTROL = "public, max-age=3600"
# Rutas que nunca se cachean (estado en vivo y administración).
SIN_CACHE = ("/api/v1/health", "/api/v1/admin/")


class CacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        datos = getattr(request.app.state, "datos", None)
        version = datos.data_version if datos is not None else None
        cacheable = (
            request.method in ("GET", "HEAD")
            and request.url.path.startswith("/api/v1/")
            and not request.url.path.startswith(SIN_CACHE)
            and version is not None
        )
        if not cacheable:
            return await call_next(request)

        etag = f'"{version}"'
        if etag in _etags(request.headers.get("if-none-match")):
            return Response(status_code=304, headers={"ETag": etag, "Cache-Control": CACHE_CONTROL})
        respuesta = await call_next(request)
        if respuesta.status_code == 200:
            respuesta.headers["ETag"] = etag
            respuesta.headers["Cache-Control"] = CACHE_CONTROL
        return respuesta


def _etags(cabecera: str | None) -> set[str]:
    if not cabecera:
        return set()
    return {e.strip().removeprefix("W/") for e in cabecera.split(",")}
