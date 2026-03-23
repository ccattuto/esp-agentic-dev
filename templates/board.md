# Board: [Board Name]

[Brief description of the board — manufacturer, form factor, key features.]

## Pin assignments

### I2C

| Bus | SDA | SCL | Speed | Connected devices |
|-----|-----|-----|-------|-------------------|
| I2C0 | GPIO5 | GPIO6 | 400kHz | — |

### SPI

| Bus | MOSI | MISO | CLK | CS | Connected devices |
|-----|------|------|-----|-----|-------------------|
| SPI2 | — | — | — | — | External flash |

### UART

| Port | TX | RX | Notes |
|------|-----|-----|-------|
| UART0 | GPIO21 | GPIO20 | USB Serial/JTAG console |

### GPIO

| Pin | Function | Direction | Notes |
|-----|----------|-----------|-------|
| GPIO10 | LED | Output | SK6805-EC10 addressable RGB (WS2812 protocol) |
| GPIO9 | BOOT button | Input | Active low, external pull-up |

## LEDs

| Pin | Type | Protocol | Notes |
|-----|------|----------|-------|
| GPIO10 | SK6805-EC10 | WS2812 (single-wire, timed pulse) | Cannot be driven by GPIO toggle — requires RMT or SPI bit-bang. 24-bit GRB, 800kHz. |

## Buttons

| Pin | Label | Active | Pull | Notes |
|-----|-------|--------|------|-------|
| GPIO9 | BOOT | Low | External pull-up | Can be used as general input after boot |

## USB

The board uses the ESP32-C3's built-in USB Serial/JTAG controller on
GPIO18 (D-) and GPIO19 (D+). This is the same USB connection used for
JTAG debugging — do not reconfigure these pins.

## Power

[Voltage levels, power domains, sleep mode considerations.]

## Flash

| Size | Type | Notes |
|------|------|-------|
| 4MB | Quad SPI | Memory-mapped at 0x3C000000 (data) / 0x42000000 (instruction) |

## Board-specific constraints

- [Any pins that must not be used or reconfigured]
- [Boot strapping pin requirements]
- [Known hardware errata or quirks]

## References

- [Link to schematic PDF]
- [Link to manufacturer documentation]
- [Link to datasheet for key components]
