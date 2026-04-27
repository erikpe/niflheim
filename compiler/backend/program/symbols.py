from __future__ import annotations

from dataclasses import dataclass

from compiler.backend.ir import BackendDataId, BackendProgram
from compiler.backend.ir._ordering import class_id_sort_key, data_blob_sort_key, interface_id_sort_key
from compiler.semantic.symbols import ClassId, ConstructorId, FunctionId, InterfaceId, MethodId


def _mangle_fragment(name: str) -> str:
    return name.replace(".", "_").replace(":", "_").replace("[", "_").replace("]", "_")


def qualified_class_name(class_id: ClassId) -> str:
    return f"{'.'.join(class_id.module_path)}::{class_id.name}"


def qualified_interface_name(interface_id: InterfaceId) -> str:
    return f"{'.'.join(interface_id.module_path)}::{interface_id.name}"


def mangle_function_symbol(module_path: tuple[str, ...], name: str) -> str:
    return f"__nif_fn_{_mangle_fragment('.'.join(module_path))}__{_mangle_fragment(name)}"


def mangle_method_symbol(method_id: MethodId) -> str:
    return f"__nif_method_{_mangle_fragment(qualified_class_name(ClassId(method_id.module_path, method_id.class_name)))}_{_mangle_fragment(method_id.name)}"


def mangle_constructor_symbol(constructor_id: ConstructorId) -> str:
    base = f"__nif_ctor_{_mangle_fragment(qualified_class_name(ClassId(constructor_id.module_path, constructor_id.class_name)))}"
    if constructor_id.ordinal == 0:
        return base
    return f"{base}__{constructor_id.ordinal}"


def mangle_constructor_init_symbol(constructor_id: ConstructorId) -> str:
    base = f"__nif_ctor_init_{_mangle_fragment(qualified_class_name(ClassId(constructor_id.module_path, constructor_id.class_name)))}"
    if constructor_id.ordinal == 0:
        return base
    return f"{base}__{constructor_id.ordinal}"


def mangle_type_symbol(type_name: str) -> str:
    return f"__nif_type_{_mangle_fragment(type_name)}"


def mangle_type_name_symbol(type_name: str) -> str:
    return f"__nif_type_name_{_mangle_fragment(type_name)}"


def mangle_type_pointer_offsets_symbol(type_name: str) -> str:
    return f"{mangle_type_name_symbol(type_name)}__ptr_offsets"


def mangle_class_vtable_symbol(class_id: ClassId) -> str:
    return f"__nif_vtable_{_mangle_fragment(qualified_class_name(class_id))}"


def mangle_interface_symbol(interface_id: InterfaceId) -> str:
    return f"__nif_interface_{_mangle_fragment(qualified_interface_name(interface_id))}"


def mangle_interface_name_symbol(interface_id: InterfaceId) -> str:
    return f"__nif_interface_name_{_mangle_fragment(qualified_interface_name(interface_id))}"


def mangle_interface_method_table_symbol(class_id: ClassId, interface_id: InterfaceId) -> str:
    return (
        f"__nif_interface_methods_{_mangle_fragment(qualified_class_name(class_id))}"
        f"__{_mangle_fragment(qualified_interface_name(interface_id))}"
    )


def mangle_class_interface_tables_symbol(class_id: ClassId) -> str:
    return f"__nif_interface_tables_{_mangle_fragment(qualified_class_name(class_id))}"


def string_literal_symbol(data_id: BackendDataId | int) -> str:
    ordinal = data_id if isinstance(data_id, int) else data_id.ordinal
    return f"__nif_str_lit_{ordinal}"


def epilogue_label(fn_name: str) -> str:
    return f".L{fn_name}_epilogue"


@dataclass(frozen=True, slots=True)
class BackendCallableSymbol:
    callable_id: FunctionId | MethodId | ConstructorId
    direct_call_symbol: str
    emitted_label: str | None
    alias_labels: tuple[str, ...]
    global_label: str | None
    constructor_init_symbol: str | None = None


@dataclass(frozen=True, slots=True)
class BackendClassSymbols:
    class_id: ClassId
    qualified_type_name: str
    type_symbol: str
    type_name_symbol: str
    pointer_offsets_symbol: str
    interface_tables_symbol: str
    class_vtable_symbol: str


@dataclass(frozen=True, slots=True)
class BackendInterfaceSymbols:
    interface_id: InterfaceId
    qualified_type_name: str
    descriptor_symbol: str
    name_symbol: str


@dataclass(frozen=True, slots=True)
class BackendDataBlobSymbols:
    data_id: BackendDataId
    symbol: str


@dataclass(frozen=True, slots=True)
class BackendProgramSymbolTable:
    callable_symbols_by_id: dict[FunctionId | MethodId | ConstructorId, BackendCallableSymbol]
    class_symbols_by_id: dict[ClassId, BackendClassSymbols]
    interface_symbols_by_id: dict[InterfaceId, BackendInterfaceSymbols]
    data_blob_symbols_by_id: dict[BackendDataId, BackendDataBlobSymbols]

    def callable(self, callable_id: FunctionId | MethodId | ConstructorId) -> BackendCallableSymbol:
        return self.callable_symbols_by_id[callable_id]

    def class_symbols(self, class_id: ClassId) -> BackendClassSymbols:
        return self.class_symbols_by_id[class_id]

    def interface_symbols(self, interface_id: InterfaceId) -> BackendInterfaceSymbols:
        return self.interface_symbols_by_id[interface_id]

    def data_blob_symbols(self, data_id: BackendDataId) -> BackendDataBlobSymbols:
        return self.data_blob_symbols_by_id[data_id]


def build_backend_program_symbol_table(program: BackendProgram) -> BackendProgramSymbolTable:
    emitted_symbols: dict[str, str] = {}

    def register_symbol(symbol: str, owner: str) -> str:
        existing_owner = emitted_symbols.get(symbol)
        if existing_owner is not None and existing_owner != owner:
            raise ValueError(
                f"Conflicting backend program symbol '{symbol}' for {owner} (already used by {existing_owner})"
            )
        emitted_symbols[symbol] = owner
        return symbol

    callable_symbols_by_id: dict[FunctionId | MethodId | ConstructorId, BackendCallableSymbol] = {}
    for callable_decl in program.callables:
        callable_id = callable_decl.callable_id
        owner = _format_callable_owner(callable_id)
        internal_symbol = _callable_internal_symbol(callable_id)
        if callable_decl.is_extern:
            if not isinstance(callable_id, FunctionId):
                raise ValueError(
                    f"Extern backend callable '{owner}' must be a plain function for stable symbol emission"
                )
            direct_call_symbol = register_symbol(callable_id.name, f"extern {owner}")
            callable_symbols_by_id[callable_id] = BackendCallableSymbol(
                callable_id=callable_id,
                direct_call_symbol=direct_call_symbol,
                emitted_label=None,
                alias_labels=(),
                global_label=None,
                constructor_init_symbol=None,
            )
            continue

        register_symbol(internal_symbol, owner)
        if callable_id == program.entry_callable_id and isinstance(callable_id, FunctionId) and callable_id.name == "main":
            register_symbol("main", f"entrypoint {owner}")
            callable_symbols_by_id[callable_id] = BackendCallableSymbol(
                callable_id=callable_id,
                direct_call_symbol=internal_symbol,
                emitted_label="main",
                alias_labels=(internal_symbol,),
                global_label="main",
                constructor_init_symbol=None,
            )
            continue

        global_label = internal_symbol if callable_decl.is_export else None
        constructor_init_symbol = mangle_constructor_init_symbol(callable_id) if isinstance(callable_id, ConstructorId) else None
        callable_symbols_by_id[callable_id] = BackendCallableSymbol(
            callable_id=callable_id,
            direct_call_symbol=internal_symbol,
            emitted_label=internal_symbol,
            alias_labels=(),
            global_label=global_label,
            constructor_init_symbol=constructor_init_symbol,
        )

    class_symbols_by_id: dict[ClassId, BackendClassSymbols] = {}
    for class_decl in sorted(program.classes, key=lambda decl: class_id_sort_key(decl.class_id)):
        class_id = class_decl.class_id
        qualified_type_name = qualified_class_name(class_id)
        class_symbols = BackendClassSymbols(
            class_id=class_id,
            qualified_type_name=qualified_type_name,
            type_symbol=register_symbol(mangle_type_symbol(qualified_type_name), f"type {qualified_type_name}"),
            type_name_symbol=register_symbol(mangle_type_name_symbol(qualified_type_name), f"type-name {qualified_type_name}"),
            pointer_offsets_symbol=register_symbol(
                mangle_type_pointer_offsets_symbol(qualified_type_name),
                f"pointer-offsets {qualified_type_name}",
            ),
            interface_tables_symbol=register_symbol(
                mangle_class_interface_tables_symbol(class_id),
                f"interface-tables {qualified_type_name}",
            ),
            class_vtable_symbol=register_symbol(
                mangle_class_vtable_symbol(class_id),
                f"class-vtable {qualified_type_name}",
            ),
        )
        class_symbols_by_id[class_id] = class_symbols

    interface_symbols_by_id: dict[InterfaceId, BackendInterfaceSymbols] = {}
    for interface_decl in sorted(program.interfaces, key=lambda decl: interface_id_sort_key(decl.interface_id)):
        interface_id = interface_decl.interface_id
        qualified_type_name = qualified_interface_name(interface_id)
        interface_symbols_by_id[interface_id] = BackendInterfaceSymbols(
            interface_id=interface_id,
            qualified_type_name=qualified_type_name,
            descriptor_symbol=register_symbol(
                mangle_interface_symbol(interface_id),
                f"interface-descriptor {qualified_type_name}",
            ),
            name_symbol=register_symbol(
                mangle_interface_name_symbol(interface_id),
                f"interface-name {qualified_type_name}",
            ),
        )

    data_blob_symbols_by_id: dict[BackendDataId, BackendDataBlobSymbols] = {}
    for blob in sorted(program.data_blobs, key=data_blob_sort_key):
        data_blob_symbols_by_id[blob.data_id] = BackendDataBlobSymbols(
            data_id=blob.data_id,
            symbol=register_symbol(string_literal_symbol(blob.data_id), f"data-blob d{blob.data_id.ordinal}"),
        )

    return BackendProgramSymbolTable(
        callable_symbols_by_id=callable_symbols_by_id,
        class_symbols_by_id=class_symbols_by_id,
        interface_symbols_by_id=interface_symbols_by_id,
        data_blob_symbols_by_id=data_blob_symbols_by_id,
    )


def _callable_internal_symbol(callable_id: FunctionId | MethodId | ConstructorId) -> str:
    if isinstance(callable_id, FunctionId):
        return mangle_function_symbol(callable_id.module_path, callable_id.name)
    if isinstance(callable_id, MethodId):
        return mangle_method_symbol(callable_id)
    if isinstance(callable_id, ConstructorId):
        return mangle_constructor_symbol(callable_id)
    raise TypeError(f"Unsupported backend callable ID '{callable_id!r}'")


def _format_callable_owner(callable_id: FunctionId | MethodId | ConstructorId) -> str:
    if isinstance(callable_id, FunctionId):
        return f"function {'.'.join(callable_id.module_path)}::{callable_id.name}"
    if isinstance(callable_id, MethodId):
        return f"method {qualified_class_name(ClassId(callable_id.module_path, callable_id.class_name))}.{callable_id.name}"
    return f"constructor {qualified_class_name(ClassId(callable_id.module_path, callable_id.class_name))}#{callable_id.ordinal}"


__all__ = [
    "BackendCallableSymbol",
    "BackendClassSymbols",
    "BackendDataBlobSymbols",
    "BackendInterfaceSymbols",
    "BackendProgramSymbolTable",
    "build_backend_program_symbol_table",
    "epilogue_label",
    "mangle_class_interface_tables_symbol",
    "mangle_class_vtable_symbol",
    "mangle_constructor_init_symbol",
    "mangle_constructor_symbol",
    "mangle_function_symbol",
    "mangle_interface_method_table_symbol",
    "mangle_interface_name_symbol",
    "mangle_interface_symbol",
    "mangle_method_symbol",
    "mangle_type_name_symbol",
    "mangle_type_pointer_offsets_symbol",
    "mangle_type_symbol",
    "qualified_class_name",
    "qualified_interface_name",
    "string_literal_symbol",
]