"""Backend analysis public surface."""

from compiler.backend.analysis.cfg import (
	BackendCallableCfg,
	BackendCfgError,
	build_block_index,
	build_predecessor_map,
	build_successor_map,
	index_callable_cfg,
	iter_block_instructions,
	iter_callable_instructions,
	reachable_block_ids,
	reverse_postorder_block_ids,
)
from compiler.backend.analysis.block_order import (
	order_callable_blocks,
	ordered_block_ids_for_callable,
)
from compiler.backend.analysis.liveness import (
	BackendCallableLiveness,
	analyze_callable_liveness,
	instruction_def_reg,
	instruction_use_regs,
	operand_use_regs,
	terminator_use_regs,
	transfer_instruction_live_set,
	transfer_terminator_live_set,
)
from compiler.backend.analysis.safepoints import (
	BackendCallableSafepoints,
	analyze_callable_safepoints,
	instruction_effects,
	instruction_is_safepoint,
	register_is_gc_reference,
	safepoint_live_regs_for_instruction,
)
from compiler.backend.analysis.root_slots import (
	BackendCallableRootSlots,
	analyze_callable_root_slots,
	build_root_slot_plan_from_live_reg_sets,
)
from compiler.backend.analysis.stack_homes import (
	BackendCallableStackHomes,
	analyze_callable_stack_homes,
	stack_home_name_for_register,
)
from compiler.backend.analysis.pipeline import (
	BackendPipelineCallableAnalysis,
	BackendPipelineResult,
	run_backend_ir_pipeline,
)
from compiler.backend.analysis.simplify_cfg import (
	eliminate_unreachable_blocks,
	simplify_callable_cfg,
	simplify_trivial_jump_blocks,
)

__all__ = [
	"BackendCallableCfg",
	"BackendCfgError",
	"BackendPipelineCallableAnalysis",
	"BackendPipelineResult",
	"build_block_index",
	"build_predecessor_map",
	"build_successor_map",
	"eliminate_unreachable_blocks",
	"index_callable_cfg",
	"instruction_def_reg",
	"instruction_use_regs",
	"iter_block_instructions",
	"iter_callable_instructions",
	"operand_use_regs",
	"order_callable_blocks",
	"ordered_block_ids_for_callable",
	"reachable_block_ids",
	"reverse_postorder_block_ids",
	"BackendCallableLiveness",
	"BackendCallableRootSlots",
	"BackendCallableStackHomes",
	"BackendCallableSafepoints",
	"analyze_callable_liveness",
	"analyze_callable_root_slots",
	"analyze_callable_stack_homes",
	"analyze_callable_safepoints",
	"build_root_slot_plan_from_live_reg_sets",
	"run_backend_ir_pipeline",
	"simplify_callable_cfg",
	"simplify_trivial_jump_blocks",
	"stack_home_name_for_register",
	"instruction_effects",
	"instruction_is_safepoint",
	"register_is_gc_reference",
	"safepoint_live_regs_for_instruction",
	"terminator_use_regs",
	"transfer_instruction_live_set",
	"transfer_terminator_live_set",
]
