from __future__ import annotations

from pathlib import Path

from compiler.codegen.generator import CodeGenerator
from compiler.codegen.emitter_expr import EmitContext, emit_expr
from compiler.codegen.model import (
    ARRAY_CONSTRUCTOR_RUNTIME_CALLS,
    ARRAY_FROM_BYTES_U8_RUNTIME_CALL,
    ARRAY_INDEX_GET_RUNTIME_CALLS,
    ARRAY_SLICE_GET_RUNTIME_CALLS,
)
from compiler.codegen.program_generator import ProgramGenerator
from compiler.codegen.layout import build_layout
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_I64
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.ir import (
    CallableValueCallExpr,
    ConstructorCallExpr,
    FunctionCallExpr,
    IndexReadExpr,
    InterfaceMethodCallExpr,
    InstanceMethodCallExpr,
    SemanticReturn,
    SliceReadExpr,
    StaticMethodCallExpr,
)
from compiler.semantic.lowering import lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _build_emit_fixture(tmp_path: Path, files: dict[str, str], *, function_name: str = "main"):
    for relative_path, content in files.items():
        _write(tmp_path / relative_path, content)

    program = link_semantic_program(
        lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    )
    fn = next(
        fn
        for fn in program.functions
        if fn.function_id.module_path == ("main",) and fn.function_id.name == function_name
    )
    generator = CodeGenerator()
    tables = ProgramGenerator(program).build_declaration_tables()
    layout = build_layout(fn)
    emit_ctx = EmitContext(
        layout=layout,
        fn_name=function_name,
        current_module_path=fn.function_id.module_path,
        label_counter=[0],
        string_literal_labels={},
        temp_root_depth=[0],
        declaration_tables=tables,
    )
    return fn, generator, emit_ctx


def test_emitter_expr_emits_resolved_call_forms(tmp_path: Path) -> None:
    fn, generator, ctx = _build_emit_fixture(
        tmp_path,
        {
            "main.nif": """
            class Math {
                static fn add(a: i64, b: i64) -> i64 {
                    return a + b;
                }
            }

            class Box {
                value: i64;

                fn get() -> i64 {
                    return __self.value;
                }
            }

            fn inc(v: i64) -> i64 {
                return v + 1;
            }

            fn choose(flag: bool) -> fn(i64) -> i64 {
                if flag {
                    return inc;
                }
                return inc;
            }

            fn main() -> i64 {
                var f: fn(i64) -> i64 = choose(true);
                var a: i64 = inc(1);
                var b: i64 = Math.add(a, 2);
                var box: Box = Box(b);
                var c: i64 = box.get();
                var d: i64 = f(c);
                return a + b + c + d;
            }
            """
        },
    )

    returns = [stmt for stmt in fn.body.statements if isinstance(stmt, SemanticReturn)]
    var_inits = [
        stmt.initializer
        for stmt in fn.body.statements
        if hasattr(stmt, "initializer") and stmt.initializer is not None
    ]

    assert isinstance(var_inits[1], FunctionCallExpr)
    emit_expr(generator, var_inits[1], ctx)
    assert "    call inc" in generator.asm.lines

    generator.asm.lines.clear()
    assert isinstance(var_inits[2], StaticMethodCallExpr)
    emit_expr(generator, var_inits[2], ctx)
    assert "    call __nif_method_Math_add" in generator.asm.lines

    generator.asm.lines.clear()
    assert isinstance(var_inits[3], ConstructorCallExpr)
    emit_expr(generator, var_inits[3], ctx)
    assert "    call __nif_ctor_Box" in generator.asm.lines

    generator.asm.lines.clear()
    assert isinstance(var_inits[4], InstanceMethodCallExpr)
    emit_expr(generator, var_inits[4], ctx)
    assert "    call __nif_method_Box_get" in generator.asm.lines

    generator.asm.lines.clear()
    assert isinstance(var_inits[5], CallableValueCallExpr)
    emit_expr(generator, var_inits[5], ctx)
    assert "    mov r11, rax" in generator.asm.lines
    assert "    call r11" in generator.asm.lines

    generator.asm.lines.clear()
    emit_expr(generator, returns[0].value, ctx)
    assert "    add rax, rcx" in generator.asm.lines


def test_emitter_expr_emits_numeric_casts_and_array_ops(tmp_path: Path) -> None:
    fn, generator, ctx = _build_emit_fixture(
        tmp_path,
        {
            "main.nif": """
            fn main() -> i64 {
                var arr: i64[] = i64[](4u);
                var x: i64 = arr[0];
                var y: double = (double)x;
                return (i64)y;
            }
            """
        },
    )

    var_inits = [
        stmt.initializer
        for stmt in fn.body.statements
        if hasattr(stmt, "initializer") and stmt.initializer is not None
    ]
    assert isinstance(var_inits[0], object)

    emit_expr(generator, var_inits[0], ctx)
    assert f"    call {ARRAY_CONSTRUCTOR_RUNTIME_CALLS[TYPE_NAME_I64]}" in generator.asm.lines

    generator.asm.lines.clear()
    assert isinstance(var_inits[1], IndexReadExpr)
    emit_expr(generator, var_inits[1], ctx)
    assert f"    call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in generator.asm.lines

    generator.asm.lines.clear()
    emit_expr(generator, var_inits[2], ctx)
    assert "    cvtsi2sd xmm0, rax" in generator.asm.lines

    generator.asm.lines.clear()
    return_stmt = fn.body.statements[-1]
    assert isinstance(return_stmt, SemanticReturn)
    emit_expr(generator, return_stmt.value, ctx)
    assert "    cvttsd2si rax, xmm0" in generator.asm.lines


def test_emitter_expr_emits_string_literal_helper_form_and_slice_reads(tmp_path: Path) -> None:
    fn, generator, ctx = _build_emit_fixture(
        tmp_path,
        {
            "main.nif": """
            class Str {
                static fn from_u8_array(value: u8[]) -> Str {
                    return Str();
                }

                static fn concat(left: Str, right: Str) -> Str {
                    return Str();
                }
            }

            fn main() -> Str {
                var arr: i64[] = i64[](4u);
                var part: i64[] = arr[1:3];
                return "hi" + " there";
            }
            """
        },
    )
    ctx.string_literal_labels = {'"hi"': ("__nif_str_lit_0", 2), '" there"': ("__nif_str_lit_1", 6)}

    var_inits = [
        stmt.initializer
        for stmt in fn.body.statements
        if hasattr(stmt, "initializer") and stmt.initializer is not None
    ]

    assert isinstance(var_inits[1], SliceReadExpr)
    emit_expr(generator, var_inits[1], ctx)
    assert f"    call {ARRAY_SLICE_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in generator.asm.lines

    generator.asm.lines.clear()
    return_stmt = fn.body.statements[-1]
    assert isinstance(return_stmt, SemanticReturn)
    emit_expr(generator, return_stmt.value, ctx)
    assert f"    call {ARRAY_FROM_BYTES_U8_RUNTIME_CALL}" in generator.asm.lines
    assert "    call __nif_method_Str_from_u8_array" in generator.asm.lines
    assert "    call __nif_method_Str_concat" in generator.asm.lines


def test_emitter_expr_emits_class_structural_index_reads(tmp_path: Path) -> None:
    fn, generator, ctx = _build_emit_fixture(
        tmp_path,
        {
            "main.nif": """
            class Buffer {
                fn index_get(index: i64) -> i64 {
                    return 1;
                }
            }

            fn main(buffer: Buffer) -> i64 {
                return buffer[0];
            }
            """
        },
    )

    return_stmt = fn.body.statements[-1]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, IndexReadExpr)
    emit_expr(generator, return_stmt.value, ctx)
    assert "    call __nif_method_Buffer_index_get" in generator.asm.lines


def test_emitter_expr_emits_interface_dispatch_via_lookup_helper(tmp_path: Path) -> None:
    fn, generator, ctx = _build_emit_fixture(
        tmp_path,
        {
            "main.nif": """
            interface Hashable {
                fn hash_code() -> u64;
            }

            class Key implements Hashable {
                fn hash_code() -> u64 {
                    return 7u;
                }
            }

            fn main(value: Hashable) -> u64 {
                return value.hash_code();
            }
            """
        },
    )

    return_stmt = fn.body.statements[-1]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, InterfaceMethodCallExpr)
    emit_expr(generator, return_stmt.value, ctx)
    assert "    call rt_lookup_interface_method" in generator.asm.lines
    assert "    mov r11, qword ptr [r10 + 8]" in generator.asm.lines
    assert "    call r11" in generator.asm.lines
