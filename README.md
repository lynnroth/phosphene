# phosphene

Wireless battery-powered theatrical lighting system for live performance.

**ETC Eos** → Ethernet → **LoRa 915MHz** → battery-powered **NeoPixel endpoints**

No DMX cables. No WiFi dependency — LoRa runs standalone. No power drops to the stage.

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
│   ├── code.py          # ESP32-S3 Feather: sACN/ArtNet → LoRa gateway
│   └── ui.html          # Web UI (copy to CIRCUITPY/gateway/ui.html)
├── endpoint/
│   └── code.py          # ESP32-S3 Feather: LoRa → NeoPixel endpoint
├── wiring/
│   ├── gateway_wiring.html
│   └── endpoint_wiring.html
├── docs/
│   ├── eos_patch_guide.md
│   └── phosphene_endpoint.gdtf.xml   # GDTF fixture profile for Eos import
└── settings.toml                     # Sample settings (copy to CIRCUITPY/settings.toml)
```

## How It Works

The **gateway** sits at the side of the stage or in the booth. It receives sACN (E1.31) or ArtNet from Eos over Ethernet and translates DMX channel values into compact 12-byte LoRa packets. Each command is transmitted three times at 50ms intervals for redundancy. Protocol (sACN or ArtNet) and all other options are set via `settings.toml` on the board — no code changes needed. Optionally, `DMX_WIFI_ENABLED = 1` makes the gateway also listen for DMX on the WiFi interface. A WiFi access point provides a touch-friendly web UI for direct control and live monitoring.

The **endpoints** are battery-powered, fully wireless, and hidden in props or rigging. Each listens for LoRa packets addressed to its device ID (or the broadcast address 0), applies duplicate suppression, and runs the specified effect on its NeoPixel strip. When ACK mode is enabled on the gateway, endpoints send back a confirmation packet carrying RSSI and battery level.

## Status Indicators

### Gateway — onboard NeoPixel (boot sequence)

The gateway's single onboard NeoPixel steps through colours during boot so you can see exactly where it stops if something fails.

| Colour | Stage |
|---|---|
| Amber | Power-on, starting up |
| Cyan (dim) | WIZ5500 Ethernet chip initialising |
| Cyan | WIZ5500 ready |
| **Red** (stays on) | WIZ5500 failed — check SPI wiring / RST pin |
| Green (dim) | RFM95W LoRa radio initialising |
| Green | LoRa radio ready |
| **Amber** (stays on) | LoRa radio failed — check SPI wiring / EN pin |
| Blue | WiFi AP starting |
| Off | Fully running — ready for commands |
| Cyan flash (2 s) | Ethernet link came up, IP configured |

During normal operation the pixel flashes briefly per-device colour when a command is sent (red=device 1, green=2, blue=3, cyan=4, magenta=5, amber=broadcast).

### Endpoint — onboard NeoPixel (event flashes)

The endpoint pixel flashes on packet events. Controlled by `STATUS_LED_ENABLED` and `STATUS_LED_BRIGHTNESS` in `settings.toml` (set `STATUS_LED_ENABLED = "0"` to disable during performance).

| Colour | Event |
|---|---|
| Green | Valid command received and applied |
| Yellow | Duplicate command ignored |
| Red | Checksum error |
| Cyan flash | ACK transmitted back to gateway |

## Packet Protocol

12-byte binary command packet (gateway → endpoint):

| Byte | Field | Notes |
|---|---|---|
| 0 | Device ID | 0 = broadcast, 1–5 = specific endpoint |
| 1 | Command ID | Auto-increments, used for dedup |
| 2 | Preset | 0–27, see preset map below |
| 3 | Intensity | 0–255 |
| 4 | Red | 0–255 |
| 5 | Green | 0–255 |
| 6 | Blue | 0–255 |
| 7 | Speed | 0=slow, 255=fast |
| 8 | Config flags | Bit 0 = ACK requested |
| 9–10 | Reserved | 0x00 |
| 11 | Checksum | XOR of bytes 0–10 |

7-byte ACK packet (endpoint → gateway, when ACK mode enabled):

| Byte | Field | Notes |
|---|---|---|
| 0 | 0xAC | Marker |
| 1 | Device ID | Sender |
| 2 | Command ID | Command being ACKed |
| 3 | RSSI encoded | `rssi + 200`; decode: `byte − 200` |
| 4 | Battery % | 0–100, or 255 = not available |
| 5 | Reserved | 0x00 |
| 6 | Checksum | XOR of bytes 0–5 |

## Presets

Each preset occupies 5 DMX values.

| DMX Range | # | Effect |
|---|---|---|
| 0–4 | 0 | Blackout |
| 5–9 | 1 | Sparkle |
| 10–14 | 2 | Chase |
| 15–19 | 3 | Fade (breathe) |
| 20–24 | 4 | Solid |
| 25–29 | 5 | Twinkle on Solid |
| 30–34 | 6 | Strobe |
| 35–39 | 7 | Meteor |
| 40–44 | 8 | Fire |
| 45–49 | 9 | Rainbow |
| 50–54 | 10 | Lightning |
| 55–59 | 11 | Marquee |
| 60–64 | 12 | Candle |
| 65–69 | 13 | Color Wipe |
| 70–74 | 14 | Heartbeat |
| 75–79 | 15 | Alarm |
| 80–84 | 16 | Comet |
| 85–89 | 17 | Ripple |
| 90–94 | 18 | Scanner (Cylon) |
| 95–99 | 19 | Bubbles |
| 100–104 | 20 | Campfire |
| 105–109 | 21 | Confetti |
| 110–114 | 22 | Wave |
| 115–119 | 23 | Flicker |
| 120–124 | 24 | Theater Chase |
| 125–129 | 25 | Rainbow Chase |
| 130–134 | 26 | Aurora |
| 135–139 | 27 | Wave Pastel |

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

Default patch (used when no `PATCH_N` keys are set in `settings.toml`):
- Device 0 (broadcast): address 50
- Device 1: address 1 — Device 2: address 8 — Device 3: address 15 — Device 4: address 22 — Device 5: address 29

Override any address by setting `PATCH_0` through `PATCH_5` in the gateway's `settings.toml`. Only devices with a `PATCH_N` key present are monitored.

## Setup

### Gateway
1. Install CircuitPython 10.1.1 for **Adafruit Feather ESP32-S3 4MB/2MB PSRAM** from [circuitpython.org](https://circuitpython.org/board/adafruit_feather_esp32s3/)
2. Install libraries into `/lib`: `adafruit_rfm9x`, `adafruit_wiznet5k`, `adafruit_bus_device`, `adafruit_httpserver`
3. Copy `gateway/code.py` to the board as `code.py`
4. Copy `gateway/ui.html` to `CIRCUITPY/gateway/ui.html` on the board
5. Copy `settings.toml` from the repo to `CIRCUITPY/settings.toml` and edit the gateway section:
   - Set `PROTOCOL` to `"sacn"` or `"artnet"` to match your Eos output
   - Set `STATIC_IP` (or `USE_DHCP = 1`) to match your show network
   - Set `SACN_UNIVERSE` or `ARTNET_UNIVERSE` to match Eos
   - Set `PATCH_N` keys for your actual DMX patch addresses (see `docs/eos_patch_guide.md`)
   - Set `DMX_WIFI_ENABLED = 1` if you want Eos to reach the gateway over WiFi instead of Ethernet
6. In Eos: **Setup > Show > Output** — add sACN or ArtNet output
   - sACN: set destination to the gateway's static IP, universe 1
   - ArtNet: set Broadcast Mode to **Broadcast** (gateway does not respond to ArtPoll)
7. Optional: import `docs/phosphene_endpoint.gdtf.xml` into Eos for named preset labels and colour picker (see `docs/eos_patch_guide.md`)

### Web UI

The gateway runs a WiFi access point named **phosphene** (password: `gobo1234` by default, configurable via `settings.toml`). Connect a phone or tablet to this AP and open **http://192.168.4.1:8080** to get a touch-friendly preset/intensity/color control panel.

The web UI and Eos sACN are designed for independent use — both routes drive the same LoRa transmit queue, so any command from either source reaches endpoints identically.

### Endpoints
1. Install CircuitPython 10.1.1 for **Adafruit Feather ESP32-S3 4MB/2MB PSRAM**
2. Install libraries into `/lib`: `adafruit_rfm9x`, `neopixel`, `adafruit_pixelbuf`, `adafruit_max1704x`, `adafruit_lc709203f`, `adafruit_bus_device`
3. Copy `endpoint/code.py` to the board as `code.py`
4. Copy `settings.toml` from the repo to `CIRCUITPY/settings.toml` and edit the endpoint section:
   - Set `DEVICE_ID` to a unique value (1–5) per board
   - Set `NUM_PIXELS` to the length of the NeoPixel strip
   - Set `NEOPIXEL_PIN` to the GPIO pin connected to the strip data line
   - Set `WIFI_AP_SSID` and `WIFI_AP_PASSWORD` to match the gateway's AP credentials

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
