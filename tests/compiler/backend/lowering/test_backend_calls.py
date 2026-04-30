from __future__ import annotations

from compiler.backend.ir import (
    BackendBinaryInst,
    BackendCallInst,
    BackendConstOperand,
    BackendCopyInst,
    BackendDirectCallTarget,
    BackendFunctionOperand,
    BackendIndirectCallTarget,
    BackendNullConst,
    BackendReturnTerminator,
    BackendUnaryInst,
)
from compiler.backend.ir.text import dump_backend_program_text
from tests.compiler.backend.lowering.helpers import (
    block_by_ordinal,
    callable_by_name,
    callable_by_suffix,
    lower_source_to_backend_program,
)


def test_lower_to_backend_ir_lowers_straight_line_local_unary_binary_and_copy_shapes(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        fn calc(input: i64) -> i64 {
            var base: i64 = input;
            var neg: i64 = -base;
            var sum: i64 = neg + 5;
            var same: i64 = sum;
            same = same + 1;
            return same;
        }

        fn main() -> i64 {
            return calc(3);
        }
        """,
        skip_optimize=True,
    )

    calc_callable = callable_by_name(program, "calc")
    calc_block = block_by_ordinal(calc_callable, 0)
    instructions = list(calc_block.instructions)

    assert [type(instruction) for instruction in instructions] == [
        BackendCopyInst,
        BackendUnaryInst,
        BackendBinaryInst,
        BackendCopyInst,
        BackendBinaryInst,
    ]
    assert isinstance(calc_block.terminator, BackendReturnTerminator)
    assert calc_block.terminator.value is not None


def test_lower_to_backend_ir_lowers_direct_function_and_static_method_calls_with_exact_signatures(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        extern fn sink(value: Obj) -> unit;

        class Math {
            static fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }
        }

        fn inc(v: i64) -> i64 {
            return v + 1;
        }

        fn main() -> i64 {
            sink(null);
            var a: i64 = inc(20);
            var b: i64 = Math.add(a, 22);
            return b;
        }
        """,
        skip_optimize=True,
    )

    main_callable = callable_by_name(program, "main")
    calls = [instruction for instruction in block_by_ordinal(main_callable, 0).instructions if isinstance(instruction, BackendCallInst)]

    assert len(calls) == 3

    sink_call, inc_call, add_call = calls
    assert sink_call.dest is None
    assert isinstance(sink_call.target, BackendDirectCallTarget)
    assert sink_call.target.callable_id.name == "sink"
    assert sink_call.signature.return_type is None
    assert len(sink_call.args) == 1
    assert isinstance(sink_call.args[0], BackendConstOperand)
    assert isinstance(sink_call.args[0].constant, BackendNullConst)

    assert isinstance(inc_call.target, BackendDirectCallTarget)
    assert inc_call.target.callable_id.name == "inc"
    assert [param_type.canonical_name for param_type in inc_call.signature.param_types] == ["i64"]
    assert inc_call.signature.return_type is not None
    assert inc_call.signature.return_type.canonical_name == "i64"

    assert isinstance(add_call.target, BackendDirectCallTarget)
    assert add_call.target.callable_id.class_name == "Math"
    assert add_call.target.callable_id.name == "add"
    assert [param_type.canonical_name for param_type in add_call.signature.param_types] == ["i64", "i64"]
    assert add_call.signature.return_type is not None
    assert add_call.signature.return_type.canonical_name == "i64"
    assert len(add_call.args) == 2


def test_lower_to_backend_ir_keeps_nested_expression_evaluation_order_deterministic(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Math {
            static fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }

            static fn twice(value: i64) -> i64 {
                return value + value;
            }
        }

        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn compute(input: i64) -> i64 {
            return Math.add(inc(input + 1), Math.twice(3));
        }

        fn main() -> i64 {
            return compute(4);
        }
        """,
        skip_optimize=True,
    )

    compute_callable = callable_by_name(program, "compute")
    dumped = dump_backend_program_text(program)
    compute_header = "func main::compute(r0: i64) -> i64 {"
    assert compute_header in dumped

    compute_block = block_by_ordinal(compute_callable, 0)
    rendered_instructions = [line.strip() for line in dump_backend_program_text(program).splitlines() if line.strip().startswith("i")]

    assert isinstance(compute_block.instructions[0], BackendBinaryInst)
    assert isinstance(compute_block.instructions[1], BackendCallInst)
    assert isinstance(compute_block.instructions[2], BackendCallInst)
    assert isinstance(compute_block.instructions[3], BackendCallInst)

    inc_call_text = "call direct main::inc"
    twice_call_text = "call direct main::Math.twice"
    add_call_text = "call direct main::Math.add"

    assert any(inc_call_text in line for line in rendered_instructions)
    assert any(twice_call_text in line for line in rendered_instructions)
    assert any(add_call_text in line for line in rendered_instructions)
    assert dumped.index(inc_call_text) < dumped.index(twice_call_text) < dumped.index(add_call_text)


def test_lower_to_backend_ir_preserves_static_method_calls_without_receiver_arguments(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Math {
            static fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }
        }

        fn main() -> i64 {
            return Math.add(20, 22);
        }
        """,
        skip_optimize=True,
    )

    main_callable = callable_by_name(program, "main")
    call_inst = next(
        instruction for instruction in block_by_ordinal(main_callable, 0).instructions if isinstance(instruction, BackendCallInst)
    )

    assert isinstance(call_inst.target, BackendDirectCallTarget)
    assert call_inst.target.callable_id.class_name == "Math"
    assert len(call_inst.args) == len(call_inst.signature.param_types)
    assert call_inst.target.callable_id == callable_by_suffix(program, "main.Math.add").callable_id


def test_lower_to_backend_ir_preserves_mixed_scalar_call_signatures_with_double_types(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        fn mix(a: i64, b: double, c: u64, d: double, e: bool) -> double {
            if e {
                return b + d;
            }
            return b;
        }

        fn main() -> i64 {
            var out: double = mix(2, 0.5, 3u, 0.25, true);
            if out == 0.75 {
                return 0;
            }
            return 1;
        }
        """,
        skip_optimize=True,
    )

    main_callable = callable_by_name(program, "main")
    mix_call = next(
        instruction for instruction in block_by_ordinal(main_callable, 0).instructions if isinstance(instruction, BackendCallInst)
    )

    assert isinstance(mix_call.target, BackendDirectCallTarget)
    assert mix_call.target.callable_id.name == "mix"
    assert [param_type.canonical_name for param_type in mix_call.signature.param_types] == [
        "i64",
        "double",
        "u64",
        "double",
        "bool",
    ]
    assert mix_call.signature.return_type is not None
    assert mix_call.signature.return_type.canonical_name == "double"


def test_lower_to_backend_ir_materializes_function_refs_for_callable_value_calls(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        fn inc(value: i64) -> i64 {
            return value + 1;
        }

        fn apply(f: fn(i64) -> i64, value: i64) -> i64 {
            return f(value);
        }

        fn main() -> i64 {
            var func: fn(i64) -> i64 = inc;
            return apply(func, 41);
        }
        """,
        skip_optimize=True,
    )

    main_callable = callable_by_name(program, "main")
    main_block = block_by_ordinal(main_callable, 0)
    function_copy = next(instruction for instruction in main_block.instructions if isinstance(instruction, BackendCopyInst))
    apply_call = next(instruction for instruction in main_block.instructions if isinstance(instruction, BackendCallInst))

    assert isinstance(function_copy.source, BackendFunctionOperand)
    assert function_copy.source.function_id.name == "inc"
    assert isinstance(apply_call.target, BackendDirectCallTarget)

    apply_callable = callable_by_name(program, "apply")
    indirect_call = next(instruction for instruction in block_by_ordinal(apply_callable, 0).instructions if isinstance(instruction, BackendCallInst))

    assert isinstance(indirect_call.target, BackendIndirectCallTarget)