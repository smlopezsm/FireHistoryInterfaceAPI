# 05 · Despliegue (Docker + Dokploy)

## 1. Imagen Docker

| Aspecto | Especificación |
|---|---|
| Base | `python:3.12-slim` |
| Etapas | 2 (builder con dependencias + runtime mínimo) |
| Usuario | No root (`app`, UID 10001) |
| Puerto | `8000` |
| Comando | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers` |
| Datos | **Dentro de la imagen**: la versión publicada en `data/current/` del repo se copia a `/var/data/current` (sin volumen) |
| Healthcheck | `GET /api/v1/health` cada 30 s, timeout 5 s, 3 reintentos |
| Tamaño objetivo | Código < 250 MB; total < 400 MB con los datos (~100 MB por versión) |
| Dependencias | `fastapi`, `uvicorn[standard]`, `duckdb`, `pyarrow`, `pydantic-settings`, `shapely` (validación de polígonos), `orjson` |
| **Sin** | `lightgbm`, `scikit-learn`, compiladores |

El archivo vigente es el [`Dockerfile`](../Dockerfile) de la raíz del repo; la tabla de arriba resume sus decisiones.

## 2. Variables de entorno

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `DATA_DIR` | No | `/var/data/current` | Carpeta con los Parquet |
| `DUCKDB_MEMORY_LIMIT` | No | `500MB` | Límite de memoria por conexión (una por worker) |
| `DUCKDB_THREADS` | No | `1` | Hilos por conexión |
| `QUERY_TIMEOUT_S` | No | `10` | Corte de consultas largas |
| `MAX_CONSULTAS_CONCURRENTES` | No | `4` | Consultas DuckDB simultáneas por worker; las demás esperan |
| `CORS_ORIGINS` | **Sí** | — | Origen u orígenes del frontend separados por comas, por ejemplo `https://fuegos.example.com.ar` |
| `RELOAD_TOKEN` | **Sí** | — | Token para `POST /admin/reload` |
| `MAX_CELDAS_MAPA` | No | `20000` | Límite de `/mapa/celdas` |
| `MAX_FILAS_CSV` | No | `500000` | Límite de `/descargas/focos.csv` |
| `LOG_LEVEL` | No | `info` | `debug`, `info`, `warning` |

## 3. Dokploy

| Configuración | Valor |
|---|---|
| Tipo de aplicación | Docker image |
| Imagen | `ghcr.io/smlopezsm/firehistory-api:latest` |
| Dominio / ruta | Mismo dominio que el frontend, prefijo `/api` (Traefik `PathPrefix(/api)`) |
| Puerto interno | `8000` |
| Volumen | **Ninguno**: los datos vienen en la imagen. Un mount sobre `/var/data` taparía los datos de la imagen |
| Límite de memoria | 1,5 GB |
| Límite de CPU | 1,5 vCPU |
| Reinicio | `unless-stopped` |
| Despliegue automático | Webhook llamado desde GitHub Actions |

## 4. GitHub Actions (`.github/workflows/build-push.yml`)

| Paso | Detalle |
|---|---|
| Disparador | `push` a `main` y tags `v*` |
| Tests | `pytest` con fixtures Parquet chicos (ver [06](06-pruebas-y-aceptacion.md)) |
| Build | `docker/build-push-action` con caché de capas |
| Tags | `:latest`, `:<sha-corto>` y `:vX.Y.Z` en los tags |
| Registro | `ghcr.io/smlopezsm/firehistory-api` |
| Deploy | `curl -X POST $DOKPLOY_WEBHOOK_URL` (secreto) |

**Secretos del repo:** `DOKPLOY_WEBHOOK_URL`. El `GITHUB_TOKEN` alcanza para publicar en GHCR.

## 5. Preparación del VPS (una sola vez)

| Paso | Comando o acción |
|---|---|
| 1. Usuario y SSH | Usuario sin privilegios + clave pública; deshabilitar el login de root por contraseña |
| 2. Firewall | `ufw allow 22,80,443/tcp && ufw enable` |
| 3. Swap 4 GB | `fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile` + `vm.swappiness=10` |
| 4. Dokploy | Script oficial de instalación de Dokploy |

No hace falta preparar una carpeta de datos en el VPS: los datos vienen dentro de la imagen (§5 bis).

## 5 bis. Actualizar los datos

Los datos viajan **dentro de la imagen** (decisión del 2026-11-14). Para publicar una versión nueva del pipeline:

1. Reemplazar el contenido de `data/current/` con la carpeta `serving_api/<versión>/` del pipeline ([`ML_NasaSpaceApp`](https://github.com/DenisPablo/ML_NasaSpaceApp)).
2. Abrir un PR contra `main`. El CI valida el contrato con las pruebas, construye la imagen y comprueba que `/health` responda con el `data_version` de `data/current/metadata.json`.
3. Al mergear, el CI publica la imagen y Dokploy la despliega (webhook o **Redeploy**).

`POST /admin/reload` y la detección del cambio de `current` siguen funcionando, pero solo sirven si alguien monta otra carpeta de datos a propósito.

## 6. Volver atrás (rollback)

| Qué falló | Cómo se vuelve atrás |
|---|---|
| Código de la API | En Dokploy, volver a desplegar la imagen `:<sha>` anterior |
| Datos | En Dokploy, volver a desplegar la imagen `:<sha>` anterior (trae su versión de datos) |

## 7. Verificar un despliegue

`scripts/verificar_despliegue.py` revisa una API desplegada contra los datos de `data/current/`:
- que `/health` dé `ok` con el mismo `data_version`;
- calendario, serie anual, anomalía y `calendario.csv` de cada provincia;
- las reglas del contrato mes por mes;
- que las respuestas sean iguales a las de la API corrida localmente;
- la clasificación;
- los tiempos contra los objetivos de [06 §4](06-pruebas-y-aceptacion.md#4-pruebas-de-rendimiento-en-el-vps-con-datos-reales).

```bash
PYTHONPATH=. .venv/bin/python scripts/verificar_despliegue.py --base https://<dominio> --informe informe.md
```

Sale con código 1 si algún chequeo falla. `--sin-local` omite la comparación con la API local.
