from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import BackendCallableDecl, BackendFunctionAnalysisDump, BackendRegId, BackendRegister
from compiler.backend.ir._ordering import reg_id_sort_key, register_sort_key


@dataclass(frozen=True)
class BackendCallableStackHomes:
    callable_decl: BackendCallableDecl
    stack_home_by_reg: dict[BackendRegId, str]

    def for_reg(self, reg_id: BackendRegId) -> str | None:
        return self.stack_home_by_reg.get(reg_id)

    @property
    def reg_ids(self) -> frozenset[BackendRegId]:
        return frozenset(self.stack_home_by_reg)

    @property
    def home_count(self) -> int:
        return len(self.stack_home_by_reg)

    def to_analysis_dump(self) -> BackendFunctionAnalysisDump:
        return BackendFunctionAnalysisDump(
            predecessors={},
            successors={},
            live_in={},
            live_out={},
            safepoint_live_regs={},
            root_slot_by_reg={},
            stack_home_by_reg=dict(self.stack_home_by_reg),
        )


def analyze_callable_stack_homes(callable_decl: BackendCallableDecl) -> BackendCallableStackHomes:
    if callable_decl.is_extern:
        return BackendCallableStackHomes(callable_decl=callable_decl, stack_home_by_reg={})

    return BackendCallableStackHomes(
        callable_decl=callable_decl,
        stack_home_by_reg={
            register.reg_id: stack_home_name_for_register(register)
            for register in sorted(callable_decl.registers, key=register_sort_key)
        },
    )


def stack_home_name_for_register(register: BackendRegister) -> str:
    sanitized_debug_name = _sanitize_home_fragment(register.debug_name)
    return f"home.{register.origin_kind}.{sanitized_debug_name}.r{register.reg_id.ordinal}"


def _sanitize_home_fragment(fragment: str) -> str:
    if not fragment:
        return "reg"
    sanitized = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in fragment)
    return sanitized or "reg"