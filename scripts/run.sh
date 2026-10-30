#!/usr/bin/env bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
export URNAS_PROJECT_ROOT="$project_root"
export UV_CACHE_DIR="$project_root/data/cache/uv"
export TMPDIR="$project_root/data/tmp"
export PYTHONDONTWRITEBYTECODE=1
mkdir -p -- "$TMPDIR" "$UV_CACHE_DIR" "$project_root/output/reports" "$project_root/output/logs" "$project_root/data/checkpoints"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
cd -- "$project_root"
exec uv run --frozen auditoria-urnas "$@"
