import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStreamReader;
import java.util.ArrayList;
import java.util.List;

public final class test_solver {
    private static final class Rat {
        final long num;
        final long den;

        Rat(long num, long den) {
            this.num = num;
            this.den = den;
        }

        Rat sub(Rat other) {
            return make_rat(this.num * other.den - other.num * this.den, this.den * other.den);
        }

        Rat mul(Rat other) {
            return make_rat(this.num * other.num, this.den * other.den);
        }

        Rat scale(long factor) {
            return make_rat(this.num * factor, this.den);
        }

        Rat div(Rat other) {
            if (other.num == 0L) {
                throw new IllegalStateException("Division by zero rational.");
            }
            return make_rat(this.num * other.den, this.den * other.num);
        }

        boolean isZero() {
            return this.num == 0L;
        }

        boolean isNegative() {
            return this.num < 0L;
        }

        boolean isInteger() {
            return this.den == 1L;
        }

        long as_i64() {
            if (this.den != 1L) {
                throw new IllegalStateException("Expected integer rational.");
            }
            return this.num;
        }
    }

    private static final class Machine {
        final long[] targets;
        final long[][] buttons;

        Machine(long[] targets, long[][] buttons) {
            this.targets = targets;
            this.buttons = buttons;
        }
    }

    private test_solver() {
    }

    private static long abs_i64(long value) {
        if (value < 0L) {
            return -value;
        }
        return value;
    }

    private static long gcd_i64(long left, long right) {
        long a = abs_i64(left);
        long b = abs_i64(right);
        while (b != 0L) {
            long next = a % b;
            a = b;
            b = next;
        }
        if (a == 0L) {
            return 1L;
        }
        return a;
    }

    private static Rat make_rat(long num, long den) {
        if (den == 0L) {
            throw new IllegalStateException("Zero denominator.");
        }

        long reduced_num = num;
        long reduced_den = den;
        if (reduced_den < 0L) {
            reduced_num = -reduced_num;
            reduced_den = -reduced_den;
        }
        if (reduced_num == 0L) {
            return new Rat(0L, 1L);
        }

        long gcd = gcd_i64(reduced_num, reduced_den);
        return new Rat(reduced_num / gcd, reduced_den / gcd);
    }

    private static long[] decode_levels(String levelsStr) {
        String[] parts = levelsStr.substring(1, levelsStr.length() - 1).split(",");
        long[] levels = new long[parts.length];
        for (int index = 0; index < parts.length; index++) {
            levels[index] = Long.parseLong(parts[index]);
        }
        return levels;
    }

    private static long[] decode_button(String buttonStr, int width) {
        long[] button = new long[width];
        String inner = buttonStr.substring(1, buttonStr.length() - 1);
        if (inner.isEmpty()) {
            return button;
        }
        String[] indices = inner.split(",");
        for (String indexStr : indices) {
            button[Integer.parseInt(indexStr)] = 1L;
        }
        return button;
    }

    private static Machine parse_machine(String machine) {
        String[] parts = machine.split(" ");
        long[] targets = decode_levels(parts[parts.length - 1]);
        long[][] buttons = new long[parts.length - 2][];
        for (int partIndex = 1; partIndex < parts.length - 1; partIndex++) {
            buttons[partIndex - 1] = decode_button(parts[partIndex], targets.length);
        }
        return new Machine(targets, buttons);
    }

    private static long[] compute_upper_bounds(Machine machine) {
        long[] upperBounds = new long[machine.buttons.length];
        for (int buttonIndex = 0; buttonIndex < machine.buttons.length; buttonIndex++) {
            long bound = -1L;
            for (int targetIndex = 0; targetIndex < machine.targets.length; targetIndex++) {
                if (machine.buttons[buttonIndex][targetIndex] != 0L) {
                    long candidate = machine.targets[targetIndex];
                    if (bound < 0L || candidate < bound) {
                        bound = candidate;
                    }
                }
            }
            if (bound < 0L) {
                bound = 0L;
            }
            upperBounds[buttonIndex] = bound;
        }
        return upperBounds;
    }

    private static void sort_buttons_by_upper_bound(Machine machine, long[] upperBounds) {
        for (int leftIndex = 0; leftIndex < machine.buttons.length; leftIndex++) {
            int bestIndex = leftIndex;
            for (int rightIndex = leftIndex + 1; rightIndex < machine.buttons.length; rightIndex++) {
                if (upperBounds[rightIndex] > upperBounds[bestIndex]) {
                    bestIndex = rightIndex;
                }
            }

            if (bestIndex != leftIndex) {
                long tmpBound = upperBounds[leftIndex];
                upperBounds[leftIndex] = upperBounds[bestIndex];
                upperBounds[bestIndex] = tmpBound;

                long[] tmpButton = machine.buttons[leftIndex];
                machine.buttons[leftIndex] = machine.buttons[bestIndex];
                machine.buttons[bestIndex] = tmpButton;
            }
        }
    }

    private static Rat[][] build_augmented_matrix(Machine machine) {
        Rat[][] matrix = new Rat[machine.targets.length][];
        for (int rowIndex = 0; rowIndex < machine.targets.length; rowIndex++) {
            Rat[] row = new Rat[machine.buttons.length + 1];
            for (int colIndex = 0; colIndex < machine.buttons.length; colIndex++) {
                row[colIndex] = make_rat(machine.buttons[colIndex][rowIndex], 1L);
            }
            row[machine.buttons.length] = make_rat(machine.targets[rowIndex], 1L);
            matrix[rowIndex] = row;
        }
        return matrix;
    }

    private static void swap_rows(Rat[][] matrix, int leftRow, int rightRow) {
        Rat[] temp = matrix[leftRow];
        matrix[leftRow] = matrix[rightRow];
        matrix[rightRow] = temp;
    }

    private static long[] rref(Rat[][] matrix, int numButtons) {
        long[] pivotCols = new long[matrix.length];
        int pivotCount = 0;
        int pivotRow = 0;

        for (int colIndex = 0; colIndex < numButtons; colIndex++) {
            if (pivotRow >= matrix.length) {
                break;
            }

            int foundRow = -1;
            for (int searchRow = pivotRow; searchRow < matrix.length; searchRow++) {
                if (!matrix[searchRow][colIndex].isZero()) {
                    foundRow = searchRow;
                    break;
                }
            }
            if (foundRow < 0) {
                continue;
            }

            if (foundRow != pivotRow) {
                swap_rows(matrix, pivotRow, foundRow);
            }

            Rat pivotValue = matrix[pivotRow][colIndex];
            for (int normalizeCol = colIndex; normalizeCol < numButtons + 1; normalizeCol++) {
                matrix[pivotRow][normalizeCol] = matrix[pivotRow][normalizeCol].div(pivotValue);
            }

            for (int eliminateRow = 0; eliminateRow < matrix.length; eliminateRow++) {
                if (eliminateRow == pivotRow) {
                    continue;
                }

                Rat factor = matrix[eliminateRow][colIndex];
                if (factor.isZero()) {
                    continue;
                }

                for (int updateCol = colIndex; updateCol < numButtons + 1; updateCol++) {
                    matrix[eliminateRow][updateCol] = matrix[eliminateRow][updateCol].sub(
                        factor.mul(matrix[pivotRow][updateCol])
                    );
                }
            }

            pivotCols[pivotCount] = colIndex;
            pivotCount = pivotCount + 1;
            pivotRow = pivotRow + 1;
        }

        long[] result = new long[pivotCount];
        for (int index = 0; index < pivotCount; index++) {
            result[index] = pivotCols[index];
        }
        return result;
    }

    private static void validate_consistent(Rat[][] matrix, int numButtons) {
        for (Rat[] row : matrix) {
            if (!row_has_coeff(row, numButtons) && !row[numButtons].isZero()) {
                throw new IllegalStateException("Machine has no integer solution.");
            }
        }
    }

    private static boolean row_has_coeff(Rat[] row, int numButtons) {
        for (int colIndex = 0; colIndex < numButtons; colIndex++) {
            if (!row[colIndex].isZero()) {
                return true;
            }
        }
        return false;
    }

    private static long[] collect_free_columns(int numButtons, long[] pivotCols) {
        boolean[] isPivot = new boolean[numButtons];
        for (long pivotCol : pivotCols) {
            isPivot[(int)pivotCol] = true;
        }

        long[] freeCols = new long[numButtons - pivotCols.length];
        int freeIndex = 0;
        for (int colIndex = 0; colIndex < numButtons; colIndex++) {
            if (!isPivot[colIndex]) {
                freeCols[freeIndex] = colIndex;
                freeIndex = freeIndex + 1;
            }
        }
        return freeCols;
    }

    private static long evaluate_cost(
        Rat[][] matrix,
        int numButtons,
        long[] pivotCols,
        long[] freeCols,
        long[] freeVals,
        long freeCost
    ) {
        long totalCost = freeCost;

        for (int pivotIndex = 0; pivotIndex < pivotCols.length; pivotIndex++) {
            Rat value = matrix[pivotIndex][numButtons];
            for (int freeIndex = 0; freeIndex < freeCols.length; freeIndex++) {
                Rat coeff = matrix[pivotIndex][(int)freeCols[freeIndex]];
                if (!coeff.isZero()) {
                    value = value.sub(coeff.scale(freeVals[freeIndex]));
                }
            }

            if (value.isNegative() || !value.isInteger()) {
                return -1L;
            }

            totalCost = totalCost + value.as_i64();
        }

        return totalCost;
    }

    private static long search_best_cost(
        Rat[][] matrix,
        int numButtons,
        long[] pivotCols,
        long[] freeCols,
        long[] upperBounds,
        long[] freeVals,
        int depth,
        long freeCost,
        long bestCost
    ) {
        long currentBest = bestCost;
        if (depth == freeCols.length) {
            long candidate = evaluate_cost(matrix, numButtons, pivotCols, freeCols, freeVals, freeCost);
            if (candidate >= 0L && (currentBest < 0L || candidate < currentBest)) {
                return candidate;
            }
            return currentBest;
        }

        long upperBound = upperBounds[(int)freeCols[depth]];
        for (long current = 0L; current <= upperBound; current++) {
            long nextFreeCost = freeCost + current;
            if (currentBest >= 0L && nextFreeCost >= currentBest) {
                continue;
            }

            freeVals[depth] = current;
            currentBest = search_best_cost(
                matrix,
                numButtons,
                pivotCols,
                freeCols,
                upperBounds,
                freeVals,
                depth + 1,
                nextFreeCost,
                currentBest
            );
        }

        return currentBest;
    }

    private static long solve_machine(String machineLine) {
        Machine machine = parse_machine(machineLine);
        long[] upperBounds = compute_upper_bounds(machine);
        sort_buttons_by_upper_bound(machine, upperBounds);

        int numButtons = machine.buttons.length;
        Rat[][] matrix = build_augmented_matrix(machine);
        long[] pivotCols = rref(matrix, numButtons);
        validate_consistent(matrix, numButtons);

        long[] freeCols = collect_free_columns(numButtons, pivotCols);
        if (freeCols.length > 3) {
            throw new IllegalStateException("Too many free variables.");
        }

        if (freeCols.length == 0) {
            return evaluate_cost(matrix, numButtons, pivotCols, freeCols, new long[0], 0L);
        }

        long bestCost = search_best_cost(
            matrix,
            numButtons,
            pivotCols,
            freeCols,
            upperBounds,
            new long[freeCols.length],
            0,
            0L,
            -1L
        );

        if (bestCost < 0L) {
            throw new IllegalStateException("Machine has no non-negative integer solution.");
        }
        return bestCost;
    }

    public static void main(String[] args) throws IOException {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        List<String> lines = new ArrayList<>();
        while (true) {
            String line = reader.readLine();
            if (line == null) {
                break;
            }
            lines.add(line);
        }

        long totalPresses = 0L;
        for (String line : lines) {
            totalPresses = totalPresses + solve_machine(line);
        }

        System.out.print("RESULT:");
        System.out.println(totalPresses);
    }
}