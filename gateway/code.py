# =============================================================================
# THEATER LORA GATEWAY - code.py
# =============================================================================
# Runs on: Adafruit ESP32-S3 Feather (#5477)              <- 4MB flash, 2MB PSRAM, USB-C
#          + Adafruit WIZ5500 Ethernet Breakout (#6348)   <- Ethernet, wired via primary SPI
#          + Adafruit RFM95W Breakout 915MHz (#3072)      <- LoRa radio, wired via second SPI
#
# Receives sACN (E1.31) from ETC Eos over Ethernet
# Translates DMX channels to compact LoRa preset commands
# Re-broadcasts each command 3x (50ms apart) for reliability
#
# HARDWARE CONNECTIONS:
#   All boards wired point-to-point. Gateway is USB-C powered — no battery needed.
#
#   WIZ5500 Ethernet Breakout (#6348) — Primary SPI bus:
#     VIN  -> 3.3V  (Feather 3V3 pin)
#     GND  -> GND
#     SCK  -> SCK   (board.SCK  — primary SPI clock)
#     MOSI -> MOSI  (board.MOSI — primary SPI TX)
#     MISO -> MISO  (board.MISO — primary SPI RX)
#     CS   -> D9    (board.D9   — chip select)
#
#   RFM95W Breakout (#3072) — Second SPI bus:
#     VIN  -> 3.3V  (Feather 3V3 pin)
#     GND  -> GND
#     SCK  -> D10   (board.D10  — second SPI clock)
#     MOSI -> D11   (board.D11  — second SPI TX)
#     MISO -> D12   (board.D12  — second SPI RX)
#     CS   -> D13   (board.D13  — chip select)
#     RST  -> A0    (board.A0)
#     G0   -> A1    (board.A1   — DIO0/IRQ)
#     Antenna: spring antenna (#4269) to uFL connector
#
# SETUP:
#   1. Install CircuitPython 9.x for "Adafruit Feather ESP32-S3 4MB Flash 2MB PSRAM"
#      from https://circuitpython.org/board/adafruit_feather_esp32s3/
#   2. Install these libraries into /lib on the board:
#        adafruit_rfm9x.mpy
#        adafruit_wiznet5k/  (folder)
#        adafruit_bus_device/ (folder)
#   3. Configure the settings section below
#   4. In ETC Eos: Setup > Show > Output > Add sACN output to this device's IP
#   5. Copy this file to the board as code.py
#
# EOS PATCH GUIDE (per device, 7 channels each):
#   Ch+0: Preset select  (DMX 0-255 maps to presets 0-25, 10 values per preset)
#   Ch+1: Intensity      (0-255)
#   Ch+2: Red            (0-255)
#   Ch+3: Green          (0-255)
#   Ch+4: Blue           (0-255)
#   Ch+5: Speed          (0-255, 0=slow 255=fast)
#   Ch+6: Reserved/spare (future use)
#
# Example patch:
#   Device 1 starts at DMX address 1   (channels 1-7)
#   Device 2 starts at DMX address 8   (channels 8-14)
#   Broadcast "all devices" at address 50 (channels 50-56) - set device id=0
# =============================================================================

import time
import struct
import board
import busio
import digitalio
import adafruit_rfm9x
from adafruit_wiznet5k.adafruit_wiznet5k import WIZNET5K
import adafruit_wiznet5k.adafruit_wiznet5k_socket as socket

# =============================================================================
# CONFIGURATION
# =============================================================================

# --- Network ---
USE_DHCP       = False
STATIC_IP      = (192, 168, 1, 50)   # Change to match your network
SUBNET_MASK    = (255, 255, 255, 0)
GATEWAY_IP     = (192, 168, 1, 1)
DNS_SERVER     = (8, 8, 8, 8)
MAC_ADDRESS    = b"\xDE\xAD\xBE\xEF\xFE\x01"  # Must be unique on your network

SACN_PORT      = 5568   # Standard sACN port, do not change
SACN_UNIVERSE  = 1      # Must match Eos output universe config

# --- LoRa ---
LORA_FREQ      = 915.0  # MHz - must match all endpoints
LORA_SF        = 7
LORA_BW        = 250000
LORA_CR        = 5
LORA_TX_POWER  = 13

# --- Redundant Send ---
SEND_REPEATS    = 3     # How many times to transmit each command
SEND_REPEAT_GAP = 0.05  # Seconds between repeats (50ms)

# --- Device Patch Map ---
# Maps Device ID -> DMX start address (1-based, as shown in Eos patch)
DEVICE_PATCH = {
    0: 50,   # Broadcast "all devices" - address 50
    1: 1,    # Device 1 - address 1
    2: 8,    # Device 2 - address 8
    3: 15,   # Device 3 - address 15
    4: 22,   # Device 4 - address 22
    5: 29,   # Device 5 - address 29
}

# =============================================================================
# PACKET PROTOCOL (must match endpoints)
# =============================================================================
# Byte 0:  Device ID
# Byte 1:  Command ID (auto-increments)
# Byte 2:  Preset
# Byte 3:  Intensity
# Byte 4:  R
# Byte 5:  G
# Byte 6:  B
# Byte 7:  Speed
# Byte 8:  Checksum (XOR bytes 0-7)

CH_PRESET           = 0
CH_INTENSITY        = 1
CH_RED              = 2
CH_GREEN            = 3
CH_BLUE             = 4
CH_SPEED            = 5
CHANNELS_PER_DEVICE = 7

# =============================================================================
# sACN (E1.31) PROTOCOL CONSTANTS
# =============================================================================
SACN_HEADER_SIZE       = 126
E131_PACKET_IDENTIFIER = b"ASC-E1.17\x00\x00\x00"

# =============================================================================
# HARDWARE INIT
# =============================================================================

print("Theater LoRa Gateway booting...")
print("Board: Adafruit ESP32-S3 Feather (#5477)")

# -------------------------------------------------------------------------
# Primary SPI — WIZ5500 Ethernet Breakout (#6348)
# board.SCK=SCK, board.MOSI=MOSI, board.MISO=MISO, CS=D9
# -------------------------------------------------------------------------
spi0 = busio.SPI(
    clock=board.SCK,
    MOSI=board.MOSI,
    MISO=board.MISO,
)

eth_cs = digitalio.DigitalInOut(board.D9)
eth_cs.direction = digitalio.Direction.OUTPUT
eth_cs.value = True   # Deassert CS before init

try:
    eth = WIZNET5K(spi0, eth_cs, mac=MAC_ADDRESS)
    print("WIZ5500 Ethernet found")
except Exception as e:
    print(f"Ethernet init failed: {e}")
    print("Check wires: SCK->SCK, MOSI->MOSI, MISO->MISO, CS->D9, VIN->3.3V")
    raise

if USE_DHCP:
    print("Getting IP via DHCP...")
    eth.dhcp()
    print(f"IP Address: {eth.pretty_ip(eth.ip_address)}")
else:
    eth.ifconfig = (STATIC_IP, SUBNET_MASK, GATEWAY_IP, DNS_SERVER)
    print(f"Static IP: {'.'.join(str(b) for b in STATIC_IP)}")

# -------------------------------------------------------------------------
# Second SPI — RFM95W Breakout (#3072)
# D10=SCK, D11=MOSI, D12=MISO, D13=CS, A0=RST, A1=G0/IRQ
# ESP32-S3 GPIO matrix allows any pins as SPI — fully independent from spi0
# -------------------------------------------------------------------------
spi1 = busio.SPI(
    clock=board.D10,
    MOSI=board.D11,
    MISO=board.D12,
)

lora_cs  = digitalio.DigitalInOut(board.D13)
lora_rst = digitalio.DigitalInOut(board.A0)
# A1 (G0/DIO0) used internally by adafruit_rfm9x — no manual setup needed

lora_cs.direction = digitalio.Direction.OUTPUT
lora_cs.value = True   # Deassert CS before init

try:
    rfm9x = adafruit_rfm9x.RFM9x(spi1, lora_cs, lora_rst, LORA_FREQ)
    rfm9x.spreading_factor = LORA_SF
    rfm9x.signal_bandwidth = LORA_BW
    rfm9x.coding_rate      = LORA_CR
    rfm9x.tx_power         = LORA_TX_POWER
    rfm9x.enable_crc       = True
    rfm9x.node             = 0   # Gateway is node 0
    print(f"LoRa radio ready | SF{LORA_SF} BW{LORA_BW//1000}kHz @ {LORA_FREQ}MHz")
except Exception as e:
    print(f"LoRa init failed: {e}")
    print("Check wires: SCK->D10, MOSI->D11, MISO->D12, CS->D13, RST->A0, G0->A1")
    raise

# =============================================================================
# UDP SOCKET for sACN
# =============================================================================

socket.set_interface(eth)
udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.bind(('', SACN_PORT))
udp.setblocking(False)
print(f"Listening for sACN on UDP port {SACN_PORT}, universe {SACN_UNIVERSE}")

# =============================================================================
# STATE
# =============================================================================

dmx_data         = bytearray(512)
prev_device_state = {}
command_id       = 0
pending_sends    = []   # List of (send_at_time, packet_bytes)

# =============================================================================
# sACN PARSING
# =============================================================================

def parse_sacn(data):
    """
    Parse an sACN (E1.31) UDP packet.
    Returns the DMX payload bytes if valid, or None if invalid/wrong universe.
    """
    if len(data) < SACN_HEADER_SIZE + 1:
        return None
    if data[4:16] != E131_PACKET_IDENTIFIER:
        return None
    universe = struct.unpack_from(">H", data, 113)[0]
    if universe != SACN_UNIVERSE:
        return None
    if data[125] != 0:   # Null start code = standard DMX data
        return None
    prop_count = struct.unpack_from(">H", data, 123)[0] & 0x0FFF
    dmx_length = prop_count - 1
    return data[SACN_HEADER_SIZE : SACN_HEADER_SIZE + dmx_length]


# =============================================================================
# LORA PACKET BUILDING
# =============================================================================

def build_packet(device_id, cmd_id, preset, intensity, r, g, b, speed):
    """Build a 9-byte LoRa command packet with XOR checksum."""
    data = bytearray(9)
    data[0] = device_id  & 0xFF
    data[1] = cmd_id     & 0xFF
    data[2] = preset     & 0xFF
    data[3] = intensity  & 0xFF
    data[4] = r          & 0xFF
    data[5] = g          & 0xFF
    data[6] = b          & 0xFF
    data[7] = speed      & 0xFF
    checksum = 0
    for byte in data[:8]:
        checksum ^= byte
    data[8] = checksum
    return bytes(data)


def dmx_to_preset(raw_value):
    """
    Map a DMX value (0-255) to one of 26 preset numbers.
    Each preset gets ~10 DMX values for easy Eos encoder control.

    Preset map:
      0-9   =  0  Blackout        10-19 =  1  Sparkle
      20-29 =  2  Chase           30-39 =  3  Fade (breathe)
      40-49 =  4  Solid           50-59 =  5  Twinkle on Solid
      60-69 =  6  Strobe          70-79 =  7  Meteor
      80-89 =  8  Fire            90-99 =  9  Rainbow
      100-109 = 10 Lightning      110-119 = 11 Marquee
      120-129 = 12 Candle         130-139 = 13 Color Wipe
      140-149 = 14 Heartbeat      150-159 = 15 Alarm
      160-169 = 16 Comet          170-179 = 17 Ripple
      180-189 = 18 Scanner        190-199 = 19 Bubbles
      200-209 = 20 Campfire       210-219 = 21 Confetti
      220-229 = 22 Wave           230-239 = 23 Flicker
      240-249 = 24 Theater Chase  250-255 = 25 Rainbow Chase
    """
    return min(raw_value // 10, 25)


def schedule_sends(packet):
    """Schedule SEND_REPEATS transmissions spaced SEND_REPEAT_GAP seconds apart."""
    now = time.monotonic()
    for i in range(SEND_REPEATS):
        pending_sends.append((now + (i * SEND_REPEAT_GAP), packet))


# =============================================================================
# DMX CHANGE DETECTION
# =============================================================================

def check_device_changes():
    """
    For each patched device, read its DMX channels and compare to previous state.
    Schedule a LoRa broadcast for any device whose channels have changed.
    """
    global command_id

    for device_id, start_addr in DEVICE_PATCH.items():
        base = start_addr - 1   # DMX is 1-based in Eos, 0-based in our array

        if base + CHANNELS_PER_DEVICE > len(dmx_data):
            continue

        preset    = dmx_to_preset(dmx_data[base + CH_PRESET])
        intensity = dmx_data[base + CH_INTENSITY]
        r         = dmx_data[base + CH_RED]
        g         = dmx_data[base + CH_GREEN]
        b         = dmx_data[base + CH_BLUE]
        speed     = dmx_data[base + CH_SPEED]

        new_state = (preset, intensity, r, g, b, speed)

        if new_state != prev_device_state.get(device_id):
            prev_device_state[device_id] = new_state
            packet = build_packet(device_id, command_id, preset, intensity, r, g, b, speed)
            schedule_sends(packet)
            print(f"Device {device_id} -> Preset={preset} Int={intensity} "
                  f"RGB=({r},{g},{b}) Spd={speed} CmdID={command_id}")
            command_id = (command_id + 1) & 0xFF


# =============================================================================
# MAIN LOOP
# =============================================================================

print("\nGateway running. Waiting for sACN from Eos...\n")

while True:
    now = time.monotonic()

    # --- Process pending LoRa sends ---
    still_pending = []
    for send_at, packet in pending_sends:
        if now >= send_at:
            rfm9x.send(packet)
        else:
            still_pending.append((send_at, packet))
    pending_sends[:] = still_pending

    # --- Receive sACN from Eos ---
    try:
        raw, addr = udp.recvfrom(638)
        if raw:
            payload = parse_sacn(raw)
            if payload is not None:
                dmx_data[:len(payload)] = payload
                check_device_changes()
    except OSError:
        pass   # No packet available in non-blocking mode

    time.sleep(0.002)   # 2ms — keeps loop responsive without burning CPU
