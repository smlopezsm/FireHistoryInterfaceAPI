# 07 · Trabajo con GitHub Spec Kit (Spec-Driven Development)

Usamos **[Spec Kit](https://github.com/github/spec-kit)** para que las especificaciones guíen la implementación con agentes de IA.

## 1. Instalación (una vez por computadora)

```bash
# uv (gestor de Python) si no está instalado
curl -LsSf https://astral.sh/uv/install.sh | sh

# Specify CLI: reemplazar vX.Y.Z por el último tag de https://github.com/github/spec-kit/releases
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git@vX.Y.Z
specify version
```

## 2. Inicialización en este repo

```bash
cd FireHistoryInterfaceAPI
specify init --here --integration claude     # en versiones anteriores: --ai claude
```

Esto crea `.specify/` (plantillas y scripts) y los comandos del agente. **Se commitea al repo.**

## 3. Flujo

| Paso | Comando en el agente | Entrada sugerida |
|---|---|---|
| 1 | `/speckit.constitution` | Texto de la §4 |
| 2 | `/speckit.specify` | Texto de la §5 (una feature por vez) |
| 3 | `/speckit.plan` | "Usar el stack y los contratos de docs/01–05" |
| 4 | `/speckit.tasks` | — |
| 5 | `/speckit.implement` | — |

**Regla:** los contratos de `docs/02` y `docs/03` son la **fuente de verdad**. Si una spec los contradice, primero se actualiza el documento por PR.

## 4. Texto para `/speckit.constitution`

> Principios de FireHistoryInterfaceAPI:
> 1. **Contratos primero:** respetar exactamente `docs/02-contratos-de-datos.md` y `docs/03-contratos-api.md`; todo cambio de contrato se hace primero en la documentación.
> 2. **Honestidad del dato:** nunca devolver 0 cuando no hay dato (usar `null`); toda estimación lleva `estado`, rango y `confianza`.
> 3. **Sin modelos en el servidor:** la armonización es una tabla de factores; prohibido agregar dependencias de ML en la imagen.
> 4. **Liviano:** debe correr en 1,5 GB de RAM con 2 workers; DuckDB en solo lectura con límite de memoria.
> 5. **Probado:** toda lógica de armonización tiene pruebas unitarias con fixtures (U1–U10); los contratos se validan en CI.
> 6. **Reproducible:** cada respuesta incluye `data_version`; la imagen se construye solo en CI.
> 7. **Seguro por defecto:** CORS restringido, secretos solo en variables de entorno, volumen de datos read-only.

## 5. Features para `/speckit.specify` (en orden)

| # | Feature | Texto inicial |
|---|---|---|
| F1 | Esqueleto y salud | "Crear la app FastAPI con configuración por entorno, conexión DuckDB read-only por worker, `/api/v1/health` y `/api/v1/metadata` según docs/03, Dockerfile según docs/05 y CI que construye y publica en GHCR." |
| F2 | Provincias y zonas | "Implementar `/provincias` y la resolución de zona (provincia_id, bbox o polígono GeoJSON) a un conjunto de celdas por centroide, con las validaciones y los errores de docs/03." |
| F3 | Calendario armonizado | "Implementar `/calendario` y `/serie` aplicando el algoritmo de docs/04 (referencia por fecha, satélite operativo, factor provincia × mes, rangos, confianza), con las pruebas U1–U9." |
| F4 | Anomalía | "Implementar `/anomalia` según docs/03 §anomalía y docs/04 §6, con la prueba U10." |
| F5 | Mapa | "Implementar `/mapa/celdas` (polígonos, límite de 20.000) y `/mapa/industriales`." |
| F6 | Descargas | "Implementar `/descargas/focos.csv` y `/descargas/calendario.csv` en streaming, con los límites y cabeceras de docs/03." |
| F7 | Recarga de datos | "Implementar `POST /admin/reload` con token y el cambio atómico de `current`." |
