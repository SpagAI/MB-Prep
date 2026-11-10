# Practical Projector

A spotting-exam simulator for medical school practicals (Histopathology, Chemical Pathology, MMP, Haematology).
A slide, pot or photomicrograph is shown with questions under it, a countdown runs, and you can't go back.
It uses **your own picture bank**, works **fully offline**, and runs on a phone or on a laptop plugged into a projector.

Just double-click `index.html`. You don't need a server or internet.

---

## Quick start (try it now)

1. Double-click **`index.html`**. It opens in your browser with a small sample bank (placeholder pictures).
2. Pick courses → categories → a mode → a timer → the number of slides → **Start**.

## The three modes

| Mode | What you get |
|---|---|
| **Study** | Label and answers visible. Browse freely, filter by category. |
| **Easy Money** | No labels. 4 options per question, instant ✓/✗, hints, Previous/Next, pause. |
| **Distinction** | Just the image, the questions and a countdown. No options, hints, pause or going back. Write your answers on paper, like the real exam. At the end you get the full **answer key** (numbered by slide) to check against, and you can mark yourself ✓ / ½ / ✗ for a score. |

**Writing answers in Distinction:** by default there's nowhere to type. You write on paper as "Slide 1, Slide 2…", just like the hall.
Prefer typing? Tick **"Type answers on screen"** on the home screen (or press the ✎ button during the exam). An answer box then appears under each question, and what you typed is shown next to the correct answer at the end.
The answer key has a **Show pictures** switch. Turn it off for a compact list that's quick to check against your notes.

**Number of slides:**
- **Same total**: e.g. 20, shared evenly across the practicals you picked (all four → 5 each).
- **Choose per practical**: e.g. Histopathology 10, Chem Path 5, MMP 8, Haematology 7. Set a practical to 0 to leave it out.

**Order** (when more than one practical is picked):
- **🔀 Mix practicals together**: one round that cuts across all of them, and the same practical never shows twice in a row (when that's possible).
- **One practical at a time**: Histopathology first, then Chem Path, MMP, Haematology, each shuffled inside its block. A banner shows "Practical 2 of 4: Chemical Pathology" when the next one starts.

Timer: Off (use Next), or anything from 5 s to 30 min. It turns amber at 25% left and red at 10 s, can beep, and moves on by itself at 0.
Distinction mode always has a timer (1 min by default).

**Keyboard (laptop / projector):** `→` next · `←` previous (Easy/Study) · `1`–`4` pick option · `H` hint · `F` fullscreen · `Space` pause (not in Distinction).
A presentation clicker also works (it sends Page Down / Page Up).
**Zoom:** click/tap the picture, pinch, scroll the mouse wheel, or use the ＋ / － buttons.

Your settings and past scores are saved in the browser on that device.

---

## Step 1: Turn your PDFs, PowerPoints and Word files into a picture bank

Put your study materials in `/source`, one folder per course:

```
source/
  Histopathology/        <- PDFs, PowerPoints (.pptx), Word (.docx), images, zips
  Chemical Pathology/
  MMP/
  Haematology/
```

Sub-folders are fine (e.g. `source/Histopathology/Liver/`); a folder name is used as the category when it matches one.

**One-time setup:** install [Python 3](https://www.python.org/downloads/) and [Node.js](https://nodejs.org/), then in this folder run:

```
pip install -r requirements.txt
```

(On Windows use `py -m pip install -r requirements.txt`.)

**Run the extractor:**

```
python3 extract.py
```

(On Windows: `py extract.py`.)

It:
- pulls every picture out of PDFs, PowerPoints, Word files and zips, and copies loose photos (jpg/png/webp/heic → jpg).
  Old `.ppt` / `.doc` files are converted automatically if LibreOffice is installed; otherwise "Save As" .pptx/.docx first.
- takes the **label** from the slide title, caption, heading or nearest text (or the answer in the slide notes). If it finds nothing, the picture becomes `unlabelled-001.jpg`.
- **removes duplicates** even when a copy was resized, recompressed (WhatsApp), slightly cropped or turned grey. It keeps the sharpest copy and the best label, and merges the questions from every copy.
- **skips junk:** school logos/crests repeated on many slides, icons, tiny pictures, blank pictures.
- **sorts** each picture into `bank/<Course>/<Category>/` (e.g. Liver, Kidney, Bacteria, Parasites…). If unsure: `_Unsorted`.
- guesses the **type** (slide / pot / photomicrograph) and saves any **questions** it found next to the picture.
- runs `node build-bank.js` for you at the end.

**Check its work:** open **`extract-report.html`**. You see every kept picture with its label, category, type and source files, plus everything it rejected (duplicates and junk) so you can spot mistakes.

**Fix mistakes** in either of these ways:
- On the report page: change a label / category / type, or tick *delete*, then click **Save corrections.csv** and save it in this folder.
- Or open `corrections.csv` in Excel / Google Sheets and edit it.

Then run:

```
python3 extract.py --apply
```

That moves and renames the files (deleted ones go to `extract-trash/`) and rebuilds the bank.

Adding more files later? Drop them into `/source` and run `python3 extract.py` again. It only **adds** new pictures, and your renames, moves and question files are never overwritten.
(`python3 extract.py --fresh` throws away everything it extracted before and starts again.)

> You can also skip Step 1 completely and just put pictures into `/bank` yourself (see below).

---

## The picture bank (`/bank`)

The folder names are the categories, and the file name is the answer:

```
bank/
  Histopathology/
    Liver/
      cirrhosis.jpg
      cirrhosis.json            <- optional questions, same name as the picture
      hepatocellular-carcinoma.jpg
    Kidney/
  Chemical Pathology/
  MMP/
    Viruses/
    Bacteria/
    Parasites/
  Haematology/
```

- Level 1 = course, level 2 = category. Deeper folders become sub-categories.
- `hepatocellular-carcinoma.jpg` → answer **"Hepatocellular carcinoma"**. Use hyphens or underscores between words.
  Two pictures of the same thing? Name them `cirrhosis.jpg` and `cirrhosis__2.jpg`. The `__2` is ignored.
- **To fix a label, just rename the file.**
- Pictures named `unlabelled-…` only show in Study mode until you rename them.

**After adding, renaming or moving pictures, run:**

```
node build-bank.js
```

This rewrites `bank.js`, the file the app reads. Then reload `index.html`.

### Adding your own questions

Without a question file, each picture gets *"Identify this slide / pot / photomicrograph / specimen"*.
For more, put a JSON file with the **same name** next to the picture:

```json
{
  "type": "slide",
  "label": "Hepatocellular carcinoma",
  "questions": [
    { "q": "Identify the specimen", "a": "Hepatocellular carcinoma", "hint": "Malignant tumour of the liver's main parenchymal cell" },
    { "q": "Give two histological features", "a": "Trabecular pattern of atypical hepatocytes; bile production", "hint": "Think architecture + what liver cells secrete" },
    { "q": "Name one risk factor", "a": "Chronic hepatitis B infection", "hint": "Very common in Nigeria" }
  ]
}
```

- `type`: `slide`, `pot` or `photomicrograph` (optional).
- `label`: optional; overrides the file name.
- `hint`: optional; shown when you press Hint in Easy Money.
- In **Easy Money**, "Identify…" questions get 4 options automatically: the right answer plus 3 others from the **same category** first, then the same course, then any course.
  Any question can supply its own options (the answer must be one of them):
  `{ "q": "What does fluoride do?", "a": "Inhibits glycolysis", "options": ["Inhibits glycolysis", "Anticoagulant", "Preserves bilirubin", "Lyses red cells"] }`
- Other questions without options get a *Show answer* button, and you mark yourself ✓ or ✗.

**Fast way to add questions:** run

```
node make-templates.js
```

It creates a blank question file for every picture that doesn't have one, and adds empty question slots to files that have none yet.
Fill in what you like (blank questions are ignored), then run `node build-bank.js`.

---

## Using it on your phone

The app is just files, so any of these work:

1. **Copy the folder to your phone** (USB, Google Drive download, zip → extract) and open `index.html` with your browser.
   On Android, a file-manager app that can "Open with Chrome" works best.
2. **Host it free, so it's a link you can open anywhere:**
   - **Netlify Drop:** go to <https://app.netlify.com/drop> and drag the whole folder onto the page. You get a link.
   - **GitHub Pages:** push this folder to a GitHub repository → Settings → Pages → *Deploy from branch* → `main` / root.
   Re-upload after you add pictures (and run `node build-bank.js` first).
   Your `/source` files are **not** uploaded to GitHub (they're in `.gitignore`).

> iPhone Safari can't do true fullscreen for web pages. Use the phone sideways, or "Add to Home Screen".

## On a projector

Plug in the laptop, open `index.html`, press **F** (or ⛶) for fullscreen. The exam screen is dark like a practical hall, and the text and timer are large.

---

## Files

| File | What it is |
|---|---|
| `index.html`, `styles.css`, `app.js` | The app |
| `bank/` | Your pictures (sample placeholders included; delete them when you add your own) |
| `bank.js` | Generated by `node build-bank.js`. Don't edit it. |
| `build-bank.js` | Scans `/bank` → writes `bank.js` |
| `make-templates.js` | Creates blank question files |
| `extract.py` | Step 1: pulls pictures out of `/source` |
| `extract-report.html`, `corrections.csv`, `extract-manifest.json` | Made by `extract.py` (report, your fixes, and its record of what it extracted) |

**Troubleshooting**
- *"No picture bank found"*: run `node build-bank.js`, then reload.
- *A picture shows "could not be loaded"*: you moved or renamed files. Run `node build-bank.js` again.
- *PDFs skipped*: `pip install pymupdf`. *HEIC skipped*: `pip install pillow-heif`.
