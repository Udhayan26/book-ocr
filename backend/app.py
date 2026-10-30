"""Book OCR server — FastAPI + Tesseract. Self-hosted, open source, no page limits.

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pymupdf as fitz
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image

import exporters as ex
import layout
import ocr_engine as eng
import tamil_text as tt

DATA = Path(os.environ.get("DATA_DIR", Path(__file__).parent.parent / "data")).resolve()
BOOKS = DATA / "books"
RULES_FILE = DATA / "rules.json"
FRONTEND = Path(__file__).parent.parent / "frontend"
WORKERS = int(os.environ.get("OCR_WORKERS", max(1, (os.cpu_count() or 2) // 2)))
API_KEY = os.environ.get("API_KEY", "")  # optional: protect the API when exposed on a network
BOOKS.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Book OCR", version="2.0",
              description="Self-hosted Tamil/English/multilingual OCR with layout analysis and conversion.")
pool = ThreadPoolExecutor(max_workers=WORKERS)
lock = threading.RLock()

DEFAULT_RULES = [
    {"find": "ஶ்ரீ", "replace": "ஸ்ரீ", "regex": False, "enabled": False,
     "note": "Example: unify the two spellings of Sri (ஶ்ரீ -> ஸ்ரீ). Add your own misread -> symbol mappings."},
]
IMG_EXT = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
BLOCK_TYPES = {"heading1", "heading2", "heading3", "paragraph", "caption", "header", "footer",
               "table", "image", "ignore"}


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def require_key(x_api_key: str = Header(default=""), key: str = ""):
    if API_KEY and API_KEY not in (x_api_key, key):
        raise HTTPException(401, "Missing or wrong X-API-Key header")


def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception:
        return default


def write_json(p: Path, obj) -> None:
    tmp = p.with_suffix(f".{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False), "utf-8")
    tmp.replace(p)


def book_dir(book_id: str) -> Path:
    if not book_id.isalnum():
        raise HTTPException(404, "Book not found")
    d = BOOKS / book_id
    if not (d / "book.json").exists():
        raise HTTPException(404, "Book not found")
    return d


def get_book(d: Path) -> dict:
    return read_json(d / "book.json")


def update_book(d: Path, **kw) -> dict:
    with lock:
        b = read_json(d / "book.json", {})
        b.update(kw)
        write_json(d / "book.json", b)
        return b


def rules() -> list[dict]:
    r = read_json(RULES_FILE, None)
    return DEFAULT_RULES if r is None else r


def pn(n: int) -> str:
    return f"{n:04d}"


def page_rec(d: Path, n: int) -> dict | None:
    return read_json(d / "ocr" / f"{pn(n)}.json")


def page_text(rec: dict | None) -> str:
    if not rec:
        return ""
    return ex.to_txt("", [rec], None, ex.opts(page_breaks=False, images=False)).decode("utf-8").strip()


def parse_range(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    out = []
    for part in spec.replace(" ", "").split(","):
        if "-" in part:
            a, b = part.split("-", 1)
            out += range(int(a or 1), int(b or total) + 1)
        elif part:
            out.append(int(part))
    return [n for n in dict.fromkeys(out) if 1 <= n <= total]


def clean(text: str) -> str:
    return tt.apply_rules(tt.clean_tamil(text), rules())


# ---------------------------------------------------------------------------
# pipeline
# ---------------------------------------------------------------------------
def render_inputs(d: Path, files: list[Path], dpi: int) -> int:
    (d / "pages").mkdir(exist_ok=True)
    n = 0
    for f in files:
        if f.suffix.lower() == ".pdf":
            with fitz.open(f) as pdf:
                for page in pdf:
                    n += 1
                    page.get_pixmap(dpi=dpi).save(d / "pages" / f"{pn(n)}.png")
        else:
            im = Image.open(f)
            for i in range(getattr(im, "n_frames", 1)):  # multi-page TIFF
                im.seek(i)
                n += 1
                im.convert("RGB").save(d / "pages" / f"{pn(n)}.png", dpi=im.info.get("dpi", (dpi, dpi)))
    return n


def _source_dpi(path: Path, default: int) -> int:
    try:
        v = Image.open(path).info.get("dpi", (default,))[0]
        return int(v) if 70 <= v <= 1200 else default
    except Exception:
        return default


def _ocr_fn(langs):
    def fn(crop_array, offset):
        words = eng.run_ocr(Image.fromarray(crop_array), langs, 6, offset)["words"]
        for w in words:
            w["text"] = tt.clean_tamil(w["text"])
        return words
    return fn


def _finish_block(b: dict, idx: int, n: int, view: Image.Image, d: Path):
    b["id"] = f"b{idx}"
    b["edited"] = False
    if b["type"] == "image":
        x, y, w, h = b["bbox"]
        name = f"{pn(n)}_{b['id']}_{uuid.uuid4().hex[:4]}.jpg"
        (d / "figs").mkdir(exist_ok=True)
        view.crop((x, y, x + w, y + h)).save(d / "figs" / name, quality=90)
        b["image"] = name
    elif b["type"] == "table":
        b["raw_rows"] = [list(r) for r in b["rows"]]
        b["rows"] = [[clean(c) for c in r] for r in b["rows"]]
    else:
        b["raw"] = b["text"]
        b["text"] = clean(b["text"])
    return b


def process_page(d: Path, n: int, override: dict | None = None) -> dict:
    """Normalise -> detect languages -> OCR -> layout -> save page record."""
    b = get_book(d)
    s = {**b["settings"], **(override or {})}
    for sub in ("view", "proc", "ocr"):
        (d / sub).mkdir(exist_ok=True)
    t0 = time.time()
    src = d / "pages" / f"{pn(n)}.png"
    dpi = _source_dpi(src, b.get("dpi", 300))
    view, proc, gray, meta = eng.normalize_page(Image.open(src), s["preprocess"], s["auto_rotate"])
    view.save(d / "view" / f"{pn(n)}.jpg", quality=88)
    proc.save(d / "proc" / f"{pn(n)}.png")

    auto = s["langs"] == ["auto"]
    if auto:
        langs = None if (override or {}).get("redetect") else b.get("auto_langs")
        if not langs:
            langs = eng.detect_languages(proc)
            if not b.get("auto_langs"):
                update_book(d, auto_langs=langs)
    else:
        langs = s["langs"]
    r = eng.run_ocr(proc, langs, s["psm"])
    if auto and r["mean_conf"] < 60 and r["words"]:  # this page may be in another language
        page_langs = eng.detect_languages(proc)
        if page_langs != langs:
            r2 = eng.run_ocr(proc, page_langs, s["psm"])
            if r2["mean_conf"] > r["mean_conf"] + 5:
                r, langs = r2, page_langs
    for w in r["words"]:
        w["text"] = tt.clean_tamil(w["text"])

    blocks = layout.analyze(r["words"], gray, dpi, meta["scale"], _ocr_fn(langs),
                            s.get("detect_tables", True), s.get("detect_images", True))
    blocks = [_finish_block(bl, i + 1, n, view, d) for i, bl in enumerate(blocks)]
    # remove old figure crops of this page
    old = page_rec(d, n)
    if old:
        for ob in old.get("blocks", []):
            if ob.get("image"):
                (d / "figs" / ob["image"]).unlink(missing_ok=True)

    all_text = " ".join(bl.get("text", "") for bl in blocks)
    rec = {
        "page": n, "size": list(view.size), "dpi": dpi, **meta,
        "langs": langs, "auto_lang": auto, "psm": s["psm"], "preprocess": s["preprocess"],
        "words": [{"text": w["text"], "conf": w["conf"], "box": w["box"]} for w in r["words"]],
        "blocks": blocks, "next_id": len(blocks) + 1,
        "mean_conf": r["mean_conf"], "mix": tt.script_mix(all_text),
        "seconds": round(time.time() - t0, 2), "reviewed": False, "updated": time.time(),
    }
    write_json(d / "ocr" / f"{pn(n)}.json", rec)
    return rec


def _ocr_job(d: Path, n: int):
    try:
        process_page(d, n)
    except Exception as e:  # keep going with other pages
        with lock:
            b = read_json(d / "book.json", {})
            b.setdefault("errors", {})[str(n)] = f"{type(e).__name__}: {e}"
            write_json(d / "book.json", b)
    finally:
        with lock:
            b = read_json(d / "book.json", {})
            done = len(list((d / "ocr").glob("*.json"))) if (d / "ocr").exists() else 0
            b["done_pages"] = done
            if done + len(b.get("errors", {})) >= b.get("total_pages", 0):
                b["status"] = "done" if not b.get("errors") else "done_with_errors"
                b["finished"] = time.time()
            write_json(d / "book.json", b)


def start_book(d: Path, files: list[Path], dpi: int):
    try:
        total = render_inputs(d, files, dpi)
        update_book(d, total_pages=total, status="ocr" if total else "error",
                    error=None if total else "No pages found")
        for n in range(1, total + 1):
            pool.submit(_ocr_job, d, n)
    except Exception as e:
        update_book(d, status="error", error=str(e))


@app.on_event("startup")
def resume_unfinished():
    """Pick up books that were mid-OCR when the server stopped."""
    for d in BOOKS.iterdir():
        b = read_json(d / "book.json")
        if not b or b.get("status") != "ocr":
            continue
        for p in sorted((d / "pages").glob("*.png")):
            if not (d / "ocr" / f"{p.stem}.json").exists():
                pool.submit(_ocr_job, d, int(p.stem))


def _settings(langs: str, psm: int, preprocess: str, tables: bool, images: bool, rotate: bool) -> dict:
    lang_list = [l for l in langs.replace(",", "+").split("+") if l] or ["auto"]
    if "auto" in lang_list:
        lang_list = ["auto"]
    return {"langs": lang_list, "psm": psm, "preprocess": preprocess,
            "detect_tables": tables, "detect_images": images, "auto_rotate": rotate}


def _save_uploads(d: Path, files: list[UploadFile]) -> list[Path]:
    (d / "src").mkdir(parents=True, exist_ok=True)
    saved = []
    for i, f in enumerate(sorted(files, key=lambda f: f.filename or "")):
        ext = Path(f.filename or "x.png").suffix.lower() or ".png"
        if ext != ".pdf" and ext not in IMG_EXT:
            raise HTTPException(400, f"Unsupported file type: {f.filename}")
        p = d / "src" / f"{i:04d}{ext}"
        with p.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        saved.append(p)
    return saved


# ---------------------------------------------------------------------------
# API: info, symbols, rules
# ---------------------------------------------------------------------------
@app.get("/api/info")
def info():
    return {"tesseract": eng.tesseract_version(), "workers": WORKERS, "osd": eng.has_osd(),
            "languages": eng.available_languages(), "auth": bool(API_KEY),
            "formats": ["docx", "xlsx", "html", "epub", "pdf", "txt", "md", "json"]}


@app.get("/api/symbols")
def symbols():
    return tt.symbol_catalogue()


@app.get("/api/rules", dependencies=[Depends(require_key)])
def get_rules():
    return rules()


@app.put("/api/rules", dependencies=[Depends(require_key)])
def put_rules(body: list[dict]):
    write_json(RULES_FILE, body)
    return {"ok": True, "count": len(body)}


# ---------------------------------------------------------------------------
# API: books
# ---------------------------------------------------------------------------
@app.post("/api/books", dependencies=[Depends(require_key)])
async def create_book(
    files: list[UploadFile] = File(...), title: str = Form(""),
    langs: str = Form("auto"), psm: int = Form(3), preprocess: str = Form("auto"), dpi: int = Form(300),
    detect_tables: bool = Form(True), detect_images: bool = Form(True), auto_rotate: bool = Form(True),
):
    book_id = uuid.uuid4().hex[:12]
    d = BOOKS / book_id
    try:
        saved = _save_uploads(d, files)
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    b = {
        "id": book_id, "title": title or Path(files[0].filename or "Untitled").stem,
        "settings": _settings(langs, psm, preprocess, detect_tables, detect_images, auto_rotate),
        "dpi": max(150, min(dpi, 600)), "status": "rendering", "total_pages": 0, "done_pages": 0,
        "created": time.time(), "errors": {},
    }
    write_json(d / "book.json", b)
    threading.Thread(target=start_book, args=(d, saved, b["dpi"]), daemon=True).start()
    return b


@app.get("/api/books", dependencies=[Depends(require_key)])
def list_books():
    out = []
    for d in BOOKS.iterdir():
        b = read_json(d / "book.json")
        if not b:
            continue
        recs = [read_json(p, {}) for p in (d / "ocr").glob("*.json")] if (d / "ocr").exists() else []
        confs = [r.get("mean_conf", 0) for r in recs if r]
        b["reviewed_pages"] = sum(1 for r in recs if r.get("reviewed"))
        b["mean_conf"] = round(sum(confs) / len(confs), 1) if confs else None
        b["words"] = sum(len(page_text(r).split()) for r in recs)
        b["tables"] = sum(1 for r in recs for bl in r.get("blocks", []) if bl["type"] == "table")
        b["images"] = sum(1 for r in recs for bl in r.get("blocks", []) if bl["type"] == "image")
        out.append(b)
    return sorted(out, key=lambda b: -b.get("created", 0))


@app.get("/api/books/{book_id}", dependencies=[Depends(require_key)])
def book_detail(book_id: str):
    d = book_dir(book_id)
    b = get_book(d)
    pages = []
    for n in range(1, b.get("total_pages", 0) + 1):
        r = page_rec(d, n)
        kinds = [bl["type"] for bl in r["blocks"]] if r else []
        pages.append({
            "page": n,
            "status": "done" if r else ("error" if str(n) in b.get("errors", {}) else "pending"),
            "mean_conf": r and r["mean_conf"], "reviewed": bool(r and r.get("reviewed")),
            "edited": bool(r and any(bl.get("edited") for bl in r["blocks"])),
            "tables": kinds.count("table"), "images": kinds.count("image"),
            "langs": r and r["langs"], "rotate": r and r.get("rotate"),
        })
    b["pages"] = pages
    return b


@app.patch("/api/books/{book_id}", dependencies=[Depends(require_key)])
def patch_book(book_id: str, body: dict):
    d = book_dir(book_id)
    b = get_book(d)
    if "title" in body:
        b["title"] = str(body["title"])[:200]
    if "settings" in body:
        b["settings"].update({k: v for k, v in body["settings"].items() if k in b["settings"]})
        b.pop("auto_langs", None)
    return update_book(d, **b)


@app.delete("/api/books/{book_id}", dependencies=[Depends(require_key)])
def delete_book(book_id: str):
    shutil.rmtree(book_dir(book_id))
    return {"ok": True}


@app.get("/api/books/{book_id}/pages/{n}/image", dependencies=[Depends(require_key)])
def page_image(book_id: str, n: int, kind: str = "view"):
    d = book_dir(book_id)
    p = {"processed": d / "proc" / f"{pn(n)}.png", "original": d / "pages" / f"{pn(n)}.png"}.get(
        kind, d / "view" / f"{pn(n)}.jpg")
    if not p.exists():  # not processed yet -> show the raw render
        p = d / "pages" / f"{pn(n)}.png"
    if not p.exists():
        raise HTTPException(404, "Image not ready")
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@app.get("/api/books/{book_id}/figures/{name}", dependencies=[Depends(require_key)])
def figure(book_id: str, name: str):
    p = book_dir(book_id) / "figs" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


@app.get("/api/books/{book_id}/pages/{n}", dependencies=[Depends(require_key)])
def page_detail(book_id: str, n: int):
    r = page_rec(book_dir(book_id), n)
    if not r:
        raise HTTPException(404, "Page not processed yet")
    r["plain_text"] = page_text(r)
    return r


@app.put("/api/books/{book_id}/pages/{n}", dependencies=[Depends(require_key)])
def save_page(book_id: str, n: int, body: dict):
    """Save edited blocks (text, table cells, type, order, deletions) and/or the reviewed flag."""
    d = book_dir(book_id)
    p = d / "ocr" / f"{pn(n)}.json"
    with lock:
        r = read_json(p)
        if not r:
            raise HTTPException(404, "Page not processed yet")
        if "blocks" in body:
            old = {b["id"]: b for b in r["blocks"]}
            new = []
            for b in body["blocks"]:
                o = old.get(b.get("id"))
                if not o:
                    continue
                o = dict(o)
                if b.get("type") in BLOCK_TYPES:
                    o["type"] = b["type"]
                if "text" in b and o["type"] not in ("table", "image"):
                    o["edited"] = o.get("edited") or b["text"] != o.get("text")
                    o["text"] = b["text"]
                if "rows" in b and o["type"] == "table":
                    o["edited"] = o.get("edited") or b["rows"] != o.get("rows")
                    o["rows"] = b["rows"]
                if isinstance(b.get("style"), dict):
                    o.setdefault("style", {}).update(b["style"])
                new.append(o)
            for gone in set(old) - {b["id"] for b in new}:
                if old[gone].get("image"):
                    (d / "figs" / old[gone]["image"]).unlink(missing_ok=True)
            r["blocks"] = new
        if "reviewed" in body:
            r["reviewed"] = bool(body["reviewed"])
        r["updated"] = time.time()
        write_json(p, r)
    r["plain_text"] = page_text(r)
    return r


@app.post("/api/books/{book_id}/pages/{n}/reocr", dependencies=[Depends(require_key)])
def reocr_page(book_id: str, n: int, body: dict | None = None):
    d = book_dir(book_id)
    body = body or {}
    ov = {k: body[k] for k in ("psm", "preprocess", "detect_tables", "detect_images", "auto_rotate") if k in body}
    if body.get("langs"):
        ov["langs"] = list(body["langs"])
        if ov["langs"] == ["auto"]:
            ov["redetect"] = True  # detect again for this page
    r = process_page(d, n, ov)
    r["plain_text"] = page_text(r)
    return r


@app.post("/api/books/{book_id}/pages/{n}/region", dependencies=[Depends(require_key)])
def read_region(book_id: str, n: int, body: dict):
    """Draw an area on the page and read it as text / heading / table / image (FineReader-style).
    Blocks mostly covered by the new area are replaced. Pass replace=<block id> to re-read one block."""
    d = book_dir(book_id)
    r = page_rec(d, n)
    if not r:
        raise HTTPException(404, "Page not processed yet")
    typ = body.get("type", "paragraph")
    if typ not in BLOCK_TYPES - {"ignore"}:
        raise HTTPException(400, "bad type")
    W, H = r["size"]
    x, y, w, h = [int(v) for v in body["bbox"]]
    x, y = max(0, x), max(0, y)
    w, h = min(w, W - x), min(h, H - y)
    if w < 10 or h < 10:
        raise HTTPException(400, "Area too small")
    bbox = [x, y, w, h]
    langs = body.get("langs") or r["langs"]
    gray = np.array(Image.open(d / "proc" / f"{pn(n)}.png").convert("L"))
    view = Image.open(d / "view" / f"{pn(n)}.jpg")
    ocr_fn = _ocr_fn(langs)

    if typ == "image":
        blk = {"type": "image", "bbox": bbox, "conf": None}
    elif typ == "table":
        sub = gray[y:y + h, x:x + w]
        found = [t for t in layout.detect_ruled_tables(sub) if t["vs"]]
        hs = vs = None
        if found:
            t = max(found, key=lambda t: t["bbox"][2] * t["bbox"][3])
            hs, vs = [y + v for v in t["hs"]], [x + v for v in t["vs"]]
        tab, _ = layout.read_table(gray, bbox, ocr_fn, hs, vs)
        if not tab:
            raise HTTPException(422, "No table structure found in that area - try drawing it as text")
        blk = {"type": "table", "bbox": bbox, **tab}
        blk["lang"] = layout.detect_lang(" ".join(c for row in tab["rows"] for c in row))
    else:
        pad = 12  # a little margin so glyphs touching a hand-drawn edge aren't clipped
        x0, y0 = max(0, x - pad), max(0, y - pad)
        words = ocr_fn(gray[y0:y + h + pad, x0:x + w + pad], (x0, y0))
        if not words:
            raise HTTPException(422, "No text found in that area")
        parts = layout.build_text_blocks(words, gray, r.get("dpi", 300), r.get("scale", 1.0)) or []
        text = "\n".join(p["text"] for p in parts)
        style = parts[0]["style"] if parts else {"size": 11, "bold": False, "align": "left"}
        confs = [wd["conf"] for wd in words if wd["conf"] >= 0]
        blk = {"type": typ, "bbox": bbox, "text": text, "style": style,
               "lines": [l for p in parts for l in p["lines"]],
               "conf": round(sum(confs) / len(confs), 1) if confs else 0, "lang": layout.detect_lang(text)}
        # refresh word confidences inside the area
        r["words"] = [wd for wd in r["words"] if not layout._inside(layout._center(wd["box"]), bbox)] + \
                     [{"text": wd["text"], "conf": wd["conf"], "box": wd["box"]} for wd in words]

    blk = _finish_block(blk, r.get("next_id", len(r["blocks"]) + 1), n, view, d)
    r["next_id"] = r.get("next_id", len(r["blocks"]) + 1) + 1
    blocks = r["blocks"]
    rep = body.get("replace")
    if rep and any(b["id"] == rep for b in blocks):
        i = next(i for i, b in enumerate(blocks) if b["id"] == rep)
        removed = [blocks[i]]
        blocks[i] = blk
    else:
        area = w * h
        removed = [b for b in blocks if layout._overlap(b["bbox"], bbox) > 0.6 * b["bbox"][2] * b["bbox"][3]
                   or layout._overlap(b["bbox"], bbox) > 0.8 * area]
        keep = [b for b in blocks if b not in removed]
        pos = len(keep)
        for i, b in enumerate(keep):
            bb = b["bbox"]
            horiz = min(bb[0] + bb[2], x + w) - max(bb[0], x) > 0
            if b["type"] != "header" and horiz and bb[1] >= y:
                pos = i; break
        keep.insert(pos, blk)
        blocks = keep
    for b in removed:
        if b.get("image"):
            (d / "figs" / b["image"]).unlink(missing_ok=True)
    r["blocks"] = blocks
    r["updated"] = time.time()
    write_json(d / "ocr" / f"{pn(n)}.json", r)
    r["plain_text"] = page_text(r)
    r["new_block"] = blk["id"]
    return r


@app.post("/api/books/{book_id}/reapply-rules", dependencies=[Depends(require_key)])
def reapply_rules(book_id: str):
    """Re-run clean-up + replacement rules on blocks you haven't edited (no re-OCR needed)."""
    d = book_dir(book_id)
    count = 0
    for p in (d / "ocr").glob("*.json"):
        r = read_json(p)
        if not r:
            continue
        for b in r["blocks"]:
            if b.get("edited"):
                continue
            if b["type"] == "table" and b.get("raw_rows"):
                b["rows"] = [[clean(c) for c in row] for row in b["raw_rows"]]
            elif "raw" in b:
                b["text"] = clean(b["raw"])
            count += 1
        write_json(p, r)
    return {"updated_blocks": count}


# ---------------------------------------------------------------------------
# API: export / convert
# ---------------------------------------------------------------------------
def _export(d: Path, title: str, page_nums: list[int], fmt: str, o: dict, langs_default) -> tuple[bytes, str, str]:
    recs = [r for r in (page_rec(d, n) for n in page_nums) if r]
    if not recs:
        raise HTTPException(409, "No OCR'd pages in that range yet")
    fig = lambda p, b: (d / "figs" / b["image"]).read_bytes()
    if fmt == "json":
        slim = [{k: v for k, v in r.items() if k != "words"} for r in recs]
        return json.dumps({"title": title, "pages": slim}, ensure_ascii=False).encode(), "application/json", "json"
    if fmt == "pdf":  # searchable PDF: cleaned page image + invisible OCR text layer
        out = fitz.open()
        for r in recs:
            img = Image.open(d / "view" / f"{pn(r['page'])}.jpg")
            with fitz.open("pdf", eng.searchable_pdf_page(img, r.get("langs") or langs_default, r.get("psm", 3))) as pg:
                out.insert_pdf(pg)
        return out.tobytes(garbage=3, deflate=True), "application/pdf", "pdf"
    if fmt not in ex.FORMATS:
        raise HTTPException(400, f"format must be one of: {', '.join(['json', 'pdf', *ex.FORMATS])}")
    fn, mime, ext = ex.FORMATS[fmt]
    return fn(title, recs, fig, o), mime, ext


def _disp(title: str, ext: str) -> dict:
    from urllib.parse import quote
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip() or "book"
    return {"Content-Disposition": f"attachment; filename=\"book.{ext}\"; filename*=UTF-8''{quote(safe)}.{ext}"}


@app.get("/api/books/{book_id}/export", dependencies=[Depends(require_key)])
def export(book_id: str, format: str = "docx", pages: str = "", images: bool = True, headers: bool = False,
           line_breaks: bool = False, page_breaks: bool = True):
    """format: docx | xlsx | html | epub | pdf (searchable) | txt | md (zip) | json.
    pages: e.g. "1-5,8" (default: all)."""
    d = book_dir(book_id)
    b = get_book(d)
    o = ex.opts(images=images, headers=headers, line_breaks=line_breaks, page_breaks=page_breaks)
    data, mime, ext = _export(d, b["title"], parse_range(pages, b["total_pages"]), format, o,
                              b.get("auto_langs") or ["tam", "eng"])
    return Response(data, media_type=mime, headers=_disp(b["title"], ext))


@app.post("/api/convert", dependencies=[Depends(require_key)])
def convert(
    file: UploadFile = File(...), format: str = Form("docx"), langs: str = Form("auto"),
    psm: int = Form(3), preprocess: str = Form("auto"), detect_tables: bool = Form(True),
    detect_images: bool = Form(True), auto_rotate: bool = Form(True), images: bool = Form(True),
    headers: bool = Form(False), line_breaks: bool = Form(False), page_breaks: bool = Form(True),
):
    """One call: scanned PDF/image in -> Word / Excel / HTML / EPUB / searchable PDF / text / JSON out."""
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        d = Path(tmp)
        saved = _save_uploads(d, [file])
        settings = _settings(langs, psm, preprocess, detect_tables, detect_images, auto_rotate)
        write_json(d / "book.json", {"settings": settings, "dpi": 300})
        total = render_inputs(d, saved, 300)
        if total > 300:
            raise HTTPException(413, "Over 300 pages - upload it as a book instead")
        for n in range(1, total + 1):
            process_page(d, n)
        title = Path(file.filename or "document").stem
        o = ex.opts(images=images, headers=headers, line_breaks=line_breaks, page_breaks=page_breaks)
        data, mime, ext = _export(d, title, list(range(1, total + 1)), format, o, ["tam", "eng"])
    return Response(data, media_type=mime, headers=_disp(title, ext))


@app.post("/api/ocr", dependencies=[Depends(require_key)])
def quick_ocr(file: UploadFile = File(...), langs: str = Form("auto"), psm: int = Form(3),
              preprocess: str = Form("auto"), layout_blocks: bool = Form(True), words: bool = Form(False)):
    """Image/PDF -> JSON: plain text per page, plus typed layout blocks and (optionally) word boxes."""
    with tempfile.TemporaryDirectory(dir=DATA) as tmp:
        d = Path(tmp)
        saved = _save_uploads(d, [file])
        write_json(d / "book.json", {"settings": _settings(langs, psm, preprocess, True, True, True), "dpi": 300})
        total = render_inputs(d, saved, 300)
        pages = []
        for n in range(1, total + 1):
            r = process_page(d, n)
            item = {"page": n, "text": page_text(r), "langs": r["langs"], "mean_conf": r["mean_conf"],
                    "rotate": r["rotate"]}
            if layout_blocks:
                item["blocks"] = [{k: v for k, v in b.items() if k not in ("raw", "raw_rows", "lines", "image")}
                                  for b in r["blocks"]]
            if words:
                item["words"] = r["words"]
            pages.append(item)
    return {"pages": pages, "text": "\n\n".join(p["text"] for p in pages)}


app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="ui")
