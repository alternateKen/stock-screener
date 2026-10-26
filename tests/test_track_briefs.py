"""Offline checks for scripts/track_briefs.py (no network). Run: python -m unittest discover -s tests -v"""
import json, os, sys, tempfile, unittest
from datetime import date, datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import track_briefs as tb  # noqa: E402


def day_ts(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def weekdays(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def chart(closes, start=date(2026, 9, 1), opens=None):
    ds = weekdays(start, len(closes))
    return {"t": [day_ts(d) for d in ds], "o": opens or closes, "h": [c * 1.01 for c in closes],
            "l": [c * 0.99 for c in closes], "c": closes, "v": [1] * len(closes)}, ds


class Fake:
    """Stands in for Yahoo: benchmarks flat at 100."""
    def __call__(self, sym):
        b, _ = chart([100.0] * 80)
        return {**b, "intraday": False}


def setup_dir(charts, live=None):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "charts"))
    for k, b in charts.items():
        with open(os.path.join(d, "charts", tb.screen.chart_file(k)), "w") as f:
            json.dump(b, f)
    with open(os.path.join(d, "data.json"), "w") as f:
        json.dump({"stocks": {k: {"intraday": (live or {}).get(k, False)} for k in charts},
                   "themes": [{"title": "T", "groups": [{"items": [{"k": k} for k in charts]}]}]}, f)
    return d


class Scoring(unittest.TestCase):
    def setUp(self):
        tb.CACHE = tempfile.mkdtemp()
        closes = [100.0] * 30 + [110.0] + [120.0] * 49
        self.b, self.ds = chart(closes, opens=[100.0] * 30 + [105.0] + [120.0] * 49)
        self.session = self.ds[29].isoformat()   # signal bar = index 29 (close 100)

    def run_card(self, side, card=None, live=False, today=None):
        d = setup_dir({"AAA": self.b}, {"AAA": live})
        p = tb.Prices(d, fetcher=Fake(), today=today or self.ds[-1] + timedelta(days=3))
        card = card or {"sym": "AAA", "k": "AAA", "last": 100.0}
        return tb.score_card(card, side, self.session, p, p.today)

    def test_long_and_short_returns(self):
        r = self.run_card(1)
        self.assertEqual(r["res"]["1D"]["close"]["ret"], 10.0)
        self.assertAlmostEqual(r["res"]["1D"]["open"]["ret"], (110 / 105 - 1) * 100, places=1)
        self.assertEqual(r["res"]["1W"]["close"]["dir"], 20.0)
        self.assertEqual(r["res"]["1W"]["close"]["x_spx"], 20.0)   # flat benchmark
        s = self.run_card(-1)
        self.assertEqual(s["res"]["1W"]["close"]["dir"], -20.0)
        self.assertLess(s["res"]["1W"]["mae"], 0)

    def test_pending_and_no_month(self):
        r = self.run_card(1, today=self.ds[29] + timedelta(days=1))
        self.assertEqual(set(r["res"]), {"1D", "1W", "20D"})
        short, _ = chart([100.0] * 32)
        d = setup_dir({"BBB": short})
        p = tb.Prices(d, fetcher=Fake(), today=date(2026, 10, 20))
        out = tb.score_card({"sym": "BBB", "k": "BBB", "last": 100.0}, 1, self.session, p, p.today)
        self.assertTrue(out["res"]["20D"]["pending"])
        self.assertFalse(out["res"]["1D"].get("pending", False))

    def test_holiday_placeholder_is_not_a_session(self):
        b = {"t": [0, 86400, 172800], "o": [10, 11, 11], "h": [10.5, 11.5, 11], "l": [9.5, 10.5, 11], "c": [10, 11, 11],
             "v": [5, 6, 0]}
        self.assertEqual(tb.Prices._clean(b)["c"], [10, 11])

    def test_peak_and_trough_prices(self):
        r = self.run_card(1)
        d1, w1 = r["res"]["1D"], r["res"]["1W"]
        self.assertAlmostEqual(d1["hi"], 111.1)          # the 1D bar's high (close 110)
        self.assertAlmostEqual(w1["hi"], 121.2)          # highest high over 5 sessions
        self.assertAlmostEqual(w1["lo"], 108.9)          # lowest low over 5 sessions
        self.assertAlmostEqual(w1["hi_pct"], 21.2)       # from the signal close of 100
        self.assertEqual(w1["px"], 120.0)

    def test_live_bar_never_counts(self):
        b, ds = chart([100.0] * 30 + [130.0])
        d = setup_dir({"CCC": b}, {"CCC": True})
        p = tb.Prices(d, fetcher=Fake(), today=ds[-1])
        out = tb.score_card({"sym": "CCC", "k": "CCC", "last": 100.0}, 1, ds[29].isoformat(), p, p.today)
        self.assertTrue(out["res"]["1D"]["pending"])

    def test_levels_targets(self):
        card = {"sym": "AAA", "k": "AAA", "last": 100.0, "why": "Bull flag forming, 1.0% below its breakout level 101 (target 115)"}
        r = self.run_card(1, card)
        self.assertTrue(r["res"]["1W"]["triggered"])
        self.assertTrue(r["res"]["1W"]["target_hit"])
        card = {"sym": "AAA", "k": "AAA", "last": 100.0, "why": "Breakout above resistance 99 on 2x volume"}
        self.assertTrue(self.run_card(1, card)["res"]["1W"]["level_held"])

    def test_signal_bar_by_price_when_not_stamped(self):
        b, ds = chart([100.0, 101.0, 102.0, 103.0])
        p = tb.Prices(setup_dir({"X": b}), fetcher=Fake(), today=ds[-1])
        bb = p.get("X")
        self.assertEqual(tb.signal_index(bb, {"last": 101.0}, ds[3].isoformat()), 1)
        self.assertEqual(tb.signal_index(bb, {}, ds[2].isoformat()), 2)


class NotionImport(unittest.TestCase):
    MD = """## Bottom line
- <b>Market health: Risk-off.</b> stuff
- <b>Best long:</b> MSFT, Lead-tier pullback. <b>Best short:</b> IONQ, bear flag.
## Long setups
### Lead-tier pullbacks
| Stock | Where | Why | Last | Day | 1M | vs S&P 3M | Trend / short-term | vs 21 EMA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <b>MSFT</b> Microsoft | GICS / IT | Lead tier, pulling back to the 9 / 21 EMA | 524.51 USD | +0.7% | +5.3% | +32.0 pts | Strong uptrend / mixed | +0.1% |
| <b>003160 KP</b> D.I Corp | Korea / Semis | Lead tier, pulling back to the 9 / 21 EMA | 37,350 KRW | +4.0% | +18.9% | +86.9 pts | Strong uptrend / mixed | -0.1% |
<b>Cleanest:</b>
- <b>MSFT</b>: Lead.
- <b>Extended (do not chase):</b> DK-Lok (003160 KP) +10.3%.
## Short setups
### Near breakdown
| Stock | Where | Why | Last | Day | 1M | vs S&P 3M | Trend / short-term | vs 21 EMA |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| <b>IONQ</b> IonQ | Leaders / Quantum | Bear flag forming, 0.1% above its breakdown level 31.24 (target 18.03) | 31.27 USD | +0.4% | -30.5% | -15.8 pts | Strong downtrend / down | -12.7% |
## High-ADR Leaders
<b>Lead (2):</b> <b>AAPL</b> (Information Technology); <b>MSFT</b> (Information Technology)
<b>Lagging (2):</b>
- Quantum: IONQ, RGTI
## Data notes
- Screener generated 2026-10-25 17:05 UTC (US session 2026-10-23, end of day, not intraday).
"""

    def test_parse(self):
        b = tb.parse_notion(self.MD)
        self.assertEqual(b["us_session"], "2026-10-23")
        self.assertEqual(b["leaders"]["health"]["status"], "Risk-off")
        pb = b["long"]["pullbacks"]
        self.assertEqual([c["k"] for c in pb], ["MSFT", "003160.KS"])
        self.assertEqual(pb[1]["last"], 37350.0)
        self.assertEqual(pb[0]["tier"], "lead")
        self.assertEqual(b["short"]["near_breakdown"][0]["short"], "down")
        self.assertEqual([c["sym"] for c in b["leaders"]["tiers"]["lead"]], ["AAPL", "MSFT"])
        self.assertEqual([c["sym"] for c in b["leaders"]["tiers"]["lag"]], ["IONQ", "RGTI"])
        self.assertEqual(b["picks"]["pick_best_long"], ["MSFT"])
        self.assertEqual(b["picks"]["pick_best_short"], ["IONQ"])
        self.assertEqual(b["picks"]["pick_clean_long"], ["MSFT"])
        self.assertEqual(b["picks"]["pick_extended"], ["003160 KP"])


class Window(unittest.TestCase):
    def test_brief_window(self):
        f = datetime.fromisoformat
        self.assertTrue(tb.in_brief_window(f("2026-10-25T17:05:00+00:00"), "2026-10-23", False))   # weekend rebuild
        self.assertTrue(tb.in_brief_window(f("2026-10-23T21:05:00+00:00"), "2026-10-23", False))
        self.assertFalse(tb.in_brief_window(f("2026-10-23T21:05:00+00:00"), "2026-10-23", True))
        self.assertFalse(tb.in_brief_window(f("2026-10-26T00:20:00+00:00"), "2026-10-23", False))  # Asia trading
        self.assertFalse(tb.in_brief_window(f("2026-10-22T21:05:00+00:00"), "2026-10-23", False))


class Positions(unittest.TestCase):
    """A stock long in one brief and short in a later one: one closed position (the flip) and one open."""
    class P:
        def __init__(self, b):
            self.b = b

        def get(self, k):
            return self.b

    def setUp(self):
        closes = [100.0] * 5 + [100.0, 104.0, 108.0, 106.0, 103.0, 101.0, 99.0, 97.0] + [97.0] * 30
        raw, self.ds = chart(closes)
        self.b = tb.Prices._clean(raw)

    def row(self, i, side, lst):
        return {"k": "MER", "sym": "4385 JT", "brief": self.ds[i].isoformat(), "signal_day": self.ds[i].isoformat(),
                "side": side, "list": lst, "status": "ok"}

    def test_flip_closes_and_reopens(self):
        rows = [self.row(5, 1, "pullbacks"), self.row(7, 1, "breakouts"), self.row(9, -1, "bounces")]
        short = {x: v[:18] for x, v in self.b.items() if isinstance(v, list)}   # the new short is still open
        ps = tb.positions(rows, self.P({**self.b, **short}))
        closed = [p for p in ps if p["status"] == "closed"]
        self.assertEqual(len(closed), 1)
        c = closed[0]
        self.assertEqual((c["reason"], c["side"], c["held"], c["repeats"]), ("flip", 1, 4, 1))
        self.assertAlmostEqual(c["ret"], 3.0)                 # 100 -> 103 at the flip brief's close
        self.assertAlmostEqual(c["hi"], 108.0 * 1.01)         # highest high before the flip
        self.assertAlmostEqual(c["best_dir"], 8.0)
        self.assertAlmostEqual(c["giveback"], 5.0)            # best close +8%, closed at +3%
        self.assertTrue(c["whipsaw"])                         # reversed within 5 sessions
        o = [p for p in ps if p["status"] == "open"][0]
        self.assertEqual((o["side"], o["entry"], o["entry_day"]), (-1, 103.0, self.ds[9].isoformat()))

    def test_closes_after_20_sessions(self):
        ps = tb.positions([self.row(5, 1, "pullbacks")], self.P(self.b))
        self.assertEqual((ps[0]["status"], ps[0]["reason"], ps[0]["held"]), ("closed", "20 sessions", 20))
        s = tb.positions_summary(ps)["pullbacks"]
        self.assertEqual((s["closed"], s["flip"]), (1, 0))


class Bloomberg(unittest.TestCase):
    def test_bbg_file_is_used_and_dated_by_trading_day(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "bbg_daily.json")
        with open(p, "w") as f:
            json.dump({"asof": "2026-10-27", "prices": {"CSL.AX": {"d": ["2026-10-22", "2026-10-23", "2026-10-26"],
                       "o": [196, 197, 195], "h": [198, 199, 196], "l": [195, 196, 191], "c": [197, 196.7, 195.1]}}}, f)
        pr = tb.Prices(None, fetch=True, fetcher=Fake(), today=date(2026, 10, 27), bbg=p)
        b = pr.get("CSL.AX")
        self.assertEqual(b["src"], "bbg")
        # the stamped Yahoo t0 is ignored for Bloomberg bars; the 23 Oct bar is the signal bar for the 23 Oct US session
        i = tb.signal_index(b, {"t0": 12345, "last": 196.7}, "2026-10-23")
        self.assertEqual(b["d"][i], date(2026, 10, 23))
        out = tb.score_card({"sym": "CSL AU", "k": "CSL.AX", "last": 196.7}, 1, "2026-10-23", pr, pr.today)
        self.assertEqual(out["px_src"], "bbg")
        self.assertEqual(out["res"]["1D"]["day"], "2026-10-26")


class MiddayEditions(unittest.TestCase):
    def test_windows(self):
        f = lambda x: datetime.fromisoformat(x)   # noqa: E731
        self.assertEqual(tb.midday_edition(f("2026-10-27T04:05:00+00:00"), False), ("asia", date(2026, 10, 27)))   # 12:05 local
        self.assertIsNone(tb.midday_edition(f("2026-10-27T02:05:00+00:00"), False))                               # 10:05: too early
        self.assertEqual(tb.midday_edition(f("2026-10-27T14:05:00+00:00"), True), ("us", date(2026, 10, 27)))      # 35 min after the open
        self.assertIsNone(tb.midday_edition(f("2026-10-27T13:50:00+00:00"), True))                                # 20 min after: not yet
        # after the clocks change the open is 14:30 UTC, so 14:35 is too soon
        self.assertIsNone(tb.midday_edition(f("2026-11-03T14:35:00+00:00"), True))
        self.assertEqual(tb.us_open_utc(date(2026, 11, 3)).hour, 14)

    def test_cards_split_by_market(self):
        br = {"long": {"breakouts": [{"sym": "MSFT", "cur": "USD"}, {"sym": "2330 TT", "cur": "TWD"}]},
              "improving": [{"sym": "NVDA", "cur": "USD"}]}
        tb.edition_cards(br, "asia")
        self.assertEqual([c["sym"] for c in br["long"]["breakouts"]], ["2330 TT"])
        self.assertEqual(br["improving"], [])

    def test_intraday_card_measured_from_its_midday_price(self):
        closes = [100.0] * 30 + [102.0] + [110.0] * 10
        raw, ds = chart(closes)
        d = setup_dir({"AAA": raw})
        p = tb.Prices(d, fetcher=Fake(), today=ds[-1] + timedelta(days=3))
        card = {"sym": "AAA", "k": "AAA", "last": 101.0, "t0": raw["t"][30]}   # the build saw 101 during day 30
        out = tb.score_card(card, 1, ds[30].isoformat(), p, p.today, intraday=True)
        self.assertEqual(list(out["res"])[0], "Close")
        self.assertAlmostEqual(out["res"]["Close"]["close"]["ret"], (102 / 101 - 1) * 100, places=1)
        self.assertAlmostEqual(out["res"]["1D"]["close"]["ret"], (110 / 101 - 1) * 100, places=1)
        self.assertNotIn("hi", out["res"]["Close"])

    def test_live_day_is_pending(self):
        raw, ds = chart([100.0] * 31)
        d = setup_dir({"AAA": raw}, {"AAA": True})   # day 30 is still trading: dropped as a result
        p = tb.Prices(d, fetcher=Fake(), today=ds[30])
        out = tb.score_card({"sym": "AAA", "k": "AAA", "last": 100.5, "t0": raw["t"][30]}, 1, ds[30].isoformat(), p, p.today, intraday=True)
        self.assertTrue(out["res"]["Close"]["pending"])

    def test_archive_keeps_the_first_asia_build(self):
        tb.ARCHIVE = tempfile.mkdtemp()
        raw, ds = chart([100.0] * 31)
        d = setup_dir({"2330.TW": raw, "MSFT": raw})
        brief = {"generated": "2026-10-27T04:05:00+00:00", "us_session": "2026-10-26", "intraday": False,
                 "long": {"breakouts": [{"sym": "2330 TT", "k": "2330.TW", "cur": "TWD", "last": 100.0},
                                        {"sym": "MSFT", "k": "MSFT", "cur": "USD", "last": 100.0}]}}
        with open(os.path.join(d, "brief.json"), "w") as f:
            json.dump(brief, f)
        dest = tb.archive(d)
        self.assertTrue(dest.endswith("2026-10-27-asia.json"))
        with open(dest) as f:
            kept = json.load(f)
        self.assertEqual((kept["edition"], kept["edition_date"]), ("asia", "2026-10-27"))
        self.assertEqual([c["sym"] for c in kept["long"]["breakouts"]], ["2330 TT"])
        self.assertEqual(kept["long"]["breakouts"][0]["t0"], raw["t"][-1])
        brief["generated"] = "2026-10-27T04:35:00+00:00"   # a later build the same day is not kept
        with open(os.path.join(d, "brief.json"), "w") as f:
            json.dump(brief, f)
        tb.archive(d)
        with open(dest) as f:
            self.assertEqual(json.load(f)["generated"], "2026-10-27T04:05:00+00:00")
        self.assertEqual([tb.brief_id(b) for b in tb.load_archive()], ["2026-10-27 Asia midday"])

    def test_labels(self):
        m = {"us_session": "2026-10-23", "generated": "2026-10-25T22:40:00+00:00"}
        a = {"us_session": "2026-10-23", "edition": "asia", "edition_date": "2026-10-26", "generated": "2026-10-26T04:05:00+00:00"}
        self.assertEqual((tb.brief_id(m), tb.brief_id(a)), ("2026-10-23", "2026-10-26 Asia midday"))
        self.assertEqual(tb.brief_label(m), "26 Oct morning (US 10-23)")
        self.assertEqual(tb.brief_label(a), "26 Oct Asia midday")


class EndToEnd(unittest.TestCase):
    def test_evaluate_writes_scorecard(self):
        tb.CACHE = tempfile.mkdtemp()
        tb.ARCHIVE = tempfile.mkdtemp()
        b, ds = chart([100.0] * 30 + [101.0 + i for i in range(30)])
        brief = {"us_session": ds[29].isoformat(), "leaders": {"health": {"status": "Risk-off"}, "tiers": {"lead": [], "lag": []}},
                 "long": {"breakouts": [{"sym": "AAA", "k": "AAA", "last": 100.0}], "pullbacks": [], "near_breakout": []},
                 "short": {"breakdowns": [{"sym": "BBB", "k": "BBB", "last": 100.0}], "bounces": [], "near_breakdown": []},
                 "improving": [], "deteriorating": [], "themes": [], "picks": {"pick_best_long": ["AAA"]}}
        with open(os.path.join(tb.ARCHIVE, brief["us_session"] + ".json"), "w") as f:
            json.dump(brief, f)
        d = setup_dir({"AAA": b, "BBB": b})
        out = tb.evaluate(d, today=ds[-1] + timedelta(days=3), fetcher=Fake())
        c = out["cube"]
        self.assertEqual(c["breakouts|1W|close|all|dir"]["hit"], 100)
        self.assertEqual(c["breakdowns|1W|close|Risk-off|dir"]["hit"], 0)
        self.assertEqual(c["pick_best_long|1D|close|all|dir"]["n"], 1)
        self.assertEqual(out["mech"]["breakouts|1W|close|all"]["n"], 1)
        self.assertTrue(os.path.exists(os.path.join(d, "scorecard.csv")))


if __name__ == "__main__":
    unittest.main()
