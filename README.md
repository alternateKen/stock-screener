# Stock Screener

One website with all your themed watchlists plus a broad technical screen. It refreshes itself during US market hours, using free Yahoo Finance prices, TradingView's technical rating and Wikipedia index membership, with no API keys.

- **Home page:** one card per theme (day / 1M / YTD, relative strength vs the S&P 500, breadth, average trend score, signal counts, best and worst basket). Below that, a summary of the broad screen.
- **Market direction (top of the home page):** about 70 index, style, sector, industry, bond, commodity and country ETFs (theme file `themes/market-etfs.txt`), each with its trend. Rotation gauges show where money is moving: equal weight vs cap weight, small vs large caps, growth vs value, high yield vs Treasuries, discretionary vs staples, semis vs the S&P, international vs US, gold vs stocks.
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

**Price structure** (`scripts/patterns.py`):
- **Trend:** uptrend, downtrend or sideways. Each of these adds or subtracts a point: higher or lower swing highs; higher or lower swing lows; price above or below the 50-day average; the 50-day average rising or falling; the 50-day above or below the 200-day; price above or below the 21-day EMA; and the 21-day EMA rising or falling (over 5 sessions). +3 or more is an uptrend, -3 or less a downtrend. "Strong" means ADX is above 25; a sideways reading with ADX above 25 shows as "Sideways (strong move)", since mixed signals during a forceful move are not a quiet range. "Range-bound" means sideways with ADX below 20.
- **Short-term trend** (shown under the trend): up when price is above EMA 9, EMA 9 is above EMA 21 and both are rising; down for the mirror image; mixed otherwise.
- **Support / resistance:** turning points (swing highs and lows) from the past year are grouped into price bands about one ATR wide. A level's strength is the number of times price turned there. The two nearest levels below and above the price are shown, ranked by distance and touches, within 30% of the price.
- **Moving averages:** EMA 9, 21, 50, 100 and 200 on daily closes, and the same five on weekly closes (9 to 200 weeks), from five years of prices. The tables show price above (▲) or below (▼) each and whether that EMA is rising (↗) or falling (↘): higher or lower than 5 bars ago. The chart draws the daily EMAs (EMA 100 starts switched off) and, optionally, the simple MA 50 and MA 200, which still drive the trend score, the 50 / 200-day crosses and the Bloomberg data check.
- **EMA touches:** a signal whenever the day's range (low to high) reaches a daily EMA, or the week's range reaches a weekly EMA, saying whether that EMA is rising or falling (green = rising, red = falling). They can be filtered on the signals page but are left out of the bullish / bearish counts and rankings.
- **Chart patterns** (each "forming" until the close breaks its neckline / breakout level by 1%, then "confirmed" for 15 sessions, always with a measured target):
  - **Double top / bottom:** two peaks or troughs within 3%, at least 15 days apart, with a dip of at least 5% (or 3× ATR) between them, after a prior move.
  - **Head and shoulders / inverse:** a head at least 3% beyond two roughly level, roughly balanced shoulders; neckline through the two troughs.
  - **Ascending / descending / symmetrical triangle, rising / falling wedge:** least-squares trendlines through at least 2 recent swing highs and 2 swing lows (15–120 bars, last touch within 25 bars). Every touch must sit within ~0.6 ATR of its line, the closes must stay inside the lines, and the lines must converge by at least 25%. Flat top + rising bottom = ascending; falling top + flat bottom = descending; falling top + rising bottom = symmetrical; both rising and converging = rising wedge (bearish); both falling and converging = falling wedge (bullish). Confirmed breaks say which way they broke.
  - **Bull / bear flag and pennant:** a pole of at least 10% and 5× ATR in at most 12 bars (ending 4–20 bars ago), then a tight pause retracing less than 40% of the pole. A converging pause is a pennant; a parallel one drifting against the pole is a flag. The target is the pole's length added to the breakout.
  - **Cup and handle:** after an advance of at least 15%, two rims within 5% and a U-shaped cup 30–250 bars wide and 12–50% deep (parabola fit, R² ≥ 0.7, bottom in the middle), then a 3–30 bar handle staying in the cup's upper third. The breakout is the rim.
  - **Rounding bottom:** a U-shaped base over 60–200 bars (R² ≥ 0.7, low point in the middle half, at least 12% deep) whose right side has recovered at least 60%. The breakout is the left rim.
- **Breakout / breakdown:** the close moved at least 1% through the nearest level (touched twice or more) within the last 3 sessions, on at least 1.3× the 20-day average volume.
- The chart page draws all of these on the candles: S1/S2 and R1/R2 lines, the pattern's peaks and troughs, the neckline, and the target.

**Trend score (0–6):** one point each for price above its 50-day average, above its 200-day average, 50-day above 200-day, MACD above its signal line, RSI above 50, and beating the S&P 500 over 3 months.

Signals from a run during market hours use today's partial bar, so they're provisional until the close. The page and the Claude brief say when this applies.

## Refresh times (weekdays)
Every 30 minutes during Asian market hours (00:20 to 08:50 UTC, 8:20am to 4:50pm Singapore / Hong Kong time), about 6:15am New York time (after every Asian market has closed), then every 30 minutes from about 9:05am to 4:35pm New York time. It also refreshes whenever a theme file changes or you press **Run workflow**. GitHub often starts scheduled runs late; the external timer in macro-updates' `TIMER_SETUP.md` works here too (point it at this repository's workflow).

## Files
`scripts/screen.py` (download + indicators + signals, standard Python only), `scripts/track_briefs.py` (brief scorecard), `data/briefs/` (archived morning briefs), `tests/` (offline checks run before every build),
`docs/` (the pages: `index.html`, `theme.html`, `screen.html`, `chart.html`, plus `common.js`, `style.css` and `vendor/` with TradingView's open-source Lightweight Charts library, Apache 2.0),
`themes/*.txt` (your lists), `universe.txt` (broad screen), `.github/workflows/update.yml` (schedule).

## Technical brief (`brief.html`, `brief.json`)
Every rebuild also writes `brief.json`: long setups (breakouts and new highs, Lead-tier pullbacks to the 9 / 21 EMA, bullish patterns within 3% of breaking out), short setups (breakdowns and new lows, Lagging-tier bounces into the 9 / 21 EMA, bearish patterns within 3% of breaking down), what improved or deteriorated since the previous session (tier changes, short-term trend turns), breadth, themes and the leaders' health. It covers the theme stocks and the leaders list, and the setup lists need about US$5M traded a day. Each rebuild also compares itself with the previous one (`state.json`) and keeps a 24-hour log of what changed: tier moves, short-term trend turns, trend changes, 21-day EMA crosses, new breakouts / breakdowns, 52-week highs / lows, 50 / 200-day crosses and the leaders' health. `brief.html` shows it as strengthening (long) vs weakening (short), with filters for since 06:30 and for Asian / non-US stocks. `brief.html` shows it; the daily Claude brief in Notion is written from it.

## Brief scorecard (`scorecard.html`, `scripts/track_briefs.py`)
Measures how every setup in the morning brief actually did afterwards, so the rules can be tuned on evidence.

The page opens on the latest brief: every setup grouped by list, with its entry price and, for 1D, 1W and 20D, the close-to-close move and the high and low traded. Statistics across all briefs (hit rates, mechanics, the health call, themes) sit below it.

- **Archive:** after each rebuild, `track_briefs.py archive docs` copies the brief the 06:30 Notion brief is written from (any build between that US session's close and Tokyo's next open, weekend rebuilds included) to `data/briefs/<US session>.json`, stamping each setup with its signal bar. The workflow commits new archive files; `brief.json` itself is overwritten every 30 minutes, so this is the only record.
- **Score:** `track_briefs.py evaluate docs` scores every archived brief from the screener's own candles (`docs/charts/`, no extra Yahoo calls for stocks; only the ~10 benchmark indices are fetched) and writes `docs/scorecard.json` and `docs/scorecard.csv`.
- **Measures:** entry at the signal close and at the next session's open; 1D, 1W (5 sessions) and 20D in each stock's own sessions; the highest and lowest prices traded in each window; return with shorts flipped, excess vs the S&P 500, vs the home index (KOSPI / KOSDAQ / TAIEX / TOPIX ETF / HSI / CSI 300 ETF / ASX 200 / SET50 ETF / KLCI) and vs an equal-weight basket of all theme stocks; best / worst excursion, pattern trigger and target hits, broken levels held, tiers held; the leaders' health call and the theme ranking (rank correlation with what came next).
- **Curated layer:** brief.json has no Best long / Cleanest / Extended picks, which only exist in the Notion text. Save a Notion brief as Markdown and run `python scripts/track_briefs.py import-notion page.md` to add them (also rebuilds a missing day from Notion).
- **On your PC (no Bloomberg calls):** `python scripts/track_briefs.py evaluate out --fetch` pulls Yahoo prices with the screener's own code (cached per day in `data/.price_cache`) and writes `out/scorecard.csv` for Excel.
- **Midday editions:** the first build from 12:00 Malaysia time (the Asia midday update) and the first build 1 hour after the US open (the US midday update) are also archived, as `data/briefs/<day>-asia.json` (non-US stocks only) and `<day>-us.json` (US stocks only). Their setups are measured from the price at that build, with a Close window (the rest of that day) before 1D / 1W / 20D. The statistics, health call, themes and positions use the morning brief only, so they stay comparable.
- **Shadow test (shorts):** a filtered short book is scored next to the brief's own, without changing the brief: no bounce or breakdown shorts on mornings whose leaders' health call is Risk-off or Improving (near-breakdown shorts stay), and bounce shorts that only touched a falling EMA need a close within 5% of the 21 EMA. It comes from the 2-year backtest (20-day result vs the theme basket: whole short book +0.6% now, +1.7% filtered). Shorts it would drop are tagged "shadow: skip"; the statistics show both books and `pos_summary_shadow` the short positions. It scores a subset of the brief's 15-name lists, while the real rule would refill them.
- **Positions:** the same setups followed per stock. A position opens the first time a stock appears in a long or short setup list, stays open while later briefs repeat that direction, and closes when a brief lists the stock on the other side (a flip: closed at that brief's signal close, and a new position opens) or after 20 sessions. Each has its result, the high and low traded while open, the best close and how much was given back; a flip within 5 sessions is marked as a whipsaw. Every appearance still keeps its own 1D / 1W / 20D windows. `positions.csv` has them all.
- **Bloomberg prices (private):** `bloomberg/bbg_sync.py` also uploads daily open / high / low / close for every stock in the last 45 days of briefs, and the benchmark indices, to the private repository `stock-screener-prices` (raw Bloomberg prices never go to this public site; see `bloomberg/SETUP.md`, step 10). On a PC with a clone of it, `python scripts/track_briefs.py evaluate out --fetch --bbg=../stock-screener-prices/bbg_daily.json` scores with Bloomberg first and Yahoo for anything missing. The public site's own scorecard stays on Yahoo.
- **Sub-lists:** breakouts and breakdowns are also scored by signal (through a level / 52-week high or low only / moving-average cross only), and pullbacks and bounces by rule path (within the 21-EMA band / EMA touch only, i.e. extended).
- **Historical backtest (on your PC):** `python scripts/backtest_briefs.py [--years=2]` rebuilds the brief for every past US session from five years of Yahoo candles with the same `analyse()` and `build_brief()`, scores them all and writes `backtest/` (git-ignored): `summary.md` (hit rates, excess vs the theme basket with block-bootstrap 90% intervals, results by health call), `scorecard.csv`, and `scorecard.html` (serve with `python -m http.server -d backtest`). It uses today's theme lists (survivorship), so read excess vs the theme basket rather than raw returns; it has no TradingView ratings or Bloomberg checks, which the setup lists don't use.

## High-ADR leaders (`leaders.html`)
A fixed list in `leaders.txt` (Quantum, Space, AI, Crypto, Semis, plus mega-caps as the benchmark), chosen for a 20-day ADR above 5% and $20M+ traded a day. Every rebuild sorts them into tiers by their EMAs, as Kristjan Qullamaggie and Martin Luk do: **Lead** (9 > 21 > 50 EMA), **Lagging** (9 < 21 < 50 EMA) and **Mediocre** (anything else). The page tracks the tier counts over 120 sessions as a market-health gauge: when Lead shrinks and Lagging expands, stop buying breakouts, reduce size and look for shorts on bounces. The list is not a theme, so the Bloomberg sync does not read it.

## Bloomberg
`bloomberg/bbg_sync.py` runs on the PC where you're logged in to Bloomberg (your main terminal). Windows Task Scheduler starts it every 15 minutes, but it only does anything once a day (the first time Bloomberg is logged in on a weekday from 05:30, until 21:00), plus whenever you double-click `run_now.bat`. Each run also reads the Excel exports of your Bloomberg worksheets saved in `%USERPROFILE%bg_sync\worksheets` and adds names the site does not have yet to the Inbox theme. It updates the screener's **Street** column: Bloomberg consensus as derived numbers only (upside to target, % Buy, 4-week EPS revisions), and Bloomberg's 50 / 200-day averages for the ⚠ data check. It stays inside the Bloomberg API allowance (under 2,500 unique securities a month). The macro dashboard's Bloomberg files are no longer updated by it.

When a stock gets the ⚠ (its averages are more than 3% from Bloomberg's), the usual cause is a corporate action Yahoo has not adjusted its history for: a spin-off, return of capital or rights issue (check `CACS <GO>`). Add a line to `data/adjustments.txt` (`CODE | effective date | factor | note`): the screener scales Yahoo's prices before that date by the factor, and the ⚠ clears on the next rebuild.

The file goes up in one commit, using a GitHub key that can only write to this repository.

**Setup:** [`bloomberg/SETUP.md`](bloomberg/SETUP.md) is a plain-English guide: connection check, then the GitHub key, then a test run that uploads nothing, then switching it on.
