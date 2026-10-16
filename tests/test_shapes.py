"""Checks for scripts/shapes.py: triangles, wedges, flags / pennants, rounding bottom, cup and handle."""
import math, os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_patterns import path, run  # noqa: E402


def zig(start, n_legs, top, bot, leg=10, x0=0):
    """Waypoints bouncing between two lines top(i) and bot(i)."""
    pts, x, up = [(x0, start)], x0, True
    for _ in range(n_legs):
        x += leg
        pts.append((x, top(x) if up else bot(x)))
        up = not up
    return pts


def kinds(c, vols=None):
    f, sig = run(c, vols)
    return {(p["k"], p["state"]) for p in f["pat"]}, f


class Shapes(unittest.TestCase):
    def test_ascending_triangle(self):
        pre = [(0, 70), (60, 95)]
        legs = zig(95, 8, lambda x: 110, lambda x: 95 + (x - 60) * 0.17, leg=10, x0=60)
        k, f = kinds(path(pre + legs[1:] + [(legs[-1][0] + 4, 107)]))
        self.assertIn("tria", {x[0] for x in k}, k)

    def test_ascending_triangle_breakout(self):
        pre = [(0, 70), (60, 95)]
        legs = zig(95, 8, lambda x: 110, lambda x: 95 + (x - 60) * 0.17, leg=10, x0=60)
        k, _ = kinds(path(pre + legs[1:] + [(legs[-1][0] + 6, 116)]))
        self.assertIn(("tria", "confirmed"), k)

    def test_descending_triangle(self):
        pre = [(0, 130), (60, 115)]
        legs = zig(115, 8, lambda x: 115 - (x - 60) * 0.17, lambda x: 100, leg=10, x0=60)
        k, _ = kinds(path(pre + legs[1:] + [(legs[-1][0] + 4, 103)]))
        self.assertIn("trid", {x[0] for x in k}, k)

    def test_symmetrical_triangle(self):
        pre = [(0, 80), (60, 100)]
        legs = zig(100, 8, lambda x: 120 - (x - 60) * 0.15, lambda x: 90 + (x - 60) * 0.15, leg=10, x0=60)
        k, _ = kinds(path(pre + legs[1:] + [(legs[-1][0] + 4, 106)]))
        self.assertIn("tris", {x[0] for x in k}, k)

    def test_rising_wedge(self):
        pre = [(0, 70), (60, 90)]
        legs = zig(90, 8, lambda x: 100 + (x - 60) * 0.25, lambda x: 90 + (x - 60) * 0.34, leg=10, x0=60)
        k, _ = kinds(path(pre + legs[1:] + [(legs[-1][0] + 4, 118.5)]))
        self.assertIn("wedr", {x[0] for x in k}, k)

    def test_falling_wedge(self):
        pre = [(0, 140), (60, 120)]
        legs = zig(120, 8, lambda x: 120 - (x - 60) * 0.34, lambda x: 110 - (x - 60) * 0.25, leg=10, x0=60)
        k, _ = kinds(path(pre + legs[1:] + [(legs[-1][0] + 4, 91.5)]))
        self.assertIn("wedf", {x[0] for x in k}, k)

    def test_bull_flag(self):
        c = path([(0, 80), (120, 82), (130, 100), (134, 98), (137, 99.5), (140, 97.5), (143, 98.5), (145, 97)], noise=0.001)
        k, f = kinds(c)
        self.assertIn(("flagu", "forming"), k)
        c2 = path([(0, 80), (120, 82), (130, 100), (134, 98), (137, 99.5), (140, 97.5), (143, 98.5), (145, 97), (147, 103)], noise=0.001)
        self.assertIn(("flagu", "confirmed"), kinds(c2)[0])

    def test_bear_flag(self):
        c = path([(0, 120), (120, 118), (130, 100), (134, 102), (137, 100.5), (140, 102.5), (143, 101.5), (145, 103)], noise=0.001)
        self.assertIn("flagd", {x[0] for x in kinds(c)[0]})

    def test_rounding_bottom(self):
        c = [150.0] * 40 + [100 + 50 * ((i - 100) / 100) ** 2 for i in range(0, 175)]
        random.seed(3)
        c = [x * (1 + random.gauss(0, 0.003)) for x in c]
        k, _ = kinds(c)
        self.assertIn("rbot", {x[0] for x in k}, k)

    def test_cup_and_handle(self):
        cup = [(0, 70), (40, 100)] + [(40 + i * 10, 100 - 25 * math.sin(math.pi * i / 10)) for i in range(1, 11)]
        c = path(cup + [(110, 99), (118, 94), (124, 96)], noise=0.002)
        k, f = kinds(c)
        self.assertIn(("cup", "forming"), k, k)
        c2 = path(cup + [(110, 99), (118, 94), (124, 96), (128, 104)], noise=0.002)
        self.assertIn(("cup", "confirmed"), kinds(c2)[0])

    def test_random_walk_rate(self):
        total = 0
        for seed in range(60):
            random.seed(seed)
            c = [100.0]
            for _ in range(500):
                c.append(c[-1] * (1 + random.gauss(0, 0.018)))
            k, _ = kinds(c)
            total += len([x for x in k if x[0] in ("tria", "trid", "tris", "wedr", "wedf", "flagu", "flagd", "rbot", "cup")])
        self.assertLess(total / 60, 0.6)


if __name__ == "__main__":
    unittest.main()
