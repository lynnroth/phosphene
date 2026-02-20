# Eos Patch Guide

## Overview

Phosphene receives sACN Universe 1 from Eos. Each wireless endpoint occupies 7 consecutive DMX addresses. The gateway translates channel values to LoRa commands whenever a value changes.

## Default Address Map

| Device | DMX Start | Channels |
|---|---|---|
| Broadcast (all endpoints) | 50 | 50–56 |
| Endpoint 1 | 1 | 1–7 |
| Endpoint 2 | 8 | 8–14 |

To change the patch, edit `DEVICE_PATCH` in `gateway/code.py`.

## Channel Layout (per device)

| Offset | Label | Range | Notes |
|---|---|---|---|
| +0 | Preset | 0–255 | Divided into 10-DMX bands, see table |
| +1 | Intensity | 0–255 | Master brightness |
| +2 | Red | 0–255 | |
| +3 | Green | 0–255 | |
| +4 | Blue | 0–255 | |
| +5 | Speed | 0–255 | 0=slowest, 255=fastest |
| +6 | Reserved | — | Future use |

## Preset Bands

Set the Preset channel to any value in the range to select that effect.

| Range | Effect | Good for |
|---|---|---|
| 0–9 | Blackout | Cue out |
| 10–19 | Sparkle | Stars, magic |
| 20–29 | Chase | Energy, movement |
| 30–39 | Fade / Breathe | Tension, meditation |
| 40–49 | Solid | Practical lamp, area fill |
| 50–59 | Twinkle on Solid | Ambient shimmer |
| 60–69 | Strobe | Seizure warning — use carefully |
| 70–79 | Meteor | Shooting star, energy bolt |
| 80–89 | Fire | Torch, candelabra, fireplace |
| 90–99 | Rainbow | Party, pride, carnival |
| 100–109 | Lightning | Storm, tension, danger |
| 110–119 | Marquee | Old Hollywood, opening number |
| 120–129 | Candle | Intimate, romantic, period |
| 130–139 | Color Wipe | Slow reveal, transformation |
| 140–149 | Heartbeat | Tension, life/death moments |
| 150–159 | Alarm | Emergency, siren |
| 160–169 | Comet | One-shot streak |
| 170–179 | Ripple | Water, pond, calm |
| 180–189 | Scanner (Cylon) | Robotic, surveillance |
| 190–199 | Bubbles | Underwater, dreamy |
| 200–209 | Campfire | Warmer/softer fire |
| 210–219 | Confetti | Celebration, chaos |
| 220–229 | Wave | Ocean, undulation |
| 230–239 | Flicker | Dying bulb, fluorescent |
| 240–249 | Theater Chase | Classic marquee |
| 250–255 | Rainbow Chase | Rainbow marquee |

## Eos Setup Steps

1. **Enable sACN output**: Setup > Show > Output > Add sACN Output
2. **Set destination IP**: the gateway's static IP (default `192.168.1.50`)
3. **Set universe**: Universe 1 (must match `SACN_UNIVERSE` in gateway code)
4. **Patch channels**: Patch the 7-channel blocks per device at the addresses above
5. **Create attribute palette** for Preset values so operators can select effects by name

## Tips

- Use **submasters** for each endpoint — one submaster per device makes it easy to bring endpoints in/out independently.
- The **Intensity channel** scales all effects. Use it like a dimmer — effects still run at Intensity 0, they're just invisible, so when you bring it up the effect is already running.
- **Speed 128** is a good middle default for most effects. Go lower for atmospheric/slow scenes, higher for energy/dance numbers.
- The **broadcast address (50)** sends to all endpoints simultaneously. Useful for global blackout or synchronized looks.
- Gateway only sends a LoRa packet when a value **changes** — no traffic on a held cue.
