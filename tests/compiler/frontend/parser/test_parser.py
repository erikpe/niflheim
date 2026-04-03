from dataclasses import fields, is_dataclass

import pytest

from compiler.common.literals import IntLiteralKind
from compiler.frontend.ast_nodes import *
from compiler.common.span import SourceSpan
from compiler.frontend.lexer import lex
from compiler.frontend.parser import ParserError, TokenStream, parse, parse_expression
from compiler.frontend.tokens import TokenKind


def _assert_ast_nodes_have_spans(node: object) -> None:
    if node is None:
        return

    if isinstance(node, (str, int, float, bool)):
        return

    if isinstance(node, list):
        for item in node:
            _assert_ast_nodes_have_spans(item)
        return

    if isinstance(node, tuple):
        for item in node:
            _assert_ast_nodes_have_spans(item)
        return

    if isinstance(node, dict):
        for key, value in node.items():
            _assert_ast_nodes_have_spans(key)
            _assert_ast_nodes_have_spans(value)
        return

    if is_dataclass(node):
        if type(node).__module__ == "compiler.frontend.ast_nodes":
            if hasattr(node, "span"):
                span = getattr(node, "span")
                assert isinstance(span, SourceSpan), f"{type(node).__name__}.span must be SourceSpan"

        for field in fields(node):
            _assert_ast_nodes_have_spans(getattr(node, field.name))


def test_token_stream_peek_and_advance() -> None:
    tokens = lex("fn main() -> unit { return; }")
    stream = TokenStream(tokens)

    assert stream.peek().kind == TokenKind.FN
    assert stream.peek(1).kind == TokenKind.IDENT

    first = stream.advance()
    assert first.kind == TokenKind.FN
    assert stream.peek().kind == TokenKind.IDENT


def test_token_stream_match_and_expect() -> None:
    tokens = lex("return;")
    stream = TokenStream(tokens)

    assert stream.match(TokenKind.RETURN)
    semicolon = stream.expect(TokenKind.SEMICOLON, "Expected ';'")
    assert semicolon.kind == TokenKind.SEMICOLON
    assert stream.is_at_end()


def test_token_stream_expect_raises_with_location() -> None:
    tokens = lex("return", source_path="examples/missing_semicolon.nif")
    stream = TokenStream(tokens)
    stream.expect(TokenKind.RETURN, "Expected return")

    with pytest.raises(ParserError) as error:
        stream.expect(TokenKind.SEMICOLON, "Expected ';'")

    assert "examples/missing_semicolon.nif:1:7" in str(error.value)


def test_token_stream_previous_and_end_behavior() -> None:
    tokens = lex("var x: i64;", source_path="examples/sample.nif")
    stream = TokenStream(tokens)

    assert stream.previous().kind == TokenKind.VAR
    stream.advance()
    assert stream.previous().kind == TokenKind.VAR

    while not stream.is_at_end():
        stream.advance()

    eof1 = stream.peek()
    eof2 = stream.advance()
    assert eof1.kind == TokenKind.EOF
    assert eof2.kind == TokenKind.EOF


def test_parse_module_level_declarations() -> None:
    source = """
import a.b;
export import std.io;

class Point {
    x: i64;
    y: i64;

    fn reset() -> unit {
        return;
    }
}

export fn main() -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/module.nif"))

    assert len(module.imports) == 2
    assert all(isinstance(item, ImportDecl) for item in module.imports)
    assert module.imports[0].module_path == ["a", "b"]
    assert module.imports[0].is_export is False
    assert module.imports[1].module_path == ["std", "io"]
    assert module.imports[1].is_export is True

    assert module.interfaces == []

    assert len(module.classes) == 1
    cls = module.classes[0]
    assert isinstance(cls, ClassDecl)
    assert cls.name == "Point"
    assert cls.is_export is False
    assert cls.implements == []
    assert cls.constructors == []
    assert [field.name for field in cls.fields] == ["x", "y"]
    assert len(cls.methods) == 1
    assert cls.methods[0].name == "reset"
    assert isinstance(cls.methods[0].body, BlockStmt)
    assert len(cls.methods[0].body.statements) == 1
    assert isinstance(cls.methods[0].body.statements[0], ReturnStmt)

    assert len(module.functions) == 1
    fn = module.functions[0]
    assert isinstance(fn, FunctionDecl)
    assert fn.name == "main"
    assert fn.is_export is True
    assert fn.return_type.name == "unit"
    assert isinstance(fn.body, BlockStmt)
    assert len(fn.body.statements) == 1
    assert isinstance(fn.body.statements[0], ReturnStmt)


def test_parse_function_body_statements_and_assignments() -> None:
    source = """
fn main() -> unit {
    var x: i64 = 1;
    x = x + 2;
    foo(x);
    while x < 10 {
        x = x + 1;
    }
    if x > 2 {
        return;
    } else {
        return;
    }
}
"""
    module = parse(lex(source, source_path="examples/body_parse.nif"))
    fn = module.functions[0]
    statements = fn.body.statements

    assert isinstance(statements[0], VarDeclStmt)
    assert isinstance(statements[1], AssignStmt)
    assert isinstance(statements[2], ExprStmt)
    assert isinstance(statements[3], WhileStmt)
    assert isinstance(statements[4], IfStmt)


def test_parse_break_and_continue_statements() -> None:
    source = """
fn main() -> unit {
    while true {
        if false {
            break;
        }
        continue;
    }
    return;
}
"""
    module = parse(lex(source, source_path="examples/break_continue_parse.nif"))
    loop_stmt = module.functions[0].body.statements[0]
    assert isinstance(loop_stmt, WhileStmt)
    assert isinstance(loop_stmt.body.statements[0], IfStmt)
    assert isinstance(loop_stmt.body.statements[0].then_branch.statements[0], BreakStmt)
    assert isinstance(loop_stmt.body.statements[1], ContinueStmt)


def test_parse_for_in_statement() -> None:
    source = """
fn main() -> unit {
    for elem in coll {
        foo(elem);
    }
    return;
}
"""
    module = parse(lex(source, source_path="examples/for_in_parse.nif"))
    fn = module.functions[0]
    for_stmt = fn.body.statements[0]

    assert isinstance(for_stmt, ForInStmt)
    assert for_stmt.element_name == "elem"
    assert isinstance(for_stmt.collection_expr, IdentifierExpr)
    assert for_stmt.collection_expr.name == "coll"
    assert for_stmt.coll_temp_name.startswith("__nif_sugar_for_coll_")
    assert for_stmt.len_temp_name.startswith("__nif_sugar_for_len_")
    assert for_stmt.index_temp_name.startswith("__nif_sugar_for_i_")


def test_parse_static_method_in_class_body() -> None:
    source = """
class Counter {
    static fn add(a: i64, b: i64) -> i64 {
        return a + b;
    }
}
"""
    module = parse(lex(source, source_path="examples/static_method_parse.nif"))

    assert len(module.classes) == 1
    cls = module.classes[0]
    assert cls.constructors == []
    assert len(cls.methods) == 1
    method = cls.methods[0]
    assert method.name == "add"
    assert method.is_static is True


def test_parse_constructor_declarations_in_class_body() -> None:
    source = """
class Counter {
    value: i64;

    constructor() {
        return;
    }

    private constructor(value: i64) {
        __self.value = value;
    }

    fn read() -> i64 {
        return __self.value;
    }
}
"""
    module = parse(lex(source, source_path="examples/constructors_parse.nif"))

    cls = module.classes[0]
    assert len(cls.fields) == 1
    assert len(cls.constructors) == 2
    assert cls.constructors[0].params == []
    assert cls.constructors[0].is_private is False
    assert isinstance(cls.constructors[0].body, BlockStmt)
    assert len(cls.constructors[0].body.statements) == 1
    assert isinstance(cls.constructors[0].body.statements[0], ReturnStmt)

    assert len(cls.constructors[1].params) == 1
    assert cls.constructors[1].params[0].name == "value"
    assert cls.constructors[1].params[0].type_ref.name == "i64"
    assert cls.constructors[1].is_private is True
    assert len(cls.methods) == 1
    assert cls.methods[0].name == "read"


def test_parse_mixed_field_constructor_and_method_members() -> None:
    source = """
class Counter {
    value: i64;

    constructor() {
        return;
    }

    fn read() -> i64 {
        return __self.value;
    }

    private constructor(value: i64) {
        __self.value = value;
    }
}
"""
    module = parse(lex(source, source_path="examples/mixed_constructor_members.nif"))

    cls = module.classes[0]
    assert [field.name for field in cls.fields] == ["value"]
    assert [len(constructor.params) for constructor in cls.constructors] == [0, 1]
    assert [constructor.is_private for constructor in cls.constructors] == [False, True]
    assert [method.name for method in cls.methods] == ["read"]


def test_parse_rejects_constructor_return_type() -> None:
    source = """
class Counter {
    constructor() -> Counter {
        return;
    }
}
"""
    with pytest.raises(ParserError, match="Constructors cannot declare a return type"):
        parse(lex(source, source_path="examples/bad_constructor_return_type.nif"))


def test_parse_rejects_static_constructor() -> None:
    source = """
class Counter {
    static constructor() {
        return;
    }
}
"""
    with pytest.raises(ParserError, match="'static' modifier is not allowed on constructors"):
        parse(lex(source, source_path="examples/static_constructor_parse.nif"))


def test_parse_rejects_final_constructor() -> None:
    source = """
class Counter {
    final constructor() {
        return;
    }
}
"""
    with pytest.raises(ParserError, match="'final' modifier is not allowed on constructors"):
        parse(lex(source, source_path="examples/final_constructor_parse.nif"))


def test_parse_interface_declarations_and_class_implements() -> None:
    source = """
export interface Hashable {
    fn hash_code() -> u64;
}

interface Equalable {
    fn equals(other: Obj) -> bool;
}

class MyKey implements Hashable, Equalable {
    fn hash_code() -> u64 {
        return 42u;
    }

    fn equals(other: Obj) -> bool {
        return false;
    }
}
"""
    module = parse(lex(source, source_path="examples/interfaces_parse.nif"))

    assert len(module.interfaces) == 2
    hashable = module.interfaces[0]
    equalable = module.interfaces[1]

    assert isinstance(hashable, InterfaceDecl)
    assert hashable.name == "Hashable"
    assert hashable.is_export is True
    assert len(hashable.methods) == 1
    assert isinstance(hashable.methods[0], InterfaceMethodDecl)
    assert hashable.methods[0].name == "hash_code"
    assert hashable.methods[0].params == []
    assert hashable.methods[0].return_type.name == "u64"

    assert equalable.name == "Equalable"
    assert equalable.is_export is False
    assert len(equalable.methods) == 1
    assert equalable.methods[0].name == "equals"
    assert len(equalable.methods[0].params) == 1
    assert equalable.methods[0].params[0].name == "other"
    assert equalable.methods[0].params[0].type_ref.name == "Obj"
    assert equalable.methods[0].return_type.name == "bool"

    assert len(module.classes) == 1
    cls = module.classes[0]
    assert [type_ref.name for type_ref in cls.implements] == ["Hashable", "Equalable"]


def test_parse_class_extends_clause_before_implements() -> None:
    source = """
class Derived extends Base implements Hashable {
    fn read() -> i64 {
        return 1;
    }
}
"""
    module = parse(lex(source, source_path="examples/inheritance_parse.nif"))

    cls = module.classes[0]
    assert cls.base_class is not None
    assert cls.base_class.name == "Base"
    assert [type_ref.name for type_ref in cls.implements] == ["Hashable"]


def test_parse_class_without_extends_has_no_base_class() -> None:
    source = """
class Base {
    fn read() -> i64 {
        return 1;
    }
}
"""
    module = parse(lex(source, source_path="examples/no_inheritance_parse.nif"))

    assert module.classes[0].base_class is None


def test_parse_rejects_interface_method_body() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64 {
        return 42u;
    }
}
"""

    with pytest.raises(ParserError, match="Expected ';' after interface method signature"):
        parse(lex(source, source_path="examples/interface_method_body_error.nif"))


def test_parse_rejects_malformed_implements_clause() -> None:
    source = "class MyKey implements Hashable, { }"

    with pytest.raises(ParserError, match="Expected type name"):
        parse(lex(source, source_path="examples/malformed_implements.nif"))


def test_parse_private_field_and_methods_in_class_body() -> None:
    source = """
class Counter {
    private value: i64;

    private fn get_value() -> i64 {
        return __self.value;
    }

    private static fn from_i64(value: i64) -> Counter {
        return Counter(value);
    }
}
"""
    module = parse(lex(source, source_path="examples/private_members_parse.nif"))

    cls = module.classes[0]
    assert len(cls.fields) == 1
    assert cls.constructors == []
    assert cls.fields[0].name == "value"
    assert cls.fields[0].is_private is True

    assert len(cls.methods) == 2
    assert cls.methods[0].name == "get_value"
    assert cls.methods[0].is_private is True
    assert cls.methods[0].is_static is False
    assert cls.methods[1].name == "from_i64"
    assert cls.methods[1].is_private is True
    assert cls.methods[1].is_static is True


def test_parse_final_field_modifiers_in_class_body() -> None:
    source = """
class Counter {
    final value: i64;
    private final secret: i64;
}
"""
    module = parse(lex(source, source_path="examples/final_fields_parse.nif"))

    cls = module.classes[0]
    assert len(cls.fields) == 2
    assert cls.fields[0].name == "value"
    assert cls.fields[0].is_final is True
    assert cls.fields[0].is_private is False
    assert cls.fields[1].name == "secret"
    assert cls.fields[1].is_final is True
    assert cls.fields[1].is_private is True


def test_parse_rejects_final_modifier_on_method() -> None:
    source = """
class Counter {
    final fn value() -> i64 {
        return 1;
    }
}
"""
    with pytest.raises(ParserError, match="'final' modifier is only allowed on fields"):
        parse(lex(source, source_path="examples/final_method_parse.nif"))


def test_parse_rejects_duplicate_private_modifier() -> None:
    source = """
class Counter {
    private private value: i64;
}
"""
    with pytest.raises(ParserError, match="Duplicate 'private' modifier"):
        parse(lex(source, source_path="examples/dup_private_parse.nif"))


def test_parse_rejects_duplicate_final_modifier() -> None:
    source = """
class Counter {
    final final value: i64;
}
"""
    with pytest.raises(ParserError, match="Duplicate 'final' modifier"):
        parse(lex(source, source_path="examples/dup_final_parse.nif"))


def test_parse_rejects_duplicate_private_with_mixed_order() -> None:
    source = """
class Counter {
    private final private value: i64;
}
"""
    with pytest.raises(ParserError, match="Duplicate 'private' modifier"):
        parse(lex(source, source_path="examples/dup_private_mixed_parse.nif"))


def test_parse_rejects_duplicate_final_with_mixed_order() -> None:
    source = """
class Counter {
    final private final value: i64;
}
"""
    with pytest.raises(ParserError, match="Duplicate 'final' modifier"):
        parse(lex(source, source_path="examples/dup_final_mixed_parse.nif"))


def test_parse_export_requires_import_class_or_fn() -> None:
    source = "export return;"
    with pytest.raises(ParserError) as error:
        parse(lex(source, source_path="examples/bad_export.nif"))

    assert "Expected 'import', 'class', 'interface', 'fn', or 'extern fn' after 'export'" in str(error.value)
    assert "examples/bad_export.nif" in str(error.value)


def test_parse_vec_type_and_static_call_via_identifier_path() -> None:
    source = """
fn main() -> unit {
    var v: Vec = Vec.new();
    return;
}
"""
    module = parse(lex(source, source_path="examples/vec_ident_parse.nif"))

    fn = module.functions[0]
    decl = fn.body.statements[0]
    assert isinstance(decl, VarDeclStmt)
    assert isinstance(decl.type_ref, TypeRef)
    assert decl.type_ref.name == "Vec"

    assert isinstance(decl.initializer, CallExpr)
    assert isinstance(decl.initializer.callee, FieldAccessExpr)
    assert isinstance(decl.initializer.callee.object_expr, IdentifierExpr)
    assert decl.initializer.callee.object_expr.name == "Vec"
    assert decl.initializer.callee.field_name == "new"


def test_parse_extern_and_export_extern_function_declarations() -> None:
    source = """
extern fn rt_gc_collect(ts: Obj) -> unit;
export extern fn rt_panic(msg: Str) -> unit;
"""
    module = parse(lex(source, source_path="examples/extern.nif"))

    assert len(module.functions) == 2

    local = module.functions[0]
    assert local.name == "rt_gc_collect"
    assert local.is_export is False
    assert local.is_extern is True
    assert local.body is None
    assert local.params[0].type_ref.name == "Obj"

    exported = module.functions[1]
    assert exported.name == "rt_panic"
    assert exported.is_export is True
    assert exported.is_extern is True
    assert exported.body is None
    assert exported.params[0].type_ref.name == "Str"


def test_parse_unterminated_block_raises_parser_error() -> None:
    source = "fn main() -> unit {"
    with pytest.raises(ParserError) as error:
        parse(lex(source, source_path="examples/bad_block.nif"))

    assert "Unterminated block" in str(error.value)
    assert "examples/bad_block.nif" in str(error.value)


def test_parse_invalid_assignment_target_raises_parser_error() -> None:
    source = "fn main() -> unit { 1 = 2; }"
    with pytest.raises(ParserError) as error:
        parse(lex(source, source_path="examples/bad_assign.nif"))

    assert "Invalid assignment target" in str(error.value)
    assert "examples/bad_assign.nif" in str(error.value)


def test_parse_expression_precedence_multiplicative_over_additive() -> None:
    expr = parse_expression(lex("1 + 2 * 3", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "+"
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "*"


def test_parse_expression_precedence_power_over_multiplicative() -> None:
    expr = parse_expression(lex("2 * 3 ** 4", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "*"
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "**"


def test_parse_expression_power_is_right_associative() -> None:
    expr = parse_expression(lex("2 ** 3 ** 2", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "**"
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "**"


def test_parse_expression_precedence_additive_over_shift() -> None:
    expr = parse_expression(lex("1 + 2 << 3", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "<<"
    assert isinstance(expr.left, BinaryExpr)
    assert expr.left.operator == "+"


def test_parse_expression_precedence_shift_over_comparison() -> None:
    expr = parse_expression(lex("x << 1u < y", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "<"
    assert isinstance(expr.left, BinaryExpr)
    assert expr.left.operator == "<<"


def test_parse_expression_char_literal() -> None:
    expr = parse_expression(lex("'q'", source_path="examples/expr.nif"))

    assert isinstance(expr, LiteralExpr)
    assert isinstance(expr.literal, CharLiteralValue)
    assert expr.literal.raw_text == "'q'"


def test_parse_expression_u8_suffixed_integer_literal() -> None:
    expr = parse_expression(lex("113u8", source_path="examples/expr.nif"))

    assert isinstance(expr, LiteralExpr)
    assert isinstance(expr.literal, IntLiteralValue)
    assert expr.literal.raw_text == "113u8"
    assert expr.literal.magnitude == 113
    assert expr.literal.kind == IntLiteralKind.U8


def test_parse_expression_hex_integer_literal_uses_structured_payload() -> None:
    expr = parse_expression(lex("0x2Au", source_path="examples/expr.nif"))

    assert isinstance(expr, LiteralExpr)
    assert isinstance(expr.literal, IntLiteralValue)
    assert expr.literal.raw_text == "0x2Au"
    assert expr.literal.magnitude == 42
    assert expr.literal.kind == IntLiteralKind.U64


def test_parse_expression_hex_u8_literal_uses_structured_payload() -> None:
    expr = parse_expression(lex("0xffu8", source_path="examples/expr.nif"))

    assert isinstance(expr, LiteralExpr)
    assert isinstance(expr.literal, IntLiteralValue)
    assert expr.literal.raw_text == "0xffu8"
    assert expr.literal.magnitude == 255
    assert expr.literal.kind == IntLiteralKind.U8


@pytest.mark.parametrize(
    "literal_text",
    ["0x", "0xu", "0xu8", "0xg", "0x1g", "0x1gu8"],
)
def test_parse_expression_rejects_malformed_hex_literal(literal_text: str) -> None:
    with pytest.raises(ParserError, match=rf"Unsupported integer literal syntax: {literal_text}"):
        parse_expression(lex(literal_text, source_path="examples/bad_hex_expr.nif"))


def test_parse_expression_float_literal_uses_structured_payload() -> None:
    expr = parse_expression(lex("12.5", source_path="examples/expr.nif"))

    assert isinstance(expr, LiteralExpr)
    assert isinstance(expr.literal, FloatLiteralValue)
    assert expr.literal.raw_text == "12.5"
    assert expr.literal.value == 12.5


def test_parse_expression_precedence_logical_and_over_or() -> None:
    expr = parse_expression(lex("a || b && c", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "||"
    assert isinstance(expr.left, IdentifierExpr)
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "&&"


def test_parse_expression_precedence_bitwise_over_logical_and() -> None:
    expr = parse_expression(lex("a && b | c", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "&&"
    assert isinstance(expr.left, IdentifierExpr)
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "|"


def test_parse_expression_precedence_bitwise_and_over_xor_over_or() -> None:
    expr = parse_expression(lex("a | b ^ c & d", source_path="examples/expr.nif"))

    assert isinstance(expr, BinaryExpr)
    assert expr.operator == "|"
    assert isinstance(expr.right, BinaryExpr)
    assert expr.right.operator == "^"
    assert isinstance(expr.right.right, BinaryExpr)
    assert expr.right.right.operator == "&"


def test_parse_expression_unary_bitwise_not() -> None:
    expr = parse_expression(lex("~x", source_path="examples/expr.nif"))

    assert isinstance(expr, UnaryExpr)
    assert expr.operator == "~"
    assert isinstance(expr.operand, IdentifierExpr)


def test_parse_expression_postfix_binding_order() -> None:
    expr = parse_expression(lex("obj.field(1, 2)[0]", source_path="examples/expr.nif"))

    assert isinstance(expr, IndexExpr)
    assert isinstance(expr.object_expr, CallExpr)
    assert isinstance(expr.object_expr.callee, FieldAccessExpr)
    assert expr.object_expr.callee.field_name == "field"
    assert len(expr.object_expr.arguments) == 2


def test_parse_expression_slice_full_bounds_desugars_to_slice_call() -> None:
    expr = parse_expression(lex("v[3:5]", source_path="examples/slice_expr.nif"))

    assert isinstance(expr, CallExpr)
    assert isinstance(expr.callee, FieldAccessExpr)
    assert expr.callee.field_name == "slice_get"
    assert isinstance(expr.callee.object_expr, IdentifierExpr)
    assert expr.callee.object_expr.name == "v"
    assert len(expr.arguments) == 2
    assert isinstance(expr.arguments[0], LiteralExpr)
    assert isinstance(expr.arguments[0].literal, IntLiteralValue)
    assert expr.arguments[0].literal.magnitude == 3
    assert isinstance(expr.arguments[1], LiteralExpr)
    assert isinstance(expr.arguments[1].literal, IntLiteralValue)
    assert expr.arguments[1].literal.magnitude == 5


def test_parse_expression_slice_from_start_desugars_to_zero_begin() -> None:
    expr = parse_expression(lex("v[:7]", source_path="examples/slice_expr.nif"))

    assert isinstance(expr, CallExpr)
    assert isinstance(expr.callee, FieldAccessExpr)
    assert expr.callee.field_name == "slice_get"
    assert len(expr.arguments) == 2
    assert isinstance(expr.arguments[0], LiteralExpr)
    assert isinstance(expr.arguments[0].literal, IntLiteralValue)
    assert expr.arguments[0].literal.magnitude == 0
    assert isinstance(expr.arguments[1], LiteralExpr)
    assert isinstance(expr.arguments[1].literal, IntLiteralValue)
    assert expr.arguments[1].literal.magnitude == 7


def test_parse_expression_slice_to_end_desugars_to_casted_len_call() -> None:
    expr = parse_expression(lex("v[4:]", source_path="examples/slice_expr.nif"))

    assert isinstance(expr, CallExpr)
    assert isinstance(expr.callee, FieldAccessExpr)
    assert expr.callee.field_name == "slice_get"
    assert len(expr.arguments) == 2
    assert isinstance(expr.arguments[0], LiteralExpr)
    assert isinstance(expr.arguments[0].literal, IntLiteralValue)
    assert expr.arguments[0].literal.magnitude == 4
    assert isinstance(expr.arguments[1], CastExpr)
    assert expr.arguments[1].type_ref.name == "i64"
    assert isinstance(expr.arguments[1].operand, CallExpr)
    assert isinstance(expr.arguments[1].operand.callee, FieldAccessExpr)
    assert expr.arguments[1].operand.callee.field_name == "len"


def test_parse_expression_slice_full_omission_desugars_to_zero_and_casted_len() -> None:
    expr = parse_expression(lex("v[:]", source_path="examples/slice_expr.nif"))

    assert isinstance(expr, CallExpr)
    assert isinstance(expr.callee, FieldAccessExpr)
    assert expr.callee.field_name == "slice_get"
    assert len(expr.arguments) == 2
    assert isinstance(expr.arguments[0], LiteralExpr)
    assert isinstance(expr.arguments[0].literal, IntLiteralValue)
    assert expr.arguments[0].literal.magnitude == 0
    assert isinstance(expr.arguments[1], CastExpr)
    assert expr.arguments[1].type_ref.name == "i64"
    assert isinstance(expr.arguments[1].operand, CallExpr)
    assert isinstance(expr.arguments[1].operand.callee, FieldAccessExpr)
    assert expr.arguments[1].operand.callee.field_name == "len"


def test_parse_slice_assignment_desugars_to_set_slice_call() -> None:
    source = """
fn main() -> unit {
    var v: Vec = Vec.new();
    v[1:3] = Vec.new();
    return;
}
"""
    module = parse(lex(source, source_path="examples/slice_assign.nif"))

    stmt = module.functions[0].body.statements[1]
    assert isinstance(stmt, ExprStmt)
    assert isinstance(stmt.expression, CallExpr)
    assert isinstance(stmt.expression.callee, FieldAccessExpr)
    assert stmt.expression.callee.field_name == "slice_set"
    assert len(stmt.expression.arguments) == 3
    assert isinstance(stmt.expression.arguments[0], LiteralExpr)
    assert isinstance(stmt.expression.arguments[0].literal, IntLiteralValue)
    assert stmt.expression.arguments[0].literal.magnitude == 1
    assert isinstance(stmt.expression.arguments[1], LiteralExpr)
    assert isinstance(stmt.expression.arguments[1].literal, IntLiteralValue)
    assert stmt.expression.arguments[1].literal.magnitude == 3


def test_parse_expression_cast_then_unary_operand() -> None:
    expr = parse_expression(lex("(i64)-x", source_path="examples/expr.nif"))

    assert isinstance(expr, CastExpr)
    assert expr.type_ref.name == "i64"


def test_parse_expression_cast_with_qualified_type() -> None:
    expr = parse_expression(lex("(util.Counter)x", source_path="examples/expr.nif"))

    assert isinstance(expr, CastExpr)
    assert expr.type_ref.name == "util.Counter"


def test_parse_expression_type_test() -> None:
    expr = parse_expression(lex("value is Key", source_path="examples/expr.nif"))

    assert isinstance(expr, TypeTestExpr)
    assert isinstance(expr.operand, IdentifierExpr)
    assert expr.operand.name == "value"
    assert expr.type_ref.name == "Key"


def test_parse_expression_type_test_with_shift_operand_and_qualified_type() -> None:
    expr = parse_expression(lex("value << 1u is util.Hashable", source_path="examples/expr.nif"))

    assert isinstance(expr, TypeTestExpr)
    assert expr.type_ref.name == "util.Hashable"
    assert isinstance(expr.operand, BinaryExpr)
    assert expr.operand.operator == "<<"


def test_parse_function_signature_and_var_decl_with_array_types() -> None:
    source = """
fn build(values: u8[]) -> Person[] {
    var out: Person[] = Person[](3);
    return out;
}
"""
    module = parse(lex(source, source_path="examples/array_types.nif"))
    fn = module.functions[0]

    assert isinstance(fn.params[0].type_ref, ArrayTypeRef)
    assert isinstance(fn.params[0].type_ref.element_type, TypeRef)


def test_parse_function_type_in_var_decl() -> None:
    source = """
fn add(a: i64, b: i64) -> i64 {
    return a + b;
}

fn main() -> unit {
    var f: fn(i64, i64) -> i64 = add;
    return;
}
"""
    module = parse(lex(source, source_path="examples/fn_type_var.nif"))
    main_fn = module.functions[1]
    decl = main_fn.body.statements[0]
    assert isinstance(decl, VarDeclStmt)
    assert isinstance(decl.type_ref, FunctionTypeRef)
    assert len(decl.type_ref.param_types) == 2
    assert isinstance(decl.type_ref.param_types[0], TypeRef)
    assert decl.type_ref.param_types[0].name == "i64"
    assert isinstance(decl.type_ref.param_types[1], TypeRef)
    assert decl.type_ref.param_types[1].name == "i64"
    assert isinstance(decl.type_ref.return_type, TypeRef)
    assert decl.type_ref.return_type.name == "i64"


def test_parse_function_type_in_param_and_return_positions() -> None:
    source = """
fn apply2(f: fn(i64, i64) -> i64, x: i64, y: i64) -> fn(i64) -> i64 {
    return identity;
}

fn identity(v: i64) -> i64 {
    return v;
}
"""
    module = parse(lex(source, source_path="examples/fn_type_param_return.nif"))
    apply2_fn = module.functions[0]

    assert isinstance(apply2_fn.params[0].type_ref, FunctionTypeRef)
    param_fn_type = apply2_fn.params[0].type_ref
    assert len(param_fn_type.param_types) == 2
    assert isinstance(param_fn_type.return_type, TypeRef)
    assert param_fn_type.return_type.name == "i64"

    assert isinstance(apply2_fn.return_type, FunctionTypeRef)
    ret_fn_type = apply2_fn.return_type
    assert len(ret_fn_type.param_types) == 1
    assert isinstance(ret_fn_type.param_types[0], TypeRef)
    assert ret_fn_type.param_types[0].name == "i64"
    assert isinstance(ret_fn_type.return_type, TypeRef)
    assert ret_fn_type.return_type.name == "i64"


def test_parse_function_type_in_class_field_position() -> None:
    source = """
class Predicates {
    trim: fn(Str) -> Str;
    empty: fn(Str) -> bool;
}
"""
    module = parse(lex(source, source_path="examples/fn_type_field.nif"))
    cls = module.classes[0]
    assert isinstance(cls.fields[0].type_ref, FunctionTypeRef)
    assert isinstance(cls.fields[1].type_ref, FunctionTypeRef)


def test_parse_class_field_default_initializer() -> None:
    source = """
class Counter {
    value: i64 = 0;
    done: bool = false;
}
"""
    module = parse(lex(source, source_path="examples/field_defaults.nif"))
    cls = module.classes[0]
    assert isinstance(cls.fields[0].initializer, LiteralExpr)
    assert isinstance(cls.fields[0].initializer.literal, IntLiteralValue)
    assert cls.fields[0].initializer.literal.magnitude == 0
    assert isinstance(cls.fields[1].initializer, LiteralExpr)
    assert isinstance(cls.fields[1].initializer.literal, BoolLiteralValue)
    assert cls.fields[1].initializer.literal.value is False


def test_parse_nested_function_type_in_param_position() -> None:
    source = """
fn compose(
    f: fn(i64) -> i64,
    g: fn(i64) -> fn(i64) -> i64
) -> unit {
    return;
}
"""
    module = parse(lex(source, source_path="examples/fn_type_nested.nif"))
    fn_decl = module.functions[0]

    assert isinstance(fn_decl.params[1].type_ref, FunctionTypeRef)
    outer = fn_decl.params[1].type_ref
    assert isinstance(outer.return_type, FunctionTypeRef)
    inner = outer.return_type
    assert len(inner.param_types) == 1
    assert isinstance(inner.return_type, TypeRef)
    assert inner.return_type.name == "i64"


def test_parse_rejects_malformed_function_type_missing_arrow() -> None:
    source = """
fn main() -> unit {
    var f: fn(i64, i64) i64;
    return;
}
"""
    with pytest.raises(ParserError, match="Expected '->' after function type parameter list"):
        parse(lex(source, source_path="examples/fn_type_missing_arrow.nif"))


def test_parse_rejects_function_literal_expression_with_clear_diagnostic() -> None:
    source = """
fn main() -> unit {
    var f: fn(i64) -> i64 = fn(x: i64) -> i64 { return x; };
    return;
}
"""
    with pytest.raises(ParserError, match="Function literals/closures are not supported in MVP"):
        parse(lex(source, source_path="examples/fn_literal_rejected.nif"))


def test_parse_rejects_nested_function_declaration_with_clear_diagnostic() -> None:
    source = """
fn main() -> unit {
    fn helper(x: i64) -> i64 {
        return x;
    }
    return;
}
"""
    with pytest.raises(ParserError, match="Nested functions/closures are not supported in MVP"):
        parse(lex(source, source_path="examples/nested_fn_rejected.nif"))


def test_parse_function_type_can_return_array_type() -> None:
    source = """
fn main() -> unit {
    var make: fn(u64) -> i64[];
    return;
}
"""
    module = parse(lex(source, source_path="examples/fn_type_array_return.nif"))
    decl = module.functions[0].body.statements[0]
    assert isinstance(decl, VarDeclStmt)
    assert isinstance(decl.type_ref, FunctionTypeRef)
    assert isinstance(decl.type_ref.return_type, ArrayTypeRef)
    assert isinstance(decl.type_ref.return_type.element_type, TypeRef)
    assert decl.type_ref.return_type.element_type.name == "i64"


def test_parse_expression_array_constructor() -> None:
    expr = parse_expression(lex("u8[](23)", source_path="examples/array_ctor_expr.nif"))

    assert isinstance(expr, ArrayCtorExpr)
    assert isinstance(expr.element_type_ref, ArrayTypeRef)
    assert isinstance(expr.element_type_ref.element_type, TypeRef)
    assert expr.element_type_ref.element_type.name == "u8"
    assert isinstance(expr.length_expr, LiteralExpr)
    assert isinstance(expr.length_expr.literal, IntLiteralValue)
    assert expr.length_expr.literal.magnitude == 23


def test_parse_expression_array_constructor_requires_length_expression() -> None:
    with pytest.raises(ParserError) as error:
        parse_expression(lex("u8[]()", source_path="examples/bad_array_ctor.nif"))

    assert "Expected array constructor length expression" in str(error.value)


def test_parse_allows_nested_array_type() -> None:
    source = """
fn main() -> unit {
    var x: u8[][] = null;
    return;
}
"""
    module = parse(lex(source, source_path="examples/nested_array_type.nif"))
    decl = module.functions[0].body.statements[0]

    assert isinstance(decl, VarDeclStmt)
    assert isinstance(decl.type_ref, ArrayTypeRef)
    assert isinstance(decl.type_ref.element_type, ArrayTypeRef)
    assert isinstance(decl.type_ref.element_type.element_type, TypeRef)
    assert decl.type_ref.element_type.element_type.name == "u8"


def test_parse_allows_nested_array_constructor() -> None:
    expr = parse_expression(lex("u8[][](3u)", source_path="examples/nested_array_ctor.nif"))

    assert isinstance(expr, ArrayCtorExpr)
    assert isinstance(expr.element_type_ref, ArrayTypeRef)
    assert isinstance(expr.element_type_ref.element_type, ArrayTypeRef)
    assert isinstance(expr.element_type_ref.element_type.element_type, TypeRef)
    assert expr.element_type_ref.element_type.element_type.name == "u8"


def test_parse_allows_nested_array_cast() -> None:
    expr = parse_expression(lex("(u8[][])x", source_path="examples/nested_array_cast.nif"))

    assert isinstance(expr, CastExpr)
    assert isinstance(expr.type_ref, ArrayTypeRef)
    assert isinstance(expr.type_ref.element_type, ArrayTypeRef)
    assert isinstance(expr.type_ref.element_type.element_type, TypeRef)
    assert expr.type_ref.element_type.element_type.name == "u8"


def test_parse_function_signature_and_var_decl_with_qualified_types() -> None:
    source = """
fn build(c: util.Counter) -> util.Counter {
    var out: util.Counter = c;
    return out;
}
"""
    module = parse(lex(source, source_path="examples/qualified_types.nif"))
    fn = module.functions[0]

    assert fn.params[0].type_ref.name == "util.Counter"
    assert fn.return_type.name == "util.Counter"
    assert isinstance(fn.body.statements[0], VarDeclStmt)
    assert fn.body.statements[0].type_ref.name == "util.Counter"


def test_parse_allows_str_as_class_name() -> None:
    source = """
export class Str {
}
"""
    module = parse(lex(source, source_path="examples/str_class.nif"))
    assert len(module.classes) == 1
    assert module.classes[0].name == "Str"


def test_parse_allows_str_in_qualified_type_segment() -> None:
    source = """
fn main() -> unit {
    var s: std.Str = null;
    return;
}
"""
    module = parse(lex(source, source_path="examples/qualified_str_type.nif"))
    stmt = module.functions[0].body.statements[0]
    assert isinstance(stmt, VarDeclStmt)
    assert stmt.type_ref.name == "std.Str"


def test_parse_allows_str_in_qualified_constructor_call() -> None:
    expr = parse_expression(lex("strmod.Str()", source_path="examples/qualified_str_ctor.nif"))
    assert isinstance(expr, CallExpr)
    assert isinstance(expr.callee, FieldAccessExpr)
    assert isinstance(expr.callee.object_expr, IdentifierExpr)
    assert expr.callee.object_expr.name == "strmod"
    assert expr.callee.field_name == "Str"


def test_parse_expression_invalid_missing_rhs() -> None:
    with pytest.raises(ParserError) as error:
        parse_expression(lex("1 +", source_path="examples/bad_expr.nif"))

    assert "Expected expression" in str(error.value)
    assert "examples/bad_expr.nif" in str(error.value)


def test_parse_expression_invalid_unclosed_group() -> None:
    with pytest.raises(ParserError) as error:
        parse_expression(lex("(1 + 2", source_path="examples/bad_expr.nif"))

    assert "Expected ')' after expression" in str(error.value)
    assert "examples/bad_expr.nif" in str(error.value)


def test_parse_module_ast_nodes_have_spans_recursively() -> None:
    source = """
import a.b;

class Point {
    x: i64;
    y: i64;

    fn move(dx: i64, dy: i64) -> unit {
        var nx: i64 = dx + 1;
        if nx > 0 {
            return;
        } else {
            return;
        }
    }
}

fn main() -> unit {
    var i: i64 = 0;
    while i < 3 {
        i = i + 1;
    }
    return;
}
"""
    module = parse(lex(source, source_path="examples/span_check_module.nif"))
    _assert_ast_nodes_have_spans(module)


def test_parse_expression_ast_nodes_have_spans_recursively() -> None:
    expr = parse_expression(lex("(i64)foo(1 + 2).bar[3]", source_path="examples/span_check_expr.nif"))
    _assert_ast_nodes_have_spans(expr)
