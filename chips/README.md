# Chip Hardware Descriptions

Each JSON file in this directory describes the hardware of a specific
microcontroller. These files contain only facts about the silicon —
memory map, architecture, chip name. No tooling configuration, no
project-specific settings.

## Using a chip config

Chip configs are referenced from `esp_target_config.json`:

```json
{
  "chip": "chips/esp32c3.json",
  ...
}
```

The tools never need to be told about the chip directly — they read
the project config and follow the reference.

## Adding a new chip

Create a JSON file named `<chip>.json` with the following structure:

```json
{
  "name": "ESP32-S3",
  "arch": "xtensa",
  "svd": "chips/esp32c3.svd",
  "memory": {
   "sram": {
      "start": "0x3FC88000",
      "size": "0x78000",
      "description": "Internal SRAM (data bus)"
    }
  }
}
```

### Required fields

**`name`** — human-readable chip name. Shown in `esp_target.py health`
and `esp_target.py info` output.

**`arch`** — CPU architecture. Used by tools to select the correct
register set for `regs` command. Current values: `riscv32`, `xtensa`.

**`memory.sram`** — the main SRAM region accessible via the data bus.
Must have `start` (hex string) and `size` (hex string). This is used
by `rtt_reader.py` to determine the search range when scanning for the
RTT control block, and by `esp_target.py memmap` to display the memory
layout.

### Optional fields

**`svd`** — Points to an SVD file for the chip.
Download from https://github.com/espressif/svd.
The SVD file provides peripheral register definitions with field-level
bitfield layouts, enabling `esp_target.py decode` and `read-reg`.

### Optional memory regions

Add as many memory regions as useful. Each region needs `start`, `size`,
and `description`. Common regions:

```json
{
  "memory": {
    "sram": {
      "start": "0x3FC88000",
      "size": "0x78000",
      "description": "Internal SRAM (data bus)"
    },
    "sram0_ibus": {
      "start": "0x40370000",
      "size": "0x8000",
      "description": "Internal SRAM 0 (instruction bus alias)"
    },
    "sram1_ibus": {
      "start": "0x40378000",
      "size": "0x68000",
      "description": "Internal SRAM 1 (instruction bus alias)"
    },
    "flash_dbus": {
      "start": "0x3C000000",
      "size": "0x2000000",
      "description": "Flash (data bus, memory-mapped, read-only)"
    },
    "flash_ibus": {
      "start": "0x42000000",
      "size": "0x2000000",
      "description": "Flash (instruction bus, memory-mapped, read-only)"
    },
    "peripherals": {
      "start": "0x60000000",
      "size": "0xD1000",
      "description": "Peripheral registers"
    }
  }
}
```

The `sram*_ibus` aliases are important to document because OpenOCD memory
reads must use data bus addresses, not instruction bus aliases. Having
both in the chip config helps the agent (and humans) avoid this mistake.

### Where to find the information

The memory map for each ESP32 variant is in the Technical Reference
Manual, typically in Chapter 1 (System and Memory). Espressif publishes
these at https://www.espressif.com/en/support/documents/technical-documents.

Key sections to look for:
- "Address Mapping" or "System Address Mapping" — gives the full address space layout
- "Internal Memory" — SRAM size and data/instruction bus addresses
- "Peripheral Registers" — base address range for peripherals

### Companion files

**An `esp_target_config.json`** — references the board config,
and adds the tooling settings (OpenOCD board config, flash command,
GDB executable, ports). See `templates/esp_target_config.json` for
the structure.

An **optional SVD file** — Download from https://github.com/espressif/svd.
The SVD file provides peripheral register definitions with field-level
bitfield layouts, enabling `esp_target.py decode` and `read-reg`.

### Testing a new chip config

Verify the memory map displays correctly:

```bash
python3 esp_target.py memmap
```

Verify SRAM is accessible (with OpenOCD running and target connected):

```bash
python3 esp_target.py read <sram_start_address> 4
```

Verify SVD peripheral listing works:

```bash
python3 esp_target.py list-periph
```

If the RTT reader can scan and find a control block in SRAM,
the memory region is correctly defined:

```bash
python3 rtt_reader.py --scan-only
```

## Existing chip configs

| File | Chip | Architecture | SRAM | Tested |
|------|------|-------------|------|--------|
| `esp32c3.json` | ESP32-C3 | RISC-V (RV32IMC) | 400KB | Yes |
| `esp32s3.json` | ESP32-S3 | Xtensa LX7 (dual-core) | 512KB | No |
