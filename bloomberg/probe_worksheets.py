"""Probe: can the Bloomberg API read a Security Worksheet (W <GO>) by name?

If it can, the daily sync could add new worksheet names to the screener's Inbox by itself. Run probe_worksheets.bat on
the Bloomberg PC while logged in. It tries a few ways of asking Bloomberg's query language (BQL) for the members of
ONE worksheet and stops at the first that works. It uploads nothing and changes nothing.

Cost: failed attempts cost nothing; a successful one counts each member once against the monthly unique-securities
allowance (about 24 for W45 Alpha, whose names are already in the screener and counted this month).

Usage:  python probe_worksheets.py ["W45 Alpha"]"""
import json, sys, traceback
import bbg_sync as s

DEFAULT = "W45 Alpha"


def candidates(ws):
    """Ways of naming the worksheet and the list type that BQL might accept, most likely first."""
    parts = ws.split(None, 1)
    names = [ws] + ([parts[0], parts[1]] if len(parts) == 2 else [])
    out = []
    for kind in ("WATCHLIST", "WORKSHEET", "LIST"):
        for n in names:
            out.append(f"get(name) for(members('{n}', type={kind}))")
    return out


def bql(bbg, expr):
    """One BQL query -> (member names or None, what Bloomberg answered, shortened)."""
    req = bbg.bql_svc.createRequest("sendQuery")
    req.set("expression", expr)
    raw = []
    for m in bbg._send(req, 60000):
        try:
            raw.append(m.toPy())
        except Exception:  # noqa: BLE001   older blpapi: no toPy
            raw.append(str(m))
    text = json.dumps(raw, default=str)
    names = None
    for r in raw:   # the answer is JSON (as a dict, or as a string inside the message)
        if isinstance(r, str):
            try:
                r = json.loads(r[r.index("{"):]) if "{" in r else r
            except ValueError:
                continue
        found = find_names(r)
        if found:
            names = found
    return names, text[:600]


def find_names(obj):
    """The member tickers and names, wherever BQL puts them: {"results": {"name": {"idColumn": {"values": [...]},
    "valuesColumn": {"values": [...]}}}}."""
    if isinstance(obj, dict):
        res = obj.get("results")
        if isinstance(res, dict) and isinstance(res.get("name"), dict):
            col = res["name"]
            ids = (col.get("idColumn") or {}).get("values") or []
            vals = (col.get("valuesColumn") or {}).get("values") or []
            if ids:
                return list(zip(ids, vals + [""] * (len(ids) - len(vals))))
        for v in obj.values():
            f = find_names(v)
            if f:
                return f
    elif isinstance(obj, list):
        for v in obj:
            f = find_names(v)
            if f:
                return f
    return None


def main():
    ws = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or DEFAULT
    print(f"Worksheet probe {s.datetime.now():%Y-%m-%d %H:%M}: can the API read '{ws}'?")
    try:
        bbg = s.Bbg()
    except Exception as e:  # noqa: BLE001
        print(f"  [!!]  Bloomberg not reachable: {e}")
        return 1
    try:
        if not s.logged_in(bbg):
            print(f"  [!!]  Bloomberg is not serving data: are you logged in? ({s.LOGIN_DETAIL})")
            return 1
        if not bbg.s.openService("//blp/bqlsvc"):
            print("  [!!]  Bloomberg refused the BQL service (//blp/bqlsvc): this API login cannot run BQL, so worksheets")
            print("        cannot be read this way. Exporting from W <GO> stays the way to share new names.")
            return 0
        bbg.bql_svc = bbg.s.getService("//blp/bqlsvc")
        for expr in candidates(ws):
            try:
                names, raw = bql(bbg, expr)
            except Exception as e:  # noqa: BLE001
                print(f"  [..]  {expr}\n        failed: {e}")
                continue
            if names:
                print(f"  [OK]  {expr}\n        returned {len(names)} members, e.g. " + ", ".join(f"{t} ({n})" for t, n in names[:8]))
                print("        The daily sync CAN read worksheets this way. Send this window to Claude to switch it on.")
                return 0
            print(f"  [..]  {expr}\n        no members. Bloomberg answered: {raw}")
        print("  [!!]  None of the ways tried returned the worksheet's members. Send this window to Claude: the answers")
        print("        above show what Bloomberg expects, and there may be another way to ask.")
        return 0
    finally:
        print(f"  [..]  Bloomberg allowance used by this probe: {len(bbg.secs | {'SPX Index'})} securities (counted once a month), "
              f"about {bbg.hits + 1} hits. Nothing was uploaded.")
        bbg.close()


if __name__ == "__main__":
    try:
        code = main()
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        print(f"  [!!]  Probe failed: {e}")
        code = 1
    print()
    print("Copy everything in this window and send it to Claude.")
    sys.exit(code)
