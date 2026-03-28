from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO

from compiler.common.logging import configure_logging, get_logger, resolve_log_settings


def test_resolve_log_settings_defaults_to_warning_without_verbosity_flags() -> None:
    settings = resolve_log_settings(None, verbose=0, quiet=0)

    assert settings.level_name == "warning"
    assert settings.verbosity == 0


def test_resolve_log_settings_verbose_promotes_severity_and_detail() -> None:
    settings = resolve_log_settings(None, verbose=2, quiet=0)

    assert settings.level_name == "debug"
    assert settings.verbosity == 2


def test_resolve_log_settings_quiet_suppresses_below_error() -> None:
    settings = resolve_log_settings(None, verbose=0, quiet=2)

    assert settings.level_name == "error"
    assert settings.verbosity == 0


def test_resolve_log_settings_explicit_level_keeps_severity_independent() -> None:
    settings = resolve_log_settings("warning", verbose=2, quiet=0)

    assert settings.level_name == "warning"
    assert settings.verbosity == 2


def test_configure_logging_tracks_current_stderr_stream() -> None:
    first_stderr = StringIO()
    with redirect_stderr(first_stderr):
        configure_logging(resolve_log_settings("info", verbose=0, quiet=0))

    first_stderr.close()

    current_stderr = StringIO()
    with redirect_stderr(current_stderr):
        get_logger(__name__).info("hello")

    assert current_stderr.getvalue().strip() == "nifc: info: hello"