from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from compiler.ast_nodes import BlockStmt, Expression, FieldAccessExpr, Statement, TypeRefNode
from compiler.lexer import SourceSpan
from compiler.typecheck.model import ClassInfo, FunctionSig, TypeInfo


@dataclass(slots=True)
class TypeCheckOps:
    resolve_type_ref: Callable[[TypeRefNode], TypeInfo]
    declare_variable: Callable[[str, TypeInfo, SourceSpan], None]
    check_block: Callable[[BlockStmt, TypeInfo], None]
    block_guarantees_return: Callable[[BlockStmt], bool]
    push_scope: Callable[[], None]
    pop_scope: Callable[[], None]
    canonicalize_reference_type_name: Callable[[str], str]
    check_statement: Callable[[Statement, TypeInfo], None]
    infer_expression_type: Callable[[Expression], TypeInfo]
    require_assignable: Callable[[TypeInfo, TypeInfo, SourceSpan], None]
    require_type_name: Callable[[TypeInfo, str, SourceSpan], None]
    resolve_for_in_element_type: Callable[[TypeInfo, SourceSpan], TypeInfo]
    ensure_assignable_target: Callable[[Expression], None]
    ensure_index_assignment: Callable[[TypeInfo, Expression, TypeInfo, SourceSpan], None]
    lookup_variable: Callable[[str], TypeInfo | None]
    require_array_size_type: Callable[[TypeInfo, SourceSpan], None]
    is_comparable: Callable[[TypeInfo, TypeInfo], bool]
    check_explicit_cast: Callable[[TypeInfo, TypeInfo, SourceSpan], None]
    require_member_visible: Callable[[ClassInfo, str, str, str, SourceSpan], None]
    ensure_field_access_assignable: Callable[[FieldAccessExpr], None]
    ensure_structural_set_method_available_for_index_assignment: Callable[[TypeInfo, SourceSpan], FunctionSig]
    lookup_class_by_type_name: Callable[[str], ClassInfo | None]
    resolve_structural_slice_method_result_type: Callable[[TypeInfo, ClassInfo, list[Expression], SourceSpan], TypeInfo]
    resolve_structural_set_slice_method_result_type: Callable[[
        TypeInfo, ClassInfo, list[Expression], SourceSpan], TypeInfo]
