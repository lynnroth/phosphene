import random
from . import Effect, Rainbow, scale_color, hsv_to_rgb


class RainbowEffect(Rainbow):
    """Full rainbow cycles across the strip.

    Args:
        r, g, b: Ignored - cycles through full hue spectrum
        intensity: Peak brightness (0-255)
        speed: Controls rotation rate (0=slow, 255=fast)
    """


class Lightning(Effect):
    """Random white flashes of varying brightness and duration against a dark sky.

    Args:
        r, g, b: Color channels (0-255) - tints the lightning (white=255,255,255)
        intensity: Peak flash brightness (0-255)
        speed: Controls how frequently strikes happen (0=rare, 255=frequent)
    """

    def reset(self):
        self.on = False
        self.timer = 0
        self.next = random.randint(10, 60)

    def update(self, pixels, r, g, b, intensity, speed):
        self.timer += 1

        if not self.on:
            if self.timer >= self.next:
                self.on = True
                self.timer = 0
                self.next = random.randint(1, random.randint(3, 8))
                flash_level = random.uniform(0.4, 1.0)
                r, g, b = scale_color(r, g, b, intensity)
                r = int(r * flash_level)
                g = int(g * flash_level)
                b = int(b * flash_level)
                pixels.fill((r, g, b))
                pixels.show()
        else:
            if self.timer >= self.next:
                self.on = False
                pixels.fill((0, 0, 0))
                pixels.show()
                self.timer = 0
                min_wait = int(speed_to_rate(speed, 200, 10))
                max_wait = int(speed_to_rate(speed, 500, 40))
                if random.randint(0, 3) == 0:
                    self.next = random.randint(2, 6)
                else:
                    self.next = random.randint(min_wait, max_wait)


class Aurora(Effect):
    """Northern lights: slow drifting hues create an organic, dreamy atmosphere.

    Args:
        r, g, b: Ignored - uses drifting hues
        intensity: Peak brightness (0-255)
        speed: Controls drift rate (0=slow, 255=fast)
    """

    def reset(self):
        self.hues = [random.random() for _ in range(self.num_pixels)]

    def update(self, pixels, r, g, b, intensity, speed):
        drift = speed_to_rate(speed, 0.0005, 0.008)
        scale = intensity / 255.0

        for i in range(self.num_pixels):
            self.hues[i] = (self.hues[i] + drift + random.uniform(-0.003, 0.003)) % 1.0
            rgb = hsv_to_rgb(self.hues[i], 0.6, scale)
            pixels[i] = rgb

        pixels.show()


def speed_to_rate(speed_byte, slow_val, fast_val):
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)
