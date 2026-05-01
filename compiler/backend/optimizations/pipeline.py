from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from time import perf_counter

from compiler.backend.ir import BackendProgram
from compiler.backend.ir.verify import verify_backend_program
from compiler.common.logging import get_logger

from .dead_pure_definition_elimination import dead_pure_definition_elimination
from .simplify_cfg import simplify_cfg
from .trivial_copy_elimination import trivial_copy_elimination


BackendOptimization = Callable[[BackendProgram], BackendProgram]


@dataclass(frozen=True)
class BackendOptimizationPass:
    name: str
    transform: BackendOptimization


DEFAULT_BACKEND_OPTIMIZATION_PASSES: tuple[BackendOptimizationPass, ...] = (
    BackendOptimizationPass(
        name="dead_pure_definition_elimination",
        transform=dead_pure_definition_elimination,
    ),
    BackendOptimizationPass(name="trivial_copy_elimination", transform=trivial_copy_elimination),
    BackendOptimizationPass(name="simplify_cfg", transform=simplify_cfg),
)


def optimize_backend_ir_program(
    program: BackendProgram,
    *,
    passes: Sequence[BackendOptimizationPass] = DEFAULT_BACKEND_OPTIMIZATION_PASSES,
) -> BackendProgram:
    logger = get_logger(__name__)
    optimized_program = program
    verify_backend_program(optimized_program)
    for optimization_pass in passes:
        start = perf_counter()
        optimized_program = optimization_pass.transform(optimized_program)
        verify_backend_program(optimized_program)
        duration_ms = (perf_counter() - start) * 1000.0
        logger.debugv(1, "Backend optimization pass %s completed in %.2f ms", optimization_pass.name, duration_ms)
    return optimized_program


__all__ = [
    "BackendOptimization",
    "BackendOptimizationPass",
    "DEFAULT_BACKEND_OPTIMIZATION_PASSES",
    "optimize_backend_ir_program",
]
