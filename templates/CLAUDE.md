# Agentic Firmware Development over JTAG

This project uses a pure-JTAG workflow for embedded firmware development.
No serial port is used at any point — flashing, log capture, and debugging
all go through OpenOCD's JTAG interface via USB.

## Configuration

Two configuration files control the tooling:

**`esp_target_config.json`** — project-level tooling setup:
- Which chip hardware description to use
- OpenOCD settings (board config, ports, flash command)
- GDB executable
- Logging method (rtt or apptrace)

**`chips/<chip>.json`** — pure hardware reference (memory map, architecture).
Referenced by `esp_target_config.json`. Never needs editing per-project.
A chip JSON file may contain a reference to the corresponding SVD file with peripheral register definitions.

**`board.md`** — describes the specific development board: GPIO pin
assignments, I2C/SPI bus connections, LEDs (type, pin, protocol),
buttons, sensors, power domains, and any other hardware context
relevant to firmware development. Read this before writing any code
that interacts with board peripherals.

To see the full resolved configuration:
```
python3 esp_target.py info
```

To see the chip memory map:
```
python3 esp_target.py memmap
```

All tools (`esp_target.py`, `rtt_reader.py`, `esp-session-start.sh`) read
`esp_target_config.json` automatically from the current directory.

## Project structure

```
project/
├── CLAUDE.md                     # this file
├── esp_target_config.json        # tooling config (OpenOCD, GDB, logging)
├── board.md                      # board-specific hardware (pins, LEDs, buses)
├── main/
│   ├── CMakeLists.txt            # component registration (idf_component_register)
│   ├── *.c / *.h                 # application source
│   ├── SEGGER_RTT.c              # RTT library (target side)
│   ├── SEGGER_RTT.h
│   ├── SEGGER_RTT_Conf.h         # RTT config (architecture-specific lock macros)
│   └── SEGGER_RTT_printf.c
├── CMakeLists.txt                # top-level project CMakeLists
├── sdkconfig                     # ESP-IDF menuconfig output
├── build/                        # build output (generated)
│   ├── flasher_args.json         # flash layout: which binary at which offset
│   ├── <project>.bin             # application binary
│   ├── <project>.elf             # ELF with debug symbols
│   ├── bootloader/
│   │   └── bootloader.bin
│   └── partition_table/
│       └── partition-table.bin
├── chips/
│   └── <chip>.json               # hardware reference (memory map, architecture)
│   └── <chip>.svd                # CMSIS SVD peripheral register definitions (optional)
├── boards/
│   └── <board>.md                # sample board files
├── esp_target.py                 # target control tool
├── svd_parser.py                 # SVD parser (used by esp_target.py)
├── rtt_reader.py                 # RTT log reader daemon
├── esp-session-start.sh          # launch OpenOCD
├── esp-session-stop.sh           # tear down daemons
└── .esp-agent/                   # runtime state (created at session start)
    ├── openocd.log               # OpenOCD daemon log
    ├── rtt.log                   # firmware RTT output
    └── rtt_reader.log            # RTT reader daemon log
```

## Architecture

```
Claude Code
  ├── idf.py build                    → compile firmware
  ├── esp_target.py (shell exec)      → flash, reset, inspect registers
  ├── GDB batch scripts (on-demand)   → symbol-aware debugging
  ├── reads board.md                  → board description
  ├── reads .esp-agent/rtt.log        → firmware log output
  └── reads .esp-agent/openocd.log    → infrastructure diagnostics

esp_target.py
  └── OpenOCD Tcl port                → mww/mdw, program_esp, halt/resume

rtt_reader.py (background daemon)
  └── OpenOCD Tcl port                → polls RTT ring buffer via mdw/mww

OpenOCD (persistent daemon)
  ├── Tcl port     — commands from esp_target.py and rtt_reader.py
  ├── GDB RSP port — on-demand symbol-aware debugging
  └── USB-JTAG     → target MCU
```

Both esp_target.py and rtt_reader.py connect to OpenOCD's Tcl port
concurrently. OpenOCD serializes the JTAG transactions internally.
Port numbers are defined in `esp_target_config.json`.

## Prerequisites

The ESP-IDF environment must be active in the shell — `idf.py`, `openocd`,
and the cross-compiler must be on PATH. If any command fails with "command not found",
tell the user to run `. $IDF_PATH/export.sh`
in the shell where they started the session, then restart.

OpenOCD must be running before any target commands. Start it with:

```
./esp-session-start.sh
```

This reads `esp_target_config.json`, launches OpenOCD with the correct
board config, and verifies the target is responsive. To stop:

```
./esp-session-stop.sh
```

To verify manually:
```
python3 esp_target.py health
```

RTT logging is started separately, after firmware with RTT support has
been built and flashed:
```
python3 rtt_reader.py --elf build/<project>.elf --output .esp-agent/rtt.log &
```

## Building

```
idf.py build
```

Parse compiler output for errors and warnings. All build artifacts land in
`build/`. The key outputs are:
- `build/flasher_args.json` — authoritative source for flash offsets
- `build/<project>.bin` — application binary
- `build/<project>.elf` — ELF with debug symbols (needed for GDB and RTT)

## ESP-IDF reference

The ESP-IDF framework source tree is available at `$IDF_PATH`. This is
an essential reference when writing firmware — consult it for API usage,
peripheral driver patterns, and working examples.

Key directories:

```
$IDF_PATH/
├── examples/                     # working examples for every feature
│   ├── peripherals/              # GPIO, I2C, SPI, UART, RMT, ADC, ...
│   ├── wifi/                     # station, AP, scan, provisioning
│   ├── bluetooth/                # BLE, classic BT
│   ├── system/                   # sleep, watchdog, OTA, console, app_trace
│   ├── protocols/                # HTTP, MQTT, mDNS, SNTP
│   └── get-started/              # hello_world, blink
├── components/                   # framework source code
│   ├── driver/                   # peripheral drivers (gpio, i2c, spi, rmt, ...)
│   ├── esp_wifi/                 # WiFi stack
│   ├── esp_hw_support/           # low-level hardware abstraction
│   ├── freertos/                 # FreeRTOS kernel
│   ├── app_trace/                # application tracing (apptrace, SystemView)
│   ├── nvs_flash/                # non-volatile storage
│   └── ...
└── tools/
    └── esp_app_trace/            # host-side apptrace decoder (logtrace_proc.py)
```

When implementing a peripheral driver or feature:
1. Check `$IDF_PATH/examples/` for a working reference implementation
2. Read the component header in `$IDF_PATH/components/<component>/include/` for the API
3. Check `$IDF_PATH/components/<component>/Kconfig` for menuconfig options

Example: to drive a WS2812 LED via RMT, look at `$IDF_PATH/examples/peripherals/rmt/led_strip/`.

### Never guess chip-specific hardware constants

Chip-specific values — GPIO matrix signal indices, register bitfield positions,
opcode encodings, peripheral base addresses — are arbitrary hardware assignments
that vary between chip families. They cannot be derived from first principles and
must never be guessed or assumed from memory.

Always look them up in the chip-specific headers before writing any register-level
code:

```
$IDF_PATH/components/soc/<chip>/include/soc/
  gpio_sig_map.h      — GPIO matrix signal indices (IN_IDX / OUT_IDX per peripheral)
  io_mux_reg.h        — IO_MUX register bit definitions
  <periph>_struct.h   — peripheral register layouts and bitfield positions

$IDF_PATH/components/hal/<chip>/include/hal/
  <periph>_ll.h       — low-level driver constants (opcodes, enums, timing formulas)
```

## Flashing

Flash all components (bootloader + partition table + app):
```
python3 esp_target.py flash build/
```

Flash only the application (faster, for iterative development):
```
python3 esp_target.py flash build/ --app-only
```

Flash, reset, and wait for boot:
```
python3 esp_target.py flash-and-run build/ --app-only
```

Flashing goes over JTAG. Never use esptool.py or serial.
Flash offsets come from `build/flasher_args.json` — do not hardcode them.

After flashing new firmware, the RTT reader must be restarted (the control
block address may have changed):
```
python3 rtt_reader.py --elf build/<project>.elf --output .esp-agent/rtt.log &
```

## Target control

All commands go through esp_target.py:

```
# Reset
python3 esp_target.py reset run

# Check execution state
python3 esp_target.py state

# Halt CPU (required before reading CPU registers)
python3 esp_target.py halt

# Wait until CPU halts
python3 esp_target.py wait-halt

# Resume
python3 esp_target.py resume

# Erase entire flash
python3 esp_target.py erase

# Read memory (works while CPU is running)
python3 esp_target.py read <addr> <count>

# Write memory
python3 esp_target.py write <addr> <value>

# Read with byte or halfword width
python3 esp_target.py read <addr> <count> --width 8

# Dump all CPU registers (must halt first)
python3 esp_target.py halt
python3 esp_target.py cpu-regs
python3 esp_target.py resume

# Read a single CPU register
python3 esp_target.py cpu-reg pc
python3 esp_target.py cpu-reg mepc

# Write a single CPU register
python3 esp_target.py cpu-reg-write a0 0x1234

# Send raw OpenOCD command
python3 esp_target.py raw "targets"
```

For valid SRAM and peripheral addresses, check the memory map:
```
python3 esp_target.py memmap
```

Use data bus addresses for SRAM access, not instruction bus aliases.
The chip JSON documents both under `memory.sram` and `memory.sram_ibus`.

## SVD-aware register inspection

When an SVD file is configured in `esp_target_config.json`, registers can
be accessed by name:

```
# List all peripherals
python3 esp_target.py list-periph

# List registers in a peripheral
python3 esp_target.py list-regs GPIO

# Read a register by name
python3 esp_target.py read-reg GPIO.OUT

# Decode a register into named bitfields
python3 esp_target.py decode GPIO.OUT

# Read all registers of a peripheral
python3 esp_target.py inspect UART0

# Write a register by name
python3 esp_target.py write-reg GPIO.OUT_W1TS 0x400
```

Register path notation is PERIPHERAL.REGISTER or PERIPHERAL.REGISTER.FIELD.
list-periph, list-regs, and memmap work offline without OpenOCD.

## GDB debugging

GDB connects to OpenOCD's GDB RSP port for symbol-aware debugging.
The GDB executable and port are configured in `esp_target_config.json`.
View them with:
```
python3 esp_target.py info
```

### Batch mode (preferred for agentic use)

Run GDB non-interactively with `-batch`. Always pass the ELF for symbols:

```
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "<command>" \
    build/<project>.elf
```

Common batch operations:

```
# Backtrace after crash (target must be halted)
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "bt" \
    build/<project>.elf

# Print a global variable by name
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "print some_global_var" \
    build/<project>.elf

# Show local variables at current frame
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "info locals" \
    build/<project>.elf

# Dump a struct with full type info
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "ptype struct my_struct" \
    -ex "print my_struct_instance" \
    build/<project>.elf

# Set a breakpoint, continue, inspect when hit
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "break app_main" \
    -ex "continue" \
    -ex "bt" \
    -ex "info registers" \
    build/<project>.elf

# List all FreeRTOS threads
<gdb_executable> -batch \
    -ex "target remote :<gdb_port>" \
    -ex "info threads" \
    build/<project>.elf
```

### GDB script files

For complex inspection, write a .gdb script and run with `-batch -x`:

```gdb
# inspect.gdb
target remote :<gdb_port>
bt full
info registers
info threads
quit
```

```
<gdb_executable> -batch -x inspect.gdb build/<project>.elf
```

### Halt/resume protocol with GDB

GDB expects to own execution control. Follow this protocol:

1. Halt the CPU before connecting: `esp_target.py halt`
2. Connect GDB and do inspection
3. When done, disconnect GDB (it exits in batch mode)
4. Resume the CPU: `esp_target.py resume`

While GDB is connected, do not use esp_target.py's halt, resume, or reset
commands — GDB tracks execution state and will desynchronize.

Memory reads via esp_target.py and RTT polling via rtt_reader.py are safe
to use concurrently with GDB.

## RTT log capture

Firmware must include the SEGGER RTT library and write to channel 0:
```c
#include "SEGGER_RTT.h"
SEGGER_RTT_WriteString(0, "Hello from RTT\n");
SEGGER_RTT_printf(0, "value = %d\n", some_value);
```

The RTT reader runs as a background daemon:
```
python3 rtt_reader.py --elf build/<project>.elf --output .esp-agent/rtt.log &
```

Options for locating the RTT control block:
1. `--elf build/<project>.elf` — **default**: extracts address via nm, instant, always correct for the current build
2. `--address <addr>` — known address, instant (only if address is already known)
3. (no flag) — scans SRAM; **last resort only**, use when no ELF is available — slow

Reading firmware output:
```
# Tail the log
tail -f .esp-agent/rtt.log

# Read recent output
cat .esp-agent/rtt.log

# Read only new output since last check: note file size before an
# operation, then read new bytes after
WC=$(wc -c < .esp-agent/rtt.log)
# ... do something ...
tail -c +$((WC + 1)) .esp-agent/rtt.log
```

### RTT recovery

If the RTT reader produces garbage or stops receiving data:
1. Kill the rtt_reader.py process
2. Reflash the firmware: `esp_target.py flash-and-run build/ --app-only`
3. Restart the reader with `--elf` to pick up the new control block address

This typically happens when the firmware crashes and corrupts the ring buffer,
or when a rebuild moves the control block to a different address.

## ESP-IDF apptrace (alternative logging)

For capturing all ESP-IDF internal logging (WiFi, BLE, RTOS, driver
internals), the ESP-IDF apptrace mechanism can redirect all `ESP_LOGx`
output over JTAG. This is complementary to RTT — use RTT for continuous
agentic logging, use apptrace for diagnostic capture sessions.

### Enabling apptrace in firmware

1. In `idf.py menuconfig`, navigate to:
   `Component config → Application Level Tracing → Data Destination 1`
   and set it to `JTAG`.

2. In firmware code:
   ```c
   #include "esp_app_trace.h"
   #include "esp_log.h"

   esp_log_set_vprintf(esp_apptrace_vprintf);
   ```

3. Low-rate logging requires an explicit flush — the 16KB trace buffer
   only becomes visible to OpenOCD when a block fills up. Without flush,
   a few log lines per second will never trigger transfer:
   ```c
   ESP_LOGI("main", "some message");
   esp_apptrace_flush(ESP_APPTRACE_DEST_JTAG, 1000);
   ```

### Capturing apptrace data

The target must be reset while OpenOCD is connected so the apptrace
handshake fires during boot. Sequence in telnet:

```
reset run
```

Wait 2 seconds, then:

```
esp apptrace start file:///tmp/apptrace.log 1 -1 30 0
```

Arguments: poll_period(1ms) trace_size(-1=unlimited) stop_tmo(30s)
wait4halt(0).

### Decoding apptrace output

The output is binary. Decode with:
```
python3 $IDF_PATH/tools/esp_app_trace/logtrace_proc.py /tmp/apptrace.log build/<project>.elf
```

### Critical limitation

`esp apptrace start` **blocks the OpenOCD event loop**. While a capture
is running, esp_target.py and rtt_reader.py cannot communicate with
OpenOCD. This makes apptrace unsuitable for the continuous agentic
development loop. Use it as a deliberate diagnostic capture session:
stop other tooling, capture for N seconds, decode, then resume normal
operation.

### RTT vs apptrace summary

| | RTT | apptrace |
|---|---|---|
| Log source | Explicit SEGGER_RTT_printf() | All ESP_LOGx automatically |
| Output format | Plain text, immediate | Binary, requires decode |
| Continuous streaming | Yes | No (timed capture window) |
| Blocks OpenOCD | No | Yes |
| esp_target.py usable | Yes | No (during capture) |
| Best for | Agentic dev loop | Deep ESP-IDF diagnostics |

## Accessing logs

Two log files provide diagnostic information:

**Firmware output** — `.esp-agent/rtt.log`
- Written by rtt_reader.py from the RTT ring buffer
- Contains application-level output: printf, status messages, panics
- Check this after flash+reset to verify firmware booted correctly
- Wait ~2 seconds after reset before reading (firmware needs time to boot)

**OpenOCD log** — `.esp-agent/openocd.log`
- Written by the OpenOCD daemon (stderr redirect)
- Contains JTAG transport diagnostics, flash operation details, errors
- Check this when flash fails, target is unresponsive, or OpenOCD crashes

## Important constraints

- Never use /dev/tty* or /dev/cu.* — no serial port access
- Memory reads (mdw) work while the CPU is running; CPU register reads
  require halting first
- Do not halt the CPU via esp_target.py while a GDB session is active
- After chip reset, allow ~1 second before issuing commands — the USB-JTAG
  link briefly drops during reset
- The RTT control block address changes when firmware is rebuilt with
  different static variable layout — always restart rtt_reader.py after
  reflashing
- Flash offsets are chip and project dependent — always read them from
  build/flasher_args.json, never hardcode
- Consult `esp_target.py memmap` for memory addresses — do not assume
  address ranges from one chip apply to another

## Typical development cycle

1. Edit source code in main/
2. `idf.py build` — fix any compiler errors
3. `python3 esp_target.py flash build/ --app-only`
4. `python3 esp_target.py reset run`
5. Wait 2 seconds, then read .esp-agent/rtt.log for firmware output
6. If something is wrong, inspect hardware state:
   - `decode` peripheral registers to check configuration
   - `inspect` an entire peripheral to see all register values
   - `halt` + `cpu-regs` to examine CPU state after a crash
   - `wait-halt` after an asynchronous stop condition or debugger-driven resume
   - Use GDB batch mode for symbol-aware inspection
7. Diagnose, edit code, repeat from step 2

For the flash-and-run shortcut (steps 3-4 combined):
```
python3 esp_target.py flash-and-run build/ --app-only
```

## Debugging a crash or hang

If the firmware crashes or hangs:

1. Check .esp-agent/rtt.log for panic backtrace or last output before hang
2. Halt the CPU: `esp_target.py halt`
3. Read CPU registers: `esp_target.py cpu-regs` — check pc for crash location
4. Read a single register: `esp_target.py cpu-reg mcause` — check exception cause
   Use `esp_target.py wait-halt` when a script needs to block until execution stops again.
5. Use GDB for symbol-aware diagnosis (find executable and port via
   `esp_target.py info`):
   ```
   <gdb_executable> -batch \
       -ex "target remote :<gdb_port>" \
       -ex "bt full" \
       -ex "info registers" \
       -ex "info threads" \
       build/<project>.elf
   ```
6. Inspect peripheral state with SVD: `esp_target.py decode <PERIPH>.<REG>`
7. Read memory around the stack pointer to check for corruption
8. Resume: `esp_target.py resume`

## OpenOCD Tcl interface

For advanced use, esp_target.py's `raw` command exposes the full OpenOCD
command vocabulary via the Tcl port:

```
python3 esp_target.py raw "targets"
python3 esp_target.py raw "flash info 0"
```

The Tcl interface is a full Tcl interpreter. Compound expressions and
loops can be composed into a single call for efficiency:
```
python3 esp_target.py raw "set val [mdw 0x60004000 1]; return \$val"
```

When you need to query hardware state repeatedly (e.g., sampling GPIO levels, probing multiple registers),
consider using OpenOCD's Tcl interpreter instead of issuing many individual commands.
Prepare a small Tcl script and run it via:

```bash
python3 esp_target.py raw "<tcl script>"
```

You can loop, add delays (`after`), and aggregate output before returning,
which is much faster than repeated `esp_target.py read` calls.
Notice that the caller can only see the value returned by the script,
so do not print results to stdout in the Tcl script — just pack the results into the return value.

## Adding RTT to new firmware

1. Copy SEGGER_RTT.c, SEGGER_RTT.h, SEGGER_RTT_Conf.h, and
   SEGGER_RTT_printf.c into the main/ component directory

2. Register them in main/CMakeLists.txt:
   ```cmake
   idf_component_register(SRCS "SEGGER_RTT.c" "SEGGER_RTT_printf.c" "app_main.c"
                          PRIV_REQUIRES spi_flash
                          INCLUDE_DIRS ".")
   ```

3. SEGGER_RTT_Conf.h contains architecture-specific interrupt lock macros.
   RISC-V targets use csrrci/csrw on the mstatus MIE bit, guarded by
   `#if defined(__riscv)`. ARM targets use the stock PRIMASK/BASEPRI
   macros. No changes needed if the correct architecture guard is present.

4. In application code:
   ```c
   #include "SEGGER_RTT.h"

   void app_main(void) {
       SEGGER_RTT_WriteString(0, "Boot complete\n");
       while (1) {
           SEGGER_RTT_printf(0, "tick %d\n", counter++);
           vTaskDelay(pdMS_TO_TICKS(1000));
       }
   }
   ```
