# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phosphene is a wireless battery-powered theatrical lighting system. An ETC Eos lighting console sends DMX via sACN (E1.31) over Ethernet to a **gateway** board, which translates commands into LoRa (915MHz) radio packets and broadcasts them to battery-powered **endpoint** boards driving NeoPixel LED strips. This eliminates DMX cables and power drops on stage.

## Tech Stack

- **Language:** CircuitPython 10.1.1 (runs directly on microcontrollers — no build step)
- **Platform:** Adafruit ESP32-S3 Feather (#5477)
- **Protocols:** sACN/E1.31 (UDP port 5568) → LoRa 915MHz → NeoPixel
- **Key libraries:** `adafruit_rfm9x`, `adafruit_wiznet5k`, `neopixel`, `adafruit_bus_device`

## Deployment

There is no build system. Development workflow:

1. Connect the ESP32-S3 board via USB — it mounts as a USB drive (`CIRCUITPY`)
2. Copy `gateway/code.py` or `endpoint/code.py` directly to `CIRCUITPY/code.py`
3. CircuitPython auto-reloads on save; use a serial monitor (e.g., `screen /dev/ttyUSB0 115200` or Mu editor) to view output
4. Third-party libraries must be installed separately into `CIRCUITPY/lib/` from the [CircuitPython Library Bundle](https://circuitpython.org/libraries)

**Secrets/config not in repo:** Network credentials and device-specific settings go in `secrets.py` or `settings.toml` on the board (git-ignored).

## Architecture

### Control Flow

```
Eos console → sACN UDP → Gateway (WIZ5500 Ethernet)
                               ↓ parse DMX channels
                         Build 9-byte LoRa packet
                               ↓ transmit 3× (50ms apart)
                         Endpoint (RFM95W LoRa RX)
                               ↓ verify XOR checksum, dedup
                         Apply effect + run effect loop at ~100fps
```

### 9-Byte Packet Protocol

| Byte | Field | Notes |
|------|-------|-------|
| 0 | Device ID | 0=broadcast, 1–5=specific endpoint |
| 1 | Command ID | Auto-incrementing, used for dedup |
| 2 | Preset | 0–25 (maps to effect function) |
| 3 | Intensity | 0–255 |
| 4–6 | R, G, B | Color |
| 7 | Speed | 0=slow, 255=fast |
| 8 | Checksum | XOR of bytes 0–7 |

### Gateway (`gateway/code.py`)

Key functions:
- `parse_sacn(data)` — parses raw E1.31 UDP payload
- `build_packet(...)` — constructs the 9-byte LoRa command
- `dmx_to_preset(raw_value)` — maps DMX 0–255 to preset index 0–25
- `schedule_sends(packet)` — queues 3 redundant transmits at 50ms spacing
- `check_device_changes()` — detects DMX changes and triggers scheduling

Configurable at top of file: static IP (`192.168.1.50`), device-to-DMX address map (6 devices), LoRa radio params (SF7, 250kHz BW).

Hardware SPI buses: primary SPI → WIZ5500 (CS=D9); secondary SPI → RFM95W (CS=D13, RST=A0, IRQ=A1).

### Endpoint (`endpoint/code.py`)

Key configuration at top of file: `DEVICE_ID` (unique per board, 1–5), `NUM_PIXELS`, `NEOPIXEL_PIN`.

Key functions:
- `apply_packet(packet)` — verifies checksum, deduplicates (1s window by command ID), updates effect state
- `effect_*()` — 26 effect implementations called from main loop
- `scale_color(r, g, b, intensity)` — applies intensity scaling
- `speed_to_rate(speed_byte, slow_val, fast_val)` — maps speed byte to animation interval
- `hsv_to_rgb(h, s, v)` — used by rainbow/color-cycling effects

Main loop runs at ~100fps (10ms sleep), receiving LoRa packets non-blocking (`timeout=0.0`) and calling the current effect function each iteration.

### DMX Channel Layout (per device, 7 channels)

| Ch | Parameter |
|----|-----------|
| 1 | Preset (0–255 mapped to 0–25) |
| 2 | Intensity |
| 3 | Red |
| 4 | Green |
| 5 | Blue |
| 6 | Speed |
| 7 | Reserved |

## Key Files

| File | Purpose |
|------|---------|
| `gateway/code.py` | Gateway firmware: sACN → LoRa |
| `endpoint/code.py` | Endpoint firmware: LoRa → NeoPixel effects |
| `docs/eos_patch_guide.md` | Eos console patch configuration |
| `wiring/gateway_wiring.html` | Interactive GPIO wiring diagram (gateway) |
| `wiring/endpoint_wiring.html` | Interactive GPIO wiring diagram (endpoint) |
