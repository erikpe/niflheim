from __future__ import annotations

from pathlib import Path

from compiler.common.collection_protocols import ArrayRuntimeKind, CollectionOpKind
from compiler.codegen.walk import (
    walk_block_expressions,
    walk_codegen_program_expressions,
    walk_expression,
    walk_statement_expressions,
)
from compiler.common.span import SourcePos, SourceSpan
from compiler.semantic.ir import *
from compiler.semantic.linker import LinkedSemanticProgram
from compiler.semantic.symbols import ClassId, FunctionId, InterfaceId, InterfaceMethodId, LocalId, MethodId


def _span() -> SourceSpan:
    pos = SourcePos(path="<test>", offset=0, line=1, column=1)
    return SourceSpan(start=pos, end=pos)


def _describe_expr(expr: SemanticExpr) -> str:
    if isinstance(expr, LocalRefExpr):
        return f"LocalRefExpr:{expr.name}"
    if isinstance(expr, LiteralExprS):
        return f"LiteralExprS:{_describe_constant(expr.constant)}"
    return type(expr).__name__


def _describe_constant(constant: SemanticConstant) -> str:
    if isinstance(constant, BoolConstant):
        return "true" if constant.value else "false"
    return str(constant.value)


def _local_ref(name: str, type_name: str, span: SourceSpan) -> LocalRefExpr:
    return LocalRefExpr(
        local_id=LocalId(owner_id=FunctionId(module_path=("test",), name="walk"), ordinal=sum(ord(ch) for ch in name)),
        name=name,
        type_name=type_name,
        span=span,
    )


def test_walk_expression_visits_callable_value_call_in_preorder() -> None:
    span = _span()
    expr = CallableValueCallExpr(
        callee=FieldReadExpr(
            receiver=_local_ref("receiver", "Box", span),
            receiver_type_name="Box",
            owner_class_id=ClassId(module_path=("main",), name="Box"),
            field_name="invoke",
            type_name="fn(i64) -> i64",
            span=span,
        ),
        args=[
            CastExprS(
                operand=BinaryExprS(
                    operator="+",
                    left=LiteralExprS(constant=IntConstant(value=1, type_name="i64"), type_name="i64", span=span),
                    right=_local_ref("arg", "i64", span),
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


def test_walk_expression_visits_type_test_operand_in_preorder() -> None:
    span = _span()
    expr = TypeTestExprS(
        operand=BinaryExprS(
            operator="+",
            left=LiteralExprS(constant=IntConstant(value=1, type_name="i64"), type_name="i64", span=span),
            right=_local_ref("arg", "i64", span),
            type_name="i64",
            span=span,
        ),
        target_type_name="Box",
        type_name="bool",
        span=span,
    )

    seen: list[str] = []
    walk_expression(expr, lambda current: seen.append(_describe_expr(current)))

    assert seen == [
        "TypeTestExprS",
        "BinaryExprS",
        "LiteralExprS:1",
        "LocalRefExpr:arg",
    ]


def test_walk_statement_expressions_skips_assignment_target_expressions() -> None:
    span = _span()
    stmt = SemanticAssign(
        target=FieldLValue(
            receiver=_local_ref("target_receiver", "Box", span),
            receiver_type_name="Box",
            owner_class_id=ClassId(module_path=("main",), name="Box"),
            field_name="value",
            type_name="i64",
            span=span,
        ),
        value=FunctionCallExpr(
            function_id=FunctionId(module_path=("main",), name="compute"),
            args=[LiteralExprS(constant=IntConstant(value=7, type_name="i64"), type_name="i64", span=span)],
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
                condition=_local_ref("if_cond", "bool", span),
                then_block=SemanticBlock(
                    statements=[
                        SemanticExprStmt(expr=_local_ref("then_expr", "i64", span), span=span)
                    ],
                    span=span,
                ),
                else_block=SemanticBlock(
                    statements=[
                        SemanticReturn(value=_local_ref("else_expr", "i64", span), span=span)
                    ],
                    span=span,
                ),
                span=span,
            ),
            SemanticWhile(
                condition=_local_ref("while_cond", "bool", span),
                body=SemanticBlock(
                    statements=[
                        SemanticExprStmt(expr=_local_ref("while_expr", "i64", span), span=span)
                    ],
                    span=span,
                ),
                span=span,
            ),
            SemanticForIn(
                element_name="value",
                element_local_id=LocalId(owner_id=FunctionId(module_path=("test",), name="walk"), ordinal=0),
                collection=_local_ref("collection", "Vec", span),
                iter_len_dispatch=RuntimeDispatch(operation=CollectionOpKind.ITER_LEN),
                iter_get_dispatch=RuntimeDispatch(
                    operation=CollectionOpKind.ITER_GET, runtime_kind=ArrayRuntimeKind.I64
                ),
                element_type_name="i64",
                body=SemanticBlock(
                    statements=[
                        SemanticExprStmt(expr=_local_ref("for_expr", "i64", span), span=span)
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
            statements=[SemanticReturn(value=_local_ref("fn_expr", "i64", span), span=span)],
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
                initializer=LiteralExprS(
                    constant=IntConstant(value=3, type_name="i64"), type_name="i64", span=span
                ),
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
                        SemanticReturn(value=_local_ref("method_expr", "i64", span), span=span)
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
    program = LinkedSemanticProgram(
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
        receiver=_local_ref("receiver", "Hashable", span),
        receiver_type_name="Hashable",
        args=[_local_ref("arg", "Obj", span)],
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
                        receiver=_local_ref("receiver", "Hashable", span),
                        receiver_type_name="Hashable",
                        args=[_local_ref("other", "Obj", span)],
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
    program = LinkedSemanticProgram(
        entry_module=("main",), ordered_modules=(module,), classes=(), functions=(fn,), span=span
    )

    seen: list[str] = []
    walk_codegen_program_expressions(program, lambda expr: seen.append(_describe_expr(expr)))

    assert seen == [
        "InterfaceMethodCallExpr",
        "LocalRefExpr:receiver",
        "LocalRefExpr:other",
    ]
