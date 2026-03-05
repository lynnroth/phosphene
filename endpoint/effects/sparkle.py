import random
from . import Effect, Sparkle, scale_color


class SparkleEffect(Sparkle):
    """Random pixels flash bright, rest stay dark."""

    def update(self, pixels, r, g, b, intensity, speed):
        r, g, b = scale_color(r, g, b, intensity)

        num_sparkles = max(1, int(speed_to_rate(speed, 1, self.num_pixels * 0.2)))
        fade_factor = speed_to_rate(speed, 0.85, 0.5)

        for i in range(self.num_pixels):
            pr, pg, pb = pixels[i]
            pixels[i] = (
                int(pr * fade_factor),
                int(pg * fade_factor),
                int(pb * fade_factor),
            )

        for _ in range(num_sparkles):
            idx = random.randint(0, self.num_pixels - 1)
            pixels[idx] = (r, g, b)

        pixels.show()


class Twinkle(Sparkle):
    """Each pixel has its own independent brightness that slowly wanders."""

    def reset(self):
        self.levels = [0.0] * self.num_pixels
        self.speeds = [random.uniform(0.01, 0.05) for _ in range(self.num_pixels)]
        self.targets = [random.uniform(0.2, 1.0) for _ in range(self.num_pixels)]

    def update(self, pixels, r, g, b, intensity, speed):
        r, g, b = scale_color(r, g, b, intensity)
        speed_factor = speed_to_rate(speed, 0.3, 3.0)

        for i in range(self.num_pixels):
            diff = self.targets[i] - self.levels[i]
            self.levels[i] += diff * self.speeds[i] * speed_factor

            if abs(diff) < 0.02:
                self.targets[i] = random.uniform(0.2, 1.0)
                self.speeds[i] = random.uniform(0.01, 0.06)

            lvl = self.levels[i]
            pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

        pixels.show()


class Confetti(Sparkle):
    """Random pixels light up in random colors, constantly refreshing."""

    def reset(self):
        self.tick = 0
        self.levels = [0.0] * self.num_pixels
        self.targets = [0.0] * self.num_pixels
        self.speeds = [0.0] * self.num_pixels

    def update(self, pixels, r, g, b, intensity, speed):
        from . import hsv_to_rgb

        spawn_rate = max(1, int(speed_to_rate(speed, 1, 8)))

        for i in range(self.num_pixels):
            pr, pg, pb = pixels[i]
            pixels[i] = (int(pr * 0.92), int(pg * 0.92), int(pb * 0.92))

        for _ in range(spawn_rate):
            idx = random.randint(0, self.num_pixels - 1)
            hue = random.random()
            rgb = hsv_to_rgb(hue, 1.0, intensity / 255.0)
            pixels[idx] = rgb

        pixels.show()
        self.tick += 1


class Bubbles(Sparkle):
    """Random pixels bloom up from darkness and pop, like bubbles rising."""

    def reset(self):
        self.levels = [0.0] * self.num_pixels
        self.targets = [0.0] * self.num_pixels
        self.speeds = [0.0] * self.num_pixels

    def update(self, pixels, r, g, b, intensity, speed):
        r, g, b = scale_color(r, g, b, intensity)
        speed_factor = speed_to_rate(speed, 0.3, 3.0)
        spawn_chance = speed_to_rate(speed, 0.01, 0.15)

        for i in range(self.num_pixels):
            diff = self.targets[i] - self.levels[i]
            if self.speeds[i] > 0:
                self.levels[i] += diff * self.speeds[i] * speed_factor

            if self.targets[i] > 0.5 and abs(diff) < 0.05:
                self.targets[i] = 0.0
                self.speeds[i] = random.uniform(0.08, 0.25)

            if self.levels[i] < 0.02 and self.targets[i] < 0.1:
                if random.random() < spawn_chance:
                    self.targets[i] = random.uniform(0.6, 1.0)
                    self.speeds[i] = random.uniform(0.02, 0.08)

            lvl = max(0.0, self.levels[i])
            pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

        pixels.show()


class Flicker(Sparkle):
    """Like a bad fluorescent tube. Random intensity drops per pixel."""

    def reset(self):
        self.levels = [1.0] * self.num_pixels
        self.targets = [0.0] * self.num_pixels
        self.speeds = [0.0] * self.num_pixels

    def update(self, pixels, r, g, b, intensity, speed):
        r, g, b = scale_color(r, g, b, intensity)
        flicker_chance = speed_to_rate(speed, 0.02, 0.25)

        for i in range(self.num_pixels):
            if random.random() < flicker_chance:
                self.levels[i] = random.uniform(0.0, 1.0)
            else:
                self.levels[i] = min(1.0, self.levels[i] + 0.1)

            lvl = self.levels[i]
            pixels[i] = (int(r * lvl), int(g * lvl), int(b * lvl))

        pixels.show()


def speed_to_rate(speed_byte, slow_val, fast_val):
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)
