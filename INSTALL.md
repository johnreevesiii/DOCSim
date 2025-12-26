# DOCSim — Step-by-Step Install & Run Guide (Non‑Technical)

This guide walks you through getting DOCSim running on your computer from a GitHub download.

DOCSim is a fan-made, text-based simulation inspired by Derby Owners Club. It does **not** include any game ROMs or proprietary arcade assets.

---

## Option A (Recommended): Download the ready-to-run ZIP from GitHub

1. Go to the GitHub page for DOCSim.
2. Click **Releases** (right side) and download the latest **DOCSim_...zip** file.
3. Extract the ZIP:
   - Windows: right-click → **Extract All**
   - Mac: double-click the ZIP (it will expand into a folder)

---

## Step 1 — Install Python (required)

DOCSim requires **Python 3.10+**.

### Windows
1. Go to python.org → **Downloads** → download Python 3.10+ for Windows.
2. Run the installer.
3. **Important:** check the box **“Add python.exe to PATH”**.
4. Finish installation.

### Mac
Option 1: python.org installer (simple)
1. Go to python.org → **Downloads** → download Python 3.10+ for macOS.
2. Install it.

Option 2: Homebrew (advanced)
- `brew install python`

---

## Step 2 — Download (or locate) the Breeder HTML file

DOCSim expects a local file named like:

- `DOC_Horse_Breeder_Lite_RevC_RevD.html`

You will be asked for its file path when you launch DOCSim.

Tip: keep it in the same folder as DOCSim to make this easy.

---

## Step 3 — Run DOCSim

### Windows (easiest)
1. Open the extracted DOCSim folder.
2. Double-click: **Run-DOCSim.bat**
3. Answer the on-screen prompts:
   - Breeder HTML path
   - Revision (revC or revD)
   - Seed (optional)
   - Max rounds

If Windows asks for permission, choose **Run anyway** (it’s a local script).

### Windows (PowerShell alternative)
1. Open the DOCSim folder.
2. Hold **Shift** and right-click in empty space → **Open PowerShell window here**
3. Run:
   - `powershell -ExecutionPolicy Bypass -File .\Run-DOCSim.ps1`

### Mac (Terminal)
1. Open **Terminal**
2. Go to the DOCSim folder (drag the folder into Terminal after typing `cd `)
3. Run:
   - `python3 -m docsim.main --breeder-html "/full/path/to/DOC_Horse_Breeder_Lite_RevC_RevD.html" --rev revD --seed 12345 --max-rounds 1`

---

## Common Troubleshooting

### “python is not recognized” (Windows)
Python was not added to PATH.
- Re-run the Python installer and select **Add python.exe to PATH**, or
- Install again and ensure that checkbox is selected.

### “Running scripts is disabled on this system”
Use the BAT launcher:
- **Run-DOCSim.bat**
Or run PowerShell with a bypass just for this launch:
- `powershell -ExecutionPolicy Bypass -File .\Run-DOCSim.ps1`

### I don’t know the path to the Breeder HTML file
On Windows:
- Right-click the file → **Copy as path** (then paste into the prompt)

On Mac:
- Drag the file into Terminal to paste its full path

---

## Where save data lives

DOCSim writes a few local files while you play:
- `data/records_state.json` (national records — created on first run)
- `docsim_config.json` (launcher remembers your breeder HTML path and revision)

You can delete these files to “reset” things, or use the launcher prompts to reset records/world.

