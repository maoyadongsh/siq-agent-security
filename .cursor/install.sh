#!/usr/bin/env bash
# Cloud Agent install：幂等刷新本仓库开发依赖。
# 语言工具链（Python 3.12 / Node 22 / Go 1.22）由默认基础镜像提供；
# 这里补齐 uv 与 PostgreSQL 两个缺失的系统依赖，并安装各子项目依赖。
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 1) uv（Python 包管理器）——缺失才安装
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# 2) PostgreSQL（本地开发数据库，稳定系统依赖）——缺失才安装
if ! command -v pg_ctlcluster >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib
fi

# 3) Control API Python 依赖：从提交的 uv.lock 安装。
#    --frozen 直接按锁文件安装、不改写锁文件，可容忍与新版 uv/PyPI 索引的次要漂移。
cd "$REPO_ROOT/apps/control-api"
uv sync --dev --frozen

# 4) Web 依赖 + 本地开发环境变量（dev 身份注入）
cd "$REPO_ROOT/apps/web"
npm ci
[ -f .env.local ] || cp .env.example .env.local

# 5) 预热 Edge Agent 与首个 Connector 的 Go 构建缓存（加速首次扫描演示）
cd "$REPO_ROOT/edge/agent" && go build ./...
cd "$REPO_ROOT/connectors/hermes" && go build -o hermes-connector .

echo "install.sh: done"
