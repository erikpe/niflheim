from __future__ import annotations

from compiler.common.type_names import TYPE_NAME_DOUBLE
from compiler.codegen.model import FLOAT_PARAM_REGISTERS, PARAM_REGISTERS


def plan_sysv_arg_locations(arg_type_names: list[str]) -> list[tuple[str, str | None, int | None]]:
    locations: list[tuple[str, str | None, int | None]] = []
    integer_reg_index = 0
    float_reg_index = 0
    stack_index = 0

    for type_name in arg_type_names:
        if type_name == TYPE_NAME_DOUBLE:
            if float_reg_index < len(FLOAT_PARAM_REGISTERS):
                locations.append(("float_reg", FLOAT_PARAM_REGISTERS[float_reg_index], None))
                float_reg_index += 1
            else:
                locations.append(("stack", None, stack_index))
                stack_index += 1
            continue

        if integer_reg_index < len(PARAM_REGISTERS):
            locations.append(("int_reg", PARAM_REGISTERS[integer_reg_index], None))
            integer_reg_index += 1
        else:
            locations.append(("stack", None, stack_index))
            stack_index += 1

    return locations
