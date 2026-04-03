from __future__ import annotations

from compiler.common.span import SourceSpan
from compiler.common.collection_protocols import CollectionOpKind
from compiler.common.type_names import TYPE_NAME_I64, TYPE_NAME_U64
from compiler.semantic.ir import (
    RuntimeDispatch,
    SemanticBlock,
    SemanticClass,
    SemanticConstructor,
    SemanticField,
    SemanticForIn,
    SemanticFunction,
    SemanticIf,
    SemanticLocalInfo,
    SemanticMethod,
    SemanticStmt,
    SemanticWhile,
    expression_type_ref,
)
from compiler.semantic.linker import LinkedSemanticProgram
from compiler.semantic.lowered_ir import (
    LoweredLinkedSemanticProgram,
    LoweredSemanticBlock,
    LoweredSemanticClass,
    LoweredSemanticConstructor,
    LoweredSemanticField,
    LoweredSemanticForIn,
    LoweredSemanticForInStrategy,
    LoweredSemanticFunction,
    LoweredSemanticIf,
    LoweredSemanticMethod,
    LoweredSemanticModule,
    LoweredSemanticStmt,
    LoweredSemanticWhile,
)
from compiler.semantic.symbols import LocalId, LocalOwnerId
from compiler.semantic.types import semantic_primitive_type_ref


class _HelperLocalAllocator:
    def __init__(self, owner_id: LocalOwnerId, local_info_by_id: dict[LocalId, SemanticLocalInfo]) -> None:
        self.owner_id = owner_id
        self.local_info_by_id = local_info_by_id
        self.next_ordinal = max((local_id.ordinal for local_id in local_info_by_id), default=-1) + 1

    def declare(self, *, display_name: str, type_ref, span: SourceSpan, binding_kind: str) -> LocalId:
        local_id = LocalId(owner_id=self.owner_id, ordinal=self.next_ordinal)
        self.next_ordinal += 1
        self.local_info_by_id[local_id] = SemanticLocalInfo(
            local_id=local_id,
            owner_id=self.owner_id,
            display_name=display_name,
            type_ref=type_ref,
            span=span,
            binding_kind=binding_kind,
        )
        return local_id


def lower_linked_semantic_program(program: LinkedSemanticProgram) -> LoweredLinkedSemanticProgram:
    lowered_modules: list[LoweredSemanticModule] = []
    lowered_functions: list[LoweredSemanticFunction] = []
    lowered_classes: list[LoweredSemanticClass] = []

    for module in program.ordered_modules:
        module_functions: list[LoweredSemanticFunction] = []
        module_classes: list[LoweredSemanticClass] = []

        for cls in module.classes:
            lowered_class = _lower_class(cls)
            module_classes.append(lowered_class)
            lowered_classes.append(lowered_class)

        for fn in module.functions:
            lowered_function = _lower_function(fn)
            module_functions.append(lowered_function)
            lowered_functions.append(lowered_function)

        lowered_modules.append(
            LoweredSemanticModule(
                module_path=module.module_path,
                file_path=module.file_path,
                classes=module_classes,
                functions=module_functions,
                span=module.span,
                interfaces=module.interfaces,
            )
        )

    return LoweredLinkedSemanticProgram(
        entry_module=program.entry_module,
        ordered_modules=tuple(lowered_modules),
        classes=tuple(lowered_classes),
        functions=tuple(lowered_functions),
        span=program.span,
    )


def _lower_class(cls: SemanticClass) -> LoweredSemanticClass:
    lowered_fields = [_lower_field(field) for field in cls.fields]
    lowered_methods = [_lower_method(method) for method in cls.methods]
    lowered_constructors = [_lower_constructor(constructor) for constructor in cls.constructors]
    return LoweredSemanticClass(
        class_id=cls.class_id,
        is_export=cls.is_export,
        fields=lowered_fields,
        methods=lowered_methods,
        span=cls.span,
        superclass_id=cls.superclass_id,
        implemented_interfaces=list(cls.implemented_interfaces),
        constructors=lowered_constructors,
    )


def _lower_field(field: SemanticField) -> LoweredSemanticField:
    return LoweredSemanticField(
        name=field.name,
        type_ref=field.type_ref,
        initializer=field.initializer,
        is_private=field.is_private,
        is_final=field.is_final,
        span=field.span,
    )


def _lower_function(fn: SemanticFunction) -> LoweredSemanticFunction:
    if fn.body is None:
        return LoweredSemanticFunction(
            function_id=fn.function_id,
            params=list(fn.params),
            return_type_ref=fn.return_type_ref,
            body=None,
            is_export=fn.is_export,
            is_extern=fn.is_extern,
            span=fn.span,
            local_info_by_id=dict(fn.local_info_by_id),
        )
    local_info_by_id = dict(fn.local_info_by_id)
    allocator = _HelperLocalAllocator(fn.function_id, local_info_by_id)
    lowered_body = _lower_block(fn.body, allocator)
    return LoweredSemanticFunction(
        function_id=fn.function_id,
        params=list(fn.params),
        return_type_ref=fn.return_type_ref,
        body=lowered_body,
        is_export=fn.is_export,
        is_extern=fn.is_extern,
        span=fn.span,
        local_info_by_id=local_info_by_id,
    )


def _lower_method(method: SemanticMethod) -> LoweredSemanticMethod:
    local_info_by_id = dict(method.local_info_by_id)
    allocator = _HelperLocalAllocator(method.method_id, local_info_by_id)
    lowered_body = _lower_block(method.body, allocator)
    return LoweredSemanticMethod(
        method_id=method.method_id,
        params=list(method.params),
        return_type_ref=method.return_type_ref,
        body=lowered_body,
        is_static=method.is_static,
        is_private=method.is_private,
        span=method.span,
        local_info_by_id=local_info_by_id,
    )


def _lower_constructor(constructor: SemanticConstructor) -> LoweredSemanticConstructor:
    if constructor.body is None:
        return LoweredSemanticConstructor(
            constructor_id=constructor.constructor_id,
            params=list(constructor.params),
            body=None,
            is_private=constructor.is_private,
            span=constructor.span,
            local_info_by_id=dict(constructor.local_info_by_id),
            super_constructor_id=constructor.super_constructor_id,
        )

    local_info_by_id = dict(constructor.local_info_by_id)
    allocator = _HelperLocalAllocator(constructor.constructor_id, local_info_by_id)
    lowered_body = _lower_block(constructor.body, allocator)
    return LoweredSemanticConstructor(
        constructor_id=constructor.constructor_id,
        params=list(constructor.params),
        body=lowered_body,
        is_private=constructor.is_private,
        span=constructor.span,
        local_info_by_id=local_info_by_id,
        super_constructor_id=constructor.super_constructor_id,
    )


def _lower_block(block: SemanticBlock, allocator: _HelperLocalAllocator) -> LoweredSemanticBlock:
    return LoweredSemanticBlock(statements=[_lower_stmt(stmt, allocator) for stmt in block.statements], span=block.span)


def _lower_stmt(stmt: SemanticStmt, allocator: _HelperLocalAllocator) -> LoweredSemanticStmt:
    if isinstance(stmt, SemanticBlock):
        return _lower_block(stmt, allocator)
    if isinstance(stmt, SemanticIf):
        return LoweredSemanticIf(
            condition=stmt.condition,
            then_block=_lower_block(stmt.then_block, allocator),
            else_block=None if stmt.else_block is None else _lower_block(stmt.else_block, allocator),
            span=stmt.span,
        )
    if isinstance(stmt, SemanticWhile):
        return LoweredSemanticWhile(condition=stmt.condition, body=_lower_block(stmt.body, allocator), span=stmt.span)
    if isinstance(stmt, SemanticForIn):
        collection_local_id = allocator.declare(
            display_name="__for_in_collection",
            type_ref=expression_type_ref(stmt.collection),
            span=stmt.collection.span,
            binding_kind="for_in_collection",
        )
        length_local_id = allocator.declare(
            display_name="__for_in_length",
            type_ref=semantic_primitive_type_ref(TYPE_NAME_U64),
            span=stmt.span,
            binding_kind="for_in_length",
        )
        index_local_id = allocator.declare(
            display_name="__for_in_index",
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            span=stmt.span,
            binding_kind="for_in_index",
        )
        return LoweredSemanticForIn(
            element_name=stmt.element_name,
            element_local_id=stmt.element_local_id,
            collection_local_id=collection_local_id,
            length_local_id=length_local_id,
            index_local_id=index_local_id,
            collection=stmt.collection,
            iter_len_dispatch=stmt.iter_len_dispatch,
            iter_get_dispatch=stmt.iter_get_dispatch,
            element_type_ref=stmt.element_type_ref,
            body=_lower_block(stmt.body, allocator),
            span=stmt.span,
            strategy=_lowered_for_in_strategy(stmt),
        )
    return stmt


def _lowered_for_in_strategy(stmt: SemanticForIn) -> LoweredSemanticForInStrategy:
    iter_len_dispatch = stmt.iter_len_dispatch
    iter_get_dispatch = stmt.iter_get_dispatch

    if isinstance(iter_len_dispatch, RuntimeDispatch) and isinstance(iter_get_dispatch, RuntimeDispatch):
        if (
            iter_len_dispatch.operation is CollectionOpKind.ITER_LEN
            and iter_get_dispatch.operation is CollectionOpKind.ITER_GET
        ):
            if iter_get_dispatch.runtime_kind is not None:
                return LoweredSemanticForInStrategy.ARRAY_DIRECT
            return LoweredSemanticForInStrategy.ARRAY_RUNTIME_DISPATCH

    return LoweredSemanticForInStrategy.COLLECTION_PROTOCOL_DISPATCH
