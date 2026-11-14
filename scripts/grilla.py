"""Grilla de 5 x 5 km en la proyección Albers custom de Argentina (docs/01 §3, docs/02).

Implementa la proyección cónica equivalente de Albers sobre el elipsoide GRS80
(Snyder, *Map Projections: A Working Manual*, 1987, ecs. 14-1 a 14-21), sin
depender de pyproj.

``cell_id = fila * 460 + columna``. El **origen de la grilla** (``X_MIN``, ``Y_MAX``)
no está fijado en docs/: lo define el pipeline. Acá se usa un origen supuesto, solo
para generar fixtures y datos de demostración. La API nunca recalcula la grilla:
usa los centroides y polígonos de ``dim_celdas``.
"""

from __future__ import annotations

import json
import math

# +proj=aea +lat_0=-37 +lon_0=-60 +lat_1=-26 +lat_2=-48 +x_0=2500000 +y_0=0 +ellps=GRS80
A = 6378137.0
E2 = 0.00669438002290
E = math.sqrt(E2)
LAT0, LON0, LAT1, LAT2 = -37.0, -60.0, -26.0, -48.0
X0, Y0 = 2_500_000.0, 0.0

TAM_CELDA = 5_000.0
FILAS, COLUMNAS = 780, 460
X_MIN = 1_450_000.0  # supuesto (solo demo / fixtures)
Y_MAX = 1_800_000.0  # supuesto (solo demo / fixtures)


def _q(phi: float) -> float:
    s = math.sin(phi)
    return (1 - E2) * (s / (1 - E2 * s * s) - (1 / (2 * E)) * math.log((1 - E * s) / (1 + E * s)))


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - E2 * s * s)


_P0, _P1, _P2 = (math.radians(v) for v in (LAT0, LAT1, LAT2))
_M1, _M2 = _m(_P1), _m(_P2)
_Q0, _Q1, _Q2 = _q(_P0), _q(_P1), _q(_P2)
N = (_M1**2 - _M2**2) / (_Q2 - _Q1)
C = _M1**2 + N * _Q1
RHO0 = A * math.sqrt(C - N * _Q0) / N


def a_albers(lon: float, lat: float) -> tuple[float, float]:
    rho = A * math.sqrt(C - N * _q(math.radians(lat))) / N
    theta = N * math.radians(lon - LON0)
    return X0 + rho * math.sin(theta), Y0 + RHO0 - rho * math.cos(theta)


def a_geograficas(x: float, y: float) -> tuple[float, float]:
    dx, dy = x - X0, RHO0 - (y - Y0)
    signo = 1.0 if N > 0 else -1.0
    rho = signo * math.hypot(dx, dy)
    theta = math.atan2(signo * dx, signo * dy)
    q = (C - (rho * N / A) ** 2) / N
    phi = math.asin(max(-1.0, min(1.0, q / 2)))
    for _ in range(20):
        s = math.sin(phi)
        d = (
            (1 - E2 * s * s) ** 2
            / (2 * math.cos(phi))
            * (
                q / (1 - E2)
                - s / (1 - E2 * s * s)
                + (1 / (2 * E)) * math.log((1 - E * s) / (1 + E * s))
            )
        )
        phi += d
        if abs(d) < 1e-12:
            break
    return LON0 + math.degrees(theta / N), math.degrees(phi)


def celda_de(lon: float, lat: float) -> tuple[int, int, int]:
    """Devuelve (cell_id, fila, columna) de la celda que contiene el punto."""
    x, y = a_albers(lon, lat)
    col = int((x - X_MIN) // TAM_CELDA)
    fila = int((Y_MAX - y) // TAM_CELDA)
    if not (0 <= fila < FILAS and 0 <= col < COLUMNAS):
        raise ValueError(f"Punto fuera de la grilla: {lon}, {lat}")
    return fila * COLUMNAS + col, fila, col


def centroide(fila: int, col: int) -> tuple[float, float]:
    """(lon, lat) del centro de la celda."""
    return a_geograficas(X_MIN + (col + 0.5) * TAM_CELDA, Y_MAX - (fila + 0.5) * TAM_CELDA)


def poligono_geojson(fila: int, col: int) -> str:
    """Polígono de la celda (4 vértices, EPSG:4326) en GeoJSON."""
    x0, x1 = X_MIN + col * TAM_CELDA, X_MIN + (col + 1) * TAM_CELDA
    y1, y0 = Y_MAX - fila * TAM_CELDA, Y_MAX - (fila + 1) * TAM_CELDA
    esquinas = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
    anillo = [[round(v, 6) for v in a_geograficas(x, y)] for x, y in esquinas]
    return json.dumps({"type": "Polygon", "coordinates": [anillo]}, separators=(",", ":"))


def rectangulo_geojson(oeste: float, sur: float, este: float, norte: float) -> str:
    anillo = [[oeste, sur], [este, sur], [este, norte], [oeste, norte], [oeste, sur]]
    return json.dumps({"type": "Polygon", "coordinates": [anillo]}, separators=(",", ":"))


def _autoprueba() -> None:
    for lon, lat in [(-60, -37), (-66.3, -33.3), (-70, -54.5), (-55, -22)]:
        lon2, lat2 = a_geograficas(*a_albers(lon, lat))
        assert abs(lon - lon2) < 1e-7 and abs(lat - lat2) < 1e-7, (lon, lat, lon2, lat2)
    assert (
        a_albers(LON0, LAT0) == (X0, Y0)
        or max(abs(a - b) for a, b in zip(a_albers(LON0, LAT0), (X0, Y0), strict=True)) < 1e-6
    )


_autoprueba()
