from __future__ import annotations

from dataclasses import dataclass
import sys


@dataclass(frozen=True)
class Rat:
    num: int
    den: int

    def sub(self, other: Rat) -> Rat:
        return make_rat(self.num * other.den - other.num * self.den, self.den * other.den)

    def mul(self, other: Rat) -> Rat:
        return make_rat(self.num * other.num, self.den * other.den)

    def scale(self, factor: int) -> Rat:
        return make_rat(self.num * factor, self.den)

    def div(self, other: Rat) -> Rat:
        if other.num == 0:
            raise RuntimeError("Division by zero rational.")
        return make_rat(self.num * other.den, self.den * other.num)

    def is_zero(self) -> bool:
        return self.num == 0

    def is_negative(self) -> bool:
        return self.num < 0

    def is_integer(self) -> bool:
        return self.den == 1

    def as_i64(self) -> int:
        if self.den != 1:
            raise RuntimeError("Expected integer rational.")
        return self.num


@dataclass
class Machine:
    targets: list[int]
    buttons: list[list[int]]


def abs_i64(value: int) -> int:
    if value < 0:
        return -value
    return value


def gcd_i64(left: int, right: int) -> int:
    a = abs_i64(left)
    b = abs_i64(right)
    while b != 0:
        next_value = a % b
        a = b
        b = next_value
    if a == 0:
        return 1
    return a


def make_rat(num: int, den: int) -> Rat:
    if den == 0:
        raise RuntimeError("Zero denominator.")

    reduced_num = num
    reduced_den = den
    if reduced_den < 0:
        reduced_num = -reduced_num
        reduced_den = -reduced_den
    if reduced_num == 0:
        return Rat(0, 1)

    gcd = gcd_i64(reduced_num, reduced_den)
    return Rat(reduced_num // gcd, reduced_den // gcd)


def decode_levels(levels_str: str) -> list[int]:
    parts = levels_str[1:-1].split(",")
    levels = [0] * len(parts)
    index = 0
    for part in parts:
        levels[index] = int(part)
        index += 1
    return levels


def decode_button(button_str: str, width: int) -> list[int]:
    button = [0] * width
    for raw_index in button_str[1:-1].split(","):
        button[int(raw_index)] = 1
    return button


def parse_machine(machine: str) -> Machine:
    parts = machine.split(" ")
    targets = decode_levels(parts[-1])
    buttons = [[0] * len(targets) for _ in range(len(parts) - 2)]
    for part_index in range(1, len(parts) - 1):
        buttons[part_index - 1] = decode_button(parts[part_index], len(targets))
    return Machine(targets, buttons)


def compute_upper_bounds(machine: Machine) -> list[int]:
    upper_bounds = [0] * len(machine.buttons)
    for button_index in range(len(machine.buttons)):
        bound = -1
        for target_index in range(len(machine.targets)):
            if machine.buttons[button_index][target_index] != 0:
                candidate = machine.targets[target_index]
                if bound < 0 or candidate < bound:
                    bound = candidate
        if bound < 0:
            bound = 0
        upper_bounds[button_index] = bound
    return upper_bounds


def sort_buttons_by_upper_bound(machine: Machine, upper_bounds: list[int]) -> None:
    for left_index in range(len(machine.buttons)):
        best_index = left_index
        for right_index in range(left_index + 1, len(machine.buttons)):
            if upper_bounds[right_index] > upper_bounds[best_index]:
                best_index = right_index

        if best_index != left_index:
            tmp_bound = upper_bounds[left_index]
            upper_bounds[left_index] = upper_bounds[best_index]
            upper_bounds[best_index] = tmp_bound

            tmp_button = machine.buttons[left_index]
            machine.buttons[left_index] = machine.buttons[best_index]
            machine.buttons[best_index] = tmp_button


def build_augmented_matrix(machine: Machine) -> list[list[Rat]]:
    matrix: list[list[Rat]] = [None] * len(machine.targets)
    for row_index in range(len(machine.targets)):
        row = [Rat(0, 1) for _ in range(len(machine.buttons) + 1)]
        for col_index in range(len(machine.buttons)):
            row[col_index] = make_rat(machine.buttons[col_index][row_index], 1)
        row[len(machine.buttons)] = make_rat(machine.targets[row_index], 1)
        matrix[row_index] = row
    return matrix


def swap_rows(matrix: list[list[Rat]], left_row: int, right_row: int) -> None:
    temp = matrix[left_row]
    matrix[left_row] = matrix[right_row]
    matrix[right_row] = temp


def rref(matrix: list[list[Rat]], num_buttons: int) -> list[int]:
    pivot_cols = [0] * len(matrix)
    pivot_count = 0
    pivot_row = 0

    for col_index in range(num_buttons):
        if pivot_row >= len(matrix):
            break

        found_row = -1
        for search_row in range(pivot_row, len(matrix)):
            if not matrix[search_row][col_index].is_zero():
                found_row = search_row
                break
        if found_row < 0:
            continue

        if found_row != pivot_row:
            swap_rows(matrix, pivot_row, found_row)

        pivot_value = matrix[pivot_row][col_index]
        for normalize_col in range(col_index, num_buttons + 1):
            matrix[pivot_row][normalize_col] = matrix[pivot_row][normalize_col].div(pivot_value)

        for eliminate_row in range(len(matrix)):
            if eliminate_row == pivot_row:
                continue

            factor = matrix[eliminate_row][col_index]
            if factor.is_zero():
                continue

            for update_col in range(col_index, num_buttons + 1):
                matrix[eliminate_row][update_col] = matrix[eliminate_row][update_col].sub(
                    factor.mul(matrix[pivot_row][update_col])
                )

        pivot_cols[pivot_count] = col_index
        pivot_count += 1
        pivot_row += 1

    return pivot_cols[:pivot_count]


def validate_consistent(matrix: list[list[Rat]], num_buttons: int) -> None:
    for row in matrix:
        if not row_has_coeff(row, num_buttons) and not row[num_buttons].is_zero():
            raise RuntimeError("Machine has no integer solution.")


def row_has_coeff(row: list[Rat], num_buttons: int) -> bool:
    for col_index in range(num_buttons):
        if not row[col_index].is_zero():
            return True
    return False


def collect_free_columns(num_buttons: int, pivot_cols: list[int]) -> list[int]:
    is_pivot = [False] * num_buttons
    for pivot_col in pivot_cols:
        is_pivot[pivot_col] = True

    free_cols = [0] * (num_buttons - len(pivot_cols))
    free_index = 0
    for col_index in range(num_buttons):
        if not is_pivot[col_index]:
            free_cols[free_index] = col_index
            free_index += 1
    return free_cols


def evaluate_cost(
    matrix: list[list[Rat]],
    num_buttons: int,
    pivot_cols: list[int],
    free_cols: list[int],
    free_vals: list[int],
    free_cost: int,
) -> int:
    total_cost = free_cost

    for pivot_index in range(len(pivot_cols)):
        value = matrix[pivot_index][num_buttons]
        for free_index in range(len(free_cols)):
            coeff = matrix[pivot_index][free_cols[free_index]]
            if not coeff.is_zero():
                value = value.sub(coeff.scale(free_vals[free_index]))

        if value.is_negative() or not value.is_integer():
            return -1

        total_cost += value.as_i64()

    return total_cost


def search_best_cost(
    matrix: list[list[Rat]],
    num_buttons: int,
    pivot_cols: list[int],
    free_cols: list[int],
    upper_bounds: list[int],
    free_vals: list[int],
    depth: int,
    free_cost: int,
    best_cost: int,
) -> int:
    current_best = best_cost
    if depth == len(free_cols):
        candidate = evaluate_cost(matrix, num_buttons, pivot_cols, free_cols, free_vals, free_cost)
        if candidate >= 0 and (current_best < 0 or candidate < current_best):
            return candidate
        return current_best

    upper_bound = upper_bounds[free_cols[depth]]
    for current in range(upper_bound + 1):
        next_free_cost = free_cost + current
        if current_best >= 0 and next_free_cost >= current_best:
            continue

        free_vals[depth] = current
        current_best = search_best_cost(
            matrix,
            num_buttons,
            pivot_cols,
            free_cols,
            upper_bounds,
            free_vals,
            depth + 1,
            next_free_cost,
            current_best,
        )

    return current_best


def solve_machine(machine_line: str) -> int:
    machine = parse_machine(machine_line)
    upper_bounds = compute_upper_bounds(machine)
    sort_buttons_by_upper_bound(machine, upper_bounds)

    num_buttons = len(machine.buttons)
    matrix = build_augmented_matrix(machine)
    pivot_cols = rref(matrix, num_buttons)
    validate_consistent(matrix, num_buttons)

    free_cols = collect_free_columns(num_buttons, pivot_cols)
    if len(free_cols) > 3:
        raise RuntimeError("Too many free variables.")

    if len(free_cols) == 0:
        return evaluate_cost(matrix, num_buttons, pivot_cols, free_cols, [], 0)

    best_cost = search_best_cost(
        matrix,
        num_buttons,
        pivot_cols,
        free_cols,
        upper_bounds,
        [0] * len(free_cols),
        0,
        0,
        -1,
    )

    if best_cost < 0:
        raise RuntimeError("Machine has no non-negative integer solution.")
    return best_cost


def main() -> int:
    total_presses = 0
    for line in sys.stdin.read().splitlines():
        total_presses += solve_machine(line)

    print("RESULT:", end="")
    print(total_presses)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())