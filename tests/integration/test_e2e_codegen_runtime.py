from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

from compiler.codegen import emit_asm
from compiler.lexer import lex
from compiler.parser import parse


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _compile_and_run(source: str) -> int:
    cc = shutil.which("cc")
    if cc is None:
        pytest.skip("C compiler 'cc' is required for end-to-end compile+run tests")

    root = _repo_root()
    runtime_include = root / "runtime" / "include"
    runtime_c = root / "runtime" / "src" / "runtime.c"
    gc_c = root / "runtime" / "src" / "gc.c"

    module = parse(lex(source, source_path="tests/e2e_input.nif"))
    asm = emit_asm(module)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        asm_path = tmp / "program.s"
        exe_path = tmp / "program"

        asm_path.write_text(asm, encoding="utf-8")

        compile_cmd = [
            cc,
            "-std=c11",
            "-I",
            str(runtime_include),
            str(runtime_c),
            str(gc_c),
            str(asm_path),
            "-o",
            str(exe_path),
        ]
        subprocess.run(compile_cmd, check=True, capture_output=True, text=True)

        run = subprocess.run([str(exe_path)], check=False)
        return run.returncode


def test_e2e_arithmetic_control_flow_exit_code() -> None:
    source = """
fn main() -> i64 {
    var i: i64 = 0;
    var acc: i64 = 0;
    while i < 5 {
        acc = acc + 3;
        i = i + 1;
    }
    if acc == 15 {
        return 15;
    } else {
        return 1;
    }
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 15


def test_e2e_function_calls_and_argument_passing() -> None:
    source = """
fn add3(a: i64, b: i64, c: i64) -> i64 {
    return a + b + c;
}

fn main() -> i64 {
    return add3(7, 8, 9);
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 24


def test_e2e_reference_cast_path_links_and_runs() -> None:
    source = """
fn main() -> i64 {
    var o: Obj = null;
    var p: Obj = (Obj)o;
    if p == null {
        return 5;
    }
    return 1;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 5


def test_e2e_method_call_lowering_links_and_runs() -> None:
    source = """
class Counter {
    fn id(delta: i64) -> i64 {
        return delta;
    }
}

fn main() -> i64 {
    var c: Counter = null;
    return c.id(13);
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 13
