CC := cc
CFLAGS := -std=c11 -Wall -Wextra -Werror -Iinclude

RUNTIME_SRC := src/runtime.c src/gc.c src/gc_trace.c src/gc_tracked_set.c src/io.c src/array.c src/panic.c
RUNTIME_OBJ := $(RUNTIME_SRC:.c=.o)
TEST_DIR := ../tests/runtime
GC_STRESS_BIN := $(TEST_DIR)/test_gc_stress
GC_STRESS_SRC := $(TEST_DIR)/test_gc_stress.c
ROOTS_POSITIVE_BIN := $(TEST_DIR)/test_roots_positive
ROOTS_POSITIVE_SRC := $(TEST_DIR)/test_roots_positive.c
ROOTS_NEGATIVE_BIN := $(TEST_DIR)/test_roots_negative
ROOTS_NEGATIVE_SRC := $(TEST_DIR)/test_roots_negative.c
ARRAY_RUNTIME_BIN := $(TEST_DIR)/test_array_runtime
ARRAY_RUNTIME_SRC := $(TEST_DIR)/test_array_runtime.c
ARRAY_NEGATIVE_BIN := $(TEST_DIR)/test_array_negative
ARRAY_NEGATIVE_SRC := $(TEST_DIR)/test_array_negative.c
INTERFACE_METADATA_BIN := $(TEST_DIR)/test_interface_metadata
INTERFACE_METADATA_SRC := $(TEST_DIR)/test_interface_metadata.c
INTERFACE_CASTS_BIN := $(TEST_DIR)/test_interface_casts
INTERFACE_CASTS_SRC := $(TEST_DIR)/test_interface_casts.c
INTERFACE_CASTS_NEGATIVE_BIN := $(TEST_DIR)/test_interface_casts_negative
INTERFACE_CASTS_NEGATIVE_SRC := $(TEST_DIR)/test_interface_casts_negative.c
INTERFACE_DISPATCH_BIN := $(TEST_DIR)/test_interface_dispatch
INTERFACE_DISPATCH_SRC := $(TEST_DIR)/test_interface_dispatch.c
INTERFACE_DISPATCH_NEGATIVE_BIN := $(TEST_DIR)/test_interface_dispatch_negative
INTERFACE_DISPATCH_NEGATIVE_SRC := $(TEST_DIR)/test_interface_dispatch_negative.c
TRACKED_SET_TOMBSTONES_BIN := $(TEST_DIR)/test_tracked_set_tombstones
TRACKED_SET_TOMBSTONES_SRC := $(TEST_DIR)/test_tracked_set_tombstones.c
NEGATIVE_DRIVER := $(TEST_DIR)/run_negative_driver.sh

all: libruntime.a

libruntime.a: $(RUNTIME_OBJ)
	ar rcs $@ $^

$(GC_STRESS_BIN): $(GC_STRESS_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(GC_STRESS_SRC) $(RUNTIME_SRC)

$(ROOTS_POSITIVE_BIN): $(ROOTS_POSITIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(ROOTS_POSITIVE_SRC) $(RUNTIME_SRC)

$(ROOTS_NEGATIVE_BIN): $(ROOTS_NEGATIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(ROOTS_NEGATIVE_SRC) $(RUNTIME_SRC)

$(ARRAY_RUNTIME_BIN): $(ARRAY_RUNTIME_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(ARRAY_RUNTIME_SRC) $(RUNTIME_SRC)

$(ARRAY_NEGATIVE_BIN): $(ARRAY_NEGATIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(ARRAY_NEGATIVE_SRC) $(RUNTIME_SRC)

$(INTERFACE_METADATA_BIN): $(INTERFACE_METADATA_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(INTERFACE_METADATA_SRC) $(RUNTIME_SRC)

$(INTERFACE_CASTS_BIN): $(INTERFACE_CASTS_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(INTERFACE_CASTS_SRC) $(RUNTIME_SRC)

$(INTERFACE_CASTS_NEGATIVE_BIN): $(INTERFACE_CASTS_NEGATIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(INTERFACE_CASTS_NEGATIVE_SRC) $(RUNTIME_SRC)

$(INTERFACE_DISPATCH_BIN): $(INTERFACE_DISPATCH_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(INTERFACE_DISPATCH_SRC) $(RUNTIME_SRC)

$(INTERFACE_DISPATCH_NEGATIVE_BIN): $(INTERFACE_DISPATCH_NEGATIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(INTERFACE_DISPATCH_NEGATIVE_SRC) $(RUNTIME_SRC)

$(TRACKED_SET_TOMBSTONES_BIN): $(TRACKED_SET_TOMBSTONES_SRC) $(RUNTIME_SRC) include/runtime.h include/gc_tracked_set.h
	$(CC) $(CFLAGS) -o $@ $(TRACKED_SET_TOMBSTONES_SRC) $(RUNTIME_SRC)

test: $(GC_STRESS_BIN)
	./$(GC_STRESS_BIN)

test-positive: $(ROOTS_POSITIVE_BIN)
	./$(ROOTS_POSITIVE_BIN)

test-negative: $(ROOTS_NEGATIVE_BIN) $(NEGATIVE_DRIVER)
	@$(NEGATIVE_DRIVER) test_roots_negative ./$(ROOTS_NEGATIVE_BIN) \
		pop_underflow \
		slot_store_oob \
		slot_load_oob \
		register_global_null \
		unregister_global_null

test-array: $(ARRAY_RUNTIME_BIN)
	./$(ARRAY_RUNTIME_BIN)

test-array-negative: $(ARRAY_NEGATIVE_BIN) $(NEGATIVE_DRIVER)
	@$(NEGATIVE_DRIVER) test_array_negative ./$(ARRAY_NEGATIVE_BIN) \
		"get_negative::panic: rt_array_get_u8: index out of bounds" \
		"slice_negative::panic: rt_array_slice_u8: invalid slice range"

test-interface-metadata: $(INTERFACE_METADATA_BIN)
	./$(INTERFACE_METADATA_BIN)

test-interface-casts: $(INTERFACE_CASTS_BIN)
	./$(INTERFACE_CASTS_BIN)

test-interface-casts-negative: $(INTERFACE_CASTS_NEGATIVE_BIN) $(NEGATIVE_DRIVER)
	@$(NEGATIVE_DRIVER) test_interface_casts_negative ./$(INTERFACE_CASTS_NEGATIVE_BIN) \
		"non_implementing_object::panic: bad cast (Plain -> Hashable)" \
		"interface_to_interface_failure::panic: bad cast (HashOnly -> Equalable)"

test-interface-dispatch: $(INTERFACE_DISPATCH_BIN)
	./$(INTERFACE_DISPATCH_BIN)

test-interface-dispatch-negative: $(INTERFACE_DISPATCH_NEGATIVE_BIN) $(NEGATIVE_DRIVER)
	@$(NEGATIVE_DRIVER) test_interface_dispatch_negative ./$(INTERFACE_DISPATCH_NEGATIVE_BIN) \
		"null_receiver::panic: null dereference" \
		"missing_interface::panic: bad cast (Plain -> Hashable)" \
		"slot_out_of_bounds::panic: interface dispatch: invalid interface method slot"

test-tracked-set-tombstones: $(TRACKED_SET_TOMBSTONES_BIN)
	./$(TRACKED_SET_TOMBSTONES_BIN)

test-all: test test-positive test-negative test-array test-array-negative test-interface-metadata test-interface-casts test-interface-casts-negative test-interface-dispatch test-interface-dispatch-negative test-tracked-set-tombstones

clean:
	rm -f $(RUNTIME_OBJ) libruntime.a $(GC_STRESS_BIN) $(ROOTS_POSITIVE_BIN) $(ROOTS_NEGATIVE_BIN) $(ARRAY_RUNTIME_BIN) $(ARRAY_NEGATIVE_BIN) $(INTERFACE_METADATA_BIN) $(INTERFACE_CASTS_BIN) $(INTERFACE_CASTS_NEGATIVE_BIN) $(INTERFACE_DISPATCH_BIN) $(INTERFACE_DISPATCH_NEGATIVE_BIN) $(TRACKED_SET_TOMBSTONES_BIN)
