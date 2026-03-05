# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Phosphene is a wireless battery-powered theatrical lighting system. An ETC Eos lighting console sends DMX via sACN (E1.31) over Ethernet to a **gateway** board, which translates commands into LoRa (915MHz) radio packets and broadcasts them to battery-powered **endpoint** boards driving NeoPixel LED strips. This eliminates DMX cables and power drops on stage.

## Tech Stack

- **Language:** CircuitPython 10.1.1 (runs directly on microcontrollers — no build step)
- **Platform:** Adafruit ESP32-S3 Feather (#5477)
- **Protocols:** sACN/E1.31 (UDP 5568) or ArtNet (UDP 6454) → LoRa 915MHz → NeoPixel
- **Key libraries:** `adafruit_rfm9x`, `adafruit_wiznet5k`, `neopixel`, `adafruit_bus_device`

## Deployment

There is no build system. Development workflow:

1. Connect the ESP32-S3 board via USB — it mounts as a USB drive (`CIRCUITPY`)
2. For gateway: copy `gateway/code.py` to `CIRCUITPY/code.py`
3. For endpoint: copy entire `endpoint/` folder to `CIRCUITPY/` (includes code.py, config.py, hardware.py, effects/)
4. CircuitPython auto-reloads on save; use a serial monitor (e.g., `screen /dev/ttyUSB0 115200` or Mu editor) to view output
5. Third-party libraries must be installed separately into `CIRCUITPY/lib/` from the [CircuitPython Library Bundle](https://circuitpython.org/libraries)

**Secrets/config not in repo:** Network credentials and device-specific settings go in `secrets.py` or `settings.toml` on the board (git-ignored).

## Architecture

### Control Flow

```
Eos console → sACN or ArtNet UDP → Gateway (WIZ5500 Ethernet, or WiFi if DMX_WIFI_ENABLED)
                               ↓ parse DMX channels
                         Build 12-byte LoRa packet
                               ↓ transmit 3× (50ms apart)
                         Endpoint (RFM95W LoRa RX)
                               ↓ verify XOR checksum, dedup
                         Apply effect + run effect loop at ~100fps
                               ↓ (if ACK requested) send 7-byte ACK after stagger delay
                         Gateway receives ACK → web UI status dots
```

### 12-Byte Command Packet Protocol

| Byte | Field | Notes |
|------|-------|-------|
| 0 | Device ID | 0=broadcast, 1–5=specific endpoint |
| 1 | Command ID | Auto-incrementing, used for dedup |
| 2 | Preset | 0–27 (maps to effect function) |
| 3 | Intensity | 0–255 |
| 4–6 | R, G, B | Color |
| 7 | Speed | 0=slow, 255=fast |
| 8 | Config flags | Bit 0 = `CONFIG_ACK_REQUESTED` (0x01) |
| 9–10 | Reserved | Send 0x00 |
| 11 | Checksum | XOR of bytes 0–10 |

### 7-Byte ACK Packet Protocol (endpoint → gateway)

| Byte | Field | Notes |
|------|-------|-------|
| 0 | 0xAC | Marker byte |
| 1 | Device ID | Sender's device ID (1–5) |
| 2 | Command ID | Command being ACKed |
| 3 | RSSI encoded | `(rssi + 200) & 0xFF`; decode: `byte - 200` |
| 4 | Battery % | 0–100, or 255 = not available |
| 5 | Reserved | 0x00 |
| 6 | Checksum | XOR of bytes 0–5 |

ACK stagger: endpoint sends at `150ms + DEVICE_ID × 80ms` after receiving (avoids LoRa collision). Gateway listens on UDP port 5570 for WiFi ACKs.

### Gateway (`gateway/code.py`)

Key functions:
- `parse_sacn(data)` — parses raw E1.31 UDP payload
- `parse_artnet(data)` — parses raw ArtNet ArtDmx payload
- `build_packet(...)` — constructs the 12-byte LoRa command
- `dmx_to_preset(raw_value)` — maps DMX 0–255 to preset index 0–27
- `schedule_sends(packet)` — queues 3 redundant transmits at 50ms spacing
- `check_device_changes()` — detects DMX changes and triggers scheduling

All configurable options (static IP, protocol, universe, patch map, WiFi credentials, DMX_WIFI_ENABLED) are read from `settings.toml` on the board at boot. LoRa radio params (SF7, 250kHz BW) remain as constants in the code.

Hardware SPI buses: primary SPI → WIZ5500 (CS=A5, RST=A0); secondary SPI → RFM95W (CS=D13, RST=D5, IRQ=D6).

Boot NeoPixel sequence: amber → cyan dim (ETH init) → cyan (ETH OK) / red (fail) → green dim (LoRa init) → green (LoRa OK) / amber (fail) → blue (WiFi AP) → off (running). Cyan 2s flash when Ethernet link comes up. During operation, flashes per-device colour on each command sent.

### Endpoint (`endpoint/`)

The endpoint code is organized into multiple modules:

```
endpoint/
├── code.py           # Main entry, main loop
├── config.py         # Configuration loading from settings.toml
├── hardware.py       # Hardware initialization
└── effects/
    ├── __init__.py   # Base Effect classes, EFFECTS registry, helpers
    ├── simple.py     # Solid, Fade, Strobe, Heartbeat, Alarm, ColorWipe, Ripple
    ├── chase.py      # Chase, Marquee, TheaterChase, RainbowChase, Scanner
    ├── sparkle.py    # Sparkle, Twinkle, Confetti, Bubbles, Flicker
    ├── fire.py       # Fire, Campfire
    ├── weather.py    # Rainbow, Lightning, Aurora
    └── wave.py       # Wave, WavePastel, Comet, ColorWipe
```

Key configuration in `settings.toml`: `DEVICE_ID` (1-5), `NUM_PIXELS`, `NEOPIXEL_PIN`.

Each effect is a class inheriting from a base (`Simple`, `Chase`, `Fire`, `Sparkle`, `Rainbow`) with:
- `__init__(num_pixels)` - initialize state
- `reset()` - called on preset change
- `update(pixels, r, g, b, intensity, speed)` - called every frame

Main loop runs at ~100fps (10ms sleep).

### DMX Channel Layout (per device, 7 channels)

| Ch | Parameter |
|----|-----------|
| 1 | Preset (0–255 mapped to 0–27) |
| 2 | Intensity |
| 3 | Red |
| 4 | Green |
| 5 | Blue |
| 6 | Speed |
| 7 | Reserved |

## Key Files

| File | Purpose |
|------|---------|
| `gateway/code.py` | Gateway firmware: sACN/ArtNet → LoRa |
| `endpoint/code.py` | Endpoint main loop |
| `endpoint/config.py` | Endpoint configuration loading |
| `endpoint/hardware.py` | Endpoint hardware init |
| `endpoint/effects/` | Effect classes |
| `docs/eos_patch_guide.md` | Eos console patch configuration |
| `wiring/gateway_wiring.html` | Interactive GPIO wiring diagram (gateway) |
| `wiring/endpoint_wiring.html` | Interactive GPIO wiring diagram (endpoint) |
| `settings.toml` | Sample settings file — copy to CIRCUITPY/settings.toml on each board |
| `docs/phosphene_endpoint.gdtf.xml` | GDTF 1.1 fixture profile for ETC Eos import |
