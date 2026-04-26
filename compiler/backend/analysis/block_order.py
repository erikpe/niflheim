from __future__ import annotations

from dataclasses import replace

from compiler.backend.analysis.cfg import build_block_index, build_successor_map, reachable_block_ids, reverse_postorder_block_ids
from compiler.backend.ir import BackendCallableDecl
from compiler.backend.ir._ordering import block_sort_key


def ordered_block_ids_for_callable(callable_decl: BackendCallableDecl) -> tuple:
    """Return a deterministic emission order for one callable's blocks.

    The primary order is reverse postorder from the entry block so later target
    emission sees a stable, readable layout. Any non-reachable blocks that are
    still present are appended in stable block-id order as a conservative fallback.
    """

    if callable_decl.is_extern or not callable_decl.blocks:
        return ()

    block_by_id = build_block_index(callable_decl)
    successor_by_block = build_successor_map(callable_decl, block_by_id=block_by_id)
    reachable_ids = reachable_block_ids(
        callable_decl,
        successor_by_block=successor_by_block,
        block_by_id=block_by_id,
    )
    ordered_ids = list(
        reverse_postorder_block_ids(
            callable_decl,
            successor_by_block=successor_by_block,
            block_by_id=block_by_id,
        )
    )
    trailing_ids = [
        block.block_id
        for block in sorted(callable_decl.blocks, key=lambda block: block_sort_key(block))
        if block.block_id not in reachable_ids
    ]
    return tuple(ordered_ids + trailing_ids)


def order_callable_blocks(callable_decl: BackendCallableDecl) -> BackendCallableDecl:
    """Reorder blocks into deterministic emission order without changing ids."""

    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    ordered_block_ids = ordered_block_ids_for_callable(callable_decl)
    if not ordered_block_ids:
        return callable_decl

    block_by_id = build_block_index(callable_decl)
    reordered_blocks = tuple(block_by_id[block_id] for block_id in ordered_block_ids)
    if reordered_blocks == callable_decl.blocks:
        return callable_decl
    return replace(callable_decl, blocks=reordered_blocks)


__all__ = ["order_callable_blocks", "ordered_block_ids_for_callable"]