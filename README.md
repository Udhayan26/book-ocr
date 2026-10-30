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

## Quick web OCR (`docs/`) — paste, crop, convert

A single-page tool that runs entirely in the visitor's browser (Tesseract.js, same "best" Tamil models), so it can be hosted for free on GitHub Pages and has no server or limits:

- **Paste** a screenshot (Ctrl+V), **drop** a file, **upload**, or use the phone **camera**; PDFs open page by page.
- **Crop** the area you want, rotate sideways pages, zoom.
- Tamil + English (default), Tamil, English, Sanskrit, Hindi, Malayalam, Telugu, Kannada; layout and clean-up options.
- Tamil clean-up, low-confidence word list, Tamil/Tamil Supplement symbol palette; copy, .txt or Word download.
- **Embed** on any site with an iframe (`?embed=1`, optional `&lang=tam`). The frame reports its height and sends each result to the parent page as `{type: "ezhuthu-ocr", text}`.

Live at **https://ocr.udhayam.in** (GitHub Pages from `main` → `/docs`; DNS: CNAME `ocr` → `udhayan26.github.io`). To run it locally: `cd docs && python -m http.server` and open http://localhost:8000.

### Embed snippet

```html
<iframe id="ezhuthu-ocr" src="https://ocr.udhayam.in/?embed=1&lang=tam+eng"
  style="width:100%;height:760px;border:0" allow="clipboard-write; camera" title="Tamil OCR"></iframe>
<script>
addEventListener("message", e => {
  if (e.data?.type === "ezhuthu-height")
    document.getElementById("ezhuthu-ocr").style.height = e.data.height + "px";
  // if (e.data?.type === "ezhuthu-ocr") console.log(e.data.text);
});
</script>
```

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
