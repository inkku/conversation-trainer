# Designer Setup Guide

This guide gets you from zero to a live, interactive version of the app running on your machine — no API keys, no backend knowledge needed.

---

## What you're working with

There are two files you'll work with:

| File | What it is |
|---|---|
| `static/style.css` | **All the visual styling.** This is yours — colours, spacing, typography, layout, animations. |
| `templates/index.html` | HTML structure and JavaScript logic. Touch the HTML structure freely; leave the `<script>` block at the bottom alone. |

No build tools, no frameworks. Edit a file, refresh the browser, see the change.

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

### Edit the styles

Open `static/style.css` in your editor. Save, refresh the browser — done. This file contains every colour, spacing value, font size, and animation in the app. The design tokens at the top of the file (the `:root { }` block) are the fastest place to make sweeping changes.

You can also edit the HTML structure in `templates/index.html`. The mock server watches for file changes and reloads automatically.

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
2. Update `static/style.css` — all colours, spacing, and typography live there
3. For structural changes, find the relevant section in `templates/index.html` (use `⌘F` to search)

The design tokens at the top of `style.css` are the fastest lever — changing one variable updates everything that uses it:

```css
:root {
  --bg: #0d0d0f;          /* page background */
  --surface: #18181b;     /* header, panels */
  --surface-alt: #27272a; /* cards, inputs */
  --primary: #6366f1;     /* brand colour — buttons, links, highlights */
  --text: #e4e4e7;        /* body text */
  --muted: #71717a;       /* secondary text, labels */
  --border: #3f3f46;      /* all borders */
  --radius: 12px;         /* corner rounding */
}
```

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
| Everything in `static/style.css` | Changing element IDs (`id="mic-btn"`, `id="thread"`, etc.) |
| HTML structure and layout in `index.html` | Removing or renaming form fields in the setup screen |
| Icons, copy, and labels | Changing `onclick` handlers or JavaScript logic |
| Adding new HTML elements | The `<script>` block at the bottom of `index.html` |

The safest rule: **`style.css` is entirely yours. In `index.html`, change structure freely — leave the JavaScript alone**.

---

## Getting help

If something breaks or you're not sure where to find something, ping the dev team with:
- What you were trying to change
- What you see in the browser (a screenshot helps)
- The line number in `index.html` if you can find it (`⌘G` jumps to a line number)
