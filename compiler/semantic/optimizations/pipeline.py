from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from compiler.common.logging import get_logger
from compiler.semantic.ir import SemanticProgram

from .constant_folding import fold_constants
from .reachability import prune_unreachable_semantic


SemanticOptimization = Callable[[SemanticProgram], SemanticProgram]


@dataclass(frozen=True)
class SemanticOptimizationPass:
    name: str
    transform: SemanticOptimization


DEFAULT_SEMANTIC_OPTIMIZATION_PASSES: tuple[SemanticOptimizationPass, ...] = (
    SemanticOptimizationPass(name="constant_fold", transform=fold_constants),
    SemanticOptimizationPass(name="prune_unreachable", transform=prune_unreachable_semantic),
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
