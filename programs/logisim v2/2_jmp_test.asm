ldai 0
ldbi 0
add          ; A = 0, sets Z = 1
jmpz 0A      ; jump to ldai 12 if Z = 1
ldbi 12      ; should be skipped
ldai 12
outa

05 00 06 00 03 00 80 0A 06 0C 05 0C 07 00