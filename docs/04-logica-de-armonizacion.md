# 04 · Lógica de armonización en la API

> **Fundamento científico:** ver `propuesta_B_calendario_focos_armonizado_ES.md` / `proposal_B_harmonized_hotspot_calendar_EN.md` (documentación del equipo). Acá se describe **cómo la API aplica** la regla.

## 1. Regla en una línea

> Para cada **mes** y cada **provincia** de la zona: si hubo VIIRS de referencia operativo, se muestra lo **observado**; si no, se **estima** como `focos MODIS × factor(provincia, mes)`, con su rango.

## 2. Satélite de referencia por fecha

| Período | Referencia "observado" | Fuente MODIS para estimar | Factor |
|---|---|---|---|
| 2000-11-01 → 2002-07-03 | — (no existía VIIRS) | Solo Terra (`n_terra`) | `tipo = terra` |
| 2002-07-04 → 2012-01-19 | — (no existía VIIRS) | Terra + Aqua (`n_terra + n_aqua`) | `tipo = modis` |
| 2012-01-20 → 2026-11-02 | **S-NPP** (`n_snpp`) | Terra + Aqua (solo para días con S-NPP caído) | `tipo = modis` |
| 2026-11-03 → hoy | **NOAA-20** (`n_n20`) | Terra + Aqua (solo para días con N20 caído) | `tipo = modis` |

- S-NPP y NOAA-20 cuentan prácticamente igual (razón 0,99), así que el cambio de referencia **no requiere corrección**.
- **NOAA-21 nunca se suma**, para no contar dos veces el mismo fuego.

## 3. Algoritmo por consulta

```text
ENTRADA: zona (→ conjunto de celdas C), período [desde, hasta], capa

1. Filtrar conteos_celda_dia por cell_id ∈ C y fecha ∈ período.
2. Unir con satelite_operativo para saber, por día, si la referencia estaba operativa.
3. Para cada día d y provincia p:
     si referencia operativa(d):   obs_d = n_ref ; est_d = null
     si no:                        obs_d = null  ; modis_d = n_terra (+ n_aqua si corresponde)
4. Agrupar por (provincia p, mes m):
     observado_pm   = Σ obs_d                (días con referencia)
     modis_est_pm   = Σ modis_d              (días sin referencia)
     estimado_pm    = modis_est_pm × factor(p, mes(m), tipo)
     [min, max]_pm  = rango(modis_est_pm) aplicado a estimado_pm   (ver §4)
5. Agrupar por mes m (sumando provincias):
     armonizado_m = Σ_p (observado_pm + estimado_pm)
     minimo_m     = Σ_p (observado_pm + min_pm)
     maximo_m     = Σ_p (observado_pm + max_pm)
     frac_estimada_m = días estimados / días del mes
     estado_m     = observado | estimado | mixto
6. Capa "modis": devolver Σ (n_terra + n_aqua). Capa "viirs": Σ n_ref o null si no había referencia.
```

**Importante:** el factor se aplica a los **totales mensuales por provincia**, no a cada día suelto. Así se calibraron los factores y así el rango tiene sentido.

## 4. Rango del 80 %

1. Se busca en `rangos.parquet` el tramo donde cae `modis_est_pm`.
2. Si `modis_est_pm = 0`: `min_pm = 0` y `max_pm = mult_alto` (valor absoluto, por defecto 10 focos), **solo si el mes es 100 % estimado**. En meses mixtos se usa 0.
3. Si no: `min_pm = estimado_pm × mult_bajo` y `max_pm = estimado_pm × mult_alto`.

Sumar los límites provincia por provincia da un rango **conservador** (más ancho que el real) para zonas grandes. Es aceptable para el MVP y está documentado.

## 5. Confianza

| `confianza` | Condición |
|---|---|
| `alta` | `frac_estimada ≤ 0,1` |
| `media` | Estimado con MODIS Terra + Aqua y `modis_est ≥ 21` focos en el mes |
| `baja` | Período solo Terra (antes de 2002-07-04), o `modis_est ≤ 20`, o la zona tiene más del 50 % de su área en provincias marcadas como "pocos datos" (Tierra del Fuego, Santa Cruz, CABA) |

## 6. Anomalía (mes vs. lo normal)

- Se calcula sobre `armonizado` del **mismo mes calendario** en todos los años disponibles, **excluyendo** el mes evaluado.
- Se usan mediana, p10, p25, p75 y p90 empíricos.
- Hacen falta al menos 10 años; si hay menos, se devuelve `categoria = null`.

## 7. Casos borde

| Caso | Comportamiento |
|---|---|
| Zona sin ninguna celda | 400 `ZONA_INVALIDA` ("La zona no contiene celdas de Argentina") |
| Zona que cruza provincias | Se calcula por provincia y se suma (§3) |
| Mes en curso (incompleto) | Se devuelve con `parcial: true` y sin categoría de anomalía |
| Factor faltante (provincia, mes) | Se usa el de la región de `factores_region_mes.parquet`; si falta, el nacional (`region = Argentina`). `nivel_origen` informa cuál |
| Días antes de 2000-11-01 | No hay datos: los meses no se devuelven |
| Diferencia entre SP y NRT | Transparente: la columna `fuente` existe en `focos/`, pero los conteos los unifican |
