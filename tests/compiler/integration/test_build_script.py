from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.compiler.integration.helpers import repo_root, write


def require_command(command: str) -> str:
    resolved = shutil.which(command)
    if resolved is None:
        pytest.skip(f"{command} not available")
    return resolved


def run_script(
    script_name: str,
    *script_args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo_root() / "scripts" / script_name), *script_args],
        cwd=repo_root(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_build_script_rejects_missing_prebuilt_runtime_archive(tmp_path: Path) -> None:
    require_command("cc")

    source = repo_root() / "samples" / "arithmetic_loop.nif"
    output = tmp_path / "main_program"
    env = os.environ.copy()
    env["NIF_PREBUILT_RUNTIME"] = str(tmp_path / "missing_runtime.a")

    proc = run_script("build.sh", str(source), str(output), env=env)

    assert proc.returncode != 0
    assert "build.sh: prebuilt runtime archive not found" in proc.stderr


def test_build_runtime_script_writes_requested_archive_path(tmp_path: Path) -> None:
    require_command("make")

    output_archive = tmp_path / "custom_runtime" / "libruntime.a"

    proc = run_script("build_runtime.sh", str(output_archive))

    assert proc.returncode == 0, proc.stderr or proc.stdout
    assert output_archive.exists()
    assert f"Built runtime archive: {output_archive}" in proc.stdout


class TestBuildAndRunScriptsNativeRuntime:
    @pytest.fixture(autouse=True)
    def _require_native_runtime_backend(self, require_native_runtime_backend: str) -> None:
        assert require_native_runtime_backend

    def test_build_script_forwards_compiler_cli_args(self, tmp_path: Path) -> None:
        require_command("cc")

        source = repo_root() / "samples" / "arithmetic_loop.nif"
        output = tmp_path / "main_program"

        proc = run_script(
            "build.sh",
            str(source),
            str(output),
            "--log-level",
            "info",
        )

        assert proc.returncode == 0, proc.stderr or proc.stdout
        assert output.exists()
        assert output.with_suffix(".s").exists()
        assert "nifc: info: Resolving program graph" in proc.stderr

    def test_build_script_supports_explicit_native_target(self, tmp_path: Path, native_runtime_backend_name: str) -> None:
        require_command("cc")

        source = repo_root() / "samples" / "arithmetic_loop.nif"
        output = tmp_path / "main_program_explicit_target"

        proc = run_script(
            "build.sh",
            str(source),
            str(output),
            "--",
            "--target",
            native_runtime_backend_name,
        )

        assert proc.returncode == 0, proc.stderr or proc.stdout
        assert output.exists()
        assert output.with_suffix(".s").exists()

    def test_run_script_supports_absolute_output_paths(self, tmp_path: Path) -> None:
        require_command("cc")

        source = repo_root() / "samples" / "arithmetic_loop.nif"
        output = tmp_path / "main_program"

        proc = run_script("run.sh", str(source), str(output))

        assert proc.returncode == 15, proc.stderr or proc.stdout
        assert output.exists()
        assert output.with_suffix(".s").exists()
        assert "RUN_EXIT:15" in proc.stdout