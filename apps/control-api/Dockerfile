# Control API runtime image — dependencies MUST come from uv.lock (DEV17-A / M-P3).
# Build: docker build -t siq-control-api -f apps/control-api/Dockerfile apps/control-api
#
# Builder installs with `uv sync --locked --no-dev`. Do not `pip install .` from
# an unlocked resolver. Base images pinned by digest (DEV17-D).

FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.7@sha256:240fb85ab0f263ef12f492d8476aa3a2e4e1e333f7d67fbdd923d00a506a516a /uv /uvx /bin/

WORKDIR /workspace
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/workspace/.venv

# Lock first for better layer reuse; project sources after.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN uv sync --locked --no-dev

FROM python:3.12-slim-bookworm@sha256:782412e85d0f0984994c290652577d4018aff08145c85b262bb63dc0c7522254 AS runtime

WORKDIR /workspace
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin appuser

COPY --from=builder /workspace/.venv /workspace/.venv
COPY --from=builder /workspace/alembic.ini /workspace/alembic.ini
COPY --from=builder /workspace/migrations /workspace/migrations
COPY --from=builder /workspace/app /workspace/app

ENV PATH="/workspace/.venv/bin:$PATH" \
    PYTHONPATH=/workspace \
    PYTHONDONTWRITEBYTECODE=1

USER appuser
EXPOSE 8600
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
