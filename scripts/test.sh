#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

cd "$repo_root"

echo "[1/3] Running Python tests (pytest)..."
pytest

echo "[2/3] Running golden tests..."
./scripts/golden.sh

echo "[3/3] Running runtime C harnesses..."
make -C runtime test-all

echo "All tests passed."
