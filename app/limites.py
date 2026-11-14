"""Límite de tamaño del body de los POST (docs/03 §Límites de uso: 256 KB)."""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.errores import respuesta_error

MAX_BODY_BYTES = 256 * 1024


class LimiteBodyMiddleware:
    """Lee el body completo (como máximo 256 KB) antes de pasarlo a la app."""

    def __init__(self, app: ASGIApp, maximo: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.maximo = maximo

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            await self.app(scope, receive, send)
            return

        declarado = dict(scope["headers"]).get(b"content-length")
        if declarado is not None and declarado.isdigit() and int(declarado) > self.maximo:
            await self._rechazar(scope, receive, send)
            return

        mensajes: list[Message] = []
        total = 0
        while True:
            mensaje = await receive()
            mensajes.append(mensaje)
            if mensaje["type"] != "http.request":
                break
            total += len(mensaje.get("body", b""))
            if total > self.maximo:
                await self._rechazar(scope, receive, send)
                return
            if not mensaje.get("more_body", False):
                break

        async def reproducir() -> Message:
            return mensajes.pop(0) if mensajes else await receive()

        await self.app(scope, reproducir, send)

    async def _rechazar(self, scope: Scope, receive: Receive, send: Send) -> None:
        respuesta = respuesta_error(
            413,
            "CUERPO_DEMASIADO_GRANDE",
            f"El cuerpo de la solicitud supera los {self.maximo // 1024} KB.",
        )
        await respuesta(scope, receive, send)
