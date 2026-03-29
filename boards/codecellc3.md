# Board: CodeCell C3 (Microbots)

A compact (18.5 mm wide) development module by Microbots featuring
the ESP32-C3-MINI-1-N4. Designed for robotics, wearables, and IoT.
Includes onboard light/proximity sensor, 9-axis IMU, LiPo
battery charging, and USB-C for power/programming/debugging.

## MCU

| Parameter | Value |
|-----------|-------|
| Module | ESP32-C3-MINI-1-N4 |
| Core | 32-bit RISC-V single-core, up to 160 MHz |
| Flash | 4 MB (SPI, in-package) |
| SRAM | 400 KB |
| Wireless | Wi-Fi 802.11 b/g/n, Bluetooth 5 (LE) |

## MCU architecture notes

### RISC-V implementation

The ESP32-C3 implements RV32IMC (integer, multiply/divide, compressed
instructions). It does **not** implement the Zicntr extension, so the
standard performance-monitoring CSRs are absent:

| CSR | Address | Status |
|-----|---------|--------|
| `mcycle` | 0xB00 | **Not implemented** — illegal instruction trap |
| `mcycleh` | 0xB80 | **Not implemented** — illegal instruction trap |
| `minstret` | 0xB02 | **Not implemented** — illegal instruction trap |
| `minstreth` | 0xB82 | **Not implemented** — illegal instruction trap |

Code that uses `csrr a0, mcycle` (common on SiFive and other standard
RISC-V cores) will raise an illegal instruction exception on this chip.

### Non-standard performance counter CSRs

The ESP32-C3 provides a set of custom CSRs derived from the PULP/RI5CY
lineage that can be used for cycle counting, instruction counting, and
other micro-architectural events:

| CSR | Address | Description |
|-----|---------|-------------|
| `mpcer` | 0x7E0 | Performance Counter Enable Register — one bit per counter, selects which event each `mpccr` slot counts |
| `mpcmr` | 0x7E1 | Performance Counter Mode Register — global enable (bit 0) and saturation mode (bit 1) |
| `mpccr0`–`mpccr31` | 0x780–0x79F | Per-event 32-bit counters |

### ESP-IDF API to use in firmware

In ESP-IDF application code, prefer the standard CPU-counter helpers
instead of open-coding CSR reads:

```c
#include "esp_cpu.h"
#include "esp_private/esp_clk.h"

uint32_t start = esp_cpu_get_cycle_count();
/* ... short code section or busy-wait ... */
uint32_t elapsed_cycles = esp_cpu_get_cycle_count() - start;
uint32_t elapsed_us = elapsed_cycles / (esp_clk_cpu_freq() / 1000000U);
```

On ESP32-C3, `esp_cpu_get_cycle_count()` does **not** read `mcycle`.
ESP-IDF routes it to the chip's custom performance-counter CSR path
instead, so this is the correct API for timing short code paths and
implementing cycle-based delays in normal firmware.

### Raw CSR background

Event select values for `mpcer` (written as a field per active counter):

| Value | Event counted |
|-------|--------------|
| 0 | No event (counter disabled) |
| 1 | Cycles |
| 2 | Instructions retired |
| 3 | Load data hazard stall cycles |
| 4 | Jump/branch stall cycles |
| 5 | Instruction memory stall cycles |

If you need direct bare-metal CSR access, counter 0 can be configured
for cycles like this:

```c
/* Enable counter 0 to count cycles */
__asm__ volatile ("csrwi mpcmr, 0");        /* disable while configuring  */
__asm__ volatile ("csrwi mpccr0, 0");       /* clear counter 0            */
__asm__ volatile ("csrwi mpcer, 1");        /* counter 0 → cycles (event 1) */
__asm__ volatile ("csrwi mpcmr, 1");        /* global enable              */

uint32_t t0, t1;
__asm__ volatile ("csrr %0, mpccr0" : "=r"(t0));
/* ... code under measurement ... */
__asm__ volatile ("csrr %0, mpccr0" : "=r"(t1));
uint32_t cycles = t1 - t0;
```

Note: these CSRs are machine-mode only. They are not accessible from
user-mode code and are not preserved across FreeRTOS context switches —
disable the counter or save/restore `mpccr` around task boundaries if
used in an RTOS context.

## Pin assignments

### I2C

| Bus | SDA | SCL | Speed | Connected devices |
|-----|-----|-----|-------|-------------------|
| I2C0 | GPIO8 | GPIO9 | 400 kHz | VCNL4040 (0x60), BNO085 (0x4A) |

The I2C bus is shared between the onboard sensors and the header pins.
Do not use conflicting I2C addresses when connecting external devices.
The bus configuration is fixed if onboard sensors are used.

### GPIO (exposed on headers)

| Pin | Label | ADC | PWM | Notes |
|-----|-------|-----|-----|-------|
| GPIO1 | IO1 | ADC1_CH1 | Yes | Analog input capable |
| GPIO2 | IO2 | ADC1_CH2 | Yes | Analog input capable; shared with charge status (CHG, active low); strapping pin |
| GPIO3 | IO3 | ADC1_CH3 | Yes | Analog input capable; shared with battery voltage monitor (VBAT/2 divider) |
| GPIO5 | IO5 | ADC2_CH0 | Yes | General purpose |
| GPIO6 | IO6 | — | Yes | General purpose |
| GPIO7 | IO7 | — | Yes | General purpose |
| GPIO8 | SDA | — | Yes | I2C data; shared with onboard sensors (2k pullup) |
| GPIO9 | SCL | — | Yes | I2C clock; shared with onboard sensors (2k pullup); strapping pin (boot mode) |

All exposed GPIOs support PWM output via the ESP32-C3's LEDC peripheral
(6 channels, configurable frequency and resolution).

### Reserved / not exposed

| Pin | Function | Notes |
|-----|----------|-------|
| GPIO0 | Not exposed | Connected to ESP32-C3-MINI-1 module internally; not routed to any header |
| GPIO4 | Not exposed | Connected to ESP32-C3-MINI-1 module internally; not routed to any header |
| GPIO10 | SK6805-EC10 LED | Onboard addressable RGB LED (WS2812 protocol) |
| GPIO18 | USB D- | USB Serial/JTAG — do not reconfigure |
| GPIO19 | USB D+ | USB Serial/JTAG — do not reconfigure |

## LEDs

| Pin | Type | Protocol | Notes |
|-----|------|----------|-------|
| GPIO10 | SK6805-EC10 | WS2812 (single-wire, timed pulse) | Addressable RGB. Cannot be driven by GPIO toggle — requires RMT peripheral or SPI bit-bang. 24-bit GRB color order, 800 kHz. See `$IDF_PATH/examples/peripherals/rmt/led_strip/` for driver example. |

There is no simple on/off LED on this board.

## Onboard sensors

### VCNL4040 — Light and proximity sensor

| Parameter | Value |
|-----------|-------|
| I2C address | 0x60 |
| Bus | I2C0 (GPIO8/GPIO9) |
| Capabilities | 16-bit ambient light, proximity up to 20 cm |
| Datasheet | [VCNL4040](https://www.vishay.com/docs/84274/vcnl4040.pdf) |

### BNO085 — 9-axis IMU

| Parameter | Value |
|-----------|-------|
| I2C address | 0x4A |
| Bus | I2C0 (GPIO8/GPIO9) |
| Capabilities | 3-axis accelerometer, gyroscope, magnetometer; onboard sensor fusion providing roll/pitch/yaw, activity classification, tap detection, step counting |
| Datasheet | [BNO085](https://www.ceva-ip.com/wp-content/uploads/BNO080_085-Datasheet.pdf) |

## Power

| Source | Voltage | Notes |
|--------|---------|-------|
| USB-C | 5V | Also used for programming and JTAG debug |
| LiPo battery | 3.7V nominal | 1.25 mm pitch JST connector; optional 170 mAh 20C battery |
| 3.3V output | 3.3V | NCP177 LDO, up to 500 mA |

Power management is handled by the BQ24232 chip with dynamic
power-path control — the board operates while charging. Default LiPo
charge current is 90 mA.

## USB

The board uses the ESP32-C3's built-in USB Serial/JTAG controller on
GPIO18 (D-) and GPIO19 (D+). A single USB-C connector provides:

- JTAG debugging (used by this framework)
- Serial CDC-ACM (not used in this framework)
- Power and battery charging

Do not reconfigure GPIO18/GPIO19 — this would break both JTAG access
and USB charging.

## Flash

| Size | Type | Notes |
|------|------|-------|
| 4 MB | Quad SPI (in-package) | Memory-mapped at 0x3C000000 (data) / 0x42000000 (instruction) |

## Buttons

No BOOT or RESET buttons on this board. The ESP32-C3 enters boot mode
automatically via USB. In case of a firmware crash loop, manual boot
mode entry requires shorting SCL (GPIO9) to GND while reconnecting USB.

## Board-specific constraints

- GPIO0 and GPIO4 are not routed to any header — not available for use
- GPIO10 is hardwired to the SK6805 LED — not available for general use
- GPIO18/GPIO19 are USB — not available for general use
- GPIO8/GPIO9 are shared between I2C headers and onboard sensors —
  external I2C devices must not conflict with addresses 0x60 (VCNL4040)
  or 0x4A (BNO085)
- GPIO2 is a strapping pin — avoid heavy loads or capacitance
- GPIO9 is a strapping pin (boot mode select) — avoid pulling low at
  boot unless intentionally entering download mode
- GPIO5 (ADC2_CH0) cannot be used for ADC while Wi-Fi is active —
  use GPIO1/GPIO2/GPIO3 (ADC1) for analog reads in Wi-Fi applications
- SK6805 LED is powered from VCC (charger output rail), not 3.3V —
  LED may not work without USB or battery connected
- No PSRAM on this module
- No RESET button — programmatic reset via RTC watchdog or `esp_restart()`
- PCB antenna is at the board edge — avoid placing metal or ground
  planes near it

## References

- [Product page](https://microbots.io/products/codecell)
- [Schematics](https://github.com/microbotsio/CodeCell)
- [Arduino library and examples](https://github.com/microbotsio/CodeCell)
- [Tutorials](https://microbots.io/pages/learn-codecell)
- [I2C communication guide](https://microbots.io/blogs/codecell/codecell-i2c-communication)
- [Circuit description](https://microbots.io/blogs/codecell/understanding-codecell-circuitry)
