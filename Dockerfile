FROM python:3.15-alpine AS builder

# Copiar el binario de uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Instalar herramientas básicas de compilación en Alpine
RUN apk add --no-cache build-base

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

COPY app ./app


FROM python:3.15-alpine AS runtime

# Actualizar paquetes del sistema
RUN apk upgrade --no-cache

# El servicio no usa sqlite3, bz2, lzma, ctypes, readline, curses ni dbm.
# Quitar el meta-paquete .python-rundeps elimina esas libs opcionales y
# sqlite-libs, cuyas CVEs Alpine 3.24 aún no ha corregido.
RUN apk del .python-rundeps

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Sintaxis de Alpine (busybox) para crear usuario y grupo sin privilegios
RUN addgroup -S app && adduser -S -G app -h /app -H app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8000

STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--timeout-graceful-shutdown", "20", "--no-access-log"]