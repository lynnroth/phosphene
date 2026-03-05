import os
import board


def load_config():
    """Load configuration from environment (settings.toml)."""

    dev_id = os.getenv("DEVICE_ID")
    if dev_id is None:
        print(
            "ERROR: DEVICE_ID not set in settings.toml — defaulting to 1. "
            "Set DEVICE_ID = 1 (or 2-5) in CIRCUITPY/settings.toml."
        )
        dev_id = "1"
    device_id = int(dev_id)

    num_pixels = int(os.getenv("NUM_PIXELS", "40"))
    neopixel_pin = getattr(board, os.getenv("NEOPIXEL_PIN", "D5"))

    wifi_sim_enabled = os.getenv("WIFI_SIM_ENABLED", "1") != "0"
    wifi_sim_network = os.getenv("WIFI_SIM_NETWORK", "ap")
    wifi_sim_port = 5569

    status_led_enabled = os.getenv("STATUS_LED_ENABLED", "1") != "0"
    status_led_brightness = int(os.getenv("STATUS_LED_BRIGHTNESS", "30"))

    boost_en_pin = os.getenv("BOOST_EN_PIN")
    radio_en_pin = os.getenv("RADIO_EN_PIN")

    lora_freq = 915.0
    lora_sf = 7
    lora_bw = 250000
    lora_cr = 5
    lora_tx_power = 13

    dedup_window = 1.0

    return {
        "device_id": device_id,
        "num_pixels": num_pixels,
        "neopixel_pin": neopixel_pin,
        "wifi_sim_enabled": wifi_sim_enabled,
        "wifi_sim_network": wifi_sim_network,
        "wifi_sim_port": wifi_sim_port,
        "status_led_enabled": status_led_enabled,
        "status_led_brightness": status_led_brightness,
        "boost_en_pin": boost_en_pin,
        "radio_en_pin": radio_en_pin,
        "lora_freq": lora_freq,
        "lora_sf": lora_sf,
        "lora_bw": lora_bw,
        "lora_cr": lora_cr,
        "lora_tx_power": lora_tx_power,
        "dedup_window": dedup_window,
    }
