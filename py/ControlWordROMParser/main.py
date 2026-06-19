from pathlib import Path

path = Path("bin.txt")

matrix = [
    [int(x) for x in line.split()]
    for line in path.read_text().splitlines()
    if line.strip()
]

target_cols = 32

for row_index, row in enumerate(matrix):
    if len(row) > target_cols:
        raise ValueError(
            f"row {row_index} has {len(row)} columns, more than {target_cols}"
        )

    row.extend([0] * (target_cols - len(row)))

rom4bin = [row[0:8] for row in matrix]
rom3bin = [row[8:16] for row in matrix]
rom2bin = [row[16:24] for row in matrix]
rom1bin = [row[24:32] for row in matrix]


def bin_rows_to_hex(bin_matrix):
    return [
        f"{int(''.join(str(bit) for bit in row), 2):02X}"
        for row in bin_matrix
    ]


rom4hex = bin_rows_to_hex(rom4bin)
rom3hex = bin_rows_to_hex(rom3bin)
rom2hex = bin_rows_to_hex(rom2bin)
rom1hex = bin_rows_to_hex(rom1bin)


rom_size = 32 * 1024
microsteps_per_instruction = 16

flag_0_base = 0x0000  # flag bit = 0 address starts here
flag_1_base = 0x1000  # flag bit = 1 address starts here

noopwopr_opcode = 0x23  # 0010 0011, skip dummy operand

positive_jump_opcodes = range(0x10, 0x14)
negative_jump_opcodes = range(0x14, 0x18)

highest_needed_opcode = max(0x17, noopwopr_opcode)
needed_words = (highest_needed_opcode + 1) * microsteps_per_instruction

if len(rom1hex) < needed_words:
    raise ValueError(
        f"bin.txt only has {len(rom1hex)} microcode words, "
        f"but opcodes up to 0x{highest_needed_opcode:02X} need {needed_words}"
    )


def get_instruction_words(hex_data, opcode):
    start = opcode * microsteps_per_instruction
    end = start + microsteps_per_instruction
    return hex_data[start:end]


def write_instruction_words(rom_image, base_address, opcode, instruction_words):
    start = base_address + opcode * microsteps_per_instruction

    for step, value in enumerate(instruction_words):
        rom_image[start + step] = value


def make_full_rom_image(hex_data):
    rom_image = ["00"] * rom_size

    # first duplicate the normal input microcode into both flag pages
    for base_address in [flag_0_base, flag_1_base]:
        for i, value in enumerate(hex_data):
            rom_image[base_address + i] = value

    noopwopr_words = get_instruction_words(hex_data, noopwopr_opcode)

    # positive jumps:
    # JMPC, JMPZ, JMPN, JMPOVR
    #
    # when selected flag is 0, replace with NOOPWOPR
    # when selected flag is 1, keep the real jump
    for opcode in positive_jump_opcodes:
        real_jump_words = get_instruction_words(hex_data, opcode)

        write_instruction_words(rom_image, flag_0_base, opcode, noopwopr_words)
        write_instruction_words(rom_image, flag_1_base, opcode, real_jump_words)

    # negative jumps:
    # JMPNC, JMPNZ, JMPNN, JMPNOVR
    #
    # when selected flag is 0, keep the real jump
    # when selected flag is 1, replace with NOOPWOPR
    for opcode in negative_jump_opcodes:
        real_jump_words = get_instruction_words(hex_data, opcode)

        write_instruction_words(rom_image, flag_0_base, opcode, real_jump_words)
        write_instruction_words(rom_image, flag_1_base, opcode, noopwopr_words)

    return rom_image


rom4image = make_full_rom_image(rom4hex)
rom3image = make_full_rom_image(rom3hex)
rom2image = make_full_rom_image(rom2hex)
rom1image = make_full_rom_image(rom1hex)


def write_hex_file(filename, hex_data):
    with open(filename, "w") as f:
        f.write("v2.0 raw\n")

        for i in range(0, len(hex_data), 16):
            line = hex_data[i:i + 16]
            f.write(" ".join(line))
            f.write("\n")


write_hex_file("rom4_microcode_control_words.hex", rom4image)
write_hex_file("rom3_microcode_control_words.hex", rom3image)
write_hex_file("rom2_microcode_control_words.hex", rom2image)
write_hex_file("rom1_microcode_control_words.hex", rom1image)

total_microcode_words = len(matrix)
total_instructions = total_microcode_words // 16

print("total microcode words:", total_microcode_words)
print("total instructions:", total_instructions)