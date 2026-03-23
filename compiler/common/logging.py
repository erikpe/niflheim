from __future__ import annotations

import logging
import sys
from dataclasses import dataclass


LOG_LEVEL_NAMES = ("error", "warning", "info", "debug")
_LOG_LEVEL_VALUES = {
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}
_DEFAULT_LEVEL_INDEX = LOG_LEVEL_NAMES.index("warning")


@dataclass(frozen=True, slots=True)
class LogSettings:
    level_name: str
    level_value: int
    verbosity: int


class _VerbosityFilter(logging.Filter):
    def __init__(self, verbosity: int) -> None:
        super().__init__()
        self._verbosity = verbosity

    def filter(self, record: logging.LogRecord) -> bool:
        return getattr(record, "verbosity", 0) <= self._verbosity


class _CompilerLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.levelno >= logging.ERROR:
            return f"nifc: {message}"
        return f"nifc: {record.levelname.lower()}: {message}"


class CompilerLogger(logging.LoggerAdapter[logging.Logger]):
    def process(self, msg: object, kwargs: dict[str, object]) -> tuple[object, dict[str, object]]:
        extra = kwargs.setdefault("extra", {})
        if isinstance(extra, dict):
            extra.setdefault("verbosity", 0)
        return msg, kwargs

    def logv(self, level: int, verbosity: int, msg: object, *args: object, **kwargs: object) -> None:
        if not self.isEnabledFor(level):
            return
        extra = kwargs.pop("extra", None)
        merged_extra = {} if not isinstance(extra, dict) else dict(extra)
        merged_extra.setdefault("verbosity", verbosity)
        kwargs["extra"] = merged_extra
        self.log(level, msg, *args, **kwargs)

    def debugv(self, verbosity: int, msg: object, *args: object, **kwargs: object) -> None:
        self.logv(logging.DEBUG, verbosity, msg, *args, **kwargs)

    def infov(self, verbosity: int, msg: object, *args: object, **kwargs: object) -> None:
        self.logv(logging.INFO, verbosity, msg, *args, **kwargs)

    def warningv(self, verbosity: int, msg: object, *args: object, **kwargs: object) -> None:
        self.logv(logging.WARNING, verbosity, msg, *args, **kwargs)

    def errorv(self, verbosity: int, msg: object, *args: object, **kwargs: object) -> None:
        self.logv(logging.ERROR, verbosity, msg, *args, **kwargs)


def resolve_log_settings(level_name: str | None, verbose: int, quiet: int) -> LogSettings:
    verbosity = max(0, verbose - quiet)
    if level_name is None:
        level_index = _DEFAULT_LEVEL_INDEX + verbose - quiet
        level_index = max(0, min(level_index, len(LOG_LEVEL_NAMES) - 1))
        resolved_level_name = LOG_LEVEL_NAMES[level_index]
    else:
        resolved_level_name = level_name.lower()
        if resolved_level_name not in _LOG_LEVEL_VALUES:
            raise ValueError(f"Unsupported log level: {level_name}")

    return LogSettings(
        level_name=resolved_level_name,
        level_value=_LOG_LEVEL_VALUES[resolved_level_name],
        verbosity=verbosity,
    )


def configure_logging(settings: LogSettings) -> None:
    root_logger = logging.getLogger("nifc")
    root_logger.handlers.clear()
    root_logger.filters.clear()
    root_logger.setLevel(logging.DEBUG)
    root_logger.propagate = False

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(settings.level_value)
    handler.addFilter(_VerbosityFilter(settings.verbosity))
    handler.setFormatter(_CompilerLogFormatter())
    root_logger.addHandler(handler)


def get_logger(name: str | None = None) -> CompilerLogger:
    logger_name = "nifc" if not name else f"nifc.{name}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)
    return CompilerLogger(logger, {})