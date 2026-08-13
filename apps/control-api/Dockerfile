# 开发镜像（Phase 0）；生产镜像需硬化（非 root、read_only、cap_drop ALL，对齐 siq-platform 对 hub 的做法）
FROM python:3.12-slim

WORKDIR /workspace

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN pip install --no-cache-dir .[dev] || pip install --no-cache-dir -e .
RUN pip install --no-cache-dir psycopg[binary] alembic

EXPOSE 8600
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
