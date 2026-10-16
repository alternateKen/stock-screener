"""More chart patterns for the screener, on daily bars (oldest first):
  - triangles (ascending, descending, symmetrical) and wedges (rising, falling): trendlines fitted through recent
    swing highs and swing lows;
  - flags and pennants: a sharp "pole" followed by a short, tight consolidation;
  - rounding bottom and cup and handle: a U-shaped base (quadratic fit), the cup with a shallow handle at its rim.
Each pattern is "forming" until the close breaks out by 1% (then "confirmed" for 15 sessions) and carries a measured
target. Output dicts use the same keys as patterns.find_patterns, plus "lines" (2-point lines to draw)."""

BREAK = 0.01
RECENT = 15


def _fit(points):
    """Least-squares line through [(x, y)] -> (slope, intercept)."""
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    if sxx == 0:
        return 0.0, my
    b = sum((x - mx) * (y - my) for x, y in points) / sxx
    return b, my - b * mx


def _quad(xs, ys):
    """Least-squares parabola y = a x^2 + b x + c -> (a, b, c, r2)."""
    n = len(xs)
    sx = [sum(x ** k for x in xs) for k in range(5)]
    sy = [sum(y * x ** k for x, y in zip(xs, ys)) for k in range(3)]
    m = [[sx[4], sx[3], sx[2], sy[2]], [sx[3], sx[2], sx[1], sy[1]], [sx[2], sx[1], n, sy[0]]]
    for i in range(3):                      # Gauss-Jordan on the 3x3 normal equations
        p = max(range(i, 3), key=lambda r: abs(m[r][i]))
        m[i], m[p] = m[p], m[i]
        if abs(m[i][i]) < 1e-12:
            return 0.0, 0.0, 0.0, 0.0
        for r in range(3):
            if r != i:
                f = m[r][i] / m[i][i]
                m[r] = [a - f * b for a, b in zip(m[r], m[i])]
    a, b, c = (m[i][3] / m[i][i] for i in range(3))
    my = sum(ys) / n
    ss_tot = sum((y - my) ** 2 for y in ys) or 1e-12
    ss_res = sum((y - (a * x * x + b * x + c)) ** 2 for x, y in zip(xs, ys))
    return a, b, c, 1 - ss_res / ss_tot


def _state(closes, start, upper, lower, bias):
    """Breakout check after bar `start`: -> (state, direction, break bar) or None if the pattern failed long ago.
    upper/lower: functions bar -> line value."""
    n = len(closes)
    for i in range(start + 1, n):
        if closes[i] > upper(i) * (1 + BREAK):
            return ("confirmed", 1, i) if n - 1 - i <= RECENT else None
        if closes[i] < lower(i) * (1 - BREAK):
            return ("confirmed", -1, i) if n - 1 - i <= RECENT else None
    return "forming", bias, None


# ---------------- triangles and wedges ----------------
TRI = {"tria": ("Ascending triangle", 1), "trid": ("Descending triangle", -1), "tris": ("Symmetrical triangle", 0),
       "wedr": ("Rising wedge", -1), "wedf": ("Falling wedge", 1)}


def triangles(highs, lows, closes, sw, atr):
    """The longest well-fitting converging trendline pattern over the last 15-120 bars (one per stock)."""
    n, last = len(closes), closes[-1]
    if not atr or n < 40:
        return []
    tol = max(0.6 * atr, last * 0.012)
    pts = [s for s in sw if s[0] >= n - 120]
    best = None
    for start in range(0, len(pts) - 4):                # longest window first, i.e. oldest start
        win = pts[start:]
        hs = [(i, p) for i, p, k in win if k == "H"]
        ls = [(i, p) for i, p, k in win if k == "L"]
        if len(hs) < 2 or len(ls) < 2 or len(win) < 5:
            continue
        i0, i1 = win[0][0], win[-1][0]
        span = i1 - i0
        if not 15 <= span <= 120 or n - 1 - i1 > 25:    # the last touch must be recent
            continue
        su, iu = _fit(hs)
        sl, il = _fit(ls)
        up = lambda i, su=su, iu=iu: su * i + iu        # noqa: E731
        lo = lambda i, sl=sl, il=il: sl * i + il        # noqa: E731
        if any(abs(p - up(i)) > tol for i, p in hs) or any(abs(p - lo(i)) > tol for i, p in ls):
            continue
        # the closes between the first and last touch stay inside the lines
        if any(closes[i] > up(i) + tol or closes[i] < lo(i) - tol for i in range(i0, i1 + 1)):
            continue
        w0, w1 = up(i0) - lo(i0), up(n - 1) - lo(n - 1)
        if w0 <= 0 or w1 <= 0 or w1 > 0.75 * w0:       # must converge, apex not yet reached
            continue
        flat = max(atr, last * 0.02)                    # a line that moves less than this over the span is "flat"
        du, dl = su * span, sl * span
        fu, fl = abs(du) < flat, abs(dl) < flat
        if fu and dl > 0:
            k = "tria"
        elif fl and du < 0:
            k = "trid"
        elif du < 0 < dl and not fu and not fl:
            k = "tris"
        elif du > 0 and dl > 0 and dl > du:
            k = "wedr"
        elif du < 0 and dl < 0 and du < dl:
            k = "wedf"
        else:
            continue
        best = (k, i0, i1, up, lo, w0)
        break
    if not best:
        return []
    k, i0, i1, up, lo, w0 = best
    name, bias = TRI[k]
    st = _state(closes, i1, up, lo, bias)
    if not st:
        return []
    state, d, brk = st
    at = brk if brk is not None else n - 1
    if state == "forming" and not (lo(n - 1) * (1 - BREAK) <= last <= up(n - 1) * (1 + BREAK)):
        return []
    if d > 0 or (d == 0 and state == "forming"):
        neck, target = up(at), up(at) + w0
    else:
        neck, target = lo(at), lo(at) - w0
    if state == "confirmed":
        name += " (broke up)" if d > 0 else " (broke down)"
    return [{"k": k, "name": name, "state": state, "d": d, "neck": neck, "target": target, "pts": [],
             "neck_pts": [], "lines": [[(i0, up(i0)), (n - 1, up(n - 1))], [(i0, lo(i0)), (n - 1, lo(n - 1))]]}]


# ---------------- flags and pennants ----------------
def flags(highs, lows, closes, atr):
    """A pole (a move of at least 10% and 5 ATRs in 3-12 bars, ending 4-20 bars ago) followed by a tight
    consolidation that retraces less than 40% of the pole. Converging consolidation = pennant, otherwise flag."""
    n, last = len(closes), closes[-1]
    if not atr or n < 40:
        return []
    best = None
    for e in range(n - 21, n - 4):                       # pole end
        for s in range(e - 12, e - 2):                   # pole start
            mv = closes[e] / closes[s] - 1
            if abs(closes[e] - closes[s]) < 5 * atr or abs(mv) < 0.10:
                continue
            if best is None or abs(mv) > abs(best[2]):
                best = (s, e, mv)
    if not best:
        return []
    s, e, mv = best
    up = mv > 0
    pole = abs(closes[e] - closes[s])
    cons = list(range(e + 1, n - 1))                     # the consolidation, before today's bar
    if len(cons) < 3:
        return []
    hi, lo_ = max(highs[i] for i in cons), min(lows[i] for i in cons)
    extreme = max(highs[s:e + 1]) if up else min(lows[s:e + 1])
    if up and (lo_ < closes[e] - 0.4 * pole or hi > extreme * 1.02):
        return []
    if not up and (hi > closes[e] + 0.4 * pole or lo_ < extreme * 0.98):
        return []
    if hi - lo_ > 0.5 * pole:
        return []
    su, iu = _fit([(i, highs[i]) for i in cons])
    sl, il = _fit([(i, lows[i]) for i in cons])
    upf = lambda i: su * i + iu                          # noqa: E731
    lof = lambda i: sl * i + il                          # noqa: E731
    w0, w1 = upf(cons[0]) - lof(cons[0]), upf(n - 1) - lof(n - 1)
    if w0 <= 0:
        return []
    pennant = w1 < 0.6 * w0 and su < 0 < sl
    if not pennant and (up and su * len(cons) > 0.5 * atr or not up and su * len(cons) < -0.5 * atr):
        return []                                        # a flag drifts against (or sideways to) the pole
    kind = ("Bull " if up else "Bear ") + ("pennant" if pennant else "flag")
    k = "flagu" if up else "flagd"
    if up and last > upf(n - 1) * (1 + BREAK):
        state, d, neck = "confirmed", 1, upf(n - 1)
    elif not up and last < lof(n - 1) * (1 - BREAK):
        state, d, neck = "confirmed", -1, lof(n - 1)
    elif lof(n - 1) * (1 - BREAK) <= last <= upf(n - 1) * (1 + BREAK):
        state, d, neck = "forming", 1 if up else -1, upf(n - 1) if up else lof(n - 1)
    else:
        return []                                        # broke the wrong way: no longer a flag
    if state == "confirmed":
        kind += " (breakout)" if up else " (breakdown)"
    return [{"k": k, "name": kind, "state": state, "d": d, "neck": neck,
             "target": neck + pole if up else neck - pole, "pts": [(s, closes[s]), (e, closes[e])], "neck_pts": [],
             "lines": [[(cons[0], upf(cons[0])), (n - 1, upf(n - 1))], [(cons[0], lof(cons[0])), (n - 1, lof(n - 1))]]}]


# ---------------- rounding bottom and cup and handle ----------------
def bases(highs, lows, closes, sw, atr):
    """Cup and handle: after an advance of at least 15%, two rims within 5% (left rim a swing high), a U-shaped cup
    30-250 bars wide and 12-50% deep between them (bottom in the middle 40%), then a 3-30 bar handle that holds in the cup's upper third. Rounding bottom: a U-shaped base
    (no handle needed) whose right side has recovered at least 60% of the decline. Breakout = close above the rim."""
    n, last = len(closes), closes[-1]
    if n < 60:
        return []
    out = []
    highs_sw = [(i, p) for i, p, k in sw if k == "H" and i >= n - 260]
    # ---- cup and handle
    for li in range(len(highs_sw) - 1):
        L = highs_sw[li]
        for R in highs_sw[li + 1:]:
            width = R[0] - L[0]
            if not 30 <= width <= 250 or abs(R[1] / L[1] - 1) > 0.05:
                continue
            bot_i = min(range(L[0], R[0] + 1), key=lambda i: lows[i])
            rim = min(L[1], R[1])
            depth = (rim - lows[bot_i]) / rim
            if not 0.12 <= depth <= 0.50 or not 0.3 <= (bot_i - L[0]) / width <= 0.7:
                continue
            pre = closes[max(0, L[0] - 80):L[0]]
            if not pre or min(pre) > rim * 0.85:          # a cup follows an advance of at least 15%
                continue
            xs = list(range(L[0], R[0] + 1))
            a, b, c, r2 = _quad(xs, [closes[i] for i in xs])
            if a <= 0 or r2 < 0.7:
                continue
            handle = list(range(R[0] + 1, n))
            if not 3 <= len(handle) <= 30:
                continue
            h_low = min(lows[i] for i in handle[:-1] or handle)
            if h_low < rim - (rim - lows[bot_i]) / 3:   # the handle must stay in the cup's upper third
                continue
            top = max(L[1], R[1])
            brk = next((i for i in handle if closes[i] > top * (1 + BREAK)), None)
            if brk is not None and n - 1 - brk > RECENT:
                continue
            state = "confirmed" if brk is not None else "forming"
            curve = [(i, a * i * i + b * i + c) for i in range(L[0], R[0] + 1, max(1, width // 12))]
            out.append({"k": "cup", "name": "Cup and handle", "state": state, "d": 1, "neck": top,
                        "target": top + (top - lows[bot_i]), "pts": curve + [(R[0], R[1])],
                        "neck_pts": [(L[0], top), (n - 1, top)], "lines": []})
            break
        if out:
            break
    if out:
        return out
    # ---- rounding bottom: the U fitted over the last 60-200 bars, lowest point in the middle half
    for w in (200, 150, 100, 60):
        if n < w + 5:
            continue
        xs = list(range(n - w, n))
        ys = [closes[i] for i in xs]
        a, b, c, r2 = _quad(xs, ys)
        if a <= 0 or r2 < 0.7:
            continue
        vx = -b / (2 * a)
        if not n - w + 0.25 * w <= vx <= n - w + 0.75 * w:
            continue
        lip = max(highs[n - w:n - w + max(5, w // 10)])   # the left rim of the base
        bottom = min(lows[n - w:n])
        depth = (lip - bottom) / lip
        if depth < 0.12 or (last - bottom) / (lip - bottom) < 0.6:
            continue
        brk = next((i for i in range(int(vx), n) if closes[i] > lip * (1 + BREAK)), None)
        if brk is not None and n - 1 - brk > RECENT:
            continue
        state = "confirmed" if brk is not None else "forming"
        curve = [(i, a * i * i + b * i + c) for i in range(n - w, n, max(1, w // 12))]
        out.append({"k": "rbot", "name": "Rounding bottom", "state": state, "d": 1, "neck": lip,
                     "target": lip + (lip - bottom), "pts": curve, "neck_pts": [(n - w, lip), (n - 1, lip)],
                     "lines": []})
        break
    return out


def find_shapes(highs, lows, closes, sw, atr):
    out = []
    for f in (lambda: triangles(highs, lows, closes, sw, atr), lambda: flags(highs, lows, closes, atr),
              lambda: bases(highs, lows, closes, sw, atr)):
        out += f()
    return out
