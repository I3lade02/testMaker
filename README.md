# GIFT Formatter GUI (PySide6)

A small desktop tool for teachers to quickly convert multiple-choice questions into **Moodle GIFT** format.

It’s designed for a fast workflow when you already have a finished test and only need help with **formatting**.

---

## Features

- **Batch conversion**: paste multiple questions at once (separated by blank lines)
- **Supports answer labels**
  - Letters: `a) ...`, `b) ...`
  - Numbers: `1) ...`, `2) ...`
- **Correct answer marking**
  - Mark correct with `)*` (e.g. `a)* ...` or `1)* ...`)
  - Or use a **default correct option** if none is marked
- **Question cleanup**
  - Removes trailing `:` from the question line during conversion
  - Normalizes question ending to ` ?` (e.g. `Question:` → `Question ?`)
- **Tolerant mode (auto-fixes)**
  - Automatically fixes common formatting issues (e.g. `A.` / `1.` / extra spaces / `a ) *`)
  - Fixes are applied **internally** (your input text is not rewritten)
- **Student view (Preview)**
  - Preview questions as a student (radio buttons)
  - Optional “Show correct” toggle
- **Multilingual UI**
  - Default **Czech**
  - Switch to **English**
- **Input highlighting**
  - Questions are highlighted (bold)
  - Marked correct answers are highlighted
  - Suspicious/invalid answer lines are highlighted
- **Export**
  - Save output to a `.gift` file
- **Persistent settings**
  - Remembers language, tolerant mode, default correct option, window size, splitter position, etc.

---

## Example

### Input
```text
Jak mohou kočky přispět k šíření toxoplazmózy u lidí:
a)* Vylučují oocysty Toxoplasma gondii ve stolici...
b) Přenášejí toxoplazmózu pouze přímým poškrábáním nebo kousnutím
c) Infikují člověka jen pokud jsou klinicky nemocné
d) Kočky nemají žádný význam pro přenos toxoplazmózy
```

### Output (GIFT)
```text
Jak mohou kočky přispět k šíření toxoplazmózy u lidí ? {
=Vylučují oocysty Toxoplasma gondii ve stolici...
~Přenášejí toxoplazmózu pouze přímým poškrábáním nebo kousnutím
~Infikují člověka jen pokud jsou klinicky nemocné
~Kočky nemají žádný význam pro přenos toxoplazmózy
}
```

---

## Installation

### Requirements
- Python 3.10+ recommended
- PySide6

Install dependencies:

```bash
pip install -r requirements.txt
```

Minimal `requirements.txt`:

```text
PySide6>=6.5
```

---

## Run

```bash
python main.py
```

### App icon
Place your icon file next to the script:

- `icon.png` (recommended)

Example project structure:

```text
.
├─ gift_formatter_gui.py
├─ icon.png
├─ requirements.txt
└─ README.md
```

---

## Keyboard Shortcuts

- **Convert**: `Ctrl + Enter`
- **Save .gift**: `Ctrl + S`
- **Stats**: `Ctrl + I`
- **Preview (Student view)**: `Ctrl + P`
- **Clear**: `Ctrl + L`

(Shortcuts can be adjusted in code.)

---

## Tips

- Separate questions using **one or more blank lines**
- If you don’t want to manually mark correct answers, set “Default correct” (e.g. `a`) and keep “Use default…” enabled
- Tolerant mode is great when pasting from Word or inconsistent sources

---

## Known probles

- Manual inserting text is throwing errors while auto-convert is ON (fixed)

---

## License

Unlicensed
