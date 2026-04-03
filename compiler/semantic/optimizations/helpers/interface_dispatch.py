from __future__ import annotations

from dataclasses import dataclass

from compiler.semantic.ir import SemanticProgram
from compiler.semantic.symbols import ClassId, InterfaceId, InterfaceMethodId, MethodId


@dataclass(frozen=True)
class InterfaceDispatchIndex:
    implementing_method_by_class_and_interface_method: dict[tuple[ClassId, InterfaceMethodId], MethodId]


def build_interface_dispatch_index(program: SemanticProgram) -> InterfaceDispatchIndex:
    interfaces_by_id: dict[InterfaceId, object] = {}
    classes_by_id: dict[ClassId, object] = {}
    implementing_method_by_class_and_interface_method: dict[tuple[ClassId, InterfaceMethodId], MethodId] = {}

    for module in program.modules.values():
        for interface in module.interfaces:
            interfaces_by_id[interface.interface_id] = interface
        for cls in module.classes:
            classes_by_id[cls.class_id] = cls

    for module in program.modules.values():
        for cls in module.classes:
            for interface_id in cls.implemented_interfaces:
                interface = interfaces_by_id.get(interface_id)
                if interface is None:
                    raise ValueError(f"Missing semantic interface metadata for {interface_id}")
                for interface_method in interface.methods:
                    method_id = _resolve_declared_or_inherited_method_id(
                        classes_by_id, cls.class_id, interface_method.method_id.name
                    )
                    if method_id is None:
                        raise ValueError(
                            f"Missing implementing method '{interface_method.method_id.name}' for class {cls.class_id} and interface {interface_id}"
                        )
                    implementing_method_by_class_and_interface_method[(cls.class_id, interface_method.method_id)] = method_id

    return InterfaceDispatchIndex(
        implementing_method_by_class_and_interface_method=implementing_method_by_class_and_interface_method
    )


def resolve_implementing_method(
    dispatch_index: InterfaceDispatchIndex, class_id: ClassId, interface_method_id: InterfaceMethodId
) -> MethodId | None:
    return dispatch_index.implementing_method_by_class_and_interface_method.get((class_id, interface_method_id))


def _resolve_declared_or_inherited_method_id(classes_by_id: dict[ClassId, object], class_id: ClassId, method_name: str) -> MethodId | None:
    current_class = classes_by_id.get(class_id)
    while current_class is not None:
        for method in current_class.methods:
            if method.method_id.name == method_name:
                return method.method_id
        if current_class.superclass_id is None:
            return None
        current_class = classes_by_id.get(current_class.superclass_id)
    return None