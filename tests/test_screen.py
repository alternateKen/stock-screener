"""Offline checks for scripts/screen.py (no network). Run: python -m unittest discover -s tests -v"""
import math, os, random, sys, tempfile, unittest, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import screen  # noqa: E402


def bars(closes, vols=None, start=1_700_000_000):
    n = len(closes)
    return {"t": [start + i * 86400 for i in range(n)], "c": closes, "h": [c * 1.01 for c in closes],
            "l": [c * 0.99 for c in closes], "v": vols or [1_000_000] * n, "last": closes[-1], "time": start + (n - 1) * 86400}


class Indicators(unittest.TestCase):
    def test_sma_ema(self):
        xs = list(range(1, 31))
        self.assertEqual(screen.sma(xs, 10), sum(range(21, 31)) / 10)
        e = screen.ema_series(xs, 10)
        self.assertIsNone(e[8])
        self.assertAlmostEqual(e[9], 5.5)
        self.assertAlmostEqual(e[10], 11 * 2 / 11 + 5.5 * 9 / 11)

    def test_rsi_extremes(self):
        self.assertEqual(screen.rsi14([float(i) for i in range(1, 40)]), 100.0)
        self.assertLess(screen.rsi14([float(i) for i in range(40, 1, -1)]), 1)

    def test_macd_constant_is_zero(self):
        line, sig = screen.macd([10.0] * 60)
        self.assertAlmostEqual(line[-1], 0)
        self.assertAlmostEqual(sig[-1], 0)
        self.assertIsNone(sig[30])   # signal needs 26 + 9 - 1 bars
        self.assertIsNotNone(sig[33])

    def test_atr(self):
        c = [100.0] * 30
        self.assertAlmostEqual(screen.atr14([101.0] * 30, [99.0] * 30, c), 2.0)

    def test_crossed(self):
        self.assertEqual(screen.crossed([1, 1, 3], [2, 2, 2], 3), 0)
        self.assertEqual(screen.crossed([1, 3, 3], [2, 2, 2], 3), 1)
        self.assertEqual(screen.crossed([3, 3, 1], [2, 2, 2], 3), -1)
        self.assertIsNone(screen.crossed([1, 3, 3, 3, 3], [2, 2, 2, 2, 2], 3))


class Signals(unittest.TestCase):
    def test_new_high_and_200d_reclaim(self):
        closes = [100 - i * 0.1 for i in range(240)] + [76 + i * 3 for i in range(12)]
        r = screen.analyse(bars(closes), {"m1": 0, "m3": 0})
        keys = {s["k"] for s in r["signals"]}
        self.assertIn("rsi70", keys)
        r2 = screen.analyse(bars([50.0] * 250 + [49.0, 60.0]), {"m1": 0, "m3": 0})
        keys2 = {s["k"] for s in r2["signals"]}
        self.assertIn("hi52", keys2)
        self.assertIn("x200u", keys2)
        self.assertIn("x50u", keys2)

    def test_volume_surge_and_low(self):
        vols = [1_000_000] * 251 + [3_000_000]
        r = screen.analyse(bars([50.0] * 251 + [40.0], vols), None)
        keys = {s["k"]: s["d"] for s in r["signals"]}
        self.assertEqual(keys.get("vol"), -1)
        self.assertEqual(keys.get("lo52"), -1)
        self.assertIsNone(r["score"])   # no S&P reference -> no full score

    def test_score_range(self):
        random.seed(1)
        c = [100.0]
        for _ in range(260):
            c.append(c[-1] * (1 + random.gauss(0.001, 0.02)))
        r = screen.analyse(bars(c), {"m1": 1, "m3": 2})
        self.assertTrue(0 <= r["score"] <= 6)
        for k in ("pct", "w1", "m1", "m3", "ytd", "rsi", "macd", "atr_pct", "vol_x", "rs1", "rs3", "ema9", "ema21", "ema50", "ema100", "ema200",
                  "wema9", "wema21", "ma100"):
            self.assertIsNotNone(r[k], k)
            self.assertFalse(math.isnan(r[k]), k)

    def test_weekly_bars(self):
        # Monday 2 Jan 2023 00:00 UTC, five sessions then the next Monday
        mon = 1_672_617_600
        ts = [mon + d * 86400 for d in range(5)] + [mon + 7 * 86400]
        c, h, l = [1.0, 2, 3, 4, 5, 6], [1.5, 2.5, 9, 4.5, 5.5, 6.5], [0.5, 1.5, 2.5, 0.1, 4.5, 5.5]
        self.assertEqual(screen.weekly(ts, c, h, l), ([5, 6], [9, 6.5], [0.1, 5.5]))
        # a Sydney Monday opens at 23:00 UTC on Sunday: it still belongs to Monday's week
        self.assertEqual(len(screen.weekly([mon - 3600, mon + 86400], [1, 2], [1, 2], [1, 2])[0]), 1)

    def test_ema_touch_rising_and_falling(self):
        up = [100.0 + i * 0.5 for i in range(1300)]   # five years of a steady climb: every EMA rising
        r = screen.analyse(bars(up), None)
        e21 = r["ema21"]
        b = bars(up[:-1] + [e21 * 1.005])   # the last day dips onto the 21-day EMA (its range 0.99-1.01x of the close)
        sig = {s["k"]: s for s in screen.analyse(b, None)["signals"]}
        self.assertIn("t21d", sig)
        self.assertEqual(sig["t21d"]["d"], 1)
        self.assertIn("rising", sig["t21d"]["t"])
        self.assertNotIn("t200d", sig)   # far below the price
        down = [800.0 - i * 0.5 for i in range(1300)]
        b = bars(down)
        b["t"] = [t for t in range(1_672_617_600, 1_672_617_600 + 3000 * 86400, 86400) if (t // 86400 + 3) % 7 < 5][:1300]   # weekdays only
        r = screen.analyse(b, None)
        sig = {s["k"]: s for s in screen.analyse(bars(down[:-1] + [r["ema9"] * 0.998]), None)["signals"]}
        self.assertEqual(sig["t9d"]["d"], -1)
        self.assertEqual(r["eslope"]["w200"], -1)
        self.assertIsNotNone(r["wema200"])   # five years = about 260 weeks, enough for the 200-week EMA

    def test_long_history_trimmed_but_emas_full(self):
        c = [100.0 + math.sin(i / 20) * 10 for i in range(1300)]
        r = screen.analyse(bars(c), None)
        self.assertAlmostEqual(r["ema200"], screen.ema_series(c, 200)[-1])
        self.assertEqual(len(r["spark"]), 45)
        cp = screen.chart_payload(bars(c))
        self.assertEqual(len(cp["c"]), screen.KEEP)
        # the chart continues the EMA from its seed and lands on the same value as the tables
        k, e = 2 / 201, cp["e"]["200"]
        for x in cp["c"]:
            e = x * k + e * (1 - k)
        self.assertAlmostEqual(e, r["ema200"], places=3)

    def test_short_history(self):
        r = screen.analyse(bars([10.0, 11.0, 12.0]), {"m1": 0, "m3": 0})
        self.assertIsNone(r["ma50"])
        self.assertEqual(r["signals"], [])


class Codes(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(screen.yahoo_candidates("SHOP US"), (["SHOP"], "SHOP"))
        self.assertEqual(screen.yahoo_candidates("BRK/B US"), (["BRK-B"], "BRK-B"))
        self.assertEqual(screen.yahoo_candidates("2345 TT")[0], ["2345.TW", "2345.TWO"])
        self.assertEqual(screen.yahoo_candidates("0700 HK")[0], ["0700.HK"])
        self.assertEqual(screen.yahoo_candidates("600519 CH")[0], ["600519.SS"])
        self.assertEqual(screen.yahoo_candidates("300308 CH")[0], ["300308.SZ"])
        self.assertEqual(screen.yahoo_candidates("BA LN")[0], ["BA.L"])
        self.assertEqual(screen.yahoo_candidates("BA/ LN")[0], ["BA.L"])
        self.assertEqual(screen.yahoo_candidates("RHM GY")[0], ["RHM.DE"])
        self.assertEqual(screen.yahoo_candidates("SU FP")[0], ["SU.PA"])
        self.assertEqual(screen.yahoo_candidates("7751 JT")[0], ["7751.T"])
        self.assertEqual(screen.yahoo_candidates("255A JT")[0], ["255A.T"])
        self.assertEqual(screen.yahoo_candidates("278470 KP")[0], ["278470.KS", "278470.KQ"])
        self.assertEqual(screen.yahoo_candidates("084370 KQ")[0], ["084370.KQ", "084370.KS"])
        self.assertEqual(screen.yahoo_candidates("PTTGC TB")[0], ["PTTGC.BK"])
        self.assertEqual(screen.yahoo_candidates("241 HK")[0], ["0241.HK"])

    def test_tv(self):
        self.assertEqual(screen.tv_symbol("0700.HK"), "HKEX:700")
        self.assertEqual(screen.tv_symbol("BRK-B"), "BRK.B")
        self.assertEqual(screen.tv_symbol("SHOP", "NASDAQ"), "NASDAQ:SHOP")
        self.assertEqual(screen.tv_symbol("^VIX"), "TVC:VIX")
        self.assertEqual(screen.tv_symbol("AAPL", "", "NMS"), "NASDAQ:AAPL")
        self.assertEqual(screen.tv_symbol("BRK-B", "", "NYQ"), "NYSE:BRK.B")
        self.assertEqual(screen.tv_symbol("2330.TW", "", "TAI"), "TWSE:2330")

    def test_tv_label(self):
        self.assertEqual([screen.tv_label(v) for v in (0.6, 0.3, 0, -0.3, -0.7, None)],
                         ["Strong buy", "Buy", "Neutral", "Sell", "Strong sell", None])

    def test_wikipedia_table(self):
        rows = "".join(f"<tr><td>T{i:02d}</td><td>Co {i}</td><td>Energy</td><td>Oil</td></tr>" for i in range(30))
        html = f"<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th></tr>{rows}</table>"
        m = screen.wikipedia_members(html.replace("T0", "TA").replace("T1", "TB").replace("T2", "TC"))
        self.assertEqual(len(m), 30)
        self.assertEqual(m[0][2], "Energy")


class MemberSources(unittest.TestCase):
    def test_ticker_column_without_header(self):
        rows = "".join(f"<tr><td>Company number {i}</td><td>{chr(65 + i % 26)}{chr(65 + i // 26)}X</td><td>Tech</td></tr>" for i in range(40))
        m = screen.wikipedia_members(f"<table><tr><th>Name</th><th>Code</th><th>Industry</th></tr>{rows}</table>")
        self.assertEqual(len(m), 40)
        self.assertEqual(m[0], ("AAX", "Company number 0", ""))

    def test_nasdaq_json(self):
        raw = json.dumps({"data": {"data": {"rows": [{"symbol": f"T{i:02d}".replace("0", "A").replace("1", "B").replace("2", "C").replace("3", "D"),
                                                      "companyName": f"Co {i}"} for i in range(30)]}}})
        self.assertEqual(len(screen.nasdaq_api_members(raw)), 30)

    def test_sources_tried_in_order(self):
        good = json.dumps({"data": {"data": {"rows": [{"symbol": s, "companyName": s} for s in
                                                      [a + b for a in "ABCDE" for b in "FGHIJ"]]}}}).encode()
        calls = []
        def fake_get(url, tries=2, timeout=12):
            calls.append(url)
            if "wikipedia" in url:
                raise ValueError("blocked")
            return good
        orig = screen.get
        screen.get = fake_get
        try:
            u = {"groups": [{"name": "Nasdaq-100", "wiki": "w", "sources": ["https://en.wikipedia.org/x", "https://api.nasdaq.com/y"],
                             "index": None, "items": []},
                            {"name": "S&P 500", "wiki": None, "sources": [], "index": None,
                             "items": [{"cands": ["AF"], "sym": "AF", "label": "AF", "exch": "", "sector": "Energy"}]}]}
            errors = []
            screen.fill_universe(u, errors)
            screen.borrow_sectors(u)
        finally:
            screen.get = orig
        self.assertEqual(len(u["groups"][0]["items"]), 25)
        self.assertIn("api.nasdaq.com", errors[0])
        self.assertEqual(u["groups"][0]["items"][0]["sector"], "Energy")   # borrowed from the S&P 500 group


class ListingChoice(unittest.TestCase):
    def test_stale_duplicate_listing_is_skipped(self):
        def fake(sym):
            closes = [100.0 + i * 0.1 for i in range(260)]
            b = bars(closes)
            if sym.endswith(".KS"):           # stale duplicate: one bar behind and a frozen live price
                b = bars(closes[:-1])
                b["last"], b["live_bad"] = None, 180.0
            b["ysym"] = sym
            return b
        with tempfile.TemporaryDirectory() as d:
            orig = screen.ROOT
            data = screen.build(d, fetch=fake, fetch_news=lambda s: [], load_universe=False, fetch_tv=lambda s: {})
        self.assertEqual(data["stocks"]["000660.KS"]["ysym"], "000660.KQ")


class Consensus(unittest.TestCase):
    def test_merge(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            with open(p, "w") as fh:
                json.dump({"asof": "2026-10-15T08:30+08:00", "stocks": {"NVDA": {"up": 12.5, "buy": 90, "n": 60, "rt": 4.7, "rev4w": 3.1}}}, fh)
            # Bloomberg's averages (synced weekly) are compared with ours as of the last close before the sync day
            stocks, errors = {"NVDA": {"ma50": 130.0, "ma200": 130.0,
                                       "_mah": {"2026-10-13": (90.0, 70.0), "2026-10-14": (100.0, 80.0), "2026-10-15": (130.0, 130.0)}},
                              "AAPL": {}}, []
            with open(p, "w") as fh:
                json.dump({"asof": "2026-10-15T08:30+08:00", "stocks": {"NVDA": {"up": 12.5, "buy": 90, "n": 60, "rt": 4.7, "rev4w": 3.1,
                                                                                  "bma50": 101.0, "bma200": 90.0}}}, fh)
            self.assertEqual(screen.load_consensus(stocks, errors, p), "2026-10-15T08:30+08:00")
            self.assertIn("200-day", stocks["NVDA"]["dq"])        # 80 vs 90 is flagged
            self.assertNotIn("50-day", stocks["NVDA"]["dq"])      # 100 vs 101 is fine
            self.assertEqual(stocks["NVDA"]["st"]["up"], 12.5)
            self.assertNotIn("st", stocks["AAPL"])


class RealFiles(unittest.TestCase):
    """Every theme and universe file in the repository parses, and every line becomes a ticker."""
    def test_files_parse(self):
        tdir = os.path.join(screen.ROOT, "themes")
        for f in os.listdir(tdir):
            t = screen.read_list(os.path.join(tdir, f))
            for g in t["groups"]:
                for it in g["items"]:
                    self.assertTrue(it["cands"][0] and " " not in it["cands"][0], (f, it))
        u = screen.read_list(os.path.join(screen.ROOT, "universe.txt"))
        self.assertTrue(any(g["wiki"] for g in u["groups"]))

    def test_build_offline(self):
        random.seed(7)

        def fake(sym):
            if sym.endswith(".TWO") or sym == "SNDK":
                raise ValueError("404")
            c = [100.0]
            for _ in range(255):
                c.append(c[-1] * (1 + random.gauss(0.0005, 0.02)))
            return bars(c, [random.randint(5, 30) * 100_000 for _ in c])

        with tempfile.TemporaryDirectory() as d:
            b = fake("X")
            b["exch"] = "NMS"
            def tv(syms):
                self.assertIn("NASDAQ:NVDA", syms)
                return {"NASDAQ:NVDA": {"tvr": 0.4, "tv_ma": 0.6, "tv_osc": 0.1, "tv_sector": "Electronic Technology", "tv_industry": "Semiconductors"}}
            data = screen.build(d, fetch=lambda s: {**fake(s), "exch": "NMS"} if "." not in s else fake(s),
                                fetch_news=lambda s: [{"title": "t", "link": "l", "time": ""}], load_universe=False, fetch_tv=tv)
            self.assertEqual(data["stocks"]["NVDA"]["tv_label"], "Buy")
            with open(os.path.join(d, "charts", screen.chart_file("BRK-B"))) as fh:
                cp = json.load(fh)
            self.assertEqual(len({len(cp[x]) for x in "tohlcv"}), 1)
            self.assertTrue(os.path.exists(os.path.join(d, "charts", "0700.HK.json")))
            self.assertTrue(data["themes"])
            self.assertTrue(any(e.startswith("SNDK") for e in data["errors"]))
            with open(os.path.join(d, "data.json")) as fh:
                json.load(fh)


if __name__ == "__main__":
    unittest.main()
