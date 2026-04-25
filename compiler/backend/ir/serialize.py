"""Canonical JSON serialization helpers for backend IR phase-1 work."""

from __future__ import annotations

import json
import struct
from collections.abc import Mapping
from pathlib import Path

from compiler.backend.ir import model as ir_model
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.span import SourcePos, SourceSpan
from compiler.semantic.operations import (
    BinaryOpFlavor,
    BinaryOpKind,
    CastSemanticsKind,
    SemanticBinaryOp,
    SemanticUnaryOp,
    TypeTestSemanticsKind,
    UnaryOpFlavor,
    UnaryOpKind,
)
from compiler.semantic.symbols import (
    ClassId,
    ConstructorId,
    FunctionId,
    InterfaceId,
    InterfaceMethodId,
    LocalId,
    MethodId,
)
from compiler.semantic.types import SemanticTypeRef


_ARRAY_RUNTIME_KIND_TO_TEXT = {
    ArrayRuntimeKind.I64: "i64",
    ArrayRuntimeKind.U64: "u64",
    ArrayRuntimeKind.U8: "u8",
    ArrayRuntimeKind.BOOL: "bool",
    ArrayRuntimeKind.DOUBLE: "double",
    ArrayRuntimeKind.REF: "ref",
}
_ARRAY_RUNTIME_KIND_BY_TEXT = {text: kind for kind, text in _ARRAY_RUNTIME_KIND_TO_TEXT.items()}
_LOWER_HEX_DIGITS = frozenset("0123456789abcdef")


def backend_program_to_dict(
    program: ir_model.BackendProgram, *, project_root: str | Path | None = None
) -> dict[str, object]:
    root = None if project_root is None else Path(project_root).resolve()
    return {
        "schema_version": program.schema_version,
        "entry_callable_id": _serialize_function_id(program.entry_callable_id),
        "data_blobs": [_serialize_data_blob(blob) for blob in sorted(program.data_blobs, key=_data_id_sort_key)],
        "interfaces": [
            _serialize_interface_decl(interface_decl)
            for interface_decl in sorted(program.interfaces, key=lambda decl: _interface_id_sort_key(decl.interface_id))
        ],
        "classes": [
            _serialize_class_decl(class_decl)
            for class_decl in sorted(program.classes, key=lambda decl: _class_id_sort_key(decl.class_id))
        ],
        "callables": [
            _serialize_callable_decl(callable_decl, project_root=root)
            for callable_decl in sorted(program.callables, key=lambda decl: _callable_id_sort_key(decl.callable_id))
        ],
    }


def backend_program_from_dict(data: Mapping[str, object]) -> ir_model.BackendProgram:
    payload = _expect_object(data, "program")
    schema_version = _require_str(payload, "schema_version", "program")
    if schema_version != ir_model.BACKEND_IR_SCHEMA_VERSION:
        raise ValueError(f"Unsupported backend IR schema_version '{schema_version}'")

    entry_callable_id = _parse_function_id(_require_object(payload, "entry_callable_id", "program"), "entry_callable_id")
    data_blobs = tuple(_parse_data_blob(item) for item in _require_list(payload, "data_blobs", "program"))
    interfaces = tuple(
        _parse_interface_decl(item) for item in _require_list(payload, "interfaces", "program")
    )
    classes = tuple(_parse_class_decl(item) for item in _require_list(payload, "classes", "program"))
    callables = tuple(_parse_callable_decl(item) for item in _require_list(payload, "callables", "program"))

    return ir_model.BackendProgram(
        schema_version=schema_version,
        entry_callable_id=entry_callable_id,
        data_blobs=data_blobs,
        interfaces=interfaces,
        classes=classes,
        callables=callables,
    )


def dump_backend_program_json(
    program: ir_model.BackendProgram, *, project_root: str | Path | None = None
) -> str:
    return json.dumps(backend_program_to_dict(program, project_root=project_root), indent=2)


def load_backend_program_json(text: str) -> ir_model.BackendProgram:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed backend IR JSON: {exc.msg}") from exc
    return backend_program_from_dict(_expect_object(data, "program"))


def _serialize_data_blob(blob: ir_model.BackendDataBlob) -> dict[str, object]:
    return {
        "id": _serialize_data_id(blob.data_id),
        "debug_name": blob.debug_name,
        "alignment": blob.alignment,
        "bytes_hex": blob.bytes_hex,
        "readonly": blob.readonly,
    }


def _serialize_interface_decl(interface_decl: ir_model.BackendInterfaceDecl) -> dict[str, object]:
    return {
        "interface_id": _serialize_interface_id(interface_decl.interface_id),
        "methods": [_serialize_interface_method_id(method_id) for method_id in interface_decl.methods],
    }


def _serialize_field_decl(field_decl: ir_model.BackendFieldDecl) -> dict[str, object]:
    return {
        "owner_class_id": _serialize_class_id(field_decl.owner_class_id),
        "name": field_decl.name,
        "type": _serialize_semantic_type_ref(field_decl.type_ref),
        "is_private": field_decl.is_private,
        "is_final": field_decl.is_final,
    }


def _serialize_class_decl(class_decl: ir_model.BackendClassDecl) -> dict[str, object]:
    return {
        "class_id": _serialize_class_id(class_decl.class_id),
        "superclass_id": None
        if class_decl.superclass_id is None
        else _serialize_class_id(class_decl.superclass_id),
        "implemented_interfaces": [
            _serialize_interface_id(interface_id) for interface_id in class_decl.implemented_interfaces
        ],
        "fields": [_serialize_field_decl(field_decl) for field_decl in class_decl.fields],
        "methods": [_serialize_method_id(method_id) for method_id in class_decl.methods],
        "constructors": [
            _serialize_constructor_id(constructor_id) for constructor_id in class_decl.constructors
        ],
    }


def _serialize_callable_decl(
    callable_decl: ir_model.BackendCallableDecl, *, project_root: Path | None
) -> dict[str, object]:
    return {
        "callable_id": _serialize_callable_id(callable_decl.callable_id),
        "kind": callable_decl.kind,
        "signature": _serialize_signature(callable_decl.signature),
        "is_export": callable_decl.is_export,
        "is_extern": callable_decl.is_extern,
        "is_static": callable_decl.is_static,
        "is_private": callable_decl.is_private,
        "registers": [
            _serialize_register(register, project_root=project_root)
            for register in sorted(callable_decl.registers, key=lambda register: register.reg_id.ordinal)
        ],
        "param_regs": [_serialize_reg_id(reg_id) for reg_id in sorted(callable_decl.param_regs, key=lambda reg_id: reg_id.ordinal)],
        "receiver_reg": None if callable_decl.receiver_reg is None else _serialize_reg_id(callable_decl.receiver_reg),
        "entry_block_id": None
        if callable_decl.entry_block_id is None
        else _serialize_block_id(callable_decl.entry_block_id),
        "blocks": [
            _serialize_block(block, project_root=project_root)
            for block in sorted(callable_decl.blocks, key=lambda block: block.block_id.ordinal)
        ],
        "span": _serialize_source_span(callable_decl.span, project_root=project_root),
    }


def _serialize_register(register: ir_model.BackendRegister, *, project_root: Path | None) -> dict[str, object]:
    return {
        "id": _serialize_reg_id(register.reg_id),
        "type": _serialize_semantic_type_ref(register.type_ref),
        "debug_name": register.debug_name,
        "origin_kind": register.origin_kind,
        "semantic_local_id": None
        if register.semantic_local_id is None
        else _serialize_local_id(register.semantic_local_id),
        "span": None if register.span is None else _serialize_source_span(register.span, project_root=project_root),
    }


def _serialize_signature(signature: ir_model.BackendSignature) -> dict[str, object]:
    return {
        "param_types": [_serialize_semantic_type_ref(type_ref) for type_ref in signature.param_types],
        "return_type": None if signature.return_type is None else _serialize_semantic_type_ref(signature.return_type),
    }


def _serialize_block(block: ir_model.BackendBlock, *, project_root: Path | None) -> dict[str, object]:
    return {
        "id": _serialize_block_id(block.block_id),
        "debug_name": block.debug_name,
        "instructions": [
            _serialize_instruction(instruction, project_root=project_root)
            for instruction in sorted(block.instructions, key=lambda instruction: instruction.inst_id.ordinal)
        ],
        "terminator": _serialize_terminator(block.terminator, project_root=project_root),
        "span": _serialize_source_span(block.span, project_root=project_root),
    }


def _serialize_instruction(
    instruction: ir_model.BackendInstruction, *, project_root: Path | None
) -> dict[str, object]:
    base = {"id": _serialize_inst_id(instruction.inst_id)}
    if isinstance(instruction, ir_model.BackendConstInst):
        base.update(
            {
                "kind": "const",
                "dest": _serialize_reg_id(instruction.dest),
                "constant": _serialize_constant(instruction.constant),
            }
        )
    elif isinstance(instruction, ir_model.BackendCopyInst):
        base.update(
            {
                "kind": "copy",
                "dest": _serialize_reg_id(instruction.dest),
                "source": _serialize_operand(instruction.source),
            }
        )
    elif isinstance(instruction, ir_model.BackendUnaryInst):
        base.update(
            {
                "kind": "unary",
                "dest": _serialize_reg_id(instruction.dest),
                "op": _serialize_unary_op(instruction.op),
                "operand": _serialize_operand(instruction.operand),
            }
        )
    elif isinstance(instruction, ir_model.BackendBinaryInst):
        base.update(
            {
                "kind": "binary",
                "dest": _serialize_reg_id(instruction.dest),
                "op": _serialize_binary_op(instruction.op),
                "left": _serialize_operand(instruction.left),
                "right": _serialize_operand(instruction.right),
            }
        )
    elif isinstance(instruction, ir_model.BackendCastInst):
        base.update(
            {
                "kind": "cast",
                "dest": _serialize_reg_id(instruction.dest),
                "cast_kind": instruction.cast_kind.value,
                "operand": _serialize_operand(instruction.operand),
                "target_type": _serialize_semantic_type_ref(instruction.target_type_ref),
                "trap_on_failure": instruction.trap_on_failure,
            }
        )
    elif isinstance(instruction, ir_model.BackendTypeTestInst):
        base.update(
            {
                "kind": "type_test",
                "dest": _serialize_reg_id(instruction.dest),
                "test_kind": instruction.test_kind.value,
                "operand": _serialize_operand(instruction.operand),
                "target_type": _serialize_semantic_type_ref(instruction.target_type_ref),
            }
        )
    elif isinstance(instruction, ir_model.BackendAllocObjectInst):
        base.update(
            {
                "kind": "alloc_object",
                "dest": _serialize_reg_id(instruction.dest),
                "class_id": _serialize_class_id(instruction.class_id),
                "effects": _serialize_effects(instruction.effects),
            }
        )
    elif isinstance(instruction, ir_model.BackendFieldLoadInst):
        base.update(
            {
                "kind": "field_load",
                "dest": _serialize_reg_id(instruction.dest),
                "object_ref": _serialize_operand(instruction.object_ref),
                "owner_class_id": _serialize_class_id(instruction.owner_class_id),
                "field_name": instruction.field_name,
            }
        )
    elif isinstance(instruction, ir_model.BackendFieldStoreInst):
        base.update(
            {
                "kind": "field_store",
                "object_ref": _serialize_operand(instruction.object_ref),
                "owner_class_id": _serialize_class_id(instruction.owner_class_id),
                "field_name": instruction.field_name,
                "value": _serialize_operand(instruction.value),
            }
        )
    elif isinstance(instruction, ir_model.BackendArrayAllocInst):
        base.update(
            {
                "kind": "array_alloc",
                "dest": _serialize_reg_id(instruction.dest),
                "array_runtime_kind": _serialize_array_runtime_kind(instruction.array_runtime_kind),
                "length": _serialize_operand(instruction.length),
                "effects": _serialize_effects(instruction.effects),
            }
        )
    elif isinstance(instruction, ir_model.BackendArrayLengthInst):
        base.update(
            {
                "kind": "array_len",
                "dest": _serialize_reg_id(instruction.dest),
                "array_ref": _serialize_operand(instruction.array_ref),
            }
        )
    elif isinstance(instruction, ir_model.BackendArrayLoadInst):
        base.update(
            {
                "kind": "array_load",
                "dest": _serialize_reg_id(instruction.dest),
                "array_runtime_kind": _serialize_array_runtime_kind(instruction.array_runtime_kind),
                "array_ref": _serialize_operand(instruction.array_ref),
                "index": _serialize_operand(instruction.index),
            }
        )
    elif isinstance(instruction, ir_model.BackendArrayStoreInst):
        base.update(
            {
                "kind": "array_store",
                "array_runtime_kind": _serialize_array_runtime_kind(instruction.array_runtime_kind),
                "array_ref": _serialize_operand(instruction.array_ref),
                "index": _serialize_operand(instruction.index),
                "value": _serialize_operand(instruction.value),
            }
        )
    elif isinstance(instruction, ir_model.BackendArraySliceInst):
        base.update(
            {
                "kind": "array_slice",
                "dest": _serialize_reg_id(instruction.dest),
                "array_runtime_kind": _serialize_array_runtime_kind(instruction.array_runtime_kind),
                "array_ref": _serialize_operand(instruction.array_ref),
                "begin": _serialize_operand(instruction.begin),
                "end": _serialize_operand(instruction.end),
                "effects": _serialize_effects(instruction.effects),
            }
        )
    elif isinstance(instruction, ir_model.BackendArraySliceStoreInst):
        base.update(
            {
                "kind": "array_slice_store",
                "array_runtime_kind": _serialize_array_runtime_kind(instruction.array_runtime_kind),
                "array_ref": _serialize_operand(instruction.array_ref),
                "begin": _serialize_operand(instruction.begin),
                "end": _serialize_operand(instruction.end),
                "value": _serialize_operand(instruction.value),
            }
        )
    elif isinstance(instruction, ir_model.BackendNullCheckInst):
        base.update({"kind": "null_check", "value": _serialize_operand(instruction.value)})
    elif isinstance(instruction, ir_model.BackendBoundsCheckInst):
        base.update(
            {
                "kind": "bounds_check",
                "array_ref": _serialize_operand(instruction.array_ref),
                "index": _serialize_operand(instruction.index),
            }
        )
    elif isinstance(instruction, ir_model.BackendCallInst):
        base.update(
            {
                "kind": "call",
                "dest": None if instruction.dest is None else _serialize_reg_id(instruction.dest),
                "target": _serialize_call_target(instruction.target),
                "args": [_serialize_operand(argument) for argument in instruction.args],
                "signature": _serialize_signature(instruction.signature),
                "effects": _serialize_effects(instruction.effects),
            }
        )
    else:
        raise TypeError(f"Unsupported backend instruction type: {type(instruction).__name__}")

    base["span"] = _serialize_source_span(instruction.span, project_root=project_root)
    return base


def _serialize_terminator(
    terminator: ir_model.BackendTerminator, *, project_root: Path | None
) -> dict[str, object]:
    if isinstance(terminator, ir_model.BackendJumpTerminator):
        return {
            "kind": "jump",
            "target_block_id": _serialize_block_id(terminator.target_block_id),
            "span": _serialize_source_span(terminator.span, project_root=project_root),
        }
    if isinstance(terminator, ir_model.BackendBranchTerminator):
        return {
            "kind": "branch",
            "condition": _serialize_operand(terminator.condition),
            "true_block_id": _serialize_block_id(terminator.true_block_id),
            "false_block_id": _serialize_block_id(terminator.false_block_id),
            "span": _serialize_source_span(terminator.span, project_root=project_root),
        }
    if isinstance(terminator, ir_model.BackendReturnTerminator):
        return {
            "kind": "return",
            "value": None if terminator.value is None else _serialize_operand(terminator.value),
            "span": _serialize_source_span(terminator.span, project_root=project_root),
        }
    if isinstance(terminator, ir_model.BackendTrapTerminator):
        return {
            "kind": "trap",
            "trap_kind": terminator.trap_kind,
            "message": terminator.message,
            "span": _serialize_source_span(terminator.span, project_root=project_root),
        }
    raise TypeError(f"Unsupported backend terminator type: {type(terminator).__name__}")


def _serialize_call_target(target: ir_model.BackendCallTarget) -> dict[str, object]:
    if isinstance(target, ir_model.BackendDirectCallTarget):
        return {"kind": "direct", "callable_id": _serialize_callable_id(target.callable_id)}
    if isinstance(target, ir_model.BackendRuntimeCallTarget):
        return {"kind": "runtime", "name": target.name, "ref_arg_indices": list(target.ref_arg_indices)}
    if isinstance(target, ir_model.BackendIndirectCallTarget):
        return {"kind": "indirect", "callee": _serialize_operand(target.callee)}
    if isinstance(target, ir_model.BackendVirtualCallTarget):
        return {
            "kind": "virtual",
            "slot_owner_class_id": _serialize_class_id(target.slot_owner_class_id),
            "method_name": target.method_name,
            "selected_method_id": _serialize_method_id(target.selected_method_id),
        }
    if isinstance(target, ir_model.BackendInterfaceCallTarget):
        return {
            "kind": "interface",
            "interface_id": _serialize_interface_id(target.interface_id),
            "method_id": _serialize_interface_method_id(target.method_id),
        }
    raise TypeError(f"Unsupported backend call target type: {type(target).__name__}")


def _serialize_operand(operand: ir_model.BackendOperand) -> dict[str, object]:
    if isinstance(operand, ir_model.BackendRegOperand):
        return {"kind": "reg", "reg_id": _serialize_reg_id(operand.reg_id)}
    if isinstance(operand, ir_model.BackendConstOperand):
        return {"kind": "const", "constant": _serialize_constant(operand.constant)}
    if isinstance(operand, ir_model.BackendDataOperand):
        return {"kind": "data", "data_id": _serialize_data_id(operand.data_id)}
    raise TypeError(f"Unsupported backend operand type: {type(operand).__name__}")


def _serialize_constant(constant: ir_model.BackendConstant) -> dict[str, object]:
    if isinstance(constant, ir_model.BackendIntConst):
        return {"kind": constant.type_name, "value": constant.value}
    if isinstance(constant, ir_model.BackendBoolConst):
        return {"kind": "bool", "value": constant.value}
    if isinstance(constant, ir_model.BackendDoubleConst):
        return {"kind": "double", "bits_hex": f"{_double_value_bits(constant.value):016x}"}
    if isinstance(constant, ir_model.BackendNullConst):
        return {"kind": "null"}
    if isinstance(constant, ir_model.BackendUnitConst):
        return {"kind": "unit"}
    raise TypeError(f"Unsupported backend constant type: {type(constant).__name__}")


def _serialize_effects(effects: ir_model.BackendEffects) -> dict[str, object]:
    return {
        "reads_memory": effects.reads_memory,
        "writes_memory": effects.writes_memory,
        "may_gc": effects.may_gc,
        "may_trap": effects.may_trap,
        "is_noreturn": effects.is_noreturn,
        "needs_safepoint_hooks": effects.needs_safepoint_hooks,
    }


def _serialize_semantic_type_ref(type_ref: SemanticTypeRef) -> dict[str, object]:
    data: dict[str, object] = {
        "kind": type_ref.kind,
        "canonical_name": type_ref.canonical_name,
        "display_name": type_ref.display_name,
    }
    if type_ref.class_id is not None:
        data["class_id"] = _serialize_class_id(type_ref.class_id)
    if type_ref.interface_id is not None:
        data["interface_id"] = _serialize_interface_id(type_ref.interface_id)
    if type_ref.element_type is not None:
        data["element_type"] = _serialize_semantic_type_ref(type_ref.element_type)
    if type_ref.param_types:
        data["param_types"] = [_serialize_semantic_type_ref(param_type) for param_type in type_ref.param_types]
    if type_ref.return_type is not None:
        data["return_type"] = _serialize_semantic_type_ref(type_ref.return_type)
    return data


def _serialize_unary_op(op: SemanticUnaryOp) -> dict[str, object]:
    return {"kind": op.kind.value, "flavor": op.flavor.value}


def _serialize_binary_op(op: SemanticBinaryOp) -> dict[str, object]:
    return {"kind": op.kind.value, "flavor": op.flavor.value}


def _serialize_local_id(local_id: LocalId) -> dict[str, object]:
    return {"owner": _serialize_callable_id(local_id.owner_id), "ordinal": local_id.ordinal}


def _serialize_source_span(span: SourceSpan, *, project_root: Path | None) -> dict[str, object]:
    return {
        "start": _serialize_source_pos(span.start, project_root=project_root),
        "end": _serialize_source_pos(span.end, project_root=project_root),
    }


def _serialize_source_pos(pos: SourcePos, *, project_root: Path | None) -> dict[str, object]:
    return {
        "path": _normalize_source_path(pos.path, project_root=project_root),
        "offset": pos.offset,
        "line": pos.line,
        "column": pos.column,
    }


def _normalize_source_path(path: str, *, project_root: Path | None) -> str:
    if path.startswith("<") and path.endswith(">"):
        return path

    normalized = path.replace("\\", "/")
    if project_root is None:
        return normalized

    raw_path = Path(path)
    if not raw_path.is_absolute():
        return normalized

    try:
        relative_path = raw_path.resolve().relative_to(project_root)
    except ValueError:
        return normalized
    return relative_path.as_posix()


def _serialize_callable_id(callable_id: ir_model.BackendCallableId) -> dict[str, object]:
    if isinstance(callable_id, FunctionId):
        return _serialize_function_id(callable_id)
    if isinstance(callable_id, MethodId):
        return _serialize_method_id(callable_id)
    return _serialize_constructor_id(callable_id)


def _serialize_function_id(function_id: FunctionId) -> dict[str, object]:
    return {"kind": "function", "module_path": list(function_id.module_path), "name": function_id.name}


def _serialize_method_id(method_id: MethodId) -> dict[str, object]:
    return {
        "kind": "method",
        "module_path": list(method_id.module_path),
        "class_name": method_id.class_name,
        "name": method_id.name,
    }


def _serialize_constructor_id(constructor_id: ConstructorId) -> dict[str, object]:
    return {
        "kind": "constructor",
        "module_path": list(constructor_id.module_path),
        "class_name": constructor_id.class_name,
        "ordinal": constructor_id.ordinal,
    }


def _serialize_class_id(class_id: ClassId) -> dict[str, object]:
    return {"kind": "class", "module_path": list(class_id.module_path), "name": class_id.name}


def _serialize_interface_id(interface_id: InterfaceId) -> dict[str, object]:
    return {"kind": "interface", "module_path": list(interface_id.module_path), "name": interface_id.name}


def _serialize_interface_method_id(method_id: InterfaceMethodId) -> dict[str, object]:
    return {
        "kind": "interface_method",
        "module_path": list(method_id.module_path),
        "interface_name": method_id.interface_name,
        "name": method_id.name,
    }


def _serialize_reg_id(reg_id: ir_model.BackendRegId) -> str:
    return f"r{reg_id.ordinal}"


def _serialize_block_id(block_id: ir_model.BackendBlockId) -> str:
    return f"b{block_id.ordinal}"


def _serialize_inst_id(inst_id: ir_model.BackendInstId) -> str:
    return f"i{inst_id.ordinal}"


def _serialize_data_id(data_id: ir_model.BackendDataId) -> str:
    return f"d{data_id.ordinal}"


def _serialize_array_runtime_kind(runtime_kind: ArrayRuntimeKind) -> str:
    return _ARRAY_RUNTIME_KIND_TO_TEXT[runtime_kind]


def _parse_data_blob(value: object) -> ir_model.BackendDataBlob:
    payload = _expect_object(value, "data blob")
    return ir_model.BackendDataBlob(
        data_id=_parse_data_id(_require_str(payload, "id", "data blob"), context="data blob id"),
        debug_name=_require_str(payload, "debug_name", "data blob"),
        alignment=_require_int(payload, "alignment", "data blob"),
        bytes_hex=_require_str(payload, "bytes_hex", "data blob"),
        readonly=_require_bool(payload, "readonly", "data blob"),
    )


def _parse_interface_decl(value: object) -> ir_model.BackendInterfaceDecl:
    payload = _expect_object(value, "interface declaration")
    return ir_model.BackendInterfaceDecl(
        interface_id=_parse_interface_id(
            _require_object(payload, "interface_id", "interface declaration"),
            "interface declaration interface_id",
        ),
        methods=tuple(
            _parse_interface_method_id(_expect_object(method_id, "interface declaration method id"), "interface method id")
            for method_id in _require_list(payload, "methods", "interface declaration")
        ),
    )


def _parse_field_decl(value: object) -> ir_model.BackendFieldDecl:
    payload = _expect_object(value, "field declaration")
    return ir_model.BackendFieldDecl(
        owner_class_id=_parse_class_id(
            _require_object(payload, "owner_class_id", "field declaration"), "field declaration owner_class_id"
        ),
        name=_require_str(payload, "name", "field declaration"),
        type_ref=_parse_semantic_type_ref(_require_object(payload, "type", "field declaration")),
        is_private=_require_bool(payload, "is_private", "field declaration"),
        is_final=_require_bool(payload, "is_final", "field declaration"),
    )


def _parse_class_decl(value: object) -> ir_model.BackendClassDecl:
    payload = _expect_object(value, "class declaration")
    superclass_payload = payload.get("superclass_id")
    return ir_model.BackendClassDecl(
        class_id=_parse_class_id(_require_object(payload, "class_id", "class declaration"), "class declaration class_id"),
        superclass_id=None
        if superclass_payload is None
        else _parse_class_id(_expect_object(superclass_payload, "class declaration superclass_id"), "superclass_id"),
        implemented_interfaces=tuple(
            _parse_interface_id(_expect_object(interface_id, "implemented interface"), "implemented interface")
            for interface_id in _require_list(payload, "implemented_interfaces", "class declaration")
        ),
        fields=tuple(_parse_field_decl(field_decl) for field_decl in _require_list(payload, "fields", "class declaration")),
        methods=tuple(
            _parse_method_id(_expect_object(method_id, "class method id"), "class method id")
            for method_id in _require_list(payload, "methods", "class declaration")
        ),
        constructors=tuple(
            _parse_constructor_id(_expect_object(constructor_id, "class constructor id"), "class constructor id")
            for constructor_id in _require_list(payload, "constructors", "class declaration")
        ),
    )


def _parse_callable_decl(value: object) -> ir_model.BackendCallableDecl:
    payload = _expect_object(value, "callable declaration")
    callable_id = _parse_callable_id(
        _require_object(payload, "callable_id", "callable declaration"), "callable declaration callable_id"
    )
    receiver_payload = payload.get("receiver_reg")
    entry_block_payload = payload.get("entry_block_id")
    return ir_model.BackendCallableDecl(
        callable_id=callable_id,
        kind=_require_literal(payload, "kind", "callable declaration", {"function", "method", "constructor"}),
        signature=_parse_signature(_require_object(payload, "signature", "callable declaration")),
        is_export=_require_bool(payload, "is_export", "callable declaration"),
        is_extern=_require_bool(payload, "is_extern", "callable declaration"),
        is_static=_require_optional_bool(payload, "is_static", "callable declaration"),
        is_private=_require_optional_bool(payload, "is_private", "callable declaration"),
        registers=tuple(
            _parse_register(register, callable_id=callable_id)
            for register in _require_list(payload, "registers", "callable declaration")
        ),
        param_regs=tuple(
            _parse_reg_id(_require_str_value(reg_id, "param reg id"), callable_id=callable_id, context="param reg id")
            for reg_id in _require_list(payload, "param_regs", "callable declaration")
        ),
        receiver_reg=None
        if receiver_payload is None
        else _parse_reg_id(_require_str_value(receiver_payload, "receiver_reg"), callable_id=callable_id, context="receiver_reg"),
        entry_block_id=None
        if entry_block_payload is None
        else _parse_block_id(
            _require_str_value(entry_block_payload, "entry_block_id"), callable_id=callable_id, context="entry_block_id"
        ),
        blocks=tuple(
            _parse_block(block, callable_id=callable_id)
            for block in _require_list(payload, "blocks", "callable declaration")
        ),
        span=_parse_source_span(_require_object(payload, "span", "callable declaration")),
    )


def _parse_register(value: object, *, callable_id: ir_model.BackendCallableId) -> ir_model.BackendRegister:
    payload = _expect_object(value, "register")
    span_payload = payload.get("span")
    semantic_local_payload = payload.get("semantic_local_id")
    return ir_model.BackendRegister(
        reg_id=_parse_reg_id(_require_str(payload, "id", "register"), callable_id=callable_id, context="register id"),
        type_ref=_parse_semantic_type_ref(_require_object(payload, "type", "register")),
        debug_name=_require_str(payload, "debug_name", "register"),
        origin_kind=_require_literal(
            payload,
            "origin_kind",
            "register",
            {"receiver", "param", "local", "helper", "temp", "synthetic"},
        ),
        semantic_local_id=None
        if semantic_local_payload is None
        else _parse_local_id(_expect_object(semantic_local_payload, "semantic_local_id")),
        span=None if span_payload is None else _parse_source_span(_expect_object(span_payload, "register span")),
    )


def _parse_signature(value: object) -> ir_model.BackendSignature:
    payload = _expect_object(value, "signature")
    return_type_payload = payload.get("return_type")
    return ir_model.BackendSignature(
        param_types=tuple(
            _parse_semantic_type_ref(_expect_object(type_ref, "signature param type"))
            for type_ref in _require_list(payload, "param_types", "signature")
        ),
        return_type=None
        if return_type_payload is None
        else _parse_semantic_type_ref(_expect_object(return_type_payload, "signature return type")),
    )


def _parse_block(value: object, *, callable_id: ir_model.BackendCallableId) -> ir_model.BackendBlock:
    payload = _expect_object(value, "block")
    return ir_model.BackendBlock(
        block_id=_parse_block_id(_require_str(payload, "id", "block"), callable_id=callable_id, context="block id"),
        debug_name=_require_str(payload, "debug_name", "block"),
        instructions=tuple(
            _parse_instruction(instruction, callable_id=callable_id)
            for instruction in _require_list(payload, "instructions", "block")
        ),
        terminator=_parse_terminator(
            _require_object(payload, "terminator", "block"), callable_id=callable_id
        ),
        span=_parse_source_span(_require_object(payload, "span", "block")),
    )


def _parse_instruction(value: object, *, callable_id: ir_model.BackendCallableId) -> ir_model.BackendInstruction:
    payload = _expect_object(value, "instruction")
    inst_id = _parse_inst_id(_require_str(payload, "id", "instruction"), callable_id=callable_id, context="instruction id")
    span = _parse_source_span(_require_object(payload, "span", "instruction"))
    kind = _require_str(payload, "kind", "instruction")

    if kind == "const":
        return ir_model.BackendConstInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "const instruction"), callable_id=callable_id, context="const dest"),
            constant=_parse_constant(_require_object(payload, "constant", "const instruction")),
            span=span,
        )
    if kind == "copy":
        return ir_model.BackendCopyInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "copy instruction"), callable_id=callable_id, context="copy dest"),
            source=_parse_operand(_require_object(payload, "source", "copy instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "unary":
        return ir_model.BackendUnaryInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "unary instruction"), callable_id=callable_id, context="unary dest"),
            op=_parse_unary_op(_require_object(payload, "op", "unary instruction")),
            operand=_parse_operand(_require_object(payload, "operand", "unary instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "binary":
        return ir_model.BackendBinaryInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "binary instruction"), callable_id=callable_id, context="binary dest"),
            op=_parse_binary_op(_require_object(payload, "op", "binary instruction")),
            left=_parse_operand(_require_object(payload, "left", "binary instruction"), callable_id=callable_id),
            right=_parse_operand(_require_object(payload, "right", "binary instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "cast":
        return ir_model.BackendCastInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "cast instruction"), callable_id=callable_id, context="cast dest"),
            cast_kind=_parse_enum_value(
                CastSemanticsKind, _require_str(payload, "cast_kind", "cast instruction"), "cast semantics"
            ),
            operand=_parse_operand(_require_object(payload, "operand", "cast instruction"), callable_id=callable_id),
            target_type_ref=_parse_semantic_type_ref(_require_object(payload, "target_type", "cast instruction")),
            trap_on_failure=_require_bool(payload, "trap_on_failure", "cast instruction"),
            span=span,
        )
    if kind == "type_test":
        return ir_model.BackendTypeTestInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "type_test instruction"), callable_id=callable_id, context="type_test dest"),
            test_kind=_parse_enum_value(
                TypeTestSemanticsKind, _require_str(payload, "test_kind", "type_test instruction"), "type-test semantics"
            ),
            operand=_parse_operand(_require_object(payload, "operand", "type_test instruction"), callable_id=callable_id),
            target_type_ref=_parse_semantic_type_ref(_require_object(payload, "target_type", "type_test instruction")),
            span=span,
        )
    if kind == "alloc_object":
        return ir_model.BackendAllocObjectInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "alloc_object instruction"), callable_id=callable_id, context="alloc_object dest"),
            class_id=_parse_class_id(_require_object(payload, "class_id", "alloc_object instruction"), "alloc_object class_id"),
            effects=_parse_effects(_require_object(payload, "effects", "alloc_object instruction")),
            span=span,
        )
    if kind == "field_load":
        return ir_model.BackendFieldLoadInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "field_load instruction"), callable_id=callable_id, context="field_load dest"),
            object_ref=_parse_operand(_require_object(payload, "object_ref", "field_load instruction"), callable_id=callable_id),
            owner_class_id=_parse_class_id(_require_object(payload, "owner_class_id", "field_load instruction"), "field_load owner_class_id"),
            field_name=_require_str(payload, "field_name", "field_load instruction"),
            span=span,
        )
    if kind == "field_store":
        return ir_model.BackendFieldStoreInst(
            inst_id=inst_id,
            object_ref=_parse_operand(_require_object(payload, "object_ref", "field_store instruction"), callable_id=callable_id),
            owner_class_id=_parse_class_id(_require_object(payload, "owner_class_id", "field_store instruction"), "field_store owner_class_id"),
            field_name=_require_str(payload, "field_name", "field_store instruction"),
            value=_parse_operand(_require_object(payload, "value", "field_store instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "array_alloc":
        return ir_model.BackendArrayAllocInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "array_alloc instruction"), callable_id=callable_id, context="array_alloc dest"),
            array_runtime_kind=_parse_array_runtime_kind(_require_str(payload, "array_runtime_kind", "array_alloc instruction")),
            length=_parse_operand(_require_object(payload, "length", "array_alloc instruction"), callable_id=callable_id),
            effects=_parse_effects(_require_object(payload, "effects", "array_alloc instruction")),
            span=span,
        )
    if kind == "array_len":
        return ir_model.BackendArrayLengthInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "array_len instruction"), callable_id=callable_id, context="array_len dest"),
            array_ref=_parse_operand(_require_object(payload, "array_ref", "array_len instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "array_load":
        return ir_model.BackendArrayLoadInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "array_load instruction"), callable_id=callable_id, context="array_load dest"),
            array_runtime_kind=_parse_array_runtime_kind(_require_str(payload, "array_runtime_kind", "array_load instruction")),
            array_ref=_parse_operand(_require_object(payload, "array_ref", "array_load instruction"), callable_id=callable_id),
            index=_parse_operand(_require_object(payload, "index", "array_load instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "array_store":
        return ir_model.BackendArrayStoreInst(
            inst_id=inst_id,
            array_runtime_kind=_parse_array_runtime_kind(_require_str(payload, "array_runtime_kind", "array_store instruction")),
            array_ref=_parse_operand(_require_object(payload, "array_ref", "array_store instruction"), callable_id=callable_id),
            index=_parse_operand(_require_object(payload, "index", "array_store instruction"), callable_id=callable_id),
            value=_parse_operand(_require_object(payload, "value", "array_store instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "array_slice":
        return ir_model.BackendArraySliceInst(
            inst_id=inst_id,
            dest=_parse_reg_id(_require_str(payload, "dest", "array_slice instruction"), callable_id=callable_id, context="array_slice dest"),
            array_runtime_kind=_parse_array_runtime_kind(_require_str(payload, "array_runtime_kind", "array_slice instruction")),
            array_ref=_parse_operand(_require_object(payload, "array_ref", "array_slice instruction"), callable_id=callable_id),
            begin=_parse_operand(_require_object(payload, "begin", "array_slice instruction"), callable_id=callable_id),
            end=_parse_operand(_require_object(payload, "end", "array_slice instruction"), callable_id=callable_id),
            effects=_parse_effects(_require_object(payload, "effects", "array_slice instruction")),
            span=span,
        )
    if kind == "array_slice_store":
        return ir_model.BackendArraySliceStoreInst(
            inst_id=inst_id,
            array_runtime_kind=_parse_array_runtime_kind(_require_str(payload, "array_runtime_kind", "array_slice_store instruction")),
            array_ref=_parse_operand(_require_object(payload, "array_ref", "array_slice_store instruction"), callable_id=callable_id),
            begin=_parse_operand(_require_object(payload, "begin", "array_slice_store instruction"), callable_id=callable_id),
            end=_parse_operand(_require_object(payload, "end", "array_slice_store instruction"), callable_id=callable_id),
            value=_parse_operand(_require_object(payload, "value", "array_slice_store instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "null_check":
        return ir_model.BackendNullCheckInst(
            inst_id=inst_id,
            value=_parse_operand(_require_object(payload, "value", "null_check instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "bounds_check":
        return ir_model.BackendBoundsCheckInst(
            inst_id=inst_id,
            array_ref=_parse_operand(_require_object(payload, "array_ref", "bounds_check instruction"), callable_id=callable_id),
            index=_parse_operand(_require_object(payload, "index", "bounds_check instruction"), callable_id=callable_id),
            span=span,
        )
    if kind == "call":
        dest_payload = payload.get("dest")
        return ir_model.BackendCallInst(
            inst_id=inst_id,
            dest=None
            if dest_payload is None
            else _parse_reg_id(_require_str_value(dest_payload, "call dest"), callable_id=callable_id, context="call dest"),
            target=_parse_call_target(_require_object(payload, "target", "call instruction"), callable_id=callable_id),
            args=tuple(
                _parse_operand(_expect_object(argument, "call argument"), callable_id=callable_id)
                for argument in _require_list(payload, "args", "call instruction")
            ),
            signature=_parse_signature(_require_object(payload, "signature", "call instruction")),
            effects=_parse_effects(_require_object(payload, "effects", "call instruction")),
            span=span,
        )

    raise ValueError(f"Unsupported backend IR instruction kind '{kind}'")


def _parse_terminator(value: object, *, callable_id: ir_model.BackendCallableId) -> ir_model.BackendTerminator:
    payload = _expect_object(value, "terminator")
    span = _parse_source_span(_require_object(payload, "span", "terminator"))
    kind = _require_str(payload, "kind", "terminator")

    if kind == "jump":
        return ir_model.BackendJumpTerminator(
            span=span,
            target_block_id=_parse_block_id(
                _require_str(payload, "target_block_id", "jump terminator"), callable_id=callable_id, context="jump target_block_id"
            ),
        )
    if kind == "branch":
        return ir_model.BackendBranchTerminator(
            span=span,
            condition=_parse_operand(_require_object(payload, "condition", "branch terminator"), callable_id=callable_id),
            true_block_id=_parse_block_id(
                _require_str(payload, "true_block_id", "branch terminator"), callable_id=callable_id, context="branch true_block_id"
            ),
            false_block_id=_parse_block_id(
                _require_str(payload, "false_block_id", "branch terminator"), callable_id=callable_id, context="branch false_block_id"
            ),
        )
    if kind == "return":
        value_payload = payload.get("value")
        return ir_model.BackendReturnTerminator(
            span=span,
            value=None
            if value_payload is None
            else _parse_operand(_expect_object(value_payload, "return value"), callable_id=callable_id),
        )
    if kind == "trap":
        message_payload = payload.get("message")
        return ir_model.BackendTrapTerminator(
            span=span,
            trap_kind=_require_literal(
                payload,
                "trap_kind",
                "trap terminator",
                {"bad_cast", "bounds", "null_deref", "panic", "unreachable"},
            ),
            message=None if message_payload is None else _require_str_value(message_payload, "trap message"),
        )

    raise ValueError(f"Unsupported backend IR terminator kind '{kind}'")


def _parse_call_target(
    value: object, *, callable_id: ir_model.BackendCallableId
) -> ir_model.BackendCallTarget:
    payload = _expect_object(value, "call target")
    kind = _require_str(payload, "kind", "call target")

    if kind == "direct":
        return ir_model.BackendDirectCallTarget(
            callable_id=_parse_callable_id(
                _require_object(payload, "callable_id", "direct call target"), "direct call target callable_id"
            )
        )
    if kind == "runtime":
        return ir_model.BackendRuntimeCallTarget(
            name=_require_str(payload, "name", "runtime call target"),
            ref_arg_indices=tuple(
                _require_int_value(index, "runtime ref_arg_indices entry")
                for index in _require_list(payload, "ref_arg_indices", "runtime call target")
            ),
        )
    if kind == "indirect":
        return ir_model.BackendIndirectCallTarget(
            callee=_parse_operand(_require_object(payload, "callee", "indirect call target"), callable_id=callable_id)
        )
    if kind == "virtual":
        return ir_model.BackendVirtualCallTarget(
            slot_owner_class_id=_parse_class_id(
                _require_object(payload, "slot_owner_class_id", "virtual call target"), "virtual slot_owner_class_id"
            ),
            method_name=_require_str(payload, "method_name", "virtual call target"),
            selected_method_id=_parse_method_id(
                _require_object(payload, "selected_method_id", "virtual call target"), "virtual selected_method_id"
            ),
        )
    if kind == "interface":
        return ir_model.BackendInterfaceCallTarget(
            interface_id=_parse_interface_id(
                _require_object(payload, "interface_id", "interface call target"), "interface call target interface_id"
            ),
            method_id=_parse_interface_method_id(
                _require_object(payload, "method_id", "interface call target"), "interface call target method_id"
            ),
        )

    raise ValueError(f"Unsupported backend IR call target kind '{kind}'")


def _parse_operand(value: object, *, callable_id: ir_model.BackendCallableId) -> ir_model.BackendOperand:
    payload = _expect_object(value, "operand")
    kind = _require_str(payload, "kind", "operand")
    if kind == "reg":
        return ir_model.BackendRegOperand(
            reg_id=_parse_reg_id(_require_str(payload, "reg_id", "reg operand"), callable_id=callable_id, context="reg operand reg_id")
        )
    if kind == "const":
        return ir_model.BackendConstOperand(
            constant=_parse_constant(_require_object(payload, "constant", "const operand"))
        )
    if kind == "data":
        return ir_model.BackendDataOperand(
            data_id=_parse_data_id(_require_str(payload, "data_id", "data operand"), context="data operand data_id")
        )
    raise ValueError(f"Unsupported backend IR operand kind '{kind}'")


def _parse_constant(value: object) -> ir_model.BackendConstant:
    payload = _expect_object(value, "constant")
    kind = _require_str(payload, "kind", "constant")
    if kind in {"i64", "u64", "u8"}:
        return ir_model.BackendIntConst(type_name=kind, value=_require_int(payload, "value", "integer constant"))
    if kind == "bool":
        return ir_model.BackendBoolConst(value=_require_bool(payload, "value", "boolean constant"))
    if kind == "double":
        bits_hex = _require_str(payload, "bits_hex", "double constant")
        if len(bits_hex) != 16 or any(ch not in _LOWER_HEX_DIGITS for ch in bits_hex):
            raise ValueError(
                "Malformed backend IR double constant: bits_hex must contain exactly 16 lower-case hexadecimal digits"
            )
        return ir_model.BackendDoubleConst(value=_float_from_binary64_bits(int(bits_hex, 16)))
    if kind == "null":
        return ir_model.BackendNullConst()
    if kind == "unit":
        return ir_model.BackendUnitConst()
    raise ValueError(f"Unsupported backend IR constant kind '{kind}'")


def _parse_effects(value: object) -> ir_model.BackendEffects:
    payload = _expect_object(value, "effects")
    return ir_model.BackendEffects(
        reads_memory=_require_bool(payload, "reads_memory", "effects"),
        writes_memory=_require_bool(payload, "writes_memory", "effects"),
        may_gc=_require_bool(payload, "may_gc", "effects"),
        may_trap=_require_bool(payload, "may_trap", "effects"),
        is_noreturn=_require_bool(payload, "is_noreturn", "effects"),
        needs_safepoint_hooks=_require_bool(payload, "needs_safepoint_hooks", "effects"),
    )


def _parse_semantic_type_ref(value: object) -> SemanticTypeRef:
    payload = _expect_object(value, "semantic type")
    class_id_payload = payload.get("class_id")
    interface_id_payload = payload.get("interface_id")
    element_type_payload = payload.get("element_type")
    return_type_payload = payload.get("return_type")
    param_types_payload = payload.get("param_types", [])
    if not isinstance(param_types_payload, list):
        raise ValueError("Malformed backend IR semantic type: 'param_types' must be a list")
    return SemanticTypeRef(
        kind=_require_literal(
            payload,
            "kind",
            "semantic type",
            {"primitive", "null", "reference", "interface", "callable"},
        ),
        canonical_name=_require_str(payload, "canonical_name", "semantic type"),
        display_name=_require_str(payload, "display_name", "semantic type"),
        class_id=None if class_id_payload is None else _parse_class_id(_expect_object(class_id_payload, "semantic type class_id"), "semantic type class_id"),
        interface_id=None
        if interface_id_payload is None
        else _parse_interface_id(_expect_object(interface_id_payload, "semantic type interface_id"), "semantic type interface_id"),
        element_type=None
        if element_type_payload is None
        else _parse_semantic_type_ref(_expect_object(element_type_payload, "semantic type element_type")),
        param_types=tuple(
            _parse_semantic_type_ref(_expect_object(param_type, "semantic type param_types entry"))
            for param_type in param_types_payload
        ),
        return_type=None
        if return_type_payload is None
        else _parse_semantic_type_ref(_expect_object(return_type_payload, "semantic type return_type")),
    )


def _parse_unary_op(value: object) -> SemanticUnaryOp:
    payload = _expect_object(value, "unary op")
    return SemanticUnaryOp(
        kind=_parse_enum_value(UnaryOpKind, _require_str(payload, "kind", "unary op"), "unary op kind"),
        flavor=_parse_enum_value(UnaryOpFlavor, _require_str(payload, "flavor", "unary op"), "unary op flavor"),
    )


def _parse_binary_op(value: object) -> SemanticBinaryOp:
    payload = _expect_object(value, "binary op")
    return SemanticBinaryOp(
        kind=_parse_enum_value(BinaryOpKind, _require_str(payload, "kind", "binary op"), "binary op kind"),
        flavor=_parse_enum_value(BinaryOpFlavor, _require_str(payload, "flavor", "binary op"), "binary op flavor"),
    )


def _parse_local_id(value: object) -> LocalId:
    payload = _expect_object(value, "local id")
    return LocalId(
        owner_id=_parse_callable_id(_require_object(payload, "owner", "local id"), "local id owner"),
        ordinal=_require_int(payload, "ordinal", "local id"),
    )


def _parse_source_span(value: object) -> SourceSpan:
    payload = _expect_object(value, "source span")
    return SourceSpan(
        start=_parse_source_pos(_require_object(payload, "start", "source span"), context="source span start"),
        end=_parse_source_pos(_require_object(payload, "end", "source span"), context="source span end"),
    )


def _parse_source_pos(value: object, *, context: str = "source position") -> SourcePos:
    payload = _expect_object(value, context)
    return SourcePos(
        path=_require_str(payload, "path", context),
        offset=_require_int(payload, "offset", context),
        line=_require_int(payload, "line", context),
        column=_require_int(payload, "column", context),
    )


def _parse_function_id(value: Mapping[str, object], context: str) -> FunctionId:
    payload = _expect_object(value, context)
    if _require_str(payload, "kind", context) != "function":
        raise ValueError(f"Malformed backend IR {context}: expected function ID")
    return FunctionId(
        module_path=_parse_module_path(_require_list(payload, "module_path", context), context),
        name=_require_str(payload, "name", context),
    )


def _parse_method_id(value: Mapping[str, object], context: str) -> MethodId:
    payload = _expect_object(value, context)
    if _require_str(payload, "kind", context) != "method":
        raise ValueError(f"Malformed backend IR {context}: expected method ID")
    return MethodId(
        module_path=_parse_module_path(_require_list(payload, "module_path", context), context),
        class_name=_require_str(payload, "class_name", context),
        name=_require_str(payload, "name", context),
    )


def _parse_constructor_id(value: Mapping[str, object], context: str) -> ConstructorId:
    payload = _expect_object(value, context)
    if _require_str(payload, "kind", context) != "constructor":
        raise ValueError(f"Malformed backend IR {context}: expected constructor ID")
    return ConstructorId(
        module_path=_parse_module_path(_require_list(payload, "module_path", context), context),
        class_name=_require_str(payload, "class_name", context),
        ordinal=_require_int(payload, "ordinal", context),
    )


def _parse_class_id(value: Mapping[str, object], context: str) -> ClassId:
    payload = _expect_object(value, context)
    if _require_str(payload, "kind", context) != "class":
        raise ValueError(f"Malformed backend IR {context}: expected class ID")
    return ClassId(
        module_path=_parse_module_path(_require_list(payload, "module_path", context), context),
        name=_require_str(payload, "name", context),
    )


def _parse_interface_id(value: Mapping[str, object], context: str) -> InterfaceId:
    payload = _expect_object(value, context)
    if _require_str(payload, "kind", context) != "interface":
        raise ValueError(f"Malformed backend IR {context}: expected interface ID")
    return InterfaceId(
        module_path=_parse_module_path(_require_list(payload, "module_path", context), context),
        name=_require_str(payload, "name", context),
    )


def _parse_interface_method_id(value: Mapping[str, object], context: str) -> InterfaceMethodId:
    payload = _expect_object(value, context)
    if _require_str(payload, "kind", context) != "interface_method":
        raise ValueError(f"Malformed backend IR {context}: expected interface method ID")
    return InterfaceMethodId(
        module_path=_parse_module_path(_require_list(payload, "module_path", context), context),
        interface_name=_require_str(payload, "interface_name", context),
        name=_require_str(payload, "name", context),
    )


def _parse_callable_id(value: Mapping[str, object], context: str) -> ir_model.BackendCallableId:
    payload = _expect_object(value, context)
    kind = _require_str(payload, "kind", context)
    if kind == "function":
        return _parse_function_id(payload, context)
    if kind == "method":
        return _parse_method_id(payload, context)
    if kind == "constructor":
        return _parse_constructor_id(payload, context)
    raise ValueError(f"Malformed backend IR {context}: unsupported callable ID kind '{kind}'")


def _parse_module_path(values: list[object], context: str) -> tuple[str, ...]:
    module_parts: list[str] = []
    for part in values:
        if not isinstance(part, str):
            raise ValueError(f"Malformed backend IR {context}: module_path entries must be strings")
        module_parts.append(part)
    return tuple(module_parts)


def _parse_reg_id(text: str, *, callable_id: ir_model.BackendCallableId, context: str) -> ir_model.BackendRegId:
    return ir_model.BackendRegId(owner_id=callable_id, ordinal=_parse_short_id_ordinal(text, prefix="r", context=context))


def _parse_block_id(text: str, *, callable_id: ir_model.BackendCallableId, context: str) -> ir_model.BackendBlockId:
    return ir_model.BackendBlockId(owner_id=callable_id, ordinal=_parse_short_id_ordinal(text, prefix="b", context=context))


def _parse_inst_id(text: str, *, callable_id: ir_model.BackendCallableId, context: str) -> ir_model.BackendInstId:
    return ir_model.BackendInstId(owner_id=callable_id, ordinal=_parse_short_id_ordinal(text, prefix="i", context=context))


def _parse_data_id(text: str, *, context: str) -> ir_model.BackendDataId:
    return ir_model.BackendDataId(ordinal=_parse_short_id_ordinal(text, prefix="d", context=context))


def _parse_short_id_ordinal(text: str, *, prefix: str, context: str) -> int:
    if not text.startswith(prefix) or not text[len(prefix) :].isdigit():
        raise ValueError(f"Malformed backend IR {context}: expected '{prefix}<ordinal>'")
    return int(text[len(prefix) :])


def _parse_array_runtime_kind(text: str) -> ArrayRuntimeKind:
    runtime_kind = _ARRAY_RUNTIME_KIND_BY_TEXT.get(text)
    if runtime_kind is None:
        raise ValueError(f"Malformed backend IR array runtime kind: unsupported value '{text}'")
    return runtime_kind


def _parse_enum_value(enum_type, value: str, context: str):
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"Malformed backend IR {context}: unsupported value '{value}'") from exc


def _double_value_bits(value: float) -> int:
    return struct.unpack("<Q", struct.pack("<d", value))[0]


def _float_from_binary64_bits(bits: int) -> float:
    return struct.unpack("<d", struct.pack("<Q", bits))[0]


def _data_id_sort_key(blob: ir_model.BackendDataBlob) -> int:
    return blob.data_id.ordinal


def _class_id_sort_key(class_id: ClassId) -> tuple[tuple[str, ...], str]:
    return class_id.module_path, class_id.name


def _interface_id_sort_key(interface_id: InterfaceId) -> tuple[tuple[str, ...], str]:
    return interface_id.module_path, interface_id.name


def _callable_id_sort_key(callable_id: ir_model.BackendCallableId) -> tuple[tuple[str, ...], int, str, str, int]:
    if isinstance(callable_id, FunctionId):
        return callable_id.module_path, 0, callable_id.name, "", -1
    if isinstance(callable_id, MethodId):
        return callable_id.module_path, 1, callable_id.class_name, callable_id.name, -1
    return callable_id.module_path, 2, callable_id.class_name, "", callable_id.ordinal


def _expect_object(value: object, context: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"Malformed backend IR {context}: expected object")
    return value


def _require_object(payload: Mapping[str, object], field_name: str, context: str) -> Mapping[str, object]:
    if field_name not in payload:
        raise ValueError(f"Malformed backend IR {context}: missing '{field_name}'")
    return _expect_object(payload[field_name], f"{context} {field_name}")


def _require_list(payload: Mapping[str, object], field_name: str, context: str) -> list[object]:
    if field_name not in payload:
        raise ValueError(f"Malformed backend IR {context}: missing '{field_name}'")
    value = payload[field_name]
    if not isinstance(value, list):
        raise ValueError(f"Malformed backend IR {context}: '{field_name}' must be a list")
    return value


def _require_str(payload: Mapping[str, object], field_name: str, context: str) -> str:
    if field_name not in payload:
        raise ValueError(f"Malformed backend IR {context}: missing '{field_name}'")
    return _require_str_value(payload[field_name], f"{context} {field_name}")


def _require_str_value(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Malformed backend IR {context}: expected string")
    return value


def _require_int(payload: Mapping[str, object], field_name: str, context: str) -> int:
    if field_name not in payload:
        raise ValueError(f"Malformed backend IR {context}: missing '{field_name}'")
    return _require_int_value(payload[field_name], f"{context} {field_name}")


def _require_int_value(value: object, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"Malformed backend IR {context}: expected integer")
    return value


def _require_bool(payload: Mapping[str, object], field_name: str, context: str) -> bool:
    if field_name not in payload:
        raise ValueError(f"Malformed backend IR {context}: missing '{field_name}'")
    value = payload[field_name]
    if not isinstance(value, bool):
        raise ValueError(f"Malformed backend IR {context}: '{field_name}' must be a boolean")
    return value


def _require_optional_bool(payload: Mapping[str, object], field_name: str, context: str) -> bool | None:
    value = payload.get(field_name)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"Malformed backend IR {context}: '{field_name}' must be a boolean or null")
    return value


def _require_literal(payload: Mapping[str, object], field_name: str, context: str, allowed: set[str]) -> str:
    value = _require_str(payload, field_name, context)
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"Malformed backend IR {context}: '{field_name}' must be one of {allowed_values}")
    return value


__all__ = [
    "backend_program_from_dict",
    "backend_program_to_dict",
    "dump_backend_program_json",
    "load_backend_program_json",
]