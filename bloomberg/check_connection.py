"""Bloomberg connection check: asks the Bloomberg Terminal running on THIS computer for a few numbers
and says, in plain English, whether everything is ready for the automatic daily sync.

Nothing is sent anywhere: the answers are only printed on your screen. Run it by double-clicking
check_connection.bat (in the same folder) while you are logged in to Bloomberg."""
import datetime as dt
import sys

OK, BAD = "  [OK]  ", "  [!!]  "


def stop(msg):
    print()
    print(BAD + msg)
    print()
    print("Copy everything in this window and send it to Claude.")
    sys.exit(1)


print("Bloomberg connection check")
print("=" * 60)
print(OK + f"Python {sys.version.split()[0]} is installed")

try:
    import blpapi
except ImportError:
    stop("The Bloomberg Python connector (blpapi) is not installed yet. Do step 4 of the guide, then run this again.")
print(OK + f"Bloomberg Python connector installed (blpapi {getattr(blpapi, '__version__', '?')})")

# The Bloomberg Terminal listens on this computer ("localhost") on port 8194 while you are logged in
opts = blpapi.SessionOptions()
opts.setServerHost("localhost")
opts.setServerPort(8194)
session = blpapi.Session(opts)
if not session.start():
    stop("Could not reach the Bloomberg Terminal on this computer. Is Bloomberg open and are you logged in "
         "(you can see a normal Bloomberg screen)? Log in, wait a minute, and run this again.")
print(OK + "Reached the Bloomberg Terminal on this computer")
if not session.openService("//blp/refdata"):
    stop("Bloomberg answered but refused the data service. Your login may not include API access: "
         "type HELP HELP on Bloomberg and ask 'Is the Desktop API (Excel/Python) enabled for my Bloomberg Anywhere login?'")
svc = session.getService("//blp/refdata")


def ask(request):
    session.sendRequest(request)
    out = []
    while True:
        ev = session.nextEvent(10000)
        for msg in ev:
            if msg.messageType() in (blpapi.Name("ReferenceDataResponse"), blpapi.Name("HistoricalDataResponse")):
                out.append(msg)
        if ev.eventType() == blpapi.Event.RESPONSE:
            return out
        if ev.eventType() == blpapi.Event.TIMEOUT:
            stop("Bloomberg did not answer within 10 seconds. Try again; if it keeps happening, restart the Terminal.")


# 1) today's numbers (like =BDP in Excel)
req = svc.createRequest("ReferenceDataRequest")
for t in ("SPX Index", "NVDA US Equity", "2330 TT Equity"):
    req.append("securities", t)
for f in ("NAME", "PX_LAST", "CHG_PCT_1D"):
    req.append("fields", f)
for msg in ask(req):
    data = msg.getElement("securityData")
    for i in range(data.numValues()):
        sd = data.getValueAsElement(i)
        name = sd.getElementAsString("security")
        if sd.hasElement("securityError"):
            print(BAD + f"{name}: {sd.getElement('securityError').getElementAsString('message')}")
            continue
        fd = sd.getElement("fieldData")
        get = lambda f: fd.getElementAsString(f) if fd.hasElement(f) else "n/a"   # noqa: E731
        print(OK + f"{name:<16} {get('NAME')[:28]:<28} last {get('PX_LAST')}  day {get('CHG_PCT_1D')}%")

# 2) price history (like =BDH in Excel)
req = svc.createRequest("HistoricalDataRequest")
req.append("securities", "SPX Index")
req.append("fields", "PX_LAST")
req.set("startDate", (dt.date.today() - dt.timedelta(days=10)).strftime("%Y%m%d"))
req.set("endDate", dt.date.today().strftime("%Y%m%d"))
rows = 0
for msg in ask(req):
    rows += msg.getElement("securityData").getElement("fieldData").numValues()
print((OK if rows else BAD) + f"Price history works: {rows} days of S&P 500 closes in the last 10 days")

# 3) index members (needed to keep stock lists current automatically)
req = svc.createRequest("ReferenceDataRequest")
req.append("securities", "NDX Index")
req.append("fields", "INDX_MEMBERS")
members = 0
for msg in ask(req):
    sd = msg.getElement("securityData").getValueAsElement(0)
    if sd.getElement("fieldData").hasElement("INDX_MEMBERS"):
        members = sd.getElement("fieldData").getElement("INDX_MEMBERS").numValues()
print((OK if members else BAD) + f"Index members work: {members} Nasdaq-100 members")

session.stop()
print("=" * 60)
print("All done. Copy everything in this window and send it to Claude.")
