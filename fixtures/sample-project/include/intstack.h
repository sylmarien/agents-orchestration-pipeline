#ifndef INTSTACK_H
#define INTSTACK_H

#define INTSTACK_CAPACITY 32

typedef struct {
    int items[INTSTACK_CAPACITY];
    int count;
} IntStack;

void intstack_init(IntStack *stack);

/* Returns 0 on success, -1 if the stack is already at INTSTACK_CAPACITY. */
int intstack_push(IntStack *stack, int value);

/* Pops the top value into *out. Returns 0 on success, -1 if the stack is empty. */
int intstack_pop(IntStack *stack, int *out);

int intstack_is_empty(const IntStack *stack);
int intstack_is_full(const IntStack *stack);

#endif
