from __future__ import annotations

from compiler.semantic.optimizations.helpers.dataflow import solve_loop_fixed_point


def test_solve_loop_fixed_point_converges_to_stable_state() -> None:
    stable_state, control_flow = solve_loop_fixed_point(
        initial_state=0, loop_exit_state=10, next_state=lambda current, _control: min(current + 1, 3)
    )

    assert stable_state == 3
    assert control_flow.continue_state == 3
    assert control_flow.break_state == 10


def test_solve_loop_fixed_point_exposes_loop_control_states_to_transition() -> None:
    stable_state, control_flow = solve_loop_fixed_point(
        initial_state=frozenset({"seed"}),
        loop_exit_state=frozenset({"break"}),
        next_state=lambda current, loop: current | loop.break_state | frozenset({"continue"}),
    )

    assert stable_state == frozenset({"seed", "break", "continue"})
    assert control_flow.continue_state == stable_state
    assert control_flow.break_state == frozenset({"break"})
