#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

cd "$repo_root"

echo "[1/6] Running Python tests (pytest)..."
pytest

echo "[2/6] Running golden tests..."
./scripts/golden.sh

echo "[3/6] Running runtime GC stress harness..."
make -C runtime test

echo "[4/6] Running runtime roots positive harness..."
make -C runtime test-positive

echo "[5/6] Running runtime roots negative harness (driver)..."
make -C runtime test-negative

echo "[6/6] Running runtime array harnesses (positive + negative driver)..."
make -C runtime test-array
make -C runtime test-array-negative

echo "All tests passed."
