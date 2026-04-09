# Board: Waveshare ESP32-C6-LCD-1.47

A compact development board by Waveshare featuring the ESP32-C6FH4 SoC with a
1.47-inch 172×320 TFT LCD (ST7789V3), onboard WS2812B RGB LED, microSD card
slot (SPI and 4-bit SDIO modes), two buttons (RESET and BOOT), and USB-C for
power/programming/debugging.

## MCU

| Parameter | Value |
|-----------|-------|
| Chip | ESP32-C6FH4 |
| HP Core | 32-bit RISC-V, up to 160 MHz, 4-stage pipeline |
| LP Core | 32-bit RISC-V, up to 20 MHz, 2-stage pipeline |
| Flash | 4 MB (Quad SPI, in-package) |
| HP SRAM | 512 KB |
| LP SRAM | 16 KB |
| Wireless | Wi-Fi 6 (802.11ax), Bluetooth 5.3 LE, Zigbee 3.0, Thread 1.3 |
| Package | QFN32 (5×5 mm) |

## MCU architecture notes

### RISC-V implementation

The ESP32-C6 has two RISC-V cores.

**HP (High-Performance) CPU** — the main application core:
- ISA: RV32IMACU (integer, multiply/divide, atomic, compressed, user-mode)
- 4-stage in-order scalar pipeline, up to 160 MHz
- Runs ESP-IDF / FreeRTOS application code

**LP (Low-Power) CPU** — available in all power modes including deep sleep:
- ISA: RV32IMC, up to 20 MHz, 2-stage pipeline
- Has exclusive access to LP peripherals (LP_UART, LP_I2C, LP_GPIO0–7)
- Not used by ESP-IDF in normal application firmware

### Standard RISC-V performance-counter CSRs absent from HP CPU

The HP CPU does **not** implement the Zicntr extension:

| CSR | Address | Status |
|-----|---------|--------|
| `mcycle` | 0xB00 | **Not implemented** — illegal instruction trap |
| `mcycleh` | 0xB80 | **Not implemented** — illegal instruction trap |
| `minstret` | 0xB02 | **Not implemented** — illegal instruction trap |
| `minstreth` | 0xB82 | **Not implemented** — illegal instruction trap |

### Non-standard performance counter CSRs

The ESP32-C6 HP CPU provides custom performance counter CSRs in the RISC-V
custom CSR address space (PULP/RI5CY lineage, same addresses as ESP32-C3):

| CSR | Address | Description |
|-----|---------|-------------|
| `mpcer` | 0x7E0 | Machine Performance Counter Event — bit 0: CYCLE, bit 1: INST, bit 2: LD_HAZARD, bit 3: JMP_HAZARD, bit 4: IDLE, bit 5: LOAD, bit 6: STORE, bit 7: JMP_UNCOND, bit 8: BRANCH, bit 9: BRANCH_TAKEN, bit 10: INST_COMP |
| `mpcmr` | 0x7E1 | Machine Performance Counter Mode — bit 0: COUNT_EN, bit 1: COUNT_SAT (0=wrap, 1=halt at max). **Reset value: 0x3** (enabled, saturating) |
| `mpccr` | 0x7E2 | Machine Performance Counter Count — 32-bit R/W counter value |

> **Note:** There is exactly **one** counter register (`mpccr` at 0x7E2). The
> init sequence is not required unless changing the counted event, since
> `mpcmr` resets to 0x3 (enabled).

### ESP-IDF API to use in firmware

In ESP-IDF application code, use the standard CPU-counter helpers:

```c
#include "esp_cpu.h"
#include "esp_private/esp_clk.h"

uint32_t start = esp_cpu_get_cycle_count();
/* ... short code section or busy-wait ... */
uint32_t elapsed_cycles = esp_cpu_get_cycle_count() - start;
uint32_t elapsed_us = elapsed_cycles / (esp_clk_cpu_freq() / 1000000U);
```

On ESP32-C6, `esp_cpu_get_cycle_count()` reads the custom `mpccr` CSR at
0x7E2, not `mcycle`. This is the correct API for timing short code paths and
cycle-based delays in normal firmware.

### Raw CSR access

```c
/* One-time init: select cycles as the counted event and enable */
__asm__ volatile ("csrwi 0x7E1, 0");   /* mpcmr: disable while configuring */
__asm__ volatile ("csrwi 0x7E0, 1");   /* mpcer: set bit 0 (CYCLE)         */
__asm__ volatile ("csrwi 0x7E1, 1");   /* mpcmr: global enable             */

uint32_t t0, t1;
__asm__ volatile ("csrr %0, 0x7E2" : "=r"(t0));
/* ... code under measurement ... */
__asm__ volatile ("csrr %0, 0x7E2" : "=r"(t1));
uint32_t cycles = t1 - t0;
```

`mpcer` bit map:

| Bit | Field | Event counted |
|-----|-------|--------------|
| 0 | CYCLE | Clock cycles (does not increment during WFI) |
| 1 | INST | Instructions retired |
| 2 | LD_HAZARD | Load data hazard stall cycles |
| 3 | JMP_HAZARD | Jump hazard stall cycles |
| 4 | IDLE | Idle cycles |
| 5 | LOAD | Load instructions |
| 6 | STORE | Store instructions |
| 7 | JMP_UNCOND | Unconditional jumps |
| 8 | BRANCH | Branch instructions |
| 9 | BRANCH_TAKEN | Branches taken |
| 10 | INST_COMP | Compressed instructions |

These CSRs are machine-mode only and are not preserved across FreeRTOS context
switches.

## Pin assignments

### Shared SPI bus (LCD + SD card)

GPIO6 and GPIO7 form a single SPI bus shared by the LCD and the SD card.
Devices are selected via individual chip-select lines.

| Signal | GPIO |
|--------|------|
| MOSI (LCD_DIN / SD_MOSI) | GPIO6 |
| CLK  (LCD_CLK / SD_SCLK) | GPIO7 |

### LCD (ST7789V3, 4-wire SPI)

| Signal | GPIO | Notes |
|--------|------|-------|
| DIN (MOSI) | GPIO6 | Shared SPI bus |
| CLK | GPIO7 | Shared SPI bus |
| CS | GPIO14 | Active low |
| DC | GPIO15 | Low = command, high = data |
| RST | GPIO21 | Active low; conflicts with SDIO_D1 |
| BL | GPIO22 | Backlight via N-MOSFET Q1; PWM capable; conflicts with SDIO_D2 |

### microSD card

**SPI mode:**

| Signal | GPIO | Notes |
|--------|------|-------|
| MOSI | GPIO6 | Shared with LCD_DIN |
| SCLK | GPIO7 | Shared with LCD_CLK |
| MISO | GPIO5 | |
| CS | GPIO4 | |

**SDIO 4-bit mode:**

| Signal | GPIO | Notes |
|--------|------|-------|
| SDIO_CMD | GPIO18 | |
| SDIO_CLK | GPIO19 | |
| SDIO_D0 | GPIO20 | |
| SDIO_D1 | GPIO21 | Conflicts with LCD_RST |
| SDIO_D2 | GPIO22 | Conflicts with LCD_BL |
| SDIO_D3 | GPIO23 | |

SDIO mode and LCD use cannot overlap: SDIO_D1/D2 share GPIO21/GPIO22 with
LCD_RST and LCD_BL. The LCD must not be initialised or driven while the SD
card operates in 4-bit SDIO mode.

### ADC

The ESP32-C6 has a single 12-bit SAR ADC (ADC1) with 7 channels. There is no
ADC2, so there is no ADC conflict with Wi-Fi (all channels remain usable while
Wi-Fi is active, unlike ESP32-C3).

| GPIO | ADC channel | Notes |
|------|-------------|-------|
| GPIO0 | ADC1_CH0 | Also XTAL_32K_P (no 32 kHz crystal fitted) |
| GPIO1 | ADC1_CH1 | Also XTAL_32K_N (no 32 kHz crystal fitted) |
| GPIO2 | ADC1_CH2 | |
| GPIO3 | ADC1_CH3 | |
| GPIO4 | ADC1_CH4 | SD_CS in SPI mode; strapping pin (MTMS) |
| GPIO5 | ADC1_CH5 | SD_MISO in SPI mode; strapping pin (MTDI) |
| GPIO6 | ADC1_CH6 | Dedicated to SPI MOSI — not available for ADC |

### GPIO exposed on header

| GPIO | ADC | LP GPIO | Notes |
|------|-----|---------|-------|
| GPIO0 | ADC1_CH0 | LP_GPIO0 | General purpose |
| GPIO1 | ADC1_CH1 | LP_GPIO1 | General purpose |
| GPIO2 | ADC1_CH2 | LP_GPIO2 | General purpose |
| GPIO3 | ADC1_CH3 | LP_GPIO3 | General purpose |
| GPIO4 | ADC1_CH4 | LP_GPIO4 | SD_CS (SPI); strapping pin (MTMS) |
| GPIO5 | ADC1_CH5 | LP_GPIO5 | SD_MISO (SPI); strapping pin (MTDI) |
| GPIO9 | — | — | BOOT button (Key2, 10 kΩ pull-up); strapping pin (boot mode) |
| GPIO16 | — | — | UART0 TXD |
| GPIO17 | — | — | UART0 RXD |
| GPIO18 | — | — | SDIO_CMD (SDIO mode) |
| GPIO19 | — | — | SDIO_CLK (SDIO mode) |
| GPIO20 | — | — | SDIO_D0 (SDIO mode) |
| GPIO23 | — | — | SDIO_D3 (SDIO mode) |

### Reserved / not exposed

| GPIO | Function | Notes |
|------|----------|-------|
| GPIO6 | SPI MOSI | Shared LCD_DIN / SD_MOSI — not for general use |
| GPIO7 | SPI CLK | Shared LCD_CLK / SD_SCLK — not for general use |
| GPIO8 | WS2812B LED | Onboard addressable RGB LED |
| GPIO12 | USB D− | USB Serial/JTAG — do not reconfigure |
| GPIO13 | USB D+ | USB Serial/JTAG — do not reconfigure |
| GPIO14 | LCD_CS | LCD chip select |
| GPIO15 | LCD_DC | LCD data/command |
| GPIO21 | LCD_RST / SDIO_D1 | LCD reset or SDIO 4-bit mode |
| GPIO22 | LCD_BL / SDIO_D2 | LCD backlight or SDIO 4-bit mode |
| GPIO10, GPIO11 | — | Do not exist on QFN32 package |

## LED

| GPIO | Type | Protocol | Notes |
|------|------|----------|-------|
| GPIO8 | WS2812B-0807 | WS2812 (single-wire, timed pulse) | Addressable RGB. 800 kHz. **Byte order is RGB (not GRB)**: the actual part is Xinglight XL-0807RGBC-WS2812B; its datasheet explicitly specifies R, G, B channel order throughout ("single line transmission three channel (RGB)"). Standard WS2812B uses GRB — this variant differs. Send `{0xFF,0x00,0x00}` for red. See `$IDF_PATH/examples/peripherals/rmt/led_strip/` |

## Display

### ST7789V3 TFT LCD — 1.47 inch

| Parameter | Value |
|-----------|-------|
| Module part number | LBS147TC-IF15 |
| Driver IC | ST7789V3 |
| Size | 1.47 inch |
| Resolution | 172 (H) × 320 (V) pixels |
| Color depth | 262K colors (18-bit, driven as RGB565 over SPI) |
| Display mode | Normally black, transmissive |
| Pixel arrangement | RGB vertical stripe |
| Interface | 4-line SPI |
| Active area | 17.39 mm (H) × 32.35 mm (V) |
| Pixel pitch | 0.034 mm (H) × 0.101 mm (V) |
| Luminance | 350 cd/m² (typ) |
| Contrast ratio | 1000:1 (typ) |
| Viewing angle | ≥ 80° all directions |
| Backlight | 2 white LEDs in parallel; Vf = 2.8–3.2 V, If = 40 mA typ |
| Operating temp | −20 °C to +70 °C |

#### SPI signal connections

| LCD signal | GPIO | Description |
|------------|------|-------------|
| SCL (CLK) | GPIO7 | SPI clock |
| SDA (DIN) | GPIO6 | SPI MOSI |
| CS | GPIO14 | Chip select, active low |
| D/C (RS) | GPIO15 | Data (high) / command (low) |
| RES | GPIO21 | Reset, active low |
| LED (BL) | GPIO22 | Backlight enable |

#### SPI timing constraints

| Parameter | Min | Notes |
|-----------|-----|-------|
| SCL write cycle | 16 ns | Max write clock ≈ 62.5 MHz |
| SCL high / low width | 7 ns | |
| CS setup / hold | 15 ns | |
| D/CX setup | 10 ns | |

#### Backlight circuit

Backlight is driven by SI2302CDS N-channel MOSFET (Q1):
- Gate: GPIO22 → 1 kΩ (R9) → MOSFET gate
- 100 kΩ (R7) pull-down ensures LED off when GPIO is floating
- Source connected to GND; drain to LED cathode
- Supports PWM brightness control via ESP32-C6 LEDC peripheral on GPIO22

#### ESP-IDF driver note

Use the `esp_lcd` component with SPI bus. The ST7789V3 is register-compatible
with ST7789. Confirmed working settings:

- `x_gap = 34` (34-pixel horizontal offset; panel uses columns 34–205 of the 240-wide GRAM)
- `y_gap = 0` (panel uses all 320 rows)
- `mirror_x = true`, `mirror_y = false` — portrait orientation, y=0 at top (away from USB connector)
- `data_endian = LCD_RGB_DATA_ENDIAN_LITTLE` — **required**: ESP32-C6 DMA sends the low byte of each RGB565 word first; without this the ST7789 defaults to big-endian and all colors are scrambled
- `invert_color = true` — required for correct luminance on this normally-black panel
- `rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB`
- `bits_per_pixel = 16` (RGB565)
- Backlight: GPIO22 HIGH = on (N-MOSFET gate, active high)
- SPI clock: up to ~40 MHz tested; panel spec allows ~62.5 MHz max

Reference: `$IDF_PATH/examples/peripherals/lcd/tjpgd/`

## Strapping pins

| Pin | Function | Default at reset | Notes |
|-----|----------|-----------------|-------|
| GPIO8 | Boot mode (with GPIO9); ROM UART print control | Floating | Float or high → SPI boot |
| GPIO9 | Boot mode (with GPIO8) | Pull-up (=1) | High → SPI boot (normal); low → Download boot; Key2 shorts to GND |
| GPIO15 | JTAG signal source | Floating | Low → select USB JTAG; not pulled on board |
| MTMS (GPIO4) | SDIO sampling/driving clock edge | Floating | Sampled at reset only; free as GPIO4 afterward |
| MTDI (GPIO5) | SDIO sampling/driving clock edge | Floating | Sampled at reset only; free as GPIO5 afterward |

To enter Download (flash) mode manually: hold Key2 (GPIO9 to GND) while
pressing Key1 (RESET / CHIP_PU).

## Power

| Source | Voltage | Notes |
|--------|---------|-------|
| USB-C | 5V input | Programming, JTAG, and board power |
| 3.3V rail | 3.3V | ME6217C33M5G LDO regulator from 5V |

No LiPo battery connector on this board.

## USB

The ESP32-C6's built-in USB Serial/JTAG controller uses GPIO12 (D−) and
GPIO13 (D+). The USB-C connector provides:

- JTAG debugging (used by OpenOCD / `idf.py flash monitor`)
- USB CDC-ACM serial (secondary console, not UART0)
- 5V board power

Do not reconfigure GPIO12 or GPIO13.

## Flash

| Size | Type | Notes |
|------|------|-------|
| 4 MB | Quad SPI (in-package) | Memory-mapped: 0x42000000 (instruction) / 0x3C000000 (data) |

## Buttons

| Button | Signal | GPIO | Notes |
|--------|--------|------|-------|
| Key1 | RESET | CHIP_PU | Resets the chip; 10 kΩ pull-up (R4) to 3.3V |
| Key2 | BOOT | GPIO9 | Hold at power-on for Download boot mode; 10 kΩ pull-up (R5) to 3.3V |

## Board-specific constraints

- GPIO6 and GPIO7 are shared between LCD and SD card — do not use both
  peripherals concurrently without CS control; these pins are not available
  for general GPIO
- GPIO8 is hardwired to the WS2812B LED — not available for general use
- GPIO12/GPIO13 are USB D−/D+ — do not reconfigure
- GPIO14, GPIO15, GPIO21, GPIO22 are dedicated to the LCD; reuse requires
  disabling LCD driver initialization
- SDIO 4-bit mode (GPIO18–GPIO23) conflicts with LCD_RST (GPIO21) and
  LCD_BL (GPIO22); LCD must not be active during SDIO 4-bit transfers
- GPIO9 is the BOOT strapping pin — must be high (pulled up, Key2 released)
  at reset for normal SPI boot
- GPIO4 (MTMS) and GPIO5 (MTDI) are strapping pins sampled at reset; they
  should be floating or weakly pulled during boot
- GPIO15 (JTAG source select) has no pull resistor on the board; leave
  floating for USB JTAG (default)
- No 32 kHz crystal is fitted; GPIO0/GPIO1 XTAL_32K_P/N function is
  unavailable — do not use it
- GPIO10 and GPIO11 do not exist on the QFN32 package
- No PSRAM on this module
- PCB antenna is at the board edge — avoid metal or ground planes near it
- All ADC channels (GPIO0–GPIO6) are on ADC1; Wi-Fi does not block ADC1 on
  ESP32-C6 (no ADC2 exists on this chip)

## References

- [Waveshare Wiki](https://www.waveshare.com/wiki/ESP32-C6-LCD-1.47)
- [ESP32-C6 Datasheet](https://www.espressif.com/documentation/esp32-c6_datasheet_en.pdf)
- [ESP32-C6 TRM (pre-release v0.3)](https://www.espressif.com/documentation/esp32-c6_technical_reference_manual_en.pdf)
- [ST7789V3 datasheet](https://www.waveshare.com/wiki/File:ST7789V3_SPEC_V1.0.pdf)
- [XL-0807RGBC-WS2812B datasheet (Xinglight)](https://files.waveshare.com/wiki/ESP32-S3-Nano/XL-0807RGBC-WS2812B.pdf)
