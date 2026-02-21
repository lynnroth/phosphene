# phosphene

Wireless battery-powered theatrical lighting system for live performance.

**ETC Eos** → Ethernet → **LoRa 915MHz** → battery-powered **NeoPixel endpoints**

No DMX cables. No WiFi. No power drops to the stage.

---

## Hardware

| Role | Board | Part |
|---|---|---|
| Gateway | Adafruit ESP32-S3 Feather | #5477 |
| Endpoint × 2 | Adafruit ESP32-S3 Feather | #5477 |
| LoRa radio × 3 | Adafruit RFM95W 915MHz | #3072 |
| Ethernet | Adafruit WIZ5500 Breakout | #6348 |
| LiPo charger + 5V boost × 2 | Adafruit bq25185 | #6106 |
| Antenna × 3 | 915MHz spring antenna | #4269 |
| Battery × 2 | 2500mAh LiPo | #328 |

## Repository Layout

```
phosphene/
├── gateway/
│   └── code.py          # ESP32-S3 Feather: sACN → LoRa gateway
├── endpoint/
│   └── code.py          # ESP32-S3 Feather: LoRa → NeoPixel endpoint
├── wiring/
│   ├── gateway_wiring.html
│   └── endpoint_wiring.html
└── docs/
    └── eos_patch_guide.md
```

## How It Works

The **gateway** sits at the side of the stage or in the booth. It receives sACN (E1.31) from Eos over Ethernet and translates DMX channel values into compact 9-byte LoRa packets. Each command is transmitted three times at 50ms intervals for redundancy.

The **endpoints** are battery-powered, fully wireless, and hidden in props or rigging. Each listens for LoRa packets addressed to its device ID (or the broadcast address 0), applies duplicate suppression, and runs the specified effect on its NeoPixel strip.

## Packet Protocol

9-byte binary packet, all fields 0–255:

| Byte | Field | Notes |
|---|---|---|
| 0 | Device ID | 0 = broadcast, 1–5 = specific endpoint |
| 1 | Command ID | Auto-increments, used for dedup |
| 2 | Preset | 0–25, see preset map below |
| 3 | Intensity | 0–255 |
| 4 | Red | 0–255 |
| 5 | Green | 0–255 |
| 6 | Blue | 0–255 |
| 7 | Speed | 0=slow, 255=fast |
| 8 | Checksum | XOR of bytes 0–7 |

## Presets

| DMX Range | # | Effect |
|---|---|---|
| 0–9 | 0 | Blackout |
| 10–19 | 1 | Sparkle |
| 20–29 | 2 | Chase |
| 30–39 | 3 | Fade (breathe) |
| 40–49 | 4 | Solid |
| 50–59 | 5 | Twinkle on Solid |
| 60–69 | 6 | Strobe |
| 70–79 | 7 | Meteor |
| 80–89 | 8 | Fire |
| 90–99 | 9 | Rainbow |
| 100–109 | 10 | Lightning |
| 110–119 | 11 | Marquee |
| 120–129 | 12 | Candle |
| 130–139 | 13 | Color Wipe |
| 140–149 | 14 | Heartbeat |
| 150–159 | 15 | Alarm |
| 160–169 | 16 | Comet |
| 170–179 | 17 | Ripple |
| 180–189 | 18 | Scanner (Cylon) |
| 190–199 | 19 | Bubbles |
| 200–209 | 20 | Campfire |
| 210–219 | 21 | Confetti |
| 220–229 | 22 | Wave |
| 230–239 | 23 | Flicker |
| 240–249 | 24 | Theater Chase |
| 250–255 | 25 | Rainbow Chase |

## Eos Patch

Each device occupies 7 consecutive DMX channels:

| Offset | Channel | Range |
|---|---|---|
| +0 | Preset select | 0–255 (maps to presets via table above) |
| +1 | Intensity | 0–255 |
| +2 | Red | 0–255 |
| +3 | Green | 0–255 |
| +4 | Blue | 0–255 |
| +5 | Speed | 0–255 |
| +6 | Reserved | — |

Default patch:
- Device 0 (broadcast): address 50
- Device 1: address 1
- Device 2: address 8

## Setup

### Gateway
1. Install CircuitPython 10.1.1 for **Adafruit Feather ESP32-S3 4MB/2MB PSRAM** from [circuitpython.org](https://circuitpython.org/board/adafruit_feather_esp32s3/)
2. Install libraries into `/lib`: `adafruit_rfm9x`, `adafruit_wiznet5k`, `adafruit_bus_device`
3. Edit `gateway/code.py`: set `STATIC_IP` to match your network, set `SACN_UNIVERSE` to match Eos output
4. Copy `gateway/code.py` to the board as `code.py`
5. In Eos: **Setup > Show > Output > Add sACN universe** pointing to the gateway's IP

### Endpoints
1. Install CircuitPython 10.1.1 for **Adafruit Feather ESP32-S3 4MB/2MB PSRAM**
2. Install libraries into `/lib`: `adafruit_rfm9x`, `neopixel`, `adafruit_pixelbuf`
3. Edit `endpoint/code.py`: set `DEVICE_ID` (1 on first board, 2 on second), set `NUM_PIXELS`
4. Copy `endpoint/code.py` to each board as `code.py`

### LoRa Settings
All three radios must use identical settings (defaults in code):
- Frequency: 915.0 MHz
- Spreading factor: 7
- Bandwidth: 250 kHz
- Coding rate: 4/5

## Power

Each endpoint runs from a single 2500mAh LiPo. The battery feeds two paths:
- **Feather JST** → powers ESP32-S3 and RFM95W via the Feather's 3.3V regulator
- **bq25185 BATT port** → boosts to regulated 5V for the NeoPixel strip

Runtime at typical theatrical effect load (~400mA NeoPixels + 150mA Feather): **~4.5 hours**

Charge via the **bq25185 USB-C port only**. Do not connect both USB-C ports simultaneously.

> ⚠️ Avoid full-white at full brightness (40 pixels × 60mA = 2.4A, exceeds bq25185 1A boost limit). Theatrical effects at moderate intensity stay well within limits.

## License

MIT
