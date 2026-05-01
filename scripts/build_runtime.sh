#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "$0")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"

if [[ $# -gt 1 ]]; then
	echo "Usage: $0 [output-archive]" >&2
	exit 1
fi

if [[ $# -eq 1 ]]; then
	if [[ "$1" = /* ]]; then
		output_archive="$1"
	else
		output_archive="$repo_root/$1"
	fi
else
	output_archive="$repo_root/runtime/libruntime.a"
fi

mkdir -p "$(dirname "$output_archive")"

make -C "$repo_root/runtime" libruntime.a

default_archive="$repo_root/runtime/libruntime.a"
if [[ "$output_archive" != "$default_archive" ]]; then
	cp "$default_archive" "$output_archive"
fi

echo "Built runtime archive: $output_archive"
