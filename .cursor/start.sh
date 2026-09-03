#!/usr/bin/env bash
# Cloud Agent start：每次开机把本地 PostgreSQL 拉起并把控制面数据库迁到最新。
# 必须可重复执行（容忍已启动）、就绪后返回，不常驻前台。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

# 1) 启动 PostgreSQL 集群（容忍已运行）
sudo pg_ctlcluster 16 main start 2>/dev/null || true

# 2) 等待就绪
for _ in $(seq 1 30); do
  if sudo -u postgres pg_isready -q; then break; fi
  sleep 1
done

# 3) 幂等确保开发角色与数据库存在（口令仅本地开发用，与 deploy/compose 一致）
sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='siq_as'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE ROLE siq_as LOGIN PASSWORD 'siq_as_dev';"
sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='siq_as'" | grep -q 1 \
  || sudo -u postgres psql -c "CREATE DATABASE siq_as OWNER siq_as;"

# 4) 迁移到最新（干净库可全量回放；已在最新则为空操作）
cd "$REPO_ROOT/apps/control-api"
export SIQ_AS_DEV=1
export SIQ_AS_DATABASE_URL="postgresql+psycopg://siq_as:siq_as_dev@127.0.0.1:5432/siq_as"
uv run --frozen alembic upgrade head

echo "start.sh: PostgreSQL ready and migrations applied"
