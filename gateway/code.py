# =============================================================================
# THEATER LORA GATEWAY - code.py
# =============================================================================
# Runs on: Adafruit ESP32-S3 Feather (#5477)              <- 4MB flash, 2MB PSRAM, USB-C
#          + Adafruit WIZ5500 Ethernet Breakout (#6348)   <- Ethernet, wired via primary SPI
#          + Adafruit RFM95W Breakout 915MHz (#3072)      <- LoRa radio, wired via second SPI
#
# Receives sACN (E1.31) or ArtNet from ETC Eos over Ethernet
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
#   1. Install CircuitPython 10.1.1 for "Adafruit Feather ESP32-S3 4MB Flash 2MB PSRAM"
#      from https://circuitpython.org/board/adafruit_feather_esp32s3/
#   2. Install these libraries into /lib on the board:
#        adafruit_rfm9x.mpy
#        adafruit_wiznet5k/  (folder)
#        adafruit_bus_device/ (folder)
#   3. Configure PROTOCOL and settings below
#   4. In ETC Eos: Setup > Show > Output > Add sACN or ArtNet output as appropriate
#   5. Copy this file to the board as code.py
#
# EOS PATCH GUIDE (per device, 7 channels each):
#   Ch+0: Preset select  (DMX 0-255 maps to presets 0-51, 5 values per preset)
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
import neopixel
import adafruit_rfm9x
from adafruit_wiznet5k.adafruit_wiznet5k import WIZNET5K
import adafruit_wiznet5k.adafruit_wiznet5k_socketpool as wiznet_socketpool
import os
import wifi
import socketpool
import gc
from adafruit_httpserver import Server, Request, Response, JSONResponse, POST, GET

# =============================================================================
# LOGGING  (requires boot.py to remount filesystem writable — see gateway/boot.py)
# =============================================================================

LOG_FILE   = "/log.txt"
LOG_MAX_KB = 64   # Truncate when log exceeds this size


def log(msg):
    """Print to serial and append to /log.txt with a monotonic timestamp."""
    print(msg)
    try:
        try:
            if os.stat(LOG_FILE)[6] > LOG_MAX_KB * 1024:
                with open(LOG_FILE, "w") as _f:
                    _f.write("[log truncated — size limit reached]\n")
        except OSError:
            pass   # File doesn't exist yet, that's fine
        with open(LOG_FILE, "a") as _f:
            _f.write(f"{time.monotonic():.3f}  {msg}\n")
    except OSError:
        pass   # Filesystem not writable (boot.py not deployed — logs serial only)


# Mark a new boot session in the log
try:
    with open(LOG_FILE, "a") as _f:
        _f.write(f"\n{'='*60}\n=== BOOT at t={time.monotonic():.3f} ===\n{'='*60}\n")
except OSError:
    pass   # Filesystem not writable

# =============================================================================
# CONFIGURATION
# =============================================================================

# --- WiFi Access Point ---
AP_SSID     = os.getenv("WIFI_AP_SSID",     "phosphene")
AP_PASSWORD = os.getenv("WIFI_AP_PASSWORD", "gobo1234")

# --- WiFi Simulation Mode ---
# Broadcasts the same 9-byte packets over UDP so endpoints can receive them without LoRa.
# WIFI_SIM_ENABLED: set "0" in settings.toml to disable.
# WIFI_SIM_NETWORK: "ap" = use gateway's own AP (default), "sta" = use station network.
WIFI_SIM_ENABLED = os.getenv("WIFI_SIM_ENABLED", "1") != "0"
WIFI_SIM_NETWORK = os.getenv("WIFI_SIM_NETWORK", "ap")
WIFI_SIM_PORT    = 5569   # Must match WIFI_SIM_PORT on all endpoints

# --- Protocol Selection ---
# "sacn" for sACN (E1.31) or "artnet" for ArtNet — must match Eos output type
PROTOCOL = os.getenv("PROTOCOL", "sacn")

# --- Ethernet Network ---
# USE_DHCP: set "1" in settings.toml to use DHCP instead of static IP
USE_DHCP = os.getenv("USE_DHCP", "0") != "0"

def _parse_ip(key, default):
    s = os.getenv(key, default)
    return tuple(int(x) for x in s.split("."))

STATIC_IP   = _parse_ip("STATIC_IP",   "192.168.1.50")
SUBNET_MASK = _parse_ip("SUBNET_MASK", "255.255.255.0")
GATEWAY_IP  = _parse_ip("GATEWAY_IP",  "192.168.1.1")
DNS_SERVER  = _parse_ip("DNS_SERVER",  "8.8.8.8")
MAC_ADDRESS = b"\xDE\xAD\xBE\xEF\xFE\x01"  # Must be unique on your network

# Protocol-specific settings
SACN_PORT       = 5568   # Standard sACN port, do not change
SACN_UNIVERSE   = int(os.getenv("SACN_UNIVERSE",   "1"))  # Must match Eos output universe
ARTNET_PORT     = 6454   # Standard ArtNet port, do not change
ARTNET_UNIVERSE = int(os.getenv("ARTNET_UNIVERSE", "1"))  # Must match Eos output universe

# --- LoRa ---
LORA_FREQ      = 915.0  # MHz - must match all endpoints
LORA_SF        = 7
LORA_BW        = 250000
LORA_CR        = 5
LORA_TX_POWER  = 13

# --- Redundant Send ---
SEND_REPEATS    = 3     # How many times to transmit each command
SEND_REPEAT_GAP = 0.05  # Seconds between repeats (50ms)

# --- Status NeoPixel ---
# Flashes the onboard NeoPixel when a command is sent.
# Colors per device ID (R, G, B) at a low brightness.
PIXEL_FLASH_SEC = 0.15  # How long the flash lasts
PIXEL_COLORS = {
    0: (180,  80,   0),   # Broadcast  — amber
    1: (180,   0,   0),   # Device 1   — red
    2: (  0, 180,   0),   # Device 2   — green
    3: (  0,   0, 180),   # Device 3   — blue
    4: (  0, 160, 160),   # Device 4   — cyan
    5: (160,   0, 160),   # Device 5   — magenta
}

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
# ARTNET PROTOCOL CONSTANTS
# =============================================================================
ARTNET_IDENTIFIER = b"ArtNet\x00"
ARTDMX_OPCODE     = 0x5200
MIN_ARTNET_SIZE   = 18

# =============================================================================
# HARDWARE INIT
# =============================================================================

log(f"Theater LoRa Gateway booting ({PROTOCOL.upper()})...")
log("Board: Adafruit ESP32-S3 Feather (#5477)")

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

log("Initialising WIZ5500 Ethernet...")
try:
    eth = WIZNET5K(spi0, eth_cs, mac=MAC_ADDRESS)
    log("WIZ5500 Ethernet found")
    if USE_DHCP:
        log("Getting IP via DHCP...")
        eth.dhcp()
        log(f"Ethernet IP: {eth.pretty_ip(eth.ip_address)}")
    else:
        eth.ifconfig = (STATIC_IP, SUBNET_MASK, GATEWAY_IP, DNS_SERVER)
        log(f"Ethernet static IP: {'.'.join(str(b) for b in STATIC_IP)}")
except Exception as e:
    eth = None
    log(f"WARNING: Ethernet not available: {e}")
    log("sACN/ArtNet disabled — web UI still active")

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

log("Initialising RFM95W LoRa radio...")
try:
    rfm9x = adafruit_rfm9x.RFM9x(spi1, lora_cs, lora_rst, LORA_FREQ)
    rfm9x.spreading_factor = LORA_SF
    rfm9x.signal_bandwidth = LORA_BW
    rfm9x.coding_rate      = LORA_CR
    rfm9x.tx_power         = LORA_TX_POWER
    rfm9x.enable_crc       = True
    rfm9x.node             = 0   # Gateway is node 0
    log(f"LoRa radio ready | SF{LORA_SF} BW{LORA_BW//1000}kHz @ {LORA_FREQ}MHz")
except Exception as e:
    rfm9x = None
    log(f"WARNING: LoRa radio not available: {e}")
    log("LoRa transmit disabled — web UI still active")

# =============================================================================
# WIFI ACCESS POINT + HTTP SERVER
# =============================================================================

# Status NeoPixel (board.NEOPIXEL — single pixel on Feather ESP32-S3)
status_pixel = neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=1.0, auto_write=True)
status_pixel[0] = (0, 0, 0)
_pixel_off_at = 0.0

def flash_pixel(device_id):
    """Flash the onboard NeoPixel in the color for the given device ID."""
    global _pixel_off_at
    color = PIXEL_COLORS.get(device_id, (100, 100, 100))
    status_pixel[0] = color
    _pixel_off_at = time.monotonic() + PIXEL_FLASH_SEC

log(f"Starting WiFi AP '{AP_SSID}'...")
try:
    wifi.radio.start_ap(ssid=AP_SSID, password=AP_PASSWORD)
    ap_ip = str(wifi.radio.ipv4_address_ap) if wifi.radio.ipv4_address_ap else "192.168.4.1"
    log(f"WiFi AP up | IP {ap_ip}")
except Exception as e:
    log(f"FATAL: WiFi AP start failed: {e}")
    raise
ap_pool = socketpool.SocketPool(wifi.radio)
server = Server(ap_pool, debug=False)
log("HTTP server created")


@server.route("/")
def serve_ui(request: Request):
    try:
        html = open("/gateway/ui.html", "r").read()
    except OSError:
        html = "<h1>ui.html not found — copy gateway/ui.html to CIRCUITPY/gateway/ui.html</h1>"
    return Response(request, html,
                    content_type="text/html",
                    headers={"Connection": "close"})


@server.route("/status")
def handle_status(request: Request):
    clients = 0
    try:
        ap = wifi.radio.ap_info
        if ap and hasattr(ap, "stations_count"):
            clients = ap.stations_count
    except Exception:
        pass
    return JSONResponse(request, {
        "eth_link": bool(eth.link_status) if eth is not None else False,
        "wifi_clients": clients,
        "last_cmd": last_web_cmd,
        "rssi": {}
    }, headers={"Connection": "close"})


@server.route("/send", [POST])
def handle_send(request: Request):
    global command_id, last_web_cmd
    try:
        data = request.json()
        device    = int(data.get("device",    0))
        preset    = int(data.get("preset",    4))
        intensity = int(data.get("intensity", 128))
        r         = int(data.get("r",         255))
        g         = int(data.get("g",         255))
        b         = int(data.get("b",         255))
        speed     = int(data.get("speed",     128))

        # Clamp all values to 0-255
        device    = max(0, min(5,   device))
        preset    = max(0, min(255, preset))
        intensity = max(0, min(255, intensity))
        r         = max(0, min(255, r))
        g         = max(0, min(255, g))
        b         = max(0, min(255, b))
        speed     = max(0, min(255, speed))

        packet = build_packet(device, command_id, preset, intensity, r, g, b, speed)
        command_id = (command_id + 1) & 0xFF
        schedule_sends(packet)
        last_web_cmd = {"preset": preset, "device": device, "t": time.monotonic()}
        flash_pixel(device)
        log(f"[WEB] Device {device} -> Preset={preset} Int={intensity} "
            f"RGB=({r},{g},{b}) Spd={speed}")
        return JSONResponse(request, {"ok": True}, headers={"Connection": "close"})
    except Exception as e:
        log(f"[WEB /send ERROR] {type(e).__name__}: {e}")
        return JSONResponse(request, {"ok": False, "error": str(e)},
                            headers={"Connection": "close"})


sta_ip = str(wifi.radio.ipv4_address) if wifi.radio.ipv4_address else None

# WiFi sim: broadcast LoRa packets over UDP when station connection is available
sim_udp = None
if WIFI_SIM_ENABLED:
    try:
        if WIFI_SIM_NETWORK == "ap":
            # Broadcast on the gateway's own AP subnet — no station connection needed.
            _parts = ap_ip.split(".")
            _sim_addr = f"{_parts[0]}.{_parts[1]}.{_parts[2]}.255"
            _label = f"AP subnet ({ap_ip})"
        else:  # "sta"
            if not sta_ip:
                raise OSError("no station IP available for WIFI_SIM_NETWORK='sta'")
            _parts = sta_ip.split(".")
            _sim_addr = f"{_parts[0]}.{_parts[1]}.{_parts[2]}.255"
            _label = f"station subnet ({sta_ip})"
        sim_udp = ap_pool.socket(ap_pool.AF_INET, ap_pool.SOCK_DGRAM)
        try:
            sim_udp.setsockopt(ap_pool.SOL_SOCKET, ap_pool.SO_BROADCAST, 1)
        except (AttributeError, OSError):
            pass  # Some builds don't expose the constant; send may still work
        log(f"WiFi sim mode enabled | broadcast {_sim_addr}:{WIFI_SIM_PORT} via {_label}")
    except Exception as e:
        sim_udp = None
        _sim_addr = None
        log(f"WiFi sim mode unavailable: {e}")
else:
    _sim_addr = None
    log("WiFi sim mode disabled (WIFI_SIM_ENABLED = False)")

log("Starting HTTP server on port 8080...")
try:
    server.start("0.0.0.0", port=8080)
    log(f"Web UI at http://{ap_ip}:8080 (AP)")
    if sta_ip:
        log(f"Web UI at http://{sta_ip}:8080 (local network)")
except Exception as e:
    log(f"FATAL: HTTP server start failed: {e}")
    raise

# =============================================================================
# UDP SOCKET
# =============================================================================

if eth is not None:
    log("Opening UDP socket...")
    try:
        eth_pool = wiznet_socketpool.SocketPool(eth)
        udp = eth_pool.socket(eth_pool.AF_INET, eth_pool.SOCK_DGRAM)
        if PROTOCOL == "sacn":
            udp.bind(('', SACN_PORT))
            udp.settimeout(0)
            log(f"Listening for sACN on UDP port {SACN_PORT}, universe {SACN_UNIVERSE}")
        else:
            try:
                udp.setsockopt(eth_pool.SOL_SOCKET, eth_pool.SO_BROADCAST, 1)
            except (AttributeError, OSError):
                pass  # Broadcast opt may not be needed on WIZnet hardware
            udp.bind(('', ARTNET_PORT))
            udp.settimeout(0)
            log(f"Listening for ArtNet broadcast on UDP port {ARTNET_PORT}, universe {ARTNET_UNIVERSE}")
    except Exception as e:
        udp = None
        log(f"WARNING: UDP socket setup failed: {e}")
else:
    udp = None

# =============================================================================
# STATE
# =============================================================================

dmx_data          = bytearray(512)
prev_device_state = {}
command_id        = 0
pending_sends     = []   # List of (send_at_time, packet_bytes)
last_web_cmd      = {}   # Most recent command from web UI (for /status)
loop_tick         = 0

# =============================================================================
# PROTOCOL PARSING
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


def parse_artnet(data):
    """
    Parse an ArtNet UDP packet.
    Returns the DMX payload bytes if valid, or None if invalid/wrong universe.
    """
    if len(data) < MIN_ARTNET_SIZE:
        return None
    
    # Check ArtNet identifier
    if data[0:8] != ARTNET_IDENTIFIER:
        return None
    
    # Check opcode (must be ArtDMX = 0x5200)
    opcode = struct.unpack_from(">H", data, 8)[0]
    if opcode != ARTDMX_OPCODE:
        return None
    
    # Check version (must be >= 14)
    version = struct.unpack_from(">H", data, 10)[0]
    if version < 14:
        return None
    
    # Extract universe (Net + SubUni)
    net = data[15] & 0x7F
    subuni = data[14] & 0x0F
    universe = (net << 4) | subuni
    
    if universe != ARTNET_UNIVERSE:
        return None
    
    # Get DMX data length
    dmx_length = struct.unpack_from(">H", data, 16)[0]
    if dmx_length < 1 or dmx_length > 512:
        return None
    
    # Return DMX data (starts at offset 18)
    return data[18:18 + dmx_length]


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
    Map a DMX value (0-255) to a preset number.
    Each preset gets 5 DMX values for easy Eos encoder control.

    Preset map:
      0-4   =  0  Blackout        5-9   =  1  Sparkle
      10-14 =  2  Chase           15-19 =  3  Fade (breathe)
      20-24 =  4  Solid           25-29 =  5  Twinkle on Solid
      30-34 =  6  Strobe          35-39 =  7  Meteor
      40-44 =  8  Fire            45-49 =  9  Rainbow
      50-54 = 10  Lightning       55-59 = 11 Marquee
      60-64 = 12  Candle          65-69 = 13 Color Wipe
      70-74 = 14  Heartbeat       75-79 = 15 Alarm
      80-84 = 16  Comet           85-89 = 17 Ripple
      90-94 = 18  Scanner         95-99 = 19 Bubbles
      100-104 = 20 Campfire       105-109 = 21 Confetti
      110-114 = 22 Wave           115-119 = 23 Flicker
      120-124 = 24 Theater Chase  125-129 = 25 Rainbow Chase
      130-134 = 26 Aurora         135-139 = 27 Wave Pastel
    """
    return min(raw_value // 5, 51)


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
            log(f"[sACN] Device {device_id} -> Preset={preset} Int={intensity} "
                f"RGB=({r},{g},{b}) Spd={speed} CmdID={command_id}")
            flash_pixel(device_id)
            command_id = (command_id + 1) & 0xFF


# =============================================================================
# MAIN LOOP
# =============================================================================

log(f"\nGateway running. Waiting for {PROTOCOL.upper()} from Eos...")

if PROTOCOL == "artnet":
    log("Note: ArtNet uses broadcast — no gateway IP needed in Eos.")

parse_func = parse_sacn if PROTOCOL == "sacn" else parse_artnet

while True:
    now = time.monotonic()

    # --- Process pending sends (LoRa and/or WiFi sim) ---
    if pending_sends and (rfm9x is not None or sim_udp is not None):
        still_pending = []
        for send_at, packet in pending_sends:
            if now >= send_at:
                if rfm9x is not None:
                    rfm9x.send(packet)
                    log(f"[LORA TX] dev={packet[0]} cmd={packet[1]} preset={packet[2]}")
                if sim_udp is not None:
                    try:
                        sim_udp.sendto(packet, (_sim_addr, WIFI_SIM_PORT))
                        log(f"[SIM TX]  dev={packet[0]} cmd={packet[1]} preset={packet[2]}")
                    except OSError as e:
                        log(f"[SIM TX]  FAILED: {e}")
            else:
                still_pending.append((send_at, packet))
        pending_sends[:] = still_pending

    # --- Receive DMX from Eos ---
    if udp is not None:
        try:
            raw, addr = udp.recvfrom(638)
            if raw:
                payload = parse_func(raw)
                if payload is not None:
                    dmx_data[:len(payload)] = payload
                    check_device_changes()
        except OSError:
            pass   # No packet available in non-blocking mode

    # --- Serve web UI requests ---
    try:
        server.poll()
    except OSError as e:
        log(f"[server.poll OSError] {e}")
    except Exception as e:
        log(f"[server.poll ERROR] {type(e).__name__}: {e}")

    # --- Status pixel off timer ---
    if _pixel_off_at and now >= _pixel_off_at:
        status_pixel[0] = (0, 0, 0)
        _pixel_off_at = 0.0

    # --- Periodic GC (~every 5s at 500 ticks × 10ms) ---
    if loop_tick % 500 == 0:
        gc.collect()

    # --- Remind user of web UI address every 30s ---
    if loop_tick % 3000 == 0:
        log(f"Web UI: http://{ap_ip}:8080")
        if sta_ip:
            log(f"        http://{sta_ip}:8080")

    loop_tick += 1

    time.sleep(0.010)   # 10ms — keeps loop responsive without burning CPU
