"""Acceso a los datos: una conexión DuckDB por worker, en solo lectura.

DuckDB trabaja en memoria (``:memory:``) con **vistas** sobre los Parquet de
``DATA_DIR``; no existe un archivo ``.duckdb`` ni se escribe nada. En la imagen, los datos
están en ``/var/data/current`` y el usuario ``app`` solo puede leerlos (docs/05).

Cada consulta usa su propio cursor (seguro entre hilos), con un máximo de consultas
simultáneas por worker y un corte por tiempo (``QUERY_TIMEOUT_S``).
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import duckdb
import pyarrow as pa
from pydantic import ValidationError

from app.config import Settings
from app.errores import ApiError, datos_no_disponibles, tiempo_excedido
from app.schemas.metadata import MetadataArchivo

log = logging.getLogger(__name__)
T = TypeVar("T")

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


@dataclass(frozen=True)
class VersionDatos:
    base: Path
    con: duckdb.DuckDBPyConnection
    metadata: MetadataArchivo
    celdas: int
    provincias: int


class Datos:
    """Estado de los datos de un worker."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._actual: VersionDatos | None = None
        self._peticion: ContextVar[tuple[VersionDatos | None] | None] = ContextVar(
            "version_datos", default=None
        )
        self._recarga = threading.Lock()
        self._cupos = threading.BoundedSemaphore(settings.max_consultas_concurrentes)
        self.error: str | None = None

    @contextmanager
    def fijar_version(self) -> Iterator[None]:
        # La petición conserva una referencia a la conexión hasta terminar sus consultas.
        token = self._peticion.set((self._actual,))
        try:
            yield
        finally:
            self._peticion.reset(token)

    @property
    def _version(self) -> VersionDatos | None:
        fijada = self._peticion.get()
        return self._actual if fijada is None else fijada[0]

    @property
    def metadata(self) -> MetadataArchivo | None:
        version = self._version
        return version.metadata if version else None

    @property
    def listo(self) -> bool:
        return self._version is not None

    @property
    def data_version(self) -> str | None:
        meta = self.metadata
        return meta.data_version if meta else None

    @property
    def celdas_total(self) -> int:
        version = self._version
        return version.celdas if version else 0

    @property
    def provincias_total(self) -> int:
        version = self._version
        return version.provincias if version else 0

    def abrir(self, *, solo_si_cambio: bool = False) -> bool:
        """Publica una versión completa y conserva la anterior si la apertura falla."""
        with self._recarga:
            try:
                base = self._settings.data_dir.resolve(strict=True)
                if solo_si_cambio and self._actual and self._actual.base == base:
                    return True
                version = self._conectar(base)
            except Exception as exc:
                if self.error != str(exc):
                    log.error(
                        "No se pudieron abrir los datos en %s: %s", self._settings.data_dir, exc
                    )
                self.error = str(exc)
                return False
            # La versión anterior no se cierra a mano: puede haber peticiones fijadas a ella
            # (fijar_version). DuckDB cierra la conexión cuando la última referencia se libera.
            self._actual = version
            self.error = None
            log.info("Datos abiertos: data_version=%s", version.metadata.data_version)
            return True

    def cerrar(self) -> None:
        with self._recarga:
            self._actual = None

    def _conectar(self, base: Path) -> VersionDatos:
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
        return VersionDatos(base, con, metadata, (celdas or (0,))[0], (provincias or (0,))[0])

    def consultar(
        self,
        sql: str,
        parametros: list[Any] | dict[str, Any] | None = None,
        celdas: Sequence[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Ejecuta una consulta de lectura y devuelve las filas como diccionarios.

        Con ``celdas``, la consulta puede filtrar con ``SELECT cell_id FROM zona_celdas``.
        """

        def _filas(resultado: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
            columnas = [d[0] for d in resultado.description or []]
            return [dict(zip(columnas, fila, strict=True)) for fila in resultado.fetchall()]

        return self._ejecutar(sql, parametros, _filas, celdas)

    def exportar_filas(
        self,
        filtro: str,
        columnas: str,
        parametros: list[Any],
        maximo: int,
        escribir: Callable[[list[tuple[Any, ...]]], object],
        celdas: Sequence[int] | None = None,
    ) -> None:
        """Cuenta y exporta en lotes con el mismo cursor y presupuesto de consulta."""

        def exportar(cursor: duckdb.DuckDBPyConnection) -> None:
            conteo = cursor.fetchone()
            assert conteo is not None
            if conteo[0] > maximo:
                raise ApiError(
                    413,
                    "RESULTADO_DEMASIADO_GRANDE",
                    "La descarga supera el máximo de filas. Achicá la zona o el período.",
                )
            cursor.execute(f"SELECT {columnas} {filtro} LIMIT ?", [*parametros, maximo + 1])
            restantes = maximo
            while filas := cursor.fetchmany(4096):
                restantes -= len(filas)
                if restantes < 0:
                    raise ApiError(
                        413,
                        "RESULTADO_DEMASIADO_GRANDE",
                        "La descarga supera el máximo de filas. Achicá la zona o el período.",
                    )
                escribir(filas)

        self._ejecutar(f"SELECT count(*) {filtro}", parametros, exportar, celdas)

    def consultar_columnas(
        self, sql: str, parametros: list[Any] | dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Ejecuta una consulta y devuelve un arreglo NumPy por columna."""
        return self._ejecutar(sql, parametros, lambda r: dict(r.fetchnumpy()))

    def _ejecutar(
        self,
        sql: str,
        parametros: list[Any] | dict[str, Any] | None,
        leer: Callable[[duckdb.DuckDBPyConnection], T],
        celdas: Sequence[int] | None = None,
    ) -> T:
        version = self._version
        if version is None:
            raise datos_no_disponibles()
        limite = self._settings.query_timeout_s
        if not self._cupos.acquire(timeout=limite):
            raise tiempo_excedido(limite)
        try:
            cursor = version.con.cursor()
            reloj = threading.Timer(limite, cursor.interrupt)
            try:
                if celdas is not None:
                    # Las celdas de la zona viajan como tabla Arrow del cursor: pasarlas como
                    # lista parametrizada (unnest) tarda ~8 s con las 112.000 celdas del país.
                    tabla = pa.table({"cell_id": pa.array(celdas, type=pa.int32())})
                    cursor.register("zona_celdas", tabla)
                reloj.start()
                return leer(cursor.execute(sql, parametros))
            except duckdb.InterruptException as exc:
                raise tiempo_excedido(limite) from exc
            finally:
                reloj.cancel()
                cursor.close()
        finally:
            self._cupos.release()
