"""Offline checks for the brief tracker's Bloomberg prices: bloomberg/bbg_sync.py tracker_prices() writes the file that
scripts/track_briefs.py reads (no Bloomberg, no network)."""
import json, os, sys, tempfile, unittest
from datetime import date, timedelta
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "bloomberg"))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import bbg_sync as b  # noqa: E402
import track_briefs as tb  # noqa: E402


class GH:
    def __init__(self, briefs):
        self.briefs = briefs

    def list_dir(self, repo, path):
        return [{"name": n} for n in self.briefs] + [{"name": "notion"}]

    def read(self, repo, path):
        return json.dumps(self.briefs[path.rsplit("/", 1)[1]])


class Bbg:
    def __init__(self):
        self.secs, self.hits, self.asked = set(), 0, None

    def hist(self, secs, fields, start, end=None):
        self.asked = (sorted(secs), fields, start)
        days = [start + timedelta(days=i) for i in range(10)]
        return {s: [(d, {"PX_OPEN": 10 + i, "PX_HIGH": 11 + i, "PX_LOW": 9 + i, "PX_LAST": 10.5 + i}) for i, d in enumerate(days)]
                for s in secs if s != "NOPE US Equity"}, {}


class TrackerPrices(unittest.TestCase):
    def test_round_trip(self):
        day = date.today() - timedelta(days=3)
        old = date.today() - timedelta(days=60)
        brief = {"us_session": day.isoformat(), "long": {"breakouts": [{"sym": "005930 KS", "k": "005930.KS"}]},
                 "short": {"bounces": [{"sym": "MSFT", "k": "MSFT"}, {"sym": "NOPE", "k": "NOPE"}]},
                 "leaders": {"tiers": {"lag": [{"sym": "8869.KL", "k": "8869.KL"}]}}}
        gh = GH({f"{day}.json": brief, f"{old}.json": {"long": {"breakouts": [{"sym": "OLD", "k": "OLD"}]}}})
        bbg, st = Bbg(), {}
        files = b.tracker_prices(bbg, gh, st)
        secs, fields, start = bbg.asked
        self.assertIn("005930 KS Equity", secs)
        self.assertIn("8869 MK Equity", secs)
        self.assertIn("SPX Index", secs)
        self.assertNotIn("OLD US Equity", secs)            # briefs older than 45 days are no longer tracked
        self.assertEqual(start, day - timedelta(days=7))
        raw = json.loads(files["bbg_daily.json"])
        self.assertNotIn("NOPE", raw["prices"])
        d = tempfile.mkdtemp()
        p = os.path.join(d, "bbg_daily.json")
        with open(p, "w") as f:
            f.write(files["bbg_daily.json"])
        pr = tb.Prices(None, fetch=True, bbg=p)
        x = pr.get("005930.KS")
        self.assertEqual((x["src"], x["c"][0], x["h"][0]), ("bbg", 10.5, 11))
        self.assertEqual(pr.get("^GSPC")["src"], "bbg")      # benchmarks come from Bloomberg too


if __name__ == "__main__":
    unittest.main()
