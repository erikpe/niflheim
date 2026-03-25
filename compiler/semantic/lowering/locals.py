from __future__ import annotations

from dataclasses import dataclass, field

from compiler.semantic.ir import LocalBindingKind, SemanticLocalInfo
from compiler.semantic.symbols import LocalId, LocalOwnerId
from compiler.semantic.types import semantic_type_ref_from_type_info
from compiler.typecheck.context import LocalBinding


@dataclass
class LocalIdTracker:
    owner_id: LocalOwnerId
    next_ordinal: int = 0
    scope_stack: list[set[LocalBinding]] = field(default_factory=list)
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)
    local_id_by_binding: dict[LocalBinding, LocalId] = field(default_factory=dict)

    def push_scope(self) -> None:
        self.scope_stack.append(set())

    def pop_scope(self) -> None:
        self.scope_stack.pop()

    def declare_binding(self, binding: LocalBinding, *, binding_kind: LocalBindingKind = "local") -> LocalId:
        if not self.scope_stack:
            raise ValueError("LocalIdTracker requires an active scope before declaring locals")

        scope = self.scope_stack[-1]
        if binding in scope:
            raise ValueError(f"Duplicate local binding '{binding.name}' in current LocalIdTracker scope")

        local_id = LocalId(owner_id=self.owner_id, ordinal=self.next_ordinal)
        self.next_ordinal += 1
        scope.add(binding)
        self.local_id_by_binding[binding] = local_id
        self.local_info_by_id[local_id] = SemanticLocalInfo(
            local_id=local_id,
            owner_id=self.owner_id,
            display_name=binding.name,
            type_name=binding.var_type.name,
            type_ref=semantic_type_ref_from_type_info(local_id.owner_id.module_path, binding.var_type),
            span=binding.span,
            binding_kind=binding_kind,
        )
        return local_id

    def lookup_binding(self, binding: LocalBinding) -> LocalId | None:
        return self.local_id_by_binding.get(binding)

    def snapshot_local_info_by_id(self) -> dict[LocalId, SemanticLocalInfo]:
        return dict(self.local_info_by_id)
