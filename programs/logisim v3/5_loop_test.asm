ldxi 05

loop:
mov x, a
outa

decx

mov x, a
ldbi 00
sub
jmpnz loop

ldai AA
outa
halt

19 05 20 00 07 00 22 01 20 00 06 00 04 00 15 02 05 AA 07 00 0E 00