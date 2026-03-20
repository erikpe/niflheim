from __future__ import annotations

from collections.abc import Callable

from compiler.codegen.linker import CodegenProgram
from compiler.semantic.ir import *


def walk_codegen_program_expressions(program: CodegenProgram, visit_expr: Callable[[SemanticExpr], None]) -> None:
    for fn in program.functions:
        if fn.body is not None:
            walk_block_expressions(fn.body, visit_expr)
    for cls in program.classes:
        for field in cls.fields:
            if field.initializer is not None:
                walk_expression(field.initializer, visit_expr)
        for method in cls.methods:
            walk_block_expressions(method.body, visit_expr)


def walk_block_expressions(block: SemanticBlock, visit_expr: Callable[[SemanticExpr], None]) -> None:
    for stmt in block.statements:
        walk_statement_expressions(stmt, visit_expr)


def walk_statement_expressions(stmt: SemanticStmt, visit_expr: Callable[[SemanticExpr], None]) -> None:
    if isinstance(stmt, SemanticBlock):
        walk_block_expressions(stmt, visit_expr)
        return
    if isinstance(stmt, SemanticVarDecl):
        if stmt.initializer is not None:
            walk_expression(stmt.initializer, visit_expr)
        return
    if isinstance(stmt, SemanticAssign):
        walk_expression(stmt.value, visit_expr)
        return
    if isinstance(stmt, SemanticExprStmt):
        walk_expression(stmt.expr, visit_expr)
        return
    if isinstance(stmt, SemanticReturn):
        if stmt.value is not None:
            walk_expression(stmt.value, visit_expr)
        return
    if isinstance(stmt, SemanticIf):
        walk_expression(stmt.condition, visit_expr)
        walk_block_expressions(stmt.then_block, visit_expr)
        if stmt.else_block is not None:
            walk_block_expressions(stmt.else_block, visit_expr)
        return
    if isinstance(stmt, SemanticWhile):
        walk_expression(stmt.condition, visit_expr)
        walk_block_expressions(stmt.body, visit_expr)
        return
    if isinstance(stmt, SemanticForIn):
        walk_expression(stmt.collection, visit_expr)
        walk_block_expressions(stmt.body, visit_expr)


def walk_expression(expr: SemanticExpr, visit_expr: Callable[[SemanticExpr], None]) -> None:
    visit_expr(expr)

    if isinstance(expr, CastExprS):
        walk_expression(expr.operand, visit_expr)
        return
    if isinstance(expr, UnaryExprS):
        walk_expression(expr.operand, visit_expr)
        return
    if isinstance(expr, BinaryExprS):
        walk_expression(expr.left, visit_expr)
        walk_expression(expr.right, visit_expr)
        return
    if isinstance(expr, FieldReadExpr):
        walk_expression(expr.receiver, visit_expr)
        return
    if isinstance(expr, FunctionCallExpr | StaticMethodCallExpr | ConstructorCallExpr):
        for arg in expr.args:
            walk_expression(arg, visit_expr)
        return
    if isinstance(expr, CallableValueCallExpr):
        for arg in expr.args:
            walk_expression(arg, visit_expr)
        walk_expression(expr.callee, visit_expr)
        return
    if isinstance(expr, InstanceMethodCallExpr):
        walk_expression(expr.receiver, visit_expr)
        for arg in expr.args:
            walk_expression(arg, visit_expr)
        return
    if isinstance(expr, InterfaceMethodCallExpr):
        walk_expression(expr.receiver, visit_expr)
        for arg in expr.args:
            walk_expression(arg, visit_expr)
        return
    if isinstance(expr, ArrayLenExpr):
        walk_expression(expr.target, visit_expr)
        return
    if isinstance(expr, IndexReadExpr):
        walk_expression(expr.target, visit_expr)
        walk_expression(expr.index, visit_expr)
        return
    if isinstance(expr, SliceReadExpr):
        walk_expression(expr.target, visit_expr)
        walk_expression(expr.begin, visit_expr)
        walk_expression(expr.end, visit_expr)
        return
    if isinstance(expr, ArrayCtorExprS):
        walk_expression(expr.length_expr, visit_expr)
        return
    if isinstance(expr, SyntheticExpr):
        for arg in expr.args:
            walk_expression(arg, visit_expr)
