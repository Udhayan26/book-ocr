#!/usr/bin/env bash
# Linux / macOS launcher.
#   Ubuntu/Debian: sudo apt install tesseract-ocr python3-venv
#   macOS:         brew install tesseract
set -e
cd "$(dirname "$0")"
TD_SYS=$(dirname "$(find /usr/share/tesseract-ocr /opt/homebrew/share/tessdata /usr/local/share/tessdata -name osd.traineddata 2>/dev/null | head -1)")
export TESSDATA_PREFIX="${TESSDATA_PREFIX:-$TD_SYS}"
export OCR_WORKERS="${OCR_WORKERS:-2}"

[ -d .venv ] || { python3 -m venv .venv; .venv/bin/pip install -r backend/requirements.txt; }
if [ ! -f "$TESSDATA_PREFIX/tam.traineddata" ]; then
  echo "Downloading Tamil + English models into $TESSDATA_PREFIX (may ask for sudo)"
  sudo .venv/bin/python download_models.py "$TESSDATA_PREFIX" tam eng
fi
cd backend
exec ../.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
