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
    io_c = root / "runtime" / "src" / "io.c"
    str_c = root / "runtime" / "src" / "str.c"
    box_c = root / "runtime" / "src" / "box.c"
    vec_c = root / "runtime" / "src" / "vec.c"

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
            str(io_c),
            str(str_c),
            str(box_c),
            str(vec_c),
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


def test_e2e_while_break_and_continue_links_and_runs() -> None:
    source = """
fn main() -> i64 {
    var i: i64 = 0;
    var sum: i64 = 0;
    while i < 10 {
        i = i + 1;
        if i == 5 {
            continue;
        }
        if i == 8 {
            break;
        }
        sum = sum + i;
    }
    return sum;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 23


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


def test_e2e_constructor_call_lowering_links_and_runs() -> None:
    source = """
class Counter {
    value: i64;
}

fn main() -> i64 {
    var c: Counter = Counter(9);
    if c == null {
        return 1;
    }
    return 9;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 9


def test_e2e_builtin_box_i64_constructor_and_value_read() -> None:
    source = """
fn main() -> i64 {
    var b: BoxI64 = BoxI64(33);
    var v: i64 = b.value;
    return v;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 33


def test_e2e_str_literal_and_indexing_links_and_runs() -> None:
    source = """
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;

class Str {
    fn get_u8(index: i64) -> u8 {
        return rt_str_get_u8(__self, index);
    }
}

fn main() -> i64 {
    var s: Str = "AB\\n";
    var b: u8 = s[1];
    return (i64)b;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 66


def test_e2e_str_hex_escape_links_and_runs() -> None:
    source = """
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;

class Str {
    fn get_u8(index: i64) -> u8 {
        return rt_str_get_u8(__self, index);
    }
}

fn main() -> i64 {
    var s: Str = "\\x41\\x42";
    var b: u8 = s[0];
    return (i64)b;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 65


def test_e2e_str_slice_syntax_links_and_runs() -> None:
    source = """
extern fn rt_str_len(value: Str) -> i64;
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;
extern fn rt_str_slice(value: Str, begin: i64, end: i64) -> Str;

class Str {
    fn len() -> i64 {
        return rt_str_len(__self);
    }

    fn get_u8(index: i64) -> u8 {
        return rt_str_get_u8(__self, index);
    }

    fn slice(begin: i64, end: i64) -> Str {
        return rt_str_slice(__self, begin, end);
    }
}

fn main() -> i64 {
    var v: Str = "Hello world!";
    var s1: Str = v[3:5];
    var s2: Str = v[:7];
    var s3: Str = v[4:];
    var s4: Str = v[:];
    var c1: u8 = s1[0];
    var c2: u8 = s2[6];
    var c3: u8 = s3[0];
    var c4: u8 = s4[11];
    return (i64)c1 + (i64)c2 + (i64)c3 + (i64)c4;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == ((108 + 119 + 111 + 33) & 0xFF)


def test_e2e_str_negative_index_and_slice_links_and_runs() -> None:
    source = """
extern fn rt_str_len(value: Str) -> i64;
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;
extern fn rt_str_slice(value: Str, begin: i64, end: i64) -> Str;

class Str {
    fn len() -> i64 {
        return rt_str_len(__self);
    }

    fn get_u8(index: i64) -> u8 {
        var resolved: i64 = index;
        if resolved < 0 {
            resolved = __self.len() + resolved;
        }
        return rt_str_get_u8(__self, resolved);
    }

    fn slice(begin: i64, end: i64) -> Str {
        var resolved_begin: i64 = begin;
        if resolved_begin < 0 {
            resolved_begin = __self.len() + resolved_begin;
        }

        var resolved_end: i64 = end;
        if resolved_end < 0 {
            resolved_end = __self.len() + resolved_end;
        }

        return rt_str_slice(__self, resolved_begin, resolved_end);
    }
}

fn main() -> i64 {
    var v: Str = "Hello world!";
    var c1: u8 = v[-1];
    var c2: u8 = v[-3];
    var s1: Str = v[:-1];
    var s2: Str = v[-8:8];
    var c3: u8 = s1[-1];
    var c4: u8 = s2[2];
    return (i64)c1 + (i64)c2 + (i64)c3 + (i64)c4;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == ((33 + 108 + 100 + 119) & 0xFF)


def test_e2e_str_negative_and_positive_oob_index_panics() -> None:
    source = """
extern fn rt_str_len(value: Str) -> i64;
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;

class Str {
    fn len() -> i64 {
        return rt_str_len(__self);
    }

    fn get_u8(index: i64) -> u8 {
        var resolved: i64 = index;
        if resolved < 0 {
            resolved = __self.len() + resolved;
        }
        return rt_str_get_u8(__self, resolved);
    }
}

fn main() -> i64 {
    var v: Str = "Hello world!";
    var c1: u8 = v[-15];
    var c2: u8 = v[15];
    return (i64)c1 + (i64)c2;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code != 0


def test_e2e_str_negative_and_positive_oob_slice_panics() -> None:
    source = """
extern fn rt_str_len(value: Str) -> i64;
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;
extern fn rt_str_slice(value: Str, begin: i64, end: i64) -> Str;

class Str {
    fn len() -> i64 {
        return rt_str_len(__self);
    }

    fn get_u8(index: i64) -> u8 {
        var resolved: i64 = index;
        if resolved < 0 {
            resolved = __self.len() + resolved;
        }
        return rt_str_get_u8(__self, resolved);
    }

    fn slice(begin: i64, end: i64) -> Str {
        var resolved_begin: i64 = begin;
        if resolved_begin < 0 {
            resolved_begin = __self.len() + resolved_begin;
        }

        var resolved_end: i64 = end;
        if resolved_end < 0 {
            resolved_end = __self.len() + resolved_end;
        }

        return rt_str_slice(__self, resolved_begin, resolved_end);
    }
}

fn main() -> i64 {
    var v: Str = "Hello world!";
    var s1: Str = v[-15:5];
    var s2: Str = v[15:20];
    return (i64)s1[0] + (i64)s2[0];
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code != 0


def test_e2e_vec_baseline_ops_links_and_runs() -> None:
    source = """
fn main() -> i64 {
    var v: Vec = Vec();
    v.push(BoxI64(10));
    v.push(BoxI64(20));
    var first: Obj = v.get(0);
    v.set(1, first);

    var n: i64 = v.len();
    if n != 2 {
        return 1;
    }

    var via_index: Obj = v[1];
    if via_index == null {
        return 2;
    }
    return 0;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 0


def test_e2e_vec_inline_boxed_args_survive_runtime_gc_links_and_runs() -> None:
    source = """
extern fn rt_box_bool_get(box_obj: Obj) -> bool;

fn main() -> i64 {
    var max: i64 = 2000;
    var flags: Vec = Vec();
    var i: i64 = 0;

    while i <= max {
        flags.push(BoxBool(true));
        i = i + 1;
    }

    flags.set(0, BoxBool(false));
    flags.set(1, BoxBool(false));

    var p: i64 = 2;
    while p <= max / p {
        if rt_box_bool_get(flags.get(p)) {
            var m: i64 = p * p;
            while m <= max {
                flags.set(m, BoxBool(false));
                m = m + p;
            }
        }
        p = p + 1;
    }

    var primes: Vec = Vec();
    var n: i64 = 2;
    while n <= max {
        if rt_box_bool_get(flags.get(n)) {
            primes.push(BoxI64(n));
        }
        n = n + 1;
    }

    if primes.len() != 303 {
        return 1;
    }
    return 0;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 0


def test_e2e_vec_cast_receiver_field_value_links_and_runs() -> None:
    source = """
fn main() -> i64 {
    var v: Vec = Vec();
    v.push(BoxI64(41));
    v.push(BoxI64(1));
    return ((BoxI64)v.get(0)).value + ((BoxI64)v.get(1)).value;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 42


def test_e2e_double_call_and_return_abi_links_and_runs() -> None:
    source = """
fn add(a: double, b: double) -> double {
    return a + b;
}

fn main() -> i64 {
    var x: double = add(1.25, 2.75);
    if x > 3.5 {
        return 0;
    }
    return 1;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 0


def test_e2e_boxdouble_value_read_links_and_runs() -> None:
    source = """
fn main() -> i64 {
    var b: BoxDouble = BoxDouble(5.5);
    var d: double = b.value;
    if d >= 5.5 {
        return 0;
    }
    return 1;
}
"""

    exit_code = _compile_and_run(source)
    assert exit_code == 0
