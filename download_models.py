"""Download Tesseract 'best' (most accurate) language models.

Usage:
    python download_models.py <tessdata-folder> [lang ...]
    python download_models.py "C:\\Program Files\\Tesseract-OCR\\tessdata" tam eng
Defaults to: tam eng
"""
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main/"

dest = Path(sys.argv[1] if len(sys.argv) > 1 else "tessdata")
langs = sys.argv[2:] or ["tam", "eng"]
dest.mkdir(parents=True, exist_ok=True)
for lang in langs:
    out = dest / f"{lang}.traineddata"
    url = BASE + f"{lang}.traineddata"
    print(f"Downloading {lang} ...", end=" ", flush=True)
    urllib.request.urlretrieve(url, out)
    print(f"{out.stat().st_size / 1e6:.1f} MB -> {out}")
print("Done. Restart the server to see the new languages.")
