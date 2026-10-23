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

What it does once a week: ask Bloomberg for analyst consensus on every stock in your themes, and save it to the stock-screener repository, so you never type it in by hand. Only derived numbers, such as upside percentages, appear on the public website, never raw Bloomberg data. (The charts themselves come from free data and don't use Bloomberg.)

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

The sync needs a key to upload to GitHub. This key can **only** change the files in `stock-screener`, nothing else in your account. (An existing key that also covers `macro-updates` keeps working.)

1. In Chrome, go to **github.com → your picture (top right) → Settings → Developer settings** (bottom of the left menu) **→ Personal access tokens → Fine-grained tokens → Generate new token**.
2. **Token name:** `Bloomberg sync`. **Expiration:** the longest offered (put a reminder in your calendar to renew it).
3. **Repository access:** choose **Only select repositories** and pick **stock-screener**.
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
3. It fetches consensus for 5 stocks and saves the file in a folder on your Desktop called **`bloomberg_test_output`**. It does **not** upload anything.
4. Copy everything in the black window (**Ctrl+A**, then **Enter**) and send it to Claude.
   Lines starting with `[..] check against ...` ask you to compare one number with the Bloomberg screen (ANR). Mention whether they match.

Claude fixes anything Bloomberg named differently, and you download the updated file. Then:

## Step 9: Switch it on (2 minutes)

1. Double-click **`install_schedule.bat`**. From now on Windows starts the sync every 15 minutes:
   - It does nothing unless **this week's run** is still due. The weekly run happens **the first time you're logged in to Bloomberg on a weekday from Monday, after 08:30** (07:00–21:00 on this PC's clock). If you're not logged in on Monday, it runs on Tuesday, and so on.
   - **If Bloomberg is logged out**, it stops quietly and tries again 15 minutes later. It never logs in for you.
   - Weekly runs start on **2 November 2026** (October's allowance is used up).
2. To see what it did, double-click **`show_log.bat`**. To switch it off, double-click **`remove_schedule.bat`**.

## Extra runs, whenever you want (about 2–3 a week is fine)

Double-click **`run_now.bat`**. It asks for **extra tickers**:
- **Press Enter** to refresh every theme stock straight away.
- **Or type tickers** separated by commas, e.g. `NVDA, 2330 TT, 0700 HK`. Every theme stock is refreshed, plus these. Tickers that aren't in any theme yet are added to the **Inbox** theme on the site, so they get charts and signals too (sort them into a theme later).

Re-running the same stocks doesn't count again against the monthly unique-securities limit, so extra runs are cheap. Each new ticker counts once a month.

### What it fills in automatically
`data/bloomberg_consensus.json` in stock-screener: the **Street** column (upside to the average analyst target, % of analysts rating Buy, whether earnings estimates rose or fell over 4 weeks) and Bloomberg's 50 / 200-day averages, used for the ⚠ data check.

The macro dashboard's Bloomberg files (Fed pricing, credit, economic calendar, index weights) are **no longer updated** by the sync, to save the allowance. They keep their last values.

### Good to know
- **Data limits:** Bloomberg Anywhere's API allowance counts **unique securities per month** and **hits per day** (one security × one field = one hit). The sync keeps its own count and stays under **2,500 unique securities a month** and **300,000 hits a day**, stopping rather than going over. Every run prints its totals, e.g. `Bloomberg allowance used by this sync: 840 unique securities this month`. A full run is about 830 securities (your theme stocks) and roughly 10,000 hits, so weekly runs plus 2–3 extra a week fit easily. `run_test.bat` costs almost nothing (5 stocks).
- **The public site** shows only derived numbers for the screener (percentages, never Bloomberg's raw target prices).
- **Your firm's rules:** if this is a work computer, make sure running a scheduled script with Bloomberg data is allowed.
- **If you change PC:** repeat steps 3, 4 and 6–9 on the new PC.
