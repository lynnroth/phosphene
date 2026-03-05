import math
import random
from . import Effect, Rainbow, scale_color, hsv_to_rgb


class Wave(Rainbow):
    """A smooth sine wave of brightness rolls down the strip."""

    def update(self, pixels, r, g, b, intensity, speed):
        step = speed_to_rate(speed, 0.02, 0.3)
        self.offset = (self.offset + step) % (2 * math.pi)

        r, g, b = scale_color(r, g, b, intensity)

        for i in range(self.num_pixels):
            phase = self.offset + (i / self.num_pixels) * 2 * math.pi
            lvl = (math.sin(phase) + 1.0) / 2.0
            pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

        pixels.show()


class WavePastel(Rainbow):
    """Rainbow hues with traveling sine wave, saturation follows brightness."""

    def reset(self):
        self.offset = 0.0
        self.hue_offset = 0.0

    def update(self, pixels, r, g, b, intensity, speed):
        step = speed_to_rate(speed, 0.02, 0.3)
        self.offset = (self.offset + step) % (2 * math.pi)
        self.hue_offset = (self.hue_offset + step * 0.05) % 1.0

        scale = intensity / 255.0

        for i in range(self.num_pixels):
            hue = (self.hue_offset + i / self.num_pixels) % 1.0
            phase = self.offset + (i / self.num_pixels) * 2 * math.pi
            lvl = (math.sin(phase) + 1.0) / 2.0
            sat = lvl * 0.6
            val = (0.35 + lvl * 0.65) * scale
            rgb = hsv_to_rgb(hue, sat, val)
            pixels[i] = rgb

        pixels.show()


class Comet(Rainbow):
    """A bright comet with a tapering tail shoots across the strip and loops."""

    def reset(self):
        self.position = 0.0
        self.tick = 0

    def update(self, pixels, r, g, b, intensity, speed):
        tail_length = max(4, self.num_pixels // 6)
        ticks_per_step = max(1, int(speed_to_rate(speed, 8, 1)))

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.position = (self.position + 1) % self.num_pixels
            self.tick = 0

        pixels.fill((0, 0, 0))
        r, g, b = scale_color(r, g, b, intensity)

        for i in range(tail_length):
            idx = int(self.position - i) % self.num_pixels
            brightness = (1.0 - (i / tail_length)) ** 2
            pixels[idx] = (
                int(r * brightness),
                int(g * brightness),
                int(b * brightness),
            )

        pixels.show()


class ColorWipe(Effect):
    """Pixels fill in one by one from one end, then clear from one end."""

    def reset(self):
        self.position = 0
        self.tick = 0

    def update(self, pixels, r, g, b, intensity, speed):
        ticks_per_step = max(1, int(speed_to_rate(speed, 30, 1)))
        self.tick += 1
        if self.tick >= ticks_per_step:
            self.tick = 0
            self.position += 1
            if self.position > self.num_pixels * 2:
                self.position = 0

        r, g, b = scale_color(r, g, b, intensity)

        if self.position <= self.num_pixels:
            for i in range(self.num_pixels):
                pixels[i] = (r, g, b) if i < self.position else (0, 0, 0)
        else:
            clear_pos = self.position - self.num_pixels
            for i in range(self.num_pixels):
                pixels[i] = (0, 0, 0) if i < clear_pos else (r, g, b)

        pixels.show()


def speed_to_rate(speed_byte, slow_val, fast_val):
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)
