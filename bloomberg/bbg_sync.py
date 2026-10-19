"""Bloomberg -> GitHub daily sync for the macro dashboard and the stock screener.

Runs on the PC where you are logged in to Bloomberg. Windows Task Scheduler starts it every 15 minutes;
each time it:
  1. stops at once outside the window (weekdays 07:00-21:00 on this PC's clock) or if no slot is due,
  2. stops quietly if Bloomberg is not logged in (it never logs in for you and never sees your password),
  3. otherwise fetches what is due and uploads it to GitHub in ONE commit per repository.

Slots (this PC's clock): 08:30, 16:30, 20:00. Each slot runs once, the first time you are logged in after it.
  every slot      : Fed pricing (WIRP-style, from fed funds futures), CDX / iTraxx, US economic calendar
  once a day      : screener consensus (upside to target, % buy ratings, EPS revisions) - derived numbers only
  once a week     : index weights for the top-movers cards

Usage
  python bbg_sync.py --test    fetch everything now, save files in a folder on the Desktop, print a report. Uploads NOTHING.
  python bbg_sync.py --now     fetch everything now and upload (ignores the window and the slots)
  python bbg_sync.py           what Task Scheduler runs (window + slots + login check)

Needs: the blpapi package and a GitHub token in %USERPROFILE%\\bbg_sync\\token.txt (see SETUP.md). Standard library otherwise."""
import base64, calendar, csv, io, json, os, re, sys, time, traceback, urllib.request, urllib.error
from datetime import date, datetime, timedelta

# ---------------- settings ----------------
OWNER = "alternateKen"
MACRO_REPO, SCREENER_REPO = "macro-updates", "stock-screener"
WINDOW = ("07:00", "21:00")            # this PC's clock; weekdays only
SLOTS = ["08:30", "16:30", "20:00"]
WEIGHTS_EVERY_DAYS = 7
WEIGHT_INDICES = {                     # macro-updates weights/<file>  <-  Bloomberg index
    "dow.csv": "INDU Index", "spx.csv": "SPX Index", "ndx.csv": "NDX Index", "hshares.csv": "HSCEI Index",
    "ashares.csv": "SHSZ300 Index", "taiex.csv": "TWSE Index", "kospi.csv": "KOSPI Index",
}
HOME = os.path.join(os.path.expanduser("~"), "bbg_sync")          # token.txt lives here
STATE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", HOME), "bbg_sync")
HERE = os.path.dirname(os.path.abspath(__file__))

REPORT = []


def say(line):
    REPORT.append(line)
    print(line)


def log(msg):
    os.makedirs(STATE_DIR, exist_ok=True)
    path = os.path.join(STATE_DIR, "sync.log")
    if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
        os.replace(path, path + ".old")
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")


def load_state():
    try:
        with open(os.path.join(STATE_DIR, "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def save_state(st):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, "state.json"), "w", encoding="utf-8") as f:
        json.dump(st, f, indent=1)


# ---------------- Bloomberg ----------------
class Bbg:
    """Thin wrapper over the Desktop API (the Terminal on this PC, localhost:8194)."""

    def __init__(self):
        import blpapi
        self.b = blpapi
        o = blpapi.SessionOptions()
        o.setServerHost("localhost")
        o.setServerPort(8194)
        for name, val in (("setConnectTimeout", 4000), ("setNumStartAttempts", 1), ("setAutoRestartOnDisconnection", False)):
            if hasattr(o, name):
                getattr(o, name)(val)
        self.s = blpapi.Session(o)
        if not self.s.start():
            raise ConnectionError("Bloomberg Terminal not reachable on this PC")
        if not self.s.openService("//blp/refdata"):
            raise ConnectionError("Bloomberg refused the data service")
        self.svc = self.s.getService("//blp/refdata")

    def close(self):
        try:
            self.s.stop()
        except Exception:  # noqa: BLE001
            pass

    def _send(self, req, timeout_ms=30000):
        self.s.sendRequest(req)
        msgs = []
        while True:
            ev = self.s.nextEvent(timeout_ms)
            for m in ev:
                msgs.append(m)
            if ev.eventType() == self.b.Event.RESPONSE:
                return msgs
            if ev.eventType() == self.b.Event.TIMEOUT:
                raise TimeoutError("Bloomberg did not answer in time")

    @staticmethod
    def _value(el):
        try:
            return el.getValue()
        except Exception:  # noqa: BLE001
            try:
                return el.getValueAsString()
            except Exception:  # noqa: BLE001
                return None

    def _bulk(self, el):
        rows = []
        for i in range(el.numValues()):
            row = el.getValueAsElement(i)
            rows.append({str(row.getElement(j).name()): self._value(row.getElement(j)) for j in range(row.numElements())})
        return rows

    def ref(self, securities, fields, overrides=None, chunk=200):
        """-> ({security: {field: value}}, {security or security|field: error message})"""
        data, errs = {}, {}
        securities = list(dict.fromkeys(securities))
        for i in range(0, len(securities), chunk):
            req = self.svc.createRequest("ReferenceDataRequest")
            for s in securities[i:i + chunk]:
                req.append("securities", s)
            for f in fields:
                req.append("fields", f)
            for k, v in (overrides or {}).items():
                o = req.getElement("overrides").appendElement()
                o.setElement("fieldId", k)
                o.setElement("value", v)
            for m in self._send(req):
                if not m.hasElement("securityData"):
                    if m.hasElement("responseError"):
                        errs["request"] = str(m.getElement("responseError"))
                    continue
                arr = m.getElement("securityData")
                for j in range(arr.numValues()):
                    sd = arr.getValueAsElement(j)
                    sec = sd.getElementAsString("security")
                    if sd.hasElement("securityError"):
                        errs[sec] = sd.getElement("securityError").getElementAsString("message")
                        continue
                    if sd.hasElement("fieldExceptions"):
                        fx = sd.getElement("fieldExceptions")
                        for k in range(fx.numValues()):
                            e = fx.getValueAsElement(k)
                            errs[f"{sec}|{e.getElementAsString('fieldId')}"] = e.getElement("errorInfo").getElementAsString("message")
                    fd = sd.getElement("fieldData")
                    row = {}
                    for k in range(fd.numElements()):
                        el = fd.getElement(k)
                        row[str(el.name())] = self._bulk(el) if el.isArray() else self._value(el)
                    data[sec] = row
        return data, errs

    def hist(self, securities, fields, start, end=None, overrides=None, chunk=100):
        """-> ({security: [(date, {field: value})]}, errors)"""
        data, errs = {}, {}
        securities = list(dict.fromkeys(securities))
        for i in range(0, len(securities), chunk):
            req = self.svc.createRequest("HistoricalDataRequest")
            for s in securities[i:i + chunk]:
                req.append("securities", s)
            for f in fields:
                req.append("fields", f)
            req.set("startDate", start.strftime("%Y%m%d"))
            req.set("endDate", (end or date.today()).strftime("%Y%m%d"))
            req.set("periodicitySelection", "DAILY")
            for k, v in (overrides or {}).items():
                o = req.getElement("overrides").appendElement()
                o.setElement("fieldId", k)
                o.setElement("value", v)
            for m in self._send(req, 60000):
                if not m.hasElement("securityData"):
                    continue
                sd = m.getElement("securityData")
                sec = sd.getElementAsString("security")
                if sd.hasElement("securityError"):
                    errs[sec] = sd.getElement("securityError").getElementAsString("message")
                    continue
                fd = sd.getElement("fieldData")
                rows = data.setdefault(sec, [])
                for k in range(fd.numValues()):
                    p = fd.getValueAsElement(k)
                    d = p.getElementAsDatetime("date")
                    rows.append((date(d.year, d.month, d.day),
                                 {str(p.getElement(j).name()): self._value(p.getElement(j)) for j in range(p.numElements())}))
        return data, errs


def logged_in(bbg):
    """One tiny request: a real S&P 500 price means the Terminal is logged in and serving data."""
    try:
        d, _ = bbg.ref(["SPX Index"], ["PX_LAST"])
        v = d.get("SPX Index", {}).get("PX_LAST")
        return isinstance(v, (int, float)) and v > 0
    except Exception:  # noqa: BLE001
        return False


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def as_date(v):
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y%m%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                return datetime.strptime(v[:19] if "T" in v else v[:10], fmt).date()
            except ValueError:
                continue
    return None


def csv_text(meta, header, rows):
    out = io.StringIO()
    for k, v in meta:
        out.write(f"# {k}: {v}\n")
    w = csv.writer(out, lineterminator="\n")
    w.writerow(header)
    w.writerows(rows)
    return out.getvalue()


def f3(x, d=3):
    return "" if x is None else f"{x:.{d}f}"


# ---------------- datasets ----------------
def fed_pricing(bbg, gh):
    """WIRP-style Fed pricing from fed funds futures (the CME FedWatch method) -> macro-updates bloomberg/wirp_us.csv."""
    d, errs = bbg.ref(["FDTR Index", "FEDL01 Index"], ["PX_LAST"])
    target, eff = num(d.get("FDTR Index", {}).get("PX_LAST")), num(d.get("FEDL01 Index", {}).get("PX_LAST"))
    if eff is None:
        raise ValueError(f"effective fed funds (FEDL01 Index) unavailable {errs}")
    futs = [f"FF{i} Comdty" for i in range(1, 25)]
    fd, ferr = bbg.ref(futs, ["PX_LAST", "LAST_TRADEABLE_DT"])
    avg = {}
    for s in futs:
        px, ltd = num(fd.get(s, {}).get("PX_LAST")), as_date(fd.get(s, {}).get("LAST_TRADEABLE_DT"))
        if px and ltd:
            avg[(ltd.year, ltd.month)] = 100 - px
    if len(avg) < 6:
        raise ValueError(f"fed funds futures unavailable ({len(avg)} months) {list(ferr.items())[:3]}")
    meetings = fomc_dates(bbg, gh)
    meetings = sorted(m for m in meetings if m >= date.today() and (m.year, m.month) in avg)
    if not meetings:
        raise ValueError("no FOMC meeting dates found")
    months = sorted(avg)
    by_month = {(m.year, m.month): m for m in meetings}
    rows, pre, prev_cum = [], eff, 0.0
    for i, ym in enumerate(months):
        a = avg[ym]
        nxt = months[i + 1] if i + 1 < len(months) else None
        if ym in by_month:
            day = by_month[ym].day
            n = calendar.monthrange(*ym)[1]
            if n - day < 7 and nxt and nxt not in by_month:
                post = avg[nxt]                       # meeting late in the month: next month's contract is cleaner
            else:
                post = (a * n - pre * day) / (n - day) if n > day else a
            cum = (post - eff) / 0.25
            rows.append([by_month[ym].isoformat(), f3(cum), f"{(cum - prev_cum) * 100:.1f}", f3(post - eff), f3(post)])
            pre, prev_cum = post, cum
        else:
            pre = a                                   # no meeting: the month's average is the rate in force
    meta = [("source", "Bloomberg fed funds futures FF1-FF24 Comdty, meeting-by-meeting implied rates (WIRP method), automatic sync"),
            ("asof", date.today().isoformat()), ("target", f3(target, 2) if target else ""), ("effective", f3(eff, 2)),
            ("note", "cum = cumulative hikes (+) or cuts (-) priced from today; pct = % chance of a hike (+) or cut (-) at that meeting")]
    say(f"  [OK]  Fed pricing: {len(rows)} meetings, next {rows[0][0]} {rows[0][2]}% (target {target}, effective {eff})")
    return {"bloomberg/wirp_us.csv": csv_text(meta, ["meeting", "cum", "pct", "imp_change", "implied_rate"], rows)}


def fomc_dates(bbg, gh):
    """FOMC decision dates: Bloomberg's release calendar for FDTR Index (if it answers), plus fomc_dates.csv
    (the Fed's published schedule, editable), plus the dates already in wirp_us.csv."""
    out = set()
    try:
        d, _ = bbg.ref(["FDTR Index"], ["ECO_FUTURE_RELEASE_DATE_LIST"],
                       overrides={"START_DT": date.today().strftime("%Y%m%d"),
                                  "END_DT": (date.today() + timedelta(days=800)).strftime("%Y%m%d")})
        for row in d.get("FDTR Index", {}).get("ECO_FUTURE_RELEASE_DATE_LIST") or []:
            for v in row.values():
                dd = as_date(v)
                if dd:
                    out.add(dd)
                    break
    except Exception as e:  # noqa: BLE001
        log(f"FOMC calendar from Bloomberg failed: {e}")
    src = "Bloomberg" if out else ""
    try:
        out |= {as_date(r["meeting"]) for r in read_config("fomc_dates.csv")} - {None}
        src = src or "fomc_dates.csv"
    except Exception as e:  # noqa: BLE001
        log(f"fomc_dates.csv unreadable: {e}")
    if gh:
        try:
            txt = gh.read(MACRO_REPO, "bloomberg/wirp_us.csv")
            out |= {as_date(m) for m in re.findall(r"^(\d{4}-\d{2}-\d{2}),", txt, re.M)} - {None}
        except Exception:  # noqa: BLE001
            pass
    if src != "Bloomberg":
        say(f"  [..]  FOMC dates from {src or 'wirp_us.csv'} (Bloomberg's calendar field did not answer; add new dates to fomc_dates.csv when the Fed publishes them)")
    return out


def read_config(name):
    with open(os.path.join(HERE, name), encoding="utf-8") as f:
        return [r for r in csv.DictReader(line for line in f if line.strip() and not line.startswith("#"))]


def credit(bbg):
    """CDX / iTraxx levels with 3-month context -> macro-updates bloomberg/credit.csv (tickers in credit_tickers.csv)."""
    cfg = read_config("credit_tickers.csv")
    cands = {c["index"]: [t.strip() for t in c["ticker"].split("|") if t.strip()] for c in cfg}
    h, errs = bbg.hist([t for ts in cands.values() for t in ts], ["PX_LAST"], date.today() - timedelta(days=100))
    rows, bad = [], []
    for c in cfg:
        pts, used = [], None
        for t in cands[c["index"]]:
            pts = [p for p in (num(v.get("PX_LAST")) for _, v in h.get(t, [])) if p is not None]
            if len(pts) >= 2:
                used = t
                break
        if not used:
            bad.append(f"{c['index']} (tried {' / '.join(cands[c['index']])})")
            continue
        if len(cands[c["index"]]) > 1:
            say(f"  [..]    {c['index']}: using {used}")
        q = pts[-63:]
        lvl, avg_ = pts[-1], sum(q) / len(q)
        rows.append([c["group"], c["index"], f"{lvl:.2f}", f"{lvl - pts[-2]:.2f}", "", "", f"{min(q):.1f}", f"{max(q):.1f}",
                     f"{avg_:.1f}", f"{lvl - avg_:.1f}", f"{lvl - q[0]:.1f}", c["quote"]])
    say(f"  [{'OK' if rows else '!!'}]  Credit: {len(rows)} of {len(cfg)} indices")
    for b in bad:
        say(f"  [!!]    not found: {b}  -> fix the ticker in credit_tickers.csv")
    if not rows:
        return {}
    meta = [("source", "Bloomberg API, generic 5Y on-the-run CDX / iTraxx (3 months of history), automatic sync"),
            ("asof", date.today().isoformat()),
            ("note", "quote = spread (bp) or price. For price-quoted indices a FALLING price means spreads WIDENED. basis and roll are not available by API")]
    return {"bloomberg/credit.csv": csv_text(meta, ["group", "index", "level", "chg", "basis", "roll", "low", "high", "avg", "vs_avg", "chg_3m", "quote"], rows)}


ECO_FIELDS = ["ECO_RELEASE_DT", "ECO_RELEASE_TIME", "BN_SURVEY_MEDIAN", "PX_LAST", "OBSERVATION_PERIOD"]


def eco(bbg, state):
    """US economic calendar (next 14 days, plus the last 7 days with actuals) -> macro-updates bloomberg/eco.csv."""
    cfg = read_config("eco_tickers.csv")
    d, errs = bbg.ref([c["ticker"] for c in cfg], ECO_FIELDS)
    cache = state.setdefault("eco", {})         # ticker -> the upcoming release we saw last time
    done = state.setdefault("eco_done", [])     # releases that already happened, kept 7 days
    today, rows, bad = date.today(), [], []
    for c in cfg:
        v = d.get(c["ticker"])
        if not v:
            bad.append(f"{c['event']} ({c['ticker']}): {errs.get(c['ticker'], 'no data')}")
            continue
        rel = as_date(v.get("ECO_RELEASE_DT"))
        tm = str(v.get("ECO_RELEASE_TIME") or "")[:5] or "00:00"
        cur = {"date": rel.isoformat() if rel else "", "time": tm, "event": c["event"], "period": str(v.get("OBSERVATION_PERIOD") or ""),
               "survey": fmt_eco(v.get("BN_SURVEY_MEDIAN")), "prior": fmt_eco(v.get("ACTUAL_RELEASE") if v.get("ACTUAL_RELEASE") is not None else v.get("PX_LAST"))}
        old = cache.get(c["ticker"])
        if old and old.get("date") and cur["date"] and old["date"] < cur["date"]:
            # the release we saw last time has happened: its actual is now Bloomberg's latest value
            done.append({**old, "actual": cur["prior"]})
        cache[c["ticker"]] = cur
        if rel and today <= rel <= today + timedelta(days=14):
            rows.append(cur)
    week_ago = (today - timedelta(days=7)).isoformat()
    state["eco_done"] = [r for r in done if r["date"] >= week_ago]
    allr = state["eco_done"] + [{**r, "actual": ""} for r in rows]
    allr.sort(key=lambda r: (r["date"], r["time"], r["event"]))
    tz = datetime.now().astimezone().strftime("%z")
    tz = f"{tz[:3]}:{tz[3:]}"
    say(f"  [{'OK' if allr else '!!'}]  Economic calendar: {len(rows)} upcoming releases, {len(state['eco_done'])} recent with actuals")
    sample = next((r for r in rows if "CPI" in r["event"]), rows[0] if rows else None)
    if sample:
        say(f"  [..]    check against ECO <GO>: {sample['event']} {sample['period']} on {sample['date']} at {sample['time']} "
            f"(this PC's clock, UTC{tz}), survey {sample['survey'] or 'n/a'}, prior {sample['prior'] or 'n/a'}")
    for b in bad:
        say(f"  [!!]    not found: {b}  -> fix the ticker in eco_tickers.csv")
    missing = sorted({k.split('|')[1] for k in errs if '|' in k})
    if missing:
        say(f"  [!!]    fields Bloomberg did not recognise: {', '.join(missing)}")
    if not allr:
        return {}
    meta = [("source", "Bloomberg API, US economic releases (tickers in eco_tickers.csv), automatic sync"), ("asof", today.isoformat()),
            ("timezone", tz), ("note", "times are this PC's clock; survey = Bloomberg median; the page converts to New York time")]
    return {"bloomberg/eco.csv": csv_text(meta, ["datetime", "event", "period", "survey", "actual", "prior", "revised"],
                                          [[f"{r['date']} {r['time']}", r["event"], r["period"], r["survey"], r.get("actual", ""), r["prior"], ""]
                                           for r in allr])}


def fmt_eco(v):
    x = num(v)
    if x is None:
        return "" if v is None else str(v)
    return f"{x:,.3f}".rstrip("0").rstrip(".")


KEEP_TOP = {"dow.csv": 30, "spx.csv": 600, "ndx.csv": 110}   # US indices in full; others: the 100 largest (README: 60-100 is plenty)


def norm_ticker(t):
    """Bloomberg member code -> the style the dashboards read: Korean exchange codes KP / KQ -> KS (KOSPI / KOSDAQ both tried)."""
    t = str(t).strip()
    return re.sub(r"\s+(KP|KQ)$", " KS", t)


def member_rows(rows):
    """INDX_MWEIGHT rows -> [(ticker, weight)]. The weight is the column named like 'Percentage Weight'."""
    out = []
    for r in rows:
        tick = next((v for k, v in r.items() if "ticker" in k.lower() or "member" in k.lower()), None)
        wk = next((k for k in r if "percent" in k.lower()), None) or next((k for k in r if "weight" in k.lower()), None)
        w = num(r.get(wk)) if wk else None
        if tick:
            out.append((norm_ticker(tick), w))
    return out


def weights(bbg):
    """Index weights -> macro-updates weights/*.csv (read by the top-movers cards).
    Official weights (INDX_MWEIGHT) when Bloomberg provides them; some index providers do not allow their weights to be
    sent (they come back as zeros), and then the weights are computed from free-float market caps of the members."""
    files, members = {}, {}
    d, errs = bbg.ref(list(WEIGHT_INDICES.values()), ["INDX_MWEIGHT"])
    for fname, idx in WEIGHT_INDICES.items():
        raw = d.get(idx, {}).get("INDX_MWEIGHT") or []
        mem = member_rows(raw)
        if not mem:
            say(f"  [!!]  Weights {idx}: no members returned ({errs.get(idx) or errs.get(idx + '|INDX_MWEIGHT') or 'empty'})")
            continue
        members[fname] = [t for t, _ in mem]
        total = sum(w for _, w in mem if w and w > 0)
        if 50 <= total <= 150:
            method = "official index weights (INDX_MWEIGHT)"
        else:
            if raw:
                log(f"{idx} INDX_MWEIGHT first row: {raw[0]}")
            mem, method = cap_weights(bbg, [t for t, _ in mem], idx == "INDU Index")
            if not mem:
                say(f"  [!!]  Weights {idx}: official weights not provided and market caps unavailable")
                continue
        mem.sort(key=lambda x: -x[1])
        keep = KEEP_TOP.get(fname, 100)
        cover = sum(w for _, w in mem[:keep])
        files[fname] = (mem[:keep], method, cover)
    allm = sorted({t for mem, _, _ in files.values() for t, _ in mem})
    nm, _ = bbg.ref([t + " Equity" for t in allm], ["NAME"]) if allm else ({}, {})
    out = {}
    for fname, (mem, method, cover) in files.items():
        rows = [[t, (nm.get(t + " Equity", {}).get("NAME") or t), f"{w:.4f}"] for t, w in mem]
        out[f"weights/{fname}"] = csv_text([("source", f"Bloomberg API {WEIGHT_INDICES[fname]}: {method}, automatic sync"),
                                            ("asof", date.today().isoformat())], ["Ticker", "Name", "% Weight"], rows)
        tag = "official" if method.startswith("official") else "free-float cap"
        say(f"  [OK]  Weights {WEIGHT_INDICES[fname]} ({tag}): top {len(rows)} members = {cover:.0f}% of the index, "
            f"largest {rows[0][0]} {float(rows[0][2]):.2f}%")
    return out, members


def cap_weights(bbg, tickers, price_weighted=False):
    """Weights from Bloomberg data when official weights are not provided: free-float market cap share
    (CUR_MKT_CAP x EQY_FREE_FLOAT_PCT), or the price share for a price-weighted index (the Dow)."""
    fields = ["PX_LAST"] if price_weighted else ["CUR_MKT_CAP", "EQY_FREE_FLOAT_PCT"]
    d, _ = bbg.ref([t + " Equity" for t in tickers], fields)
    vals = []
    for t in tickers:
        v = d.get(t + " Equity", {})
        if price_weighted:
            x = num(v.get("PX_LAST"))
        else:
            cap, ff = num(v.get("CUR_MKT_CAP")), num(v.get("EQY_FREE_FLOAT_PCT"))
            x = cap * (ff / 100 if ff and 0 < ff <= 100 else 1) if cap else None
        if x and x > 0:
            vals.append((t, x))
    tot = sum(x for _, x in vals)
    if not tot:
        return [], ""
    method = ("price-weighted share of member prices" if price_weighted
              else "computed from free-float market caps (official weights not provided by the index licence)")
    return [(t, x / tot * 100) for t, x in vals], method


# ---------------- screener consensus ----------------
BBG_SFX = {".TW": "TT", ".TWO": "TT", ".HK": "HK", ".T": "JP", ".KS": "KS", ".KQ": "KQ", ".SS": "CH", ".SZ": "CH", ".L": "LN",
           ".DE": "GY", ".PA": "FP", ".AS": "NA", ".SW": "SW", ".OL": "NO", ".AX": "AU", ".TO": "CN", ".MI": "IM", ".MC": "SM",
           ".ST": "SS", ".CO": "DC", ".HE": "FH", ".NS": "IN", ".SI": "SP"}
US_SFX = ("US", "UN", "UQ", "UW", "UA", "UR", "UV", "UP")


def yahoo_key(code):
    """Same rule as scripts/screen.py yahoo_candidates()[0]: '2330 TT' -> '2330.TW', 'BRK/B US' -> 'BRK-B', '700 HK' -> '0700.HK'."""
    code = code.strip().upper()
    m = re.match(r"^(.+?)\s+([A-Z][A-Z0-9])$", code)
    if not m:
        return code.replace("/", "-").replace(" ", "")
    base, cc = m.group(1).replace(" ", "").rstrip("/").replace("/", "-"), m.group(2)
    if cc in US_SFX:
        return base
    if cc in ("CH", "C1", "C2"):
        return base + (".SS" if base.startswith("6") else ".SZ")
    if cc == "HK":
        base = base.lstrip("0").zfill(4)
    rev = {"TT": ".TW", "HK": ".HK", "JP": ".T", "JT": ".T", "KS": ".KS", "KQ": ".KQ", "KP": ".KS", "KT": ".KQ", "TB": ".BK", "LN": ".L", "GY": ".DE", "GR": ".DE",
           "FP": ".PA", "NA": ".AS", "SW": ".SW", "SE": ".SW", "NO": ".OL", "AU": ".AX", "CN": ".TO", "IM": ".MI", "IT": ".MI",
           "SM": ".MC", "SS": ".ST", "DC": ".CO", "FH": ".HE", "IN": ".NS", "IS": ".NS", "SP": ".SI"}
    return base + rev.get(cc, "")


def bbg_code(code):
    """A line from a theme file ('NVDA', 'BRK/B US', '0700 HK', '600519 CH') -> Bloomberg security ('NVDA US Equity', ...)."""
    code = code.strip().upper()
    m = re.match(r"^(.+?)\s+([A-Z][A-Z0-9])$", code)
    if not m:
        return code.replace("-", "/") + " US Equity"
    base, cc = m.group(1), m.group(2)
    if cc == "HK":
        base = base.lstrip("0") or "0"
    return f"{base} {cc} Equity"


def screener_codes(gh, members):
    """Every ticker in the screener's theme files and universe.txt, plus the index members from Bloomberg -> {yahoo key: bbg code}."""
    out = {}
    files = [f"themes/{f['name']}" for f in gh.list_dir(SCREENER_REPO, "themes") if f["name"].endswith(".txt")] + ["universe.txt"]
    for path in files:
        for line in gh.read(SCREENER_REPO, path).splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith(("[", "@")):
                continue
            code = line.split("|")[0].strip()
            if code and not code.startswith("^") and "." not in code:   # indices and Yahoo-only codes have no consensus
                out.setdefault(yahoo_key(code), bbg_code(code))
    for f in ("spx.csv", "ndx.csv"):
        for t in members.get(f, []):
            out.setdefault(yahoo_key(t), t + " Equity")
    return out


def consensus(bbg, gh, members):
    """Street view per stock, DERIVED numbers only (the site is public): upside to the consensus target, % of analysts
    rating Buy, consensus rating 1-5, number of analysts, and the 4-week change in the next-12-month EPS estimate."""
    codes = screener_codes(gh, members)
    secs = sorted(set(codes.values()))
    d, errs = bbg.ref(secs, ["PX_LAST", "BEST_TARGET_PRICE", "BEST_ANALYST_RATING", "TOT_ANALYST_REC", "TOT_BUY_REC",
                             "MOV_AVG_50D", "MOV_AVG_200D"])
    h, _ = bbg.hist(secs, ["BEST_EPS"], date.today() - timedelta(days=35), overrides={"BEST_FPERIOD_OVERRIDE": "BF"})
    out, have = {}, 0
    for key, sec in codes.items():
        v = d.get(sec)
        if not v:
            continue
        px, tp = num(v.get("PX_LAST")), num(v.get("BEST_TARGET_PRICE"))
        n, buy, rt = num(v.get("TOT_ANALYST_REC")), num(v.get("TOT_BUY_REC")), num(v.get("BEST_ANALYST_RATING"))
        eps = [num(x.get("BEST_EPS")) for _, x in h.get(sec, [])]
        eps = [e for e in eps if e is not None]
        rec = {}
        if px and tp:
            rec["up"] = round((tp / px - 1) * 100, 1)
        if n:
            rec["n"] = int(n)
            if buy is not None:
                rec["buy"] = round(buy / n * 100)
        if rt:
            rec["rt"] = round(rt, 2)
        # data check: Bloomberg's own 50 / 200-day averages, compared with the screener's (Yahoo-based) ones
        for f, key in (("MOV_AVG_50D", "bma50"), ("MOV_AVG_200D", "bma200")):
            x = num(v.get(f))
            if x:
                rec[key] = float(f"{x:.6g}")
        if len(eps) >= 15 and eps[0]:
            rec["rev4w"] = round((eps[-1] / eps[0] - 1) * 100 * (1 if eps[0] > 0 else -1), 1)
        if rec:
            out[key] = rec
            have += 1
    missing = sorted({k.split('|')[1] for k in errs if '|' in k})
    say(f"  [{'OK' if have else '!!'}]  Screener consensus: {have} of {len(codes)} stocks"
        + (f"; fields not recognised: {', '.join(missing)}" if missing else ""))
    nv = out.get("NVDA")
    if nv:
        say(f"  [..]    check against ANR <GO> for NVDA: upside {nv.get('up')}%, buy {nv.get('buy')}%, analysts {nv.get('n')}, "
            f"rating {nv.get('rt')}, EPS revision 4w {nv.get('rev4w')}%")
    bad = [k for k in codes if k not in out and not re.match(r"^(XL|RSP|KRE|XHB|GDX|ITA|TLT|IWM|VNQ|IYT)", k)]
    if bad:
        say(f"  [..]    no consensus for {len(bad)} tickers (ETFs and some small or foreign names have none), e.g. {', '.join(bad[:8])}")
    if not out:
        return {}
    payload = {"asof": datetime.now().astimezone().isoformat(timespec="minutes"),
               "note": "Derived from Bloomberg consensus: up = % upside to consensus target, buy = % of analysts rating Buy, "
                       "rt = consensus rating (1 sell .. 5 buy), n = analysts, rev4w = % change in the next-12-month EPS estimate over 4 weeks; "
                       "bma50 / bma200 = Bloomberg's 50 / 200-day moving averages, used to cross-check the screener's data",
               "stocks": out}
    return {"data/bloomberg_consensus.json": json.dumps(payload, separators=(",", ":"), sort_keys=True)}


# ---------------- GitHub (one commit per repository, no Git needed) ----------------
class GitHub:
    def __init__(self, token):
        self.token = token

    def call(self, method, url, body=None, raw=False):
        req = urllib.request.Request("https://api.github.com" + url, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": f"Bearer {self.token}", "User-Agent": "bbg-sync",
                                              "Accept": "application/vnd.github.raw" if raw else "application/vnd.github+json",
                                              "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
        return data.decode("utf-8") if raw else (json.loads(data) if data else None)

    def read(self, repo, path):
        return self.call("GET", f"/repos/{OWNER}/{repo}/contents/{path}", raw=True)

    def list_dir(self, repo, path):
        return self.call("GET", f"/repos/{OWNER}/{repo}/contents/{path}")

    def commit(self, repo, files, message):
        """Write several files in one commit on main. Returns False when nothing changed."""
        base = f"/repos/{OWNER}/{repo}/git"
        for attempt in range(3):
            head = self.call("GET", f"{base}/ref/heads/main")["object"]["sha"]
            base_tree = self.call("GET", f"{base}/commits/{head}")["tree"]["sha"]
            tree = self.call("POST", f"{base}/trees", {"base_tree": base_tree, "tree": [
                {"path": p, "mode": "100644", "type": "blob", "content": c} for p, c in sorted(files.items())]})["sha"]
            if tree == base_tree:
                return False
            new = self.call("POST", f"{base}/commits", {"message": message, "tree": tree, "parents": [head]})["sha"]
            try:
                self.call("PATCH", f"{base}/refs/heads/main", {"sha": new})
                return True
            except urllib.error.HTTPError as e:
                if e.code != 422 or attempt == 2:   # 422 = someone pushed in between: rebuild on the new head
                    raise
                time.sleep(2)
        return False


def read_token():
    path = os.path.join(HOME, "token.txt")
    try:
        with open(path, encoding="utf-8") as f:
            t = f.read().strip()
        return t or None
    except FileNotFoundError:
        return None


# ---------------- main ----------------
def due_slot(now, st):
    if now.weekday() >= 5 or not (WINDOW[0] <= now.strftime("%H:%M") < WINDOW[1]):
        return None
    done = st.get("slots", {}).get(now.date().isoformat(), [])
    passed = [s for s in SLOTS if s <= now.strftime("%H:%M")]
    return passed[-1] if passed and passed[-1] not in done else None


def run(mode):
    now = datetime.now()
    st = load_state()
    slot = due_slot(now, st) if mode == "auto" else "manual"
    if not slot:
        return 0
    token = read_token()
    if mode != "test" and not token:
        log("no GitHub token in " + os.path.join(HOME, "token.txt"))
        return 2
    try:
        bbg = Bbg()
    except Exception as e:  # noqa: BLE001
        log(f"slot {slot}: Bloomberg not reachable ({e}); will try again in 15 minutes")
        if mode != "auto":
            say(f"  [!!]  Bloomberg not reachable: {e}")
        return 0
    try:
        if not logged_in(bbg):
            log(f"slot {slot}: Bloomberg is not logged in; will try again in 15 minutes")
            if mode != "auto":
                say("  [!!]  Bloomberg answered but is not serving data: are you logged in?")
            return 0
        gh = GitHub(token) if token else None
        say(f"Bloomberg sync {now:%Y-%m-%d %H:%M} ({'TEST: nothing will be uploaded' if mode == 'test' else 'slot ' + slot})")
        macro, screener, members = {}, {}, {}
        today = date.today().isoformat()
        for name, fn in (("Fed pricing", lambda: fed_pricing(bbg, gh)), ("Credit", lambda: credit(bbg)), ("Economic calendar", lambda: eco(bbg, st))):
            try:
                t0 = time.time()
                macro.update(fn())
                log(f"{name} took {time.time() - t0:.0f}s")
            except Exception as e:  # noqa: BLE001
                say(f"  [!!]  {name} failed: {e}")
                log(traceback.format_exc())
        last_w = st.get("weights_date", "2000-01-01")
        if mode != "auto" or (date.today() - date.fromisoformat(last_w)).days >= WEIGHTS_EVERY_DAYS:
            try:
                say("  ...   index weights: 7 indices, about 1,100 member names (can take a minute)")
                t0 = time.time()
                wf, members = weights(bbg)
                say(f"        (index weights took {time.time() - t0:.0f}s)")
                macro.update(wf)
                if wf and mode != "test":
                    st["weights_date"] = today
            except Exception as e:  # noqa: BLE001
                say(f"  [!!]  Index weights failed: {e}")
                log(traceback.format_exc())
        if mode != "auto" or st.get("consensus_date") != today:
            try:
                if not members:   # consensus also covers the S&P 500 / Nasdaq-100 members
                    _, members = weights_members_only(bbg)
                if gh:
                    say("  ...   screener consensus: about 800 stocks plus 5 weeks of EPS estimates (can take 1-3 minutes)")
                    t0 = time.time()
                    screener.update(consensus(bbg, gh, members))
                    say(f"        (consensus took {time.time() - t0:.0f}s)")
                    if screener and mode != "test":
                        st["consensus_date"] = today
                else:
                    say("  [..]  Screener consensus skipped: it needs the GitHub token to read the theme lists (step 7 of SETUP.md)")
            except Exception as e:  # noqa: BLE001
                say(f"  [!!]  Screener consensus failed: {e}")
                log(traceback.format_exc())
        if mode == "test":
            out = os.path.join(os.path.expanduser("~"), "Desktop", "bloomberg_test_output")
            for repo, files in ((MACRO_REPO, macro), (SCREENER_REPO, screener)):
                for p, c in files.items():
                    fp = os.path.join(out, repo, *p.split("/"))
                    os.makedirs(os.path.dirname(fp), exist_ok=True)
                    with open(fp, "w", encoding="utf-8", newline="") as f:
                        f.write(c)
            say(f"Saved {len(macro) + len(screener)} files in {out} (nothing uploaded).")
        else:
            msg = f"Bloomberg sync {now:%Y-%m-%d %H:%M} (automatic)"
            for repo, files in ((MACRO_REPO, macro), (SCREENER_REPO, screener)):
                if files:
                    changed = gh.commit(repo, files, msg)
                    say(f"  [OK]  {repo}: {'uploaded ' + str(len(files)) + ' files' if changed else 'no changes'}")
            st.setdefault("slots", {}).setdefault(today, []).append(slot)
            st["slots"] = {k: v for k, v in st["slots"].items() if k >= (date.today() - timedelta(days=7)).isoformat()}
        save_state(st)
        log("\n".join(REPORT))
        return 0
    finally:
        bbg.close()


def weights_members_only(bbg):
    """Index members for the screener when the weekly weights step did not run today (no files written)."""
    d, _ = bbg.ref(["SPX Index", "NDX Index"], ["INDX_MWEIGHT"])
    out = {}
    for f, idx in (("spx.csv", "SPX Index"), ("ndx.csv", "NDX Index")):
        out[f] = [str(next((v for k, v in r.items() if "ticker" in k.lower() or "member" in k.lower()), "")).strip()
                  for r in d.get(idx, {}).get("INDX_MWEIGHT") or []]
        out[f] = [t for t in out[f] if t]
    return {}, out


if __name__ == "__main__":
    mode = "test" if "--test" in sys.argv else "now" if "--now" in sys.argv else "auto"
    try:
        code = run(mode)
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc())
        say(f"  [!!]  Sync failed: {e}")
        code = 1
    if mode != "auto":
        print()
        print("Copy everything in this window and send it to Claude.")
    sys.exit(code)
