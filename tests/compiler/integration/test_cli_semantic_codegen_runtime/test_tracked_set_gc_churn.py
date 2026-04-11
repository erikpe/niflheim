from __future__ import annotations

from pathlib import Path

import pytest

from tests.compiler.integration.helpers import compile_and_run, write


SOURCE = """
extern fn rt_gc_collect() -> unit;

class Box {
    value: i64;
}

fn expected_value_before_reinsert(round: i64, slot_index: i64) -> i64 {
    if round == 0 {
        return slot_index + 1;
    }
    return ((round - 1) * 1000) + slot_index + 1;
}

fn replacement_value(round: i64, slot_index: i64) -> i64 {
    return (round * 1000) + slot_index + 1;
}

fn seed_active(values: Box[]) -> unit {
    var slot: u64 = 0u;
    while slot < 16u {
        values[(i64)slot] = Box((i64)slot + 1);
        slot = slot + 1u;
    }
}

fn allocate_short_lived_garbage(base: i64) -> unit {
    var i: u64 = 0u;
    while i < 24u {
        var temp: Box = Box(base + (i64)i);
        var alias: Box = temp;

        if alias == null {
            return;
        }

        temp = null;
        alias = null;
        i = i + 1u;
    }
}

fn churn_round(values: Box[], round: i64) -> i64 {
    var slot: u64 = 0u;
    while slot < 16u {
        var index: i64 = (i64)slot;
        var alias: Box = values[index];
        rt_gc_collect();

        if alias == null {
            return 10;
        }
        if alias.value != expected_value_before_reinsert(round, index) {
            return 11;
        }

        values[index] = null;
        rt_gc_collect();

        if alias == null {
            return 12;
        }
        if alias.value != expected_value_before_reinsert(round, index) {
            return 13;
        }

        allocate_short_lived_garbage((round * 10000) + (index * 100));
        rt_gc_collect();

        var replacement: Box = Box(replacement_value(round, index));
        values[index] = replacement;
        rt_gc_collect();

        if values[index] == null {
            return 14;
        }
        if values[index].value != replacement_value(round, index) {
            return 15;
        }

        alias = null;
        replacement = null;
        slot = slot + 1u;
    }

    return 0;
}

fn checksum(values: Box[]) -> i64 {
    var slot: u64 = 0u;
    var total: i64 = 0;

    while slot < 16u {
        var current: Box = values[(i64)slot];
        rt_gc_collect();

        if current == null {
            return -1;
        }

        total = total + current.value;
        slot = slot + 1u;
    }

    return total;
}

fn expected_checksum(last_round: i64) -> i64 {
    var slot: u64 = 0u;
    var total: i64 = 0;

    while slot < 16u {
        total = total + replacement_value(last_round, (i64)slot);
        slot = slot + 1u;
    }

    return total;
}

fn main() -> i64 {
    var active: Box[] = Box[](16u);
    seed_active(active);

    var round: i64 = 0;
    while round < 24 {
        var result: i64 = churn_round(active, round);
        if result != 0 {
            return result;
        }
        round = round + 1;
    }

    rt_gc_collect();

    var total: i64 = checksum(active);
    if total < 0 {
        return 20;
    }
    if total != expected_checksum(23) {
        return 21;
    }

    return 0;
}
"""


@pytest.mark.parametrize(
    "extra_args",
    [
        [],
        ["--omit-runtime-trace"],
    ],
    ids=["default", "no_trace"],
)
def test_cli_semantic_codegen_runs_tracked_set_gc_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extra_args: list[str]
) -> None:
    entry = tmp_path / "main.nif"
    write(entry, SOURCE)

    run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "out.s",
        exe_path=tmp_path / "program",
        extra_args=extra_args,
    )

    assert run.returncode == 0, run.stderr