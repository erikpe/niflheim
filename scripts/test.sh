#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

cd "$repo_root"

echo "[1/2] Running Python tests (pytest)..."
pytest -q

echo "[2/2] Running runtime C harnesses..."
make -C runtime test-all

echo "All tests passed."
