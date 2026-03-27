from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from compiler.common.type_names import NON_CLASS_TYPE_NAMES, PRIMITIVE_TYPE_NAMES, TYPE_NAME_NULL
from compiler.resolver import ModulePath
from compiler.semantic.symbols import ClassId, InterfaceId
from compiler.typecheck.model import TypeInfo


SemanticTypeKind = Literal["primitive", "null", "reference", "interface", "callable"]


@dataclass(frozen=True)
class SemanticTypeRef:
    kind: SemanticTypeKind
    canonical_name: str
    display_name: str = field(compare=False)
    class_id: ClassId | None = field(default=None, compare=False)
    interface_id: InterfaceId | None = field(default=None, compare=False)
    element_type: "SemanticTypeRef | None" = None
    param_types: tuple["SemanticTypeRef", ...] = ()
    return_type: "SemanticTypeRef | None" = None

    def __post_init__(self) -> None:
        if self.kind == "callable":
            if self.class_id is not None or self.interface_id is not None or self.element_type is not None:
                raise ValueError("Callable semantic types cannot also be nominal or array types")
            if self.return_type is None and self.param_types:
                raise ValueError("Callable semantic types cannot carry param_types without a return_type")
            return

        if self.param_types or self.return_type is not None:
            raise ValueError("Only callable semantic types may carry param_types or return_type")

        if self.kind == "interface":
            if self.class_id is not None:
                raise ValueError("Interface semantic types cannot carry a class_id")
            return

        if self.kind in {"primitive", "null"}:
            if self.class_id is not None or self.interface_id is not None or self.element_type is not None:
                raise ValueError("Primitive and null semantic types cannot carry nominal or array metadata")
            return

        if self.interface_id is not None:
            raise ValueError("Reference semantic types cannot carry an interface_id")


def semantic_type_display_name(type_ref: SemanticTypeRef) -> str:
    return type_ref.display_name


def semantic_type_display_name_relative(current_module_path: ModulePath, type_ref: SemanticTypeRef) -> str:
    if semantic_type_is_array(type_ref):
        element_type = semantic_type_array_element(type_ref)
        if element_type is None:
            return semantic_type_display_name(type_ref)
        return f"{semantic_type_display_name_relative(current_module_path, element_type)}[]"
    if semantic_type_is_callable(type_ref):
        params = ", ".join(
            semantic_type_display_name_relative(current_module_path, param)
            for param in semantic_type_callable_params(type_ref)
        )
        return_type = semantic_type_callable_return(type_ref)
        if return_type is None:
            return semantic_type_display_name(type_ref)
        return f"fn({params}) -> {semantic_type_display_name_relative(current_module_path, return_type)}"
    if semantic_type_is_reference(type_ref) and type_ref.class_id is not None:
        if type_ref.class_id.module_path == current_module_path:
            return type_ref.class_id.name
        return _qualified_display_name(type_ref.class_id.module_path, type_ref.class_id.name)
    if semantic_type_is_interface(type_ref) and type_ref.interface_id is not None:
        if type_ref.interface_id.module_path == current_module_path:
            return type_ref.interface_id.name
        return _qualified_display_name(type_ref.interface_id.module_path, type_ref.interface_id.name)
    return semantic_type_display_name(type_ref)


def semantic_type_canonical_name(type_ref: SemanticTypeRef) -> str:
    return type_ref.canonical_name


def semantic_type_kind(type_ref: SemanticTypeRef) -> SemanticTypeKind:
    return type_ref.kind


def semantic_primitive_type_ref(type_name: str) -> SemanticTypeRef:
    if type_name not in PRIMITIVE_TYPE_NAMES:
        raise ValueError(f"'{type_name}' is not a primitive type name")
    return SemanticTypeRef(kind="primitive", canonical_name=type_name, display_name=type_name)


def semantic_null_type_ref() -> SemanticTypeRef:
    return SemanticTypeRef(kind="null", canonical_name=TYPE_NAME_NULL, display_name=TYPE_NAME_NULL)


def semantic_type_is_primitive(type_ref: SemanticTypeRef) -> bool:
    return type_ref.kind == "primitive"


def semantic_type_is_null(type_ref: SemanticTypeRef) -> bool:
    return type_ref.kind == "null"


def semantic_type_is_reference(type_ref: SemanticTypeRef) -> bool:
    return type_ref.kind == "reference"


def semantic_type_is_interface(type_ref: SemanticTypeRef) -> bool:
    return type_ref.kind == "interface"


def semantic_type_is_callable(type_ref: SemanticTypeRef) -> bool:
    return type_ref.kind == "callable"


def semantic_type_is_array(type_ref: SemanticTypeRef) -> bool:
    return type_ref.element_type is not None


def semantic_type_nominal_id(type_ref: SemanticTypeRef) -> ClassId | InterfaceId | None:
    if type_ref.class_id is not None:
        return type_ref.class_id
    return type_ref.interface_id


def semantic_types_have_same_nominal_identity(left: SemanticTypeRef, right: SemanticTypeRef) -> bool:
    left_id = semantic_type_nominal_id(left)
    right_id = semantic_type_nominal_id(right)
    return left_id is not None and left_id == right_id


def semantic_type_array_element(type_ref: SemanticTypeRef) -> SemanticTypeRef:
    if type_ref.element_type is None:
        raise ValueError("semantic type is not an array")
    return type_ref.element_type


def semantic_type_callable_params(type_ref: SemanticTypeRef) -> tuple[SemanticTypeRef, ...]:
    if type_ref.kind != "callable":
        raise ValueError("semantic type is not callable")
    return type_ref.param_types


def semantic_type_callable_return(type_ref: SemanticTypeRef) -> SemanticTypeRef:
    if type_ref.kind != "callable" or type_ref.return_type is None:
        raise ValueError("semantic type is not a callable with a return type")
    return type_ref.return_type


def iter_semantic_nominal_ids(type_ref: SemanticTypeRef):
    if type_ref.class_id is not None:
        yield type_ref.class_id
    if type_ref.interface_id is not None:
        yield type_ref.interface_id
    if type_ref.element_type is not None:
        yield from iter_semantic_nominal_ids(type_ref.element_type)
    for param_type in type_ref.param_types:
        yield from iter_semantic_nominal_ids(param_type)
    if type_ref.return_type is not None:
        yield from iter_semantic_nominal_ids(type_ref.return_type)


def semantic_type_ref_from_type_info(current_module_path: ModulePath, type_info: TypeInfo) -> SemanticTypeRef:
    if type_info.kind == "callable":
        if type_info.callable_params is None or type_info.callable_return is None:
            return SemanticTypeRef(kind="callable", canonical_name=type_info.name, display_name=type_info.name)
        param_types = tuple(
            semantic_type_ref_from_type_info(current_module_path, param) for param in type_info.callable_params
        )
        return_type = semantic_type_ref_from_type_info(current_module_path, type_info.callable_return)
        return _callable_semantic_type_ref(param_types, return_type)

    if type_info.element_type is not None:
        element_type = semantic_type_ref_from_type_info(current_module_path, type_info.element_type)
        return _array_semantic_type_ref(element_type)

    if type_info.kind == TYPE_NAME_NULL:
        return semantic_null_type_ref()

    if type_info.kind == "primitive":
        return semantic_primitive_type_ref(type_info.name)

    if type_info.kind == "interface":
        interface_id = _interface_id_from_type_info_name(current_module_path, type_info.name)
        canonical_name = (
            type_info.name
            if interface_id is None
            else _qualified_nominal_name(interface_id.module_path, interface_id.name)
        )
        return SemanticTypeRef(
            kind="interface", canonical_name=canonical_name, display_name=type_info.name, interface_id=interface_id
        )

    if type_info.kind == "reference":
        class_id = _class_id_from_type_info_name(current_module_path, type_info.name)
        canonical_name = (
            type_info.name if class_id is None else _qualified_nominal_name(class_id.module_path, class_id.name)
        )
        return SemanticTypeRef(
            kind="reference", canonical_name=canonical_name, display_name=type_info.name, class_id=class_id
        )

    raise ValueError(f"Unsupported TypeInfo kind for semantic lowering: {type_info.kind}")


def semantic_type_ref_for_class_id(class_id: ClassId, *, display_name: str | None = None) -> SemanticTypeRef:
    return SemanticTypeRef(
        kind="reference",
        canonical_name=_qualified_nominal_name(class_id.module_path, class_id.name),
        display_name=class_id.name if display_name is None else display_name,
        class_id=class_id,
    )


def semantic_type_ref_for_interface_id(
    interface_id: InterfaceId, *, display_name: str | None = None
) -> SemanticTypeRef:
    return SemanticTypeRef(
        kind="interface",
        canonical_name=_qualified_nominal_name(interface_id.module_path, interface_id.name),
        display_name=interface_id.name if display_name is None else display_name,
        interface_id=interface_id,
    )


def semantic_array_type_ref(element_type: SemanticTypeRef) -> SemanticTypeRef:
    return _array_semantic_type_ref(element_type)


def _callable_semantic_type_ref(
    param_types: tuple[SemanticTypeRef, ...], return_type: SemanticTypeRef
) -> SemanticTypeRef:
    return SemanticTypeRef(
        kind="callable",
        canonical_name=f"fn({', '.join(semantic_type_canonical_name(param) for param in param_types)}) -> {semantic_type_canonical_name(return_type)}",
        display_name=f"fn({', '.join(semantic_type_display_name(param) for param in param_types)}) -> {semantic_type_display_name(return_type)}",
        param_types=param_types,
        return_type=return_type,
    )


def _array_semantic_type_ref(element_type: SemanticTypeRef) -> SemanticTypeRef:
    return SemanticTypeRef(
        kind="reference",
        canonical_name=f"{semantic_type_canonical_name(element_type)}[]",
        display_name=f"{semantic_type_display_name(element_type)}[]",
        element_type=element_type,
    )


def _class_id_from_type_info_name(current_module_path: ModulePath, type_name: str) -> ClassId | None:
    if not _is_user_nominal_type_name(type_name):
        return None
    if "::" in type_name:
        owner_dotted, class_name = type_name.split("::", 1)
        return ClassId(module_path=tuple(owner_dotted.split(".")), name=class_name)
    return ClassId(module_path=current_module_path, name=type_name)


def _interface_id_from_type_info_name(current_module_path: ModulePath, type_name: str) -> InterfaceId | None:
    if not _is_user_nominal_type_name(type_name):
        return None
    if "::" in type_name:
        owner_dotted, interface_name = type_name.split("::", 1)
        return InterfaceId(module_path=tuple(owner_dotted.split(".")), name=interface_name)
    return InterfaceId(module_path=current_module_path, name=type_name)


def _qualified_nominal_name(module_path: ModulePath, name: str) -> str:
    return f"{'.'.join(module_path)}::{name}"


def _qualified_display_name(module_path: ModulePath, name: str) -> str:
    if not module_path:
        return name
    return f"{'.'.join(module_path)}::{name}"


def _is_user_nominal_type_name(type_name: str) -> bool:
    return bool(type_name) and type_name not in NON_CLASS_TYPE_NAMES and not type_name.startswith("__")
