ldai 0
ldbi 0
add          ; result 0, should set Z = 1
jmpz 0A      ; jump to LDAI 12
ldbi 12      ; should be skipped
ldai 12
outa

05 00 06 00 03 00 11 0A 06 0C 05 0C 07 00