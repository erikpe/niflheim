from __future__ import annotations

from dataclasses import dataclass, field

from compiler.common.span import SourceSpan
from compiler.semantic.ir import LocalBindingKind, SemanticLocalInfo
from compiler.semantic.symbols import LocalId, LocalOwnerId


@dataclass
class LocalIdTracker:
    owner_id: LocalOwnerId
    next_ordinal: int = 0
    scope_stack: list[dict[str, LocalId]] = field(default_factory=list)
    local_info_by_id: dict[LocalId, SemanticLocalInfo] = field(default_factory=dict)

    def push_scope(self) -> None:
        self.scope_stack.append({})

    def pop_scope(self) -> None:
        self.scope_stack.pop()

    def declare_local(
        self,
        name: str,
        *,
        type_name: str,
        span: SourceSpan,
        binding_kind: LocalBindingKind = "local",
    ) -> LocalId:
        if not self.scope_stack:
            raise ValueError("LocalIdTracker requires an active scope before declaring locals")

        scope = self.scope_stack[-1]
        if name in scope:
            raise ValueError(f"Duplicate local binding '{name}' in current LocalIdTracker scope")

        local_id = LocalId(owner_id=self.owner_id, ordinal=self.next_ordinal)
        self.next_ordinal += 1
        scope[name] = local_id
        self.local_info_by_id[local_id] = SemanticLocalInfo(
            local_id=local_id,
            owner_id=self.owner_id,
            display_name=name,
            type_name=type_name,
            span=span,
            binding_kind=binding_kind,
        )
        return local_id

    def lookup_local(self, name: str) -> LocalId | None:
        for scope in reversed(self.scope_stack):
            local_id = scope.get(name)
            if local_id is not None:
                return local_id
        return None

    def snapshot_local_info_by_id(self) -> dict[LocalId, SemanticLocalInfo]:
        return dict(self.local_info_by_id)
