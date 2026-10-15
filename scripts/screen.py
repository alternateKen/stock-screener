#!/usr/bin/env python3
"""Stock Screener: fetch Yahoo Finance data for every stock in themes/*.txt and universe.txt, compute technical
indicators and signals, and write docs/data.json for the pages. Standard library only.
Usage: python scripts/screen.py [output folder, default docs]"""
import json, os, re, sys, time, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/csv,application/json,text/html;q=0.9,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}
WORKERS = 8


def get(url, tries=2, timeout=12):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001
            last = e
            # Yahoo answers 429 when asked too fast: back off longer for that
            time.sleep((4 if "429" in str(e) else 1) * (i + 1))
    raise last


# ---------------- indicators (pure Python, checked against TradingView defaults) ----------------
def sma(xs, n, end=None):
    """Simple moving average of the n values ending at index end (default: the last one)."""
    end = len(xs) if end is None else end + 1
    if end < n:
        return None
    return sum(xs[end - n:end]) / n


def ema_series(xs, n):
    """EMA seeded with the first n-value simple average, as TradingView does. Returns a list aligned to xs (None before seed)."""
    out = [None] * len(xs)
    if len(xs) < n:
        return out
    k = 2 / (n + 1)
    e = sum(xs[:n]) / n
    out[n - 1] = e
    for i in range(n, len(xs)):
        e = xs[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi14(closes):
    """Wilder RSI(14), the same smoothing TradingView uses by default."""
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for a, b in zip(closes, closes[1:]):
        d = b - a
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag, al = sum(gains[:14]) / 14, sum(losses[:14]) / 14
    for g, l in zip(gains[14:], losses[14:]):
        ag, al = (ag * 13 + g) / 14, (al * 13 + l) / 14
    return 100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al)


def macd(closes):
    """MACD(12, 26, 9) -> (macd line list, signal line list), aligned to closes."""
    e12, e26 = ema_series(closes, 12), ema_series(closes, 26)
    line = [a - b if a is not None and b is not None else None for a, b in zip(e12, e26)]
    first = next((i for i, v in enumerate(line) if v is not None), None)
    sig = [None] * len(line)
    if first is not None:
        s = ema_series(line[first:], 9)
        sig[first:] = s
    return line, sig


def atr14(highs, lows, closes):
    """Wilder ATR(14)."""
    if len(closes) < 15:
        return None
    trs = [max(h - l, abs(h - pc), abs(l - pc)) for h, l, pc in zip(highs[1:], lows[1:], closes[:-1])]
    a = sum(trs[:14]) / 14
    for t in trs[14:]:
        a = (a * 13 + t) / 14
    return a


def crossed(a, b, lookback):
    """Days ago (0 = today) that series a crossed series b within the last `lookback` sessions:
    +days for a crossing up through b, -days-1 for crossing down (so 0 and -1 are both 'today'). None if no cross."""
    n = len(a)
    for d in range(lookback):
        i = n - 1 - d
        if i < 1 or None in (a[i], b[i], a[i - 1], b[i - 1]):
            return None
        if a[i - 1] < b[i - 1] and a[i] >= b[i]:
            return d
        if a[i - 1] > b[i - 1] and a[i] <= b[i]:
            return -d - 1
    return None


def sma_series(xs, n):
    out, s = [None] * len(xs), 0.0
    for i, x in enumerate(xs):
        s += x
        if i >= n:
            s -= xs[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def analyse(bars, spx=None, now=None):
    """bars = {"t": [unix], "c": [close], "h": [high], "l": [low], "v": [volume], "last": live price, "time": unix,
    "intraday": bool} -> dict of indicators and signals for one stock."""
    ts, closes, highs, lows, vols = bars["t"], list(bars["c"]), bars["h"], bars["l"], bars["v"]
    if bars.get("last") is not None and closes:
        closes[-1] = bars["last"]
    last = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else None

    def ago(n):
        return closes[-1 - n] if len(closes) > n else None

    def pct(a, b):
        return None if a is None or not b else (a / b - 1) * 100

    now = now or datetime.now(timezone.utc)
    prior = [c for t, c in zip(ts, closes) if datetime.fromtimestamp(t, timezone.utc).year < now.year]
    ytd_base = prior[-1] if prior else (closes[0] if closes else None)
    yr = closes[-252:]
    m50, m200, m20 = sma_series(closes, 50), sma_series(closes, 200), sma_series(closes, 20)
    ml, ms = macd(closes)
    base = sum(vols[-21:-1]) / 20 if len(vols) >= 21 else 0
    vol_x = vols[-1] / base if base and vols[-1] is not None else None
    atr = atr14(highs, lows, closes)
    r = {
        "last": last, "prev": prev, "pct": pct(last, prev), "w1": pct(last, ago(5)), "m1": pct(last, ago(21)),
        "m3": pct(last, ago(63)), "ytd": pct(last, ytd_base),
        "hi52": max(yr), "lo52": min(yr), "ma20": m20[-1], "ma50": m50[-1], "ma200": m200[-1],
        "rsi": rsi14(closes), "macd": ml[-1], "macd_sig": ms[-1],
        "atr_pct": atr / last * 100 if atr and last else None, "vol_x": vol_x,
        "off_hi": pct(last, max(yr)),
        "spark": [round(x, 4) for x in closes[-45:]],
        "asof": datetime.fromtimestamp(bars.get("time") or ts[-1], timezone.utc).isoformat(),
        "intraday": bool(bars.get("intraday")),
    }
    if spx:
        r["rs1"] = None if r["m1"] is None or spx.get("m1") is None else r["m1"] - spx["m1"]
        r["rs3"] = None if r["m3"] is None or spx.get("m3") is None else r["m3"] - spx["m3"]
    # trend score: one point for each bullish condition (0 = every condition bearish, 6 = every one bullish)
    checks = [(r["ma50"], lambda: last > r["ma50"]), (r["ma200"], lambda: last > r["ma200"]),
              (r["ma200"], lambda: r["ma50"] > r["ma200"]), (r["macd_sig"], lambda: r["macd"] > r["macd_sig"]),
              (r["rsi"], lambda: r["rsi"] > 50), (r.get("rs3"), lambda: r["rs3"] > 0)]
    known = [f() for v, f in checks if v is not None]
    r["score"] = sum(known) if len(known) == len(checks) else None

    sig = []
    def add(key, d, text):
        sig.append({"k": key, "d": d, "t": text})
    if len(closes) >= 200:
        prior_yr = closes[-252:-1]
        if last > max(prior_yr):
            add("hi52", 1, "New 52-week high")
        elif last < min(prior_yr):
            add("lo52", -1, "New 52-week low")
    for n, ser, look in ((200, m200, 3), (50, m50, 3)):
        c = crossed(closes, ser, look)
        if c is not None:
            up = c >= 0
            days = c if up else -c - 1
            add(f"x{n}{'u' if up else 'd'}", 1 if up else -1,
                f"Crossed {'above' if up else 'below'} {n}-day{' today' if days == 0 else f' ({days}d ago)'}")
    c = crossed(m50, m200, 5)
    if c is not None:
        up = c >= 0
        days = c if up else -c - 1
        add("golden" if up else "death", 1 if up else -1,
            f"{'Golden' if up else 'Death'} cross (50d {'over' if up else 'under'} 200d){' today' if days == 0 else f', {days}d ago'}")
    c = crossed(ml, ms, 3)
    if c is not None:
        up = c >= 0
        add("macdu" if up else "macdd", 1 if up else -1, f"MACD {'bullish' if up else 'bearish'} cross")
    if r["rsi"] is not None and r["rsi"] >= 70:
        add("rsi70", -1, f"RSI {r['rsi']:.0f} overbought")
    elif r["rsi"] is not None and r["rsi"] <= 30:
        add("rsi30", 1, f"RSI {r['rsi']:.0f} oversold")
    if vol_x is not None and vol_x >= 2 and r["pct"] is not None:
        add("vol", 1 if r["pct"] >= 0 else -1, f"Volume {vol_x:.1f}x average on a {r['pct']:+.1f}% day")
    r["signals"] = sig
    return r


# ---------------- chart files (one per stock, for chart.html) ----------------
def chart_file(k):
    return re.sub(r"[^A-Za-z0-9.-]", "_", k) + ".json"


def chart_payload(b):
    """Two years of daily candles, compact: day start (unix seconds), open, high, low, close, volume.
    The last close is the live price, as everywhere else on the site."""
    sig = lambda x: float(f"{x:.6g}")   # noqa: E731   6 significant digits is plenty for a chart
    c = list(b["c"])
    o, h, l = list(b.get("o") or c), list(b["h"]), list(b["l"])
    if b.get("last") is not None and c:
        c[-1] = b["last"]
        h[-1], l[-1] = max(h[-1], c[-1]), min(l[-1], c[-1])
    return {"t": [t - t % 86400 for t in b["t"]], "o": [sig(x) for x in o], "h": [sig(x) for x in h],
            "l": [sig(x) for x in l], "c": [sig(x) for x in c], "v": [int(x or 0) for x in b["v"]]}


# ---------------- Yahoo ----------------
def yahoo_bars(symbol):
    q = urllib.parse.quote(symbol)
    raw, err = None, None
    for host in ("query1", "query2"):
        try:
            raw = get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{q}?range=2y&interval=1d&includePrePost=false", tries=2)
            break
        except Exception as e:  # noqa: BLE001
            err = e
    if raw is None:
        raise err
    res = json.loads(raw)["chart"]["result"][0]
    meta, quote = res["meta"], res["indicators"]["quote"][0]
    n = len(res["timestamp"])
    vol = quote.get("volume") or [0] * n   # some indices have no volume series
    opens = quote.get("open") or [None] * n
    rows = [(t, c, h, l, v, o) for t, c, h, l, v, o in zip(res["timestamp"], quote["close"], quote["high"], quote["low"], vol, opens)
            if c is not None and h is not None and l is not None]
    if len(rows) < 2:
        raise ValueError("not enough price history")
    reg = (meta.get("currentTradingPeriod") or {}).get("regular") or {}
    tm = meta.get("regularMarketTime", rows[-1][0])
    return {"t": [r[0] for r in rows], "c": [r[1] for r in rows], "h": [r[2] for r in rows], "l": [r[3] for r in rows],
            "v": [r[4] or 0 for r in rows], "o": [r[5] if r[5] is not None else r[1] for r in rows],
            "last": meta.get("regularMarketPrice"), "time": tm,
            "currency": meta.get("currency"), "exch": meta.get("exchangeName"),
            "name": meta.get("longName") or meta.get("shortName"), "intraday": bool(reg) and reg.get("start", 0) <= tm < reg.get("end", 0)}


def news(feed_sym, limit=3):
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={urllib.parse.quote(feed_sym)}&region=US&lang=en-US"
    root = ET.fromstring(get(url, tries=1))
    out = []
    for it in root.iter("item"):
        out.append({"title": (it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip(),
                    "time": (it.findtext("pubDate") or "").strip()})
        if len(out) >= limit:
            break
    return out


# ---------------- ticker codes ----------------
# Bloomberg country suffix -> Yahoo suffixes to try, in order (Taiwan: main board .TW or OTC .TWO; Korea: KOSPI .KS or KOSDAQ .KQ)
BBG_SUFFIX = {"TT": [".TW", ".TWO"], "KS": [".KS", ".KQ"], "KP": [".KS", ".KQ"], "KQ": [".KQ", ".KS"], "KT": [".KQ", ".KS"],
              "JP": [".T"], "JT": [".T"], "HK": [".HK"], "TB": [".BK"], "NO": [".OL"], "LN": [".L"],
              "GR": [".DE"], "GY": [".DE"], "FP": [".PA"], "NA": [".AS"], "SW": [".SW"], "SE": [".SW"], "AU": [".AX"],
              "CN": [".TO"], "IM": [".MI"], "IT": [".MI"], "SM": [".MC"], "SS": [".ST"], "DC": [".CO"], "FH": [".HE"],
              "IN": [".NS"], "IS": [".NS"], "SP": [".SI"]}
US_SUFFIX = ("US", "UN", "UQ", "UW", "UA")
# Yahoo suffix -> TradingView exchange prefix (for the live quotes box)
TV_EXCH = {".TW": "TWSE", ".TWO": "TPEX", ".SZ": "SZSE", ".SS": "SSE", ".T": "TSE", ".HK": "HKEX", ".OL": "OSL",
           ".L": "LSE", ".DE": "XETR", ".PA": "EURONEXT", ".AS": "EURONEXT", ".SW": "SIX", ".KS": "KRX", ".KQ": "KRX",
           ".AX": "ASX", ".TO": "TSX", ".MI": "MIL", ".MC": "BME", ".ST": "OMXSTO", ".CO": "OMXCOP",
           ".HE": "OMXHEX", ".NS": "NSE", ".SI": "SGX", ".BK": "SET"}


def yahoo_candidates(code):
    """'SHOP US' -> (['SHOP'], 'SHOP');  '2345 TT' -> (['2345.TW', '2345.TWO'], '2345 TT');  'BRK/B US' -> (['BRK-B'], 'BRK-B')"""
    code = code.strip().upper()
    m = re.match(r"^(.+?)\s+([A-Z]{2})$", code)
    if not m:
        return [code.replace("/", "-").replace(" ", "")], code
    base, cc = m.group(1).replace(" ", "").rstrip("/").replace("/", "-"), m.group(2)   # "BA/ LN" -> BA.L
    if cc in US_SUFFIX:
        return [base], base
    if cc in ("CH", "C1", "C2"):   # mainland China: 6xxxxx = Shanghai, otherwise Shenzhen
        return [base + (".SS" if base.startswith("6") else ".SZ")], code
    if cc == "HK":
        base = base.lstrip("0").zfill(4)
    return [base + x for x in BBG_SUFFIX.get(cc, [""])], code


# Yahoo exchange codes for US listings -> TradingView exchange prefix
US_EXCH = {"NMS": "NASDAQ", "NGM": "NASDAQ", "NCM": "NASDAQ", "NAS": "NASDAQ", "NYQ": "NYSE", "NYS": "NYSE",
           "PCX": "AMEX", "ASE": "AMEX", "AMX": "AMEX", "BTS": "CBOE", "BATS": "CBOE"}


def tv_symbol(ysym, exch_override="", yahoo_exch=""):
    if not exch_override and yahoo_exch in US_EXCH:
        exch_override = US_EXCH[yahoo_exch]
    for sfx in sorted(TV_EXCH, key=len, reverse=True):
        if ysym.endswith(sfx):
            base, ex = ysym[: -len(sfx)], TV_EXCH[sfx]
            if ex == "HKEX":
                base = base.lstrip("0") or "0"
            return f"{exch_override or ex}:{base}"
    base = ysym.replace("-", ".")   # TradingView writes share classes with a dot (BRK.B)
    return f"{exch_override}:{base}" if exch_override else base


# ---------------- TradingView technical rating ----------------
TV_COLS = ["Recommend.All", "Recommend.MA", "Recommend.Other", "sector", "industry"]


def tv_label(v):
    """TradingView's own buckets for its technical rating (-1 .. +1)."""
    if v is None:
        return None
    return ("Strong buy" if v > 0.5 else "Buy" if v > 0.1 else "Neutral" if v >= -0.1 else "Sell" if v >= -0.5 else "Strong sell")


def tv_ratings(tv_syms, chunk=400):
    """{"NASDAQ:AAPL": {...}} from TradingView's screener endpoint (undocumented, so any failure just leaves the column blank)."""
    out = {}
    syms = sorted({s for s in tv_syms if ":" in s})
    for i in range(0, len(syms), chunk):
        body = json.dumps({"symbols": {"tickers": syms[i:i + chunk], "query": {"types": []}}, "columns": TV_COLS}).encode()
        req = urllib.request.Request("https://scanner.tradingview.com/global/scan", data=body,
                                     headers={**UA, "Content-Type": "application/json", "Origin": "https://www.tradingview.com"})
        with urllib.request.urlopen(req, timeout=25) as r:
            for row in json.loads(r.read()).get("data", []):
                d = dict(zip(TV_COLS, row.get("d", [])))
                out[row["s"]] = {"tvr": d.get("Recommend.All"), "tv_ma": d.get("Recommend.MA"), "tv_osc": d.get("Recommend.Other"),
                                 "tv_sector": d.get("sector"), "tv_industry": d.get("industry")}
    return out


# ---------------- list files ----------------
def read_list(path):
    """A theme or universe file -> {"title", "description", "order", "groups": [{"name", "wiki", "index", "items": [item]}]}
    item = {"cands": [yahoo symbols], "sym": display code, "label": company name, "exch": TradingView exchange override}"""
    out = {"title": None, "description": "", "order": 100, "groups": []}
    cur = None
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip() if line.strip().startswith("@") else line.split("#")[0].strip()
            if not line:
                continue
            if line.startswith("[") and line.endswith("]"):
                cur = {"name": line[1:-1].strip(), "wiki": None, "sources": [], "index": None, "items": []}
                out["groups"].append(cur)
            elif line.startswith("@"):
                key, _, val = line[1:].partition(" ")
                key, val = key.lower(), val.strip()
                if cur is None and key in ("title", "description"):
                    out[key] = val
                elif cur is None and key == "order":
                    out["order"] = int(val) if val.isdigit() else 100
                elif cur is not None and key in ("wikipedia", "source"):   # tried in the order written
                    cur["wiki"] = cur["wiki"] or val
                    cur["sources"].append(val)
                elif cur is not None and key == "index":   # alternatives after commas are tried in order
                    cur["index"] = [v.strip() for v in val.split(",") if v.strip()]
            else:
                if cur is None:
                    cur = {"name": "Watchlist", "wiki": None, "sources": [], "index": None, "items": []}
                    out["groups"].append(cur)
                code, _, rest = line.partition("|")
                name, _, exch = rest.partition("|")
                if code.strip():
                    cands, disp = yahoo_candidates(code)
                    cur["items"].append({"cands": cands, "sym": disp, "label": name.strip() or disp, "exch": exch.strip().upper()})
    return out


class TableCollector(HTMLParser):
    """Collects every HTML table on a page as a list of rows (nested tables handled)."""
    def __init__(self):
        super().__init__()
        self.stack, self.tables = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.stack.append({"rows": [], "row": None, "cell": None})
        elif self.stack:
            t = self.stack[-1]
            if tag == "tr":
                t["row"] = []
            elif tag in ("td", "th") and t["row"] is not None:
                t["cell"] = []
            elif tag == "br" and t["cell"] is not None:
                t["cell"].append(" ")

    def handle_endtag(self, tag):
        if not self.stack:
            return
        t = self.stack[-1]
        if tag == "table":
            self.tables.append(self.stack.pop()["rows"])
        elif tag in ("td", "th") and t["cell"] is not None and t["row"] is not None:
            t["row"].append(" ".join("".join(t["cell"]).split()))
            t["cell"] = None
        elif tag == "tr" and t["row"] is not None:
            if t["row"]:
                t["rows"].append(t["row"])
            t["row"] = None

    def handle_data(self, d):
        if self.stack and self.stack[-1]["cell"] is not None:
            self.stack[-1]["cell"].append(d)


def _clean(x):
    return re.sub(r"\[.*?\]", "", x).strip()


def wikipedia_members(html, min_rows=20):
    """-> [(yahoo symbol, company name, GICS sector or "")]: the largest table on the page with a Symbol / Ticker column."""
    p = TableCollector()
    p.feed(html)
    has = lambda pat: (lambda c: re.search(pat, _clean(c), re.I) is not None)   # noqa: E731
    is_sym, is_name, is_sec = has(r"symbol|ticker"), has(r"security|company|name"), has(r"sector")
    best = []
    for rows in p.tables:
        hi = next((i for i, r in enumerate(rows[:4]) if any(is_sym(c) for c in r)), None)
        if hi is None:
            continue
        head = rows[hi]
        si = next(i for i, c in enumerate(head) if is_sym(c))
        ni = next((i for i, c in enumerate(head) if is_name(c) and i != si), None)
        ci = next((i for i, c in enumerate(head) if is_sec(c) and not re.search(r"sub", c, re.I)), None)
        seen, members = set(), []
        for r in rows[hi + 1:]:
            if len(r) <= si:
                continue
            sym = _clean(r[si]).split(":")[-1].strip().upper().replace(".", "-")
            if re.match(r"^[A-Z][A-Z0-9-]{0,6}$", sym) and sym not in seen:
                seen.add(sym)
                members.append((sym, _clean(r[ni]) if ni is not None and len(r) > ni else sym,
                                _clean(r[ci]) if ci is not None and len(r) > ci else ""))
        if len(members) > len(best):
            best = members
    if len(best) < min_rows:
        best = ticker_column_members(p.tables, min_rows) or best
    if len(best) < min_rows:
        big = sorted(p.tables, key=len, reverse=True)[:3]
        look = "; ".join(f"{len(t)} rows, first row {[_clean(c)[:14] for c in t[0]][:6]}" for t in big if t)
        raise ValueError(f"members table not found (page {len(html)} chars, {len(p.tables)} tables, best {len(best)} rows; largest: {look})")
    return best


TICKER = re.compile(r"^[A-Z]{1,5}([.-][A-Z])?$")


def ticker_column_members(tables, min_rows):
    """Fallback when no header says Symbol/Ticker: the column where most cells look like tickers;
    the company name is the neighbouring column with the longest text."""
    best = []
    for rows in tables:
        body = [r for r in rows if len(r) >= 2]
        if len(body) < min_rows:
            continue
        width = max(len(r) for r in body)
        for ci in range(width):
            vals = [_clean(r[ci]) if ci < len(r) else "" for r in body]
            hits = [i for i, v in enumerate(vals) if TICKER.match(v)]
            if len(hits) < max(min_rows, 0.7 * len(body)):
                continue
            def name_of(r):
                cands = [_clean(c) for j, c in enumerate(r) if j != ci and not TICKER.match(_clean(c))]
                return max(cands, key=len) if cands else ""
            seen, members = set(), []
            for i in hits:
                sym = vals[i].replace(".", "-")
                if sym not in seen:
                    seen.add(sym)
                    members.append((sym, name_of(body[i]) or sym, ""))
            if len(members) > len(best):
                best = members
    return best


def nasdaq_api_members(raw):
    """api.nasdaq.com/api/quote/list-type/nasdaq100 -> [(symbol, name, "")]."""
    d = json.loads(raw)
    rows = ((d.get("data") or {}).get("data") or {}).get("rows") or (d.get("data") or {}).get("rows") or []
    out = [(r["symbol"].strip().upper().replace(".", "-").replace("/", "-"), (r.get("companyName") or r["symbol"]).strip(), "")
           for r in rows if r.get("symbol")]
    if len(out) < 20:
        raise ValueError(f"Nasdaq list had {len(out)} rows")
    return out


def members_from(url):
    """Index members from any source: a JSON list from api.nasdaq.com, or any web page with a ticker table."""
    raw = get(url, tries=2, timeout=25).decode("utf-8", "ignore")
    if raw.lstrip().startswith("{"):
        return nasdaq_api_members(raw)
    return wikipedia_members(raw)


# Used only when Wikipedia cannot be read AND there is no previously published list (approximate membership)
NDX_FALLBACK = ["AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN", "AMZN", "APP", "ARM", "ASML", "AVGO", "AXON",
                "AZN", "BIIB", "BKNG", "BKR", "CCEP", "CDNS", "CDW", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP", "CSX",
                "CTAS", "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC", "FANG", "FAST", "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON",
                "IDXX", "INTC", "INTU", "ISRG", "KDP", "KHC", "KLAC", "LIN", "LRCX", "LULU", "MAR", "MCHP", "MDB", "MDLZ", "MELI", "META",
                "MNST", "MRVL", "MSFT", "MSTR", "MU", "NFLX", "NVDA", "NXPI", "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP",
                "PLTR", "PYPL", "QCOM", "REGN", "ROP", "ROST", "SBUX", "SHOP", "SNPS", "TEAM", "TMUS", "TRI", "TSLA", "TTD", "TTWO", "TXN",
                "VRSK", "VRTX", "WBD", "WDAY", "XEL", "ZS"]
FALLBACKS = {"Nasdaq": NDX_FALLBACK}


def previous_data():
    """The data.json this site published last time, used when Wikipedia cannot be read (GitHub Actions only)."""
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return None
    owner, name = repo.split("/", 1)
    try:
        return json.loads(get(f"https://{owner.lower()}.github.io/{name}/data.json", tries=1))
    except Exception:  # noqa: BLE001
        return None


def fill_universe(universe, errors):
    """Load index members for every universe group with @wikipedia / @source lines, trying each source in order,
    then the list published last time, then a built-in list. GICS sectors come from Wikipedia when it is readable."""
    prev = None
    for g in universe["groups"]:
        if not g["sources"]:
            continue
        fails = []
        for i, src in enumerate(g["sources"]):
            try:
                members = members_from(src)
                g["items"] = [{"cands": [s], "sym": s, "label": n, "exch": "", "sector": sec} for s, n, sec in members]
                if fails:
                    errors.append(f"{g['name']}: {'; '.join(fails)}; used {host(src)} instead ({len(members)} members)")
                break
            except Exception as e:  # noqa: BLE001
                fails.append(f"{host(src)} unreadable ({e})")
        else:
            if prev is None:
                prev = previous_data() or {}
            old = next((u for u in prev.get("universe", []) if u["name"] == g["name"]), None)
            fb = next((v for k, v in FALLBACKS.items() if k.lower() in g["name"].lower()), None)
            if old:
                g["items"] = [{"cands": [i["k"]], "sym": i["sym"], "label": i["label"], "exch": "", "sector": i.get("sector", "")}
                              for i in old["items"]]
                errors.append(f"{g['name']}: {'; '.join(fails)}; reused last published member list")
            elif fb:
                g["items"] = [{"cands": [s], "sym": s, "label": s, "exch": "", "sector": ""} for s in fb]
                errors.append(f"{g['name']}: {'; '.join(fails)}; used the built-in member list")
            else:
                errors.append(f"{g['name']}: {'; '.join(fails)}; group skipped")


def host(url):
    return urllib.parse.urlparse(url).netloc or url


def borrow_sectors(universe):
    """Members loaded from a source without sectors (e.g. Nasdaq's list) take the GICS sector of the same stock
    in another group (the S&P 500 from Wikipedia)."""
    known = {it["k"] if "k" in it else it["cands"][0]: it.get("sector") for g in universe["groups"] for it in g["items"] if it.get("sector")}
    for g in universe["groups"]:
        for it in g["items"]:
            if not it.get("sector") and it["cands"][0] in known:
                it["sector"] = known[it["cands"][0]]


# ---------------- Bloomberg consensus (written by bloomberg/bbg_sync.py on the Bloomberg PC) ----------------
def load_consensus(stocks, errors, path=None):
    """Merge data/bloomberg_consensus.json (derived numbers only) into the stocks as r["st"]. Returns its as-of time or None."""
    path = path or os.path.join(ROOT, "data", "bloomberg_consensus.json")
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            c = json.load(f)
    except Exception as e:  # noqa: BLE001
        errors.append(f"Bloomberg consensus file unreadable: {e}")
        return None
    n = 0
    for k, rec in (c.get("stocks") or {}).items():
        if k in stocks:
            stocks[k]["st"] = rec
            n += 1
    print(f"Bloomberg consensus for {n} stocks (as of {c.get('asof')})")
    return c.get("asof")


# ---------------- build ----------------
def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def build(out_dir, fetch=yahoo_bars, fetch_news=news, load_universe=True, fetch_tv=tv_ratings):
    errors = []
    theme_files = sorted(f for f in os.listdir(os.path.join(ROOT, "themes")) if f.endswith(".txt"))
    themes = []
    for f in theme_files:
        t = read_list(os.path.join(ROOT, "themes", f))
        t["slug"] = slug(f[:-4])
        t["title"] = t["title"] or f[:-4].replace("-", " ").title()
        if any(g["items"] for g in t["groups"]):
            themes.append(t)
    themes.sort(key=lambda t: (t["order"], t["title"]))
    universe = read_list(os.path.join(ROOT, "universe.txt"))
    if load_universe:
        fill_universe(universe, errors)
        borrow_sectors(universe)

    # every stock is fetched once, however many themes and universes it is in
    jobs = {}
    for coll, with_news in ((themes, True), ([universe], False)):
        for t in coll:
            for g in t["groups"]:
                for it in g["items"]:
                    k = it["cands"][0]
                    it["k"] = k
                    jobs.setdefault(k, {"cands": it["cands"], "news": False})
                    jobs[k]["news"] |= with_news
    idx_syms = {tuple(g["index"]) for g in universe["groups"] if g["index"]} | {("^GSPC",)}

    def one(k):
        last = None
        for c in jobs[k]["cands"]:
            try:
                b = fetch(c)
                b["ysym"] = c
                return k, b, None
            except Exception as e:  # noqa: BLE001
                last = e
        return k, None, f"{k}: {last}"

    def one_news(k):
        try:
            return k, fetch_news(k)
        except Exception:  # noqa: BLE001   headlines are optional (often missing for non-US names)
            return k, []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        idx = {s: b for s, b, e in ex.map(lambda s: (s, *one_idx(s, fetch)), sorted(idx_syms))}
        raw = list(ex.map(one, list(jobs)))
        hl = dict(ex.map(one_news, [k for k, j in jobs.items() if j["news"]]))
    spx_b = idx.get(("^GSPC",))
    spx = analyse(spx_b) if spx_b else None
    if not spx:
        errors.append("S&P 500 reference unavailable: relative strength columns are blank")
    stocks, missing, charts = {}, 0, {}
    for k, b, err in raw:
        if err:
            missing += 1
            errors.append(err)
            continue
        try:
            r = analyse(b, spx)
        except Exception as e:  # noqa: BLE001
            missing += 1
            errors.append(f"{k}: {e}")
            continue
        r["ysym"], r["cur"], r["exch"], r["name"] = b["ysym"], b.get("currency"), b.get("exch"), b.get("name")
        charts[k] = chart_payload(b)
        if k in hl:
            r["news"] = hl[k]
        stocks[k] = r
    print(f"fetched {len(stocks)}/{len(jobs)} stocks in {time.time() - t0:.0f}s")
    street = load_consensus(stocks, errors)
    # TradingView's technical rating, as a second opinion next to our own indicators
    overrides = {it["k"]: it["exch"] for coll in (themes, [universe]) for t in coll for g in t["groups"] for it in g["items"] if it["exch"]}
    for k, r in stocks.items():
        r["tvs"] = tv_symbol(r["ysym"], overrides.get(k, ""), r.get("exch") or "")
    try:
        tv = fetch_tv([r["tvs"] for r in stocks.values()])
        for r in stocks.values():
            x = tv.get(r["tvs"])
            if x:
                r.update(x)
                r["tv_label"] = tv_label(x["tvr"])
        print(f"TradingView ratings for {sum(1 for r in stocks.values() if r.get('tv_label'))}/{len(stocks)} stocks")
    except Exception as e:  # noqa: BLE001
        errors.append(f"TradingView ratings unavailable this run: {e}")
    if len(stocks) < max(1, len(jobs) // 2):
        for e in errors[:15]:
            print("WARN", e)
        print("Fewer than half the stocks could be fetched; keeping the previously published data.", file=sys.stderr)
        sys.exit(1)

    named = {}

    def items(g, with_sector=False):
        out = []
        for it in g["items"]:
            st = stocks.get(it["k"], {})
            label = it["label"]
            if label == it["sym"] and st.get("name"):   # no name in the theme file: use the company name from Yahoo
                label = st["name"]
                named[it["sym"]] = label
            row = {"k": it["k"], "sym": it["sym"], "label": label,
                   "tv": st.get("tvs") or tv_symbol(it["cands"][0], it["exch"])}
            if with_sector:
                row["sector"] = it.get("sector") or g["name"]
            out.append(row)
        return out

    data = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "spx": {k: spx.get(k) for k in ("last", "pct", "w1", "m1", "m3", "ytd", "intraday")} if spx else {},
        "themes": [{"slug": t["slug"], "title": t["title"], "description": t["description"],
                    "groups": [{"name": g["name"], "items": items(g)} for g in t["groups"] if g["items"]]} for t in themes],
        "universe": [{"name": g["name"], "index": (g["index"] or [None])[0], "items": items(g, True),
                      "index_q": ({k: v for k, v in analyse(idx[tuple(g["index"])]).items() if k in ("last", "pct", "m1", "m3", "ytd")}
                                  if g["index"] and idx.get(tuple(g["index"])) else None)}
                     for g in universe["groups"] if g["items"]],
        "stocks": stocks,
        "street_asof": street,
        "errors": errors,
    }
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "data.json")
    with open(path, "w") as f:
        json.dump(data, f, separators=(",", ":"), default=lambda x: None)
    cdir = os.path.join(out_dir, "charts")
    os.makedirs(cdir, exist_ok=True)
    for f in os.listdir(cdir):   # drop charts of stocks no longer on any list
        if f.endswith(".json"):
            os.remove(os.path.join(cdir, f))
    for k, cp in charts.items():
        with open(os.path.join(cdir, chart_file(k)), "w") as f:
            json.dump(cp, f, separators=(",", ":"))
    nsig = sum(len(s["signals"]) for s in stocks.values())
    print(f"wrote {path}: {len(themes)} themes, {sum(len(u['items']) for u in data['universe'])} universe names, "
          f"{len(stocks)} stocks with data, {missing} without, {nsig} signals")
    for e in errors:
        print("WARN", e)
    if named:   # tickers added without a company name: shown here so they can be named in the theme file if wanted
        print(f"named from Yahoo ({len(named)}): " + "; ".join(f"{k} = {v}" for k, v in sorted(named.items())))
    return data


def one_idx(cands, fetch):
    err = None
    for sym in cands:
        try:
            return fetch(sym), None
        except Exception as e:  # noqa: BLE001
            err = str(e)
    return None, err


if __name__ == "__main__":
    build(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "docs"))
