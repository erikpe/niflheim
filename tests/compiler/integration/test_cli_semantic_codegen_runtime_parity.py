from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write


def _run_both_backends(tmp_path: Path, monkeypatch, source: str):
    entry = tmp_path / "main.nif"
    write(entry, source)
    source_run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "source_out.s",
        exe_path=tmp_path / "source_program",
    )
    semantic_run = compile_and_run(
        monkeypatch,
        entry,
        project_root=tmp_path,
        out_path=tmp_path / "semantic_out.s",
        exe_path=tmp_path / "semantic_program",
        extra_args=["--semantic-codegen"],
    )
    return source_run, semantic_run


def test_cli_semantic_codegen_runtime_matches_source_backend_for_calls_and_objects(tmp_path: Path, monkeypatch) -> None:
    source = """
    fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }

    class Math {
        static fn inc(v: i64) -> i64 {
            return v + 1;
        }
    }

    class Box {
        value: i64;

        fn get() -> i64 {
            return __self.value;
        }
    }

    fn main() -> i64 {
        var box: Box = Box(Math.inc(20));
        var f: fn(i64, i64) -> i64 = add;
        if f(box.get(), 21) == 42 {
            return 0;
        }
        return 1;
    }
    """

    source_run, semantic_run = _run_both_backends(tmp_path, monkeypatch, source)

    assert source_run.returncode == 0
    assert semantic_run.returncode == 0
    assert semantic_run.stdout == source_run.stdout
    assert semantic_run.stderr == source_run.stderr


def test_cli_semantic_codegen_runtime_matches_source_backend_for_arrays_and_control_flow(tmp_path: Path, monkeypatch) -> None:
    source = """
    class Box {
        value: i64;
    }

    fn main() -> i64 {
        var values: i64[] = i64[](4u);
        values[0] = 10;
        values[1] = 20;

        var sum: i64 = 0;
        for value in values {
            sum = sum + value;
            if sum > 25 {
                break;
            }
        }

        var box: Box = Box(sum);
        if box.value == 30 {
            return 0;
        }
        return 1;
    }
    """

    source_run, semantic_run = _run_both_backends(tmp_path, monkeypatch, source)

    assert source_run.returncode == 0
    assert semantic_run.returncode == 0
    assert semantic_run.stdout == source_run.stdout
    assert semantic_run.stderr == source_run.stderr


def test_cli_semantic_codegen_runtime_matches_source_backend_for_strings_and_casts(tmp_path: Path, monkeypatch) -> None:
    source = """
    class Str {
        _bytes: u8[];

        static fn from_u8_array(value: u8[]) -> Str {
            return Str(value);
        }

        static fn concat(left: Str, right: Str) -> Str {
            return Str(left._bytes);
        }
    }

    class Person {
        age: i64;
    }

    fn main() -> i64 {
        var msg: Str = "hi" + " there";
        var obj: Obj = (Obj)Person(7);
        var p: Person = (Person)obj;
        if msg == null {
            return 1;
        }
        if p == null {
            return 1;
        }
        return 0;
    }
    """

    source_run, semantic_run = _run_both_backends(tmp_path, monkeypatch, source)

    assert source_run.returncode == 0
    assert semantic_run.returncode == 0
    assert semantic_run.stdout == source_run.stdout
    assert semantic_run.stderr == source_run.stderr