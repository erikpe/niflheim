import pytest

from compiler.frontend.lexer import lex
from compiler.frontend.parser import parse
from compiler.common.span import SourcePos, SourceSpan
from compiler.resolver import resolve_program
from compiler.typecheck.context import TypeCheckContext
from compiler.typecheck.declarations import collect_module_declarations
from compiler.typecheck.model import TypeCheckError
from compiler.typecheck.module_lookup import resolve_imported_interface_name
from tests.compiler.typecheck.helpers import parse_and_typecheck


def _collect_declarations(source: str) -> TypeCheckContext:
    module = parse(lex(source))
    ctx = TypeCheckContext(module_ast=module)
    collect_module_declarations(ctx)
    return ctx


def test_typecheck_rejects_field_method_name_collision() -> None:
    source = """
class Bad {
    value: i64;

    fn value() -> i64 {
        return 1;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate member 'value'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_class_and_function_declaration_name() -> None:
    source = """
class Counter {
    value: i64;
}

fn Counter() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate declaration 'Counter'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_field_names() -> None:
    source = """
class Counter {
    value: i64;
    value: bool;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate field 'value'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_method_names() -> None:
    source = """
class Counter {
    fn tick() -> unit {
        return;
    }

    fn tick() -> unit {
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate method 'tick'"):
        parse_and_typecheck(source)


def test_typecheck_allows_public_implicit_constructor_for_public_final_fields() -> None:
    source = """
class BoxI64 {
    final value: i64;
}

fn main() -> unit {
    var b: BoxI64 = BoxI64(7);
    var x: i64 = b.value;
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_constructor_omits_default_initialized_fields_from_params() -> None:
    source = """
class Counter {
    value: i64;
    cached: bool = false;
}

fn main() -> unit {
    var c: Counter = Counter(7);
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_collects_compatibility_constructor_when_class_declares_none() -> None:
    source = """
class Counter {
    value: i64;
    cached: bool = false;
}

fn main() -> unit {
    return;
}
"""
    ctx = _collect_declarations(source)

    counter_info = ctx.classes["Counter"]

    assert len(counter_info.constructors) == 1
    assert counter_info.constructors[0].ordinal == 0
    assert counter_info.constructors[0].param_names == ["value"]
    assert [param.name for param in counter_info.constructors[0].params] == ["i64"]
    assert counter_info.constructors[0].is_private is False


def test_typecheck_collects_explicit_constructors_without_compatibility_constructor() -> None:
    source = """
class Counter {
    private value: i64;

    constructor(value: i64) {
        return;
    }

    private constructor() {
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    ctx = _collect_declarations(source)

    counter_info = ctx.classes["Counter"]

    assert len(counter_info.constructors) == 2
    assert [constructor.ordinal for constructor in counter_info.constructors] == [0, 1]
    assert [constructor.param_names for constructor in counter_info.constructors] == [["value"], []]
    assert [[param.name for param in constructor.params] for constructor in counter_info.constructors] == [["i64"], []]
    assert [constructor.is_private for constructor in counter_info.constructors] == [False, True]


def test_typecheck_collects_chained_compatibility_constructor_for_subclass() -> None:
    source = """
class Base {
    base: i64;
}

class Derived extends Base {
    extra: i64;
    cached: bool = false;
}

fn main() -> unit {
    return;
}
"""
    ctx = _collect_declarations(source)

    derived_info = ctx.classes["Derived"]

    assert len(derived_info.constructors) == 1
    assert derived_info.constructors[0].param_names == ["base", "extra"]
    assert [param.name for param in derived_info.constructors[0].params] == ["i64", "i64"]


def test_typecheck_collects_superclass_name_for_local_base() -> None:
    source = """
class Base {
    value: i64;
}

class Derived extends Base {
    extra: i64;
}

fn main() -> unit {
    return;
}
"""
    ctx = _collect_declarations(source)

    assert ctx.classes["Base"].superclass_name is None
    assert ctx.classes["Derived"].superclass_name == "Base"


def test_typecheck_collects_superclass_name_when_base_declared_later() -> None:
    source = """
class Derived extends Base {
    extra: i64;
}

class Base {
    value: i64;
}

fn main() -> unit {
    return;
}
"""
    ctx = _collect_declarations(source)

    assert ctx.classes["Derived"].superclass_name == "Base"


def test_typecheck_collects_effective_inherited_members_and_interfaces() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Base implements Hashable {
    value: i64 = 1;

    fn read() -> i64 {
        return __self.value;
    }

    fn hash_code() -> u64 {
        return 1u;
    }
}

class Derived extends Base {
    extra: i64;
}

fn main() -> unit {
    return;
}
"""
    ctx = _collect_declarations(source)

    derived_info = ctx.classes["Derived"]

    assert derived_info.declared_field_order == ["extra"]
    assert derived_info.field_order == ["value", "extra"]
    assert list(derived_info.fields) == ["value", "extra"]
    assert derived_info.field_members["value"].owner_class_name == "Base"
    assert derived_info.field_members["extra"].owner_class_name == "Derived"
    assert derived_info.method_members["read"].owner_class_name == "Base"
    assert derived_info.implemented_interfaces == {"Hashable"}


def test_typecheck_rejects_field_redeclaration_of_inherited_field() -> None:
    source = """
class Base {
    value: i64;
}

class Derived extends Base {
    value: i64;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate field 'value'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_method_redeclaration_of_inherited_method() -> None:
    source = """
class Base {
    fn read() -> i64 {
        return 1;
    }
}

class Derived extends Base {
    fn read() -> i64 {
        return 2;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate method 'read'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_unknown_superclass() -> None:
    source = """
class Derived extends Missing {
    value: i64;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Unknown superclass 'Missing'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_class_superclass() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Derived extends Hashable {
    value: i64;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Superclass 'Hashable' is not a class"):
        parse_and_typecheck(source)


def test_typecheck_rejects_self_inheritance() -> None:
    source = """
class Loop extends Loop {
    value: i64;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Class 'Loop' cannot extend itself"):
        parse_and_typecheck(source)


def test_typecheck_rejects_inheritance_cycle() -> None:
    source = """
class Alpha extends Beta {
    value: i64;
}

class Beta extends Alpha {
    value: i64;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Inheritance cycle detected"):
        parse_and_typecheck(source)


def test_typecheck_rejects_constructor_call_including_defaulted_field_argument() -> None:
    source = """
class Counter {
    value: i64;
    cached: bool = false;
}

fn main() -> unit {
    var c: Counter = Counter(7, true);
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Expected 1 arguments, got 2"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_explicit_constructor_signatures() -> None:
    source = """
class Counter {
    constructor(value: i64) {
        return;
    }

    constructor(other: i64) {
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate constructor signature"):
        parse_and_typecheck(source)


def test_typecheck_rejects_non_constant_class_field_initializer() -> None:
    source = """
fn seed() -> i64 {
    return 1;
}

class Counter {
    value: i64 = seed();
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Class field initializer must be a constant expression in MVP"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_interface_declaration() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

interface Hashable {
    fn equals(other: Obj) -> bool;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate declaration 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_duplicate_interface_method_names() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
    fn hash_code() -> u64;
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="Duplicate interface method 'hash_code'"):
        parse_and_typecheck(source)


def test_typecheck_collects_interfaces_alongside_classes_and_functions() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Counter {
    value: i64;
}

fn helper() -> unit {
    return;
}

fn main() -> unit {
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_collects_imported_interface_declarations_across_modules(tmp_path) -> None:
    util_path = tmp_path / "util.nif"
    util_path.write_text(
        """
export interface Hashable {
    fn hash_code() -> u64;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    main_path = tmp_path / "main.nif"
    main_path.write_text(
        """
import util;

fn main() -> unit {
    return;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    program = resolve_program(main_path, project_root=tmp_path)
    module_function_sigs = {module_path: {} for module_path in program.modules}
    module_class_infos = {module_path: {} for module_path in program.modules}
    module_interface_infos = {module_path: {} for module_path in program.modules}
    contexts: dict[tuple[str, ...], TypeCheckContext] = {}

    for module_path, module_info in program.modules.items():
        contexts[module_path] = TypeCheckContext(
            module_ast=module_info.ast,
            module_path=module_path,
            modules=program.modules,
            module_function_sigs=module_function_sigs,
            module_class_infos=module_class_infos,
            module_interface_infos=module_interface_infos,
            functions=module_function_sigs[module_path],
            classes=module_class_infos[module_path],
            interfaces=module_interface_infos[module_path],
        )

    for ctx in contexts.values():
        collect_module_declarations(ctx)

    main_ctx = contexts[("main",)]
    util_ctx = contexts[("util",)]
    span = SourceSpan(start=SourcePos(path="<test>", offset=0, line=1, column=1), end=SourcePos(path="<test>", offset=0, line=1, column=1))

    assert "Hashable" in util_ctx.interfaces
    assert resolve_imported_interface_name(main_ctx, "Hashable", span) == "util::Hashable"


def test_typecheck_rejects_missing_interface_method() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="missing method 'hash_code' required by interface 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_wrong_interface_method_return_type() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> i64 {
        return 1;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="returns 'i64' but interface 'Hashable.hash_code' requires 'u64'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_wrong_interface_method_parameter_type() -> None:
    source = """
interface Equalable {
    fn equals(other: Obj) -> bool;
}

class Key implements Equalable {
    fn equals(other: i64) -> bool {
        return false;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="parameter 1 has type 'i64' but interface 'Equalable.equals' requires 'Obj'"):
        parse_and_typecheck(source)


def test_typecheck_allows_extra_methods_on_interface_implementer() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    fn hash_code() -> u64 {
        return 1u;
    }

    fn debug() -> unit {
        return;
    }
}

fn main() -> unit {
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_checks_multiple_interfaces_together() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

interface Equalable {
    fn equals(other: Obj) -> bool;
}

class Key implements Hashable, Equalable {
    fn hash_code() -> u64 {
        return 1u;
    }

    fn equals(other: Obj) -> bool {
        return false;
    }
}

fn main() -> unit {
    return;
}
"""
    parse_and_typecheck(source)


def test_typecheck_rejects_private_method_as_interface_implementation() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    private fn hash_code() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="is private and cannot satisfy interface 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_rejects_static_method_as_interface_implementation() -> None:
    source = """
interface Hashable {
    fn hash_code() -> u64;
}

class Key implements Hashable {
    static fn hash_code() -> u64 {
        return 1u;
    }
}

fn main() -> unit {
    return;
}
"""
    with pytest.raises(TypeCheckError, match="is static and cannot satisfy interface 'Hashable'"):
        parse_and_typecheck(source)


def test_typecheck_allows_imported_interface_in_implements_list(tmp_path) -> None:
    util_path = tmp_path / "util.nif"
    util_path.write_text(
        """
export class Token {
    value: i64;
}

export interface TokenFactory {
    fn make() -> Token;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )
    main_path = tmp_path / "main.nif"
    main_path.write_text(
        """
import util;

class Factory implements TokenFactory {
    fn make() -> util.Token {
        return util.Token(7);
    }
}

fn main() -> unit {
    return;
}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    program = resolve_program(main_path, project_root=tmp_path)
    from compiler.typecheck.api import typecheck_program

    typecheck_program(program)
