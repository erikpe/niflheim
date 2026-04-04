from __future__ import annotations

from pathlib import Path

from compiler.common.collection_protocols import ArrayRuntimeKind, CollectionOpKind, collection_method_name
from compiler.semantic.display import (
    semantic_bound_member_receiver_display_name,
    semantic_call_target_display_name,
    semantic_local_display_name,
    semantic_local_type_display_name,
    semantic_type_display_name_relative,
)
from compiler.semantic.ir import *
from compiler.semantic.linker import link_semantic_program
from compiler.semantic.lowered_ir import (
    LoweredSemanticClass,
    LoweredSemanticBlock,
    LoweredSemanticField,
    LoweredSemanticForIn,
    LoweredSemanticForInStrategy,
    LoweredSemanticFunction,
    LoweredSemanticIf,
    LoweredSemanticMethod,
    LoweredSemanticWhile,
)
from compiler.semantic.lowering.executable import lower_linked_semantic_program
from compiler.semantic.operations import (
    BinaryOpFlavor,
    BinaryOpKind,
    CastSemanticsKind,
    TypeTestSemanticsKind,
    UnaryOpFlavor,
    UnaryOpKind,
)
from compiler.resolver import resolve_program
from compiler.semantic.lowering.orchestration import lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def _assert_method_dispatch_matches_op(dispatch: MethodDispatch, *, class_name: str, op_kind: CollectionOpKind) -> None:
    assert dispatch.method_id.class_name == class_name
    assert dispatch.method_id.name == collection_method_name(op_kind)


def _assert_runtime_dispatch_matches_op(
    dispatch: RuntimeDispatch, *, op_kind: CollectionOpKind, runtime_kind: ArrayRuntimeKind | None = None
) -> None:
    assert dispatch.operation is op_kind
    assert dispatch.runtime_kind is runtime_kind


def _assert_call_target(expr: SemanticExpr, expected_target_type: type[object]):
    assert isinstance(expr, CallExprS)
    assert isinstance(expr.target, expected_target_type)
    return expr.target


def test_lower_program_builds_semantic_declarations_and_ids(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Counter {
            value: i64;

            fn get() -> i64 {
                return 1;
            }
        }

        export fn twice(x: i64) -> i64 {
            return x + x;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)

    util_module = semantic.modules[("util",)]
    assert util_module.classes[0].class_id.module_path == ("util",)
    assert util_module.classes[0].class_id.name == "Counter"
    assert util_module.classes[0].fields[0].type_ref.canonical_name == "i64"
    assert util_module.classes[0].methods[0].method_id.class_name == "Counter"
    assert util_module.classes[0].methods[0].return_type_ref.canonical_name == "i64"
    assert util_module.functions[0].function_id.module_path == ("util",)
    assert util_module.functions[0].params[0].type_ref.canonical_name == "i64"
    assert util_module.functions[0].return_type_ref.canonical_name == "i64"


def test_lower_program_lowers_explicit_and_compatibility_constructors(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class ExplicitBox {
            value: i64;

            constructor(value: i64) {
                var tmp: i64 = value;
                __self.value = tmp;
                return;
            }
        }

        class CompatBox {
            value: i64;
        }

        fn main() -> i64 {
            var a: ExplicitBox = ExplicitBox(7);
            var b: CompatBox = CompatBox(9);
            return 0;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    explicit_cls = next(cls for cls in semantic.modules[("main",)].classes if cls.class_id.name == "ExplicitBox")
    compat_cls = next(cls for cls in semantic.modules[("main",)].classes if cls.class_id.name == "CompatBox")

    assert len(explicit_cls.constructors) == 1
    assert explicit_cls.constructors[0].constructor_id == ConstructorId(
        module_path=("main",), class_name="ExplicitBox", ordinal=0
    )
    assert explicit_cls.constructors[0].body is not None
    constructor_local_infos = sorted(
        explicit_cls.constructors[0].local_info_by_id.values(),
        key=lambda local_info: local_info.local_id.ordinal,
    )
    assert [local_info.binding_kind for local_info in constructor_local_infos] == ["receiver", "param", "local"]
    assert all(local_info.owner_id == explicit_cls.constructors[0].constructor_id for local_info in constructor_local_infos)

    assert len(compat_cls.constructors) == 1
    assert compat_cls.constructors[0].constructor_id == ConstructorId(
        module_path=("main",), class_name="CompatBox", ordinal=0
    )
    assert compat_cls.constructors[0].body is None


def test_lower_program_lowers_super_constructor_init_calls_and_chained_compatibility_metadata(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            value: i64;

            constructor(value: i64) {
                __self.value = value;
                return;
            }
        }

        class Derived extends Base {
            extra: i64;

            constructor(value: i64, extra: i64) {
                super(value);
                __self.extra = extra;
                return;
            }
        }

        class CompatLeaf extends Derived {
            leaf: i64;
        }

        fn main() -> i64 {
            var leaf: CompatLeaf = CompatLeaf(1, 2, 3);
            return leaf.leaf;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    module = semantic.modules[("main",)]
    derived_cls = next(cls for cls in module.classes if cls.class_id.name == "Derived")
    compat_leaf_cls = next(cls for cls in module.classes if cls.class_id.name == "CompatLeaf")

    first_stmt = derived_cls.constructors[0].body.statements[0]
    assert isinstance(first_stmt, SemanticExprStmt)
    super_target = _assert_call_target(first_stmt.expr, ConstructorInitCallTarget)
    assert super_target.constructor_id == ConstructorId(module_path=("main",), class_name="Base", ordinal=0)

    compat_ctor = compat_leaf_cls.constructors[0]
    assert compat_ctor.body is None
    assert compat_ctor.super_constructor_id == ConstructorId(module_path=("main",), class_name="Derived", ordinal=0)
    compat_local_infos = sorted(compat_ctor.local_info_by_id.values(), key=lambda local_info: local_info.local_id.ordinal)
    assert [local_info.binding_kind for local_info in compat_local_infos] == ["receiver", "param", "param", "param"]


def test_lower_program_preserves_statement_and_field_structure(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn sum(box: Box, flag: bool) -> i64 {
            var total: i64 = 0;
            if flag {
                box.value = box.value + 1;
            }
            while total < 3 {
                total = total + 1;
            }
            return box.value;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    function = semantic.modules[("main",)].functions[0]
    assert function.params[0].type_ref.canonical_name == "main::Box"

    assert isinstance(function.body.statements[0], SemanticVarDecl)
    assert function.body.statements[0].local_id.owner_id == function.function_id
    assert local_type_name_for_owner(function, function.body.statements[0].local_id) == "i64"

    if_stmt = function.body.statements[1]
    assert isinstance(if_stmt, SemanticIf)
    assign_stmt = if_stmt.then_block.statements[0]
    assert isinstance(assign_stmt, SemanticAssign)
    assert isinstance(assign_stmt.target, FieldLValue)
    assert assign_stmt.target.field_name == "value"
    assert assign_stmt.target.owner_class_id == ClassId(module_path=("main",), name="Box")
    assert assign_stmt.target.type_ref.canonical_name == "i64"
    assert not hasattr(assign_stmt.target, "type_name")
    assert isinstance(assign_stmt.value, BinaryExprS)
    assert isinstance(assign_stmt.value.left, FieldReadExpr)
    assert assign_stmt.value.left.owner_class_id == ClassId(module_path=("main",), name="Box")
    assert assign_stmt.value.left.type_ref.canonical_name == "i64"
    assert expression_type_name(assign_stmt.value.left) == "i64"
    assert not hasattr(assign_stmt.value.left, "type_name")

    while_stmt = function.body.statements[2]
    assert isinstance(while_stmt, SemanticWhile)
    while_assign = while_stmt.body.statements[0]
    assert isinstance(while_assign, SemanticAssign)
    assert isinstance(while_assign.target, LocalLValue)
    assert while_assign.target.local_id == function.body.statements[0].local_id
    assert local_display_name_for_owner(function, while_assign.target.local_id) == "total"
    assert local_type_name_for_owner(function, while_assign.target.local_id) == "i64"
    assert isinstance(while_assign.value, BinaryExprS)
    assert isinstance(while_assign.value.left, LocalRefExpr)
    assert while_assign.value.left.local_id == function.body.statements[0].local_id

    return_stmt = function.body.statements[3]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, FieldReadExpr)
    assert return_stmt.value.owner_class_id == ClassId(module_path=("main",), name="Box")
    assert return_stmt.value.type_ref.canonical_name == "i64"
    assert expression_type_name(return_stmt.value) == "i64"
    assert not hasattr(return_stmt.value, "type_name")


def test_lower_program_builds_typed_semantic_constants_for_literals(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> unit {
            var a: i64 = 1;
            var b: u64 = 2u;
            var c: u8 = 'q';
            var d: bool = false;
            var e: double = 1.5;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[0].initializer, LiteralExprS)
    assert isinstance(statements[0].initializer.constant, IntConstant)
    assert statements[0].initializer.type_ref.canonical_name == "i64"
    assert not hasattr(statements[0].initializer.constant, "type_name")
    assert statements[0].initializer.constant.value == 1

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[1].initializer, LiteralExprS)
    assert isinstance(statements[1].initializer.constant, IntConstant)
    assert statements[1].initializer.type_ref.canonical_name == "u64"
    assert not hasattr(statements[1].initializer.constant, "type_name")
    assert statements[1].initializer.constant.value == 2

    assert isinstance(statements[2], SemanticVarDecl)
    assert isinstance(statements[2].initializer, LiteralExprS)
    assert isinstance(statements[2].initializer.constant, CharConstant)
    assert statements[2].initializer.type_ref.canonical_name == "u8"
    assert not hasattr(statements[2].initializer.constant, "type_name")
    assert statements[2].initializer.constant.value == ord("q")

    assert isinstance(statements[3], SemanticVarDecl)
    assert isinstance(statements[3].initializer, LiteralExprS)
    assert isinstance(statements[3].initializer.constant, BoolConstant)
    assert statements[3].initializer.type_ref.canonical_name == "bool"
    assert not hasattr(statements[3].initializer.constant, "type_name")
    assert statements[3].initializer.constant.value is False

    assert isinstance(statements[4], SemanticVarDecl)
    assert isinstance(statements[4].initializer, LiteralExprS)
    assert isinstance(statements[4].initializer.constant, FloatConstant)
    assert statements[4].initializer.type_ref.canonical_name == "double"
    assert not hasattr(statements[4].initializer.constant, "type_name")
    assert statements[4].initializer.constant.value == 1.5


def test_lower_program_tracks_superclass_ids_and_inherited_member_owners(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
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
            extra: i64 = 2;
        }

        fn use(value: Derived) -> i64 {
            var read_value: i64 = value.read();
            return value.value;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    main_module = semantic.modules[("main",)]
    classes_by_name = {cls.class_id.name: cls for cls in main_module.classes}
    derived_class = classes_by_name["Derived"]

    assert derived_class.superclass_id == ClassId(module_path=("main",), name="Base")
    assert derived_class.methods == []
    assert derived_class.implemented_interfaces == [InterfaceId(module_path=("main",), name="Hashable")]

    use_fn = next(fn for fn in main_module.functions if fn.function_id.name == "use")
    read_decl = use_fn.body.statements[0]
    assert isinstance(read_decl, SemanticVarDecl)
    read_call = read_decl.initializer
    assert isinstance(read_call, CallExprS)
    assert isinstance(read_call.target, VirtualMethodCallTarget)
    assert read_call.target.slot_owner_class_id == ClassId(module_path=("main",), name="Base")
    assert read_call.target.slot_method_name == "read"
    assert read_call.target.selected_method_id == MethodId(module_path=("main",), class_name="Base", name="read")

    return_stmt = use_fn.body.statements[1]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, FieldReadExpr)
    assert return_stmt.value.owner_class_id == ClassId(module_path=("main",), name="Base")

    lowered = lower_linked_semantic_program(link_semantic_program(semantic))
    lowered_derived = next(cls for cls in lowered.classes if cls.class_id.name == "Derived")
    assert lowered_derived.superclass_id == ClassId(module_path=("main",), name="Base")
    assert lowered_derived.methods == []


def test_lower_program_builds_typed_semantic_constants_for_hex_literals(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> unit {
            var a: i64 = 0x2a;
            var b: u64 = 0x2au;
            var c: u8 = 0xffu8;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[0].initializer, LiteralExprS)
    assert isinstance(statements[0].initializer.constant, IntConstant)
    assert statements[0].initializer.type_ref.canonical_name == "i64"
    assert not hasattr(statements[0].initializer.constant, "type_name")
    assert statements[0].initializer.constant.value == 42

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[1].initializer, LiteralExprS)
    assert isinstance(statements[1].initializer.constant, IntConstant)
    assert statements[1].initializer.type_ref.canonical_name == "u64"
    assert not hasattr(statements[1].initializer.constant, "type_name")
    assert statements[1].initializer.constant.value == 42

    assert isinstance(statements[2], SemanticVarDecl)
    assert isinstance(statements[2].initializer, LiteralExprS)
    assert isinstance(statements[2].initializer.constant, IntConstant)
    assert statements[2].initializer.type_ref.canonical_name == "u8"
    assert not hasattr(statements[2].initializer.constant, "type_name")
    assert statements[2].initializer.constant.value == 255


def test_lower_program_handles_simple_function_constructor_method_and_index_forms(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export class Box {
            value: i64;

            fn get() -> i64 {
                return 1;
            }

            static fn from_i64(value: i64) -> Box {
                return Box(value);
            }
        }

        export fn twice(x: i64) -> i64 {
            return x + x;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn helper(x: i64) -> i64 {
            return x;
        }

        fn main() -> i64 {
            var a: i64 = helper(1);
            var b: i64 = util.twice(a);
            var box: util.Box = util.Box(b);
            var alt: util.Box = util.Box.from_i64(b);
            var c: i64 = box.get();
            var arr: i64[] = i64[](2u);
            var x: i64 = arr[0];
            helper;
            util.Box;
            return c + x;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[1].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    _assert_call_target(statements[0].initializer, FunctionCallTarget)
    assert statements[0].initializer.type_ref.canonical_name == "i64"

    assert isinstance(statements[1], SemanticVarDecl)
    _assert_call_target(statements[1].initializer, FunctionCallTarget)
    assert statements[1].initializer.type_ref.canonical_name == "i64"

    assert isinstance(statements[2], SemanticVarDecl)
    constructor_target = _assert_call_target(statements[2].initializer, ConstructorCallTarget)
    assert statements[2].initializer.type_ref.canonical_name == "util::Box"
    assert constructor_target.constructor_id.class_name == "Box"

    assert isinstance(statements[3], SemanticVarDecl)
    static_target = _assert_call_target(statements[3].initializer, StaticMethodCallTarget)
    assert statements[3].initializer.type_ref.canonical_name == "util::Box"
    assert static_target.method_id.name == "from_i64"

    assert isinstance(statements[4], SemanticVarDecl)
    instance_target = _assert_call_target(statements[4].initializer, VirtualMethodCallTarget)
    assert statements[4].initializer.type_ref.canonical_name == "i64"
    assert instance_target.slot_method_name == "get"
    assert instance_target.selected_method_id.name == "get"

    assert isinstance(statements[6], SemanticVarDecl)
    assert isinstance(statements[6].initializer, IndexReadExpr)
    assert statements[6].initializer.type_ref.canonical_name == "i64"

    assert isinstance(statements[7], SemanticExprStmt)
    assert isinstance(statements[7].expr, FunctionRefExpr)
    assert expression_type_name(statements[7].expr) == "fn(i64) -> i64"

    assert isinstance(statements[8], SemanticExprStmt)
    assert isinstance(statements[8].expr, ClassRefExpr)
    assert expression_type_name(statements[8].expr) == "__class__:util:Box"


def test_lower_program_lowers_callable_value_calls_explicitly(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn inc(v: i64) -> i64 {
            return v + 1;
        }

        fn dec(v: i64) -> i64 {
            return v - 1;
        }

        fn choose(use_inc: bool) -> fn(i64) -> i64 {
            if use_inc {
                return inc;
            }
            return dec;
        }

        class Math {
            static fn add(a: i64, b: i64) -> i64 {
                return a + b;
            }
        }

        class Holder {
            f: fn(i64) -> i64;

            fn run(v: i64) -> i64 {
                return __self.f(v);
            }
        }

        fn main() -> i64 {
            var f: fn(i64) -> i64 = choose(true);
            var g: fn(i64, i64) -> i64 = Math.add;
            var h: Holder = Holder(inc);
            var a: i64 = f(10);
            var b: i64 = g(20, 22);
            var c: i64 = h.f(41);
            return a + b + c;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)

    holder_method = semantic.modules[("main",)].classes[1].methods[0]
    holder_return = holder_method.body.statements[0]
    assert isinstance(holder_return, SemanticReturn)
    callable_target = _assert_call_target(holder_return.value, CallableValueCallTarget)
    assert isinstance(callable_target.callee, FieldReadExpr)
    assert holder_return.value.type_ref.canonical_name == "i64"
    assert expression_type_name(holder_return.value) == "i64"
    assert not hasattr(holder_return.value, "type_name")

    main_fn = semantic.modules[("main",)].functions[3]
    statements = main_fn.body.statements

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[1].initializer, MethodRefExpr)
    assert expression_type_name(statements[1].initializer) == "fn(i64, i64) -> i64"

    assert isinstance(statements[3], SemanticVarDecl)
    callable_target = _assert_call_target(statements[3].initializer, CallableValueCallTarget)
    assert isinstance(callable_target.callee, LocalRefExpr)

    assert isinstance(statements[4], SemanticVarDecl)
    callable_target = _assert_call_target(statements[4].initializer, CallableValueCallTarget)
    assert isinstance(callable_target.callee, LocalRefExpr)

    assert isinstance(statements[5], SemanticVarDecl)
    callable_target = _assert_call_target(statements[5].initializer, CallableValueCallTarget)
    assert isinstance(callable_target.callee, FieldReadExpr)


def test_lower_program_prefers_local_callable_over_same_named_function_for_direct_call(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn choose(flag: bool) -> i64 {
            if flag {
                return 1;
            }
            return 2;
        }

        fn inc(v: i64) -> i64 {
            return v + 1;
        }

        fn main() -> i64 {
            var choose: fn(i64) -> i64 = inc;
            return choose(41);
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[2].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    callable_target = _assert_call_target(return_stmt.value, CallableValueCallTarget)
    assert isinstance(callable_target.callee, LocalRefExpr)


def test_lower_program_assigns_imported_canonical_ids_to_refs_and_calls(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export fn twice(x: i64) -> i64 {
            return x + x;
        }

        export class Box {
            value: i64;

            static fn from_i64(value: i64) -> Box {
                return Box(value);
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> i64 {
            var f: fn(i64) -> i64 = util.twice;
            var ctor: fn(i64) -> util.Box = util.Box.from_i64;
            var box: util.Box = util.Box(7);
            var a: i64 = util.twice(9);
            var b: util.Box = util.Box.from_i64(a);
            util.Box;
            return a + b.value;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    function_ref = statements[0]
    assert isinstance(function_ref, SemanticVarDecl)
    assert isinstance(function_ref.initializer, FunctionRefExpr)
    assert function_ref.initializer.function_id.module_path == ("util",)
    assert function_ref.initializer.function_id.name == "twice"
    assert not hasattr(function_ref.initializer, "type_name")

    method_ref = statements[1]
    assert isinstance(method_ref, SemanticVarDecl)
    assert isinstance(method_ref.initializer, MethodRefExpr)
    assert method_ref.initializer.method_id.module_path == ("util",)
    assert method_ref.initializer.method_id.class_name == "Box"
    assert method_ref.initializer.method_id.name == "from_i64"
    assert method_ref.initializer.receiver is None
    assert not hasattr(method_ref.initializer, "type_name")

    constructor_call = statements[2]
    assert isinstance(constructor_call, SemanticVarDecl)
    constructor_target = _assert_call_target(constructor_call.initializer, ConstructorCallTarget)
    assert constructor_target.constructor_id.module_path == ("util",)
    assert constructor_target.constructor_id.class_name == "Box"

    function_call = statements[3]
    assert isinstance(function_call, SemanticVarDecl)
    function_target = _assert_call_target(function_call.initializer, FunctionCallTarget)
    assert function_target.function_id.module_path == ("util",)
    assert function_target.function_id.name == "twice"

    static_method_call = statements[4]
    assert isinstance(static_method_call, SemanticVarDecl)
    static_target = _assert_call_target(static_method_call.initializer, StaticMethodCallTarget)
    assert static_target.method_id.module_path == ("util",)
    assert static_target.method_id.class_name == "Box"
    assert static_target.method_id.name == "from_i64"

    class_ref = statements[5]
    assert isinstance(class_ref, SemanticExprStmt)
    assert isinstance(class_ref.expr, ClassRefExpr)
    assert class_ref.expr.class_id.module_path == ("util",)
    assert class_ref.expr.class_id.name == "Box"
    assert not hasattr(class_ref.expr, "type_name")


def test_lower_program_preserves_nested_instance_method_call_chains(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Leaf {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }

        class Mid {
            fn leaf() -> Leaf {
                return Leaf(7);
            }
        }

        class Root {
            fn mid() -> Mid {
                return Mid();
            }
        }

        fn main() -> i64 {
            var root: Root = Root();
            return root.mid().leaf().read();
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    read_target = _assert_call_target(return_stmt.value, VirtualMethodCallTarget)
    assert read_target.slot_owner_class_id == ClassId(module_path=("main",), name="Leaf")
    assert read_target.slot_method_name == "read"
    assert read_target.selected_method_id.class_name == "Leaf"
    assert semantic_bound_member_receiver_display_name(read_target.access, current_module_path=("main",)) == "Leaf"
    assert semantic_call_target_display_name(read_target, current_module_path=("main",)) == "Leaf.read"
    assert read_target.access.receiver_type_ref.class_id == ClassId(module_path=("main",), name="Leaf")
    assert return_stmt.value.type_ref.canonical_name == "i64"

    leaf_call = read_target.access.receiver
    leaf_target = _assert_call_target(leaf_call, VirtualMethodCallTarget)
    assert leaf_target.slot_owner_class_id == ClassId(module_path=("main",), name="Mid")
    assert leaf_target.slot_method_name == "leaf"
    assert leaf_target.selected_method_id.class_name == "Mid"
    assert semantic_bound_member_receiver_display_name(leaf_target.access, current_module_path=("main",)) == "Mid"
    assert semantic_call_target_display_name(leaf_target, current_module_path=("main",)) == "Mid.leaf"
    assert leaf_target.access.receiver_type_ref.class_id == ClassId(module_path=("main",), name="Mid")

    mid_call = leaf_target.access.receiver
    mid_target = _assert_call_target(mid_call, VirtualMethodCallTarget)
    assert mid_target.slot_owner_class_id == ClassId(module_path=("main",), name="Root")
    assert mid_target.slot_method_name == "mid"
    assert mid_target.selected_method_id.class_name == "Root"
    assert semantic_bound_member_receiver_display_name(mid_target.access, current_module_path=("main",)) == "Root"
    assert semantic_call_target_display_name(mid_target, current_module_path=("main",)) == "Root.mid"
    assert mid_target.access.receiver_type_ref.class_id == ClassId(module_path=("main",), name="Root")
    assert isinstance(mid_target.access.receiver, LocalRefExpr)
    assert (
        semantic_local_display_name(semantic.modules[("main",)].functions[0], mid_target.access.receiver.local_id)
        == "root"
    )


def test_lower_program_lowers_interface_receiver_calls_to_explicit_interface_nodes(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn read_hash(value: Hashable) -> u64 {
            return value.hash_code();
        }

        fn main() -> u64 {
            return read_hash(Key());
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    interface_target = _assert_call_target(return_stmt.value, InterfaceMethodCallTarget)
    assert interface_target.interface_id.module_path == ("main",)
    assert interface_target.interface_id.name == "Hashable"
    assert interface_target.method_id.module_path == ("main",)
    assert interface_target.method_id.interface_name == "Hashable"
    assert interface_target.method_id.name == "hash_code"
    assert (
        semantic_bound_member_receiver_display_name(interface_target.access, current_module_path=("main",))
        == "Hashable"
    )
    assert semantic_call_target_display_name(interface_target, current_module_path=("main",)) == "Hashable.hash_code"
    assert interface_target.access.receiver_type_ref.interface_id == InterfaceId(module_path=("main",), name="Hashable")
    assert return_stmt.value.type_ref.canonical_name == "u64"
    assert isinstance(interface_target.access.receiver, LocalRefExpr)
    assert (
        semantic_local_display_name(semantic.modules[("main",)].functions[0], interface_target.access.receiver.local_id)
        == "value"
    )


def test_lower_program_lowers_base_typed_override_calls_to_virtual_targets(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Base {
            fn read() -> i64 {
                return 1;
            }
        }

        class Derived extends Base {
            override fn read() -> i64 {
                return 2;
            }
        }

        fn use(value: Base) -> i64 {
            return value.read();
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    virtual_target = _assert_call_target(return_stmt.value, VirtualMethodCallTarget)
    assert virtual_target.slot_owner_class_id == ClassId(module_path=("main",), name="Base")
    assert virtual_target.slot_method_name == "read"
    assert virtual_target.selected_method_id == MethodId(module_path=("main",), class_name="Base", name="read")
    assert virtual_target.access.receiver_type_ref.class_id == ClassId(module_path=("main",), name="Base")


def test_lower_program_keeps_private_method_calls_on_direct_instance_targets(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            private fn read() -> i64 {
                return 1;
            }

            fn use() -> i64 {
                return __self.read();
            }
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    return_stmt = semantic.modules[("main",)].classes[0].methods[1].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    direct_target = _assert_call_target(return_stmt.value, InstanceMethodCallTarget)
    assert direct_target.method_id == MethodId(module_path=("main",), class_name="Box", name="read")


def test_lower_program_uses_imported_interface_ids_for_interface_receiver_calls(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn read_hash(value: util.Hashable) -> u64 {
            return value.hash_code();
        }

        fn main() -> u64 {
            return read_hash(util.Key());
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    interface_target = _assert_call_target(return_stmt.value, InterfaceMethodCallTarget)
    assert interface_target.interface_id.module_path == ("util",)
    assert interface_target.interface_id.name == "Hashable"
    assert interface_target.method_id.module_path == ("util",)
    assert interface_target.method_id.interface_name == "Hashable"
    assert interface_target.method_id.name == "hash_code"
    assert (
        semantic_bound_member_receiver_display_name(interface_target.access, current_module_path=("main",))
        == "util::Hashable"
    )
    assert (
        semantic_call_target_display_name(interface_target, current_module_path=("main",)) == "util::Hashable.hash_code"
    )
    assert interface_target.access.receiver_type_ref.interface_id == InterfaceId(module_path=("util",), name="Hashable")


def test_lower_program_preserves_explicit_obj_to_interface_casts(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        interface Hashable {
            fn hash_code() -> u64;
        }

        class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }

        fn main() -> Hashable {
            var value: Obj = Key();
            return (Hashable)value;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CastExprS)
    assert return_stmt.value.cast_kind is CastSemanticsKind.REFERENCE_COMPATIBILITY
    assert semantic_type_display_name_relative(("main",), return_stmt.value.target_type_ref) == "Hashable"
    assert return_stmt.value.target_type_ref.interface_id == InterfaceId(module_path=("main",), name="Hashable")
    assert expression_type_name(return_stmt.value) == "Hashable"
    assert return_stmt.value.type_ref.canonical_name == "main::Hashable"
    assert isinstance(return_stmt.value.operand, LocalRefExpr)
    assert (
        semantic_local_display_name(semantic.modules[("main",)].functions[0], return_stmt.value.operand.local_id)
        == "value"
    )
    assert (
        semantic_local_type_display_name(semantic.modules[("main",)].functions[0], return_stmt.value.operand.local_id)
        == "Obj"
    )


def test_lower_program_preserves_imported_interface_cast_target_names(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> util.Hashable {
            var value: Obj = util.Key();
            return (util.Hashable)value;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, CastExprS)
    assert return_stmt.value.cast_kind is CastSemanticsKind.REFERENCE_COMPATIBILITY
    assert semantic_type_display_name_relative(("main",), return_stmt.value.target_type_ref) == "util::Hashable"
    assert return_stmt.value.target_type_ref.interface_id == InterfaceId(module_path=("util",), name="Hashable")
    assert expression_type_name(return_stmt.value) == "util::Hashable"
    assert return_stmt.value.type_ref.canonical_name == "util::Hashable"
    assert isinstance(return_stmt.value.operand, LocalRefExpr)
    assert (
        semantic_local_display_name(semantic.modules[("main",)].functions[0], return_stmt.value.operand.local_id)
        == "value"
    )
    assert (
        semantic_local_type_display_name(semantic.modules[("main",)].functions[0], return_stmt.value.operand.local_id)
        == "Obj"
    )


def test_lower_program_preserves_imported_interface_type_test_target_names(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }

        export class Key implements Hashable {
            fn hash_code() -> u64 {
                return 1u;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn main() -> bool {
            var value: Obj = util.Key();
            return value is util.Hashable;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, TypeTestExprS)
    assert return_stmt.value.test_kind is TypeTestSemanticsKind.INTERFACE_COMPATIBILITY
    assert semantic_type_display_name_relative(("main",), return_stmt.value.target_type_ref) == "util::Hashable"
    assert return_stmt.value.target_type_ref.interface_id == InterfaceId(module_path=("util",), name="Hashable")
    assert expression_type_name(return_stmt.value) == "bool"
    assert return_stmt.value.type_ref.canonical_name == "bool"
    assert isinstance(return_stmt.value.operand, LocalRefExpr)
    assert (
        semantic_local_display_name(semantic.modules[("main",)].functions[0], return_stmt.value.operand.local_id)
        == "value"
    )
    assert (
        semantic_local_type_display_name(semantic.modules[("main",)].functions[0], return_stmt.value.operand.local_id)
        == "Obj"
    )


def test_lower_program_resolves_structural_index_slice_and_for_in_methods(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Buffer {
            fn index_get(index: i64) -> i64 {
                return 1;
            }

            fn index_set(index: i64, value: i64) -> unit {
                return;
            }

            fn slice_get(begin: i64, end: i64) -> Buffer {
                return Buffer();
            }

            fn slice_set(begin: i64, end: i64, value: Buffer) -> unit {
                return;
            }

            fn iter_len() -> u64 {
                return 0u;
            }

            fn iter_get(index: i64) -> i64 {
                return 0;
            }
        }

        fn main(buffer: Buffer, values: i64[]) -> i64 {
            var first: i64 = buffer[0];
            buffer[0] = first;
            var part: Buffer = buffer[0:1];
            buffer[0:1] = part;
            for value in buffer {
                return value;
            }
            for item in values {
                return item;
            }
            return first;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    first_decl = statements[0]
    assert isinstance(first_decl, SemanticVarDecl)
    assert isinstance(first_decl.initializer, IndexReadExpr)
    assert isinstance(first_decl.initializer.dispatch, MethodDispatch)
    _assert_method_dispatch_matches_op(
        first_decl.initializer.dispatch, class_name="Buffer", op_kind=CollectionOpKind.INDEX_GET
    )

    index_assign = statements[1]
    assert isinstance(index_assign, SemanticAssign)
    assert isinstance(index_assign.target, IndexLValue)
    assert isinstance(index_assign.target.dispatch, MethodDispatch)
    _assert_method_dispatch_matches_op(
        index_assign.target.dispatch, class_name="Buffer", op_kind=CollectionOpKind.INDEX_SET
    )

    slice_decl = statements[2]
    assert isinstance(slice_decl, SemanticVarDecl)
    assert isinstance(slice_decl.initializer, SliceReadExpr)
    assert isinstance(slice_decl.initializer.dispatch, MethodDispatch)
    _assert_method_dispatch_matches_op(
        slice_decl.initializer.dispatch, class_name="Buffer", op_kind=CollectionOpKind.SLICE_GET
    )

    slice_assign = statements[3]
    assert isinstance(slice_assign, SemanticAssign)
    assert isinstance(slice_assign.target, SliceLValue)
    assert isinstance(slice_assign.target.dispatch, MethodDispatch)
    _assert_method_dispatch_matches_op(
        slice_assign.target.dispatch, class_name="Buffer", op_kind=CollectionOpKind.SLICE_SET
    )

    structural_for_in = statements[4]
    assert isinstance(structural_for_in, SemanticForIn)
    assert isinstance(structural_for_in.iter_len_dispatch, MethodDispatch)
    assert isinstance(structural_for_in.iter_get_dispatch, MethodDispatch)
    _assert_method_dispatch_matches_op(
        structural_for_in.iter_len_dispatch, class_name="Buffer", op_kind=CollectionOpKind.ITER_LEN
    )
    _assert_method_dispatch_matches_op(
        structural_for_in.iter_get_dispatch, class_name="Buffer", op_kind=CollectionOpKind.ITER_GET
    )

    array_for_in = statements[5]
    assert isinstance(array_for_in, SemanticForIn)
    assert isinstance(array_for_in.iter_len_dispatch, RuntimeDispatch)
    assert isinstance(array_for_in.iter_get_dispatch, RuntimeDispatch)
    _assert_runtime_dispatch_matches_op(array_for_in.iter_len_dispatch, op_kind=CollectionOpKind.ITER_LEN)
    _assert_runtime_dispatch_matches_op(
        array_for_in.iter_get_dispatch, op_kind=CollectionOpKind.ITER_GET, runtime_kind=ArrayRuntimeKind.I64
    )


def test_lower_program_lowers_explicit_array_structural_calls_and_assignments(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(values: i64[]) -> i64 {
            var first: i64 = values.index_get(0);
            values.index_set(0, 7);
            var part: i64[] = values.slice_get(0, 1);
            values.slice_set(0, 1, part);
            return values.iter_get(0) + (i64)values.iter_len();
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    assert isinstance(statements[0], SemanticVarDecl)
    assert isinstance(statements[0].initializer, IndexReadExpr)
    assert isinstance(statements[0].initializer.dispatch, RuntimeDispatch)
    _assert_runtime_dispatch_matches_op(
        statements[0].initializer.dispatch, op_kind=CollectionOpKind.INDEX_GET, runtime_kind=ArrayRuntimeKind.I64
    )

    assert isinstance(statements[1], SemanticAssign)
    assert isinstance(statements[1].target, IndexLValue)
    assert isinstance(statements[1].target.dispatch, RuntimeDispatch)
    _assert_runtime_dispatch_matches_op(
        statements[1].target.dispatch, op_kind=CollectionOpKind.INDEX_SET, runtime_kind=ArrayRuntimeKind.I64
    )

    assert isinstance(statements[2], SemanticVarDecl)
    assert isinstance(statements[2].initializer, SliceReadExpr)
    assert isinstance(statements[2].initializer.dispatch, RuntimeDispatch)
    _assert_runtime_dispatch_matches_op(
        statements[2].initializer.dispatch, op_kind=CollectionOpKind.SLICE_GET, runtime_kind=ArrayRuntimeKind.I64
    )

    assert isinstance(statements[3], SemanticAssign)
    assert isinstance(statements[3].target, SliceLValue)
    assert isinstance(statements[3].target.dispatch, RuntimeDispatch)
    _assert_runtime_dispatch_matches_op(
        statements[3].target.dispatch, op_kind=CollectionOpKind.SLICE_SET, runtime_kind=ArrayRuntimeKind.I64
    )

    assert isinstance(statements[4], SemanticReturn)
    assert isinstance(statements[4].value, BinaryExprS)
    assert isinstance(statements[4].value.left, IndexReadExpr)
    assert isinstance(statements[4].value.right, CastExprS)
    assert isinstance(statements[4].value.right.operand, ArrayLenExpr)


def test_lower_program_uses_index_set_value_type_for_structural_assignment_targets(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class WeirdStore {
            stored: bool;

            fn index_get(index: i64) -> bool {
                return __self.stored;
            }

            fn index_set(index: i64, value: i64) -> unit {
                __self.stored = value > 0;
            }
        }

        fn main() -> unit {
            var w: WeirdStore = WeirdStore(false);
            w[0] = 7;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    assign_stmt = semantic.modules[("main",)].functions[0].body.statements[1]

    assert isinstance(assign_stmt, SemanticAssign)
    assert isinstance(assign_stmt.target, IndexLValue)
    assert semantic_type_display_name(assign_stmt.target.value_type_ref) == "i64"
    assert isinstance(assign_stmt.target.dispatch, MethodDispatch)
    _assert_method_dispatch_matches_op(
        assign_stmt.target.dispatch, class_name="WeirdStore", op_kind=CollectionOpKind.INDEX_SET
    )


def test_lower_program_lowers_string_literals_and_concat_to_explicit_helpers(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Str {
            static fn from_u8_array(value: u8[]) -> Str {
                return Str();
            }

            static fn concat(left: Str, right: Str) -> Str {
                return Str();
            }
        }

        fn main() -> Str {
            var prefix: Str = "hi";
            return prefix + " there";
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    prefix_decl = statements[0]
    assert isinstance(prefix_decl, SemanticVarDecl)
    prefix_target = _assert_call_target(prefix_decl.initializer, StaticMethodCallTarget)
    assert prefix_target.method_id.class_name == "Str"
    assert prefix_target.method_id.name == "from_u8_array"
    assert isinstance(prefix_decl.initializer.args[0], StringLiteralBytesExpr)
    assert not hasattr(prefix_decl.initializer.args[0], "type_name")
    assert prefix_decl.initializer.args[0].literal_text == '"hi"'

    return_stmt = statements[1]
    assert isinstance(return_stmt, SemanticReturn)
    return_target = _assert_call_target(return_stmt.value, StaticMethodCallTarget)
    assert return_target.method_id.class_name == "Str"
    assert return_target.method_id.name == "concat"
    assert return_stmt.value.type_ref.canonical_name == "main::Str"
    assert isinstance(return_stmt.value.args[0], LocalRefExpr)
    nested_target = _assert_call_target(return_stmt.value.args[1], StaticMethodCallTarget)
    assert nested_target.method_id.name == "from_u8_array"
    assert return_stmt.value.args[1].type_ref.canonical_name == "main::Str"
    assert return_stmt.value.args[1].args[0].type_ref.canonical_name == "u8[]"
    assert not hasattr(return_stmt.value.args[1].args[0], "type_name")


def test_lower_program_lowers_array_len_calls_to_explicit_array_len_expr(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(values: i64[]) -> u64 {
            return values.len();
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, ArrayLenExpr)
    assert not hasattr(return_stmt.value, "type_name")
    assert isinstance(return_stmt.value.target, LocalRefExpr)
    assert (
        local_display_name_for_owner(semantic.modules[("main",)].functions[0], return_stmt.value.target.local_id)
        == "values"
    )
    assert return_stmt.value.type_ref.canonical_name == "u64"


def test_lower_program_uses_ref_runtime_dispatch_for_reference_element_arrays(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn main(values: Box[]) -> Box {
            return values.iter_get(0);
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, IndexReadExpr)
    assert return_stmt.value.type_ref.canonical_name == "main::Box"
    assert isinstance(return_stmt.value.dispatch, RuntimeDispatch)
    _assert_runtime_dispatch_matches_op(
        return_stmt.value.dispatch, op_kind=CollectionOpKind.ITER_GET, runtime_kind=ArrayRuntimeKind.REF
    )


def test_lower_program_preserves_private_owner_context_for_in_class_constructor_calls(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Str {
            private _bytes: u8[];

            static fn from_u8_array(value: u8[]) -> Str {
                return Str(value[:]);
            }
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].classes[0].methods[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    constructor_target = _assert_call_target(return_stmt.value, ConstructorCallTarget)
    assert constructor_target.constructor_id.class_name == "Str"
    assert return_stmt.value.type_ref.canonical_name == "main::Str"


def test_lower_program_lowers_null_and_array_ctor_expressions_explicitly(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn main() -> unit {
            var values: i64[] = i64[](2u);
            var box: Box = null;
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    values_decl = statements[0]
    assert isinstance(values_decl, SemanticVarDecl)
    assert isinstance(values_decl.initializer, ArrayCtorExprS)
    assert semantic_type_display_name(values_decl.initializer.element_type_ref) == "i64"
    assert expression_type_name(values_decl.initializer) == "i64[]"
    assert values_decl.initializer.type_ref.canonical_name == "i64[]"
    assert isinstance(values_decl.initializer.length_expr, LiteralExprS)
    assert isinstance(values_decl.initializer.length_expr.constant, IntConstant)
    assert values_decl.initializer.length_expr.type_ref.canonical_name == "u64"
    assert not hasattr(values_decl.initializer.length_expr.constant, "type_name")
    assert values_decl.initializer.length_expr.constant.value == 2

    box_decl = statements[1]
    assert isinstance(box_decl, SemanticVarDecl)
    assert isinstance(box_decl.initializer, NullExprS)
    assert not hasattr(box_decl.initializer, "type_name")
    assert box_decl.initializer.type_ref.canonical_name == "null"


def test_lower_program_lowers_nested_blocks_with_local_refs_and_assignments(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> bool {
            var flag: bool = true;
            var result: bool = false;
            {
                var inner: bool = flag;
                result = inner;
            }
            return result;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    inner_block = statements[2]
    assert isinstance(inner_block, SemanticBlock)
    assert isinstance(inner_block.statements[0], SemanticVarDecl)
    assert inner_block.statements[0].local_id.owner_id == semantic.modules[("main",)].functions[0].function_id
    assert (
        local_type_name_for_owner(semantic.modules[("main",)].functions[0], inner_block.statements[0].local_id)
        == "bool"
    )
    assert isinstance(inner_block.statements[0].initializer, LocalRefExpr)
    assert inner_block.statements[0].initializer.local_id == statements[0].local_id
    assert (
        local_display_name_for_owner(
            semantic.modules[("main",)].functions[0], inner_block.statements[0].initializer.local_id
        )
        == "flag"
    )
    assert (
        local_type_name_for_owner(
            semantic.modules[("main",)].functions[0], inner_block.statements[0].initializer.local_id
        )
        == "bool"
    )
    assert isinstance(inner_block.statements[1], SemanticAssign)
    assert isinstance(inner_block.statements[1].target, LocalLValue)
    assert inner_block.statements[1].target.local_id == statements[1].local_id
    assert (
        local_display_name_for_owner(
            semantic.modules[("main",)].functions[0], inner_block.statements[1].target.local_id
        )
        == "result"
    )
    assert (
        local_type_name_for_owner(semantic.modules[("main",)].functions[0], inner_block.statements[1].target.local_id)
        == "bool"
    )
    assert isinstance(inner_block.statements[1].value, LocalRefExpr)
    assert inner_block.statements[1].value.local_id == inner_block.statements[0].local_id
    assert (
        local_display_name_for_owner(semantic.modules[("main",)].functions[0], inner_block.statements[1].value.local_id)
        == "inner"
    )
    assert (
        local_type_name_for_owner(semantic.modules[("main",)].functions[0], inner_block.statements[1].value.local_id)
        == "bool"
    )
    assert inner_block.statements[0].local_id != statements[0].local_id
    assert inner_block.statements[0].local_id != statements[1].local_id

    return_stmt = statements[3]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LocalRefExpr)
    assert return_stmt.value.local_id == statements[1].local_id
    assert (
        local_display_name_for_owner(semantic.modules[("main",)].functions[0], return_stmt.value.local_id) == "result"
    )
    assert local_type_name_for_owner(semantic.modules[("main",)].functions[0], return_stmt.value.local_id) == "bool"


def test_lower_program_lowers_for_in_body_locals_and_preserves_following_return(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(done: bool, values: i64[]) -> bool {
            for item in values {
                var current: i64 = item;
            }
            return done;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    statements = semantic.modules[("main",)].functions[0].body.statements

    loop_stmt = statements[0]
    assert isinstance(loop_stmt, SemanticForIn)
    assert loop_stmt.element_name == "item"
    assert loop_stmt.element_local_id.owner_id == semantic.modules[("main",)].functions[0].function_id
    assert semantic_type_display_name(loop_stmt.element_type_ref) == "i64"
    assert loop_stmt.element_type_ref.canonical_name == "i64"
    assert isinstance(loop_stmt.body.statements[0], SemanticVarDecl)
    assert loop_stmt.body.statements[0].local_id.owner_id == semantic.modules[("main",)].functions[0].function_id
    assert isinstance(loop_stmt.body.statements[0].initializer, LocalRefExpr)
    assert loop_stmt.body.statements[0].initializer.local_id == loop_stmt.element_local_id
    assert (
        semantic_local_display_name(
            semantic.modules[("main",)].functions[0], loop_stmt.body.statements[0].initializer.local_id
        )
        == "item"
    )
    assert (
        semantic_local_type_display_name(
            semantic.modules[("main",)].functions[0], loop_stmt.body.statements[0].initializer.local_id
        )
        == "i64"
    )
    assert loop_stmt.body.statements[0].initializer.local_id != loop_stmt.body.statements[0].local_id
    assert all(
        local_info.display_name not in {"__for_in_collection", "__for_in_length", "__for_in_index"}
        for local_info in semantic.modules[("main",)].functions[0].local_info_by_id.values()
    )

    return_stmt = statements[1]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LocalRefExpr)
    assert return_stmt.value.local_id.owner_id == semantic.modules[("main",)].functions[0].function_id
    assert local_display_name_for_owner(semantic.modules[("main",)].functions[0], return_stmt.value.local_id) == "done"
    assert local_type_name_for_owner(semantic.modules[("main",)].functions[0], return_stmt.value.local_id) == "bool"


def test_lower_linked_semantic_program_materializes_for_in_helper_temps(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(values: i64[]) -> i64 {
            var total: i64 = 0;
            for item in values {
                total = total + item;
            }
            return total;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    lowered_program = lower_linked_semantic_program(link_semantic_program(lower_program(program)))
    fn = lowered_program.functions[0]
    loop_stmt = fn.body.statements[1]

    assert isinstance(loop_stmt, LoweredSemanticForIn)
    assert loop_stmt.collection_local_id.owner_id == fn.function_id
    assert loop_stmt.length_local_id.owner_id == fn.function_id
    assert loop_stmt.index_local_id.owner_id == fn.function_id
    assert local_display_name_for_owner(fn, loop_stmt.collection_local_id) == "__for_in_collection"
    assert local_type_name_for_owner(fn, loop_stmt.collection_local_id) == "i64[]"
    assert local_display_name_for_owner(fn, loop_stmt.length_local_id) == "__for_in_length"
    assert local_type_name_for_owner(fn, loop_stmt.length_local_id) == "u64"
    assert local_display_name_for_owner(fn, loop_stmt.index_local_id) == "__for_in_index"
    assert local_type_name_for_owner(fn, loop_stmt.index_local_id) == "i64"
    assert loop_stmt.strategy is LoweredSemanticForInStrategy.ARRAY_DIRECT


def test_lower_linked_semantic_program_preserves_for_in_iteration_strategy(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Buffer {
            values: i64[];

            fn iter_len() -> u64 {
                return __self.values.len();
            }

            fn iter_get(index: i64) -> i64 {
                return __self.values[index];
            }
        }

        fn main(buffer: Buffer, values: i64[]) -> i64 {
            var total: i64 = 0;
            for left in buffer {
                total = total + left;
            }
            for right in values {
                total = total + right;
            }
            return total;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    lowered_program = lower_linked_semantic_program(link_semantic_program(lower_program(program)))
    fn = lowered_program.functions[0]

    protocol_loop = fn.body.statements[1]
    assert isinstance(protocol_loop, LoweredSemanticForIn)
    assert protocol_loop.strategy is LoweredSemanticForInStrategy.COLLECTION_PROTOCOL_DISPATCH
    assert isinstance(protocol_loop.iter_len_dispatch, MethodDispatch)
    assert isinstance(protocol_loop.iter_get_dispatch, MethodDispatch)

    array_loop = fn.body.statements[2]
    assert isinstance(array_loop, LoweredSemanticForIn)
    assert array_loop.strategy is LoweredSemanticForInStrategy.ARRAY_DIRECT
    assert isinstance(array_loop.iter_len_dispatch, RuntimeDispatch)
    assert isinstance(array_loop.iter_get_dispatch, RuntimeDispatch)


def test_lower_linked_semantic_program_uses_explicit_lowered_control_flow_nodes(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(flag: bool) -> i64 {
            var total: i64 = 0;
            if flag {
                total = 1;
            } else {
                total = 2;
            }
            while flag {
                return total;
            }
            return total;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    lowered_program = lower_linked_semantic_program(link_semantic_program(lower_program(program)))
    fn = lowered_program.functions[0]

    if_stmt = fn.body.statements[1]
    while_stmt = fn.body.statements[2]

    assert isinstance(if_stmt, LoweredSemanticIf)
    assert isinstance(if_stmt.then_block, LoweredSemanticBlock)
    assert isinstance(if_stmt.else_block, LoweredSemanticBlock)
    assert isinstance(while_stmt, LoweredSemanticWhile)
    assert isinstance(while_stmt.body, LoweredSemanticBlock)


def test_lower_linked_semantic_program_uses_explicit_lowered_function_and_class_wrappers(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;

            fn read() -> i64 {
                return __self.value;
            }
        }

        fn main(box: Box) -> i64 {
            return box.read();
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    lowered_program = lower_linked_semantic_program(link_semantic_program(lower_program(program)))

    fn = lowered_program.functions[0]
    cls = lowered_program.classes[0]
    method = cls.methods[0]

    assert isinstance(fn, LoweredSemanticFunction)
    assert isinstance(fn.body, LoweredSemanticBlock)
    assert isinstance(cls, LoweredSemanticClass)
    assert isinstance(cls.fields[0], LoweredSemanticField)
    assert isinstance(method, LoweredSemanticMethod)
    assert isinstance(method.body, LoweredSemanticBlock)


def test_lower_program_local_identity_is_stable_under_local_rename(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(flag: bool) -> bool {
            var result: bool = flag;
            return result;
        }
        """,
    )
    _write(
        tmp_path / "renamed.nif",
        """
        fn main(flag: bool) -> bool {
            var outcome: bool = flag;
            return outcome;
        }
        """,
    )

    original = (
        lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path)).modules[("main",)].functions[0]
    )
    renamed = (
        lower_program(resolve_program(tmp_path / "renamed.nif", project_root=tmp_path))
        .modules[("renamed",)]
        .functions[0]
    )

    original_decl = original.body.statements[0]
    renamed_decl = renamed.body.statements[0]
    original_return = original.body.statements[1]
    renamed_return = renamed.body.statements[1]

    assert isinstance(original_decl, SemanticVarDecl)
    assert isinstance(renamed_decl, SemanticVarDecl)
    assert isinstance(original_return, SemanticReturn)
    assert isinstance(renamed_return, SemanticReturn)
    assert isinstance(original_return.value, LocalRefExpr)
    assert isinstance(renamed_return.value, LocalRefExpr)

    assert local_display_name_for_owner(original, original_decl.local_id) == "result"
    assert local_display_name_for_owner(renamed, renamed_decl.local_id) == "outcome"
    assert original_decl.local_id.ordinal == renamed_decl.local_id.ordinal == 1
    assert original_return.value.local_id.ordinal == renamed_return.value.local_id.ordinal == 1


def test_lower_program_assigns_distinct_ids_to_shadowed_bindings(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main(value: i64) -> i64 {
            var total: i64 = value;
            {
                var value: i64 = 7;
                total = total + value;
            }
            return value;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    function = semantic.modules[("main",)].functions[0]
    param_local_info = next(
        local_info
        for local_info in function.local_info_by_id.values()
        if local_info.binding_kind == "param" and local_info.display_name == "value"
    )

    total_decl = function.body.statements[0]
    inner_block = function.body.statements[1]
    return_stmt = function.body.statements[2]

    assert isinstance(total_decl, SemanticVarDecl)
    assert isinstance(inner_block, SemanticBlock)
    assert isinstance(inner_block.statements[0], SemanticVarDecl)
    assert isinstance(inner_block.statements[1], SemanticAssign)
    assert isinstance(inner_block.statements[1].value, BinaryExprS)
    assert isinstance(inner_block.statements[1].value.right, LocalRefExpr)
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, LocalRefExpr)

    shadow_decl = inner_block.statements[0]
    assert local_display_name_for_owner(function, shadow_decl.local_id) == "value"
    assert shadow_decl.local_id != param_local_info.local_id
    assert inner_block.statements[1].value.right.local_id == shadow_decl.local_id
    assert return_stmt.value.local_id == param_local_info.local_id


def test_lower_program_preserves_min_i64_literal_inside_unary_negation(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        fn main() -> i64 {
            return -9223372036854775808;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    semantic = lower_program(program)
    return_stmt = semantic.modules[("main",)].functions[0].body.statements[0]

    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, UnaryExprS)
    assert return_stmt.value.op.kind is UnaryOpKind.NEGATE
    assert return_stmt.value.op.flavor is UnaryOpFlavor.INTEGER
    assert return_stmt.value.type_ref.canonical_name == "i64"
    assert isinstance(return_stmt.value.operand, LiteralExprS)
    assert isinstance(return_stmt.value.operand.constant, IntConstant)
    assert return_stmt.value.operand.type_ref.canonical_name == "i64"
    assert not hasattr(return_stmt.value.operand.constant, "type_name")
    assert return_stmt.value.operand.constant.value == 9223372036854775808


def test_lower_program_distinguishes_operation_flavors_after_type_resolution(tmp_path: Path) -> None:
    _write(
        tmp_path / "main.nif",
        """
        class Box {
            value: i64;
        }

        fn add_i64(left: i64, right: i64) -> i64 {
            return left + right;
        }

        fn add_double(left: double, right: double) -> double {
            return left + right;
        }

        fn same_box(left: Box, right: Box) -> bool {
            return left == right;
        }
        """,
    )

    semantic = lower_program(resolve_program(tmp_path / "main.nif", project_root=tmp_path))
    functions = semantic.modules[("main",)].functions

    int_return = functions[0].body.statements[0]
    double_return = functions[1].body.statements[0]
    identity_return = functions[2].body.statements[0]

    assert isinstance(int_return, SemanticReturn)
    assert isinstance(int_return.value, BinaryExprS)
    assert int_return.value.op.kind is BinaryOpKind.ADD
    assert int_return.value.op.flavor is BinaryOpFlavor.INTEGER

    assert isinstance(double_return, SemanticReturn)
    assert isinstance(double_return.value, BinaryExprS)
    assert double_return.value.op.kind is BinaryOpKind.ADD
    assert double_return.value.op.flavor is BinaryOpFlavor.FLOAT

    assert isinstance(identity_return, SemanticReturn)
    assert isinstance(identity_return.value, BinaryExprS)
    assert identity_return.value.op.kind is BinaryOpKind.EQUAL
    assert identity_return.value.op.flavor is BinaryOpFlavor.IDENTITY_COMPARISON
