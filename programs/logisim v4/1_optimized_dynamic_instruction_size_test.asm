; Expected success:
; OUT = AA

; Failure:
; OUT = E0 -> a conditional jump was taken when it should not be
; OUT = E1 -> normal opcode-only / ALU / MOV / INCX test failed
; early halt/no AA -> false conditional path did not consume operand

jmp main

noop
noop
noop
noop
noop
noop
noop
noop
noop
noop
noop
noop

fail_cond:
ldai E0
outa
halt

main:
noop

; SUB / JMPZ test: 0x42 - 0x42 = 0
ldai 42
ldbi 42
sub
jmpz test_add
jmp fail_normal

test_add:
; 1 + 2 = 3
ldai 01
ldbi 02
add
ldbi 03
sub
jmpz test_sub
jmp fail_normal

test_sub:
; 5 - 2 = 3
ldai 05
ldbi 02
sub
ldbi 03
sub
jmpz test_and
jmp fail_normal

test_and:
; F0 AND 0F = 00
ldai F0
ldbi 0F
and
jmpz test_or
jmp fail_normal

test_or:
; F0 OR 0F = FF
ldai F0
ldbi 0F
or
ldbi FF
sub
jmpz test_xor
jmp fail_normal

test_xor:
; AA XOR FF = 55
ldai AA
ldbi FF
xor
ldbi 55
sub
jmpz test_incx
jmp fail_normal

test_incx:
; X = 03, INCX -> 04, MOV X,A, compare with 04
ldxi 03
incx
mov x, a
ldbi 04
sub
jmpz test_mov_ab_ba
jmp fail_normal

test_mov_ab_ba:
; MOV A,B then MOV B,A
ldai 66
mov a, b
ldai 00
mov b, a
ldbi 66
sub
jmpz test_mov_ax_xb
jmp fail_normal

test_mov_ax_xb:
; MOV A,X then MOV X,B
ldai 77
mov a, x
ldbi 00
mov x, b
ldai 77
sub
jmpz test_mov_bx_xa
jmp fail_normal

test_mov_bx_xa:
; MOV B,X then MOV X,A
ldbi 55
mov b, x
ldai 00
mov x, a
ldbi 55
sub
jmpz test_false_jumps
jmp fail_normal

test_false_jumps:
; These must not jump.
; Their operand is 0E, which points to fail_cond.
; If false path does not consume operand, 0E executes as HALT.

; 1 + 0 = 1
; C=0, Z=0, N=0, V=0
ldai 01
ldbi 00
add
jmpc fail_cond
jmpz fail_cond
jmpn fail_cond
jmpovr fail_cond

; FF + 01 = 00
; C=1, Z=1
; So JMPNC and JMPNZ must not jump.
ldai FF
ldbi 01
add
jmpnc fail_cond
jmpnz fail_cond

; FF + 00 = FF
; N=1
; So JMPNN must NOT jump.
ldai FF
ldbi 00
add
jmpnn fail_cond

; 7F + 01 = 80
; OVF=1
; So JMPNOVR must NOT jump.
ldai 7F
ldbi 01
add
jmpnovr fail_cond

success:
ldai AA
outa
halt

fail_normal:
ldai E1
outa
halt

08 12 00 00 00 00 00 00 00 00 00 00 00 00 05 E0 07 0E 00 05 42 06 42 04 11 1C 08 AF 05 01 06 02 03 06 03 04 11 28 08 AF 05 05 06 02 04 06 03 04 11 34 08 AF 05 F0 06 0F 09 11 3D 08 AF 05 F0 06 0F 0A 06 FF 04 11 49 08 AF 05 AA 06 FF 0B 06 55 04 11 55 08 AF 19 03 1B 20 06 04 04 11 60 08 AF 05 66 1C 05 00 1E 06 66 04 11 6D 08 AF 05 77 1D 06 00 21 05 77 04 11 7A 08 AF 06 55 1F 05 00 20 06 55 04 11 87 08 AF 05 01 06 00 03 10 0E 11 0E 12 0E 13 0E 05 FF 06 01 03 14 0E 15 0E 05 FF 06 00 03 16 0E 05 7F 06 01 03 17 0E 05 AA 07 0E 05 E1 07 0E
