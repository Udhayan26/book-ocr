"""Page layout analysis — the FineReader-style part.

Given the OCR'd words of a page plus the page image, split it into typed blocks:
heading / paragraph / caption / header / footer / table / image, with reading order,
alignment, approximate font size, bold, and per-block language.
Pure OpenCV + NumPy, no extra models.
"""
from __future__ import annotations

import re
import statistics as st

import cv2
import numpy as np

# Unicode ranges per script -> language label used in exports (BCP-47-ish)
SCRIPTS = [
    ("ta", 0x0B80, 0x0BFF), ("ta", 0x11FC0, 0x11FFF), ("hi", 0x0900, 0x097F), ("bn", 0x0980, 0x09FF),
    ("pa", 0x0A00, 0x0A7F), ("gu", 0x0A80, 0x0AFF), ("or", 0x0B00, 0x0B7F), ("te", 0x0C00, 0x0C7F),
    ("kn", 0x0C80, 0x0CFF), ("ml", 0x0D00, 0x0D7F), ("si", 0x0D80, 0x0DFF), ("ar", 0x0600, 0x06FF),
]
LANG_SCRIPT = {"tam": "ta", "hin": "hi", "mar": "hi", "san": "hi", "nep": "hi", "ben": "bn", "asm": "bn",
               "pan": "pa", "guj": "gu", "ori": "or", "tel": "te", "kan": "kn", "mal": "ml", "sin": "si",
               "ara": "ar", "urd": "ar", "fas": "ar"}
_JUNK = re.compile(r"^[\|\[\]_—–\-=~:;.,'`\"!]+$")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def char_script(c: str) -> str | None:
    o = ord(c)
    for code, a, b in SCRIPTS:
        if a <= o <= b:
            return code
    if c.isascii() and c.isalpha():
        return "en"
    return None


def detect_lang(text: str) -> str:
    counts: dict[str, int] = {}
    for c in text:
        s = char_script(c)
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return ""
    total = sum(counts.values())
    main = [k for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v / total >= 0.2]
    return "+".join(main[:2])


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def _center(b):
    return b[0] + b[2] / 2, b[1] + b[3] / 2


def _inside(pt, b, pad=0):
    return b[0] - pad <= pt[0] <= b[0] + b[2] + pad and b[1] - pad <= pt[1] <= b[1] + b[3] + pad


def _union(boxes):
    x0 = min(b[0] for b in boxes); y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes); y1 = max(b[1] + b[3] for b in boxes)
    return [int(x0), int(y0), int(x1 - x0), int(y1 - y0)]


def _overlap(a, b):
    x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    return x * y


def _positions(profile: np.ndarray, frac: float, length: int, merge: int = 10) -> list[int]:
    """Indices where a projection profile is 'a line', merged into line centres."""
    idx = np.where(profile > frac * length * 255)[0]
    out, run = [], []
    for i in idx:
        if run and i - run[-1] > merge:
            out.append(int(np.mean(run))); run = []
        run.append(i)
    if run:
        out.append(int(np.mean(run)))
    return out


def _dedupe(vals, tol):
    vals = sorted(vals)
    out = []
    for v in vals:
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


# ---------------------------------------------------------------------------
# tables
# ---------------------------------------------------------------------------
def line_masks(gray: np.ndarray):
    h, w = gray.shape
    inv = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY_INV, 15, 10)
    hor = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(25, w // 35), 1)))
    ver = cv2.morphologyEx(inv, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(20, h // 70))))
    return hor, ver


def without_lines(gray: np.ndarray, hor=None, ver=None) -> np.ndarray:
    """Erase ruling lines so Tesseract reads the cell text instead of treating it as graphics."""
    if hor is None:
        hor, ver = line_masks(gray)
    lines = cv2.dilate(cv2.add(hor, ver), np.ones((3, 3), np.uint8), iterations=1)
    out = gray.copy()
    out[lines > 0] = 255
    return out


def detect_ruled_tables(gray: np.ndarray, masks=None) -> list[dict]:
    """Find tables drawn with lines. Returns bbox + row/column line positions."""
    h, w = gray.shape
    hor, ver = masks or line_masks(gray)
    grid = cv2.dilate(cv2.add(hor, ver), np.ones((5, 5), np.uint8), iterations=2)
    cnts, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw < w * 0.2 or bh < h * 0.025:
            continue
        hs = _positions(hor[y:y + bh, x:x + bw].sum(axis=1), 0.35, bw)
        vs = _positions(ver[y:y + bh, x:x + bw].sum(axis=0), 0.25, bh)
        hs = _dedupe([0] + hs + [bh], max(8, h // 200))
        vs = _dedupe([0] + vs + [bw], max(8, w // 200))
        inner_v = len(vs) - 2
        if len(hs) < 3:
            continue
        tables.append({
            "bbox": [x, y, bw, bh],
            "hs": [y + v for v in hs] if inner_v >= 1 else None,
            "vs": [x + v for v in vs] if inner_v >= 1 else None,  # None -> infer rows/columns from text
        })
    # "booktabs" tables: only horizontal rules (top, under header, bottom), no vertical lines
    segs = []
    for c in cv2.findContours(hor, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw > w * 0.3 and bh < 15 and not any(_inside((x + bw / 2, y), t["bbox"], 5) for t in tables):
            segs.append([x, y, bw, bh])
    segs.sort(key=lambda b: b[1])
    group = []
    def flush():
        if len(group) >= 2:
            x0 = min(g[0] for g in group); x1 = max(g[0] + g[2] for g in group)
            y0 = group[0][1]; y1 = group[-1][1] + group[-1][3]
            if y1 - y0 > h * 0.04:
                tables.append({"bbox": [x0, y0, x1 - x0, y1 - y0], "hs": None, "vs": None, "rules": True})
    for sg in segs:
        if group:
            g = group[-1]
            same_x = abs(sg[0] - g[0]) < w * 0.05 and abs(sg[2] - g[2]) < w * 0.08
            if not (same_x and sg[1] - g[1] < h * 0.3):
                flush(); group = []
        group.append(sg)
    flush()
    return tables


def _rows_from_words(words, hs=None):
    """Group words into rows (by line positions if given, else by vertical clustering)."""
    if hs:
        rows = [[] for _ in range(len(hs) - 1)]
        for w in words:
            cy = _center(w["box"])[1]
            for i in range(len(hs) - 1):
                if hs[i] <= cy < hs[i + 1]:
                    rows[i].append(w); break
        return [r for r in rows if r] or [], [(hs[i], hs[i + 1]) for i in range(len(hs) - 1)]
    ws = sorted(words, key=lambda w: _center(w["box"])[1])
    rows, cur, bottom = [], [], None
    for w in ws:
        top, cy = w["box"][1], _center(w["box"])[1]
        if cur and cy > bottom:
            rows.append(cur); cur = []
        bottom = top + w["box"][3] if not cur else max(bottom, top + w["box"][3])
        cur.append(w)
    if cur:
        rows.append(cur)
    bounds = [(min(x["box"][1] for x in r), max(x["box"][1] + x["box"][3] for x in r)) for r in rows]
    return rows, bounds


def _phrases(row, gap):
    row = sorted(row, key=lambda w: w["box"][0])
    out = []
    for w in row:
        if out and w["box"][0] - (out[-1]["box"][0] + out[-1]["box"][2]) < gap:
            p = out[-1]
            p["words"].append(w)
            p["box"] = _union([p["box"], w["box"]])
        else:
            out.append({"words": [w], "box": list(w["box"])})
    return out


def table_from_words(words, bbox, hs=None, vs=None) -> dict | None:
    """Build a table (rows of cell strings) from words in a region.
    vs given -> ruled columns; otherwise columns come from vertical white gaps."""
    words = [w for w in words if not _JUNK.match(w["text"])]
    if not words:
        return None
    rows, bounds = _rows_from_words(words, hs)
    if not rows:
        return None
    med_h = st.median(w["box"][3] for w in words)
    if vs is None:
        occ = np.zeros(bbox[2] + 2, bool)
        for r in rows:
            for p in _phrases(r, med_h * 0.9):
                a = max(0, p["box"][0] - bbox[0]); b = min(bbox[2], p["box"][0] + p["box"][2] - bbox[0])
                occ[a:b] = True
        seps, i = [], 0
        while i < len(occ):
            if not occ[i]:
                j = i
                while j < len(occ) and not occ[j]:
                    j += 1
                if i > 0 and j < len(occ) and j - i >= med_h * 1.2:
                    seps.append(bbox[0] + (i + j) // 2)
                i = j
            else:
                i += 1
        vs = [bbox[0]] + seps + [bbox[0] + bbox[2]]
    ncol = len(vs) - 1
    if ncol < 2:
        return None
    grid = []
    for r in rows:
        cells = [[] for _ in range(ncol)]
        for w in sorted(r, key=lambda w: (w["box"][1] // max(1, med_h), w["box"][0])):
            cx = _center(w["box"])[0]
            for j in range(ncol):
                if vs[j] <= cx < vs[j + 1] or (j == ncol - 1 and cx >= vs[j]):
                    cells[j].append(w); break
        grid.append([_cell_text(c, med_h) for c in cells])
    grid = [r for r in grid if any(c.strip() for c in r)]
    if len(grid) < 2:
        return None
    hs_out = hs or [bounds[0][0]] + [int((bounds[i][1] + bounds[i + 1][0]) / 2) for i in range(len(bounds) - 1)] + [bounds[-1][1]]
    confs = [w["conf"] for w in words if w["conf"] >= 0]
    return {"rows": grid, "hs": hs_out, "vs": vs, "conf": round(sum(confs) / len(confs), 1) if confs else 0}


def _cell_text(ws, med_h):
    if not ws:
        return ""
    out, prev = [], None
    for w in ws:
        if prev is not None and w["box"][1] > prev["box"][1] + med_h * 0.7:
            out.append("\n")
        elif out:
            out.append(" ")
        out.append(w["text"]); prev = w
    return "".join(out).replace(" \n", "\n")


# ---------------------------------------------------------------------------
# images / figures
# ---------------------------------------------------------------------------
def detect_images(gray: np.ndarray, words, exclude) -> list[list[int]]:
    h, w = gray.shape
    inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    mask = inv.copy()
    for wd in words:
        if wd["conf"] >= 45 and _LETTER.search(wd["text"]):
            x, y, bw, bh = wd["box"]
            mask[max(0, y - 3):y + bh + 3, max(0, x - 3):x + bw + 3] = 0
    for b in exclude:
        mask[b[1]:b[1] + b[3], b[0]:b[0] + b[2]] = 0
    k = max(15, w // 80)
    closed = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
    cnts, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in cnts:
        x, y, bw, bh = cv2.boundingRect(c)
        if bw * bh < 0.01 * w * h or bw < 0.07 * w or bh < 0.04 * h:
            continue
        roi = gray[y:y + bh, x:x + bw]
        ink = mask[y:y + bh, x:x + bw].mean() / 255
        midtone = ((roi > 50) & (roi < 205)).mean()
        inside = [wd for wd in words if _inside(_center(wd["box"]), [x, y, bw, bh])]
        good = [wd for wd in inside if wd["conf"] >= 60 and _LETTER.search(wd["text"])]
        if ink < 0.03 and midtone < 0.08:
            continue
        if len(good) > 8 and len(good) > 0.5 * len(inside):  # it is really text
            continue
        boxes.append([x, y, bw, bh])
    # merge overlapping
    merged = []
    for b in sorted(boxes, key=lambda b: -b[2] * b[3]):
        for m in merged:
            if _overlap(m, b) > 0.3 * b[2] * b[3]:
                m[:] = _union([m, b]); break
        else:
            merged.append(list(b))
    return merged


# ---------------------------------------------------------------------------
# text blocks
# ---------------------------------------------------------------------------
def _ink(inv, box):
    x, y, bw, bh = box
    roi = inv[y:y + bh, x:x + bw]
    return float(roi.mean()) / 255 if roi.size else 0.0


def _main_script(text):
    lang = detect_lang(text)
    return lang.split("+")[0] if lang else ""


def build_text_blocks(words, gray, page_dpi, scale):
    """Group Tesseract words (block/par/line ids) into styled paragraphs."""
    h, w = gray.shape
    inv = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    raw: dict[tuple, dict] = {}
    for wd in words:
        key = tuple(int(v) for v in wd["line"].split("-"))
        raw.setdefault(key[:2], {}).setdefault(key[2], []).append(wd)
        wd["ink"] = _ink(inv, wd["box"])
        wd["script"] = _main_script(wd["text"])
    if not raw:
        return []

    def mkline(ws):
        ws = sorted(ws, key=lambda x: x["box"][0])
        text = " ".join(x["text"] for x in ws)
        return {"words": ws, "box": _union([x["box"] for x in ws]), "h": st.median(x["box"][3] for x in ws),
                "text": text, "script": _main_script(text)}

    pars = [{"key": k, "L": [mkline(raw[k][ln]) for ln in sorted(raw[k])]} for k in sorted(raw)]

    # 1) widely-justified lines that Tesseract cut into separate one-line paragraphs -> rejoin
    for p in list(pars):
        if len(p["L"]) != 1 or p not in pars:
            continue
        lb = p["L"][0]["box"]
        for q in pars:
            if q is p:
                continue
            for i, ql in enumerate(q["L"]):
                qb = ql["box"]
                v = min(lb[1] + lb[3], qb[1] + qb[3]) - max(lb[1], qb[1])
                gap = max(lb[0] - (qb[0] + qb[2]), qb[0] - (lb[0] + lb[2]))
                if v > 0.5 * min(lb[3], qb[3]) and gap < w * 0.25:
                    q["L"][i] = mkline(ql["words"] + p["L"][0]["words"])
                    pars.remove(p); break
            if p not in pars:
                break

    all_lines = [l for p in pars for l in p["L"]]
    # body line height per script (Latin letters are shorter than Tamil at the same point size)
    body = {}
    for scr in {l["script"] for l in all_lines}:
        hs_ = [l["h"] for l in all_lines if l["script"] == scr and len(l["words"]) >= 3]
        if hs_:
            body[scr] = st.median(hs_)
    glob_h = st.median([l["h"] for l in all_lines])
    dom = max(body, key=lambda k: sum(1 for l in all_lines if l["script"] == k)) if body else ""
    eff_dpi = page_dpi * scale
    body_pt = round(min(16, max(8, body.get(dom, glob_h) / eff_dpi * 72 / 1.12)) * 2) / 2
    ink_by = {}
    for scr in body:
        v = [x["ink"] for x in words if x["script"] == scr and len(x["text"]) > 2]
        ink_by[scr] = st.median(v) if v else None

    def ratio_of(lines):
        # per word, against the body height of that word's own script (mixed Tamil/English lines)
        r = [x["box"][3] / body[x["script"]] for l in lines for x in l["words"] if x["script"] in body]
        return st.median(r) if r else st.median(l["h"] / glob_h for l in lines)

    # Tesseract sometimes emits a lower piece of a column before the piece above it -> fix local inversions
    def _top(p): return min(l["box"][1] for l in p["L"])
    def _hspan(p): b = _union([l["box"] for l in p["L"]]); return b[0], b[0] + b[2]
    changed = True
    while changed:
        changed = False
        for i in range(len(pars) - 1):
            a, b = pars[i], pars[i + 1]
            (a0, a1), (b0, b1) = _hspan(a), _hspan(b)
            ov = min(a1, b1) - max(a0, b0)
            if ov > 0.5 * min(a1 - a0, b1 - b0) and _top(b) < _top(a) - 5:
                pars[i], pars[i + 1] = b, a; changed = True

    # 2) a paragraph Tesseract split mid-way: previous ends with a full-width line, next starts right below
    merged = []
    for p in pars:
        if merged:
            a = merged[-1]
            al, bl = a["L"][-1], p["L"][0]
            abox = _union([l["box"] for l in a["L"]])
            gap = bl["box"][1] - (al["box"][1] + al["box"][3])
            full = (al["box"][0] + al["box"][2]) >= abox[0] + abox[2] - w * 0.04 and len(a["L"]) >= 1 \
                and al["box"][2] > w * 0.45
            if (full and -5 < gap < 1.25 * al["h"] and abs(bl["box"][0] - abox[0]) < w * 0.05
                    and abs(ratio_of(a["L"]) - ratio_of(p["L"])) < 0.2):
                a["L"] += p["L"]; continue
        merged.append(p)

    lefts = [l["box"][0] for l in all_lines]; rights = [l["box"][0] + l["box"][2] for l in all_lines]
    area_l, area_r = np.percentile(lefts, 5), np.percentile(rights, 95)
    area_c = (area_l + area_r) / 2

    blocks = []
    for p in merged:
        L = p["L"]
        allw = [x for l in L for x in l["words"]]
        box = _union([l["box"] for l in L])
        ratio = ratio_of(L)
        text = "\n".join(l["text"] for l in L)
        n_words = len(allw)
        bw_ = [x for x in allw if len(x["text"]) > 2 and ink_by.get(x["script"])]
        bold = len(bw_) >= 2 and st.median(x["ink"] / ink_by[x["script"]] for x in bw_) > 1.3
        confs = [x["conf"] for x in allw if x["conf"] >= 0]

        tol = w * 0.015
        if len(L) >= 2:
            body_lines = L[:-1] if len(L) > 2 else L
            ls = [l["box"][0] for l in body_lines]; rs = [l["box"][0] + l["box"][2] for l in body_lines]
            cs = [l["box"][0] + l["box"][2] / 2 for l in L]
            l_ok, r_ok = np.std(ls) < tol, np.std(rs) < tol
            align = ("justify" if l_ok and r_ok and len(L) > 2 else "left" if l_ok
                     else "right" if r_ok else "center" if np.std(cs) < tol else "left")
        else:
            cx = box[0] + box[2] / 2
            if abs(cx - area_c) < w * 0.03 and box[0] - area_l > w * 0.08:
                align = "center"
            elif abs(box[0] + box[2] - area_r) < tol and box[0] - area_l > w * 0.25:
                align = "right"
            else:
                align = "left"

        top, bottom = box[1], box[1] + box[3]
        short = not text.rstrip().endswith((".", "।", ";", ","))
        if (bottom < h * 0.075 or top > h * 0.925) and len(L) <= 2 and n_words <= 12:
            typ = "header" if bottom < h * 0.075 else "footer"
        elif ratio >= 1.6 and len(L) <= 3:
            typ = "heading1"
        elif ratio >= 1.2 and len(L) <= 3 and n_words <= 15 and short:
            typ = "heading2"
        elif bold and len(L) <= 2 and n_words <= 14 and short:
            typ = "heading3"
        else:
            typ = "paragraph"

        size = body_pt if 0.88 <= ratio <= 1.12 else round(min(40, max(7, body_pt * ratio)) * 2) / 2
        blocks.append({
            "type": typ, "bbox": box, "text": text, "raw": text,
            "lines": [l["box"] for l in L],
            "conf": round(sum(confs) / len(confs), 1) if confs else 0,
            "style": {"size": size, "bold": bool(bold or typ.startswith("heading")), "align": align},
            "order_key": p["key"],
        })
    return blocks


def mark_captions(blocks, page_h):
    """The text block hugging an image (just below, else just above) becomes its caption."""
    for im in [b for b in blocks if b["type"] == "image"]:
        ib = im["bbox"]
        best, best_gap = None, page_h * 0.06
        for b in blocks:
            if b["type"] not in ("paragraph", "heading3") or len(b.get("lines", [])) > 2:
                continue
            bb = b["bbox"]
            if min(ib[0] + ib[2], bb[0] + bb[2]) - max(ib[0], bb[0]) <= 0:
                continue
            below = bb[1] - (ib[1] + ib[3]); above = ib[1] - (bb[1] + bb[3])
            gap = below if below >= -5 else (above * 1.5 if above >= -5 else None)
            if gap is not None and gap < best_gap:
                best, best_gap = b, gap
        if best:
            best["type"] = "caption"


def reading_order(text_blocks, other_blocks):
    """Keep Tesseract's column-aware order for text; slot tables/images in by position."""
    order = list(text_blocks)
    for ob in sorted(other_blocks, key=lambda b: b["bbox"][1]):
        oy = ob["bbox"][1]
        pos = len(order)
        for i, tb in enumerate(order):
            tbb = tb["bbox"]
            horiz = min(tbb[0] + tbb[2], ob["bbox"][0] + ob["bbox"][2]) - max(tbb[0], ob["bbox"][0]) > 0
            if tbb[1] >= oy and horiz and tb["type"] not in ("header",):
                pos = i; break
        order.insert(pos, ob)
    heads = [b for b in order if b["type"] == "header"]
    foots = [b for b in order if b["type"] == "footer"]
    rest = [b for b in order if b["type"] not in ("header", "footer")]
    return heads + rest + foots


def read_table(gray, bbox, ocr_fn, hs=None, vs=None, masks=None):
    """OCR a table region on its own (lines erased) and build the cell grid."""
    x, y, bw, bh = bbox
    clean = without_lines(gray, *(masks or line_masks(gray)))
    pad = 4
    crop = clean[max(0, y - pad):y + bh + pad, max(0, x - pad):x + bw + pad]
    words = ocr_fn(crop, (max(0, x - pad), max(0, y - pad)))
    return table_from_words(words, bbox, hs, vs), words


def analyze(words, gray, page_dpi, scale, ocr_fn=None, detect_tables=True, detect_figs=True):
    """Full page analysis -> ordered blocks (without ids / figure files).
    ocr_fn(gray_crop_array, offset) -> words; used to re-read table regions."""
    words = [dict(w) for w in words]
    others, used = [], set()

    if detect_tables:
        masks = line_masks(gray)
        for t in detect_ruled_tables(gray, masks):
            inside = [i for i, w in enumerate(words) if _inside(_center(w["box"]), t["bbox"])]
            if ocr_fn:
                tab, _ = read_table(gray, t["bbox"], ocr_fn, t["hs"], t["vs"], masks)
            else:
                tab = table_from_words([words[i] for i in inside], t["bbox"], t["hs"], t["vs"])
            if tab and t["vs"] is None and (len(tab["rows"]) < 3 or len(tab["rows"][0]) > 8):
                tab = None  # rules around ordinary text, not a table
            if tab:
                others.append({"type": "table", "bbox": t["bbox"], **tab})
                used.update(inside)

    if detect_figs:
        for b in detect_images(gray, [w for i, w in enumerate(words) if i not in used], [o["bbox"] for o in others]):
            inside = [i for i, w in enumerate(words) if _inside(_center(w["box"]), b)]
            used.update(inside)
            others.append({"type": "image", "bbox": b, "conf": None})

    text_words = [w for i, w in enumerate(words) if i not in used and w["text"].strip()]
    tblocks = build_text_blocks(text_words, gray, page_dpi, scale)
    blocks = reading_order(tblocks, others)
    mark_captions(blocks, gray.shape[0])
    for b in blocks:
        b.pop("order_key", None)
        if b["type"] == "table":
            b["lang"] = detect_lang(" ".join(c for r in b["rows"] for c in r))
        elif b["type"] != "image":
            b["lang"] = detect_lang(b["text"])
    return blocks
