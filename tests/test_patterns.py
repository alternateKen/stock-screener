"""Checks for scripts/patterns.py on synthetic price paths with textbook shapes."""
import os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import patterns as P  # noqa: E402
import screen  # noqa: E402


def path(points, noise=0.002, seed=1):
    """Piecewise-linear closes through (bars, price) waypoints, with a little noise."""
    random.seed(seed)
    out = [points[0][1]]
    for (n0, p0), (n1, p1) in zip(points, points[1:]):
        for i in range(1, n1 - n0 + 1):
            out.append((p0 + (p1 - p0) * i / (n1 - n0)) * (1 + random.gauss(0, noise)))
    return out


def ohlc(c):
    return [x * 1.006 for x in c], [x * 0.994 for x in c]


def run(c):
    h, l = ohlc(c)
    ts = [1_700_000_000 + i * 86400 for i in range(len(c))]
    atr = screen.atr14(h, l, c)
    m50 = screen.sma_series(c, 50)
    m200 = screen.sma_series(c, 200)[-1]
    return P.structure(ts, h, l, c, atr, m50, m200)


class Patterns(unittest.TestCase):
    def kinds(self, c):
        f, sig = run(c)
        return {(p["k"], p["state"]) for p in f["pat"]}, f, sig

    def test_double_top_confirmed(self):
        c = path([(0, 60), (120, 100), (150, 85), (180, 100), (205, 80)])
        k, f, sig = self.kinds(c)
        self.assertIn(("dtop", "confirmed"), k)
        p = next(p for p in f["pat"] if p["k"] == "dtop")
        self.assertAlmostEqual(p["neck"], 85, delta=2)
        self.assertAlmostEqual(p["target"], 70, delta=4)

    def test_double_top_forming(self):
        c = path([(0, 60), (120, 100), (150, 85), (180, 100), (190, 92)])
        k, _, _ = self.kinds(c)
        self.assertIn(("dtop", "forming"), k)

    def test_double_bottom_confirmed(self):
        c = path([(0, 140), (120, 100), (150, 115), (180, 100), (205, 120)])
        k, _, sig = self.kinds(c)
        self.assertIn(("dbot", "confirmed"), k)
        self.assertTrue(any(s[0] == "dbot" and s[1] == 1 for s in sig))

    def test_head_and_shoulders(self):
        c = path([(0, 60), (100, 90), (120, 80), (140, 100), (160, 80), (180, 90), (200, 72)])
        k, _, _ = self.kinds(c)
        self.assertIn(("hs", "confirmed"), k)

    def test_inverse_head_and_shoulders(self):
        c = path([(0, 130), (100, 100), (120, 110), (140, 90), (160, 110), (180, 100), (200, 118)])
        k, _, _ = self.kinds(c)
        self.assertIn(("ihs", "confirmed"), k)

    def test_no_patterns_in_a_steady_trend(self):
        c = path([(0, 50), (250, 120)], noise=0.004)
        k, f, _ = self.kinds(c)
        self.assertFalse({x for x in k if x[0] in ("dtop", "hs")})
        self.assertEqual(f["trend"]["dir"], "up")

    def test_downtrend(self):
        c = path([(0, 120), (60, 105), (80, 112), (140, 90), (160, 97), (230, 70)])
        _, f, _ = self.kinds(c)
        self.assertEqual(f["trend"]["dir"], "down")
        self.assertIn("lower highs", f["trend"]["why"])

    def test_support_resistance(self):
        # a range: tops near 110, bottoms near 90, price now ~100
        c = path([(0, 100), (20, 110), (40, 90), (60, 110), (80, 90), (100, 110), (120, 90), (140, 100)])
        _, f, _ = self.kinds(c)
        self.assertTrue(f["sr"]["res"] and abs(f["sr"]["res"][0]["p"] - 110.6) < 3)
        self.assertTrue(f["sr"]["sup"] and abs(f["sr"]["sup"][0]["p"] - 89.5) < 3)
        self.assertGreaterEqual(f["sr"]["res"][0]["n"], 2)

    def test_breakout(self):
        c = path([(0, 100), (20, 110), (40, 95), (60, 110), (80, 95), (100, 110), (120, 96), (138, 109), (141, 114)])
        _, _, sig = self.kinds(c)
        self.assertTrue(any(s[0] == "brku" for s in sig), sig)

    def test_adx(self):
        c = path([(0, 50), (100, 150)], noise=0.001)
        h, l = ohlc(c)
        self.assertGreater(P.adx14(h, l, c), 25)
        r = path([(0, 100), (10, 104), (20, 100), (30, 104), (40, 100), (50, 104), (60, 100), (70, 104), (80, 100)], noise=0.003)
        h, l = ohlc(r)
        self.assertLess(P.adx14(h, l, r), 25)

    def test_random_walks_rarely_flag(self):
        flagged = 0
        for seed in range(40):
            random.seed(seed)
            c = [100.0]
            for _ in range(300):
                c.append(c[-1] * (1 + random.gauss(0, 0.015)))
            k, f, _ = self.kinds(c)
            flagged += len(k)
            self.assertIn(f["trend"]["dir"], ("up", "down", "side"))
        self.assertLess(flagged / 40, 1.5)   # patterns should be the exception, not the rule


if __name__ == "__main__":
    unittest.main()
