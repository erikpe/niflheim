from __future__ import annotations

# Exact solver outline:
# 1. Parse each machine into a target vector and button incidence vectors.
# 2. Reorder buttons by simple upper bounds to reduce free-variable search.
# 3. Run Fraction-based RREF on the augmented linear system.
# 4. Enumerate the remaining free variables with pruning to minimize total presses.

from fractions import Fraction
import sys


def parse_machine(line: str) -> tuple[tuple[int, ...], list[list[int]]]:
    parts = line.split()
    target = tuple(map(int, parts[-1][1:-1].split(",")))
    buttons: list[list[int]] = []

    for token in parts[1:-1]:
        button = [0] * len(target)
        inner = token[1:-1]
        if inner:
            for index in map(int, inner.split(",")):
                button[index] = 1
        buttons.append(button)

    return target, buttons


def sort_buttons(target: tuple[int, ...], buttons: list[list[int]]) -> tuple[list[list[int]], list[int]]:
    upper_bounds = [min(value for value, bit in zip(target, button) if bit) if any(button) else 0 for button in buttons]
    order = sorted(range(len(buttons)), key=upper_bounds.__getitem__, reverse=True)
    return [buttons[index] for index in order], [upper_bounds[index] for index in order]


def rref(target: tuple[int, ...], buttons: list[list[int]]) -> tuple[list[list[Fraction]], list[int]]:
    row_count = len(target)
    col_count = len(buttons)
    matrix = [
        [Fraction(buttons[col][row]) for col in range(col_count)] + [Fraction(target[row])]
        for row in range(row_count)
    ]

    pivot_cols: list[int] = []
    pivot_row = 0
    for col in range(col_count):
        if pivot_row >= row_count:
            break

        found_row = next((row for row in range(pivot_row, row_count) if matrix[row][col]), None)
        if found_row is None:
            continue

        if found_row != pivot_row:
            matrix[pivot_row], matrix[found_row] = matrix[found_row], matrix[pivot_row]

        pivot = matrix[pivot_row][col]
        matrix[pivot_row][col:] = [value / pivot for value in matrix[pivot_row][col:]]

        for row in range(row_count):
            if row == pivot_row:
                continue
            factor = matrix[row][col]
            if not factor:
                continue
            matrix[row][col:] = [
                value - factor * pivot_value
                for value, pivot_value in zip(matrix[row][col:], matrix[pivot_row][col:])
            ]

        pivot_cols.append(col)
        pivot_row += 1

    if any(not any(row[:-1]) and row[-1] for row in matrix):
        raise RuntimeError("Machine has no integer solution.")

    return matrix, pivot_cols


def solve_machine(line: str) -> int:
    target, buttons = parse_machine(line)
    buttons, upper_bounds = sort_buttons(target, buttons)
    matrix, pivot_cols = rref(target, buttons)

    free_cols = [col for col in range(len(buttons)) if col not in set(pivot_cols)]
    if len(free_cols) > 3:
        raise RuntimeError("Too many free variables.")

    rows = [
        (matrix[row][-1], [(free_index, matrix[row][col]) for free_index, col in enumerate(free_cols) if matrix[row][col]])
        for row in range(len(pivot_cols))
    ]

    if not free_cols:
        total = 0
        for rhs, _ in rows:
            if rhs < 0 or rhs.denominator != 1:
                raise RuntimeError("Machine has no non-negative integer solution.")
            total += rhs.numerator
        return total

    free_vals = [0] * len(free_cols)
    best: int | None = None

    def dfs(depth: int, free_cost: int) -> None:
        nonlocal best
        if best is not None and free_cost >= best:
            return

        if depth == len(free_cols):
            total = free_cost
            for rhs, coeffs in rows:
                value = rhs
                for free_index, coeff in coeffs:
                    value -= coeff * free_vals[free_index]
                if value < 0 or value.denominator != 1:
                    return
                total += value.numerator
                if best is not None and total >= best:
                    return
            best = total
            return

        for current in range(upper_bounds[free_cols[depth]] + 1):
            free_vals[depth] = current
            dfs(depth + 1, free_cost + current)

    dfs(0, 0)

    if best is None:
        raise RuntimeError("Machine has no non-negative integer solution.")
    return best


def main() -> int:
    total = sum(solve_machine(line) for line in sys.stdin.read().splitlines() if line)
    print(f"RESULT:{total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())