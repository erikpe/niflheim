from __future__ import annotations

from pathlib import Path

import pytest

from compiler.frontend.ast_nodes import ConstructorDecl
from compiler.resolver import resolve_program
from compiler.semantic.symbols import (
    ClassId,
    ConstructorId,
    FunctionId,
    InterfaceId,
    InterfaceMethodId,
    MethodId,
    build_program_symbol_index,
    resolve_visible_interface_id,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def test_build_program_symbol_index_collects_canonical_ids_across_modules(tmp_path: Path) -> None:
    _write(
        tmp_path / "pkg" / "alpha.nif",
        """
        export fn collide() -> unit {
            return;
        }

        export class Box {
            value: i64;

            fn value() -> i64 {
                return self.value;
            }
        }
        """,
    )
    _write(
        tmp_path / "pkg" / "beta.nif",
        """
        export fn collide() -> unit {
            return;
        }

        export class Box {
            value: i64;

            fn value() -> i64 {
                return self.value;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import pkg.alpha;
        import pkg.beta;

        fn main() -> unit {
            pkg.alpha.collide();
            pkg.beta.collide();
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    alpha_function = FunctionId(module_path=("pkg", "alpha"), name="collide")
    beta_function = FunctionId(module_path=("pkg", "beta"), name="collide")
    alpha_class = ClassId(module_path=("pkg", "alpha"), name="Box")
    beta_class = ClassId(module_path=("pkg", "beta"), name="Box")
    alpha_method = MethodId(module_path=("pkg", "alpha"), class_name="Box", name="value")
    beta_method = MethodId(module_path=("pkg", "beta"), class_name="Box", name="value")
    alpha_constructor = ConstructorId(module_path=("pkg", "alpha"), class_name="Box")
    beta_constructor = ConstructorId(module_path=("pkg", "beta"), class_name="Box")

    assert alpha_function in index.functions
    assert beta_function in index.functions
    assert alpha_class in index.classes
    assert beta_class in index.classes
    assert alpha_method in index.methods
    assert beta_method in index.methods
    assert alpha_constructor in index.constructors
    assert beta_constructor in index.constructors
    assert index.class_ids_by_name["Box"] == {alpha_class, beta_class}


def test_build_program_symbol_index_tracks_local_lookups_by_module(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export fn helper() -> unit {
            return;
        }

        export class Counter {
            value: i64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        fn helper() -> unit {
            return;
        }

        class Counter {
            value: i64;
        }

        fn main() -> unit {
            helper();
            util.helper();
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    assert index.local_functions_by_module[("main",)]["helper"] == FunctionId(("main",), "helper")
    assert index.local_functions_by_module[("util",)]["helper"] == FunctionId(("util",), "helper")
    assert index.local_classes_by_module[("main",)]["Counter"] == ClassId(("main",), "Counter")
    assert index.local_classes_by_module[("util",)]["Counter"] == ClassId(("util",), "Counter")


def test_build_program_symbol_index_maps_constructors_back_to_class_decls(tmp_path: Path) -> None:
    _write(
        tmp_path / "models.nif",
        """
        export class PublicBox {
            value: i64;
        }

        export class WithDefault {
            value: i64 = 7;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import models;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    public_box_ctor = ConstructorId(module_path=("models",), class_name="PublicBox")
    with_default_ctor = ConstructorId(module_path=("models",), class_name="WithDefault")

    assert index.constructors[public_box_ctor].name == "PublicBox"
    assert index.constructors[with_default_ctor].name == "WithDefault"


def test_build_program_symbol_index_collects_explicit_constructor_ordinals(tmp_path: Path) -> None:
    _write(
        tmp_path / "models.nif",
        """
        export class Box {
            constructor() {
                return;
            }

            constructor(value: i64) {
                return;
            }
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import models;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    ctor0 = ConstructorId(module_path=("models",), class_name="Box", ordinal=0)
    ctor1 = ConstructorId(module_path=("models",), class_name="Box", ordinal=1)

    assert isinstance(index.constructors[ctor0], ConstructorDecl)
    assert isinstance(index.constructors[ctor1], ConstructorDecl)
    assert len(index.constructors[ctor0].params) == 0
    assert len(index.constructors[ctor1].params) == 1


def test_build_program_symbol_index_collects_interface_ids_across_modules(tmp_path: Path) -> None:
    _write(
        tmp_path / "pkg" / "alpha.nif",
        """
        export interface Shared {
            fn hash_code() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "pkg" / "beta.nif",
        """
        export interface Shared {
            fn equals(other: Obj) -> bool;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import pkg.alpha;
        import pkg.beta;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    alpha_interface = InterfaceId(module_path=("pkg", "alpha"), name="Shared")
    beta_interface = InterfaceId(module_path=("pkg", "beta"), name="Shared")
    alpha_method = InterfaceMethodId(module_path=("pkg", "alpha"), interface_name="Shared", name="hash_code")
    beta_method = InterfaceMethodId(module_path=("pkg", "beta"), interface_name="Shared", name="equals")

    assert alpha_interface in index.interfaces
    assert beta_interface in index.interfaces
    assert alpha_method in index.interface_methods
    assert beta_method in index.interface_methods
    assert index.interface_ids_by_name["Shared"] == {alpha_interface, beta_interface}


def test_build_program_symbol_index_tracks_local_and_imported_interface_lookup(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;

        interface Hashable {
            fn local_hash() -> u64;
        }

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    assert index.local_interfaces_by_module[("main",)]["Hashable"] == InterfaceId(("main",), "Hashable")
    assert index.local_interfaces_by_module[("util",)]["Hashable"] == InterfaceId(("util",), "Hashable")
    assert resolve_visible_interface_id(index, program, ("main",), "Hashable") == InterfaceId(("main",), "Hashable")

    _write(
        tmp_path / "consumer.nif",
        """
        import util;

        fn main() -> unit {
            return;
        }
        """,
    )

    consumer_program = resolve_program(tmp_path / "consumer.nif", project_root=tmp_path)
    consumer_index = build_program_symbol_index(consumer_program)
    assert resolve_visible_interface_id(consumer_index, consumer_program, ("consumer",), "Hashable") == InterfaceId(
        ("util",), "Hashable"
    )


def test_build_program_symbol_index_rejects_ambiguous_imported_interface_lookup(tmp_path: Path) -> None:
    _write(
        tmp_path / "pkg" / "left.nif",
        """
        export interface Shared {
            fn left() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "pkg" / "right.nif",
        """
        export interface Shared {
            fn right() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import pkg.left;
        import pkg.right;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    with pytest.raises(ValueError, match="Ambiguous imported interface 'Shared'"):
        resolve_visible_interface_id(index, program, ("main",), "Shared")


def test_build_program_symbol_index_deduplicates_root_flatten_reexported_interface_owner(tmp_path: Path) -> None:
    _write(
        tmp_path / "util.nif",
        """
        export interface Hashable {
            fn hash_code() -> u64;
        }
        """,
    )
    _write(
        tmp_path / "lib.nif",
        """
        export import util as .;
        """,
    )
    _write(
        tmp_path / "main.nif",
        """
        import util;
        import lib;

        fn main() -> unit {
            return;
        }
        """,
    )

    program = resolve_program(tmp_path / "main.nif", project_root=tmp_path)
    index = build_program_symbol_index(program)

    assert resolve_visible_interface_id(index, program, ("main",), "Hashable") == InterfaceId(("util",), "Hashable")
