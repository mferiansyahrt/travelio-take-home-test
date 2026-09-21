# ── Base: pinned runtime dependencies + application code ──────────────────
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/source

WORKDIR /app

# Dependencies before code, so code changes don't invalidate this layer.
# --no-deps installs exactly the lock file; `pip check` fails the build if the lock is incomplete.
COPY requirements.txt ./
RUN pip install --no-deps -r requirements.txt && pip check

COPY source/ ./source/


# ── Test: dev dependencies + test suite (docker compose --profile test run --rm tests) ──
FROM base AS test

COPY requirements-dev.txt pytest.ini ./
RUN pip install --no-deps -r requirements-dev.txt && pip check

COPY tests/ ./tests/

CMD ["pytest", "-q"]


# ── Runtime: non-root user, healthcheck, service runner ───────────────────
FROM base AS runtime

RUN useradd --create-home --uid 10001 appuser
USER appuser

WORKDIR /app/source
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8000/health', headers={'User-Agent': 'docker-healthcheck'}), timeout=2)"]

CMD ["python", "-m", "services.run_swagger_service", "--host", "0.0.0.0", "--port", "8000"]
