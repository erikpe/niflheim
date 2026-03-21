from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from compiler.semantic.ir import SemanticProgram

from .reachability import prune_unreachable_semantic


SemanticOptimization = Callable[[SemanticProgram], SemanticProgram]


@dataclass(frozen=True)
class SemanticOptimizationPass:
    name: str
    transform: SemanticOptimization


DEFAULT_SEMANTIC_OPTIMIZATION_PASSES: tuple[SemanticOptimizationPass, ...] = (
    SemanticOptimizationPass(name="prune_unreachable", transform=prune_unreachable_semantic),
)


def optimize_semantic_program(
    program: SemanticProgram, *, passes: Sequence[SemanticOptimizationPass] = DEFAULT_SEMANTIC_OPTIMIZATION_PASSES
) -> SemanticProgram:
    optimized_program = program
    for optimization_pass in passes:
        optimized_program = optimization_pass.transform(optimized_program)
    return optimized_program
