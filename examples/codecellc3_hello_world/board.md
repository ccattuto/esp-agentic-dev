# Board: CodeCell C3 (Microbots)

A compact (18.5 × 18.5 mm) development module by Microbots featuring
the ESP32-C3-MINI-1-N4. Designed for robotics, wearables, and IoT.
Includes onboard light/proximity sensor, optional 9-axis IMU, LiPo
battery charging, and USB-C for power/programming/debugging.

## MCU

| Parameter | Value |
|-----------|-------|
| Module | ESP32-C3-MINI-1-N4 |
| Core | 32-bit RISC-V single-core, up to 160 MHz |
| Flash | 4 MB (SPI, in-package) |
| SRAM | 400 KB |
| Wireless | Wi-Fi 802.11 b/g/n, Bluetooth 5 (LE) |

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
| GPIO0 | IO0 | — | Yes | General purpose |
| GPIO1 | IO1 | ADC1_CH1 | Yes | Analog input capable |
| GPIO2 | IO2 | ADC1_CH2 | Yes | Analog input capable; strapping pin (pull up recommended) |
| GPIO3 | IO3 | ADC1_CH3 | Yes | Analog input capable |
| GPIO4 | IO4 | ADC1_CH4 | Yes | General purpose |
| GPIO5 | IO5 | ADC2_CH0 | Yes | General purpose |
| GPIO8 | SDA | — | Yes | I2C data; shared with onboard sensors |
| GPIO9 | SCL | — | Yes | I2C clock; shared with onboard sensors; strapping pin (boot mode) |

### Reserved / not exposed

| Pin | Function | Notes |
|-----|----------|-------|
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

### BNO085 — 9-axis IMU (optional, depends on board variant)

| Parameter | Value |
|-----------|-------|
| I2C address | 0x4A |
| Bus | I2C0 (GPIO8/GPIO9) |
| Capabilities | 3-axis accelerometer, gyroscope, magnetometer; onboard sensor fusion providing roll/pitch/yaw, activity classification, tap detection, step counting |
| Datasheet | [BNO085](https://www.ceva-ip.com/wp-content/uploads/BNO080_085-Datasheet.pdf) |

Not present on the "C3 Light" variant. Check which board variant you
have before referencing the IMU in firmware.

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

- GPIO10 is hardwired to the SK6805 LED — not available for general use
- GPIO18/GPIO19 are USB — not available for general use
- GPIO8/GPIO9 are shared between I2C headers and onboard sensors —
  external I2C devices must not conflict with addresses 0x60 (VCNL4040)
  or 0x4A (BNO085)
- GPIO2 is a strapping pin — avoid heavy loads or capacitance
- GPIO9 is a strapping pin (boot mode select) — avoid pulling low at
  boot unless intentionally entering download mode
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
