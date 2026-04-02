from __future__ import annotations

from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_DOUBLE, TYPE_NAME_I64, TYPE_NAME_NULL, TYPE_NAME_OBJ, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_UNIT
from compiler.typecheck.context import TypeCheckContext
from compiler.common.span import SourceSpan
from compiler.typecheck.module_lookup import lookup_class_by_type_name
from compiler.typecheck.model import TypeCheckError, TypeInfo


def canonicalize_nominal_type_name(ctx: TypeCheckContext, type_name: str) -> str:
    if "::" in type_name:
        return type_name
    if ctx.module_path is None:
        return type_name
    if type_name not in ctx.classes and type_name not in ctx.interfaces:
        return type_name
    owner_dotted = ".".join(ctx.module_path)
    return f"{owner_dotted}::{type_name}"


def canonicalize_reference_type_name(ctx: TypeCheckContext, type_name: str) -> str:
    return canonicalize_nominal_type_name(ctx, type_name)


def _type_names_equal(ctx: TypeCheckContext, left: str, right: str) -> bool:
    if left == right:
        return True
    return canonicalize_nominal_type_name(ctx, left) == canonicalize_nominal_type_name(ctx, right)


def _type_infos_equal(ctx: TypeCheckContext, left: TypeInfo, right: TypeInfo) -> bool:
    if left.kind == "callable" or right.kind == "callable":
        if left.kind != "callable" or right.kind != "callable":
            return False
        if left.callable_params is None or right.callable_params is None:
            return False
        if left.callable_return is None or right.callable_return is None:
            return False
        if len(left.callable_params) != len(right.callable_params):
            return False
        if not all(
            _type_infos_equal(ctx, left_param, right_param)
            for left_param, right_param in zip(left.callable_params, right.callable_params)
        ):
            return False
        return _type_infos_equal(ctx, left.callable_return, right.callable_return)

    if left.element_type is not None or right.element_type is not None:
        if left.element_type is None or right.element_type is None:
            return False
        return _type_infos_equal(ctx, left.element_type, right.element_type)

    return _type_names_equal(ctx, left.name, right.name)


def format_function_type_name(params: list[TypeInfo], return_type: TypeInfo) -> str:
    params_text = ", ".join(param.name for param in params)
    return f"fn({params_text}) -> {return_type.name}"


def _display_type_name(type_info: TypeInfo) -> str:
    if type_info.kind == "callable" and type_info.callable_params is not None and type_info.callable_return is not None:
        return format_function_type_name(type_info.callable_params, type_info.callable_return)
    return type_info.name


def require_type_name(actual: TypeInfo, expected_name: str, span: SourceSpan) -> None:
    if actual.name != expected_name:
        raise TypeCheckError(f"Expected '{expected_name}', got '{actual.name}'", span)


def require_array_size_type(actual: TypeInfo, span: SourceSpan) -> None:
    if actual.name in {TYPE_NAME_U64, TYPE_NAME_I64}:
        return
    raise TypeCheckError(f"Expected '{TYPE_NAME_U64}', got '{actual.name}'", span)


def require_array_index_type(actual: TypeInfo, span: SourceSpan) -> None:
    if actual.name == TYPE_NAME_I64:
        return
    raise TypeCheckError(f"Expected '{TYPE_NAME_I64}', got '{actual.name}'", span)


def type_infos_equal(ctx: TypeCheckContext, left: TypeInfo, right: TypeInfo) -> bool:
    return _type_infos_equal(ctx, left, right)


def is_assignable(ctx: TypeCheckContext, target: TypeInfo, value: TypeInfo) -> bool:
    if _type_infos_equal(ctx, target, value):
        return True
    if target.kind in {"reference", "interface"} and value.kind == TYPE_NAME_NULL:
        return True
    if target.name == TYPE_NAME_OBJ and value.kind in {"reference", "interface"}:
        return True
    if target.kind == "interface" and value.kind == "reference" and _class_implements_interface(ctx, value.name, target.name):
        return True
    return False


def require_assignable(ctx: TypeCheckContext, target: TypeInfo, value: TypeInfo, span: SourceSpan) -> None:
    if is_assignable(ctx, target, value):
        return
    raise TypeCheckError(f"Cannot assign '{_display_type_name(value)}' to '{_display_type_name(target)}'", span)


def is_comparable(ctx: TypeCheckContext, left: TypeInfo, right: TypeInfo) -> bool:
    if _type_infos_equal(ctx, left, right):
        return True
    if left.kind in {"reference", "interface"} and right.kind == TYPE_NAME_NULL:
        return True
    if right.kind in {"reference", "interface"} and left.kind == TYPE_NAME_NULL:
        return True
    if left.kind in {"reference", "interface"} and right.kind in {"reference", "interface"}:
        return _may_alias_under_identity_comparison(ctx, left, right)
    return False


def check_type_test(ctx: TypeCheckContext, source: TypeInfo, target: TypeInfo, span: SourceSpan) -> None:
    if target.kind == "interface":
        pass
    elif not _is_concrete_class_type(ctx, target):
        raise TypeCheckError("Operator 'is' requires class or interface type on right operand", span)

    if source.kind == TYPE_NAME_NULL:
        return

    if source.kind == "callable" or source.element_type is not None:
        raise TypeCheckError("Operator 'is' requires reference, interface, Obj, or null left operand", span)

    if source.kind not in {"reference", "interface"}:
        raise TypeCheckError("Operator 'is' requires reference, interface, Obj, or null left operand", span)

    if source.kind == "reference" and source.name != TYPE_NAME_OBJ and not _is_concrete_class_type(ctx, source):
        raise TypeCheckError("Operator 'is' requires reference, interface, Obj, or null left operand", span)

    try:
        check_explicit_cast(ctx, source, target, span)
    except TypeCheckError as error:
        if error.message.startswith("Invalid cast from '"):
            raise TypeCheckError("Operator 'is' has incompatible operand types", span) from None
        raise


def _may_alias_under_identity_comparison(ctx: TypeCheckContext, left: TypeInfo, right: TypeInfo) -> bool:
    if left.name == TYPE_NAME_OBJ or right.name == TYPE_NAME_OBJ:
        return True

    if left.kind == "interface" and right.kind == "interface":
        return True

    if left.kind == "reference" and right.kind == "interface":
        return _class_implements_interface(ctx, left.name, right.name)

    if left.kind == "interface" and right.kind == "reference":
        return _class_implements_interface(ctx, right.name, left.name)

    return False


def check_explicit_cast(ctx: TypeCheckContext, source: TypeInfo, target: TypeInfo, span: SourceSpan) -> None:
    if source.kind == "callable" or target.kind == "callable":
        raise TypeCheckError("Casts involving function types are not allowed in MVP", span)

    if _type_infos_equal(ctx, source, target):
        return

    if source.kind == "primitive" and target.kind == "primitive":
        if source.name == TYPE_NAME_UNIT or target.name == TYPE_NAME_UNIT:
            raise TypeCheckError("Casts involving 'unit' are not allowed", span)
        if _primitive_cast_allowed(source.name, target.name):
            return
        raise TypeCheckError(f"Invalid cast from '{source.name}' to '{target.name}'", span)

    if source.kind == TYPE_NAME_NULL and target.kind == "interface":
        return

    if source.kind in {"reference", "interface"} and target.name == TYPE_NAME_OBJ:
        return

    if source.name == TYPE_NAME_OBJ and target.kind in {"reference", "interface"} and target.name != TYPE_NAME_OBJ:
        return

    if source.kind == "interface" and target.kind == "interface":
        return

    if source.kind == "interface" and _is_concrete_class_type(ctx, target):
        return

    if source.kind == "reference" and target.kind == "interface" and _class_implements_interface(ctx, source.name, target.name):
        return

    raise TypeCheckError(f"Invalid cast from '{source.name}' to '{target.name}'", span)


def _primitive_cast_allowed(source_name: str, target_name: str) -> bool:
    primitive_cast_targets = {
        TYPE_NAME_BOOL: {TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_DOUBLE},
        TYPE_NAME_I64: {TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_DOUBLE},
        TYPE_NAME_U64: {TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_DOUBLE},
        TYPE_NAME_U8: {TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_DOUBLE},
        TYPE_NAME_DOUBLE: {TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_U64, TYPE_NAME_U8, TYPE_NAME_DOUBLE},
    }
    return target_name in primitive_cast_targets.get(source_name, set())


def _class_implements_interface(ctx: TypeCheckContext, class_type_name: str, interface_type_name: str) -> bool:
    if ctx.module_class_infos is None:
        class_info = ctx.classes.get(class_type_name)
    elif "::" in class_type_name:
        owner_dotted, class_name = class_type_name.split("::", 1)
        owner_module = tuple(owner_dotted.split("."))
        class_info = ctx.module_class_infos.get(owner_module, {}).get(class_name)
    else:
        class_info = ctx.classes.get(class_type_name)

    if class_info is None:
        return False

    canonical_interface_name = canonicalize_nominal_type_name(ctx, interface_type_name)
    return canonical_interface_name in {canonicalize_nominal_type_name(ctx, name) for name in class_info.implemented_interfaces}


def _is_concrete_class_type(ctx: TypeCheckContext, type_info: TypeInfo) -> bool:
    if type_info.kind != "reference" or type_info.name == TYPE_NAME_OBJ or type_info.element_type is not None:
        return False
    return lookup_class_by_type_name(ctx, type_info.name) is not None
