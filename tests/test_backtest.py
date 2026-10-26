"""Offline checks for scripts/backtest_briefs.py and the tracker's sub-lists (no network)."""
import os, sys, unittest
from datetime import date, datetime, timedelta, timezone
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
import backtest_briefs as bt  # noqa: E402
import track_briefs as tb  # noqa: E402


def bars(n, start=date(2025, 1, 1)):
    ts, d = [], start
    while len(ts) < n:
        if d.weekday() < 5:
            ts.append(int(datetime(d.year, d.month, d.day, 14, 30, tzinfo=timezone.utc).timestamp()))
        d += timedelta(days=1)
    c = [100 + i * 0.5 for i in range(n)]
    return {"t": ts, "o": c, "h": [x * 1.01 for x in c], "l": [x * 0.99 for x in c], "c": c, "v": [1e6] * n}


class History(unittest.TestCase):
    def test_no_look_ahead(self):
        b = bars(300)
        days = [bt.bar_day(t) for t in b["t"]]
        s = days[200].isoformat()
        k, out = bt.analyse_history(("AAA", b, [s], {s: {"m1": 0, "m3": 0}}, True))
        r = out[s]
        self.assertEqual(r["last"], b["c"][200])   # the session's own close, nothing later
        self.assertEqual(r["t0"], b["t"][200] - b["t"][200] % 86400)
        self.assertLessEqual(len(r["_tierh"]), bt.LEADER_TIER_DAYS)
        self.assertNotIn("spark", r)

    def test_skips_unlisted_and_stale(self):
        b = bars(300)
        days = [bt.bar_day(t) for t in b["t"]]
        early, late = days[30].isoformat(), (days[-1] + timedelta(days=30)).isoformat()
        _, out = bt.analyse_history(("AAA", b, [early, late], {}, False))
        self.assertEqual(out, {})

    def test_sydney_bar_dated_to_its_own_session(self):
        t = int(datetime(2026, 10, 22, 23, 0, tzinfo=timezone.utc).timestamp())   # ASX open, 23 Oct local
        self.assertEqual(bt.bar_day(t), date(2026, 10, 23))


class Stats(unittest.TestCase):
    def test_bootstrap_brackets_the_mean(self):
        by_day = [[1.0, 2.0], [3.0], [2.0, 2.0]] * 10
        lo, hi = bt.block_bootstrap(by_day, 3)
        self.assertLessEqual(lo, 2.0)
        self.assertGreaterEqual(hi, 2.0)

    def test_bootstrap_needs_enough_days(self):
        self.assertIsNone(bt.block_bootstrap([[1.0]] * 5, 5))


class Sublists(unittest.TestCase):
    def test_breakouts_split_by_signal(self):
        self.assertEqual(tb.sublist("breakouts", {"why": "Breakout above resistance 101.5; New 52-week high"}), "breakouts_level")
        self.assertEqual(tb.sublist("breakouts", {"why": "New 52-week high"}), "breakouts_hi52")
        self.assertEqual(tb.sublist("breakouts", {"why": "Golden cross (50d over 200d) today"}), "breakouts_ma")
        self.assertEqual(tb.sublist("breakdowns", {"why": "New 52-week low"}), "breakdowns_lo52")

    def test_pullbacks_split_by_rule_path(self):
        self.assertEqual(tb.sublist("pullbacks", {"vs21": 2.0}), "pullbacks_band")
        self.assertEqual(tb.sublist("pullbacks", {"vs21": 10.2}), "pullbacks_touch")
        self.assertEqual(tb.sublist("bounces", {"vs21": -8.9}), "bounces_touch")
        self.assertIsNone(tb.sublist("improving", {"vs21": 1.0}))


if __name__ == "__main__":
    unittest.main()
