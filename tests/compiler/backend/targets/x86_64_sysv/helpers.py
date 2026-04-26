from __future__ import annotations

from dataclasses import replace

from compiler.backend.analysis.root_slots import BackendCallableRootSlots
from compiler.backend.analysis.pipeline import run_backend_ir_pipeline
from compiler.backend.targets import BackendTargetInput


def make_target_input(program) -> BackendTargetInput:
    return BackendTargetInput.from_pipeline_result(run_backend_ir_pipeline(program))


def with_root_slot(target_input: BackendTargetInput, *, callable_id, reg_id, slot_index: int = 0) -> BackendTargetInput:
    callable_analysis = target_input.analysis_for_callable(callable_id)
    updated_analysis = replace(
        callable_analysis,
        root_slots=BackendCallableRootSlots(
            callable_decl=callable_analysis.root_slots.callable_decl,
            root_slot_by_reg={reg_id: slot_index},
            slot_reg_ids=((reg_id,),),
        ),
    )
    updated_analysis_by_callable_id = dict(target_input.analysis_by_callable_id)
    updated_analysis_by_callable_id[callable_id] = updated_analysis
    return replace(target_input, analysis_by_callable_id=updated_analysis_by_callable_id)