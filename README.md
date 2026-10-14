# Stock Screener

One website with all your themed watchlists plus a broad technical screen. It refreshes itself during US market hours, using free Yahoo Finance prices, TradingView's technical rating and Wikipedia index membership, with no API keys.

- **Home page:** one card per theme (day / 1M / YTD, relative strength vs the S&P 500, breadth, average trend score, signal counts, best and worst basket). Below that, a summary of the broad screen.
- **Theme pages:** one per file in `themes/`. Each has basket cards, best/worst today, technical signals, unusual volume, RSI extremes, sortable tables (Day, 1W, 1M, YTD, vs S&P 3M, 52-week range, 50d/200d trend, RSI 14, volume, trend score), headlines, a live TradingView price box and a **Copy brief for Claude** button.
- **Chart pages:** click any stock's name for a daily candle chart (3M / 6M / 1Y / 2Y) with 20/50/200-day moving averages, volume, golden/death cross markers, and RSI 14 and MACD panels underneath, all moving together. Each page also has its technical summary, an optional live TradingView chart, and a **Copy chart read for Claude** button that sends Claude the last 60 sessions of prices and indicators.
- **Signals page:** about 650 stocks (S&P 500 and Nasdaq-100 members, loaded live from Wikipedia, plus curated large caps in Hong Kong, China A-shares, Taiwan, Korea and Japan). It shows breadth by GICS sector and market, and a filterable list of every stock with a signal. It has its own Claude brief.

Companion page: [macro-updates](https://github.com/alternateKen/macro-updates) (macro dashboard).
This replaces [agentic-watchlist](https://github.com/alternateKen/agentic-watchlist); its list is now `themes/agentic-ai.txt`.

## Switch-on (one time)
1. Settings, Pages, Source: choose **GitHub Actions**.
2. Actions tab, "Update stock screener", **Run workflow**.
3. Open the link shown on the finished run (`https://alternateken.github.io/stock-screener/`) and bookmark it.

## Changing stocks
Every theme is one text file in `themes/`. Open it on GitHub, click the pencil, edit, then **Commit changes**. The site rebuilds itself.

```
@title AI Supply Chain              <- name shown on the site
@description One sentence ...       <- shown under the name
@order 20                           <- position on the home page (lower = first)

[Memory & Storage]                  <- starts a basket
MU | Micron                         <- one stock per line: TICKER | Company name
000660 KS | SK Hynix                <- Bloomberg style codes work (TT, HK, JP, CH, KS, LN, GY, FP ...)
SHOP | Shopify | NASDAQ             <- optional 3rd column: TradingView exchange if the live box says "symbol not found"
```

- **New theme:** add a new `.txt` file to `themes/`. No new repository or workflow is needed.
- **New tickers you haven't sorted yet:** paste them into `themes/inbox.txt`. They show up under "Inbox" straight away, and Claude can sort them into themes later.
- **Broad screen universe:** `universe.txt`. US index members come from Wikipedia (`@wikipedia`, which also gives the GICS sector). If Wikipedia can't be read, the backup sources listed under it (`@source`) are tried in order: Nasdaq's own Nasdaq-100 list, then Slickcharts. Members from a backup take their sector from the S&P 500 list. Asian lists are plain stock lists.
- A stock that appears in several themes is downloaded only once.
- Only tickers go in these files, never position sizes: this repository and its site are public.

## What the signals mean
| Signal | Rule |
|---|---|
| New 52-week high / low | Today's close is above (below) every close of the past year |
| Crossed above / below 50-day or 200-day | Price crossed the moving average in the last 3 sessions |
| Golden / death cross | 50-day average crossed above (below) the 200-day in the last 5 sessions |
| MACD up / down | MACD (12, 26, 9) crossed its signal line in the last 3 sessions |
| RSI ≥ 70 / ≤ 30 | Wilder RSI 14, same as TradingView's default |
| Volume surge | Volume at least 2× the 20-day average (partial during the day) |

**TradingView rating:** TradingView's own technical summary (Strong buy … Strong sell, built from about 26 moving averages and oscillators), from its screener. It's a second opinion next to our own signals; the Claude briefs ask Claude to flag where the two disagree. It comes from an undocumented TradingView endpoint, so if TradingView changes or blocks it, the column goes blank and everything else keeps working.

**Trend score (0–6):** one point each for price above its 50-day average, above its 200-day average, 50-day above 200-day, MACD above its signal line, RSI above 50, and beating the S&P 500 over 3 months.

Signals from a run during market hours use today's partial bar, so they're provisional until the close. The page and the Claude brief say when this applies.

## Refresh times (weekdays)
About 6:15am New York time (after every Asian market has closed), then every 30 minutes from about 9:05am to 4:35pm New York time. It also refreshes whenever a theme file changes or you press **Run workflow**. GitHub often starts scheduled runs late; the external timer in macro-updates' `TIMER_SETUP.md` works here too (point it at this repository's workflow).

## Files
`scripts/screen.py` (download + indicators + signals, standard Python only), `tests/` (offline checks run before every build),
`docs/` (the pages: `index.html`, `theme.html`, `screen.html`, `chart.html`, plus `common.js`, `style.css` and `vendor/` with TradingView's open-source Lightweight Charts library, Apache 2.0),
`themes/*.txt` (your lists), `universe.txt` (broad screen), `.github/workflows/update.yml` (schedule).

## Bloomberg (in progress)
GitHub can't connect to Bloomberg, so a small script will run on the PC where you're logged in to Bloomberg (your main terminal). Once a day it will pull index members and weights, Asian price history and consensus data in a few bulk requests and save them here automatically, with no typing. Only derived signals are shown on this public site, never raw Bloomberg data.

**Start here:** [`bloomberg/SETUP.md`](bloomberg/SETUP.md) is a plain-English guide. Its first step is a 2-minute Excel test, then `bloomberg/check_connection.bat`, which only reads a few numbers and shows them on your screen.
