# Stock screener: notes for Claude Code

Static site (GitHub Pages) rebuilt by `.github/workflows/update.yml` on a schedule and on every push to `main`.

- `scripts/screen.py`: the engine (Yahoo prices, indicators, signals, TradingView rating, Bloomberg consensus merge) -> `docs/data.json` and `docs/charts/*.json`. Standard library only.
- `scripts/patterns.py`, `scripts/shapes.py`: trend, support / resistance, chart patterns.
- `docs/`: pages (`index.html`, `theme.html`, `screen.html`, `chart.html`, shared `common.js`, `style.css`).
- `themes/*.txt`: one file per theme, `[Basket]` headers and `CODE | Name` lines (Bloomberg-style codes work: `2330 TT`, `0700 HK`, `7203 JT`, `005930 KP`, `BRK/B US`). `themes/inbox.txt` holds unsorted tickers.
- `universe.txt`: broad screen (S&P 500 / Nasdaq-100 members loaded live, Asian lists inline).
- `bloomberg/`: the sync that runs on the owner's Bloomberg PC (not in CI).

Before pushing: `python -m unittest discover -s tests` (the workflow runs the same tests first).
Only tickers in theme files, never position sizes: the repository and site are public.
