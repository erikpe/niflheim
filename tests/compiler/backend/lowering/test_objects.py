from __future__ import annotations

from compiler.backend.ir import (
    BackendAllocObjectInst,
    BackendBinaryInst,
    BackendCastInst,
    BackendCallInst,
    BackendCopyInst,
    BackendDirectCallTarget,
    BackendFieldLoadInst,
    BackendFieldStoreInst,
    BackendInterfaceCallTarget,
    BackendNullCheckInst,
    BackendRegOperand,
    BackendVirtualCallTarget,
)
from compiler.backend.ir.verify import verify_backend_program
from tests.compiler.backend.lowering.helpers import (
    block_by_ordinal,
    callable_by_name,
    callable_by_suffix,
    lower_source_to_backend_program,
)


def test_lower_to_backend_ir_lowers_constructor_alloc_and_super_init_calls(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Base {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }
        }

        class Derived extends Base {
            extra: i64;

            constructor(value: i64, extra: i64) {
                super(value);
                __self.extra = extra;
            }
        }

        fn main() -> i64 {
            var value: Derived = Derived(7, 9);
            return value.extra;
        }
        """,
        skip_optimize=True,
    )

    main_callable = callable_by_name(program, "main")
    main_instructions = list(block_by_ordinal(main_callable, 0).instructions)

    assert isinstance(main_instructions[0], BackendAllocObjectInst)
    assert main_instructions[0].class_id.name == "Derived"
    assert isinstance(main_instructions[1], BackendCallInst)
    assert isinstance(main_instructions[1].target, BackendDirectCallTarget)
    assert main_instructions[1].target.callable_id.class_name == "Derived"
    assert len(main_instructions[1].args) == 3
    assert isinstance(main_instructions[1].args[0], BackendRegOperand)
    assert main_instructions[1].args[0].reg_id == main_instructions[0].dest

    derived_ctor = callable_by_suffix(program, "main.Derived.#0")
    derived_instructions = list(block_by_ordinal(derived_ctor, 0).instructions)
    super_call = next(instruction for instruction in derived_instructions if isinstance(instruction, BackendCallInst))
    extra_store = next(instruction for instruction in derived_instructions if isinstance(instruction, BackendFieldStoreInst))

    assert derived_ctor.receiver_reg is not None
    assert isinstance(super_call.target, BackendDirectCallTarget)
    assert super_call.target.callable_id.class_name == "Base"
    assert len(super_call.args) == 2
    assert isinstance(super_call.args[0], BackendRegOperand)
    assert super_call.args[0].reg_id == derived_ctor.receiver_reg
    assert extra_store.owner_class_id.name == "Derived"
    assert extra_store.field_name == "extra"


def test_lower_to_backend_ir_lowers_field_reads_and_writes_with_explicit_null_checks(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Counter {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }

            fn bump(delta: i64) -> i64 {
                __self.value = __self.value + delta;
                return __self.value;
            }
        }

        fn main() -> i64 {
            return Counter(41).bump(1);
        }
        """,
        skip_optimize=True,
    )

    bump_callable = callable_by_suffix(program, "main.Counter.bump")
    bump_instructions = list(block_by_ordinal(bump_callable, 0).instructions)

    assert bump_callable.receiver_reg is not None
    assert [type(instruction) for instruction in bump_instructions] == [
        BackendNullCheckInst,
        BackendNullCheckInst,
        BackendFieldLoadInst,
        BackendBinaryInst,
        BackendFieldStoreInst,
        BackendNullCheckInst,
        BackendFieldLoadInst,
    ]
    assert bump_instructions[2].field_name == "value"
    assert bump_instructions[4].field_name == "value"
    assert bump_instructions[6].field_name == "value"


def test_lower_to_backend_ir_lowers_direct_and_virtual_instance_calls_with_receiver_first_args(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Box {
            private fn hidden() -> i64 {
                return 1;
            }

            fn expose() -> i64 {
                return __self.hidden();
            }

            fn read() -> i64 {
                return 2;
            }
        }

        fn use(value: Box) -> i64 {
            return value.read();
        }

        fn main() -> i64 {
            var value: Box = Box();
            return use(value) + value.expose();
        }
        """,
        skip_optimize=True,
    )

    expose_callable = callable_by_suffix(program, "main.Box.expose")
    expose_call = next(
        instruction for instruction in block_by_ordinal(expose_callable, 0).instructions if isinstance(instruction, BackendCallInst)
    )

    assert expose_callable.receiver_reg is not None
    assert isinstance(expose_call.target, BackendDirectCallTarget)
    assert expose_call.target.callable_id.name == "hidden"
    assert len(expose_call.args) == 1
    assert isinstance(expose_call.args[0], BackendRegOperand)
    assert expose_call.args[0].reg_id == expose_callable.receiver_reg

    use_callable = callable_by_name(program, "use")
    use_call = next(
        instruction for instruction in block_by_ordinal(use_callable, 0).instructions if isinstance(instruction, BackendCallInst)
    )

    assert isinstance(use_call.target, BackendVirtualCallTarget)
    assert use_call.target.slot_owner_class_id.name == "Box"
    assert use_call.target.method_name == "read"
    assert use_call.target.selected_method_id.class_name == "Box"
    assert use_call.target.selected_method_id.name == "read"
    assert len(use_call.args) == 1


def test_lower_to_backend_ir_lowers_interface_calls_with_interface_metadata(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        interface Metric {
            fn score() -> i64;
        }

        class Box implements Metric {
            fn score() -> i64 {
                return 7;
            }
        }

        fn use(value: Metric) -> i64 {
            return value.score();
        }

        fn main() -> i64 {
            return use(Box());
        }
        """,
        skip_optimize=True,
    )

    use_callable = callable_by_name(program, "use")
    interface_call = next(
        instruction for instruction in block_by_ordinal(use_callable, 0).instructions if isinstance(instruction, BackendCallInst)
    )

    assert isinstance(interface_call.target, BackendInterfaceCallTarget)
    assert interface_call.target.interface_id.name == "Metric"
    assert interface_call.target.method_id.interface_name == "Metric"
    assert interface_call.target.method_id.name == "score"
    assert len(interface_call.args) == 1


def test_lower_to_backend_ir_materializes_cast_for_narrowed_local_before_copy_and_field_read(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Box {
            value: i64;
        }

        fn read(value: Obj) -> i64 {
            if !(value is Box) {
                return 0;
            }
            var alias: Box = (Box)value;
            return alias.value;
        }

        fn main() -> i64 {
            return read(Box(7));
        }
        """,
    )

    verify_backend_program(program)
    read_callable = callable_by_name(program, "read")
    instructions = [instruction for block in read_callable.blocks for instruction in block.instructions]

    cast_inst = next(instruction for instruction in instructions if isinstance(instruction, BackendCastInst))
    copy_inst = next(instruction for instruction in instructions if isinstance(instruction, BackendCopyInst))
    field_load_inst = next(instruction for instruction in instructions if isinstance(instruction, BackendFieldLoadInst))

    assert isinstance(copy_inst.source, BackendRegOperand)
    assert copy_inst.source.reg_id == cast_inst.dest
    assert isinstance(field_load_inst.object_ref, BackendRegOperand)
    assert field_load_inst.object_ref.reg_id == copy_inst.dest


def test_lower_to_backend_ir_materializes_cast_for_interface_typed_local_initializers(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        interface Comparable {
            fn compare_to(other: Obj) -> i64;
        }

        class Box implements Comparable {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
            }

            fn compare_to(other: Obj) -> i64 {
                return __self.value - ((Box)other).value;
            }
        }

        fn main() -> i64 {
            var value: Box = Box(7);
            var comparable: Comparable = value;
            return comparable.compare_to((Obj)Box(7));
        }
        """,
        skip_optimize=True,
    )

    verify_backend_program(program)
    main_callable = callable_by_name(program, "main")
    casts = [instruction for block in main_callable.blocks for instruction in block.instructions if isinstance(instruction, BackendCastInst)]

    assert any(cast.target_type_ref.interface_id is not None and cast.target_type_ref.interface_id.name == "Comparable" for cast in casts)


def test_lower_to_backend_ir_synthesizes_compatibility_constructor_field_stores(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Base {
            value: i64;
        }

        class Derived extends Base {
            ready: bool = true;
            extra: i64;
        }

        fn main() -> i64 {
            var value: Derived = Derived(7, 9);
            if !value.ready {
                return 1;
            }
            return value.value + value.extra;
        }
        """,
        skip_optimize=True,
    )

    verify_backend_program(program)
    derived_ctor = callable_by_suffix(program, "main.Derived.#0")
    instructions = list(block_by_ordinal(derived_ctor, 0).instructions)

    super_call = next(instruction for instruction in instructions if isinstance(instruction, BackendCallInst))
    field_stores = [instruction for instruction in instructions if isinstance(instruction, BackendFieldStoreInst)]

    assert isinstance(super_call.target, BackendDirectCallTarget)
    assert super_call.target.callable_id.class_name == "Base"
    assert [instruction.field_name for instruction in field_stores] == ["ready", "extra"]

