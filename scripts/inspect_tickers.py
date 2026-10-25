#!/usr/bin/env python3
"""Data check for a few tickers: what Yahoo returns for every exchange candidate, the moving averages and the
signals the screener derives from it. Run by the "Inspect tickers" workflow (Actions tab, Run workflow), or locally:
    python scripts/inspect_tickers.py "247540 KS" NVDA "0700 HK"
Compare the printed MA 50 / 100 / 200 and last close with Bloomberg (GP <GO> with the same studies)."""
import sys
from datetime import datetime, timezone
import screen


def day(t):
    return datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%d")


def main(codes):
    for code in codes:
        cands, disp = screen.yahoo_candidates(code)
        print(f"===== {code}  ->  Yahoo candidates {cands} (the screener uses the first that answers)")
        for c in cands:
            try:
                b = screen.yahoo_bars(c)
            except Exception as e:  # noqa: BLE001
                print(f"  {c}: no data ({e})")
                continue
            t, cl, v = b["t"], b["c"], b["v"]
            gaps = [(day(t[i - 1]), day(t[i])) for i in range(1, len(t)) if t[i] - t[i - 1] > 6 * 86400]
            jumps = [(day(t[i]), round((cl[i] / cl[i - 1] - 1) * 100, 1)) for i in range(1, len(cl)) if abs(cl[i] / cl[i - 1] - 1) > 0.25]
            zero_v = sum(1 for x in v[-250:] if not x)
            print(f"  {c}: {b.get('name')} | exchange {b.get('exch')} | {b.get('currency')} | {len(cl)} bars {day(t[0])} -> {day(t[-1])}"
                  f" | live price {b.get('last')}")
            print(f"     last 5 closes: {[(day(a), round(x, 2)) for a, x in zip(t[-5:], cl[-5:])]}")
            print(f"     data issues: gaps over 6 days {gaps[:5] or 'none'}; daily moves over 25% {jumps[:5] or 'none'}; "
                  f"zero-volume days in last 250: {zero_v}")
            r = screen.analyse(b)
            f = lambda x: "n/a" if x is None else f"{x:,.2f}"   # noqa: E731
            print(f"     last {f(r['last'])} | EMA9 {f(r['ema9'])} EMA21 {f(r['ema21'])} EMA50 {f(r['ema50'])} EMA100 {f(r['ema100'])} EMA200 {f(r['ema200'])} | weekly EMA9 {f(r['wema9'])} EMA21 {f(r['wema21'])} EMA50 {f(r['wema50'])} "
                  f"EMA100 {f(r['wema100'])} EMA200 {f(r['wema200'])} | MA50 {f(r['ma50'])} MA100 {f(r['ma100'])} "
                  f"MA200 {f(r['ma200'])} | RSI14 {f(r['rsi'])}")
            print(f"     trend {(r.get('trend') or {}).get('label')} | signals: {[s['t'] for s in r['signals']] or 'none'}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["247540 KS"])
