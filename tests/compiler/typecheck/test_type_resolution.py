import pytest

from compiler.frontend.ast_nodes import (
    BlockStmt,
    CastExpr,
    FunctionDecl,
    FunctionTypeRef,
    IdentifierExpr,
    LiteralExpr,
    ModuleAst,
    ParamDecl,
    ReturnStmt,
    TypeRef,
    VarDeclStmt,
)
from compiler.frontend.lexer import SourcePos, SourceSpan
from compiler.typecheck.api import typecheck
from compiler.typecheck.model import TypeCheckError
from tests.compiler.typecheck.helpers import parse_and_typecheck


def test_typecheck_rejects_unknown_type_annotation() -> None:
    source = """
fn main() -> unit {
    var value: Missing = null;
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Unknown type 'Missing'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_casts_involving_function_types() -> None:
    pos = SourcePos(path="<memory>", offset=0, line=1, column=1)
    span = SourceSpan(start=pos, end=pos)
    fn_type = FunctionTypeRef(
        param_types=[TypeRef(name="i64", span=span)], return_type=TypeRef(name="i64", span=span), span=span
    )
    source = ModuleAst(
        imports=[],
        classes=[],
        functions=[
            FunctionDecl(
                name="add",
                params=[ParamDecl(name="x", type_ref=TypeRef(name="i64", span=span), span=span)],
                return_type=TypeRef(name="i64", span=span),
                body=BlockStmt(statements=[ReturnStmt(value=LiteralExpr(value="1", span=span), span=span)], span=span),
                is_export=False,
                is_extern=False,
                span=span,
            ),
            FunctionDecl(
                name="main",
                params=[],
                return_type=TypeRef(name="unit", span=span),
                body=BlockStmt(
                    statements=[
                        VarDeclStmt(
                            name="f", type_ref=fn_type, initializer=IdentifierExpr(name="add", span=span), span=span
                        ),
                        VarDeclStmt(
                            name="g",
                            type_ref=fn_type,
                            initializer=CastExpr(
                                type_ref=fn_type, operand=IdentifierExpr(name="f", span=span), span=span
                            ),
                            span=span,
                        ),
                    ],
                    span=span,
                ),
                is_export=False,
                is_extern=False,
                span=span,
            ),
        ],
        span=span,
    )
    with pytest.raises(TypeCheckError, match="Casts involving function types are not allowed in MVP"):
        typecheck(source)
