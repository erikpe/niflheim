from __future__ import annotations

from compiler.backend.ir import (
	BackendArrayAllocInst,
	BackendArrayLengthInst,
	BackendArrayLoadInst,
	BackendArraySliceInst,
	BackendArraySliceStoreInst,
	BackendArrayStoreInst,
	BackendBoundsCheckInst,
	BackendCallInst,
	BackendCastInst,
	BackendConstOperand,
	BackendDataOperand,
	BackendDirectCallTarget,
	BackendNullCheckInst,
	BackendRegOperand,
	BackendRuntimeCallTarget,
	BackendTypeTestInst,
	BackendVirtualCallTarget,
)
from compiler.backend.ir.verify import verify_backend_program
from compiler.codegen.abi.runtime import ARRAY_FROM_BYTES_U8_RUNTIME_CALL, runtime_call_metadata
from compiler.common.collection_protocols import ArrayRuntimeKind
from tests.compiler.backend.lowering.helpers import block_by_ordinal, callable_by_name, lower_source_to_backend_program


def test_lower_to_backend_ir_lowers_array_instructions_and_explicit_checks(tmp_path) -> None:
	program = lower_source_to_backend_program(
		tmp_path,
		"""
		fn arrays(values: i64[]) -> u64 {
			var first: i64 = values[0];
			values[1] = first;
			var part: i64[] = values[0:2];
			values[0:2] = part;
			return values.len();
		}

		fn main() -> i64 {
			var values: i64[] = i64[](3u);
			return 0;
		}
		""",
		skip_optimize=True,
	)

	arrays_callable = callable_by_name(program, "arrays")
	arrays_instructions = list(block_by_ordinal(arrays_callable, 0).instructions)

	assert [type(instruction) for instruction in arrays_instructions] == [
		BackendNullCheckInst,
		BackendBoundsCheckInst,
		BackendArrayLoadInst,
		BackendNullCheckInst,
		BackendBoundsCheckInst,
		BackendArrayStoreInst,
		BackendNullCheckInst,
		BackendBoundsCheckInst,
		BackendBoundsCheckInst,
		BackendArraySliceInst,
		BackendNullCheckInst,
		BackendBoundsCheckInst,
		BackendBoundsCheckInst,
		BackendArraySliceStoreInst,
		BackendArrayLengthInst,
	]
	assert arrays_instructions[2].array_runtime_kind is ArrayRuntimeKind.I64
	assert arrays_instructions[5].array_runtime_kind is ArrayRuntimeKind.I64
	assert arrays_instructions[9].array_runtime_kind is ArrayRuntimeKind.I64
	assert arrays_instructions[13].array_runtime_kind is ArrayRuntimeKind.I64

	main_callable = callable_by_name(program, "main")
	main_instructions = list(block_by_ordinal(main_callable, 0).instructions)
	assert isinstance(main_instructions[0], BackendArrayAllocInst)
	assert main_instructions[0].array_runtime_kind is ArrayRuntimeKind.I64


def test_lower_to_backend_ir_lowers_for_in_as_cfg_with_direct_array_fast_path(tmp_path) -> None:
	program = lower_source_to_backend_program(
		tmp_path,
		"""
		fn sum(values: i64[]) -> i64 {
			var total: i64 = 0;
			for item in values {
				total = total + item;
			}
			return total;
		}

		fn main() -> i64 {
			return sum(i64[](0u));
		}
		""",
		skip_optimize=True,
	)

	sum_callable = callable_by_name(program, "sum")
	debug_names = [block.debug_name for block in sum_callable.blocks]
	assert debug_names[:5] == [
		"entry",
		"forin.cond",
		"forin.body",
		"forin.step",
		"forin.exit",
	]
	assert "forin.body_to_step" in debug_names

	all_instructions = [instruction for block in sum_callable.blocks for instruction in block.instructions]
	assert not any(isinstance(instruction, BackendCallInst) for instruction in all_instructions)

	body_instructions = list(block_by_ordinal(sum_callable, 2).instructions)
	assert isinstance(body_instructions[0], BackendNullCheckInst)
	assert isinstance(body_instructions[1], BackendBoundsCheckInst)
	assert isinstance(body_instructions[2], BackendArrayLoadInst)


def test_lower_to_backend_ir_prunes_unreachable_for_in_step_after_early_return(tmp_path) -> None:
	program = lower_source_to_backend_program(
		tmp_path,
		"""
		class IterBase {
			fn iter_len() -> u64 {
				return 1u;
			}

			fn iter_get(index: i64) -> i64 {
				return 42;
			}
		}

		fn read(values: IterBase) -> i64 {
			for item in values {
				return item;
			}
			return 0;
		}

		fn main() -> i64 {
			return read(IterBase());
		}
		""",
	)

	verify_backend_program(program)
	read_callable = callable_by_name(program, "read")
	assert "forin.step" not in [block.debug_name for block in read_callable.blocks]


def test_lower_to_backend_ir_lowers_virtual_collection_dispatch_as_calls(tmp_path) -> None:
	program = lower_source_to_backend_program(
		tmp_path,
		"""
		class Buffer {
			fn index_get(index: i64) -> i64 {
				return index;
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
		}

		fn use(buffer: Buffer) -> i64 {
			var first: i64 = buffer[0];
			buffer[0] = first;
			var part: Buffer = buffer[0:1];
			buffer[0:1] = part;
			return first;
		}

		fn main() -> i64 {
			return use(Buffer());
		}
		""",
		skip_optimize=True,
	)

	use_callable = callable_by_name(program, "use")
	calls = [instruction for instruction in block_by_ordinal(use_callable, 0).instructions if isinstance(instruction, BackendCallInst)]

	assert len(calls) == 4
	assert [type(call.target) for call in calls] == [
		BackendVirtualCallTarget,
		BackendVirtualCallTarget,
		BackendVirtualCallTarget,
		BackendVirtualCallTarget,
	]
	assert [call.target.method_name for call in calls] == [
		"index_get",
		"index_set",
		"slice_get",
		"slice_set",
	]


def test_lower_to_backend_ir_coerces_interface_typed_for_in_receiver_for_devirtualized_dispatch(tmp_path) -> None:
	program = lower_source_to_backend_program(
		tmp_path,
		"""
		interface IterSeq {
			fn iter_len() -> u64;
			fn iter_get(index: i64) -> i64;
		}

		class InterfaceSeq implements IterSeq {
			values: i64[];

			fn iter_len() -> u64 {
				return __self.values.len();
			}

			fn iter_get(index: i64) -> i64 {
				return __self.values[index];
			}
		}

		fn sum(values: IterSeq) -> i64 {
			var total: i64 = 0;
			for item in values {
				total = total + item;
			}
			return total;
		}

		fn main() -> i64 {
			var raw: i64[] = i64[](1u);
			raw[0] = 7;
			return sum((IterSeq)InterfaceSeq(raw));
		}
		""",
	)

	sum_callable = callable_by_name(program, "sum")
	instructions = [instruction for block in sum_callable.blocks for instruction in block.instructions]
	calls = [instruction for instruction in instructions if isinstance(instruction, BackendCallInst)]
	casts = [instruction for instruction in instructions if isinstance(instruction, BackendCastInst)]

	assert len(calls) == 2
	assert all(isinstance(call.target, BackendDirectCallTarget) for call in calls)
	assert [call.target.callable_id.name for call in calls] == ["iter_len", "iter_get"]

	interface_seq_cast_dests = {
		cast.dest
		for cast in casts
		if cast.target_type_ref.class_id is not None and cast.target_type_ref.class_id.name == "InterfaceSeq"
	}
	assert interface_seq_cast_dests
	assert all(isinstance(call.args[0], BackendRegOperand) for call in calls)
	assert all(call.args[0].reg_id in interface_seq_cast_dests for call in calls)


def test_lower_to_backend_ir_lowers_casts_and_pools_string_literal_byte_blobs(tmp_path) -> None:
	program = lower_source_to_backend_program(
		tmp_path,
		"""
		interface Hashable {
			fn hash_code() -> u64;
		}

		class Key implements Hashable {
			fn hash_code() -> u64 {
				return 1u;
			}
		}

		class Str {
			static fn from_u8_array(value: u8[]) -> Str {
				return Str();
			}
		}

		fn cast_and_test(value: Obj) -> bool {
			var hashable: Hashable = (Hashable)value;
			return value is Hashable;
		}

		fn bytes1() -> Str {
			return "hi";
		}

		fn bytes2() -> Str {
			return "hi";
		}

		fn main() -> i64 {
			return 0;
		}
		""",
		skip_optimize=True,
	)

	cast_callable = callable_by_name(program, "cast_and_test")
	cast_instructions = list(block_by_ordinal(cast_callable, 0).instructions)
	assert isinstance(cast_instructions[0], BackendCastInst)
	assert cast_instructions[0].trap_on_failure is True
	assert isinstance(cast_instructions[1], BackendTypeTestInst)

	bytes1_callable = callable_by_name(program, "bytes1")
	bytes2_callable = callable_by_name(program, "bytes2")
	bytes1_call = block_by_ordinal(bytes1_callable, 0).instructions[0]
	bytes2_call = block_by_ordinal(bytes2_callable, 0).instructions[0]

	assert isinstance(bytes1_call, BackendCallInst)
	assert isinstance(bytes1_call.target, BackendRuntimeCallTarget)
	assert bytes1_call.target.name == ARRAY_FROM_BYTES_U8_RUNTIME_CALL
	assert bytes1_call.target.ref_arg_indices == runtime_call_metadata(ARRAY_FROM_BYTES_U8_RUNTIME_CALL).ref_arg_indices
	assert isinstance(bytes1_call.args[0], BackendDataOperand)
	assert isinstance(bytes1_call.args[1], BackendConstOperand)

	assert isinstance(bytes2_call, BackendCallInst)
	assert isinstance(bytes2_call.target, BackendRuntimeCallTarget)
	assert isinstance(bytes2_call.args[0], BackendDataOperand)
	assert bytes2_call.args[0].data_id == bytes1_call.args[0].data_id

	assert len(program.data_blobs) == 1
	assert program.data_blobs[0].content_kind == "string"
	assert program.data_blobs[0].bytes_hex == "6869"
