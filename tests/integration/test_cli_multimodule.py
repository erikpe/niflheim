from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from compiler.cli import main


def test_cli_uses_program_resolution_for_multimodule_build(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "util.nif").write_text(
        """
export class Box {
    value: i64;
}
""",
        encoding="utf-8",
    )

    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import util;

fn main() -> i64 {
    return 0;
}
""",
        encoding="utf-8",
    )

    out_file = tmp_path / "out.s"
    monkeypatch.setattr(sys, "argv", ["nifc", str(entry), "-o", str(out_file)])

    rc = main()
    assert rc == 0
    assert out_file.exists()


def test_cli_reports_missing_import_module(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import missing.mod;

fn main() -> i64 {
    return 0;
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["nifc", str(entry)])

    rc = main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "Module 'missing.mod' not found" in captured.err


def test_cli_requires_main_i64_entrypoint(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
fn not_main() -> i64 {
    return 0;
}
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["nifc", str(source)])
    rc = main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "Program entrypoint missing" in captured.err


def test_cli_std_io_println_i64_unqualified_call(tmp_path: Path, monkeypatch) -> None:
    cc = shutil.which("cc")
    if cc is None:
        return

    (tmp_path / "std").mkdir(parents=True, exist_ok=True)
    (tmp_path / "std" / "io.nif").write_text(
        """
extern fn rt_println_i64(value: i64) -> unit;
extern fn rt_println_u64(value: u64) -> unit;
extern fn rt_println_u8(value: u8) -> unit;
extern fn rt_println_bool(value: bool) -> unit;

export fn println_i64(value: i64) -> unit {
    rt_println_i64(value);
}

export fn println_u64(value: u64) -> unit {
    rt_println_u64(value);
}

export fn println_u8(value: u8) -> unit {
    rt_println_u8(value);
}

export fn println_bool(value: bool) -> unit {
    rt_println_bool(value);
}
""",
        encoding="utf-8",
    )

    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import std.io;

fn main() -> i64 {
    var x: i64 = 23;
    println_i64(x);
    println_u64((u64)42);
    println_u8((u8)255);
    println_bool(true);
    println_bool(false);
    return 0;
}
""",
        encoding="utf-8",
    )

    out_asm = tmp_path / "out.s"
    monkeypatch.setattr(
        sys,
        "argv",
        ["nifc", str(entry), "--project-root", str(tmp_path), "-o", str(out_asm)],
    )

    rc = main()
    assert rc == 0
    assert out_asm.exists()

    repo_root = Path(__file__).resolve().parents[2]
    runtime_include = repo_root / "runtime" / "include"
    runtime_c = repo_root / "runtime" / "src" / "runtime.c"
    gc_c = repo_root / "runtime" / "src" / "gc.c"
    io_c = repo_root / "runtime" / "src" / "io.c"
    str_c = repo_root / "runtime" / "src" / "str.c"
    box_c = repo_root / "runtime" / "src" / "box.c"
    vec_c = repo_root / "runtime" / "src" / "vec.c"
    exe_path = tmp_path / "program"

    subprocess.run(
        [
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
            str(out_asm),
            "-o",
            str(exe_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    run = subprocess.run([str(exe_path)], check=False, capture_output=True, text=True)
    assert run.returncode == 0
    assert run.stdout == "23\n42\n255\ntrue\nfalse\n"


def test_cli_multimodule_imported_constructor_call_lowers(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "util.nif").write_text(
        """
export class Box {
    value: i64;
}
""",
        encoding="utf-8",
    )

    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import util;

fn main() -> i64 {
    var b: util.Box = util.Box(7);
    if b == null {
        return 1;
    }
    return 0;
}
""",
        encoding="utf-8",
    )

    out_file = tmp_path / "out.s"
    monkeypatch.setattr(
        sys,
        "argv",
        ["nifc", str(entry), "--project-root", str(tmp_path), "-o", str(out_file)],
    )

    rc = main()
    assert rc == 0
    asm = out_file.read_text(encoding="utf-8")
    assert "    call __nif_ctor_Box" in asm


def test_cli_std_io_println_i64_qualified_call(tmp_path: Path, monkeypatch) -> None:
    cc = shutil.which("cc")
    if cc is None:
        return

    (tmp_path / "std").mkdir(parents=True, exist_ok=True)
    (tmp_path / "std" / "io.nif").write_text(
        """
extern fn rt_println_i64(value: i64) -> unit;
extern fn rt_println_u64(value: u64) -> unit;
extern fn rt_println_u8(value: u8) -> unit;
extern fn rt_println_bool(value: bool) -> unit;

export fn println_i64(value: i64) -> unit {
    rt_println_i64(value);
}

export fn println_u64(value: u64) -> unit {
    rt_println_u64(value);
}

export fn println_u8(value: u8) -> unit {
    rt_println_u8(value);
}

export fn println_bool(value: bool) -> unit {
    rt_println_bool(value);
}
""",
        encoding="utf-8",
    )

    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import std.io;

fn main() -> i64 {
    io.println_i64(23);
    io.println_u64((u64)42);
    io.println_u8((u8)255);
    io.println_bool(true);
    io.println_bool(false);
    return 0;
}
""",
        encoding="utf-8",
    )

    out_asm = tmp_path / "out.s"
    monkeypatch.setattr(
        sys,
        "argv",
        ["nifc", str(entry), "--project-root", str(tmp_path), "-o", str(out_asm)],
    )

    rc = main()
    assert rc == 0
    assert out_asm.exists()

    repo_root = Path(__file__).resolve().parents[2]
    runtime_include = repo_root / "runtime" / "include"
    runtime_c = repo_root / "runtime" / "src" / "runtime.c"
    gc_c = repo_root / "runtime" / "src" / "gc.c"
    io_c = repo_root / "runtime" / "src" / "io.c"
    str_c = repo_root / "runtime" / "src" / "str.c"
    box_c = repo_root / "runtime" / "src" / "box.c"
    vec_c = repo_root / "runtime" / "src" / "vec.c"
    exe_path = tmp_path / "program"

    subprocess.run(
        [
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
            str(out_asm),
            "-o",
            str(exe_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    run = subprocess.run([str(exe_path)], check=False, capture_output=True, text=True)
    assert run.returncode == 0
    assert run.stdout == "23\n42\n255\ntrue\nfalse\n"


def test_cli_rejects_extern_main_entrypoint(tmp_path: Path, monkeypatch, capsys) -> None:
    source = tmp_path / "main.nif"
    source.write_text(
        """
extern fn main() -> i64;
""",
        encoding="utf-8",
    )

    monkeypatch.setattr(sys, "argv", ["nifc", str(source)])
    rc = main()
    captured = capsys.readouterr()

    assert rc == 1
    assert "Invalid main signature: expected concrete definition 'fn main() -> i64'" in captured.err


def test_cli_std_error_panic_unqualified_call(tmp_path: Path, monkeypatch) -> None:
    cc = shutil.which("cc")
    if cc is None:
        return

    (tmp_path / "std").mkdir(parents=True, exist_ok=True)
    (tmp_path / "std" / "str.nif").write_text(
        """
extern fn rt_str_len(value: Str) -> i64;
extern fn rt_str_get_u8(value: Str, index: i64) -> u8;
extern fn rt_str_slice(value: Str, begin: i64, end: i64) -> Str;

export class Str {
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
""",
        encoding="utf-8",
    )
    (tmp_path / "std" / "error.nif").write_text(
        """
import std.str;

extern fn rt_panic_str(msg: Str) -> unit;

export fn panic(msg: Str) -> unit {
    rt_panic_str(msg);
}
""",
        encoding="utf-8",
    )

    entry = tmp_path / "main.nif"
    entry.write_text(
        """
import std.error;
import std.str;

fn main() -> i64 {
    panic("Panic at the disco!");
    return 0;
}
""",
        encoding="utf-8",
    )

    out_asm = tmp_path / "out.s"
    monkeypatch.setattr(
        sys,
        "argv",
        ["nifc", str(entry), "--project-root", str(tmp_path), "-o", str(out_asm)],
    )

    rc = main()
    assert rc == 0
    assert out_asm.exists()

    repo_root = Path(__file__).resolve().parents[2]
    runtime_include = repo_root / "runtime" / "include"
    runtime_c = repo_root / "runtime" / "src" / "runtime.c"
    gc_c = repo_root / "runtime" / "src" / "gc.c"
    io_c = repo_root / "runtime" / "src" / "io.c"
    str_c = repo_root / "runtime" / "src" / "str.c"
    box_c = repo_root / "runtime" / "src" / "box.c"
    vec_c = repo_root / "runtime" / "src" / "vec.c"
    exe_path = tmp_path / "program"

    subprocess.run(
        [
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
            str(out_asm),
            "-o",
            str(exe_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    run = subprocess.run([str(exe_path)], check=False, capture_output=True, text=True)
    assert run.returncode != 0
    assert "panic: Panic at the disco!" in run.stderr
