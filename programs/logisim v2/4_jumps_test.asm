; conditional jump test program
; expected final output: AA
; if a test fails, output will be E1-E8 then halt

; test jmpc:
ldai 0
ldbi 0
sub
jmpc test_jmpz
ldai E1
outa
halt

; test_jmpz:
ldai 0
ldbi 0
add
jmpz test_jmpn
ldai E2
outa
halt

; test_jmpn:
ldai 0
ldbi 1
sub
jmpn test_jmpovr
ldai E3
outa
halt

; test_jmpovr:
ldai 80
ldbi 1
sub
jmpovr test_jmpnc
ldai E4
outa
halt

; test_jmpnc:
ldai 0
ldbi 1
sub
jmpnc test_jmpnz
ldai E5
outa
halt

; test_jmpnz:
ldai 1
ldbi 0
add
jmpnz test_jmpnn
ldai E6
outa
halt

; test_jmpnn:
ldai 1
ldbi 0
add
jmpnn test_jmpnovr
ldai E7
outa
halt

; test_jmpnovr:
ldai 1
ldbi 0
add
jmpnovr passed
ldai E8
outa
halt

; passed:
ldai AA
outa
halt