from __future__ import annotations

from compiler.semantic.ir import (
    IndexLValue,
    LocalLValue,
    SemanticAssign,
    SemanticBlock,
    SemanticBreak,
    SemanticContinue,
    SemanticExprStmt,
    SemanticForIn,
    SemanticIf,
    SemanticReturn,
    SemanticStmt,
    SemanticVarDecl,
    SemanticWhile,
    SliceLValue,
)
from compiler.semantic.symbols import LocalId


def assigned_local_ids_in_block(block: SemanticBlock) -> set[LocalId]:
    assigned_local_ids: set[LocalId] = set()
    for stmt in block.statements:
        assigned_local_ids.update(assigned_local_ids_in_stmt(stmt))
    return assigned_local_ids


def assigned_local_ids_in_stmt(stmt: SemanticStmt) -> set[LocalId]:
    if isinstance(stmt, SemanticBlock):
        return assigned_local_ids_in_block(stmt)

    if isinstance(stmt, SemanticAssign):
        if isinstance(stmt.target, LocalLValue):
            return {stmt.target.local_id}
        if isinstance(stmt.target, (IndexLValue, SliceLValue)):
            return set()
        return set()

    if isinstance(stmt, SemanticIf):
        assigned_local_ids = assigned_local_ids_in_block(stmt.then_block)
        if stmt.else_block is not None:
            assigned_local_ids.update(assigned_local_ids_in_block(stmt.else_block))
        return assigned_local_ids

    if isinstance(stmt, SemanticWhile):
        return assigned_local_ids_in_block(stmt.body)

    if isinstance(stmt, SemanticForIn):
        return assigned_local_ids_in_block(stmt.body)

    if isinstance(
        stmt,
        (
            SemanticVarDecl,
            SemanticExprStmt,
            SemanticReturn,
            SemanticBreak,
            SemanticContinue,
        ),
    ):
        return set()

    raise TypeError(f"Unsupported semantic statement when collecting assigned locals: {type(stmt).__name__}")