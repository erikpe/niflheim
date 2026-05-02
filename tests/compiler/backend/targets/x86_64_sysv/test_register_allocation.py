from __future__ import annotations

from pathlib import Path

from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import (
    X86_64SysVLiveInterval,
    allocate_x86_64_sysv_registers,
    build_instruction_positions,
    build_live_intervals,
    plan_x86_64_sysv_target,
)
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.targets.x86_64_sysv.helpers import make_target_input


def _callable_plan(tmp_path: Path, source: str, *, callable_name: str):
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        source,
        callable_name=callable_name,
        skip_optimize=True,
    )
    target_input = make_target_input(fixture.program)
    return plan_x86_64_sysv_target(target_input, options=BackendTargetOptions()).plan_for_callable(
        fixture.callable_decl.callable_id
    )


def _reg_id_by_debug_name(callable_plan, debug_name: str):
    for register in callable_plan.callable_decl.registers:
        if register.debug_name == debug_name:
            return register.reg_id
    raise KeyError(debug_name)


def _interval_by_debug_name(callable_plan, debug_name: str):
    reg_id = _reg_id_by_debug_name(callable_plan, debug_name)
    for interval in build_live_intervals(callable_plan):
        if interval.reg_id == reg_id:
            return interval
    raise KeyError(debug_name)


def _test_interval(
    callable_plan,
    debug_name: str,
    *,
    start: int,
    end: int,
    register_class: str = "gpr",
) -> X86_64SysVLiveInterval:
    return X86_64SysVLiveInterval(
        reg_id=_reg_id_by_debug_name(callable_plan, debug_name),
        start_position=start,
        end_position=end,
        register_class=register_class,
        crosses_call=False,
        is_gc_reference=False,
        live_at_safepoint=False,
    )


def test_build_instruction_positions_numbers_in_ordered_block_sequence(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(x: i64) -> i64 {
            var y: i64 = x;
            var z: i64 = y + 1;
            return z;
        }

        fn main() -> i64 {
            return sample(1);
        }
        """,
        callable_name="sample",
    )

    positions = build_instruction_positions(callable_plan)
    block = callable_plan.callable_decl.blocks[0]

    assert positions.instruction_position(block.instructions[0].inst_id) == 0
    assert positions.instruction_position(block.instructions[1].inst_id) == 1
    assert positions.terminator_position(block.block_id) == 2


def test_build_live_intervals_tracks_straight_line_defs_uses_and_return_terminator(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(x: i64) -> i64 {
            var y: i64 = x;
            var z: i64 = y + 1;
            return z;
        }

        fn main() -> i64 {
            return sample(1);
        }
        """,
        callable_name="sample",
    )

    x_interval = _interval_by_debug_name(callable_plan, "x")
    y_interval = _interval_by_debug_name(callable_plan, "y")
    z_interval = _interval_by_debug_name(callable_plan, "z")

    assert (x_interval.start_position, x_interval.end_position, x_interval.register_class) == (0, 0, "gpr")
    assert (y_interval.start_position, y_interval.end_position, y_interval.register_class) == (0, 1, "gpr")
    assert (z_interval.start_position, z_interval.end_position, z_interval.register_class) == (1, 2, "gpr")
    assert tuple(interval.reg_id for interval in build_live_intervals(callable_plan)) == (
        x_interval.reg_id,
        y_interval.reg_id,
        z_interval.reg_id,
    )


def test_build_live_intervals_classifies_double_registers_as_xmm(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(x: double) -> double {
            var y: double = x;
            return y;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="sample",
    )

    assert _interval_by_debug_name(callable_plan, "x").register_class == "xmm"
    assert _interval_by_debug_name(callable_plan, "y").register_class == "xmm"


def test_build_live_intervals_marks_call_crossing_and_safepoint_live_registers(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn callee(v: i64) -> i64 {
            return v;
        }

        fn sample(x: i64) -> i64 {
            var y: i64 = x;
            var z: i64 = callee(x);
            return y + z;
        }

        fn main() -> i64 {
            return sample(1);
        }
        """,
        callable_name="sample",
    )

    x_interval = _interval_by_debug_name(callable_plan, "x")
    y_interval = _interval_by_debug_name(callable_plan, "y")
    z_interval = _interval_by_debug_name(callable_plan, "z")

    assert x_interval.crosses_call is False
    assert x_interval.live_at_safepoint is True
    assert y_interval.crosses_call is True
    assert y_interval.live_at_safepoint is True
    assert z_interval.crosses_call is False
    assert z_interval.live_at_safepoint is False


def test_build_live_intervals_marks_gc_references_live_at_safepoints(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        class Box {}

        extern fn rt_gc_collect() -> unit;

        fn sample(box: Box) -> Box {
            rt_gc_collect();
            return box;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="sample",
    )

    box_interval = _interval_by_debug_name(callable_plan, "box")

    assert box_interval.register_class == "gpr"
    assert box_interval.crosses_call is True
    assert box_interval.is_gc_reference is True
    assert box_interval.live_at_safepoint is True


def test_allocate_x86_64_sysv_registers_spills_gc_references_until_root_reload_is_location_aware(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        class Box {}

        fn sample(box: Box) -> Box {
            return box;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="sample",
    )
    box_reg_id = _reg_id_by_debug_name(callable_plan, "box")

    allocation = allocate_x86_64_sysv_registers(callable_plan)
    box_location = allocation.location_for_reg(box_reg_id)

    assert box_location.physical_register is None
    assert box_location.stack_slot is not None
    assert allocation.spilled_reg_ids == (box_reg_id,)


def test_allocate_x86_64_sysv_registers_assigns_initial_callee_saved_gprs(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(a: i64, b: i64) -> i64 {
            return a;
        }

        fn main() -> i64 {
            return sample(1, 2);
        }
        """,
        callable_name="sample",
    )

    allocation = allocate_x86_64_sysv_registers(
        callable_plan,
        intervals=(
            _test_interval(callable_plan, "a", start=0, end=2),
            _test_interval(callable_plan, "b", start=0, end=2),
        ),
    )

    assert allocation.location_for_reg(_reg_id_by_debug_name(callable_plan, "a")).physical_register.name == "rbx"
    assert allocation.location_for_reg(_reg_id_by_debug_name(callable_plan, "b")).physical_register.name == "r12"
    assert tuple(register.name for register in allocation.used_callee_saved_registers) == ("rbx", "r12")
    assert allocation.spilled_reg_ids == ()


def test_allocate_x86_64_sysv_registers_reuses_expired_registers(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(a: i64, b: i64) -> i64 {
            return a;
        }

        fn main() -> i64 {
            return sample(1, 2);
        }
        """,
        callable_name="sample",
    )

    allocation = allocate_x86_64_sysv_registers(
        callable_plan,
        intervals=(
            _test_interval(callable_plan, "a", start=0, end=0),
            _test_interval(callable_plan, "b", start=1, end=1),
        ),
    )

    assert allocation.location_for_reg(_reg_id_by_debug_name(callable_plan, "a")).physical_register.name == "rbx"
    assert allocation.location_for_reg(_reg_id_by_debug_name(callable_plan, "b")).physical_register.name == "rbx"
    assert tuple(register.name for register in allocation.used_callee_saved_registers) == ("rbx",)


def test_allocate_x86_64_sysv_registers_spills_xmm_intervals_to_stack_homes(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(value: double) -> double {
            return value;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="sample",
    )
    value_reg_id = _reg_id_by_debug_name(callable_plan, "value")

    allocation = allocate_x86_64_sysv_registers(
        callable_plan,
        intervals=(_test_interval(callable_plan, "value", start=0, end=1, register_class="xmm"),),
    )
    value_location = allocation.location_for_reg(value_reg_id)

    assert value_location.physical_register is None
    assert value_location.stack_slot is not None
    assert value_location.stack_slot.byte_offset == callable_plan.frame_layout.for_reg(value_reg_id).byte_offset
    assert allocation.spilled_reg_ids == (value_reg_id,)


def test_allocate_x86_64_sysv_registers_spills_when_gpr_pressure_exceeds_initial_pool(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64) -> i64 {
            return a;
        }

        fn main() -> i64 {
            return sample(1, 2, 3, 4, 5, 6);
        }
        """,
        callable_name="sample",
    )

    allocation = allocate_x86_64_sysv_registers(
        callable_plan,
        intervals=tuple(
            _test_interval(callable_plan, name, start=0, end=10)
            for name in ("a", "b", "c", "d", "e", "f")
        ),
    )

    assert tuple(
        allocation.location_for_reg(_reg_id_by_debug_name(callable_plan, name)).physical_register.name
        for name in ("a", "b", "c", "d", "e")
    ) == ("rbx", "r12", "r13", "r14", "r15")
    f_reg_id = _reg_id_by_debug_name(callable_plan, "f")
    assert allocation.location_for_reg(f_reg_id).physical_register is None
    assert allocation.location_for_reg(f_reg_id).stack_slot is not None
    assert allocation.spilled_reg_ids == (f_reg_id,)


def test_allocate_x86_64_sysv_registers_spills_farthest_active_interval_when_useful(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64) -> i64 {
            return a;
        }

        fn main() -> i64 {
            return sample(1, 2, 3, 4, 5, 6);
        }
        """,
        callable_name="sample",
    )

    allocation = allocate_x86_64_sysv_registers(
        callable_plan,
        intervals=(
            _test_interval(callable_plan, "a", start=0, end=100),
            _test_interval(callable_plan, "b", start=0, end=90),
            _test_interval(callable_plan, "c", start=0, end=80),
            _test_interval(callable_plan, "d", start=0, end=70),
            _test_interval(callable_plan, "e", start=0, end=60),
            _test_interval(callable_plan, "f", start=1, end=10),
        ),
    )
    a_reg_id = _reg_id_by_debug_name(callable_plan, "a")

    assert allocation.location_for_reg(a_reg_id).physical_register is None
    assert allocation.location_for_reg(a_reg_id).stack_slot is not None
    assert allocation.location_for_reg(_reg_id_by_debug_name(callable_plan, "f")).physical_register.name == "rbx"
    assert allocation.spilled_reg_ids == (a_reg_id,)


def test_allocate_x86_64_sysv_registers_spills_current_interval_when_tied_with_active_candidate(tmp_path) -> None:
    callable_plan = _callable_plan(
        tmp_path,
        """
        fn sample(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64) -> i64 {
            return a;
        }

        fn main() -> i64 {
            return sample(1, 2, 3, 4, 5, 6);
        }
        """,
        callable_name="sample",
    )

    allocation = allocate_x86_64_sysv_registers(
        callable_plan,
        intervals=tuple(
            _test_interval(callable_plan, name, start=0 if name != "f" else 1, end=100)
            for name in ("a", "b", "c", "d", "e", "f")
        ),
    )
    f_reg_id = _reg_id_by_debug_name(callable_plan, "f")

    assert allocation.location_for_reg(f_reg_id).physical_register is None
    assert allocation.location_for_reg(f_reg_id).stack_slot is not None
    assert allocation.spilled_reg_ids == (f_reg_id,)
