from __future__ import annotations

import compiler.backend.targets.aarch64 as aarch64_target
from compiler.backend.targets.aarch64 import (
    AARCH64_ABI,
    AARCH64_TARGET,
    AArch64AsmBuilder,
    TARGET_NAME,
    check_aarch64_legality,
    format_stack_slot_operand,
    plan_callable_frame_layout,
)
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8
from compiler.semantic.types import SemanticTypeRef, semantic_primitive_type_ref
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.ir.helpers import FIXTURE_ENTRY_FUNCTION_ID, callable_by_id, one_function_backend_program
from tests.compiler.backend.targets.aarch64.helpers import make_target_input, unit_function_backend_program, with_root_slot


def test_aarch64_exports_explicit_target_surface() -> None:
    assert aarch64_target.__all__ == [
        "AARCH64_ABI",
        "AARCH64_TARGET",
        "AArch64Abi",
        "AArch64ArgLocation",
        "AArch64AsmBuilder",
        "AArch64FrameError",
        "AArch64FrameLayout",
        "AArch64FrameSlot",
        "AArch64LegalityError",
        "AArch64RootSlot",
        "AArch64Target",
        "TARGET_NAME",
        "check_aarch64_legality",
        "emit_aarch64_asm",
        "format_stack_slot_operand",
        "plan_callable_frame_layout",
    ]
    assert TARGET_NAME == "aarch64"
    assert AARCH64_TARGET.name == TARGET_NAME
    assert callable(check_aarch64_legality)


def test_aarch64_abi_plans_integer_like_arguments_and_returns() -> None:
    param_types = tuple(
        semantic_primitive_type_ref(type_name)
        for type_name in (TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_BOOL, TYPE_NAME_U8, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64)
    )

    locations = AARCH64_ABI.plan_argument_locations(param_types)

    assert tuple(location.kind for location in locations) == (
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "int_reg",
        "stack",
    )
    assert tuple(location.register_name for location in locations[:8]) == ("x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7")
    assert locations[8].stack_slot_index == 0
    assert AARCH64_ABI.return_register_for_type(semantic_primitive_type_ref(TYPE_NAME_BOOL)) == "x0"
    assert AARCH64_ABI.return_register_for_type(None) is None


def test_aarch64_abi_treats_callable_values_as_integer_like_arguments_and_returns() -> None:
    callable_type = SemanticTypeRef(
        kind="callable",
        canonical_name="fn(Obj) -> bool",
        display_name="fn(Obj) -> bool",
        param_types=(SemanticTypeRef(kind="reference", canonical_name="Obj", display_name="Obj"),),
        return_type=semantic_primitive_type_ref(TYPE_NAME_BOOL),
    )

    locations = AARCH64_ABI.plan_argument_locations((callable_type, semantic_primitive_type_ref(TYPE_NAME_I64)))

    assert locations[0] == type(locations[0])(kind="int_reg", register_name="x0")
    assert locations[1] == type(locations[1])(kind="int_reg", register_name="x1")
    assert AARCH64_ABI.supports_passed_type(callable_type) is True
    assert AARCH64_ABI.return_register_for_type(callable_type) == "x0"


def test_aarch64_abi_plans_mixed_integer_and_double_arguments_and_returns() -> None:
    param_types = tuple(
        semantic_primitive_type_ref(type_name)
        for type_name in (
            TYPE_NAME_I64,
            TYPE_NAME_DOUBLE,
            TYPE_NAME_U64,
            TYPE_NAME_DOUBLE,
            TYPE_NAME_U8,
            TYPE_NAME_DOUBLE,
            TYPE_NAME_BOOL,
            TYPE_NAME_DOUBLE,
            TYPE_NAME_I64,
            TYPE_NAME_DOUBLE,
            TYPE_NAME_U64,
            TYPE_NAME_I64,
        )
    )

    locations = AARCH64_ABI.plan_argument_locations(param_types)

    assert locations[0] == type(locations[0])(kind="int_reg", register_name="x0")
    assert locations[1] == type(locations[1])(kind="float_reg", register_name="d0")
    assert locations[7] == type(locations[7])(kind="float_reg", register_name="d3")
    assert locations[8].kind == "int_reg"
    assert locations[8].register_name == "x4"
    assert locations[9] == type(locations[9])(kind="float_reg", register_name="d4")
    assert locations[10].kind == "int_reg"
    assert locations[10].register_name == "x5"
    assert locations[11].kind == "int_reg"
    assert locations[11].register_name == "x6"
    assert AARCH64_ABI.return_register_for_type(semantic_primitive_type_ref(TYPE_NAME_DOUBLE)) == "d0"


def test_aarch64_abi_alignment_and_callee_saved_helpers_are_stable() -> None:
    assert AARCH64_ABI.stack_alignment_bytes == 16
    assert AARCH64_ABI.stack_size_is_aligned(0) is True
    assert AARCH64_ABI.stack_size_is_aligned(16) is True
    assert AARCH64_ABI.stack_size_is_aligned(8) is False
    assert AARCH64_ABI.align_stack_size(1) == 16
    assert AARCH64_ABI.align_stack_size(16) == 16
    assert AARCH64_ABI.align_stack_size(17) == 32
    assert AARCH64_ABI.incoming_stack_arg_byte_offset(0) == 16
    assert AARCH64_ABI.incoming_stack_arg_byte_offset(2) == 32
    assert AARCH64_ABI.callee_saved_registers == (
        "x19",
        "x20",
        "x21",
        "x22",
        "x23",
        "x24",
        "x25",
        "x26",
        "x27",
        "x28",
    )
    assert AARCH64_ABI.callee_saved_float_registers == ("d8", "d9", "d10", "d11", "d12", "d13", "d14", "d15")


def test_aarch64_call_stack_helpers_are_stable() -> None:
    assert AARCH64_ABI.outgoing_stack_arg_slot_count(()) == 0
    assert AARCH64_ABI.outgoing_stack_arg_slot_count(
        tuple(semantic_primitive_type_ref(TYPE_NAME_I64) for _ in range(8))
    ) == 0
    assert AARCH64_ABI.outgoing_stack_arg_slot_count(
        tuple(semantic_primitive_type_ref(TYPE_NAME_I64) for _ in range(9))
    ) == 1
    assert AARCH64_ABI.outgoing_stack_arg_slot_count(
        tuple(semantic_primitive_type_ref(TYPE_NAME_DOUBLE) for _ in range(9))
    ) == 1
    assert AARCH64_ABI.call_stack_reservation_bytes(0) == 0
    assert AARCH64_ABI.call_stack_reservation_bytes(1) == 16
    assert AARCH64_ABI.call_stack_reservation_bytes(2) == 16
    assert AARCH64_ABI.call_stack_reservation_bytes(3) == 32


def test_aarch64_frame_layout_assigns_deterministic_offsets_from_stack_homes(tmp_path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn keep(x: i64, y: i64) -> unit {
            var z: i64 = x;
            return;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="keep",
        skip_optimize=True,
    )
    target_input = make_target_input(fixture.program)

    first_layout = plan_callable_frame_layout(target_input, fixture.callable_decl)
    second_layout = plan_callable_frame_layout(target_input, fixture.callable_decl)
    expected_home_names = tuple(
        target_input.analysis_for_callable(fixture.callable_decl.callable_id).stack_homes.stack_home_by_reg.values()
    )

    assert first_layout == second_layout
    assert tuple(slot.home_name for slot in first_layout.slots) == expected_home_names
    assert tuple(slot.byte_offset for slot in first_layout.slots) == tuple(-8 * index for index in range(1, len(first_layout.slots) + 1))
    assert first_layout.stack_size == AARCH64_ABI.align_stack_size(first_layout.home_count * 8)

    for reg_id, home_name in target_input.analysis_for_callable(fixture.callable_decl.callable_id).stack_homes.stack_home_by_reg.items():
        slot = first_layout.for_reg(reg_id)
        assert slot is not None
        assert slot.home_name == home_name
        assert first_layout.for_home_name(home_name) == slot


def test_aarch64_frame_layout_allocates_inline_root_frame_for_root_slots() -> None:
    target_input = make_target_input(one_function_backend_program())
    callable_decl = callable_by_id(target_input.program, FIXTURE_ENTRY_FUNCTION_ID)

    layout = plan_callable_frame_layout(
        with_root_slot(
            target_input,
            callable_id=FIXTURE_ENTRY_FUNCTION_ID,
            reg_id=callable_decl.registers[0].reg_id,
        ),
        callable_decl,
    )

    home_slot = layout.for_reg(callable_decl.registers[0].reg_id)
    root_slot = layout.root_slot_for_reg(callable_decl.registers[0].reg_id)

    assert home_slot is not None
    assert layout.has_root_frame is True
    assert layout.root_slot_count == 1
    assert layout.thread_state_offset is not None
    assert layout.root_frame_offset is not None
    assert root_slot is not None
    assert layout.thread_state_offset < home_slot.byte_offset
    assert layout.root_frame_offset < layout.thread_state_offset
    assert root_slot.byte_offset < layout.root_frame_offset
    assert layout.stack_size % 16 == 0


def test_aarch64_frame_layout_reserves_scratch_and_outgoing_stack_space() -> None:
    target_input = make_target_input(unit_function_backend_program(function_name="frame_model"))
    callable_decl = callable_by_id(target_input.program, target_input.program.entry_callable_id)

    layout = plan_callable_frame_layout(
        target_input,
        callable_decl,
        outgoing_stack_arg_slot_count=3,
        scratch_slot_count=2,
    )

    assert layout.scratch_slot_offsets == (-8, -16)
    assert layout.outgoing_stack_arg_offsets == (-24, -32, -40)
    assert layout.stack_size == 48


def test_aarch64_legality_checker_accepts_minimal_callable_surface() -> None:
    check_aarch64_legality(make_target_input(unit_function_backend_program(function_name="main", param_type_names=(TYPE_NAME_I64,))))


def test_aarch64_asm_helpers_render_stable_text() -> None:
    builder = AArch64AsmBuilder(emit_debug_comments=True)
    builder.section(".text")
    builder.global_symbol("demo")
    builder.blank()
    builder.label("demo")
    builder.comment("entry")
    builder.instruction("ldr", "x0", format_stack_slot_operand("x29", -16))
    builder.instruction("ret")

    assert builder.build() == (
        "\n".join(
            [
                ".section .text",
                ".globl demo",
                "",
                "demo:",
                "    // entry",
                "    ldr x0, [x29, #-16]",
                "    ret",
            ]
        )
        + "\n"
    )


def test_aarch64_asm_stack_operand_formatter_is_stable() -> None:
    assert format_stack_slot_operand("x29", 0) == "[x29]"
    assert format_stack_slot_operand("x29", -16) == "[x29, #-16]"
    assert format_stack_slot_operand("sp", 24) == "[sp, #24]"