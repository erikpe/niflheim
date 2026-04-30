from __future__ import annotations

import json
import struct
from dataclasses import replace
from pathlib import Path

import pytest

from compiler.backend.ir import (
    BACKEND_IR_SCHEMA_VERSION,
    BackendBlock,
    BackendBlockId,
    BackendBoolConst,
    BackendCallableDecl,
    BackendConstInst,
    BackendDataBlob,
    BackendDataId,
    BackendDoubleConst,
    BackendInstId,
    BackendIntConst,
    BackendJumpTerminator,
    BackendProgram,
    BackendRegId,
    BackendRegOperand,
    BackendRegister,
    BackendReturnTerminator,
    BackendSignature,
)
from compiler.backend.ir.serialize import (
    backend_program_from_dict,
    backend_program_to_dict,
    dump_backend_program_json,
    load_backend_program_json,
)
from compiler.common.type_names import TYPE_NAME_I64
from compiler.semantic.symbols import FunctionId
from compiler.semantic.types import semantic_primitive_type_ref
from tests.compiler.backend.ir.helpers import (
    FIXTURE_ENTRY_FUNCTION_ID,
    make_source_span,
    one_constructor_backend_program,
    one_function_backend_program,
    one_method_backend_program,
)


@pytest.mark.parametrize(
    "builder",
    [one_function_backend_program, one_method_backend_program, one_constructor_backend_program],
)
def test_backend_program_json_round_trip_preserves_function_method_and_constructor_fixtures(builder) -> None:
    program = builder()

    assert backend_program_from_dict(backend_program_to_dict(program)) == program
    assert load_backend_program_json(dump_backend_program_json(program)) == program


def test_dump_backend_program_json_is_deterministic_for_representative_function_fixture() -> None:
    program = one_function_backend_program()

    assert dump_backend_program_json(program) == """{
  \"schema_version\": \"niflheim.backend-ir.v1\",
  \"entry_callable_id\": {
    \"kind\": \"function\",
    \"module_path\": [
      \"fixture\",
      \"backend_ir\"
    ],
    \"name\": \"main\"
  },
  \"data_blobs\": [],
  \"interfaces\": [],
  \"classes\": [],
  \"callables\": [
    {
      \"callable_id\": {
        \"kind\": \"function\",
        \"module_path\": [
          \"fixture\",
          \"backend_ir\"
        ],
        \"name\": \"main\"
      },
      \"kind\": \"function\",
      \"signature\": {
        \"param_types\": [],
        \"return_type\": {
          \"kind\": \"primitive\",
          \"canonical_name\": \"i64\",
          \"display_name\": \"i64\"
        }
      },
      \"is_export\": false,
      \"is_extern\": false,
      \"is_static\": null,
      \"is_private\": null,
      \"registers\": [
        {
          \"id\": \"r0\",
          \"type\": {
            \"kind\": \"primitive\",
            \"canonical_name\": \"i64\",
            \"display_name\": \"i64\"
          },
          \"debug_name\": \"ret0\",
          \"origin_kind\": \"temp\",
          \"semantic_local_id\": null,
          \"span\": null
        }
      ],
      \"param_regs\": [],
      \"receiver_reg\": null,
      \"entry_block_id\": \"b0\",
      \"blocks\": [
        {
          \"id\": \"b0\",
          \"debug_name\": \"entry\",
          \"instructions\": [
            {
              \"id\": \"i0\",
              \"kind\": \"const\",
              \"dest\": \"r0\",
              \"constant\": {
                \"kind\": \"i64\",
                \"value\": 0
              },
              \"span\": {
                \"start\": {
                  \"path\": \"fixtures/function.nif\",
                  \"offset\": 0,
                  \"line\": 1,
                  \"column\": 1
                },
                \"end\": {
                  \"path\": \"fixtures/function.nif\",
                  \"offset\": 1,
                  \"line\": 1,
                  \"column\": 2
                }
              }
            }
          ],
          \"terminator\": {
            \"kind\": \"return\",
            \"value\": {
              \"kind\": \"reg\",
              \"reg_id\": \"r0\"
            },
            \"span\": {
              \"start\": {
                \"path\": \"fixtures/function.nif\",
                \"offset\": 0,
                \"line\": 1,
                \"column\": 1
              },
              \"end\": {
                \"path\": \"fixtures/function.nif\",
                \"offset\": 1,
                \"line\": 1,
                \"column\": 2
              }
            }
          },
          \"span\": {
            \"start\": {
              \"path\": \"fixtures/function.nif\",
              \"offset\": 0,
              \"line\": 1,
              \"column\": 1
            },
            \"end\": {
              \"path\": \"fixtures/function.nif\",
              \"offset\": 1,
              \"line\": 1,
              \"column\": 2
            }
          }
        }
      ],
      \"span\": {
        \"start\": {
          \"path\": \"fixtures/function.nif\",
          \"offset\": 0,
          \"line\": 1,
          \"column\": 1
        },
        \"end\": {
          \"path\": \"fixtures/function.nif\",
          \"offset\": 1,
          \"line\": 1,
          \"column\": 2
        }
      }
    }
  ]
}"""


def test_dump_backend_program_json_normalizes_project_relative_paths_and_preserves_synthetic_paths(tmp_path: Path) -> None:
    absolute_source = tmp_path / "samples" / "factorial.nif"
    absolute_span = make_source_span(path=str(absolute_source), start_offset=4, end_offset=12, line=2, start_column=3)
    synthetic_span = make_source_span(path="<memory>", start_offset=0, end_offset=4)
    program = one_function_backend_program()
    callable_decl = program.callables[0]
    register = replace(callable_decl.registers[0], span=synthetic_span)
    instruction = replace(callable_decl.blocks[0].instructions[0], span=absolute_span)
    terminator = replace(callable_decl.blocks[0].terminator, span=absolute_span)
    block = replace(callable_decl.blocks[0], instructions=(instruction,), terminator=terminator, span=absolute_span)
    callable_decl = replace(callable_decl, registers=(register,), blocks=(block,), span=absolute_span)
    program = replace(program, callables=(callable_decl,))

    payload = backend_program_to_dict(program, project_root=tmp_path)
    register_span = payload["callables"][0]["registers"][0]["span"]
    instruction_span = payload["callables"][0]["blocks"][0]["instructions"][0]["span"]

    assert register_span["start"]["path"] == "<memory>"
    assert instruction_span["start"] == {
        "path": "samples/factorial.nif",
        "offset": 4,
        "line": 2,
        "column": 3,
    }
    assert instruction_span["end"] == {
        "path": "samples/factorial.nif",
        "offset": 12,
        "line": 2,
        "column": 11,
    }


def test_dump_backend_program_json_preserves_double_raw_bits_for_signed_zero_infinities_and_nan_payloads() -> None:
    callable_id = FunctionId(module_path=("fixture", "backend_ir"), name="double_bits")
    span = make_source_span(path="fixtures/doubles.nif")
    registers = tuple(
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=ordinal),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64 if ordinal == 4 else "double"),
            debug_name=f"tmp{ordinal}",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        )
        for ordinal in range(5)
    )
    nan_value = struct.unpack("<d", struct.pack("<Q", 0x7ff8000000000001))[0]
    instructions = (
        BackendConstInst(
            inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
            dest=registers[0].reg_id,
            constant=BackendDoubleConst(value=-0.0),
            span=span,
        ),
        BackendConstInst(
            inst_id=BackendInstId(owner_id=callable_id, ordinal=1),
            dest=registers[1].reg_id,
            constant=BackendDoubleConst(value=float("inf")),
            span=span,
        ),
        BackendConstInst(
            inst_id=BackendInstId(owner_id=callable_id, ordinal=2),
            dest=registers[2].reg_id,
            constant=BackendDoubleConst(value=float("-inf")),
            span=span,
        ),
        BackendConstInst(
            inst_id=BackendInstId(owner_id=callable_id, ordinal=3),
            dest=registers[3].reg_id,
            constant=BackendDoubleConst(value=nan_value),
            span=span,
        ),
        BackendConstInst(
            inst_id=BackendInstId(owner_id=callable_id, ordinal=4),
            dest=registers[4].reg_id,
            constant=BackendIntConst(type_name=TYPE_NAME_I64, value=0),
            span=span,
        ),
    )
    callable_decl = BackendCallableDecl(
        callable_id=callable_id,
        kind="function",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=registers,
        param_regs=(),
        receiver_reg=None,
        entry_block_id=BackendBlockId(owner_id=callable_id, ordinal=0),
        blocks=(
            BackendBlock(
                block_id=BackendBlockId(owner_id=callable_id, ordinal=0),
                debug_name="entry",
                instructions=instructions,
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=registers[4].reg_id)),
                span=span,
            ),
        ),
        span=span,
    )
    program = BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=callable_id,
        data_blobs=(),
        interfaces=(),
        classes=(),
        callables=(callable_decl,),
    )

    payload = backend_program_to_dict(program)
    dumped = dump_backend_program_json(program)
    constants = [instruction["constant"] for instruction in payload["callables"][0]["blocks"][0]["instructions"][:4]]

    assert constants == [
        {"kind": "double", "bits_hex": "8000000000000000"},
        {"kind": "double", "bits_hex": "7ff0000000000000"},
        {"kind": "double", "bits_hex": "fff0000000000000"},
        {"kind": "double", "bits_hex": "7ff8000000000001"},
    ]
    assert dump_backend_program_json(load_backend_program_json(dumped)) == dumped


def test_backend_program_to_dict_canonicalizes_data_callable_register_block_and_instruction_order() -> None:
    callable_id = FunctionId(module_path=("fixture", "backend_ir"), name="sort_demo")
    helper_id = FunctionId(module_path=("fixture", "backend_ir"), name="aaa")
    span = make_source_span(path="fixtures/ordering.nif")
    registers = (
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=2),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            debug_name="r2",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=0),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            debug_name="r0",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
        BackendRegister(
            reg_id=BackendRegId(owner_id=callable_id, ordinal=1),
            type_ref=semantic_primitive_type_ref(TYPE_NAME_I64),
            debug_name="r1",
            origin_kind="temp",
            semantic_local_id=None,
            span=None,
        ),
    )
    exit_block_id = BackendBlockId(owner_id=callable_id, ordinal=1)
    entry_block_id = BackendBlockId(owner_id=callable_id, ordinal=0)
    callable_decl = BackendCallableDecl(
        callable_id=callable_id,
        kind="function",
        signature=BackendSignature(param_types=(), return_type=semantic_primitive_type_ref(TYPE_NAME_I64)),
        is_export=False,
        is_extern=False,
        is_static=None,
        is_private=None,
        registers=registers,
        param_regs=(),
        receiver_reg=None,
        entry_block_id=entry_block_id,
        blocks=(
            BackendBlock(
                block_id=exit_block_id,
                debug_name="exit",
                instructions=(),
                terminator=BackendReturnTerminator(span=span, value=BackendRegOperand(reg_id=BackendRegId(owner_id=callable_id, ordinal=1))),
                span=span,
            ),
            BackendBlock(
                block_id=entry_block_id,
                debug_name="entry",
                instructions=(
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=1),
                        dest=BackendRegId(owner_id=callable_id, ordinal=1),
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=2),
                        span=span,
                    ),
                    BackendConstInst(
                        inst_id=BackendInstId(owner_id=callable_id, ordinal=0),
                        dest=BackendRegId(owner_id=callable_id, ordinal=0),
                        constant=BackendIntConst(type_name=TYPE_NAME_I64, value=1),
                        span=span,
                    ),
                ),
                terminator=BackendJumpTerminator(span=span, target_block_id=exit_block_id),
                span=span,
            ),
        ),
        span=span,
    )
    helper_callable = replace(one_function_backend_program().callables[0], callable_id=helper_id)
    program = BackendProgram(
        schema_version=BACKEND_IR_SCHEMA_VERSION,
        entry_callable_id=helper_id,
        data_blobs=(
            BackendDataBlob(data_id=BackendDataId(ordinal=2), debug_name="d2", alignment=1, bytes_hex="22", readonly=True),
            BackendDataBlob(data_id=BackendDataId(ordinal=0), debug_name="d0", alignment=1, bytes_hex="00", readonly=True),
            BackendDataBlob(data_id=BackendDataId(ordinal=1), debug_name="d1", alignment=1, bytes_hex="11", readonly=True),
        ),
        interfaces=(),
        classes=(),
        callables=(callable_decl, helper_callable),
    )

    payload = backend_program_to_dict(program)

    assert [blob["id"] for blob in payload["data_blobs"]] == ["d0", "d1", "d2"]
    assert [blob["content_kind"] for blob in payload["data_blobs"]] == ["raw", "raw", "raw"]
    assert [callable_data["callable_id"]["name"] for callable_data in payload["callables"]] == ["aaa", "sort_demo"]
    assert [register["id"] for register in payload["callables"][1]["registers"]] == ["r0", "r1", "r2"]
    assert [block["id"] for block in payload["callables"][1]["blocks"]] == ["b0", "b1"]
    assert [instruction["id"] for instruction in payload["callables"][1]["blocks"][0]["instructions"]] == ["i0", "i1"]


@pytest.mark.parametrize(
    ("mutator", "expected_message"),
    [
        (
            lambda payload: payload | {"schema_version": "niflheim.backend-ir.v2"},
            "Unsupported backend IR schema_version 'niflheim.backend-ir.v2'",
        ),
        (
            lambda payload: _replace_nested(payload, ("callables", 0, "span", "start"), {"path": "fixtures/function.nif", "offset": 0, "column": 1}),
            "Malformed backend IR source span start: missing 'line'",
        ),
        (
            lambda payload: _replace_nested(payload, ("callables", 0, "blocks", 0, "instructions", 0, "constant"), {"kind": "double", "bits_hex": "1"}),
            "Malformed backend IR double constant: bits_hex must contain exactly 16 lower-case hexadecimal digits",
        ),
        (
            lambda payload: _replace_nested(payload, ("callables", 0, "blocks", 0, "instructions", 0, "kind"), "bogus"),
            "Unsupported backend IR instruction kind 'bogus'",
        ),
    ],
)
def test_backend_program_from_dict_rejects_malformed_json(mutator, expected_message: str) -> None:
    payload = json.loads(dump_backend_program_json(one_function_backend_program()))
    malformed_payload = mutator(payload)

    with pytest.raises(ValueError, match=expected_message):
        backend_program_from_dict(malformed_payload)


def _replace_nested(payload: object, path: tuple[object, ...], replacement: object) -> object:
    if not path:
        return replacement

    head, *tail = path
    if isinstance(head, int):
        items = list(payload)
        items[head] = _replace_nested(items[head], tuple(tail), replacement)
        return items

    updated = dict(payload)
    updated[head] = _replace_nested(updated[head], tuple(tail), replacement)
    return updated