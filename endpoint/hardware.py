import time
import board
import busio
import digitalio
import neopixel


def init_status_pixel():
    """Initialize the onboard status NeoPixel."""
    return neopixel.NeoPixel(board.NEOPIXEL, 1, brightness=1.0, auto_write=True)


def init_neopixel(pin, num_pixels):
    """Initialize the LED strip NeoPixels."""
    return neopixel.NeoPixel(
        pin, num_pixels, brightness=1.0, auto_write=False, pixel_order=neopixel.GRB
    )


def init_boost_enable(pin_name):
    """Initialize the bq25185 boost enable pin if configured."""
    if not pin_name:
        return None
    try:
        boost_en = digitalio.DigitalInOut(getattr(board, pin_name))
        boost_en.direction = digitalio.Direction.OUTPUT
        boost_en.value = True
        time.sleep(0.25)
        return boost_en
    except Exception as e:
        print(f"WARNING: BOOST_EN_PIN '{pin_name}' failed: {e}")
        return None


def init_radio_enable(pin_name):
    """Initialize the RFM95W radio enable pin if configured."""
    if not pin_name:
        return None
    try:
        radio_en = digitalio.DigitalInOut(getattr(board, pin_name))
        radio_en.direction = digitalio.Direction.OUTPUT
        radio_en.value = True
        time.sleep(0.5)
        return radio_en
    except Exception as e:
        print(f"WARNING: RADIO_EN_PIN '{pin_name}' failed: {e}")
        return None


def init_spi():
    """Initialize SPI for LoRa radio."""
    return busio.SPI(clock=board.SCK, MOSI=board.MOSI, MISO=board.MISO)


def init_lora_pins():
    """Initialize GPIO pins for LoRa radio."""
    cs = digitalio.DigitalInOut(board.D9)
    cs.direction = digitalio.Direction.OUTPUT
    cs.value = True

    rst = digitalio.DigitalInOut(board.D10)
    rst.direction = digitalio.Direction.OUTPUT

    return cs, rst


def init_battery_monitor():
    """Initialize battery monitor - tries MAX17048 first, then LC709203F."""
    try:
        import adafruit_max1704x
        import adafruit_lc709203f

        i2c = board.I2C()
        try:
            monitor = adafruit_max1704x.MAX17048(i2c)
            return monitor, "MAX17048"
        except ValueError:
            try:
                monitor = adafruit_lc709203f.LC709203F(i2c)
                monitor.thermistor_bconstant = 3950
                monitor.pack_size = adafruit_lc709203f.PackSize.MAH500
                return monitor, "LC709203F"
            except ValueError:
                return None, None
    except Exception as e:
        return None, None


def read_battery(monitor):
    """Read battery percentage. Returns 255 if unavailable."""
    if monitor is None:
        return 255
    try:
        return max(0, min(100, int(monitor.cell_percent)))
    except Exception:
        return 255
