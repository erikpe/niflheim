#!/usr/bin/env sh
set -eu

if [ "$#" -lt 3 ]; then
    echo "usage: run_negative_driver.sh <label> <binary> <case>|<case::expected> ..." >&2
    exit 2
fi

label=$1
bin=$2
shift 2

for spec in "$@"; do
    case_name=${spec%%::*}
    expected=""
    if [ "$case_name" != "$spec" ]; then
        expected=${spec#*::}
    fi

    set +e
    out=$($bin "$case_name" 2>&1 >/dev/null)
    rc=$?
    set -e

    if [ "$rc" -eq 0 ]; then
        echo "$label[$case_name]: expected failure but process exited successfully"
        exit 1
    fi

    if [ -n "$expected" ]; then
        echo "$out" | grep -Fq "$expected" || {
            echo "$label[$case_name]: expected panic message not found"
            exit 1
        }
    fi

    echo "$label[$case_name]: ok (failed as expected)"
done
