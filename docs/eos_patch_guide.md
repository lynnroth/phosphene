# Eos Patch Guide

## Overview

Phosphene receives sACN Universe 1 from Eos. Each wireless endpoint occupies 7 consecutive DMX addresses. The gateway translates channel values to LoRa commands whenever a value changes.

## Default Address Map

| Device | DMX Start | Channels |
|---|---|---|
| Broadcast (all endpoints) | 50 | 50–56 |
| Endpoint 1 | 1 | 1–7 |
| Endpoint 2 | 8 | 8–14 |
| Endpoint 3 | 15 | 15–21 |
| Endpoint 4 | 22 | 22–28 |
| Endpoint 5 | 29 | 29–35 |

To change the patch, edit `DEVICE_PATCH` in `gateway/code.py`.

## Channel Layout (per device)

| Offset | Label | Range | Notes |
|---|---|---|---|
| +0 | Preset | 0–255 | Divided into 5-DMX bands, see table |
| +1 | Intensity | 0–255 | Master brightness |
| +2 | Red | 0–255 | |
| +3 | Green | 0–255 | |
| +4 | Blue | 0–255 | |
| +5 | Speed | 0–255 | 0=slowest, 255=fastest |
| +6 | Reserved | — | Future use |

## Preset Bands

Set the Preset channel to any value in the 5-DMX range to select that effect.

| Range | Effect | Good for |
|---|---|---|
| 0–4 | Blackout | Cue out |
| 5–9 | Sparkle | Stars, magic |
| 10–14 | Chase | Energy, movement |
| 15–19 | Fade / Breathe | Tension, meditation |
| 20–24 | Solid | Practical lamp, area fill |
| 25–29 | Twinkle on Solid | Ambient shimmer |
| 30–34 | Strobe | Seizure warning — use carefully |
| 35–39 | Meteor | Shooting star, energy bolt |
| 40–44 | Fire | Torch, candelabra, fireplace |
| 45–49 | Rainbow | Party, pride, carnival |
| 50–54 | Lightning | Storm, tension, danger |
| 55–59 | Marquee | Old Hollywood, opening number |
| 60–64 | Candle | Intimate, romantic, period |
| 65–69 | Color Wipe | Slow reveal, transformation |
| 70–74 | Heartbeat | Tension, life/death moments |
| 75–79 | Alarm | Emergency, siren |
| 80–84 | Comet | One-shot streak |
| 85–89 | Ripple | Water, pond, calm |
| 90–94 | Scanner (Cylon) | Robotic, surveillance |
| 95–99 | Bubbles | Underwater, dreamy |
| 100–104 | Campfire | Warmer/softer fire |
| 105–109 | Confetti | Celebration, chaos |
| 110–114 | Wave | Ocean, undulation |
| 115–119 | Flicker | Dying bulb, fluorescent |
| 120–124 | Theater Chase | Classic marquee |
| 125–129 | Rainbow Chase | Rainbow marquee |
| 130–134 | Aurora | Northern lights, slow drift |
| 135–139 | Wave Pastel | Soft rainbow sine pulse |

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
