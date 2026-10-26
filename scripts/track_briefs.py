#!/usr/bin/env python3
"""Brief tracker: how did the setups in each morning technical brief actually perform afterwards?

Standard library only, like screen.py, and it reuses screen.py's Yahoo code, so prices come from the same source the
signals were computed from and nothing touches the Bloomberg API allowance.

Commands
  archive  [out_dir]           Copy the morning brief (out_dir/brief.json, the one the Notion brief is written from) to
                               data/briefs/<US session>.json, with each setup's signal bar stamped from out_dir/charts.
                               Only builds made after the US close and before Asia opens count (the 06:30 MYT brief).
  import-notion FILE.md [--session=YYYY-MM-DD] [--force]
                               Rebuild an archive entry from a Notion brief page saved as Markdown. Also reads the
                               curated layer (Best long / short, Cleanest, Extended: do not chase), which brief.json lacks.
  evaluate [out_dir] [--fetch] [--bbg=FILE]
                               Score every archived brief and write out_dir/scorecard.json, scorecard.csv and
                               positions.csv. Prices: Bloomberg from FILE (bbg_daily.json written by bloomberg/bbg_sync.py)
                               for every stock it has; otherwise out_dir/charts/*.json when present (the screener's own
                               candles); otherwise, or with --fetch, Yahoo directly (cached for the day in data/.price_cache).
                               Positions: each stock followed from its first appearance until the brief reverses it (a
                               flip) or 20 sessions pass, with the high, low and best close in between.

Measurement rules
  Entry "close" = close of the signal bar (the bar the brief was computed from). Entry "open" = next session's open,
  i.e. what you could actually trade after reading the brief.
  Horizons: 1D, 1W (5 sessions) and 20D (20 sessions) after the signal bar, in the stock's own market sessions (no 1M:
  it lands one to three sessions after 20D). Shorts are scored with the sign flipped.
  Peak / trough: the highest high and lowest low traded in each window, as prices and as % from the signal close.
  Excess returns: vs the S&P 500, vs the stock's home index, and vs an equal-weight basket of all theme stocks
  (the "do nothing special" baseline), all over the same dates.
"""
import bisect, csv, json, math, os, re, sys, time
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen  # noqa: E402

ROOT = screen.ROOT
ARCHIVE = os.path.join(ROOT, "data", "briefs")
CACHE = os.path.join(ROOT, "data", ".price_cache")
HORIZONS = (("1D", 1), ("1W", 5), ("20D", 20))
ENTRIES = ("close", "open")
US_CLOSE_UTC_HOUR = 20      # 16:00 New York = 20:00 UTC (summer) / 21:00 UTC (winter); brief["intraday"] covers the gap

# list key -> (section in brief.json, side: +1 long / -1 short, label)
LISTS = {
    "breakouts": (("long", "breakouts"), 1, "Long: breakouts"),
    "pullbacks": (("long", "pullbacks"), 1, "Long: Lead-tier pullbacks"),
    "near_breakout": (("long", "near_breakout"), 1, "Long: near breakout"),
    "breakdowns": (("short", "breakdowns"), -1, "Short: breakdowns"),
    "bounces": (("short", "bounces"), -1, "Short: Lagging-tier bounces"),
    "near_breakdown": (("short", "near_breakdown"), -1, "Short: near breakdown"),
    "improving": (("improving",), 1, "Improving"),
    "deteriorating": (("deteriorating",), -1, "Deteriorating"),
    "leaders_lead": (("leaders", "tiers", "lead"), 1, "High-ADR leaders: Lead tier"),
    "leaders_lag": (("leaders", "tiers", "lag"), -1, "High-ADR leaders: Lagging tier"),
}
PICKS = {   # the curated layer written in the Notion brief (from import-notion)
    "pick_best_long": (1, "Pick: best long"), "pick_best_short": (-1, "Pick: best short"),
    "pick_clean_long": (1, "Pick: cleanest longs"), "pick_clean_short": (-1, "Pick: cleanest shorts"),
    "pick_extended": (1, "Flagged extended, do not chase (scored as longs)"),
}
AGGREGATES = {"all_long": (1, "All long setups (unique names)"), "all_short": (-1, "All short setups (unique names)")}
# the breakout / pullback lists mix different signals and rule paths: each row is also scored in one sub-list
SUBLISTS = {
    "breakouts_level": (1, "Long: breakouts, through a level"), "breakouts_hi52": (1, "Long: breakouts, 52-week high only"),
    "breakouts_ma": (1, "Long: breakouts, MA reclaim / golden cross only"),
    "breakdowns_level": (-1, "Short: breakdowns, through a level"), "breakdowns_lo52": (-1, "Short: breakdowns, 52-week low only"),
    "breakdowns_ma": (-1, "Short: breakdowns, MA loss / death cross only"),
    "pullbacks_band": (1, "Long: pullbacks, -1% to +3% from the 21 EMA"), "pullbacks_touch": (1, "Long: pullbacks, EMA touch only (extended)"),
    "bounces_band": (-1, "Short: bounces, -3% to +1% from the 21 EMA"), "bounces_touch": (-1, "Short: bounces, EMA touch only"),
}
LONG_SETUPS, SHORT_SETUPS = ("breakouts", "pullbacks", "near_breakout"), ("breakdowns", "bounces", "near_breakdown")

# home-market benchmark by Yahoo suffix. Where Yahoo has no usable index history, an ETF tracking it stands in:
# TOPIX = 1306.T, CSI 300 = 510300.SS (Huatai-PineBridge), SET50 = TDEX.BK (ThaiDEX)
LOCAL_INDEX = {".KS": "^KS11", ".KQ": "^KQ11", ".TW": "^TWII", ".TWO": "^TWII", ".T": "1306.T", ".HK": "^HSI",
               ".SS": "510300.SS", ".SZ": "510300.SS", ".AX": "^AXJO", ".BK": "TDEX.BK", ".KL": "^KLSE",
               ".SI": "^STI", ".NS": "^NSEI", ".L": "^FTSE", ".DE": "^GDAXI", ".PA": "^FCHI", ".AS": "^AEX",
               ".SW": "^SSMI", ".TO": "^GSPTSE"}
SPX = "^GSPC"


def suffix(k):
    m = re.search(r"(\.[A-Z]{1,3})$", k or "")
    return m.group(1) if m else ""


def key_for(sym):
    """Display code in a brief ('005930 KS', 'MSFT', '8869.KL') -> the screener's key (its first Yahoo candidate)."""
    return screen.yahoo_candidates(sym)[0][0]


def day_of(t):
    return datetime.fromtimestamp(t, timezone.utc).date()


def add_month(d):
    y, m = (d.year + (d.month == 12), d.month % 12 + 1)
    for day in (d.day, 30, 29, 28):
        try:
            return date(y, m, day)
        except ValueError:
            continue


def add_weekdays(d, n):
    """The date n weekdays after d (holidays are not known, so a result can land a day or two later)."""
    while n > 0:
        d += timedelta(days=1)
        n -= d.weekday() < 5
    return d


def num(s):
    """'37,350 KRW' -> 37350.0; '+9.4%' -> 9.4; '+100.5 pts' -> 100.5; '2.15e+05' -> 215000.0; '–' -> None"""
    if s is None:
        return None
    m = re.search(r"[-+−]?\d[\d,]*\.?\d*(?:e[+-]?\d+)?", str(s).replace("−", "-"))
    return float(m.group(0).replace(",", "")) if m else None


# ---------------- prices ----------------
class Prices:
    """Daily candles by screener key: Bloomberg (a file written by bloomberg/bbg_sync.py, when given), else the charts
    written by screen.py (2 years, last bar may be live), else Yahoo directly. Each series says which in "src"."""

    def __init__(self, out_dir=None, fetch=False, fetcher=None, today=None, bbg=None):
        self.bbg = load_bbg(bbg) if bbg else {}
        self.cdir = os.path.join(out_dir, "charts") if out_dir else None
        self.fetch = fetch or not (self.cdir and os.path.isdir(self.cdir))
        self.fetcher = fetcher or screen.yahoo_bars
        self.today = today or datetime.now(timezone.utc).date()
        self.live = {}
        if out_dir and os.path.exists(os.path.join(out_dir, "data.json")):
            with open(os.path.join(out_dir, "data.json"), encoding="utf-8") as f:
                self.data = json.load(f)
            self.live = {k: bool(s.get("intraday")) for k, s in self.data.get("stocks", {}).items()}
        else:
            self.data = None
        self.mem = {}

    def get(self, k):
        if k in self.mem:
            return self.mem[k]
        if k in self.bbg:
            self.mem[k] = self.bbg[k]
            return self.mem[k]
        b = None
        if self.cdir and not self.fetch:
            p = os.path.join(self.cdir, screen.chart_file(k))
            if os.path.exists(p):
                with open(p, encoding="utf-8") as f:
                    b = json.load(f)
                b["partial"] = self.live.get(k, False)
        if b is None and (self.fetch or k.startswith("^") or k in LOCAL_INDEX.values()):
            b = self._yahoo(k)
        if b is not None:
            b = self._clean(b)
            b["src"] = "yahoo"
        self.mem[k] = b
        return b

    def _yahoo(self, k):
        os.makedirs(CACHE, exist_ok=True)
        p = os.path.join(CACHE, f"{screen.chart_file(k)[:-5]}_{self.today.isoformat()}.json")
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        twin = {".KS": ".KQ", ".KQ": ".KS", ".TW": ".TWO", ".TWO": ".TW"}.get(suffix(k))
        cands = [k] + ([k[: -len(suffix(k))] + twin] if twin else [])
        got = []
        for c in cands:   # Korea / Taiwan codes can sit on two boards: the genuine listing wins, as in screen.py
            try:
                got.append(self.fetcher(c))
                time.sleep(0.3)   # gentle on Yahoo
            except Exception as e:  # noqa: BLE001
                if len(cands) == 1:
                    print(f"  price fetch failed for {c}: {e}")
        if not got:
            return None
        raw = max(got, key=lambda r: (r.get("live_bad") is None, r["t"][-1]))
        b = {"t": [t - t % 86400 for t in raw["t"]], "o": raw["o"], "h": raw["h"], "l": raw["l"],
             "c": raw["c"], "v": raw.get("v"), "partial": bool(raw.get("intraday"))}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(b, f)
        return b

    @staticmethod
    def _clean(b):
        n = len(b["c"]) - (1 if b.get("partial") else 0)   # a live (unfinished) bar never counts as a result
        # Yahoo fills some market holidays with a placeholder bar (no volume, one price): not a session
        v = b.get("v")
        keep = [i for i in range(n) if not (v and not v[i] and b["h"][i] == b["l"][i])]
        out = {x: [b[x][i] for i in keep] for x in ("t", "o", "h", "l", "c")}
        out["d"] = [day_of(t) for t in out["t"]]
        out["e"] = b.get("e") or {}
        out["memo"] = {}
        return out


def load_bbg(path):
    """bbg_daily.json (bloomberg/bbg_sync.py) -> {screener key: candles}. Bloomberg dates each bar by its own market's
    trading day, so these series need no holiday or time-zone fixes."""
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    out = {}
    for k, x in (raw.get("prices") or {}).items():
        keep = [i for i, c in enumerate(x["c"]) if c is not None and x["h"][i] is not None and x["l"][i] is not None]
        if len(keep) < 2:
            continue
        ds = [date.fromisoformat(x["d"][i]) for i in keep]
        b = {"d": ds, "t": [int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) for d in ds],
             "h": [x["h"][i] for i in keep], "l": [x["l"][i] for i in keep], "c": [x["c"][i] for i in keep],
             "e": {}, "memo": {}, "src": "bbg"}
        b["o"] = [x["o"][i] if x["o"][i] is not None else x["c"][i] for i in keep]
        out[k] = b
    print(f"Bloomberg prices: {len(out)} series as of {raw.get('asof')}")
    return out


def ema_continued(closes, n, seed=None):
    if seed is None:
        return screen.ema_series(closes, n)
    k, e, out = 2 / (n + 1), seed, []
    for c in closes:
        e = c * k + e * (1 - k)
        out.append(e)
    return out


def tiers_of(b):
    if "tiers" in b["memo"]:
        return b["memo"]["tiers"]
    es = {n: ema_continued(b["c"], n, b["e"].get(str(n))) for n in (9, 21, 50)}
    b["memo"]["tiers"] = [screen.tier(es[9][i], es[21][i], es[50][i]) for i in range(len(b["c"]))]
    return b["memo"]["tiers"]


def signal_index(b, card, session):
    """The bar the brief was computed from: stamped t0 (archive), else the bar near the session date whose close
    matches the brief's price, else the last bar on or before the session date."""
    if card.get("t0") is not None and b.get("src") != "bbg":   # t0 is a Yahoo bar time; Bloomberg bars match by date
        return b["t"].index(card["t0"]) if card["t0"] in b["t"] else None
    mk = ("sig", session, card.get("last"))
    if mk not in b.get("memo", {}):
        b.setdefault("memo", {})[mk] = _signal_index(b, card, session)
    return b["memo"][mk]


def _signal_index(b, card, session):
    sd = date.fromisoformat(session)
    # Bloomberg dates bars by the local trading day, so the signal bar is on or before the US session date
    late = timedelta(days=0 if b.get("src") == "bbg" else 1)
    near = range(bisect.bisect_left(b["d"], sd - timedelta(days=4)), bisect.bisect_right(b["d"], sd + late))
    last = card.get("last")
    if last:
        good = [i for i in near if abs(b["c"][i] / last - 1) < 0.006]
        if good:
            return max(good)
    i = bisect.bisect_right(b["d"], sd) - 1
    return i if i >= 0 else None


def horizon_index(b, i0, h, today):
    if h == "M":
        target = add_month(b["d"][i0])
        j = bisect.bisect_right(b["d"], target) - 1
        j = j if j >= 0 else None
        done = j is not None and (j < len(b["d"]) - 1 or today > target + timedelta(days=1))
        return (j if done and j > i0 else None), target
    j = i0 + h
    return (j if j < len(b["c"]) else None), None


def bench_return(bb, d0, d1):
    if not bb:
        return None
    i0, i1 = bisect.bisect_right(bb["d"], d0) - 1, bisect.bisect_right(bb["d"], d1) - 1
    if i0 < 0 or i1 < 0 or i1 <= i0 and d1 > d0:
        return None
    return (bb["c"][i1] / bb["c"][i0] - 1) * 100


LEVEL_RE = re.compile(r"(breakout|breakdown) level ([0-9.e+]+) \(target ([0-9.e+]+)\)")
SR_RE = re.compile(r"(?:Breakout above resistance|Breakdown below support) ([0-9.e+]+)")


def score_card(card, side, session, prices, today, univ=None):
    """One setup -> its measured outcome at every horizon and entry."""
    k = card.get("k") or key_for(card["sym"])
    out = {"k": k, "status": "ok", "res": {}}
    b = prices.get(k)
    out["px_src"] = (b or {}).get("src")
    if not b or len(b["c"]) < 3:
        out["status"] = "no prices"
        return out
    i0 = signal_index(b, card, session)
    if i0 is None:
        out["status"] = "signal bar not found"
        return out
    c0 = b["c"][i0]
    if card.get("last") and abs(c0 / card["last"] - 1) > 0.02:
        out["flag"] = f"signal close {c0:.4g} vs brief {card['last']:.4g}: history revised (split / adjustment?)"
    hs = [h / l for h, l in zip(b["h"][max(0, i0 - 19):i0 + 1], b["l"][max(0, i0 - 19):i0 + 1]) if h and l]
    adr = (sum(hs) / len(hs) - 1) * 100 if hs else None
    out.update(signal_day=b["d"][i0].isoformat(), entry_close=c0, adr=round(adr, 2) if adr else None)
    lv = LEVEL_RE.search(card.get("why") or "")
    level, target = (float(lv.group(2)), float(lv.group(3))) if lv else (None, None)
    sr = SR_RE.search(card.get("why") or "")
    brk_level = float(sr.group(1)) if sr else None
    tiers = tiers_of(b) if card.get("tier") else None
    spx, loc = prices.get(SPX), prices.get(LOCAL_INDEX.get(suffix(k), SPX))
    for name, h in HORIZONS:
        j, due = horizon_index(b, i0, h, today)
        if j is None:
            out["res"][name] = {"pending": True, "due": (due or add_weekdays(b["d"][i0], h)).isoformat()}
            continue
        r = {}
        for ent in ENTRIES:
            if ent == "open":
                if i0 + 1 > j:
                    continue
                e_px, d_from = b["o"][i0 + 1], b["d"][i0]
            else:
                e_px, d_from = c0, b["d"][i0]
            if not e_px:
                continue
            ret = (b["c"][j] / e_px - 1) * 100
            x = {"ret": round(ret, 2), "dir": round(side * ret, 2)}
            for lab, bb in (("spx", spx), ("loc", loc)):
                br = bench_return(bb, d_from, b["d"][j])
                x[f"x_{lab}"] = None if br is None else round(side * (ret - br), 2)
            if univ is not None and ent == "close":   # the baseline basket is measured close to close
                ur = univ(session, name)
                x["x_univ"] = None if ur is None else round(side * (ret - ur), 2)
            if adr:
                x["adr_units"] = round(side * ret / adr, 2)
            r[ent] = x
        hi, lo = max(b["h"][i0 + 1:j + 1]), min(b["l"][i0 + 1:j + 1])
        mfe, mae = ((hi / c0 - 1) * 100, (lo / c0 - 1) * 100) if side > 0 else ((1 - lo / c0) * 100, (1 - hi / c0) * 100)
        r.update(mfe=round(mfe, 2), mae=round(mae, 2), day=b["d"][j].isoformat(), px=b["c"][j],
                 hi=hi, lo=lo, hi_pct=round((hi / c0 - 1) * 100, 2), lo_pct=round((lo / c0 - 1) * 100, 2))
        if level:
            closes = b["c"][i0 + 1:j + 1]
            r["triggered"] = any((c >= level * 1.01) if side > 0 else (c <= level * 0.99) for c in closes)
            r["target_hit"] = (hi >= target) if side > 0 else (lo <= target)
        if brk_level:
            closes = b["c"][i0 + 1:j + 1]
            r["level_held"] = all((c >= brk_level) if side > 0 else (c <= brk_level) for c in closes)
        if tiers:
            r["tier"] = tiers[j]
            r["tier_held"] = tiers[j] == card.get("tier")
        out["res"][name] = r
    return out


# ---------------- archive ----------------
def in_brief_window(gen, session, intraday):
    """True for builds the 06:30 MYT brief can be written from: after that US session's close, before Tokyo next opens
    (00:00 UTC on the next weekday). Weekend and manual rebuilds count, as long as no market is trading."""
    if intraday or not session:
        return False
    sd = date.fromisoformat(session)
    nxt = sd + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    start = datetime(sd.year, sd.month, sd.day, US_CLOSE_UTC_HOUR, tzinfo=timezone.utc)
    end = datetime(nxt.year, nxt.month, nxt.day, tzinfo=timezone.utc)
    gen = gen if gen.tzinfo else gen.replace(tzinfo=timezone.utc)
    return start <= gen < end


def strip_brief(brief):
    return {k: v for k, v in brief.items() if k not in ("changes", "data_flags")}


def archive(out_dir, now=None):
    p = os.path.join(out_dir, "brief.json")
    if not os.path.exists(p):
        print("archive: no brief.json")
        return None
    with open(p, encoding="utf-8") as f:
        brief = json.load(f)
    gen = datetime.fromisoformat(brief["generated"])
    session = brief.get("us_session")
    if not in_brief_window(gen, session, brief.get("intraday")):
        print(f"archive: build {brief['generated']} is not between the {session} US close and the next Asian open; nothing archived")
        return None
    prices = Prices(out_dir)
    for card in iter_cards(brief):
        b = prices.get(card["k"]) if card.get("k") else None
        if b and b["t"]:
            card["t0"] = b["t"][-1]
    brief = strip_brief(brief)
    brief["source"] = "brief.json"
    os.makedirs(ARCHIVE, exist_ok=True)
    dest = os.path.join(ARCHIVE, f"{session}.json")
    old = None
    if os.path.exists(dest):
        with open(dest, encoding="utf-8") as f:
            old = json.load(f)
        brief["picks"] = old.get("picks")   # keep a curated layer imported from Notion
        same = lambda x: {k: v for k, v in x.items() if k != "generated"}   # noqa: E731
        if old.get("source") == "brief.json" and same(old) == same(brief):
            print(f"archive: {dest} unchanged")
            return dest
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(brief, f, separators=(",", ":"))
    print(f"archive: wrote {dest}")
    return dest


def iter_cards(brief):
    for key, (path, side, _) in LISTS.items():
        node = brief
        for p in path:
            node = (node or {}).get(p)
        for c in node or []:
            yield c


# ---------------- Notion import ----------------
SECTION_KEYS = {"breakouts": ("long", "breakouts"), "lead-tier pullbacks": ("long", "pullbacks"),
                "near breakout": ("long", "near_breakout"), "breakdowns": ("short", "breakdowns"),
                "lagging-tier bounces": ("short", "bounces"), "near breakdown": ("short", "near_breakdown"),
                "improving": ("improving",), "deteriorating": ("deteriorating",)}
TREND_SHORT = re.compile(r"^(.*?)\s*/\s*(up|down|mixed)$")


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _bold(s):
    return re.findall(r"<b>(.*?)</b>|\*\*(.*?)\*\*", s)


def _strip(s):
    return re.sub(r"</?b>|\*\*", "", s).strip()


def parse_notion(md, session=None):
    md = md.replace("\\|", "/")
    brief = {"long": {"breakouts": [], "pullbacks": [], "near_breakout": []},
             "short": {"breakdowns": [], "bounces": [], "near_breakdown": []},
             "improving": [], "deteriorating": [], "themes": [], "leaders": {"tiers": {"lead": [], "med": [], "lag": []}},
             "source": "notion"}
    m = re.search(r"US session (\d{4}-\d{2}-\d{2})", md)
    brief["us_session"] = session or (m.group(1) if m else None)
    m = re.search(r"Screener generated (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}) UTC", md)
    brief["generated"] = f"{m.group(1)}T{m.group(2)}:00+00:00" if m else None
    m = re.search(r"Market health: ([A-Za-z-]+)", _strip(md))
    brief["leaders"]["health"] = {"status": m.group(1)} if m else None
    section, head, part = None, None, None
    picks = {k: [] for k in PICKS}
    clean_side = None
    for raw in md.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            part = line[3:].strip().lower()
            section, head, clean_side = (("themes",) if part == "themes" else None), None, None
            continue
        if line.startswith("### "):
            section, head = SECTION_KEYS.get(line[4:].strip().lower()), None
            continue
        plain = _strip(line)
        if plain.startswith("Cleanest:"):
            clean_side = "long" if part == "long setups" else "short"
            section = None
            continue
        if plain.startswith("- Best long:") or "Best long:" in plain:
            for t in re.findall(r"Best long:\s*([^,;]+)", plain):
                picks["pick_best_long"].append(t.strip().split()[0])
            for t in re.findall(r"Best short:\s*([^,;]+)", plain):
                picks["pick_best_short"].append(t.strip().split()[0])
        if clean_side and line.startswith("- "):
            bolds = [a or b for a, b in _bold(line)]
            lead = bolds[0] if bolds else ""
            if lead.lower().startswith("extended"):
                picks["pick_extended"].append(plain)
            else:
                picks[f"pick_clean_{clean_side}"].append(lead)
            continue
        if part == "high-adr leaders":
            plainl = _strip(line)
            if plainl.startswith("Lead ("):
                syms = [t for t in (a or b for a, b in _bold(line)) if re.fullmatch(r"[A-Z0-9.\- ]+", t)]
                brief["leaders"]["tiers"]["lead"] = [{"sym": t, "name": t, "where": "Leaders", "why": "Lead tier"} for t in syms]
            elif line.startswith("- ") and ":" in plainl:
                sector, _, names = plainl[2:].partition(":")
                for s in names.split(","):
                    if s.strip():
                        brief["leaders"]["tiers"]["lag"].append({"sym": s.strip(), "name": s.strip(), "where": f"Leaders / {sector.strip()}",
                                                                 "why": "Lagging tier"})
            continue
        if not line.startswith("|") or section is None:
            continue
        cells = _cells(line)
        if set("".join(cells)) <= set("-: "):
            continue
        if head is None:
            head = [c.lower() for c in cells]
            continue
        row = dict(zip(head, cells))
        if section == ("themes",):
            lead, lag = row.get("lead (5d chg)", ""), row.get("lagging (5d chg)", "")
            brief["themes"].append({"theme": row["theme"], "n": int(num(row["stocks"])), "day": num(row["day"]),
                                    "w1": num(row["1w"]), "m1": num(row["1m"]), "above50_pct": num(row["% above 50-day"]),
                                    "lead": int(num(lead)), "lead_5d": num(lead.split("(")[1]) if "(" in lead else None,
                                    "lag": int(num(lag)), "lag_5d": num(lag.split("(")[1]) if "(" in lag else None})
            continue
        stock = row.get("stock", "")
        bm = re.match(r"(?:<b>|\*\*)(.*?)(?:</b>|\*\*)\s*(.*)", stock)
        sym, name = (bm.group(1).strip(), bm.group(2).strip()) if bm else (stock, "")
        lastcell = row.get("last", "")
        card = {"sym": sym, "k": key_for(sym), "name": name, "where": row.get("where"), "why": row.get("why") or row.get("change"),
                "last": num(lastcell), "cur": lastcell.split()[-1] if lastcell else None, "day": num(row.get("day")),
                "m1": num(row.get("1m")), "rs3": num(row.get("vs s&p 3m")), "vs21": num(row.get("vs 21 ema"))}
        tm = TREND_SHORT.match(row.get("trend / short-term", "") or "")
        if tm:
            card["trend"], card["short"] = tm.group(1), tm.group(2)
        if row.get("tier"):
            card["tier"] = row["tier"].strip().lower()
        elif "Lead tier" in (card["why"] or ""):
            card["tier"] = "lead"
        elif "Lagging tier" in (card["why"] or ""):
            card["tier"] = "lag"
        node = brief
        for p in section[:-1]:
            node = node[p]
        node[section[-1]].append(card)
    for side in ("lead", "lag"):
        for c in brief["leaders"]["tiers"][side]:
            c["k"] = key_for(c["sym"])
            c["tier"] = side
    brief["picks"] = resolve_picks(brief, picks)
    return brief


def resolve_picks(brief, picks):
    """Curated text -> the setup symbols it names (whole-word matches of symbols listed on that side of the brief)."""
    side_syms = {1: [c["sym"] for k in LONG_SETUPS for c in brief["long"][k]],
                 -1: [c["sym"] for k in SHORT_SETUPS for c in brief["short"][k]]}
    out = {}
    for key, texts in picks.items():
        side = PICKS[key][0]
        found = []
        for t in texts:
            for s in sorted(set(side_syms[side]), key=len, reverse=True):
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(s)}(?![A-Za-z0-9])", t) and s not in found:
                    found.append(s)
        out[key] = found
    return out


def import_notion(path, session=None, force=False):
    with open(path, encoding="utf-8") as f:
        brief = parse_notion(f.read(), session)
    if not brief["us_session"]:
        raise SystemExit("import-notion: no US session date found; pass --session YYYY-MM-DD")
    os.makedirs(ARCHIVE, exist_ok=True)
    dest = os.path.join(ARCHIVE, f"{brief['us_session']}.json")
    if os.path.exists(dest) and not force:
        with open(dest, encoding="utf-8") as f:
            cur = json.load(f)
        cur["picks"] = brief["picks"]   # keep the machine archive, add the curated layer
        brief = cur
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(brief, f, indent=1)
    n = sum(1 for _ in iter_cards(brief))
    print(f"import-notion: {dest}: {n} setups, picks " + ", ".join(f"{k}={v}" for k, v in brief.get("picks", {}).items()))
    return dest


# ---------------- positions: the same signals, followed per stock until the call reverses ----------------
POS_MAX = 20      # a position closes after this many sessions if the brief never reverses it
WHIPSAW = 5       # a reversal within this many sessions counts as a whipsaw


def positions(rows, prices):
    """One position per stock and direction: opened at its first appearance in a long or short setup list, kept while
    later briefs repeat that direction, closed when the stock appears on the other side (a flip: the flip brief's
    signal close is the exit, and a new position opens there) or after POS_MAX sessions. The signal view is never cut
    short by this: every appearance keeps its own fixed 1D / 1W / 20D windows."""
    sig = {}
    for r in rows:
        if r["list"] in LONG_SETUPS + SHORT_SETUPS and r["status"] == "ok" and r.get("signal_day"):
            sig.setdefault((r["k"], r["brief"]), r)   # in two lists of one brief: the first list counts
    by_k = {}
    for (k, _), r in sorted(sig.items(), key=lambda x: x[0][1]):
        by_k.setdefault(k, []).append(r)
    out = []
    for k, rs in by_k.items():
        b = prices.get(k)
        if not b or len(b["c"]) < 2:
            continue
        last = len(b["c"]) - 1
        cur = None
        for r in rs:
            i = bisect.bisect_right(b["d"], date.fromisoformat(r["signal_day"])) - 1
            if i < 0:
                continue
            if cur and i - cur["i0"] >= POS_MAX:
                out.append(position_stats(cur, b, cur["i0"] + POS_MAX, "20 sessions"))
                cur = None
            if cur is None:
                cur = opened(k, r, i, b)
            elif r["side"] == cur["side"]:
                cur["repeats"] += 1
                cur["lists"].add(r["list"])
            else:
                out.append(position_stats(cur, b, i, "flip"))
                cur = opened(k, r, i, b)
        if cur:
            done = last - cur["i0"] >= POS_MAX
            out.append(position_stats(cur, b, cur["i0"] + POS_MAX if done else last, "20 sessions" if done else None))
    out.sort(key=lambda p: (p["status"] == "open", p["last_day"], p["entry_day"]), reverse=True)
    return out


def opened(k, r, i, b):
    return {"k": k, "sym": r["sym"], "name": r.get("name"), "cur": r.get("cur"), "side": r["side"], "i0": i,
            "open_brief": r["brief"], "list": r["list"], "lists": {r["list"]}, "repeats": 0, "src": b.get("src")}


def position_stats(p, b, j, reason):
    """Entry to bar j: return, highest high / lowest low traded, best close, and how much of it was given back."""
    i0, side = p["i0"], p["side"]
    e = b["c"][i0]
    rnd = lambda v: None if v is None else round(v, 2)   # noqa: E731
    pct = lambda v: None if v is None else (v / e - 1) * 100   # noqa: E731
    span = range(i0 + 1, j + 1)
    hi = max(b["h"][i] for i in span) if j > i0 else None
    lo = min(b["l"][i] for i in span) if j > i0 else None
    best = (max if side > 0 else min)(b["c"][i] for i in span) if j > i0 else None
    ret = pct(b["c"][j])
    return {"k": p["k"], "sym": p["sym"], "name": p["name"], "cur": p["cur"], "side": side, "list": p["list"],
            "lists": sorted(p["lists"]), "repeats": p["repeats"], "open_brief": p["open_brief"], "src": p["src"],
            "entry_day": b["d"][i0].isoformat(), "entry": e, "status": "closed" if reason else "open", "reason": reason,
            "exit_day": b["d"][j].isoformat() if reason else None, "last_day": b["d"][j].isoformat(), "px": b["c"][j],
            "held": j - i0, "ret": rnd(ret), "dir": rnd(side * ret), "hi": hi, "hi_pct": rnd(pct(hi)), "lo": lo,
            "lo_pct": rnd(pct(lo)), "best_dir": rnd(side * pct(best)) if best is not None else None,
            "giveback": rnd(side * pct(best) - side * ret) if best is not None else None,
            "whipsaw": reason == "flip" and j - i0 <= WHIPSAW}


def positions_summary(ps):
    """Closed positions by the list they opened from (and all longs / all shorts): result, holding, flips, whipsaws."""
    out = {}
    groups = [(k, [p for p in ps if p["list"] == k]) for k in LONG_SETUPS + SHORT_SETUPS]
    groups += [("all_long", [p for p in ps if p["side"] > 0]), ("all_short", [p for p in ps if p["side"] < 0])]
    avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None   # noqa: E731
    share = lambda n, d: round(100 * n / d) if d else None   # noqa: E731
    for key, g in groups:
        c = [p for p in g if p["status"] == "closed"]
        d = [p["dir"] for p in c if p["dir"] is not None]
        out[key] = {"open": len(g) - len(c), "closed": len(c), "mean": avg(d), "hit": share(sum(1 for x in d if x > 0), len(d)),
                    "held": avg([p["held"] for p in c]), "giveback": avg([p["giveback"] for p in c if p["giveback"] is not None]),
                    "flip": share(sum(1 for p in c if p["reason"] == "flip"), len(c)),
                    "whipsaw": share(sum(1 for p in c if p["whipsaw"]), len(c))}
    return out


def write_positions_csv(ps, path):
    cols = ["sym", "name", "side", "list", "lists", "repeats", "open_brief", "entry_day", "entry", "status", "reason",
            "exit_day", "last_day", "px", "held", "ret", "dir", "hi", "hi_pct", "lo", "lo_pct", "best_dir", "giveback",
            "whipsaw", "cur", "src"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for p in ps:
            w.writerow([" / ".join(p[c]) if c == "lists" else p.get(c) for c in cols])


# ---------------- evaluate ----------------
def load_archive():
    out = []
    if os.path.isdir(ARCHIVE):
        for f in sorted(os.listdir(ARCHIVE)):
            if re.match(r"\d{4}-\d{2}-\d{2}\.json$", f):
                with open(os.path.join(ARCHIVE, f), encoding="utf-8") as fh:
                    out.append(json.load(fh))
    return out


def sublist(key, card):
    """Which sub-list a breakout / breakdown / pullback / bounce row belongs to (None for the other lists)."""
    why, v = card.get("why") or "", card.get("vs21")
    if key in ("breakouts", "breakdowns"):
        if "Breakout above" in why or "Breakdown below" in why:
            return f"{key}_level"
        if "52-week" in why:
            return "breakouts_hi52" if key == "breakouts" else "breakdowns_lo52"
        return f"{key}_ma"
    if key == "pullbacks" and v is not None:
        return "pullbacks_band" if -1 <= v <= 3 else "pullbacks_touch"
    if key == "bounces" and v is not None:
        return "bounces_band" if -3 <= v <= 1 else "bounces_touch"
    return None


def theme_members(prices):
    if not prices.data:
        return {}
    return {t["title"]: sorted({it["k"] for g in t["groups"] for it in g["items"]}) for t in prices.data.get("themes", [])}


def basket_return(prices, keys, session, horizon, today):
    rets = []
    for k in keys:
        b = prices.get(k)
        if not b:
            continue
        i0 = signal_index(b, {}, session)
        if i0 is None:
            continue
        j, _ = horizon_index(b, i0, dict(HORIZONS)[horizon], today)
        if j is not None:
            rets.append((b["c"][j] / b["c"][i0] - 1) * 100)
    return (sum(rets) / len(rets), len(rets)) if rets else (None, 0)


def spearman(xs, ys):
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if len(pairs) < 4:
        return None
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for pos, i in enumerate(o):
            r[i] = pos
        return r
    rx, ry = ranks([p[0] for p in pairs]), ranks([p[1] for p in pairs])
    n = len(pairs)
    return round(1 - 6 * sum((a - b) ** 2 for a, b in zip(rx, ry)) / (n * (n * n - 1)), 2)


MEASURES = ("dir", "x_spx", "x_loc", "x_univ", "adr_units")
ROWS_BRIEFS = 20   # scorecard.json carries row detail for the latest briefs only (the CSV keeps everything)


def _median(v):
    s = sorted(v)
    return None if not s else s[len(s) // 2] if len(s) % 2 else (s[len(s) // 2 - 1] + s[len(s) // 2]) / 2


def summarise(rows):
    """Results by list x horizon x entry x measure x health call ('all' plus each call), and setup mechanics."""
    cube, mech = {}, {}
    rnd = lambda v, d=2: None if v is None else round(v, d)   # noqa: E731
    for r in rows:
        for hs in ("all", r.get("health") or "n/a"):
            for name, _ in HORIZONS:
                res = r["res"].get(name) or {}
                for ent in ENTRIES:
                    key = f"{r['list']}|{name}|{ent}|{hs}"
                    m = mech.setdefault(key, {"label": r["label"], "pending": 0, "missing": 0, "due": None, "vals": []})
                    if r["status"] != "ok":
                        m["missing"] += 1
                    elif res.get("pending"):
                        m["pending"] += 1
                        m["due"] = min(filter(None, (m["due"], res.get("due")))) if res.get("due") else m["due"]
                    elif res.get(ent):
                        m["vals"].append((res[ent], res))
    for key, m in mech.items():
        for meas in MEASURES:
            v = [x[meas] for x, _ in m["vals"] if x.get(meas) is not None]
            cube[f"{key}|{meas}"] = {"n": len(v), "hit": rnd(100 * sum(1 for a in v if a > 0) / len(v), 0) if v else None,
                                     "mean": rnd(sum(v) / len(v)) if v else None, "med": rnd(_median(v)),
                                     "pend": m["pending"], "due": m["due"], "miss": m["missing"]}
        d = [x["dir"] for x, _ in m["vals"]]
        wins, losses = [a for a in d if a > 0], [-a for a in d if a < 0]
        res = [r for _, r in m["vals"]]
        def rate(f):
            v = [r[f] for r in res if f in r]
            return rnd(100 * sum(1 for a in v if a) / len(v), 0) if v else None
        avg = lambda f: rnd(sum(r[f] for r in res) / len(res)) if res else None   # noqa: E731
        m.clear()
        m.update(n=len(res), payoff=rnd(sum(wins) / len(wins) / (sum(losses) / len(losses))) if wins and losses else None,
                 mfe=avg("mfe"), mae=avg("mae"), triggered=rate("triggered"), target_hit=rate("target_hit"),
                 level_held=rate("level_held"), tier_held=rate("tier_held"))
    return cube, mech


def evaluate(out_dir, fetch=False, today=None, fetcher=None, briefs=None, prices=None, members=None, quiet=False, bbg=None):
    """briefs / prices / members default to the archive, the screener's charts and data.json's themes; the backtest
    (backtest_briefs.py) passes its own. bbg: a Bloomberg price file (bbg_daily.json), used first where it has the stock."""
    today = today or datetime.now(timezone.utc).date()
    prices = prices or Prices(out_dir, fetch=fetch, fetcher=fetcher, today=today, bbg=bbg)
    briefs = load_archive() if briefs is None else briefs
    members = theme_members(prices) if members is None else members
    univ_keys = sorted({k for ks in members.values() for k in ks})
    ucache = {}

    def univ(session, h):
        if not univ_keys:
            return None
        if (session, h) not in ucache:
            ucache[(session, h)] = basket_return(prices, univ_keys, session, h, today)[0]
        return ucache[(session, h)]

    rows, health, themes = [], [], []
    for n_br, br in enumerate(briefs):
        if not quiet and n_br and n_br % 50 == 0:
            print(f"  scored {n_br}/{len(briefs)} briefs")
        session = br["us_session"]
        status = ((br.get("leaders") or {}).get("health") or {}).get("status")
        seen, first = {}, len(rows)
        for key, (path, side, label) in LISTS.items():
            node = br
            for p in path:
                node = (node or {}).get(p)
            for card in node or []:
                sc = score_card(card, side, session, prices, today, univ)
                row = {"brief": session, "health": status, "list": key, "label": label, "side": side,
                       "sym": card["sym"], "name": card.get("name"), "where": card.get("where"), "why": card.get("why"),
                       "tier0": card.get("tier"), "vs21": card.get("vs21"), "rs3": card.get("rs3"), "last": card.get("last"),
                       "cur": card.get("cur"), **sc}
                rows.append(row)
                sub = sublist(key, card)
                if sub:
                    rows.append({**row, "list": sub, "label": SUBLISTS[sub][1]})
                if key in LONG_SETUPS + SHORT_SETUPS:
                    seen.setdefault((card["sym"], side), row)
        for (sym, side), row in seen.items():
            rows.append({**row, "list": "all_long" if side > 0 else "all_short", "label": AGGREGATES["all_long" if side > 0 else "all_short"][1]})
        for pk, syms in (br.get("picks") or {}).items():
            for sym in syms:
                src = seen.get((sym, PICKS[pk][0]))
                if src:
                    rows.append({**src, "list": pk, "label": PICKS[pk][1]})
        # market-health call: what did the leaders and the S&P do next?
        h = {"brief": session, "status": status}
        lead = [r for r in rows[first:] if r["list"] == "leaders_lead" and r["status"] == "ok"]
        lag = [r for r in rows[first:] if r["list"] == "leaders_lag" and r["status"] == "ok"]
        spx = prices.get(SPX)
        for name, hz in HORIZONS:
            lr = [r["res"][name]["close"]["ret"] for r in lead if (r["res"].get(name) or {}).get("close")]
            gr = [r["res"][name]["close"]["ret"] for r in lag if (r["res"].get(name) or {}).get("close")]
            sr = None
            if spx:
                i0 = signal_index(spx, {}, session)
                j, _ = horizon_index(spx, i0, hz, today) if i0 is not None else (None, None)
                sr = None if j is None else round((spx["c"][j] / spx["c"][i0] - 1) * 100, 2)
            h[name] = {"spx": sr, "lead_ew": round(sum(lr) / len(lr), 2) if lr else None,
                       "lag_ew": round(sum(gr) / len(gr), 2) if gr else None,
                       "univ_ew": None if univ(session, name) is None else round(univ(session, name), 2)}
        health.append(h)
        # theme calls: did the brief's 1M momentum ranking carry forward?
        trows = br.get("themes") or []
        if trows and members:
            t = {"brief": session, "themes": []}
            for th in trows:
                tk = members.get(th["theme"], [])
                fw = {name: basket_return(prices, tk, session, name, today)[0] for name, _ in HORIZONS}
                net = None
                if "tiers" in th:
                    net = (th["tiers"]["lead"] - th["tiers_5d"]["lead"]) - (th["tiers"]["lag"] - th["tiers_5d"]["lag"])
                elif th.get("lead_5d") is not None:
                    net = th["lead_5d"] - th["lag_5d"]
                t["themes"].append({"theme": th["theme"], "m1": th.get("m1"), "net_tier_5d": net,
                                    **{f"fwd_{k}": (None if v is None else round(v, 2)) for k, v in fw.items()}})
            for name, _ in HORIZONS:
                t[f"rho_m1_{name}"] = spearman([x["m1"] for x in t["themes"]], [x[f"fwd_{name}"] for x in t["themes"]])
                t[f"rho_tier_{name}"] = spearman([x["net_tier_5d"] for x in t["themes"]], [x[f"fwd_{name}"] for x in t["themes"]])
            themes.append(t)
    cube, mech = summarise(rows)
    ps = positions(rows, prices)
    keep = {b["us_session"] for b in briefs[-ROWS_BRIEFS:]}
    srcs = {}
    for r in rows:
        if r["list"] in LISTS and r.get("px_src"):
            srcs[r["px_src"]] = srcs.get(r["px_src"], 0) + 1
    labels = {k: v[2] for k, v in LISTS.items()}
    labels.update({k: v[1] for k, v in PICKS.items()})
    labels.update({k: v[1] for k, v in AGGREGATES.items()})
    labels.update({k: v[1] for k, v in SUBLISTS.items()})
    out = {"generated": datetime.now(timezone.utc).isoformat(timespec="minutes"), "today": today.isoformat(),
           "horizons": [h for h, _ in HORIZONS], "briefs": [{"session": b["us_session"], "source": b.get("source"),
                                                            "status": ((b.get("leaders") or {}).get("health") or {}).get("status"),
                                                            "picks": bool(b.get("picks"))} for b in briefs],
           "labels": labels, "cube": cube, "mech": mech, "health": health, "themes": themes,
           "rows": [r for r in rows if r["brief"] in keep], "rows_briefs": sorted(keep),
           "price_source": " + ".join(f"{'Bloomberg' if k == 'bbg' else 'Yahoo'} {v}" for k, v in sorted(srcs.items())) or "–",
           "positions": ps, "pos_summary": positions_summary(ps), "pos_rules": {"max": POS_MAX, "whipsaw": WHIPSAW},
           "universe_baseline": bool(univ_keys)}
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "scorecard.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, separators=(",", ":"), default=str)
    write_csv(rows, os.path.join(out_dir, "scorecard.csv"))
    write_positions_csv(ps, os.path.join(out_dir, "positions.csv"))
    done = sum(1 for r in rows if (r["res"].get("1D") or {}).get("close"))
    print(f"evaluate: {len(briefs)} briefs, {len(rows)} setup rows, {done} with a 1D result, "
          f"{sum(1 for p in ps if p['status'] == 'open')} open / {sum(1 for p in ps if p['status'] == 'closed')} closed positions "
          f"(prices: {out['price_source']}); wrote scorecard.json / .csv, positions.csv")
    return out


def write_csv(rows, path):
    cols = ["brief", "health", "list", "side", "sym", "name", "where", "why", "tier0", "vs21", "rs3", "cur", "last",
            "status", "flag", "signal_day", "entry_close", "adr"]
    hcols = []
    for name, _ in HORIZONS:
        for ent in ENTRIES:
            hcols += [f"{name}_{ent}_{x}" for x in ("ret", "dir", "x_spx", "x_loc", "x_univ", "adr_units")]
        hcols += [f"{name}_{x}" for x in ("px", "hi", "hi_pct", "lo", "lo_pct", "mfe", "mae", "triggered", "target_hit",
                                          "level_held", "tier", "tier_held", "due")]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols + hcols)
        for r in rows:
            line = [r.get(c) for c in cols]
            for name, _ in HORIZONS:
                res = r.get("res", {}).get(name) or {}
                for ent in ENTRIES:
                    x = res.get(ent) or {}
                    line += [x.get(k) for k in ("ret", "dir", "x_spx", "x_loc", "x_univ", "adr_units")]
                line += [res.get(k) for k in ("px", "hi", "hi_pct", "lo", "lo_pct", "mfe", "mae", "triggered", "target_hit",
                                              "level_held", "tier", "tier_held", "due")]
            w.writerow(line)


if __name__ == "__main__":
    args = sys.argv[1:]
    cmd = args[0] if args else "evaluate"
    flags = [a for a in args[1:] if a.startswith("--")]
    pos = [a for a in args[1:] if not a.startswith("--")]
    if cmd == "archive":
        archive(pos[0] if pos else os.path.join(ROOT, "docs"))
    elif cmd == "import-notion":
        sess = next((a.split("=", 1)[1] for a in flags if a.startswith("--session=")), None)
        import_notion(pos[0], sess, "--force" in flags)
    elif cmd == "evaluate":
        bbg = next((a.split("=", 1)[1] for a in flags if a.startswith("--bbg=")), None)
        evaluate(pos[0] if pos else os.path.join(ROOT, "docs"), fetch="--fetch" in flags, bbg=bbg)
    else:
        print(__doc__)
