"""Backend IR optimization public surface."""

from compiler.backend.optimizations.dead_pure_definition_elimination import (
    dead_pure_definition_elimination,
    instruction_is_dead_eliminable,
)
from compiler.backend.optimizations.pipeline import (
    DEFAULT_BACKEND_OPTIMIZATION_PASSES,
    BackendOptimization,
    BackendOptimizationPass,
    optimize_backend_ir_program,
)
from compiler.backend.optimizations.simplify_cfg import (
    eliminate_unreachable_blocks,
    simplify_callable_cfg,
    simplify_cfg,
    simplify_trivial_jump_blocks,
)

__all__ = [
    "BackendOptimization",
    "BackendOptimizationPass",
    "DEFAULT_BACKEND_OPTIMIZATION_PASSES",
    "dead_pure_definition_elimination",
    "eliminate_unreachable_blocks",
    "instruction_is_dead_eliminable",
    "optimize_backend_ir_program",
    "simplify_callable_cfg",
    "simplify_cfg",
    "simplify_trivial_jump_blocks",
]
