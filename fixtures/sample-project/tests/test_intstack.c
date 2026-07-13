#include <stdio.h>

#include "intstack.h"

static int failures = 0;

#define CHECK(name, cond, msg)                                                                     \
    do {                                                                                           \
        if (cond) {                                                                                \
            printf("[PASS] %s\n", name);                                                           \
        } else {                                                                                   \
            printf("[FAIL] %s: %s\n", name, msg);                                                  \
            failures++;                                                                            \
        }                                                                                          \
    } while (0)

static void test_push_and_pop(void) {
    IntStack stack;
    intstack_init(&stack);
    intstack_push(&stack, 1);
    intstack_push(&stack, 2);

    int value = 0;
    CHECK("test_push_and_pop_lifo_order", intstack_pop(&stack, &value) == 0 && value == 2,
          "expected pop to return the most recently pushed value");
    CHECK("test_push_and_pop_second_value", intstack_pop(&stack, &value) == 0 && value == 1,
          "expected the second pop to return the first pushed value");
    CHECK("test_push_and_pop_now_empty", intstack_is_empty(&stack),
          "expected stack to be empty after both pops");
}

static void test_pop_empty_fails(void) {
    IntStack stack;
    intstack_init(&stack);

    int value = 0;
    CHECK("test_pop_empty_fails", intstack_pop(&stack, &value) != 0,
          "expected pop on an empty stack to fail");
}

static void test_push_overflow_fails(void) {
    IntStack stack;
    intstack_init(&stack);
    for (int i = 0; i < INTSTACK_CAPACITY; i++) {
        intstack_push(&stack, i);
    }

    CHECK("test_push_overflow_fails", intstack_push(&stack, 99) != 0,
          "expected push beyond INTSTACK_CAPACITY to fail");
}

int main(void) {
    test_push_and_pop();
    test_pop_empty_fails();
    test_push_overflow_fails();
    return failures == 0 ? 0 : 1;
}
