CC := cc
CFLAGS := -std=c11 -Wall -Wextra -Werror -Iinclude

RUNTIME_SRC := src/runtime.c src/gc.c
RUNTIME_OBJ := $(RUNTIME_SRC:.c=.o)

all: libruntime.a

libruntime.a: $(RUNTIME_OBJ)
	ar rcs $@ $^

clean:
	rm -f $(RUNTIME_OBJ) libruntime.a
