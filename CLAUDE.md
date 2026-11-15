# FireHistoryInterfaceAPI · guía para agentes

API REST (FastAPI + DuckDB) del calendario armonizado de focos MODIS × VIIRS para Argentina.

- **Fuente de verdad:** `docs/01` a `docs/06`. No contradecirlos; si algo falta o es ambiguo, preguntar.
- **Dónde estamos y qué sigue:** [docs/08-proximos-pasos.md](docs/08-proximos-pasos.md) (estado, decisiones tomadas y pendientes).
- **Ramas:** una feature por vez; cada rama sale de `main` actualizado y cada PR va **contra `main`** (nunca apilar).
- **Antes de cada PR:** `ruff check . && ruff format --check . && mypy app && pytest -q`.
- **Reglas fijas:** sin dependencias de ML; `null` nunca es 0; todo estimado lleva `estado`, `minimo`, `maximo` y `confianza`; NOAA-21 nunca suma; el factor se aplica a totales mensuales por provincia; textos y claves en español (claves sin tildes).
- **Datos:** la versión publicada va en `data/current/` (copiada de `serving_api/<versión>/` del pipeline) y se empaqueta en la imagen. Los demás Parquet solo van en `tests/fixtures/`. **Nunca subir secretos.**
