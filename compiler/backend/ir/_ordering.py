"""Internal deterministic ordering helpers shared by backend IR dumpers."""

from __future__ import annotations

from compiler.backend.ir import model as ir_model
from compiler.semantic.symbols import ClassId, FunctionId, InterfaceId, InterfaceMethodId, MethodId


def data_blob_sort_key(blob: ir_model.BackendDataBlob) -> int:
    return blob.data_id.ordinal


def interface_id_sort_key(interface_id: InterfaceId) -> tuple[tuple[str, ...], str]:
    return interface_id.module_path, interface_id.name


def interface_method_id_sort_key(method_id: InterfaceMethodId) -> tuple[tuple[str, ...], str, str]:
    return method_id.module_path, method_id.interface_name, method_id.name


def class_id_sort_key(class_id: ClassId) -> tuple[tuple[str, ...], str]:
    return class_id.module_path, class_id.name


def callable_id_sort_key(callable_id: ir_model.BackendCallableId) -> tuple[tuple[str, ...], int, str, str, int]:
    if isinstance(callable_id, FunctionId):
        return callable_id.module_path, 0, callable_id.name, "", -1
    if isinstance(callable_id, MethodId):
        return callable_id.module_path, 1, callable_id.class_name, callable_id.name, -1
    return callable_id.module_path, 2, callable_id.class_name, "", callable_id.ordinal


def reg_id_sort_key(reg_id: ir_model.BackendRegId) -> int:
    return reg_id.ordinal


def register_sort_key(register: ir_model.BackendRegister) -> int:
    return reg_id_sort_key(register.reg_id)


def block_id_sort_key(block_id: ir_model.BackendBlockId) -> int:
    return block_id.ordinal


def block_sort_key(block: ir_model.BackendBlock) -> int:
    return block_id_sort_key(block.block_id)


def inst_id_sort_key(inst_id: ir_model.BackendInstId) -> int:
    return inst_id.ordinal


def instruction_sort_key(instruction: ir_model.BackendInstruction) -> int:
    return inst_id_sort_key(instruction.inst_id)