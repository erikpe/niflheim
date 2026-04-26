from __future__ import annotations

from pathlib import Path

from compiler.backend.analysis import analyze_callable_stack_homes
from compiler.backend.ir import BackendFunctionAnalysisDump
from compiler.backend.ir.text import dump_backend_program_text
from tests.compiler.backend.analysis.helpers import lower_source_to_backend_callable_fixture
from tests.compiler.backend.lowering.helpers import callable_by_suffix, lower_source_to_backend_program


def _registers_by_name(callable_decl, debug_name: str):
    return tuple(register for register in callable_decl.registers if register.debug_name == debug_name)


def _register_by_name(callable_decl, debug_name: str):
    matches = _registers_by_name(callable_decl, debug_name)
    assert len(matches) == 1
    return matches[0]


def test_stack_home_plan_assigns_homes_to_params_locals_and_temps(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        class Math {
            static fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }
        }

        fn f(values: i64[]) -> i64 {
            var total: i64 = 0;
            for item in values {
                total = Math.add(total, item);
            }
            return total;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    homes = analyze_callable_stack_homes(fixture.callable_decl)
    values_reg = _register_by_name(fixture.callable_decl, "values")
    total_reg = _register_by_name(fixture.callable_decl, "total")
    forin_collection_reg = _register_by_name(fixture.callable_decl, "forin_collection0")
    forin_index_reg = _register_by_name(fixture.callable_decl, "forin_index3")

    assert homes.home_count == len(fixture.callable_decl.registers)
    assert homes.for_reg(values_reg.reg_id) == "home.param.values.r0"
    assert homes.for_reg(total_reg.reg_id) == f"home.local.total.r{total_reg.reg_id.ordinal}"
    assert homes.for_reg(forin_collection_reg.reg_id) == f"home.temp.forin_collection0.r{forin_collection_reg.reg_id.ordinal}"
    assert homes.for_reg(forin_index_reg.reg_id) == f"home.temp.forin_index3.r{forin_index_reg.reg_id.ordinal}"


def test_stack_home_plan_assigns_distinct_homes_to_shadowed_locals(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        class Box {
        }

        fn f(value: Box) -> Box {
            var kept: Box = value;
            {
                var value: Box = Box();
                kept = value;
            }
            return kept;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    homes = analyze_callable_stack_homes(fixture.callable_decl)
    value_registers = _registers_by_name(fixture.callable_decl, "value")

    assert len(value_registers) == 2
    assert homes.for_reg(value_registers[0].reg_id) != homes.for_reg(value_registers[1].reg_id)


def test_stack_home_plan_tracks_mixed_primitive_reference_and_double_shapes_deterministically(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn combine(value: Obj, count: i64, scale: double) -> double {
            var kept: Obj = value;
            var adjusted: double = scale + 1.5;
            var total: i64 = count + 1;
            if total > count {
                return adjusted;
            }
            return adjusted;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="combine",
        skip_optimize=True,
    )

    first_homes = analyze_callable_stack_homes(fixture.callable_decl)
    second_homes = analyze_callable_stack_homes(fixture.callable_decl)
    scale_reg = _register_by_name(fixture.callable_decl, "scale")
    adjusted_reg = _register_by_name(fixture.callable_decl, "adjusted")
    total_reg = _register_by_name(fixture.callable_decl, "total")

    assert first_homes.stack_home_by_reg == second_homes.stack_home_by_reg
    assert first_homes.for_reg(scale_reg.reg_id) == f"home.param.scale.r{scale_reg.reg_id.ordinal}"
    assert first_homes.for_reg(adjusted_reg.reg_id) == f"home.local.adjusted.r{adjusted_reg.reg_id.ordinal}"
    assert first_homes.for_reg(total_reg.reg_id) == f"home.local.total.r{total_reg.reg_id.ordinal}"


def test_stack_home_plan_covers_constructor_receiver_and_params(tmp_path: Path) -> None:
    program = lower_source_to_backend_program(
        tmp_path,
        """
        class Box {
            next: Obj;

            constructor(next: Obj) {
                var tmp: Obj = next;
                __self.next = tmp;
                return;
            }
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        skip_optimize=True,
    )
    constructor_callable = callable_by_suffix(program, "main.Box.#0")
    homes = analyze_callable_stack_homes(constructor_callable)
    self_reg = _register_by_name(constructor_callable, "__self")
    next_reg = _register_by_name(constructor_callable, "next")
    tmp_reg = _register_by_name(constructor_callable, "tmp")

    assert homes.for_reg(self_reg.reg_id) == "home.receiver.__self.r0"
    assert homes.for_reg(next_reg.reg_id) == f"home.param.next.r{next_reg.reg_id.ordinal}"
    assert homes.for_reg(tmp_reg.reg_id) == f"home.local.tmp.r{tmp_reg.reg_id.ordinal}"


def test_stack_home_plan_can_render_analysis_dump_sections(tmp_path: Path) -> None:
    fixture = lower_source_to_backend_callable_fixture(
        tmp_path,
        """
        fn f(value: Obj) -> Obj {
            var kept: Obj = value;
            return kept;
        }

        fn main() -> i64 {
            return 0;
        }
        """,
        callable_name="f",
        skip_optimize=True,
    )

    homes = analyze_callable_stack_homes(fixture.callable_decl)
    rendered = dump_backend_program_text(
        fixture.program,
        analysis_by_callable={fixture.callable_decl.callable_id: homes.to_analysis_dump()},
    )

    assert isinstance(homes.to_analysis_dump(), BackendFunctionAnalysisDump)
    assert "stack_home_by_reg:" in rendered