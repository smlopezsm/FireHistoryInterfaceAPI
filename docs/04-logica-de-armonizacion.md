# 04 · Lógica de armonización en la API

> **Fundamento científico:** [`CLASIFICACION.md`](https://github.com/DenisPablo/ML_NasaSpaceApp/blob/main/CLASIFICACION.md) del pipeline (cómo se calculan los factores y los rangos) y el [veredicto científico de la armonización](https://github.com/DenisPablo/ML_NasaSpaceApp/blob/main/analisis/veredicto-armonizacion/veredicto-armonizacion.md) (validación con datos reales y scripts para replicarla). El documento original de la propuesta B no está publicado en ningún repo. Acá se describe **cómo la API aplica** la regla.

## 1. Regla en una línea

> Para cada **mes** y cada **provincia** de la zona: si hubo VIIRS de referencia operativo, se muestra lo **observado**; si no, se **estima** como `focos MODIS × factor(provincia, mes)`, con su rango.

## 2. Satélite de referencia por fecha

| Período | Referencia "observado" | Fuente MODIS para estimar | Factor |
|---|---|---|---|
| 2000-11-01 → 2002-07-03 | — (no existía VIIRS) | Solo Terra (`n_terra`) | `tipo = terra` |
| 2002-07-04 → 2012-01-19 | — (no existía VIIRS) | Terra + Aqua (`n_terra + n_aqua`) | `tipo = modis` |
| 2012-01-20 → 2026-11-02 | **S-NPP** (`n_snpp`) | Terra + Aqua (solo para días con S-NPP caído) | `tipo = modis` |
| 2026-11-03 → hoy | **NOAA-20** (`n_n20`) | Terra + Aqua (solo para días con N20 caído) | `tipo = modis` |

- S-NPP y NOAA-20 cuentan prácticamente igual: la razón S-NPP/NOAA-20 medida en 2018-04 → 2026-11 es **1,02** en los días con los dos operativos. Por eso el cambio de referencia **no requiere corrección**.
- **NOAA-21 nunca se suma**, para no contar dos veces el mismo fuego.
- Las fechas de esta tabla para la referencia VIIRS **se leen de `metadata.referencia_viirs`** (docs/02 §9): si el pipeline cambia la fecha de paso a NOAA-20, la API la sigue sin cambios de código. Solo se aceptan `SNPP` y `N20`; cualquier otro valor deja la API en estado `degradado`.

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
     frac_estimada_m = días estimados / días del mes con datos   (en el mes en curso, hasta fecha_max)
     estado_m     = observado | estimado | mixto
6. Capa "modis": devolver Σ (n_terra + n_aqua). Capa "viirs": Σ n_ref o null si no había referencia.
```

**Meses que combinan factores** (por ejemplo julio de 2002, con días solo Terra y días Terra + Aqua): se suman por separado los focos MODIS de cada tipo y se aplica a cada suma su factor (`terra` o `modis`). El tramo del rango (§4) se elige con el total de `modis_est_pm`.

**Importante:** el factor se aplica a los **totales mensuales por provincia**, no a cada día suelto. Así se calibraron los factores y así el rango tiene sentido.

## 4. Rango del 80 %

1. Se busca en `rangos.parquet` el tramo donde cae `modis_est_pm`.
2. Si `modis_est_pm = 0`: `min_pm = 0` y `max_pm = mult_alto` (valor absoluto: 9 focos en la versión publicada), **solo si el mes es 100 % estimado**. En meses mixtos se usa 0.
3. Si no: `min_pm = estimado_pm × mult_bajo` y `max_pm = estimado_pm × mult_alto`.

Sumar los límites provincia por provincia da un rango **conservador** (más ancho que el real) para zonas grandes. Es aceptable para el MVP y está documentado. Medido a escala nacional, el rango que resulta de sumar provincias contiene el valor real en el **98,8 %** de los meses: es más un rango del 99 % que uno del 80 %.

## 5. Confianza

| `confianza` | Condición |
|---|---|
| `alta` | `frac_estimada ≤ 0,1` (en cualquier zona, también en provincias con "pocos datos") |
| `media` | Estimado con MODIS Terra + Aqua y `modis_est ≥ 21` focos en el mes |
| `baja` | Período solo Terra (antes de 2002-07-04), o `modis_est ≤ 20`, o la zona tiene más del 50 % de su área en provincias marcadas como "pocos datos" (Tierra del Fuego, Santa Cruz, CABA) y el mes tiene `frac_estimada > 0,1` |

Se evalúa en orden: primero `alta`; "pocos datos" solo baja la confianza de lo **estimado**, porque un mes observado no depende de los factores.

## 6. Anomalía (mes vs. lo normal)

- Se calcula sobre `armonizado` del **mismo mes calendario** en todos los años disponibles, **excluyendo** el mes evaluado.
- Se usan mediana, p10, p25, p75 y p90 empíricos.
- Hacen falta al menos 10 años; si hay menos, se devuelve `categoria = null`.

## 7. Casos borde

| Caso | Comportamiento |
|---|---|
| Zona sin ninguna celda | 400 `ZONA_INVALIDA` ("La zona no contiene celdas de Argentina") |
| Zona que cruza provincias | Se calcula por provincia y se suma (§3) |
| Mes en curso (incompleto) | Se devuelve con `parcial: true` y sin categoría de anomalía; `frac_estimada` se calcula sobre los días transcurridos hasta `fecha_max` |
| Factor faltante (provincia, mes) | Se usa el de la región de `factores_region_mes.parquet`; si falta, el nacional (`region = Argentina`). `nivel_origen` informa cuál |
| Días antes de 2000-11-01 | No hay datos: los meses no se devuelven |
| Diferencia entre SP y NRT | Transparente: la columna `fuente` existe en `focos/`, pero los conteos los unifican |

## 8. Validación científica y limitaciones conocidas

El [veredicto de armonización](https://github.com/DenisPablo/ML_NasaSpaceApp/blob/main/analisis/veredicto-armonizacion/veredicto-armonizacion.md) evalúa este método con los datos publicados y concluye que es **"sólido con reservas"**. Los puntos que afectan a la API son:

| Tema | Qué se midió | Estado en la API |
|---|---|---|
| Anomalía entre eras | La referencia mezcla 2001–2011 (estimado) con 2012+ (observado). MODIS crudo baja un 33 % entre esas eras, y en 2012+ el 35 % de los meses sale "por debajo" (lo esperado es 25 %). | Pendiente: usar como referencia solo los años observados, o informar las dos referencias |
| Mes parcial en la referencia | Un mes en curso entraba en la muestra de los demás años | Resuelto (`anomalia.py` filtra `parcial`) |
| Días con MODIS caído | Si la referencia está caída y MODIS también, el estimado sale en 0 o incompleto, sin aviso. Pasa en 72 días sin Terra (2000–2002) y en 201 días con un MODIS caído (2002–2012; en 14 cayeron los dos). Faltan ≈ 12.700 focos VIIRS-equivalentes. | Pendiente: contarlos como "sin datos" en `frac_estimada` y en la confianza |
| Días con cobertura parcial | El criterio "≥ 1 foco nacional" toma como observados 31 días con S-NPP < 0,5 × NOAA-20 (7.054 focos) | Depende de una bandera del pipeline |
| Respaldo regional | Si se usa el factor de la región en lugar del de la provincia, el sesgo mediano es 7,7 % (Neuquén −29,7 %) | Pendiente: bajar la confianza cuando `nivel_origen ≠ provincia` |
| Umbral `modis_est ≥ 21` | El error baja de forma continua con la cantidad de focos MODIS; 21 no marca ningún quiebre | Pendiente: basar la confianza en el ancho relativo del rango |

