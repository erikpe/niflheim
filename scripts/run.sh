#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <input.nif> [output-executable] [build-args...] [-- <program-args...>]" >&2
  echo "Examples:" >&2
  echo "  $0 samples/arithmetic_loop.nif" >&2
  echo "  $0 samples/arithmetic_loop.nif build/loopy" >&2
  echo "  $0 samples/arithmetic_loop.nif --log-level info -v" >&2
  echo "  $0 samples/arithmetic_loop.nif build/loopy -- arg1 arg2" >&2
  echo "  $0 samples/arithmetic_loop.nif build/loopy --log-level info -- arg1 arg2" >&2
  exit 1
fi

input="$1"
shift

output=""
if [[ $# -gt 0 && "$1" != "--" && "$1" != -* ]]; then
  output="$1"
  shift
else
  base_name="$(basename "$input" .nif)"
  output="build/$base_name"
fi

build_args=()
while [[ $# -gt 0 && "$1" != "--" ]]; do
  build_args+=("$1")
  shift
done

if [[ $# -gt 0 && "$1" == "--" ]]; then
  shift
fi

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

"$script_dir/build.sh" "$input" "$output" "${build_args[@]}"

set +e
"$repo_root/$output" "$@"
run_exit=$?
set -e

echo "RUN_EXIT:$run_exit"
exit "$run_exit"
