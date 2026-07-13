#include "intstack.h"

void intstack_init(IntStack *stack) { stack->count = 0; }

int intstack_push(IntStack *stack, int value) {
    if (intstack_is_full(stack)) {
        return -1;
    }
    stack->items[stack->count] = value;
    stack->count += 1;
    return 0;
}

int intstack_pop(IntStack *stack, int *out) {
    if (intstack_is_empty(stack)) {
        return -1;
    }
    stack->count -= 1;
    *out = stack->items[stack->count];
    return 0;
}

int intstack_is_empty(const IntStack *stack) { return stack->count == 0; }

int intstack_is_full(const IntStack *stack) { return stack->count == INTSTACK_CAPACITY; }
