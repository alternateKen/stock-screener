"""Bloomberg -> GitHub daily sync for the stock screener (analyst consensus and a moving-average data check).

Runs on the PC where you are logged in to Bloomberg. Windows Task Scheduler starts it every 15 minutes;
each time it:
  1. stops at once unless today's run is due (the first slot of each weekday, 05:30-21:00 on this PC's clock),
  2. stops quietly if Bloomberg is not logged in (it never logs in for you and never sees your password),
  3. otherwise fetches consensus for every theme stock and uploads it to GitHub in ONE commit,
  4. and adds names from the worksheet exports in %USERPROFILE%\\bbg_sync\\worksheets that the site lacks to the Inbox.

Only derived numbers are uploaded: upside to the consensus target, % buy ratings, consensus rating, number of analysts,
the 4-week EPS revision, and Bloomberg's 50 / 200-day averages (used to cross-check the screener's price data).

Usage
  python bbg_sync.py --test                 5 stocks only, saves a file on the Desktop, uploads NOTHING
  python bbg_sync.py --now [TICKER ...]     every theme stock now, plus any tickers given (new ones go into themes/inbox.txt)
  python bbg_sync.py                        what Task Scheduler runs (daily, weekdays)

Needs: the blpapi package and a GitHub token in %USERPROFILE%\\bbg_sync\\token.txt (see SETUP.md). Standard library otherwise."""
import base64, json, os, re, sys, time, traceback, urllib.request, urllib.error
from datetime import date, datetime, timedelta

# ---------------- settings ----------------
OWNER = "alternateKen"
SCREENER_REPO = "stock-screener"
WINDOW = ("05:30", "21:00")            # this PC's clock; weekdays only
SLOTS = ["05:30", "16:30", "20:00"]    # the daily run happens in the first of these you are logged in for
CONSENSUS_FROM = date(2026, 10, 25)    # runs allowed from this day (the daily schedule itself is weekdays only)
# Bloomberg Anywhere API allowance (the owner's ceiling: under 3,000 unique securities a month, 400,000 hits a day).
# The sync keeps its own count and stops rather than go past these.
BUDGET_SECS_MONTH = 2500
BUDGET_HITS_DAY = 300_000
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
        self.secs, self.hits = set(), 0      # what this run used (the allowance counts both)

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
                        self.hits += len(row[str(el.name())]) if isinstance(row[str(el.name())], list) else 1
                    data[sec] = row
                    self.secs.add(sec)
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
                    self.hits += max(p.numElements() - 1, 1)
                self.secs.add(sec)
        return data, errs


# ---------------- API allowance ----------------
def usage(st):
    """This month's unique securities and today's hits, as counted by this sync (state.json)."""
    u = st.setdefault("usage", {})
    if u.get("month") != date.today().strftime("%Y-%m"):
        u.update(month=date.today().strftime("%Y-%m"), secs=[])
    if u.get("day") != date.today().isoformat():
        u.update(day=date.today().isoformat(), hits=0)
    return u


def record_usage(st, bbg):
    u = usage(st)
    u["secs"] = sorted(set(u["secs"]) | bbg.secs)
    u["hits"] += bbg.hits
    bbg.hits = 0


def affordable(st, bbg, secs, hits):
    """Would asking for these securities (about `hits` data points) stay inside the allowance? -> (ok, reason)"""
    u = usage(st)
    used = set(u["secs"]) | bbg.secs
    new = len(set(secs) - used)
    if len(used) + new > BUDGET_SECS_MONTH:
        return False, f"would take this month's unique securities to {len(used) + new:,} (budget {BUDGET_SECS_MONTH:,})"
    if u["hits"] + bbg.hits + hits > BUDGET_HITS_DAY:
        return False, f"would take today's hits to {u['hits'] + bbg.hits + hits:,} (budget {BUDGET_HITS_DAY:,})"
    return True, ""


LOGIN_DETAIL = ""


def logged_in(bbg):
    """One tiny request: a real S&P 500 price means the Terminal is logged in and serving data.
    LOGIN_DETAIL keeps what Bloomberg actually answered, for the test report."""
    global LOGIN_DETAIL
    try:
        d, errs = bbg.ref(["SPX Index"], ["PX_LAST"])
        v = d.get("SPX Index", {}).get("PX_LAST")
        if isinstance(v, (int, float)) and v > 0:
            return True
        LOGIN_DETAIL = f"S&P 500 last price came back as {v!r}; Bloomberg's messages: {errs or 'none'}"
    except Exception as e:  # noqa: BLE001
        LOGIN_DETAIL = f"the request failed: {e}"
    return False


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


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


def screener_codes(gh):
    """Every ticker in the screener's theme files and universe.txt -> {yahoo key: bbg code}. The S&P 500 / Nasdaq-100
    members that are in no theme are left out to save the API allowance."""
    out = {}
    if not gh:
        return out
    files = [f"themes/{f['name']}" for f in gh.list_dir(SCREENER_REPO, "themes") if f["name"].endswith(".txt")] + ["universe.txt"]
    for path in files:
        for line in gh.read(SCREENER_REPO, path).splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith(("[", "@")):
                continue
            code = line.split("|")[0].strip()
            if code and not code.startswith("^") and "." not in code:   # indices and Yahoo-only codes have no consensus
                out.setdefault(yahoo_key(code), bbg_code(code))
    return out


CONSENSUS_SAMPLE = ["NVDA", "MSFT", "2330 TT", "005930 KS", "247540 KS"]


def consensus(bbg, gh, st, sample=False, extra=()):
    """Street view per stock, DERIVED numbers only (the site is public): upside to the consensus target, % of analysts
    rating Buy, consensus rating 1-5, number of analysts, and the 4-week change in the next-12-month EPS estimate.
    `extra`: tickers typed for a bespoke run (theme-file style: NVDA, 2330 TT, 0700 HK), on top of the theme stocks."""
    codes = {yahoo_key(c): bbg_code(c) for c in CONSENSUS_SAMPLE} if sample else screener_codes(gh)
    for c in extra:
        codes.setdefault(yahoo_key(c), bbg_code(c))
    secs = sorted(set(codes.values()))
    ok, why = affordable(st, bbg, secs, len(secs) * 12)
    if not ok:
        say(f"  [!!]  Screener consensus skipped to stay inside the Bloomberg allowance: {why}")
        return None
    fields = ["PX_LAST", "BEST_TARGET_PRICE", "BEST_ANALYST_RATING", "TOT_ANALYST_REC", "TOT_BUY_REC", "MOV_AVG_50D", "MOV_AVG_200D"]
    d, errs = bbg.ref(secs, fields)
    # EPS revision: today's next-12-month estimate against the one 4 weeks ago (a 5-day window, not 5 weeks of history)
    eps_now, _ = bbg.ref(secs, ["BEST_EPS"], overrides={"BEST_FPERIOD_OVERRIDE": "BF"})
    h, _ = bbg.hist(secs, ["BEST_EPS"], date.today() - timedelta(days=31), date.today() - timedelta(days=27),
                    overrides={"BEST_FPERIOD_OVERRIDE": "BF"})
    out, have = {}, 0
    for key, sec in codes.items():
        v = d.get(sec)
        if not v:
            continue
        px, tp = num(v.get("PX_LAST")), num(v.get("BEST_TARGET_PRICE"))
        n, buy, rt = num(v.get("TOT_ANALYST_REC")), num(v.get("TOT_BUY_REC")), num(v.get("BEST_ANALYST_RATING"))
        eps = [num(x.get("BEST_EPS")) for _, x in h.get(sec, [])][:1] + [num(eps_now.get(sec, {}).get("BEST_EPS"))]
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
        for f, fk in (("MOV_AVG_50D", "bma50"), ("MOV_AVG_200D", "bma200")):
            x = num(v.get(f))
            if x:
                rec[fk] = float(f"{x:.6g}")
        if len(eps) == 2 and eps[0]:
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


def add_to_inbox(gh, bbg, typed, codes_before):
    """Tickers typed for a bespoke run that are in no theme yet -> appended to themes/inbox.txt (so the site shows them).
    Only codes Bloomberg recognised are added. Returns {path: new text} or {}."""
    new = [c for c in typed if yahoo_key(c) not in codes_before]
    if not new:
        return {}
    d, errs = bbg.ref([bbg_code(c) for c in new], ["NAME"])
    good = [(c, d[bbg_code(c)].get("NAME") or "") for c in new if d.get(bbg_code(c))]
    for c in new:
        if not d.get(bbg_code(c)):
            say(f"  [!!]  {c}: Bloomberg does not recognise {bbg_code(c)} ({errs.get(bbg_code(c), 'no data')}); not added")
    if not good:
        return {}
    text = gh.read(SCREENER_REPO, "themes/inbox.txt").rstrip("\n") + "\n"
    text += "".join(f"{c} | {n}\n" if n else f"{c}\n" for c, n in good)
    say(f"  [OK]  added to the Inbox theme: {', '.join(c for c, _ in good)} (sort them into themes when convenient)")
    return {"themes/inbox.txt": text}


EXCHANGES = set("TT HK JP JT KS KQ KP KT CH C1 C2 TB LN GY GR FP NA SW SE NO AU CN IM IT SM SS DC FH IN IS SP".split()) | set(US_SFX)


def parse_tickers(text):
    """'NVDA 2330 TT, 0700 HK brk/b us' -> ['NVDA', '2330 TT', '0700 HK', 'BRK/B US']: an exchange code joins the word before it."""
    out = []
    for w in re.split(r"[\s,;]+", text.upper()):
        if not w:
            continue
        if w in EXCHANGES and out and " " not in out[-1]:
            out[-1] += " " + w
        else:
            out.append(w)
    return list(dict.fromkeys(out))


# ---------------- worksheet exports (W <GO> -> Excel, saved in WORKSHEETS) -> new names into the Inbox ----------------
# This login cannot read Security Worksheets through the API (no BQL), so the owner exports a worksheet to Excel into
# WORKSHEETS whenever it changes. Every run reads the folder, and names the screener does not have yet go into
# themes/inbox.txt, once each: a name deleted from the site later is not added again (state "ws_offered").
WORKSHEETS = os.path.join(HOME, "worksheets")
WS_MAX_NEW = 150          # names looked up per run at most (each new one counts once against the monthly allowance)
# market from a worksheet's tab or file name, for exports without the "Ticker and Exchange Code" column
WS_MARKETS = [("japan", "JP"), ("korea", "KS"), ("taiwan", "TT"), ("china", "CN"), ("hong kong", "HK"), ("australia", "AU"),
              ("singapore", "SP"), ("malaysia", "MK"), ("thailand", "TB")]
WS_SKIP = re.compile(r"\b(ETF|ETN|FUND|TRACKER|INDEX|CURNCY|COMDTY)\b", re.I)
WS_YAHOO_SFX = {"SP": ".SI", "MK": ".KL"}   # Yahoo numbers these markets differently: the code comes from ID_EXCH_SYMBOL


def xlsx_rows(path):
    """An .xlsx file -> {sheet name: [row as a list of strings]}, standard library only."""
    import zipfile
    import xml.etree.ElementTree as ET
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rel = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        ss = ["".join(t.text or "" for t in si.iter(ns + "t")) for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall(ns + "si")]
    rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for sh in ET.fromstring(z.read("xl/workbook.xml")).iter(ns + "sheet"):
        target = rels.get(sh.get(rel), "")
        target = target.lstrip("/") if target.startswith("/") else "xl/" + target
        rows = []
        for row in ET.fromstring(z.read(target)).iter(ns + "row"):
            vals = {}
            for c in row.findall(ns + "c"):
                col = re.match(r"[A-Z]+", c.get("r", "A")).group(0)
                idx = 0
                for ch in col:
                    idx = idx * 26 + ord(ch) - 64
                v, inl = c.find(ns + "v"), c.find(ns + "is")
                if c.get("t") == "s" and v is not None:
                    vals[idx - 1] = ss[int(v.text)]
                elif c.get("t") == "inlineStr" and inl is not None:
                    vals[idx - 1] = "".join(t.text or "" for t in inl.iter(ns + "t"))
                elif v is not None:
                    vals[idx - 1] = v.text
            rows.append([(vals.get(i) or "").strip() for i in range(max(vals) + 1)] if vals else [])
        out[sh.get("name")] = rows
    return out


def ws_entries(path):
    """One exported worksheet file -> [(candidate Bloomberg codes, name from the export, where)]. Candidates are tried in
    order; several only when the export has no exchange codes and the market leaves a choice (Korea KS / KQ, China HK / CH)."""
    out = []
    fname = os.path.basename(path)
    for sheet, rows in xlsx_rows(path).items():
        hdr = next((r for r in rows if r and r[0].lower().startswith("ticker")), None)
        if not hdr:
            continue
        low = [h.lower() for h in hdr]
        cex = next((i for i, h in enumerate(low) if "exchange" in h), None)   # "Ticker and Exchange Code": the full code
        ctk = next((i for i, h in enumerate(low) if h.startswith("ticker") and i != cex), cex)
        cnm = next((i for i, h in enumerate(low) if "name" in h), None)
        market = next((m for k, m in WS_MARKETS if k in f"{sheet} {fname}".lower()), None)
        for r in rows[rows.index(hdr) + 1:]:
            tk = (r[cex] if cex is not None and cex < len(r) and r[cex] else r[ctk] if ctk < len(r) else "").strip()
            nm = r[cnm] if cnm is not None and cnm < len(r) else ""
            if not tk or "(" in tk or (cnm is not None and not nm) or WS_SKIP.search(f"{tk} {nm}"):
                continue   # group headings ("Top Performers (10)") have no name; currencies, indices and funds are skipped
            tk = re.sub(r"\s+EQUITY$", "", tk.upper()).strip()
            cands = ws_candidates(tk, market, bool(nm))
            out.append((cands, nm if cands else f"{tk} {nm}".strip(), f"{fname} / {sheet}"))
    return out


def ws_candidates(tk, market, named=True):
    """'2330 TT' -> ['2330 TT']; bare '660' on a Korea tab -> ['000660 KS', '000660 KQ']; bare 'NVDA' on another tab -> ['NVDA US']
    when the export gives a company name to confirm it with (otherwise BHP could become the BHP US ADR, not BHP AU)."""
    if re.match(r"^\S+\s+[A-Z][A-Z0-9]$", tk):
        return [tk]
    if " " in tk:
        return []   # a heading such as "My Securities"
    if market == "KS":
        base = tk.zfill(6) if tk.isdigit() else tk
        return [f"{base} KS", f"{base} KQ"]
    if market == "CN":
        return [f"{tk} CH"] if len(tk) == 6 else [f"{tk} HK", f"{tk.zfill(6)} CH"]
    if market:
        return [f"{tk} {market}"]
    return [] if tk.isdigit() or not named else [f"{tk} US"]   # mixed tab: a bare number, or no name to confirm a guess


def name_key(name):
    """'Samsung Electronics Co Ltd' -> ['samsung', 'electronics']: the words that identify a company."""
    stop = {"co", "corp", "corporation", "inc", "ltd", "limited", "plc", "holdings", "holding", "group", "bhd", "berhad", "pcl",
            "public", "company", "the", "sa", "nv", "se", "ag", "asa", "ab", "tbk", "class", "a", "b", "h", "shares", "of", "and",
            "adr", "ads", "spon", "sponsored", "reg", "unsp"}
    return [w for w in re.findall(r"[a-z0-9]+", (name or "").lower().split("(")[0]) if w not in stop]


def same_company(a, b):
    """Two names for the same company? Equal identifying words, or one is the start of the other with at least two words.
    Exports cut names at about 29 characters ('Commonwealth Bank of Australi'), so a last word may be cut short too."""
    ka, kb = name_key(a), name_key(b)
    if not ka or not kb:
        return False
    short, long_ = sorted((ka, kb), key=len)
    if len(short) < 2 and ka != kb:
        return False
    head, last = short[:-1], short[-1]
    if len(long_) <= len(head) or long_[:len(head)] != head:
        return False
    other = long_[len(head)]   # either name may be the one cut shorter ('internationa' vs 'internation')
    return other.startswith(last) or (len(long_) == len(short) and last.startswith(other))


def site_index(gh):
    """Everything on the site: theme and universe codes as Yahoo keys (Korean ones also by their 6 digits), and the names."""
    keys, names = set(), []
    files = [f"themes/{f['name']}" for f in gh.list_dir(SCREENER_REPO, "themes") if f["name"].endswith(".txt")] + ["universe.txt"]
    for path in files:
        for line in gh.read(SCREENER_REPO, path).splitlines():
            line = line.split("#")[0].strip()
            if not line or line.startswith(("[", "@")):
                continue
            parts = [p.strip() for p in line.split("|")]
            k = yahoo_key(parts[0]) if "." not in parts[0] else parts[0].upper()
            keys.add(k)
            m = re.match(r"^(\d{6})\.K[SQ]$", k)
            if m:
                keys.add(m.group(1))
            if len(parts) > 1:
                names.append(parts[1])
    return keys, names


def ws_known(code, name, keys, names):
    k = yahoo_key(code)
    return k in keys or (re.match(r"^\d{6}\.K[SQ]$", k) and k[:6] in keys) or any(same_company(name, n) for n in names)


def worksheet_inbox(gh, bbg, st, files):
    """Read the worksheet exports and add names the screener does not have to themes/inbox.txt (in `files`)."""
    if not os.path.isdir(WORKSHEETS):
        os.makedirs(WORKSHEETS, exist_ok=True)
    paths = sorted(os.path.join(WORKSHEETS, f) for f in os.listdir(WORKSHEETS) if f.lower().endswith(".xlsx") and not f.startswith("~$"))
    if not paths:
        return
    entries = []
    for p in paths:
        try:
            entries += ws_entries(p)
        except Exception as e:  # noqa: BLE001
            say(f"  [!!]  worksheet {os.path.basename(p)}: cannot read it ({e})")
    keys, names = site_index(gh)
    offered = set(st.get("ws_offered", []))
    todo, unclear, seen = [], [], set()
    for cands, nm, where in entries:
        if not cands:
            unclear.append(f"{nm or '?'} ({where})")
            continue
        if any(ws_known(c, nm, keys, names) for c in cands) or any(c in offered for c in cands) or cands[0] in seen:
            continue
        seen.add(cands[0])
        todo.append((cands, nm, where))
    say(f"  [..]  worksheets: {len(paths)} files, {len(entries)} names, {len(todo)} not on the site yet")
    if unclear:
        say(f"  [..]    {len(unclear)} names without an exchange code skipped (export with the 'Ticker and Exchange Code' column): "
            + "; ".join(unclear[:6]) + (" ..." if len(unclear) > 6 else ""))
    if not todo:
        return
    if len(todo) > WS_MAX_NEW:
        say(f"  [..]    looking up the first {WS_MAX_NEW} today; the rest follow on the next runs")
        todo = todo[:WS_MAX_NEW]
    secs = sorted({bbg_code(c) for cands, _, _ in todo for c in cands})
    ok, why = affordable(st, bbg, secs, len(secs) * 2)
    if not ok:
        say(f"  [!!]  worksheet names not looked up, to stay inside the Bloomberg allowance: {why}")
        return
    d, errs = bbg.ref(secs, ["NAME", "ID_EXCH_SYMBOL"])
    added, mismatch = [], []
    for cands, nm, where in todo:
        hit = next((c for c in cands if d.get(bbg_code(c)) and (not nm or same_company(nm, d[bbg_code(c)].get("NAME") or ""))), None)
        if not hit:
            got = [f"{c} = {d[bbg_code(c)].get('NAME')}" for c in cands if d.get(bbg_code(c))]
            mismatch.append(f"{nm} ({where})" + (f": Bloomberg has {'; '.join(got)}" if got else ": not recognised"))
            continue
        bname = (d[bbg_code(hit)].get("NAME") or nm).title()
        if any(same_company(bname, n) for n in names):   # on the site under another listing (e.g. BHP AU vs the BHP US ADR)
            offered.add(hit)
            continue
        cc = hit.split()[-1]
        code = hit
        if cc in WS_YAHOO_SFX:   # Singapore / Malaysia: Yahoo uses the exchange's own code (DBS SP -> D05.SI)
            sym = (d[bbg_code(hit)].get("ID_EXCH_SYMBOL") or "").strip()
            if not sym:
                mismatch.append(f"{nm} ({where}): no exchange symbol from Bloomberg, add it by hand")
                continue
            code = sym + WS_YAHOO_SFX[cc]
            if code.upper() in keys:
                offered.add(hit)
                continue
        added.append((code, nm or bname))
        offered.add(hit)
    if mismatch:
        say(f"  [..]    {len(mismatch)} names not added (Bloomberg did not confirm the ticker and name): " + "; ".join(mismatch[:6])
            + (" ..." if len(mismatch) > 6 else ""))
    st["ws_offered"] = sorted(offered)
    if not added:
        return
    text = files.get("themes/inbox.txt") or gh.read(SCREENER_REPO, "themes/inbox.txt")
    text = text.rstrip("\n") + "\n" + "".join(f"{c} | {n}\n" for c, n in added)
    files["themes/inbox.txt"] = text
    say(f"  [OK]  from the worksheets, added to the Inbox theme: {', '.join(c for c, _ in added)}")


# ---------------- main ----------------
def daily_due(now, st):
    """The daily run: each weekday (from CONSENSUS_FROM), the first slot inside the window that has passed.
    A run_now.bat upload earlier the same day counts as that day's run."""
    if now.date() < CONSENSUS_FROM or now.weekday() >= 5 or not (WINDOW[0] <= now.strftime("%H:%M") < WINDOW[1]):
        return False
    return st.get("consensus_day") != now.date().isoformat() and any(s <= now.strftime("%H:%M") for s in SLOTS)


def run(mode, typed=()):
    now = datetime.now()
    st = load_state()
    if mode == "auto" and not daily_due(now, st):
        return 0
    if mode == "now" and now.date() < CONSENSUS_FROM:
        say(f"  [..]  Paused until {CONSENSUS_FROM:%d %b %Y} so no Bloomberg allowance is used before then. Nothing fetched.")
        return 0
    token = read_token()
    if mode != "test" and not token:
        say("  [!!]  No GitHub token: see step 7 of SETUP.md")
        log("no GitHub token in " + os.path.join(HOME, "token.txt"))
        return 2
    try:
        bbg = Bbg()
    except Exception as e:  # noqa: BLE001
        log(f"{mode}: Bloomberg not reachable ({e}); will try again in 15 minutes")
        if mode != "auto":
            say(f"  [!!]  Bloomberg not reachable: {e}")
        return 0
    try:
        if not logged_in(bbg):
            log(f"{mode}: Bloomberg is not logged in ({LOGIN_DETAIL}); will try again in 15 minutes")
            if mode != "auto":
                say("  [!!]  Bloomberg answered but is not serving data: are you logged in?")
                say(f"        Bloomberg said: {LOGIN_DETAIL}")
                say("        Check: is the Terminal showing live prices right now (not a login or 'session moved' screen)?")
                say("        Bloomberg Anywhere allows one session at a time: logging in on a phone or another PC locks this one.")
                say("        If prices are missing on the Terminal too, the monthly API allowance may be used up until the month resets.")
            return 0
        gh = GitHub(token) if token else None
        kind = {"test": "TEST: 5 stocks, nothing will be uploaded", "now": "run now", "auto": "daily"}[mode]
        say(f"Bloomberg sync {now:%Y-%m-%d %H:%M} ({kind})" + (f", extra tickers: {', '.join(typed)}" if typed else ""))
        files = {}
        try:
            before = screener_codes(gh) if typed else {}
            say("  ...   screener consensus: " + ("a 5-stock sample" if mode == "test" else "every theme stock (1-3 minutes)"))
            t0 = time.time()
            got = consensus(bbg, gh, st, sample=mode == "test", extra=typed)
            say(f"        (consensus took {time.time() - t0:.0f}s)")
            if got:
                files.update(got)
                if typed and gh:
                    files.update(add_to_inbox(gh, bbg, typed, before))
            if gh:   # new names from the worksheet exports (a test run reports them without remembering them)
                worksheet_inbox(gh, bbg, json.loads(json.dumps(st)) if mode == "test" else st, files)
        except Exception as e:  # noqa: BLE001
            say(f"  [!!]  Screener consensus failed: {e}")
            log(traceback.format_exc())
        record_usage(st, bbg)
        u = usage(st)
        say(f"  [..]  Bloomberg allowance used by this sync: {len(u['secs']):,} unique securities this month "
            f"(budget {BUDGET_SECS_MONTH:,}), {u['hits']:,} hits today (budget {BUDGET_HITS_DAY:,})")
        if mode == "test":
            out = os.path.join(os.path.expanduser("~"), "Desktop", "bloomberg_test_output")
            for p, c in files.items():
                fp = os.path.join(out, *p.split("/"))
                os.makedirs(os.path.dirname(fp), exist_ok=True)
                with open(fp, "w", encoding="utf-8", newline="") as f:
                    f.write(c)
            say(f"Saved {len(files)} files in {out} (nothing uploaded).")
        elif files:
            changed = gh.commit(SCREENER_REPO, files, f"Bloomberg sync {now:%Y-%m-%d %H:%M} ({kind})")
            say(f"  [OK]  {SCREENER_REPO}: {'uploaded ' + str(len(files)) + ' files' if changed else 'no changes'}")
            st["consensus_day"] = now.date().isoformat()
        save_state(st)
        log("\n".join(REPORT))
        return 0
    finally:
        bbg.close()


if __name__ == "__main__":
    mode = "test" if "--test" in sys.argv else "now" if "--now" in sys.argv else "auto"
    typed = parse_tickers(" ".join(a for a in sys.argv[1:] if not a.startswith("--"))) if mode == "now" else []
    try:
        code = run(mode, typed)
    except Exception as e:  # noqa: BLE001
        log(traceback.format_exc())
        say(f"  [!!]  Sync failed: {e}")
        code = 1
    if mode != "auto":
        print()
        print("Copy everything in this window and send it to Claude.")
    sys.exit(code)
