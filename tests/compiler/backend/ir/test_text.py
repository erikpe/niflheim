from __future__ import annotations

from dataclasses import replace

import pytest

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendDataBlob,
    BackendDataId,
    BackendFunctionAnalysisDump,
    BackendInstId,
    BackendIntConst,
    BackendJumpTerminator,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.backend.ir.text import dump_backend_program_text
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U64
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref, semantic_type_ref_for_class_id
from tests.compiler.backend.ir.helpers import (
    FIXTURE_CLASS_ID,
    FIXTURE_ENTRY_FUNCTION_ID,
    make_source_span,
    one_constructor_backend_program,
    one_function_backend_program,
    one_method_backend_program,
    representative_direct_call_instruction,
    representative_runtime_call_instruction,
)


@pytest.mark.parametrize(
    ("builder", "expected"),
    [
        (
            one_function_backend_program,
            """backend_ir niflheim.backend-ir.v1 entry=fixture.backend_ir::main

func fixture.backend_ir::main() -> i64 {
  regs:
    r0 temp ret0: i64

  b0 entry:
    i0 r0 = const.i64 0
    ret r0
}""",
        ),
        (
            one_method_backend_program,
            """backend_ir niflheim.backend-ir.v1 entry=fixture.backend_ir::main

classes:
  class fixture.backend_ir::Box
    methods:
      fixture.backend_ir::Box.value

func fixture.backend_ir::main() -> i64 {
  regs:
    r0 temp ret0: i64

  b0 entry:
    i0 r0 = const.i64 0
    ret r0
}

method fixture.backend_ir::Box.value(receiver=r0: Box, r1: i64) -> i64 {
  regs:
    r0 receiver self: Box
    r1 param value: i64
    r2 temp ret0: i64

  b0 entry:
    i0 r2 = const.i64 7
    ret r2
}""",
        ),
        (
            one_constructor_backend_program,
            """backend_ir niflheim.backend-ir.v1 entry=fixture.backend_ir::main

classes:
  class fixture.backend_ir::Box
    constructors:
      fixture.backend_ir::Box#0

func fixture.backend_ir::main() -> i64 {
  regs:
    r0 temp ret0: i64

  b0 entry:
    i0 r0 = const.i64 0
    ret r0
}

constructor fixture.backend_ir::Box#0(receiver=r0: Box, r1: bool) -> Box {
  regs:
    r0 receiver self: Box
    r1 param flag: bool

  b0 entry:
    ret r0
}""",
        ),
    ],
)
def test_dump_backend_program_text_renders_stable_snapshots(builder, expected: str) -> None:
    assert dump_backend_program_text(builder()) == expected


def test_dump_backend_program_text_canonicalizes_data_callable_register_block_and_instruction_order() -> None:
    callable_id = FunctionId(module_path=("fixture", "backend_ir"), name="sort_demo")
    helper_id = FunctionId(module_path=("fixture", "backend_ir"), name="aaa")
    span = make_source_span(path="fixtures/ordering.nif")
    registers = (
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=2),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            debug_name="r2",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=0),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            debug_name="r0",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=1),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            debug_name="r1",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
    )
    exit_block_id = BackendBlockId(owner_id=callable_id, ordinal=1)
    entry_block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    callable_decl = replace(
        one_function_backend_program().callables[0],
        callable_id=callable_id,
        registers=registers,
        param_regs=(),
        entry_block_id=entry_block_id,
        blocks=(
            BackendBlock(
                block_id=exit_block_id,
                debug_name="exit",
                instructions=(),
                terminator=BackendReturnTerminator(
                    span=span,
                    value=BackendRegOperand(reg_id=BackendRegId(owner_id=callable_id, ordinal=1)),
                ),
                span=span,
            ),
            BackendBlock(
                block_id=entry_block_id,
                debug_name="entry",
                instructions=(
                    replace(
                        one_function_backend_program().callables[0].blocks[0].instructions[0],
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=1),
                        dest=BackendRegId(owner_id=callable_id, ordinal=1),
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=2),
                        span=span,
                    ),
                    replace(
                        one_function_backend_program().callables[0].blocks[0].instructions[0],
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=BackendRegId(owner_id=callable_id, ordinal=0),
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1),
                        span=span,
                    ),
                ),
                terminator=BackendJumpTerminator(span=span, target_block_id=exit_block_id),
                span=span,
            ),
        ),
        span=span,
    )
    helper_callable = replace(one_function_backend_program().callables[0], callable_id=helper_id)
    program = BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=helper_id,
        data_blobs=(
            BackendDataBlob(data_id=BackendDataId(ordinal=2), debug_name="d2", alignment=1, bytes_hex="22", readonly=True),
            BackendDataBlob(data_id=BackendDataId(ordinal=0), debug_name="d0", alignment=1, bytes_hex="00", readonly=True),
            BackendDataBlob(data_id=BackendDataId(ordinal=1), debug_name="d1", alignment=1, bytes_hex="11", readonly=True),
        ),
        interfaces=(),
        classes=(),
        callables=(callable_decl, helper_callable),
    )

    dumped = dump_backend_program_text(program)

    assert dumped.index("  d0 \"d0\" align=1 readonly bytes=00") < dumped.index(
        "  d1 \"d1\" align=1 readonly bytes=11"
    ) < dumped.index("  d2 \"d2\" align=1 readonly bytes=22")
    assert dumped.index("func fixture.backend_ir::aaa() -> i64 {") < dumped.index(
        "func fixture.backend_ir::sort_demo() -> i64 {"
    )
    assert dumped.index("    r0 temp r0: i64") < dumped.index("    r1 temp r1: i64") < dumped.index(
        "    r2 temp r2: i64"
    )
    assert dumped.index("  b0 entry:") < dumped.index("  b1 exit:")
    assert dumped.index("    i0 r0 = const.i64 1") < dumped.index("    i1 r1 = const.i64 2")


def test_dump_backend_program_text_renders_string_blobs_readably() -> None:
    program = BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=FIXTURE_ENTRY_FUNCTION_ID,
        data_blobs=(
            BackendDataBlob(
                data_id=BackendDataId(ordinal=0),
                debug_name="string_bytes_0",
                alignment=1,
                bytes_hex="68690a00ff",
                readonly=True,
                content_kind="string",
            ),
        ),
        interfaces=(),
        classes=(),
        callables=one_function_backend_program().callables,
    )

    dumped = dump_backend_program_text(program)

    assert '  d0 "string_bytes_0" align=1 readonly string="hi\\n\\000\\377"' in dumped


def test_dump_backend_program_text_formats_direct_and_runtime_calls_readably() -> None:
    program = one_function_backend_program()
    callable_decl = program.callables[0]
    block = callable_decl.blocks[0]
    span = block.span
    callable_decl = replace(
        callable_decl,
        registers=(
            callable_decl.registers[0],
            BackendRegister(
                reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1),
                type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
                debug_name="call0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=2),
                type_ref=semantic_primitive_type_ref(TYPE_NAME_U64),
                debug_name="call1",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
            BackendRegister(
                reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=3),
                type_ref=semantic_type_ref_for_class_id(FIXTURE_CLASS_ID),
                debug_name="box0",
                origin_kind="temp",
                semantic_local_id=None,
                span=None,
            ),
        ),
        blocks=(
            replace(
                block,
                instructions=(
                    block.instructions[0],
                    representative_direct_call_instruction(),
                    representative_runtime_call_instruction(),
                ),
                terminator=BackendReturnTerminator(
                    span=span,
                    value=BackendRegOperand(reg_id=BackendRegId(owner_id=FIXTURE_ENTRY_FUNCTION_ID, ordinal=1)),
                ),
            ),
        ),
    )
    program = replace(program, callables=(callable_decl,))

    dumped = dump_backend_program_text(program)

    assert (
        "    i1 r1 = call direct fixture.backend_ir::helper(r0) sig=(i64) -> i64 effects[none]"
        in dumped
    )
    assert (
        "    i2 r2 = call runtime rt_array_len ref_args=[0](r3) sig=(Box) -> u64 effects[reads_memory]"
        in dumped
    )


def test_dump_backend_program_text_keeps_analysis_rendering_opt_in() -> None:
    program = one_function_backend_program()
    callable_decl = program.callables[0]
    block = callable_decl.blocks[0]
    register = callable_decl.registers[0]
    analysis_dump = BackendFunctionAnalysisDump(
        predecessors={block.block_id: ()},
        successors={block.block_id: ()},
        live_in={block.block_id: (register.reg_id,)},
        live_out={block.block_id: ()},
        safepoint_live_regs={block.instructions[0].inst_id: (register.reg_id,)},
        root_slot_by_reg={register.reg_id: 0},
        stack_home_by_reg={register.reg_id: "rbp-8"},
    )

    without_analysis = dump_backend_program_text(program)
    with_analysis = dump_backend_program_text(
        program,
        analysis_by_callable={callable_decl.callable_id: analysis_dump},
    )

    assert "analysis:" not in without_analysis
    assert (
        """  analysis:
    predecessors:
      b0: []
    successors:
      b0: []
    live_in:
      b0: [r0]
    live_out:
      b0: []
    safepoint_live_regs:
      i0: [r0]
    root_slot_by_reg:
      r0: 0
    stack_home_by_reg:
      r0: rbp-8"""
        in with_analysis
    )