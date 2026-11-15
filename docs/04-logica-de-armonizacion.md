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
4. **Días sin MODIS.** Un día estimado sin el MODIS necesario (Terra; Terra + Aqua desde 2002-07-04, según `satelite_operativo`) no aporta focos, así que el estimado puede quedar corto. No se rellena: parte de esos días son probablemente cero fuego real, porque "operativo" se define con ≥ 1 foco nacional. Solo se ensancha el máximo, suponiendo que esos días fueron como el promedio de los estimados con MODIS: `max_pm × dias_estimados / (dias_estimados − dias_sin_modis)`. Si ningún día estimado tuvo MODIS, el máximo no cambia. La respuesta informa `dias_sin_modis`.

Sumar los límites provincia por provincia da un rango **conservador** (más ancho que el real) para zonas grandes. Es aceptable para el MVP y está documentado. Medido a escala nacional, el rango que resulta de sumar provincias contiene el valor real en el **98,8 %** de los meses: es más un rango del 99 % que uno del 80 %.

## 5. Confianza

| `confianza` | Condición |
|---|---|
| `alta` | `frac_estimada ≤ 0,1` (en cualquier zona, también en provincias con "pocos datos") |
| `media` | Estimado con MODIS Terra + Aqua, con un rango no más ancho que lo estimado (`maximo − minimo ≤ armonizado − viirs`, y lo estimado > 0) y ninguna de las condiciones de `baja` |
| `baja` | `frac_estimada > 0,1` y al menos una de estas: período solo Terra (antes de 2002-07-04); el rango es más ancho que lo estimado, o lo estimado es 0; la zona tiene más del 50 % de su área en provincias marcadas como "pocos datos" (Tierra del Fuego, Santa Cruz, CABA); `dias_sin_modis` supera el 10 % de los días estimados; o más del 50 % del estimado sale de factores con `nivel_origen` `region` o `pais` |

Se evalúa en orden: primero `alta`; las condiciones de `baja` solo afectan a lo **estimado**, porque un mes observado no depende de los factores ni de MODIS.

Los tres últimos criterios salen del [veredicto de armonización](#8-validación-científica-y-limitaciones-conocidas):
- **Ancho del rango (antes, `modis_est ≥ 21`):** el umbral de 21 focos se aplicaba al total de la zona, así que una región con muchas provincias de pocos focos cada una quedaba en `media`. El ancho relativo sale de `rangos.parquet`: en una provincia es 0,73 en el tramo de 21–100 focos MODIS y 1,34 en el de 6–20, de modo que el límite "ancho ≤ estimado" separa en el mismo punto que antes. Con los datos `20261114T174945`, las 24 provincias y el país no cambian; en las regiones, 54 meses pasan de `media` a `baja` (35 en Patagonia y 17 en Cuyo).
- **Días sin MODIS:** el 10 % es el mismo umbral que separa `alta`. Con los datos `20261114T174945`, 90 meses tienen algún día sin MODIS, pero en 58 son solo 1 o 2 días (muchos, probablemente cero fuego real en invierno). Con el umbral, la confianza baja en 25 meses.
- **Factor no provincial:** dejando cada provincia afuera y usando el factor de su región, el sesgo mediano es 7,7 % (Neuquén −29,7 %). Se mide la parte del estimado (focos × factor) que usa factores `region` o `pais`, sea porque falta el de la provincia o porque el pipeline marcó el factor así (shrinkage). El umbral del 50 % sigue la misma lógica que "pocos datos".

## 6. Anomalía (mes vs. lo normal)

- Se calcula sobre `armonizado` del **mismo mes calendario**, **excluyendo** el mes evaluado y los meses incompletos.
- **Se compara solo con años de la misma era** (`referencia`), definida **por fecha**: desde el primer mes completo con referencia VIIRS (`2012-02`, porque S-NPP empieza el 2012-01-20; se calcula con `metadata.referencia_viirs`) la era es `observada`; antes, `estimada` (desde MODIS). No se usa `frac_estimada`: un mes de la época VIIRS con la referencia caída varios días (2022-07, 2022-08, 2024-07 y 2026-07 con los datos `20261114T174945`) sigue comparándose con los años observados, y no con 2001–2011. Motivo: MODIS crudo baja un 33 % entre 2003–2011 y 2012–2025, así que mezclar las eras hacía que el 35 % de los meses 2012+ saliera "por debajo" y el 40 % de los anteriores "por encima" (escala nacional). Con la referencia por era, cada era queda con 27 % abajo y 27 % arriba. No se asume que esa caída sea real ni un efecto del sensor: no está verificado.
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
| Anomalía entre eras | La referencia mezcla 2001–2011 (estimado) con 2012+ (observado). MODIS crudo baja un 33 % entre esas eras, y en 2012+ el 35 % de los meses sale "por debajo" (lo esperado es 25 %). | Resuelto: cada mes se compara con los años de su misma era (`referencia`, §6) |
| Mes parcial en la referencia | Un mes en curso entraba en la muestra de los demás años | Resuelto (`anomalia.py` filtra `parcial`) |
| Días con MODIS caído | Si la referencia está caída y MODIS también, el estimado sale en 0 o incompleto, sin aviso. Pasa en 72 días sin Terra (2000–2002) y en 201 días con un MODIS caído (2002–2012; en 14 cayeron los dos). Faltan ≈ 12.700 focos VIIRS-equivalentes. | Resuelto: `dias_sin_modis` en la respuesta, máximo ensanchado y confianza `baja` si superan el 10 % de los días estimados (§4 y §5) |
| Días con cobertura parcial | El criterio "≥ 1 foco nacional" toma como observados 31 días con S-NPP < 0,5 × NOAA-20 (7.054 focos) | Depende de una bandera del pipeline |
| Respaldo regional | Si se usa el factor de la región en lugar del de la provincia, el sesgo mediano es 7,7 % (Neuquén −29,7 %) | Resuelto: confianza `baja` si más del 50 % del estimado usa factores `region` o `pais` (§5) |
| Umbral `modis_est ≥ 21` | El error baja de forma continua con la cantidad de focos MODIS; 21 no marca ningún quiebre | Resuelto: `media` exige un rango no más ancho que lo estimado (§5) |

