# FireHistoryInterfaceAPI

API REST del **calendario armonizado de focos de calor MODIS × VIIRS para Argentina** (NASA Space Apps Challenge 2026: *Harmonization of MODIS and VIIRS Hot Spots*).

Sirve conteos de focos **armonizados a escala VIIRS** por región y período, para que la interfaz web ([FireHistoryInterface](https://github.com/smlopezsm/FireHistoryInterface)) muestre:
- un calendario mes × año;
- la comparación con la mediana histórica;
- la descarga de los datos.

> **No hay modelos de IA en el servidor.** La armonización se resuelve con **tablas de factores** precalculadas (provincia × mes). La API solo filtra, suma y multiplica sobre archivos Parquet con DuckDB.

---

## Resumen técnico

| Aspecto | Decisión |
|---|---|
| Lenguaje / framework | Python 3.12 + FastAPI + Uvicorn (2 workers) |
| Motor de consultas | DuckDB embebido, **solo lectura**, sobre Parquet |
| Datos | Generados por el pipeline [`ml_nasaspaceapp`](https://github.com/DenisPablo/ml_nasaspaceapp) y montados en `/var/data` |
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

## Estructura prevista del repositorio

```text
FireHistoryInterfaceAPI/
├── app/
│   ├── main.py              # FastAPI app, routers, CORS, healthcheck
│   ├── config.py            # Variables de entorno (pydantic-settings)
│   ├── db.py                # Conexión DuckDB read-only por worker
│   ├── routers/             # health, metadata, provincias, calendario, serie, anomalia, mapa, descargas
│   ├── services/            # armonizacion.py, agregaciones.py, geometria.py
│   └── schemas/             # Modelos Pydantic de request/response
├── tests/                   # pytest + datos de prueba chicos (fixtures Parquet)
├── docs/                    # Esta documentación
├── Dockerfile
├── .dockerignore
├── pyproject.toml
└── .github/workflows/       # build-push.yml (imagen a GHCR + webhook Dokploy)
```

## Inicio rápido (local)

```bash
# Requiere Docker y los datos en ./data (ver docs/02)
docker build -t firehistory-api .
docker run --rm -p 8000:8000 -v "$PWD/data:/var/data:ro" firehistory-api
# → http://localhost:8000/api/v1/health
# → http://localhost:8000/docs  (Swagger)
```

## Licencia y datos

Datos de focos: NASA FIRMS (MODIS C6.1, VIIRS 375 m). Límites: IGN, vía API Georef. Ver la sección de citas en [docs/02](docs/02-contratos-de-datos.md#fuentes-y-citas).
