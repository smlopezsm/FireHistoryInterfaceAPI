# 01 · Arquitectura

## 1. Visión general

El sistema tiene **tres piezas**, cada una en su propio repositorio:

| Pieza | Repositorio | Dónde corre | Qué hace |
|---|---|---|---|
| **Pipeline de datos** | `DenisPablo/ml_nasaspaceapp` | GitHub Actions (programado) o PC local | Descarga FIRMS, limpia, excluye fuentes industriales, cuenta y armoniza. **Produce los Parquet.** |
| **API** | `smlopezsm/FireHistoryInterfaceAPI` (este) | VPS DonWeb, contenedor Docker | Lee los Parquet con DuckDB y responde consultas por región y período |
| **Frontend** | `smlopezsm/FireHistoryInterface` | VPS DonWeb, contenedor Docker (Nginx) | Mapa, calendario, comparación con la mediana y descargas |

## 2. Topología en el servidor

```text
                       Usuarios (Internet)
                               │  80 / 443
┌──────────────────────────────▼───────────────────────────────────┐
│ VPS DonWeb · Ubuntu 24.04 · 2 vCPU · 4 GB RAM · 40–50 GB NVMe    │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Dokploy + Traefik (SSL Let's Encrypt, ruteo por path)      │  │
│  └──────────────┬───────────────────────────────┬─────────────┘  │
│        ruta: /*  │                     ruta: /api/*               │
│  ┌──────────────▼──────────────┐   ┌──────────────▼────────────┐ │
│  │ frontend (Nginx Alpine)     │   │ api (FastAPI + Uvicorn)   │ │
│  │ React compilado (estático)  │   │ 2 workers · DuckDB r/o    │ │
│  │ límite 256 MB               │   │ límite 1,5 GB             │ │
│  └─────────────────────────────┘   └──────────────┬────────────┘ │
│                                                   │ solo lectura │
│  ┌────────────────────────────────────────────────▼────────────┐ │
│  │ Dentro de la imagen: /var/data/current (data/current/ repo) │ │
│  │  ├── focos/anio=YYYY/*.parquet        detecciones limpias    │ │
│  │  ├── conteos_celda_dia/anio=YYYY/*.parquet                   │ │
│  │  ├── dim_celdas.parquet · dim_provincias.parquet             │ │
│  │  ├── factores_provincia_mes.parquet (tipo modis / terra)     │ │
│  │  ├── factores_region_mes.parquet  respaldo región / país     │ │
│  │  ├── rangos.parquet · satelite_operativo.parquet             │ │
│  │  ├── puntos_industriales.parquet                             │ │
│  │  └── metadata.json                                           │ │
│  └──────────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────────┘
```

> El detalle de cada archivo está en [02-contratos-de-datos.md](02-contratos-de-datos.md).

## 3. Decisiones de base

- **Sin modelo de IA en el servidor:** la armonización usa tablas de factores provincia × mes (no el LightGBM del informe de infraestructura original).
- **Alcance:** toda Argentina, de 2000-11 a hoy (la cantidad de celdas está en `celdas_total` de `/metadata`).
- **Proyección de la grilla:** Albers custom `+proj=aea +lat_0=-37 +lon_0=-60 +lat_1=-26 +lat_2=-48 +x_0=2500000 +y_0=0 +ellps=GRS80`. El informe original citaba EPSG:5347, que es Gauss-Krüger faja 5 y no Albers.
- **Disco del VPS:** 40–50 GB (SO, imágenes, 4 GB de swap y margen).

## 4. Presupuesto de memoria (4.096 MB)

| Proceso | Nominal | Pico | Límite configurado |
|---|---:|---:|---:|
| Linux + systemd + SSH | ~300 MB | ~400 MB | — |
| Dokploy + Traefik | ~350 MB | ~500 MB | — |
| Frontend (Nginx Alpine) | ~20 MB | ~40 MB | 256 MB |
| API: Python + FastAPI (2 workers) | ~200 MB | ~300 MB | 1,5 GB (contenedor) |
| API: DuckDB (2 conexiones) | ~200 MB | ~1.000 MB | 500 MB por conexión (`memory_limit`) |
| **Total comprometido** | **~1,1 GB** | **~2,2 GB** | |
| Libre / page cache | ~3,0 GB | ~1,9 GB | Swap de 4 GB solo como contingencia |

*Valores estimados; se miden en el servidor en la primera semana (ver [06](06-pruebas-y-aceptacion.md)).*

## 5. Flujo de actualización de datos

Los datos viajan **dentro de la imagen** (decisión del 2026-11-14):

```text
[pipeline ML_NasaSpaceApp]  genera serving_api/<versión>/ y lo valida
   │
   ▼
PR en este repo que reemplaza data/current/
   │  CI: pruebas + imagen + /health con el data_version de data/current/metadata.json
   ▼
merge a main ─► imagen nueva en GHCR ─► Dokploy la despliega
```

El paso a paso está en [05 §5 bis](05-despliegue.md#5-bis-actualizar-los-datos). Para volver a una versión anterior de los datos se despliega la imagen `:<sha>` anterior.

`POST /api/v1/admin/reload` y la revisión de `current` cada 5 s siguen en el código, pero solo actúan si alguien monta otra carpeta de datos a propósito.

## 6. CI/CD de la aplicación

```text
git push (main) ─► GitHub Actions ─► docker build ─► ghcr.io/smlopezsm/firehistory-api:<sha> y :latest
                                                   └► webhook Dokploy ─► pull + restart (< 10 s)
```

Regla: **nada se compila en el VPS** (ni `pip install` ni `npm run build`).

## 7. Seguridad y resiliencia

| Medida | Detalle |
|---|---|
| Firewall (UFW) | Solo 22, 80 y 443 |
| SSH | Solo con clave pública; sin login de root por contraseña |
| Datos | Dentro de la imagen, copiados como root: el usuario `app` solo puede leerlos |
| Secretos | `MAP_KEY` de FIRMS en el pipeline. En este repo, `DOKPLOY_WEBHOOK_URL` en *GitHub Secrets*. `RELOAD_TOKEN` y `CORS_ORIGINS` como variables de entorno en Dokploy |
| Límites | Contenedor API 1,5 GB / frontend 256 MB; tiempo máximo por consulta 10 s |
| Swap | 4 GB, `vm.swappiness=10` |
| Backups | Cada imagen `:<sha>` de GHCR trae su versión de datos; el historial de `data/current/` está en git |
