# Control API 运行镜像。源码以包名 `app` 安装，工作目录保留 alembic.ini。
FROM python:3.12-slim

WORKDIR /workspace

COPY pyproject.toml alembic.ini ./
COPY migrations ./migrations
COPY app ./app

RUN pip install --no-cache-dir .

ENV PYTHONPATH=/workspace
EXPOSE 8600
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8600"]
