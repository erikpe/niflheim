"""Legacy tree-walk assembly backend support.

The checked compiler path lowers through ``compiler.backend`` and no longer
depends on the tree-walk assembly pipeline in this package. The legacy emitter
stack remains for measurement scripts, migration-reference tests, and a small
set of shared helper modules such as ``abi.runtime``, ``runtime_calls``,
``symbols``, and ``types`` that are still consumed by the backend IR path.
"""

LEGACY_TREEWALK_BACKEND_MODULES = frozenset(
	{
		"compiler.codegen.emitter_expr",
		"compiler.codegen.emitter_fn",
		"compiler.codegen.emitter_module",
		"compiler.codegen.emitter_stmt",
		"compiler.codegen.generator",
		"compiler.codegen.layout",
		"compiler.codegen.program_generator",
		"compiler.codegen.root_liveness",
		"compiler.codegen.root_slot_plan",
		"compiler.codegen.walk",
	}
)

__all__ = ["LEGACY_TREEWALK_BACKEND_MODULES"]
