"""Backend target APIs."""

from compiler.backend.targets.api import (
	BackendEmitResult,
	BackendTarget,
	BackendTargetInput,
	BackendTargetLoweringError,
	BackendTargetOptions,
)
from compiler.backend.targets.registry import (
	BackendTargetRegistration,
	backend_target_registration,
	default_checked_backend_target_name,
	native_runtime_backend_name,
	registered_backend_target_names,
	registered_backend_targets,
	resolve_backend_target,
)

__all__ = [
	"BackendEmitResult",
	"BackendTarget",
	"BackendTargetInput",
	"BackendTargetLoweringError",
	"BackendTargetOptions",
	"BackendTargetRegistration",
	"backend_target_registration",
	"default_checked_backend_target_name",
	"native_runtime_backend_name",
	"registered_backend_target_names",
	"registered_backend_targets",
	"resolve_backend_target",
]
