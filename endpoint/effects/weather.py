import random
from . import Effect, Rainbow, scale_color, hsv_to_rgb


class RainbowEffect(Rainbow):
    """Full rainbow cycles across the strip."""

    def update(self, pixels, r, g, b, intensity, speed):
        step = speed_to_rate(speed, 0.001, 0.02)
        self.offset = (self.offset + step) % 1.0

        scale = intensity / 255.0
        for i in range(self.num_pixels):
            hue = (self.offset + i / self.num_pixels) % 1.0
            rgb = hsv_to_rgb(hue, 1.0, scale)
            pixels[i] = rgb

        pixels.show()


class Lightning(Effect):
    """Random white flashes of varying brightness and duration against a dark sky."""

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
    """Northern lights: slow drifting hues create an organic, dreamy atmosphere."""

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
