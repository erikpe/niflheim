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
from compiler.backend.analysis.simplify_cfg import (
	eliminate_unreachable_blocks,
	simplify_callable_cfg,
	simplify_trivial_jump_blocks,
)

__all__ = [
	"BackendCallableCfg",
	"BackendCfgError",
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
	"reachable_block_ids",
	"reverse_postorder_block_ids",
	"BackendCallableLiveness",
	"analyze_callable_liveness",
	"simplify_callable_cfg",
	"simplify_trivial_jump_blocks",
	"terminator_use_regs",
	"transfer_instruction_live_set",
	"transfer_terminator_live_set",
]
