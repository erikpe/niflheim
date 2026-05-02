from __future__ import annotations

from dataclasses import dataclass, replace

from compiler.backend.analysis.cfg import build_block_index, build_successor_map, reachable_block_ids
from compiler.backend.ir import (
    BackendBlock,
    BackendBoolConst,
    BackendBranchTerminator,
    BackendCallableDecl,
    BackendConstOperand,
    BackendJumpTerminator,
    BackendProgram,
)
from compiler.common.logging import get_logger


@dataclass
class _SimplifyCfgStats:
    removed_unreachable_blocks: int = 0
    removed_trivial_jump_blocks: int = 0
    folded_constant_branches: int = 0
    rewritten_terminators: int = 0
    optimized_callables: int = 0


def simplify_cfg(program: BackendProgram) -> BackendProgram:
    logger = get_logger(__name__)
    stats = _SimplifyCfgStats()
    optimized_callables = tuple(simplify_callable_cfg(callable_decl, stats=stats) for callable_decl in program.callables)
    optimized_program = replace(program, callables=optimized_callables)
    logger.debugv(
        1,
        "Backend optimization pass simplify_cfg removed %d unreachable blocks, %d trivial jump blocks, folded %d constant branches, rewrote %d terminators across %d callables",
        stats.removed_unreachable_blocks,
        stats.removed_trivial_jump_blocks,
        stats.folded_constant_branches,
        stats.rewritten_terminators,
        stats.optimized_callables,
    )
    return optimized_program


def eliminate_unreachable_blocks(
    callable_decl: BackendCallableDecl,
    *,
    stats: _SimplifyCfgStats | None = None,
) -> BackendCallableDecl:
    """Drop blocks that are not reachable from the callable entry block.

    This pass preserves the original block and instruction ids of every surviving block.
    Extern callables are returned unchanged.
    """

    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    block_by_id = build_block_index(callable_decl)
    successor_by_block = build_successor_map(callable_decl, block_by_id=block_by_id)
    reachable_ids = reachable_block_ids(
        callable_decl,
        successor_by_block=successor_by_block,
        block_by_id=block_by_id,
    )
    if len(reachable_ids) == len(callable_decl.blocks):
        return callable_decl

    if stats is not None:
        stats.removed_unreachable_blocks += len(callable_decl.blocks) - len(reachable_ids)
    return replace(
        callable_decl,
        blocks=tuple(block for block in callable_decl.blocks if block.block_id in reachable_ids),
    )


def simplify_trivial_jump_blocks(
    callable_decl: BackendCallableDecl,
    *,
    stats: _SimplifyCfgStats | None = None,
) -> BackendCallableDecl:
    """Forward through empty non-entry jump blocks and collapse redundant branches.

    Only blocks with no instructions and a jump terminator are removed. Blocks carrying
    merge-copy instructions or any other real work are intentionally preserved.
    """

    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    build_block_index(callable_decl)
    forward_target_by_block = _forward_target_by_block(callable_decl)
    if not forward_target_by_block:
        return callable_decl

    rewritten_blocks: list[BackendBlock] = []
    changed = False
    removed_jump_blocks = 0
    rewritten_terminators = 0
    for block in callable_decl.blocks:
        if block.block_id in forward_target_by_block:
            changed = True
            removed_jump_blocks += 1
            continue
        rewritten_terminator = _rewrite_terminator(block, forward_target_by_block)
        if rewritten_terminator != block.terminator:
            changed = True
            rewritten_terminators += 1
            rewritten_blocks.append(replace(block, terminator=rewritten_terminator))
        else:
            rewritten_blocks.append(block)

    if not changed:
        return callable_decl
    if stats is not None:
        stats.removed_trivial_jump_blocks += removed_jump_blocks
        stats.rewritten_terminators += rewritten_terminators
    return replace(callable_decl, blocks=tuple(rewritten_blocks))


def fold_constant_branches(
    callable_decl: BackendCallableDecl,
    *,
    stats: _SimplifyCfgStats | None = None,
) -> BackendCallableDecl:
    if callable_decl.is_extern or not callable_decl.blocks:
        return callable_decl

    rewritten_blocks: list[BackendBlock] = []
    folded_count = 0
    for block in callable_decl.blocks:
        terminator = block.terminator
        if not isinstance(terminator, BackendBranchTerminator):
            rewritten_blocks.append(block)
            continue
        if not isinstance(terminator.condition, BackendConstOperand) or not isinstance(terminator.condition.constant, BackendBoolConst):
            rewritten_blocks.append(block)
            continue
        target_block_id = terminator.true_block_id if terminator.condition.constant.value else terminator.false_block_id
        rewritten_blocks.append(
            replace(block, terminator=BackendJumpTerminator(span=terminator.span, target_block_id=target_block_id))
        )
        folded_count += 1

    if folded_count == 0:
        return callable_decl
    if stats is not None:
        stats.folded_constant_branches += folded_count
    return replace(callable_decl, blocks=tuple(rewritten_blocks))


def simplify_callable_cfg(
    callable_decl: BackendCallableDecl,
    *,
    stats: _SimplifyCfgStats | None = None,
) -> BackendCallableDecl:
    """Run the conservative backend CFG simplifier to a fixed point."""

    current = callable_decl
    changed = False
    while True:
        next_callable = eliminate_unreachable_blocks(
            simplify_trivial_jump_blocks(fold_constant_branches(current, stats=stats), stats=stats),
            stats=stats,
        )
        if next_callable == current:
            if changed and stats is not None:
                stats.optimized_callables += 1
            return current
        changed = True
        current = next_callable


def _forward_target_by_block(
    callable_decl: BackendCallableDecl,
) -> dict:
    raw_candidates = {
        block.block_id: block.terminator.target_block_id
        for block in callable_decl.blocks
        if block.block_id != callable_decl.entry_block_id
        and not block.instructions
        and isinstance(block.terminator, BackendJumpTerminator)
        and block.terminator.target_block_id != block.block_id
    }
    if not raw_candidates:
        return {}

    resolved_targets: dict = {}
    for block_id in raw_candidates:
        resolved_target = _resolve_forward_target(block_id, raw_candidates)
        if resolved_target is None or resolved_target == block_id:
            continue
        resolved_targets[block_id] = resolved_target
    return resolved_targets


def _resolve_forward_target(block_id, raw_candidates):
    visited = set()
    current_block_id = block_id
    while current_block_id in raw_candidates:
        if current_block_id in visited:
            return None
        visited.add(current_block_id)
        next_block_id = raw_candidates[current_block_id]
        if next_block_id == current_block_id:
            return None
        current_block_id = next_block_id
    return current_block_id


def _rewrite_terminator(block: BackendBlock, forward_target_by_block: dict):
    terminator = block.terminator
    if isinstance(terminator, BackendJumpTerminator):
        resolved_target = _remap_target(terminator.target_block_id, forward_target_by_block)
        if resolved_target == terminator.target_block_id:
            return terminator
        return BackendJumpTerminator(span=terminator.span, target_block_id=resolved_target)
    if isinstance(terminator, BackendBranchTerminator):
        resolved_true = _remap_target(terminator.true_block_id, forward_target_by_block)
        resolved_false = _remap_target(terminator.false_block_id, forward_target_by_block)
        if resolved_true == resolved_false:
            return BackendJumpTerminator(span=terminator.span, target_block_id=resolved_true)
        if resolved_true == terminator.true_block_id and resolved_false == terminator.false_block_id:
            return terminator
        return BackendBranchTerminator(
            span=terminator.span,
            condition=terminator.condition,
            true_block_id=resolved_true,
            false_block_id=resolved_false,
        )
    return terminator


def _remap_target(block_id, forward_target_by_block):
    current_block_id = block_id
    visited = set()
    while current_block_id in forward_target_by_block:
        if current_block_id in visited:
            return block_id
        visited.add(current_block_id)
        current_block_id = forward_target_by_block[current_block_id]
    return current_block_id


__all__ = [
    "eliminate_unreachable_blocks",
    "fold_constant_branches",
    "simplify_callable_cfg",
    "simplify_cfg",
    "simplify_trivial_jump_blocks",
]
