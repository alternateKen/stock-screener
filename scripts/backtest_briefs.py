#!/usr/bin/env python3
"""Historical backtest of the morning brief: rebuild the brief for every past US session from five years of Yahoo
candles, with screen.py's own analyse() and build_brief(), then score every setup with track_briefs.py.

Runs on your PC, not in the workflow (about 1,000 stocks x 500 sessions). Standard library only; Yahoo only, so it
never touches the Bloomberg allowance.

  python scripts/backtest_briefs.py [out_dir] [--years=2] [--every=1] [--workers=N] [--limit=N]

  out_dir     default backtest/ (git-ignored): briefs/<session>.json, scorecard.json / .csv, summary.md, and a copy
              of scorecard.html to view it (python -m http.server -d backtest, then open localhost:8000/scorecard.html)
  --years     how many years of sessions to rebuild (the first year of the five is kept as indicator history)
  --every     rebuild every Nth session only (quicker; 1 = every session)
  --limit     only the first N stocks (a quick trial run)

What it cannot reproduce (read the results with these in mind):
  - Survivorship: today's theme and leaders lists, so stocks were picked with hindsight. The equal-weight theme basket
    has the same bias, which is why excess vs that basket ("x_univ") is the fairest measure here.
  - No TradingView ratings and no Bloomberg data checks (neither affects the setup lists).
  - Weekly EMAs see a shorter history early on; daily EMAs (the tiers) have at least a year of warm-up.
  - Yahoo revises history and adjusts for splits, not dividends. The liquidity cut uses today's rough FX rates.
"""
import json, os, random, shutil, sys, time
from bisect import bisect_right
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import screen  # noqa: E402
import track_briefs as tb  # noqa: E402

ROOT = screen.ROOT
CACHE = os.path.join(ROOT, "data", ".backtest_cache")
# the analyse() fields build_brief() and the scorer read; everything else is dropped to keep memory down
KEEP_FIELDS = ("last", "pct", "w1", "m1", "m3", "rs3", "tier", "tier_prev", "tier_5d", "trend", "sterm", "sterm_prev",
               "ema21", "ma50", "ma200", "adr", "rsi", "dv20", "signals", "pat")
LEADER_TIER_DAYS = 10   # enough tier history for leader_health()'s 5-session window


def bar_day(t):
    """The session a bar belongs to, as screen.adjust_bars dates it (Sydney's open is the evening before in UTC)."""
    return datetime.fromtimestamp(t + 21600, timezone.utc).date()


# ---------------- lists and prices ----------------
def load_lists():
    themes = []
    for f in sorted(x for x in os.listdir(os.path.join(ROOT, "themes")) if x.endswith(".txt")):
        t = screen.read_list(os.path.join(ROOT, "themes", f))
        t["title"] = t["title"] or f[:-4].replace("-", " ").title()
        if any(g["items"] for g in t["groups"]):
            themes.append(t)
    themes.sort(key=lambda t: (t["order"], t["title"]))
    lpath = os.path.join(ROOT, "leaders.txt")
    leaders = screen.read_list(lpath) if os.path.exists(lpath) else {"title": None, "groups": []}
    jobs = {}
    for t in themes + [leaders]:
        for g in t["groups"]:
            for it in g["items"]:
                it["k"] = it["cands"][0]
                jobs.setdefault(it["k"], it["cands"])
    return themes, leaders, jobs


def fetch_all(jobs, today, workers=8):
    """5 years of daily bars per stock, the genuine listing chosen as in screen.build; cached for the day."""
    cdir = os.path.join(CACHE, today.isoformat())
    os.makedirs(cdir, exist_ok=True)
    for old in os.listdir(CACHE):   # yesterday's download is stale: keep only today's
        if old != today.isoformat():
            shutil.rmtree(os.path.join(CACHE, old), ignore_errors=True)
    adj = screen.load_adjustments([])

    def one(k):
        p = os.path.join(cdir, screen.chart_file(k))
        if os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return k, json.load(f)
        got = []
        for c in jobs[k]:
            try:
                b = screen.yahoo_bars(c)
                b["ysym"] = c
                got.append(b)
                if len(jobs[k]) == 1:
                    break
            except Exception:  # noqa: BLE001
                pass
        if not got:
            return k, None
        b = max(got, key=lambda x: (x.get("live_bad") is None, x["t"][-1]))
        if k in adj:
            screen.adjust_bars(b, adj[k])
        if b.get("intraday") and len(b["t"]) > 1:   # a market still trading: its unfinished bar never counts
            b = {**b, **{x: b[x][:-1] for x in ("t", "o", "h", "l", "c", "v")}}
        b = {x: b.get(x) for x in ("t", "o", "h", "l", "c", "v", "currency", "name", "ysym")}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(b, f, separators=(",", ":"))
        return k, b

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        out = dict(ex.map(one, list(jobs)))
    ok = {k: b for k, b in out.items() if b}
    print(f"prices: {len(ok)}/{len(jobs)} stocks in {time.time() - t0:.0f}s"
          + (f"; none for {', '.join(sorted(set(jobs) - set(ok))[:12])}" if len(ok) < len(jobs) else ""))
    return ok


# ---------------- rebuilding one stock's history (runs in worker processes) ----------------
def slim(r, keep_tiers):
    out = {k: r.get(k) for k in KEEP_FIELDS}
    if keep_tiers:
        th = r.get("_tierh") or {}
        out["_tierh"] = dict(list(th.items())[-LEADER_TIER_DAYS:])
    return out


def analyse_history(job):
    """One stock -> {session: analyse() as it would have read after that session's close}."""
    k, b, sessions, spx_by, keep_tiers = job
    days = [bar_day(t) for t in b["t"]]
    out = {}
    for s in sessions:
        sd = date.fromisoformat(s)
        n = bisect_right(days, sd)
        if n < 60 or days[n - 1] < sd - timedelta(days=7):   # not listed yet, or no longer trading
            continue
        bars = {"t": b["t"][:n], "c": b["c"][:n], "h": b["h"][:n], "l": b["l"][:n], "v": b["v"][:n],
                "last": None, "time": b["t"][n - 1], "intraday": False}
        now = datetime(sd.year, sd.month, sd.day, 22, tzinfo=timezone.utc)
        try:
            r = screen.analyse(bars, spx_by.get(s), now=now)
        except Exception:  # noqa: BLE001
            continue
        r = slim(r, keep_tiers)
        r["t0"] = b["t"][n - 1] - b["t"][n - 1] % 86400   # the signal bar, as the scorer dates bars
        out[s] = r
    return k, out


# ---------------- assembling each session's brief ----------------
def items_for(g, prices):
    out = []
    for it in g["items"]:
        b = prices.get(it["k"]) or {}
        label = it["label"]
        if label == it["sym"] and b.get("name"):
            label = b["name"]
        out.append({"k": it["k"], "sym": it["sym"], "label": label})
    return out


def brief_for(session, stocks, spx_r, themes_d, leaders_d, leader_keys):
    lhist = screen.leader_history([stocks[k] for k in leader_keys if k in stocks])
    data = {"generated": f"{session}T22:00:00+00:00", "spx": {k: spx_r.get(k) for k in ("last", "pct", "w1", "m1", "m3", "ytd")},
            "spx_asof": session, "themes": themes_d, "leaders": {**leaders_d, "hist": lhist}}
    data["spx"]["intraday"] = False
    brief = screen.build_brief(data, stocks)
    brief.pop("_keys", None)
    brief.pop("data_flags", None)
    brief["us_session"], brief["source"] = session, "backtest"
    for card in tb.iter_cards(brief):
        card["t0"] = stocks[card["k"]]["t0"]
    return brief


# ---------------- statistics for the summary ----------------
def block_bootstrap(by_day, block, reps=1000, seed=7):
    """90% interval for the mean, resampling blocks of consecutive briefs (setups on nearby days overlap and repeat,
    so they are not independent samples). by_day = [[values of one brief], ...] in date order."""
    days = [v for v in by_day if v]
    if len(days) < 2 * block:
        return None
    rng, nb, means = random.Random(seed), max(1, len(days) // block), []
    for _ in range(reps):
        vals = []
        for _ in range(nb):
            i = rng.randrange(0, len(days) - block + 1)
            for d in days[i:i + block]:
                vals.extend(d)
        means.append(sum(vals) / len(vals))
    means.sort()
    return means[int(0.05 * reps)], means[int(0.95 * reps) - 1]


SUMMARY_LISTS = ["breakouts", "breakouts_level", "breakouts_hi52", "breakouts_ma", "pullbacks", "pullbacks_band",
                 "pullbacks_touch", "near_breakout", "all_long", "breakdowns", "breakdowns_level", "breakdowns_lo52",
                 "breakdowns_ma", "bounces", "bounces_band", "bounces_touch", "near_breakdown", "all_short",
                 "improving", "deteriorating", "leaders_lead", "leaders_lag"]
BLOCK = {"1D": 1, "1W": 5, "20D": 20, "1M": 21}


def summary_md(sc, rows, briefs, args):
    cube, mech, labels = sc["cube"], sc["mech"], sc["labels"]
    dates = [b["us_session"] for b in briefs]
    pos = {d: i for i, d in enumerate(dates)}
    L = [f"# Brief backtest: {len(briefs)} rebuilt briefs, {dates[0]} to {dates[-1]}", "",
         f"Rebuilt {sc['generated']} with `{' '.join(args)}`. Entry at the signal close; returns with shorts flipped.",
         "**x_univ** = return minus the equal-weight basket of every theme stock over the same dates (the fairest measure "
         "here: it has the same survivorship bias). **90% CI** = block bootstrap by brief date. "
         "**Payoff** = average win / average loss on the raw return.", ""]
    for h in ("1W", "20D"):
        L += [f"## {h} ({BLOCK[h]} sessions)", "",
              "| List | n | Right % | Avg return | Avg x_univ | 90% CI x_univ | Right % x_univ | Payoff | Avg in ADR units |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for l in SUMMARY_LISTS:
            d, x = cube.get(f"{l}|{h}|close|all|dir") or {}, cube.get(f"{l}|{h}|close|all|x_univ") or {}
            a, m = cube.get(f"{l}|{h}|close|all|adr_units") or {}, mech.get(f"{l}|{h}|close|all") or {}
            if not d.get("n"):
                continue
            by_day = [[] for _ in dates]
            for r in rows:
                if r["list"] == l:
                    v = ((r["res"].get(h) or {}).get("close") or {}).get("x_univ")
                    if v is not None:
                        by_day[pos[r["brief"]]].append(v)
            ci = block_bootstrap(by_day, BLOCK[h])
            f = lambda v, s="%": "–" if v is None else f"{v:+.2f}{s}"   # noqa: E731
            L.append(f"| {labels.get(l, l)} | {d['n']} | {d['hit']}% | {f(d['mean'])} | {f(x.get('mean'))} | "
                     + (f"{ci[0]:+.2f} to {ci[1]:+.2f}" if ci else "–") + f" | {x.get('hit', '–')}% | "
                     + (f"{m['payoff']:.2f}" if m.get("payoff") else "–") + f" | {f(a.get('mean'), '')} |")
        L.append("")
    L += ["## By the leaders' health call (20D, avg x_univ / right %)", "", "| List | " +
          " | ".join(s for s in ("Healthy", "Weakening", "Improving", "Risk-off")) + " |", "|---|---:|---:|---:|---:|"]
    for l in ("breakouts", "pullbacks", "near_breakout", "breakdowns", "bounces", "near_breakdown"):
        cells = []
        for s in ("Healthy", "Weakening", "Improving", "Risk-off"):
            x = cube.get(f"{l}|20D|close|{s}|x_univ") or {}
            cells.append(f"{x['mean']:+.2f}% / {x['hit']}% (n {x['n']})" if x.get("n") else "–")
        L.append(f"| {labels.get(l, l)} | " + " | ".join(cells) + " |")
    calls = {}
    for h in sc["health"]:
        r = (h.get("20D") or {})
        if h.get("status") and r.get("spx") is not None:
            calls.setdefault(h["status"], []).append((r["spx"], r.get("lead_ew"), r.get("lag_ew")))
    L += ["", "## The health call itself (20D after the call, equal-weight averages)", "",
          "| Call | Briefs | S&P 500 | Lead-tier leaders | Lagging-tier leaders |", "|---|---:|---:|---:|---:|"]
    for s, v in sorted(calls.items()):
        avg = lambda i: (lambda xs: f"{sum(xs) / len(xs):+.2f}%" if xs else "–")([x[i] for x in v if x[i] is not None])   # noqa: E731
        L.append(f"| {s} | {len(v)} | {avg(0)} | {avg(1)} | {avg(2)} |")
    rho = [t.get("rho_m1_20D") for t in sc["themes"] if t.get("rho_m1_20D") is not None]
    rt = [t.get("rho_tier_20D") for t in sc["themes"] if t.get("rho_tier_20D") is not None]
    L += ["", "## Theme calls", "",
          f"Rank correlation between a theme's 1M momentum and its next 20 sessions: average {sum(rho) / len(rho):+.2f} over {len(rho)} briefs." if rho else "",
          f"Same for the theme's 5-day net tier change: average {sum(rt) / len(rt):+.2f}." if rt else "", ""]
    return "\n".join(L)


# ---------------- main ----------------
def main(argv):
    flags = dict((a[2:].split("=", 1) + [""])[:2] for a in argv if a.startswith("--"))
    pos = [a for a in argv if not a.startswith("--")]
    out_dir = pos[0] if pos else os.path.join(ROOT, "backtest")
    years, every = float(flags.get("years") or 2), int(flags.get("every") or 1)
    workers = int(flags.get("workers") or max(1, (os.cpu_count() or 2) - 1))
    today = datetime.now(timezone.utc).date()

    themes, leaders, jobs = load_lists()
    if flags.get("limit"):
        lk = {it["k"] for g in leaders["groups"] for it in g["items"]}
        keep = sorted(jobs, key=lambda k: (k not in lk, k))[: int(flags["limit"])]
        jobs = {k: jobs[k] for k in keep}
    prices = fetch_all(jobs, today)
    spx_raw = screen.yahoo_bars(tb.SPX)
    spx_days = [bar_day(t) for t in spx_raw["t"]]
    if spx_raw.get("intraday"):
        spx_days = spx_days[:-1]
    start = spx_days[-1] - timedelta(days=round(365.25 * years))
    sessions = [d.isoformat() for d in spx_days if d >= start and d >= spx_days[0] + timedelta(days=370)][::-1][::every][::-1]
    print(f"sessions: {len(sessions)} from {sessions[0]} to {sessions[-1]} (every {every})")

    spx_by, spx_full = {}, {}
    for s in sessions:
        n = bisect_right(spx_days, date.fromisoformat(s))
        r = screen.analyse({"t": spx_raw["t"][:n], "c": spx_raw["c"][:n], "h": spx_raw["h"][:n], "l": spx_raw["l"][:n],
                            "v": spx_raw["v"][:n], "last": None, "time": spx_raw["t"][n - 1]},
                           now=datetime.fromisoformat(s + "T22:00:00+00:00"))
        spx_by[s], spx_full[s] = {"m1": r["m1"], "m3": r["m3"]}, r

    leader_keys = [it["k"] for g in leaders["groups"] for it in g["items"]]
    lkset = set(leader_keys)
    t0 = time.time()
    hist = {}
    work = [(k, b, sessions, spx_by, k in lkset) for k, b in prices.items()]
    with ProcessPoolExecutor(max_workers=workers) as ex:
        for i, (k, h) in enumerate(ex.map(analyse_history, work, chunksize=4), 1):
            cur = prices[k].get("currency")
            for r in h.values():
                r["cur"] = cur
            hist[k] = h
            if i % 100 == 0:
                print(f"  analysed {i}/{len(work)} stocks ({time.time() - t0:.0f}s)")
    print(f"analysed {len(hist)} stocks x {len(sessions)} sessions in {time.time() - t0:.0f}s")

    themes_d = [{"title": t["title"], "groups": [{"name": g["name"], "items": items_for(g, prices)}
                                                 for g in t["groups"] if g["items"]]} for t in themes]
    leaders_d = {"title": leaders["title"], "groups": [{"name": g["name"], "items": items_for(g, prices)}
                                                       for g in leaders["groups"] if g["items"]]}
    bdir = os.path.join(out_dir, "briefs")
    shutil.rmtree(bdir, ignore_errors=True)
    os.makedirs(bdir)
    briefs = []
    for s in sessions:
        stocks = {k: h[s] for k, h in hist.items() if s in h}
        br = brief_for(s, stocks, spx_full[s], themes_d, leaders_d, leader_keys)
        with open(os.path.join(bdir, f"{s}.json"), "w", encoding="utf-8") as f:
            json.dump(br, f, separators=(",", ":"), default=lambda x: None)
        briefs.append(br)
    del hist

    # score with the tracker, on the same candles (no live bar: every result is a finished session)
    p = tb.Prices(None, fetch=True, today=today)
    for k, b in prices.items():
        p.mem[k] = tb.Prices._clean({"t": [t - t % 86400 for t in b["t"]], "o": b["o"], "h": b["h"], "l": b["l"],
                                     "c": b["c"], "partial": False})
    members = {t["title"]: sorted({it["k"] for g in t["groups"] for it in g["items"] if it["k"] in prices}) for t in themes}
    rows_box = []
    orig = tb.summarise
    tb.summarise = lambda rows: (rows_box.append(rows), orig(rows))[1]   # keep every row for the bootstrap
    try:
        sc = tb.evaluate(out_dir, briefs=briefs, prices=p, members=members, today=today)
    finally:
        tb.summarise = orig
    md = summary_md(sc, rows_box[0], briefs, ["backtest_briefs.py"] + argv)
    with open(os.path.join(out_dir, "summary.md"), "w", encoding="utf-8") as f:
        f.write(md)
    for f in ("scorecard.html", "style.css", "common.js"):
        shutil.copy(os.path.join(ROOT, "docs", f), os.path.join(out_dir, f))
    print(md)
    print(f"\nwrote {out_dir}: briefs/, scorecard.json / .csv, summary.md, scorecard.html")


if __name__ == "__main__":
    main(sys.argv[1:])
