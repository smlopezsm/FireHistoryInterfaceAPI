# FireHistoryInterfaceAPI

API REST del **calendario armonizado de focos de calor MODIS × VIIRS para Argentina** (NASA Space Apps Challenge 2026: *Harmonization of MODIS and VIIRS Hot Spots*).

Sirve conteos de focos **armonizados a escala VIIRS** por región y período, para que la interfaz web ([FireHistoryInterface](https://github.com/smlopezsm/FireHistoryInterface)) muestre:
- un calendario mes × año;
- la comparación con la mediana histórica;
- la descarga de los datos.

> **No hay modelos de IA en el servidor.** La armonización se resuelve con **tablas de factores** precalculadas (provincia × mes). La API solo filtra, suma y multiplica sobre archivos Parquet con DuckDB.
>
> **Aviso:** Esta es una **rama experimental** y una **demostración** con fines exploratorios y educativos. Sus resultados y estimaciones no deben tomarse en ningún caso como verdad absoluta ni utilizarse como modelo predictivo ni para la toma de decisiones operativas o de emergencia.

---

## Resumen técnico

| Aspecto | Decisión |
|---|---|
| Lenguaje / framework | Python 3.12 + FastAPI + Uvicorn (2 workers) |
| Motor de consultas | DuckDB embebido, **solo lectura**, sobre Parquet |
| Datos | Generados por el pipeline [`ML_NasaSpaceApp`](https://github.com/DenisPablo/ML_NasaSpaceApp); la versión publicada está en `data/current/` y viaja **dentro de la imagen** (`/var/data/current`) |
| Alcance | Argentina completa, noviembre 2000 → hoy |
| Producto principal | **Conteos de focos** (no FRP) |
| Despliegue | Docker en VPS DonWeb (4 GB / 2 vCPU) con Dokploy + Traefik |
| Imagen | Construida en GitHub Actions y publicada en GHCR; el VPS solo hace `pull` |

## Documentación

| Documento | Contenido |
|---|---|
| [docs/01-arquitectura.md](docs/01-arquitectura.md) | Topología, componentes, presupuesto de RAM, flujo de actualización |
| [docs/02-contratos-de-datos.md](docs/02-contratos-de-datos.md) | **Formato exacto de cada archivo de datos** (tablas de columnas, tipos, reglas) |
| [docs/03-contratos-api.md](docs/03-contratos-api.md) | **Endpoints**: parámetros, respuestas, errores y límites |
| [docs/04-logica-de-armonizacion.md](docs/04-logica-de-armonizacion.md) | Cómo la API calcula observado, estimado y rangos |
| [docs/05-despliegue.md](docs/05-despliegue.md) | Dockerfile, variables de entorno, Dokploy, CI/CD |
| [docs/06-pruebas-y-aceptacion.md](docs/06-pruebas-y-aceptacion.md) | Plan de pruebas y criterios de aceptación |
| [docs/07-spec-kit.md](docs/07-spec-kit.md) | Cómo trabajamos con GitHub Spec Kit (SDD) y los textos iniciales |
| [docs/08-proximos-pasos.md](docs/08-proximos-pasos.md) | **Estado actual, decisiones tomadas y pendientes** (para retomar el trabajo) |

## Estructura del repositorio

```text
FireHistoryInterfaceAPI/
├── app/
│   ├── main.py              # Fábrica de la app, routers, middlewares, ciclo de vida
│   ├── config.py            # Variables de entorno (pydantic-settings)
│   ├── db.py                # Conexión DuckDB por worker, versión de datos, recarga
│   ├── cache.py · limites.py · errores.py · deps.py
│   ├── routers/             # Un archivo por grupo de endpoints (ver docs/03)
│   ├── services/            # armonizacion, anomalia, mapa, zonas
│   └── schemas/             # Modelos Pydantic de request/response
├── data/current/            # Versión de datos publicada (entra en la imagen)
├── scripts/                 # Fixtures, datos demo, esquemas y grilla
├── tests/                   # pytest + fixtures Parquet chicos
├── docs/                    # Esta documentación
├── Dockerfile
├── .dockerignore
├── pyproject.toml
└── .github/workflows/       # build-push.yml (pruebas, imagen a GHCR + webhook Dokploy)
```

## Inicio rápido (local)

### 1. Entorno de desarrollo

```bash
uv venv --python 3.12 .venv          # o: python3.12 -m venv .venv
uv pip install -e ".[dev]"           # o: .venv/bin/pip install -e ".[dev]"
```

### 2. Datos

> ⚠️ **Datos de demostración.** `scripts/make_demo_data.py` genera focos **sintéticos**
> (San Luis, Córdoba y Neuquén, 2000-11 → 2026-11, con una caída simulada de S-NPP del
> 2022-08-01 al 2022-08-10). Sirven para probar la API y la interfaz, **no para analizar
> incendios reales**. `metadata.json` lo indica en `fuentes`.

| Datos | Cómo se obtienen | Carpeta |
|---|---|---|
| **Demo** (sintéticos) | `.venv/bin/python scripts/make_demo_data.py` | `data/demo/` (no se sube al repo) |
| **Reales** | Versión publicada por el pipeline [`ML_NasaSpaceApp`](https://github.com/DenisPablo/ML_NasaSpaceApp) con el formato de [docs/02](docs/02-contratos-de-datos.md) | `data/current/` (en el repo y dentro de la imagen) |
| **Fixtures** de prueba | `.venv/bin/python scripts/make_fixtures.py` (ya están en el repo) | `tests/fixtures/` |

### 3. Levantar la API

Sin Docker:

```bash
cp .env.example .env                 # DATA_DIR=data/demo por defecto
.venv/bin/uvicorn app.main:app --reload
```

Con Docker (la carpeta de datos se monta en `/var/data/current`, solo lectura):

```bash
docker build -t firehistory-api:dev .
docker run --rm -p 8000:8000 -v "$PWD/data/demo:/var/data/current:ro" \
  -e CORS_ORIGINS=http://localhost:5173 -e RELOAD_TOKEN=dev firehistory-api:dev
```

La imagen ya trae los datos reales de `data/current/`: sin el `-v` usa esos. El `-v` de arriba los reemplaza por los de demo.

- Salud: <http://localhost:8000/api/v1/health>
- Swagger: <http://localhost:8000/docs>

### 4. Verificación

```bash
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy app
.venv/bin/pytest -q
```

Si faltan los datos, la API levanta igual: `/health` responde `estado: degradado` y los
endpoints de datos devuelven `503 DATOS_NO_DISPONIBLES`.

## Datos de producción

La versión publicada por el pipeline está en **`data/current/`** y **se copia dentro de la imagen Docker** (no hace falta montar nada en el VPS). Cómo actualizarla: [docs/05 §5 bis](docs/05-despliegue.md#5-bis-actualizar-los-datos).

Para levantar la API local con esos datos: `DATA_DIR=data/current CORS_ORIGINS=http://localhost:5173 RELOAD_TOKEN=dev .venv/bin/uvicorn app.main:app`.

## Licencia y datos

Datos de focos: NASA FIRMS (MODIS C6.1, VIIRS 375 m). Límites: IGN, vía API Georef. Ver la sección de citas en [docs/02](docs/02-contratos-de-datos.md#fuentes-y-citas).
