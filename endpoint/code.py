# =============================================================================
# THEATER LORA ENDPOINT - code.py
# =============================================================================
# Runs on: Adafruit ESP32-S3 Feather (#5477)             <- 4MB flash, 2MB PSRAM, USB-C
#          + Adafruit RFM95W Breakout 915MHz (#3072)      <- LoRa radio, wired via primary SPI
#          + Adafruit bq25185 Charger/Booster (#6106)     <- LiPo charge + regulated 5V boost
# Battery powered, drives NeoPixel strip, receives LoRa preset commands
#
# HARDWARE CONNECTIONS:
#
#   RFM95W Breakout (#3072) — Primary SPI bus:
#     VIN  -> 3.3V  (Feather 3V3 pin)
#     GND  -> GND
#     SCK  -> SCK   (board.SCK  — primary SPI clock)
#     MOSI -> MOSI  (board.MOSI — primary SPI TX)
#     MISO -> MISO  (board.MISO — primary SPI RX)
#     CS   -> D9    (board.D9)
#     RST  -> D10   (board.D10)
#     G0   -> D11   (board.D11  — DIO0/IRQ)
#     Antenna: spring antenna (#4269) to uFL connector
#
#   bq25185 Charger/Booster (#6106) — power only, no data connection to Feather:
#     BATT port (JST-PH) -> LiPo battery
#     USB-C              -> charge input (charge from backstage, bq25185 port only)
#     5V output +        -> NeoPixel 5V rail
#     5V output −        -> GND (common with Feather GND)
#     (Feather is powered separately via its own JST port from the same LiPo)
#
#   NeoPixels:
#     DATA -> D5    (board.D5 — change NEOPIXEL_PIN below if needed)
#     5V   -> 5V output of bq25185
#     GND  -> GND (common ground)
#
#   POWER NOTE: Both the Feather JST and the bq25185 BATT input connect to the
#   same LiPo cell. Charge via bq25185 USB-C only during use. Use Feather USB-C
#   for programming only. Do not connect both USB-C ports simultaneously.
#
# SETUP:
#   1. Install CircuitPython 10.1.1 for "Adafruit Feather ESP32-S3 4MB Flash 2MB PSRAM"
#      from https://circuitpython.org/board/adafruit_feather_esp32s3/
#   2. Install these libraries into /lib on the board:
#        adafruit_rfm9x.mpy
#        adafruit_pixelbuf.mpy
#        neopixel.mpy
#   3. Set DEVICE_ID below (1 or 2, unique per endpoint)
#   4. Set NUM_PIXELS to match your strip
#   5. Copy this file to the board as code.py
# =============================================================================

import time

# Power-on stabilisation delay — gives the 3.3V LDO and bq25185 boost
# time to reach steady state before heavy hardware init (LoRa SPI + WiFi).
# Soft restart (Ctrl-D) skips the inrush so this only matters on cold boot.
time.sleep(0.5)

import random
import os
import board
import busio
import digitalio
import neopixel
import wifi
import socketpool
import adafruit_rfm9x
import adafruit_max1704x
import adafruit_lc709203f

# =============================================================================
# CONFIGURATION — per-device settings loaded from CIRCUITPY/settings.toml
# =============================================================================
# All per-device values live in settings.toml so the same code.py runs on every
# endpoint. See the settings.toml template in the repo for the full key list.

# DEVICE_ID: unique per board (1-5). Required — prints a clear error if missing.
_dev_id = os.getenv("DEVICE_ID")
if _dev_id is None:
    print("ERROR: DEVICE_ID not set in settings.toml — defaulting to 1. "
          "Set DEVICE_ID = 1 (or 2-5) in CIRCUITPY/settings.toml.")
DEVICE_ID = int(_dev_id) if _dev_id is not None else 1

# Stagger startup by device ID so endpoints don't all hit WiFi init simultaneously.
# Device 1=0.5s, 2=1.0s, 3=1.5s, 4=2.0s, 5=2.5s  (on top of the 0.5s above)
time.sleep(DEVICE_ID * 0.5)

# NUM_PIXELS: number of NeoPixels on this device's strip.
NUM_PIXELS = int(os.getenv("NUM_PIXELS", "40"))

# NEOPIXEL_PIN: board pin name as a string, e.g. "D5".
NEOPIXEL_PIN = getattr(board, os.getenv("NEOPIXEL_PIN", "D5"))

# --- WiFi Simulation Mode ---
# Listens for 9-byte UDP packets from the gateway over WiFi instead of (or alongside) LoRa.
# WIFI_SIM_ENABLED: set to "0" in settings.toml to disable.
# WIFI_SIM_NETWORK: "ap" = join gateway AP (default), "sta" = join existing network.
WIFI_SIM_ENABLED = os.getenv("WIFI_SIM_ENABLED", "1") != "0"
WIFI_SIM_NETWORK = os.getenv("WIFI_SIM_NETWORK", "ap")
WIFI_SIM_PORT    = 5569   # Must match WIFI_SIM_PORT in gateway/code.py

LORA_FREQ = 915.0       # MHz - must match gateway

# LoRa radio settings - tuned for low latency at short-to-medium range
# All endpoints and gateway must use identical settings
LORA_SF = 7             # Spreading factor 7 = fastest
LORA_BW = 250000        # 250kHz bandwidth = faster than default 125kHz
LORA_CR = 5             # Coding rate 4/5 = minimal overhead
LORA_TX_POWER = 13      # dBm - more than enough for 300ft indoors

# Duplicate suppression window - ignore repeated packets with same command ID
# within this many seconds (gateway re-sends 3x, we only want to act once)
DEDUP_WINDOW = 1.0      # seconds

# =============================================================================
# PACKET PROTOCOL (must match gateway)
# =============================================================================
# Byte 0:  Device ID (0=broadcast to all, 1-5=specific device)
# Byte 1:  Command ID (increments each new command, wraps 0-255)
# Byte 2:  Preset number
# Byte 3:  Intensity (0-255)
# Byte 4:  Red
# Byte 5:  Green
# Byte 6:  Blue
# Byte 7:  Speed (0=slow, 255=fast)
# Byte 8:  Config flags (bit 0 = CONFIG_ACK_REQUESTED)
# Byte 9:  Reserved (0x00)
# Byte 10: Reserved (0x00)
# Byte 11: Checksum (XOR of bytes 0-10)

PACKET_SIZE          = 12
ACK_PACKET_SIZE      = 7
ACK_MARKER           = 0xAC
CONFIG_ACK_REQUESTED = 0x01
ACK_PORT             = 5570
BASE_ACK_DELAY       = 0.15
ACK_STAGGER          = 0.08

PING_MARKER      = 0xBB
PING_PACKET_SIZE = 4

PRESET_BLACKOUT          = 0
PRESET_SPARKLE           = 1
PRESET_CHASE             = 2
PRESET_FADE              = 3
PRESET_SOLID             = 4
PRESET_TWINKLE_ON_SOLID  = 5
PRESET_STROBE            = 6
PRESET_METEOR            = 7
PRESET_FIRE              = 8
PRESET_RAINBOW           = 9
PRESET_LIGHTNING         = 10
PRESET_MARQUEE           = 11
PRESET_CANDLE            = 12
PRESET_COLOR_WIPE        = 13
PRESET_HEARTBEAT         = 14
PRESET_ALARM             = 15
PRESET_COMET             = 16   # single comet, one-shot then dark, re-triggers on next cue
PRESET_RIPPLE            = 17   # concentric pulses expand outward from center
PRESET_SCANNER           = 18   # Cylon/Knight Rider eye bounce
PRESET_BUBBLES           = 19   # random pixels bloom up and pop
PRESET_CAMPFIRE          = 20   # fire but cooler, more orange/amber
PRESET_CONFETTI          = 21   # random pixels random colors, party mode
PRESET_WAVE              = 22   # sine wave of brightness rolls down the strip
PRESET_FLICKER           = 23   # random intensity drops, like a bad fluorescent
PRESET_THEATER_CHASE     = 24   # classic every-third-pixel marquee chase
PRESET_RAINBOW_CHASE     = 25   # rainbow marquee
PRESET_AURORA            = 26   # northern lights, slow drifting colors
PRESET_WAVE_PASTEL       = 27   # sine wave from soft white to color, never goes dark

# =============================================================================
# HARDWARE INIT
# =============================================================================

# NeoPixels — using ESP32-S3 RMT peripheral for glitch-free output
pixels = neopixel.NeoPixel(
    NEOPIXEL_PIN,
    NUM_PIXELS,
    brightness=1.0,      # We handle brightness in software via intensity
    auto_write=False,    # Manual .show() for smooth animation control
    pixel_order=neopixel.GRB
)

# Battery monitor — try MAX17048 first, fall back to LC709203F
_bat_monitor = None
try:
    _bat_i2c = board.I2C()
    try:
        _bat_monitor = adafruit_max1704x.MAX17048(_bat_i2c)
        print(f"Battery monitor ready (MAX17048 | {_bat_monitor.cell_voltage:.2f}V "
              f"{_bat_monitor.cell_percent:.0f}%)")
    except ValueError:
        try:
            _bat_monitor = adafruit_lc709203f.LC709203F(_bat_i2c)
            _bat_monitor.thermistor_bconstant = 3950
            _bat_monitor.pack_size = adafruit_lc709203f.PackSize.MAH500
            print(f"Battery monitor ready (LC709203F | {_bat_monitor.cell_voltage:.2f}V "
                  f"{_bat_monitor.cell_percent:.0f}%)")
        except ValueError:
            print("No battery monitor chip found (tried MAX17048 and LC709203F)")
except Exception as e:
    _bat_monitor = None
    if "in use" in str(e).lower():
        print(f"Battery monitor unavailable: I2C bus already claimed ({e})")
        print("  Check CIRCUITPY/boot.py — something may have called busio.I2C() there.")
    else:
        print(f"Battery monitor unavailable: {e}")

def read_battery_pct():
    """Return battery percentage 0-100, or 255 if not available."""
    if _bat_monitor is None:
        return 255
    try:
        return max(0, min(100, int(_bat_monitor.cell_percent)))
    except Exception:
        return 255

# LoRa Radio — RFM95W Breakout (#3072) on primary SPI bus
# board.SCK=SCK, board.MOSI=MOSI, board.MISO=MISO, CS=D9, RST=D10, G0/IRQ=D11
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)
cs  = digitalio.DigitalInOut(board.D9)
rst = digitalio.DigitalInOut(board.D10)

print(f"Phosphene Endpoint {DEVICE_ID} booting...")
print(f"Board: ESP32-S3 Feather (#5477) | {NUM_PIXELS} pixels")
print("Initialising RFM95W LoRa radio...")

try:
    rfm9x = adafruit_rfm9x.RFM9x(spi, cs, rst, LORA_FREQ)
    rfm9x.spreading_factor  = LORA_SF
    rfm9x.signal_bandwidth  = LORA_BW
    rfm9x.coding_rate       = LORA_CR
    rfm9x.tx_power          = LORA_TX_POWER
    rfm9x.enable_crc        = True
    rfm9x.node              = DEVICE_ID
    rfm9x.destination       = 0xFF  # Accept any sender
    print(f"LoRa ready | SF{LORA_SF} BW{LORA_BW//1000}kHz @ {LORA_FREQ}MHz")
except Exception as e:
    rfm9x = None
    print(f"WARNING: LoRa not available: {e}")
    print("LoRa receive disabled — WiFi sim still active if configured")

# WiFi sim mode — connect to a network and listen for UDP packets from gateway
_ack_gateway_ip = None
sim_udp = None
if WIFI_SIM_ENABLED:
    if WIFI_SIM_NETWORK == "ap":
        _sim_ssid = os.getenv("WIFI_AP_SSID", "phosphene")
        _sim_pass = os.getenv("WIFI_AP_PASSWORD", "gobo1234")
        _sim_label = f"gateway AP '{_sim_ssid}'"
    else:  # "sta"
        _sim_ssid = os.getenv("WIFI_SSID")
        _sim_pass = os.getenv("WIFI_PASSWORD", "")
        _sim_label = f"network '{_sim_ssid}'"
    if _sim_ssid:
        try:
            print(f"Connecting to {_sim_label}...")
            wifi.radio.connect(_sim_ssid, _sim_pass)
            print(f"WiFi connected | IP {wifi.radio.ipv4_address}")
            _gw = wifi.radio.ipv4_gateway
            _ack_gateway_ip = str(_gw) if _gw else None
            _pool = socketpool.SocketPool(wifi.radio)
            sim_udp = _pool.socket(_pool.AF_INET, _pool.SOCK_DGRAM)
            sim_udp.bind(("0.0.0.0", WIFI_SIM_PORT))
            sim_udp.settimeout(0)
            print(f"WiFi sim mode: listening on UDP :{WIFI_SIM_PORT}")
        except Exception as e:
            sim_udp = None
            print(f"WiFi sim mode unavailable: {e}")
    else:
        print("WiFi sim mode disabled (WIFI_SSID not set in settings.toml)")
else:
    print("WiFi sim mode disabled (WIFI_SIM_ENABLED = False)")

# =============================================================================
# STATE
# =============================================================================

# Current effect parameters (set by received LoRa packet)
current_preset    = PRESET_BLACKOUT
current_intensity = 128
current_r         = 255
current_g         = 255
current_b         = 255
current_speed     = 128

# Duplicate suppression
last_command_id   = -1
last_command_time = 0.0

# Animation state (used differently per effect)
anim_phase        = 0.0   # General float counter, used for fades/chases
anim_tick         = 0     # Integer tick counter
chase_position    = 0     # Current chase head position
fade_direction    = 1     # 1 = fading in, -1 = fading out
fade_level        = 0.0   # 0.0 - 1.0

# Per-pixel twinkle state: each pixel has an independent brightness target
twinkle_levels    = [0.0] * NUM_PIXELS
twinkle_speeds    = [random.uniform(0.01, 0.05) for _ in range(NUM_PIXELS)]
twinkle_targets   = [random.uniform(0.0, 1.0) for _ in range(NUM_PIXELS)]

# Strobe state
strobe_on         = False
strobe_tick       = 0

# Meteor / comet state
meteor_pos        = 0.0
meteor_tick       = 0

# Fire / campfire state - per-pixel heat values
fire_heat         = [0] * NUM_PIXELS

# Rainbow state
rainbow_offset    = 0.0

# Lightning state
lightning_on      = False
lightning_timer   = 0
lightning_next    = 0

# Marquee / theater chase offset
marquee_offset    = 0
marquee_tick      = 0

# Candle state - per-pixel flicker level
candle_levels     = [random.uniform(0.5, 1.0) for _ in range(NUM_PIXELS)]
candle_targets    = [random.uniform(0.5, 1.0) for _ in range(NUM_PIXELS)]
candle_speeds     = [random.uniform(0.05, 0.15) for _ in range(NUM_PIXELS)]

# Color wipe state
wipe_position     = 0
wipe_tick         = 0

# Heartbeat state
heartbeat_phase   = 0.0

# Alarm state
alarm_phase       = False
alarm_tick        = 0

# Ripple state
ripple_pos        = 0.0
ripple_tick       = 0

# Scanner (Cylon) state
scanner_pos       = 0
scanner_dir       = 1
scanner_tick      = 0

# Bubbles state - per-pixel bloom level and target
bubble_levels     = [0.0] * NUM_PIXELS
bubble_targets    = [0.0] * NUM_PIXELS
bubble_speeds     = [0.0] * NUM_PIXELS

# Confetti state
confetti_tick     = 0

# Wave state
wave_offset       = 0.0

# Flicker state - per-pixel flicker value
flicker_levels    = [1.0] * NUM_PIXELS

# Aurora state - per-pixel hue
aurora_hues       = [random.random() for _ in range(NUM_PIXELS)]

# ACK state
ack_pending       = None   # (send_at, ack_bytes) or None
last_ping_seq     = -1
last_ping_time    = 0.0

# =============================================================================
# HELPERS
# =============================================================================

def scale_color(r, g, b, intensity):
    """Scale an RGB color by an intensity value (0-255)."""
    scale = intensity / 255.0
    return (int(r * scale), int(g * scale), int(b * scale))


def verify_checksum(packet):
    """Return True if packet checksum byte is valid."""
    if len(packet) < PACKET_SIZE:
        return False
    checksum = 0
    for b in packet[:11]:
        checksum ^= b
    return checksum == packet[11]


def speed_to_rate(speed_byte, slow_val, fast_val):
    """
    Map speed byte (0-255) to a rate value between slow_val and fast_val.
    Linear interpolation. Can be used for seconds-per-cycle or pixels-per-tick.
    """
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)


def set_all(r, g, b):
    """Set all pixels to one color."""
    pixels.fill((r, g, b))


def apply_blackout():
    """Immediately cut all pixels."""
    pixels.fill((0, 0, 0))
    pixels.show()


# =============================================================================
# EFFECT FUNCTIONS
# Called every loop iteration. Use anim_* globals to track state across frames.
# =============================================================================

def effect_blackout():
    apply_blackout()


def effect_solid():
    """Steady color at current intensity."""
    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    set_all(r, g, b)
    pixels.show()


def effect_sparkle():
    """
    Random pixels flash bright, rest stay dark.
    Speed controls how many pixels sparkle per frame.
    Color tints the sparkles.
    """
    global anim_tick

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)

    # Number of sparkles per frame: speed maps 1 to ~20% of strip
    num_sparkles = max(1, int(speed_to_rate(current_speed, 1, NUM_PIXELS * 0.2)))

    # Fade all pixels toward black each frame (persistence of vision effect)
    fade_factor = speed_to_rate(current_speed, 0.85, 0.5)
    for i in range(NUM_PIXELS):
        pr, pg, pb = pixels[i]
        pixels[i] = (int(pr * fade_factor), int(pg * fade_factor), int(pb * fade_factor))

    # Light up random pixels
    for _ in range(num_sparkles):
        idx = random.randint(0, NUM_PIXELS - 1)
        pixels[idx] = (r, g, b)

    pixels.show()
    anim_tick += 1


def effect_chase():
    """
    A moving block of lit pixels travels along the strip.
    Speed controls travel rate, color is the chase color.
    """
    global chase_position, anim_tick

    CHASE_LENGTH = max(3, NUM_PIXELS // 8)  # Block is 1/8 of strip

    # How many ticks to wait before advancing one pixel
    # Speed 0 = slow (many ticks), speed 255 = fast (1 tick)
    ticks_per_step = max(1, int(speed_to_rate(current_speed, 20, 1)))

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    dim_r, dim_g, dim_b = r // 8, g // 8, b // 8  # Dim trail

    # Draw strip: head block bright, brief trail behind, rest dark
    pixels.fill((0, 0, 0))
    for i in range(NUM_PIXELS):
        dist = (i - chase_position) % NUM_PIXELS
        if dist < CHASE_LENGTH:
            # Brightness tapers from head to tail
            taper = 1.0 - (dist / CHASE_LENGTH) * 0.7
            pixels[i] = (int(r * taper), int(g * taper), int(b * taper))
        elif dist == CHASE_LENGTH:
            pixels[i] = (dim_r, dim_g, dim_b)

    pixels.show()

    anim_tick += 1
    if anim_tick >= ticks_per_step:
        chase_position = (chase_position + 1) % NUM_PIXELS
        anim_tick = 0


def effect_fade():
    """
    Whole strip breathes in and out between full color and black.
    Speed controls breath cycle time.
    """
    global fade_direction, fade_level

    # Speed maps: 0=very slow (0.003/frame), 255=fast (0.05/frame)
    step = speed_to_rate(current_speed, 0.003, 0.05)

    fade_level += step * fade_direction
    if fade_level >= 1.0:
        fade_level = 1.0
        fade_direction = -1
    elif fade_level <= 0.0:
        fade_level = 0.0
        fade_direction = 1

    effective_intensity = int(current_intensity * fade_level)
    r, g, b = scale_color(current_r, current_g, current_b, effective_intensity)
    set_all(r, g, b)
    pixels.show()


def effect_twinkle_on_solid():
    """
    Each pixel has its own independent brightness that slowly wanders.
    Creates an organic, gentle twinkle over the base color.
    Speed controls how quickly individual pixels change.
    """
    global twinkle_levels, twinkle_speeds, twinkle_targets

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)

    # Speed maps to how fast pixels transition
    speed_factor = speed_to_rate(current_speed, 0.3, 3.0)

    for i in range(NUM_PIXELS):
        # Move toward target
        diff = twinkle_targets[i] - twinkle_levels[i]
        twinkle_levels[i] += diff * twinkle_speeds[i] * speed_factor

        # When close to target, pick a new one
        if abs(diff) < 0.02:
            # Min brightness 0.2 so no pixel fully goes dark (more elegant look)
            twinkle_targets[i] = random.uniform(0.2, 1.0)
            twinkle_speeds[i]  = random.uniform(0.01, 0.06)

        lvl = twinkle_levels[i]
        pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

    pixels.show()


# =============================================================================
# MATH HELPERS
# =============================================================================

import math

def hsv_to_rgb(h, s, v):
    """Convert HSV (0.0-1.0 each) to (r, g, b) 0-255."""
    if s == 0.0:
        c = int(v * 255)
        return (c, c, c)
    i = int(h * 6.0)
    f = (h * 6.0) - i
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    i %= 6
    if i == 0: r, g, b = v, t, p
    elif i == 1: r, g, b = q, v, p
    elif i == 2: r, g, b = p, v, t
    elif i == 3: r, g, b = p, q, v
    elif i == 4: r, g, b = t, p, v
    else:        r, g, b = v, p, q
    return (int(r * 255), int(g * 255), int(b * 255))


# =============================================================================
# NEW EFFECT FUNCTIONS
# =============================================================================

def effect_strobe():
    """
    Hard on/off flash. Speed controls flash rate.
    Intensity controls peak brightness of the ON state.
    Color sets the strobe color (white is classic).
    """
    global strobe_on, strobe_tick

    # Speed 0 = very slow strobe (~2Hz), speed 255 = fast (~30Hz)
    ticks_per_half = max(1, int(speed_to_rate(current_speed, 50, 2)))

    strobe_tick += 1
    if strobe_tick >= ticks_per_half:
        strobe_on = not strobe_on
        strobe_tick = 0

    if strobe_on:
        r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
        pixels.fill((r, g, b))
    else:
        pixels.fill((0, 0, 0))
    pixels.show()


def effect_meteor():
    """
    A bright meteor with a tapering tail shoots across the strip and loops.
    Speed controls travel speed. Color is the meteor color.
    Intensity controls peak brightness.
    """
    global meteor_pos, meteor_tick

    TAIL_LENGTH = max(4, NUM_PIXELS // 6)
    ticks_per_step = max(1, int(speed_to_rate(current_speed, 8, 1)))

    meteor_tick += 1
    if meteor_tick >= ticks_per_step:
        meteor_pos = (meteor_pos + 1) % NUM_PIXELS
        meteor_tick = 0

    pixels.fill((0, 0, 0))
    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)

    for i in range(TAIL_LENGTH):
        idx = int(meteor_pos - i) % NUM_PIXELS
        # Tail fades exponentially
        brightness = (1.0 - (i / TAIL_LENGTH)) ** 2
        pixels[idx] = (int(r * brightness), int(g * brightness), int(b * brightness))

    pixels.show()


def effect_fire():
    """
    Fire simulation using per-pixel heat values.
    Color channel biases the flame hue (default warm = R:255 G:80 B:0).
    Speed controls flame intensity/height. Intensity caps overall brightness.
    """
    global fire_heat

    COOLING  = int(speed_to_rate(current_speed, 80, 30))   # High = cooler flame
    SPARKING = int(speed_to_rate(current_speed, 40, 120))   # High = more sparks

    # Cool each cell
    for i in range(NUM_PIXELS):
        cooldown = random.randint(0, ((COOLING * 10) // NUM_PIXELS) + 2)
        fire_heat[i] = max(0, fire_heat[i] - cooldown)

    # Heat drifts upward
    for i in range(NUM_PIXELS - 1, 1, -1):
        fire_heat[i] = (fire_heat[i - 1] + fire_heat[i - 2] + fire_heat[i - 2]) // 3

    # Sparks at base
    if random.randint(0, 255) < SPARKING:
        y = random.randint(0, min(7, NUM_PIXELS - 1))
        fire_heat[y] = min(255, fire_heat[y] + random.randint(160, 255))

    # Map heat to color, blended with user color
    scale = current_intensity / 255.0
    for i in range(NUM_PIXELS):
        h = fire_heat[i]
        if h < 85:
            pixel_r = h * 3
            pixel_g = 0
            pixel_b = 0
        elif h < 170:
            pixel_r = 255
            pixel_g = (h - 85) * 3
            pixel_b = 0
        else:
            pixel_r = 255
            pixel_g = 255
            pixel_b = (h - 170) * 3

        # Blend toward user color
        blend = current_r / 255.0
        pixel_r = int((pixel_r * blend + pixel_r * (1 - blend)) * scale)
        pixel_g = int(pixel_g * (current_g / 255.0) * scale)
        pixel_b = int(pixel_b * (current_b / 255.0) * scale)
        pixels[i] = (pixel_r, pixel_g, pixel_b)

    pixels.show()


def effect_campfire():
    """
    Softer fire, cooler and more amber. Same engine as fire but different tuning.
    Great for lanterns and warm prop lighting.
    """
    global fire_heat

    COOLING  = int(speed_to_rate(current_speed, 100, 50))
    SPARKING = int(speed_to_rate(current_speed, 25, 80))

    for i in range(NUM_PIXELS):
        cooldown = random.randint(0, ((COOLING * 10) // NUM_PIXELS) + 2)
        fire_heat[i] = max(0, fire_heat[i] - cooldown)

    for i in range(NUM_PIXELS - 1, 1, -1):
        fire_heat[i] = (fire_heat[i - 1] + fire_heat[i - 2] + fire_heat[i - 2]) // 3

    if random.randint(0, 255) < SPARKING:
        y = random.randint(0, min(5, NUM_PIXELS - 1))
        fire_heat[y] = min(200, fire_heat[y] + random.randint(100, 200))

    scale = current_intensity / 255.0
    for i in range(NUM_PIXELS):
        h = fire_heat[i]
        # Amber palette: red -> orange -> yellow, no blue
        if h < 85:
            pixel_r = h * 3
            pixel_g = h
            pixel_b = 0
        elif h < 170:
            pixel_r = 255
            pixel_g = 85 + (h - 85) * 2
            pixel_b = 0
        else:
            pixel_r = 255
            pixel_g = 200
            pixel_b = (h - 170)
        pixels[i] = (int(pixel_r * scale), int(pixel_g * scale * 0.6), int(pixel_b * scale * 0.2))

    pixels.show()


def effect_rainbow():
    """
    Full rainbow cycles across the strip.
    Speed controls rotation rate. Intensity controls brightness.
    Color channels are ignored (it's a rainbow!).
    """
    global rainbow_offset

    step = speed_to_rate(current_speed, 0.001, 0.02)
    rainbow_offset = (rainbow_offset + step) % 1.0

    scale = current_intensity / 255.0
    for i in range(NUM_PIXELS):
        hue = (rainbow_offset + i / NUM_PIXELS) % 1.0
        r, g, b = hsv_to_rgb(hue, 1.0, scale)
        pixels[i] = (r, g, b)

    pixels.show()


def effect_rainbow_chase():
    """
    Every-third-pixel marquee using rainbow colors.
    Speed controls chase rate.
    """
    global marquee_offset, marquee_tick

    ticks_per_step = max(1, int(speed_to_rate(current_speed, 15, 1)))
    marquee_tick += 1
    if marquee_tick >= ticks_per_step:
        marquee_offset = (marquee_offset + 1) % 3
        marquee_tick = 0

    scale = current_intensity / 255.0
    for i in range(NUM_PIXELS):
        if (i + marquee_offset) % 3 == 0:
            hue = (i / NUM_PIXELS + rainbow_offset) % 1.0
            r, g, b = hsv_to_rgb(hue, 1.0, scale)
            pixels[i] = (r, g, b)
        else:
            pixels[i] = (0, 0, 0)

    pixels.show()


def effect_lightning():
    """
    Random white flashes of varying brightness and duration against a dark sky.
    Speed controls how frequently strikes happen.
    Intensity controls peak flash brightness.
    Color tints the lightning (pure white is R:255 G:255 B:255).
    """
    global lightning_on, lightning_timer, lightning_next

    lightning_timer += 1

    if not lightning_on:
        # Waiting for next strike
        if lightning_timer >= lightning_next:
            lightning_on = True
            # Flash duration: 1-5 frames
            lightning_timer = 0
            lightning_next  = random.randint(1, random.randint(3, 8))
            # Randomize brightness for each strike
            flash_level = random.uniform(0.4, 1.0)
            r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
            r = int(r * flash_level)
            g = int(g * flash_level)
            b = int(b * flash_level)
            pixels.fill((r, g, b))
            pixels.show()
        # else: stay dark
    else:
        # Flash is on, check if it should end
        if lightning_timer >= lightning_next:
            lightning_on = False
            pixels.fill((0, 0, 0))
            pixels.show()
            lightning_timer = 0
            # Time until next strike: speed controls frequency
            min_wait = int(speed_to_rate(current_speed, 200, 10))
            max_wait = int(speed_to_rate(current_speed, 500, 40))
            # Occasional double-flash
            if random.randint(0, 3) == 0:
                lightning_next = random.randint(2, 6)  # Quick second strike
            else:
                lightning_next = random.randint(min_wait, max_wait)


def effect_marquee():
    """
    Classic theater marquee: every Nth pixel lit, block scrolls.
    Speed controls scroll rate. Color is the lit pixel color.
    Intensity controls brightness.
    """
    global marquee_offset, marquee_tick

    SPACING = 3  # Every 3rd pixel lit
    ticks_per_step = max(1, int(speed_to_rate(current_speed, 20, 1)))
    marquee_tick += 1
    if marquee_tick >= ticks_per_step:
        marquee_offset = (marquee_offset + 1) % SPACING
        marquee_tick = 0

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    dim_r, dim_g, dim_b = r // 12, g // 12, b // 12

    for i in range(NUM_PIXELS):
        if (i + marquee_offset) % SPACING == 0:
            pixels[i] = (r, g, b)
        else:
            pixels[i] = (dim_r, dim_g, dim_b)

    pixels.show()


def effect_candle():
    """
    Gentle per-pixel flicker like candlelight. Warmer and subtler than fire.
    Speed controls flicker rate. Intensity controls overall brightness.
    Color sets the candle hue (warm yellow-orange default: R:255 G:147 B:41).
    """
    global candle_levels, candle_targets, candle_speeds

    speed_factor = speed_to_rate(current_speed, 0.5, 4.0)
    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)

    for i in range(NUM_PIXELS):
        diff = candle_targets[i] - candle_levels[i]
        candle_levels[i] += diff * candle_speeds[i] * speed_factor

        if abs(diff) < 0.03:
            candle_targets[i] = random.uniform(0.6, 1.0)
            candle_speeds[i]  = random.uniform(0.04, 0.12)
            # Occasional dramatic dip
            if random.randint(0, 30) == 0:
                candle_targets[i] = random.uniform(0.25, 0.5)

        lvl = candle_levels[i]
        pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

    pixels.show()


def effect_color_wipe():
    """
    Pixels fill in one by one from one end, then clear from one end.
    Great for slow reveals. Speed controls wipe rate.
    Intensity controls brightness. Color is the wipe color.
    """
    global wipe_position, wipe_tick, fade_direction

    ticks_per_step = max(1, int(speed_to_rate(current_speed, 30, 1)))
    wipe_tick += 1
    if wipe_tick >= ticks_per_step:
        wipe_tick = 0
        wipe_position += 1
        if wipe_position > NUM_PIXELS * 2:
            wipe_position = 0

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)

    if wipe_position <= NUM_PIXELS:
        # Filling in
        for i in range(NUM_PIXELS):
            pixels[i] = (r, g, b) if i < wipe_position else (0, 0, 0)
    else:
        # Wiping out
        clear_pos = wipe_position - NUM_PIXELS
        for i in range(NUM_PIXELS):
            pixels[i] = (0, 0, 0) if i < clear_pos else (r, g, b)

    pixels.show()


def effect_heartbeat():
    """
    Double-pulse (lub-dub) that repeats. Looks great in red for a literal heartbeat,
    but works in any color for a dramatic rhythmic pulse.
    Speed controls BPM. Intensity controls peak brightness.
    """
    global heartbeat_phase

    bpm_rate = speed_to_rate(current_speed, 0.008, 0.04)
    heartbeat_phase = (heartbeat_phase + bpm_rate) % 1.0

    # Lub-dub envelope: two quick peaks close together, then long rest
    p = heartbeat_phase
    if p < 0.08:
        lvl = math.sin(p / 0.08 * math.pi)           # Lub
    elif p < 0.18:
        lvl = math.sin((p - 0.1) / 0.08 * math.pi) * 0.7  # Dub (softer)
    else:
        lvl = 0.0                                      # Rest

    lvl = max(0.0, lvl)
    effective_intensity = int(current_intensity * lvl)
    r, g, b = scale_color(current_r, current_g, current_b, effective_intensity)
    pixels.fill((r, g, b))
    pixels.show()


def effect_alarm():
    """
    Fast two-color alternating flash. Great for warnings, emergencies, sirens.
    Color 1 = the RGB values set. Color 2 = complementary (auto-computed).
    Speed controls alternation rate. Intensity controls brightness.
    """
    global alarm_phase, alarm_tick

    ticks_per_half = max(1, int(speed_to_rate(current_speed, 30, 2)))
    alarm_tick += 1
    if alarm_tick >= ticks_per_half:
        alarm_phase = not alarm_phase
        alarm_tick = 0

    if alarm_phase:
        r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    else:
        # Complement: flip R<->B so red alarm alternates with blue
        r, g, b = scale_color(current_b, current_g, current_r, current_intensity)

    pixels.fill((r, g, b))
    pixels.show()


def effect_ripple():
    """
    A brightness pulse expands outward from the center of the strip.
    Speed controls pulse speed. Intensity controls peak brightness.
    Color is the ripple color.
    """
    global ripple_pos, ripple_tick

    RIPPLE_WIDTH = max(3, NUM_PIXELS // 8)
    ticks_per_step = max(1, int(speed_to_rate(current_speed, 8, 1)))

    ripple_tick += 1
    if ripple_tick >= ticks_per_step:
        ripple_pos += 1
        ripple_tick = 0
        if ripple_pos > NUM_PIXELS // 2 + RIPPLE_WIDTH:
            ripple_pos = 0

    center = NUM_PIXELS // 2
    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    pixels.fill((0, 0, 0))

    for i in range(NUM_PIXELS):
        dist = abs(i - center)
        # Two ripples: one going each direction from center
        ripple_dist = abs(dist - ripple_pos)
        if ripple_dist < RIPPLE_WIDTH:
            brightness = 1.0 - (ripple_dist / RIPPLE_WIDTH)
            brightness = brightness ** 2
            pixels[i] = (int(r * brightness), int(g * brightness), int(b * brightness))

    pixels.show()


def effect_scanner():
    """
    Cylon/Knight Rider eye: a bright segment bounces back and forth.
    Speed controls travel speed. Intensity controls brightness.
    Color is the eye color.
    """
    global scanner_pos, scanner_dir, scanner_tick

    EYE_WIDTH = max(3, NUM_PIXELS // 10)
    ticks_per_step = max(1, int(speed_to_rate(current_speed, 10, 1)))

    scanner_tick += 1
    if scanner_tick >= ticks_per_step:
        scanner_pos += scanner_dir
        scanner_tick = 0
        if scanner_pos >= NUM_PIXELS - EYE_WIDTH:
            scanner_dir = -1
        elif scanner_pos <= 0:
            scanner_dir = 1

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    pixels.fill((0, 0, 0))

    for i in range(EYE_WIDTH):
        idx = scanner_pos + i
        if 0 <= idx < NUM_PIXELS:
            # Bright center, taper to edges
            dist_from_center = abs(i - EYE_WIDTH // 2)
            brightness = 1.0 - (dist_from_center / (EYE_WIDTH / 2)) * 0.7
            # Very dim trail on both sides
            pixels[idx] = (int(r * brightness), int(g * brightness), int(b * brightness))

    # Ghost trail
    trail_len = EYE_WIDTH * 2
    for i in range(1, trail_len):
        ghost_idx = scanner_pos - (i * scanner_dir)
        if 0 <= ghost_idx < NUM_PIXELS:
            fade = max(0.0, 1.0 - i / trail_len) * 0.15
            pixels[ghost_idx] = (int(r * fade), int(g * fade), int(b * fade))

    pixels.show()


def effect_bubbles():
    """
    Random pixels bloom up from darkness and pop, like bubbles rising.
    Speed controls how quickly new bubbles appear and rise.
    Intensity controls brightness. Color is the bubble color.
    """
    global bubble_levels, bubble_targets, bubble_speeds

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    speed_factor = speed_to_rate(current_speed, 0.3, 3.0)
    spawn_chance = speed_to_rate(current_speed, 0.01, 0.15)

    for i in range(NUM_PIXELS):
        diff = bubble_targets[i] - bubble_levels[i]
        if bubble_speeds[i] > 0:
            bubble_levels[i] += diff * bubble_speeds[i] * speed_factor

        # When a bubble reaches its peak, it pops (goes dark)
        if bubble_targets[i] > 0.5 and abs(diff) < 0.05:
            bubble_targets[i] = 0.0
            bubble_speeds[i]  = random.uniform(0.08, 0.25)  # Pop fast

        # Spawn new bubble
        if bubble_levels[i] < 0.02 and bubble_targets[i] < 0.1:
            if random.random() < spawn_chance:
                bubble_targets[i] = random.uniform(0.6, 1.0)
                bubble_speeds[i]  = random.uniform(0.02, 0.08)

        lvl = max(0.0, bubble_levels[i])
        pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

    pixels.show()


def effect_confetti():
    """
    Random pixels light up in random colors, constantly refreshing.
    Speed controls how fast new confetti appears.
    Intensity controls brightness.
    """
    global confetti_tick

    spawn_rate = max(1, int(speed_to_rate(current_speed, 1, 8)))

    # Fade all pixels slightly each frame
    for i in range(NUM_PIXELS):
        pr, pg, pb = pixels[i]
        pixels[i] = (int(pr * 0.92), int(pg * 0.92), int(pb * 0.92))

    # Spawn new confetti pixels
    for _ in range(spawn_rate):
        idx = random.randint(0, NUM_PIXELS - 1)
        hue = random.random()
        r, g, b = hsv_to_rgb(hue, 1.0, current_intensity / 255.0)
        pixels[idx] = (r, g, b)

    pixels.show()
    confetti_tick += 1


def effect_wave():
    """
    A smooth sine wave of brightness rolls down the strip.
    Speed controls wave travel speed. Intensity controls peak brightness.
    Color is the wave color.
    """
    global wave_offset

    step = speed_to_rate(current_speed, 0.02, 0.3)
    wave_offset = (wave_offset + step) % (2 * math.pi)

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)

    for i in range(NUM_PIXELS):
        phase = wave_offset + (i / NUM_PIXELS) * 2 * math.pi
        lvl = (math.sin(phase) + 1.0) / 2.0   # 0.0 to 1.0
        pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

    pixels.show()


def effect_wave_pastel():
    """
    Rainbow hues distributed across the strip, pulsing with a traveling sine wave.
    Saturation rises at the wave crest and drops to near-white at the trough, keeping
    all colors soft and pastel. Speed controls pulse travel. Intensity controls brightness.
    Color channel is ignored — hues cycle through the full spectrum automatically.
    """
    global wave_offset, rainbow_offset

    step = speed_to_rate(current_speed, 0.02, 0.3)
    wave_offset = (wave_offset + step) % (2 * math.pi)
    # Rainbow drifts at 1/20th the wave step so hues shift gently while the wave pulses
    rainbow_offset = (rainbow_offset + step * 0.05) % 1.0

    scale = current_intensity / 255.0

    for i in range(NUM_PIXELS):
        hue = (rainbow_offset + i / NUM_PIXELS) % 1.0
        phase = wave_offset + (i / NUM_PIXELS) * 2 * math.pi
        lvl = (math.sin(phase) + 1.0) / 2.0  # 0.0 to 1.0
        # Saturation follows the wave: 0 at trough (white) → 0.6 at crest (soft pastel)
        sat = lvl * 0.6
        # Value: 0.35 at trough → 1.0 at crest, all scaled by intensity
        val = (0.35 + lvl * 0.65) * scale
        r, g, b = hsv_to_rgb(hue, sat, val)
        pixels[i] = (r, g, b)

    pixels.show()


def effect_flicker():
    """
    Like a bad fluorescent tube or dying torch. Random intensity drops per pixel.
    Speed controls flicker frequency. Intensity is the baseline brightness.
    Color is the flicker color.
    """
    global flicker_levels

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    flicker_chance = speed_to_rate(current_speed, 0.02, 0.25)

    for i in range(NUM_PIXELS):
        if random.random() < flicker_chance:
            flicker_levels[i] = random.uniform(0.0, 1.0)
        else:
            # Recover toward full brightness
            flicker_levels[i] = min(1.0, flicker_levels[i] + 0.1)

        lvl = flicker_levels[i]
        pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

    pixels.show()


def effect_theater_chase():
    """
    Classic theater chase: every 3rd pixel lit, offset advances each step.
    Like marquee but with a dim background fill.
    Speed controls chase rate. Intensity controls brightness.
    """
    global marquee_offset, marquee_tick

    SPACING = 3
    ticks_per_step = max(1, int(speed_to_rate(current_speed, 15, 1)))
    marquee_tick += 1
    if marquee_tick >= ticks_per_step:
        marquee_offset = (marquee_offset + 1) % SPACING
        marquee_tick = 0

    r, g, b = scale_color(current_r, current_g, current_b, current_intensity)
    bg_r, bg_g, bg_b = r // 6, g // 6, b // 6

    for i in range(NUM_PIXELS):
        if (i + marquee_offset) % SPACING == 0:
            pixels[i] = (r, g, b)
        else:
            pixels[i] = (bg_r, bg_g, bg_b)

    pixels.show()


def effect_aurora():
    """
    Northern lights: slow drifting hues create an organic, dreamy atmosphere.
    Speed controls drift rate. Intensity controls brightness.
    Color is ignored (it's an aurora!).
    """
    global aurora_hues

    drift = speed_to_rate(current_speed, 0.0005, 0.008)
    scale = current_intensity / 255.0

    for i in range(NUM_PIXELS):
        aurora_hues[i] = (aurora_hues[i] + drift + random.uniform(-0.003, 0.003)) % 1.0
        r, g, b = hsv_to_rgb(aurora_hues[i], 0.6, scale)
        pixels[i] = (r, g, b)

    pixels.show()


# Effect dispatch table
EFFECTS = {
    PRESET_BLACKOUT:         effect_blackout,
    PRESET_SPARKLE:          effect_sparkle,
    PRESET_CHASE:            effect_chase,
    PRESET_FADE:             effect_fade,
    PRESET_SOLID:            effect_solid,
    PRESET_TWINKLE_ON_SOLID: effect_twinkle_on_solid,
    PRESET_STROBE:           effect_strobe,
    PRESET_METEOR:           effect_meteor,
    PRESET_FIRE:             effect_fire,
    PRESET_RAINBOW:          effect_rainbow,
    PRESET_LIGHTNING:        effect_lightning,
    PRESET_MARQUEE:          effect_marquee,
    PRESET_CANDLE:           effect_candle,
    PRESET_COLOR_WIPE:       effect_color_wipe,
    PRESET_HEARTBEAT:        effect_heartbeat,
    PRESET_ALARM:            effect_alarm,
    PRESET_COMET:            effect_meteor,           # Alias: comet = meteor (one-shot feel)
    PRESET_RIPPLE:           effect_ripple,
    PRESET_SCANNER:          effect_scanner,
    PRESET_BUBBLES:          effect_bubbles,
    PRESET_CAMPFIRE:         effect_campfire,
    PRESET_CONFETTI:         effect_confetti,
    PRESET_WAVE:             effect_wave,
    PRESET_FLICKER:          effect_flicker,
    PRESET_THEATER_CHASE:    effect_theater_chase,
    PRESET_RAINBOW_CHASE:    effect_rainbow_chase,
    PRESET_AURORA:           effect_aurora,
    PRESET_WAVE_PASTEL:      effect_wave_pastel,
}

# =============================================================================
# PACKET HANDLING
# =============================================================================

def apply_packet(packet):
    """
    Parse a received LoRa packet and update effect state.
    Returns True if packet was valid and acted on.
    """
    global current_preset, current_intensity
    global current_r, current_g, current_b, current_speed
    global last_command_id, last_command_time
    global chase_position, fade_direction, fade_level, anim_tick
    global twinkle_levels, twinkle_speeds, twinkle_targets

    if len(packet) < PACKET_SIZE:
        print(f"  Packet too short ({len(packet)} bytes), ignoring")
        return False

    if not verify_checksum(packet):
        print("  Checksum failed, ignoring")
        return False

    device_id    = packet[0]
    command_id   = packet[1]
    preset       = packet[2]
    intensity    = packet[3]
    r            = packet[4]
    g            = packet[5]
    b            = packet[6]
    speed        = packet[7]
    config_flags = packet[8]

    # Check if this packet is for us (our ID or broadcast)
    if device_id != 0 and device_id != DEVICE_ID:
        print(f"  Packet for device {device_id}, we are {DEVICE_ID}, ignoring")
        return False

    # Duplicate suppression: ignore if same command_id within dedup window
    now = time.monotonic()
    if command_id == last_command_id and (now - last_command_time) < DEDUP_WINDOW:
        print(f"  Duplicate command {command_id}, ignoring")
        return False

    # Accept the command
    last_command_id   = command_id
    last_command_time = now

    print(f"  CMD {command_id} | Preset {preset} | RGBA({r},{g},{b}) Int={intensity} Spd={speed}")

    if config_flags & CONFIG_ACK_REQUESTED:
        _schedule_ack(command_id)

    # If preset is changing, reset animation state for a clean transition
    if preset != current_preset:
        chase_position  = 0
        fade_direction  = 1
        fade_level      = 0.0
        anim_tick       = 0
        # Randomize twinkle state for fresh start
        twinkle_levels  = [0.0] * NUM_PIXELS
        twinkle_speeds  = [random.uniform(0.01, 0.05) for _ in range(NUM_PIXELS)]
        twinkle_targets = [random.uniform(0.2, 1.0) for _ in range(NUM_PIXELS)]
        # New effect state resets
        global strobe_on, strobe_tick
        global meteor_pos, meteor_tick
        global fire_heat
        global rainbow_offset
        global lightning_on, lightning_timer, lightning_next
        global marquee_offset, marquee_tick
        global candle_levels, candle_targets, candle_speeds
        global wipe_position, wipe_tick
        global heartbeat_phase
        global alarm_phase, alarm_tick
        global ripple_pos, ripple_tick
        global scanner_pos, scanner_dir, scanner_tick
        global bubble_levels, bubble_targets, bubble_speeds
        global confetti_tick
        global wave_offset
        global flicker_levels
        global aurora_hues

        strobe_on      = False
        strobe_tick    = 0
        meteor_pos     = 0.0
        meteor_tick    = 0
        fire_heat      = [0] * NUM_PIXELS
        lightning_on   = False
        lightning_timer = 0
        lightning_next = random.randint(10, 60)
        marquee_offset = 0
        marquee_tick   = 0
        candle_levels  = [random.uniform(0.5, 1.0) for _ in range(NUM_PIXELS)]
        candle_targets = [random.uniform(0.5, 1.0) for _ in range(NUM_PIXELS)]
        candle_speeds  = [random.uniform(0.05, 0.15) for _ in range(NUM_PIXELS)]
        wipe_position  = 0
        wipe_tick      = 0
        heartbeat_phase = 0.0
        alarm_phase    = False
        alarm_tick     = 0
        ripple_pos     = 0.0
        ripple_tick    = 0
        scanner_pos    = 0
        scanner_dir    = 1
        scanner_tick   = 0
        bubble_levels  = [0.0] * NUM_PIXELS
        bubble_targets = [0.0] * NUM_PIXELS
        bubble_speeds  = [0.0] * NUM_PIXELS
        confetti_tick  = 0
        wave_offset    = 0.0
        flicker_levels = [1.0] * NUM_PIXELS
        aurora_hues    = [random.random() for _ in range(NUM_PIXELS)]

    current_preset    = preset
    current_intensity = intensity
    current_r         = r
    current_g         = g
    current_b         = b
    current_speed     = speed

    return True


def handle_ping(packet):
    """Process a received ping packet and schedule an ACK response."""
    global last_ping_seq, last_ping_time
    if len(packet) < PING_PACKET_SIZE or packet[0] != PING_MARKER:
        return False
    cs = packet[0] ^ packet[1] ^ packet[2]
    if cs != packet[3]:
        return False
    device_id = packet[1]
    if device_id != 0 and device_id != DEVICE_ID:
        return False
    ping_seq = packet[2]
    now = time.monotonic()
    if ping_seq == last_ping_seq and (now - last_ping_time) < 2.0:
        return True  # dedup — already responded to this ping
    last_ping_seq = ping_seq
    last_ping_time = now
    print(f"[PING RX] seq={ping_seq}")
    _schedule_ack(ping_seq)
    return True


def _schedule_ack(cmd_id):
    """Schedule an ACK packet to be sent after the stagger delay."""
    global ack_pending
    rssi_raw = rfm9x.last_rssi if rfm9x is not None else 0
    rssi_enc = (rssi_raw + 200) & 0xFF
    bat = read_battery_pct()
    pkt = bytearray(ACK_PACKET_SIZE)
    pkt[0] = ACK_MARKER
    pkt[1] = DEVICE_ID
    pkt[2] = cmd_id & 0xFF
    pkt[3] = rssi_enc
    pkt[4] = bat
    pkt[5] = 0x00
    pkt[6] = pkt[0] ^ pkt[1] ^ pkt[2] ^ pkt[3] ^ pkt[4] ^ pkt[5]
    ack_pending = (time.monotonic() + BASE_ACK_DELAY + DEVICE_ID * ACK_STAGGER, bytes(pkt))


# =============================================================================
# MAIN LOOP
# =============================================================================

# Boot indication: brief white flash so you know the board is alive
pixels.fill((40, 40, 40))
pixels.show()
time.sleep(0.5)
pixels.fill((0, 0, 0))
pixels.show()

_sim_buf = bytearray(16)  # Reusable receive buffer for WiFi sim packets
_loop_tick = 0

print("Entering main loop...")

while True:
    # --- Check for incoming LoRa packet (non-blocking) ---
    if rfm9x is not None:
        packet = rfm9x.receive(timeout=0.0)
        if packet is not None:
            if len(packet) >= PING_PACKET_SIZE and packet[0] == PING_MARKER:
                print(f"[LORA RX] PING RSSI={rfm9x.last_rssi}dBm seq={packet[2] if len(packet) > 2 else '?'}")
                handle_ping(packet)
            else:
                print(f"[LORA RX] RSSI={rfm9x.last_rssi}dBm "
                      f"dev={packet[0]} cmd={packet[1]} preset={packet[2]} "
                      f"int={packet[3]} rgb=({packet[4]},{packet[5]},{packet[6]})")
                apply_packet(packet)

    # --- Check for incoming WiFi sim packet (non-blocking) ---
    if sim_udp is not None:
        try:
            nbytes, addr = sim_udp.recvfrom_into(_sim_buf)
            if nbytes >= PING_PACKET_SIZE and _sim_buf[0] == PING_MARKER:
                print(f"[SIM PING] from={addr[0]} seq={_sim_buf[2]}")
                handle_ping(_sim_buf)
            elif nbytes >= PACKET_SIZE:
                print(f"[SIM RX]  from={addr[0]} "
                      f"dev={_sim_buf[0]} cmd={_sim_buf[1]} preset={_sim_buf[2]} "
                      f"int={_sim_buf[3]} rgb=({_sim_buf[4]},{_sim_buf[5]},{_sim_buf[6]})")
                apply_packet(_sim_buf)
        except OSError:
            pass  # No packet available

    # --- Send pending ACK ---
    if ack_pending is not None:
        ack_send_at, ack_pkt = ack_pending
        if time.monotonic() >= ack_send_at:
            if rfm9x is not None:
                rfm9x.send(ack_pkt)
            if sim_udp is not None and _ack_gateway_ip is not None:
                try:
                    sim_udp.sendto(ack_pkt, (_ack_gateway_ip, ACK_PORT))
                except OSError:
                    pass
            bat_val = ack_pkt[4]
            bat_str = f"{bat_val}%" if bat_val != 255 else "N/A"
            print(f"[ACK TX] dev={DEVICE_ID} cmd={ack_pkt[2]} rssi={ack_pkt[3]-200}dBm bat={bat_str}")
            ack_pending = None

    # --- Run current effect ---
    effect_fn = EFFECTS.get(current_preset, effect_solid)
    effect_fn()

    # --- Remind user of connection info every 30s ---
    if _loop_tick % 3000 == 0 and sim_udp is not None:
        print(f"Endpoint {DEVICE_ID} | IP {wifi.radio.ipv4_address} | listening UDP :{WIFI_SIM_PORT}")
    _loop_tick += 1

    time.sleep(0.01)  # 10ms = ~100fps
