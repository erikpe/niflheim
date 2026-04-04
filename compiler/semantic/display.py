from __future__ import annotations

from compiler.semantic.ir import (
    BoundMemberAccess,
    CallableValueCallTarget,
    ConstructorCallTarget,
    ConstructorInitCallTarget,
    FunctionCallTarget,
    InstanceMethodCallTarget,
    InterfaceMethodCallTarget,
    SemanticCallTarget,
    SemanticFunctionLike,
    StaticMethodCallTarget,
    VirtualMethodCallTarget,
    expression_type_ref,
    local_display_name_for_owner,
    local_type_ref_for_owner,
)
from compiler.resolver import ModulePath
from compiler.semantic.symbols import ConstructorId, FunctionId, InterfaceMethodId, LocalId, MethodId
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_type_display_name,
    semantic_type_display_name_relative,
)


def semantic_local_display_name(owner: SemanticFunctionLike, local_id: LocalId) -> str:
    return local_display_name_for_owner(owner, local_id)


def semantic_local_type_display_name(owner: SemanticFunctionLike, local_id: LocalId) -> str:
    return semantic_type_display_name_relative(_owner_module_path(owner), local_type_ref_for_owner(owner, local_id))


def semantic_bound_member_receiver_display_name(
    access: BoundMemberAccess, *, current_module_path: ModulePath | None = None
) -> str:
    if current_module_path is None:
        return semantic_type_display_name(access.receiver_type_ref)
    return semantic_type_display_name_relative(current_module_path, access.receiver_type_ref)


def semantic_function_display_name(function_id: FunctionId, *, current_module_path: ModulePath | None = None) -> str:
    return _qualified_display_name(function_id.module_path, function_id.name, current_module_path=current_module_path)


def semantic_method_display_name(method_id: MethodId, *, current_module_path: ModulePath | None = None) -> str:
    return f"{_qualified_display_name(method_id.module_path, method_id.class_name, current_module_path=current_module_path)}.{method_id.name}"


def semantic_interface_method_display_name(
    method_id: InterfaceMethodId, *, current_module_path: ModulePath | None = None
) -> str:
    return f"{_qualified_display_name(method_id.module_path, method_id.interface_name, current_module_path=current_module_path)}.{method_id.name}"


def semantic_constructor_display_name(
    constructor_id: ConstructorId, *, current_module_path: ModulePath | None = None
) -> str:
    return f"{_qualified_display_name(constructor_id.module_path, constructor_id.class_name, current_module_path=current_module_path)}(...)"


def semantic_call_target_display_name(target: SemanticCallTarget, *, current_module_path: ModulePath | None = None) -> str:
    if isinstance(target, FunctionCallTarget):
        return semantic_function_display_name(target.function_id, current_module_path=current_module_path)
    if isinstance(target, StaticMethodCallTarget):
        return semantic_method_display_name(target.method_id, current_module_path=current_module_path)
    if isinstance(target, InstanceMethodCallTarget):
        return f"{semantic_bound_member_receiver_display_name(target.access, current_module_path=current_module_path)}.{target.method_id.name}"
    if isinstance(target, VirtualMethodCallTarget):
        return f"{semantic_bound_member_receiver_display_name(target.access, current_module_path=current_module_path)}.{target.slot_method_name}"
    if isinstance(target, InterfaceMethodCallTarget):
        return f"{semantic_bound_member_receiver_display_name(target.access, current_module_path=current_module_path)}.{target.method_id.name}"
    if isinstance(target, ConstructorCallTarget):
        return semantic_constructor_display_name(target.constructor_id, current_module_path=current_module_path)
    if isinstance(target, ConstructorInitCallTarget):
        return semantic_constructor_display_name(target.constructor_id, current_module_path=current_module_path)
    if isinstance(target, CallableValueCallTarget):
        callee_type = expression_type_ref(target.callee)
        if current_module_path is None:
            return f"callable {semantic_type_display_name(callee_type)}"
        return f"callable {semantic_type_display_name_relative(current_module_path, callee_type)}"
    raise TypeError(f"Unsupported semantic call target display helper: {type(target).__name__}")


def _qualified_display_name(
    module_path: tuple[str, ...], name: str, *, current_module_path: ModulePath | None = None
) -> str:
    if not module_path or module_path == current_module_path:
        return name
    return f"{'.'.join(module_path)}::{name}"


def _owner_module_path(owner: SemanticFunctionLike) -> ModulePath:
    if hasattr(owner, "function_id"):
        return owner.function_id.module_path
    if hasattr(owner, "method_id"):
        return owner.method_id.module_path
    return owner.constructor_id.module_path