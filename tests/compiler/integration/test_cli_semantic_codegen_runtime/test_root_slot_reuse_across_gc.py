from __future__ import annotations

from pathlib import Path

import pytest

from tests.compiler.integration.helpers import compile_and_run, write


SOURCE = """
extern fn rt_gc_collect() -> unit;

class Box {
    value: i64;
}

fn choose_last(left: Box, right: Box) -> Box {
    rt_gc_collect();
    return right;
}

fn shared_slot_alias_survives_forced_gc() -> i64 {
    var first: Box = Box(41);
    var middle: Box = Box(99);
    var last: Box = null;

    rt_gc_collect();
    last = first;
    rt_gc_collect();

    var kept: Box = choose_last(middle, last);
    if kept == null {
        return 1;
    }
    if kept.value != 41 {
        return 2;
    }
    if middle == null {
        return 3;
    }
    if middle.value != 99 {
        return 4;
    }

    rt_gc_collect();
    if last == null {
        return 5;
    }
    if last.value != 41 {
        return 6;
    }

    return 0;
}

fn repeated_shared_slot_reuse() -> i64 {
    var i: i64 = 0;
    while i < 300 {
        var first: Box = Box(i);
        var middle: Box = Box(1000 + i);
        var last: Box = null;

        rt_gc_collect();
        last = first;
        rt_gc_collect();

        var kept: Box = choose_last(middle, last);
        if kept == null || kept.value != i {
            return 100 + i;
        }

        rt_gc_collect();
        if last == null || last.value != i {
            return 1000 + i;
        }

        i = i + 1;
    }

    return 0;
}

fn main() -> i64 {
    var first_result: i64 = shared_slot_alias_survives_forced_gc();
    if first_result != 0 {
        return first_result;
    }
    return repeated_shared_slot_reuse();
}
"""


@pytest.mark.parametrize("extra_args", [["--omit-runtime-trace"], ["--omit-runtime-trace", "--skip-optimize"]])
def test_cli_semantic_codegen_runs_root_slot_reuse_across_forced_gc(
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