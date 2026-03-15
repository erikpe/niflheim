from compiler.codegen.abi_sysv import plan_sysv_arg_locations


def test_plan_sysv_arg_locations_mixes_float_int_and_stack() -> None:
    locations = plan_sysv_arg_locations([
        "i64",
        "double",
        "u64",
        "double",
        "u8",
        "double",
        "bool",
        "double",
        "i64",
        "double",
        "u64",
        "i64",
    ])

    assert locations[0] == ("int_reg", "rdi", None)
    assert locations[1] == ("float_reg", "xmm0", None)
    assert locations[7] == ("float_reg", "xmm3", None)
    assert locations[8] == ("int_reg", "r8", None)
    assert locations[9] == ("float_reg", "xmm4", None)
    assert locations[10] == ("int_reg", "r9", None)
    assert locations[11] == ("stack", None, 0)