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

## Step 6: The daily sync (Claude builds this after the check passes)

Once the check is all `[OK]`, Claude will:

1. Write the sync script. It asks Bloomberg for everything in a few bulk requests and skips the day quietly if you're not logged in.
2. Walk you through **installing Git** (git-scm.com, accept every default) and creating a **GitHub access key** that can only write to your two repositories.
3. Set up **Windows Task Scheduler** to run it every weekday morning, after the time you usually log in.

### Good to know
- **Data limits:** Bloomberg Anywhere has daily and monthly limits on how much data the API can pull. The sync is designed to ask for the full history once, then only each new day.
- **Your firm's rules:** if the main terminal is a work computer, check that installing Python is allowed there.
