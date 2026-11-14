# 05 · Despliegue (Docker + Dokploy)

## 1. Imagen Docker

| Aspecto | Especificación |
|---|---|
| Base | `python:3.12-slim` |
| Etapas | 2 (builder con dependencias + runtime mínimo) |
| Usuario | No root (`app`, UID 10001) |
| Puerto | `8000` |
| Comando | `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2 --proxy-headers` |
| Datos | Volumen `/var/data` montado **read-only** |
| Healthcheck | `GET /api/v1/health` cada 30 s, timeout 5 s, 3 reintentos |
| Tamaño objetivo | < 250 MB |
| Dependencias | `fastapi`, `uvicorn[standard]`, `duckdb`, `pyarrow`, `pydantic-settings`, `shapely` (validación de polígonos), `orjson` |
| **Sin** | `lightgbm`, `scikit-learn`, compiladores |

### Dockerfile de referencia

```dockerfile
FROM python:3.12-slim AS builder
WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim
RUN useradd -u 10001 -m app
COPY --from=builder /install /usr/local
WORKDIR /srv
COPY app ./app
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=4).status==200 else 1)"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","2","--proxy-headers"]
```

## 2. Variables de entorno

| Variable | Obligatoria | Default | Descripción |
|---|---|---|---|
| `DATA_DIR` | No | `/var/data/current` | Carpeta con los Parquet |
| `DUCKDB_MEMORY_LIMIT` | No | `500MB` | Límite de memoria por conexión (una por worker) |
| `DUCKDB_THREADS` | No | `1` | Hilos por conexión |
| `QUERY_TIMEOUT_S` | No | `10` | Corte de consultas largas |
| `CORS_ORIGINS` | **Sí** | — | Dominio del frontend, por ejemplo `https://fuegos.example.com.ar` |
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
| Volumen | `/var/data` (host) → `/var/data` (contenedor), **read-only** |
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
| 5. Carpeta de datos | `mkdir -p /var/data/releases` + usuario `deploy` con permiso solo sobre `/var/data` (para el rsync del pipeline) |
| 6. Primera carga | `rsync` del paquete de datos → `releases/<version>` → `ln -sfn releases/<version> /var/data/current` |

## 6. Volver atrás (rollback)

| Qué falló | Cómo se vuelve atrás |
|---|---|
| Código de la API | En Dokploy, volver a desplegar la imagen `:<sha>` anterior |
| Datos | `ln -sfn /var/data/releases/<version-anterior> /var/data/current` + `POST /admin/reload` |
