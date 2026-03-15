from compiler.codegen.abi_sysv import plan_sysv_arg_locations


def test_plan_sysv_arg_locations_handles_empty_parameter_list() -> None:
    assert plan_sysv_arg_locations([]) == []


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


def test_plan_sysv_arg_locations_spills_float_only_args_after_xmm_registers() -> None:
    locations = plan_sysv_arg_locations(["double"] * 10)

    assert locations[:8] == [
        ("float_reg", "xmm0", None),
        ("float_reg", "xmm1", None),
        ("float_reg", "xmm2", None),
        ("float_reg", "xmm3", None),
        ("float_reg", "xmm4", None),
        ("float_reg", "xmm5", None),
        ("float_reg", "xmm6", None),
        ("float_reg", "xmm7", None),
    ]
    assert locations[8] == ("stack", None, 0)
    assert locations[9] == ("stack", None, 1)
