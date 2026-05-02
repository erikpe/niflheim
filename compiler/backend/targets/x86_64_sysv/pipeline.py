from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.analysis.pipeline import BackendPipelineCallableAnalysis
from compiler.backend.ir import BackendBlockId, BackendCallableDecl, BackendCallableId
from compiler.backend.targets.api import BackendTargetInput, BackendTargetOptions
from compiler.backend.targets.x86_64_sysv.frame import X86_64SysVFrameLayout, plan_callable_frame_layout


@dataclass(frozen=True, slots=True)
class X86_64SysVCallablePlan:
    callable_decl: BackendCallableDecl
    analysis: BackendPipelineCallableAnalysis
    frame_layout: X86_64SysVFrameLayout
    ordered_block_ids: tuple[BackendBlockId, ...]


@dataclass(frozen=True, slots=True)
class X86_64SysVTargetPlan:
    target_input: BackendTargetInput
    callable_plans: tuple[X86_64SysVCallablePlan, ...]
    callable_plan_by_id: dict[BackendCallableId, X86_64SysVCallablePlan]
    diagnostics: tuple[str, ...] = ()

    def plan_for_callable(self, callable_id: BackendCallableId) -> X86_64SysVCallablePlan:
        return self.callable_plan_by_id[callable_id]


def plan_x86_64_sysv_target(
    target_input: BackendTargetInput,
    *,
    options: BackendTargetOptions,
) -> X86_64SysVTargetPlan:
    callable_plans: list[X86_64SysVCallablePlan] = []
    callable_plan_by_id: dict[BackendCallableId, X86_64SysVCallablePlan] = {}

    for callable_decl in target_input.program.callables:
        if callable_decl.is_extern:
            continue
        callable_plan = plan_x86_64_sysv_callable(target_input, callable_decl, options=options)
        callable_plans.append(callable_plan)
        callable_plan_by_id[callable_decl.callable_id] = callable_plan

    return X86_64SysVTargetPlan(
        target_input=target_input,
        callable_plans=tuple(callable_plans),
        callable_plan_by_id=callable_plan_by_id,
    )


def plan_x86_64_sysv_callable(
    target_input: BackendTargetInput,
    callable_decl: BackendCallableDecl,
    *,
    options: BackendTargetOptions,
) -> X86_64SysVCallablePlan:
    del options
    analysis = target_input.analysis_for_callable(callable_decl.callable_id)
    return X86_64SysVCallablePlan(
        callable_decl=callable_decl,
        analysis=analysis,
        frame_layout=plan_callable_frame_layout(target_input, callable_decl),
        ordered_block_ids=analysis.ordered_block_ids,
    )


__all__ = [
    "X86_64SysVCallablePlan",
    "X86_64SysVTargetPlan",
    "plan_x86_64_sysv_callable",
    "plan_x86_64_sysv_target",
]
