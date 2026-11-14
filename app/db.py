"""Acceso a los datos: una conexión DuckDB por worker, en solo lectura.

DuckDB trabaja en memoria (``:memory:``) con **vistas** sobre los Parquet de
``DATA_DIR``; no existe un archivo ``.duckdb`` ni se escribe nada. El volumen de datos
además se monta read-only en el contenedor (docs/05).

Cada consulta usa su propio cursor (seguro entre hilos), con un máximo de consultas
simultáneas por worker y un corte por tiempo (``QUERY_TIMEOUT_S``).
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any

import duckdb
from pydantic import ValidationError

from app.config import Settings
from app.errores import datos_no_disponibles, tiempo_excedido
from app.schemas.metadata import MetadataArchivo

log = logging.getLogger(__name__)

# vista → (ruta relativa a DATA_DIR, particionado por año)
ARCHIVOS: dict[str, tuple[str, bool]] = {
    "focos": ("focos", True),
    "conteos_celda_dia": ("conteos_celda_dia", True),
    "dim_celdas": ("dim_celdas.parquet", False),
    "dim_provincias": ("dim_provincias.parquet", False),
    "factores_provincia_mes": ("factores_provincia_mes.parquet", False),
    "factores_region_mes": ("factores_region_mes.parquet", False),
    "rangos": ("rangos.parquet", False),
    "satelite_operativo": ("satelite_operativo.parquet", False),
    "puntos_industriales": ("puntos_industriales.parquet", False),
}


def _literal(texto: str) -> str:
    return "'" + texto.replace("'", "''") + "'"


class Datos:
    """Estado de los datos de un worker."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._con: duckdb.DuckDBPyConnection | None = None
        self._cupos = threading.BoundedSemaphore(settings.max_consultas_concurrentes)
        self.metadata: MetadataArchivo | None = None
        self.celdas_total = 0
        self.provincias_total = 0
        self.error: str | None = None

    @property
    def listo(self) -> bool:
        return self._con is not None and self.metadata is not None

    @property
    def data_version(self) -> str | None:
        return self.metadata.data_version if self.metadata else None

    def abrir(self) -> None:
        """Abre una conexión nueva sobre ``DATA_DIR``. Si falla, queda en estado degradado."""
        try:
            con, metadata, celdas, provincias = self._conectar()
        except Exception as exc:  # cualquier falla deja la API levantada pero degradada
            log.error("No se pudieron abrir los datos en %s: %s", self._settings.data_dir, exc)
            self.error = str(exc)
            self.cerrar()
            return
        anterior = self._con
        self._con, self.metadata = con, metadata
        self.celdas_total, self.provincias_total = celdas, provincias
        self.error = None
        if anterior is not None:
            anterior.close()
        log.info("Datos abiertos: data_version=%s", metadata.data_version)

    def cerrar(self) -> None:
        if self._con is not None:
            self._con.close()
        self._con = None
        self.metadata = None

    def _conectar(self) -> tuple[duckdb.DuckDBPyConnection, MetadataArchivo, int, int]:
        # Se resuelve el symlink "current" para que la conexión quede fija en una versión.
        base = Path(self._settings.data_dir).resolve(strict=True)
        try:
            crudo = json.loads((base / "metadata.json").read_text(encoding="utf-8"))
            metadata = MetadataArchivo.model_validate(crudo)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            raise RuntimeError(f"metadata.json inválido o ausente: {exc}") from exc

        con = duckdb.connect(
            ":memory:",
            config={
                "memory_limit": self._settings.duckdb_memory_limit,
                "threads": self._settings.duckdb_threads,
                "preserve_insertion_order": False,
            },
        )
        try:
            for vista, (relativa, particionado) in ARCHIVOS.items():
                ruta = base / relativa
                if particionado:
                    if not any(ruta.glob("anio=*/*.parquet")):
                        raise RuntimeError(f"No hay particiones en {ruta}")
                    origen = (
                        f"read_parquet({_literal(str(ruta / 'anio=*' / '*.parquet'))}, "
                        "hive_partitioning = true, hive_types = {'anio': SMALLINT})"
                    )
                else:
                    if not ruta.is_file():
                        raise RuntimeError(f"Falta el archivo {ruta}")
                    origen = f"read_parquet({_literal(str(ruta))})"
                con.execute(f"CREATE VIEW {vista} AS SELECT * FROM {origen}")
            celdas = con.execute("SELECT count(*) FROM dim_celdas").fetchone()
            provincias = con.execute("SELECT count(*) FROM dim_provincias").fetchone()
            con.execute("SET lock_configuration = true")
        except Exception:
            con.close()
            raise
        return con, metadata, (celdas or (0,))[0], (provincias or (0,))[0]

    def consultar(
        self, sql: str, parametros: list[Any] | dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Ejecuta una consulta de lectura y devuelve las filas como diccionarios."""
        con = self._con
        if con is None:
            raise datos_no_disponibles()
        limite = self._settings.query_timeout_s
        if not self._cupos.acquire(timeout=limite):
            raise tiempo_excedido(limite)
        cursor = con.cursor()
        reloj = threading.Timer(limite, cursor.interrupt)
        try:
            reloj.start()
            resultado = cursor.execute(sql, parametros)
            columnas = [d[0] for d in resultado.description or []]
            return [dict(zip(columnas, fila, strict=True)) for fila in resultado.fetchall()]
        except duckdb.InterruptException as exc:
            raise tiempo_excedido(limite) from exc
        finally:
            reloj.cancel()
            cursor.close()
            self._cupos.release()
