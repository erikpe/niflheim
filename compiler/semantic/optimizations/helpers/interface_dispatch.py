from __future__ import annotations

from dataclasses import dataclass

from compiler.semantic.ir import SemanticProgram
from compiler.semantic.symbols import ClassId, InterfaceId, InterfaceMethodId, MethodId


@dataclass(frozen=True)
class InterfaceDispatchIndex:
    implementing_method_by_class_and_interface_method: dict[tuple[ClassId, InterfaceMethodId], MethodId]


def build_interface_dispatch_index(program: SemanticProgram) -> InterfaceDispatchIndex:
    interfaces_by_id: dict[InterfaceId, object] = {}
    implementing_method_by_class_and_interface_method: dict[tuple[ClassId, InterfaceMethodId], MethodId] = {}

    for module in program.modules.values():
        for interface in module.interfaces:
            interfaces_by_id[interface.interface_id] = interface

    for module in program.modules.values():
        for cls in module.classes:
            methods_by_name = {method.method_id.name: method.method_id for method in cls.methods}
            for interface_id in cls.implemented_interfaces:
                interface = interfaces_by_id.get(interface_id)
                if interface is None:
                    raise ValueError(f"Missing semantic interface metadata for {interface_id}")
                for interface_method in interface.methods:
                    method_id = methods_by_name.get(interface_method.method_id.name)
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