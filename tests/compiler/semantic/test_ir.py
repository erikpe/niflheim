from compiler.common.collection_protocols import CollectionOpKind
from compiler.semantic.ir import (
    InterfaceDispatch,
    MethodDispatch,
    RuntimeDispatch,
    VirtualMethodDispatch,
    dispatch_interface_id,
    dispatch_method_id,
)
from compiler.semantic.symbols import ClassId, InterfaceId, InterfaceMethodId, MethodId


def test_dispatch_method_id_ignores_interface_dispatch() -> None:
    interface_dispatch = InterfaceDispatch(
        interface_id=InterfaceId(module_path=("main",), name="Seq"),
        method_id=InterfaceMethodId(module_path=("main",), interface_name="Seq", name="iter_get"),
    )

    assert dispatch_method_id(interface_dispatch) is None


def test_dispatch_interface_id_returns_only_interface_dispatch_id() -> None:
    interface_id = InterfaceId(module_path=("main",), name="Seq")
    interface_dispatch = InterfaceDispatch(
        interface_id=interface_id,
        method_id=InterfaceMethodId(module_path=("main",), interface_name="Seq", name="iter_get"),
    )
    method_dispatch = MethodDispatch(method_id=MethodId(module_path=("main",), class_name="SeqImpl", name="iter_get"))
    virtual_dispatch = VirtualMethodDispatch(
        receiver_class_id=ClassId(module_path=("main",), name="SeqImpl"),
        slot_owner_class_id=ClassId(module_path=("main",), name="SeqBase"),
        method_name="iter_get",
        selected_method_id=MethodId(module_path=("main",), class_name="SeqBase", name="iter_get"),
    )
    runtime_dispatch = RuntimeDispatch(operation=CollectionOpKind.LEN)

    assert dispatch_interface_id(interface_dispatch) == interface_id
    assert dispatch_interface_id(method_dispatch) is None
    assert dispatch_interface_id(virtual_dispatch) is None
    assert dispatch_interface_id(runtime_dispatch) is None