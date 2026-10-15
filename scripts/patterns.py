"""Price-structure analysis for the screener: swing points, support / resistance, trend, ADX and classic chart
patterns (double top / bottom, head and shoulders and its inverse). Pure Python, daily bars.

Conventions: indices refer to the bar lists passed in (oldest first); "confirmed" means the close has broken the
pattern's neckline, "forming" means the pattern is in place but the neckline has not been broken yet."""

SWING_K = 5            # a swing high is the highest high of the 5 bars either side (a "fractal" pivot)
LOOKBACK = 250         # about a year of bars for levels and patterns
RECENT = 15            # a neckline break must be this recent (bars) to be reported as "confirmed"
FORMING = 30           # a pattern's last peak / trough must be this recent to be reported as "forming"
BREAK = 0.01           # a close must clear the neckline by 1% to count as a break


def adx14(highs, lows, closes, n=14):
    """Wilder ADX(14): trend strength 0-100 (above ~25 = trending, below ~20 = no trend)."""
    if len(closes) < 2 * n + 1:
        return None
    tr, pdm, mdm = [], [], []
    for i in range(1, len(closes)):
        up, dn = highs[i] - highs[i - 1], lows[i - 1] - lows[i]
        pdm.append(up if up > dn and up > 0 else 0.0)
        mdm.append(dn if dn > up and dn > 0 else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr, p, m = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n])
    dxs = []
    for i in range(n, len(tr) + 1):
        if i > n:
            atr, p, m = atr - atr / n + tr[i - 1], p - p / n + pdm[i - 1], m - m / n + mdm[i - 1]
        pdi, mdi = (100 * p / atr if atr else 0), (100 * m / atr if atr else 0)
        dxs.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0)
    if len(dxs) < n:
        return None
    adx = sum(dxs[:n]) / n
    for d in dxs[n:]:
        adx = (adx * (n - 1) + d) / n
    return adx


def swings(highs, lows, k=SWING_K):
    """Alternating swing points [(index, price, 'H' | 'L')]. Fractal pivots, then consecutive points of the same
    kind are merged keeping the more extreme one, so highs and lows strictly alternate (a zig-zag)."""
    n, raw = len(highs), []
    for i in range(k, n - k):
        if highs[i] == max(highs[i - k:i + k + 1]):
            raw.append((i, highs[i], "H"))
        if lows[i] == min(lows[i - k:i + k + 1]):
            raw.append((i, lows[i], "L"))
    raw.sort(key=lambda x: (x[0], x[2] == "H"))
    out = []
    for pt in raw:
        if out and out[-1][2] == pt[2]:
            if (pt[2] == "H" and pt[1] >= out[-1][1]) or (pt[2] == "L" and pt[1] <= out[-1][1]):
                out[-1] = pt
            continue
        out.append(pt)
    return out


def levels(points, last, atr, upto=None):
    """Support / resistance from clustered swing points. Points within a tolerance (1 ATR, at least 1.5% of price)
    form one level; its strength is the number of touches. -> (supports below price, resistances above),
    each [{"p": level, "n": touches, "i": last touch index}], nearest first."""
    pts = [(i, p) for i, p, _ in points if upto is None or i <= upto]
    if not pts or not last:
        return [], []
    tol = max(atr or 0, last * 0.015)
    pts.sort(key=lambda x: x[1])
    clusters, cur = [], [pts[0]]
    for i, p in pts[1:]:
        if p - cur[0][1] <= tol:   # a level is a band no wider than the tolerance (no chaining)
            cur.append((i, p))
        else:
            clusters.append(cur)
            cur = [(i, p)]
    clusters.append(cur)
    lv = [{"p": sum(p for _, p in c) / len(c), "n": len(c), "i": max(i for i, _ in c)} for c in clusters]
    gap = last * 0.003
    sup = sorted([x for x in lv if x["p"] < last - gap], key=lambda x: -x["p"])
    res = sorted([x for x in lv if x["p"] > last + gap], key=lambda x: x["p"])
    # rank by distance, discounted for each extra touch (a 3-touch level 10% away beats a 1-touch level 6% away),
    # ignore anything more than 30% away, then show the two chosen levels nearest first
    def pick(xs):
        xs = [x for x in xs if abs(x["p"] / last - 1) <= 0.30]
        xs.sort(key=lambda x: abs(x["p"] - last) / (1 + 0.35 * (x["n"] - 1)))
        return sorted(xs[:2], key=lambda x: abs(x["p"] - last))
    return pick(sup), pick(res)


def _neck_at(a, b, i):
    """Value at bar i of the line through swing points a=(ia, pa) and b=(ib, pb)."""
    (ia, pa), (ib, pb) = a, b
    return pa if ib == ia else pa + (pb - pa) * (i - ia) / (ib - ia)


def _after(closes, start, test):
    """First bar index after `start` whose close passes test(i, close), or None."""
    for i in range(start + 1, len(closes)):
        if test(i, closes[i]):
            return i
    return None


def find_patterns(closes, sw, atr_pct):
    """Most recent double top / bottom and head and shoulders (plus inverse) in the swing sequence."""
    n, out = len(closes), []
    last = closes[-1]
    min_depth = max(0.05, 3 * (atr_pct or 0) / 100)   # the dip between two tops must be meaningful

    def prior_move(i, level, up):
        """A reversal pattern needs something to reverse: within the 60 bars before its first point, price was
        beyond the neckline on the other side (below it before a top, above it before a bottom)."""
        seg = closes[max(0, i - 60):i]
        return bool(seg) and (min(seg) <= level if up else max(seg) >= level)
    sw = [s for s in sw if s[0] >= n - LOOKBACK]
    done = set()
    for j in range(len(sw) - 1, 1, -1):
        a, b, c = sw[j - 2], sw[j - 1], sw[j]
        # ---- double top (H L H) / double bottom (L H L)
        kind = "dtop" if c[2] == "H" else "dbot"
        if kind not in done and 15 <= c[0] - a[0] <= 150:
            p1, p2, mid = a[1], c[1], b[1]
            similar = abs(p1 - p2) / max(p1, p2) <= 0.03
            depth = (min(p1, p2) - mid) / min(p1, p2) if kind == "dtop" else (mid - max(p1, p2)) / max(p1, p2)
            if similar and depth >= min_depth and prior_move(a[0], mid, kind == "dtop"):
                top = max(p1, p2) if kind == "dtop" else min(p1, p2)
                height = abs(top - mid)
                if kind == "dtop":
                    brk = _after(closes, c[0], lambda i, x: x < mid * (1 - BREAK))
                    dead = _after(closes, c[0], lambda i, x: x > top * 1.01)
                    target = mid - height
                else:
                    brk = _after(closes, c[0], lambda i, x: x > mid * (1 + BREAK))
                    dead = _after(closes, c[0], lambda i, x: x < top * 0.99)
                    target = mid + height
                state = None
                if brk is not None and (dead is None or dead > brk) and n - 1 - brk <= RECENT:
                    state = "confirmed"
                elif brk is None and dead is None and n - 1 - c[0] <= FORMING:
                    state = "forming"
                if state:
                    out.append({"k": kind, "d": -1 if kind == "dtop" else 1, "state": state,
                                "name": "Double top" if kind == "dtop" else "Double bottom",
                                "neck": mid, "target": target, "pts": [a[:2], b[:2], c[:2]],
                                "neck_pts": [(b[0], mid), (n - 1, mid)], "brk": brk})
                    done.add(kind)
        # ---- head and shoulders (H L H L H) / inverse (L H L H L)
        if j >= 4:
            s1, t1, hd, t2, s2 = sw[j - 4], sw[j - 3], sw[j - 2], sw[j - 1], sw[j]
            kind = "hs" if s2[2] == "H" else "ihs"
            lft, rgt = hd[0] - s1[0], s2[0] - hd[0]
            if kind not in done and 20 <= s2[0] - s1[0] <= 200 and 0.4 <= lft / max(rgt, 1) <= 2.5:
                if kind == "hs":
                    shape = hd[1] > max(s1[1], s2[1]) * 1.03
                else:
                    shape = hd[1] < min(s1[1], s2[1]) * 0.97
                level = abs(s1[1] - s2[1]) / max(s1[1], s2[1]) <= 0.06
                if shape and level and prior_move(s1[0], min(t1[1], t2[1]) if kind == "hs" else max(t1[1], t2[1]), kind == "hs"):
                    neck = lambda i: _neck_at(t1[:2], t2[:2], i)   # noqa: E731
                    height = abs(hd[1] - neck(hd[0]))
                    if kind == "hs":
                        brk = _after(closes, s2[0], lambda i, x: x < neck(i) * (1 - BREAK))
                        dead = _after(closes, s2[0], lambda i, x: x > hd[1])
                    else:
                        brk = _after(closes, s2[0], lambda i, x: x > neck(i) * (1 + BREAK))
                        dead = _after(closes, s2[0], lambda i, x: x < hd[1])
                    state = None
                    if brk is not None and (dead is None or dead > brk) and n - 1 - brk <= RECENT:
                        state = "confirmed"
                    elif brk is None and dead is None and n - 1 - s2[0] <= FORMING:
                        state = "forming"
                    if state:
                        nk = neck(brk if brk is not None else n - 1)
                        out.append({"k": kind, "d": -1 if kind == "hs" else 1, "state": state,
                                    "name": "Head and shoulders" if kind == "hs" else "Inverse head and shoulders",
                                    "neck": nk, "target": nk - height if kind == "hs" else nk + height,
                                    "pts": [s1[:2], t1[:2], hd[:2], t2[:2], s2[:2]],
                                    "neck_pts": [(t1[0], t1[1]), (n - 1, neck(n - 1))], "brk": brk})
                        done.add(kind)
        if {"dtop", "dbot", "hs", "ihs"} <= done:
            break
    return out


def trend(closes, sw, ma50_series, ma200, adx, last):
    """Trend from price structure (higher highs / higher lows), the moving averages and ADX.
    -> {"dir": "up" | "down" | "side", "label": ..., "score": -5..5, "adx": ..., "hh": bool, "hl": bool}"""
    hs = [p for _, p, k in sw if k == "H"][-2:]
    ls = [p for _, p, k in sw if k == "L"][-2:]
    score, why = 0, []
    if len(hs) == 2:
        score += 1 if hs[1] > hs[0] else -1
        why.append("higher highs" if hs[1] > hs[0] else "lower highs")
    if len(ls) == 2:
        score += 1 if ls[1] > ls[0] else -1
        why.append("higher lows" if ls[1] > ls[0] else "lower lows")
    m50 = ma50_series[-1] if ma50_series else None
    if m50:
        score += 1 if last > m50 else -1
        old = ma50_series[-11] if len(ma50_series) > 11 else None
        if old:
            score += 1 if m50 > old else -1
            why.append("50d rising" if m50 > old else "50d falling")
    if m50 and ma200:
        score += 1 if m50 > ma200 else -1
    d = "up" if score >= 3 else "down" if score <= -3 else "side"
    strong = adx is not None and adx >= 25
    label = {"up": "Uptrend", "down": "Downtrend", "side": "Sideways"}[d]
    if d != "side" and strong:
        label = "Strong " + label.lower()
    elif d == "side" and adx is not None and adx < 20:
        label = "Range-bound"
    return {"dir": d, "label": label, "score": score, "adx": round(adx, 1) if adx is not None else None,
            "why": ", ".join(why)}


def structure(ts, highs, lows, closes, atr, ma50_series, ma200, vols=None):
    """Everything above for one stock -> (fields for data.json, extra signals [(key, direction, text)])."""
    n = len(closes)
    if n < 60:
        return {}, []
    last = closes[-1]
    day = lambda i: ts[i] - ts[i] % 86400   # noqa: E731   matches the chart files' time axis
    sw = swings(highs, lows)
    recent = [s for s in sw if s[0] >= n - LOOKBACK]
    sup, res = levels(recent, last, atr)
    adx = adx14(highs, lows, closes)
    tr = trend(closes, sw, ma50_series, ma200, adx, last)
    atr_pct = atr / last * 100 if atr and last else None
    pats = find_patterns(closes, sw, atr_pct)
    sig = []
    # breakouts: a close at least 1% through the nearest level (touched twice or more) within the last 3 sessions,
    # confirmed by volume: one of those sessions traded at least 1.3x its 20-day average (skipped if no volume data)
    vx = None
    if vols and len(vols) >= 24:
        ratios = []
        for i in range(n - 3, n):
            base = sum(vols[i - 20:i]) / 20
            ratios.append(vols[i] / base if base else 0)
        vx = max(ratios)
    vol_ok = vx is None or vx >= 1.3
    vtxt = f" on {vx:.1f}x volume" if vx is not None else ""
    old_sup, old_res = levels([s for s in recent if s[0] <= n - 4], closes[-4], atr)
    lv = old_res[0] if old_res else None
    if vol_ok and lv and lv["n"] >= 2 and closes[-4] <= lv["p"] and last > lv["p"] * (1 + BREAK) and min(closes[-3:]) <= lv["p"] * 1.03:
        sig.append(("brku", 1, f"Breakout above resistance {lv['p']:.4g}{vtxt}"))
    lv = old_sup[0] if old_sup else None
    if vol_ok and lv and lv["n"] >= 2 and closes[-4] >= lv["p"] and last < lv["p"] * (1 - BREAK) and max(closes[-3:]) >= lv["p"] * 0.97:
        sig.append(("brkd", -1, f"Breakdown below support {lv['p']:.4g}{vtxt}"))
    for p in pats:
        word = "confirmed" if p["state"] == "confirmed" else "forming"
        sig.append((p["k"], p["d"], f"{p['name']} {word} (neckline {p['neck']:.4g}, target {p['target']:.4g})"))
    fields = {
        "trend": tr,
        "sr": {"sup": [{"p": round(x["p"], 4), "n": x["n"]} for x in sup],
               "res": [{"p": round(x["p"], 4), "n": x["n"]} for x in res]},
        "pat": [{"k": p["k"], "name": p["name"], "state": p["state"], "d": p["d"], "neck": round(p["neck"], 4),
                 "target": round(p["target"], 4), "pts": [[day(i), round(v, 4)] for i, v in p["pts"]],
                 "neck_pts": [[day(i), round(v, 4)] for i, v in p["neck_pts"]]} for p in pats],
    }
    return fields, sig
