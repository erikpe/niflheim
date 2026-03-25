from __future__ import annotations

from dataclasses import dataclass, field

from compiler.semantic.ir import LocalBindingKind, SemanticLocalInfo
from compiler.semantic.lowering.type_refs import semantic_type_ref_from_checked_type
from compiler.semantic.symbols import LocalId, LocalOwnerId
from compiler.typecheck.context import LocalBinding, TypeCheckContext
from compiler.typecheck.model import TypeInfo


@dataclass
class LocalIdTracker:
    owner_id: LocalOwnerId
    typecheck_ctx: TypeCheckContext
    next_ordinal: int = 0
    scope_stack: list[set[LocalBinding]] = field(default_factory=list)
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)
    local_id_by_binding: dict[LocalBinding, LocalId] = field(default_factory=dict)

    def push_scope(self) -> None:
        self.scope_stack.append(set())

    def pop_scope(self) -> None:
        self.scope_stack.pop()

    def declare_internal_local(
        self,
        *,
        display_name: str,
        var_type: TypeInfo,
        span,
        binding_kind: LocalBindingKind,
    ) -> LocalId:
        local_id = self._allocate_local_id()
        self._record_local_info(
            local_id,
            display_name=display_name,
            var_type=var_type,
            span=span,
            binding_kind=binding_kind,
        )
        return local_id

    def _allocate_local_id(self) -> LocalId:
        if not self.scope_stack:
            raise ValueError("LocalIdTracker requires an active scope before declaring locals")

        local_id = LocalId(owner_id=self.owner_id, ordinal=self.next_ordinal)
        self.next_ordinal += 1
        return local_id

    def _record_local_info(
        self,
        local_id: LocalId,
        *,
        display_name: str,
        var_type: TypeInfo,
        span,
        binding_kind: LocalBindingKind,
    ) -> None:
        self.local_info_by_id[local_id] = SemanticLocalInfo(
            local_id=local_id,
            owner_id=self.owner_id,
            display_name=display_name,
            type_name=var_type.name,
            type_ref=semantic_type_ref_from_checked_type(self.typecheck_ctx, var_type),
            span=span,
            binding_kind=binding_kind,
        )

    def _current_scope(self) -> set[LocalBinding]:
        if not self.scope_stack:
            raise ValueError("LocalIdTracker requires an active scope before declaring locals")
        return self.scope_stack[-1]

    def declare_binding(self, binding: LocalBinding, *, binding_kind: LocalBindingKind = "local") -> LocalId:
        scope = self._current_scope()
        if binding in scope:
            raise ValueError(f"Duplicate local binding '{binding.name}' in current LocalIdTracker scope")

        scope.add(binding)
        local_id = self._allocate_local_id()
        self.local_id_by_binding[binding] = local_id
        self._record_local_info(
            local_id,
            display_name=binding.name,
            var_type=binding.var_type,
            span=binding.span,
            binding_kind=binding_kind,
        )
        return local_id

    def lookup_binding(self, binding: LocalBinding) -> LocalId | None:
        return self.local_id_by_binding.get(binding)

    def snapshot_local_info_by_id(self) -> dict[LocalId, SemanticLocalInfo]:
        return dict(self.local_info_by_id)
