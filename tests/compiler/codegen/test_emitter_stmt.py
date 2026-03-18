from __future__ import annotations

from pathlib import Path

from compiler.resolver import resolve_program
from compiler.codegen.generator import emit_asm
from compiler.codegen_linker import build_codegen_program
from compiler.semantic_lowering import lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _emit(tmp_path: Path, files: dict[str, str]) -> str:
    for relative_path, content in files.items():
        _write(tmp_path / relative_path, content)
    program = build_codegen_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
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
    assert "call rt_array_set_i64" in asm
    assert "call rt_array_get_i64" in asm