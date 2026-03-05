import random
from . import Effect, Simple, scale_color


class Solid(Simple):
    """Steady color at current intensity.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Overall brightness (0-255)
        speed: Ignored for solid effect
    """

    def update(self, pixels, r, g, b, intensity, speed):
        r, g, b = scale_color(r, g, b, intensity)
        pixels.fill((r, g, b))
        pixels.show()


class Fade(Effect):
    """Whole strip breathes in and out between full color and black.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls breath cycle time (0=slow, 255=fast)
    """

    def reset(self):
        self.direction = 1
        self.level = 0.0

    def update(self, pixels, r, g, b, intensity, speed):
        step = speed_to_rate(speed, 0.003, 0.05)
        self.level += step * self.direction
        if self.level >= 1.0:
            self.level = 1.0
            self.direction = -1
        elif self.level <= 0.0:
            self.level = 0.0
            self.direction = 1

        eff_int = int(intensity * self.level)
        r, g, b = scale_color(r, g, b, eff_int)
        pixels.fill((r, g, b))
        pixels.show()


class Strobe(Simple):
    """Hard on/off flash.

    Args:
        r, g, b: Color channels (0-255) - white is classic
        intensity: Peak brightness when on (0-255)
        speed: Controls flash rate (0=slow ~2Hz, 255=fast ~30Hz)
    """

    def reset(self):
        self.on = False
        self.tick = 0

    def update(self, pixels, r, g, b, intensity, speed):
        ticks_per_half = max(1, int(speed_to_rate(speed, 50, 2)))
        self.tick += 1
        if self.tick >= ticks_per_half:
            self.on = not self.on
            self.tick = 0

        if self.on:
            r, g, b = scale_color(r, g, b, intensity)
            pixels.fill((r, g, b))
        else:
            pixels.fill((0, 0, 0))
        pixels.show()


class Heartbeat(Effect):
    """Double-pulse (lub-dub) that repeats.

    Looks great in red for a literal heartbeat, but works in any color
    for a dramatic rhythmic pulse.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls BPM (0=slow, 255=fast)
    """

    def reset(self):
        self.phase = 0.0

    def update(self, pixels, r, g, b, intensity, speed):
        import math

        bpm_rate = speed_to_rate(speed, 0.008, 0.04)
        self.phase = (self.phase + bpm_rate) % 1.0

        p = self.phase
        if p < 0.08:
            lvl = math.sin(p / 0.08 * math.pi)
        elif p < 0.18:
            lvl = math.sin((p - 0.1) / 0.08 * math.pi) * 0.7
        else:
            lvl = 0.0

        lvl = max(0.0, lvl)
        eff_int = int(intensity * lvl)
        r, g, b = scale_color(r, g, b, eff_int)
        pixels.fill((r, g, b))
        pixels.show()


class Alarm(Simple):
    """Fast two-color alternating flash.

    Great for warnings, emergencies, sirens. Alternates between the
    RGB color and its complement (R<->B flip).

    Args:
        r, g, b: Color channels (0-255) - e.g., red alarm alternates with blue
        intensity: Peak brightness (0-255)
        speed: Controls alternation rate (0=slow, 255=fast)
    """

    def reset(self):
        self.phase = False
        self.tick = 0

    def update(self, pixels, r, g, b, intensity, speed):
        ticks_per_half = max(1, int(speed_to_rate(speed, 30, 2)))
        self.tick += 1
        if self.tick >= ticks_per_half:
            self.phase = not self.phase
            self.tick = 0

        if self.phase:
            r, g, b = scale_color(r, g, b, intensity)
        else:
            r, g, b = scale_color(b, g, r, intensity)

        pixels.fill((r, g, b))
        pixels.show()


class ColorWipe(Effect):
    """Pixels fill in one by one from one end, then clear from one end.

    Great for slow reveals.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls wipe rate (0=slow, 255=fast)
    """

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


class Ripple(Effect):
    """A brightness pulse expands outward from the center of the strip.

    Concentric pulses expand outward from center.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls pulse speed (0=slow, 255=fast)
    """

    def reset(self):
        self.pos = 0
        self.tick = 0

    def update(self, pixels, r, g, b, intensity, speed):
        width = max(3, self.num_pixels // 8)
        ticks_per_step = max(1, int(speed_to_rate(speed, 8, 1)))

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.pos += 1
            self.tick = 0
            if self.pos > self.num_pixels // 2 + width:
                self.pos = 0

        center = self.num_pixels // 2
        r, g, b = scale_color(r, g, b, intensity)
        pixels.fill((0, 0, 0))

        for i in range(self.num_pixels):
            dist = abs(i - center)
            ripple_dist = abs(dist - self.pos)
            if ripple_dist < width:
                brightness = 1.0 - (ripple_dist / width)
                brightness = brightness**2
                pixels[i] = (
                    int(r * brightness),
                    int(g * brightness),
                    int(b * brightness),
                )

        pixels.show()


def speed_to_rate(speed_byte, slow_val, fast_val):
    """Map speed byte (0-255) to a rate value between slow_val and fast_val."""
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)
