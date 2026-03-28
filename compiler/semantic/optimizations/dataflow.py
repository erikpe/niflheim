from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, TypeVar


TState = TypeVar("TState")


@dataclass(frozen=True)
class LoopControlFlowState(Generic[TState]):
    continue_state: TState
    break_state: TState


def solve_loop_fixed_point(
    *,
    initial_state: TState,
    loop_exit_state: TState,
    next_state: Callable[[TState, LoopControlFlowState[TState]], TState],
) -> tuple[TState, LoopControlFlowState[TState]]:
    current_state = initial_state

    while True:
        control_flow = LoopControlFlowState(
            continue_state=current_state,
            break_state=loop_exit_state,
        )
        updated_state = next_state(current_state, control_flow)
        if updated_state == current_state:
            return current_state, control_flow
        current_state = updated_state