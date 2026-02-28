#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "Usage: $0 <input.nif> [output-executable]" >&2
  echo "Examples:" >&2
  echo "  $0 samples/arithmetic_loop.nif" >&2
  echo "  $0 samples/arithmetic_loop.nif build/loopy" >&2
  exit 1
fi

input="$1"

if [[ $# -eq 2 ]]; then
  output="$2"
else
  base_name="$(basename "$input" .nif)"
  output="build/$base_name"
fi

if [[ ! -f "$input" ]]; then
  echo "build.sh: input file not found: $input" >&2
  exit 1
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

output_dir="$(dirname "$output")"
mkdir -p "$output_dir"

asm_out="${output}.s"

python3 -m compiler.main "$input" -o "$asm_out" --project-root "$repo_root"

cc \
  -std=c11 \
  -I "$repo_root/runtime/include" \
  "$repo_root/runtime/src/runtime.c" \
  "$repo_root/runtime/src/gc.c" \
  "$repo_root/runtime/src/io.c" \
  "$repo_root/runtime/src/str.c" \
  "$repo_root/runtime/src/strbuf.c" \
  "$repo_root/runtime/src/array.c" \
  "$asm_out" \
  -o "$output"

echo "Built executable: $output"
echo "Generated assembly: $asm_out"
