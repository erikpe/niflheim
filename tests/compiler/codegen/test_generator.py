from compiler.codegen.abi import runtime_layout
from compiler.codegen.asm import offset_operand
from compiler.codegen.generator import CodeGenerator
from compiler.codegen.layout import build_layout
from compiler.codegen.program_generator import ProgramGenerator
from compiler.codegen.symbols import mangle_function_symbol
from compiler.resolver import resolve_program
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.lowering.orchestration import lower_program
from compiler.semantic.symbols import ClassId, ConstructorId, MethodId


def _write(path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_codegen_uses_builder_for_static_call_padding_and_comments(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn callee() -> i64 {
            return 7;
        }

        fn caller() -> i64 {
            return callee();
        }

        fn main() -> i64 {
            return caller();
        }
        """,
    )
    generator = ProgramGenerator(
        lower_linked_semantic_program(
            link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
        )
    )

    asm = generator.generate()

    assert generator.asm.build() == asm
    assert any(line.startswith("    # ") for line in generator.asm.lines)
    assert "    test rsp, 8" not in asm
    assert ".L__nif_aligned_call_0:" not in asm
    assert f'    call {mangle_function_symbol(("main",), "callee")}' in asm


def test_codegen_builds_constructor_and_field_tables(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
            next: Obj;

            static fn make(value: i64) -> Box {
                return Box(value, null);
            }

            fn get() -> i64 {
                return __self.value;
            }
        }

        fn helper() -> bool {
            return true;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
    )
    generator = ProgramGenerator(
        lower_linked_semantic_program(
            link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
        )
    )

    tables = generator.build_declaration_tables()
    box_id = ClassId(module_path=("main",), name="Box")
    ctor_id = ConstructorId(module_path=("main",), class_name="Box")
    make_id = MethodId(module_path=("main",), class_name="Box", name="make")
    get_id = MethodId(module_path=("main",), class_name="Box", name="get")

    assert tables.method_label(make_id) == "__nif_method_main__Box_make"
    assert tables.method_label(get_id) == "__nif_method_main__Box_get"
    assert tables.class_field_offset(box_id, "value") == 24
    assert tables.constructor_layout(ctor_id).label == "__nif_ctor_main__Box"
    assert tables.constructor_layout(ctor_id).param_field_names == ["value", "next"]


def test_codegen_emits_main_prologue_and_epilogue(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )
    generator = ProgramGenerator(
        lower_linked_semantic_program(
            link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
        )
    )

    asm = generator.generate()

    assert ".globl main" in asm
    assert "main:" in asm
    assert ".Lmain_epilogue:" in asm
    assert "    ret" in asm


def test_codegen_orchestrates_sections_and_class_symbols(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;

            fn get() -> i64 {
                return __self.value;
            }
        }

        fn main() -> i64 {
            return Box(0).get();
        }
        """,
    )
    generator = ProgramGenerator(
        lower_linked_semantic_program(
            link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
        )
    )

    asm = generator.generate()

    assert ".text" in asm
    assert "__nif_method_main__Box_get" in asm
    assert "__nif_ctor_main__Box" in asm
    assert '.section .note.GNU-stack,"",@progbits' in asm


def test_codegen_named_root_slot_updates_can_target_specific_locals(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn f(a: Obj, b: Obj) -> unit {
            return;
        }

        fn main() -> i64 {
            f(null, null);
            return 0;
        }
        """,
    )
    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "f")
    layout = build_layout(fn)
    generator = CodeGenerator()

    local_infos = sorted(
        (local_info for local_info in fn.local_info_by_id.values() if local_info.binding_kind == "param"),
        key=lambda local_info: local_info.local_id.ordinal,
    )
    first_param = local_infos[0].local_id
    second_param = local_infos[1].local_id

    generator.emit_named_root_slot_updates(layout, local_ids={first_param})

    asm = "\n".join(generator.asm.lines)
    assert f"    mov rax, {offset_operand(layout.local_slot_offsets[first_param])}" in asm
    assert f"    mov {offset_operand(layout.root_slot_offsets_by_local_id[first_param])}, rax" in asm
    assert f"    mov rax, {offset_operand(layout.local_slot_offsets[second_param])}" not in asm
    assert f"    mov {offset_operand(layout.root_slot_offsets_by_local_id[second_param])}, rax" not in asm
    assert "    call rt_root_slot_store" not in asm


def test_codegen_named_root_slot_clears_can_target_specific_locals(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn f(a: Obj, b: Obj) -> unit {
            return;
        }

        fn main() -> i64 {
            f(null, null);
            return 0;
        }
        """,
    )
    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    fn = next(fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "f")
    layout = build_layout(fn)
    generator = CodeGenerator()

    local_infos = sorted(
        (local_info for local_info in fn.local_info_by_id.values() if local_info.binding_kind == "param"),
        key=lambda local_info: local_info.local_id.ordinal,
    )
    first_param = local_infos[0].local_id
    second_param = local_infos[1].local_id

    generator.emit_named_root_slot_clears(layout, local_ids={first_param})

    asm = "\n".join(generator.asm.lines)
    assert f"    mov {offset_operand(layout.root_slot_offsets_by_local_id[first_param])}, 0" in asm
    assert f"    mov {offset_operand(layout.root_slot_offsets_by_local_id[second_param])}, 0" not in asm
    assert "    call rt_root_slot_store" not in asm


def test_codegen_zero_slots_can_skip_immediately_spilled_param_slots_but_keep_root_slots(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn keep(value: Obj) -> Obj {
            return value;
        }

        fn main() -> i64 {
            if keep(null) == null {
                return 0;
            }
            return 1;
        }
        """,
    )
    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    fn = next(
        fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "keep"
    )
    layout = build_layout(fn)
    generator = CodeGenerator()

    param_local_id = next(
        local_info.local_id for local_info in fn.local_info_by_id.values() if local_info.binding_kind == "param"
    )
    param_slot_offset = layout.local_slot_offsets[param_local_id]
    param_root_offset = layout.root_slot_offsets_by_local_id[param_local_id]

    generator.emit_zero_slots(layout, skipped_value_slot_offsets={param_slot_offset})

    asm = "\n".join(generator.asm.lines)
    assert f"    mov {offset_operand(param_slot_offset)}, 0" not in asm
    assert f"    mov {offset_operand(param_root_offset)}, 0" in asm


def test_codegen_runtime_root_layout_helpers_match_runtime_abi() -> None:
    generator = CodeGenerator()

    assert runtime_layout.RT_THREAD_STATE_ROOTS_TOP_OFFSET == 0
    assert runtime_layout.RT_ROOT_FRAME_PREV_OFFSET == 0
    assert runtime_layout.RT_ROOT_FRAME_SLOT_COUNT_OFFSET == 8
    assert runtime_layout.RT_ROOT_FRAME_RESERVED_OFFSET == 12
    assert runtime_layout.RT_ROOT_FRAME_SLOTS_OFFSET == 16
    assert runtime_layout.RT_ROOT_FRAME_SIZE_BYTES == 24

    assert generator.root_frame_size_bytes() == 24
    assert generator.thread_state_roots_top_operand("rdi") == "qword ptr [rdi]"
    assert generator.root_frame_prev_operand("rsi") == "qword ptr [rsi]"
    assert generator.root_frame_slot_count_operand("rsi") == "dword ptr [rsi + 8]"
    assert generator.root_frame_reserved_operand("rsi") == "dword ptr [rsi + 12]"
    assert generator.root_frame_slots_operand("rsi") == "qword ptr [rsi + 16]"


def test_codegen_emit_root_frame_pop_restores_previous_shadow_stack_top(tmp_path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn keep(value: Obj) -> Obj {
            return value;
        }

        fn main() -> i64 {
            if keep(null) == null {
                return 0;
            }
            return 1;
        }
        """,
    )
    program = lower_linked_semantic_program(
        link_semantic_program(lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)))
    )
    fn = next(
        fn for fn in program.functions if fn.function_id.module_path == ("main",) and fn.function_id.name == "keep"
    )
    layout = build_layout(fn)
    generator = CodeGenerator()

    generator.emit_root_frame_pop(layout)

    asm = "\n".join(generator.asm.lines)
    assert f"    mov rdi, {offset_operand(layout.thread_state_offset)}" in asm
    assert f"    lea rcx, [rbp - {abs(layout.root_frame_offset)}]" in asm
    assert "    mov rcx, qword ptr [rcx]" in asm
    assert "    mov qword ptr [rdi], rcx" in asm

