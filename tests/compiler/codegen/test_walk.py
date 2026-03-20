from __future__ import annotations

from pathlib import Path

from compiler.codegen.linker import CodegenProgram
from compiler.codegen.walk import (
    walk_block_expressions,
    walk_codegen_program_expressions,
    walk_expression,
    walk_statement_expressions,
)
from compiler.frontend.lexer import SourcePos, SourceSpan
from compiler.semantic.ir import *
from compiler.semantic.symbols import ClassId, FunctionId, MethodId


def _span() -> SourceSpan:
    pos = SourcePos(path="<test>", offset=0, line=1, column=1)
    return SourceSpan(start=pos, end=pos)


def _describe_expr(expr: SemanticExpr) -> str:
    if isinstance(expr, LocalRefExpr):
        return f"LocalRefExpr:{expr.name}"
    if isinstance(expr, LiteralExprS):
        return f"LiteralExprS:{expr.value}"
    return type(expr).__name__


def test_walk_expression_visits_callable_value_call_in_preorder() -> None:
    span = _span()
    expr = CallableValueCallExpr(
        callee=FieldReadExpr(
            receiver=LocalRefExpr(name="receiver", type_name="Box", span=span),
            receiver_type_name="Box",
            field_name="invoke",
            field_type_name="fn(i64) -> i64",
            span=span,
        ),
        args=[
            CastExprS(
                operand=BinaryExprS(
                    operator="+",
                    left=LiteralExprS(value="1", type_name="i64", span=span),
                    right=LocalRefExpr(name="arg", type_name="i64", span=span),
                    type_name="i64",
                    span=span,
                ),
                target_type_name="i64",
                type_name="i64",
                span=span,
            )
        ],
        type_name="i64",
        span=span,
    )

    seen: list[str] = []
    walk_expression(expr, lambda current: seen.append(_describe_expr(current)))

    assert seen == [
        "CallableValueCallExpr",
        "CastExprS",
        "BinaryExprS",
        "LiteralExprS:1",
        "LocalRefExpr:arg",
        "FieldReadExpr",
        "LocalRefExpr:receiver",
    ]


def test_walk_statement_expressions_skips_assignment_target_expressions() -> None:
    span = _span()
    stmt = SemanticAssign(
        target=FieldLValue(
            receiver=LocalRefExpr(name="target_receiver", type_name="Box", span=span),
            receiver_type_name="Box",
            field_name="value",
            field_type_name="i64",
            span=span,
        ),
        value=FunctionCallExpr(
            function_id=FunctionId(module_path=("main",), name="compute"),
            args=[LiteralExprS(value="7", type_name="i64", span=span)],
            type_name="i64",
            span=span,
        ),
        span=span,
    )

    seen: list[str] = []
    walk_statement_expressions(stmt, lambda expr: seen.append(_describe_expr(expr)))

    assert seen == ["FunctionCallExpr", "LiteralExprS:7"]


def test_walk_block_expressions_visits_nested_control_flow_expressions() -> None:
    span = _span()
    block = SemanticBlock(
        statements=[
            SemanticIf(
                condition=LocalRefExpr(name="if_cond", type_name="bool", span=span),
                then_block=SemanticBlock(
                    statements=[
                        SemanticExprStmt(expr=LocalRefExpr(name="then_expr", type_name="i64", span=span), span=span)
                    ],
                    span=span,
                ),
                else_block=SemanticBlock(
                    statements=[
                        SemanticReturn(value=LocalRefExpr(name="else_expr", type_name="i64", span=span), span=span)
                    ],
                    span=span,
                ),
                span=span,
            ),
            SemanticWhile(
                condition=LocalRefExpr(name="while_cond", type_name="bool", span=span),
                body=SemanticBlock(
                    statements=[
                        SemanticExprStmt(expr=LocalRefExpr(name="while_expr", type_name="i64", span=span), span=span)
                    ],
                    span=span,
                ),
                span=span,
            ),
            SemanticForIn(
                element_name="value",
                collection=LocalRefExpr(name="collection", type_name="Vec", span=span),
                iter_len_method=None,
                iter_get_method=None,
                element_type_name="i64",
                body=SemanticBlock(
                    statements=[
                        SemanticExprStmt(expr=LocalRefExpr(name="for_expr", type_name="i64", span=span), span=span)
                    ],
                    span=span,
                ),
                span=span,
            ),
        ],
        span=span,
    )

    seen: list[str] = []
    walk_block_expressions(block, lambda expr: seen.append(_describe_expr(expr)))

    assert seen == [
        "LocalRefExpr:if_cond",
        "LocalRefExpr:then_expr",
        "LocalRefExpr:else_expr",
        "LocalRefExpr:while_cond",
        "LocalRefExpr:while_expr",
        "LocalRefExpr:collection",
        "LocalRefExpr:for_expr",
    ]


def test_walk_codegen_program_expressions_visits_functions_fields_and_methods() -> None:
    span = _span()
    fn = SemanticFunction(
        function_id=FunctionId(module_path=("main",), name="main"),
        params=[],
        return_type_name="i64",
        body=SemanticBlock(
            statements=[SemanticReturn(value=LocalRefExpr(name="fn_expr", type_name="i64", span=span), span=span)],
            span=span,
        ),
        is_export=False,
        is_extern=False,
        span=span,
    )
    cls = SemanticClass(
        class_id=ClassId(module_path=("main",), name="Box"),
        is_export=False,
        fields=[
            SemanticField(
                name="value",
                type_name="i64",
                initializer=LiteralExprS(value="3", type_name="i64", span=span),
                is_private=False,
                is_final=False,
                span=span,
            )
        ],
        methods=[
            SemanticMethod(
                method_id=MethodId(module_path=("main",), class_name="Box", name="read"),
                params=[],
                return_type_name="i64",
                body=SemanticBlock(
                    statements=[
                        SemanticReturn(value=LocalRefExpr(name="method_expr", type_name="i64", span=span), span=span)
                    ],
                    span=span,
                ),
                is_static=False,
                is_private=False,
                span=span,
            )
        ],
        span=span,
    )
    module = SemanticModule(module_path=("main",), file_path=Path("main.nif"), classes=[cls], functions=[fn], span=span)
    program = CodegenProgram(
        entry_module=("main",), ordered_modules=(module,), classes=(cls,), functions=(fn,), span=span
    )

    seen: list[str] = []
    walk_codegen_program_expressions(program, lambda expr: seen.append(_describe_expr(expr)))

    assert seen == ["LocalRefExpr:fn_expr", "LiteralExprS:3", "LocalRefExpr:method_expr"]


def test_walk_expression_visits_interface_method_call_receiver_and_args() -> None:
    span = _span()
    expr = InterfaceMethodCallExpr(
        interface_id=InterfaceId(module_path=("main",), name="Hashable"),
        method_id=InterfaceMethodId(module_path=("main",), interface_name="Hashable", name="hash_code"),
        receiver=LocalRefExpr(name="receiver", type_name="Hashable", span=span),
        receiver_type_name="Hashable",
        args=[LocalRefExpr(name="arg", type_name="Obj", span=span)],
        type_name="u64",
        span=span,
    )

    seen: list[str] = []
    walk_expression(expr, lambda current: seen.append(_describe_expr(current)))

    assert seen == [
        "InterfaceMethodCallExpr",
        "LocalRefExpr:receiver",
        "LocalRefExpr:arg",
    ]


def test_walk_codegen_program_expressions_visits_interface_method_calls_in_function_bodies() -> None:
    span = _span()
    fn = SemanticFunction(
        function_id=FunctionId(module_path=("main",), name="main"),
        params=[],
        return_type_name="u64",
        body=SemanticBlock(
            statements=[
                SemanticReturn(
                    value=InterfaceMethodCallExpr(
                        interface_id=InterfaceId(module_path=("main",), name="Hashable"),
                        method_id=InterfaceMethodId(module_path=("main",), interface_name="Hashable", name="hash_code"),
                        receiver=LocalRefExpr(name="receiver", type_name="Hashable", span=span),
                        receiver_type_name="Hashable",
                        args=[LocalRefExpr(name="other", type_name="Obj", span=span)],
                        type_name="u64",
                        span=span,
                    ),
                    span=span,
                )
            ],
            span=span,
        ),
        is_extern=False,
        is_export=False,
        span=span,
    )
    module = SemanticModule(module_path=("main",), file_path=Path("main.nif"), classes=[], functions=[fn], span=span)
    program = CodegenProgram(entry_module=("main",), ordered_modules=(module,), classes=(), functions=(fn,), span=span)

    seen: list[str] = []
    walk_codegen_program_expressions(program, lambda expr: seen.append(_describe_expr(expr)))

    assert seen == [
        "InterfaceMethodCallExpr",
        "LocalRefExpr:receiver",
        "LocalRefExpr:other",
    ]
