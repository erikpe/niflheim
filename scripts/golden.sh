#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

cd "$repo_root"
NIFC_BUILD_ARGS="${NIFC_BUILD_ARGS:---source-ast-codegen}" python3 tests/golden/runner.py "$@"
