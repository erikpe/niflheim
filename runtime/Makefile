CC := cc
CFLAGS := -std=c11 -Wall -Wextra -Werror -Iinclude

RUNTIME_SRC := src/runtime.c src/gc.c src/str.c src/box.c src/vec.c
RUNTIME_OBJ := $(RUNTIME_SRC:.c=.o)
TEST_DIR := tests
GC_STRESS_BIN := $(TEST_DIR)/test_gc_stress
GC_STRESS_SRC := $(TEST_DIR)/test_gc_stress.c
ROOTS_POSITIVE_BIN := $(TEST_DIR)/test_roots_positive
ROOTS_POSITIVE_SRC := $(TEST_DIR)/test_roots_positive.c
ROOTS_NEGATIVE_BIN := $(TEST_DIR)/test_roots_negative
ROOTS_NEGATIVE_SRC := $(TEST_DIR)/test_roots_negative.c

all: libruntime.a

libruntime.a: $(RUNTIME_OBJ)
	ar rcs $@ $^

$(GC_STRESS_BIN): $(GC_STRESS_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(GC_STRESS_SRC) $(RUNTIME_SRC)

$(ROOTS_POSITIVE_BIN): $(ROOTS_POSITIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(ROOTS_POSITIVE_SRC) $(RUNTIME_SRC)

$(ROOTS_NEGATIVE_BIN): $(ROOTS_NEGATIVE_SRC) $(RUNTIME_SRC) include/runtime.h
	$(CC) $(CFLAGS) -o $@ $(ROOTS_NEGATIVE_SRC) $(RUNTIME_SRC)

test: $(GC_STRESS_BIN)
	./$(GC_STRESS_BIN)

test-positive: $(ROOTS_POSITIVE_BIN)
	./$(ROOTS_POSITIVE_BIN)

test-negative: $(ROOTS_NEGATIVE_BIN)
	@for c in pop_underflow slot_store_oob slot_load_oob register_global_null unregister_global_null; do \
		if ./$(ROOTS_NEGATIVE_BIN) $$c >/dev/null 2>&1; then \
			echo "test_roots_negative[$$c]: expected failure but process exited successfully"; \
			exit 1; \
		else \
			echo "test_roots_negative[$$c]: ok (failed as expected)"; \
		fi; \
	done

test-all: test test-positive test-negative

clean:
	rm -f $(RUNTIME_OBJ) libruntime.a $(GC_STRESS_BIN) $(ROOTS_POSITIVE_BIN) $(ROOTS_NEGATIVE_BIN)
