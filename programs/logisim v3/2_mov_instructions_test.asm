; test MOV B, A
ldbi 22
ldai 00
mov b, a
ldbi 22
sub
jmpnz fail_mov_b_a

; test MOV X, A
ldxi 33
ldai 00
mov x, a
ldbi 33
sub
jmpnz fail_mov_x_a

; test MOV A, B
ldai 44
ldbi 00
mov a, b
ldai 00
mov b, a
ldbi 44
sub
jmpnz fail_mov_a_b

; test MOV X, B
ldxi 55
ldbi 00
mov x, b
ldai 00
mov b, a
ldbi 55
sub
jmpnz fail_mov_x_b

; test MOV A, X
ldai 66
ldxi 00
mov a, x
ldai 00
mov x, a
ldbi 66
sub
jmpnz fail_mov_a_x

; test MOV B, X
ldbi 77
ldxi 00
mov b, x
ldai 00
mov x, a
ldbi 77
sub
jmpnz fail_mov_b_x

passed:
ldai AA
outa
halt

fail_mov_b_a:
ldai E1
outa
halt

fail_mov_x_a:
ldai E2
outa
halt

fail_mov_a_b:
ldai E3
outa
halt

fail_mov_x_b:
ldai E4
outa
halt

fail_mov_a_x:
ldai E5
outa
halt

fail_mov_b_x:
ldai E6
outa
halt