CC := cc
CFLAGS := -std=c11 -Wall -Wextra -Werror -Iinclude

RUNTIME_SRC := src/runtime.c src/gc.c src/io.c src/str.c src/box.c src/vec.c src/array.c
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

test-all: test test-positive test-negative test-array test-array-negative

clean:
	rm -f $(RUNTIME_OBJ) libruntime.a $(GC_STRESS_BIN) $(ROOTS_POSITIVE_BIN) $(ROOTS_NEGATIVE_BIN) $(ARRAY_RUNTIME_BIN) $(ARRAY_NEGATIVE_BIN)
