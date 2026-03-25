# Designer Setup Guide

This guide gets you from zero to a live, interactive version of the app running on your machine — no API keys, no backend knowledge needed.

---

## What you're working with

The entire UI lives in one file: `templates/index.html`. It's vanilla HTML, CSS, and JavaScript — no build tools, no frameworks. You edit the file, refresh the browser, and see the change immediately.

The mock server (`mock_server.py`) handles all the backend responses with realistic fake data so you can experience the full app flow without needing anything from the backend team.

---

## One-time setup

### 1. Install Git

Check if you already have it:
```
git --version
```
If you see a version number, skip ahead. If not, download it from https://git-scm.com/download/mac and install.

### 2. Install Python

Check if you already have it:
```
python3 --version
```
You need version 3.9 or higher. If you don't have it, download from https://www.python.org/downloads/ — get the latest version and install it.

### 3. Clone the project

Open Terminal (press `⌘ Space`, type "Terminal", press Enter) and run:
```bash
git clone https://github.com/inkku/conversation-trainer.git
cd conversation-trainer
```

### 4. Install the minimal dependencies
```bash
pip3 install fastapi uvicorn jinja2 python-multipart
```

This takes about a minute and only needs to happen once.

---

## Every time you work on it

### Start the mock server
```bash
cd conversation-trainer
python3 mock_server.py
```

You should see:
```
🎨 Mock server running — no API key or Whisper needed
   Open http://localhost:8001
```

Open http://localhost:8001 in your browser. The full app is running with realistic fake data.

### Edit the UI

Open `templates/index.html` in your editor of choice. Save the file, then refresh the browser — changes appear immediately. The mock server watches for file changes and reloads automatically.

### Stop the server

Press `Control + C` in the Terminal window.

---

## Saving and sharing your work

When you're happy with a change, save it to GitHub so others can see it:

```bash
git add templates/index.html
git commit -m "brief description of what you changed"
git push
```

To get the latest changes from someone else:
```bash
git pull
```

---

## Working with Figma

The recommended flow:
1. Design the component or layout in Figma
2. Find the corresponding section in `index.html` (use `⌘F` to search)
3. Update the HTML and CSS directly — the design language is all inline styles and CSS variables defined near the top of the file

Key CSS variables (find them by searching `--bg` in the file):
- `--bg` — page background
- `--surface-alt` — card/panel backgrounds
- `--text`, `--muted` — text colours
- `--accent` — primary highlight colour (purple)
- `--border` — border colour

---

## Working with Stitch

[Stitch](https://stitch.withgoogle.com) lets you describe a UI or paste a Figma frame and generates HTML/CSS. The output fits naturally into this project since the app is already vanilla HTML.

Suggested workflow:
1. In Stitch, describe the component you want or paste a Figma frame
2. Copy the generated HTML/CSS
3. Paste it into the relevant section of `templates/index.html`
4. Adjust colour variables to match the app's design tokens (listed above)
5. Refresh the browser to see it live

> **Tip:** When prompting Stitch, mention "dark theme", "no frameworks", and "inline styles" to get output that's closest to the existing code style.

---

## What's safe to change

| ✅ Go ahead | ⚠️ Check with the dev first |
|---|---|
| All visual styling (colours, spacing, typography, layout) | Changing element IDs (`id="mic-btn"`, `id="thread"`, etc.) |
| Adding new UI sections or panels | Removing or renaming form fields in the setup screen |
| Updating icons and copy | Changing `onclick` handlers or JavaScript logic |
| Setup screen layout and topic tile design | The `<script>` block at the bottom |
| Feedback panel layout | API endpoint calls inside `callAPI()` |

The safest rule: **change styles and structure freely, leave the JavaScript alone**.

---

## Getting help

If something breaks or you're not sure where to find something, ping the dev team with:
- What you were trying to change
- What you see in the browser (a screenshot helps)
- The line number in `index.html` if you can find it (`⌘G` jumps to a line number)
