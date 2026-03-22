# SEGGER RTT

This directory contains the patched `SEGGER_RTT_Conf.h` configuration
header with RISC-V interrupt lock support. The RTT library source files
themselves are not included — you need to obtain them from SEGGER.

## Getting the RTT sources

### Option 1: SEGGER website (official)

Download the J-Link Software and Documentation Pack from:
https://www.segger.com/downloads/jlink/

The RTT sources are included under `Samples/RTT/`. You need:

- `SEGGER_RTT.c`
- `SEGGER_RTT.h`
- `SEGGER_RTT_printf.c`

### Option 2: SEGGER GitHub

SEGGER publishes RTT as part of their SystemView package:
https://github.com/SEGGERMicro/SystemView

The files are under `SEGGER/`:

- `SEGGER_RTT.c`
- `SEGGER_RTT.h`
- `SEGGER_RTT_printf.c`

### Option 3: ESP-IDF (already on your machine)

ESP-IDF bundles SEGGER RTT sources for SystemView support:

```bash
ls $IDF_PATH/components/app_trace/sys_view/SEGGER/
```

Copy `SEGGER_RTT.c`, `SEGGER_RTT.h`, and `SEGGER_RTT_printf.c` from
there. Note: the `SEGGER_RTT_Conf.h` in ESP-IDF's tree is configured
for their apptrace integration — use the one from this directory instead.

## What's included here

**`SEGGER_RTT_Conf.h`** — the configuration header, patched to add
RISC-V support. The stock header only has lock macros for ARM
(PRIMASK/BASEPRI). This version adds a `#if defined(__riscv)` guard
at the top of the GCC/Clang block that uses `csrrci`/`csrw` on the
`mstatus` MIE bit to disable and restore interrupts:

```c
#if defined(__riscv)
  #define SEGGER_RTT_LOCK()   {                                    \
                                  unsigned int LockState;          \
                                __asm volatile ("csrrci %0, mstatus, 0x8" \
                                                : "=r" (LockState) \
                                                :                  \
                                                );

  #define SEGGER_RTT_UNLOCK()   __asm volatile ("csrw mstatus, %0" \
                                                :                  \
                                                : "r" (LockState)  \
                                                :                  \
                                                );                 \
                              }
```

ARM targets are unaffected — the existing PRIMASK/BASEPRI macros
follow as `#elif` branches.

## Setting up RTT in your project

1. Copy `SEGGER_RTT.c`, `SEGGER_RTT.h`, and `SEGGER_RTT_printf.c`
   from one of the sources above into your `main/` component directory.

2. Copy `SEGGER_RTT_Conf.h` from this directory into `main/` as well,
   replacing any default version.

3. Add the sources to your `main/CMakeLists.txt`:

   ```cmake
   idf_component_register(
       SRCS "SEGGER_RTT.c" "SEGGER_RTT_printf.c" "your_main.c"
       PRIV_REQUIRES spi_flash
       INCLUDE_DIRS "."
   )
   ```

4. Use RTT in your code:

   ```c
   #include "SEGGER_RTT.h"

   SEGGER_RTT_WriteString(0, "Hello from RTT\n");
   SEGGER_RTT_printf(0, "value = %d\n", some_value);
   ```

5. Build, flash, and start the RTT reader:

   ```bash
   idf.py build
   python3 esp_target.py flash-and-run build/ --app-only
   python3 rtt_reader.py --elf build/<project>.elf
   ```

## Configuration options

Key settings in `SEGGER_RTT_Conf.h` you may want to adjust:

| Setting | Default | Purpose |
|---------|---------|---------|
| `SEGGER_RTT_MAX_NUM_UP_BUFFERS` | 3 | Target → host channels |
| `SEGGER_RTT_MAX_NUM_DOWN_BUFFERS` | 3 | Host → target channels |
| `BUFFER_SIZE_UP` | 1024 | Channel 0 output buffer size |
| `BUFFER_SIZE_DOWN` | 16 | Channel 0 input buffer size |
| `SEGGER_RTT_MODE_DEFAULT` | `NO_BLOCK_SKIP` | What happens when buffer is full |

For the agentic workflow, the defaults work well. If you're generating
high-throughput output, increase `BUFFER_SIZE_UP` to reduce the chance
of dropped data when the reader can't poll fast enough.

## License

SEGGER RTT is distributed under a BSD-style license that permits
redistribution in source and binary forms. See the license header in
the source files for the full text. We include only the patched
configuration header here to avoid any ambiguity.
