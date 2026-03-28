from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from compiler.common.logging import get_logger
from compiler.semantic.ir import SemanticProgram

from .constant_fold import constant_fold
from .copy_propagation import copy_propagation
from .dead_store_elimination import dead_store_elimination
from .dead_stmt_prune import dead_stmt_prune
from .unreachable_prune import unreachable_prune
from .redundant_cast_elimination import redundant_cast_elimination
from .simplify_control_flow import simplify_control_flow


SemanticOptimization = Callable[[SemanticProgram], SemanticProgram]


@dataclass(frozen=True)
class SemanticOptimizationPass:
    name: str
    transform: SemanticOptimization


DEFAULT_SEMANTIC_OPTIMIZATION_PASSES: tuple[SemanticOptimizationPass, ...] = (
    SemanticOptimizationPass(name="constant_fold", transform=constant_fold),
    SemanticOptimizationPass(name="simplify_control_flow", transform=simplify_control_flow),
    SemanticOptimizationPass(name="copy_propagation", transform=copy_propagation),
    SemanticOptimizationPass(name="redundant_cast_elimination", transform=redundant_cast_elimination),
    SemanticOptimizationPass(name="dead_store_elimination", transform=dead_store_elimination),
    SemanticOptimizationPass(name="constant_fold", transform=constant_fold),
    SemanticOptimizationPass(name="dead_stmt_prune", transform=dead_stmt_prune),
    SemanticOptimizationPass(name="unreachable_prune", transform=unreachable_prune),
)


def optimize_semantic_program(
    program: SemanticProgram, *, passes: Sequence[SemanticOptimizationPass] = DEFAULT_SEMANTIC_OPTIMIZATION_PASSES
) -> SemanticProgram:
    logger = get_logger(__name__)
    optimized_program = program
    for optimization_pass in passes:
        start = perf_counter()
        optimized_program = optimization_pass.transform(optimized_program)
        duration_ms = (perf_counter() - start) * 1000.0
        logger.debugv(1, "Optimization pass %s completed in %.2f ms", optimization_pass.name, duration_ms)
    return optimized_program
