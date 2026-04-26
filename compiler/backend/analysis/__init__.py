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

__all__ = [
	"BackendCallableCfg",
	"BackendCfgError",
	"build_block_index",
	"build_predecessor_map",
	"build_successor_map",
	"index_callable_cfg",
	"iter_block_instructions",
	"iter_callable_instructions",
	"reachable_block_ids",
	"reverse_postorder_block_ids",
]
