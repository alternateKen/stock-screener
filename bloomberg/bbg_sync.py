"""Bloomberg -> GitHub weekly sync for the stock screener (analyst consensus and a moving-average data check).

Runs on the PC where you are logged in to Bloomberg. Windows Task Scheduler starts it every 15 minutes;
each time it:
  1. stops at once unless the weekly run is due (the first slot from Monday, weekdays 07:00-21:00 on this PC's clock),
  2. stops quietly if Bloomberg is not logged in (it never logs in for you and never sees your password),
  3. otherwise fetches consensus for every theme stock and uploads it to GitHub in ONE commit.

Only derived numbers are uploaded: upside to the consensus target, % buy ratings, consensus rating, number of analysts,
the 4-week EPS revision, and Bloomberg's 50 / 200-day averages (used to cross-check the screener's price data).

Usage
  python bbg_sync.py --test                 5 stocks only, saves a file on the Desktop, uploads NOTHING
  python bbg_sync.py --now [TICKER ...]     every theme stock now, plus any tickers given (new ones go into themes/inbox.txt)
  python bbg_sync.py                        what Task Scheduler runs (weekly)

Needs: the blpapi package and a GitHub token in %USERPROFILE%\\bbg_sync\\token.txt (see SETUP.md). Standard library otherwise."""
import base64, json, os, re, sys, time, traceback, urllib.request, urllib.error
from datetime import date, datetime, timedelta

# ---------------- settings ----------------
OWNER = "alternateKen"
SCREENER_REPO = "stock-screener"
WINDOW = ("07:00", "21:00")            # this PC's clock; weekdays only
SLOTS = ["08:30", "16:30", "20:00"]    # the weekly run happens in the first of these you are logged in for, from Monday
CONSENSUS_FROM = date(2026, 11, 2)     # paused until October's allowance resets
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


# ---------------- main ----------------
def weekly_due(now, st):
    """The weekly run: from Monday (and from CONSENSUS_FROM), the first slot inside the window that has passed."""
    if now.date() < CONSENSUS_FROM or now.weekday() >= 5 or not (WINDOW[0] <= now.strftime("%H:%M") < WINDOW[1]):
        return False
    week = "%d-W%02d" % now.date().isocalendar()[:2]
    return st.get("consensus_week") != week and any(s <= now.strftime("%H:%M") for s in SLOTS)


def run(mode, typed=()):
    now = datetime.now()
    st = load_state()
    if mode == "auto" and not weekly_due(now, st):
        return 0
    if mode == "now" and now.date() < CONSENSUS_FROM:
        say(f"  [..]  Paused until {CONSENSUS_FROM:%d %b %Y} so October's Bloomberg allowance is not used. Nothing fetched.")
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
        kind = {"test": "TEST: 5 stocks, nothing will be uploaded", "now": "run now", "auto": "weekly"}[mode]
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
            st["consensus_week"] = "%d-W%02d" % now.date().isocalendar()[:2]
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
