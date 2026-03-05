from . import Effect, Chase, scale_color


class ChaseEffect(Chase):
    """A moving block of lit pixels travels along the strip.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls travel rate (0=slow, 255=fast)
    """

    def update(self, pixels, r, g, b, intensity, speed):
        length = max(3, self.num_pixels // 8)
        ticks_per_step = max(1, int(speed_to_rate(speed, 20, 1)))

        r, g, b = scale_color(r, g, b, intensity)
        dr, dg, db = r // 8, g // 8, b // 8

        pixels.fill((0, 0, 0))
        for i in range(self.num_pixels):
            dist = (i - self.position) % self.num_pixels
            if dist < length:
                taper = 1.0 - (dist / length) * 0.7
                pixels[i] = (int(r * taper), int(g * taper), int(b * taper))
            elif dist == length:
                pixels[i] = (dr, dg, db)

        pixels.show()

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.position = (self.position + 1) % self.num_pixels
            self.tick = 0


class Marquee(Chase):
    """Classic theater marquee: every Nth pixel lit, block scrolls.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls scroll rate (0=slow, 255=fast)
    """

    def update(self, pixels, r, g, b, intensity, speed):
        spacing = 3
        ticks_per_step = max(1, int(speed_to_rate(speed, 20, 1)))

        r, g, b = scale_color(r, g, b, intensity)
        dr, dg, db = r // 12, g // 12, b // 12

        for i in range(self.num_pixels):
            if (i + self.position) % spacing == 0:
                pixels[i] = (r, g, b)
            else:
                pixels[i] = (dr, dg, db)

        pixels.show()

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.position = (self.position + 1) % spacing
            self.tick = 0


class TheaterChase(Chase):
    """Classic theater chase: every 3rd pixel lit, offset advances each step.

    Like marquee but with a dim background fill.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls chase rate (0=slow, 255=fast)
    """

    def update(self, pixels, r, g, b, intensity, speed):
        spacing = 3
        ticks_per_step = max(1, int(speed_to_rate(speed, 15, 1)))

        r, g, b = scale_color(r, g, b, intensity)
        bg_r, bg_g, bg_b = r // 6, g // 6, b // 6

        for i in range(self.num_pixels):
            if (i + self.position) % spacing == 0:
                pixels[i] = (r, g, b)
            else:
                pixels[i] = (bg_r, bg_g, bg_b)

        pixels.show()

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.position = (self.position + 1) % spacing
            self.tick = 0


class RainbowChase(Chase):
    """Every-third-pixel marquee using rainbow colors.

    Args:
        r, g, b: Ignored - hues cycle through full spectrum
        intensity: Peak brightness (0-255)
        speed: Controls chase rate (0=slow, 255=fast)
    """

    def update(self, pixels, r, g, b, intensity, speed):
        from . import hsv_to_rgb

        spacing = 3
        ticks_per_step = max(1, int(speed_to_rate(speed, 15, 1)))

        scale = intensity / 255.0

        for i in range(self.num_pixels):
            if (i + self.position) % spacing == 0:
                hue = (i / self.num_pixels + self.offset) % 1.0
                rgb = hsv_to_rgb(hue, 1.0, scale)
                pixels[i] = rgb
            else:
                pixels[i] = (0, 0, 0)

        pixels.show()

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.position = (self.position + 1) % spacing
            self.offset = (self.offset + 0.1) % 1.0
            self.tick = 0


class Scanner(Chase):
    """Cylon/Knight Rider eye: a bright segment bounces back and forth.

    Args:
        r, g, b: Color channels (0-255)
        intensity: Peak brightness (0-255)
        speed: Controls travel speed (0=slow, 255=fast)
    """

    def reset(self):
        self.position = 0
        self.direction = 1
        self.tick = 0

    def update(self, pixels, r, g, b, intensity, speed):
        width = max(3, self.num_pixels // 10)
        ticks_per_step = max(1, int(speed_to_rate(speed, 10, 1)))

        r, g, b = scale_color(r, g, b, intensity)
        pixels.fill((0, 0, 0))

        for i in range(width):
            idx = self.position + i
            if 0 <= idx < self.num_pixels:
                dist_from_center = abs(i - width // 2)
                brightness = 1.0 - (dist_from_center / (width / 2)) * 0.7
                pixels[idx] = (
                    int(r * brightness),
                    int(g * brightness),
                    int(b * brightness),
                )

        trail_len = width * 2
        for i in range(1, trail_len):
            ghost_idx = self.position - (i * self.direction)
            if 0 <= ghost_idx < self.num_pixels:
                fade = max(0.0, 1.0 - i / trail_len) * 0.15
                pixels[ghost_idx] = (int(r * fade), int(g * fade), int(b * fade))

        pixels.show()

        self.tick += 1
        if self.tick >= ticks_per_step:
            self.position += self.direction
            self.tick = 0
            if self.position >= self.num_pixels - width:
                self.direction = -1
            elif self.position <= 0:
                self.direction = 1


def speed_to_rate(speed_byte, slow_val, fast_val):
    t = speed_byte / 255.0
    return slow_val + t * (fast_val - slow_val)
