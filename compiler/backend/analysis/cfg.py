from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from compiler.backend.ir import (
    BackendBlock,
    BackendBlockId,
    BackendBranchTerminator,
    BackendCallableDecl,
    BackendInstruction,
    BackendJumpTerminator,
    BackendReturnTerminator,
    BackendTrapTerminator,
)
from compiler.backend.ir._ordering import block_sort_key, instruction_sort_key


class BackendCfgError(ValueError):
    """Raised when a backend callable cannot be indexed as a CFG."""


@dataclass(frozen=True)
class BackendCallableCfg:
    callable_decl: BackendCallableDecl
    block_by_id: dict[BackendBlockId, BackendBlock]
    successor_by_block: dict[BackendBlockId, tuple[BackendBlockId, ...]]
    predecessor_by_block: dict[BackendBlockId, tuple[BackendBlockId, ...]]
    reachable_block_ids: frozenset[BackendBlockId]
    reverse_postorder_block_ids: tuple[BackendBlockId, ...]


def build_block_index(callable_decl: BackendCallableDecl) -> dict[BackendBlockId, BackendBlock]:
    block_by_id: dict[BackendBlockId, BackendBlock] = {}
    for block in sorted(callable_decl.blocks, key=block_sort_key):
        if block.block_id.owner_id != callable_decl.callable_id:
            raise BackendCfgError(
                f"Callable '{_callable_name(callable_decl)}' contains block '{_block_name(block.block_id)}' "
                "owned by a different callable"
            )
        if block.block_id in block_by_id:
            raise BackendCfgError(
                f"Callable '{_callable_name(callable_decl)}' declares duplicate block '{_block_name(block.block_id)}'"
            )
        block_by_id[block.block_id] = block
    return block_by_id


def build_successor_map(
    callable_decl: BackendCallableDecl,
    *,
    block_by_id: dict[BackendBlockId, BackendBlock] | None = None,
) -> dict[BackendBlockId, tuple[BackendBlockId, ...]]:
    block_index = build_block_index(callable_decl) if block_by_id is None else block_by_id
    if callable_decl.is_extern:
        return {}

    _require_entry_block(callable_decl, block_index)

    successor_by_block: dict[BackendBlockId, tuple[BackendBlockId, ...]] = {}
    for block in sorted(callable_decl.blocks, key=block_sort_key):
        terminator = block.terminator
        if isinstance(terminator, BackendJumpTerminator):
            _require_declared_successor(callable_decl, block, terminator.target_block_id, block_index)
            successor_by_block[block.block_id] = (terminator.target_block_id,)
            continue
        if isinstance(terminator, BackendBranchTerminator):
            _require_declared_successor(callable_decl, block, terminator.true_block_id, block_index)
            _require_declared_successor(callable_decl, block, terminator.false_block_id, block_index)
            if terminator.true_block_id == terminator.false_block_id:
                raise BackendCfgError(
                    f"Callable '{_callable_name(callable_decl)}' block '{block.debug_name}' branches to the same "
                    "successor on both edges"
                )
            successor_by_block[block.block_id] = (terminator.true_block_id, terminator.false_block_id)
            continue
        if isinstance(terminator, (BackendReturnTerminator, BackendTrapTerminator)):
            successor_by_block[block.block_id] = ()
            continue
        raise BackendCfgError(
            f"Callable '{_callable_name(callable_decl)}' block '{block.debug_name}' uses unsupported terminator "
            f"'{type(terminator).__name__}'"
        )
    return successor_by_block


def build_predecessor_map(
    callable_decl: BackendCallableDecl,
    *,
    successor_by_block: dict[BackendBlockId, tuple[BackendBlockId, ...]] | None = None,
    block_by_id: dict[BackendBlockId, BackendBlock] | None = None,
) -> dict[BackendBlockId, tuple[BackendBlockId, ...]]:
    block_index = build_block_index(callable_decl) if block_by_id is None else block_by_id
    successor_index = (
        build_successor_map(callable_decl, block_by_id=block_index)
        if successor_by_block is None
        else successor_by_block
    )
    predecessor_lists = {block_id: [] for block_id in block_index}
    for source_block_id in sorted(successor_index, key=lambda block_id: block_id.ordinal):
        for successor_block_id in successor_index[source_block_id]:
            predecessor_lists[successor_block_id].append(source_block_id)
    return {
        block_id: tuple(predecessor_lists[block_id])
        for block_id in sorted(predecessor_lists, key=lambda block_id: block_id.ordinal)
    }


def reachable_block_ids(
    callable_decl: BackendCallableDecl,
    *,
    successor_by_block: dict[BackendBlockId, tuple[BackendBlockId, ...]] | None = None,
    block_by_id: dict[BackendBlockId, BackendBlock] | None = None,
) -> frozenset[BackendBlockId]:
    if callable_decl.is_extern:
        return frozenset()

    block_index = build_block_index(callable_decl) if block_by_id is None else block_by_id
    successor_index = (
        build_successor_map(callable_decl, block_by_id=block_index)
        if successor_by_block is None
        else successor_by_block
    )
    entry_block_id = _require_entry_block(callable_decl, block_index)
    reachable: set[BackendBlockId] = set()
    stack = [entry_block_id]
    while stack:
        block_id = stack.pop()
        if block_id in reachable:
            continue
        reachable.add(block_id)
        stack.extend(reversed(successor_index[block_id]))
    return frozenset(reachable)


def reverse_postorder_block_ids(
    callable_decl: BackendCallableDecl,
    *,
    successor_by_block: dict[BackendBlockId, tuple[BackendBlockId, ...]] | None = None,
    block_by_id: dict[BackendBlockId, BackendBlock] | None = None,
) -> tuple[BackendBlockId, ...]:
    if callable_decl.is_extern:
        return ()

    block_index = build_block_index(callable_decl) if block_by_id is None else block_by_id
    successor_index = (
        build_successor_map(callable_decl, block_by_id=block_index)
        if successor_by_block is None
        else successor_by_block
    )
    entry_block_id = _require_entry_block(callable_decl, block_index)
    visited: set[BackendBlockId] = set()
    postorder: list[BackendBlockId] = []

    def visit(block_id: BackendBlockId) -> None:
        if block_id in visited:
            return
        visited.add(block_id)
        for successor_block_id in successor_index[block_id]:
            visit(successor_block_id)
        postorder.append(block_id)

    visit(entry_block_id)
    return tuple(reversed(postorder))


def iter_block_instructions(block: BackendBlock) -> tuple[BackendInstruction, ...]:
    return tuple(sorted(block.instructions, key=instruction_sort_key))


def iter_callable_instructions(
    callable_decl: BackendCallableDecl,
    *,
    block_ids: Iterable[BackendBlockId] | None = None,
    block_by_id: dict[BackendBlockId, BackendBlock] | None = None,
) -> tuple[BackendInstruction, ...]:
    block_index = build_block_index(callable_decl) if block_by_id is None else block_by_id
    ordered_block_ids = (
        tuple(block.block_id for block in sorted(callable_decl.blocks, key=block_sort_key))
        if block_ids is None
        else tuple(block_ids)
    )
    instructions: list[BackendInstruction] = []
    for block_id in ordered_block_ids:
        instructions.extend(iter_block_instructions(block_index[block_id]))
    return tuple(instructions)


def index_callable_cfg(callable_decl: BackendCallableDecl) -> BackendCallableCfg:
    block_by_id = build_block_index(callable_decl)
    successor_by_block = build_successor_map(callable_decl, block_by_id=block_by_id)
    predecessor_by_block = build_predecessor_map(
        callable_decl,
        successor_by_block=successor_by_block,
        block_by_id=block_by_id,
    )
    reachable_ids = reachable_block_ids(
        callable_decl,
        successor_by_block=successor_by_block,
        block_by_id=block_by_id,
    )
    reverse_postorder_ids = reverse_postorder_block_ids(
        callable_decl,
        successor_by_block=successor_by_block,
        block_by_id=block_by_id,
    )
    return BackendCallableCfg(
        callable_decl=callable_decl,
        block_by_id=block_by_id,
        successor_by_block=successor_by_block,
        predecessor_by_block=predecessor_by_block,
        reachable_block_ids=reachable_ids,
        reverse_postorder_block_ids=reverse_postorder_ids,
    )


def _require_entry_block(
    callable_decl: BackendCallableDecl,
    block_by_id: dict[BackendBlockId, BackendBlock],
) -> BackendBlockId:
    entry_block_id = callable_decl.entry_block_id
    if entry_block_id is None:
        raise BackendCfgError(f"Callable '{_callable_name(callable_decl)}' is missing an entry block")
    if entry_block_id not in block_by_id:
        raise BackendCfgError(
            f"Callable '{_callable_name(callable_decl)}' entry block '{_block_name(entry_block_id)}' is not declared"
        )
    return entry_block_id


def _require_declared_successor(
    callable_decl: BackendCallableDecl,
    block: BackendBlock,
    successor_block_id: BackendBlockId,
    block_by_id: dict[BackendBlockId, BackendBlock],
) -> None:
    if successor_block_id.owner_id != callable_decl.callable_id or successor_block_id not in block_by_id:
        raise BackendCfgError(
            f"Callable '{_callable_name(callable_decl)}' block '{block.debug_name}' references undeclared "
            f"successor '{_block_name(successor_block_id)}'"
        )


def _callable_name(callable_decl: BackendCallableDecl) -> str:
    callable_id = callable_decl.callable_id
    pieces = [*callable_id.module_path]
    class_name = getattr(callable_id, "class_name", None)
    name = getattr(callable_id, "name", None)
    ordinal = getattr(callable_id, "ordinal", None)
    if class_name is not None:
        pieces.append(class_name)
    if name is not None:
        pieces.append(name)
    elif ordinal is not None:
        pieces.append(f"#{ordinal}")
    return ".".join(pieces)


def _block_name(block_id: BackendBlockId) -> str:
    return f"b{block_id.ordinal}"