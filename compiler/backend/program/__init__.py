"""Backend-owned program-global context for target backends."""

from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import BackendProgram
from compiler.backend.program.class_hierarchy import (
	BackendClassHierarchyIndex,
	EffectiveFieldSlot,
	EffectiveVirtualMethodSlot,
)
from compiler.backend.program.metadata import (
	BackendDataBlobMetadataRecord,
	BackendProgramMetadata,
	ClassMetadataRecord,
	ExtraRuntimeTypeRecord,
	InterfaceMetadataRecord,
	InterfaceMethodTableMetadataRecord,
	build_backend_program_metadata,
)
from compiler.backend.program.symbols import (
	BackendCallableSymbol,
	BackendClassSymbols,
	BackendDataBlobSymbols,
	BackendInterfaceSymbols,
	BackendProgramSymbolTable,
	build_backend_program_symbol_table,
)


@dataclass(frozen=True, slots=True)
class BackendProgramContext:
	"""Deterministic whole-program metadata consumed by concrete targets."""

	symbols: BackendProgramSymbolTable
	class_hierarchy: BackendClassHierarchyIndex
	metadata: BackendProgramMetadata


def build_backend_program_context(program: BackendProgram) -> BackendProgramContext:
	symbols = build_backend_program_symbol_table(program)
	class_hierarchy = BackendClassHierarchyIndex(program)
	metadata = build_backend_program_metadata(
		program,
		symbols=symbols,
		class_hierarchy=class_hierarchy,
	)
	return BackendProgramContext(
		symbols=symbols,
		class_hierarchy=class_hierarchy,
		metadata=metadata,
	)


__all__ = [
	"BackendCallableSymbol",
	"BackendClassHierarchyIndex",
	"BackendClassSymbols",
	"BackendDataBlobMetadataRecord",
	"BackendDataBlobSymbols",
	"BackendInterfaceSymbols",
	"BackendProgramContext",
	"BackendProgramMetadata",
	"BackendProgramSymbolTable",
	"ClassMetadataRecord",
	"EffectiveFieldSlot",
	"EffectiveVirtualMethodSlot",
	"ExtraRuntimeTypeRecord",
	"InterfaceMetadataRecord",
	"InterfaceMethodTableMetadataRecord",
	"build_backend_program_context",
	"build_backend_program_metadata",
	"build_backend_program_symbol_table",
]
