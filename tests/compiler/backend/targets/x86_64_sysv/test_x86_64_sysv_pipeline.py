from __future__ import annotations

from compiler.backend.targets import BackendTargetOptions
from compiler.backend.targets.x86_64_sysv import (
    X86_64SysVCallablePlan,
    X86_64SysVTargetPlan,
    plan_callable_frame_layout,
    plan_x86_64_sysv_target,
)
from tests.compiler.backend.ir.helpers import FIXTURE_ENTRY_FUNCTION_ID, callable_by_id, one_function_backend_program
from tests.compiler.backend.lowering.helpers import lower_source_to_backend_program
from tests.compiler.backend.targets.x86_64_sysv.helpers import make_target_input


def test_plan_x86_64_sysv_target_builds_allocation_aware_callable_plan() -> None:
    target_input = make_target_input(one_function_backend_program())
    callable_decl = callable_by_id(target_input.program, FIXTURE_ENTRY_FUNCTION_ID)

    target_plan = plan_x86_64_sysv_target(target_input, options=BackendTargetOptions())
    callable_plan = target_plan.plan_for_callable(FIXTURE_ENTRY_FUNCTION_ID)

    assert target_plan.target_input is target_input
    assert target_plan.diagnostics == ()
    assert target_plan.callable_plans == (callable_plan,)
    assert target_plan.callable_plan_by_id == {FIXTURE_ENTRY_FUNCTION_ID: callable_plan}
    assert callable_plan.callable_decl == callable_decl
    assert callable_plan.analysis == target_input.analysis_for_callable(FIXTURE_ENTRY_FUNCTION_ID)
    assert callable_plan.ordered_block_ids == callable_plan.analysis.ordered_block_ids
    assert callable_plan.allocation is not None
    assert callable_plan.frame_layout.allocation == callable_plan.allocation
    unallocated_slots = plan_callable_frame_layout(target_input, callable_decl).slots
    assert set(callable_plan.frame_layout.slots).issubset(set(unallocated_slots))
    assert len(callable_plan.frame_layout.slots) <= len(unallocated_slots)


def test_plan_x86_64_sysv_target_can_disable_register_allocation() -> None:
    target_input = make_target_input(one_function_backend_program())
    callable_decl = callable_by_id(target_input.program, FIXTURE_ENTRY_FUNCTION_ID)

    target_plan = plan_x86_64_sysv_target(
        target_input,
        options=BackendTargetOptions(register_allocation_enabled=False),
    )
    callable_plan = target_plan.plan_for_callable(FIXTURE_ENTRY_FUNCTION_ID)

    assert callable_plan.allocation is None
    assert callable_plan.frame_layout == plan_callable_frame_layout(target_input, callable_decl)
    assert callable_plan.frame_layout.callee_saved_slots == ()


def test_plan_x86_64_sysv_target_skips_extern_callables(tmp_path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        extern fn ext_add(value: i64) -> i64;

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )
    target_input = make_target_input(program)
    target_plan = plan_x86_64_sysv_target(target_input, options=BackendTargetOptions())

    planned_ids = tuple(callable_plan.callable_decl.callable_id for callable_plan in target_plan.callable_plans)

    assert planned_ids == (target_input.program.entry_callable_id,)
    assert all(not callable_plan.callable_decl.is_extern for callable_plan in target_plan.callable_plans)


def test_x86_64_sysv_package_exports_target_plan_surface() -> None:
    assert X86_64SysVCallablePlan.__name__ == "X86_64SysVCallablePlan"
    assert X86_64SysVTargetPlan.__name__ == "X86_64SysVTargetPlan"
