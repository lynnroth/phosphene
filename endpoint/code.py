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
#   1. Install CircuitPython 9.x for "Adafruit Feather ESP32-S3 4MB Flash 2MB PSRAM"
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
import random
import board
import busio
import digitalio
import neopixel
import adafruit_rfm9x

# =============================================================================
# CONFIGURATION - Edit these for each device
# =============================================================================

DEVICE_ID = 1           # Unique ID for this endpoint (1-5). 0 = gateway broadcast address.

NEOPIXEL_PIN = board.D5    # GPIO pin connected to NeoPixel data line
NUM_PIXELS = 40         # Number of NeoPixels on this device (change to match your strip)

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
# Byte 8:  Checksum (XOR of bytes 0-7)

PACKET_SIZE = 9

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

# LoRa Radio — RFM95W Breakout (#3072) on primary SPI bus
# board.SCK=SCK, board.MOSI=MOSI, board.MISO=MISO, CS=D9, RST=D10, G0/IRQ=D11
spi = busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)
cs  = digitalio.DigitalInOut(board.D9)
rst = digitalio.DigitalInOut(board.D10)

rfm9x = adafruit_rfm9x.RFM9x(spi, cs, rst, LORA_FREQ)
rfm9x.spreading_factor  = LORA_SF
rfm9x.signal_bandwidth  = LORA_BW
rfm9x.coding_rate       = LORA_CR
rfm9x.tx_power          = LORA_TX_POWER
rfm9x.enable_crc        = True
rfm9x.node              = DEVICE_ID
rfm9x.destination       = 0xFF  # Accept any sender

print(f"Theater LoRa Endpoint {DEVICE_ID} ready")
print(f"Board: ESP32-S3 Feather (#5477) | {NUM_PIXELS} pixels | LoRa SF{LORA_SF}/BW{LORA_BW//1000}kHz")

# =============================================================================
# STATE
# =============================================================================

# Current effect parameters (set by received LoRa packet)
current_preset    = PRESET_SOLID
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
    for b in packet[:8]:
        checksum ^= b
    return checksum == packet[8]


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

    device_id  = packet[0]
    command_id = packet[1]
    preset     = packet[2]
    intensity  = packet[3]
    r          = packet[4]
    g          = packet[5]
    b          = packet[6]
    speed      = packet[7]

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

    current_preset    = preset
    current_intensity = intensity
    current_r         = r
    current_g         = g
    current_b         = b
    current_speed     = speed

    return True


# =============================================================================
# MAIN LOOP
# =============================================================================

# Boot indication: brief white flash so you know the board is alive
pixels.fill((40, 40, 40))
pixels.show()
time.sleep(0.5)
pixels.fill((0, 0, 0))
pixels.show()

print("Entering main loop...")

while True:
    # --- Check for incoming LoRa packet (non-blocking, timeout=0) ---
    packet = rfm9x.receive(timeout=0.0)

    if packet is not None:
        rssi = rfm9x.last_rssi
        print(f"Packet received | RSSI: {rssi} dBm | {len(packet)} bytes")
        apply_packet(packet)

    # --- Run current effect ---
    effect_fn = EFFECTS.get(current_preset, effect_solid)
    effect_fn()

    # Small sleep to prevent CPU from spinning at full speed unnecessarily.
    # Keep this SHORT so animation stays smooth.
    # The LoRa radio buffers incoming packets even during this sleep.
    time.sleep(0.01)  # 10ms = ~100fps max animation rate, plenty for effects
