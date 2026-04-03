from __future__ import annotations

from pathlib import Path

from tests.compiler.integration.helpers import compile_and_run, write_project


def test_cli_interfaces_runtime_supports_imported_interfaces_across_modules(tmp_path: Path, monkeypatch) -> None:
    write_project(
        tmp_path,
        {
            "contracts.nif": """
            export interface Hashable {
                fn hash_code() -> u64;
            }
            """,
            "model.nif": """
            import contracts;

            export class Key implements Hashable {
                value: u64;

                fn hash_code() -> u64 {
                    return __self.value;
                }
            }

            export fn as_hashable(value: u64) -> contracts.Hashable {
                return Key(value);
            }
            """,
            "main.nif": """
            import contracts;
            import model;

            fn bounce(value: Hashable) -> contracts.Hashable {
                return value;
            }

            fn main() -> i64 {
                var values: Hashable[] = Hashable[](2u);
                values[0] = model.as_hashable(10u);
                values[1] = bounce(model.Key(32u));

                if values[0].hash_code() != 10u {
                    return 1;
                }
                if values[1].hash_code() != 32u {
                    return 2;
                }
                return 0;
            }
            """,
        },
    )

    entry = tmp_path / "main.nif"
    run = compile_and_run(
        monkeypatch, entry, project_root=tmp_path, out_path=tmp_path / "out.s", exe_path=tmp_path / "program"
    )

    assert run.returncode == 0