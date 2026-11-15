# Especificación Técnica y Matemática de `FireHistoryInterfaceAPI`

> **Alcance de verificación:** Revisión directa del código fuente (`app/`, `scripts/`, `tests/`), documentación (`docs/01`–`docs/09`) y artefactos publicados (`data/current/metadata.json`, `data/current/validacion.json` y esquemas/valores Parquet inspeccionados mediante DuckDB en `data/current/`) en la rama de trabajo `propuesta-denis-pablo` (cuyo código ejecutable en `app/` coincide con `main`).

---

## 1. Arquitectura Completa del Backend

### 1.1 Diseño de la aplicación FastAPI y ciclo de vida (`app/main.py`, `app/config.py`)

La aplicación sigue una arquitectura modular en cuatro capas sin estado persistente ni dependencias de *machine learning* (`pyproject.toml:11-20`, `Dockerfile:1-24`):

- **Configuración (`app/config.py:13-42`):** `Settings(BaseSettings)` inmutable (`frozen=True`, lectura opcional de `.env`) validada al arranque vía `get_settings()` (`@lru_cache`). Variables principales:
  - `data_dir` (default `/var/data/current`),
  - `duckdb_memory_limit` (`"500MB"`, validado con `^\d+(\.\d+)?\s*[KMGT]i?B$`),
  - `duckdb_threads` (`1`),
  - `query_timeout_s` (`10.0` s),
  - `max_consultas_concurrentes` (`4`),
  - `cors_origins` (obligatoria, lista separada por comas),
  - `reload_token` (obligatoria, `SecretStr`),
  - `max_celdas_mapa` (`20_000`),
  - `max_filas_csv` (`500_000`),
  - `log_level` (`"debug" | "info" | "warning"`, default `"info"`).
- **Fábrica e inicialización diferida (`app/main.py:47-116`):** `create_app(settings)` construye la instancia `FastAPI(version="0.1.0", docs_url="/docs", openapi_url="/openapi.json")`, registra los 8 routers bajo el prefijo `PREFIJO = "/api/v1"` (`app/main.py:20, 99-106`) y expone `__getattr__("app")` (`app/main.py:110-116`) para instanciar la app al importarla desde Uvicorn (`uvicorn app.main:app --workers 2 --proxy-headers`, `Dockerfile:24`).
- **Ciclo de vida por worker (`lifespan`, `app/main.py:54-73`):** Uvicorn ejecuta `lifespan` de forma independiente en cada proceso worker:
  1. Instancia `datos = Datos(config)`, ejecuta `datos.abrir()` y lo almacena en `app.state.datos`. Si falla la apertura de datos, la aplicación igualmente inicia en estado degradado (`README.md:110-111`, `app/db.py:112-132`).
  2. Lanza una tarea en segundo plano `revisar_version()` (`app/main.py:61-66`) que cada `5` s invoca `asyncio.to_thread(datos.abrir, solo_si_cambio=True)` para detectar cambios atómicos de *symlink* en `DATA_DIR` entre workers.
  3. Al apagar, cancela el monitor y ejecuta `datos.cerrar()`.
- **Middlewares (`app/main.py:87-96`):**
  1. `CacheMiddleware` (`app/cache.py:14-41`) — fijación de versión de datos por petición y cabeceras `ETag`/`Cache-Control`.
  2. `LimiteBodyMiddleware` (`app/limites.py:12-54`) — middleware ASGI puro que limita el cuerpo de `POST`/`PUT`/`PATCH` a `MAX_BODY_BYTES = 256 * 1024` bytes (256 KB), inspeccionando primero `Content-Length` y luego acumulando chunks `http.request` antes de reinyectarlos.
  3. `CORSMiddleware` — orígenes restringidos a `config.cors_origins`, métodos `GET` y `POST`, cabeceras permitidas `Authorization`, `Content-Type`, `If-None-Match`, cabeceras expuestas `ETag`, `Content-Disposition`, `max_age=3600`.
- **Inyección de dependencias (`app/deps.py:14-40`):** `obtener_datos` extrae `request.app.state.datos`; `datos_listos` exige `datos.listo` o lanza `503 DATOS_NO_DISPONIBLES`; `zona_desde_query` construye `PedidoZona(provincia_id=..., bbox=...)` para rutas `GET`.

### 1.2 Motor analítico DuckDB en proceso (`app/db.py`)

Cada worker mantiene una conexión DuckDB en memoria (`:memory:`) de **solo lectura lógica** sobre archivos Parquet (`app/db.py:1-9, 138-174`):

1. **Apertura y vistas (`Datos._conectar`, `app/db.py:138-174`):**
   - Valida `metadata.json` contra `MetadataArchivo` (`app/schemas/metadata.py:19-37`).
   - Abre `duckdb.connect(":memory:", config={"memory_limit": ..., "threads": ..., "preserve_insertion_order": False})`.
   - Crea 9 vistas (`CREATE VIEW <vista> AS SELECT * FROM read_parquet(...)`) definidas en `ARCHIVOS` (`app/db.py:35-45`):
     - Particionadas por año (`hive_partitioning = true, hive_types = {'anio': SMALLINT}` sobre `anio=*/*.parquet`): `focos`, `conteos_celda_dia`.
     - Tablas planas: `dim_celdas`, `dim_provincias`, `factores_provincia_mes`, `factores_region_mes`, `rangos`, `satelite_operativo`, `puntos_industriales`.
   - Precalcula conteos `celdas` (`dim_celdas`) y `provincias` (`dim_provincias`), y bloquea la configuración con `SET lock_configuration = true` (`app/db.py:170`).
   - Encapsula el estado en un dataclass inmutable `VersionDatos(base, con, metadata, celdas, provincias)` (`app/db.py:52-58`).
2. **Aislamiento entre recargas (`fijar_version`, `app/db.py:67-86, 112-132`):**
   - `self._peticion` (`ContextVar`) fija la referencia `VersionDatos` activa al entrar a `CacheMiddleware.dispatch()` (`app/cache.py:19-20`).
   - Durante `abrir()` (protegido por `threading.Lock` `self._recarga`), si el directorio resuelto cambió o si se fuerza recarga, se construye la nueva `VersionDatos` antes de reemplazar `self._actual`; si falla, se conserva la versión anterior (`app/db.py:113-132`). La conexión anterior no se cierra explícitamente para no romper consultas en curso (`app/db.py:127-128`, `tests/test_recarga.py:66-78`).
3. **Concurrencia, timeouts y transferencia Arrow (`Datos._ejecutar`, `app/db.py:233-263`):**
   - Controla concurrencia intra-worker mediante `self._cupos = threading.BoundedSemaphore(settings.max_consultas_concurrentes)` (default `4`), con espera acotada a `query_timeout_s` (`10` s).
   - Crea un cursor por consulta (`version.con.cursor()`) y programa `threading.Timer(limite, cursor.interrupt)`. Si se dispara `duckdb.InterruptException`, retorna `504 TIEMPO_EXCEDIDO`.
   - **Optimización crítica para zonas grandes (`app/db.py:250-254`):** Cuando se pasa `celdas: Sequence[int]`, se registra una tabla PyArrow en memoria (`pa.table({"cell_id": pa.array(celdas, type=pa.int32())})`) bajo el nombre `zona_celdas` en el cursor, evitando pasar listas `unnest(?::INTEGER[])` parametrizadas (que tardaban ~8 s para ~112.000 celdas del país frente a <0,3 s con Arrow; `docs/08:52`, `tests/test_db.py:83-105`).
   - **Exportación por lotes (`Datos.exportar_filas`, `app/db.py:193-225`):** Dentro del mismo cursor y presupuesto de tiempo, ejecuta primero `SELECT count(*) ...` contra `maximo` (`500.000`) y, si no lo excede, ejecuta `SELECT ... LIMIT maximo + 1` extrayendo bloques con `cursor.fetchmany(4096)`.

### 1.3 Datasets Parquet/GeoParquet en `data/current/` (`docs/02`, `scripts/esquemas.py`, `scripts/grilla.py`)

Todos los archivos usan Apache Parquet con compresión **ZSTD**, coordenadas WGS84 (EPSG:4326) en `FLOAT` (32 bits) y fechas en `DATE` (hora local de Argentina, UTC−3 o huso histórico provincial; `docs/02:7-17`). La grilla espacial utiliza una proyección cónica equivalente de **Albers custom para Argentina** sobre el elipsoide **GRS80** (`docs/01:53`, `scripts/grilla.py:18-26`):

```text
+proj=aea +lat_0=-37 +lon_0=-60 +lat_1=-26 +lat_2=-48 +x_0=2500000 +y_0=0 +ellps=GRS80
```

con celdas de $5 \times 5\text{ km}$ (`TAM_CELDA = 5000.0` m, área nominal $25\text{ km}^2$), matriz de $780 \times 460$ y clave $\text{cell\_id} = \text{fila} \times 460 + \text{columna}$.

En `data/current/` se encuentran los siguientes artefactos:

1. **`focos/anio=YYYY/part-0.parquet`** (`2000`–`2026`, `6.201.450` filas totales en `validacion.json:91`): detecciones individuales limpias excluyendo puntos industriales.
2. **`conteos_celda_dia/anio=YYYY/part-0.parquet`** (`1.890.033` filas totales en `validacion.json:92`): representación dispersa `(cell_id, fecha, provincia_id, n_terra, n_aqua, n_snpp, n_n20, n_n21)`.
3. **`dim_celdas.parquet`** (`112.711` filas en `validacion.json:93`): `cell_id`, `grid_row`, `grid_col`, `provincia_id`, `region`, `frac_dentro`, `lat_centro`, `lon_centro`, `geom_geojson`.
4. **`dim_provincias.parquet`** (`24` provincias en 5 regiones): `provincia_id`, `nombre`, `region`, `geom_geojson`, `bbox`.
5. **`factores_provincia_mes.parquet`** (`576` filas: `288` `terra` + `288` `modis`): valores observados `modis` $\in [2.221, 5.942]$, `terra` $\in [4.055, 25.938]$.
6. **`factores_region_mes.parquet`** (`144` filas: 5 regiones + `'Argentina'` × 12 meses × 2 tipos): `Argentina/modis` $\in [3.020, 3.886]$; `Argentina/terra` $\in [7.080, 15.073]$.
7. **`rangos.parquet`** (`6` tramos): multiplicadores empíricos `(mult_bajo, mult_alto)` para bandas de incertidumbre del 80 %.
8. **`satelite_operativo.parquet`**: cobertura operativa diaria para `Terra`, `Aqua`, `SNPP`, `N20` y `N21`.
9. **`puntos_industriales.parquet`**: `478` puntos persistentes (`73.897` focos excluidos en `validacion.json:79-82`).
10. **`metadata.json` y `validacion.json`**: `schema_version = "1.1.0"`, `factores_version = "2026.11-b1"`, `fecha_min = "2000-11-01"`, `fecha_max = "2026-11-13"`.

### 1.4 Resolución espacial de zonas (`app/services/zonas.py`)

`resolver_zona(datos, pedido)` exige exactamente uno de `provincia_id`, `bbox` o `geometria`:
- **Por `provincia_id`**: consulta `dim_provincias` (`404 PROVINCIA_NO_ENCONTRADA` si no existe) y selecciona `dim_celdas` por mayor fracción de área.
- **Por `bbox`**: valida `oeste < este` en `[-180, 180]` y `sur < norte` en `[-90, 90]` (`422 PARAMETRO_INVALIDO`) y filtra por centroide `(lon_centro, lat_centro)`.
- **Por polígono GeoJSON (`POST`)**: valida `Polygon`/`MultiPolygon`, hasta `2000` vértices y `geom.is_valid` (`400 GEOMETRIA_INVALIDA`), prefiltra por bounding box en DuckDB y aplica filtro exacto vectorizado con `shapely.prepare` + `shapely.intersects_xy`.

### 1.5 Catálogo completo de endpoints (`/api/v1`)

| Método y Ruta | Handler | Parámetros / Cuerpo | Comportamiento y Respuesta |
|---|---|---|---|
| `GET /api/v1/health` | `app/routers/health.py:13-30` | — | Siempre `200`. `estado`, `datos_listos`, `data_version`, `fecha_max`. Excluido de caché. |
| `GET /api/v1/metadata` | `app/routers/metadata.py:14-31` | — | Campos de `metadata.json` + `celdas_total` y `provincias_total`. |
| `GET /api/v1/provincias` | `app/routers/provincias.py:17-47` | `geometria: bool = false` | Lista de 24 provincias ordenada por `provincia_id`. |
| `GET` / `POST /api/v1/calendario` | `app/routers/armonizacion.py:57-83` | Zona + `desde`/`hasta` (`YYYY-MM`) + `capa` | Serie mensual armonizada con `minimo`, `maximo`, `estado`, `confianza`. |
| `GET` / `POST /api/v1/serie` | `app/routers/armonizacion.py:86-115` | Zona + período + `granularidad` (`mes\|anio`) | Serie mensual o anual agregada (`agrupar_anios`). |
| `GET` / `POST /api/v1/anomalia` | `app/routers/anomalia.py:24-52` | Zona + `mes` (`YYYY-MM`) | Comparación contra mediana histórica, `p25`, `p75`, `percentil` y `categoria`. |
| `GET /api/v1/mapa/celdas` | `app/routers/mapa.py:17-46` | `bbox`, `desde`, `hasta` (máx. 366 días), `capa`, `min_focos` | `FeatureCollection` GeoJSON (`orjson`); `413` si supera `20.000` celdas. |
| `GET /api/v1/mapa/industriales` | `app/routers/mapa.py:49-63` | `bbox` opcional | `FeatureCollection` de `Point` industriales excluidos. |
| `GET` / `POST /api/v1/descargas/focos.csv` | `app/routers/descargas.py:144-183` | Zona + rango diario + `sensor` | CSV streaming (`413` si $> 500.000$ filas). |
| `GET` / `POST /api/v1/descargas/calendario.csv` | `app/routers/descargas.py:186-214` | Zona + `PeriodoConsulta` | CSV streaming con serie mensual armonizada. |
| `POST /api/v1/admin/reload` | `app/routers/admin.py:15-41` | `Authorization: Bearer <RELOAD_TOKEN>` | Recarga atómica de `Datos`; devuelve `204`, `401`, `403` o `503`. |

### 1.6 Estrategia de Caché (`app/cache.py`) y Manejo de Errores (`app/errores.py`)

- `CacheMiddleware` fija la versión de datos por petición (`datos.fijar_version()`), emite `ETag: "<data_version>"` y `Cache-Control: public, max-age=3600` (excluyendo `/health` y `/admin/`), y responde `304 Not Modified` si coincide `If-None-Match`.
- Todos los errores retornan `{"error": {"codigo": "...", "mensaje": "...", "detalle": ...}}` (`400`, `401`, `403`, `404`, `405`, `413`, `422`, `503`, `504`).

---

## 2. Formulación Matemática y Física de la Armonización (`MODIS → VIIRS`)

### 2.1 Por qué es necesaria

1. **Desajuste de resolución espacial y sensibilidad:** MODIS (Terra/Aqua) resuelve a **1 km**, mientras que VIIRS (S-NPP/NOAA-20) opera a **375 m**, detectando focos pequeños que MODIS pierde. En `data/current/validacion.json`, usar MODIS crudo respecto a escala VIIRS produce un error de **$69{,}74\%$ a $70{,}74\%$**.
2. **Asimetría orbital histórica:**
   - **2000-11-01 → 2002-07-03:** solo opera MODIS **Terra** (una sola ventana diaria; factor nacional implícito $\approx 9{,}08$, máximos provinciales hasta $25{,}94$ en invierno).
   - **2002-07-04 → 2012-01-19:** operan **Terra + Aqua** (`tipo = modis`, factor nacional implícito $\approx 3{,}33$).
   - **2012-01-20 → 2026-11-02:** **S-NPP VIIRS** es la referencia observada (con días aislados no operativos).
   - **2026-11-03 → hoy:** **NOAA-20 (`N20`)** es referencia operativa (razón empírica $0{,}99$ respecto a S-NPP, sin factor adicional). **NOAA-21 (`N21`) nunca se suma** para evitar doble conteo.
3. **Validación fuera de muestra (`data/current/validacion.json`):**
   - Hacia atrás (`2012–2014`, $n=840$ meses): error **$15{,}49\%$**, sesgo **$+0{,}012\%$**.
   - Hacia adelante (`2020–2025`, $n=1728$ meses): error **$16{,}52\%$**, sesgo **$-4{,}89\%$**.
   - Cobertura empírica de los intervalos del 80 %: **$83{,}11\%$** (objetivo $72\text{--}88\%$).

### 2.2 Ecuaciones paso a paso

#### Paso 1: Asignación a la grilla $5 \times 5\text{ km}$ (`scripts/grilla.py:79-86`)
$$\text{col} = \left\lfloor \frac{x - X_{\min}}{5000} \right\rfloor, \quad \text{fila} = \left\lfloor \frac{Y_{\max} - y}{5000} \right\rfloor, \quad \text{cell\_id} = \text{fila} \times 460 + \text{col}$$

#### Paso 2: Separación diaria observado vs. a estimar (`app/services/armonizacion.py:20-53`)
Sea $\text{op}(d) = \mathbb{I}[\text{operativo}(d, \text{ref}(d)) = \text{true}]$. Para cada celda $c \in C_Z$ y día $d$:
$$V^{\text{obs}}_{c,d} = \begin{cases} n^{\text{SNPP}}_{c,d} & \text{si } \text{op}(d)=1 \land \text{ref}(d)=\text{SNPP} \\ n^{\text{N20}}_{c,d} & \text{si } \text{op}(d)=1 \land \text{ref}(d)=\text{N20} \\ 0 & \text{si } \text{op}(d)=0 \end{cases}$$
$$M^{\text{terra}}_{c,d} = \mathbb{I}[\text{op}(d)=0 \land d < \text{2002-07-04}] \cdot n^{\text{Terra}}_{c,d}$$
$$M^{\text{modis}}_{c,d} = \mathbb{I}[\text{op}(d)=0 \land d \ge \text{2002-07-04}] \cdot (n^{\text{Terra}}_{c,d} + n^{\text{Aqua}}_{c,d})$$

#### Paso 3: Agregación mensual por provincia (`app/services/armonizacion.py:55-75`)
$$O_{p,m} = \sum_{c \in Z_p, d \in m} V^{\text{obs}}_{c,d}, \quad T_{p,m} = \sum_{c \in Z_p, d \in m} M^{\text{terra}}_{c,d}, \quad A_{p,m} = \sum_{c \in Z_p, d \in m} M^{\text{modis}}_{c,d}$$
con $M^{\text{est}}_{p,m} = T_{p,m} + A_{p,m}$.

#### Paso 4: Factor jerárquico y cotas (`Factores.obtener`, `app/services/armonizacion.py:149-170`)
$$f(p, k, \tau) = \begin{cases} f_{\text{prov}}(p, k, \tau) & \text{si existe} \\ f_{\text{reg}}(r(p), k, \tau) & \text{respaldo regional} \\ f_{\text{reg}}(\text{Argentina}, k, \tau) & \text{respaldo nacional} \end{cases}$$
Cotas validadas en publicación: $0{,}5 < f < 20$ para $\tau=\text{modis}$, y $0{,}5 < f < 40$ para $\tau=\text{terra}$.

#### Paso 5: Estimación e intervalo del 80 % (`_sumar_provincia`, `app/services/armonizacion.py:173-199`)
$$\hat{E}_{p,m} = T_{p,m} \cdot f(p, k, \text{terra}) + A_{p,m} \cdot f(p, k, \text{modis})$$
Con $(\text{mult\_bajo}, \text{mult\_alto})$ de `rangos.parquet` según el tramo de $M^{\text{est}}_{p,m}$:
$$\text{min}_{p,m} = \hat{E}_{p,m} \cdot \text{mult\_bajo}, \qquad \text{max}_{p,m} = \begin{cases} \hat{E}_{p,m} \cdot \text{mult\_alto} & M^{\text{est}}_{p,m} > 0 \\ \text{mult\_alto} & M^{\text{est}}_{p,m} = 0 \land E_m = D_m \end{cases}$$

#### Paso 6: Serie de zona, estado y confianza (`app/services/armonizacion.py:78-125, 234-261`)
$$\text{armonizado}_m = \sum_{p \in Z} (O_{p,m} + \hat{E}_{p,m}), \qquad \phi_m = \frac{E_m}{D_m}$$
- `estado`: `"observado"` ($\phi_m = 0$), `"estimado"` ($\phi_m = 1$), `"mixto"` ($0 < \phi_m < 1$).
- `confianza`: `"alta"` si $\phi_m \le 0{,}1$; `"media"` si $\phi_m > 0{,}1$, mayoría de área fuera de `{94, 78, 02}`, $T_m = 0$ y $A_m \ge 21$; `"baja"` en otro caso.

#### Paso 7: Anomalía histórica (`app/services/anomalia.py:12-53`)
Con la muestra ordenada $S$ de meses pasados completos del mismo mes calendario ($n = |S|$):
- Cuantil discreto: $Q(S, q) = s_{\lceil n \cdot q \rceil - 1}$ ($p_{10}, p_{25}, p_{75}, p_{90}$).
- Razón: $v / \text{mediana}(S)$; Percentil: $100 \cdot \text{bisect\_right}(S, v) / n$.
- `categoria` (solo si $n \ge 10$ y mes completo): `muy_por_debajo` ($<p_{10}$), `por_debajo` ($[p_{10}, p_{25})$), `normal` ($[p_{25}, p_{75}]$), `por_encima` ($(p_{75}, p_{90}]$), `muy_por_encima` ($>p_{90}$).
