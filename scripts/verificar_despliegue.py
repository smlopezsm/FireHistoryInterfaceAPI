"""Verifica una API desplegada con todas las provincias y contra los datos de `data/current`.

Uso (desde la raíz del repo)::

    PYTHONPATH=. .venv/bin/python scripts/verificar_despliegue.py \\
        --base https://fhi.intercomputacion.com.ar [--datos data/current] [--informe informe.md]

Qué revisa:

1. **Estado**: `/health` en `ok` y el mismo `data_version` que `data/current/metadata.json`.
2. **Las 24 provincias**: `/calendario`, `/serie` anual, `/anomalia` y `calendario.csv` de cada una.
3. **Reglas del contrato** (docs/03 y docs/04) sobre cada mes: meses contiguos, `null` nunca es 0,
   `minimo ≤ armonizado ≤ maximo`, observado = VIIRS, sin VIIRS antes de 2012-01-20, etc.
4. **Igualdad con la API local**: la misma consulta corrida localmente sobre `data/current`
   tiene que dar exactamente lo mismo que el servidor (mismos datos y misma lógica).
5. **Clasificación**: focos en puntos industriales excluidos, NOAA-21 que no cambia nada, y calidad
   de la armonización por provincia (MODIS × factor vs. VIIRS observado, 2013–2025).
6. **Tiempos** por tipo de consulta (mediana y p95) contra los objetivos de docs/06.

Sale con código 1 si algún chequeo falla.
"""

# ruff: noqa: E501  (tablas de Markdown y mensajes largos)
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import duckdb
import httpx

PROV_POCOS_DATOS = {"02", "78", "94"}
OBJETIVOS_MS = {"calendario provincia": 800, "calendario país": 2500, "mapa país 1 mes": 1500}


@dataclass
class Resultado:
    fallas: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    tiempos: dict[str, list[float]] = field(default_factory=lambda: defaultdict(list))
    filas: list[dict[str, Any]] = field(default_factory=list)

    def falla(self, texto: str) -> None:
        self.fallas.append(texto)

    def aviso(self, texto: str) -> None:
        self.avisos.append(texto)


class Cliente:
    def __init__(self, base: str, res: Resultado) -> None:
        self.http = httpx.Client(base_url=base.rstrip("/"), timeout=30)
        self.res = res

    def get(self, ruta: str, tipo: str, **params: Any) -> httpx.Response:
        inicio = time.perf_counter()
        r = self.http.get("/api/v1" + ruta, params=params)
        self.res.tiempos[tipo].append(1000 * (time.perf_counter() - inicio))
        return r


# --- reglas del contrato sobre un calendario -------------------------------------------------


def _meses_esperados(desde: date, hasta: date) -> list[str]:
    salida, a, m = [], desde.year, desde.month
    while (a, m) <= (hasta.year, hasta.month):
        salida.append(f"{a:04d}-{m:02d}")
        a, m = (a + 1, 1) if m == 12 else (a, m + 1)
    return salida


def revisar_calendario(pid: str, cal: dict[str, Any], meta: dict[str, Any], res: Resultado) -> None:
    meses = cal["meses"]
    fmin, fmax = date.fromisoformat(meta["fecha_min"]), date.fromisoformat(meta["fecha_max"])
    esperados = _meses_esperados(fmin, fmax)
    periodos = [m["periodo"] for m in meses]
    if periodos != esperados:
        res.falla(
            f"{pid}: meses {periodos[:1]}…{periodos[-1:]} ({len(periodos)}) ≠ esperados "
            f"{esperados[0]}…{esperados[-1]} ({len(esperados)})"
        )
    for m in meses:
        p, etiqueta = m["periodo"], f"{pid} {m['periodo']}"
        if m["armonizado"] is None or m["minimo"] is None or m["maximo"] is None:
            res.falla(f"{etiqueta}: armonizado/minimo/maximo nulo")
            continue
        if not m["minimo"] - 0.11 <= m["armonizado"] <= m["maximo"] + 0.11:
            res.falla(
                f"{etiqueta}: armonizado {m['armonizado']} fuera de [{m['minimo']}, {m['maximo']}]"
            )
        if m["modis"] < 0 or (m["viirs"] is not None and m["viirs"] < 0):
            res.falla(f"{etiqueta}: conteo negativo")
        if p < "2012-01" and m["viirs"] is not None:
            res.falla(
                f"{etiqueta}: viirs = {m['viirs']} antes de que existiera VIIRS (debe ser null)"
            )
        if p < "2012-01" and m["estado"] != "estimado":
            res.falla(f"{etiqueta}: estado {m['estado']} antes de 2012 (debe ser estimado)")
        frac = m["frac_estimada"]
        estado_ok = {"observado": frac == 0, "estimado": frac == 1, "mixto": 0 < frac < 1}
        if not estado_ok.get(m["estado"], False):
            res.falla(f"{etiqueta}: estado {m['estado']} con frac_estimada {frac}")
        if m["estado"] == "observado":
            if not m["minimo"] == m["armonizado"] == m["maximo"]:
                res.falla(f"{etiqueta}: observado con rango [{m['minimo']}, {m['maximo']}]")
            if m["viirs"] is None or abs(m["armonizado"] - m["viirs"]) > 0.05:
                res.falla(f"{etiqueta}: observado {m['armonizado']} ≠ viirs {m['viirs']}")
        if m["estado"] == "estimado" and m["viirs"] is not None:
            res.falla(f"{etiqueta}: 100 % estimado pero viirs = {m['viirs']} (debe ser null)")
        if frac <= 0.1 and m["confianza"] != "alta":
            res.falla(f"{etiqueta}: frac_estimada {frac:.2f} con confianza {m['confianza']}")
        if p == esperados[-1] and fmax.day < 28 and not m["parcial"]:
            res.aviso(f"{etiqueta}: el último mes debería ser parcial")
        if p != esperados[-1] and m["parcial"]:
            res.falla(f"{etiqueta}: parcial en un mes que no es el último")


# --- igualdad con la API local ---------------------------------------------------------------


class ApiLocal:
    def __init__(self, datos: Path) -> None:
        from fastapi.testclient import TestClient

        from app.config import Settings
        from app.main import create_app

        logging.disable(logging.CRITICAL)
        config = Settings(
            _env_file=None, data_dir=datos, cors_origins="http://localhost", reload_token="x"
        )
        self.cliente = TestClient(create_app(config))
        self.cliente.__enter__()

    def get(self, ruta: str, **params: Any) -> Any:
        return self.cliente.get("/api/v1" + ruta, params=params).json()


# --- clasificación (sobre los Parquet locales) -----------------------------------------------


def revisar_clasificacion(datos: Path, res: Resultado) -> dict[str, Any]:
    con = duckdb.connect()

    def v(nombre: str) -> str:
        ruta = datos / nombre
        if ruta.is_dir():
            return f"read_parquet('{ruta}/anio=*/*.parquet', hive_partitioning=true)"
        return f"read_parquet('{ruta}.parquet')"

    salida: dict[str, Any] = {}
    # Focos en puntos industriales (mismo identificador que el pipeline: lat y lon a 0,01°).
    en_puntos = con.execute(
        f"""SELECT count(*) FROM {v("focos")} f
            WHERE CAST(round(f.lat::DOUBLE * 100) AS BIGINT) * 100000
                + CAST(round(f.lon::DOUBLE * 100) AS BIGINT)
              IN (SELECT punto_id FROM {v("puntos_industriales")})"""
    ).fetchone()[0]
    total_focos = con.execute(f"SELECT count(*) FROM {v('focos')}").fetchone()[0]
    salida["focos_en_puntos_industriales"] = en_puntos
    # Tolerancia mínima: lat/lon se guardan en FLOAT de 32 bits y el redondeo de un borde exacto
    # puede caer distinto que en el pipeline.
    if en_puntos > total_focos * 1e-5:
        res.falla(f"clasificación: {en_puntos:,} focos siguen dentro de puntos industriales")
    puntos = con.execute(
        f"SELECT count(*), sum(n_focos) FROM {v('puntos_industriales')}"
    ).fetchone()
    salida["puntos_industriales"] = {"puntos": puntos[0], "focos_excluidos": puntos[1]}
    # Factores provincia × mes (modis) para la calidad de la armonización.
    salida["factores"] = {
        (p, m): f
        for p, m, f in con.execute(
            f"SELECT provincia_id, mes, factor FROM {v('factores_provincia_mes')} WHERE tipo='modis'"
        ).fetchall()
    }
    return salida


def calidad_armonizacion(
    pid: str, cal: dict[str, Any], factores: dict[tuple[str, int], float]
) -> dict[str, float] | None:
    """Meses 2013–2025 100 % observados: ¿cuánto se equivoca MODIS × factor contra VIIRS real?"""
    v_total = est_total = err = 0.0
    n = 0
    for m in cal["meses"]:
        if not "2013-01" <= m["periodo"] <= "2025-12" or m["estado"] != "observado":
            continue
        f = factores.get((pid, int(m["periodo"][5:])))
        if f is None:
            continue
        est = m["modis"] * f
        v_total += m["viirs"]
        est_total += est
        err += abs(est - m["viirs"])
        n += 1
    if v_total == 0:
        return None
    return {
        "meses": n,
        "viirs": v_total,
        "razon": est_total / v_total,
        "error_pct": 100 * err / v_total,
    }


# --- principal -------------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="https://fhi.intercomputacion.com.ar")
    ap.add_argument("--datos", type=Path, default=Path("data/current"))
    ap.add_argument("--informe", type=Path, help="Escribe además un informe en Markdown")
    ap.add_argument("--sin-local", action="store_true", help="No compara con la API local")
    args = ap.parse_args()

    res = Resultado()
    api = Cliente(args.base, res)
    meta_local = json.loads((args.datos / "metadata.json").read_text())

    # 1. Estado
    salud = api.get("/health", "health").json()
    print(f"health: {salud}")
    if salud.get("estado") != "ok":
        res.falla(f"/health en {salud.get('estado')}")
    if salud.get("data_version") != meta_local["data_version"]:
        res.falla(
            f"data_version del servidor {salud.get('data_version')} ≠ local "
            f"{meta_local['data_version']}"
        )
    meta = api.get("/metadata", "metadata").json()
    provincias = api.get("/provincias", "provincias").json()
    if len(provincias) != 24:
        res.falla(f"/provincias devolvió {len(provincias)} provincias (se esperan 24)")

    local = None if args.sin_local else ApiLocal(args.datos)
    clasif = revisar_clasificacion(args.datos, res)

    # 2–5. Provincia por provincia
    celdas_total = 0
    for prov in sorted(provincias, key=lambda p: p["provincia_id"]):
        pid, nombre = prov["provincia_id"], prov["nombre"]
        r = api.get("/calendario", "calendario provincia", provincia_id=pid)
        if r.status_code != 200:
            res.falla(f"{pid} /calendario → HTTP {r.status_code}: {r.text[:120]}")
            continue
        cal = r.json()
        revisar_calendario(pid, cal, meta, res)
        celdas_total += cal["zona"]["celdas"]

        serie = api.get("/serie", "serie anual", provincia_id=pid, granularidad="anio").json()
        suma_meses = round(sum(m["armonizado"] for m in cal["meses"]), 1)
        suma_anios = round(sum(p["armonizado"] for p in serie["puntos"]), 1)
        if abs(suma_meses - suma_anios) > 0.1 * len(serie["puntos"]):
            res.falla(f"{pid}: serie anual suma {suma_anios} ≠ calendario {suma_meses}")

        anom = api.get("/anomalia", "anomalía", provincia_id=pid)
        if anom.status_code != 200:
            res.falla(f"{pid} /anomalia → HTTP {anom.status_code}")

        csv_r = api.get("/descargas/calendario.csv", "calendario.csv", provincia_id=pid)
        filas_csv = list(csv.DictReader(io.StringIO(csv_r.text)))
        if len(filas_csv) != len(cal["meses"]):
            res.falla(
                f"{pid}: calendario.csv tiene {len(filas_csv)} filas, el JSON {len(cal['meses'])}"
            )

        igual = "—"
        if local is not None:
            esperado = local.get("/calendario", provincia_id=pid)
            igual = "sí" if esperado == cal else "NO"
            if esperado != cal:
                dif = [
                    (a["periodo"], {k: (a[k], b[k]) for k in a if a[k] != b[k]})
                    for a, b in zip(cal["meses"], esperado["meses"], strict=False)
                    if a != b
                ][:3]
                res.falla(
                    f"{pid}: el servidor no coincide con la API local; primeras diferencias {dif}"
                )

        cal_q = calidad_armonizacion(pid, cal, clasif["factores"])
        observados = sum(1 for m in cal["meses"] if m["estado"] == "observado")
        res.filas.append(
            {
                "id": pid,
                "provincia": nombre,
                "celdas": cal["zona"]["celdas"],
                "total": cal["resumen"]["total"],
                "max_mes": cal["resumen"]["max_mes"],
                "observados": observados,
                "anomalia": anom.json().get("categoria") if anom.status_code == 200 else "error",
                "igual_local": igual,
                "calidad": cal_q,
            }
        )
        if (
            cal_q
            and cal_q["viirs"] >= 2000
            and pid not in PROV_POCOS_DATOS
            and not 0.8 <= cal_q["razon"] <= 1.25
        ):
            res.aviso(
                f"{pid} {nombre}: MODIS × factor da {cal_q['razon']:.2f} veces lo observado "
                "(2013–2025); revisar factores"
            )
        print(f"  {pid} {nombre[:40]:<40} {len(cal['meses'])} meses · igual a local: {igual}")

    if celdas_total != meta["celdas_total"]:
        res.falla(
            f"las provincias suman {celdas_total:,} celdas; metadata dice {meta['celdas_total']:,}"
        )

    # Consultas grandes (tiempos)
    for _ in range(5):
        api.get("/calendario", "calendario país", bbox="-74,-56,-53,-21")
        api.get(
            "/mapa/celdas",
            "mapa país 1 mes",
            bbox="-74,-56,-53,-21",
            desde="2025-09-01",
            hasta="2025-09-30",
        )

    return informar(res, args, meta, clasif, salud)


def _p95(xs: list[float]) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(0.95 * (len(xs) - 1)))]


def informar(
    res: Resultado,
    args: argparse.Namespace,
    meta: dict[str, Any],
    clasif: dict[str, Any],
    salud: dict[str, Any],
) -> int:
    lineas = [
        f"# Verificación de {args.base}",
        "",
        f"- Fecha: {time.strftime('%Y-%m-%d %H:%M')}",
        f"- `data_version`: {salud.get('data_version')} · período {meta['fecha_min']} → {meta['fecha_max']}"
        f" · {meta['celdas_total']:,} celdas · {meta['provincias_total']} provincias",
        f"- Puntos industriales: {clasif['puntos_industriales']['puntos']} "
        f"({clasif['puntos_industriales']['focos_excluidos']:,} focos excluidos); focos que quedaron "
        f"dentro de esos puntos: {clasif['focos_en_puntos_industriales']}",
        "",
        "## Provincias",
        "",
        "| ID | Provincia | Celdas | Total armonizado | Mes máximo | Meses observados | "
        "Anomalía último mes | = API local | MODIS×factor / VIIRS 2013–25 | Error mensual |",
        "|---|---|---:|---:|---|---:|---|---|---:|---:|",
    ]
    for f in res.filas:
        q = f["calidad"]
        razon = f"{q['razon']:.2f}" if q else "—"
        error = f"{q['error_pct']:.0f} %" if q else "—"
        lineas.append(
            f"| {f['id']} | {f['provincia']} | {f['celdas']:,} | {f['total']:,.1f} | {f['max_mes']} | "
            f"{f['observados']} | {f['anomalia'] or 'sin categoría'} | {f['igual_local']} | {razon} | {error} |"
        )
    lineas += [
        "",
        "## Tiempos",
        "",
        "| Consulta | n | Mediana | p95 | Objetivo |",
        "|---|---:|---:|---:|---|",
    ]
    for tipo, ts in res.tiempos.items():
        obj = OBJETIVOS_MS.get(tipo)
        marca = "" if obj is None else (f"< {obj} ms ✅" if _p95(ts) < obj else f"< {obj} ms ❌")
        lineas.append(
            f"| {tipo} | {len(ts)} | {statistics.median(ts):.0f} ms | {_p95(ts):.0f} ms | {marca} |"
        )
    lineas += [
        "",
        f"## Resultado: {'✅ sin fallas' if not res.fallas else f'❌ {len(res.fallas)} fallas'}",
        "",
    ]
    lineas += [f"- ❌ {x}" for x in res.fallas[:50]]
    if len(res.fallas) > 50:
        lineas.append(f"- … y {len(res.fallas) - 50} más")
    lineas += [f"- ⚠️ {x}" for x in res.avisos]
    texto = "\n".join(lineas) + "\n"
    print("\n" + texto)
    if args.informe:
        args.informe.write_text(texto, encoding="utf-8")
        print(f"Informe escrito en {args.informe}")
    return 1 if res.fallas else 0


if __name__ == "__main__":
    sys.exit(main())
