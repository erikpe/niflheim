from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from compiler.codegen.abi.runtime import ARRAY_INDEX_GET_RUNTIME_CALLS, ARRAY_INDEX_SET_RUNTIME_CALLS
from compiler.codegen.emitter_fn import emit_function
from compiler.codegen.generator import CodeGenerator, emit_asm
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowered_ir import LoweredSemanticForIn
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.codegen.program_generator import ProgramGenerator


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _emit(tmp_path: Path, files: dict[str, str]) -> str:
    for relative_path, content in files.items():
        _write(tmp_path / relative_path, content)
    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    return emit_asm(program)


def test_emitter_stmt_emits_control_flow_and_assignments(tmp_path: Path) -> None:
    asm = _emit(
        tmp_path,
        {
            "main.nif": """
            class Box {
                value: i64;

                fn set(v: i64) -> unit {
                    __self.value = v;
                    return;
                }
            }

            fn main() -> i64 {
                var total: i64 = 0;
                var box: Box = Box(0);
                while total < 4 {
                    if total == 2 {
                        total = total + 1;
                        continue;
                    }
                    box.value = total;
                    if total == 3 {
                        break;
                    }
                    total = total + 1;
                }
                return box.value;
            }
            """,
        },
    )

    assert ".Lmain_while_start_" in asm
    assert ".Lmain_if_else_" in asm
    assert ".Lmain_if_end_" in asm
    assert "mov qword ptr [rcx + 24], rax" in asm
    assert "jmp .Lmain_while_start_" in asm


def test_emitter_stmt_emits_for_in_and_structural_writes(tmp_path: Path) -> None:
    asm = _emit(
        tmp_path,
        {
            "main.nif": """
            class Buffer {
                fn iter_len() -> u64 {
                    return 1u;
                }

                fn iter_get(index: i64) -> i64 {
                    return index;
                }

                fn index_set(index: i64, value: i64) -> unit {
                    return;
                }
            }

            fn main(buffer: Buffer, values: i64[]) -> i64 {
                var total: i64 = 0;
                for value in buffer {
                    total = total + value;
                }
                values[0] = total;
                return values[0];
            }
            """,
        },
    )

    assert ".Lmain_for_in_start_" in asm
    assert "call __nif_method_Buffer_iter_len" in asm
    assert "call __nif_method_Buffer_iter_get" in asm
    assert f"call {ARRAY_INDEX_SET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in asm
    assert f"call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" in asm


def test_emitter_stmt_for_in_helper_identity_does_not_depend_on_span_values(tmp_path: Path) -> None:
    files = {
        "main.nif": """
        fn main(values: i64[]) -> i64 {
            var total: i64 = 0;
            for first in values { total = total + first; }
            for second in values { total = total + second; }
            return total;
        }
        """,
    }
    for relative_path, content in files.items():
        _write(tmp_path / relative_path, content)

    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "main")
    loop_one = fn.body.statements[1]
    loop_two = fn.body.statements[2]

    assert isinstance(loop_one, LoweredSemanticForIn)
    assert isinstance(loop_two, LoweredSemanticForIn)

    rewritten_fn = replace(
        fn,
        body=replace(
            fn.body,
            statements=[
                fn.body.statements[0],
                loop_one,
                replace(loop_two, span=loop_one.span),
                fn.body.statements[3],
            ],
        ),
    )

    codegen = CodeGenerator()
    declaration_tables = ProgramGenerator(program).build_declaration_tables()
    emit_function(codegen, declaration_tables, rewritten_fn)
    asm = "\n".join(codegen.asm.lines)

    assert "call rt_array_len" not in asm
    assert f"call {ARRAY_INDEX_GET_RUNTIME_CALLS[ArrayRuntimeKind.I64]}" not in asm