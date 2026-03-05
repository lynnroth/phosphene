import math


class Effect:
    """Base class for all LED effects."""

    def __init__(self, num_pixels):
        self.num_pixels = num_pixels
        self.reset()

    def reset(self):
        """Reset animation state. Called on preset change."""
        pass

    def update(self, pixels, r, g, b, intensity, speed):
        """Called every frame. Override in subclass."""
        raise NotImplementedError


class Simple(Effect):
    """Stateless effects - no per-frame state needed."""

    def update(self, pixels, r, g, b, intensity, speed):
        pass


class Chase(Effect):
    """Base for effects with position/tick state."""

    def reset(self):
        self.position = 0
        self.tick = 0


class Fire(Effect):
    """Base for fire simulation effects."""

    def reset(self):
        self.heat = [0] * self.num_pixels


class Sparkle(Effect):
    """Base for random/pixel effects."""

    def reset(self):
        self.levels = [0.0] * self.num_pixels
        self.targets = [0.0] * self.num_pixels
        self.speeds = [0.0] * self.num_pixels
        for i in range(self.num_pixels):
            self.speeds[i] = 0.02
            self.targets[i] = 1.0


class Rainbow(Effect):
    """Base for hue-cycling effects."""

    def reset(self):
        self.offset = 0.0


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
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return (int(r * 255), int(g * 255), int(b * 255))


def scale_color(r, g, b, intensity):
    """Scale an RGB color by an intensity value (0-255)."""
    scale = intensity / 255.0
    return (int(r * scale), int(g * scale), int(b * scale))


# Import all effect classes and build registry
from .simple import Solid, Fade, Strobe, Heartbeat, Alarm, ColorWipe, Ripple
from .chase import (
    ChaseEffect,
    Marquee,
    TheaterChase,
    RainbowChase as ChaseRainbow,
    Scanner,
)
from .sparkle import SparkleEffect, Twinkle, Candle, Confetti, Bubbles, Flicker
from .fire import FireEffect, Campfire
from .weather import RainbowEffect, Lightning, Aurora
from .wave import Wave, WavePastel, Comet, ColorWipe as WaveWipe


EFFECTS = {
    0: Solid,  # Blackout - handled specially
    1: SparkleEffect,
    2: ChaseEffect,
    3: Fade,
    4: Solid,
    5: Twinkle,
    6: Strobe,
    7: Comet,
    8: FireEffect,
    9: RainbowEffect,
    10: Lightning,
    11: Marquee,
    12: Candle,
    13: ColorWipe,
    14: Heartbeat,
    15: Alarm,
    16: Comet,
    17: Ripple,
    18: Scanner,
    19: Bubbles,
    20: Campfire,
    21: Confetti,
    22: Wave,
    23: Flicker,
    24: TheaterChase,
    25: ChaseRainbow,
    26: Aurora,
    27: WavePastel,
}
