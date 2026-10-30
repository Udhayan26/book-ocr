"""OCR engine: page normalisation (rotate, deskew, clean), language auto-detect, Tesseract.

Open source, runs locally, no limits.
"""
from __future__ import annotations

import os

import cv2
import numpy as np
import pytesseract
from PIL import Image

import layout

TESSDATA = os.environ.get("TESSDATA_PREFIX")  # folder that holds *.traineddata
if os.environ.get("TESSERACT_CMD"):  # e.g. C:\Program Files\Tesseract-OCR\tesseract.exe
    pytesseract.pytesseract.tesseract_cmd = os.environ["TESSERACT_CMD"]

LANG_NAMES = {
    "tam": "Tamil", "eng": "English", "hin": "Hindi", "mal": "Malayalam", "tel": "Telugu",
    "kan": "Kannada", "san": "Sanskrit", "ben": "Bengali", "guj": "Gujarati", "pan": "Punjabi",
    "ori": "Odia", "mar": "Marathi", "urd": "Urdu", "ara": "Arabic", "fra": "French",
    "deu": "German", "spa": "Spanish", "sin": "Sinhala", "nep": "Nepali", "asm": "Assamese",
}


def _cfg_base() -> str:
    return f'--tessdata-dir "{TESSDATA}"' if TESSDATA else ""


def installed_languages() -> list[str]:
    try:
        return sorted(l for l in pytesseract.get_languages(config=_cfg_base()) if l != "osd")
    except Exception:
        return []


def available_languages() -> list[dict]:
    return [{"code": l, "name": LANG_NAMES.get(l, l)} for l in installed_languages()]


def has_osd() -> bool:
    try:
        return "osd" in pytesseract.get_languages(config=_cfg_base())
    except Exception:
        return False


def tesseract_version() -> str:
    try:
        return str(pytesseract.get_tesseract_version())
    except Exception:
        return "not found"


# ---------------------------------------------------------------------------
# Page normalisation — every output image shares one coordinate system
# ---------------------------------------------------------------------------
def detect_rotation(img: Image.Image) -> int:
    """Degrees the page must be turned (clockwise) to be upright; 0 if unsure."""
    if not has_osd():
        return 0
    small = img.convert("L")
    if small.width > 1800:
        small = small.resize((1800, int(small.height * 1800 / small.width)))
    try:
        d = pytesseract.image_to_osd(small, config=f"{_cfg_base()} --psm 0",
                                     output_type=pytesseract.Output.DICT)
        return int(d["rotate"]) if d.get("orientation_conf", 0) >= 2.0 else 0
    except Exception:
        return 0


def _skew_angle(gray: np.ndarray) -> float:
    thr = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    coords = np.column_stack(np.where(thr > 0))
    if len(coords) < 500:
        return 0.0
    angle = cv2.minAreaRect(coords[:, ::-1].astype(np.float32))[-1]
    if angle > 45:
        angle -= 90
    if angle < -45:
        angle += 90
    return float(angle) if 0.3 <= abs(angle) <= 15 else 0.0


def normalize_page(img: Image.Image, mode: str = "auto", auto_rotate: bool = True):
    """Return (view RGB, proc image for OCR, gray array, meta). All share one geometry."""
    rgb = img.convert("RGB")
    rotate = detect_rotation(rgb) if auto_rotate else 0
    if rotate:
        rgb = rgb.rotate(-rotate, expand=True, fillcolor="white")
    arr = np.array(rgb)
    scale = 1.0
    if arr.shape[1] < 1600:  # small scans: Tamil glyphs need pixels
        scale = min(3.0, 2400 / arr.shape[1])
        arr = cv2.resize(arr, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
    deskew = 0.0
    if mode != "none":
        deskew = _skew_angle(gray)
        if deskew:
            h, w = gray.shape
            m = cv2.getRotationMatrix2D((w / 2, h / 2), deskew, 1.0)
            arr = cv2.warpAffine(arr, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=(255, 255, 255))
            gray = cv2.warpAffine(gray, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)
        gray = cv2.fastNlMeansDenoising(gray, h=10)
    proc = gray
    if mode == "binarize":
        proc = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15)
    meta = {"rotate": rotate, "deskew": round(deskew, 2), "scale": round(scale, 3)}
    return Image.fromarray(arr), Image.fromarray(proc), gray, meta


# ---------------------------------------------------------------------------
# Language auto-detection
# ---------------------------------------------------------------------------
def detect_languages(proc: Image.Image, candidates: list[str] | None = None) -> list[str]:
    """Probe each installed script model on a reduced page and keep the ones that read well.
    English is added when the page also has confident Latin words."""
    langs = candidates or installed_languages()
    if not langs:
        return ["eng"]
    small = proc
    if small.width > 1400:
        small = small.resize((1400, int(small.height * 1400 / small.width)))
    w, h = small.size
    small = small.crop((0, int(h * 0.06), w, int(h * 0.94)))  # skip running headers/footers

    def probe(lang):
        try:
            d = pytesseract.image_to_data(small, lang=lang, config=f"{_cfg_base()} --oem 1 --psm 3",
                                          output_type=pytesseract.Output.DICT)
        except Exception:
            return 0.0, 0
        score, n = 0.0, 0
        want = layout.LANG_SCRIPT.get(lang, "en")
        for t, c in zip(d["text"], d["conf"]):
            c = float(c)
            if c < 50 or not t.strip():
                continue
            scr = [s for s in (layout.char_script(ch) for ch in t) if s]
            if scr and scr.count(want) / len(scr) > 0.6:
                score += c * len(t); n += 1
        return score, n

    results = {l: probe(l) for l in langs if l in layout.LANG_SCRIPT}
    chosen = []
    if results:
        best = max(results, key=lambda l: results[l][0])
        if results[best][1] >= 3:
            chosen.append(best)
            for l, (s, n) in results.items():  # a second Indic script on the page (e.g. Tamil + Sanskrit)
                if l != best and n >= 8 and s > 0.35 * results[best][0] and \
                        layout.LANG_SCRIPT[l] != layout.LANG_SCRIPT[best]:
                    chosen.append(l)
    if "eng" in langs:
        s, n = probe("eng")
        if not chosen or n >= 3:
            chosen.append("eng")
    return chosen or langs[:1]


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------
def run_ocr(img: Image.Image, langs: list[str], psm: int = 3, offset=(0, 0)) -> dict:
    lang = "+".join(langs) or "eng"
    cfg = f"{_cfg_base()} --oem 1 --psm {psm} -c preserve_interword_spaces=1"
    data = pytesseract.image_to_data(img, lang=lang, config=cfg, output_type=pytesseract.Output.DICT)
    words = []
    for i, w in enumerate(data["text"]):
        if not w.strip():
            continue
        words.append({
            "text": w, "conf": round(float(data["conf"][i]), 1),
            "box": [data["left"][i] + offset[0], data["top"][i] + offset[1], data["width"][i], data["height"][i]],
            "line": f'{data["block_num"][i]}-{data["par_num"][i]}-{data["line_num"][i]}',
        })
    confs = [w["conf"] for w in words if w["conf"] >= 0]
    return {"words": words, "mean_conf": round(sum(confs) / len(confs), 1) if confs else 0.0}


def searchable_pdf_page(img: Image.Image, langs: list[str], psm: int = 3) -> bytes:
    cfg = f"{_cfg_base()} --oem 1 --psm {psm}"
    return pytesseract.image_to_pdf_or_hocr(img, lang="+".join(langs), config=cfg, extension="pdf")
