from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import install_std_modules


STD_IO_MODULE_SOURCE = """
import std.str;

extern fn rt_write_u8_array(value: u8[]) -> unit;

fn print(value: Str) -> unit {
    var len: u64 = value.len();
    var out: u8[] = u8[](len + 1u);

    var i: u64 = 0u;
    while i < len {
        out[(i64)i] = value[(i64)i];
        i = i + 1u;
    }

    out[(i64)len] = '\\n';
    rt_write_u8_array(out);
}

export fn println_i64(value: i64) -> unit {
    print(Str.from_i64(value));
}

export fn println_u64(value: u64) -> unit {
    print(Str.from_u64(value));
}

export fn println_u8(value: u8) -> unit {
    print(Str.from_u8(value));
}

export fn println_bool(value: bool) -> unit {
    print(Str.from_bool(value));
}
"""


MINIMAL_STR_MODULE_SOURCE = """
export class Str {
    _bytes: u8[];

    static fn from_u8_array(value: u8[]) -> Str {
        return Str(value);
    }
}
"""


STD_ERROR_MODULE_SOURCE = """
import std.str;

extern fn rt_panic_null_term_array(msg: u8[]) -> unit;

export fn panic(msg: Str) -> unit {
    var msg_bytes: u8[] = msg._bytes;
    var length: i64 = (i64)msg_bytes.len();
    var msg_arr: u8[] = u8[]((u64)length + 1u);

    var i: i64 = 0;
    while i < length {
        msg_arr[i] = msg_bytes[i];
        i = i + 1;
    }
    msg_arr[length] = 0u8;

    rt_panic_null_term_array(msg_arr);
}
"""


def install_std_io_fixture(project_root: Path) -> None:
    install_std_modules(
        project_root,
        ["str", "object", "error", "vec"],
        overrides={"std/io.nif": STD_IO_MODULE_SOURCE},
    )


def install_std_error_fixture(project_root: Path) -> None:
    install_std_modules(
        project_root,
        ["str"],
        overrides={
            "std/str.nif": MINIMAL_STR_MODULE_SOURCE,
            "std/error.nif": STD_ERROR_MODULE_SOURCE,
        },
    )


def make_std_io_entry(call_lines: str) -> str:
    return f"""
    import std.io;

    fn main() -> i64 {{
        {call_lines.strip()}
        return 0;
    }}
    """


def _nif_string_literal(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("\"", "\\\"").replace("\n", "\\n")
    return f'"{escaped}"'


def make_std_error_entry(message: str) -> str:
    return f"""
    import std.error;

    fn main() -> i64 {{
        panic({_nif_string_literal(message)});
        return 0;
    }}
    """