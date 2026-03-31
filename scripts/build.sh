#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <input.nif> [output-executable] [--] [nifc-args...]" >&2
  echo "Examples:" >&2
  echo "  $0 samples/arithmetic_loop.nif" >&2
  echo "  $0 samples/arithmetic_loop.nif build/loopy" >&2
  echo "  $0 samples/arithmetic_loop.nif -- --log-level info -v" >&2
  echo "  $0 samples/arithmetic_loop.nif build/loopy --print-asm" >&2
  echo "  NIF_PROFILE_BUILD=1 $0 samples/arithmetic_loop.nif build/loopy_profile" >&2
  exit 1
fi

input="$1"
shift

if [[ $# -gt 0 && "$1" != "--" && "$1" != -* ]]; then
  output="$1"
  shift
else
  base_name="$(basename "$input" .nif)"
  output="build/$base_name"
fi

if [[ $# -gt 0 && "$1" == "--" ]]; then
  shift
fi

cli_nifc_args=("$@")

if [[ ! -f "$input" ]]; then
  echo "build.sh: input file not found: $input" >&2
  exit 1
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

output_dir="$(dirname "$output")"
mkdir -p "$output_dir"

asm_out="${output}.s"

extra_nifc_args=()
if [[ -n "${NIFC_BUILD_ARGS:-}" ]]; then
  read -r -a extra_nifc_args <<< "$NIFC_BUILD_ARGS"
fi

gcc_args=(-O2 -std=c11)
if [[ "${NIF_PROFILE_BUILD:-0}" != "0" ]]; then
  gcc_args+=(-g -fno-omit-frame-pointer)
fi
if [[ -n "${NIF_GCC_ARGS:-}" ]]; then
  read -r -a extra_gcc_args <<< "$NIF_GCC_ARGS"
  gcc_args+=("${extra_gcc_args[@]}")
fi

ld_args=()
if [[ -n "${NIF_LD_ARGS:-}" ]]; then
  read -r -a extra_ld_args <<< "$NIF_LD_ARGS"
  ld_args+=("${extra_ld_args[@]}")
fi

python3 -m compiler.main "$input" -o "$asm_out" --project-root "$repo_root" "${extra_nifc_args[@]}" "${cli_nifc_args[@]}"

gcc \
  "${gcc_args[@]}" \
  -I "$repo_root/runtime/include" \
  "$repo_root/runtime/src/runtime.c" \
  "$repo_root/runtime/src/gc.c" \
  "$repo_root/runtime/src/gc_trace.c" \
  "$repo_root/runtime/src/gc_tracked_set.c" \
  "$repo_root/runtime/src/io.c" \
  "$repo_root/runtime/src/array.c" \
  "$repo_root/runtime/src/panic.c" \
  "$asm_out" \
  "${ld_args[@]}" \
  -o "$output"

echo "Built executable: $output"
echo "Generated assembly: $asm_out"
