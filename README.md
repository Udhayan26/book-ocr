# எழுத்து · Book OCR

Self-hosted, FineReader-style OCR for whole books: Tamil, English and mixed pages, with layout recognition (headings, paragraphs, tables, pictures, captions, headers/footers) and conversion to Word, Excel, HTML, EPUB and searchable PDF.
100% open source (Tesseract 5 LSTM + OpenCV + FastAPI). Runs on your own machine: **no API fees, no page limits, nothing leaves your computer.**

## What it does

**Recognition**
- **Layout analysis** per page: Heading 1/2/3, Text, Caption, Header, Footer, Table, Picture — with reading order, alignment (left/centre/right/justify), approximate font size and bold.
- **Tables**: ruled tables (grid lines) and borderless "booktabs" tables (rules only above/below). Table regions are re-read separately with the lines erased, because Tesseract alone often drops text inside grids.
- **Pictures** are cut out of the colour page and placed back into the exports at the right position; the paragraph hugging a picture becomes its caption.
- **Auto-detect language**: probes each installed script model on the first page, caches it for the book, and re-checks any page that reads poorly. Every block is tagged with its language (ta, en, ta+en…).
- **Auto-rotate & deskew**: sideways / upside-down scans are turned upright (Tesseract OSD), tilted pages straightened.
- **Tamil-aware clean-up**: stray zero-width joiners after ், vowel signs in visual order (ெக → கெ), split two-part vowels (ொ ோ ௌ), dotted circles.

**Review dashboard**
- Scan with colour-coded areas (like FineReader) next to a block editor. Click an area to jump to its block and vice versa.
- **Draw an area** (Text / Heading / Table / Picture) to read any region again the way you want; areas it covers are replaced. ⟳ re-reads one block.
- Change a block's type, reorder, delete; edit table cells directly, add/remove rows and columns.
- **Preview** tab shows the formatted page; **Text** tab gives plain text to copy.
- "Weak words" overlay + list of low-confidence words; "Next weak page" sorts pages worst-first.
- Symbols palette: Tamil digits & signs (௦–௯, ௰ ௱ ௲, ௳–௺, ௐ) and the full **Tamil Supplement** block (fractions, measures, clerical marks).
- Replacement rules (plain or regex) applied after OCR, re-applicable to a book without re-OCR.

**Export / convert** (whole book or a page range like `1-5,8`)

| Format | What you get |
|---|---|
| Word (.docx) | Headings as Word headings, real tables, pictures, captions, alignment; Tamil font (Nirmala UI) set for complex script |
| Excel (.xlsx) | Every table on its own sheet, numbers stored as numbers; all other text on a "Content" sheet |
| Searchable PDF | Original look, invisible text layer you can search/copy |
| Web page (.html) | Single file, pictures embedded, `lang` tags, Noto Tamil fonts |
| E-book (.epub) | EPUB 3 for phones, Google Play Books, Kindle apps |
| Text / Markdown / JSON | Plain UTF-8; Markdown zip with images; JSON with every block, box, style and confidence |

Options: include pictures, include headers/footers/page numbers, keep original line breaks (for poetry/verse — otherwise paragraphs are re-flowed and hyphenated words re-joined), page breaks.

## Quick web OCR — https://ocr.udhayam.in (`docs/`)

**Protection:** all code (Tesseract.js + WASM core, PDF.js, Cropper.js, docx) is served from this site — no third-party scripts; only language data comes from jsDelivr. A Content-Security-Policy blocks other script sources, `eval`, plugins and forms; results are posted only to the page that embeds the tool; the page moves itself to HTTPS as soon as the certificate works and warns while it doesn't; "Clear saved work" wipes everything stored in the browser. Licenses: `docs/vendor/LICENSES.txt`.

**Phones:** single-column layout, swipeable page strip, a fixed Convert / Copy / Text bar at the bottom, settings tucked under "More settings", bottom-sheet language picker, large touch targets.

A page that runs entirely in the visitor's browser (Tesseract.js with the same "best" Tamil models), hosted free on GitHub Pages. No server, no limits, nothing uploaded.

**Single image:** paste a screenshot (Ctrl+V), drop, upload, or use the phone camera → crop → Convert → copy / .txt / Word.

**Whole books, page by page:** open a multi-page PDF or select many page photos at once.
- Page strip with thumbnails, status and confidence per page (amber = check it); "+ Add pages" to append more photos.
- Crop once and tick **Same crop for every page** to skip running headers and page numbers; rotate any sideways page.
- **Read all pages** (or a range like `1-20, 25`) with 1–3 parallel readers, live progress and time left. You can keep reviewing and editing pages while it runs; Stop/Start resumes.
- **This page / Whole book** tabs; download the book as Word (.docx), web page, .txt, Markdown or JSON, with or without page numbers.
- Work is saved in the browser (IndexedDB). Reopen the same file later to continue where you stopped.

**Tables and pictures:** switch the page to **Areas** and draw boxes typed Text / Heading / Table / Picture / Skip (move, resize, reorder, change type), or press **✦ Detect automatically**. With "Find tables & pictures automatically" on, every page without drawn areas is split into headings, paragraphs, ruled and borderless tables, and pictures (captions kept as text, page numbers skipped). Word (.docx) and web-page downloads keep real tables and the pictures.

**Tables — rows and columns you control:** a table is read with its ruling lines erased; columns come from vertical lines or white gaps, rows from horizontal lines or text lines. After reading, the column/row lines are shown on the scan (Areas mode, select the table): drag them, **+ Column line / + Row line** (placed on the nearest white gap), double-click or double-tap a line to remove it (removing a row line merges two rows, e.g. wrapped cells), type a **number of columns** (picks the widest white gaps), **Auto rows / Auto columns**, then **↻ Re-read table** — only that table is read again. In **Preview** every cell and paragraph is editable, with + / − Row and Column and "Merge header rows"; edits in the Text tab are parsed back into the same structure, so Word, web page, CSV and text downloads all get them. **Tables for Excel (.csv)** downloads every table.

**Languages:** a multi-select dropdown (search, checkboxes, priority numbers; a bottom sheet on phones). The default **✦ Auto-detect** samples up to 12 text lines, lets each script model compete line by line (Tamil, Devanagari, Malayalam, Telugu, Kannada, Bengali, Gujarati, Gurmukhi, Odia, Sinhala, Arabic script, Latin) and keeps every script that wins enough lines — so a Tamil + Sanskrit page is detected as both — plus English for inline English words. Scripts seen before are tried first (typically 4–8 s). Devanagari can be read as Hindi, Sanskrit or Marathi and Arabic script as Urdu or Arabic; "↻ Detect again" re-runs it. Or pick any combination of 17 languages yourself.

**Layout:** Auto, Single column, **Two columns**, **Three columns**, **Multi-column (find columns)**, One block, Single line, Scattered text. Column modes find the white gutters, keep full-width titles/pictures as their own bands, and read each column top to bottom (right-to-left for Urdu/Arabic). Image clean-up for old paper; keep line breaks for verse.

### Add it to your website

```html
<!-- 1. inline tool, sizes itself (works in a WordPress "Custom HTML" block) -->
<script src="https://ocr.udhayam.in/embed.js" data-lang="tam+eng"></script>

<!-- 2. a button that opens the tool in a pop-up (add data-floating="true" for a corner button) -->
<script src="https://ocr.udhayam.in/embed.js" data-mode="button" data-label="தமிழ் OCR"></script>

<!-- 3. plain iframe -->
<iframe src="https://ocr.udhayam.in/?embed=1&lang=tam+eng" style="width:100%;height:820px;border:0"
  allow="clipboard-write; camera" title="Tamil OCR"></iframe>
```

For developers: `EzhuthuOCR.open({lang})`, `EzhuthuOCR.close()`, and `EzhuthuOCR.onText = (text, info) => …` (also fired as a `document` event `ezhuthu-ocr`).

## Run the full Book OCR app

### Docker (easiest, any OS)
```bash
docker compose up --build
# open http://localhost:8000
```
Add languages in `docker-compose.yml` → `LANGS: "tam eng hin mal tel kan san"` and rebuild. Auto-detect then chooses between them.

### Windows (no Docker)
1. Install Python 3.10+ and Tesseract from the UB Mannheim build (github.com/UB-Mannheim/tesseract/wiki). It already includes the orientation model (`osd`) used for auto-rotate.
2. In an **Administrator** prompt inside this folder, get the high-accuracy models:
   `python download_models.py "C:\Program Files\Tesseract-OCR\tessdata" tam eng`
3. Double-click `run.bat`. The dashboard opens at http://localhost:8000.

### Linux / macOS
```bash
sudo apt install tesseract-ocr python3-venv     # or: brew install tesseract
./run.sh
```

## Settings (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `TESSDATA_PREFIX` | Tesseract default | Folder with `*.traineddata` (keep Tesseract's `osd.traineddata`, `configs/` and `pdf.ttf` there) |
| `TESSERACT_CMD` | `tesseract` on PATH | Full path to the binary (Windows) |
| `DATA_DIR` | `./data` | Books, page images, OCR results, rules |
| `OCR_WORKERS` | CPU cores ÷ 2 | Pages processed in parallel |
| `API_KEY` | empty (off) | If set, every API call needs `X-API-Key` |

## API

Interactive docs at `http://localhost:8000/docs`.

```bash
# scan -> Word in one call (also: xlsx, html, epub, pdf, txt, md, json)
curl -X POST http://localhost:8000/api/convert -F file=@scan.pdf -F format=docx -F langs=auto -o scan.docx

# image/PDF -> JSON with text, language, and layout blocks
curl -X POST http://localhost:8000/api/ocr -F file=@page.jpg -F langs=auto

# books: queue, review in the dashboard, export a range
curl -X POST http://localhost:8000/api/books -F files=@book.pdf -F langs=auto
curl -OJ "http://localhost:8000/api/books/<id>/export?format=xlsx&pages=10-20"
```
Other endpoints: `GET /api/books`, `GET|PUT /api/books/{id}/pages/{n}` (blocks), `POST …/pages/{n}/region` (draw & read an area), `POST …/pages/{n}/reocr`, `POST /api/books/{id}/reapply-rules`, `GET|PUT /api/rules`, `GET /api/symbols`, `GET /api/info`.

## Accuracy tips

- Scan at **300 DPI** (400 for small print); flat, evenly lit pages matter more than resolution.
- Auto-detect works well for one-script books. For a book that is mostly Tamil with English terms, auto gives `tam+eng`; you can also pick languages yourself (order = priority).
- Old or yellowed paper → **Image clean-up: Old / yellowed**. A table that wasn't found → draw it with the **Table** tool.

## Honest limits

- Layout recognition is rule-based (OpenCV), tuned for typical printed books. Complex magazine layouts, tables without any lines or clear column gaps, and merged cells are where FineReader or cloud services still do better — draw/fix those areas in the dashboard.
- Font size and bold are estimates from the scan; italics and font families are not recognised.
- No free OCR model reads **Tamil Supplement** symbols (old fractions, measures) directly — use the palette or a replacement rule.
- Searchable PDF uses the engine's text layer; your edits go into Word/HTML/EPUB/Excel/Text exports.
- If you need stronger layout AI later, `backend/layout.py` is the place to plug in PaddleOCR PP-StructureV3 (open source; has a Tamil recogniser) or Docling.

## Layout

```
backend/app.py          REST API, job queue, region tool, export endpoints
backend/layout.py       layout analysis: tables, pictures, headings, captions, reading order, language
backend/ocr_engine.py   rotate/deskew/clean, language auto-detect, Tesseract
backend/exporters.py    Word, Excel, HTML, EPUB, Markdown, text
backend/tamil_text.py   Tamil clean-up, replacement rules, symbol catalogue
frontend/index.html     the dashboard (single file, no build step)
docs/                   quick browser-only OCR page for GitHub Pages (ocr.udhayam.in)
samples/                test PDFs (Tamil+English text; layout with tables, picture, sideways page)
```
