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
#     DATA -> D5    (board.D5 — change NEOPIXEL_PIN in settings.toml if needed)
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
#        adafruit_max1704x.mpy  (or adafruit_lc709203f.mpy for alternative battery monitor)
#   3. Copy endpoint/ folder to CIRCUITPY (code.py, config.py, hardware.py, effects/)
#   4. Create CIRCUITPY/settings.toml with DEVICE_ID, NUM_PIXELS, etc.
#
# PRESETS (0-27):
#    0:Blackout  1:Sparkle    2:Chase      3:Fade       4:Solid
#    5:Twinkle   6:Strobe     7:Comet      8:Fire       9:Rainbow
#   10:Lightning 11:Marquee   12:Candle    13:ColorWipe 14:Heartbeat
#   15:Alarm     16:Comet     17:Ripple    18:Scanner   19:Bubbles
#   20:Campfire  21:Confetti  22:Wave      23:Flicker   24:TheaterChase
#   25:RainbowChase 26:Aurora  27:WavePastel
# =============================================================================

import time
import random
import os

import board
import busio
import digitalio
import neopixel
import wifi
import socketpool
import adafruit_rfm9x

import config
import hardware
from effects import EFFECTS, Effect, scale_color


# =============================================================================
# CONFIGURATION
# =============================================================================

CFG = config.load_config()

DEVICE_ID = CFG["device_id"]
NUM_PIXELS = CFG["num_pixels"]
NEOPIXEL_PIN = CFG["neopixel_pin"]

WIFI_SIM_ENABLED = CFG["wifi_sim_enabled"]
WIFI_SIM_NETWORK = CFG["wifi_sim_network"]
WIFI_SIM_PORT = CFG["wifi_sim_port"]

STATUS_LED_ENABLED = CFG["status_led_enabled"]
STATUS_LED_BRIGHTNESS = CFG["status_led_brightness"]

LORA_FREQ = CFG["lora_freq"]
LORA_SF = CFG["lora_sf"]
LORA_BW = CFG["lora_bw"]
LORA_CR = CFG["lora_cr"]
LORA_TX_POWER = CFG["lora_tx_power"]

DEDUP_WINDOW = CFG["dedup_window"]

# Packet constants
PACKET_SIZE = 12
ACK_PACKET_SIZE = 7
ACK_MARKER = 0xAC
CONFIG_ACK_REQUESTED = 0x01
ACK_PORT = 5570
BASE_ACK_DELAY = 0.15
ACK_STAGGER = 0.08

PING_MARKER = 0xBB
PING_PACKET_SIZE = 4


# =============================================================================
# STATUS LED
# =============================================================================

_status_pixel = None
_status_off_at = 0.0

_SL_RADIO_OFF = (100, 0, 0)
_SL_RADIO_ON = (0, 100, 100)
_SL_BOOST_OFF = (0, 0, 100)
_SL_BOOST_ON = (750, 0, 100)
_SL_WIFI_OK = (0, 80, 0)
_SL_LORA_RX = (0, 0, 80)
_SL_WIFI_RX = (0, 60, 60)
_SL_PING = (60, 60, 0)
_SL_ACK_TX = (60, 0, 60)


def status_flash(color, duration=0.15):
    global _status_off_at
    if _status_pixel is None:
        return
    scale = STATUS_LED_BRIGHTNESS / 100.0
    _status_pixel[0] = (
        min(255, int(color[0] * scale)),
        min(255, int(color[1] * scale)),
        min(255, int(color[2] * scale)),
    )
    _status_off_at = time.monotonic() + duration


# =============================================================================
# HARDWARE INIT
# =============================================================================

print(f"Phosphene Endpoint {DEVICE_ID} booting...")
print(f"Board: ESP32-S3 Feather | {NUM_PIXELS} pixels")

time.sleep(1.0)

# Status pixel
if STATUS_LED_ENABLED:
    try:
        _status_pixel = hardware.init_status_pixel()
    except Exception as e:
        print(f"WARNING: Status LED unavailable: {e}")

# Boost enable
if CFG["boost_en_pin"]:
    print(f"Boost EN ({CFG['boost_en_pin']}) enabling...")
    status_flash(_SL_BOOST_OFF, 0.5)
    hardware.init_boost_enable(CFG["boost_en_pin"])
    print(f"Boost EN ({CFG['boost_en_pin']}) HIGH")
    status_flash(_SL_BOOST_ON, 0.5)

# LED strip
pixels = hardware.init_neopixel(NEOPIXEL_PIN, NUM_PIXELS)
print(f"NeoPixels: {NUM_PIXELS} on {NEOPIXEL_PIN}")

# Battery monitor
_bat_monitor, _bat_type = hardware.init_battery_monitor()
if _bat_monitor:
    print(
        f"Battery monitor ready ({_bat_type} | {_bat_monitor.cell_voltage:.2f}V "
        f"{_bat_monitor.cell_percent:.0f}%)"
    )


def read_battery_pct():
    return hardware.read_battery(_bat_monitor)


# Radio enable
if CFG["radio_en_pin"]:
    print(f"Radio EN ({CFG['radio_en_pin']}) enabling...")
    status_flash(_SL_RADIO_OFF, 0.5)
    hardware.init_radio_enable(CFG["radio_en_pin"])
    print(f"Radio EN ({CFG['radio_en_pin']}) HIGH")
    status_flash(_SL_RADIO_ON, 0.5)

# LoRa radio
spi = hardware.init_spi()
lora_cs, lora_rst = hardware.init_lora_pins()

print("Initialising RFM95W LoRa radio...")
try:
    rfm9x = adafruit_rfm9x.RFM9x(spi, lora_cs, lora_rst, LORA_FREQ)
    rfm9x.spreading_factor = LORA_SF
    rfm9x.signal_bandwidth = LORA_BW
    rfm9x.coding_rate = LORA_CR
    rfm9x.tx_power = LORA_TX_POWER
    rfm9x.enable_crc = True
    rfm9x.node = DEVICE_ID
    rfm9x.destination = 0xFF
    print(f"LoRa ready | SF{LORA_SF} BW{LORA_BW // 1000}kHz @ {LORA_FREQ}MHz")
except Exception as e:
    rfm9x = None
    print(f"WARNING: LoRa not available: {e}")

# WiFi sim mode
_ack_gateway_ip = None
sim_udp = None
if WIFI_SIM_ENABLED:
    if WIFI_SIM_NETWORK == "ap":
        _sim_ssid = os.getenv("WIFI_AP_SSID", "phosphene")
        _sim_pass = os.getenv("WIFI_AP_PASSWORD", "gobo1234")
        _sim_label = f"gateway AP '{_sim_ssid}'"
    else:
        _sim_ssid = os.getenv("WIFI_SSID")
        _sim_pass = os.getenv("WIFI_PASSWORD", "")
        _sim_label = f"network '{_sim_ssid}'"

    if _sim_ssid:
        try:
            print(f"Connecting to {_sim_label}...")
            wifi.radio.connect(_sim_ssid, _sim_pass)
            print(f"WiFi connected | IP {wifi.radio.ipv4_address}")
            status_flash(_SL_WIFI_OK, 0.5)
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
        print("WiFi sim mode disabled (WIFI_SSID not set)")


# =============================================================================
# STATE
# =============================================================================

current_preset = 0
current_intensity = 128
current_r = 255
current_g = 255
current_b = 255
current_speed = 128

last_command_id = -1
last_command_time = 0.0

current_effect = None

ack_pending = None
last_ping_seq = -1
last_ping_time = 0.0


# =============================================================================
# PACKET HANDLING
# =============================================================================


def verify_checksum(packet):
    if len(packet) < PACKET_SIZE:
        return False
    checksum = 0
    for b in packet[:11]:
        checksum ^= b
    return checksum == packet[11]


def apply_packet(packet):
    global current_preset, current_intensity
    global current_r, current_g, current_b, current_speed
    global last_command_id, last_command_time
    global current_effect

    if len(packet) < PACKET_SIZE:
        print(f"  Packet too short ({len(packet)} bytes), ignoring")
        return False

    if not verify_checksum(packet):
        print("  Checksum failed, ignoring")
        return False

    device_id = packet[0]
    command_id = packet[1]
    preset = packet[2]
    intensity = packet[3]
    r = packet[4]
    g = packet[5]
    b = packet[6]
    speed = packet[7]
    config_flags = packet[8]

    if device_id != 0 and device_id != DEVICE_ID:
        print(f"  Packet for device {device_id}, we are {DEVICE_ID}, ignoring")
        return False

    now = time.monotonic()
    if command_id == last_command_id and (now - last_command_time) < DEDUP_WINDOW:
        print(f"  Duplicate command {command_id}, ignoring")
        return False

    last_command_id = command_id
    last_command_time = now

    print(
        f"  CMD {command_id} | Preset {preset} | RGBA({r},{g},{b}) Int={intensity} Spd={speed}"
    )

    if config_flags & CONFIG_ACK_REQUESTED:
        _schedule_ack(command_id)

    if preset != current_preset:
        effect_class = EFFECTS.get(preset, EFFECTS[4])
        current_effect = effect_class(NUM_PIXELS)

    current_preset = preset
    current_intensity = intensity
    current_r = r
    current_g = g
    current_b = b
    current_speed = speed

    return True


def _schedule_ack(cmd_id):
    global ack_pending
    rssi_raw = rfm9x.last_rssi if rfm9x is not None else 0
    rssi_enc = (int(rssi_raw) + 200) & 0xFF
    bat = read_battery_pct()
    pkt = bytearray(ACK_PACKET_SIZE)
    pkt[0] = ACK_MARKER
    pkt[1] = DEVICE_ID
    pkt[2] = cmd_id & 0xFF
    pkt[3] = rssi_enc
    pkt[4] = bat
    pkt[5] = 0x00
    pkt[6] = pkt[0] ^ pkt[1] ^ pkt[2] ^ pkt[3] ^ pkt[4] ^ pkt[5]
    ack_pending = (
        time.monotonic() + BASE_ACK_DELAY + DEVICE_ID * ACK_STAGGER,
        bytes(pkt),
    )


def handle_ping(packet):
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
        return True
    last_ping_seq = ping_seq
    last_ping_time = now
    print(f"[PING RX] seq={ping_seq}")
    status_flash(_SL_PING)
    _schedule_ack(ping_seq)
    return True


# =============================================================================
# MAIN LOOP
# =============================================================================

# Boot flash
pixels.fill((40, 40, 40))
pixels.show()
time.sleep(0.5)
pixels.fill((0, 0, 0))
pixels.show()

# Initialize effect
current_effect = EFFECTS[0](NUM_PIXELS)  # Blackout

_sim_buf = bytearray(16)
_loop_tick = 0

print("Entering main loop...")

while True:
    # Status LED off timer
    if (
        _status_off_at
        and _status_pixel is not None
        and time.monotonic() >= _status_off_at
    ):
        _status_pixel[0] = (0, 0, 0)
        _status_off_at = 0.0

    # LoRa RX
    if rfm9x is not None:
        packet = rfm9x.receive(timeout=0.0)
        if packet is not None:
            if len(packet) >= PING_PACKET_SIZE and packet[0] == PING_MARKER:
                print(
                    f"[LORA RX] PING RSSI={rfm9x.last_rssi}dBm seq={packet[2] if len(packet) > 2 else '?'}"
                )
                handle_ping(packet)
            else:
                print(
                    f"[LORA RX] RSSI={rfm9x.last_rssi}dBm "
                    f"dev={packet[0]} cmd={packet[1]} preset={packet[2]} "
                    f"int={packet[3]} rgb=({packet[4]},{packet[5]},{packet[6]})"
                )
                status_flash(_SL_LORA_RX)
                apply_packet(packet)

    # WiFi sim RX
    if sim_udp is not None:
        try:
            nbytes, addr = sim_udp.recvfrom_into(_sim_buf)
            if nbytes >= PING_PACKET_SIZE and _sim_buf[0] == PING_MARKER:
                print(f"[SIM PING] from={addr[0]} seq={_sim_buf[2]}")
                handle_ping(_sim_buf)
            elif nbytes >= PACKET_SIZE:
                print(
                    f"[SIM RX]  from={addr[0]} "
                    f"dev={_sim_buf[0]} cmd={_sim_buf[1]} preset={_sim_buf[2]} "
                    f"int={_sim_buf[3]} rgb=({_sim_buf[4]},{_sim_buf[5]},{_sim_buf[6]})"
                )
                status_flash(_SL_WIFI_RX)
                apply_packet(_sim_buf)
        except OSError:
            pass

    # Send pending ACK
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
            print(
                f"[ACK TX] dev={DEVICE_ID} cmd={ack_pkt[2]} rssi={ack_pkt[3] - 200}dBm bat={bat_str}"
            )
            status_flash(_SL_ACK_TX)
            ack_pending = None

    # Run effect
    if current_effect is not None:
        if current_preset == 0:
            pixels.fill((0, 0, 0))
            pixels.show()
        else:
            current_effect.update(
                pixels,
                current_r,
                current_g,
                current_b,
                current_intensity,
                current_speed,
            )

    # Info every 30s
    if _loop_tick % 3000 == 0 and sim_udp is not None:
        print(
            f"Endpoint {DEVICE_ID} | IP {wifi.radio.ipv4_address} | listening UDP :{WIFI_SIM_PORT}"
        )
    _loop_tick += 1

    time.sleep(0.01)
