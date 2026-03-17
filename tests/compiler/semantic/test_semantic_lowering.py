from __future__ import annotations

from pathlib import Path

from compiler.semantic_ir import (
    BinaryExprS,
    CallableValueCallExpr,
    ClassRefExpr,
    ConstructorCallExpr,
    FieldLValue,
    FieldReadExpr,
    FunctionCallExpr,
    FunctionRefExpr,
    IndexLValue,
    IndexReadExpr,
    InstanceMethodCallExpr,
    LocalLValue,
    LocalRefExpr,
    MethodRefExpr,
    SemanticAssign,
    SemanticExprStmt,
    SemanticForIn,
    SemanticIf,
    SemanticReturn,
    SemanticVarDecl,
    SemanticWhile,
    SliceLValue,
    SliceReadExpr,
    StaticMethodCallExpr,
    SyntheticExpr,
)
from compiler.resolver import resolve_program
from compiler.semantic_lowering import lower_program


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


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
    assert util_module.classes[0].fields[0].type_name == "i64"
    assert util_module.classes[0].methods[0].method_id.class_name == "Counter"
    assert util_module.classes[0].methods[0].return_type_name == "i64"
    assert util_module.functions[0].function_id.module_path == ("util",)
    assert util_module.functions[0].params[0].type_name == "i64"
    assert util_module.functions[0].return_type_name == "i64"


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

    assert isinstance(function.body.statements[0], SemanticVarDecl)
    assert function.body.statements[0].type_name == "i64"

    if_stmt = function.body.statements[1]
    assert isinstance(if_stmt, SemanticIf)
    assign_stmt = if_stmt.then_block.statements[0]
    assert isinstance(assign_stmt, SemanticAssign)
    assert isinstance(assign_stmt.target, FieldLValue)
    assert assign_stmt.target.field_name == "value"
    assert isinstance(assign_stmt.value, BinaryExprS)
    assert isinstance(assign_stmt.value.left, FieldReadExpr)

    while_stmt = function.body.statements[2]
    assert isinstance(while_stmt, SemanticWhile)
    while_assign = while_stmt.body.statements[0]
    assert isinstance(while_assign, SemanticAssign)
    assert isinstance(while_assign.target, LocalLValue)
    assert while_assign.target.name == "total"
    assert isinstance(while_assign.value, BinaryExprS)
    assert isinstance(while_assign.value.left, LocalRefExpr)

    return_stmt = function.body.statements[3]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, FieldReadExpr)


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
    assert isinstance(statements[0].initializer, FunctionCallExpr)

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[1].initializer, FunctionCallExpr)

    assert isinstance(statements[2], SemanticVarDecl)
    assert isinstance(statements[2].initializer, ConstructorCallExpr)

    assert isinstance(statements[3], SemanticVarDecl)
    assert isinstance(statements[3].initializer, StaticMethodCallExpr)

    assert isinstance(statements[4], SemanticVarDecl)
    assert isinstance(statements[4].initializer, InstanceMethodCallExpr)

    assert isinstance(statements[6], SemanticVarDecl)
    assert isinstance(statements[6].initializer, IndexReadExpr)

    assert isinstance(statements[7], SemanticExprStmt)
    assert isinstance(statements[7].expr, FunctionRefExpr)

    assert isinstance(statements[8], SemanticExprStmt)
    assert isinstance(statements[8].expr, ClassRefExpr)


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
    assert isinstance(holder_return.value, CallableValueCallExpr)
    assert isinstance(holder_return.value.callee, FieldReadExpr)
    assert holder_return.value.type_name == "i64"

    main_fn = semantic.modules[("main",)].functions[3]
    statements = main_fn.body.statements

    assert isinstance(statements[1], SemanticVarDecl)
    assert isinstance(statements[1].initializer, MethodRefExpr)

    assert isinstance(statements[3], SemanticVarDecl)
    assert isinstance(statements[3].initializer, CallableValueCallExpr)
    assert isinstance(statements[3].initializer.callee, LocalRefExpr)

    assert isinstance(statements[4], SemanticVarDecl)
    assert isinstance(statements[4].initializer, CallableValueCallExpr)
    assert isinstance(statements[4].initializer.callee, LocalRefExpr)

    assert isinstance(statements[5], SemanticVarDecl)
    assert isinstance(statements[5].initializer, CallableValueCallExpr)
    assert isinstance(statements[5].initializer.callee, FieldReadExpr)


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

    method_ref = statements[1]
    assert isinstance(method_ref, SemanticVarDecl)
    assert isinstance(method_ref.initializer, MethodRefExpr)
    assert method_ref.initializer.method_id.module_path == ("util",)
    assert method_ref.initializer.method_id.class_name == "Box"
    assert method_ref.initializer.method_id.name == "from_i64"
    assert method_ref.initializer.receiver is None

    constructor_call = statements[2]
    assert isinstance(constructor_call, SemanticVarDecl)
    assert isinstance(constructor_call.initializer, ConstructorCallExpr)
    assert constructor_call.initializer.constructor_id.module_path == ("util",)
    assert constructor_call.initializer.constructor_id.class_name == "Box"

    function_call = statements[3]
    assert isinstance(function_call, SemanticVarDecl)
    assert isinstance(function_call.initializer, FunctionCallExpr)
    assert function_call.initializer.function_id.module_path == ("util",)
    assert function_call.initializer.function_id.name == "twice"

    static_method_call = statements[4]
    assert isinstance(static_method_call, SemanticVarDecl)
    assert isinstance(static_method_call.initializer, StaticMethodCallExpr)
    assert static_method_call.initializer.method_id.module_path == ("util",)
    assert static_method_call.initializer.method_id.class_name == "Box"
    assert static_method_call.initializer.method_id.name == "from_i64"

    class_ref = statements[5]
    assert isinstance(class_ref, SemanticExprStmt)
    assert isinstance(class_ref.expr, ClassRefExpr)
    assert class_ref.expr.class_id.module_path == ("util",)
    assert class_ref.expr.class_id.name == "Box"


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
    assert isinstance(return_stmt.value, InstanceMethodCallExpr)
    assert return_stmt.value.method_id.class_name == "Leaf"
    assert return_stmt.value.method_id.name == "read"
    assert return_stmt.value.receiver_type_name == "Leaf"

    leaf_call = return_stmt.value.receiver
    assert isinstance(leaf_call, InstanceMethodCallExpr)
    assert leaf_call.method_id.class_name == "Mid"
    assert leaf_call.method_id.name == "leaf"
    assert leaf_call.receiver_type_name == "Mid"

    mid_call = leaf_call.receiver
    assert isinstance(mid_call, InstanceMethodCallExpr)
    assert mid_call.method_id.class_name == "Root"
    assert mid_call.method_id.name == "mid"
    assert mid_call.receiver_type_name == "Root"
    assert isinstance(mid_call.receiver, LocalRefExpr)
    assert mid_call.receiver.name == "root"


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
    assert first_decl.initializer.get_method is not None
    assert first_decl.initializer.get_method.class_name == "Buffer"
    assert first_decl.initializer.get_method.name == "index_get"

    index_assign = statements[1]
    assert isinstance(index_assign, SemanticAssign)
    assert isinstance(index_assign.target, IndexLValue)
    assert index_assign.target.set_method is not None
    assert index_assign.target.set_method.class_name == "Buffer"
    assert index_assign.target.set_method.name == "index_set"

    slice_decl = statements[2]
    assert isinstance(slice_decl, SemanticVarDecl)
    assert isinstance(slice_decl.initializer, SliceReadExpr)
    assert slice_decl.initializer.get_method is not None
    assert slice_decl.initializer.get_method.class_name == "Buffer"
    assert slice_decl.initializer.get_method.name == "slice_get"

    slice_assign = statements[3]
    assert isinstance(slice_assign, SemanticAssign)
    assert isinstance(slice_assign.target, SliceLValue)
    assert slice_assign.target.set_method is not None
    assert slice_assign.target.set_method.class_name == "Buffer"
    assert slice_assign.target.set_method.name == "slice_set"

    structural_for_in = statements[4]
    assert isinstance(structural_for_in, SemanticForIn)
    assert structural_for_in.iter_len_method is not None
    assert structural_for_in.iter_get_method is not None
    assert structural_for_in.iter_len_method.class_name == "Buffer"
    assert structural_for_in.iter_len_method.name == "iter_len"
    assert structural_for_in.iter_get_method.class_name == "Buffer"
    assert structural_for_in.iter_get_method.name == "iter_get"

    array_for_in = statements[5]
    assert isinstance(array_for_in, SemanticForIn)
    assert array_for_in.iter_len_method is None
    assert array_for_in.iter_get_method is None


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
    assert isinstance(prefix_decl.initializer, StaticMethodCallExpr)
    assert prefix_decl.initializer.method_id.class_name == "Str"
    assert prefix_decl.initializer.method_id.name == "from_u8_array"
    assert isinstance(prefix_decl.initializer.args[0], SyntheticExpr)
    assert prefix_decl.initializer.args[0].synthetic_id.kind == "string_literal_bytes"
    assert prefix_decl.initializer.args[0].synthetic_id.name == '"hi"'

    return_stmt = statements[1]
    assert isinstance(return_stmt, SemanticReturn)
    assert isinstance(return_stmt.value, StaticMethodCallExpr)
    assert return_stmt.value.method_id.class_name == "Str"
    assert return_stmt.value.method_id.name == "concat"
    assert isinstance(return_stmt.value.args[0], LocalRefExpr)
    assert isinstance(return_stmt.value.args[1], StaticMethodCallExpr)
    assert return_stmt.value.args[1].method_id.name == "from_u8_array"
