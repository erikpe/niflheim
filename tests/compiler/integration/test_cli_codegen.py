from __future__ import annotations

from pathlib import Path

import pytest

import compiler.cli as cli
from compiler.backend.program.symbols import mangle_function_symbol
from compiler.backend.targets import BackendEmitResult, BackendTargetInput
from tests.compiler.integration.helpers import compile_to_asm, run_cli, write, write_project


class _RecordingTarget:
    def __init__(self, emit_backend, *, name: str = "x86_64_sysv") -> None:
        self.name = name
        self._emit_backend = emit_backend

    def emit_assembly(self, target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return self._emit_backend(target_input, options=options)


def _patch_resolve_backend_target(
    monkeypatch: pytest.MonkeyPatch,
    emit_backend,
    *,
    target_name: str = "x86_64_sysv",
    seen: dict[str, object] | None = None,
) -> None:
    def _fake_resolve_backend_target(requested_target_name: str | None = None) -> _RecordingTarget:
        if seen is not None:
            seen["requested_target_name"] = requested_target_name
        return _RecordingTarget(emit_backend, name=target_name)

    monkeypatch.setattr(cli, "resolve_backend_target", _fake_resolve_backend_target)


def test_cli_defaults_to_backend_ir_x86_64_sysv_path(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        seen["target_input"] = target_input
        seen["runtime_trace_enabled"] = options.runtime_trace_enabled
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend, seen=seen)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; backend-ir target selected\n"
    target_input = seen["target_input"]
    assert isinstance(target_input, BackendTargetInput)
    assert target_input.program.entry_callable_id.module_path == ("main",)
    assert target_input.program.entry_callable_id.name == "main"
    assert target_input.analysis_by_callable_id
    assert seen["runtime_trace_enabled"] is True
    assert seen["requested_target_name"] is None


def test_cli_explicit_target_routes_through_target_resolution(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        seen["target_input"] = target_input
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend, seen=seen)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--target", "x86_64_sysv", "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; backend-ir target selected\n"
    assert isinstance(seen["target_input"], BackendTargetInput)
    assert seen["requested_target_name"] == "x86_64_sysv"


def test_cli_can_omit_runtime_trace_calls(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        seen["target_input"] = target_input
        seen["runtime_trace_enabled"] = options.runtime_trace_enabled
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend, seen=seen)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--omit-runtime-trace", "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; backend-ir target selected\n"
    assert seen["runtime_trace_enabled"] is False


def test_cli_can_disable_all_optimization_phases(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {"semantic_optimize_called": False, "backend_optimize_called": False}

    def _fake_optimize_program(lowered_program, *, passes):
        seen["semantic_optimize_called"] = True
        return lowered_program

    def _fake_optimize_backend_program(backend_program, *, passes):
        seen["backend_optimize_called"] = True
        return backend_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        seen["target_input"] = target_input
        seen["runtime_trace_enabled"] = options.runtime_trace_enabled
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_semantic_program", _fake_optimize_program)
    monkeypatch.setattr(cli, "optimize_backend_ir_program", _fake_optimize_backend_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend, seen=seen)

    rc = run_cli(monkeypatch, ["nifc", str(entry), "--disable-all-optimization", "-o", str(out_file)])

    assert rc == 0
    assert out_file.read_text(encoding="utf-8") == "; backend-ir target selected\n"
    assert seen["semantic_optimize_called"] is False
    assert seen["backend_optimize_called"] is False
    assert isinstance(seen["target_input"], BackendTargetInput)


def test_cli_disable_all_optimization_overrides_named_disabled_passes(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {"semantic_optimize_called": False, "backend_optimize_called": False}

    def _fake_optimize_program(lowered_program, *, passes):
        seen["semantic_optimize_called"] = True
        return lowered_program

    def _fake_optimize_backend_program(backend_program, *, passes):
        seen["backend_optimize_called"] = True
        return backend_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_semantic_program", _fake_optimize_program)
    monkeypatch.setattr(cli, "optimize_backend_ir_program", _fake_optimize_backend_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        [
            "nifc",
            str(entry),
            "--disable-all-optimization",
            "--disable-semantic-optimization",
            "constant_fold",
            "--disable-backend-optimization",
            "constant_fold",
            "-o",
            str(out_file),
        ],
    )

    assert rc == 0
    assert seen["semantic_optimize_called"] is False
    assert seen["backend_optimize_called"] is False


def test_cli_can_disable_named_semantic_optimization_pass(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 1 + 2;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_optimize_program(lowered_program, *, passes):
        seen["pass_names"] = tuple(optimization_pass.name for optimization_pass in passes)
        return lowered_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_semantic_program", _fake_optimize_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--disable-semantic-optimization", "constant_fold", "-o", str(out_file)],
    )

    assert rc == 0
    assert "constant_fold" not in seen["pass_names"]
    assert "copy_propagation" in seen["pass_names"]


def test_cli_can_disable_multiple_semantic_optimization_passes_with_one_flag(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 1 + 2;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_optimize_program(lowered_program, *, passes):
        seen["pass_names"] = tuple(optimization_pass.name for optimization_pass in passes)
        return lowered_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_semantic_program", _fake_optimize_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        [
            "nifc",
            str(entry),
            "--disable-semantic-optimization",
            "algebraic_simplify",
            "constant_fold",
            "-o",
            str(out_file),
        ],
    )

    assert rc == 0
    assert "algebraic_simplify" not in seen["pass_names"]
    assert "constant_fold" not in seen["pass_names"]
    assert "copy_propagation" in seen["pass_names"]


def test_cli_can_disable_all_semantic_optimization_passes_by_name(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 1 + 2;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_optimize_program(lowered_program, *, passes):
        seen["pass_names"] = tuple(optimization_pass.name for optimization_pass in passes)
        return lowered_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_semantic_program", _fake_optimize_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--disable-semantic-optimization", "all", "-o", str(out_file)],
    )

    assert rc == 0
    assert seen["pass_names"] == ()


def test_cli_can_disable_named_backend_optimization_pass(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_optimize_backend_program(backend_program, *, passes):
        seen["pass_names"] = tuple(optimization_pass.name for optimization_pass in passes)
        return backend_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_backend_ir_program", _fake_optimize_backend_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--disable-backend-optimization", "constant_fold", "-o", str(out_file)],
    )

    assert rc == 0
    assert "constant_fold" not in seen["pass_names"]
    assert "simplify_cfg" in seen["pass_names"]


def test_cli_disables_all_backend_optimization_passes_when_all_is_grouped_with_names(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_optimize_backend_program(backend_program, *, passes):
        seen["pass_names"] = tuple(optimization_pass.name for optimization_pass in passes)
        return backend_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_backend_ir_program", _fake_optimize_backend_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        [
            "nifc",
            str(entry),
            "--disable-backend-optimization",
            "constant_fold",
            "all",
            "-o",
            str(out_file),
        ],
    )

    assert rc == 0
    assert seen["pass_names"] == ()


def test_cli_can_disable_all_backend_optimization_passes_by_name(tmp_path: Path, monkeypatch) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    seen: dict[str, object] = {}

    def _fake_optimize_backend_program(backend_program, *, passes):
        seen["pass_names"] = tuple(optimization_pass.name for optimization_pass in passes)
        return backend_program

    def _fake_emit_backend(target_input: BackendTargetInput, *, options) -> BackendEmitResult:
        return BackendEmitResult(assembly_text="; backend-ir target selected\n")

    monkeypatch.setattr(cli, "optimize_backend_ir_program", _fake_optimize_backend_program)
    _patch_resolve_backend_target(monkeypatch, _fake_emit_backend)

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--disable-backend-optimization", "all", "-o", str(out_file)],
    )

    assert rc == 0
    assert seen["pass_names"] == ()


def test_cli_rejects_unknown_disabled_optimization_pass(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    out_file = tmp_path / "out.s"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    rc = run_cli(
        monkeypatch,
        ["nifc", str(entry), "--disable-semantic-optimization", "nope", "-o", str(out_file)],
    )
    captured = capsys.readouterr()

    assert rc == 1
    assert "Unknown semantic optimization pass 'nope'" in captured.err


def test_cli_source_ast_codegen_flag_is_rejected(tmp_path: Path, monkeypatch, capsys) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        fn main() -> i64 {
            return 0;
        }
        """,
    )

    with pytest.raises(SystemExit) as exc_info:
        run_cli(monkeypatch, ["nifc", str(entry), "--source-ast-codegen"])
    captured = capsys.readouterr()

    assert exc_info.value.code == 2
    assert "unrecognized arguments: --source-ast-codegen" in captured.err


def test_cli_default_codegen_prunes_dead_duplicate_class_symbols_before_link(
    tmp_path: Path, monkeypatch
) -> None:
    write_project(
        tmp_path,
        {
            "left.nif": """
            export class Box {
                value: i64;
            }
            """,
            "right.nif": """
            export class Box {
                value: i64;
            }
            """,
            "main.nif": """
            import left;
            import right;

            fn main() -> i64 {
                return 0;
            }
            """,
        },
    )

    out_file = compile_to_asm(monkeypatch, tmp_path / "main.nif", project_root=tmp_path, out_path=tmp_path / "out.s")

    assert out_file.exists()


def test_cli_default_codegen_prunes_dead_declarations_but_keeps_virtual_methods_needed_for_vtables(
    tmp_path: Path, monkeypatch
) -> None:
    entry = tmp_path / "main.nif"
    write(
        entry,
        """
        class Box {
            value: i64;

            static fn make(value: i64) -> Box {
                return Box(value);
            }

            fn read() -> i64 {
                return __self.value;
            }

            fn dead() -> i64 {
                return 99;
            }

            private fn dead_private() -> i64 {
                return 100;
            }

            static fn dead_static() -> i64 {
                return 101;
            }
        }

        fn helper() -> i64 {
            return 1;
        }

        fn dead_helper() -> i64 {
            return 7;
        }

        fn main() -> i64 {
            var box: Box = Box.make(helper());
            return box.read();
        }
        """,
    )

    out_file = compile_to_asm(monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert f'{mangle_function_symbol(("main",), "dead_helper")}:' not in asm
    assert "__nif_method_main__Box_dead:" in asm
    assert "__nif_method_main__Box_dead_private:" not in asm
    assert "__nif_method_main__Box_dead_static:" not in asm
    assert f'{mangle_function_symbol(("main",), "helper")}:' in asm
    assert "__nif_method_main__Box_make:" in asm
    assert "__nif_method_main__Box_read:" in asm


def test_cli_default_codegen_prunes_dead_imported_interface_descriptors_from_assembly(
    tmp_path: Path, monkeypatch
) -> None:
    write_project(
        tmp_path,
        {
            "contracts.nif": """
            export interface Hashable {
                fn hash_code() -> u64;
            }

            export interface DeadContract {
                fn dead() -> i64;
            }
            """,
            "model.nif": """
            import contracts;

            export class Key implements Hashable {
                fn hash_code() -> u64 {
                    return 1u;
                }
            }

            export fn make() -> Key {
                return Key();
            }
            """,
            "main.nif": """
            import model;

            fn main() -> i64 {
                if model.make() == null {
                    return 1;
                }
                return 0;
            }
            """,
        },
    )

    out_file = compile_to_asm(monkeypatch, tmp_path / "main.nif", project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert "__nif_interface_contracts__DeadContract:" not in asm
    assert "__nif_interface_name_contracts__DeadContract:" not in asm
    assert "__nif_interface_contracts__Hashable:" in asm


def test_cli_default_codegen_keeps_referenced_imported_interface_descriptors_in_assembly(
    tmp_path: Path, monkeypatch
) -> None:
    write_project(
        tmp_path,
        {
            "contracts.nif": """
            export interface Hashable {
                fn hash_code() -> u64;
            }

            export interface DeadContract {
                fn dead() -> i64;
            }
            """,
            "model.nif": """
            import contracts;

            export class Key implements Hashable {
                fn hash_code() -> u64 {
                    return 1u;
                }
            }

            export fn make_hashable() -> contracts.Hashable {
                return Key();
            }
            """,
            "main.nif": """
            import model;

            fn main() -> i64 {
                if model.make_hashable().hash_code() == 1u {
                    return 0;
                }
                return 1;
            }
            """,
        },
    )

    out_file = compile_to_asm(monkeypatch, tmp_path / "main.nif", project_root=tmp_path, out_path=tmp_path / "out.s")
    asm = out_file.read_text(encoding="utf-8")

    assert "__nif_interface_contracts__Hashable:" in asm
    assert "__nif_interface_name_contracts__Hashable:" in asm
    assert "__nif_interface_methods_model__Key__contracts__Hashable:" in asm
    assert "__nif_interface_contracts__DeadContract:" not in asm
