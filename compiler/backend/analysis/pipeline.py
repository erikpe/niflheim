from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.backend.analysis.block_order import order_callable_blocks, ordered_block_ids_for_callable
from compiler.backend.analysis.cfg import BackendCallableCfg, index_callable_cfg
from compiler.backend.analysis.liveness import BackendCallableLiveness, analyze_callable_liveness
from compiler.backend.analysis.root_slots import BackendCallableRootSlots, analyze_callable_root_slots
from compiler.backend.analysis.safepoints import BackendCallableSafepoints, analyze_callable_safepoints
from compiler.backend.analysis.simplify_cfg import simplify_callable_cfg
from compiler.backend.analysis.stack_homes import BackendCallableStackHomes, analyze_callable_stack_homes
from compiler.backend.ir import BackendCallableDecl, BackendCallableId, BackendFunctionAnalysisDump, BackendProgram
from compiler.backend.ir.verify import verify_backend_program


@dataclass(frozen=True)
class BackendPipelineCallableAnalysis:
    callable_id: BackendCallableId
    cfg: BackendCallableCfg | None
    liveness: BackendCallableLiveness
    safepoints: BackendCallableSafepoints
    root_slots: BackendCallableRootSlots
    stack_homes: BackendCallableStackHomes
    ordered_block_ids: tuple
    analysis_dump: BackendFunctionAnalysisDump


@dataclass(frozen=True)
class BackendPipelineResult:
    program: BackendProgram
    analysis_by_callable_id: dict[BackendCallableId, BackendPipelineCallableAnalysis]


def run_backend_ir_pipeline(program: BackendProgram) -> BackendPipelineResult:
    """Run the phase-3 backend cleanup and analysis pipeline.

    The returned program is verified and ready for post-pass dumping or later
    target-specific lowering. Analysis results remain sidecar data; only CFG
    cleanup and block reordering mutate the backend program structure.
    """

    verify_backend_program(program)

    rewritten_callables: list[BackendCallableDecl] = []
    analysis_by_callable_id: dict[BackendCallableId, BackendPipelineCallableAnalysis] = {}

    for callable_decl in program.callables:
        simplified_callable = simplify_callable_cfg(callable_decl)
        ordered_callable = order_callable_blocks(simplified_callable)
        callable_analysis = _analyze_callable(ordered_callable)
        rewritten_callables.append(ordered_callable)
        analysis_by_callable_id[ordered_callable.callable_id] = callable_analysis

    rewritten_program = replace(program, callables=tuple(rewritten_callables))
    verify_backend_program(rewritten_program)
    return BackendPipelineResult(
        program=rewritten_program,
        analysis_by_callable_id=analysis_by_callable_id,
    )


def _analyze_callable(callable_decl: BackendCallableDecl) -> BackendPipelineCallableAnalysis:
    cfg = None if callable_decl.is_extern or not callable_decl.blocks else index_callable_cfg(callable_decl)
    liveness = analyze_callable_liveness(callable_decl)
    safepoints = analyze_callable_safepoints(callable_decl, liveness=liveness)
    root_slots = analyze_callable_root_slots(callable_decl, safepoints=safepoints)
    stack_homes = analyze_callable_stack_homes(callable_decl)
    ordered_block_ids = ordered_block_ids_for_callable(callable_decl)
    analysis_dump = BackendFunctionAnalysisDump(
        predecessors={} if cfg is None else cfg.predecessor_by_block,
        successors={} if cfg is None else cfg.successor_by_block,
        live_in=liveness.live_in_by_block,
        live_out=liveness.live_out_by_block,
        safepoint_live_regs=safepoints.safepoint_live_regs,
        root_slot_by_reg=root_slots.root_slot_by_reg,
        stack_home_by_reg=stack_homes.stack_home_by_reg,
    )
    return BackendPipelineCallableAnalysis(
        callable_id=callable_decl.callable_id,
        cfg=cfg,
        liveness=liveness,
        safepoints=safepoints,
        root_slots=root_slots,
        stack_homes=stack_homes,
        ordered_block_ids=ordered_block_ids,
        analysis_dump=analysis_dump,
    )


__all__ = [
    "BackendPipelineCallableAnalysis",
    "BackendPipelineResult",
    "run_backend_ir_pipeline",
]