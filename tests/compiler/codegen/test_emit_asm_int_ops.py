from tests.compiler.codegen.helpers import emit_source_asm


def test_emit_asm_masks_u8_arithmetic_results(tmp_path) -> None:
    source = """
fn f(a: u8, b: u8) -> u8 {
    var x: u8 = a + b;
    var y: u8 = a - b;
    var z: u8 = a * b;
    return z;
}

fn main() -> i64 {
    return (i64)f(7u8, 3u8);
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})

    assert "    add rax, rcx" in asm
    assert "    sub rax, rcx" in asm
    assert "    imul rax, rcx" in asm
    assert asm.count("    and rax, 255") >= 3


def test_emit_asm_emits_bitwise_integer_ops_and_u8_masks(tmp_path) -> None:
    source = """
fn f(a: u8, b: u8, c: i64, d: i64) -> i64 {
    var x: u8 = (a & b) | (a ^ b);
    var y: u8 = ~a;
    var z: i64 = (c & d) | (c ^ d);
    return z;
}

fn main() -> i64 {
    return f(7u8, 3u8, 12, 5);
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})

    assert "    and rax, rcx" in asm
    assert "    or rax, rcx" in asm
    assert "    xor rax, rcx" in asm
    assert "    not rax" in asm
    assert asm.count("    and rax, 255") >= 2


def test_emit_asm_emits_checked_shift_ops(tmp_path) -> None:
    source = """
fn f(a: u64, b: i64, c: u8) -> i64 {
    var x: u64 = a << 3u;
    var y: i64 = b >> 1u;
    var z: u8 = c >> 2u;
    return y;
}

fn main() -> i64 {
    return f(8u, 12, 7u8);
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})

    assert "    shl rax, cl" in asm
    assert "    sar rax, cl" in asm
    assert "    shr rax, cl" in asm
    assert "    cmp rcx, 64" in asm
    assert "    cmp rcx, 8" in asm
    assert "    call rt_panic" in asm


def test_emit_asm_emits_integer_power_op(tmp_path) -> None:
    source = """
fn f(a: u64, b: u8) -> u64 {
    var x: u64 = a ** 5u;
    var y: u8 = b ** 3u;
    return x;
}

fn main() -> i64 {
    return (i64)f(2u, 3u8);
}
"""
    asm = emit_source_asm(tmp_path, source, disabled_passes={"dead_stmt_prune", "dead_store_elimination"})

    assert "    test rcx, rcx" in asm
    assert "    test rcx, 1" in asm
    assert "    imul r8, r9" in asm
    assert "    imul r9, r9" in asm
    assert "    shr rcx, 1" in asm
    assert "    mov rax, r8" in asm
    assert "    and rax, 255" in asm


def test_emit_asm_normalizes_signed_modulo_to_true_modulo(tmp_path) -> None:
    source = """
fn f(a: i64, b: i64) -> i64 {
    return a % b;
}

fn main() -> i64 {
    return f(-7, 3);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    cqo" in asm
    assert "    idiv rcx" in asm
    assert "    mov r8, rax" in asm
    assert "    xor r8, rcx" in asm
    assert "    add rax, rcx" in asm


def test_emit_asm_normalizes_signed_division_to_floor_division(tmp_path) -> None:
    source = """
fn f(a: i64, b: i64) -> i64 {
    return a / b;
}

fn main() -> i64 {
    return f(-7, 3);
}
"""
    asm = emit_source_asm(tmp_path, source)

    assert "    cqo" in asm
    assert "    idiv rcx" in asm
    assert "    test rdx, rdx" in asm
    assert "    mov r8, rdx" in asm
    assert "    xor r8, rcx" in asm
    assert "    sub rax, 1" in asm
