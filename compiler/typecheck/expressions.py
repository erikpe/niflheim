from __future__ import annotations

import math
from compiler.common.collection_protocols import COLLECTION_PROTOCOL_METHOD_NAMES
from compiler.common.literals import IntLiteralKind
from compiler.common.type_names import *
from compiler.common.type_shapes import is_str_type_name
from compiler.frontend.ast_nodes import *
from compiler.typecheck.call_helpers import callable_type_from_signature, class_type_name_from_callable
from compiler.typecheck.constants import *
from compiler.typecheck.context import lookup_variable
from compiler.typecheck.model import TypeCheckError, TypeInfo
from compiler.typecheck.module_lookup import (
    current_module_info,
    lookup_class_by_type_name,
    lookup_interface_by_type_name,
    resolve_imported_class_name,
    resolve_imported_function_sig,
    resolve_module_member,
)
from compiler.typecheck.relations import (
    check_explicit_cast,
    check_type_test,
    is_comparable,
    require_array_size_type,
    require_type_name,
)
from compiler.typecheck.type_resolution import qualify_member_type_for_owner, resolve_string_type, resolve_type_ref
from compiler.typecheck.visibility import require_member_visible
from compiler.typecheck.context import TypeCheckContext
from compiler.resolver import has_bound_import_root


def _infer_identifier_expression_type(ctx: TypeCheckContext, expr: IdentifierExpr) -> TypeInfo:
    symbol_type = lookup_variable(ctx, expr.name)
    if symbol_type is not None:
        return symbol_type

    fn_sig = ctx.functions.get(expr.name)
    if fn_sig is not None:
        return callable_type_from_signature(f"__fn__:{expr.name}", fn_sig)

    imported_fn_sig = resolve_imported_function_sig(ctx, expr.name, expr.span)
    if imported_fn_sig is not None:
        return callable_type_from_signature(f"__fn__:{expr.name}", imported_fn_sig)

    if expr.name in ctx.classes:
        return TypeInfo(name=f"__class__:{expr.name}", kind="callable")

    imported_class_name = resolve_imported_class_name(ctx, expr.name, expr.span)
    if imported_class_name is not None:
        if "::" in imported_class_name:
            owner_dotted, class_name = imported_class_name.split("::", 1)
            return TypeInfo(name=f"__class__:{owner_dotted}:{class_name}", kind="callable")
        return TypeInfo(name=f"__class__:{imported_class_name}", kind="callable")

    module_info = current_module_info(ctx)
    if module_info is not None and has_bound_import_root(module_info.bound_imports, expr.name):
        return TypeInfo(name=f"__module__:{expr.name}", kind="module")

    raise TypeCheckError(f"Unknown identifier '{expr.name}'", expr.span)


def _infer_literal_expression_type(ctx: TypeCheckContext, expr: LiteralExpr) -> TypeInfo:
    literal = expr.literal

    if isinstance(literal, StringLiteralValue):
        return resolve_string_type(ctx, expr.span)
    if isinstance(literal, CharLiteralValue):
        return TypeInfo(name=TYPE_NAME_U8, kind="primitive")
    if isinstance(literal, BoolLiteralValue):
        return TypeInfo(name=TYPE_NAME_BOOL, kind="primitive")
    if isinstance(literal, FloatLiteralValue):
        if not math.isfinite(literal.value):
            raise TypeCheckError("double literal out of range (expected finite IEEE-754 double)", expr.span)
        return TypeInfo(name=TYPE_NAME_DOUBLE, kind="primitive")
    if isinstance(literal, IntLiteralValue):
        if literal.kind == IntLiteralKind.U8:
            if literal.magnitude > U8_MAX_LITERAL:
                raise TypeCheckError("u8 literal out of range (expected 0..255)", expr.span)
            return TypeInfo(name=TYPE_NAME_U8, kind="primitive")
        if literal.kind == IntLiteralKind.U64:
            if literal.magnitude > U64_MAX_LITERAL:
                raise TypeCheckError("u64 literal out of range (expected 0..18446744073709551615)", expr.span)
            return TypeInfo(name=TYPE_NAME_U64, kind="primitive")
        if literal.magnitude > I64_MAX_LITERAL:
            raise TypeCheckError(
                "i64 literal out of range (expected -9223372036854775808..9223372036854775807)", expr.span
            )
        return TypeInfo(name=TYPE_NAME_I64, kind="primitive")

    raise TypeCheckError("Unsupported literal expression", expr.span)


def _infer_unary_expression_type(ctx: TypeCheckContext, expr: UnaryExpr) -> TypeInfo:
    if expr.operator == "!":
        operand_type = infer_expression_type(ctx, expr.operand)
        require_type_name(operand_type, TYPE_NAME_BOOL, expr.operand.span)
        return TypeInfo(name=TYPE_NAME_BOOL, kind="primitive")

    if expr.operator == "-":
        if isinstance(expr.operand, LiteralExpr) and isinstance(expr.operand.literal, IntLiteralValue):
            literal = expr.operand.literal
            if literal.kind == IntLiteralKind.UNSUFFIXED and literal.magnitude == I64_MIN_MAGNITUDE_LITERAL:
                return TypeInfo(name=TYPE_NAME_I64, kind="primitive")
        operand_type = infer_expression_type(ctx, expr.operand)
        if operand_type.name not in {TYPE_NAME_I64, TYPE_NAME_DOUBLE}:
            raise TypeCheckError("Unary '-' requires signed numeric operand", expr.span)
        return operand_type

    if expr.operator == "~":
        operand_type = infer_expression_type(ctx, expr.operand)
        if operand_type.name not in BITWISE_TYPE_NAMES:
            raise TypeCheckError("Unary '~' requires integer operand", expr.span)
        return operand_type

    raise TypeCheckError(f"Unknown unary operator '{expr.operator}'", expr.span)


def _infer_binary_expression_type(ctx: TypeCheckContext, expr: BinaryExpr) -> TypeInfo:
    left_type = infer_expression_type(ctx, expr.left)
    right_type = infer_expression_type(ctx, expr.right)
    op = expr.operator

    if op in {"+", "-", "*", "/", "%"}:
        if op == "+" and is_str_type_name(left_type.name) and is_str_type_name(right_type.name):
            return resolve_string_type(ctx, expr.span)

        if left_type.name not in NUMERIC_TYPE_NAMES or right_type.name not in NUMERIC_TYPE_NAMES:
            if op == "+":
                raise TypeCheckError("Operator '+' requires numeric operands or Str operands", expr.span)
            raise TypeCheckError(f"Operator '{op}' requires numeric operands", expr.span)
        if left_type.name != right_type.name:
            raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
        if op == "%" and left_type.name == TYPE_NAME_DOUBLE:
            raise TypeCheckError("Operator '%' is not supported for 'double'", expr.span)
        return left_type

    if op == "**":
        if left_type.name not in BITWISE_TYPE_NAMES:
            raise TypeCheckError("Operator '**' requires integer left operand", expr.span)
        if right_type.name != TYPE_NAME_U64:
            raise TypeCheckError("Operator '**' requires 'u64' exponent", expr.span)
        return left_type

    if op in {"<<", ">>"}:
        if left_type.name not in BITWISE_TYPE_NAMES:
            raise TypeCheckError(f"Operator '{op}' requires integer left operand", expr.span)
        if right_type.name != TYPE_NAME_U64:
            raise TypeCheckError(f"Operator '{op}' requires 'u64' shift count", expr.span)
        return left_type

    if op in {"&", "|", "^"}:
        if left_type.name not in BITWISE_TYPE_NAMES or right_type.name not in BITWISE_TYPE_NAMES:
            raise TypeCheckError(f"Operator '{op}' requires integer operands", expr.span)
        if left_type.name != right_type.name:
            raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
        return left_type

    if op in {"<", "<=", ">", ">="}:
        if left_type.name not in NUMERIC_TYPE_NAMES or right_type.name not in NUMERIC_TYPE_NAMES:
            raise TypeCheckError(f"Operator '{op}' requires numeric operands", expr.span)
        if left_type.name != right_type.name:
            raise TypeCheckError(f"Operator '{op}' requires matching operand types", expr.span)
        return TypeInfo(name=TYPE_NAME_BOOL, kind="primitive")

    if op in {"==", "!="}:
        if not is_comparable(ctx, left_type, right_type):
            raise TypeCheckError(f"Operator '{op}' has incompatible operand types", expr.span)
        return TypeInfo(name=TYPE_NAME_BOOL, kind="primitive")

    if op in {"&&", "||"}:
        require_type_name(left_type, TYPE_NAME_BOOL, expr.left.span)
        require_type_name(right_type, TYPE_NAME_BOOL, expr.right.span)
        return TypeInfo(name=TYPE_NAME_BOOL, kind="primitive")

    raise TypeCheckError(f"Unknown binary operator '{op}'", expr.span)


def _infer_module_member_field_access_type(ctx: TypeCheckContext, expr: FieldAccessExpr) -> TypeInfo | None:
    module_member = resolve_module_member(ctx, expr)
    if module_member is None:
        return None

    kind, owner_module, member_name = module_member
    if kind == "function":
        dotted = ".".join(owner_module)
        fn_sig = ctx.module_function_sigs[owner_module][member_name]
        return callable_type_from_signature(f"__fn__:{dotted}:{member_name}", fn_sig)
    if kind == "class":
        dotted = ".".join(owner_module)
        return TypeInfo(name=f"__class__:{dotted}:{member_name}", kind="callable")
    dotted = ".".join(owner_module)
    return TypeInfo(name=f"__module__:{dotted}", kind="module")


def _infer_class_callable_field_access_type(
    ctx: TypeCheckContext, expr: FieldAccessExpr, class_type_name: str
) -> TypeInfo:
    class_info = lookup_class_by_type_name(ctx, class_type_name)
    if class_info is None:
        raise TypeCheckError(f"Type '{class_type_name}' has no callable members", expr.span)

    method_sig = class_info.methods.get(expr.field_name)
    if method_sig is None:
        raise TypeCheckError(f"Class '{class_info.name}' has no method '{expr.field_name}'", expr.span)
    method_member = class_info.method_members[expr.field_name]
    require_member_visible(ctx, class_info, method_member.owner_class_name, expr.field_name, "method", expr.span)
    if not method_sig.is_static:
        owner_display_name = method_member.owner_class_name.split("::", 1)[-1]
        raise TypeCheckError(f"Method '{owner_display_name}.{expr.field_name}' is not static", expr.span)

    qualified_params = [
        qualify_member_type_for_owner(ctx, param_type, method_member.owner_class_name) for param_type in method_sig.params
    ]
    qualified_return = qualify_member_type_for_owner(ctx, method_sig.return_type, method_member.owner_class_name)
    owner_display_name = method_member.owner_class_name.split("::", 1)[-1]
    return TypeInfo(
        name=f"__method__:{owner_display_name}:{method_sig.name}",
        kind="callable",
        callable_params=qualified_params,
        callable_return=qualified_return,
    )


def _infer_instance_field_access_type(ctx: TypeCheckContext, expr: FieldAccessExpr, object_type: TypeInfo) -> TypeInfo:
    class_info = lookup_class_by_type_name(ctx, object_type.name)
    if class_info is None:
        raise TypeCheckError(f"Type '{object_type.name}' has no fields/methods", expr.span)

    field_type = class_info.fields.get(expr.field_name)
    if field_type is not None:
        field_member = class_info.field_members[expr.field_name]
        require_member_visible(ctx, class_info, field_member.owner_class_name, expr.field_name, "field", expr.span)
        return qualify_member_type_for_owner(ctx, field_type, field_member.owner_class_name)

    method_sig = class_info.methods.get(expr.field_name)
    if method_sig is not None:
        method_member = class_info.method_members[expr.field_name]
        require_member_visible(ctx, class_info, method_member.owner_class_name, expr.field_name, "method", expr.span)
        if not method_sig.is_static:
            raise TypeCheckError("Instance methods are not first-class values in MVP", expr.span)
        qualified_params = [
            qualify_member_type_for_owner(ctx, param_type, method_member.owner_class_name)
            for param_type in method_sig.params
        ]
        qualified_return = qualify_member_type_for_owner(ctx, method_sig.return_type, method_member.owner_class_name)
        owner_display_name = method_member.owner_class_name.split("::", 1)[-1]
        return TypeInfo(
            name=f"__method__:{owner_display_name}:{method_sig.name}",
            kind="callable",
            callable_params=qualified_params,
            callable_return=qualified_return,
        )

    raise TypeCheckError(f"Class '{class_info.name}' has no member '{expr.field_name}'", expr.span)


def _infer_interface_field_access_type(ctx: TypeCheckContext, expr: FieldAccessExpr, object_type: TypeInfo) -> TypeInfo:
    interface_info = lookup_interface_by_type_name(ctx, object_type.name)
    if interface_info is None:
        raise TypeCheckError(f"Type '{object_type.name}' has no fields/methods", expr.span)

    if expr.field_name in interface_info.methods:
        raise TypeCheckError("Interface method references are not supported in v1", expr.span)

    raise TypeCheckError(f"Interface '{interface_info.name}' has no method '{expr.field_name}'", expr.span)


def _infer_field_access_expression_type(ctx: TypeCheckContext, expr: FieldAccessExpr) -> TypeInfo:
    module_member_result = _infer_module_member_field_access_type(ctx, expr)
    if module_member_result is not None:
        return module_member_result

    object_type = infer_expression_type(ctx, expr.object_expr)

    if object_type.kind == "callable" and object_type.name.startswith("__class__:"):
        return _infer_class_callable_field_access_type(ctx, expr, class_type_name_from_callable(object_type.name))

    if object_type.element_type is not None:
        if expr.field_name not in COLLECTION_PROTOCOL_METHOD_NAMES:
            raise TypeCheckError(f"Array type '{object_type.name}' has no member '{expr.field_name}'", expr.span)
        return TypeInfo(name=f"__array_method__:{expr.field_name}", kind="callable")

    if object_type.kind == "interface":
        return _infer_interface_field_access_type(ctx, expr, object_type)

    return _infer_instance_field_access_type(ctx, expr, object_type)


def infer_expression_type(ctx: TypeCheckContext, expr: Expression) -> TypeInfo:
    from compiler.typecheck.calls import infer_call_type
    from compiler.typecheck.structural import resolve_index_expression_type

    if isinstance(expr, IdentifierExpr):
        return _infer_identifier_expression_type(ctx, expr)

    if isinstance(expr, LiteralExpr):
        return _infer_literal_expression_type(ctx, expr)

    if isinstance(expr, NullExpr):
        return TypeInfo(name=TYPE_NAME_NULL, kind="null")

    if isinstance(expr, UnaryExpr):
        return _infer_unary_expression_type(ctx, expr)

    if isinstance(expr, BinaryExpr):
        return _infer_binary_expression_type(ctx, expr)

    if isinstance(expr, CastExpr):
        source_type = infer_expression_type(ctx, expr.operand)
        target_type = resolve_type_ref(ctx, expr.type_ref)
        check_explicit_cast(ctx, source_type, target_type, expr.span)
        return target_type

    if isinstance(expr, TypeTestExpr):
        source_type = infer_expression_type(ctx, expr.operand)
        target_type = resolve_type_ref(ctx, expr.type_ref)
        check_type_test(ctx, source_type, target_type, expr.span)
        return TypeInfo(name=TYPE_NAME_BOOL, kind="primitive")

    if isinstance(expr, CallExpr):
        return infer_call_type(ctx, expr)

    if isinstance(expr, ArrayCtorExpr):
        array_type = resolve_type_ref(ctx, expr.element_type_ref)
        if array_type.element_type is None:
            raise TypeCheckError("Array constructor requires array element type", expr.element_type_ref.span)
        length_type = infer_expression_type(ctx, expr.length_expr)
        require_array_size_type(length_type, expr.length_expr.span)
        return array_type

    if isinstance(expr, FieldAccessExpr):
        return _infer_field_access_expression_type(ctx, expr)

    if isinstance(expr, IndexExpr):
        obj_type = infer_expression_type(ctx, expr.object_expr)
        index_type = infer_expression_type(ctx, expr.index_expr)
        return resolve_index_expression_type(ctx, obj_type, index_type, expr.index_expr.span, expr.span)

    raise TypeCheckError("Unsupported expression", expr.span)
