# Connecting Bloomberg to the screener: plain-English guide

## The idea in one picture

Think of the Bloomberg Terminal on your PC as a **shop** with a **back door**.

- You normally go in the front door: the Bloomberg screens and the keyboard.
- Excel's Bloomberg tab already uses the back door: when you type `=BDP("SPX Index","PX_LAST")`, Excel walks round the back and asks the shop for the number.
- **Python can use the same back door.** A small helper called `blpapi` (Bloomberg's own "key" for Python) lets a script ask for prices the same way Excel does.

Three rules come with this:

1. **The shop must be open:** Bloomberg has to be running and **you must be logged in** on that PC. The script can't log in for you, because it doesn't have your fingerprint or B-Unit.
2. **The back door only opens from inside the same PC.** The script has to run on the computer where you're logged in to Bloomberg.
3. **One login at a time:** logging in on a second PC usually logs you out of the first. So the script should run on the PC you're normally logged in on: your **main terminal**.

The script doesn't need Claude, Yahoo, Wikipedia or X. It only needs **Bloomberg** (the back door on the same PC) and **github.com** (to upload results to your website). That's why your main terminal's blocks on Yahoo, Wikipedia and X don't matter here.

What it would do every morning: ask Bloomberg for a few things in bulk (index members and weights, Asian prices, consensus, WIRP-type data) and save them to your GitHub repositories, so you never type them in by hand. Only derived numbers, such as signals and rankings, appear on the public website, never raw Bloomberg data.

---

## Step 1: Check that the back door is open (no installing, 2 minutes)

On the **main terminal**, while logged in to Bloomberg:

1. Open **Excel**. You should see a **Bloomberg** tab in the ribbon.
2. In any cell, type `=BDP("SPX Index","PX_LAST")` and press Enter.
3. **A number appears** → the back door works on this PC. Go to step 2.
   **`#NAME?` or no Bloomberg tab** → on Bloomberg, type **HELP HELP** and ask: *"Please enable the Excel add-in / Desktop API for my login."*

If Excel works, Python will almost certainly work too, because they use the same door.

## Step 2: Can you install programs on the main terminal?

Try installing Python (step 3).

- **It installs** → great, keep going.
- **It asks for an administrator password you don't have, or is blocked** → stop here and tell Claude. There's a plan B that runs entirely inside Excel on the main terminal.

## Step 3: Install Python (5 minutes)

1. Go to **python.org/downloads** and press the big yellow **Download Python** button.
2. Open the downloaded file.
3. **Important:** on the first screen, tick **"Add python.exe to PATH"** at the bottom, then press **Install Now**.
4. When it says "Setup was successful", close it.

## Step 4: Install Bloomberg's Python "key" (2 minutes)

1. Press the **Windows key**, type `cmd`, and open **Command Prompt** (a black window).
2. Copy this whole line, paste it into the black window (right-click pastes), and press Enter:

   ```
   python -m pip install --index-url=https://blpapi.bloomberg.com/repository/releases/python/simple/ blpapi
   ```

3. Wait until it says **Successfully installed blpapi**.
   If you see red text about a proxy or a certificate, copy it and send it to Claude.

## Step 5: Run the check (1 minute)

1. Go to **github.com/alternateKen/stock-screener**, press the green **Code** button, then **Download ZIP**.
2. Open the ZIP, open the `bloomberg` folder, and drag `check_connection.py` and `check_connection.bat` onto your Desktop.
3. Make sure you're logged in to Bloomberg, then **double-click `check_connection.bat`**.
4. A window shows lines starting with `[OK]` or `[!!]`. **Copy everything in that window and send it to Claude.**

The check only *reads* a few numbers (S&P 500, Nvidia, TSMC, the Nasdaq-100 member list) and shows them on your screen. It sends nothing anywhere.

## Step 6: Give the sync a permanent home (3 minutes)

1. Download the repository ZIP again (green **Code** button, then **Download ZIP**), because it now contains the sync files.
2. Open **File Explorer** and go to your user folder (`C:\Users\<your name>`). Create a folder named exactly **`bbg_sync`**.
3. From the ZIP's `bloomberg` folder, copy **everything** into `bbg_sync`. That includes `bbg_sync.py`, the two `..._tickers.csv` lists and all the `.bat` files.

From now on, everything happens in `C:\Users\<your name>\bbg_sync`.

## Step 7: Create a GitHub key that can only update your two repositories (5 minutes)

The sync needs a key to upload to GitHub. This key can **only** change the files in `macro-updates` and `stock-screener`, nothing else in your account.

1. In Chrome, go to **github.com → your picture (top right) → Settings → Developer settings** (bottom of the left menu) **→ Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Token name:** `Bloomberg sync`. **Expiration:** the longest offered (put a reminder in your calendar to renew it).
3. **Repository access:** choose **Only select repositories** and pick **macro-updates** and **stock-screener**.
4. **Permissions → Repository permissions → Contents:** choose **Read and write**. Leave everything else as it is.
5. Press **Generate token** and **copy** the long code that starts with `github_pat_`.
6. Open **Notepad**, paste the code, then **File → Save as**:
   - Go to the `bbg_sync` folder.
   - Set **Save as type** to **All files**.
   - Set **File name** to **`token.txt`**.
   - Press Save.

Treat this key like a password: **never paste it into a chat (including Claude), an email or a GitHub file.** It stays in `token.txt` on this PC only.

## Step 8: Test run, which uploads nothing (2 minutes)

1. Make sure you're logged in to Bloomberg.
2. In `bbg_sync`, double-click **`run_test.bat`**.
3. It fetches everything once and saves the files in a folder on your Desktop called **`bloomberg_test_output`**. It does **not** upload anything.
4. Copy everything in the black window (**Ctrl+A**, then **Enter**) and send it to Claude.
   Lines starting with `[..] check against ...` ask you to compare one number with the Bloomberg screen (ECO or ANR). Mention whether they match.

Claude fixes anything Bloomberg named differently, and you download the updated file. Then:

## Step 9: Switch it on (2 minutes)

1. Double-click **`run_now.bat`** once. It fetches and **uploads** straight away, so you can see the dashboards update within a few minutes.
2. Double-click **`install_schedule.bat`**. From now on Windows starts the sync every 15 minutes:
   - **Outside weekdays 07:00–21:00** (this PC's clock) it does nothing.
   - **At 08:30, 16:30 and 20:00** a "slot" becomes due. It runs **the first time you're logged in to Bloomberg after that time**.
   - **If Bloomberg is logged out**, it stops quietly and tries again 15 minutes later. It never logs in for you.
   - Every slot updates Fed pricing, credit indices and the economic calendar. The screener's analyst consensus updates once a day, and index weights once a week.
3. To see what it did, double-click **`show_log.bat`**. To switch it off, double-click **`remove_schedule.bat`**.

### What it fills in automatically
| Macro dashboard (`macro-updates`) | Screener (`stock-screener`) |
|---|---|
| `bloomberg/wirp_us.csv`: Fed pricing by meeting, calculated from fed funds futures (the same method as WIRP and CME FedWatch, so numbers can differ slightly from the WIRP screen) | `data/bloomberg_consensus.json`: the **Street** column. Upside to the average analyst target, % of analysts rating Buy, and whether earnings estimates rose or fell over 4 weeks |
| `bloomberg/credit.csv`: CDX / iTraxx levels and 3-month range (the basis and roll columns are not available by API, so they stay blank) | |
| `bloomberg/eco.csv`: US releases for the next 2 weeks with survey and prior, plus last week's actuals | |
| `weights/*.csv`: exact index weights for the top-movers cards | |

**Still typed by hand for now:** `wirp_global.csv` (other central banks). Bloomberg's WIRP screen for other countries uses each country's OIS curve, and there is no simple API field for it. Ask Bloomberg (**HELP HELP**): *"Can WIRP meeting probabilities for other central banks be downloaded through the Excel/Desktop API, and with which tickers or fields?"* If they give you tickers, Claude can add them.

### Good to know
- **Data limits:** each run uses a small part of Bloomberg Anywhere's API allowance. The heaviest step, consensus for about 800 stocks, runs once a day.
- **The public site** shows only derived numbers for the screener (percentages, never Bloomberg's raw target prices). The macro files show the same kind of numbers you previously typed in by hand.
- **Your firm's rules:** if this is a work computer, make sure running a scheduled script with Bloomberg data is allowed.
- **If you change PC:** repeat steps 3, 4 and 6–9 on the new PC.
