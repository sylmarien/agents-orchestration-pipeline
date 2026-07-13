CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Iinclude

.PHONY: build test format-check lint clean

build: bin/intstack.o

bin/intstack.o: src/intstack.c include/intstack.h
	@mkdir -p bin
	$(CC) $(CFLAGS) -c src/intstack.c -o bin/intstack.o

bin/intstack_test: src/intstack.c tests/test_intstack.c include/intstack.h
	@mkdir -p bin
	$(CC) $(CFLAGS) -o bin/intstack_test src/intstack.c tests/test_intstack.c

test: bin/intstack_test
	./bin/intstack_test

format-check:
	clang-format --dry-run -Werror src/*.c include/*.h tests/*.c

lint:
	clang-tidy src/*.c -- $(CFLAGS)

clean:
	rm -rf bin
