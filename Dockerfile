# syntax=docker/dockerfile:1
# Imagen de FireHistoryInterfaceAPI (docs/05 §1). Sin compiladores ni dependencias de ML.

FROM python:3.12-slim AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
COPY pyproject.toml README.md ./
RUN pip install --prefix=/install . \
 && find /install -depth \( -name "__pycache__" -o -name "tests" -o -name "*.pyi" \) \
      -path "*site-packages*" -exec rm -rf {} +

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/var/data/current
RUN useradd --uid 10001 --create-home --shell /usr/sbin/nologin app
COPY --from=builder /install /usr/local
WORKDIR /srv
COPY app ./app
# Versión de datos publicada (copiada del pipeline). Solo lectura para el usuario app.
COPY data/current /var/data/current
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health',timeout=4).status==200 else 1)"
CMD ["uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","2","--proxy-headers"]
