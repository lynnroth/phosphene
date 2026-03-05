import random
from . import Effect, Fire, scale_color


class FireEffect(Fire):
    """Fire simulation using per-pixel heat values."""

    def update(self, pixels, r, g, b, intensity, speed):
        cooling = int(speed_to_rate(speed, 80, 30))
        sparking = int(speed_to_rate(speed, 40, 120))

        for i in range(self.num_pixels):
            cooldown = random.randint(0, ((cooling * 10) // self.num_pixels) + 2)
            self.heat[i] = max(0, self.heat[i] - cooldown)

        for i in range(self.num_pixels - 1, 1, -1):
            self.heat[i] = (self.heat[i - 1] + self.heat[i - 2] + self.heat[i - 2]) // 3

        if random.randint(0, 255) < sparking:
            y = random.randint(0, min(7, self.num_pixels - 1))
            self.heat[y] = min(255, self.heat[y] + random.randint(160, 255))

        scale = intensity / 255.0
        for i in range(self.num_pixels):
            h = self.heat[i]
            if h < 85:
                pixel_r = h * 3
                pixel_g = 0
                pixel_b = 0
            elif h < 170:
                pixel_r = 255
                pixel_g = (h - 85) * 3
                pixel_b = 0
            else:
                pixel_r = 255
                pixel_g = 255
                pixel_b = (h - 170) * 3

            blend = r / 255.0
            pixel_r = int((pixel_r * blend + pixel_r * (1 - blend)) * scale)
            pixel_g = int(pixel_g * (g / 255.0) * scale)
            pixel_b = int(pixel_b * (b / 255.0) * scale)
            pixels[i] = (pixel_r, pixel_g, pixel_b)

        pixels.show()


class Campfire(Fire):
    """Softer fire, cooler and more amber."""

    def update(self, pixels, r, g, b, intensity, speed):
        cooling = int(speed_to_rate(speed, 100, 50))
        sparking = int(speed_to_rate(speed, 25, 80))

        for i in range(self.num_pixels):
            cooldown = random.randint(0, ((cooling * 10) // self.num_pixels) + 2)
            self.heat[i] = max(0, self.heat[i] - cooldown)

        for i in range(self.num_pixels - 1, 1, -1):
            self.heat[i] = (self.heat[i - 1] + self.heat[i - 2] + self.heat[i - 2]) // 3

        if random.randint(0, 255) < sparking:
            y = random.randint(0, min(5, self.num_pixels - 1))
            self.heat[y] = min(200, self.heat[y] + random.randint(100, 200))

        scale = intensity / 255.0
        for i in range(self.num_pixels):
            h = self.heat[i]
            if h < 85:
                pixel_r = h * 3
                pixel_g = h
                pixel_b = 0
            elif h < 170:
                pixel_r = 255
                pixel_g = 85 + (h - 85) * 2
                pixel_b = 0
            else:
                pixel_r = 255
                pixel_g = 200
                pixel_b = h - 170
            pixels[i] = (
                int(pixel_r * scale),
                int(pixel_g * scale * 0.6),
                int(pixel_b * scale * 0.2),
            )

        pixels.show()


def speed_to_rate(speed_byte, slow_val, fast_val):
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)
