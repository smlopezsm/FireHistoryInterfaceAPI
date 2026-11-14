"""Recarga manual y cambio de versión por worker."""

import json
import shutil
import time
from pathlib import Path

from app.db import Datos
from tests.conftest import FIXTURES, crear_settings

RUTA = "/api/v1/admin/reload"
TOKEN = {"Authorization": "Bearer token-de-prueba"}


def _publicar(current: Path, destino: Path) -> None:
    temporal = current.with_name("nuevo")
    temporal.symlink_to(destino, target_is_directory=True)
    temporal.replace(current)


def test_autorizacion_c6(cliente):
    assert cliente.post(RUTA).status_code == 401
    assert cliente.post(RUTA, headers={"Authorization": "Bearer incorrecto"}).status_code == 403
    r = cliente.post(RUTA, headers=TOKEN)
    assert r.status_code == 204
    assert r.content == b""
    assert "etag" not in r.headers


def test_recarga_manual_y_automatica(tmp_path, hacer_cliente):
    current = tmp_path / "current"
    _publicar(current, FIXTURES)
    primero = hacer_cliente(data_dir=current)
    segundo = hacer_cliente(data_dir=current)
    vieja = primero.get("/api/v1/metadata").headers["etag"]

    rota = tmp_path / "rota"
    rota.mkdir()
    _publicar(current, rota)
    assert primero.post(RUTA, headers=TOKEN).status_code == 503
    assert primero.get("/api/v1/metadata").headers["etag"] == vieja

    nueva = tmp_path / "v2"
    shutil.copytree(FIXTURES, nueva)
    ruta = nueva / "metadata.json"
    meta = json.loads(ruta.read_text())
    meta["data_version"] = "2026-11-14T10:00:00-03:00"
    ruta.write_text(json.dumps(meta))
    _publicar(current, nueva)

    assert primero.post(RUTA, headers=TOKEN).status_code == 204
    respuesta = primero.get("/api/v1/metadata", headers={"If-None-Match": vieja})
    assert respuesta.status_code == 200
    assert respuesta.json()["data_version"] == meta["data_version"]
    assert respuesta.headers["etag"] != vieja

    limite = time.monotonic() + 8
    while time.monotonic() < limite:
        if segundo.get("/api/v1/metadata").headers["etag"] == respuesta.headers["etag"]:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("El segundo worker no detectó el cambio de versión")


def test_peticion_en_curso_conserva_su_version(tmp_path):
    current = tmp_path / "current"
    _publicar(current, FIXTURES)
    datos = Datos(crear_settings(data_dir=current))
    assert datos.abrir()
    with datos.fijar_version():
        version = datos.data_version
        assert datos.abrir()
        # Quitar la referencia activa no invalida la conexión fijada por esta petición.
        datos.cerrar()
        assert datos.data_version == version
        assert datos.consultar("SELECT count(*) AS n FROM dim_celdas") == [{"n": 20}]
    assert not datos.listo
