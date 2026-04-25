"""Backend IR verifier for phase-1 backend pipeline work."""

from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import model as ir_model
from compiler.backend.ir._ordering import block_sort_key, callable_id_sort_key, instruction_sort_key
from compiler.codegen.abi.runtime import has_runtime_call_metadata, runtime_call_metadata
from compiler.codegen.types import array_element_runtime_kind_for_type_ref, is_reference_type_ref
from compiler.common.collection_protocols import ArrayRuntimeKind
from compiler.common.type_names import TYPE_NAME_BOOL, TYPE_NAME_I64, TYPE_NAME_OBJ, TYPE_NAME_U64, TYPE_NAME_UNIT
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, MethodId
from compiler.semantic.types import (
    SemanticTypeRef,
    semantic_null_type_ref,
    semantic_primitive_type_ref,
    semantic_type_canonical_name,
    semantic_type_display_name,
    semantic_type_is_array,
    semantic_type_ref_for_class_id,
    semantic_type_ref_for_interface_id,
)


_BOOL_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_BOOL)
_I64_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_I64)
_U64_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_U64)
_UNIT_TYPE_REF = semantic_primitive_type_ref(TYPE_NAME_UNIT)
_NULL_TYPE_REF = semantic_null_type_ref()
_OPAQUE_DATA_TYPE_REF = SemanticTypeRef(kind="reference", canonical_name=TYPE_NAME_OBJ, display_name=TYPE_NAME_OBJ)
_ARRAY_RUNTIME_KIND_TO_TEXT = {
    ArrayRuntimeKind.I64: TYPE_NAME_I64,
    ArrayRuntimeKind.U64: TYPE_NAME_U64,
    ArrayRuntimeKind.U8: "u8",
    ArrayRuntimeKind.BOOL: TYPE_NAME_BOOL,
    ArrayRuntimeKind.DOUBLE: "double",
    ArrayRuntimeKind.REF: "ref",
}


class BackendIRVerificationError(ValueError):
    """Raised when backend IR violates the frozen phase-1 contract."""


@dataclass(frozen=True)
class _ProgramIndex:
    data_blob_by_id: dict[ir_model.BackendDataId, ir_model.BackendDataBlob]
    interface_by_id: dict[InterfaceId, ir_model.BackendInterfaceDecl]
    class_by_id: dict[ClassId, ir_model.BackendClassDecl]
    callable_by_id: dict[ir_model.BackendCallableId, ir_model.BackendCallableDecl]
    field_by_owner_and_name: dict[tuple[ClassId, str], ir_model.BackendFieldDecl]


@dataclass(frozen=True)
class _CallableMustState:
    in_defined: dict[ir_model.BackendBlockId, frozenset[ir_model.BackendRegId]]
    in_nonnull: dict[ir_model.BackendBlockId, frozenset[ir_model.BackendOperand]]
    in_bounds: dict[
        ir_model.BackendBlockId,
        frozenset[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
    ]


def verify_backend_program(program: ir_model.BackendProgram) -> None:
    if program.schema_version != ir_model.BACKEND_IR_SCHEMA_VERSION:
        raise BackendIRVerificationError(
            f"Backend IR program: unsupported schema_version '{program.schema_version}'"
        )

    index = _build_program_index(program)
    entry_callable = index.callable_by_id.get(program.entry_callable_id)
    if entry_callable is None:
        raise BackendIRVerificationError(
            f"Backend IR program: entry callable '{_format_function_id(program.entry_callable_id)}' is missing"
        )
    if entry_callable.kind != "function":
        raise BackendIRVerificationError(
            f"Backend IR program: entry callable '{_format_function_id(program.entry_callable_id)}' must be a function"
        )

    for callable_decl in sorted(program.callables, key=lambda decl: callable_id_sort_key(decl.callable_id)):
        _verify_callable(callable_decl, index)


def _build_program_index(program: ir_model.BackendProgram) -> _ProgramIndex:
    data_blob_by_id: dict[ir_model.BackendDataId, ir_model.BackendDataBlob] = {}
    interface_by_id: dict[InterfaceId, ir_model.BackendInterfaceDecl] = {}
    class_by_id: dict[ClassId, ir_model.BackendClassDecl] = {}
    callable_by_id: dict[ir_model.BackendCallableId, ir_model.BackendCallableDecl] = {}
    field_by_owner_and_name: dict[tuple[ClassId, str], ir_model.BackendFieldDecl] = {}

    for data_blob in program.data_blobs:
        _ensure_unique(
            data_blob_by_id,
            data_blob.data_id,
            data_blob,
            lambda data_id: f"Backend IR program: duplicate data blob ID '{_format_data_id(data_id)}'",
        )

    for interface_decl in program.interfaces:
        _ensure_unique(
            interface_by_id,
            interface_decl.interface_id,
            interface_decl,
            lambda interface_id: f"Backend IR program: duplicate interface ID '{_format_interface_id(interface_id)}'",
        )

    for class_decl in program.classes:
        _ensure_unique(
            class_by_id,
            class_decl.class_id,
            class_decl,
            lambda class_id: f"Backend IR program: duplicate class ID '{_format_class_id(class_id)}'",
        )
        for field_decl in class_decl.fields:
            field_key = (class_decl.class_id, field_decl.name)
            _ensure_unique(
                field_by_owner_and_name,
                field_key,
                field_decl,
                lambda key: (
                    f"Backend IR class '{_format_class_id(key[0])}': duplicate field '{key[1]}'"
                ),
            )

    for callable_decl in program.callables:
        _ensure_unique(
            callable_by_id,
            callable_decl.callable_id,
            callable_decl,
            lambda callable_id: f"Backend IR program: duplicate callable ID '{_format_callable_id(callable_id)}'",
        )

    return _ProgramIndex(
        data_blob_by_id=data_blob_by_id,
        interface_by_id=interface_by_id,
        class_by_id=class_by_id,
        callable_by_id=callable_by_id,
        field_by_owner_and_name=field_by_owner_and_name,
    )


def _verify_callable(callable_decl: ir_model.BackendCallableDecl, index: _ProgramIndex) -> None:
    _verify_callable_id_matches_kind(callable_decl)

    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister] = {}
    block_by_id: dict[ir_model.BackendBlockId, ir_model.BackendBlock] = {}
    instruction_by_id: dict[ir_model.BackendInstId, ir_model.BackendInstruction] = {}

    for register in callable_decl.registers:
        if register.reg_id.owner_id != callable_decl.callable_id:
            _callable_error(
                callable_decl,
                f"register '{_format_reg_id(register.reg_id)}' is owned by a different callable",
            )
        _ensure_unique(
            register_by_id,
            register.reg_id,
            register,
            lambda reg_id: (
                f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}': "
                f"duplicate register ID '{_format_reg_id(reg_id)}'"
            ),
        )

    for block in callable_decl.blocks:
        if block.block_id.owner_id != callable_decl.callable_id:
            _callable_error(
                callable_decl,
                f"block '{_format_block_id(block.block_id)}' is owned by a different callable",
            )
        _ensure_unique(
            block_by_id,
            block.block_id,
            block,
            lambda block_id: (
                f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}': "
                f"duplicate block ID '{_format_block_id(block_id)}'"
            ),
        )
        for instruction in block.instructions:
            if instruction.inst_id.owner_id != callable_decl.callable_id:
                _block_error(
                    callable_decl,
                    block,
                    f"instruction '{_format_inst_id(instruction.inst_id)}' is owned by a different callable",
                )
            _ensure_unique(
                instruction_by_id,
                instruction.inst_id,
                instruction,
                lambda inst_id: (
                    f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}': "
                    f"duplicate instruction ID '{_format_inst_id(inst_id)}'"
                ),
            )

    _verify_callable_signature_and_entry(callable_decl, register_by_id, block_by_id, index)
    if callable_decl.is_extern:
        return

    assert callable_decl.entry_block_id is not None
    successor_by_block = _build_successor_map(callable_decl, block_by_id, register_by_id, index)
    reachable_block_ids = _reachable_blocks(callable_decl.entry_block_id, successor_by_block)
    if len(reachable_block_ids) != len(block_by_id):
        unreachable_block = next(
            block
            for block in sorted(callable_decl.blocks, key=block_sort_key)
            if block.block_id not in reachable_block_ids
        )
        _callable_error(
            callable_decl,
            f"block '{_format_block_id(unreachable_block.block_id)}' is unreachable from entry",
        )

    must_state = _compute_callable_must_state(
        callable_decl,
        register_by_id=register_by_id,
        successor_by_block=successor_by_block,
        reachable_block_ids=reachable_block_ids,
    )
    _verify_blocks_and_instructions(
        callable_decl,
        index=index,
        register_by_id=register_by_id,
        block_by_id=block_by_id,
        successor_by_block=successor_by_block,
        must_state=must_state,
    )


def _verify_callable_id_matches_kind(callable_decl: ir_model.BackendCallableDecl) -> None:
    callable_id = callable_decl.callable_id
    if callable_decl.kind == "function" and not isinstance(callable_id, FunctionId):
        _callable_error(callable_decl, "kind 'function' must use a FunctionId")
    if callable_decl.kind == "method" and not isinstance(callable_id, MethodId):
        _callable_error(callable_decl, "kind 'method' must use a MethodId")
    if callable_decl.kind == "constructor" and not isinstance(callable_id, ConstructorId):
        _callable_error(callable_decl, "kind 'constructor' must use a ConstructorId")


def _verify_callable_signature_and_entry(
    callable_decl: ir_model.BackendCallableDecl,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    block_by_id: dict[ir_model.BackendBlockId, ir_model.BackendBlock],
    index: _ProgramIndex,
) -> None:
    if len(callable_decl.param_regs) != len(callable_decl.signature.param_types):
        _callable_error(
            callable_decl,
            "signature.param_types must have the same length as param_regs",
        )

    seen_param_regs: set[ir_model.BackendRegId] = set()
    for reg_id, type_ref in zip(callable_decl.param_regs, callable_decl.signature.param_types):
        register = register_by_id.get(reg_id)
        if register is None:
            _callable_error(
                callable_decl,
                f"param_regs contains undeclared register '{_format_reg_id(reg_id)}'",
            )
        if reg_id in seen_param_regs:
            _callable_error(
                callable_decl,
                f"param_regs contains duplicate register '{_format_reg_id(reg_id)}'",
            )
        seen_param_regs.add(reg_id)
        if register.type_ref != type_ref:
            _callable_error(
                callable_decl,
                f"parameter register '{_format_reg_id(reg_id)}' type '{_format_type(register.type_ref)}' "
                f"does not match signature type '{_format_type(type_ref)}'",
            )

    if callable_decl.is_extern:
        if callable_decl.entry_block_id is not None:
            _callable_error(callable_decl, "extern callables must not declare an entry_block_id")
        if callable_decl.blocks:
            _callable_error(callable_decl, "extern callables must not contain blocks")
    else:
        if callable_decl.entry_block_id is None:
            _callable_error(callable_decl, "non-extern callables must declare an entry_block_id")
        if not callable_decl.blocks:
            _callable_error(callable_decl, "non-extern callables must contain at least one block")
        if callable_decl.entry_block_id is not None and callable_decl.entry_block_id not in block_by_id:
            _callable_error(
                callable_decl,
                f"entry block '{_format_block_id(callable_decl.entry_block_id)}' is not declared in the callable",
            )

    receiver_register = None
    if callable_decl.receiver_reg is not None:
        receiver_register = register_by_id.get(callable_decl.receiver_reg)
        if receiver_register is None:
            _callable_error(
                callable_decl,
                f"receiver_reg '{_format_reg_id(callable_decl.receiver_reg)}' is not declared",
            )
        if receiver_register.origin_kind != "receiver":
            _callable_error(
                callable_decl,
                f"receiver_reg '{_format_reg_id(callable_decl.receiver_reg)}' must use origin_kind 'receiver'",
            )
        if callable_decl.receiver_reg in seen_param_regs:
            _callable_error(
                callable_decl,
                f"receiver_reg '{_format_reg_id(callable_decl.receiver_reg)}' must not appear in param_regs",
            )

    if callable_decl.kind == "function" and callable_decl.receiver_reg is not None:
        _callable_error(callable_decl, "functions must not declare a receiver_reg")

    if callable_decl.kind == "method":
        owner_class_id = ClassId(
            module_path=callable_decl.callable_id.module_path,
            name=callable_decl.callable_id.class_name,
        )
        if owner_class_id not in index.class_by_id:
            _callable_error(
                callable_decl,
                f"owner class '{_format_class_id(owner_class_id)}' is not declared",
            )
        if callable_decl.is_static is False and callable_decl.receiver_reg is None:
            _callable_error(callable_decl, "instance methods must declare a receiver_reg")
        if callable_decl.is_static is True and callable_decl.receiver_reg is not None:
            _callable_error(callable_decl, "static methods must not declare a receiver_reg")
        if receiver_register is not None:
            expected_receiver_type = semantic_type_ref_for_class_id(owner_class_id)
            if receiver_register.type_ref != expected_receiver_type:
                _callable_error(
                    callable_decl,
                    f"receiver register '{_format_reg_id(receiver_register.reg_id)}' type "
                    f"'{_format_type(receiver_register.type_ref)}' must match owner class '{_format_type(expected_receiver_type)}'",
                )

    if callable_decl.kind == "constructor":
        owner_class_id = ClassId(
            module_path=callable_decl.callable_id.module_path,
            name=callable_decl.callable_id.class_name,
        )
        if owner_class_id not in index.class_by_id:
            _callable_error(
                callable_decl,
                f"owner class '{_format_class_id(owner_class_id)}' is not declared",
            )
        if callable_decl.receiver_reg is None or receiver_register is None:
            _callable_error(callable_decl, "constructors must declare a receiver_reg")
        expected_receiver_type = semantic_type_ref_for_class_id(owner_class_id)
        if receiver_register is not None and receiver_register.type_ref != expected_receiver_type:
            _callable_error(
                callable_decl,
                f"constructor receiver type '{_format_type(receiver_register.type_ref)}' must match "
                f"constructed class '{_format_type(expected_receiver_type)}'",
            )
        if callable_decl.signature.return_type is None:
            _callable_error(callable_decl, "constructors must declare a non-unit return type")
        if callable_decl.signature.return_type is not None and callable_decl.signature.return_type != expected_receiver_type:
            _callable_error(
                callable_decl,
                f"constructor return type '{_format_type(callable_decl.signature.return_type)}' must match "
                f"constructed class '{_format_type(expected_receiver_type)}'",
            )


def _build_successor_map(
    callable_decl: ir_model.BackendCallableDecl,
    block_by_id: dict[ir_model.BackendBlockId, ir_model.BackendBlock],
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    index: _ProgramIndex,
) -> dict[ir_model.BackendBlockId, tuple[ir_model.BackendBlockId, ...]]:
    successor_by_block: dict[ir_model.BackendBlockId, tuple[ir_model.BackendBlockId, ...]] = {}
    for block in sorted(callable_decl.blocks, key=block_sort_key):
        terminator = block.terminator
        if isinstance(terminator, ir_model.BackendJumpTerminator):
            _require_block_reference(callable_decl, block, terminator.target_block_id, block_by_id)
            successor_by_block[block.block_id] = (terminator.target_block_id,)
            continue
        if isinstance(terminator, ir_model.BackendBranchTerminator):
            _require_block_reference(callable_decl, block, terminator.true_block_id, block_by_id)
            _require_block_reference(callable_decl, block, terminator.false_block_id, block_by_id)
            if terminator.true_block_id == terminator.false_block_id:
                _block_error(callable_decl, block, "branch successors must differ")
            successor_by_block[block.block_id] = (terminator.true_block_id, terminator.false_block_id)
            continue
        if isinstance(terminator, (ir_model.BackendReturnTerminator, ir_model.BackendTrapTerminator)):
            successor_by_block[block.block_id] = ()
            continue
        _block_error(callable_decl, block, f"unsupported terminator type '{type(terminator).__name__}'")
    return successor_by_block


def _require_block_reference(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    block_id: ir_model.BackendBlockId,
    block_by_id: dict[ir_model.BackendBlockId, ir_model.BackendBlock],
) -> None:
    if block_id.owner_id != callable_decl.callable_id or block_id not in block_by_id:
        _block_error(
            callable_decl,
            block,
            f"terminator references undeclared block '{_format_block_id(block_id)}'",
        )


def _reachable_blocks(
    entry_block_id: ir_model.BackendBlockId,
    successor_by_block: dict[ir_model.BackendBlockId, tuple[ir_model.BackendBlockId, ...]],
) -> set[ir_model.BackendBlockId]:
    reachable: set[ir_model.BackendBlockId] = set()
    stack = [entry_block_id]
    while stack:
        block_id = stack.pop()
        if block_id in reachable:
            continue
        reachable.add(block_id)
        stack.extend(reversed(successor_by_block[block_id]))
    return reachable


def _compute_callable_must_state(
    callable_decl: ir_model.BackendCallableDecl,
    *,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    successor_by_block: dict[ir_model.BackendBlockId, tuple[ir_model.BackendBlockId, ...]],
    reachable_block_ids: set[ir_model.BackendBlockId],
) -> _CallableMustState:
    block_by_id = {block.block_id: block for block in callable_decl.blocks}
    predecessor_by_block = {
        block_id: []
        for block_id in reachable_block_ids
    }
    for source_block_id, successors in successor_by_block.items():
        for successor_block_id in successors:
            if successor_block_id in predecessor_by_block:
                predecessor_by_block[successor_block_id].append(source_block_id)

    entry_defs = set(callable_decl.param_regs)
    if callable_decl.receiver_reg is not None:
        entry_defs.add(callable_decl.receiver_reg)

    in_defined = {block_id: frozenset() for block_id in reachable_block_ids}
    out_defined = {block_id: frozenset() for block_id in reachable_block_ids}
    in_nonnull = {block_id: frozenset() for block_id in reachable_block_ids}
    out_nonnull = {block_id: frozenset() for block_id in reachable_block_ids}
    in_bounds = {block_id: frozenset() for block_id in reachable_block_ids}
    out_bounds = {block_id: frozenset() for block_id in reachable_block_ids}

    changed = True
    ordered_blocks = [block for block in sorted(callable_decl.blocks, key=block_sort_key) if block.block_id in reachable_block_ids]
    while changed:
        changed = False
        for block in ordered_blocks:
            block_id = block.block_id
            predecessors = predecessor_by_block[block_id]
            if block_id == callable_decl.entry_block_id:
                next_in_defined = frozenset(entry_defs)
                next_in_nonnull = frozenset()
                next_in_bounds = frozenset()
            else:
                next_in_defined = _intersect_sets(out_defined[pred] for pred in predecessors)
                next_in_nonnull = _intersect_sets(out_nonnull[pred] for pred in predecessors)
                next_in_bounds = _intersect_sets(out_bounds[pred] for pred in predecessors)

            next_out_defined = next_in_defined | _block_defined_registers(block)
            next_out_nonnull, next_out_bounds = _apply_block_check_transfer(
                block,
                in_nonnull=next_in_nonnull,
                in_bounds=next_in_bounds,
            )

            if in_defined[block_id] != next_in_defined:
                in_defined[block_id] = next_in_defined
                changed = True
            if in_nonnull[block_id] != next_in_nonnull:
                in_nonnull[block_id] = next_in_nonnull
                changed = True
            if in_bounds[block_id] != next_in_bounds:
                in_bounds[block_id] = next_in_bounds
                changed = True
            if out_defined[block_id] != next_out_defined:
                out_defined[block_id] = next_out_defined
                changed = True
            if out_nonnull[block_id] != next_out_nonnull:
                out_nonnull[block_id] = next_out_nonnull
                changed = True
            if out_bounds[block_id] != next_out_bounds:
                out_bounds[block_id] = next_out_bounds
                changed = True

    return _CallableMustState(
        in_defined=in_defined,
        in_nonnull=in_nonnull,
        in_bounds=in_bounds,
    )


def _verify_blocks_and_instructions(
    callable_decl: ir_model.BackendCallableDecl,
    *,
    index: _ProgramIndex,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    block_by_id: dict[ir_model.BackendBlockId, ir_model.BackendBlock],
    successor_by_block: dict[ir_model.BackendBlockId, tuple[ir_model.BackendBlockId, ...]],
    must_state: _CallableMustState,
) -> None:
    for block in sorted(callable_decl.blocks, key=block_sort_key):
        available_defs = set(must_state.in_defined.get(block.block_id, frozenset()))
        available_nonnull = set(must_state.in_nonnull.get(block.block_id, frozenset()))
        available_bounds = set(must_state.in_bounds.get(block.block_id, frozenset()))

        for instruction in sorted(block.instructions, key=instruction_sort_key):
            _verify_instruction(
                callable_decl,
                block,
                instruction,
                index=index,
                register_by_id=register_by_id,
                available_defs=available_defs,
                available_nonnull=available_nonnull,
                available_bounds=available_bounds,
            )
            _apply_instruction_effects(
                instruction,
                available_defs=available_defs,
                available_nonnull=available_nonnull,
                available_bounds=available_bounds,
            )

        _verify_terminator(
            callable_decl,
            block,
            block.terminator,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )


def _verify_instruction(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: ir_model.BackendInstruction,
    *,
    index: _ProgramIndex,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    available_defs: set[ir_model.BackendRegId],
    available_nonnull: set[ir_model.BackendOperand],
    available_bounds: set[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
) -> None:
    dest_type = None
    if isinstance(instruction, (ir_model.BackendConstInst, ir_model.BackendCopyInst, ir_model.BackendUnaryInst, ir_model.BackendBinaryInst, ir_model.BackendCastInst, ir_model.BackendTypeTestInst, ir_model.BackendAllocObjectInst, ir_model.BackendFieldLoadInst, ir_model.BackendArrayAllocInst, ir_model.BackendArrayLengthInst, ir_model.BackendArrayLoadInst, ir_model.BackendArraySliceInst)):
        dest_type = _require_destination_register(callable_decl, block, instruction, register_by_id, _instruction_dest(instruction))
    elif isinstance(instruction, ir_model.BackendCallInst) and instruction.dest is not None:
        dest_type = _require_destination_register(callable_decl, block, instruction, register_by_id, instruction.dest)

    if isinstance(instruction, ir_model.BackendConstInst):
        constant_type = _constant_type(instruction.constant)
        if dest_type is not None and dest_type != constant_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"constant type '{_format_type(constant_type)}' does not match destination type '{_format_type(dest_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendCopyInst):
        source_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.source,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if dest_type is not None and source_type != dest_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"copy source type '{_format_type(source_type)}' does not match destination type '{_format_type(dest_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendUnaryInst):
        operand_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.operand,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if dest_type is not None and dest_type != operand_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"unary result type '{_format_type(dest_type)}' does not match operand type '{_format_type(operand_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendBinaryInst):
        left_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.left,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        right_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.right,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if left_type != right_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"binary operand types '{_format_type(left_type)}' and '{_format_type(right_type)}' must match",
            )
        return

    if isinstance(instruction, ir_model.BackendCastInst):
        _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.operand,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if dest_type is not None and dest_type != instruction.target_type_ref:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"cast destination type '{_format_type(dest_type)}' must match target type '{_format_type(instruction.target_type_ref)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendTypeTestInst):
        _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.operand,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if instruction.test_kind.value == "class_compatibility" and instruction.target_type_ref.class_id is None:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                "class_compatibility tests require a class target type",
            )
        if instruction.test_kind.value == "interface_compatibility" and instruction.target_type_ref.interface_id is None:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                "interface_compatibility tests require an interface target type",
            )
        if dest_type is not None and dest_type != _BOOL_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "type_test destinations must be bool-typed")
        return

    if isinstance(instruction, ir_model.BackendAllocObjectInst):
        class_decl = index.class_by_id.get(instruction.class_id)
        if class_decl is None:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"alloc_object references unknown class '{_format_class_id(instruction.class_id)}'",
            )
        expected_type = semantic_type_ref_for_class_id(instruction.class_id)
        if dest_type is not None and dest_type != expected_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"alloc_object destination type '{_format_type(dest_type)}' must match '{_format_type(expected_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendFieldLoadInst):
        object_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.object_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.object_ref, available_nonnull)
        field_decl = _require_field_decl(callable_decl, block, instruction, instruction.owner_class_id, instruction.field_name, index)
        if not _is_type_assignable(object_type, semantic_type_ref_for_class_id(instruction.owner_class_id), index):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"field_load receiver type '{_format_type(object_type)}' is incompatible with owner class '{_format_class_id(instruction.owner_class_id)}'",
            )
        if dest_type is not None and dest_type != field_decl.type_ref:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"field_load destination type '{_format_type(dest_type)}' must match field type '{_format_type(field_decl.type_ref)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendFieldStoreInst):
        object_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.object_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        value_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.value,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.object_ref, available_nonnull)
        field_decl = _require_field_decl(callable_decl, block, instruction, instruction.owner_class_id, instruction.field_name, index)
        if not _is_type_assignable(object_type, semantic_type_ref_for_class_id(instruction.owner_class_id), index):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"field_store receiver type '{_format_type(object_type)}' is incompatible with owner class '{_format_class_id(instruction.owner_class_id)}'",
            )
        if not _is_type_assignable(value_type, field_decl.type_ref, index):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"field_store value type '{_format_type(value_type)}' is incompatible with field type '{_format_type(field_decl.type_ref)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendArrayAllocInst):
        length_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.length,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if semantic_type_canonical_name(length_type) not in {TYPE_NAME_I64, TYPE_NAME_U64}:
            _instruction_error(callable_decl, block, instruction, "array_alloc length operands must be i64 or u64")
        _require_array_type(callable_decl, block, instruction, dest_type, instruction.array_runtime_kind)
        return

    if isinstance(instruction, ir_model.BackendArrayLengthInst):
        array_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.array_ref, available_nonnull)
        _require_array_operand_type(callable_decl, block, instruction, array_type)
        if dest_type is not None and dest_type != _U64_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "array_len destinations must be u64-typed")
        return

    if isinstance(instruction, ir_model.BackendArrayLoadInst):
        array_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        index_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.index,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.array_ref, available_nonnull)
        _require_explicit_bounds_check(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            instruction.index,
            available_bounds,
        )
        _require_array_runtime_kind(callable_decl, block, instruction, array_type, instruction.array_runtime_kind)
        if index_type != _I64_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "array_load indices must be i64-typed")
        if dest_type is not None:
            expected_element_type = _array_element_type(array_type)
            if dest_type != expected_element_type:
                _instruction_error(
                    callable_decl,
                    block,
                    instruction,
                    f"array_load destination type '{_format_type(dest_type)}' must match element type '{_format_type(expected_element_type)}'",
                )
        return

    if isinstance(instruction, ir_model.BackendArrayStoreInst):
        array_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        index_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.index,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        value_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.value,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.array_ref, available_nonnull)
        _require_explicit_bounds_check(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            instruction.index,
            available_bounds,
        )
        _require_array_runtime_kind(callable_decl, block, instruction, array_type, instruction.array_runtime_kind)
        if index_type != _I64_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "array_store indices must be i64-typed")
        expected_element_type = _array_element_type(array_type)
        if not _is_type_assignable(value_type, expected_element_type, index):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"array_store value type '{_format_type(value_type)}' is incompatible with element type '{_format_type(expected_element_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendArraySliceInst):
        array_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        begin_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.begin,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        end_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.end,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.array_ref, available_nonnull)
        _require_explicit_bounds_check(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            instruction.begin,
            available_bounds,
        )
        _require_explicit_bounds_check(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            instruction.end,
            available_bounds,
        )
        _require_array_runtime_kind(callable_decl, block, instruction, array_type, instruction.array_runtime_kind)
        if begin_type != _I64_TYPE_REF or end_type != _I64_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "array_slice bounds must be i64-typed")
        if dest_type is not None and dest_type != array_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"array_slice destination type '{_format_type(dest_type)}' must match array type '{_format_type(array_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendArraySliceStoreInst):
        array_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        begin_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.begin,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        end_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.end,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        value_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.value,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_explicit_null_check(callable_decl, block, instruction, instruction.array_ref, available_nonnull)
        _require_explicit_bounds_check(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            instruction.begin,
            available_bounds,
        )
        _require_explicit_bounds_check(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            instruction.end,
            available_bounds,
        )
        _require_array_runtime_kind(callable_decl, block, instruction, array_type, instruction.array_runtime_kind)
        if begin_type != _I64_TYPE_REF or end_type != _I64_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "array_slice_store bounds must be i64-typed")
        if value_type != array_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"array_slice_store value type '{_format_type(value_type)}' must match array type '{_format_type(array_type)}'",
            )
        return

    if isinstance(instruction, ir_model.BackendNullCheckInst):
        value_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.value,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if not is_reference_type_ref(value_type):
            _instruction_error(callable_decl, block, instruction, "null_check operands must be reference-like")
        return

    if isinstance(instruction, ir_model.BackendBoundsCheckInst):
        array_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.array_ref,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        index_type = _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.index,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        _require_array_operand_type(callable_decl, block, instruction, array_type)
        if index_type != _I64_TYPE_REF:
            _instruction_error(callable_decl, block, instruction, "bounds_check indices must be i64-typed")
        return

    if isinstance(instruction, ir_model.BackendCallInst):
        _verify_call_instruction(
            callable_decl,
            block,
            instruction,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        return

    _instruction_error(
        callable_decl,
        block,
        instruction,
        f"unsupported instruction type '{type(instruction).__name__}'",
    )


def _verify_call_instruction(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: ir_model.BackendCallInst,
    *,
    index: _ProgramIndex,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    available_defs: set[ir_model.BackendRegId],
) -> None:
    dest_type = None
    if instruction.dest is not None:
        dest_type = register_by_id[instruction.dest].type_ref

    if instruction.signature.return_type is None:
        if instruction.dest is not None:
            _instruction_error(callable_decl, block, instruction, "unit-returning calls must use dest=None")
    else:
        if instruction.dest is None:
            _instruction_error(callable_decl, block, instruction, "non-unit calls must store their result")
        elif dest_type != instruction.signature.return_type:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call destination type '{_format_type(dest_type)}' does not match signature return type '{_format_type(instruction.signature.return_type)}'",
            )

    receiver_type = None
    expects_receiver = False
    if isinstance(instruction.target, ir_model.BackendDirectCallTarget):
        callee_decl = index.callable_by_id.get(instruction.target.callable_id)
        if callee_decl is None:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"direct call target '{_format_callable_id(instruction.target.callable_id)}' is not declared",
            )
        if callee_decl.signature != instruction.signature:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"call signature does not match direct target '{_format_callable_id(instruction.target.callable_id)}'",
            )
        if callee_decl.kind == "constructor":
            expects_receiver = True
            receiver_type = _callable_receiver_type(callee_decl, register_by_id=None)
        elif callee_decl.kind == "method" and callee_decl.is_static is False:
            expects_receiver = True
            receiver_type = _callable_receiver_type(callee_decl, register_by_id=None)
    elif isinstance(instruction.target, ir_model.BackendRuntimeCallTarget):
        if not has_runtime_call_metadata(instruction.target.name):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"runtime call '{instruction.target.name}' is not present in the runtime metadata registry",
            )
        metadata = runtime_call_metadata(instruction.target.name)
        if instruction.target.ref_arg_indices != metadata.ref_arg_indices:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"runtime call '{instruction.target.name}' ref_arg_indices {instruction.target.ref_arg_indices} do not match runtime metadata {metadata.ref_arg_indices}",
            )
        if instruction.effects.may_gc != metadata.may_gc:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"runtime call '{instruction.target.name}' effects.may_gc={instruction.effects.may_gc} does not match runtime metadata {metadata.may_gc}",
            )
        if instruction.effects.needs_safepoint_hooks != metadata.emits_safepoint_hooks:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"runtime call '{instruction.target.name}' effects.needs_safepoint_hooks={instruction.effects.needs_safepoint_hooks} does not match runtime metadata {metadata.emits_safepoint_hooks}",
            )
    elif isinstance(instruction.target, ir_model.BackendVirtualCallTarget):
        if instruction.target.slot_owner_class_id not in index.class_by_id:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"virtual call slot owner '{_format_class_id(instruction.target.slot_owner_class_id)}' is not declared",
            )
        selected_method = index.callable_by_id.get(instruction.target.selected_method_id)
        if selected_method is None or selected_method.kind != "method":
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"virtual call selected method '{_format_method_id(instruction.target.selected_method_id)}' is not declared",
            )
        if instruction.target.selected_method_id.name != instruction.target.method_name:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                "virtual call method_name must match selected_method_id.name",
            )
        if selected_method.signature != instruction.signature:
            _instruction_error(callable_decl, block, instruction, "virtual call signature does not match selected method")
        expects_receiver = True
        receiver_type = semantic_type_ref_for_class_id(instruction.target.slot_owner_class_id)
    elif isinstance(instruction.target, ir_model.BackendInterfaceCallTarget):
        interface_decl = index.interface_by_id.get(instruction.target.interface_id)
        if interface_decl is None:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"interface call target '{_format_interface_id(instruction.target.interface_id)}' is not declared",
            )
        if instruction.target.method_id not in interface_decl.methods:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"interface method '{_format_interface_method_id(instruction.target.method_id)}' is not declared on '{_format_interface_id(instruction.target.interface_id)}'",
            )
        expects_receiver = True
        receiver_type = semantic_type_ref_for_interface_id(instruction.target.interface_id)
    elif isinstance(instruction.target, ir_model.BackendIndirectCallTarget):
        _operand_type(
            callable_decl,
            block,
            instruction,
            instruction.target.callee,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if len(instruction.args) == len(instruction.signature.param_types) + 1:
            expects_receiver = True
    
    expected_arg_count = len(instruction.signature.param_types) + (1 if expects_receiver else 0)
    if len(instruction.args) != expected_arg_count:
        suffix = " including receiver" if expects_receiver else ""
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"call expects {expected_arg_count} arguments{suffix}, got {len(instruction.args)}",
        )

    start_index = 0
    if expects_receiver:
        receiver_operand = instruction.args[0]
        receiver_operand_type = _operand_type(
            callable_decl,
            block,
            instruction,
            receiver_operand,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if receiver_type is not None and not _is_type_assignable(receiver_operand_type, receiver_type, index):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"receiver operand type '{_format_type(receiver_operand_type)}' is incompatible with '{_format_type(receiver_type)}'",
            )
        start_index = 1

    for expected_type, argument in zip(instruction.signature.param_types, instruction.args[start_index:]):
        argument_type = _operand_type(
            callable_decl,
            block,
            instruction,
            argument,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if not _is_type_assignable(argument_type, expected_type, index):
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"argument type '{_format_type(argument_type)}' is incompatible with expected type '{_format_type(expected_type)}'",
            )


def _verify_terminator(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    terminator: ir_model.BackendTerminator,
    *,
    index: _ProgramIndex,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    available_defs: set[ir_model.BackendRegId],
) -> None:
    if isinstance(terminator, ir_model.BackendBranchTerminator):
        condition_type = _operand_type(
            callable_decl,
            block,
            terminator,
            terminator.condition,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if condition_type != _BOOL_TYPE_REF:
            _block_error(
                callable_decl,
                block,
                f"branch condition type '{_format_type(condition_type)}' must be bool",
            )
        return
    if isinstance(terminator, ir_model.BackendReturnTerminator):
        if callable_decl.signature.return_type is None:
            if terminator.value is not None:
                _block_error(callable_decl, block, "unit-returning callables must use bare return terminators")
            return
        if terminator.value is None:
            _block_error(
                callable_decl,
                block,
                f"callable return type '{_format_type(callable_decl.signature.return_type)}' requires a return operand",
            )
        return_type = _operand_type(
            callable_decl,
            block,
            terminator,
            terminator.value,
            index=index,
            register_by_id=register_by_id,
            available_defs=available_defs,
        )
        if not _is_type_assignable(return_type, callable_decl.signature.return_type, index):
            _block_error(
                callable_decl,
                block,
                f"return operand type '{_format_type(return_type)}' is incompatible with callable return type '{_format_type(callable_decl.signature.return_type)}'",
            )
        if callable_decl.kind == "constructor":
            if not isinstance(terminator.value, ir_model.BackendRegOperand) or terminator.value.reg_id != callable_decl.receiver_reg:
                _block_error(callable_decl, block, "constructor returns must use the receiver_reg explicitly")
        return


def _require_destination_register(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    dest_reg_id: ir_model.BackendRegId | None,
) -> SemanticTypeRef | None:
    if dest_reg_id is None:
        return None
    destination = register_by_id.get(dest_reg_id)
    if destination is None:
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"destination register '{_format_reg_id(dest_reg_id)}' is not declared",
        )
    return destination.type_ref


def _operand_type(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    operand: ir_model.BackendOperand,
    *,
    index: _ProgramIndex,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister],
    available_defs: set[ir_model.BackendRegId],
) -> SemanticTypeRef:
    if isinstance(operand, ir_model.BackendRegOperand):
        register = register_by_id.get(operand.reg_id)
        if register is None:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"operand register '{_format_reg_id(operand.reg_id)}' is not declared",
            )
        if operand.reg_id not in available_defs:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"register '{_format_reg_id(operand.reg_id)}' is used before definition",
            )
        return register.type_ref
    if isinstance(operand, ir_model.BackendConstOperand):
        return _constant_type(operand.constant)
    if isinstance(operand, ir_model.BackendDataOperand):
        if operand.data_id not in index.data_blob_by_id:
            _instruction_error(
                callable_decl,
                block,
                instruction,
                f"data operand '{_format_data_id(operand.data_id)}' is not declared",
            )
        return _OPAQUE_DATA_TYPE_REF
    _instruction_error(callable_decl, block, instruction, f"unsupported operand type '{type(operand).__name__}'")


def _constant_type(constant: ir_model.BackendConstant) -> SemanticTypeRef:
    if isinstance(constant, ir_model.BackendIntConst):
        return semantic_primitive_type_ref(constant.type_name)
    if isinstance(constant, ir_model.BackendBoolConst):
        return _BOOL_TYPE_REF
    if isinstance(constant, ir_model.BackendDoubleConst):
        return semantic_primitive_type_ref("double")
    if isinstance(constant, ir_model.BackendNullConst):
        return _NULL_TYPE_REF
    if isinstance(constant, ir_model.BackendUnitConst):
        return _UNIT_TYPE_REF
    raise BackendIRVerificationError(f"Unsupported backend constant type '{type(constant).__name__}'")


def _require_field_decl(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    owner_class_id: ClassId,
    field_name: str,
    index: _ProgramIndex,
) -> ir_model.BackendFieldDecl:
    if owner_class_id not in index.class_by_id:
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"field owner class '{_format_class_id(owner_class_id)}' is not declared",
        )
    field_decl = index.field_by_owner_and_name.get((owner_class_id, field_name))
    if field_decl is None:
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"field '{field_name}' is not declared on class '{_format_class_id(owner_class_id)}'",
        )
    return field_decl


def _require_array_operand_type(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    array_type: SemanticTypeRef,
) -> None:
    if not semantic_type_is_array(array_type):
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"array operand type '{_format_type(array_type)}' must be an array",
        )


def _require_array_type(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    array_type: SemanticTypeRef | None,
    runtime_kind: ArrayRuntimeKind,
) -> None:
    if array_type is None:
        return
    _require_array_operand_type(callable_decl, block, instruction, array_type)
    _require_array_runtime_kind(callable_decl, block, instruction, array_type, runtime_kind)


def _require_array_runtime_kind(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    array_type: SemanticTypeRef,
    runtime_kind: ArrayRuntimeKind,
) -> None:
    _require_array_operand_type(callable_decl, block, instruction, array_type)
    actual_runtime_kind = array_element_runtime_kind_for_type_ref(_array_element_type(array_type))
    expected_runtime_kind = _ARRAY_RUNTIME_KIND_TO_TEXT[runtime_kind]
    if actual_runtime_kind != expected_runtime_kind:
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"array runtime kind '{expected_runtime_kind}' is incompatible with array element kind '{actual_runtime_kind}'",
        )


def _require_explicit_null_check(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    operand: ir_model.BackendOperand,
    available_nonnull: set[ir_model.BackendOperand],
) -> None:
    if operand not in available_nonnull:
        _instruction_error(
            callable_decl,
            block,
            instruction,
            f"explicit null_check is required before using operand '{_format_operand(operand)}'",
        )


def _require_explicit_bounds_check(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    array_ref: ir_model.BackendOperand,
    index_operand: ir_model.BackendOperand,
    available_bounds: set[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
) -> None:
    if (array_ref, index_operand) not in available_bounds:
        _instruction_error(
            callable_decl,
            block,
            instruction,
            "explicit bounds_check is required before direct array access",
        )


def _apply_instruction_effects(
    instruction: ir_model.BackendInstruction,
    *,
    available_defs: set[ir_model.BackendRegId],
    available_nonnull: set[ir_model.BackendOperand],
    available_bounds: set[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
) -> None:
    destination = _instruction_dest(instruction)
    if destination is not None:
        _kill_check_facts(destination, available_nonnull, available_bounds)
        available_defs.add(destination)
    if isinstance(instruction, ir_model.BackendNullCheckInst):
        available_nonnull.add(instruction.value)
    if isinstance(instruction, ir_model.BackendBoundsCheckInst):
        available_bounds.add((instruction.array_ref, instruction.index))


def _block_defined_registers(block: ir_model.BackendBlock) -> frozenset[ir_model.BackendRegId]:
    return frozenset(
        destination
        for instruction in sorted(block.instructions, key=instruction_sort_key)
        for destination in [_instruction_dest(instruction)]
        if destination is not None
    )


def _apply_block_check_transfer(
    block: ir_model.BackendBlock,
    *,
    in_nonnull: frozenset[ir_model.BackendOperand],
    in_bounds: frozenset[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
) -> tuple[
    frozenset[ir_model.BackendOperand],
    frozenset[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
]:
    available_nonnull = set(in_nonnull)
    available_bounds = set(in_bounds)
    for instruction in sorted(block.instructions, key=instruction_sort_key):
        destination = _instruction_dest(instruction)
        if destination is not None:
            _kill_check_facts(destination, available_nonnull, available_bounds)
        if isinstance(instruction, ir_model.BackendNullCheckInst):
            available_nonnull.add(instruction.value)
        if isinstance(instruction, ir_model.BackendBoundsCheckInst):
            available_bounds.add((instruction.array_ref, instruction.index))
    return frozenset(available_nonnull), frozenset(available_bounds)


def _kill_check_facts(
    reg_id: ir_model.BackendRegId,
    available_nonnull: set[ir_model.BackendOperand],
    available_bounds: set[tuple[ir_model.BackendOperand, ir_model.BackendOperand]],
) -> None:
    stale_nonnull = {operand for operand in available_nonnull if _operand_mentions_reg(operand, reg_id)}
    if stale_nonnull:
        available_nonnull.difference_update(stale_nonnull)
    stale_bounds = {
        bound
        for bound in available_bounds
        if _operand_mentions_reg(bound[0], reg_id) or _operand_mentions_reg(bound[1], reg_id)
    }
    if stale_bounds:
        available_bounds.difference_update(stale_bounds)


def _operand_mentions_reg(operand: ir_model.BackendOperand, reg_id: ir_model.BackendRegId) -> bool:
    return isinstance(operand, ir_model.BackendRegOperand) and operand.reg_id == reg_id


def _instruction_dest(instruction: ir_model.BackendInstruction) -> ir_model.BackendRegId | None:
    if isinstance(
        instruction,
        (
            ir_model.BackendConstInst,
            ir_model.BackendCopyInst,
            ir_model.BackendUnaryInst,
            ir_model.BackendBinaryInst,
            ir_model.BackendCastInst,
            ir_model.BackendTypeTestInst,
            ir_model.BackendAllocObjectInst,
            ir_model.BackendFieldLoadInst,
            ir_model.BackendArrayAllocInst,
            ir_model.BackendArrayLengthInst,
            ir_model.BackendArrayLoadInst,
            ir_model.BackendArraySliceInst,
        ),
    ):
        return instruction.dest
    if isinstance(instruction, ir_model.BackendCallInst):
        return instruction.dest
    return None


def _callable_receiver_type(
    callable_decl: ir_model.BackendCallableDecl,
    *,
    register_by_id: dict[ir_model.BackendRegId, ir_model.BackendRegister] | None,
) -> SemanticTypeRef:
    if callable_decl.receiver_reg is None:
        raise BackendIRVerificationError(
            f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}' is missing a receiver_reg"
        )
    if register_by_id is not None and callable_decl.receiver_reg in register_by_id:
        return register_by_id[callable_decl.receiver_reg].type_ref
    if isinstance(callable_decl.callable_id, MethodId):
        return semantic_type_ref_for_class_id(
            ClassId(module_path=callable_decl.callable_id.module_path, name=callable_decl.callable_id.class_name)
        )
    if isinstance(callable_decl.callable_id, ConstructorId):
        return semantic_type_ref_for_class_id(
            ClassId(module_path=callable_decl.callable_id.module_path, name=callable_decl.callable_id.class_name)
        )
    raise BackendIRVerificationError(
        f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}' does not have a receiver type"
    )


def _array_element_type(array_type: SemanticTypeRef) -> SemanticTypeRef:
    if array_type.element_type is None:
        raise BackendIRVerificationError(f"'{_format_type(array_type)}' is not an array type")
    return array_type.element_type


def _is_type_assignable(actual_type: SemanticTypeRef, expected_type: SemanticTypeRef, index: _ProgramIndex) -> bool:
    if actual_type == expected_type:
        return True
    if expected_type.kind in {"reference", "interface"} and actual_type == _NULL_TYPE_REF:
        return True
    if semantic_type_canonical_name(expected_type) == TYPE_NAME_OBJ and is_reference_type_ref(actual_type):
        return True
    if expected_type.class_id is not None and actual_type.class_id is not None:
        return _is_same_or_subclass(actual_type.class_id, expected_type.class_id, index)
    if expected_type.interface_id is not None:
        if actual_type.interface_id == expected_type.interface_id:
            return True
        if actual_type.class_id is not None:
            return _class_implements_interface(actual_type.class_id, expected_type.interface_id, index)
    return False


def _is_same_or_subclass(class_id: ClassId, target_class_id: ClassId, index: _ProgramIndex) -> bool:
    current_class_id: ClassId | None = class_id
    while current_class_id is not None:
        if current_class_id == target_class_id:
            return True
        class_decl = index.class_by_id.get(current_class_id)
        if class_decl is None:
            return False
        current_class_id = class_decl.superclass_id
    return False


def _class_implements_interface(class_id: ClassId, interface_id: InterfaceId, index: _ProgramIndex) -> bool:
    current_class_id: ClassId | None = class_id
    while current_class_id is not None:
        class_decl = index.class_by_id.get(current_class_id)
        if class_decl is None:
            return False
        if interface_id in class_decl.implemented_interfaces:
            return True
        current_class_id = class_decl.superclass_id
    return False


def _ensure_unique(mapping: dict, key, value, message_factory) -> None:
    if key in mapping:
        raise BackendIRVerificationError(message_factory(key))
    mapping[key] = value


def _intersect_sets(values) -> frozenset:
    values = list(values)
    if not values:
        return frozenset()
    result = set(values[0])
    for value in values[1:]:
        result.intersection_update(value)
    return frozenset(result)


def _callable_error(callable_decl: ir_model.BackendCallableDecl, message: str) -> None:
    raise BackendIRVerificationError(
        f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}': {message}"
    )


def _block_error(callable_decl: ir_model.BackendCallableDecl, block: ir_model.BackendBlock, message: str) -> None:
    raise BackendIRVerificationError(
        f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}' block '{_format_block_id(block.block_id)}': {message}"
    )


def _instruction_error(
    callable_decl: ir_model.BackendCallableDecl,
    block: ir_model.BackendBlock,
    instruction: object,
    message: str,
) -> None:
    inst_id = getattr(instruction, "inst_id", None)
    if isinstance(inst_id, ir_model.BackendInstId):
        suffix = f" instruction '{_format_inst_id(inst_id)}'"
    else:
        suffix = " terminator"
    raise BackendIRVerificationError(
        f"Backend IR callable '{_format_callable_id(callable_decl.callable_id)}' block '{_format_block_id(block.block_id)}'{suffix}: {message}"
    )


def _format_type(type_ref: SemanticTypeRef) -> str:
    return semantic_type_display_name(type_ref)


def _format_callable_id(callable_id: ir_model.BackendCallableId) -> str:
    if isinstance(callable_id, FunctionId):
        return _format_function_id(callable_id)
    if isinstance(callable_id, MethodId):
        return _format_method_id(callable_id)
    return _format_constructor_id(callable_id)


def _format_function_id(function_id: FunctionId) -> str:
    return f"{'.'.join(function_id.module_path)}::{function_id.name}"


def _format_method_id(method_id: MethodId) -> str:
    return f"{'.'.join(method_id.module_path)}::{method_id.class_name}.{method_id.name}"


def _format_constructor_id(constructor_id: ConstructorId) -> str:
    return f"{'.'.join(constructor_id.module_path)}::{constructor_id.class_name}#{constructor_id.ordinal}"


def _format_interface_id(interface_id: InterfaceId) -> str:
    return f"{'.'.join(interface_id.module_path)}::{interface_id.name}"


def _format_interface_method_id(method_id) -> str:
    return f"{'.'.join(method_id.module_path)}::{method_id.interface_name}.{method_id.name}"


def _format_class_id(class_id: ClassId) -> str:
    return f"{'.'.join(class_id.module_path)}::{class_id.name}"


def _format_reg_id(reg_id: ir_model.BackendRegId) -> str:
    return f"r{reg_id.ordinal}"


def _format_block_id(block_id: ir_model.BackendBlockId) -> str:
    return f"b{block_id.ordinal}"


def _format_inst_id(inst_id: ir_model.BackendInstId) -> str:
    return f"i{inst_id.ordinal}"


def _format_data_id(data_id: ir_model.BackendDataId) -> str:
    return f"d{data_id.ordinal}"


def _format_operand(operand: ir_model.BackendOperand) -> str:
    if isinstance(operand, ir_model.BackendRegOperand):
        return _format_reg_id(operand.reg_id)
    if isinstance(operand, ir_model.BackendConstOperand):
        constant = operand.constant
        if isinstance(constant, ir_model.BackendIntConst):
            return str(constant.value)
        if isinstance(constant, ir_model.BackendBoolConst):
            return str(constant.value).lower()
        if isinstance(constant, ir_model.BackendNullConst):
            return "null"
        if isinstance(constant, ir_model.BackendUnitConst):
            return "unit"
        if isinstance(constant, ir_model.BackendDoubleConst):
            return str(constant.value)
    if isinstance(operand, ir_model.BackendDataOperand):
        return _format_data_id(operand.data_id)
    return repr(operand)


__all__ = ["BackendIRVerificationError", "verify_backend_program"]